from __future__ import annotations

from octopus_sdk.registry.management import ManagementRequest, ManagementResult
from octopus_sdk.registry.models import AckResult, DeliveryPollResult, DeliveryRecord
from octopus_sdk.task_protocol import TaskTransitionRequest, apply_task_transition

from octopus_registry.store_base import (
    decode_json_field,
    delivery_kinds_for_registry_scope,
    registry_scope_for_agent_row,
    validated_ack_request,
    validated_management_request,
    validated_management_result,
)
from octopus_registry.store_dialect import StoreDialect
from octopus_registry.store_shared.common import record


def _in_placeholders(dialect: StoreDialect, *, start_index: int, count: int) -> str:
    return ",".join(dialect.placeholder(start_index + offset) for offset in range(count))


def poll(
    conn,
    *,
    dialect: StoreDialect,
    agent_row,
    cursor: int,
    limit: int,
    now: str,
    registry_epoch: str,
    task_snapshot_row,
) -> DeliveryPollResult:
    allowed_kinds = delivery_kinds_for_registry_scope(
        registry_scope_for_agent_row(agent_row)
    )
    params: list[object] = [agent_row["agent_id"], cursor]
    sql = f"""
        SELECT seq, delivery_id, kind, payload_json, state, created_at
        FROM {dialect.qualify('deliveries')}
        WHERE target_agent_id = {dialect.placeholder(1)}
          AND state IN ('queued', 'leased')
          AND seq > {dialect.placeholder(2)}
    """
    if allowed_kinds is not None:
        placeholders = _in_placeholders(dialect, start_index=len(params) + 1, count=len(allowed_kinds))
        sql += f" AND kind IN ({placeholders})"
        params.extend(allowed_kinds)
    params.append(limit)
    sql += f" ORDER BY seq ASC LIMIT {dialect.placeholder(len(params))}"
    deliveries = dialect.fetchall(conn, sql, params)

    delivery_ids = [item["delivery_id"] for item in deliveries]
    if delivery_ids:
        lease_placeholders = _in_placeholders(dialect, start_index=3, count=len(delivery_ids))
        dialect.execute(
            conn,
            f"""
            UPDATE {dialect.qualify('deliveries')}
            SET state = 'leased', leased_at = {dialect.placeholder(1)}, updated_at = {dialect.placeholder(2)}
            WHERE delivery_id IN ({lease_placeholders})
            """,
            (now, now, *delivery_ids),
        )
        for item in deliveries:
            if item["kind"] != "routed_task":
                continue
            payload = decode_json_field(item["payload_json"], {})
            routed_task_id = str(payload.get("routed_task_id") or "").strip()
            if not routed_task_id:
                continue
            task_row = dialect.fetchone(
                conn,
                f"SELECT * FROM {dialect.qualify('routed_tasks')} WHERE routed_task_id = {dialect.placeholder(1)}",
                (routed_task_id,),
            )
            if task_row is None:
                continue
            decision = apply_task_transition(
                task_snapshot_row(task_row),
                TaskTransitionRequest(
                    transition="lease",
                    actor_role="system",
                    transition_id=item["delivery_id"],
                    occurred_at=now,
                ),
            )
            if decision.ok and not decision.duplicate and decision.new_state != task_row["status"]:
                dialect.execute(
                    conn,
                    (
                        f"UPDATE {dialect.qualify('routed_tasks')} "
                        f"SET status = {dialect.placeholder(1)}, updated_at = {dialect.placeholder(2)} "
                        f"WHERE routed_task_id = {dialect.placeholder(3)}"
                    ),
                    (decision.new_state, now, routed_task_id),
                )
    items = [
        record(DeliveryRecord, {
            "cursor": str(item["seq"]),
            "delivery_id": item["delivery_id"],
            "kind": item["kind"],
            "payload": decode_json_field(item["payload_json"], {}),
            "state": "leased" if item["delivery_id"] in delivery_ids else item["state"],
            "created_at": item["created_at"],
        })
        for item in deliveries
    ]
    next_cursor = str(max([cursor] + [int(item["cursor"]) for item in items]))
    return record(
        DeliveryPollResult,
        {
            "deliveries": items,
            "next_cursor": next_cursor,
            "registry_epoch": registry_epoch,
        },
    )


def ack(
    conn,
    *,
    dialect: StoreDialect,
    target_agent_id: str,
    delivery_ids: list[str],
    classification: str,
    now: str,
) -> AckResult:
    validated_ids, validated_classification = validated_ack_request(
        delivery_ids=delivery_ids,
        classification=classification,
    )
    next_state = {
        "accepted": "acked",
        "rejected": "dead_letter",
        "retry_later": "queued",
    }[validated_classification]
    placeholders = _in_placeholders(dialect, start_index=4, count=len(validated_ids))
    dialect.execute(
        conn,
        f"""
        UPDATE {dialect.qualify('deliveries')}
        SET state = {dialect.placeholder(1)},
            updated_at = {dialect.placeholder(2)},
            acked_at = {dialect.placeholder(3)},
            leased_at = NULL
        WHERE delivery_id IN ({placeholders})
          AND target_agent_id = {dialect.placeholder(len(validated_ids) + 4)}
        """,
        (
            next_state,
            now,
            now if next_state != "queued" else None,
            *validated_ids,
            target_agent_id,
        ),
    )
    return record(
        AckResult,
        {"updated": len(validated_ids), "classification": validated_classification},
    )


def create_delivery(
    conn,
    *,
    dialect: StoreDialect,
    json_param,
    target_agent_id: str,
    kind: str,
    payload: dict[str, object],
    now: str,
    delivery_id: str,
) -> DeliveryRecord:
    row = dialect.fetchone(
        conn,
        f"""
        INSERT INTO {dialect.qualify('deliveries')} (
            delivery_id, target_agent_id, kind, payload_json, state, created_at, updated_at
        )
        VALUES (
            {dialect.placeholder(1)},
            {dialect.placeholder(2)},
            {dialect.placeholder(3)},
            {dialect.placeholder(4)},
            'queued',
            {dialect.placeholder(5)},
            {dialect.placeholder(6)}
        )
        RETURNING seq
        """,
        (delivery_id, target_agent_id, kind, json_param(payload), now, now),
    )
    return record(DeliveryRecord, {"delivery_id": delivery_id, "seq": row["seq"]})


def create_management_request(
    conn,
    *,
    dialect: StoreDialect,
    create_delivery,
    json_param,
    request,
    now: str,
    delivery_id: str,
) -> ManagementRequest:
    validated_request = validated_management_request(
        request.model_dump(mode="json") if hasattr(request, "model_dump") else request
    )
    dialect.execute(
        conn,
        f"""
        INSERT INTO {dialect.qualify('management_requests')} (
            request_id, target_agent_id, operation, payload_json,
            status, delivery_id, result_json, error_code, error_detail, created_at, completed_at
        )
        VALUES (
            {dialect.placeholder(1)},
            {dialect.placeholder(2)},
            {dialect.placeholder(3)},
            {dialect.placeholder(4)},
            'queued',
            {dialect.placeholder(5)},
            NULL,
            '',
            '',
            {dialect.placeholder(6)},
            ''
        )
        ON CONFLICT (request_id) DO UPDATE SET
            target_agent_id = EXCLUDED.target_agent_id,
            operation = EXCLUDED.operation,
            payload_json = EXCLUDED.payload_json,
            status = 'queued',
            delivery_id = EXCLUDED.delivery_id,
            result_json = NULL,
            error_code = '',
            error_detail = '',
            created_at = EXCLUDED.created_at,
            completed_at = ''
        """,
        (
            validated_request.request_id,
            validated_request.agent_id,
            validated_request.operation,
            json_param(validated_request.model_dump(mode="json")),
            delivery_id,
            now,
        ),
    )
    create_delivery(
        conn,
        target_agent_id=validated_request.agent_id,
        kind="management_request",
        payload=validated_request.model_dump(mode="json"),
        now=now,
        delivery_id=delivery_id,
    )
    return validated_request


def report_management_result(
    conn,
    *,
    dialect: StoreDialect,
    token_row,
    json_param,
    agent_token: str,
    request_id: str,
    payload,
    now: str,
) -> ManagementResult:
    validated_result = validated_management_result(
        payload.model_dump(mode="json", by_alias=True) if hasattr(payload, "model_dump") else payload
    )
    if validated_result.request_id != request_id:
        raise ValueError("request_id must match the requested management result")
    row = token_row(conn, agent_token)
    if row is None:
        raise PermissionError("Unknown agent token")
    request_row = dialect.fetchone(
        conn,
        f"SELECT * FROM {dialect.qualify('management_requests')} WHERE request_id = {dialect.placeholder(1)}",
        (request_id,),
    )
    if request_row is None:
        raise KeyError(request_id)
    if str(request_row["target_agent_id"] or "") != str(row["agent_id"] or ""):
        raise PermissionError("Management request does not belong to this agent")
    completed_at = validated_result.completed_at or now
    dialect.execute(
        conn,
        f"""
        UPDATE {dialect.qualify('management_requests')}
        SET status = {dialect.placeholder(1)},
            result_json = {dialect.placeholder(2)},
            error_code = {dialect.placeholder(3)},
            error_detail = {dialect.placeholder(4)},
            completed_at = {dialect.placeholder(5)}
        WHERE request_id = {dialect.placeholder(6)}
        """,
        (
            "completed" if validated_result.success else "failed",
            json_param(validated_result.model_dump(mode="json", by_alias=True)),
            validated_result.error_code,
            validated_result.error_detail,
            completed_at,
            request_id,
        ),
    )
    return validated_result


def get_management_result(
    conn,
    *,
    dialect: StoreDialect,
    request_id: str,
) -> ManagementResult | None:
    row = dialect.fetchone(
        conn,
        f"SELECT result_json FROM {dialect.qualify('management_requests')} WHERE request_id = {dialect.placeholder(1)}",
        (request_id,),
    )
    if row is None:
        return None
    payload = decode_json_field(row.get("result_json"), None)
    if not payload:
        return None
    return validated_management_result(payload)
