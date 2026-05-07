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
    usage_view = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "usage-view.js"
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
    assert "API.listAgents({ limit: 100 })" in workspace
    assert "API.listRoutingSkills()" in workspace
    assert "_agentsAdvertisingSkill(" in workspace
    assert "_selectorAgentSkillsSection(" in workspace
    assert "return UI.isHumanAssignableSkillName(item?.skill_name || item);" in workspace
    assert "Available skills" in workspace
    assert "preferred_agent_id" in workspace

    # Rehearsal API the workspace drives
    assert "API.listRehearsalSessions(" in workspace
    assert "API.respondRehearsalSession(" in workspace
    assert "API.listProtocolScenarios(" in workspace
    assert "const refreshRunId = rehearsal.runId;" in workspace
    assert "API.getProtocolRun(refreshRunId)" in workspace

    # Authoring API the kit surface drives
    assert "API.getProtocolAuthoringOptions()" in workspace
    assert "API.listProtocolTemplates()" in workspace
    assert "API.createProtocolDraft(" in workspace
    assert "created?.run?.protocol_run_id" in workspace
    assert "API.saveProtocolDraft(" in workspace
    assert "API.publishProtocol(" in workspace
    assert "API.createProtocolTemplate(" in workspace
    assert "protocol-template-chooser" in workspace
    assert "onClick: () => void _createBlankDraft()" in workspace
    assert "protocolTemplates.length" in workspace
    assert "API.archiveProtocol(" in workspace
    assert "API.deleteProtocol(" in workspace
    assert "API.validateProtocol(" in workspace
    assert "ifMatch: draftRevision" in workspace
    assert "PROTOCOL_DRAFT_CONFLICT" in workspace
    assert "state: 'conflict'" in workspace
    assert "API.previewSelectorResolution(" not in workspace
    assert "_reloadServerDraftConflict" in workspace
    assert "_overwriteServerDraftConflict" in workspace
    assert "let editorMode = { kind: 'idle'" in workspace
    assert "_startStageInsert(" in workspace
    assert "_confirmStageInsert(" in workspace
    assert "_rewriteKeyReferences(" in workspace
    assert "inputs: (stage.inputs || []).map" in workspace
    assert "outputs: (stage.outputs || []).map" in workspace
    assert "_stageTransitionId(" in workspace
    assert "_transitionEntries(" in workspace
    assert "_isAuthoringAssignableAgent(" in workspace
    assert "_authoringAssignableAgents(" in workspace
    assert "_selectorCatalogEntries(" in workspace
    assert "_documentSelectorValues(" in workspace
    assert "if (catalog.length) return String(catalog[0].value || '');" in workspace
    assert "pendingStage.stage_key = _slugSuggestion(pendingStage.display_name);" in workspace
    assert "String(_slugSuggestion(displayName) || pendingStage.stage_key || 'step')" in workspace
    assert "_selectorEditor(" in workspace
    assert "_currentAuthoringSurface()" in workspace
    assert "operator_surface_available" in workspace
    assert "_normalizeStageWriteAccess(" in workspace
    assert "_ensureStageAssignmentParticipants(" in workspace
    assert "participant_key: participantKey" in workspace
    assert "display_name: _assignmentParticipantLabel(nextStage.selector) || participantKey" in workspace
    assert "write_capable: Boolean(stage?.write_capable || outputs.length)" in workspace
    assert "label: 'Workspace path', help: Kit.dict.label('protocol.artifact.path.help'), placeholder: Kit.dict.label('protocol.artifact.path.placeholder'), commitOnInput: true" in workspace
    assert "Available now" in workspace
    assert "Preferred agent:" in workspace
    assert "quickstart-chip" in workspace
    assert "pins the step to" in workspace
    assert "Required skill" in workspace
    assert "Pin matching agent (optional)" in workspace
    assert "Specific agent" in workspace
    assert "Show workflow map" in workspace
    assert "Hide workflow map" in workspace
    assert "workflow_map" in workspace
    assert "let canvasViewport = { zoom: 'fit' }" in workspace
    assert "_selectionFromQuery(" in workspace
    assert "_selectionQueryState(" in workspace
    assert "_buildWorkflowProjection(" in workspace
    assert "_workflowStoryScene(" in workspace
    assert "_focusedWorkflowScene(" in workspace
    assert "_workflowMapEl(" in workspace
    assert "_progressiveWorkflowEl(" in workspace
    assert "_segmentPanelEl(" in workspace
    assert "_participantEditorShell(" in workspace
    assert "_routeEditorPanel(" in workspace
    assert "_stageRoutingPanel(" in workspace
    assert "window.addEventListener('resize', onResize);" in workspace
    assert "_startParticipantInsert(" not in workspace
    assert "_confirmParticipantInsert(" not in workspace
    assert "'Create new role…'" in workspace
    assert "Assignment" in workspace
    assert "Workflow stages" in workspace
    assert "Edit participant assignment" not in workspace
    assert "+ Add participant" not in workspace
    assert "Visual map" not in workspace
    assert "Workflow phases" not in workspace
    assert "Planner role" not in workspace
    assert "Reviewer role" not in workspace
    assert "_startConnectMode(" not in workspace
    assert "_cancelTransitionConnect(" not in workspace
    assert "_commitConnectField(" not in workspace
    assert "'Topology'" not in workspace
    assert "'Workflow overview'" not in workspace

    # Runs route (kept until Step 7)
    assert "API.listProtocolRuns({" in workspace
    assert "cursor: runPaginator ? runPaginator.cursor : 0" in workspace
    assert "API.getProtocolRun(requestedRunId)" in workspace
    assert "API.listProtocolIssues({" in workspace
    assert "API.actOnProtocolRun(" in workspace
    assert "btn.dataset.runAction = spec.action;" in workspace
    assert "event.currentTarget?.dataset?.runAction" in workspace
    assert "spec.action === 'cancel' ? 'btn btn-danger' : 'btn btn-primary'" in workspace
    assert "stageProgress: _runStageProgressData(currentRun)" in workspace
    assert "renderExpanded: () => _buildRunDetailPanel()" in workspace
    assert "run-stage-timeline" in workspace
    assert "const currentRunStageExecution = () =>" in workspace
    assert "run.current_stage_execution_id" in workspace
    assert "return latestStageExecution(matchingAttempts)" in workspace
    assert "WS.subscribe(`protocol-run:${currentRunId}`" in workspace
    assert "UI.subscribeWithRefresh(cleanups, 'tasks'" in workspace
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
        "_applyParticipantSuggestion(",
        "_applyParticipantDraftSuggestion(",
        "_participantSelectorSuggestions(",
        "_selectorFieldsFromString(",
        "_saveNew(",
        "_startRoleInsert(",
        "_confirmRoleInsert(",
        "_roleEditorShell(",
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
    assert "UI.readQueryParam('protocol_view'" not in workspace
    assert "protocol_view:" in workspace  # kept in _writeState to clear legacy URLs
    assert "API.getProtocolTemplate(" in workspace
    assert "API.getProtocolAuthoringManifest(" not in workspace
    assert "loadDefaultTemplate" not in workspace
    assert "UI.defaultVisibleRecords(\n            Array.isArray(protocolTemplates) ? protocolTemplates : []" in workspace

    # Protocol authoring lifecycle subscription is retained
    assert "UI.subscribeWithRefresh(cleanups, 'agents'" in workspace
    assert "UI.subscribeWithRefresh(cleanups, 'protocols'" in workspace
    assert "UI.subscribeWithRefresh(cleanups, 'summary', () => Promise.all([" in workspace

    # Router wiring
    assert "renderProtocolTemplateRedirect" not in app_js
    assert "Router.register('/ui/templates'" not in app_js
    assert "Router.register('/ui/gallery'" not in app_js
    assert "renderGallery" not in app_js
    assert "Router.register('/ui/runs', renderProtocolRuns);" in app_js
    assert "Router.register('/ui/protocol-runs', renderProtocolRuns);" not in app_js
    assert "path.startsWith('/ui/protocol-runs')" not in router_js


def test_protocol_artifact_runtime_controls_recover_after_status_or_start_failures() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "protocol-workspace.js"
    ).read_text(encoding="utf-8")

    assert "const runtimeActionErrorMessage = (err" in workspace
    assert "PROTOCOL_ARTIFACT_RUNTIME_MANIFEST_NOT_RUN_READY" in workspace
    assert ". Revise the artifact package first." in workspace
    assert "const setRuntimeActionableFailure = (message) =>" in workspace
    assert "runtimeBtn.disabled = false;" in workspace
    assert "runtimeBtn.textContent = currentRuntimeStatus === 'failed' ? 'Restart app' : 'Start app';" in workspace
    assert "Could not check current app status:" in workspace
    assert "setRuntimeActionableFailure(`Start failed: ${runtimeActionErrorMessage" in workspace
    assert "Checking current app status." not in workspace
    assert "Runtime declared. Start the app to exercise this outcome." in workspace


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
    assert ".kit-workflow-shell-scene" in css
    assert ".kit-workflow-outline" in css
    assert ".kit-workflow-cy-host" in css
    assert ".kit-workflow-outline-item" in css
    assert ".kit-workflow-outline-child" in css
    assert ".kit-workflow-controls" in css
    assert ".kit-workflow-viewport-cy" in css
    assert ".kit-protocol-segment-panel" in css
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
    assert 'href="/ui/templates"' not in index_html
    assert 'href="/ui/protocols"' in index_html
    assert '<li class="nav-group">Team</li>' not in index_html
    assert index_html.index('<li class="nav-group">Work</li>') < index_html.index('href="/ui/conversations"') < index_html.index('href="/ui/runs"') < index_html.index('href="/ui/agents"') < index_html.index('<li class="nav-group">Build</li>')
    assert index_html.index('<li class="nav-group">Build</li>') < index_html.index('href="/ui/protocols"') < index_html.index('href="/ui/skills"') < index_html.index('href="/ui/guidance"') < index_html.index('<li class="nav-group">Operations</li>')
    assert index_html.index('<li class="nav-group">Operations</li>') < index_html.index('href="/ui/"')


def test_management_views_use_shared_memory_cache_for_stale_while_revalidate() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helper = (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "ui.js"
    ).read_text(encoding="utf-8")
    css = (
        repo_root / "octopus_registry" / "ui" / "css" / "main.css"
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

    assert "Find reusable skills for conversations and protocol stages." in skill_catalog
    assert "Skill catalog" in skill_catalog
    assert "Choose a bot only when you need to manage installation or drafts." in skill_catalog
    assert "UI.isHumanAssignableSkillName(name)" in skill_catalog
    assert "String(selectedSkillOrigin || '') === 'global'" in skill_catalog
    assert "Use this in a protocol stage by choosing Assignment, then Existing skill." in skill_catalog
    assert "contentInner.classList.add('workspace-route-wide');" in skill_catalog
    assert "workspace.classList.add('dashboard-board-stacked');" in skill_catalog
    assert "detailEl.hidden = true;" in skill_catalog
    assert "skill-inline-detail" in skill_catalog
    assert "function _renderSelectedSkillInlineDetail(selected)" in skill_catalog
    assert "function _buildSelectedSkillDetailNodes(selected)" in skill_catalog
    assert "function _renderAgentSkillIntro(agentLabel)" in skill_catalog
    assert "agent-skill-intro" in skill_catalog
    assert "Loading skill instructions…" in skill_catalog
    assert "Instructions preview" in skill_catalog
    assert "API.getSkillDetail(agent.agent_id, skillName)" in skill_catalog
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
    assert "'New skill'" in skill_catalog
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
    """Plan §8: agents list + detail migrate to Kit primitives; operational
    diagnostics remain available behind one disclosure instead of the default path."""
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
    assert "selectedAgentId = UI.readQueryParam('agent_id', '')" in agent_list
    assert "selectedId: selectedAgentId" in agent_list
    assert "renderExpanded: _renderAgentInlineDetail" in agent_list
    assert "Open agent workspace" in agent_list
    assert "Open skills" in agent_list
    assert "trustTier: String(agent.trust_tier" in agent_list
    assert "currentCapacity: Number(agent.current_capacity" in agent_list
    assert "softDeletedAt: String(agent.soft_deleted_at" in agent_list

    # Detail surfaces
    assert "Kit.agentSummary(" in agent_detail
    assert "Kit.selectorResolutionPreview(" in agent_detail
    assert "function buildOperationsCard(" in agent_detail
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
    kit = (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "kit.js"
    ).read_text(encoding="utf-8")

    assert "window.RegistrySkillHub = RegistrySkillHub;" in skill_catalog
    assert "function _isGeneratedSkill(" in skill_catalog
    assert "!_isGeneratedSkill(skill)" in skill_catalog
    assert "!UI.isGeneratedTimestampName(skill)" in kit
    assert "function buildSkillsCard(agent) {" in agent_detail
    assert "Open Skills workspace" in agent_detail
    assert "Router.navigate(skillsWorkspaceHref())" in agent_detail
    assert "Open a conversation with ${label}" in skill_catalog
    assert "function openSkillsDrawer(" not in agent_detail
    assert "Open Skills page" not in agent_detail
    assert "Quick actions live here." not in agent_detail
    assert "Available skills" in agent_detail
    assert "buildSkillsCard(agent)," in agent_detail
    assert "buildOperationsCard(agent, workers)," in agent_detail
    assert "quickstart-chip static" in agent_detail
    assert "skills-drawer-dialog" not in css
    assert "skills-drawer-overlay" not in css
    assert "renderExpanded = null" in kit
    assert "agent-inline-detail" in kit


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


def test_default_work_surfaces_use_shared_generated_record_visibility() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helper = (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "ui.js"
    ).read_text(encoding="utf-8")
    css = (
        repo_root / "octopus_registry" / "ui" / "css" / "main.css"
    ).read_text(encoding="utf-8")
    kit = (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "kit.js"
    ).read_text(encoding="utf-8")
    conversation_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-list.js"
    ).read_text(encoding="utf-8")
    dashboard = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "dashboard.js"
    ).read_text(encoding="utf-8")
    agent_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "agent-list.js"
    ).read_text(encoding="utf-8")
    task_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "task-list.js"
    ).read_text(encoding="utf-8")
    workspace = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "protocol-workspace.js"
    ).read_text(encoding="utf-8")
    skill_catalog = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "skill-catalog.js"
    ).read_text(encoding="utf-8")
    usage_view = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "usage-view.js"
    ).read_text(encoding="utf-8")

    assert "function isDefaultHiddenRecord(" in helper
    assert "function defaultVisibleRecords(" in helper
    assert "isGeneratedOrRehearsalText" in helper
    assert "draft-[0-9a-f]{8}" in helper
    assert "[-_]\\d{1,4}$" in helper
    assert "item.includes('e2e')" in helper
    assert "item.includes('spec')" in helper
    assert "const canonical = normalized.replace(/[-_]+/g, ' ');" in helper
    assert "canonical.startsWith('meta protocol composer ')" in helper
    assert "hiddenFields.some((field) => isGeneratedOrRehearsalText(record?.[field]))" in helper
    assert "'compose-assistant-protocol'" in helper
    assert "'publish-report'" in helper
    assert "'current_stage_key'" in helper
    assert "function updateQueryToggleLink(" in helper
    assert "function updateGeneratedAuditToggleLink(" in helper
    assert "filter-toggle-link" in css

    assert "UI.defaultVisibleRecords(rawRows, { includeHidden: includeGenerated })" in conversation_list
    assert "let currentType = UI.readQueryParam('type', 'conversation');" in conversation_list
    assert "&& !UI.isDefaultHiddenRecord(agent)" in conversation_list
    assert "UI.updateGeneratedAuditToggleLink(generatedToggle, includeGenerated, 'work')" in conversation_list
    assert "approvalsLink" not in conversation_list

    assert "!item.protocol_run_id && !UI.isDefaultHiddenRecord(item)" in dashboard
    assert "UI.defaultVisibleRecords(dashboardState.conversations.conversations || [], { includeHidden: false })" in dashboard
    assert "UI.defaultVisibleRecords(dashboardState.agents.agents || dashboardState.agents || [], { includeHidden: false })" in dashboard
    assert "function visibleDashboardRuns()" in dashboard
    assert "function visibleDashboardProtocols()" in dashboard
    assert "function loadSecondarySnapshot(" in dashboard
    assert "void loadSecondarySnapshot({ soft });" in dashboard
    assert "API.listProtocolRuns({ limit: UI.DEFAULT_PAGE_LIMIT, include_generated: '0' })" in dashboard
    assert "API.listProtocols({ limit: 50 })" in dashboard
    assert "Filtered by default · generated/audit totals inside" in dashboard

    assert "UI.defaultVisibleRecords(currentAgents, { includeHidden: includeGenerated })" in agent_list
    assert "UI.updateGeneratedAuditToggleLink(generatedToggle, includeGenerated, 'agents')" in agent_list
    assert "!task.protocol_run_id && !UI.isDefaultHiddenRecord(task)" in task_list
    assert "function _visibleTask(task)" in task_list
    assert "renderSummary({ tasks: Object.fromEntries(entries) });" in task_list
    assert "include_generated: currentProtocolRunId || includeGenerated ? '1' : '0'" in task_list
    assert "API.getSummary()" not in task_list
    assert "<h2>Delegations</h2>" in task_list

    assert "UI.defaultVisibleRecords(protocols, { includeHidden: includeGeneratedCatalog })" in workspace
    assert "label: 'Generated drafts'" in workspace
    assert "const PROTOCOL_RUN_VIEW_FILTER_OPTIONS = [" in workspace
    assert "let runViewFilter = _protocolRunViewFilterValue(UI.readQueryParam('view', 'recent'));" in workspace
    assert "const runSource = [...(runs || [])];" in workspace
    assert "if (!_runMatchesViewFilter(item, issue)) return false;" in workspace
    assert "Improve this run" in workspace
    assert "function _runImprovementContext(runDetail)" in workspace
    assert "constraints_text: _runImprovementContext(sourceRun)" in workspace
    assert "UI.updateGeneratedAuditToggleLink(generatedToggle, includeGenerated, 'runs')" in workspace
    assert "No normal runs match this filter." in workspace
    assert "String(item?.conversation_type || 'conversation') !== 'task_thread'" in usage_view
    assert "UI.defaultVisibleRecords(candidates, { includeHidden: includeGenerated })" in usage_view
    assert "UI.updateGeneratedAuditToggleLink(generatedToggle, includeGenerated, 'usage')" in usage_view
    assert "return [...visible, ...generated];" in kit
    assert "&& !UI.isDefaultHiddenRecord(agent)" in skill_catalog


def test_dashboard_surfaces_recently_completed_tasks() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "dashboard.js"
    ).read_text(encoding="utf-8")

    assert "createGroupedSection(" in dashboard
    assert "'Work needing attention'" in dashboard
    assert "'Tasks'" not in dashboard
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
    assert "function openCleanupDialog()" in dashboard
    assert "API.cleanupWorkspaceData({" in dashboard
    assert "'Clean workspace data'" in dashboard
    assert "refreshSummaryOnly" not in dashboard
    assert "refreshAgents" not in dashboard
    assert "refreshConversations" not in dashboard
    assert "refreshTasks" not in dashboard
    assert "refreshApprovals" not in dashboard
    assert ".dashboard-board {" in css
    assert ".dashboard-column {" in css
    assert ".dashboard-work-grid {" not in css
    assert ".kit-catalog-search {\n        flex: 0 1 auto;" in css


def test_dashboard_avoids_duplicate_subjects_between_summary_and_board_sections() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "dashboard.js"
    ).read_text(encoding="utf-8")

    assert "function renderApprovalSection(" in dashboard
    assert "function renderNeedsAttentionSection(" not in dashboard
    assert "buildNeedsAttention" not in dashboard
    assert "label: 'Queued backlog'" in dashboard
    assert "label: 'Agents needing attention'" in dashboard
    assert "function visibleDashboardAgents()" in dashboard
    assert "function dashboardAgentHealth(summary)" in dashboard
    assert "label: 'Active or stuck runs'" in dashboard
    assert "with issues" in dashboard
    assert "label: 'Usage review'" in dashboard
    assert "label: 'Tokens · 24h'" not in dashboard
    assert "label: costAvailable ? 'Usage cost · 24h' : 'Usage cost unavailable'" not in dashboard
    assert "value: String(summary.conversations?.open || 0)" not in dashboard
    assert "value: String(summary.tasks?.running || 0)" not in dashboard
    assert "value: String(summary.tasks?.failed_24h || 0)" not in dashboard
    assert "value: String(summary.agents?.connected || 0)" not in dashboard


def test_usage_views_surface_cached_and_uncached_token_breakdowns() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    usage_view = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "usage-view.js"
    ).read_text(encoding="utf-8")
    event_renderers = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "event-renderers.js"
    ).read_text(encoding="utf-8")

    assert "cached_prompt_tokens_available" in usage_view
    assert "cached_completion_tokens_available" in usage_view
    assert "uncached" in usage_view
    assert "cached" in usage_view
    assert "Input uncached" in event_renderers
    assert "Reply uncached" in event_renderers


def test_conversation_views_distinguish_delegation_threads() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    conversation_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-list.js"
    ).read_text(encoding="utf-8")
    agent_detail = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "agent-detail.js"
    ).read_text(encoding="utf-8")

    assert "conversation_type" in conversation_list
    assert "delegation thread" in conversation_list
    assert "Delegation thread" in conversation_list
    assert "Open linked work" in conversation_list
    assert "conversation_type" in agent_detail
    assert "delegation thread" in agent_detail
    assert "Delegation thread" in agent_detail
    assert "No direct conversations." in agent_detail
    assert "taskThreadsGroup.hidden = false" in agent_detail
    detail = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-detail.js"
    ).read_text(encoding="utf-8")
    api_js = (
        repo_root / "octopus_registry" / "ui" / "js" / "api.js"
    ).read_text(encoding="utf-8")
    assert "externalRef.startsWith('routed-task:')" in api_js
    assert "API.routedTaskIdFromConversation(conversationData)" in detail
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
    assert "label: 'Linked work'" in detail
    assert "label: 'Tasks'" not in detail
    assert "return ['message.user', 'message.bot', 'approval.requested', 'error'].includes(event.kind || '');" in detail
    assert "let eventLoadRequestToken = 0" in detail
    assert "maybeAdoptOperationalView();" in detail
    assert "if (requestToken !== eventLoadRequestToken || requestView !== activeView)" in detail
    assert "const expansionState = activityExpansionState(visibleEvents);" in detail
    assert "renderEventElement(event, expansionState)" in detail
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
    assert "API.conversationAction(convoId, 'direct_assign'" in detail
    assert "selector: directAssignSelector(routingState.exactSuggestionMatch)" in detail
    assert "message_text: routingState.text" in detail
    assert "sendMessage();" in detail.split("function handleComposerKeydown(e) {", 1)[1].split("if (!suggestionList.hidden && suggestionMatches.length) {", 1)[0]


def test_start_conversation_entrypoints_create_new_threads() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    agent_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "agent-list.js"
    ).read_text(encoding="utf-8")
    agent_detail = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "agent-detail.js"
    ).read_text(encoding="utf-8")
    conversation_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-list.js"
    ).read_text(encoding="utf-8")

    assert "API.openConversationForAgent(agent.id, { preferExisting: false })" in agent_list
    assert "preferExisting: false" in agent_detail.split("async function openAgentConversation", 1)[1].split("function createAgentActionButton", 1)[0]
    assert "Start a new conversation with" in conversation_list
    assert "preferExisting: false" in conversation_list.split("const conversation = await API.openConversationForAgent", 1)[1].split("});", 1)[0]


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


def test_conversation_pagination_is_addressable_and_visible() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    conversation_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-list.js"
    ).read_text(encoding="utf-8")
    ui_helpers = (repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "ui.js").read_text(encoding="utf-8")
    css = (repo_root / "octopus_registry" / "ui" / "css" / "main.css").read_text(encoding="utf-8")

    assert "UI.readQueryParam('cursor', '0')" in conversation_list
    assert "initialStack: initialCursorStack" in conversation_list
    assert "cursor: paginator && Number(paginator.cursor) > 0 ? paginator.cursor : ''" in conversation_list
    assert "info: `Page ${paginator.stackLength + 1}`" in conversation_list
    assert "onChange({ cursor, hasPrev: cursorStack.length > 0, stackLength: cursorStack.length });" in ui_helpers
    assert "#content > .content-inner.conversation-list-route-shell .pagination {" in css
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

    assert "transport " not in agent_detail
    assert "Execution faulted" in agent_detail
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
    assert "protocolsManageBtn.textContent = 'Protocols';" in detail
    assert "textContent = '×';" in detail
    assert "managementPanel.hidden = !managementAgentId();" not in detail
    assert "openManagement('skills')" in detail
    assert "openManagement('settings'" in detail
    assert "openManagement('protocols'" in detail
    assert "&& !pendingSkillSetup" in detail
    assert "clearRequestedActivationSkill();" in detail
    assert "requestConversationSkillActivation(" in detail
    assert ".conversation-management-close {" in css


def test_conversation_protocol_launch_is_browser_native_and_restorable() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    detail = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-detail.js"
    ).read_text(encoding="utf-8")
    conversation_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "conversation-list.js"
    ).read_text(encoding="utf-8")
    api_js = (
        repo_root / "octopus_registry" / "ui" / "js" / "api.js"
    ).read_text(encoding="utf-8")
    helper = (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "ui.js"
    ).read_text(encoding="utf-8")
    kit = (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "kit.js"
    ).read_text(encoding="utf-8")

    assert "function renderProtocolsPanel()" in detail
    assert "function conversationProtocolOptions(" in detail
    assert "conversationProtocolLabel(" in detail
    assert "Showing the latest version of each generated protocol family." in detail
    assert "Protocol scope" in detail
    assert "will not rewrite the workflow schema at launch time." in detail
    assert "Conversation protocols" in detail
    assert "Start a published protocol" in detail
    assert "API.listProtocols({ lifecycle_state: 'published', limit: 100 })" in detail
    assert "API.listConversationProtocolRuns(convoId, conversationData, { limit: 25 })" in detail
    assert "function ensureConversationProtocolLaunchDetails(" in detail
    assert "API.getProtocolVersion(protocolId, versionId)" in detail
    assert "function loadConversationLinkedRuns(" in detail
    assert "requestedManagementMode !== 'protocols'" in detail
    assert "API.listConversationProtocolRuns(key, meta, { limit: 5 })" in conversation_list
    assert "function routedTaskIdFromConversation(conversation)" in api_js
    assert "externalRef.startsWith('routed-task:')" in api_js
    assert "request('GET', `/v1/tasks/${encodeURIComponent(taskId)}`)" in api_js
    assert "request('GET', `/v1/protocol-runs/${encodeURIComponent(runId)}`)" in api_js
    assert "API.createProtocolRun({" in detail
    assert "root_conversation_id: convoId" in detail
    assert "entry_agent_id: agentId" in detail
    assert "Kit.protocolRunLaunchForm({" in detail
    assert "includeWorkspace: false" in detail
    assert "fields: selectedProtocol?.launchFields || null" in detail
    assert "Kit.protocolArtifactContractPanel(selectedProtocol.launchDocument)" in detail
    assert "problem_statement: state.problemStatement" in detail
    assert "const launchValues = launchForm.readValues();" in detail
    assert "const problemStatement = String(launchValues.problem_statement || '').trim();" in detail
    assert "Object.keys(launchValues).forEach((key) => {" in detail
    assert "function normalizedProtocolRunLaunchFields(" in kit
    assert "rawKey === 'goal' ? 'problem_statement' : rawKey" in kit
    assert "if (!seen.has('problem_statement'))" in kit
    assert "constraints_json: constraints" in detail
    assert "raw private data" not in detail
    assert "requestedManagementMode === 'protocols'" in detail
    assert "value === 'skills' || value === 'settings' || value === 'protocols'" in detail


def test_protocol_authoring_exposes_real_run_separate_from_rehearsal() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "protocol-workspace.js"
    ).read_text(encoding="utf-8")
    kit = (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "kit.js"
    ).read_text(encoding="utf-8")

    assert "'protocol.action.run': 'Run protocol'" in kit
    assert "primaryActions = ['validate', 'publish', 'run']" in kit
    assert "function protocolRunLaunchForm(" in kit
    assert "function runStageProgressRail(" in kit
    assert "runStageProgressRail," in kit
    assert "_compressedStageProgressItems(items, currentIndex)" in kit
    assert "const terminalRun = !activeRun && Boolean(normalizedRunStatus);" in kit
    assert "normalizedRunStatus === 'completed' && index <= currentIndex" in kit
    assert "fields = null" in kit
    assert "field.default_value" in kit
    assert "function protocolRunLaunchFields()" in kit
    assert "context" in kit
    assert "constraints" in kit
    assert "protocolArtifactContractPanel" in kit
    assert "Expected outputs" not in kit
    assert "manufacturing analytics" not in kit
    assert "raw private data" not in kit
    assert "function _openRunProtocolDialog()" in workspace
    assert "Start a real run from the latest published version." in workspace
    assert "Dry-run rehearsal" in workspace
    assert "is_rehearsal: true" in workspace
    assert "Kit.protocolRunLaunchForm({" in workspace
    assert "Kit.protocolArtifactContractPanel(draft.document)" in workspace
    assert "fields: _protocolRunLaunchFields()" in workspace
    assert "includeWorkspace: true" in workspace
    assert "Router.navigate(`/ui/runs?run_id=${encodeURIComponent(runId)}`)" in workspace


def test_protocol_assignment_keeps_skill_selection_scoped_and_searchable() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "protocol-workspace.js"
    ).read_text(encoding="utf-8")

    assert "{ value: 'skill', label: 'Existing skill' }" in workspace
    assert "{ value: 'new_skill', label: 'New skill needed' }" in workspace
    assert "searchLabel.textContent = 'Search skills';" in workspace
    assert "searchInput.addEventListener('input', () => renderOptions(searchInput.value));" in workspace
    assert "Use this when the workflow needs a skill that is not available yet." in workspace


def test_artifact_preview_actions_have_link_fallbacks() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helper = (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "ui.js"
    ).read_text(encoding="utf-8")
    api_js = (
        repo_root / "octopus_registry" / "ui" / "js" / "api.js"
    ).read_text(encoding="utf-8")
    protocol_workspace = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "protocol-workspace.js"
    ).read_text(encoding="utf-8")
    task_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "task-list.js"
    ).read_text(encoding="utf-8")
    task_board = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "task-board.js"
    ).read_text(encoding="utf-8")
    event_renderers = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "event-renderers.js"
    ).read_text(encoding="utf-8")

    assert "function createArtifactActionRow({" in helper
    assert "function createArtifactListRow({" in helper
    assert "function isHumanAssignableSkillName(value)" in helper
    assert "&& !isGeneratedOrRehearsalText(normalized)" in helper
    assert "function compactMarkdownReferences(text)" in helper
    assert "function _ensureArtifactPreviewDelegation()" in helper
    assert "document.addEventListener('click', async (event)" in helper
    assert "previewHref = ''" in helper
    assert "const previewUrl = String(previewHref || openHref || '').trim();" in helper
    assert "previewBtn.setAttribute('role', 'button');" in helper
    assert "previewBtn.dataset.artifactPreviewUrl = previewUrl;" in helper
    assert "className: ['artifact-list-row', className || ''].join(' ').trim()," in helper
    assert "onClick: previewTarget" in helper
    assert "event.preventDefault();" in helper
    assert "const available = !missing && artifact?.exists !== false;" in protocol_workspace
    assert "openHref: showStorageOpen && available ? API.protocolRunArtifactContentUrl" in protocol_workspace
    assert "API.getProtocolRunArtifactRuntime(runId, artifact.artifact_key)" in protocol_workspace
    assert "API.stopProtocolRunArtifactRuntime(runId, artifact.artifact_key)" in protocol_workspace
    assert "stopRuntime.textContent = 'Stop app';" in protocol_workspace
    assert "const inferPrimaryArtifact = () => {" in protocol_workspace
    assert "Promoted from produced artifacts because this run did not declare a primary outcome." in protocol_workspace
    assert "run-primary-readiness-list" in protocol_workspace
    assert "Primary outcome inferred" in protocol_workspace
    assert "Primary outcome declared" in protocol_workspace
    assert "Release evidence available" in protocol_workspace
    assert "Release evidence missing" in protocol_workspace
    assert "Runtime launch is not acceptance" in protocol_workspace
    assert "final readiness still comes from the review evidence and run state" in protocol_workspace
    assert "required evidence check" in protocol_workspace
    assert "unavailableReason: missing ? 'Declared artifact, not produced yet.'" in protocol_workspace
    assert "UI.createArtifactListRow({" in protocol_workspace
    assert "function createTaskArtifactListRow(task, artifact, expectedOutput = null)" in helper
    assert "function createPendingTaskArtifactListRow(task, expectedOutput)" in helper
    assert "UI.compactMarkdownReferences(task.result_summary || task.result_text || task.summary || task.instructions || '')" in task_list
    assert "const displaySummary = UI.compactMarkdownReferences(summary);" in task_board
    assert "UI.esc(UI.compactMarkdownReferences(event.content))" in event_renderers
    assert "getTaskArtifactText" not in api_js
    assert "getProtocolRunArtifactText" not in api_js

    css = (
        repo_root / "octopus_registry" / "ui" / "css" / "main.css"
    ).read_text(encoding="utf-8")
    assert ".run-primary-readiness-list .list-row-label" in css
    assert "white-space: normal;" in css


def test_task_expansion_rerenders_clicked_rows_before_showing_artifacts() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    task_list = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "task-list.js"
    ).read_text(encoding="utf-8")

    assert "expanded: expandedTaskIds.has(String(task.routed_task_id || ''))" in task_list
    assert "function _taskDetailStateSignature(taskId)" in task_list
    assert "detailState: _taskDetailStateSignature(String(task.routed_task_id || ''))" in task_list
    assert "detailState: _taskDetailStateSignature(taskId)" in task_list
    assert "if (!taskDetails.has(taskId) && !(task.request || task.result))" in task_list
    assert "void loadTaskDetail(taskId);" in task_list
    assert "renderList(currentTasks, currentListData);" in task_list
    assert "const artifactEvidence = UI.taskArtifactEvidence(detailPayload);" in task_list
    assert "outputsLabel.textContent = 'Outputs';" in task_list


def test_desktop_ui_rows_are_action_explicit_and_artifact_actions_are_container_safe() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    helper = (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "ui.js"
    ).read_text(encoding="utf-8")
    css = (repo_root / "octopus_registry" / "ui" / "css" / "main.css").read_text(encoding="utf-8")

    assert "isLink || isAction ? 'is-actionable' : 'is-passive'" in helper
    assert "const hasInteractiveTrailing = hasTrailing && trailing instanceof Element" in helper
    assert "const usePressableContainer = isAction && hasInteractiveTrailing;" in helper
    assert "main.classList.add('list-row-pressable');" in helper
    assert "makePressable(main, activate);" in helper
    assert "makePressable(row, activate);" not in helper
    assert "target.closest(interactiveSelector)" in helper
    assert "Busy: ${current} of ${max} work slots used" in (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "kit.js"
    ).read_text(encoding="utf-8")
    assert ".list-row.is-actionable {" in css
    assert ".list-row-with-artifact-actions {" in css
    assert ".list-row-pressable {" in css
    assert "grid-template-columns: minmax(0, 1fr);" in css
    assert ".list-row-with-artifact-actions .artifact-action-row" in css
    assert ".protocol-runs-workbench" in css
    assert "renderExpanded = null" in (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "kit.js"
    ).read_text(encoding="utf-8")
    assert "kit-run-status-attention" in (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "kit.js"
    ).read_text(encoding="utf-8")
    workspace = (
        repo_root / "octopus_registry" / "ui" / "js" / "components" / "protocol-workspace.js"
    ).read_text(encoding="utf-8")
    assert "renderExpanded: () => _buildRunDetailPanel()" in workspace
    assert "workbench.appendChild(_buildRunDetailPanel());" not in workspace
    assert "function _buildRunsOverviewStrip(" in workspace
    assert "const buildRunFocusHero = () => {" in workspace
    assert "const progressRail = Kit.runStageProgressRail({" in workspace
    assert "onStageSelect: selectRunStageEvidence" in workspace
    assert "run-focus-live" in workspace
    assert "const taskForStage = (item) =>" in workspace
    assert "Latest agent update" in workspace
    assert "Loop/attempt history" in workspace
    assert "stageRows.length > stageAttemptsByKey.size" in workspace
    assert "UI.subscribeWithRefresh(cleanups, 'tasks'" in workspace
    assert "function _protocolEventText(event)" in workspace
    assert "quietProgressText" in workspace
    assert "let activeRunStageFollowsCurrent = true" in workspace
    assert "function _resetRunStageEvidenceSelection()" in workspace
    assert "activeRunStageFollowsCurrent && currentStageValue" in workspace
    assert "activeRunStageFollowsCurrent = value === currentStageValue" in workspace
    assert "transitionLabelForStage(transition, item.protocol_stage_execution_id)" in workspace
    assert "Operator controls" in workspace
    assert "normalizedRunId === String(currentRunId || '')" in workspace
    assert "run-expansion-panel" in workspace
    assert "run-feed-panel" in workspace
    assert "run-stage-timeline-button" in workspace
    assert "Run inspector" in workspace
    assert "issuesByRunId" in workspace
    kit = (
        repo_root / "octopus_registry" / "ui" / "js" / "helpers" / "kit.js"
    ).read_text(encoding="utf-8")
    assert "onStageSelect = null" in kit
    assert "const attemptCountByStage = new Map();" in kit
    assert "attempt ${item.attempt || item.attemptCount}" in kit
    assert "kit-run-stage-progress-node is-" in kit
    assert ".runs-overview-strip" in css
    assert ".run-focus-hero" in css
    assert ".run-focus-live" in css
    assert "kit-run-stage-current-glow" in css
    assert ".kit-runs-list-entry.is-selected .kit-runs-list-row-subtitle" in css
    assert ".run-expansion-panel" in css
    assert ".run-stage-timeline-button" in css
    assert ".run-audit-disclosure" in css
    assert ".kit-runs-list-group" in css


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
    assert "card.classList.add('is-open-by-default');" in event_renderers
    assert "expandedIds.has(_eventRenderKey(event))" in event_renderers
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
