"""Acceptance gate for the authoring kit (plan §7, §9).

The kit is the single source of UI truth for authoring surfaces. These
contract tests assert that the primitives exist, their names are stable,
strings flow through the dictionary, and the kit is wired into the shell
before component modules.
"""

from __future__ import annotations

from pathlib import Path


def _ui_root() -> Path:
    return Path(__file__).resolve().parents[1] / "octopus_registry" / "ui"


def _read(*parts: str) -> str:
    return (_ui_root().joinpath(*parts)).read_text(encoding="utf-8")


def test_kit_module_exposes_expected_primitives() -> None:
    kit = _read("js", "helpers", "kit.js")

    assert "window.Kit = (() =>" in kit, "kit must expose a single window.Kit namespace"
    for primitive in (
        "dict",
        "draftStateChip",
        "lifecycleHeader",
        "validationSurface",
        "detailsPanel",
        "authoredCatalog",
        "sectionListCanvas",
        "workflowCanvas",
        "rehearsalPanel",
        "runsList",
        "runSummary",
        "agentsList",
        "agentSummary",
        "selectorResolutionPreview",
    ):
        assert f"{primitive}" in kit, f"kit must expose {primitive}"

    # Return block must be exactly the kit API — no surface-specific primitives.
    tail = kit[kit.rfind("return {"):]
    for forbidden in ("renderStageFlow", "buildCanvas", "rawJson"):
        assert forbidden not in tail, f"kit return block must not expose {forbidden}"


def test_kit_dictionary_covers_protocol_authoring_strings() -> None:
    kit = _read("js", "helpers", "kit.js")

    required_keys = [
        "protocol.display_name.label",
        "protocol.slug.label",
        "protocol.description.label",
        "protocol.lifecycle.draft",
        "protocol.lifecycle.published",
        "protocol.lifecycle.archived",
        "protocol.lifecycle.filter.all",
        "protocol.action.validate",
        "protocol.action.publish",
        "protocol.action.archive",
        "protocol.action.discard",
        "protocol.action.rehearse",
        "protocol.stage.kind.work",
        "protocol.stage.kind.review",
        "protocol.stage.kind.acceptance",
        "protocol.participant.selector_kind.label",
        "protocol.participant.selector_strategy.label",
        "protocol.participant.selector_value.label",
        "protocol.participant.selector_advanced.label",
        "protocol.participant.selector_advanced.strategy",
        "protocol.participant.selector_override.label",
        "protocol.canvas.empty.title",
        "protocol.catalog.empty.title",
        "protocol.workflow.lane_hint",
        "protocol.workflow.outcomes_hint",
        "draftchip.idle",
        "draftchip.editing",
        "draftchip.saving",
        "draftchip.saved",
        "draftchip.conflict",
        "draftchip.error",
        "validation.empty",
        "validation.heading.errors",
        "validation.heading.warnings",
        "protocol.rehearsal.panel.title",
        "protocol.rehearsal.panel.firstrun",
        "protocol.rehearsal.panel.empty",
        "protocol.rehearsal.response.placeholder",
        "protocol.rehearsal.response.submit",
        "protocol.rehearsal.scenarios.label",
        "agents.list.title",
        "agents.empty",
        "agents.search.placeholder",
        "agents.presence.filter.all",
        "agents.presence.connected",
        "agents.presence.degraded",
        "agents.presence.disconnected",
        "agents.presence.stopped",
        "agents.presence.faulted",
        "agents.detail.firstrun",
        "agents.summary.agent_id",
        "agents.summary.trust_tier",
        "agents.summary.capacity",
        "agents.trust_tier.community",
        "agents.trust_tier.trusted",
        "agents.trust_tier.verified",
        "agents.trust_tier.restricted",
        "agents.admin.title",
        "agents.admin.gated_help",
        "agents.admin.trust_tier.label",
        "agents.admin.capacity.label",
        "agents.admin.rotate_token",
        "agents.admin.soft_delete",
        "agents.selector.title",
        "agents.selector.placeholder",
        "agents.selector.run",
        "agents.selector.empty",
        "agents.selector.no_matches",
        "agents.selector.quick_picks",
    ]
    for key in required_keys:
        assert f"'{key}'" in kit, f"kit dictionary missing {key}"


def test_kit_details_panel_does_not_prefill_values_for_blank_records() -> None:
    """Plan §7.4 invariant: new authoring starts with placeholder-only inputs."""
    kit = _read("js", "helpers", "kit.js")

    # Inputs must have empty string value when record field is blank.
    assert "control.value = '';" in kit, (
        "details panel must clear value for blank records — no prefilled defaults"
    )
    # Placeholder styling is driven by CSS; verify CSS applies italic/muted
    # styling to kit-details-control::placeholder.
    css = _read("css", "main.css")
    assert ".kit-details-control::placeholder" in css
    assert "opacity: 0.7" in css or "opacity: .7" in css


def test_kit_details_panel_debounces_live_text_commits() -> None:
    """Live-committed text fields must not re-render on every keystroke."""
    kit = _read("js", "helpers", "kit.js")

    assert "let commitTimer = null;" in kit
    assert "const scheduleCommit = () =>" in kit
    assert "field.commitDelayMs || 350" in kit
    assert "window.setTimeout(commit" in kit
    assert "control.addEventListener('input', scheduleCommit);" in kit
    assert "window.clearTimeout(commitTimer);" in kit


def test_index_html_loads_kit_between_ui_helpers_and_components() -> None:
    html = _read("index.html")
    ui_idx = html.find("helpers/ui.js")
    kit_idx = html.find("helpers/kit.js")
    dashboard_idx = html.find("components/dashboard.js")

    assert ui_idx >= 0 and kit_idx >= 0 and dashboard_idx >= 0
    assert ui_idx < kit_idx < dashboard_idx, (
        "kit.js must load after helpers/ui.js and before any component module"
    )


def test_main_css_carries_kit_primitive_classes() -> None:
    css = _read("css", "main.css")
    kit = _read("js", "helpers", "kit.js")
    for cls in (
        ".kit-lifecycle-header",
        ".kit-lifecycle-chip",
        ".kit-draft-chip",
        ".kit-validation",
        ".kit-details-panel",
        ".kit-details-control",
        ".kit-details-checklist",
        ".kit-stage-editor",
        ".kit-stage-editor-hero",
        ".kit-stage-routing",
        ".kit-authored-catalog",
        ".kit-catalog-filter-chip",
        ".kit-workflow-canvas",
        ".kit-workflow-viewbar",
        ".kit-workflow-viewbar-title",
        ".kit-workflow-shell-scene",
        ".kit-workflow-outline",
        ".kit-workflow-outline-item",
        ".kit-workflow-outline-child",
        ".kit-workflow-controls",
        ".kit-workflow-viewport",
        ".kit-workflow-canvas-column",
        ".kit-workflow-viewport-cy",
        ".kit-workflow-cy-host",
        ".kit-workflow-accessory",
        ".kit-rehearsal-panel",
        ".kit-rehearsal-session",
        ".kit-rehearsal-session-form",
        ".kit-rehearsal-scenario-btn",
        ".kit-agents-list",
        ".kit-agents-filters",
        ".kit-agents-filter-chip",
        ".kit-agents-list-row",
        ".kit-agent-presence-chip",
        ".kit-agent-trust-chip",
        ".kit-agent-summary",
        ".kit-selector-editor-field",
        ".kit-selector-editor-note",
        ".kit-selector-editor-preview",
        ".kit-selector-preview",
        ".kit-selector-preview-form",
        ".kit-selector-preview-suggestions",
        ".kit-selector-preview-row",
    ):
        assert cls in css, f"main.css missing kit class {cls}"

    # Responsive behaviour is a kit invariant, not a page-specific concern.
    assert "@media (max-width: 720px)" in css
    assert ".kit-lifecycle-header-top" in css
    assert "position: absolute;" in css
    assert ".kit-workflow-shell-scene" in css
    assert ".kit-workflow-outline" in css
    assert ".kit-workflow-cy-host" in css
    assert ".kit-workflow-view-full" not in css
    assert ".kit-workflow-view-focus" not in css
    assert ".kit-workflow-compact" not in css


def test_rehearsal_session_forms_are_keyed_by_routed_task() -> None:
    kit = _read("js", "helpers", "kit.js")

    assert "card.dataset.key = `rehearsal-session:" in kit
    assert "form.dataset.routedTaskId = routedTaskId;" in kit
    assert "const currentRoutedTaskId = String(form.dataset.routedTaskId" in kit
    assert "'protocol.workflow.narrow.empty'" not in kit


def test_kit_draft_chip_states_are_exhaustive() -> None:
    kit = _read("js", "helpers", "kit.js")
    # Any state added to the list must also have a dictionary entry; this
    # prevents silent regressions where a new chip state lacks copy.
    for state in ("idle", "editing", "saving", "saved", "conflict", "error"):
        assert f"'draftchip.{state}'" in kit, f"missing dictionary entry draftchip.{state}"
        assert f"'{state}'" in kit
