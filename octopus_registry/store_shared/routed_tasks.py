from __future__ import annotations

import uuid

from octopus_sdk.registry.models import EventRecord, TaskRecord
from octopus_sdk.task_protocol import TaskTransitionRequest, apply_task_transition

from octopus_registry.store_base import (
    decode_json_field,
    routed_task_created_event,
    validated_routed_task_request,
    validated_routed_task_result_payload,
    validated_routed_task_status_payload,
)
from octopus_registry.store_dialect import StoreDialect
from octopus_registry.store_shared.common import record


def create_routed_task(
    conn,
    *,
    dialect: StoreDialect,
    request,
    now: str,
    create_routed_task_in_tx,
) -> TaskRecord:
    validated_request = validated_routed_task_request(
        request.model_dump(mode="json") if hasattr(request, "model_dump") else request
    )
    conversation_row = dialect.fetchone(
        conn,
        (
            f"SELECT conversation_id FROM {dialect.qualify('conversations')} "
            f"WHERE conversation_id = {dialect.placeholder(1)}"
        ),
        (validated_request.parent_conversation_id,),
    )
    if conversation_row is None:
        raise KeyError(validated_request.parent_conversation_id)
    created = create_routed_task_in_tx(
        conn,
        validated_request,
        now=now,
    )
    delivery = created["delivery"]
    inserted_event = created.get("event")
    recipient_event = created.get("recipient_event")
    inserted_events = [inserted_event] if isinstance(inserted_event, EventRecord) else []
    recipient_inserted_events = [recipient_event] if isinstance(recipient_event, EventRecord) else []
    return record(TaskRecord, {
        "routed_task_id": validated_request.routed_task_id,
        "delivery_id": delivery.delivery_id,
        "events_written": bool(inserted_events or recipient_inserted_events),
        "inserted_events": inserted_events,
        "recipient_conversation_id": str(created.get("recipient_conversation_id") or ""),
        "recipient_inserted_events": recipient_inserted_events,
        "parent_conversation_id": validated_request.parent_conversation_id,
        "origin_agent_id": validated_request.origin_agent_id,
        "target_agent_id": validated_request.target_agent_id,
    })


def update_routed_task_status(
    conn,
    *,
    dialect: StoreDialect,
    token_row,
    require_coordination_scope,
    task_snapshot_row,
    insert_event,
    ensure_conversation_in_tx,
    agent_token: str,
    routed_task_id: str,
    payload,
    now: str,
) -> TaskRecord:
    payload_data = payload.model_dump(mode="json", exclude_none=True) if hasattr(payload, "model_dump") else payload
    if isinstance(payload_data, dict):
        payload_task_id = str(payload_data.pop("routed_task_id", "") or "")
        if payload_task_id and payload_task_id != routed_task_id:
            raise ValueError("routed_task_id must match the requested task")
        payload_data = {"routed_task_id": routed_task_id, **payload_data}
    validated_payload = validated_routed_task_status_payload(payload_data)

    row = token_row(conn, agent_token)
    if row is None:
        raise PermissionError("Unknown agent token")
    require_coordination_scope(row)
    task_row = dialect.fetchone(
        conn,
        f"SELECT * FROM {dialect.qualify('routed_tasks')} WHERE routed_task_id = {dialect.placeholder(1)}",
        (routed_task_id,),
    )
    if task_row is None:
        raise KeyError(routed_task_id)
    if str(task_row["target_agent_id"] or "") != str(row["agent_id"] or ""):
        raise PermissionError("Routed task does not belong to this agent")

    requested_status = validated_payload.status
    if requested_status == "running":
        transition = "progress" if str(task_row["status"] or "") == "running" else "start"
    elif requested_status == "failed":
        transition = "fail"
    elif requested_status == "timed_out":
        transition = "time_out"
    elif requested_status == "cancelled":
        transition = "cancel"
    elif requested_status == "leased":
        transition = "lease"
    else:
        raise ValueError(f"Unsupported routed task status: {requested_status}")

    decision = apply_task_transition(
        task_snapshot_row(task_row),
        TaskTransitionRequest(
            transition=transition,
            actor_role="target_bot",
            transition_id=validated_payload.transition_id,
            occurred_at=now,
            progress=validated_payload.progress,
        ),
    )
    if not decision.ok:
        raise ValueError(decision.reason or f"Task {routed_task_id} cannot transition to {requested_status}")

    inserted_events: list[EventRecord] = []
    recipient_inserted_events: list[EventRecord] = []
    recipient_conversation_id = ""
    primary_event_id = f"task-transition:{routed_task_id}:{validated_payload.transition_id}"
    duplicate = (
        dialect.fetchone(
            conn,
            f"SELECT 1 FROM {dialect.qualify('events')} WHERE event_id = {dialect.placeholder(1)}",
            (primary_event_id,),
        )
        is not None
    )
    if not duplicate:
        dialect.execute(
            conn,
            (
                f"UPDATE {dialect.qualify('routed_tasks')} "
                f"SET status = {dialect.placeholder(1)}, summary = {dialect.placeholder(2)}, "
                f"updated_at = {dialect.placeholder(3)} WHERE routed_task_id = {dialect.placeholder(4)}"
            ),
            (
                decision.new_state,
                validated_payload.summary,
                now,
                routed_task_id,
            ),
        )
        primary_metadata: dict[str, object] = {
            "routed_task_id": routed_task_id,
            "status": decision.new_state,
            "transition_id": validated_payload.transition_id,
        }
        if validated_payload.progress is not None:
            primary_metadata["progress"] = validated_payload.progress
        primary_event = insert_event(
            conn,
            event_id=primary_event_id,
            conversation_id=str(task_row["parent_conversation_id"] or ""),
            agent_id=str(row["agent_id"] or ""),
            kind="task.status",
            actor="",
            content=str(validated_payload.summary or decision.new_state),
            metadata=primary_metadata,
            created_at=now,
        )
        if primary_event is not None:
            inserted_events.append(primary_event)
        task_request = decode_json_field(task_row["request_json"], {})
        recipient_conversation_id = ensure_conversation_in_tx(
            conn,
            target_agent_id=str(task_row["target_agent_id"] or ""),
            title=str(task_row["title"] or routed_task_id),
            conversation_type="task_thread",
            origin_channel="registry",
            external_conversation_ref=str(task_request.get("external_conversation_ref", "") or ""),
            now=now,
        )
        recipient_event = insert_event(
            conn,
            event_id=f"{primary_event_id}:recipient",
            conversation_id=recipient_conversation_id,
            agent_id=str(row["agent_id"] or ""),
            kind="task.status",
            actor="",
            content=str(validated_payload.summary or decision.new_state),
            metadata=primary_metadata,
            created_at=now,
        )
        if recipient_event is not None:
            recipient_inserted_events.append(recipient_event)
            dialect.execute(
                conn,
                (
                    f"UPDATE {dialect.qualify('conversations')} "
                    f"SET updated_at = {dialect.placeholder(1)} WHERE conversation_id = {dialect.placeholder(2)}"
                ),
                (now, recipient_conversation_id),
            )
        for event in validated_payload.timeline_events:
            raw_metadata = event.metadata.as_dict() if hasattr(event.metadata, "as_dict") else dict(event.metadata or {})
            event_metadata = {
                "routed_task_id": routed_task_id,
                "status": decision.new_state,
                "transition_id": validated_payload.transition_id,
                **raw_metadata,
            }
            if event.progress is not None:
                event_metadata["progress"] = event.progress
            inserted_event = insert_event(
                conn,
                event_id=event.event_id,
                conversation_id=event.conversation_id,
                agent_id=str(row["agent_id"] or ""),
                kind="task.status",
                actor="",
                content=str(event.body or event.title or ""),
                metadata=event_metadata,
                created_at=event.created_at,
            )
            if inserted_event is not None:
                inserted_events.append(inserted_event)
        if inserted_events:
            dialect.execute(
                conn,
                (
                    f"UPDATE {dialect.qualify('conversations')} "
                    f"SET updated_at = {dialect.placeholder(1)} WHERE conversation_id = {dialect.placeholder(2)}"
                ),
                (inserted_events[-1].created_at, task_row["parent_conversation_id"]),
            )
    return record(TaskRecord, {
        "routed_task_id": routed_task_id,
        "status": decision.new_state,
        "duplicate": duplicate,
        "events_written": bool(inserted_events or recipient_inserted_events),
        "inserted_events": inserted_events,
        "recipient_conversation_id": recipient_conversation_id,
        "recipient_inserted_events": recipient_inserted_events,
        "parent_conversation_id": task_row["parent_conversation_id"],
        "origin_agent_id": task_row["origin_agent_id"],
        "target_agent_id": task_row["target_agent_id"],
    })


def update_routed_task_result(
    conn,
    *,
    dialect: StoreDialect,
    token_row,
    require_coordination_scope,
    task_snapshot_row,
    insert_event,
    ensure_conversation_in_tx,
    create_delivery,
    json_param,
    agent_token: str,
    routed_task_id: str,
    payload,
    now: str,
) -> TaskRecord:
    usage_fields = {
        "prompt_tokens",
        "completion_tokens",
        "cached_prompt_tokens",
        "cached_completion_tokens",
        "cost_usd",
    }
    if hasattr(payload, "model_fields_set"):
        include_usage_fields = bool(
            set(getattr(payload, "model_fields_set", set())) & usage_fields
        )
    elif isinstance(payload, dict):
        include_usage_fields = bool(set(payload) & usage_fields)
    else:
        include_usage_fields = False
    payload_data = payload.model_dump(mode="json", exclude_none=True) if hasattr(payload, "model_dump") else payload
    if isinstance(payload_data, dict):
        payload_task_id = str(payload_data.pop("routed_task_id", "") or "")
        if payload_task_id and payload_task_id != routed_task_id:
            raise ValueError("routed_task_id must match the requested task")
        payload_data = {"routed_task_id": routed_task_id, **payload_data}
    validated_payload = validated_routed_task_result_payload(payload_data)

    row = token_row(conn, agent_token)
    if row is None:
        raise PermissionError("Unknown agent token")
    require_coordination_scope(row)
    task = dialect.fetchone(
        conn,
        f"SELECT * FROM {dialect.qualify('routed_tasks')} WHERE routed_task_id = {dialect.placeholder(1)}",
        (routed_task_id,),
    )
    if task is None:
        raise KeyError(routed_task_id)
    task_request = decode_json_field(task["request_json"], {})
    if str(task["target_agent_id"] or "") != str(row["agent_id"] or ""):
        raise PermissionError("Routed task does not belong to this agent")
    requested_status = validated_payload.status
    if requested_status == "completed":
        transition = "complete"
    elif requested_status == "failed":
        transition = "fail"
    elif requested_status == "timed_out":
        transition = "time_out"
    else:
        raise ValueError(f"Unsupported routed task result status: {requested_status}")
    completed_at = validated_payload.completed_at or now
    decision = apply_task_transition(
        task_snapshot_row(task),
        TaskTransitionRequest(
            transition=transition,
            actor_role="target_bot",
            transition_id=validated_payload.transition_id,
            occurred_at=completed_at,
        ),
    )
    if not decision.ok:
        raise ValueError(decision.reason or f"Task {routed_task_id} cannot transition to {requested_status}")

    primary_event_id = f"task-result:{routed_task_id}:{validated_payload.transition_id}"
    duplicate = (
        dialect.fetchone(
            conn,
            f"SELECT 1 FROM {dialect.qualify('events')} WHERE event_id = {dialect.placeholder(1)}",
            (primary_event_id,),
        )
        is not None
    )
    parent_conversation = dialect.fetchone(
        conn,
        (
            f"SELECT external_conversation_ref FROM {dialect.qualify('conversations')} "
            f"WHERE conversation_id = {dialect.placeholder(1)}"
        ),
        (task["parent_conversation_id"],),
    )
    inserted_events: list[EventRecord] = []
    recipient_inserted_events: list[EventRecord] = []
    recipient_conversation_id = ""
    if not duplicate:
        persisted_result = validated_payload.model_dump(mode="json", exclude_none=True)
        persisted_result["completed_at"] = completed_at
        persisted_result["status"] = decision.new_state
        dialect.execute(
            conn,
            (
                f"UPDATE {dialect.qualify('routed_tasks')} "
                f"SET status = {dialect.placeholder(1)}, summary = {dialect.placeholder(2)}, "
                f"result_json = {dialect.placeholder(3)}, updated_at = {dialect.placeholder(4)} "
                f"WHERE routed_task_id = {dialect.placeholder(5)}"
            ),
            (
                decision.new_state,
                validated_payload.summary,
                json_param(persisted_result),
                completed_at,
                routed_task_id,
            ),
        )
        create_delivery(
            conn,
            target_agent_id=task["origin_agent_id"],
            kind="routed_result",
            payload={
                "routed_task_id": routed_task_id,
                "parent_conversation_id": task["parent_conversation_id"],
                "parent_transport_ref": str(task_request.get("origin_transport_ref", "") or ""),
                "parent_external_conversation_ref": (
                    str(parent_conversation["external_conversation_ref"] or "")
                    if parent_conversation is not None
                    else ""
                ),
                "result": persisted_result,
            },
            now=completed_at,
            delivery_id=uuid.uuid4().hex,
        )
        event_metadata = {
            "routed_task_id": routed_task_id,
            "status": decision.new_state,
            "transition_id": validated_payload.transition_id,
        }
        if include_usage_fields:
            event_metadata["prompt_tokens"] = int(validated_payload.prompt_tokens or 0)
            event_metadata["completion_tokens"] = int(validated_payload.completion_tokens or 0)
            if validated_payload.cached_prompt_tokens is not None:
                event_metadata["cached_prompt_tokens"] = int(validated_payload.cached_prompt_tokens or 0)
            if validated_payload.cached_completion_tokens is not None:
                event_metadata["cached_completion_tokens"] = int(validated_payload.cached_completion_tokens or 0)
            event_metadata["cost_usd"] = float(validated_payload.cost_usd or 0.0)
        if validated_payload.provider:
            event_metadata["provider"] = validated_payload.provider
        content = str(validated_payload.summary or validated_payload.full_text or decision.new_state)
        mirrored_event = insert_event(
            conn,
            event_id=primary_event_id,
            conversation_id=str(task["parent_conversation_id"] or ""),
            agent_id=str(row["agent_id"] or ""),
            kind="task.status",
            actor="",
            content=content,
            metadata=event_metadata,
            created_at=completed_at,
        )
        if mirrored_event is not None:
            inserted_events.append(mirrored_event)
            dialect.execute(
                conn,
                (
                    f"UPDATE {dialect.qualify('conversations')} "
                    f"SET updated_at = {dialect.placeholder(1)} WHERE conversation_id = {dialect.placeholder(2)}"
                ),
                (completed_at, task["parent_conversation_id"]),
            )
        recipient_conversation_id = ensure_conversation_in_tx(
            conn,
            target_agent_id=str(task["target_agent_id"] or ""),
            title=str(task["title"] or routed_task_id),
            conversation_type="task_thread",
            origin_channel="registry",
            external_conversation_ref=str(task_request.get("external_conversation_ref", "") or ""),
            now=completed_at,
        )
        recipient_event = insert_event(
            conn,
            event_id=f"{primary_event_id}:recipient",
            conversation_id=recipient_conversation_id,
            agent_id=str(row["agent_id"] or ""),
            kind="task.status",
            actor="",
            content=content,
            metadata={
                "routed_task_id": routed_task_id,
                "status": decision.new_state,
                "transition_id": validated_payload.transition_id,
            },
            created_at=completed_at,
        )
        if recipient_event is not None:
            recipient_inserted_events.append(recipient_event)
            dialect.execute(
                conn,
                (
                    f"UPDATE {dialect.qualify('conversations')} "
                    f"SET updated_at = {dialect.placeholder(1)} WHERE conversation_id = {dialect.placeholder(2)}"
                ),
                (completed_at, recipient_conversation_id),
            )
    return record(TaskRecord, {
        "routed_task_id": routed_task_id,
        "status": decision.new_state,
        "duplicate": duplicate,
        "events_written": bool(inserted_events or recipient_inserted_events),
        "inserted_events": inserted_events,
        "recipient_conversation_id": recipient_conversation_id,
        "recipient_inserted_events": recipient_inserted_events,
        "parent_conversation_id": task["parent_conversation_id"],
        "origin_transport_ref": str(task_request.get("origin_transport_ref", "") or ""),
        "origin_agent_id": task["origin_agent_id"],
        "target_agent_id": task["target_agent_id"],
    })
