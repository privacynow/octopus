# Contributing

This repository favors one coherent implementation path over compatibility
shims or duplicated flows. Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
before changing package boundaries or protocol behavior.

## Local Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -c constraints.txt -r requirements.txt -r requirements-dev.txt
```

The fast publication gate is:

```bash
.venv/bin/python -m pytest -q tests/test_protocol_docs.py tests/test_startup_diagnostics.py tests/test_octopus_cli.py tests/test_octopus_cli_manager.py tests/test_registry_service.py::test_registry_openapi_asset_matches_generated_schema
```

Run broader suites for behavior you touch. Registry/browser/provider work also
needs a configured local Octopus deployment and live UI verification.

## Expectations

- Keep source changes separate from generated `.deploy/`, `.tmp/`, venv, cache,
  and test-output files.
- Update `docs/registry-openapi.json` when route contracts change.
- Update architecture and documentation guard tests when public docs or package
  boundaries change.
- Do not commit credentials, provider auth state, Telegram bot tokens, or local
  workspace paths.
