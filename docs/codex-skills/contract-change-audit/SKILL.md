---
name: contract-change-audit
description: Use when changing execution context, trust, approvals, retries, provider progress, doctor orchestration, or any cross-cutting contract. Audits source of truth, equivalent paths, failure paths, and invariants before code changes.
---

# Contract Change Audit

Use this skill for any change that touches a cross-cutting runtime
contract.

## When to use

- execution identity or resolved context
- trust/public mode
- approvals or retries
- provider progress or user-visible error formatting
- health/doctor orchestration
- any feature likely to drift across multiple entry points

## Workflow

1. **State the contract being changed**
   - what user-visible or safety-sensitive rule is changing?
   - if analysis finds multiple failure modes, split them into
     separate contracts before proposing a fix

2. **Identify the authoritative source**
   - resolved context
   - one builder / one orchestrator
   - one health collector
   - one renderer

3. **Enumerate all equivalent paths with `rg`**
   - message
   - command
   - callback
   - admin
   - CLI
   - approval
   - retry

4. **Audit raw vs resolved reads**
   - replace raw state reads in safety-sensitive or user-visible logic
     unless they are intentionally persistence-only

5. **List failure paths**
   - timeout
   - interrupt
   - stale callback
   - exception
   - duplicate delivery
   - restart-in-the-middle
   - recovery path interrupted again
   - fix introduces a new failure mode in the same state machine

6. **Define invariants**
   - same resolved context => same identity
   - changed sensitive field => stale invalidation
   - equivalent ingress paths obey the same rule
   - explicit completion owner for each durable outcome
   - reset/invalidation path only fires on typed evidence, not generic
     failure

7. **Add tests**
   - focused contract test
   - real entry-point test
   - adjacent regression test
   - false-positive boundary test for any classification or reset logic
   - user-visible oracle check: assert on the object the user actually
     sees

## Completion Bar

Do not call the work complete until:

- all equivalent paths were checked
- the authoritative source is the only source
- interacting bugs were split into independent fixes and verifications
- the completion owner is explicit for durable outcomes
- at least one direct repro and one adjacent regression repro were
  rerun
