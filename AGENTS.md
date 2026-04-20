# Agent instructions (Octopus / telegram-agent-bot)

## Feature work constraints

When adding new features or extending existing ones:

- **Do not** introduce parallel code paths, backward-compatibility shims, or redundant implementations for the same capability. One coherent pipeline; extend it in place.
- **File size, module size, and LOC** are not primary success criteria. Prefer clarity, one obvious path, and maintainability over splitting or compressing code for its own sake.

## Architecture

Package boundaries and system design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
