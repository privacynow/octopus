"""Tests for config.py — env parsing, validation."""

import os
import sys
import tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from pathlib import Path
from app.config import load_dotenv_file, parse_allowed_users, validate_config, BotConfig

passed = 0
failed = 0


def check(name, got, expected):
    global passed, failed
    if got == expected:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name}")
        print(f"    expected: {expected!r}")
        print(f"    got:      {got!r}")
        failed += 1


# -- load_dotenv_file --
print("\n=== load_dotenv_file ===")
with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
    f.write("KEY1=value1\n")
    f.write("KEY2='quoted'\n")
    f.write('KEY3="double"\n')
    f.write("# comment\n")
    f.write("\n")
    f.write("KEY4=has=equals\n")
    f.name
result = load_dotenv_file(Path(f.name))
check("simple value", result.get("KEY1"), "value1")
check("single quoted", result.get("KEY2"), "quoted")
check("double quoted", result.get("KEY3"), "double")
check("comment skipped", "comment" in result, False)
check("equals in value", result.get("KEY4"), "has=equals")
os.unlink(f.name)

check("missing file", load_dotenv_file(Path("/nonexistent/.env")), {})

# -- parse_allowed_users --
print("\n=== parse_allowed_users ===")
ids, names = parse_allowed_users("123,456,@alice,bob")
check("numeric ids", ids, {123, 456})
check("usernames", names, {"alice", "bob"})

ids2, names2 = parse_allowed_users("")
check("empty string", (ids2, names2), (set(), set()))

ids3, names3 = parse_allowed_users("  , ,")
check("only commas", (ids3, names3), (set(), set()))

# -- validate_config --
print("\n=== validate_config ===")


def make_config(**overrides):
    defaults = dict(
        instance="test",
        telegram_token="fake-token",
        allow_open=False,
        allowed_user_ids=frozenset({123}),
        allowed_usernames=frozenset(),
        provider_name="claude",
        model="",
        working_dir=Path.home(),
        extra_dirs=(),
        data_dir=Path("/tmp/test-agent-bot"),
        timeout_seconds=300,
        approval_mode="on", role="", role_from_file=False, default_skills=(),
        stream_update_interval_seconds=1.0,
        typing_interval_seconds=4.0,
        codex_sandbox="workspace-write",
        codex_skip_git_repo_check=True,
        codex_full_auto=False,
        codex_dangerous=False,
        codex_profile="",
        admin_user_ids=frozenset(), admin_usernames=frozenset(),
        compact_mode=False, summary_model="claude-haiku-4-5-20251001",
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


errors = validate_config(make_config())
# May have "claude not found" if not installed, that's ok
token_errors = [e for e in errors if "TOKEN" in e]
check("valid config no token error", token_errors, [])

errors2 = validate_config(make_config(telegram_token=""))
check("missing token", any("TOKEN" in e for e in errors2), True)

errors3 = validate_config(make_config(provider_name="invalid"))
check("bad provider", any("BOT_PROVIDER" in e for e in errors3), True)

errors4 = validate_config(make_config(allowed_user_ids=frozenset(), allow_open=False))
check("no users no open", any("BOT_ALLOWED_USERS" in e for e in errors4), True)

errors5 = validate_config(make_config(allowed_user_ids=frozenset(), allow_open=True))
check("open access ok", [e for e in errors5 if "ALLOWED" in e], [])

errors6 = validate_config(make_config(codex_full_auto=True, codex_dangerous=True))
check("codex mutual exclusion", any("CODEX_FULL_AUTO" in e for e in errors6), True)

# -- Summary --
print(f"\n{'='*40}")
print(f"  {passed} passed, {failed} failed")
print(f"{'='*40}")
sys.exit(1 if failed else 0)
