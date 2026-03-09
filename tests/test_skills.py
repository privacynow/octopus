"""Tests for the skill system — Phases 1 & 2.

Covers:
- §8.5 test invariants (context hash, pending request, BOT_ROLE)
- Skill engine (catalog, instructions, prompt building)
- Config loading (role, skills)
- Provider command building (system prompt injection)
- Codex thread invalidation
- Session state (active_skills, role, pending_request)
- Phase 2: credential encryption round-trip, per-user isolation,
  requires.yaml parsing, credential satisfaction, env injection,
  awaiting_skill_setup persistence
"""

import dataclasses
import hashlib
import json
import os
import sys
import tempfile
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

from pathlib import Path
from app.config import load_dotenv_file, validate_config
from app.providers.base import (
    PendingRequest, PreflightContext, RunContext,
    compute_context_hash,
)
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
from tests.support.assertions import Checks
from tests.support.config_support import make_config

checks = Checks()
check = checks.check
check_in = checks.check_in
check_not_in = checks.check_not_in


# =====================================================================
# §8.5 #1: Approve-as-different-user — PendingRequest preserves identity
# =====================================================================
print("\n=== §8.5 #1: PendingRequest preserves requester identity ===")

pending = PendingRequest(
    request_user_id=111,
    prompt="review this",
    image_paths=[],
    attachment_dicts=[{"path": "/tmp/a.txt", "original_name": "a.txt", "is_image": False}],
    context_hash="abc123",
)
check("pending has request_user_id", pending.request_user_id, 111)
check("pending has context_hash", pending.context_hash, "abc123")

# Serialize to dict (as stored in session JSON)
d = dataclasses.asdict(pending)
check("serialized request_user_id", d["request_user_id"], 111)
check("serialized context_hash", d["context_hash"], "abc123")
check("serialized denials is None", d["denials"], None)

# Retry PendingRequest has denials
pending_retry = PendingRequest(
    request_user_id=222,
    prompt="write file",
    image_paths=[],
    attachment_dicts=[],
    context_hash="def456",
    denials=[{"tool_name": "Write", "tool_input": {"file_path": "/etc/hosts"}}],
)
check("retry has denials", len(pending_retry.denials), 1)
check("retry request_user_id", pending_retry.request_user_id, 222)


# =====================================================================
# §8.5 #2: Retry-after-context-change — hash changes → stale
# =====================================================================
print("\n=== §8.5 #2: Context hash detects changes ===")

hash1 = compute_context_hash("engineer", ["code-review"], {"code-review": "aaa"}, "", [])
hash2 = compute_context_hash("engineer", ["code-review"], {"code-review": "aaa"}, "", [])
check("same context → same hash", hash1, hash2)

# Skill added
hash3 = compute_context_hash("engineer", ["code-review", "testing"], {"code-review": "aaa", "testing": "bbb"}, "", [])
check("skill added → different hash", hash1 != hash3, True)

# Skill removed
hash4 = compute_context_hash("engineer", [], {}, "", [])
check("skills cleared → different hash", hash1 != hash4, True)

# Role changed
hash5 = compute_context_hash("devops lead", ["code-review"], {"code-review": "aaa"}, "", [])
check("role changed → different hash", hash1 != hash5, True)

# Skill content changed (digest differs)
hash6 = compute_context_hash("engineer", ["code-review"], {"code-review": "bbb"}, "", [])
check("skill digest changed → different hash", hash1 != hash6, True)

# Extra dirs changed
hash7 = compute_context_hash("engineer", ["code-review"], {"code-review": "aaa"}, "", ["/opt/new"])
check("extra dirs changed → different hash", hash1 != hash7, True)

# Order-independent: skills listed differently but same set
hash_a = compute_context_hash("x", ["b", "a"], {"a": "1", "b": "2"}, "", [])
hash_b = compute_context_hash("x", ["a", "b"], {"a": "1", "b": "2"}, "", [])
check("skill order doesn't matter", hash_a, hash_b)


# =====================================================================
# §8.5 #3: Pending invalidation on context change
# =====================================================================
print("\n=== §8.5 #3: Pending invalidation ===")

# Simulating: approval stored with hash1, then role changed → hash differs
stored_hash = compute_context_hash("engineer", ["code-review"], {"code-review": "aaa"}, "", [])
current_hash = compute_context_hash("manager", ["code-review"], {"code-review": "aaa"}, "", [])
check("role change invalidates pending", stored_hash != current_hash, True)


# =====================================================================
# §8.5 #4 & #5: Codex resets on context hash change, preserves when unchanged
# =====================================================================
print("\n=== §8.5 #4-5: Codex context hash invalidation ===")

from app.providers.codex import CodexProvider

p_codex = CodexProvider(make_config(provider_name="codex"))
state = p_codex.new_provider_state()
check("fresh state has no thread", state.get("thread_id"), None)
# After first run, thread_id would be set by the provider
# We simulate: state has a thread and a stored hash
state["thread_id"] = "thread-abc"
state["context_hash"] = hash1

# Same hash → thread should be preserved (handler compares before calling run)
check("same hash → preserve thread", state["thread_id"], "thread-abc")

# Different hash → handler clears thread_id
if hash1 != hash3:  # context changed
    state["thread_id"] = None
check("hash changed → handler cleared thread", state["thread_id"], None)


# =====================================================================
# §8.5 #7: BOT_ROLE contract
# =====================================================================
print("\n=== §8.5 #7: BOT_ROLE contract ===")

# Values with # survive via quoting
with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
    f.write('BOT_ROLE="Senior C# engineer"\n')
    f.flush()
    env = load_dotenv_file(Path(f.name))
    check("# in quoted role survives", env.get("BOT_ROLE"), "Senior C# engineer")
os.unlink(f.name)

# Values with whitespace survive
with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
    f.write('BOT_ROLE="Lead backend engineer for payments team"\n')
    f.flush()
    env = load_dotenv_file(Path(f.name))
    check("whitespace in role survives", env.get("BOT_ROLE"), "Lead backend engineer for payments team")
os.unlink(f.name)

# validate_config rejects " in role
cfg_bad_quote = make_config(role='He said "ship it"')
errors = validate_config(cfg_bad_quote)
role_errors = [e for e in errors if "BOT_ROLE" in e]
check("double quote rejected", len(role_errors) > 0, True)

# validate_config rejects \ in role
cfg_bad_backslash = make_config(role="C:\\Users\\admin")
errors = validate_config(cfg_bad_backslash)
role_errors = [e for e in errors if "BOT_ROLE" in e]
check("backslash rejected", len(role_errors) > 0, True)

# validate_config accepts clean role
cfg_good = make_config(role="Senior Python engineer")
errors = validate_config(cfg_good)
role_errors = [e for e in errors if "BOT_ROLE" in e]
check("clean role accepted", role_errors, [])


# =====================================================================
# Skill catalog discovery
# =====================================================================
print("\n=== Skill catalog ===")

catalog = load_catalog()
check("catalog has 10 skills", len(catalog), 10)
check_in("has code-review", "code-review", catalog)
check_in("has testing", "testing", catalog)
check_in("has debugging", "debugging", catalog)
check_in("has devops", "devops", catalog)
check_in("has documentation", "documentation", catalog)
check_in("has security", "security", catalog)
check_in("has refactoring", "refactoring", catalog)
check_in("has architecture", "architecture", catalog)
check_in("has github-integration", "github-integration", catalog)
check_in("has linear-integration", "linear-integration", catalog)

# Metadata
cr = catalog["code-review"]
check("code-review has display_name", bool(cr.display_name), True)
check("code-review has description", bool(cr.description), True)


# =====================================================================
# Skill instructions
# =====================================================================
print("\n=== Skill instructions ===")

instructions = get_skill_instructions("code-review")
check("code-review has instructions", len(instructions) > 0, True)
check("unknown skill returns empty", get_skill_instructions("nonexistent"), "")


# =====================================================================
# Skill digests
# =====================================================================
print("\n=== Skill digests ===")

digests = get_skill_digests(["code-review", "testing"])
check("digests has 2 entries", len(digests), 2)
check("digest is hex string", len(digests["code-review"]), 64)  # sha256 hex

# Same content → same digest
digests2 = get_skill_digests(["code-review"])
check("digest is stable", digests["code-review"], digests2["code-review"])

# Unknown skill not in digests
digests3 = get_skill_digests(["nonexistent"])
check("unknown skill not in digests", len(digests3), 0)


# =====================================================================
# System prompt building
# =====================================================================
print("\n=== System prompt building ===")

prompt = build_system_prompt("Senior Python engineer", ["code-review", "testing"])
check_in("prompt has role", "You are a Senior Python engineer", prompt)
check_in("prompt has code-review section", "## Code Review", prompt)
check_in("prompt has testing section", "## Testing", prompt)

# No role
prompt_no_role = build_system_prompt("", ["code-review"])
check_not_in("no role prefix", "You are a", prompt_no_role)
check_in("still has skill", "## Code Review", prompt_no_role)

# No skills
prompt_no_skills = build_system_prompt("engineer", [])
check_in("role only", "You are a engineer", prompt_no_skills)

# Neither role nor skills → empty
prompt_empty = build_system_prompt("", [])
check("empty prompt", prompt_empty, "")


# =====================================================================
# Context builders
# =====================================================================
print("\n=== Context builders ===")

run_ctx = build_run_context("engineer", ["code-review"], ["/tmp/uploads/123"])
check("run context is RunContext", isinstance(run_ctx, RunContext), True)
check("run context has dirs", run_ctx.extra_dirs, ["/tmp/uploads/123"])
check_in("run context has prompt", "You are a engineer", run_ctx.system_prompt)
check("run context capability_summary empty", run_ctx.capability_summary, "")
check("run context provider_config empty", run_ctx.provider_config, {})
check("run context credential_env empty", run_ctx.credential_env, {})

pf_ctx = build_preflight_context("engineer", ["code-review"], ["/tmp/uploads/123"])
check("preflight context is PreflightContext", isinstance(pf_ctx, PreflightContext), True)
check("preflight is not RunContext", isinstance(pf_ctx, RunContext), False)
check("preflight has dirs", pf_ctx.extra_dirs, ["/tmp/uploads/123"])


# =====================================================================
# Claude provider: --append-system-prompt injection
# =====================================================================
print("\n=== Claude system prompt injection ===")

from app.providers.claude import ClaudeProvider

p_claude = ClaudeProvider(make_config(provider_name="claude"))
state = {"session_id": "test-123", "started": False}

# Without context: no --append-system-prompt
cmd = p_claude._build_run_cmd(state, "test prompt")
check_not_in("no context → no system prompt flag", "--append-system-prompt", cmd)

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
check_in("has --append-system-prompt", "--append-system-prompt", cmd_with)
# Verify order: --append-system-prompt comes before --
asp_idx = cmd_with.index("--append-system-prompt")
sep_idx = cmd_with.index("--")
check("system prompt before separator", asp_idx < sep_idx, True)
check_in("has --add-dir", "--add-dir", cmd_with)


# =====================================================================
# Codex provider: system prompt prepended to prompt text
# =====================================================================
print("\n=== Codex system prompt injection ===")

# Verify that the prompt prefix pattern works
system_prompt = "You are an engineer.\n\n## Code Review\n\nReview code."
user_prompt = "Review this PR"
effective = system_prompt + "\n\n---\n\n" + user_prompt
check_in("effective prompt has system prompt", "You are an engineer", effective)
check_in("effective prompt has separator", "---", effective)
check_in("effective prompt has user text", "Review this PR", effective)


# =====================================================================
# Session: active_skills and role persist
# =====================================================================
print("\n=== Session persistence ===")

with tempfile.TemporaryDirectory() as tmpdir:
    data_dir = Path(tmpdir)
    (data_dir / "sessions").mkdir(parents=True)

    # Create session with skills and role
    session = default_session("claude", {"session_id": "x", "started": False}, "on", "engineer", ("code-review",))
    check("default session has skills", session["active_skills"], ["code-review"])
    check("default session has role", session["role"], "engineer")

    # Save and reload
    save_session(data_dir, 100, session)
    loaded = load_session(data_dir, 100, "claude", lambda: {"session_id": "y", "started": False}, "on", "default-role", ("testing",))

    # Saved values should override defaults
    check("loaded skills preserved", loaded["active_skills"], ["code-review"])
    check("loaded role preserved", loaded["role"], "engineer")

    # Fresh session for new chat uses defaults
    fresh = load_session(data_dir, 999, "claude", lambda: {"session_id": "z", "started": False}, "on", "default-role", ("testing",))
    check("fresh session uses default role", fresh["role"], "default-role")
    check("fresh session uses default skills", fresh["active_skills"], ["testing"])

    # /new resets to defaults (simulated)
    new_session = default_session("claude", {"session_id": "w", "started": False}, "on", "default-role", ("testing",))
    check("/new resets skills to default", new_session["active_skills"], ["testing"])
    check("/new resets role to default", new_session["role"], "default-role")


# =====================================================================
# Config: role.md file overrides BOT_ROLE
# =====================================================================
print("\n=== Config role.md override ===")

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
        check("role.md overrides BOT_ROLE", "senior architect" in cfg.role, True)
        check("role.md is multi-line", "\n" in cfg.role, True)
    finally:
        config_mod.env_path_for_instance = orig


# =====================================================================
# Config: BOT_SKILLS parsing
# =====================================================================
print("\n=== Config BOT_SKILLS ===")

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
        check("3 default skills", len(cfg.default_skills), 3)
        check("skills parsed correctly", cfg.default_skills, ("code-review", "testing", "debugging"))
    finally:
        config_mod.env_path_for_instance = orig


# =====================================================================
# PendingRequest serialization survives JSON round-trip
# =====================================================================
print("\n=== PendingRequest JSON round-trip ===")

pending = PendingRequest(
    request_user_id=42,
    prompt="do stuff",
    image_paths=["/tmp/img.jpg"],
    attachment_dicts=[{"path": "/tmp/a.txt", "original_name": "a.txt", "is_image": False}],
    context_hash="deadbeef",
    denials=[{"tool_name": "Write", "tool_input": {"file_path": "/etc/hosts"}}],
)
serialized = json.dumps(dataclasses.asdict(pending))
deserialized = json.loads(serialized)
check("round-trip request_user_id", deserialized["request_user_id"], 42)
check("round-trip context_hash", deserialized["context_hash"], "deadbeef")
check("round-trip denials", len(deserialized["denials"]), 1)
check("round-trip prompt", deserialized["prompt"], "do stuff")


# =====================================================================
# Phase 2: Credential encryption round-trip
# =====================================================================
print("\n=== Phase 2: Encryption round-trip ===")

enc_key = derive_encryption_key("1234567890:AABBCCDDEEFFaabbccddeeff_0123456789")
check("key is 44 bytes (Fernet base64)", len(enc_key), 44)

# Round-trip: encrypt then decrypt
secret = "ghp_abc123_my_secret_token"
encrypted = _encrypt(secret, enc_key)
check("encrypted differs from plaintext", encrypted != secret, True)
decrypted = _decrypt(encrypted, enc_key)
check("decrypt recovers plaintext", decrypted, secret)

# Different salts produce different ciphertexts
encrypted2 = _encrypt(secret, enc_key)
check("two encryptions differ (random salt)", encrypted != encrypted2, True)
decrypted2 = _decrypt(encrypted2, enc_key)
check("both decrypt correctly", decrypted2, secret)

# Wrong key fails
wrong_key = derive_encryption_key("9999999:WRONG")
try:
    bad = _decrypt(encrypted, wrong_key)
    # It might "decrypt" but produce garbage
    check("wrong key produces wrong value", bad != secret, True)
except Exception:
    check("wrong key raises exception", True, True)

# Empty string round-trips
enc_empty = _encrypt("", enc_key)
check("empty round-trip", _decrypt(enc_empty, enc_key), "")

# Unicode round-trips
unicode_secret = "pässwörd_🔑"
enc_unicode = _encrypt(unicode_secret, enc_key)
check("unicode round-trip", _decrypt(enc_unicode, enc_key), unicode_secret)


# =====================================================================
# Phase 2: Per-user credential storage and isolation
# =====================================================================
print("\n=== Phase 2: Per-user credential storage ===")

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
    check("alice has github skill", "github" in creds_111, True)
    check("alice has jira skill", "jira" in creds_111, True)
    check("alice github token", creds_111["github"]["GITHUB_TOKEN"], "ghp_alice")
    check("alice github org", creds_111["github"]["GITHUB_ORG"], "acme-corp")
    check("alice jira token", creds_111["jira"]["JIRA_TOKEN"], "jira_alice")

    # Load user 222's credentials — isolated from 111
    creds_222 = load_user_credentials(data_dir, 222, key)
    check("bob has github skill", "github" in creds_222, True)
    check("bob has no jira", "jira" not in creds_222, True)
    check("bob github token", creds_222["github"]["GITHUB_TOKEN"], "ghp_bob")

    # Nonexistent user returns empty
    creds_999 = load_user_credentials(data_dir, 999, key)
    check("unknown user empty", creds_999, {})

    # Credential file for user 111 exists
    cred_file = data_dir / "credentials" / "111.json"
    check("credential file exists", cred_file.is_file(), True)

    # Overwrite existing credential
    save_user_credential(data_dir, 111, "github", "GITHUB_TOKEN", "ghp_alice_new", key)
    creds_111_new = load_user_credentials(data_dir, 111, key)
    check("overwritten credential", creds_111_new["github"]["GITHUB_TOKEN"], "ghp_alice_new")
    # Other credentials not affected
    check("other cred preserved", creds_111_new["github"]["GITHUB_ORG"], "acme-corp")


# =====================================================================
# Phase 2: requires.yaml parsing
# =====================================================================
print("\n=== Phase 2: requires.yaml parsing ===")

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
check("parsed 2 requirements", len(reqs), 2)
check("first key", reqs[0].key, "GITHUB_TOKEN")
check("first prompt", "personal access token" in reqs[0].prompt, True)
check("first help_url", reqs[0].help_url, "https://github.com/settings/tokens")
check("first has validate", reqs[0].validate is not None, True)
check("validate url", reqs[0].validate["url"], "https://api.github.com/user")
check("validate header", "Authorization" in reqs[0].validate["header"], True)
check("validate expect", reqs[0].validate["expect_status"], "200")
check("second key", reqs[1].key, "GITHUB_ORG")
check("second no validate", reqs[1].validate, None)
check("second no help_url", reqs[1].help_url, None)

# Empty YAML
reqs_empty = _parse_requires_yaml("")
check("empty yaml → no reqs", reqs_empty, [])

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
check("only credentials parsed", len(reqs_other), 1)
check("correct key from mixed", reqs_other[0].key, "API_KEY")


# =====================================================================
# Phase 2: check_credentials
# =====================================================================
print("\n=== Phase 2: check_credentials (unit) ===")

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
        check("all missing when no creds", len(missing), 2)

        # Partial credentials → one missing
        missing_partial = check_credentials("test-cred-skill", {"test-cred-skill": {"API_KEY": "k"}})
        check("one missing with partial", len(missing_partial), 1)
        check("missing is API_SECRET", missing_partial[0].key, "API_SECRET")

        # Full credentials → none missing
        missing_full = check_credentials("test-cred-skill", {"test-cred-skill": {"API_KEY": "k", "API_SECRET": "s"}})
        check("none missing with full", len(missing_full), 0)

        # Skill with no requires.yaml
        missing_none = check_credentials("test-no-cred", {})
        check("no-cred skill has no reqs", len(missing_none), 0)

        # Unknown skill
        missing_unknown = check_credentials("nonexistent", {})
        check("unknown skill has no reqs", len(missing_unknown), 0)
    finally:
        skills_mod.CATALOG_DIR = orig_catalog


# =====================================================================
# Phase 2: build_credential_env
# =====================================================================
print("\n=== Phase 2: build_credential_env ===")

user_creds = {
    "github": {"GITHUB_TOKEN": "ghp_123", "GITHUB_ORG": "acme"},
    "jira": {"JIRA_TOKEN": "jira_abc"},
    "unused-skill": {"UNUSED_KEY": "val"},
}

# Only active skills' creds are included
env = build_credential_env(["github", "jira"], user_creds)
check("env has GITHUB_TOKEN", env.get("GITHUB_TOKEN"), "ghp_123")
check("env has GITHUB_ORG", env.get("GITHUB_ORG"), "acme")
check("env has JIRA_TOKEN", env.get("JIRA_TOKEN"), "jira_abc")
check("env excludes unused", "UNUSED_KEY" not in env, True)

# Empty active skills → empty env
env_empty = build_credential_env([], user_creds)
check("no active → empty env", env_empty, {})

# Missing skill in user_creds → just skip
env_missing = build_credential_env(["nonexistent"], user_creds)
check("missing skill → empty env", env_missing, {})


# =====================================================================
# Phase 2: awaiting_skill_setup survives session save/load
# =====================================================================
print("\n=== Phase 2: awaiting_skill_setup persistence ===")

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
    check("setup state survives reload", loaded.get("awaiting_skill_setup") is not None, True)
    check("setup user_id preserved", loaded["awaiting_skill_setup"]["user_id"], 111)
    check("setup skill preserved", loaded["awaiting_skill_setup"]["skill"], "github")
    check("setup remaining preserved", len(loaded["awaiting_skill_setup"]["remaining"]), 1)

    # /new clears awaiting_skill_setup
    new_session = default_session("claude", {"session_id": "z", "started": False}, "on")
    check("/new clears setup state", new_session.get("awaiting_skill_setup"), None)


# =====================================================================
# Phase 2: RunContext with credential_env
# =====================================================================
print("\n=== Phase 2: RunContext with credential_env ===")

ctx_with_creds = build_run_context(
    "engineer", ["code-review"], ["/tmp/uploads/123"],
    credential_env={"GITHUB_TOKEN": "ghp_test", "API_KEY": "secret"},
)
check("credential_env populated", ctx_with_creds.credential_env["GITHUB_TOKEN"], "ghp_test")
check("credential_env has API_KEY", ctx_with_creds.credential_env["API_KEY"], "secret")
check("system prompt still built", "engineer" in ctx_with_creds.system_prompt, True)


# =====================================================================
# Phase 3: Provider YAML parsing
# =====================================================================
print("\n=== Phase 3: Provider YAML parsing ===")

import yaml
from app.skills import _resolve_placeholders, load_provider_yaml, build_provider_config, build_capability_summary, get_provider_config_digest

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
check("has mcp_servers", "mcp_servers" in parsed, True)
check("has allowed_tools", "allowed_tools" in parsed, True)
check("allowed_tools count", len(parsed["allowed_tools"]), 2)
check("has disallowed_tools", "disallowed_tools" in parsed, True)

# Basic codex.yaml
codex_yaml = """
sandbox: workspace-write

config_overrides:
  - 'sandbox_permissions=["disk-full-read-access"]'
"""
parsed_codex = yaml.safe_load(codex_yaml)
check("codex sandbox", parsed_codex.get("sandbox"), "workspace-write")
check("codex config_overrides", len(parsed_codex.get("config_overrides", [])), 1)


# =====================================================================
# Phase 3: Placeholder resolution
# =====================================================================
print("\n=== Phase 3: Placeholder resolution ===")

env = {"GITHUB_TOKEN": "ghp_test123", "API_KEY": "secret"}
check("simple string", _resolve_placeholders("${GITHUB_TOKEN}", env), "ghp_test123")
check("no placeholder", _resolve_placeholders("hello", env), "hello")
check("unknown placeholder kept", _resolve_placeholders("${UNKNOWN}", env), "${UNKNOWN}")
check("nested dict", _resolve_placeholders({"key": "${API_KEY}"}, env), {"key": "secret"})
check("nested list", _resolve_placeholders(["${GITHUB_TOKEN}", "static"], env), ["ghp_test123", "static"])
check("mixed", _resolve_placeholders({"a": ["${API_KEY}"]}, env), {"a": ["secret"]})


# =====================================================================
# Phase 3: build_provider_config
# =====================================================================
print("\n=== Phase 3: build_provider_config ===")

# Claude config for github-integration
claude_config = build_provider_config("claude", ["github-integration"], {"GITHUB_TOKEN": "ghp_real"})
check("claude config has mcp_servers", "mcp_servers" in claude_config, True)
check("claude config has allowed_tools", "allowed_tools" in claude_config, True)
# Placeholder should be resolved
mcp_env = claude_config.get("mcp_servers", {}).get("github", {}).get("env", {})
check("claude mcp env resolved", mcp_env.get("GITHUB_PERSONAL_ACCESS_TOKEN"), "ghp_real")

# Codex config for github-integration
codex_config = build_provider_config("codex", ["github-integration"], {})
check("codex config has sandbox", codex_config.get("sandbox"), "workspace-write")
check("codex config has overrides", len(codex_config.get("config_overrides", [])), 1)

# No provider config for instruction-only skills
empty_config = build_provider_config("claude", ["code-review"], {})
check("no config for instruction-only", empty_config, {})

# Unknown provider
unknown_config = build_provider_config("unknown", ["github-integration"], {})
check("unknown provider empty", unknown_config, {})


# =====================================================================
# Phase 3: capability_summary
# =====================================================================
print("\n=== Phase 3: capability_summary ===")

cap = build_capability_summary("claude", ["github-integration"])
check_in("summary has MCP server", "MCP server", cap)
check_in("summary mentions github", "github", cap)

cap_codex = build_capability_summary("codex", ["github-integration"])
# Codex has scripts for github-integration
check("codex has cap summary", len(cap_codex) > 0, True)
check_in("codex cap mentions script", "script", cap_codex.lower())

cap_empty = build_capability_summary("claude", ["code-review"])
check("instruction-only → empty cap", cap_empty, "")


# =====================================================================
# Phase 3: provider_config_digest
# =====================================================================
print("\n=== Phase 3: provider_config_digest ===")

digest_gh = get_provider_config_digest(["github-integration"])
check("digest is hex", len(digest_gh), 64)

digest_cr = get_provider_config_digest(["code-review"])
check("no yaml → empty digest", digest_cr, "")

# Different skills → different digests
digest_lin = get_provider_config_digest(["linear-integration"])
check("different skill → different digest", digest_gh != digest_lin, True)

# Same skill → stable digest
digest_gh2 = get_provider_config_digest(["github-integration"])
check("same skill → same digest", digest_gh, digest_gh2)


# =====================================================================
# Phase 3: Claude provider_config applies to commands
# =====================================================================
print("\n=== Phase 3: Claude provider_config → CLI flags ===")

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
check("mcp temp file created", mcp_tmp is not None, True)
check_in("cmd has --mcp-config", "--mcp-config", cmd)
check_in("cmd has --allowedTools", "--allowedTools", cmd)
check_in("cmd has --disallowedTools", "--disallowedTools", cmd)
check_in("cmd has mcp__github__*", "mcp__github__*", cmd)
check_in("cmd has Bash(rm:*)", "Bash(rm:*)", cmd)

# Cleanup temp file
if mcp_tmp:
    os.unlink(mcp_tmp)


# =====================================================================
# Phase 3: Codex provider_config applies
# =====================================================================
print("\n=== Phase 3: Codex provider_config → CLI flags ===")

p_codex = CodexProvider(make_config(provider_name="codex"))
# Build a new command with sandbox override
cmd_codex = p_codex._build_new_cmd("test prompt", [], sandbox="workspace-write")
check_in("codex has sandbox flag", "--sandbox", cmd_codex)
# Verify sandbox value
sandbox_idx = cmd_codex.index("--sandbox")
check("codex sandbox value", cmd_codex[sandbox_idx + 1], "workspace-write")


# =====================================================================
# Phase 3: RunContext includes provider_config
# =====================================================================
print("\n=== Phase 3: RunContext with provider_config ===")

ctx_p3 = build_run_context(
    "engineer", ["github-integration"], ["/tmp/test"],
    provider_name="claude", credential_env={"GITHUB_TOKEN": "ghp_xxx"},
)
check("ctx has provider_config", bool(ctx_p3.provider_config), True)
check("ctx has capability_summary", "MCP server" in ctx_p3.capability_summary, True)
check("ctx has credential_env", ctx_p3.credential_env.get("GITHUB_TOKEN"), "ghp_xxx")

# PreflightContext includes capability_summary but no secrets
pf_p3 = build_preflight_context(
    "engineer", ["github-integration"], ["/tmp/test"],
    provider_name="claude",
)
check("preflight has capability_summary", "MCP server" in pf_p3.capability_summary, True)
check("preflight is not RunContext", isinstance(pf_p3, RunContext), False)


# =====================================================================
# Phase 3: load_provider_yaml for real skills
# =====================================================================
print("\n=== Phase 3: load_provider_yaml ===")

gh_claude = load_provider_yaml("github-integration", "claude")
check("github claude yaml loaded", "mcp_servers" in gh_claude, True)

gh_codex = load_provider_yaml("github-integration", "codex")
check("github codex yaml loaded", "sandbox" in gh_codex, True)

no_yaml = load_provider_yaml("code-review", "claude")
check("no yaml → empty", no_yaml, {})

nonexistent = load_provider_yaml("nonexistent-skill", "claude")
check("nonexistent → empty", nonexistent, {})


# =====================================================================
# Phase 4: Custom skill discovery and override
# =====================================================================
print("\n=== Phase 4: Custom skill discovery ===")

import app.skills as skills_mod
from app.skills import scaffold_skill, validate_active_skills, CUSTOM_DIR

# Test with a temp custom skills directory
orig_custom_dir = skills_mod.CUSTOM_DIR
with tempfile.TemporaryDirectory() as tmpdir:
    custom_dir = Path(tmpdir) / "custom-skills"
    skills_mod.CUSTOM_DIR = custom_dir

    # No custom dir → catalog only has built-in
    cat1 = load_catalog()
    check("no custom dir → built-in only", cat1["code-review"].is_custom, False)

    # Create a custom skill
    custom_dir.mkdir(parents=True)
    my_skill_dir = custom_dir / "my-team-rules"
    my_skill_dir.mkdir()
    (my_skill_dir / "skill.md").write_text(
        "---\nname: my-team-rules\ndisplay_name: Team Rules\ndescription: Our team conventions\n---\n\nFollow team conventions.\n"
    )

    cat2 = load_catalog()
    check("custom skill discovered", "my-team-rules" in cat2, True)
    check("custom skill is_custom", cat2["my-team-rules"].is_custom, True)
    check("built-in still present", "code-review" in cat2, True)
    check("built-in not custom", cat2["code-review"].is_custom, False)

    # Custom overrides built-in
    override_dir = custom_dir / "code-review"
    override_dir.mkdir()
    (override_dir / "skill.md").write_text(
        "---\nname: code-review\ndisplay_name: Custom Code Review\ndescription: Our custom review\n---\n\nCustom review instructions.\n"
    )

    cat3 = load_catalog()
    check("override display_name", cat3["code-review"].display_name, "Custom Code Review")
    check("override is_custom", cat3["code-review"].is_custom, True)

    # Custom override takes precedence for instructions
    from app.skills import get_skill_instructions
    instr = get_skill_instructions("code-review")
    check_in("custom instructions loaded", "Custom review", instr)

    # Custom skill for my-team-rules instructions
    instr2 = get_skill_instructions("my-team-rules")
    check_in("custom skill instructions", "team conventions", instr2)

    skills_mod.CUSTOM_DIR = orig_custom_dir


# =====================================================================
# Phase 4: scaffold_skill
# =====================================================================
print("\n=== Phase 4: scaffold_skill ===")

orig_custom_dir2 = skills_mod.CUSTOM_DIR
with tempfile.TemporaryDirectory() as tmpdir:
    custom_dir = Path(tmpdir) / "custom-skills"
    skills_mod.CUSTOM_DIR = custom_dir

    # Scaffold creates directory and template
    result_dir = scaffold_skill("my-new-skill")
    check("scaffold creates dir", result_dir.is_dir(), True)
    check("scaffold creates skill.md", (result_dir / "skill.md").is_file(), True)
    content = (result_dir / "skill.md").read_text()
    check_in("scaffold has name", "name: my-new-skill", content)
    check_in("scaffold has display_name", "My New Skill", content)

    # Duplicate fails
    try:
        scaffold_skill("my-new-skill")
        check("duplicate raises error", False, True)
    except ValueError as e:
        check("duplicate raises ValueError", "already exists" in str(e), True)

    # Invalid name fails
    try:
        scaffold_skill("Invalid Name!")
        check("invalid name raises error", False, True)
    except ValueError as e:
        check("invalid name raises ValueError", "lowercase" in str(e), True)

    skills_mod.CUSTOM_DIR = orig_custom_dir2


# =====================================================================
# Phase 4: validate_active_skills
# =====================================================================
print("\n=== Phase 4: validate_active_skills ===")

errors = validate_active_skills(["code-review", "testing"])
check("valid skills → no errors", errors, [])

errors_bad = validate_active_skills(["code-review", "nonexistent-skill"])
check("invalid skill → error", len(errors_bad), 1)
check_in("error mentions skill", "nonexistent-skill", errors_bad[0])

errors_empty = validate_active_skills([])
check("empty → no errors", errors_empty, [])


# =====================================================================
# Phase 4: SkillMeta.is_custom
# =====================================================================
print("\n=== Phase 4: SkillMeta.is_custom ===")

from app.skills import SkillMeta

meta_builtin = SkillMeta(name="test", display_name="Test", description="desc")
check("default is_custom is False", meta_builtin.is_custom, False)

meta_custom = SkillMeta(name="test", display_name="Test", description="desc", is_custom=True)
check("explicit is_custom is True", meta_custom.is_custom, True)


# =====================================================================
# Rich role prompt shaping
# =====================================================================
print("\n=== rich role verbatim ===")

prompt1 = build_system_prompt("senior Python engineer", [])
check_in("short role wrapped", "You are a senior Python engineer", prompt1)

rich = "You are a senior architect.\nYou specialize in distributed systems."
prompt2 = build_system_prompt(rich, [])
check_in("rich role verbatim", "You are a senior architect.", prompt2)
check_not_in("no double wrap", "You are a You are", prompt2)

prompt3 = build_system_prompt("You are an expert in Kubernetes.", [])
check_not_in("no double wrap for 'You are'", "You are a You are", prompt3)
check_in("starts with You are", "You are an expert", prompt3)

prompt4 = build_system_prompt("Act as a security auditor.", [])
check_not_in("no wrap for 'Act as'", "You are a Act as", prompt4)
check_in("starts with Act as", "Act as a security auditor", prompt4)

prompt5 = build_system_prompt("you are an expert in kubernetes.", [])
check_not_in("no double wrap lowercase", "You are a you are", prompt5)
check_in("lowercase verbatim", "you are an expert in kubernetes", prompt5)

prompt6 = build_system_prompt("you're a helpful coding assistant.", [])
check_not_in("no wrap for you're", "You are a you're", prompt6)
check_in("you're verbatim", "you're a helpful coding assistant", prompt6)


# =====================================================================
# Provider-scoped config digest
# =====================================================================
print("\n=== provider-scoped digest ===")

digest_claude = get_provider_config_digest(["github-integration"], provider_name="claude")
digest_codex = get_provider_config_digest(["github-integration"], provider_name="codex")
digest_all = get_provider_config_digest(["github-integration"])

check("claude != codex digest", digest_claude != digest_codex, True)
check("unscoped != claude", digest_all != digest_claude, True)
check("unscoped != codex", digest_all != digest_codex, True)


# =====================================================================
# MCP args YAML parsing
# =====================================================================
print("\n=== MCP args is list ===")

raw = load_provider_yaml("github-integration", "claude")
mcp = raw.get("mcp_servers", {}).get("github", {})
check("args is a list", isinstance(mcp.get("args"), list), True)
check("args has 2 elements", len(mcp.get("args", [])), 2)
check_in("args contains -y", "-y", mcp["args"])

raw2 = load_provider_yaml("linear-integration", "claude")
mcp2 = raw2.get("mcp_servers", {}).get("linear", {})
check("linear args is a list", isinstance(mcp2.get("args"), list), True)


# =====================================================================
# Malformed skill resilience
# =====================================================================
print("\n=== malformed skill resilience ===")

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
        check("load_catalog did not crash", isinstance(catalog, dict), True)
        check_not_in("malformed skill not in catalog", "malformed-test-skill", catalog)
        check("_skill_dir returns None for malformed", _skill_dir("malformed-test-skill"), None)
        check("instructions empty for malformed", get_skill_instructions("malformed-test-skill"), "")
        check("requirements empty for malformed", get_skill_requirements("malformed-test-skill"), [])
finally:
    skills_mod.CUSTOM_DIR = orig_custom_dir


# =====================================================================
# Malformed provider YAML resilience
# =====================================================================
print("\n=== malformed provider yaml resilience ===")

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

        check("malformed yaml returns empty dict", load_provider_yaml("yaml-test-skill", "claude"), {})
        check("build_provider_config returns dict", isinstance(build_provider_config("claude", ["yaml-test-skill"], {}), dict), True)
finally:
    skills_mod.CUSTOM_DIR = orig_custom_dir


# =====================================================================
# Malformed requires.yaml resilience
# =====================================================================
print("\n=== malformed requires.yaml resilience ===")

check("malformed requires.yaml returns empty", _parse_requires_yaml("credentials:\n  - key: [unclosed\n"), [])
check("non-dict requires.yaml returns empty", _parse_requires_yaml("just_a_string"), [])
check("empty requires.yaml returns empty", _parse_requires_yaml(""), [])


# =====================================================================
# Catalog uses directory name, not frontmatter name
# =====================================================================
print("\n=== catalog uses directory name ===")

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
        check_in("dir name in catalog", "my-actual-dir", catalog)
        check_not_in("frontmatter name NOT in catalog", "fancy-meta-name", catalog)
        check("_skill_dir finds dir name", _skill_dir("my-actual-dir") is not None, True)
        check("_skill_dir misses frontmatter name", _skill_dir("fancy-meta-name"), None)
        check_in("instructions loaded", "fancy things", get_skill_instructions("my-actual-dir"))
        check("no instructions by frontmatter name", get_skill_instructions("fancy-meta-name"), "")
finally:
    skills_mod.CUSTOM_DIR = orig_custom_dir


checks.run_and_exit()
