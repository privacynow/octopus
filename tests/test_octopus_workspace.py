from __future__ import annotations

import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def _run_bash(script: str, *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-lc", script],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


def _source_octopus(tmp_path: Path) -> str:
    return f"""
set -euo pipefail
cd "{tmp_path}"
export OCTOPUS_SOURCE_ONLY=1
source "{REPO}/octopus"
cd "{tmp_path}"
"""


# -- workspace create --


def test_workspace_create(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
cat .deploy/workspaces/myproject/workspace.conf
cat .deploy/workspaces/myproject/members.txt
"""
    result = _run_bash(script, cwd=tmp_path)
    assert 'Workspace "myproject" created.' in result.stdout
    assert f"WORKSPACE_ROOT={host_dir}" in result.stdout
    assert "WORKSPACE_MOUNT=/workspace/myproject" in result.stdout
    assert "WORKSPACE_MODE=rw" in result.stdout


def test_workspace_create_rejects_duplicate(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
if workspace_create myproject "{host_dir}"; then
  exit 1
fi
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "already exists" in result.stderr


def test_workspace_create_rejects_relative_path(tmp_path: Path) -> None:
    script = _source_octopus(tmp_path) + """
if workspace_create myproject "relative/path"; then
  exit 1
fi
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "absolute" in result.stderr


def test_workspace_create_rejects_nonexistent_path(tmp_path: Path) -> None:
    script = _source_octopus(tmp_path) + """
if workspace_create myproject "/nonexistent/path/xyz"; then
  exit 1
fi
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "does not exist" in result.stderr


def test_workspace_create_rejects_invalid_slug(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    script = _source_octopus(tmp_path) + f"""
if workspace_create "MY PROJECT" "{host_dir}"; then
  exit 1
fi
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "lowercase slug" in result.stderr


# -- workspace remove --


def test_workspace_remove(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
workspace_remove myproject
ls .deploy/workspaces/ 2>&1 || true
"""
    result = _run_bash(script, cwd=tmp_path)
    assert 'Workspace "myproject" removed.' in result.stdout


def test_workspace_remove_nonexistent(tmp_path: Path) -> None:
    script = _source_octopus(tmp_path) + """
if workspace_remove nonexistent; then
  exit 1
fi
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "does not exist" in result.stderr


# -- workspace add-bot / remove-bot --


def _setup_bot_env(tmp_path: Path, slug: str = "example-bot") -> None:
    bot_dir = tmp_path / ".deploy" / "bots" / slug
    bot_dir.mkdir(parents=True, exist_ok=True)
    (bot_dir / ".env").write_text(
        f"BOT_SLUG={slug}\n"
        f"BOT_PROVIDER=claude\n"
        f"BOT_TELEGRAM_USERNAME={slug.replace('-', '_')}\n"
    )


def test_workspace_add_bot(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    _setup_bot_env(tmp_path)
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
workspace_add_bot myproject example-bot
cat .deploy/workspaces/myproject/members.txt
"""
    result = _run_bash(script, cwd=tmp_path)
    assert 'Added "example-bot" to workspace "myproject".' in result.stdout
    assert "example-bot" in result.stdout


def test_workspace_add_bot_idempotent(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    _setup_bot_env(tmp_path)
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
workspace_add_bot myproject example-bot
workspace_add_bot myproject example-bot
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "already a member" in result.stdout


def test_workspace_add_bot_rejects_unknown_bot(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
if workspace_add_bot myproject nonexistent-bot; then
  exit 1
fi
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "not configured" in result.stderr


def test_workspace_remove_bot(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    _setup_bot_env(tmp_path)
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
workspace_add_bot myproject example-bot
workspace_remove_bot myproject example-bot
cat .deploy/workspaces/myproject/members.txt
"""
    result = _run_bash(script, cwd=tmp_path)
    assert 'Removed "example-bot" from workspace "myproject".' in result.stdout


def test_workspace_remove_bot_idempotent(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    _setup_bot_env(tmp_path)
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
workspace_remove_bot myproject example-bot
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "not a member" in result.stdout


# -- workspace status --


def test_workspace_status_empty(tmp_path: Path) -> None:
    script = _source_octopus(tmp_path) + """
workspace_status
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "No workspaces configured." in result.stdout


def test_workspace_status_with_members(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    _setup_bot_env(tmp_path)
    script = _source_octopus(tmp_path) + f"""
bot_is_running() {{ return 1; }}
workspace_create myproject "{host_dir}"
workspace_add_bot myproject example-bot
workspace_status
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "myproject" in result.stdout
    assert "example-bot" in result.stdout
    assert "myproject:/workspace/myproject|edit" in result.stdout


# -- workspace.env generation --


def test_regenerate_creates_workspace_env(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    _setup_bot_env(tmp_path)
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
workspace_add_bot myproject example-bot
cat .deploy/bots/example-bot/workspace.env
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "BOT_PROJECTS=myproject:/workspace/myproject|edit" in result.stdout
    assert "BOT_AGENT_TAGS=workspace:myproject" in result.stdout


def test_regenerate_creates_compose_override(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    _setup_bot_env(tmp_path)
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
workspace_add_bot myproject example-bot
cat .deploy/bots/example-bot/docker-compose.workspace.yml
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "env_file:" in result.stdout
    assert "workspace.env" in result.stdout
    assert f"{host_dir}:/workspace/myproject:rw" in result.stdout
    # All four services present
    assert "bot:" in result.stdout
    assert "bot-provider:" in result.stdout
    assert "bot-webhook:" in result.stdout
    assert "bot-worker:" in result.stdout


def test_regenerate_ro_workspace_uses_inspect(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    _setup_bot_env(tmp_path)
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
# Override mode to ro
printf 'WORKSPACE_ROOT={host_dir}\nWORKSPACE_MOUNT=/workspace/myproject\nWORKSPACE_MODE=ro\n' > .deploy/workspaces/myproject/workspace.conf
workspace_add_bot myproject example-bot
cat .deploy/bots/example-bot/workspace.env
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "myproject:/workspace/myproject|inspect" in result.stdout


def test_regenerate_merges_existing_projects(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    bot_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    bot_dir.mkdir(parents=True, exist_ok=True)
    (bot_dir / ".env").write_text(
        "BOT_SLUG=example-bot\n"
        "BOT_PROVIDER=claude\n"
        "BOT_PROJECTS=existing:/some/path|edit\n"
    )
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
workspace_add_bot myproject example-bot
cat .deploy/bots/example-bot/workspace.env
"""
    result = _run_bash(script, cwd=tmp_path)
    # Both workspace and existing project present
    assert "myproject:/workspace/myproject|edit" in result.stdout
    assert "existing:/some/path|edit" in result.stdout


def test_regenerate_workspace_wins_on_name_collision(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    bot_dir = tmp_path / ".deploy" / "bots" / "example-bot"
    bot_dir.mkdir(parents=True, exist_ok=True)
    (bot_dir / ".env").write_text(
        "BOT_SLUG=example-bot\n"
        "BOT_PROVIDER=claude\n"
        "BOT_PROJECTS=myproject:/old/path|inspect\n"
    )
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
workspace_add_bot myproject example-bot
cat .deploy/bots/example-bot/workspace.env
"""
    result = _run_bash(script, cwd=tmp_path)
    # Workspace entry wins — old path should not appear
    assert "myproject:/workspace/myproject|edit" in result.stdout
    assert "/old/path" not in result.stdout


def test_regenerate_multiple_workspaces(tmp_path: Path) -> None:
    dir1 = tmp_path / "proj1"
    dir2 = tmp_path / "proj2"
    dir1.mkdir()
    dir2.mkdir()
    _setup_bot_env(tmp_path)
    script = _source_octopus(tmp_path) + f"""
workspace_create proj1 "{dir1}"
workspace_create proj2 "{dir2}"
workspace_add_bot proj1 example-bot
workspace_add_bot proj2 example-bot
cat .deploy/bots/example-bot/workspace.env
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "proj1:/workspace/proj1|edit" in result.stdout
    assert "proj2:/workspace/proj2|edit" in result.stdout
    assert "workspace:proj1" in result.stdout
    assert "workspace:proj2" in result.stdout


def test_regenerate_removes_files_when_no_workspaces(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    _setup_bot_env(tmp_path)
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
workspace_add_bot myproject example-bot
test -f .deploy/bots/example-bot/workspace.env && echo "ws_env_exists"
workspace_remove_bot myproject example-bot
test -f .deploy/bots/example-bot/workspace.env && echo "ws_env_still_exists" || echo "ws_env_removed"
test -f .deploy/bots/example-bot/docker-compose.workspace.yml && echo "compose_still_exists" || echo "compose_removed"
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "ws_env_exists" in result.stdout
    assert "ws_env_removed" in result.stdout
    assert "compose_removed" in result.stdout


# -- workspace remove regenerates for former members --


def test_workspace_remove_regenerates_for_members(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    _setup_bot_env(tmp_path)
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
workspace_add_bot myproject example-bot
test -f .deploy/bots/example-bot/workspace.env && echo "before_remove_exists"
workspace_remove myproject
test -f .deploy/bots/example-bot/workspace.env && echo "after_remove_exists" || echo "after_remove_gone"
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "before_remove_exists" in result.stdout
    assert "after_remove_gone" in result.stdout


# -- workspace verify --


def test_workspace_verify_valid(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    _setup_bot_env(tmp_path)
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
workspace_add_bot myproject example-bot
workspace_verify myproject
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "OK:" in result.stdout


def test_workspace_verify_missing_host_path(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    _setup_bot_env(tmp_path)
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
workspace_add_bot myproject example-bot
rm -rf "{host_dir}"
if workspace_verify myproject; then
  exit 1
fi
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "FAIL:" in result.stdout
    assert "does not exist" in result.stdout


def test_workspace_verify_warns_about_secrets(tmp_path: Path) -> None:
    host_dir = tmp_path / "project"
    host_dir.mkdir()
    (host_dir / ".env").write_text("SECRET=value\n")
    _setup_bot_env(tmp_path)
    script = _source_octopus(tmp_path) + f"""
workspace_create myproject "{host_dir}"
workspace_add_bot myproject example-bot
workspace_verify myproject
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "WARN:" in result.stdout
    assert ".env" in result.stdout


# -- BOT_PROJECTS round-trip through _parse_projects --


def test_generated_projects_roundtrip():
    """Verify generated BOT_PROJECTS line parses via app/config.py."""
    import importlib
    config = importlib.import_module("app.config")
    result = config._parse_projects("myproject:/workspace/myproject|edit")
    assert len(result) == 1
    assert result[0].name == "myproject"
    assert result[0].root_dir == "/workspace/myproject"
    assert result[0].file_policy == "edit"


def test_generated_projects_roundtrip_ro():
    import importlib
    config = importlib.import_module("app.config")
    result = config._parse_projects("docs:/workspace/docs|inspect")
    assert len(result) == 1
    assert result[0].name == "docs"
    assert result[0].file_policy == "inspect"


def test_generated_projects_roundtrip_multiple():
    import importlib
    config = importlib.import_module("app.config")
    result = config._parse_projects(
        "proj1:/workspace/proj1|edit,proj2:/workspace/proj2|inspect,existing:/some/path|edit"
    )
    assert len(result) == 3
    names = {p.name for p in result}
    assert names == {"proj1", "proj2", "existing"}


# -- cmd_workspace routing --


def test_cmd_workspace_routes_to_status(tmp_path: Path) -> None:
    script = _source_octopus(tmp_path) + """
cmd_workspace status
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "No workspaces configured." in result.stdout


def test_cmd_workspace_no_args_shows_status(tmp_path: Path) -> None:
    script = _source_octopus(tmp_path) + """
cmd_workspace
"""
    result = _run_bash(script, cwd=tmp_path)
    assert "No workspaces configured." in result.stdout
