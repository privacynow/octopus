"""Plan §9: kit acceptance gate.

This module is the CI gate enforcing the kit-first invariant from the plan.
It asserts two things simultaneously:

1. **Kit coverage is complete for the surfaces that have migrated.** Every
   primitive named in §7 and lit through Steps 3\u20138 is exported from
   `window.Kit`, backed by dictionary entries and CSS, and actually
   consumed by the surface that owns the concern.

2. **Migrated surfaces do not regrow bespoke variants of kit-covered
   concerns.** Files for `protocols`, `agents`, and `runs` are grepped for
   the specific dead shapes the kit replaces (bespoke metadata grids,
   ad-hoc filter chips, hand-rolled run tables, inline agent cards, \u2026).
   New occurrences trip the gate.

Surfaces that have **not** migrated yet (`skills`, `guidance`,
`conversations`, `dashboards`) are explicitly exempt; the plan's §4 item
15 describes a deferred migration stage that closes this gap. The gate
prevents *new* bespoke code only and continues to hold after §9 ships.
"""

from __future__ import annotations

from pathlib import Path


def _ui_root() -> Path:
    return Path(__file__).resolve().parents[1] / "octopus_registry" / "ui"


def _read(*parts: str) -> str:
    return (_ui_root().joinpath(*parts)).read_text(encoding="utf-8")


KIT_MANIFEST: tuple[tuple[str, tuple[str, ...]], ...] = (
    # (primitive, required consuming surfaces). Use the empty tuple when the
    # primitive is composed by another kit primitive rather than a surface
    # directly \u2014 the export check still guards the public surface.
    ("dict", ("helpers/kit.js",)),
    ("draftStateChip", ()),  # consumed internally by Kit.lifecycleHeader
    ("lifecycleHeader", ("components/protocol-workspace.js",)),
    ("validationSurface", ("components/protocol-workspace.js",)),
    ("detailsPanel", ("components/protocol-workspace.js",)),
    ("authoredCatalog", ("components/protocol-workspace.js",)),
    ("workflowCanvas", ("components/protocol-workspace.js",)),
    ("rehearsalPanel", ("components/protocol-workspace.js",)),
    ("runsList", ("components/protocol-workspace.js",)),
    ("runSummary", ("components/protocol-workspace.js",)),
    ("agentsList", ("components/agent-list.js",)),
    ("agentSummary", ("components/agent-detail.js",)),
    ("selectorResolutionPreview", ("components/agent-detail.js", "components/protocol-workspace.js")),
)


def test_every_kit_primitive_is_exported_and_consumed_by_its_owning_surface() -> None:
    """Each primitive must appear in kit.js' export block AND be used by
    every surface that owns the concern it covers."""
    kit = _read("js", "helpers", "kit.js")
    # The kit return block anchors exports. Anything listed there is
    # considered part of the public surface.
    export_block = kit[kit.rfind("return {"):]
    for primitive, surfaces in KIT_MANIFEST:
        assert primitive in export_block, (
            f"kit.js must export {primitive!r} from its return block"
        )
        for surface in surfaces:
            if surface == "helpers/kit.js":
                continue
            text = _read("js", *surface.split("/"))
            marker = f"Kit.{primitive}(" if primitive != "dict" else "Kit.dict"
            assert marker in text, (
                f"{surface} must consume Kit.{primitive} "
                f"(otherwise the kit primitive is unused)"
            )


def test_migrated_surfaces_do_not_reintroduce_bespoke_kit_covered_shapes() -> None:
    """Plan §9: new bespoke variants of kit-covered concerns must not land
    in the migrated surfaces. These greps trip when someone reinvents a
    kit primitive instead of extending the existing one."""

    protocol_ws = _read("js", "components", "protocol-workspace.js")
    agent_list = _read("js", "components", "agent-list.js")
    agent_detail = _read("js", "components", "agent-detail.js")

    # Protocol workspace: authoring lifecycle + canvas owned by kit.
    for forbidden in (
        "buildLifecycleHeader",  # old bespoke lifecycle header builder
        "createRawJsonTab",       # retired raw-json shape
        "_buildStageFlow(",       # retired bespoke stage flow
        "PROTOCOL_AUTHORING_MODE_OPTIONS",
        "structuredInputDrafts",
    ):
        assert forbidden not in protocol_ws, (
            f"protocol-workspace.js must not reintroduce bespoke shape {forbidden!r}"
        )

    # Agent surfaces: list + summary + selector preview owned by kit.
    # A bespoke re-render would typically reach for UI.renderListRow with
    # agent shape or call listAgents() and hand-compose chips; the kit
    # makes both unnecessary.
    for forbidden in (
        "UI.renderListRow({\n                href: '/ui/agents",  # old list row
        "createSegmentedControl",  # retired filter chip builder in this scope
    ):
        assert forbidden not in agent_list, (
            f"agent-list.js must not hand-build kit-covered shape {forbidden!r}"
        )

    # Agent detail: admin actions + selector preview must flow through kit.
    # Any hand-rolled selector resolution inline is forbidden.
    assert "preview_target_resolution" not in agent_detail, (
        "agent-detail.js must not call the low-level resolution API; use "
        "API.previewSelectorResolution() via Kit.selectorResolutionPreview"
    )


def test_kit_primitives_carry_required_dictionary_keys() -> None:
    """Every primitive with visible strings must source them from
    Kit.dict. Missing keys surface in UI as `[key]` markers — so missing
    dictionary coverage is both a UX regression and an acceptance gate
    failure."""
    kit = _read("js", "helpers", "kit.js")
    for required in (
        # lifecycleHeader
        "'protocol.lifecycle.draft'",
        "'protocol.lifecycle.published'",
        "'protocol.lifecycle.archived'",
        # draftStateChip
        "'draftchip.saved'",
        # validationSurface
        "'validation.empty'",
        # authoredCatalog
        "'protocol.catalog.empty.title'",
        # workflowCanvas
        "'protocol.canvas.empty.title'",
        # rehearsalPanel
        "'protocol.rehearsal.panel.title'",
        # runsList / runSummary
        "'runs.empty'",
        "'runs.summary.run_id'",
        # agentsList / agentSummary / selectorResolutionPreview
        "'agents.empty'",
        "'agents.summary.trust_tier'",
        "'agents.selector.title'",
    ):
        assert required in kit, f"kit dictionary missing key {required}"


def test_acceptance_gate_documents_deferred_surfaces() -> None:
    """Plan §4 item 15: surfaces not yet migrated are named explicitly so
    the gate's scope is auditable. If you migrate one of these, move it
    out of the exempt set and into KIT_MANIFEST."""
    deferred = {
        "skill-catalog.js",
        "guidance-editor.js",
        "conversation-list.js",
        "conversation-detail.js",
        "dashboard.js",
    }
    components_dir = _ui_root() / "js" / "components"
    existing = {path.name for path in components_dir.glob("*.js")}
    assert deferred <= existing, (
        "deferred surface list drifted from the filesystem; "
        f"expected {sorted(deferred)} to all exist"
    )


def test_retired_routes_stay_retired() -> None:
    """Routes that this plan retires must not come back. Guards against
    accidentally re-registering legacy URLs that would bypass kit-migrated
    surfaces."""
    app_js = _read("js", "app.js")
    router_js = _read("js", "router.js")

    # /ui/protocol-runs was retired in Step 7 in favor of /ui/runs.
    assert "/ui/protocol-runs" not in app_js, (
        "Router must not re-register /ui/protocol-runs — it was retired in Step 7"
    )
    assert "protocol-runs" not in router_js or "/ui/runs" in router_js
