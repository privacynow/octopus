"""SQLite store for the central agent registry control plane."""

from __future__ import annotations

import json
import secrets
import sqlite3
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.agents.types import AgentCard, TimelineEvent, to_wire

_OFFLINE_AFTER_SECONDS = 60


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_json(value: Any) -> str:
    if is_dataclass(value):
        value = asdict(value)
    return json.dumps(value)


class RegistryStore:
    """Explicit SQLite store for agent registration, routing, and UI read models."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    agent_token TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL DEFAULT '',
                    skills_json TEXT NOT NULL DEFAULT '[]',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    description TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    mode TEXT NOT NULL DEFAULT 'standalone',
                    connectivity_state TEXT NOT NULL DEFAULT 'standalone',
                    current_capacity INTEGER NOT NULL DEFAULT 0,
                    max_capacity INTEGER NOT NULL DEFAULT 1,
                    surface_capabilities_json TEXT NOT NULL DEFAULT '[]',
                    version TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_heartbeat_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS deliveries (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    delivery_id TEXT NOT NULL UNIQUE,
                    target_agent_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    leased_at TEXT,
                    acked_at TEXT
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    target_agent_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    origin_surface TEXT NOT NULL DEFAULT 'registry',
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS routed_tasks (
                    routed_task_id TEXT PRIMARY KEY,
                    parent_conversation_id TEXT NOT NULL,
                    origin_agent_id TEXT NOT NULL,
                    target_agent_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    summary TEXT NOT NULL DEFAULT '',
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS timeline_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    conversation_id TEXT NOT NULL,
                    routed_task_id TEXT NOT NULL DEFAULT '',
                    agent_id TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    progress INTEGER,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )

    def _ensure_unique_slug(self, conn: sqlite3.Connection, requested: str) -> str:
        slug = requested
        suffix = 2
        while conn.execute("SELECT 1 FROM agents WHERE slug = ?", (slug,)).fetchone():
            slug = f"{requested}-{suffix}"
            suffix += 1
        return slug

    def _row_to_agent(self, row: sqlite3.Row) -> dict[str, Any]:
        last_heartbeat = row["last_heartbeat_at"]
        effective_state = row["connectivity_state"]
        if last_heartbeat:
            try:
                heartbeat_dt = datetime.fromisoformat(last_heartbeat)
                if heartbeat_dt.tzinfo is None:
                    heartbeat_dt = heartbeat_dt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - heartbeat_dt > timedelta(seconds=_OFFLINE_AFTER_SECONDS):
                    effective_state = "offline"
            except ValueError:
                pass
        return {
            "agent_id": row["agent_id"],
            "display_name": row["display_name"],
            "slug": row["slug"],
            "role": row["role"],
            "skills": json.loads(row["skills_json"] or "[]"),
            "tags": json.loads(row["tags_json"] or "[]"),
            "description": row["description"],
            "provider": row["provider"],
            "mode": row["mode"],
            "connectivity_state": effective_state,
            "current_capacity": row["current_capacity"],
            "max_capacity": row["max_capacity"],
            "surface_capabilities": json.loads(row["surface_capabilities_json"] or "[]"),
            "version": row["version"],
            "last_heartbeat_at": row["last_heartbeat_at"],
            "updated_at": row["updated_at"],
        }

    def _token_row(self, conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM agents WHERE agent_token = ?",
            (token,),
        ).fetchone()

    def enroll(self, requested_card: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        agent_id = uuid.uuid4().hex
        agent_token = secrets.token_urlsafe(32)
        with self._connect() as conn:
            slug = self._ensure_unique_slug(conn, requested_card.get("slug") or "agent")
            conn.execute(
                """
                INSERT INTO agents (
                    agent_id, agent_token, display_name, slug, role,
                    skills_json, tags_json, description, provider, mode,
                    connectivity_state, current_capacity, max_capacity,
                    surface_capabilities_json, version, created_at, updated_at, last_heartbeat_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    agent_token,
                    requested_card.get("display_name") or slug,
                    slug,
                    requested_card.get("role", ""),
                    _ensure_json(requested_card.get("skills", [])),
                    _ensure_json(requested_card.get("tags", [])),
                    requested_card.get("description", ""),
                    requested_card.get("provider", ""),
                    requested_card.get("mode", "registry"),
                    requested_card.get("connectivity_state", "degraded"),
                    int(requested_card.get("current_capacity", 0)),
                    max(1, int(requested_card.get("max_capacity", 1))),
                    _ensure_json(requested_card.get("surface_capabilities", [])),
                    requested_card.get("version", ""),
                    now,
                    now,
                    now,
                ),
            )
        return {
            "agent_id": agent_id,
            "slug": slug,
            "agent_token": agent_token,
            "poll_cursor": "0",
        }

    def register(self, agent_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        card = payload["agent_card"]
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            conn.execute(
                """
                UPDATE agents
                SET display_name = ?, role = ?, skills_json = ?, tags_json = ?,
                    description = ?, provider = ?, mode = ?, connectivity_state = ?,
                    current_capacity = ?, max_capacity = ?, surface_capabilities_json = ?,
                    version = ?, updated_at = ?, last_heartbeat_at = ?
                WHERE agent_token = ?
                """,
                (
                    card.get("display_name", row["display_name"]),
                    card.get("role", row["role"]),
                    _ensure_json(card.get("skills", [])),
                    _ensure_json(card.get("tags", [])),
                    card.get("description", row["description"]),
                    card.get("provider", row["provider"]),
                    card.get("mode", row["mode"]),
                    payload.get("connectivity_state", row["connectivity_state"]),
                    int(payload.get("current_capacity", 0)),
                    max(1, int(payload.get("max_capacity", 1))),
                    _ensure_json(card.get("surface_capabilities", [])),
                    card.get("version", row["version"]),
                    now,
                    now,
                    agent_token,
                ),
            )
            row = self._token_row(conn, agent_token)
            assert row is not None
            return self._row_to_agent(row)

    def heartbeat(self, agent_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            conn.execute(
                """
                UPDATE agents
                SET connectivity_state = ?, current_capacity = ?, max_capacity = ?,
                    updated_at = ?, last_heartbeat_at = ?
                WHERE agent_token = ?
                """,
                (
                    payload.get("connectivity_state", row["connectivity_state"]),
                    int(payload.get("current_capacity", row["current_capacity"])),
                    max(1, int(payload.get("max_capacity", row["max_capacity"]))),
                    now,
                    now,
                    agent_token,
                ),
            )
            row = self._token_row(conn, agent_token)
            assert row is not None
            return {
                "agent": self._row_to_agent(row),
                "server_time": now,
            }

    def publish_timeline(self, agent_token: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            for event in events:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO timeline_events (
                        event_id, conversation_id, routed_task_id, agent_id, kind, title,
                        body, status, progress, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event["event_id"],
                        event["conversation_id"],
                        event.get("metadata", {}).get("routed_task_id", ""),
                        row["agent_id"],
                        event["kind"],
                        event["title"],
                        event.get("body", ""),
                        event.get("status", ""),
                        event.get("progress"),
                        _ensure_json(event.get("metadata", {})),
                        event["created_at"],
                    ),
                )
            return {"accepted": len(events)}

    def bind_conversation(self, agent_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            conn.execute(
                """
                INSERT INTO conversations (
                    conversation_id, target_agent_id, title, origin_surface, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'open', ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    target_agent_id = excluded.target_agent_id,
                    title = excluded.title,
                    origin_surface = excluded.origin_surface,
                    updated_at = excluded.updated_at
                """,
                (
                    payload["conversation_id"],
                    row["agent_id"],
                    payload.get("title", ""),
                    payload.get("origin_surface", "telegram"),
                    now,
                    now,
                ),
            )
        return self.get_conversation(payload["conversation_id"])

    def search_agents(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        role = query.get("role", "").strip().lower()
        required_state = query.get("required_state", "connected")
        skills = {s.lower() for s in query.get("skills", []) if s}
        tags = {s.lower() for s in query.get("tags", []) if s}
        free_text = query.get("free_text", "").strip().lower()
        exclude = set(query.get("exclude_agent_ids", []))
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM agents ORDER BY display_name COLLATE NOCASE").fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            agent = self._row_to_agent(row)
            if agent["agent_id"] in exclude:
                continue
            if required_state and agent["connectivity_state"] != required_state:
                continue
            if role and role not in agent["role"].lower():
                continue
            agent_skills = {s.lower() for s in agent["skills"]}
            if skills and not skills.issubset(agent_skills):
                continue
            agent_tags = {s.lower() for s in agent["tags"]}
            if tags and not tags.issubset(agent_tags):
                continue
            if free_text:
                haystack = " ".join(
                    [
                        agent["display_name"],
                        agent["role"],
                        agent["description"],
                        " ".join(agent["skills"]),
                        " ".join(agent["tags"]),
                    ]
                ).lower()
                if free_text not in haystack:
                    continue
            results.append(agent)
        return results

    def create_delivery(self, *, target_agent_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        delivery_id = uuid.uuid4().hex
        with self._connect() as conn:
            return self._create_delivery(
                conn,
                target_agent_id=target_agent_id,
                kind=kind,
                payload=payload,
                now=now,
                delivery_id=delivery_id,
            )

    def _create_delivery(
        self,
        conn: sqlite3.Connection,
        *,
        target_agent_id: str,
        kind: str,
        payload: dict[str, Any],
        now: str,
        delivery_id: str,
    ) -> dict[str, Any]:
        conn.execute(
            """
            INSERT INTO deliveries (delivery_id, target_agent_id, kind, payload_json, state, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'queued', ?, ?)
            """,
            (delivery_id, target_agent_id, kind, _ensure_json(payload), now, now),
        )
        seq = conn.execute(
            "SELECT seq FROM deliveries WHERE delivery_id = ?",
            (delivery_id,),
        ).fetchone()["seq"]
        return {
            "delivery_id": delivery_id,
            "seq": seq,
        }

    def create_routed_task(self, request: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO routed_tasks (
                    routed_task_id, parent_conversation_id, origin_agent_id, target_agent_id,
                    title, request_json, status, summary, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', '', ?, ?)
                """,
                (
                    request["routed_task_id"],
                    request["parent_conversation_id"],
                    request["origin_agent_id"],
                    request["target_agent_id"],
                    request["title"],
                    _ensure_json(request),
                    now,
                    now,
                ),
            )
        delivery = self.create_delivery(
            target_agent_id=request["target_agent_id"],
            kind="routed_task",
            payload=request,
        )
        return {
            "routed_task_id": request["routed_task_id"],
            "delivery_id": delivery["delivery_id"],
        }

    def poll(self, agent_token: str, *, cursor: int, limit: int) -> dict[str, Any]:
        now = utcnow_iso()
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            deliveries = conn.execute(
                """
                SELECT seq, delivery_id, kind, payload_json, state, created_at
                FROM deliveries
                WHERE target_agent_id = ?
                  AND state = 'queued'
                  AND seq > ?
                ORDER BY seq ASC
                LIMIT ?
                """,
                (row["agent_id"], cursor, limit),
            ).fetchall()
            delivery_ids = [item["delivery_id"] for item in deliveries]
            if delivery_ids:
                placeholders = ",".join("?" for _ in delivery_ids)
                conn.execute(
                    f"""
                    UPDATE deliveries
                    SET state = 'leased', leased_at = ?, updated_at = ?
                    WHERE delivery_id IN ({placeholders})
                    """,
                    (now, now, *delivery_ids),
                )
        items = [
            {
                "cursor": str(item["seq"]),
                "delivery_id": item["delivery_id"],
                "kind": item["kind"],
                "payload": json.loads(item["payload_json"]),
                "state": "leased" if item["delivery_id"] in delivery_ids else item["state"],
                "created_at": item["created_at"],
            }
            for item in deliveries
        ]
        next_cursor = str(max([cursor] + [int(item["cursor"]) for item in items]))
        return {"deliveries": items, "next_cursor": next_cursor}

    def ack(self, agent_token: str, *, delivery_ids: list[str], classification: str) -> dict[str, Any]:
        now = utcnow_iso()
        next_state = {
            "accepted": "acked",
            "rejected": "dead_letter",
            "retry_later": "queued",
        }.get(classification, "queued")
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            for delivery_id in delivery_ids:
                conn.execute(
                    """
                    UPDATE deliveries
                    SET state = ?, updated_at = ?, acked_at = ?
                    WHERE delivery_id = ?
                      AND target_agent_id = ?
                    """,
                    (
                        next_state,
                        now,
                        now if next_state != "queued" else None,
                        delivery_id,
                        row["agent_id"],
                    ),
                )
        return {"updated": len(delivery_ids), "classification": classification}

    def update_routed_task_status(self, agent_token: str, routed_task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            conn.execute(
                """
                UPDATE routed_tasks
                SET status = ?, summary = ?, updated_at = ?
                WHERE routed_task_id = ?
                """,
                (payload.get("status", ""), payload.get("summary", ""), now, routed_task_id),
            )
            for event in payload.get("timeline_events", []):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO timeline_events (
                        event_id, conversation_id, routed_task_id, agent_id, kind, title,
                        body, status, progress, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event["event_id"],
                        event["conversation_id"],
                        routed_task_id,
                        row["agent_id"],
                        event["kind"],
                        event["title"],
                        event.get("body", ""),
                        event.get("status", ""),
                        event.get("progress"),
                        _ensure_json(event.get("metadata", {})),
                        event["created_at"],
                    ),
                )
        return {"routed_task_id": routed_task_id, "status": payload.get("status", "")}

    def update_routed_task_result(self, agent_token: str, routed_task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            task = conn.execute(
                "SELECT * FROM routed_tasks WHERE routed_task_id = ?",
                (routed_task_id,),
            ).fetchone()
            if task is None:
                raise KeyError(routed_task_id)
            conn.execute(
                """
                UPDATE routed_tasks
                SET status = ?, summary = ?, result_json = ?, updated_at = ?
                WHERE routed_task_id = ?
                """,
                (
                    payload.get("status", "completed"),
                    payload.get("summary", ""),
                    _ensure_json(payload),
                    now,
                    routed_task_id,
                ),
            )
            self._create_delivery(
                conn,
                target_agent_id=task["origin_agent_id"],
                kind="routed_result",
                payload={
                    "routed_task_id": routed_task_id,
                    "parent_conversation_id": task["parent_conversation_id"],
                    "result": payload,
                },
                now=now,
                delivery_id=uuid.uuid4().hex,
            )
        return {"routed_task_id": routed_task_id, "status": payload.get("status", "completed")}

    def deregister(self, agent_token: str) -> dict[str, Any]:
        now = utcnow_iso()
        with self._connect() as conn:
            row = self._token_row(conn, agent_token)
            if row is None:
                raise PermissionError("Unknown agent token")
            conn.execute(
                """
                UPDATE agents
                SET connectivity_state = 'offline', updated_at = ?, last_heartbeat_at = ?
                WHERE agent_token = ?
                """,
                (now, now, agent_token),
            )
            return {"agent_id": row["agent_id"], "connectivity_state": "offline"}

    def list_agents(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM agents ORDER BY display_name COLLATE NOCASE").fetchall()
        return [self._row_to_agent(row) for row in rows]

    def ui_bootstrap(self) -> dict[str, Any]:
        return {
            "bots": self.list_agents(),
            "conversations": self.list_conversations(),
            "tasks": self.list_tasks(),
        }

    def create_conversation(self, *, target_agent_id: str, title: str, message_text: str) -> dict[str, Any]:
        now = utcnow_iso()
        conversation_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations (
                    conversation_id, target_agent_id, title, origin_surface, status, created_at, updated_at
                ) VALUES (?, ?, ?, 'registry', 'open', ?, ?)
                """,
                (conversation_id, target_agent_id, title, now, now),
            )
        self.create_delivery(
            target_agent_id=target_agent_id,
            kind="surface_input",
            payload={
                "conversation_id": conversation_id,
                "title": title,
                "text": message_text,
                "surface": "registry",
            },
        )
        self.publish_ui_timeline(
            conversation_id=conversation_id,
            title="Conversation started",
            body=message_text,
            kind="surface_input",
        )
        return self.get_conversation(conversation_id)

    def publish_ui_timeline(
        self,
        *,
        conversation_id: str,
        title: str,
        body: str,
        kind: str,
        status: str = "",
        progress: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        event = TimelineEvent(
            event_id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            kind=kind,
            title=title,
            body=body,
            status=status,
            progress=progress,
            metadata=metadata or {},
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO timeline_events (
                    event_id, conversation_id, routed_task_id, agent_id, kind, title,
                    body, status, progress, metadata_json, created_at
                ) VALUES (?, ?, '', '', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.conversation_id,
                    event.kind,
                    event.title,
                    event.body,
                    event.status,
                    event.progress,
                    _ensure_json(event.metadata),
                    event.created_at,
                ),
            )

    def list_conversations(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*, a.display_name AS target_name
                FROM conversations c
                LEFT JOIN agents a ON a.agent_id = c.target_agent_id
                ORDER BY c.updated_at DESC
                """
            ).fetchall()
        return [
            {
                "conversation_id": row["conversation_id"],
                "target_agent_id": row["target_agent_id"],
                "target_display_name": row["target_name"] or "",
                "title": row["title"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT c.*, a.display_name AS target_name
                FROM conversations c
                LEFT JOIN agents a ON a.agent_id = c.target_agent_id
                WHERE c.conversation_id = ?
                """,
                (conversation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(conversation_id)
        tasks = [task for task in self.list_tasks() if task["parent_conversation_id"] == conversation_id]
        return {
            "conversation_id": row["conversation_id"],
            "target_agent_id": row["target_agent_id"],
            "target_display_name": row["target_name"] or "",
            "title": row["title"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "linked_routed_tasks": tasks,
        }

    def get_conversation_timeline(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM timeline_events
                WHERE conversation_id = ?
                ORDER BY seq ASC
                """,
                (conversation_id,),
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "conversation_id": row["conversation_id"],
                "routed_task_id": row["routed_task_id"],
                "agent_id": row["agent_id"],
                "kind": row["kind"],
                "title": row["title"],
                "body": row["body"],
                "status": row["status"],
                "progress": row["progress"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def add_conversation_message(self, conversation_id: str, text: str) -> dict[str, Any]:
        conversation = self.get_conversation(conversation_id)
        self.create_delivery(
            target_agent_id=conversation["target_agent_id"],
            kind="surface_input",
            payload={
                "conversation_id": conversation_id,
                "title": conversation["title"],
                "text": text,
                "surface": "registry",
            },
        )
        self.publish_ui_timeline(
            conversation_id=conversation_id,
            title="User message",
            body=text,
            kind="surface_input",
        )
        return {"conversation_id": conversation_id, "accepted": True}

    def add_conversation_action(self, conversation_id: str, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        conversation = self.get_conversation(conversation_id)
        action_payload = payload or {}
        self.create_delivery(
            target_agent_id=conversation["target_agent_id"],
            kind="surface_action",
            payload={
                "conversation_id": conversation_id,
                "action": action,
                "payload": action_payload,
                "surface": "registry",
            },
        )
        self.publish_ui_timeline(
            conversation_id=conversation_id,
            title=f"Action: {action}",
            body=json.dumps(action_payload) if action_payload else "",
            kind="surface_action",
        )
        return {"conversation_id": conversation_id, "accepted": True}

    def cancel_conversation(self, conversation_id: str) -> dict[str, Any]:
        conversation = self.get_conversation(conversation_id)
        self.create_delivery(
            target_agent_id=conversation["target_agent_id"],
            kind="control",
            payload={
                "conversation_id": conversation_id,
                "action": "cancel",
                "surface": "registry",
            },
        )
        self.publish_ui_timeline(
            conversation_id=conversation_id,
            title="Cancel requested",
            body="",
            kind="control",
        )
        return {"conversation_id": conversation_id, "accepted": True}

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT t.*, origin.display_name AS origin_name, target.display_name AS target_name
                FROM routed_tasks t
                LEFT JOIN agents origin ON origin.agent_id = t.origin_agent_id
                LEFT JOIN agents target ON target.agent_id = t.target_agent_id
                ORDER BY t.updated_at DESC
                """
            ).fetchall()
        return [
            {
                "routed_task_id": row["routed_task_id"],
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
            for row in rows
        ]
