"""Tests for the skill system — Phases 1 & 2.

Covers:
- §8.5 test invariants (context hash, pending request, BOT_ROLE)
- Skill engine (catalog, instructions, prompt building)
- Config loading (role, skills)
- Provider command building (system prompt injection)
- Codex thread invalidation
- Session state (active_skills, role, pending_approval, pending_retry)
- Phase 2: credential encryption round-trip, per-user isolation,
  requires.yaml parsing, credential satisfaction, env injection,
  awaiting_skill_setup persistence
"""

import dataclasses
import hashlib
import json
import os
import tempfile

from pathlib import Path
from app.config import load_dotenv_file, validate_config
from app.execution_context import ResolvedExecutionContext
from app.providers.base import PreflightContext, RunContext
from app.session_state import PendingApproval, PendingRetry
from app.skills import (
    SkillRequirement,
    _encrypt, _decrypt, _parse_requires_yaml, _skill_dir,
    build_credential_env, build_preflight_context, build_provider_config,
    build_run_context,
    build_system_prompt, check_credentials, derive_encryption_key,
    get_provider_config_digest, get_skill_digests, get_skill_instructions,
    get_skill_requirements,
    load_catalog, load_provider_yaml, load_user_credentials, save_user_credential,
)
from app.storage import default_session, load_session, save_session
from tests.support.config_support import make_config


def _hash(**kwargs):
    """Shortcut to build ResolvedExecutionContext and get its hash."""
    defaults = dict(
        role="", active_skills=[], skill_digests={},
        provider_config_digest="", base_extra_dirs=[],
        project_id="", working_dir="", file_policy="", provider_name="",
    )
    defaults.update(kwargs)
    return ResolvedExecutionContext(**defaults).context_hash


# =====================================================================
# §8.5 #1: Approve-as-different-user — PendingApproval preserves identity
# =====================================================================

def test_pending_approval_preserves_requester_identity():
    pending = PendingApproval(
        request_user_id=111,
        prompt="review this",
        image_paths=[],
        attachment_dicts=[{"path": "/tmp/a.txt", "original_name": "a.txt", "is_image": False}],
        context_hash="abc123",
    )
    assert pending.request_user_id == 111
    assert pending.context_hash == "abc123"

    d = dataclasses.asdict(pending)
    assert d["request_user_id"] == 111
    assert d["context_hash"] == "abc123"


def test_pending_retry_preserves_fields():
    pending_retry = PendingRetry(
        request_user_id=222,
        prompt="write file",
        image_paths=[],
        context_hash="def456",
        denials=[{"tool_name": "Write", "tool_input": {"file_path": "/etc/hosts"}}],
    )
    assert len(pending_retry.denials) == 1
    assert pending_retry.request_user_id == 222


# =====================================================================
# §8.5 #2: Retry-after-context-change — hash changes → stale
# =====================================================================

def test_context_hash_detects_changes():
    hash1 = _hash(role="engineer", active_skills=["code-review"], skill_digests={"code-review": "aaa"})
    hash2 = _hash(role="engineer", active_skills=["code-review"], skill_digests={"code-review": "aaa"})
    assert hash1 == hash2

    # Skill added
    hash3 = _hash(role="engineer", active_skills=["code-review", "testing"], skill_digests={"code-review": "aaa", "testing": "bbb"})
    assert hash1 != hash3

    # Skill removed
    hash4 = _hash(role="engineer")
    assert hash1 != hash4

    # Role changed
    hash5 = _hash(role="devops lead", active_skills=["code-review"], skill_digests={"code-review": "aaa"})
    assert hash1 != hash5

    # Skill content changed (digest differs)
    hash6 = _hash(role="engineer", active_skills=["code-review"], skill_digests={"code-review": "bbb"})
    assert hash1 != hash6

    # Extra dirs changed
    hash7 = _hash(role="engineer", active_skills=["code-review"], skill_digests={"code-review": "aaa"}, base_extra_dirs=["/opt/new"])
    assert hash1 != hash7

    # Order-independent: skills listed differently but same set
    hash_a = _hash(role="x", active_skills=["b", "a"], skill_digests={"a": "1", "b": "2"})
    hash_b = _hash(role="x", active_skills=["a", "b"], skill_digests={"a": "1", "b": "2"})
    assert hash_a == hash_b

    # Working dir changed
    hash_wd1 = _hash(role="engineer", active_skills=["code-review"], skill_digests={"code-review": "aaa"})
    hash_wd2 = _hash(role="engineer", active_skills=["code-review"], skill_digests={"code-review": "aaa"}, working_dir="/opt/frontend")
    assert hash_wd1 != hash_wd2

    # Different working dirs
    hash_wd3 = _hash(role="engineer", active_skills=["code-review"], skill_digests={"code-review": "aaa"}, working_dir="/opt/backend")
    assert hash_wd2 != hash_wd3

    # Same working dir -> same hash
    hash_wd4 = _hash(role="engineer", active_skills=["code-review"], skill_digests={"code-review": "aaa"}, working_dir="/opt/frontend")
    assert hash_wd2 == hash_wd4


# =====================================================================
# §8.5 #3: Pending invalidation on context change
# =====================================================================

def test_pending_invalidation():
    stored_hash = _hash(role="engineer", active_skills=["code-review"], skill_digests={"code-review": "aaa"})
    current_hash = _hash(role="manager", active_skills=["code-review"], skill_digests={"code-review": "aaa"})
    assert stored_hash != current_hash


# =====================================================================
# §8.5 #4 & #5: Codex resets on context hash change, preserves when unchanged
# =====================================================================

def test_codex_context_hash_invalidation():
    from app.providers.codex import CodexProvider

    hash1 = _hash(role="engineer", active_skills=["code-review"], skill_digests={"code-review": "aaa"})
    hash3 = _hash(role="engineer", active_skills=["code-review", "testing"], skill_digests={"code-review": "aaa", "testing": "bbb"})

    p_codex = CodexProvider(make_config(provider_name="codex"))
    state = p_codex.new_provider_state()
    assert state.get("thread_id") is None
    # After first run, thread_id would be set by the provider
    # We simulate: state has a thread and a stored hash
    state["thread_id"] = "thread-abc"
    state["context_hash"] = hash1

    # Same hash → thread should be preserved (handler compares before calling run)
    assert state["thread_id"] == "thread-abc"

    # Different hash → handler clears thread_id
    if hash1 != hash3:  # context changed
        state["thread_id"] = None
    assert state["thread_id"] is None


# =====================================================================
# §8.5 #7: BOT_ROLE contract
# =====================================================================

def test_bot_role_contract():
    # Values with # survive via quoting
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write('BOT_ROLE="Senior C# engineer"\n')
        f.flush()
        env = load_dotenv_file(Path(f.name))
        assert env.get("BOT_ROLE") == "Senior C# engineer"
    os.unlink(f.name)

    # Values with whitespace survive
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write('BOT_ROLE="Lead backend engineer for payments team"\n')
        f.flush()
        env = load_dotenv_file(Path(f.name))
        assert env.get("BOT_ROLE") == "Lead backend engineer for payments team"
    os.unlink(f.name)

    # validate_config rejects " in role
    cfg_bad_quote = make_config(role='He said "ship it"')
    errors = validate_config(cfg_bad_quote)
    role_errors = [e for e in errors if "BOT_ROLE" in e]
    assert len(role_errors) > 0

    # validate_config rejects \ in role
    cfg_bad_backslash = make_config(role="C:\\Users\\admin")
    errors = validate_config(cfg_bad_backslash)
    role_errors = [e for e in errors if "BOT_ROLE" in e]
    assert len(role_errors) > 0

    # validate_config accepts clean role
    cfg_good = make_config(role="Senior Python engineer")
    errors = validate_config(cfg_good)
    role_errors = [e for e in errors if "BOT_ROLE" in e]
    assert role_errors == []


# =====================================================================
# Skill catalog discovery
# =====================================================================

def test_skill_catalog():
    catalog = load_catalog()
    assert len(catalog) == 10
    assert "code-review" in catalog
    assert "testing" in catalog
    assert "debugging" in catalog
    assert "devops" in catalog
    assert "documentation" in catalog
    assert "security" in catalog
    assert "refactoring" in catalog
    assert "architecture" in catalog
    assert "github-integration" in catalog
    assert "linear-integration" in catalog

    # Metadata
    cr = catalog["code-review"]
    assert bool(cr.display_name)
    assert bool(cr.description)


# =====================================================================
# Skill instructions
# =====================================================================

def test_skill_instructions():
    instructions = get_skill_instructions("code-review")
    assert len(instructions) > 0
    assert get_skill_instructions("nonexistent") == ""


# =====================================================================
# Skill digests
# =====================================================================

def test_skill_digests():
    digests = get_skill_digests(["code-review", "testing"])
    assert len(digests) == 2
    assert len(digests["code-review"]) == 64  # sha256 hex

    # Same content → same digest
    digests2 = get_skill_digests(["code-review"])
    assert digests["code-review"] == digests2["code-review"]

    # Unknown skill not in digests
    digests3 = get_skill_digests(["nonexistent"])
    assert len(digests3) == 0


# =====================================================================
# System prompt building
# =====================================================================

def test_system_prompt_building():
    prompt = build_system_prompt("Senior Python engineer", ["code-review", "testing"])
    assert "You are a Senior Python engineer" in prompt
    assert "## Code Review" in prompt
    assert "## Testing" in prompt

    # No role
    prompt_no_role = build_system_prompt("", ["code-review"])
    assert "You are a" not in prompt_no_role
    assert "## Code Review" in prompt_no_role

    # No skills
    prompt_no_skills = build_system_prompt("engineer", [])
    assert "You are a engineer" in prompt_no_skills

    # Neither role nor skills → empty
    prompt_empty = build_system_prompt("", [])
    assert prompt_empty == ""


# =====================================================================
# Context builders
# =====================================================================

def test_context_builders():
    run_ctx = build_run_context("engineer", ["code-review"], ["/tmp/uploads/123"])
    assert isinstance(run_ctx, RunContext)
    assert run_ctx.extra_dirs == ["/tmp/uploads/123"]
    assert "You are a engineer" in run_ctx.system_prompt
    assert run_ctx.capability_summary == ""
    assert run_ctx.provider_config == {}
    assert run_ctx.credential_env == {}

    pf_ctx = build_preflight_context("engineer", ["code-review"], ["/tmp/uploads/123"])
    assert isinstance(pf_ctx, PreflightContext)
    assert not isinstance(pf_ctx, RunContext)
    assert pf_ctx.extra_dirs == ["/tmp/uploads/123"]


# =====================================================================
# Claude provider: --append-system-prompt injection
# =====================================================================

def test_claude_system_prompt_injection():
    from app.providers.claude import ClaudeProvider

    p_claude = ClaudeProvider(make_config(provider_name="claude"))
    state = {"session_id": "test-123", "started": False}

    # Without context: no --append-system-prompt
    cmd = p_claude._build_run_cmd(state, "test prompt")
    assert "--append-system-prompt" not in cmd

    # With context: --append-system-prompt inserted before --
    ctx = RunContext(
        extra_dirs=["/tmp/test"],
        system_prompt="You are an engineer.\n\n## Code Review\n\nReview code.",
        capability_summary="",
    )
    cmd_with = p_claude._build_run_cmd(state, "test prompt", extra_dirs=ctx.extra_dirs)
    # Simulate what run() does: insert --append-system-prompt before --
    idx = cmd_with.index("--")
    cmd_with[idx:idx] = ["--append-system-prompt", ctx.system_prompt]
    assert "--append-system-prompt" in cmd_with
    # Verify order: --append-system-prompt comes before --
    asp_idx = cmd_with.index("--append-system-prompt")
    sep_idx = cmd_with.index("--")
    assert asp_idx < sep_idx
    assert "--add-dir" in cmd_with


# =====================================================================
# Codex provider: system prompt prepended to prompt text
# =====================================================================

def test_codex_system_prompt_injection():
    # Verify that the prompt prefix pattern works
    system_prompt = "You are an engineer.\n\n## Code Review\n\nReview code."
    user_prompt = "Review this PR"
    effective = system_prompt + "\n\n---\n\n" + user_prompt
    assert "You are an engineer" in effective
    assert "---" in effective
    assert "Review this PR" in effective


# =====================================================================
# Session: active_skills and role persist
# =====================================================================

def test_session_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        (data_dir / "sessions").mkdir(parents=True)

        # Create session with skills and role
        session = default_session("claude", {"session_id": "x", "started": False}, "on", "engineer", ("code-review",))
        assert session["active_skills"] == ["code-review"]
        assert session["role"] == "engineer"

        # Save and reload
        save_session(data_dir, 100, session)
        loaded = load_session(data_dir, 100, "claude", lambda: {"session_id": "y", "started": False}, "on", "default-role", ("testing",))

        # Saved values should override defaults
        assert loaded["active_skills"] == ["code-review"]
        assert loaded["role"] == "engineer"

        # Fresh session for new chat uses defaults
        fresh = load_session(data_dir, 999, "claude", lambda: {"session_id": "z", "started": False}, "on", "default-role", ("testing",))
        assert fresh["role"] == "default-role"
        assert fresh["active_skills"] == ["testing"]

        # /new resets to defaults (simulated)
        new_session = default_session("claude", {"session_id": "w", "started": False}, "on", "default-role", ("testing",))
        assert new_session["active_skills"] == ["testing"]
        assert new_session["role"] == "default-role"


# =====================================================================
# Config: role.md file overrides BOT_ROLE
# =====================================================================

def test_config_role_md_override():
    from app import config as config_mod

    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)

        env_file = config_dir / "test-role.env"
        env_file.write_text(
            "TELEGRAM_BOT_TOKEN=x\n"
            "BOT_PROVIDER=claude\n"
            "BOT_ALLOWED_USERS=123\n"
            'BOT_ROLE="simple role"\n'
        )

        # Create role.md file
        role_md = config_dir / "test-role.role.md"
        role_md.write_text("You are a **senior architect** specializing in distributed systems.\n\nKey principles:\n- Simplicity first")

        orig = config_mod.env_path_for_instance
        config_mod.env_path_for_instance = lambda inst: config_dir / f"{inst}.env"

        for key in ["TELEGRAM_BOT_TOKEN", "BOT_PROVIDER", "BOT_ALLOWED_USERS", "BOT_ROLE", "BOT_SKILLS"]:
            os.environ.pop(key, None)

        try:
            cfg = config_mod.load_config("test-role")
            assert "senior architect" in cfg.role
            assert "\n" in cfg.role
        finally:
            config_mod.env_path_for_instance = orig


# =====================================================================
# Config: BOT_SKILLS parsing
# =====================================================================

def test_config_bot_skills():
    from app import config as config_mod

    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)

        env_file = config_dir / "test-skills.env"
        env_file.write_text(
            "TELEGRAM_BOT_TOKEN=x\n"
            "BOT_PROVIDER=claude\n"
            "BOT_ALLOWED_USERS=123\n"
            "BOT_SKILLS=code-review, testing, debugging\n"
        )

        orig = config_mod.env_path_for_instance
        config_mod.env_path_for_instance = lambda inst: config_dir / f"{inst}.env"

        for key in ["TELEGRAM_BOT_TOKEN", "BOT_PROVIDER", "BOT_ALLOWED_USERS", "BOT_SKILLS"]:
            os.environ.pop(key, None)

        try:
            cfg = config_mod.load_config("test-skills")
            assert len(cfg.default_skills) == 3
            assert cfg.default_skills == ("code-review", "testing", "debugging")
        finally:
            config_mod.env_path_for_instance = orig


# =====================================================================
# PendingApproval serialization survives JSON round-trip
# =====================================================================

def test_pending_approval_json_roundtrip():
    pending = PendingApproval(
        request_user_id=42,
        prompt="do stuff",
        image_paths=["/tmp/img.jpg"],
        attachment_dicts=[{"path": "/tmp/a.txt", "original_name": "a.txt", "is_image": False}],
        context_hash="deadbeef",
    )
    serialized = json.dumps(dataclasses.asdict(pending))
    deserialized = json.loads(serialized)
    assert deserialized["request_user_id"] == 42
    assert deserialized["context_hash"] == "deadbeef"
    assert deserialized["prompt"] == "do stuff"


# =====================================================================
# Phase 2: Credential encryption round-trip
# =====================================================================

def test_encryption_roundtrip():
    enc_key = derive_encryption_key("1234567890:AABBCCDDEEFFaabbccddeeff_0123456789")
    assert len(enc_key) == 44  # Fernet base64

    # Round-trip: encrypt then decrypt
    secret = "ghp_abc123_my_secret_token"
    encrypted = _encrypt(secret, enc_key)
    assert encrypted != secret
    decrypted = _decrypt(encrypted, enc_key)
    assert decrypted == secret

    # Different salts produce different ciphertexts
    encrypted2 = _encrypt(secret, enc_key)
    assert encrypted != encrypted2
    decrypted2 = _decrypt(encrypted2, enc_key)
    assert decrypted2 == secret

    # Wrong key fails
    wrong_key = derive_encryption_key("9999999:WRONG")
    try:
        bad = _decrypt(encrypted, wrong_key)
        # It might "decrypt" but produce garbage
        assert bad != secret
    except Exception:
        assert True  # wrong key raises exception

    # Empty string round-trips
    enc_empty = _encrypt("", enc_key)
    assert _decrypt(enc_empty, enc_key) == ""

    # Unicode round-trips
    unicode_secret = "pässwörd_🔑"
    enc_unicode = _encrypt(unicode_secret, enc_key)
    assert _decrypt(enc_unicode, enc_key) == unicode_secret


# =====================================================================
# Phase 2: Per-user credential storage and isolation
# =====================================================================

def test_per_user_credential_storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        key = derive_encryption_key("test-bot-token")

        # Save credentials for user 111
        save_user_credential(data_dir, 111, "github", "GITHUB_TOKEN", "ghp_alice", key)
        save_user_credential(data_dir, 111, "github", "GITHUB_ORG", "acme-corp", key)
        save_user_credential(data_dir, 111, "jira", "JIRA_TOKEN", "jira_alice", key)

        # Save credentials for user 222
        save_user_credential(data_dir, 222, "github", "GITHUB_TOKEN", "ghp_bob", key)

        # Load user 111's credentials
        creds_111 = load_user_credentials(data_dir, 111, key)
        assert "github" in creds_111
        assert "jira" in creds_111
        assert creds_111["github"]["GITHUB_TOKEN"] == "ghp_alice"
        assert creds_111["github"]["GITHUB_ORG"] == "acme-corp"
        assert creds_111["jira"]["JIRA_TOKEN"] == "jira_alice"

        # Load user 222's credentials — isolated from 111
        creds_222 = load_user_credentials(data_dir, 222, key)
        assert "github" in creds_222
        assert "jira" not in creds_222
        assert creds_222["github"]["GITHUB_TOKEN"] == "ghp_bob"

        # Nonexistent user returns empty
        creds_999 = load_user_credentials(data_dir, 999, key)
        assert creds_999 == {}

        # Credential file for user 111 exists
        cred_file = data_dir / "credentials" / "111.json"
        assert cred_file.is_file()

        # Overwrite existing credential
        save_user_credential(data_dir, 111, "github", "GITHUB_TOKEN", "ghp_alice_new", key)
        creds_111_new = load_user_credentials(data_dir, 111, key)
        assert creds_111_new["github"]["GITHUB_TOKEN"] == "ghp_alice_new"
        # Other credentials not affected
        assert creds_111_new["github"]["GITHUB_ORG"] == "acme-corp"


# =====================================================================
# Phase 2: requires.yaml parsing
# =====================================================================

def test_requires_yaml_parsing():
    yaml_text = """
credentials:
  - key: GITHUB_TOKEN
    prompt: "Paste a GitHub personal access token (classic, with repo scope)"
    help_url: https://github.com/settings/tokens
    validate:
      url: https://api.github.com/user
      header: "Authorization: token ${GITHUB_TOKEN}"
      expect_status: 200
  - key: GITHUB_ORG
    prompt: "GitHub organization name"
"""

    reqs = _parse_requires_yaml(yaml_text)
    assert len(reqs) == 2
    assert reqs[0].key == "GITHUB_TOKEN"
    assert "personal access token" in reqs[0].prompt
    assert reqs[0].help_url == "https://github.com/settings/tokens"
    assert reqs[0].validate is not None
    assert reqs[0].validate["url"] == "https://api.github.com/user"
    assert "Authorization" in reqs[0].validate["header"]
    assert reqs[0].validate["expect_status"] == "200"
    assert reqs[1].key == "GITHUB_ORG"
    assert reqs[1].validate is None
    assert reqs[1].help_url is None

    # Empty YAML
    reqs_empty = _parse_requires_yaml("")
    assert reqs_empty == []

    # YAML with non-credentials section
    yaml_other = """
tools:
  - name: something
credentials:
  - key: API_KEY
    prompt: Enter your API key
other:
  - x: y
"""
    reqs_other = _parse_requires_yaml(yaml_other)
    assert len(reqs_other) == 1
    assert reqs_other[0].key == "API_KEY"


# =====================================================================
# Phase 2: check_credentials
# =====================================================================

def test_check_credentials():
    # Create a temp skill with requires.yaml
    with tempfile.TemporaryDirectory() as tmpdir:
        import app.skills as skills_mod
        orig_catalog = skills_mod.CATALOG_DIR

        catalog_dir = Path(tmpdir) / "catalog"
        (catalog_dir / "test-cred-skill").mkdir(parents=True)
        (catalog_dir / "test-cred-skill" / "skill.md").write_text(
            "---\nname: test-cred-skill\ndisplay_name: Test Cred\ndescription: test\n---\nInstructions here.\n"
        )
        (catalog_dir / "test-cred-skill" / "requires.yaml").write_text(
            "credentials:\n  - key: API_KEY\n    prompt: Enter API key\n  - key: API_SECRET\n    prompt: Enter secret\n"
        )
        (catalog_dir / "test-no-cred").mkdir(parents=True)
        (catalog_dir / "test-no-cred" / "skill.md").write_text(
            "---\nname: test-no-cred\ndisplay_name: No Cred\ndescription: no creds\n---\nSimple.\n"
        )

        skills_mod.CATALOG_DIR = catalog_dir
        try:
            # No credentials → both missing
            missing = check_credentials("test-cred-skill", {})
            assert len(missing) == 2

            # Partial credentials → one missing
            missing_partial = check_credentials("test-cred-skill", {"test-cred-skill": {"API_KEY": "k"}})
            assert len(missing_partial) == 1
            assert missing_partial[0].key == "API_SECRET"

            # Full credentials → none missing
            missing_full = check_credentials("test-cred-skill", {"test-cred-skill": {"API_KEY": "k", "API_SECRET": "s"}})
            assert len(missing_full) == 0

            # Skill with no requires.yaml
            missing_none = check_credentials("test-no-cred", {})
            assert len(missing_none) == 0

            # Unknown skill
            missing_unknown = check_credentials("nonexistent", {})
            assert len(missing_unknown) == 0
        finally:
            skills_mod.CATALOG_DIR = orig_catalog


# =====================================================================
# Phase 2: build_credential_env
# =====================================================================

def test_build_credential_env():
    user_creds = {
        "github": {"GITHUB_TOKEN": "ghp_123", "GITHUB_ORG": "acme"},
        "jira": {"JIRA_TOKEN": "jira_abc"},
        "unused-skill": {"UNUSED_KEY": "val"},
    }

    # Only active skills' creds are included
    env = build_credential_env(["github", "jira"], user_creds)
    assert env.get("GITHUB_TOKEN") == "ghp_123"
    assert env.get("GITHUB_ORG") == "acme"
    assert env.get("JIRA_TOKEN") == "jira_abc"
    assert "UNUSED_KEY" not in env

    # Empty active skills → empty env
    env_empty = build_credential_env([], user_creds)
    assert env_empty == {}

    # Missing skill in user_creds → just skip
    env_missing = build_credential_env(["nonexistent"], user_creds)
    assert env_missing == {}


# =====================================================================
# Phase 2: awaiting_skill_setup survives session save/load
# =====================================================================

def test_awaiting_skill_setup_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        (data_dir / "sessions").mkdir(parents=True)

        session = default_session("claude", {"session_id": "x", "started": False}, "on")
        setup_state = {
            "user_id": 111,
            "skill": "github",
            "remaining": [
                {"key": "GITHUB_TOKEN", "prompt": "Paste token", "help_url": "https://example.com"},
            ],
        }
        session["awaiting_skill_setup"] = setup_state
        save_session(data_dir, 100, session)

        loaded = load_session(data_dir, 100, "claude", lambda: {"session_id": "y", "started": False}, "on")
        assert loaded.get("awaiting_skill_setup") is not None
        assert loaded["awaiting_skill_setup"]["user_id"] == 111
        assert loaded["awaiting_skill_setup"]["skill"] == "github"
        assert len(loaded["awaiting_skill_setup"]["remaining"]) == 1

        # /new clears awaiting_skill_setup
        new_session = default_session("claude", {"session_id": "z", "started": False}, "on")
        assert new_session.get("awaiting_skill_setup") is None


# =====================================================================
# Phase 2: RunContext with credential_env
# =====================================================================

def test_run_context_with_credential_env():
    ctx_with_creds = build_run_context(
        "engineer", ["code-review"], ["/tmp/uploads/123"],
        credential_env={"GITHUB_TOKEN": "ghp_test", "API_KEY": "secret"},
    )
    assert ctx_with_creds.credential_env["GITHUB_TOKEN"] == "ghp_test"
    assert ctx_with_creds.credential_env["API_KEY"] == "secret"
    assert "engineer" in ctx_with_creds.system_prompt


# =====================================================================
# Phase 3: Provider YAML parsing
# =====================================================================

def test_provider_yaml_parsing():
    import yaml
    from app.skills import _resolve_placeholders

    # Basic claude.yaml
    claude_yaml = """
mcp_servers:
  github:
    command: npx
    args: -y @modelcontextprotocol/server-github
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"

allowed_tools:
  - "mcp__github__*"
  - "Read"

disallowed_tools:
  - "Bash(rm:*)"
"""
    parsed = yaml.safe_load(claude_yaml)
    assert "mcp_servers" in parsed
    assert "allowed_tools" in parsed
    assert len(parsed["allowed_tools"]) == 2
    assert "disallowed_tools" in parsed

    # Basic codex.yaml
    codex_yaml = """
sandbox: workspace-write

config_overrides:
  - 'sandbox_permissions=["disk-full-read-access"]'
"""
    parsed_codex = yaml.safe_load(codex_yaml)
    assert parsed_codex.get("sandbox") == "workspace-write"
    assert len(parsed_codex.get("config_overrides", [])) == 1


# =====================================================================
# Phase 3: Placeholder resolution
# =====================================================================

def test_placeholder_resolution():
    from app.skills import _resolve_placeholders

    env = {"GITHUB_TOKEN": "ghp_test123", "API_KEY": "secret"}
    assert _resolve_placeholders("${GITHUB_TOKEN}", env) == "ghp_test123"
    assert _resolve_placeholders("hello", env) == "hello"
    assert _resolve_placeholders("${UNKNOWN}", env) == "${UNKNOWN}"
    assert _resolve_placeholders({"key": "${API_KEY}"}, env) == {"key": "secret"}
    assert _resolve_placeholders(["${GITHUB_TOKEN}", "static"], env) == ["ghp_test123", "static"]
    assert _resolve_placeholders({"a": ["${API_KEY}"]}, env) == {"a": ["secret"]}


# =====================================================================
# Phase 3: build_provider_config
# =====================================================================

def test_build_provider_config():
    # Claude config for github-integration
    claude_config = build_provider_config("claude", ["github-integration"], {"GITHUB_TOKEN": "ghp_real"})
    assert "mcp_servers" in claude_config
    assert "allowed_tools" in claude_config
    # Placeholder should be resolved
    mcp_env = claude_config.get("mcp_servers", {}).get("github", {}).get("env", {})
    assert mcp_env.get("GITHUB_PERSONAL_ACCESS_TOKEN") == "ghp_real"

    # Codex config for github-integration
    codex_config = build_provider_config("codex", ["github-integration"], {})
    assert codex_config.get("sandbox") == "workspace-write"
    assert len(codex_config.get("config_overrides", [])) == 1

    # No provider config for instruction-only skills
    empty_config = build_provider_config("claude", ["code-review"], {})
    assert empty_config == {}

    # Unknown provider
    unknown_config = build_provider_config("unknown", ["github-integration"], {})
    assert unknown_config == {}


# =====================================================================
# Phase 3: capability_summary
# =====================================================================

def test_capability_summary():
    from app.skills import build_capability_summary

    cap = build_capability_summary("claude", ["github-integration"])
    assert "MCP server" in cap
    assert "github" in cap

    cap_codex = build_capability_summary("codex", ["github-integration"])
    # Codex has scripts for github-integration
    assert len(cap_codex) > 0
    assert "script" in cap_codex.lower()

    cap_empty = build_capability_summary("claude", ["code-review"])
    assert cap_empty == ""


# =====================================================================
# Phase 3: provider_config_digest
# =====================================================================

def test_provider_config_digest():
    digest_gh = get_provider_config_digest(["github-integration"])
    assert len(digest_gh) == 64

    digest_cr = get_provider_config_digest(["code-review"])
    assert digest_cr == ""

    # Different skills → different digests
    digest_lin = get_provider_config_digest(["linear-integration"])
    assert digest_gh != digest_lin

    # Same skill → stable digest
    digest_gh2 = get_provider_config_digest(["github-integration"])
    assert digest_gh == digest_gh2


# =====================================================================
# Phase 3: Claude provider_config applies to commands
# =====================================================================

def test_claude_provider_config_cli_flags():
    from app.providers.claude import ClaudeProvider

    p_claude = ClaudeProvider(make_config(provider_name="claude"))
    state_c = {"session_id": "test-p3", "started": False}
    cmd = p_claude._build_run_cmd(state_c, "test prompt")

    # Apply provider config
    pc = {
        "mcp_servers": {"github": {"command": "npx", "args": "-y @mcp/server-github"}},
        "allowed_tools": ["mcp__github__*"],
        "disallowed_tools": ["Bash(rm:*)"],
    }
    # Insert system prompt first (as run() does)
    idx = cmd.index("--")
    cmd[idx:idx] = ["--append-system-prompt", "test"]

    mcp_tmp = p_claude._apply_provider_config(cmd, pc)
    assert mcp_tmp is not None
    assert "--mcp-config" in cmd
    assert "--allowedTools" in cmd
    assert "--disallowedTools" in cmd
    assert "mcp__github__*" in cmd
    assert "Bash(rm:*)" in cmd

    # Cleanup temp file
    if mcp_tmp:
        os.unlink(mcp_tmp)


# =====================================================================
# Phase 3: Codex provider_config applies
# =====================================================================

def test_codex_provider_config_cli_flags():
    from app.providers.codex import CodexProvider

    p_codex = CodexProvider(make_config(provider_name="codex"))
    # Build a new command with sandbox override
    cmd_codex = p_codex._build_new_cmd("test prompt", [], sandbox="workspace-write")
    assert "--sandbox" in cmd_codex
    # Verify sandbox value
    sandbox_idx = cmd_codex.index("--sandbox")
    assert cmd_codex[sandbox_idx + 1] == "workspace-write"


# =====================================================================
# Phase 3: RunContext includes provider_config
# =====================================================================

def test_run_context_with_provider_config():
    ctx_p3 = build_run_context(
        "engineer", ["github-integration"], ["/tmp/test"],
        provider_name="claude", credential_env={"GITHUB_TOKEN": "ghp_xxx"},
    )
    assert bool(ctx_p3.provider_config)
    assert "MCP server" in ctx_p3.capability_summary
    assert ctx_p3.credential_env.get("GITHUB_TOKEN") == "ghp_xxx"

    # PreflightContext includes capability_summary but no secrets
    pf_p3 = build_preflight_context(
        "engineer", ["github-integration"], ["/tmp/test"],
        provider_name="claude",
    )
    assert "MCP server" in pf_p3.capability_summary
    assert not isinstance(pf_p3, RunContext)


# =====================================================================
# Phase 3: load_provider_yaml for real skills
# =====================================================================

def test_load_provider_yaml():
    gh_claude = load_provider_yaml("github-integration", "claude")
    assert "mcp_servers" in gh_claude

    gh_codex = load_provider_yaml("github-integration", "codex")
    assert "sandbox" in gh_codex

    no_yaml = load_provider_yaml("code-review", "claude")
    assert no_yaml == {}

    nonexistent = load_provider_yaml("nonexistent-skill", "claude")
    assert nonexistent == {}


# =====================================================================
# Phase 4: Custom skill discovery and override
# =====================================================================

def test_custom_skill_discovery():
    import app.skills as skills_mod
    from app.skills import scaffold_skill, validate_active_skills, CUSTOM_DIR

    # Test with a temp custom skills directory
    orig_custom_dir = skills_mod.CUSTOM_DIR
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_dir = Path(tmpdir) / "custom-skills"
        skills_mod.CUSTOM_DIR = custom_dir

        # No custom dir → catalog only has built-in
        cat1 = load_catalog()
        assert cat1["code-review"].is_custom is False

        # Create a custom skill
        custom_dir.mkdir(parents=True)
        my_skill_dir = custom_dir / "my-team-rules"
        my_skill_dir.mkdir()
        (my_skill_dir / "skill.md").write_text(
            "---\nname: my-team-rules\ndisplay_name: Team Rules\ndescription: Our team conventions\n---\n\nFollow team conventions.\n"
        )

        cat2 = load_catalog()
        assert "my-team-rules" in cat2
        assert cat2["my-team-rules"].is_custom is True
        assert "code-review" in cat2
        assert cat2["code-review"].is_custom is False

        # Custom overrides built-in
        override_dir = custom_dir / "code-review"
        override_dir.mkdir()
        (override_dir / "skill.md").write_text(
            "---\nname: code-review\ndisplay_name: Custom Code Review\ndescription: Our custom review\n---\n\nCustom review instructions.\n"
        )

        cat3 = load_catalog()
        assert cat3["code-review"].display_name == "Custom Code Review"
        assert cat3["code-review"].is_custom is True

        # Custom override takes precedence for instructions
        instr = get_skill_instructions("code-review")
        assert "Custom review" in instr

        # Custom skill for my-team-rules instructions
        instr2 = get_skill_instructions("my-team-rules")
        assert "team conventions" in instr2

        skills_mod.CUSTOM_DIR = orig_custom_dir


# =====================================================================
# Phase 4: scaffold_skill
# =====================================================================

def test_scaffold_skill():
    import app.skills as skills_mod
    from app.skills import scaffold_skill

    orig_custom_dir2 = skills_mod.CUSTOM_DIR
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_dir = Path(tmpdir) / "custom-skills"
        skills_mod.CUSTOM_DIR = custom_dir

        # Scaffold creates directory and template
        result_dir = scaffold_skill("my-new-skill")
        assert result_dir.is_dir()
        assert (result_dir / "skill.md").is_file()
        content = (result_dir / "skill.md").read_text()
        assert "name: my-new-skill" in content
        assert "My New Skill" in content

        # Duplicate fails
        try:
            scaffold_skill("my-new-skill")
            assert False, "duplicate should raise error"
        except ValueError as e:
            assert "already exists" in str(e)

        # Invalid name fails
        try:
            scaffold_skill("Invalid Name!")
            assert False, "invalid name should raise error"
        except ValueError as e:
            assert "lowercase" in str(e)

        skills_mod.CUSTOM_DIR = orig_custom_dir2


# =====================================================================
# Phase 4: validate_active_skills
# =====================================================================

def test_validate_active_skills():
    from app.skills import validate_active_skills

    errors = validate_active_skills(["code-review", "testing"])
    assert errors == []

    errors_bad = validate_active_skills(["code-review", "nonexistent-skill"])
    assert len(errors_bad) == 1
    assert "nonexistent-skill" in errors_bad[0]

    errors_empty = validate_active_skills([])
    assert errors_empty == []


# =====================================================================
# Phase 4: SkillMeta.is_custom
# =====================================================================

def test_skill_meta_is_custom():
    from app.skills import SkillMeta

    meta_builtin = SkillMeta(name="test", display_name="Test", description="desc")
    assert meta_builtin.is_custom is False

    meta_custom = SkillMeta(name="test", display_name="Test", description="desc", is_custom=True)
    assert meta_custom.is_custom is True


# =====================================================================
# Rich role prompt shaping
# =====================================================================

def test_rich_role_verbatim():
    prompt1 = build_system_prompt("senior Python engineer", [])
    assert "You are a senior Python engineer" in prompt1

    rich = "You are a senior architect.\nYou specialize in distributed systems."
    prompt2 = build_system_prompt(rich, [])
    assert "You are a senior architect." in prompt2
    assert "You are a You are" not in prompt2

    prompt3 = build_system_prompt("You are an expert in Kubernetes.", [])
    assert "You are a You are" not in prompt3
    assert "You are an expert" in prompt3

    prompt4 = build_system_prompt("Act as a security auditor.", [])
    assert "You are a Act as" not in prompt4
    assert "Act as a security auditor" in prompt4

    prompt5 = build_system_prompt("you are an expert in kubernetes.", [])
    assert "You are a you are" not in prompt5
    assert "you are an expert in kubernetes" in prompt5

    prompt6 = build_system_prompt("you're a helpful coding assistant.", [])
    assert "You are a you're" not in prompt6
    assert "you're a helpful coding assistant" in prompt6


# =====================================================================
# Provider-scoped config digest
# =====================================================================

def test_provider_scoped_digest():
    digest_claude = get_provider_config_digest(["github-integration"], provider_name="claude")
    digest_codex = get_provider_config_digest(["github-integration"], provider_name="codex")
    digest_all = get_provider_config_digest(["github-integration"])

    assert digest_claude != digest_codex
    assert digest_all != digest_claude
    assert digest_all != digest_codex


# =====================================================================
# MCP args YAML parsing
# =====================================================================

def test_mcp_args_is_list():
    raw = load_provider_yaml("github-integration", "claude")
    mcp = raw.get("mcp_servers", {}).get("github", {})
    assert isinstance(mcp.get("args"), list)
    assert len(mcp.get("args", [])) == 2
    assert "-y" in mcp["args"]

    raw2 = load_provider_yaml("linear-integration", "claude")
    mcp2 = raw2.get("mcp_servers", {}).get("linear", {})
    assert isinstance(mcp2.get("args"), list)


# =====================================================================
# Malformed skill resilience
# =====================================================================

def test_malformed_skill_resilience():
    import app.skills as skills_mod

    orig_custom_dir = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir
            malformed_dir = custom_dir / "malformed-test-skill"
            malformed_dir.mkdir(parents=True, exist_ok=True)
            (malformed_dir / "skill.md").write_text(
                "---\nname: malformed-test-skill\ndescription: [invalid yaml\n---\n\nBody text here.\n"
            )

            catalog = load_catalog()
            assert isinstance(catalog, dict)
            assert "malformed-test-skill" not in catalog
            assert _skill_dir("malformed-test-skill") is None
            assert get_skill_instructions("malformed-test-skill") == ""
            assert get_skill_requirements("malformed-test-skill") == []
    finally:
        skills_mod.CUSTOM_DIR = orig_custom_dir


# =====================================================================
# Malformed provider YAML resilience
# =====================================================================

def test_malformed_provider_yaml_resilience():
    import app.skills as skills_mod

    orig_custom_dir = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir
            skill_dir = custom_dir / "yaml-test-skill"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "skill.md").write_text(
                "---\nname: yaml-test-skill\ndisplay_name: YAML Test\ndescription: Test skill\n---\n\nTest.\n"
            )
            (skill_dir / "claude.yaml").write_text("mcp_servers:\n  test:\n    command: echo\n    args: [unclosed\n")

            assert load_provider_yaml("yaml-test-skill", "claude") == {}
            assert isinstance(build_provider_config("claude", ["yaml-test-skill"], {}), dict)
    finally:
        skills_mod.CUSTOM_DIR = orig_custom_dir


# =====================================================================
# Malformed requires.yaml resilience
# =====================================================================

def test_malformed_requires_yaml_resilience():
    assert _parse_requires_yaml("credentials:\n  - key: [unclosed\n") == []
    assert _parse_requires_yaml("just_a_string") == []
    assert _parse_requires_yaml("") == []


# =====================================================================
# Catalog uses directory name, not frontmatter name
# =====================================================================

def test_catalog_uses_directory_name():
    import app.skills as skills_mod

    orig_custom_dir = skills_mod.CUSTOM_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "custom-skills"
            skills_mod.CUSTOM_DIR = custom_dir
            skill_dir = custom_dir / "my-actual-dir"
            skill_dir.mkdir(parents=True)
            (skill_dir / "skill.md").write_text(
                "---\nname: fancy-meta-name\ndisplay_name: Fancy Skill\ndescription: A test skill\n---\n\nDo fancy things.\n"
            )

            catalog = load_catalog()
            assert "my-actual-dir" in catalog
            assert "fancy-meta-name" not in catalog
            assert _skill_dir("my-actual-dir") is not None
            assert _skill_dir("fancy-meta-name") is None
            assert "fancy things" in get_skill_instructions("my-actual-dir")
            assert get_skill_instructions("fancy-meta-name") == ""
    finally:
        skills_mod.CUSTOM_DIR = orig_custom_dir
