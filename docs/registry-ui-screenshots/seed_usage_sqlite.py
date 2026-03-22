#!/usr/bin/env python3
"""Insert synthetic `usage` rows into the capture SQLite DB (kind not exposed via HTTP SDK)."""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: seed_usage_sqlite.py <db_path> [conversation_id ...]", file=sys.stderr)
        sys.exit(1)
    db_path = sys.argv[1]
    conv_ids = sys.argv[2:]
    if not conv_ids:
        print("Need at least one conversation_id", file=sys.stderr)
        sys.exit(1)
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        for i, cid in enumerate(conv_ids):
            meta = {
                "prompt_tokens": 1200 + i * 400,
                "completion_tokens": 200 + i * 100,
                "cost_usd": round(0.002 + i * 0.0015, 6),
            }
            eid = f"usage-seed-{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO events (event_id, conversation_id, agent_id, kind, actor, content, metadata_json, created_at)
                VALUES (?, ?, ?, 'usage', '', '', ?, ?)
                ON CONFLICT(event_id) DO NOTHING
                """,
                (eid, cid, "", json.dumps(meta), now),
            )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
