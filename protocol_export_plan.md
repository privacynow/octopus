# Protocol And Skill Export/Import Plan

This document is the execution plan for protocol and skill portability. It
captures the decisions from the design discussion and turns them into an
implementation path that fits the current Octopus architecture.

## Context

Octopus currently has two related but separate export/import concepts:

- Protocol drafts can be parsed/exported as JSON or YAML through Registry and
  SDK protocol APIs.
- Skills are currently exported/imported as ZIP archives that contain a virtual
  text file tree: `skill.md`, `requires.yaml`, provider config files, and
  optional extra files.

The ZIP skill package format is implemented in the SDK, mainly in
`octopus_sdk/skill_packages.py`, and called by runtime skill authoring and
management bridge paths. The format is therefore in the correct architectural
layer, but it is the wrong product shape for the next portability feature.

The target feature is not a loose collection of files. It is a single portable
protocol package document that contains:

- the protocol definition,
- the skills required by the protocol,
- mapping hints for source agents/stage assignments,
- normalized hashes and import planning metadata.

The import must be safe to repeat, must not silently overwrite meaningful user
content, and must not create parallel code paths for protocol or skill behavior.

## Decisions

These decisions are binding for this implementation.

1. Remove ZIP skill packages.

   No backwards compatibility path, compatibility shim, dual parser, ZIP import
   fallback, or lingering product surface should remain. This is a migration,
   not a second supported format.

2. Replace skill ZIP packages with SDK-owned JSON/YAML skill documents.

   The SDK remains the canonical owner for skill package validation,
   normalization, hashing, parsing, and rendering. Registry, Telegram, and
   future clients should call SDK workflows rather than parse ad hoc shapes.

3. Protocol package export is a single JSON/YAML document.

   A protocol package embeds the protocol document and the required skill
   documents. Do not emit a protocol ZIP that contains nested skill ZIPs.

4. Support JSON and YAML at export/import time.

   JSON is the canonical machine representation for normalized hashing. YAML is
   an operator-friendly rendering. Both parse into the same SDK records.

5. Export one protocol at a time.

   Do not add a product-level "export all protocols" feature. Bulk export is a
   backup/snapshot concern with different conflict semantics. Acceptance tests
   may use a helper that lists protocols and calls the one-protocol export API
   repeatedly.

6. Skills are idempotent dependencies by name and normalized content hash.

   Do not create duplicate skill copies such as `review-skill-copy-2` by
   default. A skill name represents a reusable dependency.

7. Protocol imports support conflict choices.

   If a protocol with the same slug already exists, import planning should warn
   and allow the operator to:

   - fail/cancel,
   - overwrite the existing protocol draft,
   - import as a separate copy with a generated or user-provided slug/name.

8. "Import as copy" is not a protocol version.

   In the current data model, "version" means a published protocol definition
   version. A separate imported protocol should be called a copy, not a new
   version. Suggested default naming:

   - slug: `manufacturing-intelligence-copy-2`
   - display name: `Manufacturing Intelligence (Imported 2)`

9. Agent ids are not portable dependencies.

   Exported source agent ids may appear only as hints. Import must map source
   stage assignments to local bots explicitly or through deterministic selector
   resolution. Provider auth, agent tokens, and deployment-specific ids must not
   be included.

10. Do not apply skills to every bot by default.

    Installing every required skill on every bot can make current skill
    selector resolution ambiguous. Import should apply skills to chosen/mapped
    target bots and pin selectors where needed.

11. Import is plan-first.

    The first operation should parse and validate the package, compare local
    protocol/skill/agent state, and return a plan. Mutating import apply should
    require explicit choices from that plan.

12. Publish is explicit.

    Import should create or update drafts by default. Publishing an imported
    protocol requires an explicit option and must only proceed if validation,
    skill application, and stage assignment resolution are clean.

## Current Architecture To Extend

The implementation must extend existing boundaries rather than introduce a
parallel path.

Relevant current files:

- `octopus_sdk/skill_packages.py`
  - currently owns ZIP skill parsing/building and should be replaced with
    JSON/YAML skill package document parsing/rendering.
- `octopus_sdk/workflows/runtime_skill_authoring.py`
  - currently exports/imports skill package archives and should export/import
    skill package documents.
- `octopus_sdk/registry/management.py`
  - currently defines `ExportCatalogSkillPackageRequest` and
    `ImportCatalogSkillPackageRequest` with ZIP-oriented payloads.
- `octopus_sdk/registry/management_executor.py`
  - executes skill export/import management requests inside the bot runtime.
- `octopus_registry/ingress.py`
  - sends skill management operations from Registry to connected agents.
- `octopus_registry/protocol_http.py`
  - currently exposes protocol parse/export routes.
- `octopus_registry/protocol_store.py`
  - currently owns protocol document parse/export, draft mutation, publish, run
    creation, and selector projection.
- `octopus_sdk/protocols/models.py`
  - current protocol document models live here and new protocol package/import
    records should also live here or in a sibling SDK module under
    `octopus_sdk/protocols/`.
- `octopus_sdk/protocols/documents.py`
  - current protocol JSON/YAML parse/render/validation helpers live here.
- `octopus_registry/store_shared/agents.py`
  - current selector resolution behavior lives here. Import mapping must respect
    that ambiguity behavior.
- `docs/PROTOCOL_ASSIGNMENT_AUDIT.md`
  - assignment belongs to the stage; `stage.selector` is canonical.
- `docs/SKILLS_MODEL.md`
  - skill state layers and product nouns.

Key current model facts:

- Canonical authored stage assignment is `stage.selector`.
- `stage.selector.kind` is currently `agent`, `skill`, or `role`.
- Skill selectors may use `preferred_agent_id` as a runtime hint.
- Current selector resolution fails if a selector matches multiple agents and
  no preferred agent is pinned.
- Skills have distinct state layers:
  - catalog,
  - available on this bot,
  - default for new conversations,
  - active in this conversation,
  - routing skills.

## Target Document Formats

### Skill Package Document

Replace ZIP archives with a structured document:

```yaml
schema_version: 1
kind: octopus.skill
skill:
  name: code-review
  display_name: Code Review
  description: Review code for correctness and maintainability.
  skill_kind: prompt
  body: |
    Review the code and prioritize correctness, regressions, and missing tests.
  requirements: []
  provider_config:
    codex: {}
    claude: {}
  files:
    - path: scripts/check.sh
      content_type: text/x-shellscript
      executable: true
      content: |
        #!/usr/bin/env sh
        exit 0
metadata:
  exported_at: "2026-05-01T00:00:00+00:00"
  source: registry
  normalized_hash: sha256:...
```

Rules:

- All content is text.
- Paths must be safe relative POSIX paths.
- Reserved conceptual files from the old ZIP shape become structured fields:
  - `skill.md` becomes `skill.body` plus metadata fields.
  - `requires.yaml` becomes `skill.requirements`.
  - provider config files become `skill.provider_config`.
  - extra files remain in `skill.files`.
- Existing skill package limits should still apply unless intentionally changed:
  - max file count,
  - max per-file text size,
  - max total text size,
  - executable allowed only for `.sh`.
- Normalized hash is computed from canonical JSON after validation and
  normalization, not from raw JSON/YAML text.

### Protocol Package Document

New portable protocol package shape:

```yaml
schema_version: 1
kind: octopus.protocol_package
protocol:
  schema_version: 1
  metadata:
    slug: manufacturing-intelligence
    display_name: Manufacturing Intelligence
    description: Build and validate an offline analytics package.
  participants: []
  artifacts: []
  stages: []
  policies: {}
skills:
  - schema_version: 1
    kind: octopus.skill
    skill:
      name: manufacturing-local-analytics
      display_name: Manufacturing Local Analytics
      description: ...
      skill_kind: prompt
      body: |
        ...
      requirements: []
      provider_config: {}
      files: []
bindings:
  source_agents:
    - source_agent_key: source-agent-1
      source_agent_id: 08fa610fd7fde5bdb16e77cf8c55c2b4
      slug: lift-and-shift-m1-bot
      display_name: M1
      provider: codex
      role: agent
      advertised_skills:
        - manufacturing-local-analytics
  stage_bindings:
    - stage_key: prepare-executive-review
      selector:
        kind: skill
        value: manufacturing-local-analytics
        preferred_agent_id: 08fa610fd7fde5bdb16e77cf8c55c2b4
      source_agent_key: source-agent-1
      required_skills:
        - manufacturing-local-analytics
metadata:
  exported_at: "2026-05-01T00:00:00+00:00"
  source_registry: local
  protocol_hash: sha256:...
  package_hash: sha256:...
```

Rules:

- `protocol` is the existing protocol definition document shape.
- `skills` embeds full skill package documents.
- `bindings.source_agents` are hints only.
- `bindings.stage_bindings` records how the source environment resolved or
  intended stage routing.
- No credentials, agent tokens, UI tokens, provider auth, local Docker paths, or
  run artifacts are included.
- Run export/archive is a separate future feature and must not be mixed into
  protocol package portability.

## Import Semantics

Import has two steps:

1. Plan
2. Apply

### Plan

Plan parses the package, validates documents, compares local state, and returns
an explicit set of choices/warnings. It does not mutate.

The plan must report:

- protocol identity:
  - package slug,
  - display name,
  - normalized protocol hash,
  - whether a local protocol with the same slug exists,
  - whether content is identical to an existing draft/current version,
  - available conflict policies.
- skills:
  - each embedded skill name,
  - package hash,
  - whether the skill exists on each relevant local bot,
  - whether content is identical,
  - whether local draft/published content differs,
  - whether provider/credential requirements are present or missing.
- agent/stage mapping:
  - each source stage selector,
  - current local resolution candidates,
  - missing mappings,
  - ambiguous mappings,
  - suggested target bot when deterministic.
- publish readiness:
  - validation status,
  - blocking issues,
  - whether all selectors resolve exactly.

### Apply

Apply takes the plan plus user choices and mutates in this order:

1. Apply/import skills to selected target bots through the existing management
   bridge.
2. Rewrite protocol stage selectors according to mapping decisions.
3. Create or update the protocol draft according to the protocol conflict
   policy.
4. Optionally publish if explicitly requested and all validation checks pass.

Apply must be idempotent:

- identical skill import is a no-op,
- identical protocol overwrite is a no-op,
- repeated import-as-copy with the same requested copy slug should be a no-op
  if content matches,
- repeated import-as-copy without a requested slug should generate the next
  available copy slug only when a new copy is actually requested.

## Protocol Conflict Policies

The import plan/apply flow should support these protocol policies:

1. `fail_if_exists`

   If the target slug exists, return a blocking plan issue or apply error.
   Useful for CI, strict scripting, or operators who want no implicit overwrite.

2. `overwrite_existing`

   Update the existing protocol draft for the target slug/protocol id.

   Semantics:

   - If normalized imported content equals the current draft, no-op.
   - If normalized imported content differs, update the draft revision.
   - Do not delete published history.
   - Publishing after overwrite creates the next published version through the
     existing publish path.

3. `import_copy`

   Create a separate protocol definition with a generated or user-specified
   slug/display name.

   Semantics:

   - Default generated slug should use `-copy-N`, not `-vN`.
   - Default generated display name should use `(Imported N)` or `(Copy N)`.
   - If the requested copy slug exists with identical content, no-op.
   - If the requested copy slug exists with different content, require another
     choice.

Do not call copied imports "versions" in UI or API copy. The data model already
uses versions for published protocol definition versions.

## Skill Conflict Policies

Skills are reusable dependencies and should not support duplicate copies by
default.

Skill import policy should be:

- Missing skill on target bot: create/import draft or published-available state
  according to the existing lifecycle decision.
- Existing skill with identical normalized hash: no-op.
- Existing skill with same name but different content:
  - plan warns,
  - apply updates the skill draft/current imported content only after explicit
    confirmation,
  - published/runtime availability should follow the existing skill lifecycle
    rules.

Questions to settle during implementation:

- Should protocol package import automatically publish imported skill drafts, or
  should skill publish remain a separate operator action?
- If an imported protocol is requested to publish immediately, should apply also
  publish/import skills automatically when safe?

Recommended default:

- Import skills as drafts or update drafts.
- Mark protocol as not publish-ready until required skills are available on the
  mapped target bots.
- Add an explicit "apply skills and make available" choice in the import apply
  request if the current skill lifecycle supports it cleanly.

## Agent Mapping Semantics

Agent handling is the riskiest part because agents are runtime/deployment state,
not portable package content.

### Export

Export should include source-agent hints:

- source agent id,
- slug/display name,
- provider,
- role,
- advertised skills,
- stages that referenced it directly or through `preferred_agent_id`.

These hints are not authoritative on import.

### Import Planning

For each stage:

1. If selector is `skill`:

   - If a mapped target bot is supplied for the source agent/stage, plan to
     apply the skill to that bot and set `preferred_agent_id`.
   - Else if exactly one connected local bot currently satisfies the skill,
     suggest that bot and mark it auto-resolvable.
   - Else if no local bot satisfies the skill, require a target bot choice.
   - Else if multiple local bots satisfy the skill, require a target bot choice
     or keep unpinned only if the operator accepts ambiguous future resolution.

2. If selector is `agent`:

   - Treat source agent id as non-portable.
   - Try matching by explicit operator mapping first.
   - Then by stable hints such as slug/display name/provider/role if unique.
   - If not unique, require mapping.

3. If selector is `role`:

   - Preview local role resolution.
   - If unique, allow import.
   - If ambiguous/missing, require mapping or leave draft unpublished.

### Apply

Recommended default after successful mapping:

- For skill selectors, preserve `kind: skill` and set
  `preferred_agent_id` when the import plan chose a specific bot.
- For direct agent selectors, rewrite to the mapped local `agent_id`.
- If no mapping is supplied for a required stage, keep the protocol as draft and
  return validation issues rather than guessing.

## Public API Plan

Names can be refined, but these are the intended API capabilities.

### Protocol Package Export

`GET /v1/protocols/{protocol_id}/package/export?format=json|yaml&revision=draft|published`

Response:

```json
{
  "format": "json",
  "file_name": "manufacturing-intelligence.octopus-protocol.json",
  "content_type": "application/json",
  "text": "{...}",
  "package": {...},
  "validation": {...},
  "warnings": []
}
```

Behavior:

- Exports one protocol.
- Uses current protocol draft/published version according to `revision`.
- Determines referenced skills.
- Exports required skill documents by invoking the existing management bridge
  export operation against relevant source agents.
- Fails with a clear warning if a required skill cannot be exported, cannot be
  found, or differs across candidate source agents without a source selection.

### Protocol Package Import Plan

`POST /v1/protocols/package/import/plan`

Request:

```json
{
  "format": "yaml",
  "text": "...",
  "target_org_id": "local"
}
```

Response:

```json
{
  "ok": false,
  "package_hash": "sha256:...",
  "protocol": {
    "slug": "manufacturing-intelligence",
    "exists": true,
    "identical_to_existing": false,
    "available_policies": ["overwrite_existing", "import_copy", "fail_if_exists"]
  },
  "skills": [
    {
      "name": "manufacturing-local-analytics",
      "status": "different_content",
      "targets": []
    }
  ],
  "stage_mappings": [
    {
      "stage_key": "prepare-executive-review",
      "status": "requires_mapping",
      "candidates": []
    }
  ],
  "blocking_issues": [],
  "warnings": []
}
```

### Protocol Package Import Apply

`POST /v1/protocols/package/import/apply`

Request:

```json
{
  "format": "yaml",
  "text": "...",
  "protocol_policy": "overwrite_existing",
  "copy_slug": "",
  "copy_display_name": "",
  "skill_policy": "update_drafts",
  "stage_mappings": [
    {
      "stage_key": "prepare-executive-review",
      "target_agent_id": "08fa610fd7fde5bdb16e77cf8c55c2b4",
      "pin_preferred_agent": true
    }
  ],
  "publish": false,
  "idempotency_key": "..."
}
```

Response:

```json
{
  "ok": true,
  "status": "applied",
  "protocol": {...},
  "created_protocol": false,
  "updated_protocol": true,
  "skill_results": [],
  "mapping_results": [],
  "validation": {...}
}
```

## SDK Implementation Plan

### Phase 1: Replace Skill Package Documents

Files:

- `octopus_sdk/skill_packages.py`
- `octopus_sdk/workflows/runtime_skill_authoring.py`
- `octopus_sdk/workflows/skills.py`
- `octopus_sdk/registry/management.py`
- `octopus_sdk/registry/management_executor.py`
- `octopus_registry/ingress.py`
- `app/workflows/runtime_skills/telegram.py`
- skill package tests and fixtures.

Tasks:

1. Replace ZIP-specific helpers:

   Remove:

   - `build_skill_package_archive`
   - `parse_skill_package_archive`
   - ZIP-specific names/content types from public flow records.

   Add:

   - `SkillPackageDocumentRecord`
   - `skill_document_from_track(track)`,
   - `skill_document_to_text(document, format)`,
   - `skill_document_from_text(text, format)`,
   - `normalize_skill_document(document)`,
   - `skill_document_hash(document)`.

2. Preserve existing validation constraints:

   - safe relative paths,
   - file count limits,
   - byte/text size limits,
   - provider config parsing,
   - requirements parsing/coercion,
   - executable only for shell scripts.

3. Update runtime skill authoring:

   - export returns document text/artifact metadata,
   - import accepts document text and format,
   - lifecycle mutation behavior remains otherwise unchanged.

4. Update management protocol:

   Replace ZIP/base64 fields with:

   - `format`,
   - `document_text`,
   - `file_name` optional,
   - `target_skill_name` optional.

5. Update Telegram runtime skill commands:

   - `/skills export <name> [json|yaml] [draft|published]`
   - `/skills import` accepts attached/pasted JSON/YAML document text.

   Exact UX can be refined, but no ZIP wording should remain.

6. Remove ZIP wording from presenters/docs/tests.

7. Update tests:

   - JSON skill document round trip,
   - YAML skill document round trip,
   - same normalized hash across equivalent JSON/YAML,
   - invalid path rejection,
   - size/file count validation,
   - import existing identical skill is no-op,
   - import existing changed skill updates draft with explicit policy.

### Phase 2: Add Protocol Package SDK Records

Files:

- `octopus_sdk/protocols/models.py`
- `octopus_sdk/protocols/documents.py`
- possibly new `octopus_sdk/protocols/packages.py`.

Tasks:

1. Add records:

   - `ProtocolPackageDocumentRecord`
   - `ProtocolPackageMetadataRecord`
   - `ProtocolPackageBindingsRecord`
   - `ProtocolPackageSourceAgentRecord`
   - `ProtocolPackageStageBindingRecord`
   - `ProtocolPackageValidationRecord`
   - `ProtocolPackageImportPlanRecord`
   - `ProtocolPackageImportApplyRequestRecord`
   - `ProtocolPackageImportApplyResultRecord`
   - `ProtocolPackageSkillPlanRecord`
   - `ProtocolPackageStageMappingPlanRecord`

2. Add helpers:

   - `protocol_package_to_text(package, format)`
   - `protocol_package_from_text(text, format)`
   - `normalize_protocol_package(package)`
   - `protocol_package_hash(package)`
   - `protocol_package_required_skill_names(protocol_document)`

3. Ensure protocol package validation calls existing protocol document
   validation and skill document validation.

4. Ensure canonical hashes are stable across JSON/YAML renderings.

### Phase 3: Registry Protocol Package Export

Files:

- `octopus_registry/protocol_http.py`
- `octopus_registry/protocol_store.py`
- `octopus_registry/store_base.py`
- `octopus_registry/store_postgres.py`
- `octopus_sdk/registry/client.py`
- SDK protocol ports/contracts.

Tasks:

1. Add store/port method:

   - `export_protocol_package(protocol_id, format, revision, access, source_agent_overrides=...)`

2. Implement protocol document selection:

   - `revision=draft`: use current draft document.
   - `revision=published`: use current published version.

3. Determine required skills:

   - all `stage.selector.kind == "skill"` values,
   - legacy/canonicalized participant required skills where still present,
   - any additional skill requirements introduced by protocol package metadata.

4. Find source agents for skill export:

   - use stage bindings/preferred agent hints where available,
   - otherwise find connected agents advertising the skill,
   - if exactly one candidate has/exportable skill, use it,
   - if multiple candidates differ, fail with a source-agent selection warning,
   - if no candidate can export, fail with a missing skill warning.

5. Export each skill by invoking management bridge export.

   Do not read bot-local content tables from Registry.

6. Build source-agent and stage-binding hints.

7. Return a single protocol package document as JSON/YAML text.

8. Update OpenAPI and SDK client tests.

### Phase 4: Registry Protocol Package Import Plan

Files:

- `octopus_registry/protocol_http.py`
- `octopus_registry/protocol_store.py`
- `octopus_registry/store_base.py`
- `octopus_registry/store_postgres.py`
- `octopus_registry/ingress.py`
- `octopus_registry/store_shared/agents.py` if helper extraction is needed.

Tasks:

1. Add parse/plan endpoint.

2. Parse package text using SDK package parser.

3. Validate embedded protocol and skills.

4. Compare protocol:

   - same slug exists?
   - identical to draft?
   - identical to current published version?
   - draft differs?
   - lifecycle state archived?

5. Compare skills against target agents:

   - if mapping supplied, compare on mapped bot,
   - if no mapping, evaluate candidates using selector preview/agent list,
   - determine no-op/create/update/conflict.

6. Plan stage mappings:

   - determine auto-resolvable mappings,
   - identify ambiguous/missing mappings,
   - identify direct agent selector rewrites needed.

7. Return blocking issues for:

   - invalid package,
   - invalid protocol document,
   - invalid skill document,
   - missing target bot for required stage,
   - ambiguous source/target mapping without user choice,
   - unsupported protocol conflict policy.

8. Do not mutate.

### Phase 5: Registry Protocol Package Import Apply

Tasks:

1. Add apply endpoint with idempotency key support.

2. Recompute the plan server-side from submitted package text and choices.

   Do not trust a client-supplied plan as authoritative.

3. Validate choices:

   - protocol policy,
   - target agent mappings,
   - skill policy,
   - publish flag.

4. Apply skills first:

   - call management bridge import for each skill on chosen target bots,
   - skip identical no-op imports,
   - update drafts only when policy allows,
   - collect per-skill results.

5. Rewrite protocol selectors:

   - direct agent selector: replace with mapped local `agent_id`,
   - skill selector with mapped target: preserve skill selector and set
     `preferred_agent_id`,
   - role selector: preserve if uniquely resolvable or mapped policy allows.

6. Apply protocol policy:

   - `fail_if_exists`
   - `overwrite_existing`
   - `import_copy`

7. Use existing draft mutation machinery.

   Do not write protocol definitions through a separate raw SQL path unless the
   existing store API cannot support the required operation. If new store
   methods are needed, they must still use the same canonical protocol mutation
   application logic used by the UI editor.

8. Publish only if requested and validation passes.

9. Return detailed result:

   - no-op/create/update/copy status,
   - protocol id/slug,
   - skill results,
   - mapping decisions,
   - validation status,
   - warnings.

### Phase 6: Registry UI

Files:

- `octopus_registry/ui/js/components/protocol-workspace.js`
- `octopus_registry/ui/js/api.js`
- `octopus_registry/ui/css/main.css`
- UI contract tests.

Tasks:

1. Add export action in protocol detail/editor.

   Options:

   - format: JSON or YAML,
   - revision: draft or published package,
   - export one protocol only.

2. Add import flow.

   It can be a modal or dedicated route. It must support:

   - paste/upload JSON/YAML,
   - parse/plan preview,
   - protocol conflict choice,
   - skill no-op/update/create preview,
   - agent/stage mapping selection,
   - final apply.

3. Avoid internal jargon in UI copy.

   Use:

   - Import as copy,
   - Overwrite draft,
   - Required skill,
   - Choose bot,
   - Ready to publish,
   - Needs mapping.

4. Do not expose raw `stage_key` as primary copy unless there is no better
   stage display name. Stage key can appear in technical detail rows.

5. Ensure narrow UI handles import plan tables/cards.

### Phase 7: Telegram/CLI Cleanup

Tasks:

1. Update Telegram `/skills export` and `/skills import` around JSON/YAML skill
   documents.

2. Decide whether Telegram should expose protocol package import/export.

   Recommendation: not initially. Protocol authoring/import is a Registry UI
   operator workflow. Telegram can keep run/inspect/control behavior.

3. CLI helper may be useful for acceptance:

   - export one protocol,
   - import plan,
   - import apply with a mapping file.

   But the Registry API/UI should be the product surface.

## No Backwards Compatibility Cleanup List

Remove or rewrite all ZIP-specific product and code concepts:

- `build_skill_package_archive`
- `parse_skill_package_archive`
- `*.skill.zip` file names
- `application/zip` skill package content type
- `package_base64` for skill import
- Telegram copy that says "Attach ZIP"
- tests that parse skill ZIP archives
- fixtures using ZIP skill packages
- docs describing skill package ZIPs

Do not leave deprecated aliases unless a test proves they are internal-only and
will be removed in the same branch. The intended end state has no ZIP skill
package implementation.

## Acceptance Tests

### SDK Unit Tests

- Skill JSON round trip preserves normalized document.
- Skill YAML round trip preserves normalized document.
- Equivalent JSON/YAML skill documents have the same normalized hash.
- Protocol package JSON round trip preserves normalized document.
- Protocol package YAML round trip preserves normalized document.
- Equivalent JSON/YAML protocol packages have the same normalized package hash.
- Invalid skill file paths are rejected.
- Oversized skill documents are rejected.
- Missing embedded required skills are detected.
- Invalid protocol package kind/schema version is rejected.

### Registry Store/API Tests

- Existing protocol draft export still works as protocol-document export if the
  route remains, but package export returns the composed package document.
- Protocol package export includes every required skill exactly once.
- Protocol package export fails clearly when a required skill cannot be found.
- Protocol package export fails clearly when two candidate source agents expose
  the same skill name with different content and no source choice was supplied.
- Import plan detects existing identical protocol.
- Import plan detects existing different protocol.
- Import plan detects missing target bot mapping.
- Import plan detects ambiguous skill selector mapping.
- Import apply `overwrite_existing` is idempotent for identical content.
- Import apply `overwrite_existing` updates draft for different protocol
  content.
- Import apply `import_copy` creates a distinct protocol with generated copy
  slug.
- Import apply `import_copy` with an existing identical requested copy slug is a
  no-op.
- Import apply does not publish unless requested.
- Import apply refuses publish when mapping/selector validation is not clean.

### Skill Workflow Tests

- Export custom skill as JSON/YAML document.
- Import identical skill document is no-op.
- Import same skill name with changed content warns in plan and updates draft
  only when policy allows.
- Skill import through management bridge reaches the bot runtime and updates the
  same store/lifecycle path as the existing UI skill editor.

### UI Contract Tests

- Protocol export action calls package export endpoint.
- Protocol import UI requires plan before apply.
- Existing protocol warning is visible.
- Skill conflict/no-op/update rows are visible.
- Agent mapping choices are visible for ambiguous/missing stages.
- Narrow import plan layout has no horizontal overflow.

### Live Acceptance Scenario

Run against the current local Registry with existing protocols.

1. List protocols.
2. Export each protocol one at a time as JSON.
3. Export each protocol one at a time as YAML.
4. For each exported package, import plan into the same Registry.
5. Confirm plan warns that the protocol already exists.
6. Confirm embedded skills are no-op or update-required by normalized hash.
7. Apply `overwrite_existing` to the same protocol.
8. Confirm identical overwrite is idempotent.
9. Apply `import_copy`.
10. Confirm a distinct protocol copy is created with copy naming, not version
    naming.
11. Validate copied protocol.
12. Map stages to available bots where needed.
13. Publish only after validation/mapping is clean.
14. Start a run from the imported copy and verify stage routing works.

Do not add a product "export all protocols" action for this test. Use a test
helper or script that loops over the one-protocol export endpoint.

## Implementation Order

1. Add SDK skill document models and JSON/YAML parse/render/hash helpers.
2. Refactor skill authoring and management protocol away from ZIP/base64.
3. Update skill tests, Telegram skill commands, and docs to remove ZIP.
4. Add SDK protocol package models and parse/render/hash helpers.
5. Add Registry protocol package export.
6. Add protocol import plan endpoint.
7. Add protocol import apply endpoint.
8. Add Registry UI export/import flow.
9. Add live acceptance script/helper that exports/imports protocols one at a
   time.
10. Run full targeted tests and live acceptance.

## Engineering Constraints

- Keep one coherent pipeline.
- Do not introduce parallel ZIP and JSON/YAML skill paths.
- Shared parsing, validation, hashing, and package records belong in SDK.
- Registry composes protocol packages and coordinates management operations.
- Bot runtime owns actual skill catalog mutation.
- Registry must not read bot-local skill tables directly.
- Import apply must recompute/validate the plan server-side.
- No credentials or provider auth may enter exported documents.
- No destructive cleanup or overwrite happens without an explicit import apply
  policy.

## Implementation Defaults

These defaults are part of the first implementation. Do not leave them as
implicit product questions in code.

1. Imported skills are drafts by default.

   Protocol package import should create/update required skills as drafts on
   mapped target bots. It should not silently make skills available for runtime
   use unless the apply request explicitly asks for that behavior and the
   caller is allowed to do it.

   Add an explicit apply option such as:

   - `skill_availability_policy: draft_only`
   - `skill_availability_policy: make_available`

   The UI default is `draft_only`. Immediate protocol publish is blocked until
   required skills are available on the mapped bots.

2. Protocol export defaults to the current published revision when one exists.

   The UI should default to `published` for portability because published
   protocol versions are the runnable contract. If no published version exists,
   the UI can select `draft` and label it clearly.

   The API should accept an explicit `revision` value. If omitted, use
   `published` when available and fall back to `draft`.

3. Imported copies use copy/import naming, never version naming.

   Default slug format: `<slug>-copy-N`.

   Default display name format: `<Display Name> (Imported N)`.

   Do not use `-vN`, "new version", or "versioned import" copy. In this system,
   protocol versions mean published protocol definition versions.

4. Provider guidance is not included in the first protocol package.

   Skills may carry provider config already modeled as skill content. Broader
   provider guidance or routing policy is deployment/operator-specific and
   should be handled by a separate lifecycle feature later.

5. Run artifacts are not included.

   Protocol package portability covers definitions and required skills only.
   Runs, run artifacts, logs, outputs, and result archives are a separate
   future export/archive feature.
