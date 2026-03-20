from pathlib import Path


def test_readme_centers_octopus_as_primary_command():
    repo = Path(__file__).resolve().parent.parent
    text = (repo / "README.md").read_text()
    assert "./octopus" in text
    assert "The primary command is" in text
    assert "guided start" not in text.lower()


def test_readme_covers_first_time_setup_and_registry_ui():
    repo = Path(__file__).resolve().parent.parent
    text = (repo / "README.md").read_text()
    assert "@BotFather" in text
    assert "./octopus --full" in text
    assert "./octopus registry" in text
    assert "Registry UI" in text
    assert "registry-ui-screenshot.png" in text


def test_readme_keeps_daily_commands_simple():
    repo = Path(__file__).resolve().parent.parent
    text = (repo / "README.md").read_text()
    assert "./octopus status" in text
    assert "./octopus logs" in text
    assert "./octopus doctor" in text
    assert "/doctor" in text
