from pathlib import Path


def test_router_waits_for_route_readiness_before_swapping_shells() -> None:
    router_path = (
        Path(__file__).resolve().parents[1]
        / "octopus_registry"
        / "ui"
        / "js"
        / "router.js"
    )
    text = router_path.read_text(encoding="utf-8")

    assert "contentEl.textContent = ''" not in text
    assert "async function _render" in text
    assert "await _routeReadyPromise(inner);" in text
    assert "contentEl.replaceChildren(inner);" in text
    assert "requestAnimationFrame(() => {" in text
    assert "_cleanupShell(previousShell);" in text
    assert "route-shell" in text
    assert "main.focus()" not in text
    assert "loading').forEach" not in text
    assert "_updateActiveNav(normalized);" not in text
    assert "_updateActiveNav(activePath);" in text
    assert "incoming" not in text
    assert "outgoing" not in text
    assert "fade-in" not in text
    assert "fade-out" not in text
    assert "classList.add('loading-route')" not in text
    assert "route-enter" not in text


def test_data_fetching_route_components_use_sync_shell_rendering_contract() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    expected = {
        "dashboard.js": "function renderDashboard(",
        "agent-list.js": "function renderAgentList(",
        "agent-detail.js": "function renderAgentDetail(",
        "conversation-list.js": "function renderConversationList(",
        "conversation-detail.js": "function renderConversationDetail(",
        "task-list.js": "function renderTaskList(",
        "approval-list.js": "function renderApprovalList(",
        "routing-policy-list.js": "function renderRoutingPolicyList(",
        "usage-view.js": "function renderUsageView(",
        "skill-catalog.js": "function renderSkillCatalog(",
        "guidance-editor.js": "function renderGuidanceEditor(",
        "protocol-workspace.js": "function renderProtocolWorkspace(",
    }

    for name, marker in expected.items():
        text = (
            repo_root
            / "octopus_registry"
            / "ui"
            / "js"
            / "components"
            / name
        ).read_text(encoding="utf-8")
        assert marker in text, f"{name} must use sync shell rendering"
        assert "async function render" not in text, f"{name} must not use async route rendering"
        assert "createSkeletonNodes" not in text, f"{name} must not render route-transition skeletons"
        assert "__routeReady" in text, f"{name} must publish an initial route readiness promise"


def test_management_views_request_agent_pages_with_supported_limit() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    api_js = (
        repo_root / "octopus_registry" / "ui" / "js" / "api.js"
    ).read_text(encoding="utf-8")
    skill_catalog = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "skill-catalog.js"
    ).read_text(encoding="utf-8")
    guidance_editor = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "guidance-editor.js"
    ).read_text(encoding="utf-8")

    assert "API.listAgents({ limit: 100 })" in skill_catalog
    assert "API.listAgents({ limit: 200 })" not in skill_catalog
    assert "API.listAgents({ limit: 100 })" in guidance_editor
    assert "API.listAgents({ limit: 200 })" not in guidance_editor
    assert "searchCatalogSkills: (agentId, query)" in api_js


def test_skill_catalog_only_offers_install_for_registry_search_hits() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    skill_catalog = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "skill-catalog.js"
    ).read_text(encoding="utf-8")

    assert "API.searchCatalogSkills(currentAgentId, queryText)" in skill_catalog
    assert "_renderRegistrySkillRow" in skill_catalog
    assert "_renderLocalSkillRow" in skill_catalog
    assert "skill.status" not in skill_catalog
    assert "can_import" in skill_catalog
    assert "can_uninstall" in skill_catalog
    assert "can_update" in skill_catalog


def test_management_views_do_not_block_route_readiness_on_slow_management_fetches() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    skill_catalog = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "skill-catalog.js"
    ).read_text(encoding="utf-8")
    guidance_editor = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "guidance-editor.js"
    ).read_text(encoding="utf-8")

    assert "void loadSkills({ soft: soft && !agentChanged, forceCatalog: agentChanged || !allSkills.length });" in skill_catalog
    assert "await loadSkills({ soft: soft && !agentChanged, forceCatalog: agentChanged || !allSkills.length });" not in skill_catalog
    assert "void loadGuidance({ soft: soft && !agentChanged });" in guidance_editor
    assert "await loadGuidance({ soft: soft && !agentChanged });" not in guidance_editor
    assert "renderLoadingState(message = 'Loading skills…')" in skill_catalog
    assert "renderLoadingState(queryText.length >= 2 ? 'Searching skills…' : 'Loading skills…');" in skill_catalog
    assert "renderLoadingState(message = 'Loading guidance…')" in guidance_editor
    assert "renderLoadingState('Loading guidance…');" in guidance_editor


def test_protocol_workspace_uses_shared_protocol_contract_and_accessible_operator_controls() -> None:
    """Protocol authoring is kit-driven (plan §7). No bespoke section tabs,
    no raw-JSON tab, no server-seeded defaults. Runs route keeps its live
    observation contract until Step 7."""
    repo_root = Path(__file__).resolve().parents[1]
    workspace = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "protocol-workspace.js"
    ).read_text(encoding="utf-8")

    # Entry points
    assert "function renderProtocolWorkspace(" in workspace
    assert "function renderProtocolRuns(" in workspace

    # Authoring: kit-first
    assert "Kit.lifecycleHeader(" in workspace
    assert "Kit.authoredCatalog(" in workspace
    assert "Kit.workflowCanvas(" in workspace
    assert "Kit.detailsPanel(" in workspace
    assert "Kit.validationSurface(" in workspace
    assert "Kit.rehearsalPanel(" in workspace
    assert "Kit.selectorResolutionPreview(" in workspace
    assert "API.listAgents({ state: 'connected', limit: 24 })" in workspace

    # Rehearsal API the workspace drives
    assert "API.listRehearsalSessions(" in workspace
    assert "API.respondRehearsalSession(" in workspace
    assert "API.listProtocolScenarios(" in workspace
    assert "API.getProtocolRun(rehearsal.runId)" in workspace

    # Authoring API the kit surface drives
    assert "API.getProtocolAuthoringManifest()" in workspace
    assert "API.previewSelectorResolution(" in workspace
    assert "API.createProtocolDraft(" in workspace
    assert "created?.run?.protocol_run_id" in workspace
    assert "API.saveProtocolDraft(" in workspace
    assert "API.publishProtocol(" in workspace
    assert "API.archiveProtocol(" in workspace
    assert "API.deleteProtocol(" in workspace
    assert "API.validateProtocol(" in workspace
    assert "ifMatch: draftRevision" in workspace
    assert "PROTOCOL_DRAFT_CONFLICT" in workspace
    assert "state: 'conflict'" in workspace
    assert "_reloadServerDraftConflict" in workspace
    assert "_overwriteServerDraftConflict" in workspace
    assert "let editorMode = { kind: 'idle'" in workspace
    assert "_startRoleInsert(" in workspace
    assert "_confirmRoleInsert(" in workspace
    assert "_startStageInsert(" in workspace
    assert "_confirmStageInsert(" in workspace
    assert "_startConnectMode(" in workspace
    assert "_cancelTransitionConnect(" in workspace
    assert "_commitConnectField(" in workspace
    assert "_rewriteKeyReferences(" in workspace
    assert "inputs: (stage.inputs || []).map" in workspace
    assert "outputs: (stage.outputs || []).map" in workspace
    assert "_stageTransitionId(" in workspace
    assert "_transitionEntries(" in workspace
    assert "_applyParticipantSuggestion(" in workspace
    assert "suggestions: _participantSelectorSuggestions(target)" in workspace
    assert "_currentWorkflowMode()" in workspace
    assert "let workflowView = { kind: 'focus'" in workspace
    assert "_buildWorkflowProjection(" in workspace
    assert "_normalizeWorkflowView(" in workspace
    assert "_setFocusSegment(" in workspace
    assert "window.addEventListener('resize', onResize);" in workspace

    # Runs route (kept until Step 7)
    assert "API.listProtocolRuns({ limit: 50 })" in workspace
    assert "API.getProtocolRun(currentRunId)" in workspace
    assert "API.listProtocolIssues({" in workspace
    assert "API.actOnProtocolRun(" in workspace
    assert "WS.subscribe(`protocol-run:${currentRunId}`" in workspace
    assert "transitionList.setAttribute('aria-live', 'polite');" in workspace
    assert "role: 'alertdialog'" in workspace

    # Runs-side copy stays; empty/hint strings for the catalog now flow
    # through Kit.dict.
    assert "Select a run to inspect state, timeline, artifacts, and operator actions." in workspace
    assert "No protocol issues detected for this run." in workspace
    assert "No blocked runs, lease issues, contract failures, or expired timeouts match this filter." in workspace

    # Dead UX must be gone
    for forbidden in (
        "API.parseProtocolDocument(",
        "API.exportProtocolDraft(",
        "API.diffProtocolDraft(",
        "Advanced raw editor",
        "Raw editor has unsynced errors.",
        "validation_mode: 'draft'",
        "Review & publish",
        "Protocol basics",
        "editorFormat",
        "_buildStageFlow(",
        "_buildModeNav(",
        "_buildStarterPanel(",
        "_buildAuthorHeader(",
        "_buildDefinitionPanel(",
        "_addNode(",
        "connectState",
        "_addParticipantFromSuggestion(",
        "_saveNew(",
        "PROTOCOL_AUTHORING_MODE_OPTIONS",
        "PROTOCOL_CATALOG_STATUS_OPTIONS",
        "single_active_writer: true",
        "max_review_rounds: 5",
        "structuredInputDrafts",
    ):
        assert forbidden not in workspace, f"dead UX remnant found: {forbidden}"


def test_protocol_routes_split_authoring_and_operations_without_mixed_workspace_modes() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "protocol-workspace.js"
    ).read_text(encoding="utf-8")
    app_js = (
        repo_root / "octopus_registry" / "ui" / "js" / "app.js"
    ).read_text(encoding="utf-8")
    router_js = (
        repo_root / "octopus_registry" / "ui" / "js" / "router.js"
    ).read_text(encoding="utf-8")

    # Forbidden: cross-cutting operator modes, launcher strips, agent
    # management dropdowns, and the retired protocol_view query param.
    assert "WORKSPACE_VIEW_OPTIONS" not in workspace
    assert "UI.createAgentManagementDropdown(" not in workspace
    assert "_setCurrentView(" not in workspace
    assert "renderOperateSurface" not in workspace
    assert "renderIssuesSurface" not in workspace
    assert "renderLauncherStrip" not in workspace
    assert "UI.readQueryParam('entry_agent_id'" not in workspace
    assert "UI.subscribeWithRefresh(cleanups, 'agents'" not in workspace
    assert "UI.readQueryParam('protocol_view'" not in workspace
    assert "protocol_view:" in workspace  # kept in _writeState to clear legacy URLs
    assert "API.getProtocolTemplate('software-engineering')" not in workspace
    assert "loadDefaultTemplate" not in workspace

    # Protocol authoring lifecycle subscription is retained
    assert "UI.subscribeWithRefresh(cleanups, 'protocols'" in workspace
    assert "UI.subscribeWithRefresh(cleanups, 'summary', () => Promise.all([" in workspace

    # Router wiring
    assert "Router.register('/ui/gallery', renderGallery);" in app_js
    assert "Router.register('/ui/runs', renderProtocolRuns);" in app_js
    assert "Router.register('/ui/protocol-runs', renderProtocolRuns);" not in app_js
    assert "path.startsWith('/ui/protocol-runs')" not in router_js


def test_protocol_workspace_css_keeps_scroll_contained_and_collapses_to_single_column() -> None:
    """Authoring styles are kit-owned; runs styles are protocol-scoped."""
    repo_root = Path(__file__).resolve().parents[1]
    css = (
        repo_root / "octopus_registry" / "ui" / "css" / "main.css"
    ).read_text(encoding="utf-8")

    # Still required for the runs route and the shared shell
    assert ".protocol-route-shell {" in css
    assert ".protocol-surface-shell {" in css
    assert ".protocol-scroll {" in css
    assert ".protocol-sticky-actions {" in css

    # Kit-owned authoring styles
    assert ".kit-lifecycle-header" in css
    assert ".kit-authoring-workspace" in css
    assert ".kit-workflow-canvas" in css
    assert ".kit-workflow-graph" in css
    assert ".kit-workflow-lane-strip" in css
    assert ".kit-workflow-lane-pill" in css
    assert ".kit-workflow-band-label" in css
    assert ".kit-workflow-band-sublabel" in css
    assert ".kit-workflow-node" in css
    assert ".kit-workflow-node-wrap {" in css
    assert "position: absolute;" in css
    assert ".kit-details-panel" in css
    assert ".kit-validation" in css
    assert ".kit-authored-catalog" in css
    assert "@media (max-width: 960px)" in css  # authoring responsive collapse

    # Legacy authoring CSS that must stay removed
    for dead in (
        ".protocol-workspace-grid {",
        ".protocol-author-board {",
        ".protocol-author-workspace {",
        ".protocol-author-header {",
        ".protocol-author-main {",
        ".protocol-author-title {",
        ".protocol-design-workspace {",
        ".protocol-inspector-panel {",
        ".protocol-first-run-card {",
        ".protocol-template-grid {",
        ".protocol-template-card {",
        ".protocol-template-card-subtle {",
        ".protocol-template-highlight {",
        ".protocol-catalog-groups {",
        ".protocol-catalog-toolbar {",
        ".protocol-catalog-heading {",
        ".protocol-catalog-list {",
        ".protocol-next-steps {",
        ".protocol-validation-gutter {",
        ".protocol-validation-list {",
        ".protocol-stage-flow {",
        ".protocol-stage-flow-compact {",
        ".protocol-stage-flow-preview {",
        ".protocol-stage-preview-node {",
        ".protocol-stage-preview-meta {",
        ".protocol-stage-preview-arrow {",
        ".protocol-stage-node {",
        ".protocol-stage-node-meta {",
        ".kit-workflow-node-connect",
        ".protocol-advanced-panel ",
        ".protocol-structured-textarea {",
        ".protocol-inline-checkbox {",
    ):
        assert dead not in css, f"dead CSS must be removed: {dead}"


def test_protocol_navigation_links_target_authoring_and_run_routes() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "dashboard.js"
    ).read_text(encoding="utf-8")
    index_html = (
        repo_root / "octopus_registry" / "ui" / "index.html"
    ).read_text(encoding="utf-8")

    assert "href: '/ui/runs'" in dashboard
    assert "href: '/ui/protocols'" in dashboard
    assert "`/ui/runs?run_id=${encodeURIComponent(item.protocol_run_id)}&issue_kind=${encodeURIComponent(item.issue_kind || 'all')}`" in dashboard
    assert "'/ui/runs?issue_kind=all'" in dashboard
    assert 'href="/ui/gallery"' in index_html
    assert 'href="/ui/protocols"' in index_html


def test_management_views_use_shared_memory_cache_for_stale_while_revalidate() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helper = (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "ui.js"
    ).read_text(encoding="utf-8")
    skill_catalog = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "skill-catalog.js"
    ).read_text(encoding="utf-8")
    guidance_editor = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "guidance-editor.js"
    ).read_text(encoding="utf-8")

    assert "function peekCachedData(" in helper
    assert "function loadCachedData(" in helper
    assert "function invalidateCachedData(" in helper
    assert "peekCachedData," in helper
    assert "loadCachedData," in helper
    assert "invalidateCachedData," in helper

    assert "UI.peekCachedData(RegistrySkillHub.listCacheKey(currentAgentId))" in skill_catalog
    assert "UI.loadCachedData(" in skill_catalog
    assert "function _invalidateSkillCaches(agentId = currentAgentId, skillName = '') {" in skill_catalog
    assert "_invalidateSkillCaches(currentAgentId, skill.name);" in skill_catalog
    assert "UI.peekCachedData(_guidanceCacheKey())" in guidance_editor
    assert "UI.loadCachedData(" in guidance_editor
    assert "_invalidateGuidanceCache();" in guidance_editor


def test_skill_catalog_unifies_bot_skill_management_and_keeps_custom_editing_progressive() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    skill_catalog = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "skill-catalog.js"
    ).read_text(encoding="utf-8")
    conversation_detail = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-detail.js"
    ).read_text(encoding="utf-8")
    api_js = (
        repo_root / "octopus_registry" / "ui" / "js" / "api.js"
    ).read_text(encoding="utf-8")

    assert "Manage a bot’s installed, custom, and store-backed skills here." in skill_catalog
    assert "contentInner.classList.add('workspace-route-wide');" in skill_catalog
    assert "label: 'Bot catalog'" not in skill_catalog
    assert "label: 'Studio'" not in skill_catalog
    assert "currentStudioTab = _readStudioTab()" in skill_catalog
    assert "label: 'Skill workspace'" in skill_catalog
    assert "label: 'Write'" in skill_catalog
    assert "label: 'Setup'" in skill_catalog
    assert "label: 'Review'" in skill_catalog
    assert "label: 'Advanced'" in skill_catalog
    assert "skills_view: ''" in skill_catalog
    assert "currentStudioTab !== 'review'" in skill_catalog
    assert "studio-workflow" not in skill_catalog
    assert "Next step" in skill_catalog
    assert "_buildStudioPanel(" not in skill_catalog
    assert "'Custom'" in skill_catalog
    assert "'Installed on this bot'" in skill_catalog
    assert "'Store'" in skill_catalog
    assert "'New custom skill'" in skill_catalog
    assert "'No skills are available on this bot yet. Create a custom skill or import one to get started.'" in skill_catalog
    assert "_renderRegistrySkillRow" in skill_catalog
    assert "API.getSkillLifecycle(currentAgentId, skillName)" in skill_catalog
    assert "API.saveSkillDraft(currentAgentId, skillName" in skill_catalog
    assert "await persistDraft({ quiet: true })" in skill_catalog
    assert "function _editableDraftState(detail, lifecycle)" in skill_catalog
    assert "detailSnapshot: _draftSnapshot(detail, lifecycle)" in skill_catalog
    assert "Loading skill details…" in skill_catalog
    assert "function _buildLoadingPanel(detail" in skill_catalog
    assert "workspace.className = 'dashboard-board';" in skill_catalog
    assert "listWrap.className = 'list-shell dashboard-column';" in skill_catalog
    assert "detailEl.className = 'editor-shell dashboard-column';" in skill_catalog
    assert "UI.showTextDialog(" in skill_catalog
    assert "allowEmpty: true" in skill_catalog
    assert "agentId: currentAgentId" in skill_catalog
    assert "agentLabel: _currentAgentLabel()" in skill_catalog
    assert "currentAgentId = agents.length === 1 ? String(agents[0].agent_id || '') : '';" in skill_catalog
    assert "selectedSkillName = local[0].name || ''" not in skill_catalog
    assert "selectedSkillName = store[0].name || ''" not in skill_catalog
    assert "How skills work" not in skill_catalog
    assert "Open this bot’s conversations" not in skill_catalog
    assert "1. Basics" not in skill_catalog
    assert "6. Review" not in skill_catalog
    assert "activate_skill" in skill_catalog
    assert "API.activateConversationSkill(agentId, conversation.conversation_id, normalizedSkill, { confirm: true })" in skill_catalog
    assert "Active in this conversation" in conversation_detail
    assert "Available on this bot" in conversation_detail
    assert "prompt instructions" in conversation_detail
    assert "runtime orchestration" in conversation_detail
    assert "requestedActivationSkill && requestedManagementMode === 'closed'" in conversation_detail
    assert "function clearRequestedActivationSkill()" in conversation_detail
    assert "await requestConversationSkillActivation(skillName);" in conversation_detail
    assert "Activated ${normalizedSkill}." in conversation_detail
    assert "is already active in this conversation." in conversation_detail
    assert "active-skills-inline" in conversation_detail
    assert "selectedActivationSkill = requestedActivationSkill;" in conversation_detail
    assert "getSkillLifecycle: (agentId, name) =>" in api_js
    assert "saveSkillDraft: (agentId, name, body = {}) =>" in api_js


def test_agents_surface_uses_shared_kit_primitives_and_admin_actions() -> None:
    """Plan §8: agents list + detail migrate to Kit primitives; detail surface
    exposes admin actions (trust tier, capacity, token rotation, soft-delete)
    and a selector resolution preview wired to /v1/selector/preview."""
    repo_root = Path(__file__).resolve().parents[1]
    agent_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "agent-list.js"
    ).read_text(encoding="utf-8")
    agent_detail = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "agent-detail.js"
    ).read_text(encoding="utf-8")
    api_js = (
        repo_root / "octopus_registry" / "ui" / "js" / "api.js"
    ).read_text(encoding="utf-8")

    # List
    assert "Kit.agentsList(" in agent_list
    assert "trustTier: String(agent.trust_tier" in agent_list
    assert "currentCapacity: Number(agent.current_capacity" in agent_list
    assert "softDeletedAt: String(agent.soft_deleted_at" in agent_list

    # Detail surfaces
    assert "Kit.agentSummary(" in agent_detail
    assert "Kit.selectorResolutionPreview(" in agent_detail
    assert "function buildAdminCard(" in agent_detail
    assert "function buildSelectorCard(" in agent_detail
    assert "API.updateAgentTrustTier(" in agent_detail
    assert "API.updateAgentCapacity(" in agent_detail
    assert "API.rotateAgentToken(" in agent_detail
    assert "API.softDeleteAgent(" in agent_detail
    assert "API.previewSelectorResolution(" in agent_detail

    # API client
    assert "updateAgentTrustTier: (id" in api_js
    assert "updateAgentCapacity: (id" in api_js
    assert "rotateAgentToken: (id" in api_js
    assert "softDeleteAgent: (id" in api_js
    assert "previewSelectorResolution: (body" in api_js


def test_agent_detail_launches_shared_skills_workspace_instead_of_passive_pills() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    agent_detail = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "agent-detail.js"
    ).read_text(encoding="utf-8")
    skill_catalog = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "skill-catalog.js"
    ).read_text(encoding="utf-8")
    css = (
        repo_root / "octopus_registry" / "ui" / "css" / "main.css"
    ).read_text(encoding="utf-8")

    assert "window.RegistrySkillHub = RegistrySkillHub;" in skill_catalog
    assert "function buildSkillsCard(agent) {" in agent_detail
    assert "Manage skills" in agent_detail
    assert "Open Skills page" in agent_detail
    assert "Open in Skills" in agent_detail
    assert "Open conversation and activate" in agent_detail
    assert "Quick actions live here." in agent_detail
    assert "Advertised for routing" in agent_detail
    assert "buildSkillsCard(agent)," in agent_detail
    assert "quickstart-chip static" in agent_detail
    assert "skills-drawer-dialog" in css
    assert "skills-drawer-overlay" in css


def test_guidance_editor_exposes_progressive_draft_and_review_workspace() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    guidance_editor = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "guidance-editor.js"
    ).read_text(encoding="utf-8")

    assert "contentInner.classList.add('workspace-route-wide');" in guidance_editor
    assert "currentGuidanceTab = _readGuidanceTab()" in guidance_editor
    assert "label: 'Guidance workspace'" in guidance_editor
    assert "label: 'Write'" in guidance_editor
    assert "label: 'Review'" in guidance_editor
    assert "label: 'Advanced'" in guidance_editor
    assert "await persistGuidanceDraft({ quiet: true })" in guidance_editor
    assert "body: guidanceDraftBody" in guidance_editor
    assert "Preview runtime" in guidance_editor
    assert "Next step" in guidance_editor
    assert "Discard unsaved guidance changes?" in guidance_editor
    assert "renderGuidanceContent(currentGuidance, currentPreview)" in guidance_editor
    assert "textarea.value = state.guidanceDraftBody || ''" in guidance_editor


def test_skills_surface_does_not_reintroduce_skills_only_layout_classes() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    skill_catalog = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "skill-catalog.js"
    ).read_text(encoding="utf-8")
    css = (
        repo_root / "octopus_registry" / "ui" / "css" / "main.css"
    ).read_text(encoding="utf-8")

    for legacy in (
        "skills-workspace",
        "skills-explainer-grid",
        "skills-meta-list",
        "skills-meta-block",
        "skills-markdown-preview",
        "skills-studio-create",
        "skills-studio-editor",
        "skills-history-panel",
        "skills-inline-form",
        "badge-primary",
        "list-row-selected",
    ):
        assert legacy not in skill_catalog
        assert legacy not in css


def test_conversation_empty_state_avoids_repeating_route_title() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    conversation_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-list.js"
    ).read_text(encoding="utf-8")

    assert "Nothing here yet." in conversation_list
    assert "No conversations yet." not in conversation_list


def test_dashboard_surfaces_recently_completed_tasks() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "dashboard.js"
    ).read_text(encoding="utf-8")

    assert "createGroupedSection(" in dashboard
    assert "'Tasks'" in dashboard
    assert "loadActiveTasks()" in dashboard
    assert "loadTasksByStatus(['queued', 'submitted', 'leased', 'running'])" in dashboard
    assert "loadTasksByStatus(['failed', 'cancelled', 'timed_out'])" in dashboard
    assert "label: 'Recently completed'" in dashboard
    assert "completed_since_iso: recentCompletedSinceIso()" in dashboard
    assert "status: 'completed'" in dashboard
    assert "function renderRunningSection(" not in dashboard
    assert "function renderRecentCompletedSection(" not in dashboard


def test_dashboard_uses_stable_board_layout_and_unified_snapshot_refresh() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "dashboard.js"
    ).read_text(encoding="utf-8")
    css = (
        repo_root / "octopus_registry" / "ui" / "css" / "main.css"
    ).read_text(encoding="utf-8")

    assert "dashboardBoard.className = 'dashboard-board';" in dashboard
    assert "primaryColumn.className = 'dashboard-column';" in dashboard
    assert "secondaryColumn.className = 'dashboard-column';" in dashboard
    assert "function refreshSnapshot(" in dashboard
    assert "refreshSummaryOnly" not in dashboard
    assert "refreshAgents" not in dashboard
    assert "refreshConversations" not in dashboard
    assert "refreshTasks" not in dashboard
    assert "refreshApprovals" not in dashboard
    assert ".dashboard-board {" in css
    assert ".dashboard-column {" in css
    assert ".dashboard-work-grid {" not in css


def test_dashboard_avoids_duplicate_subjects_between_summary_and_board_sections() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "dashboard.js"
    ).read_text(encoding="utf-8")

    assert "function renderApprovalSection(" in dashboard
    assert "function renderNeedsAttentionSection(" not in dashboard
    assert "buildNeedsAttention" not in dashboard
    assert "label: 'Queued backlog'" in dashboard
    assert "label: 'Unhealthy agents'" in dashboard
    assert "label: 'Tokens · 24h'" in dashboard
    assert "label: costAvailable ? 'Usage cost · 24h' : 'Usage cost unavailable'" in dashboard
    assert "value: String(summary.conversations?.open || 0)" not in dashboard
    assert "value: String(summary.tasks?.running || 0)" not in dashboard
    assert "value: String(summary.tasks?.failed_24h || 0)" not in dashboard
    assert "value: String(summary.agents?.connected || 0)" not in dashboard


def test_usage_views_surface_cached_and_uncached_token_breakdowns() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    usage_view = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "usage-view.js"
    ).read_text(encoding="utf-8")
    dashboard = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "dashboard.js"
    ).read_text(encoding="utf-8")
    event_renderers = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "event-renderers.js"
    ).read_text(encoding="utf-8")

    assert "cached_prompt_tokens_available" in usage_view
    assert "cached_completion_tokens_available" in usage_view
    assert "uncached" in usage_view
    assert "cached in" in dashboard
    assert "Input uncached" in event_renderers
    assert "Reply uncached" in event_renderers


def test_conversation_views_distinguish_task_threads() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    conversation_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-list.js"
    ).read_text(encoding="utf-8")
    agent_detail = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "agent-detail.js"
    ).read_text(encoding="utf-8")

    assert "conversation_type" in conversation_list
    assert "operational task thread" in conversation_list
    assert "Task thread" in conversation_list
    assert "conversation_type" in agent_detail
    assert "operational task thread" in agent_detail
    assert "Task thread" in agent_detail
    assert "No direct conversations." in agent_detail
    assert "taskThreadsGroup.hidden = false" in agent_detail
    detail = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-detail.js"
    ).read_text(encoding="utf-8")
    assert "externalRef.startsWith('routed-task:')" in detail
    assert "API.getTask(taskId)" in detail
    assert "conversationsLoaded = false" in agent_detail
    assert "document.getElementById('agent-conversations-list')" not in agent_detail
    assert "conversationListEl = list" in agent_detail
    assert "taskThreadListEl = taskList" in agent_detail
    assert "conversationPaginationEl = pag" in agent_detail
    assert "conversationPaginator = UI.createCursorPaginator" in agent_detail


def test_conversation_tab_keeps_the_parent_view_conversational() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    detail = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-detail.js"
    ).read_text(encoding="utf-8")

    assert "'delegation.submitted'" not in detail.split("const conversationLoadKinds =", 1)[1].split("];", 1)[0]
    assert "'delegation.completed'" not in detail.split("const conversationLoadKinds =", 1)[1].split("];", 1)[0]
    assert "'task.status'" not in detail.split("const conversationLoadKinds =", 1)[1].split("];", 1)[0]
    assert "return ['message.user', 'message.bot', 'approval.requested', 'error'].includes(event.kind || '');" in detail
    assert "@role:' + role" not in detail
    assert "@skill:' + value" not in detail
    assert "agent.role_selector" in detail
    assert "routingSkill.selector" in detail


def test_conversation_composer_enter_submits_exact_direct_assignments() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    detail = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-detail.js"
    ).read_text(encoding="utf-8")

    assert "function currentComposerRoutingState()" in detail
    assert "routingState.exactSuggestionMatch && routingState.instructions" in detail
    assert "sendMessage();" in detail.split("function handleComposerKeydown(e) {", 1)[1].split("if (!suggestionList.hidden && suggestionMatches.length) {", 1)[0]


def test_conversation_route_owns_scroll_on_wide_viewports() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    css = (
        repo_root / "octopus_registry" / "ui" / "css" / "main.css"
    ).read_text(encoding="utf-8")

    assert "#content > .content-inner.conversation-route-shell {" in css
    assert "height: calc(100dvh - (2 * clamp(18px, 1.8vw, 24px)));" in css
    assert ".conversation-page {" in css
    assert ".conversation-shell {" in css
    assert ".conversation-layout {" in css
    assert "overflow: hidden;" in css
    assert "flex: 1 1 auto;" in css


def test_agent_surfaces_distinguish_transport_from_execution_and_offer_reset() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    agent_detail = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "agent-detail.js"
    ).read_text(encoding="utf-8")
    agent_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "agent-list.js"
    ).read_text(encoding="utf-8")
    dashboard = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "dashboard.js"
    ).read_text(encoding="utf-8")
    api_js = (
        repo_root / "octopus_registry" / "ui" / "js" / "api.js"
    ).read_text(encoding="utf-8")

    assert "transport " in agent_detail
    assert "execution faulted" in agent_detail
    assert "Reset execution" in agent_detail
    assert "resetAgentExecutionFault" in agent_detail
    # Agents list now renders through Kit.agentsList (plan §8), which surfaces
    # an execution-faulted presence chip via the faulted flag.
    assert "Kit.agentsList(" in agent_list
    assert "executionFaulted: _executionFaulted" in agent_list
    assert "execution_faulted" in dashboard
    assert "badge-faulted" in dashboard
    assert "resetAgentExecutionFault" in api_js


def test_conversation_management_surfaces_are_dismissible_and_auto_close() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    detail = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-detail.js"
    ).read_text(encoding="utf-8")
    css = (
        repo_root / "octopus_registry" / "ui" / "css" / "main.css"
    ).read_text(encoding="utf-8")

    assert "let managementMode = 'closed';" in detail
    assert "function openManagement(" in detail
    assert "function closeManagement(" in detail
    assert "function scheduleManagementIdleClose(" in detail
    assert "function scheduleManagementSuccessClose(" in detail
    assert "skillsManageBtn.textContent = 'Skills';" in detail
    assert "settingsManageBtn.textContent = 'Settings';" in detail
    assert "textContent = '×';" in detail
    assert "managementPanel.hidden = !managementAgentId();" not in detail
    assert "openManagement('skills')" in detail
    assert "openManagement('settings'" in detail
    assert "&& !pendingSkillSetup" in detail
    assert "clearRequestedActivationSkill();" in detail
    assert "requestConversationSkillActivation(" in detail
    assert ".conversation-management-close {" in css


def test_live_refresh_lists_use_signature_skips_for_keyed_subtrees() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helper = (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "ui.js"
    ).read_text(encoding="utf-8")
    conversation_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-list.js"
    ).read_text(encoding="utf-8")
    task_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "task-list.js"
    ).read_text(encoding="utf-8")

    assert "onBeforeElUpdated" in helper
    assert "fromEl.dataset.signature === toEl.dataset.signature" in helper
    assert "signature: rowSignature" in conversation_list
    assert "item.dataset.signature" in task_list


def test_live_refresh_signatures_use_rendered_time_labels_not_raw_timestamps() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    files = {
        "agent-detail.js": [
            "heartbeatLabel: agent.last_heartbeat_at ? UI.relativeTime(agent.last_heartbeat_at) : ''",
            "lastSeenLabel: worker.last_seen_at ? UI.relativeTime(worker.last_seen_at) : ''",
            "updatedLabel: UI.relativeTime(item.updated_at || item.created_at)",
        ],
        "dashboard.js": [
            "heartbeatLabel: item.last_heartbeat_at ? UI.relativeTime(item.last_heartbeat_at) : ''",
            "updatedLabel: UI.relativeTime(item.updated_at || item.created_at)",
        ],
        "task-list.js": [
            "updatedLabel: UI.relativeTime(task.updated_at || task.created_at)",
        ],
        "approval-list.js": [
            "createdLabel: item.created_at ? UI.relativeTime(item.created_at) : ''",
            "expiresLabel: item.expires_at ? UI.formatApprovalTime(item.expires_at) : ''",
        ],
        "conversation-detail.js": [
            "updatedLabel: data.updated_at ? UI.relativeTime(data.updated_at) : ''",
            "updatedLabel: UI.relativeTime(task.updated_at || task.created_at)",
        ],
        "conversation-list.js": [
            "updatedLabel: UI.relativeTime(item.updated_at || item.created_at)",
        ],
    }

    forbidden = {
        "heartbeat: String(",
        "lastSeen: String(",
        "updatedAt: String(",
        "createdAt: String(",
        "expiresAt: String(",
    }

    for name, markers in files.items():
        text = (
            repo_root
            / "octopus_registry"
            / "ui"
            / "js"
            / "components"
            / name
        ).read_text(encoding="utf-8")
        for marker in markers:
            assert marker in text, f"{name} must sign rendered time labels"
        for marker in forbidden:
            assert marker not in text, f"{name} must not sign raw timestamp churn"

    conversation_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-list.js"
    ).read_text(encoding="utf-8")
    assert "state: String(agent.connectivity_state || '')" not in conversation_list


def test_conversation_compact_mode_keeps_timeline_scrollable() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    css = (
        repo_root / "octopus_registry" / "ui" / "css" / "main.css"
    ).read_text(encoding="utf-8")

    compact_rule = ".conversation-panel.conversation-panel-compact .chat-timeline {\n    flex: 1 1 auto;\n    overflow-y: auto;\n}"
    assert compact_rule in css


def test_agent_list_uses_disconnected_not_offline_filter() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    agent_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "agent-list.js"
    ).read_text(encoding="utf-8")
    kit = (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "kit.js"
    ).read_text(encoding="utf-8")

    assert "Kit.agentsList(" in agent_list
    assert "'offline'" not in agent_list
    assert "'agents.presence.disconnected': 'Disconnected'" in kit
    assert "'agents.presence.offline'" not in kit


def test_ui_helpers_cover_shared_registry_patterns() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helper = (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "ui.js"
    ).read_text(encoding="utf-8")

    for marker in [
        "function subscribeWithRefresh(",
        "function createSegmentedControl(",
        "function createCursorPaginator(",
        "function memoizedRender(",
        "function createTaskActionButtons(",
        "function createAgentManagementDropdown(",
        "function buildConversationTypeBadge(",
    ]:
        assert marker in helper

    assert "function createSkeletonNodes(" not in helper
    assert "function renderSkeletons(" not in helper


def test_layout_spacing_uses_shared_css_tokens() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    css = (
        repo_root / "octopus_registry" / "ui" / "css" / "main.css"
    ).read_text(encoding="utf-8")

    assert "--card-padding: 20px;" in css
    assert "--panel-padding: 16px;" in css
    assert "--compact-card-padding: 12px;" in css
    assert ".workspace-header-compact {\n    gap: var(--space-2);\n}" in css
    assert ".list-shell {\n    display: grid;\n    gap: var(--space-3);\n}" in css
    assert ".agent-detail-grid {\n    display: grid;\n    gap: var(--space-3);\n}" in css
    assert ".workspace-section .list-container" not in css
    assert ".dashboard-grid .list-container" not in css
    assert "gap: 10px" not in css
    assert "row-gap: 6px" not in css


def test_conversation_detail_is_split_into_supporting_modules() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    index_html = (
        repo_root / "octopus_registry" / "ui" / "index.html"
    ).read_text(encoding="utf-8")

    assert '/ui/js/components/composer-autocomplete.js' in index_html
    assert '/ui/js/components/event-renderers.js' in index_html
    assert '/ui/js/components/task-board.js' in index_html
    assert 'class="nav-icon"' in index_html
    assert 'data-icon=' not in index_html

    conversation_detail = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-detail.js"
    ).read_text(encoding="utf-8")
    event_renderers = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "event-renderers.js"
    ).read_text(encoding="utf-8")
    task_board = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "task-board.js"
    ).read_text(encoding="utf-8")
    autocomplete = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "composer-autocomplete.js"
    ).read_text(encoding="utf-8")

    assert "function _createConversationEventElement(" not in conversation_detail
    assert "function _createConversationTaskCard(" not in conversation_detail
    assert "function _parseConversationTargetSelector(" not in conversation_detail
    assert "function _createConversationEventElement(" in event_renderers
    assert "function _createConversationTaskCard(" in task_board
    assert "function _parseConversationTargetSelector(" not in autocomplete
    assert "function _extractConversationTargetSelectorMessage(" not in autocomplete


def test_task_event_cards_render_outcomes_in_expandable_body_without_duplicate_leads() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    event_renderers = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "event-renderers.js"
    ).read_text(encoding="utf-8")
    css = (
        repo_root / "octopus_registry" / "ui" / "css" / "main.css"
    ).read_text(encoding="utf-8")
    task_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "task-list.js"
    ).read_text(encoding="utf-8")

    assert "const leadText = _eventLeadText(" not in event_renderers
    assert "event-card-lead" not in event_renderers
    assert "content.className = terminalWithOutcome ? 'event-text-block event-text-block-outcome' : 'event-text-block';" in event_renderers
    assert ".event-text-block-outcome {" in css
    assert "UI.renderMetadataGrid([" in task_list
    assert ".task-item-facts {" in css


def test_components_use_shared_refresh_and_do_not_duplicate_ws_invalidation_plumbing() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    component_dir = repo_root / "octopus_registry" / "ui" / "js" / "components"
    helper = (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "ui.js"
    ).read_text(encoding="utf-8")

    assert "function subscribeWithRefresh(" in helper

    for name in [
        "routing-policy-list.js",
        "usage-view.js",
        "skill-catalog.js",
        "guidance-editor.js",
        "agent-list.js",
        "approval-list.js",
        "conversation-list.js",
        "task-list.js",
        "agent-detail.js",
        "dashboard.js",
    ]:
        text = (component_dir / name).read_text(encoding="utf-8")
        assert "UI.subscribeWithRefresh(" in text
        assert "WS.subscribe(" not in text

    conversation_detail = (component_dir / "conversation-detail.js").read_text(encoding="utf-8")
    assert "WS.subscribe(`conversation:${convoId}`" in conversation_detail
