from __future__ import annotations

from octopus_sdk.registry.models import AckResult, DeliveryPollResult, DeliveryRecord
from octopus_sdk.task_protocol import TaskTransitionRequest, apply_task_transition

from octopus_registry.store_base import decode_json_field, delivery_kinds_for_registry_scope, registry_scope_for_agent_row, validated_ack_request
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
