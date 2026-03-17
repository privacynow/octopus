"""Compose E2E proof suite for Shared Runtime durability and concurrency.

Every proof runs on both supported backends:
- SQLite using the same shared Docker volume topology as production Compose,
  with in-container durable-state inspection
- Postgres with direct host-side DB queries
"""

from __future__ import annotations

import json
import http.client
import os
import socket
import subprocess
import time
import uuid
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

import psycopg
import pytest

from app.identity import telegram_conversation_key
from tests.e2e.compose_support import (
    REPO_ROOT,
    build_image,
    compose,
    compose_down,
    compose_logs,
    e2e_skip,
    fail_with_logs,
    free_local_port,
    remove_image,
)

pytestmark = pytest.mark.usefixtures("e2e_skip")


def _worker_id() -> str:
    return os.environ.get("PYTEST_XDIST_WORKER", "master")


@pytest.fixture(scope="module")
def runnable_bot_image(tmp_path_factory) -> dict[str, object]:
    worker = _worker_id()
    run_id = uuid.uuid4().hex[:10]
    artifacts_dir = tmp_path_factory.mktemp(f"compose-shared-runtime-build-{worker}")
    tag = f"octopus-agent-e2e-runnable:{worker}-{run_id}"
    build_image(
        dockerfile="infra/docker/Dockerfile.runnable",
        tag=tag,
        artifacts_dir=artifacts_dir,
    )
    yield {"tag": tag, "artifacts_dir": artifacts_dir}
    remove_image(tag, artifacts_dir)


@pytest.fixture
def shared_runtime_env(tmp_path, backend, runnable_bot_image):
    worker = _worker_id()
    run_id = uuid.uuid4().hex[:10]
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    project = f"octopus-agent-shared-proof-{backend}-{worker}-{run_id}"
    webhook_port = free_local_port()
    postgres_port = free_local_port() if backend == "postgres" else 0
    env_file = tmp_path / ".env.shared.runtime"
    override_path = tmp_path / "docker-compose.shared.runtime.generated.yml"

    ctx = {
        "backend": backend,
        "project": project,
        "cwd": REPO_ROOT,
        "project_dir": REPO_ROOT,
        "artifacts_dir": artifacts_dir,
        "bot_image": runnable_bot_image["tag"],
        "volume_name": "e2e-bot-home",
        "env_file": env_file,
        "override_path": override_path,
        "webhook_port": webhook_port,
        "postgres_port": postgres_port,
        "env": {
            **os.environ,
            "COMPOSE_PROJECT_NAME": project,
        },
        "compose_files": [
            "-f", os.path.join(REPO_ROOT, "infra/compose/docker-compose.yml"),
            "-f", os.path.join(REPO_ROOT, "infra/compose/docker-compose.shared.yml"),
            "-f", os.path.join(REPO_ROOT, "infra/compose/docker-compose.e2e.yml"),
            "-f", str(override_path),
        ],
        "worker_scale": 1,
        "lease_ttl": 30.0,
        "sweep_interval": 60.0,
    }

    _write_shared_runtime_files(ctx)
    compose_down(ctx, "preclean")
    yield ctx
    try:
        compose_logs(ctx, "final", *_log_services(ctx))
    finally:
        down_result, down_log = compose_down(ctx)
        if down_result.returncode != 0:
            details = f"Compose cleanup failed for project {project}."
            if down_log is not None:
                details += f"\n\nCompose cleanup log saved to: {down_log}"
                log_text = down_log.read_text(encoding="utf-8").strip()
                if log_text:
                    details += f"\n\n{log_text}"
            pytest.fail(details)


def _write_shared_runtime_files(ctx: dict[str, object]) -> None:
    backend = str(ctx["backend"])
    env_lines = [
        "BOT_PROVIDER=claude",
        "TELEGRAM_BOT_TOKEN=123456:ABC-DEFghijklmnopqrstuvwxyz",
        "BOT_ALLOW_OPEN=1",
        "BOT_ALLOWED_USERS=tg:42",
        "BOT_APPROVAL_MODE=off",
        "BOT_RUNTIME_MODE=shared",
        "BOT_MODE=webhook",
        "BOT_WEBHOOK_URL=http://bot-webhook:8443/webhook",
        "BOT_WEBHOOK_LISTEN=0.0.0.0",
        "BOT_WEBHOOK_PORT=8443",
        "BOT_TYPING_INTERVAL=60",
        f"BOT_CLAIM_LEASE_TTL={int(float(ctx['lease_ttl']))}",
        f"BOT_CLAIM_SWEEP_INTERVAL_SECONDS={float(ctx['sweep_interval'])}",
        "BOT_TELEGRAM_API_BASE_URL=http://telegram-api-stub:8081/bot",
        "BOT_TELEGRAM_FILE_API_BASE_URL=http://telegram-api-stub:8081/file/bot",
        "TELEGRAM_AGENT_STUB_CONTROL_DIR=/home/bot/e2e-control",
    ]
    if backend == "postgres":
        env_lines.append("BOT_DATABASE_URL=postgresql://bot:bot@postgres:5432/bot")
    ctx["env_file"].write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    env_file_path = json.dumps(str(ctx["env_file"]))
    postgres_port_mapping = json.dumps(f"{ctx['postgres_port']}:5432")
    webhook_port_mapping = json.dumps(f"{ctx['webhook_port']}:8443")
    lines = [
        "volumes:",
        f"  {ctx['volume_name']}:",
        "services:",
        "  postgres:",
    ]
    if backend == "postgres":
        lines.extend(
            [
                "    ports: !override",
                f"      - {postgres_port_mapping}",
            ]
        )
    else:
        lines.extend(
            [
                "    ports: !override",
                "      []",
            ]
        )
    lines.extend(
        [
            "  telegram-api-stub:",
            f"    image: {ctx['bot_image']}",
            '    command: ["python", "/app/scripts/docker/telegram_api_stub.py", "--port", "8081"]',
            "  bot-webhook:",
            f"    image: {ctx['bot_image']}",
            "    env_file: !override",
            f"      - {env_file_path}",
            "    ports: !override",
            f"      - {webhook_port_mapping}",
            "    volumes: !override",
            f"      - {ctx['volume_name']}:/home/bot",
            "    depends_on:",
            "      telegram-api-stub:",
            "        condition: service_started",
            "  bot-worker:",
            f"    image: {ctx['bot_image']}",
            "    env_file: !override",
            f"      - {env_file_path}",
            "    volumes: !override",
            f"      - {ctx['volume_name']}:/home/bot",
            "    depends_on:",
            "      telegram-api-stub:",
            "        condition: service_started",
        ]
    )
    if backend == "postgres":
        webhook_depends_insert_at = lines.index("  bot-worker:")
        lines[webhook_depends_insert_at:webhook_depends_insert_at] = [
            "      postgres:",
            "        condition: service_healthy",
        ]
        lines.extend(
            [
                "      postgres:",
                "        condition: service_healthy",
            ]
        )
    ctx["override_path"].write_text("\n".join(lines) + "\n", encoding="utf-8")


def _set_runtime_tuning(
    ctx: dict[str, object],
    *,
    lease_ttl: float | None = None,
    sweep_interval: float | None = None,
) -> None:
    if lease_ttl is not None:
        ctx["lease_ttl"] = lease_ttl
    if sweep_interval is not None:
        ctx["sweep_interval"] = sweep_interval
    _write_shared_runtime_files(ctx)


def _wait_for_port(host: str, port: int, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            try:
                sock.connect((host, port))
                return
            except OSError:
                time.sleep(0.2)
    raise AssertionError(f"Timed out waiting for {host}:{port}")


def _wait_for_postgres(ctx: dict[str, object], *, timeout: float = 30.0) -> None:
    dsn = f"postgresql://bot:bot@127.0.0.1:{ctx['postgres_port']}/bot"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=2) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
                return
        except Exception:
            time.sleep(0.5)
    raise AssertionError("Timed out waiting for Postgres readiness")


def _start_shared_runtime(
    ctx: dict[str, object],
    *,
    worker_scale: int,
    start_workers: bool = True,
) -> None:
    ctx["worker_scale"] = worker_scale
    if ctx["backend"] == "postgres":
        result = compose(ctx, "up", "-d", "postgres")
        if result.returncode != 0:
            fail_with_logs(ctx, "postgres-start-failed", "Failed to start Postgres", "postgres")
        _wait_for_postgres(ctx)
        result = compose(ctx, "--profile", "tools", "run", "--rm", "db-bootstrap", timeout=180)
        if result.returncode != 0:
            fail_with_logs(ctx, "db-bootstrap-failed", "db-bootstrap failed", "postgres")

    services = ["telegram-api-stub", "bot-webhook"]
    args = ["up", "-d"]
    if start_workers:
        args.extend(["--scale", f"bot-worker={worker_scale}"])
        services.append("bot-worker")
    result = compose(ctx, *args, *services, timeout=180)
    if result.returncode != 0:
        fail_with_logs(ctx, "shared-runtime-up-failed", "Failed to start Shared Runtime services", *services)
    _wait_for_port("127.0.0.1", int(ctx["webhook_port"]))


def _scale_workers(ctx: dict[str, object], worker_scale: int) -> None:
    ctx["worker_scale"] = worker_scale
    result = compose(ctx, "up", "-d", "--scale", f"bot-worker={worker_scale}", "bot-worker", timeout=180)
    if result.returncode != 0:
        fail_with_logs(ctx, "scale-workers-failed", f"Failed to scale bot-worker to {worker_scale}", "bot-worker")


def _worker_container_ids(ctx: dict[str, object]) -> list[str]:
    result = compose(ctx, "ps", "-q", "bot-worker")
    if result.returncode != 0:
        fail_with_logs(ctx, "worker-ps-failed", "Failed to list bot-worker containers", "bot-worker")
    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


def _service_container_id(ctx: dict[str, object], service: str) -> str | None:
    result = compose(ctx, "ps", "-q", service)
    if result.returncode != 0:
        fail_with_logs(ctx, f"{service}-ps-failed", f"Failed to list {service} containers", service)
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return lines[0] if lines else None


def _docker_cmd(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _post_telegram_update(
    webhook_port: int,
    *,
    chat_id: int,
    text: str,
    update_id: int,
    as_command: bool = False,
    timeout: float = 10.0,
) -> int:
    message: dict[str, object] = {
        "message_id": update_id,
        "from": {"id": 42, "is_bot": False, "first_name": "Test"},
        "chat": {"id": chat_id, "type": "private"},
        "date": int(time.time()),
        "text": text,
    }
    if as_command:
        message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    payload = {"update_id": update_id, "message": message}
    body = json.dumps(payload).encode("utf-8")
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        req = urllib_request.Request(
            f"http://127.0.0.1:{webhook_port}/webhook",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=5) as response:
                response.read()
                return int(response.status)
        except (urllib_error.URLError, http.client.RemoteDisconnected, TimeoutError, ConnectionResetError) as exc:
            last_error = exc
            time.sleep(0.2)
    raise AssertionError(f"Webhook POST did not succeed within {timeout}s: {last_error}")


def _query_sqlite(ctx: dict[str, object], sql: str, params: tuple[object, ...]) -> list[dict[str, object]]:
    container_id = _service_container_id(ctx, "bot-webhook")
    if not container_id:
        return []
    script = """
import json
import sqlite3
import sys

db_path, sql, raw_params = sys.argv[1], sys.argv[2], sys.argv[3]
params = tuple(json.loads(raw_params))
conn = sqlite3.connect(db_path, timeout=5.0)
conn.row_factory = sqlite3.Row
try:
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            print("[]")
            raise SystemExit(0)
        raise
    print(json.dumps([{key: row[key] for key in row.keys()} for row in rows], default=str))
finally:
    conn.close()
""".strip()
    result = _docker_cmd(
        "exec",
        container_id,
        "python",
        "-c",
        script,
        "/home/bot/data/transport.db",
        sql,
        json.dumps(list(params), default=str),
        timeout=30,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        if "No such container" in stderr:
            return []
        raise AssertionError(f"SQLite query failed: {stderr or result.stdout or result.returncode}")
    output = (result.stdout or "").strip()
    if not output:
        return []
    return json.loads(output)


def _query_postgres(ctx: dict[str, object], sql: str, params: tuple[object, ...]) -> list[dict[str, object]]:
    dsn = f"postgresql://bot:bot@127.0.0.1:{ctx['postgres_port']}/bot"
    with psycopg.connect(dsn, connect_timeout=2) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [dict(row) for row in rows]


def _query_items(ctx: dict[str, object], conversation_key: str) -> list[dict[str, object]]:
    sql = (
        "SELECT id, event_id, conversation_key, state, worker_id, claimed_at, created_at, completed_at, "
        "dispatch_mode, error, cancel_requested_at "
        "FROM {table} WHERE conversation_key = %s ORDER BY created_at ASC"
    )
    if ctx["backend"] == "sqlite":
        return _query_sqlite(
            ctx,
            sql.format(table="work_items").replace("%s", "?"),
            (conversation_key,),
        )
    return _query_postgres(
        ctx,
        sql.format(table="bot_runtime.work_items"),
        (conversation_key,),
    )


def _query_updates(ctx: dict[str, object], conversation_key: str) -> list[dict[str, object]]:
    sql = (
        "SELECT event_id, conversation_key, actor_key, kind, received_at "
        "FROM {table} WHERE conversation_key = %s ORDER BY received_at ASC"
    )
    if ctx["backend"] == "sqlite":
        return _query_sqlite(
            ctx,
            sql.format(table="updates").replace("%s", "?"),
            (conversation_key,),
        )
    return _query_postgres(
        ctx,
        sql.format(table="bot_runtime.updates"),
        (conversation_key,),
    )


def _query_claimed(ctx: dict[str, object]) -> list[dict[str, object]]:
    sql = (
        "SELECT id, event_id, conversation_key, state, worker_id, claimed_at, dispatch_mode "
        "FROM {table} WHERE state = 'claimed' ORDER BY claimed_at ASC"
    )
    if ctx["backend"] == "sqlite":
        return _query_sqlite(ctx, sql.format(table="work_items"), ())
    return _query_postgres(ctx, sql.format(table="bot_runtime.work_items"), ())


def _query_worker_heartbeats(ctx: dict[str, object]) -> list[dict[str, object]]:
    sql = (
        "SELECT worker_id, process_role, started_at, last_seen_at, current_item_id, "
        "current_conversation_key, current_kind, items_processed, stale_recoveries_seen, last_error "
        "FROM {table} ORDER BY worker_id ASC"
    )
    if ctx["backend"] == "sqlite":
        return _query_sqlite(ctx, sql.format(table="worker_heartbeats"), ())
    return _query_postgres(ctx, sql.format(table="bot_runtime.worker_heartbeats"), ())


def _wait_for_predicate(
    predicate,
    *,
    timeout: float = 30.0,
    interval: float = 0.2,
    on_timeout=None,
    description: str = "predicate",
):
    deadline = time.monotonic() + timeout
    last_value = None
    while time.monotonic() < deadline:
        last_value = predicate()
        if last_value:
            return last_value
        time.sleep(interval)
    if on_timeout is not None:
        on_timeout(last_value)
    raise AssertionError(f"Timed out waiting for {description}. Last value: {last_value!r}")


def _wait_for_items(
    ctx: dict[str, object],
    conversation_key: str,
    *,
    count: int,
    timeout: float = 15.0,
) -> list[dict[str, object]]:
    return _wait_for_predicate(
        lambda: (_query_items(ctx, conversation_key) if len(_query_items(ctx, conversation_key)) >= count else None),
        timeout=timeout,
        description=f"{count} work items for {conversation_key}",
    )


def _wait_for_terminal(
    ctx: dict[str, object],
    conversation_key: str,
    *,
    count: int = 1,
    timeout: float = 30.0,
    on_timeout=None,
) -> list[dict[str, object]]:
    def _terminal():
        items = _query_items(ctx, conversation_key)
        if len(items) < count:
            return None
        if all(item["state"] in {"done", "failed"} for item in items[:count]):
            return items
        return None

    return _wait_for_predicate(
        _terminal,
        timeout=timeout,
        on_timeout=on_timeout,
        description=f"terminal work items for {conversation_key}",
    )


def _wait_for_recovery_pending(
    ctx: dict[str, object],
    conversation_key: str,
    *,
    timeout: float = 20.0,
) -> dict[str, object]:
    def _pending():
        items = _query_items(ctx, conversation_key)
        for item in items:
            if item["state"] == "pending_recovery":
                return item
        return None

    return _wait_for_predicate(_pending, timeout=timeout, description=f"pending_recovery for {conversation_key}")


def _release_block(ctx: dict[str, object], key: str) -> None:
    container_id = _service_container_id(ctx, "bot-webhook")
    if not container_id:
        raise AssertionError("bot-webhook container not available for release marker")
    script = """
from pathlib import Path
import sys

path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text("release\\n", encoding="utf-8")
""".strip()
    result = _docker_cmd(
        "exec",
        container_id,
        "python",
        "-c",
        script,
        f"/home/bot/e2e-control/release/{key}",
        timeout=30,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"Failed to write release marker for {key}: {result.stderr or result.stdout or result.returncode}"
        )


def _log_services(ctx: dict[str, object]) -> list[str]:
    services = ["bot-webhook", "telegram-api-stub"]
    if ctx["worker_scale"]:
        services.append("bot-worker")
    if ctx["backend"] == "postgres":
        services.append("postgres")
    return services


def _capture_debug_artifacts(ctx: dict[str, object], name: str, conversations: list[str]) -> None:
    ps = compose(ctx, "ps", "-a")
    ps_path = Path(ctx["artifacts_dir"]) / f"{name}.compose-ps.log"
    ps_text = "\n".join(part for part in [ps.stdout, ps.stderr] if part).strip()
    ps_path.write_text(ps_text + ("\n" if ps_text else ""), encoding="utf-8")
    compose_logs(ctx, name, *_log_services(ctx))
    snapshot = {
        "backend": ctx["backend"],
        "claimed": _query_claimed(ctx),
        "worker_heartbeats": _query_worker_heartbeats(ctx),
        "updates": {key: _query_updates(ctx, key) for key in conversations},
        "conversations": {key: _query_items(ctx, key) for key in conversations},
    }
    snapshot_path = Path(ctx["artifacts_dir"]) / f"{name}.db-snapshot.json"
    snapshot_path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _assert_status_ok(status: int) -> None:
    assert status == 200, f"Expected webhook POST to return 200, got {status}"


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_shared_runtime_persists_before_worker_claims(backend, shared_runtime_env):
    ctx = shared_runtime_env
    chat_id = 6101
    conversation_key = telegram_conversation_key(chat_id)

    _start_shared_runtime(ctx, worker_scale=1, start_workers=False)
    _assert_status_ok(_post_telegram_update(int(ctx["webhook_port"]), chat_id=chat_id, text="persist-first", update_id=1001))

    updates = _wait_for_predicate(
        lambda: (_query_updates(ctx, conversation_key) or None),
        timeout=10.0,
        on_timeout=lambda _: _capture_debug_artifacts(ctx, "persist-before-claim", [conversation_key]),
        description=f"persisted update for {conversation_key}",
    )
    items = _wait_for_predicate(
        lambda: (_query_items(ctx, conversation_key) or None),
        timeout=10.0,
        on_timeout=lambda _: _capture_debug_artifacts(ctx, "persist-before-claim", [conversation_key]),
        description=f"persisted work item for {conversation_key}",
    )
    assert len(updates) == 1
    assert len(items) == 1
    assert items[0]["state"] == "queued"
    assert items[0]["dispatch_mode"] == "fresh"

    _scale_workers(ctx, 1)
    terminal = _wait_for_terminal(
        ctx,
        conversation_key,
        timeout=20.0,
        on_timeout=lambda _: _capture_debug_artifacts(ctx, "persist-terminal-timeout", [conversation_key]),
    )
    assert terminal[0]["state"] == "done"


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_shared_runtime_parallel_chats_claim_concurrently(backend, shared_runtime_env):
    ctx = shared_runtime_env
    _start_shared_runtime(ctx, worker_scale=2, start_workers=True)

    chat_a = 6201
    chat_b = 6202
    conv_a = telegram_conversation_key(chat_a)
    conv_b = telegram_conversation_key(chat_b)

    _assert_status_ok(_post_telegram_update(int(ctx["webhook_port"]), chat_id=chat_a, text="parallel A E2E_BLOCK:parallel-a", update_id=2001))
    _assert_status_ok(_post_telegram_update(int(ctx["webhook_port"]), chat_id=chat_b, text="parallel B E2E_BLOCK:parallel-b", update_id=2002))

    def _both_claimed():
        claimed = _query_claimed(ctx)
        matches = [row for row in claimed if row["conversation_key"] in {conv_a, conv_b}]
        if len(matches) < 2:
            return None
        worker_ids = {row["worker_id"] for row in matches}
        convs = {row["conversation_key"] for row in matches}
        if len(worker_ids) >= 2 and convs == {conv_a, conv_b}:
            return matches
        return None

    claimed = _wait_for_predicate(
        _both_claimed,
        timeout=20.0,
        on_timeout=lambda _: _capture_debug_artifacts(ctx, "parallel-claims", [conv_a, conv_b]),
        description="simultaneous cross-chat claims",
    )
    assert len({row["worker_id"] for row in claimed}) >= 2

    _release_block(ctx, "parallel-a")
    _release_block(ctx, "parallel-b")

    terminal_a = _wait_for_terminal(
        ctx,
        conv_a,
        timeout=20.0,
        on_timeout=lambda _: _capture_debug_artifacts(ctx, "parallel-terminal-a", [conv_a, conv_b]),
    )
    terminal_b = _wait_for_terminal(
        ctx,
        conv_b,
        timeout=20.0,
        on_timeout=lambda _: _capture_debug_artifacts(ctx, "parallel-terminal-b", [conv_a, conv_b]),
    )
    assert terminal_a[0]["state"] == "done"
    assert terminal_b[0]["state"] == "done"


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_shared_runtime_same_chat_serializes_claims(backend, shared_runtime_env):
    ctx = shared_runtime_env
    _start_shared_runtime(ctx, worker_scale=2, start_workers=True)

    chat_id = 6301
    conversation_key = telegram_conversation_key(chat_id)

    _assert_status_ok(_post_telegram_update(int(ctx["webhook_port"]), chat_id=chat_id, text="first E2E_BLOCK:serial-1", update_id=3001))
    _assert_status_ok(_post_telegram_update(int(ctx["webhook_port"]), chat_id=chat_id, text="second E2E_BLOCK:serial-2", update_id=3002))

    def _first_claimed_second_queued():
        items = _query_items(ctx, conversation_key)
        if len(items) < 2:
            return None
        first, second = items[0], items[1]
        if first["state"] == "claimed" and second["state"] == "queued":
            return items
        return None

    items = _wait_for_predicate(
        _first_claimed_second_queued,
        timeout=20.0,
        on_timeout=lambda _: _capture_debug_artifacts(ctx, "same-chat-serialization", [conversation_key]),
        description="first claimed while second queued",
    )
    first, second = items[0], items[1]
    assert first["state"] == "claimed"
    assert second["state"] == "queued"

    time.sleep(1.0)
    items = _query_items(ctx, conversation_key)
    assert items[0]["state"] == "claimed"
    assert items[1]["state"] == "queued"

    _release_block(ctx, "serial-1")

    def _second_claimed():
        current = _query_items(ctx, conversation_key)
        if len(current) < 2:
            return None
        if current[0]["state"] != "claimed" and current[1]["state"] == "claimed":
            return current
        return None

    _wait_for_predicate(
        _second_claimed,
        timeout=20.0,
        on_timeout=lambda _: _capture_debug_artifacts(ctx, "same-chat-second-claim", [conversation_key]),
        description="second item claimed after first leaves claimed",
    )

    _release_block(ctx, "serial-2")
    terminal = _wait_for_terminal(
        ctx,
        conversation_key,
        count=2,
        timeout=20.0,
        on_timeout=lambda _: _capture_debug_artifacts(ctx, "same-chat-terminal-timeout", [conversation_key]),
    )
    assert [row["state"] for row in terminal[:2]] == ["done", "done"]


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_shared_runtime_worker_crash_recovers_to_replay_notice(backend, shared_runtime_env):
    ctx = shared_runtime_env
    _set_runtime_tuning(ctx, lease_ttl=4.0, sweep_interval=1.0)
    _start_shared_runtime(ctx, worker_scale=1, start_workers=True)

    chat_id = 6401
    conversation_key = telegram_conversation_key(chat_id)
    _assert_status_ok(_post_telegram_update(int(ctx["webhook_port"]), chat_id=chat_id, text="crash E2E_BLOCK:crash-a", update_id=4001))

    claimed = _wait_for_predicate(
        lambda: next((row for row in _query_items(ctx, conversation_key) if row["state"] == "claimed"), None),
        timeout=15.0,
        on_timeout=lambda _: _capture_debug_artifacts(ctx, "crash-before-kill", [conversation_key]),
        description=f"claimed item for {conversation_key}",
    )
    worker_ids = _worker_container_ids(ctx)
    assert len(worker_ids) == 1
    killed = _docker_cmd("kill", worker_ids[0])
    assert killed.returncode == 0, (killed.stdout, killed.stderr)

    _scale_workers(ctx, 1)
    recovered = _wait_for_recovery_pending(ctx, conversation_key, timeout=20.0)
    assert recovered["dispatch_mode"] == "recovery"
    assert recovered["state"] == "pending_recovery"
    assert recovered["completed_at"] is None
    assert recovered["worker_id"] in {"", None} or recovered["worker_id"] != claimed["worker_id"]


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_shared_runtime_cancel_is_durable(backend, shared_runtime_env):
    ctx = shared_runtime_env
    _start_shared_runtime(ctx, worker_scale=1, start_workers=True)

    chat_id = 6501
    conversation_key = telegram_conversation_key(chat_id)
    _assert_status_ok(_post_telegram_update(int(ctx["webhook_port"]), chat_id=chat_id, text="cancel me E2E_BLOCK:cancel-a", update_id=5001))

    _wait_for_predicate(
        lambda: next((row for row in _query_items(ctx, conversation_key) if row["state"] == "claimed"), None),
        timeout=15.0,
        on_timeout=lambda _: _capture_debug_artifacts(ctx, "cancel-claim-timeout", [conversation_key]),
        description=f"claimed item for {conversation_key}",
    )

    _assert_status_ok(
        _post_telegram_update(
            int(ctx["webhook_port"]),
            chat_id=chat_id,
            text="/cancel",
            update_id=5002,
            as_command=True,
        )
    )

    cancelled = _wait_for_predicate(
        lambda: next((row for row in _query_items(ctx, conversation_key) if row["cancel_requested_at"]), None),
        timeout=10.0,
        on_timeout=lambda _: _capture_debug_artifacts(ctx, "cancel-request-timeout", [conversation_key]),
        description=f"durable cancel flag for {conversation_key}",
    )
    assert cancelled["cancel_requested_at"]

    terminal = _wait_for_terminal(
        ctx,
        conversation_key,
        timeout=20.0,
        on_timeout=lambda _: _capture_debug_artifacts(ctx, "cancel-terminal-timeout", [conversation_key]),
    )
    assert terminal[0]["state"] in {"done", "failed"}
    assert terminal[0]["cancel_requested_at"]


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_shared_runtime_worker_replacement_preserves_drain(backend, shared_runtime_env):
    ctx = shared_runtime_env
    _start_shared_runtime(ctx, worker_scale=2, start_workers=True)

    worker_ids = _worker_container_ids(ctx)
    assert len(worker_ids) == 2
    stopped = _docker_cmd("stop", worker_ids[0], timeout=90)
    assert stopped.returncode == 0, (stopped.stdout, stopped.stderr)

    chat_one = 6601
    conv_one = telegram_conversation_key(chat_one)
    _assert_status_ok(_post_telegram_update(int(ctx["webhook_port"]), chat_id=chat_one, text="drain after stop", update_id=6001))
    terminal_one = _wait_for_terminal(
        ctx,
        conv_one,
        timeout=20.0,
        on_timeout=lambda _: _capture_debug_artifacts(ctx, "worker-replacement-terminal-one", [conv_one]),
    )
    assert terminal_one[0]["state"] == "done"

    _scale_workers(ctx, 2)

    chat_two = 6602
    chat_three = 6603
    conv_two = telegram_conversation_key(chat_two)
    conv_three = telegram_conversation_key(chat_three)
    _assert_status_ok(_post_telegram_update(int(ctx["webhook_port"]), chat_id=chat_two, text="replace A E2E_BLOCK:replace-a", update_id=6002))
    _assert_status_ok(_post_telegram_update(int(ctx["webhook_port"]), chat_id=chat_three, text="replace B E2E_BLOCK:replace-b", update_id=6003))

    def _replacement_claims():
        claimed = _query_claimed(ctx)
        matches = [row for row in claimed if row["conversation_key"] in {conv_two, conv_three}]
        if len(matches) < 2:
            return None
        if len({row["worker_id"] for row in matches}) >= 2:
            return matches
        return None

    claims = _wait_for_predicate(
        _replacement_claims,
        timeout=20.0,
        on_timeout=lambda _: _capture_debug_artifacts(ctx, "worker-replacement-claims", [conv_two, conv_three]),
        description="distinct worker claims after replacement",
    )
    assert len({row["worker_id"] for row in claims}) >= 2

    _release_block(ctx, "replace-a")
    _release_block(ctx, "replace-b")
    assert _wait_for_terminal(
        ctx,
        conv_two,
        timeout=20.0,
        on_timeout=lambda _: _capture_debug_artifacts(ctx, "worker-replacement-terminal-two", [conv_two, conv_three]),
    )[0]["state"] == "done"
    assert _wait_for_terminal(
        ctx,
        conv_three,
        timeout=20.0,
        on_timeout=lambda _: _capture_debug_artifacts(ctx, "worker-replacement-terminal-three", [conv_two, conv_three]),
    )[0]["state"] == "done"
