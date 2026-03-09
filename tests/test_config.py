"""Tests for config.py — env parsing, validation."""

import os
import sys
import tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from pathlib import Path
from app.config import load_dotenv_file, parse_allowed_users, validate_config
from tests.support.assertions import Checks
from tests.support.config_support import make_config

checks = Checks()
check = checks.check


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
errors = validate_config(
    make_config(
        telegram_token="fake-token",
        allow_open=False,
        allowed_user_ids=frozenset({123}),
        working_dir=Path.home(),
        data_dir=Path("/tmp/test-agent-bot"),
    )
)
# May have "claude not found" if not installed, that's ok
token_errors = [e for e in errors if "TOKEN" in e]
check("valid config no token error", token_errors, [])

errors2 = validate_config(
    make_config(
        telegram_token="",
        allow_open=False,
        allowed_user_ids=frozenset({123}),
        working_dir=Path.home(),
        data_dir=Path("/tmp/test-agent-bot"),
    )
)
check("missing token", any("TOKEN" in e for e in errors2), True)

errors3 = validate_config(
    make_config(
        telegram_token="fake-token",
        allow_open=False,
        allowed_user_ids=frozenset({123}),
        provider_name="invalid",
        working_dir=Path.home(),
        data_dir=Path("/tmp/test-agent-bot"),
    )
)
check("bad provider", any("BOT_PROVIDER" in e for e in errors3), True)

errors4 = validate_config(
    make_config(
        telegram_token="fake-token",
        allowed_user_ids=frozenset(),
        allow_open=False,
        working_dir=Path.home(),
        data_dir=Path("/tmp/test-agent-bot"),
    )
)
check("no users no open", any("BOT_ALLOWED_USERS" in e for e in errors4), True)

errors5 = validate_config(
    make_config(
        telegram_token="fake-token",
        allowed_user_ids=frozenset(),
        allow_open=True,
        working_dir=Path.home(),
        data_dir=Path("/tmp/test-agent-bot"),
    )
)
check("open access ok", [e for e in errors5 if "ALLOWED" in e], [])

errors6 = validate_config(
    make_config(
        telegram_token="fake-token",
        allow_open=False,
        allowed_user_ids=frozenset({123}),
        working_dir=Path.home(),
        data_dir=Path("/tmp/test-agent-bot"),
        codex_full_auto=True,
        codex_dangerous=True,
    )
)
check("codex mutual exclusion", any("CODEX_FULL_AUTO" in e for e in errors6), True)


# -- BOT_SKILLS validation --
print("\n=== BOT_SKILLS validation ===")

errors_bad_skill = validate_config(make_config(default_skills=("nonexistent-skill-xyz",), provider_name="claude"))
check("reports unknown skill", len([e for e in errors_bad_skill if "nonexistent-skill-xyz" in e]) > 0, True)

errors_good_skill = validate_config(make_config(default_skills=("github-integration",), provider_name="claude"))
check("valid skill no error", len([e for e in errors_good_skill if "BOT_SKILLS" in e and "github-integration" in e]), 0)

errors_no_skills = validate_config(make_config(default_skills=(), provider_name="claude"))
check("no skills no error", len([e for e in errors_no_skills if "BOT_SKILLS" in e]), 0)


# -- Summary --
print(f"\n{'='*40}")
print(f"  {checks.passed} passed, {checks.failed} failed")
print(f"{'='*40}")
sys.exit(1 if checks.failed else 0)
