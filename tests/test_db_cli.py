from app.db.cli import _print_sanitized_failures


def test_print_sanitized_failures_redacts_sensitive_values(capsys, monkeypatch):
    monkeypatch.setenv("BOT_DATABASE_URL", "postgresql://bot:secret@example.com/bot")

    _print_sanitized_failures(
        ["Applying 0002_demo.sql: postgresql://bot:secret@example.com/bot refused connection"]
    )

    captured = capsys.readouterr()
    assert "secret@example.com" not in captured.err
    assert "<redacted-bot-database-url>" in captured.err or "bot:<redacted>@" in captured.err


def test_print_sanitized_failures_redacts_database_password_fragment(capsys, monkeypatch):
    monkeypatch.setenv("BOT_DATABASE_URL", "postgresql://bot:supersecret@db.example.com/bot")

    _print_sanitized_failures(
        ['Applying 0002_demo.sql: driver emitted password token "supersecret" directly']
    )

    captured = capsys.readouterr()
    assert "supersecret" not in captured.err
    assert "<redacted-bot-database-url>-password" in captured.err
