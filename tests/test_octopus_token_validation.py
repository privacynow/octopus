from __future__ import annotations

import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def _run_bash(script: str, *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-lc", script],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )


def test_telegram_token_format_valid_accepts_telegram_shape(tmp_path: Path) -> None:
    script = f"""
set -euo pipefail
source "{REPO}/scripts/lib/bot.sh"
telegram_token_format_valid '123456:Abc_DEF-ghi'
! telegram_token_format_valid 'not-a-token'
! telegram_token_format_valid '123456'
"""
    _run_bash(script, cwd=tmp_path)


def test_validate_telegram_token_returns_identity_triple_without_token_in_python_argv(tmp_path: Path) -> None:
    fake_python = tmp_path / "python3"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" > argv.txt\n"
        "cat > stdin.txt\n"
        "printf '123456789\\nmy_support_bot\\nMy Support Bot\\n'\n"
    )
    fake_python.chmod(0o755)

    script = f"""
set -euo pipefail
export PATH="{tmp_path}:$PATH"
source "{REPO}/scripts/lib/bot.sh"
result="$(validate_telegram_token '123456:super-secret-token')"
printf '%s\\n' "$result"
"""
    result = _run_bash(script, cwd=tmp_path)

    assert result.stdout.splitlines() == ["123456789", "my_support_bot", "My Support Bot"]
    assert "super-secret-token" not in (tmp_path / "argv.txt").read_text()
    assert (tmp_path / "stdin.txt").read_text() == "123456:super-secret-token"


def test_validate_telegram_token_returns_nonzero_for_rejected_token(tmp_path: Path) -> None:
    fake_python = tmp_path / "python3"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "cat >/dev/null\n"
        "exit 1\n"
    )
    fake_python.chmod(0o755)

    script = f"""
set -euo pipefail
export PATH="{tmp_path}:$PATH"
source "{REPO}/scripts/lib/bot.sh"
if validate_telegram_token '123456:bad-token' >validate.out 2>validate.err; then
  exit 1
fi
test ! -s validate.out
"""
    _run_bash(script, cwd=tmp_path)


def test_validate_telegram_token_does_not_leak_token_into_process_args(tmp_path: Path) -> None:
    fake_python = tmp_path / "python3"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "cat >/dev/null\n"
        "sleep 1\n"
        "printf '1\\nexample_bot\\nExample Bot\\n'\n"
    )
    fake_python.chmod(0o755)

    script = f"""
set -euo pipefail
export PATH="{tmp_path}:$PATH"
source "{REPO}/scripts/lib/bot.sh"
printf '123456:LEAK_CHECK_TOKEN' > token.txt
(
  token="$(cat token.txt)"
  validate_telegram_token "$token" >/dev/null 2>&1
) &
job_pid=$!
sleep 0.2
if ps ax -o command= | grep -F 'LEAK_CHECK_TOKEN' | grep -v grep >ps_hits.txt; then
  cat ps_hits.txt >&2
  exit 1
fi
wait "$job_pid"
"""
    _run_bash(script, cwd=tmp_path)
