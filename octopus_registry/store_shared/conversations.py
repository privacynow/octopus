from __future__ import annotations

import hashlib
import json
import uuid

from octopus_sdk.registry.models import (
    ConversationRecord,
    CoordinationActionResult,
    DelegationTaskDraft,
    EventPageRecord,
    EventRecord,
    MessagePageRecord,
    MessageRecord,
    PublishEventsResult,
    TaskRecord,
    normalized_requested_skills,
)
from octopus_sdk.task_protocol import RoutedTaskSnapshot, TaskTransitionRequest, apply_task_transition

from octopus_registry.store_base import (
    decode_json_field,
    delegation_event,
    routed_task_external_conversation_ref,
    stable_routed_task_id,
    validated_action_payload,
    validated_conversation_action,
    validated_conversation_message_text,
)
from octopus_registry.store_dialect import StoreDialect
from octopus_registry.store_shared.common import record, records


def _in_placeholders(dialect: StoreDialect, *, start_index: int, count: int) -> str:
    return ",".join(dialect.placeholder(start_index + offset) for offset in range(count))


def _conversation_payload(row):
    return {
        "conversation_id": row["conversation_id"],
        "target_agent_id": row["target_agent_id"],
        "target_display_name": row["target_name"] or "",
        "target_name": row["target_name"] or "",
        "source_kind": row.get("source_kind", "human") or "human",
        "hidden_from_default_views": bool(row.get("hidden_from_default_views", False)),
        "title": row["title"],
        "conversation_type": row["conversation_type"] or "conversation",
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "origin_channel": row["origin_channel"],
        "external_conversation_ref": row["external_conversation_ref"],
        "event_count": int(row["event_count"] or 0),
    }


def _linked_task_payload(row):
    return {
        "routed_task_id": row["routed_task_id"],
        "source_kind": row.get("source_kind", "delegation") or "delegation",
        "hidden_from_default_views": bool(row.get("hidden_from_default_views", False)),
        "parent_conversation_id": row["parent_conversation_id"],
        "origin_agent_id": row["origin_agent_id"],
        "origin_display_name": row["origin_name"] or "",
        "target_agent_id": row["target_agent_id"],
        "target_display_name": row["target_name"] or "",
        "title": row["title"],
        "status": row["status"],
        "summary": row["summary"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def event_record_from_row(row) -> EventRecord:
    return record(EventRecord, {
        "seq": row["seq"],
        "event_id": row["event_id"],
        "conversation_id": row["conversation_id"],
        "agent_id": row["agent_id"],
        "kind": row["kind"],
        "actor": row["actor"],
        "content": row["content"],
        "metadata": decode_json_field(row["metadata_json"], {}),
        "created_at": row["created_at"],
    })


def event_record_by_id(
    conn,
    *,
    dialect: StoreDialect,
    event_id: str,
) -> EventRecord | None:
    row = dialect.fetchone(
        conn,
        (
            f"SELECT seq, event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at "
            f"FROM {dialect.qualify('events')} WHERE event_id = {dialect.placeholder(1)}"
        ),
        (event_id,),
    )
    return event_record_from_row(row) if row is not None else None


def touch_conversation(
    conn,
    *,
    dialect: StoreDialect,
    conversation_id: str,
    updated_at: str,
    status: str | None = None,
) -> None:
    if status is None:
        dialect.execute(
            conn,
            (
                f"UPDATE {dialect.qualify('conversations')} "
                f"SET updated_at = {dialect.placeholder(1)} "
                f"WHERE conversation_id = {dialect.placeholder(2)}"
            ),
            (updated_at, conversation_id),
        )
        return
    dialect.execute(
        conn,
        (
            f"UPDATE {dialect.qualify('conversations')} "
            f"SET updated_at = {dialect.placeholder(1)}, status = {dialect.placeholder(2)} "
            f"WHERE conversation_id = {dialect.placeholder(3)}"
        ),
        (updated_at, status, conversation_id),
    )


def _operator_event(
    conn,
    *,
    dialect: StoreDialect,
    json_param,
    conversation_id: str,
    event_id: str,
    kind: str,
    content: str,
    metadata: dict[str, object],
    created_at: str,
) -> EventRecord | None:
    return insert_event(
        conn,
        dialect=dialect,
        json_param=json_param,
        event_id=event_id,
        conversation_id=conversation_id,
        agent_id="",
        kind=kind,
        actor="operator",
        content=content,
        metadata=metadata,
        created_at=created_at,
    )


def _coordination_result(
    conn,
    *,
    dialect: StoreDialect,
    conversation_id: str,
    action_id: str,
    action: str,
    event_id: str,
    inserted_event: EventRecord | None,
    **extra,
) -> CoordinationActionResult:
    duplicate = inserted_event is None
    event = inserted_event or event_record_by_id(conn, dialect=dialect, event_id=event_id)
    return CoordinationActionResult(
        conversation_id=conversation_id,
        action_id=action_id,
        action=action,
        accepted=True,
        duplicate=duplicate,
        event=event,
        **extra,
    )


def _task_stub(
    *,
    routed_task_id: str,
    target_agent_id: str,
    title: str,
    status: str,
) -> dict[str, object]:
    return {
        "routed_task_id": routed_task_id,
        "target_agent_id": target_agent_id,
        "authority_ref": "",
        "title": title,
        "status": status,
    }


def _conversation_context(
    conn,
    *,
    dialect: StoreDialect,
    conversation_id: str,
) -> dict[str, object]:
    conversation = dialect.fetchone(
        conn,
        f"""
        SELECT
            c.target_agent_id,
            c.title,
            c.origin_channel,
            c.external_conversation_ref,
            a.bot_key
        FROM {dialect.qualify('conversations')} c
        LEFT JOIN {dialect.qualify('agents')} a ON a.agent_id = c.target_agent_id
        WHERE c.conversation_id = {dialect.placeholder(1)}
        """,
        (conversation_id,),
    )
    if conversation is None:
        raise KeyError(conversation_id)
    bot_key = str(conversation["bot_key"] or "").strip()
    if not bot_key:
        raise ValueError(f"Unknown agent or missing bot_key: {conversation['target_agent_id']}")
    return conversation


def _attach_resource_refs(
    conn,
    *,
    dialect: StoreDialect,
    json_param,
    resource_refs,
    target_kind: str,
    target_ref: str,
    relation: str,
    created_by: str,
    now: str,
    metadata: dict[str, object] | None = None,
) -> None:
    seen: set[str] = set()
    for resource_ref in resource_refs or []:
        resource_id = str(resource_ref or "").strip()
        if not resource_id or resource_id in seen:
            continue
        seen.add(resource_id)
        attachment_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"octopus-resource-attachment:{resource_id}:{target_kind}:{target_ref}:{relation}",
        ).hex
        dialect.execute(
            conn,
            f"""
            INSERT INTO {dialect.qualify('resource_attachments')} (
                attachment_id, resource_id, target_kind, target_ref, relation,
                metadata_json, created_by, created_at
            ) VALUES (
                {dialect.placeholder(1)}, {dialect.placeholder(2)}, {dialect.placeholder(3)}, {dialect.placeholder(4)},
                {dialect.placeholder(5)}, {dialect.placeholder(6)}, {dialect.placeholder(7)}, {dialect.placeholder(8)}
            )
            ON CONFLICT (resource_id, target_kind, target_ref, relation)
                WHERE detached_at = ''
            DO UPDATE SET metadata_json = EXCLUDED.metadata_json
            """,
            (
                attachment_id,
                resource_id,
                target_kind,
                target_ref,
                relation,
                json_param(dict(metadata or {})),
                created_by,
                now,
            ),
        )


def insert_event(
    conn,
    *,
    dialect: StoreDialect,
    json_param,
    event_id: str,
    conversation_id: str,
    agent_id: str,
    kind: str,
    actor: str,
    content: str,
    metadata: dict[str, object],
    created_at: str,
) -> EventRecord | None:
    row = dialect.fetchone(
        conn,
        f"""
        INSERT INTO {dialect.qualify('events')} (
            event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at
        )
        VALUES (
            {dialect.placeholder(1)},
            {dialect.placeholder(2)},
            {dialect.placeholder(3)},
            {dialect.placeholder(4)},
            {dialect.placeholder(5)},
            {dialect.placeholder(6)},
            {dialect.placeholder(7)},
            {dialect.placeholder(8)}
        )
        ON CONFLICT(event_id) DO NOTHING
        RETURNING seq, event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at
        """,
        (
            event_id,
            conversation_id,
            agent_id,
            kind,
            actor,
            content,
            json_param(metadata),
            created_at,
        ),
    )
    return event_record_from_row(row) if row is not None else None


def ensure_conversation_in_tx(
    conn,
    *,
    dialect: StoreDialect,
    target_agent_id: str,
    title: str,
    conversation_type: str = "conversation",
    origin_channel: str,
    external_conversation_ref: str,
    now: str,
    source_kind: str = "human",
    hidden_from_default_views: bool = False,
) -> str:
    if not origin_channel or not origin_channel.strip():
        raise ValueError("origin_channel must not be empty")
    if not external_conversation_ref or not external_conversation_ref.strip():
        raise ValueError("external_conversation_ref must not be empty")
    agent_row = dialect.fetchone(
        conn,
        f"SELECT bot_key FROM {dialect.qualify('agents')} WHERE agent_id = {dialect.placeholder(1)}",
        (target_agent_id,),
    )
    bot_key = str(agent_row["bot_key"] or "").strip() if agent_row is not None else ""
    if not bot_key:
        raise ValueError(f"Unknown agent or missing bot_key: {target_agent_id}")
    canonical = f"{bot_key}:{origin_channel}:{external_conversation_ref}"
    conversation_id = hashlib.sha256(canonical.encode()).hexdigest()[:32]
    row = dialect.fetchone(
        conn,
        f"""
        INSERT INTO {dialect.qualify('conversations')} (
            conversation_id, target_agent_id, title, conversation_type, origin_channel,
            external_conversation_ref, source_kind, hidden_from_default_views, status, created_at, updated_at
        ) VALUES (
            {dialect.placeholder(1)},
            {dialect.placeholder(2)},
            {dialect.placeholder(3)},
            {dialect.placeholder(4)},
            {dialect.placeholder(5)},
            {dialect.placeholder(6)},
            {dialect.placeholder(7)},
            {dialect.placeholder(8)},
            'open',
            {dialect.placeholder(9)},
            {dialect.placeholder(10)}
        )
        ON CONFLICT(target_agent_id, origin_channel, external_conversation_ref) DO UPDATE SET
            title = EXCLUDED.title,
            source_kind = EXCLUDED.source_kind,
            hidden_from_default_views = EXCLUDED.hidden_from_default_views,
            updated_at = EXCLUDED.updated_at
        RETURNING conversation_id
        """,
        (
            conversation_id,
            target_agent_id,
            title,
            conversation_type,
            origin_channel,
            external_conversation_ref,
            source_kind,
            hidden_from_default_views,
            now,
            now,
        ),
    )
    return str(row["conversation_id"])


def create_conversation(
    conn,
    *,
    dialect: StoreDialect,
    target_agent_id: str,
    title: str,
    origin_channel: str,
    external_conversation_ref: str,
    now: str,
    source_kind: str = "human",
    hidden_from_default_views: bool = False,
) -> ConversationRecord:
    conversation_id = ensure_conversation_in_tx(
        conn,
        dialect=dialect,
        target_agent_id=target_agent_id,
        title=title,
        conversation_type="conversation",
        origin_channel=origin_channel,
        external_conversation_ref=external_conversation_ref,
        now=now,
        source_kind=source_kind,
        hidden_from_default_views=hidden_from_default_views,
    )
    return get_conversation(conn, dialect=dialect, conversation_id=conversation_id)


def add_conversation_message(
    conn,
    *,
    dialect: StoreDialect,
    create_delivery,
    json_param,
    conversation_id: str,
    text: str,
    now: str,
    resource_refs: tuple[str, ...] = (),
) -> MessageRecord:
    validated_text = validated_conversation_message_text(text)
    conversation = _conversation_context(conn, dialect=dialect, conversation_id=conversation_id)
    event_id = uuid.uuid4().hex
    normalized_resource_refs = tuple(
        str(item or "").strip()
        for item in resource_refs
        if str(item or "").strip()
    )
    create_delivery(
        conn,
        target_agent_id=conversation["target_agent_id"],
        kind="channel_input",
        payload={
            "conversation_id": conversation_id,
            "title": conversation["title"],
            "text": validated_text,
            "channel": "registry",
            "bot_key": conversation["bot_key"],
            "origin_channel": conversation["origin_channel"],
            "external_conversation_ref": conversation["external_conversation_ref"],
            "stable_event_id": event_id,
            "stable_created_at": now,
            "resource_refs": list(normalized_resource_refs),
        },
        now=now,
        delivery_id=uuid.uuid4().hex,
    )
    inserted_event = _operator_event(
        conn,
        dialect=dialect,
        json_param=json_param,
        event_id=event_id,
        conversation_id=conversation_id,
        kind="message.user",
        content=validated_text,
        metadata={"resource_refs": list(normalized_resource_refs)} if normalized_resource_refs else {},
        created_at=now,
    )
    touch_conversation(conn, dialect=dialect, conversation_id=conversation_id, updated_at=now)
    return record(
        MessageRecord,
        {"conversation_id": conversation_id, "accepted": True, "event": inserted_event},
    )


def add_conversation_action(
    conn,
    *,
    dialect: StoreDialect,
    create_delivery,
    create_routed_task_in_tx,
    resolve_selector,
    json_param,
    conversation_id: str,
    envelope,
    now: str,
) -> CoordinationActionResult:
    validated_envelope = validated_conversation_action(envelope)
    action_payload = validated_action_payload(validated_envelope)
    conversation = _conversation_context(conn, dialect=dialect, conversation_id=conversation_id)
    routed_tasks: list[dict[str, object]] = []

    if validated_envelope.action in {
        "approve_pending",
        "reject_pending",
        "retry_allow",
        "retry_skip",
        "recovery_discard",
        "recovery_replay",
        "cancel_conversation",
    }:
        create_delivery(
            conn,
            target_agent_id=conversation["target_agent_id"],
            kind="channel_action",
            payload={
                "conversation_id": conversation_id,
                "conversation_ref": conversation_id,
                "action": validated_envelope.action,
                "payload": {} if action_payload is None else action_payload.model_dump(exclude_unset=True),
                "channel": "registry",
                "bot_key": conversation["bot_key"],
                "origin_channel": conversation["origin_channel"],
                "external_conversation_ref": conversation["external_conversation_ref"],
                "stable_event_id": validated_envelope.action_id,
                "stable_created_at": now,
            },
            now=now,
            delivery_id=uuid.uuid4().hex,
        )
        if validated_envelope.action == "cancel_conversation":
            inserted_event = _operator_event(
                conn,
                dialect=dialect,
                json_param=json_param,
                event_id=validated_envelope.action_id,
                conversation_id=conversation_id,
                kind="task.status",
                content="",
                metadata={"routed_task_id": "", "status": "cancelling"},
                created_at=now,
            )
            touch_conversation(
                conn,
                dialect=dialect,
                conversation_id=conversation_id,
                updated_at=now,
                status="cancelling",
            )
        else:
            inserted_event = _operator_event(
                conn,
                dialect=dialect,
                json_param=json_param,
                event_id=validated_envelope.action_id,
                conversation_id=conversation_id,
                kind="approval.decided",
                content=json.dumps(action_payload.model_dump(exclude_unset=True)),
                metadata={
                    "action": validated_envelope.action,
                    "decided_by": "operator",
                    "decision": (
                        "rejected"
                        if validated_envelope.action in {"reject_pending", "retry_skip", "recovery_discard"}
                        else "approved"
                    ),
                },
                created_at=now,
            )
            touch_conversation(conn, dialect=dialect, conversation_id=conversation_id, updated_at=now)
        return _coordination_result(
            conn,
            dialect=dialect,
            conversation_id=conversation_id,
            action_id=validated_envelope.action_id,
            action=validated_envelope.action,
            event_id=validated_envelope.action_id,
            inserted_event=inserted_event,
        )

    if validated_envelope.action == "delegate_tasks":
        proposal = action_payload
        task_entries = [
            {
                "draft_id": task.draft_id,
                "title": task.title,
                "target": task.selector.preferred_agent_id or task.selector.value,
                "status": "proposed",
                "routed_task_id": "",
                "selector_kind": task.selector.kind,
                "selector_value": task.selector.value,
                "instructions": task.instructions,
                "priority": task.priority,
                "requested_skills": list(task.requested_skills),
                "context": dict(task.context),
                "resource_refs": list(task.resource_refs or []),
            }
            for task in proposal.tasks
        ]
        delegation_evt = delegation_event(
            kind="delegation.proposed",
            proposal_id=validated_envelope.action_id,
            conversation_id=conversation_id,
            tasks=task_entries,
            created_at=now,
            content=proposal.title or "Delegation proposal",
            origin_transport_ref=str(proposal.origin_transport_ref or ""),
            authorized_actor_key=str(proposal.authorized_actor_key or ""),
        )
        inserted_event = _operator_event(
            conn,
            dialect=dialect,
            json_param=json_param,
            event_id=delegation_evt["event_id"],
            conversation_id=conversation_id,
            kind=delegation_evt["kind"],
            content=delegation_evt["content"],
            metadata=delegation_evt["metadata"],
            created_at=delegation_evt["created_at"],
        )
        touch_conversation(conn, dialect=dialect, conversation_id=conversation_id, updated_at=now)
        return _coordination_result(
            conn,
            dialect=dialect,
            conversation_id=conversation_id,
            action_id=validated_envelope.action_id,
            action=validated_envelope.action,
            event_id=delegation_evt["event_id"],
            inserted_event=inserted_event,
            proposal_id=validated_envelope.action_id,
        )

    if validated_envelope.action == "delegation_approve":
        proposal_id = action_payload.proposal_id
        proposal_row = dialect.fetchone(
            conn,
            f"""
            SELECT * FROM {dialect.qualify('events')}
            WHERE conversation_id = {dialect.placeholder(1)}
              AND kind = {dialect.placeholder(2)}
              AND metadata_json->>'proposal_id' = {dialect.placeholder(3)}
            ORDER BY seq DESC
            LIMIT 1
            """,
            (conversation_id, "delegation.proposed", proposal_id),
        )
        if proposal_row is None:
            raise ValueError(f"Unknown delegation proposal: {proposal_id}")
        proposal_metadata = decode_json_field(proposal_row["metadata_json"], {})
        proposal_origin_transport_ref = str(proposal_metadata.get("origin_transport_ref", "") or "")
        proposal_authorized_actor_key = str(proposal_metadata.get("authorized_actor_key", "") or "")
        task_entries = list(proposal_metadata.get("tasks", []))
        if not task_entries:
            raise ValueError(f"Delegation proposal {proposal_id} has no tasks")
        for index, entry in enumerate(task_entries):
            draft = DelegationTaskDraft.model_validate(
                {
                    "draft_id": entry.get("draft_id", f"draft-{index + 1}"),
                    "selector": {
                        "kind": entry.get("selector_kind", "agent"),
                        "value": entry.get("selector_value", entry.get("target", "")),
                        "preferred_agent_id": entry.get("target", ""),
                    },
                    "title": entry.get("title", ""),
                    "instructions": entry.get("instructions", ""),
                    "priority": entry.get("priority", "normal"),
                    "requested_skills": entry.get("requested_skills", []),
                    "context": entry.get("context", {}),
                    "resource_refs": entry.get("resource_refs", []),
                }
            )
            requested_skills = normalized_requested_skills(entry.get("requested_skills", []), selector=draft.selector)
            resolved_target = resolve_selector(conn, draft.selector)
            routed_task_id = stable_routed_task_id(conversation_id, validated_envelope.action_id, index)
            request = {
                "routed_task_id": routed_task_id,
                "parent_conversation_id": conversation_id,
                "origin_transport_ref": proposal_origin_transport_ref or str(conversation["external_conversation_ref"] or ""),
                "authorized_actor_key": proposal_authorized_actor_key,
                "external_conversation_ref": routed_task_external_conversation_ref(routed_task_id),
                "origin_agent_id": conversation["target_agent_id"],
                "target_agent_id": resolved_target["agent_id"],
                "title": draft.title,
                "instructions": draft.instructions,
                "context": dict(draft.context),
                "requested_skills": requested_skills,
                "resource_refs": list(draft.resource_refs or []),
                "priority": draft.priority,
                "created_at": now,
            }
            create_routed_task_in_tx(conn, request, now=now)
            _attach_resource_refs(
                conn,
                dialect=dialect,
                json_param=json_param,
                resource_refs=draft.resource_refs,
                target_kind="routed_task",
                target_ref=routed_task_id,
                relation="input",
                created_by="registry",
                now=now,
                metadata={"source_action": "delegation_approve", "proposal_id": proposal_id},
            )
            routed_tasks.append(_task_stub(
                routed_task_id=request["routed_task_id"],
                target_agent_id=resolved_target["agent_id"],
                title=draft.title,
                status="queued",
            ))
        submitted_event = delegation_event(
            kind="delegation.submitted",
            proposal_id=proposal_id,
            conversation_id=conversation_id,
            tasks=[
                {
                    **entry,
                    "status": "submitted",
                    "routed_task_id": routed_tasks[index]["routed_task_id"],
                    "target": routed_tasks[index]["target_agent_id"],
                }
                for index, entry in enumerate(task_entries)
            ],
            created_at=now,
            content="Delegated work submitted",
            origin_transport_ref=proposal_origin_transport_ref,
            authorized_actor_key=proposal_authorized_actor_key,
        )
        inserted_event = _operator_event(
            conn,
            dialect=dialect,
            json_param=json_param,
            event_id=f"delegation.submitted:{validated_envelope.action_id}",
            conversation_id=conversation_id,
            kind=submitted_event["kind"],
            content=submitted_event["content"],
            metadata=submitted_event["metadata"],
            created_at=submitted_event["created_at"],
        )
        touch_conversation(conn, dialect=dialect, conversation_id=conversation_id, updated_at=now)
        return _coordination_result(
            conn,
            dialect=dialect,
            conversation_id=conversation_id,
            action_id=validated_envelope.action_id,
            action=validated_envelope.action,
            event_id=f"delegation.submitted:{validated_envelope.action_id}",
            inserted_event=inserted_event,
            proposal_id=proposal_id,
            routed_tasks=routed_tasks,
        )

    if validated_envelope.action == "direct_assign":
        assignment = action_payload
        routed_task_id = stable_routed_task_id(conversation_id, validated_envelope.action_id, 0)
        resolved_target = resolve_selector(conn, assignment.selector)
        requested_skills = normalized_requested_skills(assignment.requested_skills, selector=assignment.selector)
        inserted_events: list[EventRecord] = []
        parent_event_id = str(assignment.parent_event_id or "").strip()
        message_metadata = {
            "source_action": "direct_assign",
            "action_id": validated_envelope.action_id,
            "selector_kind": assignment.selector.kind,
            "selector_value": assignment.selector.value,
            "routed_task_id": routed_task_id,
            "requested_skills": requested_skills,
            "resource_refs": list(assignment.resource_refs or []),
        }
        if parent_event_id:
            dialect.execute(
                conn,
                f"""
                UPDATE {dialect.qualify('events')}
                SET metadata_json = COALESCE(metadata_json, '{{}}'::jsonb) || {dialect.placeholder(1)}
                WHERE conversation_id = {dialect.placeholder(2)}
                  AND event_id = {dialect.placeholder(3)}
                  AND kind = 'message.user'
                """,
                (json_param(message_metadata), conversation_id, parent_event_id),
            )
        elif str(assignment.message_text or "").strip():
            inserted_message = _operator_event(
                conn,
                dialect=dialect,
                json_param=json_param,
                event_id=f"direct-assign-message:{validated_envelope.action_id}",
                conversation_id=conversation_id,
                kind="message.user",
                content=str(assignment.message_text or "").strip(),
                metadata=message_metadata,
                created_at=now,
            )
            if inserted_message is not None:
                inserted_events.append(inserted_message)
        request = {
            "routed_task_id": routed_task_id,
            "parent_conversation_id": conversation_id,
            "origin_transport_ref": (
                str(assignment.origin_transport_ref or "") or str(conversation["external_conversation_ref"] or "")
            ),
            "authorized_actor_key": str(assignment.authorized_actor_key or ""),
            "external_conversation_ref": routed_task_external_conversation_ref(routed_task_id),
            "origin_agent_id": conversation["target_agent_id"],
            "target_agent_id": resolved_target["agent_id"],
            "title": assignment.title,
            "instructions": assignment.instructions,
            "context": dict(assignment.context),
            "requested_skills": requested_skills,
            "resource_refs": list(assignment.resource_refs or []),
            "priority": assignment.priority,
            "created_at": now,
        }
        created = create_routed_task_in_tx(conn, request, now=now)
        _attach_resource_refs(
            conn,
            dialect=dialect,
            json_param=json_param,
            resource_refs=assignment.resource_refs,
            target_kind="routed_task",
            target_ref=routed_task_id,
            relation="input",
            created_by="registry",
            now=now,
            metadata={"source_action": "direct_assign", "action_id": validated_envelope.action_id},
        )
        inserted_event = created.get("event")
        if inserted_event is not None:
            inserted_events.append(inserted_event)
        routed_tasks.append(_task_stub(
            routed_task_id=request["routed_task_id"],
            target_agent_id=resolved_target["agent_id"],
            title=assignment.title,
            status="queued",
        ))
        touch_conversation(conn, dialect=dialect, conversation_id=conversation_id, updated_at=now)
        return _coordination_result(
            conn,
            dialect=dialect,
            conversation_id=conversation_id,
            action_id=validated_envelope.action_id,
            action=validated_envelope.action,
            event_id=f"routed-task:{routed_task_id}:queued",
            inserted_event=inserted_event,
            proposal_id=validated_envelope.action_id,
            routed_tasks=routed_tasks,
            inserted_events=inserted_events,
        )

    if validated_envelope.action in {"cancel_task", "retry_task", "delegation_cancel"}:
        if validated_envelope.action == "delegation_cancel":
            inserted_event = _operator_event(
                conn,
                dialect=dialect,
                json_param=json_param,
                event_id=validated_envelope.action_id,
                conversation_id=conversation_id,
                kind="approval.decided",
                content="",
                metadata={
                    "action": validated_envelope.action,
                    "decided_by": "operator",
                    "decision": "rejected",
                },
                created_at=now,
            )
            touch_conversation(conn, dialect=dialect, conversation_id=conversation_id, updated_at=now)
            return _coordination_result(
                conn,
                dialect=dialect,
                conversation_id=conversation_id,
                action_id=validated_envelope.action_id,
                action=validated_envelope.action,
                event_id=validated_envelope.action_id,
                inserted_event=inserted_event,
                proposal_id=action_payload.proposal_id,
            )
        task_row = dialect.fetchone(
            conn,
            (
                f"SELECT * FROM {dialect.qualify('routed_tasks')} "
                f"WHERE routed_task_id = {dialect.placeholder(1)} "
                f"AND parent_conversation_id = {dialect.placeholder(2)}"
            ),
            (action_payload.routed_task_id, conversation_id),
        )
        if task_row is None:
            raise ValueError(f"Unknown task {action_payload.routed_task_id} for conversation {conversation_id}")
        if validated_envelope.action == "retry_task":
            request = decode_json_field(task_row["request_json"], {})
            request["routed_task_id"] = stable_routed_task_id(conversation_id, validated_envelope.action_id, 0)
            request["created_at"] = now
            request["parent_conversation_id"] = conversation_id
            created = create_routed_task_in_tx(conn, request, now=now)
            routed_tasks.append(_task_stub(
                routed_task_id=request["routed_task_id"],
                target_agent_id=request["target_agent_id"],
                title=request["title"],
                status="queued",
            ))
            inserted_event = created.get("event")
        else:
            decision = apply_task_transition(
                RoutedTaskSnapshot(
                    status=str(task_row["status"] or "queued"),
                    queued_at=str(task_row["created_at"] or ""),
                ),
                TaskTransitionRequest(
                    transition="cancel",
                    actor_role="operator",
                    transition_id=validated_envelope.action_id,
                    occurred_at=now,
                ),
            )
            if not decision.ok:
                raise ValueError(decision.reason or f"Task {action_payload.routed_task_id} cannot be cancelled")
            dialect.execute(
                conn,
                (
                    f"UPDATE {dialect.qualify('routed_tasks')} "
                    f"SET status = {dialect.placeholder(1)}, summary = {dialect.placeholder(2)}, "
                    f"updated_at = {dialect.placeholder(3)} WHERE routed_task_id = {dialect.placeholder(4)}"
                ),
                ("cancelled", "Cancelled by operator.", now, action_payload.routed_task_id),
            )
            inserted_event = _operator_event(
                conn,
                dialect=dialect,
                json_param=json_param,
                event_id=validated_envelope.action_id,
                conversation_id=conversation_id,
                kind="task.status",
                content="Cancelled by operator.",
                metadata={
                    "routed_task_id": action_payload.routed_task_id,
                    "status": "cancelled",
                    "transition_id": validated_envelope.action_id,
                },
                created_at=now,
            )
            routed_tasks.append(_task_stub(
                routed_task_id=action_payload.routed_task_id,
                target_agent_id=str(task_row["target_agent_id"] or ""),
                title=str(task_row["title"] or ""),
                status="cancelled",
            ))
        touch_conversation(conn, dialect=dialect, conversation_id=conversation_id, updated_at=now)
        return _coordination_result(
            conn,
            dialect=dialect,
            conversation_id=conversation_id,
            action_id=validated_envelope.action_id,
            action=validated_envelope.action,
            event_id=validated_envelope.action_id,
            inserted_event=inserted_event,
            routed_tasks=routed_tasks,
        )

    raise ValueError(f"Unsupported action: {validated_envelope.action}")


def publish_events(
    conn,
    *,
    dialect: StoreDialect,
    json_param,
    agent_id: str,
    conversation_id: str,
    events: list[object],
) -> PublishEventsResult:
    inserted = 0
    skipped = 0
    inserted_ids: set[str] = set()
    inserted_events: list[EventRecord] = []
    latest_created_at = ""
    for event_model in events:
        event = event_model.model_dump(mode="json") if hasattr(event_model, "model_dump") else event_model
        serialized = json.dumps(event)
        if len(serialized) >= 256 * 1024:
            raise ValueError("Event exceeds 256KB size limit")
        event_id = str(event.get("event_id", "") or "")
        if not event_id.strip():
            raise ValueError("event_id is required")
        kind = str(event.get("kind", "") or "")
        if not kind.strip():
            raise ValueError("kind is required")
        created_at = str(event.get("created_at", "") or "")
        row = dialect.fetchone(
            conn,
            f"""
            INSERT INTO {dialect.qualify('events')} (
                event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at
            )
            VALUES (
                {dialect.placeholder(1)},
                {dialect.placeholder(2)},
                {dialect.placeholder(3)},
                {dialect.placeholder(4)},
                {dialect.placeholder(5)},
                {dialect.placeholder(6)},
                {dialect.placeholder(7)},
                {dialect.placeholder(8)}
            )
            ON CONFLICT(event_id) DO NOTHING
            RETURNING seq, event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at
            """,
            (
                event_id,
                conversation_id,
                agent_id,
                kind,
                str(event.get("actor", "") or ""),
                str(event.get("content", "") or ""),
                json_param(event.get("metadata", {})),
                created_at,
            ),
        )
        if row is None:
            skipped += 1
            continue
        inserted += 1
        inserted_ids.add(event_id)
        latest_created_at = str(row["created_at"] or latest_created_at)
        inserted_events.append(event_record_from_row(row))
    if latest_created_at:
        touch_conversation(conn, dialect=dialect, conversation_id=conversation_id, updated_at=latest_created_at)
    return record(
        PublishEventsResult,
        {
            "inserted": inserted,
            "skipped": skipped,
            "inserted_ids": list(inserted_ids),
            "inserted_events": inserted_events,
        },
    )


def list_events(
    conn,
    *,
    dialect: StoreDialect,
    conversation_id: str,
    kind: str = "",
    before_seq: int = 0,
    after_seq: int = 0,
    limit: int = 50,
) -> EventPageRecord:
    if before_seq and after_seq:
        raise ValueError("before_seq and after_seq cannot both be set")
    kinds = [item.strip() for item in kind.split(",") if item.strip()]
    clauses = [f"conversation_id = {dialect.placeholder(1)}"]
    params: list[object] = [conversation_id]
    if kinds:
        placeholders = _in_placeholders(dialect, start_index=len(params) + 1, count=len(kinds))
        clauses.append(f"kind IN ({placeholders})")
        params.extend(kinds)
    if before_seq:
        params.append(before_seq)
        clauses.append(f"seq < {dialect.placeholder(len(params))}")
        order_sql = "ORDER BY seq DESC"
    elif after_seq:
        params.append(after_seq)
        clauses.append(f"seq > {dialect.placeholder(len(params))}")
        order_sql = "ORDER BY seq ASC"
    else:
        order_sql = "ORDER BY seq DESC"
    params.append(limit + 1)
    rows = dialect.fetchall(
        conn,
        f"""
        SELECT * FROM {dialect.qualify('events')}
        WHERE {' AND '.join(clauses)}
        {order_sql}
        LIMIT {dialect.placeholder(len(params))}
        """,
        params,
    )
    has_more_before = False
    if before_seq or not after_seq:
        has_more_before = len(rows) > limit
        if has_more_before:
            rows = rows[:limit]
        rows = list(reversed(rows))
    elif len(rows) > limit:
        rows = rows[:limit]
    event_rows = [event_record_from_row(row) for row in rows]
    return record(
        EventPageRecord,
        {
            "events": event_rows,
            "has_more_before": has_more_before,
            "next_before_seq": event_rows[0].seq if has_more_before and event_rows else None,
            "next_after_seq": event_rows[-1].seq if event_rows else None,
        },
    )


def list_messages(
    conn,
    *,
    dialect: StoreDialect,
    conversation_id: str,
    cursor: int = 0,
    limit: int = 50,
) -> MessagePageRecord:
    rows = dialect.fetchall(
        conn,
        f"""
        SELECT * FROM {dialect.qualify('events')}
        WHERE conversation_id = {dialect.placeholder(1)}
          AND kind IN ('message.user', 'message.bot')
          AND seq > {dialect.placeholder(2)}
        ORDER BY seq ASC
        LIMIT {dialect.placeholder(3)}
        """,
        (conversation_id, cursor, limit),
    )
    events = [event_record_from_row(row) for row in rows]
    return record(
        MessagePageRecord,
        {"events": events, "next_cursor": events[-1].seq if events else 0},
    )


def list_conversations(
    conn,
    *,
    dialect: StoreDialect,
    for_agent_id: str | None = None,
    cursor: int = 0,
    limit: int = 25,
    status: str = "",
    conversation_type: str = "",
    search_hit_ids: list[str] | None = None,
    include_generated: bool = True,
) -> list[ConversationRecord]:
    fetch_limit = limit + 1
    params: list[object] = []
    sql = f"""
        SELECT
            c.*,
            a.display_name AS target_name,
            COUNT(e.event_id) AS event_count
        FROM {dialect.qualify('conversations')} c
        LEFT JOIN {dialect.qualify('agents')} a ON a.agent_id = c.target_agent_id
        LEFT JOIN {dialect.qualify('events')} e ON e.conversation_id = c.conversation_id
    """
    where_clauses: list[str] = []
    if search_hit_ids is not None:
        placeholders = _in_placeholders(dialect, start_index=1, count=len(search_hit_ids))
        where_clauses.append(f"c.conversation_id IN ({placeholders})")
        params.extend(search_hit_ids)
    if for_agent_id is not None:
        params.append(for_agent_id)
        where_clauses.append(f"c.target_agent_id = {dialect.placeholder(len(params))}")
    if status:
        params.append(status)
        where_clauses.append(f"c.status = {dialect.placeholder(len(params))}")
    if conversation_type:
        params.append(conversation_type)
        where_clauses.append(f"c.conversation_type = {dialect.placeholder(len(params))}")
    if not include_generated:
        where_clauses.append("c.hidden_from_default_views = FALSE")
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    params.extend([fetch_limit, cursor])
    sql += """
        GROUP BY
            c.conversation_id,
            c.target_agent_id,
            c.source_kind,
            c.hidden_from_default_views,
            c.title,
            c.conversation_type,
            c.origin_channel,
            c.external_conversation_ref,
            c.status,
            c.created_at,
            c.updated_at,
            a.display_name
        ORDER BY c.updated_at DESC
    """
    sql += (
        f" LIMIT {dialect.placeholder(len(params) - 1)} "
        f"OFFSET {dialect.placeholder(len(params))}"
    )
    rows = dialect.fetchall(conn, sql, params)
    return records(ConversationRecord, [_conversation_payload(row) for row in rows])


def get_conversation(
    conn,
    *,
    dialect: StoreDialect,
    conversation_id: str,
) -> ConversationRecord:
    row = dialect.fetchone(
        conn,
        f"""
        SELECT
            c.*,
            a.display_name AS target_name,
            COUNT(e.event_id) AS event_count
        FROM {dialect.qualify('conversations')} c
        LEFT JOIN {dialect.qualify('agents')} a ON a.agent_id = c.target_agent_id
        LEFT JOIN {dialect.qualify('events')} e ON e.conversation_id = c.conversation_id
        WHERE c.conversation_id = {dialect.placeholder(1)}
        GROUP BY
            c.conversation_id,
            c.target_agent_id,
            c.source_kind,
            c.hidden_from_default_views,
            c.title,
            c.conversation_type,
            c.origin_channel,
            c.external_conversation_ref,
            c.status,
            c.created_at,
            c.updated_at,
            a.display_name
        """,
        (conversation_id,),
    )
    if row is None:
        raise KeyError(conversation_id)
    task_rows = dialect.fetchall(
        conn,
        f"""
        SELECT t.*, origin.display_name AS origin_name, target.display_name AS target_name
        FROM {dialect.qualify('routed_tasks')} t
        LEFT JOIN {dialect.qualify('agents')} origin ON origin.agent_id = t.origin_agent_id
        LEFT JOIN {dialect.qualify('agents')} target ON target.agent_id = t.target_agent_id
        WHERE t.parent_conversation_id = {dialect.placeholder(1)}
        ORDER BY t.updated_at DESC
        """,
        (conversation_id,),
    )
    payload = _conversation_payload(row)
    payload["linked_routed_tasks"] = records(TaskRecord, [_linked_task_payload(task) for task in task_rows])
    return record(ConversationRecord, payload)


def list_agent_conversations(
    conn,
    *,
    dialect: StoreDialect,
    agent_id: str,
    for_agent_id: str | None = None,
    cursor: int = 0,
    limit: int = 50,
    conversation_type: str = "",
    include_generated: bool = True,
) -> list[ConversationRecord]:
    fetch_limit = limit + 1
    effective_agent_id = for_agent_id if for_agent_id is not None else agent_id
    params: list[object] = [effective_agent_id]
    sql = f"""
        SELECT c.*, a.display_name AS target_name
        FROM {dialect.qualify('conversations')} c
        LEFT JOIN {dialect.qualify('agents')} a ON a.agent_id = c.target_agent_id
        WHERE c.target_agent_id = {dialect.placeholder(1)}
    """
    if conversation_type:
        params.append(conversation_type)
        sql += f" AND c.conversation_type = {dialect.placeholder(len(params))}"
    if not include_generated:
        sql += " AND c.hidden_from_default_views = FALSE"
    params.extend([fetch_limit, cursor])
    sql += """
        ORDER BY c.updated_at DESC
    """
    sql += (
        f" LIMIT {dialect.placeholder(len(params) - 1)} "
        f"OFFSET {dialect.placeholder(len(params))}"
    )
    rows = dialect.fetchall(conn, sql, params)
    return records(ConversationRecord, [
        {
            "conversation_id": row["conversation_id"],
            "target_agent_id": row["target_agent_id"],
            "target_display_name": row["target_name"] or "",
            "target_name": row["target_name"] or "",
            "source_kind": row.get("source_kind", "human") or "human",
            "hidden_from_default_views": bool(row.get("hidden_from_default_views", False)),
            "title": row["title"],
            "conversation_type": row["conversation_type"] or "conversation",
            "origin_channel": row["origin_channel"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ])
