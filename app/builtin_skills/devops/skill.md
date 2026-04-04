---
name: devops
display_name: DevOps
description: Infrastructure, CI/CD, deployment
---
When working on infrastructure and deployment, follow these guidelines:

- Make infrastructure changes incremental and reversible. Avoid big-bang migrations.
- CI pipelines should be fast, deterministic, and fail with clear error messages.
- Use environment variables or secret managers for credentials — never hardcode them.
- Containerize with minimal base images. Pin dependency versions for reproducibility.
- Health checks and readiness probes should verify actual service functionality.
- Log structured data (JSON) with correlation IDs for traceability across services.
- Automate rollback procedures and test them before you need them.
- Keep deployment manifests version-controlled alongside application code.
