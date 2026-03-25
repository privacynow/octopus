"""Approval flow data shaping. No channel I/O — pure functions only."""


def build_preflight_prompt(user_prompt: str, provider_name: str) -> str:
    return (
        f"Preflight this user request for a bot that runs {provider_name} CLI.\n"
        "Do not modify files. Do not run shell commands.\n"
        "Respond briefly in Markdown with these sections exactly:\n"
        "## Tool use\n"
        "- whether shell commands are likely needed\n"
        "- whether file edits are likely needed\n"
        "- whether risky actions are likely needed\n"
        "## Planned actions\n"
        "- short bullets\n"
        "## Approval advice\n"
        "- Approve or Reject / ask for clarification\n\n"
        f"User request:\n{user_prompt}"
    )
