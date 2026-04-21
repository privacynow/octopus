const PROTOCOL_ISSUE_FILTER_OPTIONS = [
    { value: '', label: 'Runs' },
    { value: 'all', label: 'All issues' },
    { value: 'blocked_run', label: 'Blocked runs' },
    { value: 'invalid_contract', label: 'Contract errors' },
    { value: 'stuck_lease', label: 'Stuck leases' },
    { value: 'expired_timeout', label: 'Expired timeouts' },
];

function _isCompactViewport() {
    return window.innerWidth <= 960;
}

function _downloadProtocolText(filename, text, contentType) {
    const blob = new Blob([text], { type: contentType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 500);
}

function _protocolArtifactLabel(item) {
    const parts = [];
    if (item.workspace_path || item.location) {
        parts.push(String(item.workspace_path || item.location || ''));
    }
    if (item.content_hash) {
        parts.push(`sha256 ${String(item.content_hash).slice(0, 12)}`);
    }
    if (Number.isFinite(Number(item.size_bytes || 0)) && Number(item.size_bytes || 0) > 0) {
        parts.push(`${Number(item.size_bytes || 0).toLocaleString()} bytes`);
    }
    return parts.join(' · ');
}

function _artifactDefinitionPath(item) {
    return String(item?.path || item?.workspace_path || item?.location || '').trim();
}

function _artifactPurposeLabel(item) {
    const normalizedKind = String(item?.kind || 'workspace_file').trim().toLowerCase();
    const normalizedPath = _artifactDefinitionPath(item).toLowerCase();
    if (normalizedKind === 'control_plane_text') {
        return 'Notes or structured text carried with the run';
    }
    if (/\.(csv|tsv|xls|xlsx|json|jsonl|parquet)$/i.test(normalizedPath)) {
        return 'Dataset or structured data file';
    }
    if (/\.(py|js|mjs|cjs|ts|tsx|jsx|sh|sql|rb|go|java|rs|php)$/i.test(normalizedPath)) {
        return 'Code file or script';
    }
    if (/\.(pdf|md|txt|doc|docx|html)$/i.test(normalizedPath)) {
        return 'Document or report';
    }
    if (/(^|\/)(src|app|lib|scripts|reports|docs|data)\//i.test(normalizedPath)) {
        return 'Workspace file or folder';
    }
    return 'Workspace file or folder';
}

function _artifactUsage(doc, artifactKey) {
    const normalizedArtifactKey = String(artifactKey || '').trim();
    const reads = [];
    const writes = [];
    (doc?.stages || []).forEach((stage) => {
        const stageLabel = String(stage?.display_name || stage?.stage_key || 'Untitled step').trim();
        if ((stage?.inputs || []).includes(normalizedArtifactKey)) reads.push(stageLabel);
        if ((stage?.outputs || []).includes(normalizedArtifactKey)) writes.push(stageLabel);
    });
    return { reads, writes };
}

function _artifactUsageSummary(doc, artifactKey) {
    const usage = _artifactUsage(doc, artifactKey);
    const parts = [];
    if (usage.writes.length) parts.push(`${usage.writes.length} producer${usage.writes.length === 1 ? '' : 's'}`);
    if (usage.reads.length) parts.push(`${usage.reads.length} consumer${usage.reads.length === 1 ? '' : 's'}`);
    return parts.join(' · ');
}

function _artifactOptionLabel(item) {
    const label = String(item?.display_name || item?.artifact_key || 'Untitled artifact').trim();
    const pathLabel = _artifactDefinitionPath(item);
    if (pathLabel) return `${label} · ${pathLabel}`;
    if (String(item?.kind || '').trim().toLowerCase() === 'control_plane_text') {
        return `${label} · text carried with the run`;
    }
    return label;
}

function _protocolTransitionParticipantKey(transition, stageById) {
    const toStage = stageById.get(String(transition.to_stage_execution_id || ''));
    if (toStage && toStage.participant_key) {
        return String(toStage.participant_key || '');
    }
    const fromStage = stageById.get(String(transition.from_stage_execution_id || ''));
    return fromStage ? String(fromStage.participant_key || '') : '';
}

function _filteredProtocolTimelineData(currentRun, timelineParticipantFilter) {
    if (!currentRun) {
        return {
            stageRows: [],
            transitionRows: [],
            participantOptions: [],
        };
    }
    const stageById = new Map((currentRun.stage_executions || []).map((item) => [String(item.protocol_stage_execution_id || ''), item]));
    const participantOptions = Array.from(
        new Map((currentRun.participants || []).map((item) => [
            String(item.participant_key || ''),
            item.display_name || item.participant_key || '',
        ])).entries(),
    ).map(([value, label]) => ({ value, label }));
    const stageRows = (currentRun.stage_executions || []).filter((item) =>
        !timelineParticipantFilter || String(item.participant_key || '') === timelineParticipantFilter,
    );
    const transitionRows = (currentRun.transitions || []).filter((item) =>
        !timelineParticipantFilter || _protocolTransitionParticipantKey(item, stageById) === timelineParticipantFilter,
    );
    return { stageRows, transitionRows, participantOptions };
}

function _protocolIssueFilterValue(value) {
    const normalized = String(value || '').trim();
    if (!normalized) {
        return '';
    }
    if (normalized === 'all') {
        return 'all';
    }
    return PROTOCOL_ISSUE_FILTER_OPTIONS.some((item) => item.value === normalized) ? normalized : '';
}

function _protocolIssueApiValue(value) {
    return value === 'all' ? '' : String(value || '');
}

function _slugSuggestion(value) {
    return String(value || '')
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
}

const PROTOCOL_TERMINAL_TARGETS = [
    { key: '__complete__', label: 'Finish successfully' },
    { key: '__failed__', label: 'Finish as failed' },
    { key: '__cancelled__', label: 'Finish as cancelled' },
];

const PRIMARY_SELECTOR_KINDS = ['agent', 'skill'];

function _selectorString(selector) {
    if (!selector || !selector.kind || !selector.value) return '';
    const kind = String(selector.kind || '').trim();
    const value = String(selector.value || '').trim();
    if (!kind || !value) return '';
    return kind === 'agent' ? `@${value}` : `@${kind}:${value}`;
}

function _selectorFromFields(kind, value, preferredAgentId = '') {
    const selectorKind = String(kind || '').trim();
    const selectorValue = String(value || '').trim();
    if (!selectorKind || !selectorValue) return null;
    const selector = { kind: selectorKind, value: selectorValue };
    if (selectorKind === 'skill') {
        const preferred = String(preferredAgentId || '').trim();
        if (preferred) selector.preferred_agent_id = preferred;
    }
    return selector;
}

function _selectorModeFromKind(kind, fallback = 'skill') {
    const normalized = String(kind || '').trim().toLowerCase();
    if (normalized === 'agent' || normalized === 'skill') return normalized;
    if (normalized) return 'advanced';
    return String(fallback || 'skill');
}

function _protocolDecisionLabel(value) {
    const key = String(value || '').trim().toLowerCase();
    if (!key) return '';
    return Kit.dict.label(`protocol.stage.decision.${key}`, value);
}

function _transitionTargetLabel(targetKey, doc) {
    const key = String(targetKey || '').trim();
    if (!key) return '';
    const stage = (doc?.stages || []).find((item) => String(item.stage_key || '') === key);
    if (stage) {
        return String(stage.display_name || stage.stage_key || key);
    }
    const terminal = PROTOCOL_TERMINAL_TARGETS.find((item) => String(item.key || '') === key);
    return String(terminal?.label || key);
}

function _titleCaseWords(value) {
    return String(value || '')
        .trim()
        .split(/[\s_-]+/)
        .filter(Boolean)
        .map((item) => item.charAt(0).toUpperCase() + item.slice(1))
        .join(' ');
}

/*
 * Protocol authoring workspace — one progressive workflow stage stack and one
 * optional map. The old overview/detail/topology split is gone.
 *
 * The primary surface is the stage stack; the selected stage expands inline.
 * The map is a secondary reference surface that can be shown on demand.
 * Roles own steps; assignment rules resolve steps to runtime agents. No raw
 * JSON tab, no viewport-specific editor fork, and no second authoring pipeline.
 */
function renderProtocolWorkspace(container) {
    const cleanups = UI.beginCleanupScope();
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }

    let protocols = [];
    let authoringManifest = null;
    let currentProtocolId = UI.readQueryParam('protocol_id', '');
    let currentProtocol = null;
    let protocolDetailLoading = false;
    let draftRevision = 0;
    let connectedAgents = [];
    let availableAgents = [];
    let availableRoutingSkills = [];
    let draftConflict = null;
    let renderInFlight = false;
    let renderQueued = false;
    let editorMode = { kind: 'idle', sourceStageKey: '', decision: '' };
    let editorSessionNonce = 0;
    let pendingStage = {
        display_name: '',
        stage_key: '',
        participant_key: '__new__',
        selector_mode: 'skill',
        selector_kind: '',
        selector_value: '',
        selector_preferred_agent_id: '',
        role_display_name: '',
        role_participant_key: '',
        role_instructions: '',
        stage_kind: 'work',
        instructions: '',
        inputs: [],
        outputs: [],
        max_rounds: 0,
        timeout_seconds: 0,
    };
    let pendingRoute = {
        source_stage_key: '',
        decision: '',
        target_key: '',
    };
    let documentHistory = { undo: [], redo: [] };
    let canvasViewport = { zoom: 'fit' };
    let workflowMapMode = 'auto';
    let stageAssignmentEditor = { stageKey: '', mode: '' };

    function _operatorSurfaceAvailable() {
        return Boolean(authoringManifest?.operator_surface_available);
    }

    function _currentAuthoringSurface() {
        const requested = String(UI.readQueryParam('authoring_surface', '') || '').trim().toLowerCase();
        if (requested === 'operator' && _operatorSurfaceAvailable()) return 'operator';
        return String(authoringManifest?.default_surface || 'standard').trim().toLowerCase() === 'operator'
            && _operatorSurfaceAvailable()
            ? 'operator'
            : 'standard';
    }

    function _openArtifactCatalog(nodeKey = '') {
        selection = { sectionKey: 'artifacts', nodeKey: String(nodeKey || '') };
        render();
    }

    // Single coherent draft snapshot. No mirrored raw-text; no parse_error.
    let draft = {
        slug: '',
        display_name: '',
        description: '',
        document: _blankDocument(),
    };

    // The canvas/details interaction works off one selection.
    let selection = { sectionKey: 'overview', nodeKey: '' };

    let saveState = { state: 'idle', lastSavedAt: '', error: '' };
    let autosaveTimer = 0;

    // Rehearsal state. Present only while a rehearsal run is active.
    let rehearsal = {
        runId: '',
        sessions: [],
        scenarios: [],
        runDetail: null,
        pollTimer: 0,
    };

    function _canvasZoomValue() {
        return canvasViewport.zoom === 'fit'
            ? 'fit'
            : Math.max(0.35, Math.min(2.25, Number(canvasViewport.zoom || 1) || 1));
    }

    function _defaultWorkflowMapVisible(current = selection) {
        return false;
    }

    function _workflowMapModeFromQuery() {
        const value = String(UI.readQueryParam('workflow_map', '') || '').trim().toLowerCase();
        if (value === 'visible' || value === 'hidden' || value === 'auto') return value;
        return 'auto';
    }

    function _workflowMapVisible(current = selection) {
        if (workflowMapMode === 'visible') return true;
        if (workflowMapMode === 'hidden') return false;
        return _defaultWorkflowMapVisible(current);
    }

    function _setWorkflowMapMode(mode, { rerender = true } = {}) {
        workflowMapMode = ['auto', 'visible', 'hidden'].includes(String(mode || ''))
            ? String(mode || '')
            : 'auto';
        _writeState();
        if (rerender) render();
    }

    function _setCanvasViewport(zoom, { renderNow = false } = {}) {
        canvasViewport = {
            zoom: zoom === 'fit'
                ? 'fit'
                : Math.max(0.35, Math.min(2.25, Number(zoom || 1) || 1)),
        };
        if (renderNow) render();
    }

    // Layout shell
    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Protocols</h2><p>Author reusable, versioned workflow definitions. Runs live under their own tab.</p>';
    container.appendChild(header);

    const shell = document.createElement('section');
    shell.className = 'admin-shell protocol-route-shell';
    container.appendChild(shell);

    const contentEl = document.createElement('div');
    contentEl.className = 'protocol-surface-shell protocol-authoring-shell';
    shell.appendChild(contentEl);

    function _blankDocument() {
        return {
            schema_version: 1,
            metadata: {},
            participants: [],
            artifacts: [],
            stages: [],
            // policies intentionally omitted — server defaults apply until the
            // user edits them explicitly via the details panel.
        };
    }

    function _blankStageDraft(participantKey = '', seed = {}) {
        return {
            display_name: '',
            stage_key: '',
            participant_key: String(participantKey || '__new__'),
            selector_mode: 'skill',
            selector_kind: '',
            selector_value: '',
            selector_preferred_agent_id: '',
            role_display_name: '',
            role_participant_key: '',
            role_instructions: '',
            stage_kind: 'work',
            instructions: '',
            inputs: [],
            outputs: [],
            max_rounds: 0,
            timeout_seconds: 0,
            ...seed,
        };
    }

    function _blankRouteDraft(stageKey = '', stageKind = 'work', seed = {}) {
        return {
            source_stage_key: String(stageKey || ''),
            decision: _defaultDecisionForStageKind(stageKind),
            target_key: '',
            ...seed,
        };
    }

    function _baseEditorModeKind() {
        return rehearsal.runId ? 'rehearse' : 'idle';
    }

    function _setEditorMode(next) {
        editorMode = {
            kind: _baseEditorModeKind(),
            sourceStageKey: '',
            decision: '',
            ...(next || {}),
        };
        render();
    }

    function _resetEditorMode() {
        editorMode = { kind: _baseEditorModeKind(), sourceStageKey: '', decision: '' };
        pendingStage = _blankStageDraft(_defaultStageParticipantKey());
        pendingRoute = _blankRouteDraft();
    }

    function _defaultDecisionForStageKind(stageKind) {
        return String(stageKind || '') === 'work' ? 'completed' : 'accept';
    }

    function _decisionOptionsForStage(stage, currentDecision = '') {
        const stageKind = String(stage?.stage_kind || 'work');
        const defaults = stageKind === 'work'
            ? ['completed']
            : stageKind === 'acceptance'
                ? ['accept', 'fail']
                : ['accept', 'revise', 'fail'];
        const current = String(currentDecision || '').trim().toLowerCase();
        const values = Array.from(new Set([
            ...defaults,
            ...Object.keys(stage?.transitions || {}).map((item) => String(item || '').trim().toLowerCase()).filter(Boolean),
            current,
        ].filter(Boolean)));
        return values.map((value) => ({
            value,
            label: _protocolDecisionLabel(value),
        }));
    }

    function _selectionStage(doc = draft.document) {
        if (selection.sectionKey !== 'stages' || !selection.nodeKey) return null;
        return (doc.stages || []).find((item) => String(item.stage_key || '') === String(selection.nodeKey || '')) || null;
    }

    function _selectionTransition(doc = draft.document) {
        if (selection.sectionKey !== 'transitions' || !selection.nodeKey) return null;
        return _transitionEntries(doc).find((item) => String(item.id || '') === String(selection.nodeKey || '')) || null;
    }

    function _segmentPrimaryStageKey(segment) {
        return String(segment?.primaryStageKey || segment?.stageKeys?.[0] || '');
    }

    function _segmentHasHiddenPrimaryStage(segment) {
        return Boolean(segment?.stages?.length > 1 && _segmentPrimaryStageKey(segment));
    }

    function _segmentStageList(segment) {
        const primaryStageKey = _segmentPrimaryStageKey(segment);
        const stages = Array.isArray(segment?.stages) ? segment.stages : [];
        if (!_segmentHasHiddenPrimaryStage(segment)) {
            return stages;
        }
        return stages.filter((stage) => String(stage?.stage_key || '') !== primaryStageKey);
    }

    function _normalizeSelectionForProjection(current, projection) {
        const key = String(current?.sectionKey || 'overview');
        if (key !== 'segments') return current;
        const segment = projection?.segmentsById?.get(String(current?.nodeKey || ''));
        if (!segment) return current;
        const primaryStageKey = _segmentPrimaryStageKey(segment);
        if (primaryStageKey) {
            return { sectionKey: 'stages', nodeKey: primaryStageKey };
        }
        return current;
    }

    function _defaultStageInsertAnchor(stage, projection) {
        const sourceStageKey = String(stage?.stage_key || '');
        const transitions = Object.entries(stage?.transitions || {})
            .map(([decision, target]) => ({
                decision: String(decision || '').trim().toLowerCase(),
                target: String(target || '').trim(),
            }))
            .filter((item) => item.decision && item.target);
        const stageOrder = new Map((draft.document.stages || []).map((item, index) => [String(item.stage_key || ''), index]));
        const sourceIndex = Number(stageOrder.get(sourceStageKey) || 0);
        const sourceSegmentId = String(projection?.stageToSegment?.get(sourceStageKey) || '');
        const sourceColumn = Number(projection?.segmentsById?.get(sourceSegmentId)?.column || 0);
        const forward = transitions.filter((item) => {
            if (PROTOCOL_TERMINAL_TARGETS.some((terminal) => terminal.key === item.target)) return false;
            const targetSegmentId = String(projection?.stageToSegment?.get(item.target) || '');
            const targetColumn = Number(projection?.segmentsById?.get(targetSegmentId)?.column || sourceColumn);
            if (targetColumn > sourceColumn) return true;
            if (targetColumn < sourceColumn) return false;
            return Number(stageOrder.get(item.target) || -1) > sourceIndex;
        });
        const nonTerminal = transitions.filter((item) => !PROTOCOL_TERMINAL_TARGETS.some((terminal) => terminal.key === item.target));
        const anchor = forward.length === 1
            ? forward[0]
            : nonTerminal.length === 1
                ? nonTerminal[0]
                : transitions.length === 1
                    ? transitions[0]
                    : null;
        if (!anchor) return null;
        return {
            sourceStageKey: String(stage?.stage_key || ''),
            decision: String(anchor.decision || ''),
        };
    }

    function _insertAnchorForStage(stage, projection) {
        const anchor = _defaultStageInsertAnchor(stage, projection);
        if (anchor) return anchor;
        return {
            sourceStageKey: String(stage?.stage_key || ''),
            decision: _defaultDecisionForStageKind(stage?.stage_kind || 'work'),
        };
    }

    function _defaultStageParticipantKey(doc = draft.document) {
        if (selection.sectionKey === 'participants' && selection.nodeKey) {
            return String(selection.nodeKey || '');
        }
        const selectedStage = _selectionStage(doc);
        if (selectedStage?.participant_key) {
            return String(selectedStage.participant_key || '');
        }
        return String(doc.participants?.[0]?.participant_key || '__new__');
    }

    function _stageLaneRow(participantKey, doc = draft.document) {
        const laneIndex = (doc.participants || []).findIndex((item) => String(item.participant_key || '') === String(participantKey || ''));
        return laneIndex >= 0 ? laneIndex : 0;
    }

    function _cloneDoc(doc) {
        return JSON.parse(JSON.stringify(doc || _blankDocument()));
    }

    function _docFromDraft() {
        const doc = _cloneDoc(draft.document);
        doc.schema_version = Number(doc.schema_version || 1) || 1;
        doc.metadata = Object.assign({}, doc.metadata || {}, {
            slug: String(draft.slug || '').trim(),
            display_name: String(draft.display_name || '').trim(),
            description: String(draft.description || '').trim(),
        });
        doc.participants = Array.isArray(doc.participants) ? doc.participants : [];
        doc.artifacts = Array.isArray(doc.artifacts) ? doc.artifacts : [];
        doc.stages = Array.isArray(doc.stages) ? doc.stages : [];
        return doc;
    }

    function _workflowProgress(doc = draft.document) {
        const normalized = doc || _blankDocument();
        const participantCount = Array.isArray(normalized.participants) ? normalized.participants.length : 0;
        const artifactCount = Array.isArray(normalized.artifacts) ? normalized.artifacts.length : 0;
        const stageCount = Array.isArray(normalized.stages) ? normalized.stages.length : 0;
        const edgeCount = _transitionEntries(normalized).length;
        let nextStep = '';
        if (!stageCount) nextStep = 'stage';
        else if (!edgeCount) nextStep = 'transition';
        else if (!artifactCount) nextStep = 'artifact';
        return { participantCount, artifactCount, stageCount, edgeCount, nextStep };
    }

    function _participantDisplayName(participantKey, doc = draft.document) {
        const participant = (doc.participants || []).find((item) => String(item.participant_key || '') === String(participantKey || ''));
        return String(participant?.display_name || participant?.participant_key || participantKey || 'Role').trim();
    }

    function _participantRecord(participantKey, doc = draft.document) {
        return (doc.participants || []).find((item) => String(item.participant_key || '') === String(participantKey || '')) || null;
    }

    function _selectorSummary(selector, { empty = 'Unassigned', prefix = '' } = {}) {
        if (!selector || !selector.kind || !selector.value) {
            return prefix ? `${prefix}${empty}` : empty;
        }
        const kind = String(selector.kind || '').trim().toLowerCase();
        const value = String(selector.value || '').trim();
        const valueLabel = kind === 'skill' || kind === 'role' ? _titleCaseWords(value) : value;
        const preferredAgent = kind === 'skill'
            ? _selectorAgentRecord(selector.preferred_agent_id || '')
            : null;
        const preferredLabel = preferredAgent
            ? String(preferredAgent.display_name || preferredAgent.slug || selector.preferred_agent_id || '').trim()
            : '';
        const label = preferredLabel
            ? `${_selectorKindLabel(kind)} · ${valueLabel} · prefer ${preferredLabel}`
            : `${_selectorKindLabel(kind)} · ${valueLabel}`;
        return prefix ? `${prefix}${label}` : label;
    }

    function _stageAssignmentSummary(stage, options = {}) {
        return _selectorSummary(stage?.selector || null, options);
    }

    function _hasSelectorAssignment(selectorKind = '', selectorValue = '') {
        return Boolean(_selectorFromFields(selectorKind, selectorValue));
    }

    function _segmentParticipantSummary(participantLabels) {
        const labels = Array.isArray(participantLabels)
            ? participantLabels.map((item) => String(item || '').trim()).filter(Boolean)
            : [];
        if (!labels.length) return 'Unassigned role';
        if (labels.length === 1) return labels[0];
        if (labels.length === 2) return `${labels[0]} + ${labels[1]}`;
        return `${labels[0]} + ${labels.length - 1} more roles`;
    }

    function _segmentId(stageKey) {
        return `segment:${String(stageKey || '').trim()}`;
    }

    function _sortedGraphKeys(keys, documentIndex) {
        return [...keys].sort((left, right) =>
            Number(documentIndex.get(String(left || '')) || 0) - Number(documentIndex.get(String(right || '')) || 0));
    }

    function _stageTopology(doc = draft.document) {
        const stages = Array.isArray(doc?.stages) ? doc.stages : [];
        const stageByKey = new Map(stages.map((item) => [String(item.stage_key || ''), item]));
        const documentIndex = new Map(stages.map((item, index) => [String(item.stage_key || ''), index]));
        const outgoingStage = new Map();
        const incomingStage = new Map();
        const outgoingTerminal = new Map();
        stages.forEach((item) => {
            const key = String(item.stage_key || '');
            outgoingStage.set(key, []);
            incomingStage.set(key, []);
            outgoingTerminal.set(key, []);
        });
        stages.forEach((stage) => {
            const sourceKey = String(stage.stage_key || '');
            Object.entries(stage.transitions || {}).forEach(([decision, target]) => {
                const decisionKey = String(decision || '').trim().toLowerCase();
                const targetKey = String(target || '').trim();
                if (!decisionKey || !targetKey) return;
                const edge = {
                    id: _stageTransitionId(sourceKey, decisionKey),
                    from: sourceKey,
                    to: targetKey,
                    decision: decisionKey,
                };
                if (stageByKey.has(targetKey)) {
                    outgoingStage.get(sourceKey)?.push(edge);
                    incomingStage.get(targetKey)?.push(edge);
                } else if (PROTOCOL_TERMINAL_TARGETS.some((item) => item.key === targetKey)) {
                    outgoingTerminal.get(sourceKey)?.push(edge);
                }
            });
        });
        const orderedStageKeys = _sortedGraphKeys(stageByKey.keys(), documentIndex);
        const visitState = new Map();
        const backEdgeIds = new Set();
        function walk(stageKey) {
            visitState.set(stageKey, 'visiting');
            const outgoing = _sortedGraphKeys(
                (outgoingStage.get(stageKey) || []).map((edge) => String(edge.to || '')),
                documentIndex,
            ).map((targetKey) => (outgoingStage.get(stageKey) || []).find((edge) => String(edge.to || '') === targetKey)).filter(Boolean);
            outgoing.forEach((edge) => {
                const targetKey = String(edge.to || '');
                const state = visitState.get(targetKey);
                if (state === 'visiting') {
                    backEdgeIds.add(String(edge.id || ''));
                    return;
                }
                if (state === 'done') return;
                if (!stageByKey.has(targetKey)) return;
                walk(targetKey);
            });
            visitState.set(stageKey, 'done');
        }
        orderedStageKeys.forEach((stageKey) => {
            if (!visitState.has(stageKey)) walk(stageKey);
        });

        const forwardOutgoingStage = new Map(stages.map((item) => [String(item.stage_key || ''), []]));
        const forwardIncomingStage = new Map(stages.map((item) => [String(item.stage_key || ''), []]));
        stages.forEach((stage) => {
            const sourceKey = String(stage.stage_key || '');
            (outgoingStage.get(sourceKey) || []).forEach((edge) => {
                if (backEdgeIds.has(String(edge.id || ''))) return;
                forwardOutgoingStage.get(sourceKey)?.push(edge);
                forwardIncomingStage.get(String(edge.to || ''))?.push(edge);
            });
        });

        const rank = new Map(orderedStageKeys.map((stageKey) => [stageKey, 0]));
        const indegree = new Map(orderedStageKeys.map((stageKey) => [stageKey, Number((forwardIncomingStage.get(stageKey) || []).length)]));
        const queue = orderedStageKeys.filter((stageKey) => Number(indegree.get(stageKey) || 0) === 0);
        while (queue.length) {
            const stageKey = queue.shift();
            const sourceRank = Number(rank.get(stageKey) || 0);
            const outgoing = _sortedGraphKeys(
                (forwardOutgoingStage.get(stageKey) || []).map((edge) => String(edge.to || '')),
                documentIndex,
            ).map((targetKey) => (forwardOutgoingStage.get(stageKey) || []).find((edge) => String(edge.to || '') === targetKey)).filter(Boolean);
            outgoing.forEach((edge) => {
                const targetKey = String(edge.to || '');
                rank.set(targetKey, Math.max(Number(rank.get(targetKey) || 0), sourceRank + 1));
                indegree.set(targetKey, Math.max(0, Number(indegree.get(targetKey) || 0) - 1));
                if (Number(indegree.get(targetKey) || 0) === 0 && !queue.includes(targetKey)) {
                    queue.push(targetKey);
                    queue.sort((left, right) =>
                        Number(documentIndex.get(String(left || '')) || 0) - Number(documentIndex.get(String(right || '')) || 0));
                }
            });
        }
        return {
            stages,
            stageByKey,
            documentIndex,
            outgoingStage,
            incomingStage,
            outgoingTerminal,
            forwardOutgoingStage,
            forwardIncomingStage,
            backEdgeIds,
            rank,
        };
    }

    function _singleForwardStageTarget(stage, topology) {
        const sourceKey = String(stage?.stage_key || '');
        if (!sourceKey) return '';
        const targets = (topology.forwardOutgoingStage.get(sourceKey) || [])
            .map((edge) => String(edge.to || '').trim())
            .filter((targetKey, index, items) =>
                targetKey
                && items.indexOf(targetKey) === index);
        return targets.length === 1 ? targets[0] : '';
    }

    function _canAbsorbLinearSuccessor(currentStage, nextStage, topology) {
        if (!currentStage || !nextStage) return false;
        if (String(currentStage.stage_kind || 'work') !== 'work') return false;
        if ((topology.outgoingTerminal.get(String(currentStage.stage_key || '')) || []).length) return false;
        if (_singleForwardStageTarget(currentStage, topology) !== String(nextStage.stage_key || '')) return false;
        const incoming = topology.forwardIncomingStage.get(String(nextStage.stage_key || '')) || [];
        if (incoming.length !== 1 || String(incoming[0]?.from || '') !== String(currentStage.stage_key || '')) return false;
        return (
            String(currentStage.participant_key || '') === String(nextStage.participant_key || '')
            && String(nextStage.stage_kind || 'work') === 'work'
        );
    }

    function _canAbsorbReviewGate(currentStage, nextStage, chainStageKeys, topology) {
        if (!currentStage || !nextStage) return false;
        if (String(currentStage.stage_kind || 'work') !== 'work') return false;
        if (String(nextStage.stage_kind || 'work') === 'work') return false;
        if ((topology.outgoingTerminal.get(String(currentStage.stage_key || '')) || []).length) return false;
        if (_singleForwardStageTarget(currentStage, topology) !== String(nextStage.stage_key || '')) return false;
        const incoming = topology.forwardIncomingStage.get(String(nextStage.stage_key || '')) || [];
        if (incoming.length !== 1 || String(incoming[0]?.from || '') !== String(currentStage.stage_key || '')) return false;
        const chainKeys = new Set(chainStageKeys.map((item) => String(item || '').trim()).filter(Boolean));
        const stageEdges = topology.forwardOutgoingStage.get(String(nextStage.stage_key || '')) || [];
        const externalTargets = Array.from(new Set(stageEdges
            .map((edge) => String(edge.to || '').trim())
            .filter((targetKey) => targetKey && !chainKeys.has(targetKey))));
        if (externalTargets.length > 1) return false;
        return stageEdges.every((edge) => {
            const targetKey = String(edge.to || '').trim();
            if (!targetKey) return false;
            if (chainKeys.has(targetKey)) return true;
            return Number(topology.rank.get(targetKey) || 0) >= Number(topology.rank.get(String(nextStage.stage_key || '')) || 0);
        });
    }

    function _segmentRows(segmentsById, segmentOrder) {
        const usedByColumn = new Map();
        segmentOrder.forEach((segmentId) => {
            const segment = segmentsById.get(segmentId);
            if (!segment) return;
            const column = Number(segment.column || 0);
            const used = usedByColumn.get(column) || new Set();
            let preferred = -1;
            if (segment.incomingSegments.length === 1) {
                preferred = Number(segmentsById.get(segment.incomingSegments[0])?.row ?? -1);
            }
            let row = preferred >= 0 && !used.has(preferred) ? preferred : 0;
            while (used.has(row)) row += 1;
            segment.row = row;
            used.add(row);
            usedByColumn.set(column, used);
        });
    }

    function _buildWorkflowProjection(doc = draft.document) {
        const topology = _stageTopology(doc);
        const assigned = new Set();
        const segments = [];
        const stageToSegment = new Map();

        topology.stages.forEach((stage) => {
            const stageKey = String(stage.stage_key || '');
            if (!stageKey || assigned.has(stageKey)) return;
            const stageKeys = [stageKey];
            assigned.add(stageKey);
            let currentStage = stage;

            while (true) {
                const nextKey = _singleForwardStageTarget(currentStage, topology);
                const nextStage = nextKey ? topology.stageByKey.get(nextKey) : null;
                if (!nextStage || assigned.has(nextKey)) break;
                if (_canAbsorbLinearSuccessor(currentStage, nextStage, topology)) {
                    stageKeys.push(nextKey);
                    assigned.add(nextKey);
                    currentStage = nextStage;
                    continue;
                }
                if (_canAbsorbReviewGate(currentStage, nextStage, stageKeys, topology)) {
                    stageKeys.push(nextKey);
                    assigned.add(nextKey);
                }
                break;
            }

            const segmentStages = stageKeys
                .map((key) => topology.stageByKey.get(key))
                .filter(Boolean);
            const participantKeys = Array.from(new Set(segmentStages.map((item) => String(item.participant_key || '')).filter(Boolean)));
            const participantLabels = participantKeys.map((key) => _participantDisplayName(key, doc));
            const primaryStage = segmentStages.find((item) => String(item.stage_kind || 'work') === 'work') || segmentStages[0] || stage;
            const stepSummary = `${stageKeys.length} step${stageKeys.length === 1 ? '' : 's'}`;
            const participantSummary = _segmentParticipantSummary(participantLabels);
            const segment = {
                id: _segmentId(stageKeys[0]),
                startStageKey: stageKeys[0],
                endStageKey: stageKeys[stageKeys.length - 1],
                stageKeys,
                stages: segmentStages,
                primaryStageKey: String(primaryStage?.stage_key || segmentStages[0]?.stage_key || stageKeys[0] || ''),
                participantKeys,
                primaryParticipantKey: String(primaryStage?.participant_key || segmentStages[0]?.participant_key || ''),
                label: String(primaryStage?.display_name || primaryStage?.stage_key || stageKeys[0] || 'Step'),
                sublabel: participantSummary,
                stepSummary,
                participantSummary,
                badges: [
                    {
                        tone: 'phase',
                        label: stepSummary,
                    },
                ],
                outgoingEdges: [],
                incomingSegments: [],
                column: 0,
                row: 0,
            };
            segments.push(segment);
            stageKeys.forEach((key) => stageToSegment.set(key, segment.id));
        });

        const segmentsById = new Map(segments.map((segment) => [segment.id, segment]));
        segments.forEach((segment) => {
            const grouped = new Map();
            segment.stageKeys.forEach((stageKey) => {
                (topology.outgoingStage.get(stageKey) || []).forEach((edge) => {
                    const targetSegmentId = stageToSegment.get(String(edge.to || ''));
                    if (!targetSegmentId || targetSegmentId === segment.id) return;
                    const groupKey = `segment:${targetSegmentId}`;
                    const current = grouped.get(groupKey) || {
                        id: `${segment.id}::${targetSegmentId}`,
                        from: segment.id,
                        to: targetSegmentId,
                        labels: [],
                        targetKind: 'segment',
                        targetKey: targetSegmentId,
                    };
                    current.labels.push(_protocolDecisionLabel(edge.decision));
                    grouped.set(groupKey, current);
                });
                (topology.outgoingTerminal.get(stageKey) || []).forEach((edge) => {
                    const groupKey = `terminal:${edge.to}`;
                    const current = grouped.get(groupKey) || {
                        id: `${segment.id}::${String(edge.to || '')}`,
                        from: segment.id,
                        to: String(edge.to || ''),
                        labels: [],
                        targetKind: 'terminal',
                        targetKey: String(edge.to || ''),
                    };
                    current.labels.push(_protocolDecisionLabel(edge.decision));
                    grouped.set(groupKey, current);
                });
            });
            segment.outgoingEdges = Array.from(grouped.values()).map((edge) => ({
                ...edge,
                label: Array.from(new Set(edge.labels)).join(' / '),
            }));
        });

        segments.forEach((segment) => {
            segment.outgoingEdges
                .filter((edge) => edge.targetKind === 'segment')
                .forEach((edge) => {
                    const target = segmentsById.get(edge.targetKey);
                    if (!target) return;
                    target.incomingSegments.push(segment.id);
                });
        });

        segments.forEach((segment) => {
            segment.column = Number(topology.rank.get(segment.startStageKey) || 0);
        });
        const minColumn = Math.min(...segments.map((segment) => Number(segment.column || 0)), 0);
        segments.forEach((segment) => {
            segment.column = Math.max(0, Number(segment.column || 0) - minColumn);
        });
        const segmentOrder = segments
            .slice()
            .sort((a, b) =>
                Number(topology.rank.get(a.startStageKey) || 0) - Number(topology.rank.get(b.startStageKey) || 0)
                || Number(topology.documentIndex.get(a.startStageKey) || 0) - Number(topology.documentIndex.get(b.startStageKey) || 0))
            .map((segment) => segment.id);
        segmentOrder.forEach((segmentId) => {
            const segment = segmentsById.get(segmentId);
            if (!segment) return;
            segment.outgoingEdges
                .filter((edge) => edge.targetKind === 'segment')
                .forEach((edge) => {
                    const target = segmentsById.get(edge.targetKey);
                    if (!target) return;
                    const sourceIndex = Number(topology.rank.get(segment.endStageKey) || 0);
                    const targetIndex = Number(topology.rank.get(target.startStageKey) || 0);
                    if (targetIndex < sourceIndex) return;
                    target.column = Math.max(Number(target.column || 0), Number(segment.column || 0) + 1);
                });
        });
        _segmentRows(segmentsById, segmentOrder);

        return {
            topology,
            segments,
            segmentsById,
            stageToSegment,
            segmentOrder,
        };
    }

    function _applyServerDetail(detail, { preserveTransient = false } = {}) {
        const previousProtocolId = String(currentProtocol?.protocol?.protocol_id || '');
        const nextProtocolId = String(detail?.protocol?.protocol_id || '');
        const preserveLocalState = preserveTransient && previousProtocolId && previousProtocolId === nextProtocolId;
        const previousSelection = selection;
        const previousEditorMode = editorMode;
        const previousCanvasViewport = canvasViewport;
        const previousWorkflowMapMode = workflowMapMode;
        const previousPendingStage = pendingStage;
        const previousPendingRoute = pendingRoute;
        currentProtocol = detail;
        draftRevision = Number(detail?.protocol?.draft_revision || 0) || 0;
        draftConflict = null;
        documentHistory = { undo: [], redo: [] };
        if (!preserveLocalState) {
            canvasViewport = { zoom: 'fit' };
        }
        if (previousProtocolId && previousProtocolId !== String(detail?.protocol?.protocol_id || '')) {
            _stopRehearsalPolling();
            rehearsal.runId = '';
            rehearsal.sessions = [];
            rehearsal.scenarios = [];
            rehearsal.runDetail = null;
        }
        const docFromServer = (detail && detail.draft_definition_json && Object.keys(detail.draft_definition_json).length)
            ? detail.draft_definition_json
            : (detail && detail.draft_document) || _blankDocument();
        const metadata = docFromServer.metadata || {};
        draft = {
            slug: metadata.slug !== undefined ? String(metadata.slug || '') : String(detail?.protocol?.slug || ''),
            display_name: metadata.display_name !== undefined
                ? String(metadata.display_name || '')
                : String(detail?.protocol?.display_name || ''),
            description: metadata.description !== undefined
                ? String(metadata.description || '')
                : String(detail?.protocol?.description || ''),
            document: _cloneDoc(docFromServer),
        };
        saveState = { state: 'idle', lastSavedAt: detail?.protocol?.updated_at || '', error: '' };
        if (preserveLocalState) {
            selection = _repairSelection(previousSelection, draft.document);
            editorMode = previousEditorMode;
            canvasViewport = previousCanvasViewport;
            workflowMapMode = previousWorkflowMapMode;
            pendingStage = previousPendingStage;
            pendingRoute = previousPendingRoute;
        } else {
            selection = _repairSelection(_selectionFromQuery(draft.document), draft.document);
            workflowMapMode = _workflowMapModeFromQuery();
            _resetEditorMode();
        }
    }

    function _repairSelection(current, doc) {
        const key = current.sectionKey || 'overview';
        if (key === 'overview') return { sectionKey: 'overview', nodeKey: '' };
        if (key === 'protocol') return { sectionKey: 'protocol', nodeKey: '' };
        if (key === 'segments') {
            const projection = _buildWorkflowProjection(doc);
            const next = projection.segmentsById.has(String(current.nodeKey || ''))
                ? { sectionKey: 'segments', nodeKey: String(current.nodeKey || '') }
                : { sectionKey: 'overview', nodeKey: '' };
            return _normalizeSelectionForProjection(next, projection);
        }
        if (key === 'transitions') {
            const hit = _transitionEntries(doc).some((item) => String(item.id || '') === String(current.nodeKey || ''));
            return hit ? current : { sectionKey: 'overview', nodeKey: '' };
        }
        const items = key === 'participants'
            ? (doc.participants || [])
            : key === 'stages'
                ? (doc.stages || [])
                : key === 'artifacts'
                    ? (doc.artifacts || [])
                    : [];
        const hit = items.find((item) => String(
            key === 'participants' ? item.participant_key
                : key === 'stages' ? item.stage_key
                    : item.artifact_key,
        ) === String(current.nodeKey || ''));
        if (hit) return current;
        return { sectionKey: 'overview', nodeKey: '' };
    }

    function _selectionFromQuery(doc = draft.document) {
        const segmentId = UI.readQueryParam('segment_id', '');
        if (segmentId) return { sectionKey: 'segments', nodeKey: segmentId };
        const stageKey = UI.readQueryParam('stage_key', '');
        if (stageKey) return { sectionKey: 'stages', nodeKey: stageKey };
        const participantKey = UI.readQueryParam('participant_key', '');
        if (participantKey) return { sectionKey: 'participants', nodeKey: participantKey };
        const transitionId = UI.readQueryParam('transition_id', '');
        if (transitionId) return { sectionKey: 'transitions', nodeKey: transitionId };
        const artifactKey = UI.readQueryParam('artifact_key', '');
        if (artifactKey) return { sectionKey: 'artifacts', nodeKey: artifactKey };
        const panel = String(UI.readQueryParam('panel', '') || '').trim().toLowerCase();
        if (panel === 'protocol') return { sectionKey: 'protocol', nodeKey: '' };
        return { sectionKey: 'overview', nodeKey: '' };
    }

    function _selectionQueryState(current = selection) {
        const next = {
            segment_id: '',
            stage_key: '',
            participant_key: '',
            transition_id: '',
            artifact_key: '',
            panel: '',
            workflow_map: workflowMapMode,
        };
        const key = String(current?.sectionKey || 'overview');
        const nodeKey = String(current?.nodeKey || '');
        if (key === 'protocol') {
            next.panel = 'protocol';
        } else if (key === 'segments' && nodeKey) {
            next.segment_id = nodeKey;
            next.panel = 'segment';
        } else if (key === 'stages' && nodeKey) {
            next.stage_key = nodeKey;
            next.panel = 'stage';
        } else if (key === 'participants' && nodeKey) {
            next.participant_key = nodeKey;
            next.panel = 'participant';
        } else if (key === 'transitions' && nodeKey) {
            next.transition_id = nodeKey;
            next.panel = 'transition';
        } else if (key === 'artifacts' && nodeKey) {
            next.artifact_key = nodeKey;
            next.panel = 'artifact';
        }
        if (editorMode.kind === 'insert-stage') next.panel = 'new-stage';
        if (editorMode.kind === 'create-route') next.panel = 'new-route';
        if (editorMode.kind === 'rehearse') next.panel = 'rehearsal';
        return next;
    }

    function _writeState({ push = false } = {}) {
        UI.updateQueryParams({
            protocol_id: currentProtocolId || '',
            run_id: '',
            status: '',
            issue_kind: '',
            entry_agent_id: '',
            protocol_view: '',
            ..._selectionQueryState(),
        }, { replace: !push });
    }

    // -------------------------------------------------------------------
    // Persistence
    // -------------------------------------------------------------------
    function _clearAutosaveTimer() {
        if (autosaveTimer) {
            clearTimeout(autosaveTimer);
            autosaveTimer = 0;
        }
    }

    function _scheduleAutosave() {
        if (!currentProtocolId) return;
        if (saveState.state === 'conflict') return;
        _clearAutosaveTimer();
        saveState = { state: 'editing', lastSavedAt: saveState.lastSavedAt, error: '' };
        _syncLifecycleChip();
        autosaveTimer = setTimeout(() => {
            autosaveTimer = 0;
            void _autosave();
        }, 450);
    }

    async function _autosave() {
        if (!currentProtocolId) return;
        saveState = { state: 'saving', lastSavedAt: saveState.lastSavedAt, error: '' };
        _syncLifecycleChip();
        try {
            const result = await API.saveProtocolDraft(currentProtocolId, {
                slug: draft.slug,
                display_name: draft.display_name,
                description: draft.description,
                definition_json: _docFromDraft(),
            }, {
                ifMatch: draftRevision,
                authoringSurface: _currentAuthoringSurface(),
            });
            _applyServerDetail(result, { preserveTransient: true });
            saveState = { state: 'saved', lastSavedAt: result?.protocol?.updated_at || new Date().toISOString(), error: '' };
            _syncLifecycleChip();
            await loadProtocols({ quiet: true });
            render();
            return true;
        } catch (err) {
            if (err?.status === 409 && err?.errorCode === 'PROTOCOL_DRAFT_CONFLICT') {
                draftConflict = {
                    serverDetail: {
                        protocol: err?.details?.protocol || null,
                        draft_definition_json: err?.details?.draft_definition_json || {},
                        draft_document: err?.details?.draft_document || null,
                        validation: err?.details?.validation || null,
                    },
                };
                saveState = {
                    state: 'conflict',
                    lastSavedAt: err?.details?.protocol?.updated_at || saveState.lastSavedAt,
                    error: err.message || String(err),
                };
                _syncLifecycleChip();
                render();
                UI.notify('Protocol draft changed in another tab or client. Reload or overwrite to continue.', 'warning');
                return false;
            }
            saveState = { state: 'error', lastSavedAt: saveState.lastSavedAt, error: err.message || String(err) };
            _syncLifecycleChip();
            UI.reportError('Failed to save the protocol draft', err, { context: 'Protocol autosave failed' });
            return false;
        }
    }

    function _blockConflictAction(actionLabel) {
        if (saveState.state !== 'conflict' || !draftConflict?.serverDetail?.protocol) {
            return false;
        }
        UI.notify(`${actionLabel} is blocked until you reload or overwrite the latest server draft.`, 'warning');
        return true;
    }

    function _reloadServerDraftConflict() {
        if (!draftConflict?.serverDetail?.protocol) return;
        _applyServerDetail(draftConflict.serverDetail);
        saveState = { state: 'saved', lastSavedAt: currentProtocol?.protocol?.updated_at || '', error: '' };
        render();
        UI.notify('Reloaded the latest server draft.', 'success');
    }

    async function _overwriteServerDraftConflict() {
        if (!draftConflict?.serverDetail?.protocol) return;
        const localDraft = {
            slug: draft.slug,
            display_name: draft.display_name,
            description: draft.description,
            document: _cloneDoc(draft.document),
        };
        const localSelection = selection;
        _applyServerDetail(draftConflict.serverDetail);
        draft = localDraft;
        selection = _repairSelection(localSelection, draft.document);
        saveState = { state: 'editing', lastSavedAt: currentProtocol?.protocol?.updated_at || '', error: '' };
        _syncLifecycleChip();
        render();
        const saved = await _autosave();
        if (saved) {
            UI.notify('Overwrote the server draft with your local changes.', 'success');
        }
    }

    async function _validateNow() {
        if (_blockConflictAction('Validate')) return;
        if (!currentProtocolId) return;
        if (saveState.state === 'editing' || saveState.state === 'saving') {
            const saved = await _autosave();
            if (!saved) return;
        }
        saveState = { state: 'saving', lastSavedAt: saveState.lastSavedAt, error: '' };
        _syncLifecycleChip();
        currentProtocol = await API.validateProtocol(currentProtocolId);
        _applyServerDetail(currentProtocol);
        saveState = { state: 'saved', lastSavedAt: new Date().toISOString(), error: '' };
        render();
        UI.notify(
            currentProtocol.validation?.ok ? 'Protocol validated.' : 'Protocol validation found issues.',
            currentProtocol.validation?.ok ? 'success' : 'warning',
        );
    }

    async function _publishNow() {
        if (_blockConflictAction('Publish')) return;
        if (!currentProtocolId) return;
        if (saveState.state === 'editing' || saveState.state === 'saving') {
            const saved = await _autosave();
            if (!saved) return;
        }
        _clearAutosaveTimer();
        saveState = { state: 'saving', lastSavedAt: saveState.lastSavedAt, error: '' };
        _syncLifecycleChip();
        currentProtocol = await API.publishProtocol(currentProtocolId);
        _applyServerDetail(currentProtocol);
        await loadProtocols({ quiet: true });
        saveState = { state: 'saved', lastSavedAt: new Date().toISOString(), error: '' };
        render();
        UI.notify('Protocol published.', 'success');
    }

    async function _archiveNow() {
        if (_blockConflictAction('Archive')) return;
        _clearAutosaveTimer();
        saveState = { state: 'saving', lastSavedAt: saveState.lastSavedAt, error: '' };
        _syncLifecycleChip();
        currentProtocol = await API.archiveProtocol(currentProtocolId);
        _applyServerDetail(currentProtocol);
        await loadProtocols({ quiet: true });
        saveState = { state: 'saved', lastSavedAt: new Date().toISOString(), error: '' };
        render();
        UI.notify('Protocol archived.', 'success');
    }

    async function _discardNow() {
        if (_blockConflictAction('Discard')) return;
        _clearAutosaveTimer();
        if (!currentProtocolId) {
            _resetDraft();
            _writeState({ push: true });
            render();
            return;
        }
        await API.deleteProtocol(currentProtocolId);
        _resetDraft();
        _writeState({ push: true });
        await loadProtocols({ quiet: true });
        render();
        UI.notify('Protocol draft discarded.', 'success');
    }

    function _resetDraft() {
        _clearAutosaveTimer();
        currentProtocolId = '';
        currentProtocol = null;
        protocolDetailLoading = false;
        draftRevision = 0;
        draftConflict = null;
        _stopRehearsalPolling();
        rehearsal.runId = '';
        rehearsal.sessions = [];
        rehearsal.scenarios = [];
        rehearsal.runDetail = null;
        documentHistory = { undo: [], redo: [] };
        draft = { slug: '', display_name: '', description: '', document: _blankDocument() };
        selection = { sectionKey: 'overview', nodeKey: '' };
        saveState = { state: 'idle', lastSavedAt: '', error: '' };
        canvasViewport = { zoom: 'fit' };
        workflowMapMode = 'auto';
        stageAssignmentEditor = { stageKey: '', mode: '' };
        _resetEditorMode();
    }

    async function _createBlankDraft() {
        try {
            const result = await API.createProtocolDraft({ source_kind: 'blank' });
            currentProtocolId = result.protocol?.protocol_id || '';
            _applyServerDetail(result);
            _writeState({ push: true });
            await loadProtocols({ quiet: true });
            render();
            UI.notify('Protocol draft created.', 'success');
        } catch (err) {
            UI.reportError('Failed to create a blank protocol draft', err, {
                context: 'Protocol draft create failed',
            });
        }
    }

    // -------------------------------------------------------------------
    // Rehearsal
    // -------------------------------------------------------------------
    function _stopRehearsalPolling() {
        if (rehearsal.pollTimer) {
            clearTimeout(rehearsal.pollTimer);
            rehearsal.pollTimer = 0;
        }
    }

    async function _refreshRehearsalSessions() {
        if (!rehearsal.runId) return;
        try {
            const [sessionsResp, scenariosResp, runDetail] = await Promise.all([
                API.listRehearsalSessions(rehearsal.runId),
                API.listProtocolScenarios({ protocol_id: currentProtocolId || '' }),
                API.getProtocolRun(rehearsal.runId),
            ]);
            rehearsal.sessions = Array.isArray(sessionsResp?.sessions) ? sessionsResp.sessions : [];
            rehearsal.scenarios = Array.isArray(scenariosResp?.scenarios) ? scenariosResp.scenarios : [];
            rehearsal.runDetail = runDetail || null;
            render();
        } catch (err) {
            UI.reportError('Failed to refresh rehearsal state', err);
        } finally {
            if (rehearsal.runId) {
                _stopRehearsalPolling();
                rehearsal.pollTimer = setTimeout(() => { void _refreshRehearsalSessions(); }, 1500);
            }
        }
    }

    async function _startRehearsal() {
        if (_blockConflictAction('Rehearsal')) return;
        if (!currentProtocolId) return;
        const created = await API.createProtocolRun({
            protocol_id: currentProtocolId,
            is_rehearsal: true,
            entry_authority_ref: 'rehearsal',
        });
        rehearsal.runId = String(created?.run?.protocol_run_id || '');
        rehearsal.sessions = [];
        rehearsal.scenarios = [];
        rehearsal.runDetail = null;
        if (!rehearsal.runId) {
            UI.notify('Rehearsal could not be started.', 'error');
            return;
        }
        editorMode = { kind: 'rehearse', sourceStageKey: '', decision: '' };
        UI.notify('Rehearsal started — dry run, external transports gated.', 'success');
        render();
        await _refreshRehearsalSessions();
    }

    async function _respondRehearsal({ routedTaskId, responseText, decision, decisionSummary, stageKey, participantKey }) {
        if (!rehearsal.runId || !routedTaskId) return;
        try {
            await API.respondRehearsalSession(rehearsal.runId, {
                routed_task_id: routedTaskId,
                response_text: String(responseText || ''),
                decision: String(decision || ''),
                decision_summary: String(decisionSummary || ''),
                stage_key: stageKey || '',
                participant_key: participantKey || '',
            });
            await _refreshRehearsalSessions();
        } catch (err) {
            UI.reportError('Failed to submit rehearsal response', err);
        }
    }

    cleanups.add(_stopRehearsalPolling);

    // -------------------------------------------------------------------
    // Details panel field commits
    // -------------------------------------------------------------------
    function _commitOverview(_target, key, value) {
        if (key === 'display_name') {
            draft.display_name = String(value || '');
            if (!draft.slug) draft.slug = _slugSuggestion(draft.display_name);
        } else if (key === 'slug') {
            draft.slug = _slugSuggestion(value);
        } else if (key === 'description') {
            draft.description = String(value || '');
        } else if (key === 'single_active_writer') {
            draft.document.policies = Object.assign({}, draft.document.policies || {}, { single_active_writer: Boolean(value) });
        } else if (key === 'max_review_rounds') {
            draft.document.policies = Object.assign({}, draft.document.policies || {}, {
                max_review_rounds: Number.parseInt(String(value || '5'), 10) || 5,
            });
        }
        _scheduleAutosave();
        _syncLifecycleHeaderInputs();
        render();
    }

    function _historySnapshot() {
        return {
            draft: {
                slug: draft.slug,
                display_name: draft.display_name,
                description: draft.description,
                document: _cloneDoc(draft.document),
            },
            selection: { ...selection },
        };
    }

    function _pushHistory() {
        documentHistory.undo.push(_historySnapshot());
        if (documentHistory.undo.length > 40) {
            documentHistory.undo.shift();
        }
        documentHistory.redo = [];
    }

    function _restoreHistory(direction) {
        const source = direction === 'redo' ? documentHistory.redo : documentHistory.undo;
        const target = direction === 'redo' ? documentHistory.undo : documentHistory.redo;
        const snapshot = source.pop();
        if (!snapshot) return;
        target.push(_historySnapshot());
        draft = {
            slug: String(snapshot.draft.slug || ''),
            display_name: String(snapshot.draft.display_name || ''),
            description: String(snapshot.draft.description || ''),
            document: _cloneDoc(snapshot.draft.document),
        };
        selection = _repairSelection(snapshot.selection, draft.document);
        _resetEditorMode();
        _scheduleAutosave();
        render();
    }

    function _stageTransitionId(stageKey, decision) {
        return `${String(stageKey || '').trim()}::${String(decision || '').trim().toLowerCase()}`;
    }

    function _transitionEntries(doc) {
        const entries = [];
        (doc.stages || []).forEach((stage) => {
            const transitions = stage.transitions || {};
            Object.entries(transitions).forEach(([decision, target]) => {
                const decisionKey = String(decision || '').trim().toLowerCase();
                const targetKey = String(target || '').trim();
                if (!decisionKey || !targetKey) return;
                entries.push({
                    id: _stageTransitionId(stage.stage_key, decisionKey),
                    from_stage_key: String(stage.stage_key || ''),
                    decision: decisionKey,
                    target_key: targetKey,
                });
            });
        });
        return entries;
    }

    function _rewriteKeyReferences(doc, kind, fromKey, toKey) {
        const sourceKey = String(fromKey || '').trim();
        const nextKey = String(toKey || '').trim();
        if (!sourceKey || !nextKey || sourceKey === nextKey) return;
        if (kind === 'participant') {
            doc.stages = (doc.stages || []).map((stage) => (
                String(stage.participant_key || '') === sourceKey
                    ? { ...stage, participant_key: nextKey }
                    : stage
            ));
            return;
        }
        if (kind === 'stage') {
            doc.stages = (doc.stages || []).map((stage) => {
                const transitions = Object.fromEntries(
                    Object.entries(stage.transitions || {}).map(([decision, target]) => [
                        decision,
                        String(target || '') === sourceKey ? nextKey : target,
                    ]),
                );
                return { ...stage, transitions };
            });
            return;
        }
        if (kind === 'artifact') {
            doc.stages = (doc.stages || []).map((stage) => ({
                ...stage,
                inputs: (stage.inputs || []).map((item) => (String(item || '') === sourceKey ? nextKey : item)),
                outputs: (stage.outputs || []).map((item) => (String(item || '') === sourceKey ? nextKey : item)),
            }));
        }
    }

    function _nextAvailableKey(items, field, preferred, currentKey = '') {
        const normalized = _slugSuggestion(preferred) || String(field || '').replace(/_key$/, '');
        const current = String(currentKey || '').trim();
        const seen = new Set((items || []).map((item) => String(item?.[field] || '').trim()).filter(Boolean));
        if (current) seen.delete(current);
        if (!seen.has(normalized)) return normalized;
        let index = 2;
        while (seen.has(`${normalized}_${index}`)) {
            index += 1;
        }
        return `${normalized}_${index}`;
    }

    function _commitDocument(nextDoc, { nextSelection = selection, pushHistory = true } = {}) {
        if (pushHistory) _pushHistory();
        draft.document = nextDoc;
        selection = _repairSelection(nextSelection, nextDoc);
        _scheduleAutosave();
        render();
    }

    function _commitNodeField(kind, nodeKey, key, value) {
        const plural = kind + 's';
        const doc = _cloneDoc(draft.document);
        const items = Array.isArray(doc[plural]) ? doc[plural] : [];
        const idField = kind === 'participant' ? 'participant_key' : kind === 'stage' ? 'stage_key' : 'artifact_key';
        const idx = items.findIndex((item) => String(item[idField] || '') === nodeKey);
        if (idx < 0) return;
        const next = Object.assign({}, items[idx]);
        if (kind === 'stage' && key === 'selector_kind') {
            next.selector = _selectorFromFields(value, next.selector?.value || '', next.selector?.preferred_agent_id || '');
        } else if (kind === 'stage' && key === 'selector_value') {
            next.selector = _selectorFromFields(next.selector?.kind || '', value, next.selector?.preferred_agent_id || '');
        } else if (kind === 'stage' && key === 'selector_preferred_agent_id') {
            next.selector = _selectorFromFields(next.selector?.kind || '', next.selector?.value || '', value);
        } else if (key === 'inputs' || key === 'outputs') {
            next[key] = Array.isArray(value) ? value.map((item) => String(item || '').trim()).filter(Boolean) : [];
        } else if (key === 'max_rounds' || key === 'timeout_seconds') {
            next[key] = Number.parseInt(String(value || '0'), 10) || 0;
        } else if (key === 'verify') {
            next.verify = Boolean(value);
        } else {
            next[key] = value;
        }
        let nextNodeKey = nodeKey;
        if (key === idField) {
            const rewritten = _slugSuggestion(value) || nodeKey;
            next[idField] = rewritten;
            _rewriteKeyReferences(doc, kind, nodeKey, rewritten);
            nextNodeKey = rewritten;
        }
        items[idx] = next;
        doc[plural] = items;
        _commitDocument(doc, {
            nextSelection: { sectionKey: plural, nodeKey: String(nextNodeKey || '') },
        });
    }

    function _commitPendingStageField(_target, key, value) {
        if (key === 'display_name') {
            pendingStage.display_name = String(value || '');
            if (!String(pendingStage.stage_key || '').trim()) {
                pendingStage.stage_key = _slugSuggestion(pendingStage.display_name);
            }
        } else if (key === 'stage_key') {
            pendingStage.stage_key = _slugSuggestion(value);
        } else if (key === 'stage_kind') {
            pendingStage.stage_kind = String(value || 'work') || 'work';
        } else if (key === 'participant_key') {
            pendingStage.participant_key = String(value || '');
            if (String(value || '') !== '__new__') {
                pendingStage.role_display_name = '';
                pendingStage.role_participant_key = '';
                pendingStage.role_instructions = '';
            }
        } else if (key === 'selector_mode') {
            pendingStage.selector_mode = _selectorModeFromKind(value, pendingStage.selector_mode || 'skill');
        } else if (key === 'selector_kind' || key === 'selector_value' || key === 'selector_preferred_agent_id') {
            pendingStage[key] = String(value || '');
        } else if (key === 'role_display_name') {
            pendingStage.role_display_name = String(value || '');
            if (!String(pendingStage.role_participant_key || '').trim()) {
                pendingStage.role_participant_key = _slugSuggestion(pendingStage.role_display_name);
            }
        } else if (key === 'role_participant_key') {
            pendingStage.role_participant_key = _slugSuggestion(value);
        } else if (key === 'role_instructions') {
            pendingStage.role_instructions = String(value || '');
        } else if (key === 'instructions') {
            pendingStage.instructions = String(value || '');
        } else if (key === 'inputs' || key === 'outputs') {
            pendingStage[key] = Array.isArray(value) ? value.map((item) => String(item || '').trim()).filter(Boolean) : [];
        } else if (key === 'max_rounds' || key === 'timeout_seconds') {
            pendingStage[key] = Number.parseInt(String(value || '0'), 10) || 0;
        }
        if (['participant_key', 'selector_mode', 'selector_kind', 'selector_value', 'selector_preferred_agent_id', 'stage_kind'].includes(String(key || ''))) {
            queueMicrotask(() => render());
        }
    }

    function _commitPendingStageSelector(selectorKind, selectorValue, selectorPreferredAgentId = '') {
        if (String(selectorKind || '').trim()) {
            pendingStage.selector_mode = _selectorModeFromKind(selectorKind, pendingStage.selector_mode || 'skill');
        }
        pendingStage.selector_kind = String(selectorKind || '');
        pendingStage.selector_value = String(selectorValue || '');
        pendingStage.selector_preferred_agent_id = String(selectorPreferredAgentId || '');
        queueMicrotask(() => render());
    }

    function _syncPendingStageFromMountedEditor() {
        const editor = contentEl.querySelector('.kit-stage-editor-grid');
        if (!(editor instanceof Element)) return;
        const readValue = (selector) => {
            const control = editor.querySelector(selector);
            return control instanceof HTMLInputElement || control instanceof HTMLTextAreaElement || control instanceof HTMLSelectElement
                ? String(control.value || '')
                : control instanceof Element && Object.prototype.hasOwnProperty.call(control.dataset || {}, 'value')
                    ? String(control.dataset.value || '')
                : '';
        };
        pendingStage.display_name = readValue('#kit-details-display_name');
        pendingStage.participant_key = readValue('#kit-details-participant_key');
        pendingStage.stage_kind = readValue('#kit-details-stage_kind') || 'work';
        pendingStage.role_display_name = readValue('#kit-details-role_display_name');
        pendingStage.role_participant_key = _slugSuggestion(readValue('#kit-details-role_participant_key'));
        pendingStage.role_instructions = readValue('#kit-details-role_instructions');
        pendingStage.instructions = readValue('#kit-details-instructions');
        pendingStage.max_rounds = Number.parseInt(readValue('#kit-details-max_rounds') || '0', 10) || 0;
        pendingStage.timeout_seconds = Number.parseInt(readValue('#kit-details-timeout_seconds') || '0', 10) || 0;
        const activeModeButton = editor.querySelector('.segmented-control-btn.active');
        pendingStage.selector_mode = _selectorModeFromKind(
            activeModeButton instanceof HTMLButtonElement ? activeModeButton.dataset.value || '' : pendingStage.selector_mode,
            pendingStage.selector_mode || 'skill',
        );
        const advancedKind = readValue('select[aria-label="Custom selector type"]');
        const selector = _selectorFromEditorFields({
            requiredSkill: readValue('[aria-label="Required skill"]'),
            pinnedAgent: readValue('[aria-label="Pin matching agent (optional)"]')
                || readValue('[aria-label="Pinned agent"]')
                || readValue('[aria-label="Agent"]'),
            advancedKind,
            advancedValue: advancedKind === 'role'
                ? (readValue('[aria-label="Choose runtime role tag"]') || readValue('[aria-label="Custom value"]'))
                : readValue('[aria-label="Custom value"]'),
        });
        pendingStage.selector_kind = String(selector?.kind || '');
        pendingStage.selector_value = String(selector?.value || '');
        pendingStage.selector_preferred_agent_id = String(selector?.preferred_agent_id || '');
    }

    function _bindPendingStageEditorControls(root) {
        if (!(root instanceof Element)) return;
        const syncAssignment = () => {
            _syncPendingStageFromMountedEditor();
            queueMicrotask(() => render());
        };
        const bindText = (selector, key) => {
            const control = root.querySelector(selector);
            if (!(control instanceof HTMLInputElement) && !(control instanceof HTMLTextAreaElement)) return;
            if (control.__pendingStageBound === true) return;
            control.__pendingStageBound = true;
            const commit = () => _commitPendingStageField(null, key, control.value);
            control.addEventListener('input', commit);
            control.addEventListener('change', commit);
        };
        const bindSelect = (selector, key) => {
            const control = root.querySelector(selector);
            if (!(control instanceof HTMLSelectElement)) return;
            if (control.__pendingStageBound === true) return;
            control.__pendingStageBound = true;
            control.addEventListener('change', () => _commitPendingStageField(null, key, control.value));
        };
        const bindAssignmentControl = (selector, eventName = 'change') => {
            const control = root.querySelector(selector);
            if (!(control instanceof HTMLInputElement)
                && !(control instanceof HTMLSelectElement)
                && !(control instanceof HTMLTextAreaElement)
                && !(control instanceof Element && control.dataset.selectorPillGroup === 'true')) return;
            const bindingKey = `__pendingAssignmentBound_${eventName}`;
            if (control[bindingKey] === true) return;
            control[bindingKey] = true;
            control.addEventListener(control instanceof Element && control.dataset.selectorPillGroup === 'true' ? 'click' : eventName, syncAssignment);
        };
        bindText('#kit-details-display_name', 'display_name');
        bindSelect('#kit-details-participant_key', 'participant_key');
        bindSelect('#kit-details-stage_kind', 'stage_kind');
        bindText('#kit-details-role_display_name', 'role_display_name');
        bindText('#kit-details-role_participant_key', 'role_participant_key');
        bindText('#kit-details-role_instructions', 'role_instructions');
        bindText('#kit-details-instructions', 'instructions');
        bindText('#kit-details-max_rounds', 'max_rounds');
        bindText('#kit-details-timeout_seconds', 'timeout_seconds');
        root.querySelectorAll('.segmented-control[aria-label="Assignment mode"] .segmented-control-btn').forEach((button) => {
            if (!(button instanceof HTMLButtonElement) || button.__pendingStageBound === true) return;
            button.__pendingStageBound = true;
            button.addEventListener('click', () => _commitPendingStageField(null, 'selector_mode', button.dataset.value || ''));
        });
        bindAssignmentControl('[aria-label="Required skill"]');
        bindAssignmentControl('[aria-label="Pin matching agent (optional)"]');
        bindAssignmentControl('[aria-label="Agent"]');
        bindAssignmentControl('[aria-label="Limit to one of this agent\'s skills (optional)"]');
        bindAssignmentControl('[aria-label="Custom selector type"]');
        bindAssignmentControl('[aria-label="Choose runtime role tag"]');
        bindAssignmentControl('[aria-label="Custom value"]', 'input');
        bindAssignmentControl('[aria-label="Custom value"]', 'change');
    }

    function _commitStageSelector(nodeKey, selectorKind, selectorValue, selectorPreferredAgentId = '') {
        const doc = _cloneDoc(draft.document);
        const items = [...(doc.stages || [])];
        const idx = items.findIndex((item) => String(item.stage_key || '') === String(nodeKey || ''));
        if (idx < 0) return;
        stageAssignmentEditor = {
            stageKey: String(nodeKey || ''),
            mode: _selectorModeFromKind(selectorKind, stageAssignmentEditor.mode || 'skill'),
        };
        const next = Object.assign({}, items[idx], {
            selector: _selectorFromFields(selectorKind, selectorValue, selectorPreferredAgentId),
        });
        items[idx] = next;
        doc.stages = items;
        const nextNodeKey = String(nodeKey || '');
        _commitDocument(doc, {
            nextSelection: { sectionKey: 'stages', nodeKey: nextNodeKey },
        });
    }

    function _startStageInsert({ sourceStageKey = '', decision = '' } = {}) {
        pendingStage = _blankStageDraft(_defaultStageParticipantKey());
        editorMode = {
            kind: 'insert-stage',
            sourceStageKey: String(sourceStageKey || ''),
            decision: String(decision || '').trim().toLowerCase(),
            sessionKey: String(++editorSessionNonce),
        };
        render();
    }

    function _confirmStageInsert() {
        _syncPendingStageFromMountedEditor();
        const displayName = String(pendingStage.display_name || '').trim();
        if (!displayName) {
            UI.notify('Give this step a name before adding it to the workflow.', 'warning');
            return;
        }
        const creatingRole = String(pendingStage.participant_key || '') === '__new__'
            || Boolean(String(pendingStage.role_display_name || '').trim());
        if (!creatingRole && !String(pendingStage.participant_key || '').trim()) {
            UI.notify('Choose the owner role for this step before creating it.', 'warning');
            return;
        }
        if (creatingRole && !String(pendingStage.role_display_name || '').trim()) {
            UI.notify('Name the owner role before creating this step.', 'warning');
            return;
        }
        if (!_hasSelectorAssignment(pendingStage.selector_kind, pendingStage.selector_value)) {
            UI.notify('Choose how this step resolves before creating it.', 'warning');
            return;
        }
        const doc = _cloneDoc(draft.document);
        let participantKey = String(pendingStage.participant_key || '').trim();
        if (creatingRole) {
            const roleKey = _nextAvailableKey(
                doc.participants || [],
                'participant_key',
                String(pendingStage.role_participant_key || pendingStage.role_display_name || 'role'),
            );
            doc.participants = [...(doc.participants || []), {
                participant_key: roleKey,
                display_name: String(pendingStage.role_display_name || '').trim(),
                instructions: String(pendingStage.role_instructions || ''),
            }];
            participantKey = roleKey;
        }
        const stageKey = _nextAvailableKey(
            doc.stages || [],
            'stage_key',
            String(pendingStage.stage_key || displayName || 'step'),
        );
        const nextStage = {
            stage_key: stageKey,
            display_name: displayName,
            participant_key: participantKey,
            selector: _selectorFromFields(
                pendingStage.selector_kind,
                pendingStage.selector_value,
                pendingStage.selector_preferred_agent_id,
            ),
            stage_kind: String(pendingStage.stage_kind || 'work') || 'work',
            instructions: String(pendingStage.instructions || ''),
            inputs: Array.isArray(pendingStage.inputs) ? pendingStage.inputs : [],
            outputs: Array.isArray(pendingStage.outputs) ? pendingStage.outputs : [],
            transitions: {},
            max_rounds: Number.parseInt(String(pendingStage.max_rounds || '0'), 10) || 0,
            timeout_seconds: Number.parseInt(String(pendingStage.timeout_seconds || '0'), 10) || 0,
        };
        const items = [...(doc.stages || [])];
        const sourceStageKey = String(editorMode.sourceStageKey || '').trim();
        const decision = String(editorMode.decision || '').trim().toLowerCase();
        if (sourceStageKey && decision) {
            const sourceIndex = items.findIndex((item) => String(item.stage_key || '') === sourceStageKey);
            if (sourceIndex >= 0) {
                const sourceStage = { ...items[sourceIndex] };
                const priorTarget = String(sourceStage.transitions?.[decision] || '').trim();
                sourceStage.transitions = Object.assign({}, sourceStage.transitions || {}, {
                    [decision]: stageKey,
                });
                if (priorTarget) {
                    nextStage.transitions = { completed: priorTarget };
                }
                items[sourceIndex] = sourceStage;
                const targetIndex = items.findIndex((item) => String(item.stage_key || '') === priorTarget);
                const insertIndex = targetIndex > sourceIndex ? targetIndex : sourceIndex + 1;
                items.splice(insertIndex, 0, nextStage);
                doc.stages = items;
            } else {
                doc.stages = [...items, nextStage];
            }
        } else {
            doc.stages = [...items, nextStage];
        }
        _resetEditorMode();
        _commitDocument(doc, {
            nextSelection: { sectionKey: 'stages', nodeKey: stageKey },
        });
    }

    function _cancelStageInsert() {
        _resetEditorMode();
        render();
    }

    function _addArtifact() {
        const doc = _cloneDoc(draft.document);
        const n = (doc.artifacts || []).length + 1;
        const key = `artifact_${n}`;
        doc.artifacts = [...(doc.artifacts || []), {
            artifact_key: key,
            display_name: '',
            kind: 'workspace_file',
            description: '',
            path: '',
            verify: true,
        }];
        _commitDocument(doc, { nextSelection: { sectionKey: 'artifacts', nodeKey: key } });
    }

    function _moveStageBefore(nodeId, targetId) {
        const doc = _cloneDoc(draft.document);
        const items = [...(doc.stages || [])];
        const fromIndex = items.findIndex((item) => String(item.stage_key || '') === String(nodeId || ''));
        const toIndex = items.findIndex((item) => String(item.stage_key || '') === String(targetId || ''));
        if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) return;
        const [moved] = items.splice(fromIndex, 1);
        items.splice(toIndex, 0, moved);
        doc.stages = items;
        _commitDocument(doc, { nextSelection: { sectionKey: 'stages', nodeKey: String(nodeId || '') } });
    }

    function _startRouteInsert(stageKey) {
        const stage = (draft.document.stages || []).find((item) => String(item.stage_key || '') === String(stageKey || ''));
        if (!stage) return;
        pendingRoute = _blankRouteDraft(stage.stage_key, stage.stage_kind);
        selection = { sectionKey: 'stages', nodeKey: String(stage.stage_key || '') };
        editorMode = {
            kind: 'create-route',
            sourceStageKey: String(stage.stage_key || ''),
            decision: String(pendingRoute.decision || ''),
            sessionKey: String(++editorSessionNonce),
        };
        render();
    }

    function _commitPendingRouteField(_target, key, value) {
        if (key === 'decision') {
            pendingRoute.decision = String(value || '').trim().toLowerCase();
        } else if (key === 'target_key') {
            pendingRoute.target_key = String(value || '').trim();
        }
        render();
    }

    function _confirmRouteInsert() {
        const sourceStageKey = String(pendingRoute.source_stage_key || '').trim();
        const decision = String(pendingRoute.decision || '').trim().toLowerCase();
        const targetKey = String(pendingRoute.target_key || '').trim();
        if (!sourceStageKey || !decision || !targetKey) {
            UI.notify('Choose a decision and a next step or finish outcome before adding this route.', 'warning');
            return;
        }
        const doc = _cloneDoc(draft.document);
        const items = [...(doc.stages || [])];
        const idx = items.findIndex((item) => String(item.stage_key || '') === sourceStageKey);
        if (idx < 0) return;
        const stage = { ...items[idx] };
        stage.transitions = Object.assign({}, stage.transitions || {}, {
            [decision]: targetKey,
        });
        items[idx] = stage;
        doc.stages = items;
        const edgeId = _stageTransitionId(sourceStageKey, decision);
        _resetEditorMode();
        _commitDocument(doc, {
            nextSelection: { sectionKey: 'transitions', nodeKey: edgeId },
        });
    }

    function _cancelRouteInsert() {
        _resetEditorMode();
        render();
    }

    function _commitTransitionField(edgeId, key, value) {
        const [fromStageKey, currentDecision] = String(edgeId || '').split('::');
        const doc = _cloneDoc(draft.document);
        const items = [...(doc.stages || [])];
        const idx = items.findIndex((item) => String(item.stage_key || '') === fromStageKey);
        if (idx < 0) return;
        const stage = { ...items[idx] };
        const transitions = Object.assign({}, stage.transitions || {});
        const existingTarget = String(transitions[currentDecision] || '').trim();
        if (!existingTarget) return;
        let nextDecision = currentDecision;
        let nextTarget = existingTarget;
        if (key === 'decision') {
            nextDecision = String(value || '').trim().toLowerCase() || currentDecision;
            delete transitions[currentDecision];
            transitions[nextDecision] = existingTarget;
        } else if (key === 'target_key') {
            nextTarget = String(value || '').trim();
            transitions[currentDecision] = nextTarget;
        }
        stage.transitions = transitions;
        items[idx] = stage;
        doc.stages = items;
        _commitDocument(doc, {
            nextSelection: { sectionKey: 'transitions', nodeKey: _stageTransitionId(fromStageKey, nextDecision) },
        });
    }

    function _deleteTransition(edgeId) {
        const [fromStageKey, decision] = String(edgeId || '').split('::');
        const doc = _cloneDoc(draft.document);
        const items = [...(doc.stages || [])];
        const idx = items.findIndex((item) => String(item.stage_key || '') === fromStageKey);
        if (idx < 0) return;
        const stage = { ...items[idx] };
        const transitions = Object.assign({}, stage.transitions || {});
        delete transitions[decision];
        stage.transitions = transitions;
        items[idx] = stage;
        doc.stages = items;
        _commitDocument(doc, { nextSelection: { sectionKey: 'stages', nodeKey: fromStageKey } });
    }

    function _stageDeletionPlan(stageKey, doc = draft.document) {
        const normalizedStageKey = String(stageKey || '').trim();
        if (!normalizedStageKey) return null;
        const stages = Array.isArray(doc?.stages) ? doc.stages : [];
        const stageIndex = stages.findIndex((item) => String(item.stage_key || '') === normalizedStageKey);
        if (stageIndex < 0) return null;
        const stage = stages[stageIndex];
        const outgoing = Object.entries(stage.transitions || {})
            .map(([decision, target]) => ({
                decision: String(decision || '').trim().toLowerCase(),
                target: String(target || '').trim(),
            }))
            .filter((item) => item.decision && item.target);
        const successorTargets = Array.from(new Set(outgoing
            .map((item) => item.target)
            .filter((item) => item && item !== normalizedStageKey)));
        const redirectTarget = successorTargets.length === 1 ? successorTargets[0] : '';
        const incoming = stages.flatMap((source) => Object.entries(source.transitions || {})
            .filter(([, target]) => String(target || '').trim() === normalizedStageKey)
            .map(([decision]) => ({
                sourceStageKey: String(source.stage_key || ''),
                decision: String(decision || '').trim().toLowerCase(),
            })))
            .filter((item) => item.sourceStageKey && item.sourceStageKey !== normalizedStageKey);
        const siblingFallback = stages[stageIndex + 1]?.stage_key || stages[stageIndex - 1]?.stage_key || '';
        const nextSelection = redirectTarget && !PROTOCOL_TERMINAL_TARGETS.some((item) => item.key === redirectTarget)
            ? { sectionKey: 'stages', nodeKey: redirectTarget }
            : siblingFallback
                ? { sectionKey: 'stages', nodeKey: String(siblingFallback || '') }
                : { sectionKey: 'overview', nodeKey: '' };
        return {
            stage,
            stageIndex,
            outgoing,
            incoming,
            redirectTarget,
            nextSelection,
        };
    }

    function _deleteStage(stageKey) {
        const plan = _stageDeletionPlan(stageKey, draft.document);
        if (!plan) return;
        const doc = _cloneDoc(draft.document);
        doc.stages = (doc.stages || [])
            .filter((item) => String(item.stage_key || '') !== String(stageKey || ''))
            .map((item) => {
                const transitions = {};
                Object.entries(item.transitions || {}).forEach(([decision, target]) => {
                    const normalizedTarget = String(target || '').trim();
                    if (normalizedTarget !== String(stageKey || '').trim()) {
                        transitions[decision] = target;
                        return;
                    }
                    if (plan.redirectTarget) {
                        transitions[decision] = plan.redirectTarget;
                    }
                });
                return { ...item, transitions };
            });
        _commitDocument(doc, { nextSelection: plan.nextSelection });
    }

    function _confirmStageDelete(stageKey) {
        const plan = _stageDeletionPlan(stageKey, draft.document);
        if (!plan) return;
        const stageLabel = String(plan.stage?.display_name || plan.stage?.stage_key || 'this step');
        const consequences = [];
        if (plan.redirectTarget) {
            consequences.push(`Incoming routes will be rewired to ${_transitionTargetLabel(plan.redirectTarget, draft.document) || plan.redirectTarget}.`);
        } else if (plan.incoming.length) {
            consequences.push('Incoming routes to this step will be removed.');
        }
        if (plan.outgoing.length > 1) {
            consequences.push('This step fans out to multiple branches, so deleting it also removes those outgoing branches.');
        } else if (!plan.outgoing.length) {
            consequences.push('This step has no outgoing branch; deleting it simply removes it from the workflow.');
        }
        UI.showConfirm(
            'Delete step',
            [`Delete ${stageLabel}?`, ...consequences].join(' '),
            async () => { _deleteStage(stageKey); },
        );
    }

    function _isAuthoringAssignableAgent(agent) {
        const slug = String(agent?.slug || '').trim().toLowerCase();
        const role = String(agent?.role || '').trim().toLowerCase();
        const botKey = String(agent?.bot_key || '').trim().toLowerCase();
        const tags = Array.isArray(agent?.tags)
            ? agent.tags.map((item) => String(item || '').trim().toLowerCase()).filter(Boolean)
            : [];
        if (tags.includes('rehearsal') || tags.includes('system')) return false;
        return slug !== 'rehearsal' && role !== 'rehearsal' && botKey !== 'registry.rehearsal';
    }

    function _authoringAssignableAgents() {
        return (connectedAgents || []).filter((agent) => _isAuthoringAssignableAgent(agent));
    }

    function _authoringAssignableCandidates(candidates) {
        return (Array.isArray(candidates) ? candidates : []).filter((candidate) => _isAuthoringAssignableAgent(candidate));
    }

    function _availableAuthoringAgents() {
        return (availableAgents || []).filter((agent) => _isAuthoringAssignableAgent(agent));
    }

    function _isAuthoringRoutingSkill(item) {
        const skillName = String(item?.skill_name || item || '').trim().toLowerCase();
        return Boolean(skillName) && skillName !== '*' && skillName !== 'rehearsal';
    }

    function _selectorKindLabel(kind) {
        const normalized = String(kind || '').trim().toLowerCase();
        if (normalized === 'agent') return 'Specific agent';
        if (normalized === 'skill') return 'Required skill';
        if (normalized === 'role') return 'Runtime role tag';
        return _titleCaseWords(normalized);
    }

    function _selectorValueLabel(kind) {
        const normalized = String(kind || '').trim().toLowerCase();
        if (normalized === 'agent') return 'agent';
        if (normalized === 'skill') return 'skill';
        if (normalized === 'role') return 'runtime role tag';
        return normalized || 'value';
    }

    function _selectorManifestKinds() {
        const manifestKinds = Array.isArray(authoringManifest?.selector_kind_options) && authoringManifest.selector_kind_options.length
            ? authoringManifest.selector_kind_options
            : ['agent', 'skill', 'role'];
        const seen = new Set();
        const ordered = [];
        [...PRIMARY_SELECTOR_KINDS, ...manifestKinds].forEach((value) => {
            const normalized = String(value || '').trim().toLowerCase();
            if (!normalized || seen.has(normalized)) return;
            seen.add(normalized);
            ordered.push(normalized);
        });
        return ordered;
    }

    function _selectorAvailableKinds() {
        const available = _selectorManifestKinds();
        if (_currentAuthoringSurface() === 'operator') {
            return available;
        }
        const primary = available.filter((value) => PRIMARY_SELECTOR_KINDS.includes(value));
        return primary.length ? primary : available;
    }

    function _selectorPrimaryKinds() {
        const available = _selectorAvailableKinds();
        const primary = available.filter((value) => PRIMARY_SELECTOR_KINDS.includes(value));
        return primary.length ? primary : available;
    }

    function _selectorAdvancedKinds() {
        const primary = new Set(_selectorPrimaryKinds());
        return _selectorAvailableKinds().filter((value) => !primary.has(value));
    }

    function _isPrimarySelectorKind(kind) {
        return _selectorPrimaryKinds().includes(String(kind || '').trim().toLowerCase());
    }

    function _selectorKindOptions(kinds = _selectorAvailableKinds()) {
        return kinds.map((value) => ({
            value: String(value || ''),
            label: _selectorKindLabel(value),
        }));
    }

    function _nextSelectorValueForKind(kind, currentValue = '') {
        const normalized = String(kind || '').trim().toLowerCase();
        if (!normalized) return '';
        const catalog = _selectorCatalogEntries(normalized);
        const current = String(currentValue || '').trim();
        if (catalog.some((item) => item.value === current)) return current;
        if (catalog.length) return String(catalog[0].value || '');
        return current;
    }

    function _documentSelectorValues(kind) {
        const normalized = String(kind || '').trim().toLowerCase();
        if (!normalized) return [];
        return Array.from(new Set((draft.document?.stages || [])
            .map((stage) => stage?.selector)
            .filter((selector) => String(selector?.kind || '').trim().toLowerCase() === normalized)
            .map((selector) => String(selector?.value || '').trim())
            .filter(Boolean)));
    }

    function _selectorCatalogEntries(kind) {
        const normalized = String(kind || '').trim().toLowerCase();
        const entries = [];
        const seen = new Set();
        const agentSkillCounts = new Map();
        const push = (value, label, meta = '') => {
            const nextValue = String(value || '').trim();
            if (!nextValue || seen.has(nextValue)) return;
            seen.add(nextValue);
            entries.push({
                value: nextValue,
                label: String(label || nextValue).trim() || nextValue,
                meta: String(meta || '').trim(),
            });
        };
        _availableAuthoringAgents().forEach((agent) => {
            (Array.isArray(agent?.routing_skills) ? agent.routing_skills : [])
                .filter((item) => _isAuthoringRoutingSkill(item))
                .forEach((item) => {
                    const skillName = String(item?.skill_name || item || '').trim();
                    if (!skillName) return;
                    agentSkillCounts.set(skillName, Number(agentSkillCounts.get(skillName) || 0) + 1);
                });
        });
        if (normalized === 'agent') {
            _availableAuthoringAgents().forEach((agent) => {
                const slug = String(agent?.slug || '').trim();
                if (!slug) return;
                const meta = [
                    String(agent?.role || '').trim(),
                    String(agent?.connectivity_state || '').trim().toLowerCase() === 'connected'
                        ? ''
                        : String(agent?.connectivity_state || '').trim(),
                ].filter(Boolean).join(' · ');
                push(slug, String(agent?.display_name || _titleCaseWords(slug) || slug), meta);
            });
            _documentSelectorValues('agent').forEach((value) => {
                push(value, value, 'Used in workflow');
            });
        } else if (normalized === 'skill') {
            (availableRoutingSkills || []).filter((item) => _isAuthoringRoutingSkill(item)).forEach((item) => {
                const skillName = String(item?.skill_name || item || '').trim();
                if (!skillName || item?.enabled === false) return;
                const advertisedBy = Array.isArray(item?.advertised_by_agents)
                    ? item.advertised_by_agents.length
                    : Number(agentSkillCounts.get(skillName) || 0);
                push(
                    skillName,
                    _titleCaseWords(skillName),
                    advertisedBy > 0 ? `${advertisedBy} agent${advertisedBy === 1 ? '' : 's'}` : '',
                );
            });
            Array.from(agentSkillCounts.entries()).forEach(([skillName, advertisedBy]) => {
                push(
                    skillName,
                    _titleCaseWords(skillName),
                    advertisedBy > 0 ? `${advertisedBy} agent${advertisedBy === 1 ? '' : 's'}` : '',
                );
            });
            _documentSelectorValues('skill').forEach((value) => {
                push(value, _titleCaseWords(value), 'Used in workflow');
            });
        } else if (normalized === 'role') {
            _availableAuthoringAgents().forEach((agent) => {
                push(agent?.role, _titleCaseWords(agent?.role || ''));
            });
            _documentSelectorValues('role').forEach((value) => {
                push(value, _titleCaseWords(value), 'Used in workflow');
            });
        }
        return entries.sort((left, right) => String(left.label || '').localeCompare(String(right.label || '')));
    }

    function _selectorCatalogEmptyHint(kind) {
        const normalized = String(kind || '').trim().toLowerCase();
        if (normalized === 'agent') {
            return 'No available agents were loaded from the registry. Enter an agent slug only if you need to pin one anyway.';
        }
        if (normalized === 'skill') {
            return 'No available routing skills were loaded from the registry. Enter a skill slug only if you already know it.';
        }
        if (normalized === 'role') {
            return 'No runtime role tags were loaded from the registry. Enter one manually only if you need this advanced path.';
        }
        return 'Enter the exact value you want to match at runtime.';
    }

    function _selectorAgentRecord(selectorValue = '') {
        const normalized = String(selectorValue || '').trim().toLowerCase();
        if (!normalized) return null;
        return _availableAuthoringAgents().find((agent) => {
            const slug = String(agent?.slug || '').trim().toLowerCase();
            const agentId = String(agent?.agent_id || '').trim().toLowerCase();
            return normalized === slug || normalized === agentId;
        }) || null;
    }

    function _selectorAgentSkills(agent) {
        const values = Array.isArray(agent?.routing_skills) ? agent.routing_skills : [];
        return Array.from(new Set(values
            .map((item) => String(item || '').trim())
            .filter((item) => _isAuthoringRoutingSkill({ skill_name: item }))));
    }

    function _selectorAgentControlValue(selectorValue = '') {
        const agent = _selectorAgentRecord(selectorValue);
        return String(agent?.slug || selectorValue || '').trim();
    }

    function _preferredAgentForSkill(skillName = '', preferredAgentId = '') {
        const normalizedSkill = String(skillName || '').trim().toLowerCase();
        const preferred = String(preferredAgentId || '').trim();
        if (!normalizedSkill || !preferred) return '';
        const agent = _selectorAgentRecord(preferred);
        if (!agent) return '';
        const supportsSkill = _selectorAgentSkills(agent)
            .map((item) => String(item || '').trim().toLowerCase())
            .includes(normalizedSkill);
        return supportsSkill ? String(agent.agent_id || '').trim() : '';
    }

    function _currentStageAssignmentMode(stageKey = '', selectorKind = '') {
        const normalizedStageKey = String(stageKey || '').trim();
        if (normalizedStageKey
            && normalizedStageKey === String(stageAssignmentEditor.stageKey || '').trim()
            && String(stageAssignmentEditor.mode || '').trim()) {
            return _selectorModeFromKind(stageAssignmentEditor.mode, 'skill');
        }
        const derived = _selectorModeFromKind(selectorKind, 'skill');
        return derived === 'advanced' ? 'skill' : derived;
    }

    function _setStageAssignmentMode(stageKey = '', mode = '') {
        stageAssignmentEditor = {
            stageKey: String(stageKey || '').trim(),
            mode: _selectorModeFromKind(mode, 'skill'),
        };
        render();
    }

    function _selectorEditorState({
        selectorMode = '',
        selectorKind = '',
        selectorValue = '',
        selectorPreferredAgentId = '',
    } = {}) {
        const normalizedKind = String(selectorKind || '').trim().toLowerCase();
        const requestedMode = _selectorModeFromKind(selectorMode || normalizedKind, 'skill');
        const primaryMode = requestedMode === 'advanced' ? 'skill' : requestedMode;
        if (normalizedKind === 'skill') {
            return {
                mode: primaryMode,
                requiredSkill: String(selectorValue || '').trim(),
                pinnedAgent: _selectorAgentControlValue(selectorPreferredAgentId),
                advancedKind: '',
                advancedValue: '',
            };
        }
        if (normalizedKind === 'agent') {
            return {
                mode: primaryMode,
                requiredSkill: '',
                pinnedAgent: _selectorAgentControlValue(selectorValue),
                advancedKind: '',
                advancedValue: '',
            };
        }
        return {
            mode: primaryMode,
            requiredSkill: '',
            pinnedAgent: '',
            advancedKind: normalizedKind,
            advancedValue: String(selectorValue || '').trim(),
        };
    }

    function _selectorFromEditorFields({
        requiredSkill = '',
        pinnedAgent = '',
        advancedKind = '',
        advancedValue = '',
    } = {}) {
        const nextAdvancedKind = String(advancedKind || '').trim().toLowerCase();
        const nextAdvancedValue = String(advancedValue || '').trim();
        if (nextAdvancedKind && nextAdvancedValue) {
            return _selectorFromFields(nextAdvancedKind, nextAdvancedValue);
        }
        const skillName = String(requiredSkill || '').trim();
        const agentKey = String(pinnedAgent || '').trim();
        if (skillName) {
            const agent = _selectorAgentRecord(agentKey);
            return _selectorFromFields('skill', skillName, String(agent?.agent_id || '').trim());
        }
        if (agentKey) {
            return _selectorFromFields('agent', agentKey);
        }
        return null;
    }

    function _selectorSkillAgentMismatch(requiredSkill = '', pinnedAgent = '') {
        const skillName = String(requiredSkill || '').trim();
        const agent = _selectorAgentRecord(pinnedAgent);
        const agentId = String(agent?.agent_id || '').trim();
        if (!skillName || !agentId) return false;
        return !_preferredAgentForSkill(skillName, agentId);
    }

    function _agentsAdvertisingSkill(selectorValue = '') {
        const normalized = String(selectorValue || '').trim().toLowerCase();
        if (!normalized) return [];
        const seen = new Set();
        const rows = [];
        const push = ({ agentId = '', slug = '', displayName = '', role = '', connectivityState = '' } = {}) => {
            const normalizedSlug = String(slug || '').trim().toLowerCase();
            if (!normalizedSlug || seen.has(normalizedSlug)) return;
            seen.add(normalizedSlug);
            rows.push({
                agent_id: String(agentId || '').trim(),
                slug: normalizedSlug,
                display_name: String(displayName || '').trim() || _titleCaseWords(normalizedSlug) || normalizedSlug,
                role: String(role || '').trim(),
                connectivity_state: String(connectivityState || '').trim(),
            });
        };
        const availableBySlug = new Map(_availableAuthoringAgents().map((agent) => [
            String(agent?.slug || '').trim().toLowerCase(),
            agent,
        ]));
        const advertised = (availableRoutingSkills || []).find((item) =>
            String(item?.skill_name || item || '').trim().toLowerCase() === normalized,
        );
        (Array.isArray(advertised?.advertised_by_agents) ? advertised.advertised_by_agents : []).forEach((slug) => {
            const normalizedSlug = String(slug || '').trim().toLowerCase();
            const agent = availableBySlug.get(normalizedSlug);
            push({
                agentId: String(agent?.agent_id || '').trim(),
                slug: normalizedSlug,
                displayName: String(agent?.display_name || '').trim() || _titleCaseWords(normalizedSlug) || normalizedSlug,
                role: String(agent?.role || '').trim(),
                connectivityState: String(agent?.connectivity_state || '').trim(),
            });
        });
        _availableAuthoringAgents().forEach((agent) => {
            const skills = _selectorAgentSkills(agent).map((item) => item.toLowerCase());
            if (skills.includes(normalized)) {
                push({
                    agentId: String(agent?.agent_id || '').trim(),
                    slug: String(agent?.slug || '').trim(),
                    displayName: String(agent?.display_name || '').trim(),
                    role: String(agent?.role || '').trim(),
                    connectivityState: String(agent?.connectivity_state || '').trim(),
                });
            }
        });
        return rows.sort((left, right) =>
            String(left?.display_name || left?.slug || '').localeCompare(String(right?.display_name || right?.slug || '')));
    }

    function _selectorSkillMatchSection({
        selectorValue = '',
        preferredAgentId = '',
        readOnly = false,
        compact = false,
    } = {}) {
        if (!selectorValue) return null;
        const section = document.createElement('section');
        section.className = 'kit-selector-editor-context';
        section.dataset.key = `selector-skill-match:${String(selectorValue || '').trim().toLowerCase()}`;
        const title = document.createElement('strong');
        title.className = 'kit-selector-editor-context-title';
        title.textContent = 'Matching agents';
        title.dataset.key = `${section.dataset.key}:title`;
        section.appendChild(title);
        const matches = _agentsAdvertisingSkill(selectorValue);
        const preferredAgent = _selectorAgentRecord(preferredAgentId || '');
        const matchLabels = matches.map((candidate) => String(candidate?.display_name || candidate?.slug || '').trim()).filter(Boolean);
        const help = document.createElement('p');
        help.className = 'kit-selector-editor-note';
        help.dataset.key = `${section.dataset.key}:note`;
        help.textContent = readOnly
            ? 'Connected agents that currently advertise this skill.'
            : compact
                ? 'Leave the assignment dynamic unless you want to pin one of the matching agents shown above.'
                : 'Leave the pinned-agent field blank to keep this step dynamic.';
        if (!compact) {
            help.textContent += matchLabels.length
            ? ` Available now: ${matchLabels.join(', ')}.`
            : ' No connected agents currently advertise this skill.';
        }
        if (preferredAgent && !compact) {
            help.textContent += ` Preferred agent: ${String(preferredAgent.display_name || preferredAgent.slug || preferredAgentId || '').trim()}.`;
        }
        section.appendChild(help);
        return section;
    }

    function _selectorAgentSkillsSection({
        selectorValue = '',
        selectedSkill = '',
        readOnly = false,
        compact = false,
    } = {}) {
        const agent = _selectorAgentRecord(selectorValue);
        const section = document.createElement('section');
        section.className = 'kit-selector-editor-context';
        section.dataset.key = `selector-agent-skills:${String(selectorValue || '').trim().toLowerCase()}`;
        const title = document.createElement('strong');
        title.className = 'kit-selector-editor-context-title';
        title.dataset.key = `${section.dataset.key}:title`;
        title.textContent = 'Optional skill requirement';
        section.appendChild(title);
        const note = document.createElement('p');
        note.className = 'kit-selector-editor-note';
        note.dataset.key = `${section.dataset.key}:note`;
        const agentLabel = String(agent?.display_name || agent?.slug || selectorValue || '').trim();
        const skills = _selectorAgentSkills(agent);
        const selectedSkillLabel = String(selectedSkill || '').trim() ? _titleCaseWords(selectedSkill) : '';
        if (agentLabel && selectedSkillLabel) {
            note.textContent = compact
                ? `Pinned to ${agentLabel} and limited to ${selectedSkillLabel}.`
                : `Pinned to ${agentLabel} and limited to ${selectedSkillLabel}.`;
        } else if (agentLabel) {
            note.textContent = compact
                ? `Pinned to ${agentLabel}. Leave the skill blank to keep the assignment agent-only.`
                : `Pinned to ${agentLabel}. Leave the skill blank to keep the assignment agent-only.`;
        } else {
            note.textContent = 'Advertised routing skills for this pinned agent.';
        }
        if (!compact) {
            note.textContent += skills.length
            ? ` Available here: ${skills.map((skillName) => _titleCaseWords(skillName)).join(', ')}.`
            : ' No advertised routing skills are currently available for this agent.';
        } else if (!skills.length) {
            note.textContent += ' No advertised routing skills are currently available for this agent.';
        }
        section.appendChild(note);
        return section;
    }

    function _buildSelectorValueField({
        selectorKind = '',
        selectorValue = '',
        readOnly = false,
        onChange = null,
        onSelectorChange = null,
        label = '',
        catalogEntries = null,
        emptyHint = '',
        placeholderText = '',
        disabled = false,
        allowCustom = true,
        preferPillsWhenCountAtMost = 0,
        emptyChoiceLabel = '',
    } = {}) {
        const normalized = String(selectorKind || '').trim().toLowerCase();
        const block = document.createElement('div');
        block.className = 'kit-selector-editor-field';
        const row = document.createElement('div');
        row.className = 'kit-details-row';
        const valueLabel = document.createElement('label');
        valueLabel.className = 'kit-details-label';
        valueLabel.textContent = label || `Choose ${_selectorValueLabel(normalized)}`;
        row.appendChild(valueLabel);
        const catalog = Array.isArray(catalogEntries) ? catalogEntries : _selectorCatalogEntries(normalized);
        const shouldRenderSelect = Array.isArray(catalogEntries) || normalized === 'agent' || normalized === 'skill';
        const canRenderPills = !readOnly
            && !disabled
            && !allowCustom
            && shouldRenderSelect
            && Number(preferPillsWhenCountAtMost || 0) > 0
            && catalog.length > 0
            && catalog.length <= Number(preferPillsWhenCountAtMost || 0);
        if (canRenderPills) {
            const chips = document.createElement('div');
            chips.className = 'chip-row kit-selector-pill-group';
            chips.dataset.selectorPillGroup = 'true';
            chips.dataset.value = String(selectorValue || '');
            chips.setAttribute('role', 'group');
            chips.setAttribute('aria-label', valueLabel.textContent);
            const entries = [
                {
                    value: '',
                    label: String(emptyChoiceLabel || placeholderText || '(none)').replace(/^\(|\)$/g, ''),
                    meta: '',
                },
                ...catalog,
            ];
            const updateSelection = (nextValue) => {
                chips.dataset.value = String(nextValue || '');
                chips.querySelectorAll('.quickstart-chip').forEach((chip) => {
                    if (!(chip instanceof HTMLButtonElement)) return;
                    const isSelected = String(chip.dataset.value || '') === String(nextValue || '');
                    chip.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
                    chip.classList.toggle('is-selected', isSelected);
                });
            };
            entries.forEach((item) => {
                const chip = document.createElement('button');
                chip.type = 'button';
                chip.className = 'quickstart-chip';
                chip.dataset.value = String(item.value || '');
                chip.textContent = String(item.label || '');
                chip.title = String(item.meta || '').trim()
                    ? `${String(item.label || '')} · ${String(item.meta || '').trim()}`
                    : String(item.label || '');
                chips.appendChild(chip);
                chip.addEventListener('click', () => {
                    const nextValue = String(item.value || '');
                    updateSelection(nextValue);
                    if (typeof onSelectorChange === 'function') {
                        onSelectorChange(normalized, nextValue);
                    } else if (typeof onChange === 'function') {
                        onChange(null, 'selector_value', nextValue);
                    }
                });
            });
            updateSelection(selectorValue);
            row.appendChild(chips);
        } else if (catalog.length || shouldRenderSelect) {
            const select = document.createElement('select');
            select.className = 'kit-details-control';
            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = placeholderText || `(choose ${_selectorValueLabel(normalized)})`;
            select.appendChild(placeholder);
            catalog.forEach((item) => {
                const option = document.createElement('option');
                option.value = String(item.value || '');
                option.textContent = item.meta ? `${item.label} · ${item.meta}` : item.label;
                if (String(selectorValue || '') === String(item.value || '')) option.selected = true;
                select.appendChild(option);
            });
            if (allowCustom && selectorValue && !catalog.some((item) => item.value === String(selectorValue || ''))) {
                const custom = document.createElement('option');
                custom.value = String(selectorValue || '');
                custom.textContent = `Custom · ${String(selectorValue || '')}`;
                custom.selected = true;
                select.appendChild(custom);
            }
            select.disabled = Boolean(readOnly || disabled);
            if (!readOnly) {
                const commitSelect = () => {
                    if (typeof onSelectorChange === 'function') {
                        onSelectorChange(normalized, select.value);
                    } else if (typeof onChange === 'function') {
                        onChange(null, 'selector_value', select.value);
                    }
                };
                if (typeof onSelectorChange === 'function') {
                    select.addEventListener('input', commitSelect);
                    select.addEventListener('change', commitSelect);
                } else if (typeof onChange === 'function') {
                    select.addEventListener('input', commitSelect);
                    select.addEventListener('change', commitSelect);
                }
            }
            select.setAttribute('aria-label', valueLabel.textContent);
            row.appendChild(select);
            if (!catalog.length) {
                const hint = document.createElement('p');
                hint.className = 'kit-selector-editor-note';
                hint.textContent = emptyHint || _selectorCatalogEmptyHint(normalized);
                block.appendChild(hint);
            }
        } else {
            const input = document.createElement('input');
            input.type = 'text';
            input.className = 'kit-details-control';
            input.placeholder = placeholderText || Kit.dict.label('protocol.participant.selector_value.placeholder', 'e.g. legal-review, approver, m1');
            input.value = String(selectorValue || '');
            input.readOnly = Boolean(readOnly || disabled);
            if (!readOnly) {
                if (typeof onSelectorChange === 'function') {
                    const commit = () => onSelectorChange(normalized, input.value);
                    input.addEventListener('change', commit);
                    input.addEventListener('blur', commit);
                } else if (typeof onChange === 'function') {
                    const commit = () => onChange(null, 'selector_value', input.value);
                    input.addEventListener('change', commit);
                    input.addEventListener('blur', commit);
                }
            }
            input.setAttribute('aria-label', valueLabel.textContent);
            row.appendChild(input);
            const hint = document.createElement('p');
            hint.className = 'kit-selector-editor-note';
            hint.textContent = emptyHint || _selectorCatalogEmptyHint(normalized);
            block.appendChild(hint);
        }
        block.prepend(row);
        return { element: block, catalog, presentation: canRenderPills ? 'pills' : (catalog.length || shouldRenderSelect ? 'select' : 'input') };
    }

    function _buildSelectorManualOverrideField({
        selectorValue = '',
        readOnly = false,
        onChange = null,
        label = 'Custom value',
    } = {}) {
        const row = document.createElement('div');
        row.className = 'kit-details-row';
        const overrideLabel = document.createElement('label');
        overrideLabel.className = 'kit-details-label';
        overrideLabel.textContent = label;
        row.appendChild(overrideLabel);
        const overrideInput = document.createElement('input');
        overrideInput.type = 'text';
        overrideInput.className = 'kit-details-control';
        overrideInput.placeholder = Kit.dict.label('protocol.participant.selector_value.placeholder', 'e.g. legal-review, approver, m1');
        overrideInput.value = String(selectorValue || '');
        overrideInput.readOnly = Boolean(readOnly);
        if (typeof onChange === 'function' && !readOnly) {
            const commit = () => onChange(null, 'selector_value', overrideInput.value);
            overrideInput.addEventListener('change', commit);
            overrideInput.addEventListener('blur', commit);
        }
        overrideInput.setAttribute('aria-label', overrideLabel.textContent);
        row.appendChild(overrideInput);
        return row;
    }

    function _selectorEditor({
        stageKey = '',
        selectorMode = '',
        selectorKind = '',
        selectorValue = '',
        selectorPreferredAgentId = '',
        readOnly = false,
        onChange = null,
        onSelectorChange = null,
    } = {}) {
        const wrap = document.createElement('section');
        wrap.className = 'kit-selector-editor';
        const operatorSurface = _currentAuthoringSurface() === 'operator';
        const emit = (key, value) => {
            if (typeof onChange === 'function') onChange(null, key, value);
        };
        const emitMode = (mode) => {
            const nextMode = _selectorModeFromKind(mode, 'skill');
            if (stageKey) {
                _setStageAssignmentMode(stageKey, nextMode);
            } else {
                emit('selector_mode', nextMode);
            }
        };
        const emitSelector = (kind, value, preferredAgentId = '') => {
            if (typeof onSelectorChange === 'function') {
                onSelectorChange(String(kind || ''), String(value || ''), String(preferredAgentId || ''));
                return;
            }
            emit('selector_kind', kind);
            emit('selector_value', value);
            emit('selector_preferred_agent_id', preferredAgentId);
        };

        const heading = document.createElement('div');
        heading.className = 'kit-selector-editor-head';
        const copy = document.createElement('p');
        copy.className = 'kit-stage-routing-copy';
        copy.textContent = 'Choose how this step resolves at runtime. The second control, when shown, is optional refinement rather than a second required field.';
        heading.appendChild(copy);
        wrap.appendChild(heading);

        const {
            mode,
            requiredSkill,
            pinnedAgent,
            advancedKind,
            advancedValue,
        } = _selectorEditorState({
            selectorMode,
            selectorKind,
            selectorValue,
            selectorPreferredAgentId,
        });
        wrap.dataset.key = [
            'selector-editor',
            String(stageKey || 'new'),
            String(mode || ''),
            String(requiredSkill || '').trim().toLowerCase(),
            String(pinnedAgent || '').trim().toLowerCase(),
            String(advancedKind || '').trim().toLowerCase(),
            String(advancedValue || '').trim().toLowerCase(),
        ].join(':');
        const advancedKinds = _selectorAdvancedKinds();
        const activeAgent = _selectorAgentRecord(pinnedAgent);
        const activeAgentId = String(activeAgent?.agent_id || '').trim();
        const activeAgentLabel = String(activeAgent?.display_name || activeAgent?.slug || pinnedAgent || '').trim();
        const operatorManagedSelector = !operatorSurface && Boolean(advancedKind && advancedValue);
        const requiredSkillMatches = _agentsAdvertisingSkill(requiredSkill).map((candidate) => ({
            value: String(candidate?.slug || '').trim(),
            label: String(candidate?.display_name || candidate?.slug || '').trim(),
            meta: String(candidate?.role || '').trim(),
        })).filter((item) => item.value);
        const agentSkillEntries = _selectorAgentSkills(activeAgent).map((skillName) => ({
            value: String(skillName || '').trim(),
            label: _titleCaseWords(skillName),
            meta: '',
        }));
        const emitAssignment = ({
            nextSkill = requiredSkill,
            nextAgent = pinnedAgent,
            nextAdvancedKind = '',
            nextAdvancedValue = '',
        } = {}) => {
            const selector = _selectorFromEditorFields({
                requiredSkill: nextSkill,
                pinnedAgent: nextAgent,
                advancedKind: nextAdvancedKind,
                advancedValue: nextAdvancedValue,
            });
            emitSelector(
                String(selector?.kind || ''),
                String(selector?.value || ''),
                String(selector?.preferred_agent_id || ''),
            );
        };
        if (operatorManagedSelector) {
            const note = document.createElement('p');
            note.className = 'kit-selector-editor-note';
            note.textContent = 'This step uses an operator-managed assignment. Normal authoring keeps it intact but does not expose the internal selector controls.';
            wrap.appendChild(note);
            const summary = document.createElement('p');
            summary.className = 'kit-selector-editor-note';
            summary.textContent = `Current assignment: ${_selectorSummary(
                { kind: advancedKind, value: advancedValue },
                { empty: 'Operator-managed runtime selector' },
            )}.`;
            wrap.appendChild(summary);
            return wrap;
        }
        const modeControl = UI.createSegmentedControl([
            { value: 'skill', label: 'By skill' },
            { value: 'agent', label: 'Specific agent' },
        ], (nextMode) => {
            emitMode(nextMode);
            if (nextMode === 'skill' && advancedKind && advancedValue) {
                emitAssignment({
                    nextSkill: '',
                    nextAgent: '',
                    nextAdvancedKind: '',
                    nextAdvancedValue: '',
                });
            } else if (nextMode === 'agent' && advancedKind && advancedValue) {
                emitAssignment({
                    nextSkill: '',
                    nextAgent: '',
                    nextAdvancedKind: '',
                    nextAdvancedValue: '',
                });
            }
        }, { label: 'Assignment mode', value: mode });
        modeControl.element.dataset.key = 'selector-assignment-mode';
        wrap.appendChild(modeControl.element);

        if (advancedKind && advancedValue) {
            const note = document.createElement('p');
            note.className = 'kit-selector-editor-note';
            note.textContent = 'This step currently uses a custom runtime selector. Choosing one of the primary modes below will replace it.';
            wrap.appendChild(note);
        }

        let skillField = null;
        let agentField = null;
        if (mode === 'skill') {
            skillField = _buildSelectorValueField({
                selectorKind: 'skill',
                selectorValue: requiredSkill,
                readOnly,
                onSelectorChange: (_kind, nextValue) => emitAssignment({
                    nextSkill: String(nextValue || ''),
                    nextAgent: requiredSkillMatches.some((item) => item.value === pinnedAgent) ? pinnedAgent : '',
                }),
                label: 'Required skill',
                allowCustom: false,
            });
            skillField.element.dataset.key = `selector-field:${String(stageKey || 'new')}:skill:required`;
            wrap.appendChild(skillField.element);

            agentField = _buildSelectorValueField({
                selectorKind: 'agent',
                selectorValue: pinnedAgent,
                readOnly,
                onSelectorChange: (_kind, nextValue) => emitAssignment({
                    nextSkill: requiredSkill,
                    nextAgent: String(nextValue || ''),
                }),
                label: 'Pin matching agent (optional)',
                catalogEntries: requiredSkillMatches,
                emptyHint: requiredSkill
                    ? 'No connected agents currently advertise this skill. Leave the agent blank to keep the step dynamic.'
                    : 'Choose a required skill first if you want to pin one matching agent.',
                placeholderText: requiredSkill ? '(leave dynamic)' : '(choose a skill first)',
                disabled: !requiredSkill,
                allowCustom: false,
                preferPillsWhenCountAtMost: 5,
                emptyChoiceLabel: 'Dynamic',
            });
            agentField.element.dataset.key = [
                'selector-field',
                String(stageKey || 'new'),
                'skill',
                'agent-refinement',
                String(requiredSkill || '').trim().toLowerCase(),
            ].join(':');
            wrap.appendChild(agentField.element);
        } else {
            agentField = _buildSelectorValueField({
                selectorKind: 'agent',
                selectorValue: pinnedAgent,
                readOnly,
                onSelectorChange: (_kind, nextValue) => emitAssignment({
                    nextSkill: pinnedAgent === String(nextValue || '') ? requiredSkill : '',
                    nextAgent: String(nextValue || ''),
                }),
                label: 'Agent',
                allowCustom: false,
            });
            agentField.element.dataset.key = `selector-field:${String(stageKey || 'new')}:agent:pinned`;
            wrap.appendChild(agentField.element);

            skillField = _buildSelectorValueField({
                selectorKind: 'skill',
                selectorValue: requiredSkill,
                readOnly,
                onSelectorChange: (_kind, nextValue) => emitAssignment({
                    nextSkill: String(nextValue || ''),
                    nextAgent: pinnedAgent,
                }),
                label: 'Limit to one of this agent\'s skills (optional)',
                catalogEntries: agentSkillEntries,
                emptyHint: pinnedAgent
                    ? 'This agent does not currently advertise any routing skills. Leave the skill blank to keep the assignment agent-only.'
                    : 'Choose an agent first if you want to constrain it to one of its skills.',
                placeholderText: pinnedAgent ? '(leave agent-only)' : '(choose an agent first)',
                disabled: !pinnedAgent,
                allowCustom: false,
                preferPillsWhenCountAtMost: 5,
                emptyChoiceLabel: 'Agent only',
            });
            skillField.element.dataset.key = [
                'selector-field',
                String(stageKey || 'new'),
                'agent',
                'skill-refinement',
                String(pinnedAgent || '').trim().toLowerCase(),
            ].join(':');
            wrap.appendChild(skillField.element);
        }

        if (requiredSkill || pinnedAgent) {
            const summary = document.createElement('p');
            summary.className = 'kit-selector-editor-note';
            if (requiredSkill && activeAgentLabel) {
                summary.textContent = `Current assignment: requires ${_titleCaseWords(requiredSkill)} and pins the step to ${activeAgentLabel}.`;
            } else if (requiredSkill) {
                summary.textContent = `Current assignment: requires ${_titleCaseWords(requiredSkill)} and stays dynamic across matching agents.`;
            } else {
                summary.textContent = `Current assignment: pins the step to ${activeAgentLabel || 'the selected agent'}.`;
            }
            wrap.appendChild(summary);
        }

        if (_selectorSkillAgentMismatch(requiredSkill, pinnedAgent)) {
            const warning = document.createElement('p');
            warning.className = 'kit-selector-editor-note';
            warning.textContent = `Pinned agent ${activeAgentLabel || 'the selected agent'} does not currently advertise ${_titleCaseWords(requiredSkill)}.`;
            wrap.appendChild(warning);
        }

        if (mode === 'skill' && requiredSkill) {
            const matchesSection = _selectorSkillMatchSection({
                selectorValue: requiredSkill,
                preferredAgentId: activeAgentId,
                readOnly,
                compact: agentField.presentation === 'pills',
            });
            if (matchesSection) wrap.appendChild(matchesSection);
        }
        if (mode === 'agent' && pinnedAgent) {
            const skillsSection = _selectorAgentSkillsSection({
                selectorValue: pinnedAgent,
                selectedSkill: requiredSkill,
                readOnly,
                compact: skillField.presentation === 'pills',
            });
            if (skillsSection) wrap.appendChild(skillsSection);
        }

        if (operatorSurface && advancedKinds.length) {
            const advanced = document.createElement('details');
            advanced.className = 'kit-selector-editor-override';
            advanced.open = Boolean(advancedKind && advancedValue);
            const advancedSummary = document.createElement('summary');
            advancedSummary.className = 'kit-stage-editor-summary';
            const advancedTitle = document.createElement('h4');
            advancedTitle.className = 'kit-stage-editor-title';
            advancedTitle.textContent = Kit.dict.label('protocol.participant.selector_advanced.label', 'Custom runtime selector');
            advancedSummary.appendChild(advancedTitle);
            advanced.appendChild(advancedSummary);
            const advancedBody = document.createElement('div');
            advancedBody.className = 'kit-selector-editor-override-body';
            const advancedNote = document.createElement('p');
            advancedNote.className = 'kit-selector-editor-note';
            advancedNote.textContent = 'Use this only for a runtime role tag or another selector value that the normal skill and agent modes cannot express.';
            advancedBody.appendChild(advancedNote);

            const advancedKindRow = document.createElement('div');
            advancedKindRow.className = 'kit-details-row';
            const advancedKindLabel = document.createElement('label');
            advancedKindLabel.className = 'kit-details-label';
            advancedKindLabel.textContent = Kit.dict.label('protocol.participant.selector_advanced.strategy', 'Custom selector type');
            advancedKindRow.appendChild(advancedKindLabel);
            const advancedKindControl = document.createElement('select');
            advancedKindControl.className = 'kit-details-control';
            const defaultOption = document.createElement('option');
            defaultOption.value = '';
            defaultOption.textContent = '(none)';
            advancedKindControl.appendChild(defaultOption);
            _selectorKindOptions(advancedKinds).forEach((item) => {
                const option = document.createElement('option');
                option.value = String(item.value || '');
                option.textContent = String(item.label || item.value || '');
                if (String(advancedKind || '') === String(item.value || '')) option.selected = true;
                advancedKindControl.appendChild(option);
            });
            advancedKindControl.disabled = Boolean(readOnly);
            advancedKindControl.setAttribute('aria-label', advancedKindLabel.textContent);
            if ((typeof onChange === 'function' || typeof onSelectorChange === 'function') && !readOnly) {
                advancedKindControl.addEventListener('change', () => {
                    const nextKind = String(advancedKindControl.value || '').trim();
                    if (!nextKind) {
                        emitAssignment({
                            nextSkill: requiredSkill,
                            nextAgent: pinnedAgent,
                        });
                        return;
                    }
                    emitAssignment({
                        nextSkill: '',
                        nextAgent: '',
                        nextAdvancedKind: nextKind,
                        nextAdvancedValue: _nextSelectorValueForKind(nextKind, nextKind === advancedKind ? advancedValue : ''),
                    });
                });
            }
            advancedKindRow.appendChild(advancedKindControl);
            advancedBody.appendChild(advancedKindRow);

            if (advancedKind) {
                const { element, catalog } = _buildSelectorValueField({
                    selectorKind: advancedKind,
                    selectorValue: advancedValue,
                    readOnly,
                    onChange,
                    onSelectorChange: (nextKind, nextValue) => emitAssignment({
                        nextSkill: '',
                        nextAgent: '',
                        nextAdvancedKind: nextKind,
                        nextAdvancedValue: nextValue,
                    }),
                    label: `Choose ${_selectorValueLabel(advancedKind)}`,
                });
                advancedBody.appendChild(element);
                if (catalog.length) {
                    advancedBody.appendChild(_buildSelectorManualOverrideField({
                        selectorValue: advancedValue,
                        readOnly,
                        onChange: typeof onSelectorChange === 'function'
                            ? (_target, _key, nextValue) => emitAssignment({
                                nextSkill: '',
                                nextAgent: '',
                                nextAdvancedKind: advancedKind,
                                nextAdvancedValue: nextValue,
                            })
                            : onChange,
                        label: Kit.dict.label('protocol.participant.selector_override.label', 'Custom value'),
                    }));
                }
            }
            advanced.appendChild(advancedBody);
            wrap.appendChild(advanced);
        }

        return wrap;
    }

    function _participantEditorShell({
        target,
        readOnly = false,
        onCommit = null,
        createAction = null,
        cancelAction = null,
    } = {}) {
        const shell = document.createElement('div');
        shell.className = 'kit-stage-editor';
        const basics = Kit.detailsPanel({
            target,
            surfaceKey: 'protocol.participant',
            onCommit,
            schema: [
                { key: 'display_name', kind: 'text', required: true, readOnly },
                { key: 'participant_key', kind: 'text', readOnly },
            ],
            actions: createAction ? [
                { label: 'Create role', tone: 'btn-primary', onClick: createAction },
                ...(cancelAction ? [{ label: 'Cancel', onClick: cancelAction }] : []),
            ] : [],
        });
        shell.appendChild(_stageEditorSection('Role', basics));
        const instructions = Kit.detailsPanel({
            target,
            surfaceKey: 'protocol.participant',
            onCommit,
            schema: [
                { key: 'instructions', kind: 'textarea', rows: 4, readOnly },
            ],
            actions: !createAction && cancelAction ? [{ label: 'Cancel', onClick: cancelAction }] : [],
        });
        shell.appendChild(_stageEditorSection('Shared instructions', instructions, { wide: true, collapsible: !createAction, open: Boolean(String(target?.instructions || '').trim()) }));
        return shell;
    }

    function _routeScopeLabel(stageKey, projection, currentSegmentId = '') {
        const segmentId = String(projection?.stageToSegment?.get(String(stageKey || '')) || '');
        if (!segmentId) return 'Workflow';
        if (segmentId === String(currentSegmentId || '')) return 'This section';
        const segment = projection?.segmentsById?.get(segmentId);
        return String(segment?.label || 'Another section');
    }

    function _routeTargetOptions(sourceStageKey, projection) {
        const currentSegmentId = projection.stageToSegment.get(String(sourceStageKey || '')) || '';
        const options = [
            { value: '', label: '(choose next step or finish outcome)' },
            ...(draft.document.stages || []).map((stage) => ({
                value: String(stage.stage_key || ''),
                label: `${_routeScopeLabel(stage.stage_key, projection, currentSegmentId)} · ${String(stage.display_name || stage.stage_key || '')}`,
            })),
            ...PROTOCOL_TERMINAL_TARGETS.map((item) => ({
                value: item.key,
                label: `Finish outcome · ${item.label}`,
            })),
        ];
        return options;
    }

    function _routeEditorPanel({
        target,
        sourceStage,
        projection,
        readOnly = false,
        onCommit = null,
        createAction = null,
        insertAction = null,
        deleteAction = null,
        cancelAction = null,
    } = {}) {
        return Kit.detailsPanel({
            target,
            surfaceKey: 'protocol.transition',
            onCommit,
            schema: [
                { key: 'source_stage', kind: 'text', label: 'From step', help: 'This branch leaves the selected step.', readOnly: true },
                { key: 'decision', kind: 'select', options: _decisionOptionsForStage(sourceStage, target?.decision), disabled: readOnly, label: 'When', help: 'Name the outcome or decision that triggers this branch.' },
                { key: 'target_key', kind: 'select', options: _routeTargetOptions(sourceStage?.stage_key || target?.source_stage_key || '', projection), disabled: readOnly, label: 'Go to', help: 'Choose the next step or a finish outcome for this branch.' },
            ],
            actions: [
                ...(createAction ? [{ label: 'Save branch', tone: 'btn-primary', onClick: createAction }] : []),
                ...(insertAction ? [{ label: 'Insert step here', onClick: insertAction }] : []),
                ...(deleteAction ? [{ label: Kit.dict.label('protocol.transition.delete'), tone: 'btn-danger', onClick: deleteAction }] : []),
                ...(cancelAction ? [{ label: 'Cancel', onClick: cancelAction }] : []),
            ],
        });
    }

    // -------------------------------------------------------------------
    // Rendering
    // -------------------------------------------------------------------
    function _lifecycleHeaderEl() {
        const record = {
            display_name: draft.display_name,
            slug: draft.slug,
            lifecycle_state: String(currentProtocol?.protocol?.lifecycle_state || 'draft'),
        };
        const lifecycleState = String(currentProtocol?.protocol?.lifecycle_state || '');
        const progress = _workflowProgress();
        const hasPublishedVersion = Boolean(currentProtocol?.protocol?.current_version_id)
            || (Array.isArray(currentProtocol?.versions)
                && currentProtocol.versions.some((v) => String(v.lifecycle_state || '') === 'published'));
        const permissions = {
            canValidate: Boolean(currentProtocolId) && progress.stageCount > 0 && saveState.state !== 'conflict',
            canPublish: Boolean(currentProtocolId) && progress.stageCount > 0 && saveState.state !== 'conflict',
            canArchive: Boolean(currentProtocolId) && hasPublishedVersion && lifecycleState !== 'archived' && saveState.state !== 'conflict',
            canRehearse: Boolean(currentProtocolId) && hasPublishedVersion && lifecycleState !== 'archived' && saveState.state !== 'conflict',
            canDiscard: Boolean(currentProtocolId) && !hasPublishedVersion && saveState.state !== 'conflict',
        };
        return Kit.lifecycleHeader({
            surfaceKey: 'protocol',
            record,
            saveState,
            permissions,
            compact: true,
            primaryActions: ['validate', 'publish', 'rehearse'],
            secondaryActions: ['archive', 'discard'],
            utilityActions: [{
                label: 'Protocol settings',
                onClick: () => {
                    selection = { sectionKey: 'protocol', nodeKey: '' };
                    render();
                },
            }],
            actions: {
                validate: () => void _validateNow().catch((err) => UI.reportError('Validation failed', err)),
                publish: () => void _publishNow().catch((err) => UI.reportError('Publish failed', err)),
                rehearse: () => void _startRehearsal().catch((err) => UI.reportError('Rehearsal failed to start', err)),
                archive: () => UI.showConfirm(
                    'Archive protocol',
                    'Archive this protocol definition? Published versions remain immutable, but the definition will no longer be offered for new runs.',
                    async () => { await _archiveNow(); },
                ),
                discard: () => UI.showConfirm(
                    'Delete protocol draft?',
                    'This permanently deletes the unpublished draft. Published protocols must be archived instead.',
                    async () => { await _discardNow(); },
                ),
            },
            onTitleCommit: (value) => _commitOverview(null, 'display_name', value),
            onSlugCommit: (value) => _commitOverview(null, 'slug', value),
        });
    }

    // Refs maintained across renders so we can sync inputs without blurring
    // the user's caret.
    let _lifecycleHeaderRef = null;
    function _syncLifecycleChip() {
        if (_lifecycleHeaderRef && typeof _lifecycleHeaderRef.updateSaveState === 'function') {
            _lifecycleHeaderRef.updateSaveState(saveState);
        }
    }
    function _syncLifecycleHeaderInputs() {
        if (_lifecycleHeaderRef && typeof _lifecycleHeaderRef.syncRecord === 'function') {
            _lifecycleHeaderRef.syncRecord({
                display_name: draft.display_name,
                slug: draft.slug,
                lifecycle_state: String(currentProtocol?.protocol?.lifecycle_state || 'draft'),
            });
        }
    }

    function _stageNodeSublabel(stage) {
        const reads = Number((stage.inputs || []).length || 0);
        const writes = Number((stage.outputs || []).length || 0);
        const parts = [];
        const assignment = _stageAssignmentSummary(stage, { empty: '' });
        if (assignment) parts.push(assignment);
        if (reads) parts.push(`Reads ${reads}`);
        if (writes) parts.push(`Writes ${writes}`);
        if (!parts.length && String(stage.instructions || '').trim()) parts.push('Instructions ready');
        return parts.join(' · ');
    }

    function _stageNodeBadges(stage, viewKind = 'detail') {
        const stageKind = String(stage?.stage_kind || 'work');
        if (viewKind === 'topology' && stageKind === 'work') {
            return [];
        }
        return [{
            tone: stageKind,
            label: Kit.dict.label(`protocol.stage.kind.${stageKind}`),
        }];
    }

    function _showEdgeLabel(edge, sourceStage, viewKind = 'detail') {
        if (viewKind !== 'topology') {
            return false;
        }
        const decision = String(edge?.decision || '').trim().toLowerCase();
        const transitionCount = Object.keys(sourceStage?.transitions || {}).length;
        return transitionCount > 1 || decision !== 'completed';
    }

    function _firstRunState(progress) {
        const stageCount = progress.stageCount;
        const artifactCount = progress.artifactCount;
        return editorMode.kind === 'idle' && !stageCount
            ? {
                active: true,
                title: Kit.dict.label('protocol.canvas.empty.title'),
                body: 'Start with the first step, then define any shared files, datasets, code, or reports that later steps should read or produce.',
                steps: [
                    {
                        badge: '1',
                        text: 'Add the first step and create its owner role inline if you need a new one.',
                        state: 'active',
                    },
                    {
                        badge: '2',
                        text: 'Define shared workflow files and outputs once, then attach them to step inputs and outputs.',
                        state: artifactCount ? 'complete' : '',
                    },
                    {
                        badge: '3',
                        text: 'Open the workflow map only when you want route context or a spatial review of the whole flow.',
                    },
                ],
                note: 'For assistant-building flows, open the skills catalog to publish or install a capability first, then come back here and assign steps by skill.',
                actions: [
                    { label: Kit.dict.label('protocol.stages.add'), onClick: () => _startStageInsert() },
                    { label: 'Define shared files', tone: '', onClick: () => _openArtifactCatalog() },
                    { label: 'Open skills catalog', tone: '', onClick: () => Router.navigate('/ui/skills') },
                    { label: Kit.dict.label('protocol.catalog.gallery'), tone: '', onClick: () => Router.navigate('/ui/gallery') },
                ],
            }
            : null;
    }

    function _selectionSegmentId(projection) {
        if (selection.sectionKey === 'segments' && projection.segmentsById.has(String(selection.nodeKey || ''))) {
            return String(selection.nodeKey || '');
        }
        if (selection.sectionKey === 'stages') {
            return String(projection.stageToSegment.get(String(selection.nodeKey || '')) || '');
        }
        if (selection.sectionKey === 'transitions') {
            return String(projection.stageToSegment.get(String(selection.nodeKey || '').split('::')[0] || '') || '');
        }
        if (selection.sectionKey === 'participants') {
            return String(projection.segments.find((segment) =>
                segment.participantKeys.includes(String(selection.nodeKey || '')),
            )?.id || '');
        }
        if (selection.sectionKey === 'artifacts') {
            const artifactKey = String(selection.nodeKey || '');
            const ownerStage = (draft.document.stages || []).find((stage) =>
                (stage.inputs || []).includes(artifactKey) || (stage.outputs || []).includes(artifactKey));
            return String(projection.stageToSegment.get(String(ownerStage?.stage_key || '')) || '');
        }
        return '';
    }

    function _segmentStageDisplayLabel(segment, stage) {
        const stageLabel = String(stage?.display_name || stage?.stage_key || '').trim();
        return stageLabel || 'Untitled step';
    }

    function _workflowInsertHint() {
        if (editorMode.kind !== 'insert-stage' || !editorMode.sourceStageKey || !editorMode.decision) return '';
        const sourceStage = (draft.document.stages || []).find((item) => String(item.stage_key || '') === String(editorMode.sourceStageKey || ''));
        if (!sourceStage) return '';
        const targetKey = String(sourceStage.transitions?.[String(editorMode.decision || '').trim().toLowerCase()] || '').trim();
        if (!targetKey) return '';
        const decisionLabel = _protocolDecisionLabel(editorMode.decision);
        const sourceLabel = String(sourceStage.display_name || sourceStage.stage_key || 'Selected step');
        const targetLabel = _transitionTargetLabel(targetKey, draft.document) || 'the current destination';
        return `This step will be inserted on ${decisionLabel} from ${sourceLabel} before ${targetLabel}.`;
    }

    function _focusStageKey(projection, segment) {
        if (selection.sectionKey === 'stages') {
            return String(selection.nodeKey || '');
        }
        if (selection.sectionKey === 'transitions') {
            return String(selection.nodeKey || '').split('::')[0] || '';
        }
        return String(segment?.stageKeys?.[0] || '');
    }

    function _segmentFinishLabels(segment) {
        return Array.from(new Set((segment?.outgoingEdges || [])
            .filter((edge) => edge.targetKind === 'terminal')
            .map((edge) => String(_transitionTargetLabel(edge.targetKey, draft.document) || ''))
            .filter(Boolean)));
    }

    function _workflowToolbarActions(progress, projection) {
        const canMutate = saveState.state !== 'conflict' && editorMode.kind !== 'rehearse';
        const selectedStage = _selectionStage(draft.document);
        const selectedTransition = _selectionTransition(draft.document);
        const activeSegmentId = _selectionSegmentId(projection);
        const activeSegment = projection.segmentsById.get(String(activeSegmentId || '')) || null;
        let selectedStageAnchor = null;
        let insertLabel = 'Insert step here';
        if (selectedStage) {
            let anchorStage = selectedStage;
            if (
                activeSegment
                && Array.isArray(activeSegment.stageKeys)
                && activeSegment.stageKeys.includes(String(selectedStage.stage_key || ''))
                && String(activeSegment.endStageKey || '') !== String(selectedStage.stage_key || '')
            ) {
                anchorStage = (draft.document.stages || []).find((item) =>
                    String(item.stage_key || '') === String(activeSegment.endStageKey || ''),
                ) || selectedStage;
                insertLabel = `Insert after ${String(activeSegment.label || 'section')}`;
            }
            selectedStageAnchor = _insertAnchorForStage(anchorStage, projection);
        } else if (selection.sectionKey === 'segments' && activeSegment?.endStageKey) {
            const anchorStage = (draft.document.stages || []).find((item) =>
                String(item.stage_key || '') === String(activeSegment.endStageKey || ''),
            ) || null;
            selectedStageAnchor = anchorStage ? _insertAnchorForStage(anchorStage, projection) : null;
            insertLabel = `Insert after ${String(activeSegment.label || 'section')}`;
        }
        const insertAnchor = selectedTransition
            ? {
                sourceStageKey: selectedTransition.from_stage_key,
                decision: selectedTransition.decision,
            }
            : selectedStageAnchor;
        const mapVisible = _workflowMapVisible();
        const actions = [
            {
                label: selection.sectionKey === 'protocol' ? 'Back to stages' : 'Protocol settings',
                tone: 'btn-small',
                onClick: () => {
                    selection = selection.sectionKey === 'protocol'
                        ? { sectionKey: 'overview', nodeKey: '' }
                        : { sectionKey: 'protocol', nodeKey: '' };
                    render();
                },
            },
            {
                label: mapVisible ? 'Hide workflow map' : 'Show workflow map',
                tone: 'btn-small',
                onClick: () => _setWorkflowMapMode(mapVisible ? 'hidden' : 'visible'),
            },
            ...(rehearsal.runId ? [{
                label: editorMode.kind === 'rehearse' ? 'Back to authoring' : 'View rehearsal',
                tone: 'btn-small',
                onClick: () => _setEditorMode({ kind: editorMode.kind === 'rehearse' ? 'idle' : 'rehearse' }),
            }] : []),
        ];
        if (!selectedStage && !selectedTransition && !activeSegmentId) {
            actions.splice(2, 0, {
                label: progress.stageCount ? Kit.dict.label('protocol.stages.add') : 'Add first step',
                tone: 'btn-small',
                onClick: () => _startStageInsert(insertAnchor || {}),
                disabled: !canMutate,
            });
        }
        return actions;
    }

    function _sceneOutline(projection, nodeStates, activeSegmentId = '') {
        return projection.segments.map((segment) => ({
            id: String(segment.id || ''),
            kind: 'segment',
            label: String(segment.label || 'Untitled section'),
            meta: '',
            expanded: String(segment.id || '') === String(activeSegmentId || ''),
            items: _segmentStageList(segment).map((stage) => ({
                id: String(stage.stage_key || ''),
                kind: 'stage',
                label: _segmentStageDisplayLabel(segment, stage),
                meta: String(nodeStates?.[String(stage.stage_key || '')] || ''),
            })),
        }));
    }

    function _workflowStoryScene(projection, { compact = false } = {}) {
        const orderedSegments = (Array.isArray(projection.segmentOrder) && projection.segmentOrder.length
            ? projection.segmentOrder.map((segmentId) => projection.segmentsById.get(String(segmentId || '')))
            : projection.segments)
            .filter(Boolean);
        const nodes = orderedSegments.map((segment) => ({
            id: String(segment.id || ''),
            kind: 'segment',
            label: String(segment.label || 'Untitled section'),
            meta: '',
            secondary: '',
            width: compact ? 144 : 168,
            height: compact ? 44 : 48,
        }));
        const edges = orderedSegments.slice(1).map((segment, index) => ({
            id: `story:${String(orderedSegments[index]?.id || '')}::${String(segment.id || '')}`,
            from: String(orderedSegments[index]?.id || ''),
            to: String(segment.id || ''),
            label: '',
            primary: true,
        }));
        return {
            title: 'Workflow stages',
            subtitle: 'Build the workflow from the stage stack. Open the map only when you want spatial context.',
            hint: editorMode.kind === 'rehearse' ? 'Rehearsal is active. Workflow state is annotated on the same canvas while authoring is paused.' : '',
            outlineTitle: 'Workflow outline',
            direction: 'DOWN',
            fitPadding: compact ? 14 : 40,
            nodeSpacing: compact ? 14 : 24,
            layerSpacing: compact ? 22 : 54,
            emptyHint: 'Add the first step to start shaping the workflow.',
            graph: { nodes, edges },
            focusIds: nodes.map((node) => node.id),
        };
    }

    function _focusedWorkflowScene(projection, nodeStates, activeSegment, { compact = false } = {}) {
        const focusStageKey = _focusStageKey(projection, activeSegment);
        const doc = draft.document;
        const nodes = [];
        const edges = [];
        const nodeIds = new Set();
        const stageKeys = new Set((activeSegment?.stageKeys || []).map((item) => String(item || '')));

        function pushNode(node) {
            if (!node || nodeIds.has(String(node.id || ''))) return;
            nodeIds.add(String(node.id || ''));
            nodes.push(node);
        }

        function pushExternalSegment(segmentId, labelOverride = '') {
            const target = projection.segmentsById.get(String(segmentId || ''));
            if (!target) return;
            pushNode({
                id: String(target.id || ''),
                kind: 'segment',
                label: String(labelOverride || target.label || 'Section'),
                meta: '',
                secondary: '',
                width: compact ? 144 : 168,
                height: compact ? 48 : 54,
                context: true,
            });
        }

        (activeSegment?.stages || []).forEach((stage) => {
            pushNode({
                id: String(stage.stage_key || ''),
                kind: 'stage',
                label: String(stage.display_name || stage.stage_key || 'Untitled step'),
                meta: String(nodeStates?.[String(stage.stage_key || '')] || ''),
                secondary: '',
                width: compact ? 168 : 188,
                height: compact ? 74 : 84,
            });
        });

        (activeSegment?.incomingSegments || []).forEach((segmentId) => pushExternalSegment(segmentId));
        (activeSegment?.outgoingEdges || []).forEach((edge) => {
            if (edge.targetKind === 'segment') pushExternalSegment(edge.targetKey);
        });

        _segmentFinishLabels(activeSegment).forEach((label, index) => {
            pushNode({
                id: `outcome:${index}:${String(label || '')}`,
                kind: 'outcome',
                label: String(label || 'Finish'),
                meta: '',
                width: compact ? 138 : 148,
                height: compact ? 52 : 56,
            });
        });

        (activeSegment?.stages || []).forEach((stage) => {
            Object.entries(stage.transitions || {}).forEach(([decision, target]) => {
                const decisionKey = String(decision || '').trim().toLowerCase();
                const targetKey = String(target || '').trim();
                if (!targetKey) return;
                const transitionId = _stageTransitionId(stage.stage_key, decisionKey);
                if (stageKeys.has(targetKey)) {
                    edges.push({
                        id: transitionId,
                        from: String(stage.stage_key || ''),
                        to: targetKey,
                        label: _showEdgeLabel({ decision: decisionKey }, stage, 'topology')
                            ? _protocolDecisionLabel(decisionKey)
                            : '',
                        primary: String(stage.stage_key || '') === focusStageKey || targetKey === focusStageKey,
                        muted: String(stage.stage_key || '') !== focusStageKey && targetKey !== focusStageKey,
                    });
                    return;
                }
                if (PROTOCOL_TERMINAL_TARGETS.some((item) => item.key === targetKey)) {
                    const label = _transitionTargetLabel(targetKey, doc);
                    edges.push({
                        id: transitionId,
                        from: String(stage.stage_key || ''),
                        to: nodes.find((node) => node.kind === 'outcome' && node.label === label)?.id || '',
                        label: _protocolDecisionLabel(decisionKey),
                        primary: true,
                    });
                    return;
                }
                const targetSegmentId = String(projection.stageToSegment.get(targetKey) || '');
                if (!targetSegmentId) return;
                edges.push({
                    id: transitionId,
                    from: String(stage.stage_key || ''),
                    to: targetSegmentId,
                    label: _protocolDecisionLabel(decisionKey),
                    primary: Number(projection.segmentsById.get(targetSegmentId)?.column || 0) > Number(activeSegment?.column || 0),
                    muted: Number(projection.segmentsById.get(targetSegmentId)?.column || 0) <= Number(activeSegment?.column || 0),
                });
            });
        });

        (activeSegment?.incomingSegments || []).forEach((segmentId) => {
            const sourceSegment = projection.segmentsById.get(segmentId);
            if (!sourceSegment) return;
            const inboundEdges = (sourceSegment.outgoingEdges || []).filter((edge) => String(edge.targetKey || '') === String(activeSegment?.id || ''));
            inboundEdges.forEach((edge) => {
                edges.push({
                    id: `context:${String(edge.id || '')}`,
                    from: String(sourceSegment.id || ''),
                    to: String(activeSegment?.stageKeys?.[0] || ''),
                    label: String(edge.label || ''),
                    muted: true,
                });
            });
        });

        return {
            title: 'Workflow stages',
            subtitle: `Focused on ${String(activeSegment?.label || 'section')}. Edit the selected step inline and open the map only when you need route context.`,
            hint: editorMode.kind === 'rehearse' ? 'Rehearsal is active. Workflow state is annotated on the same canvas while authoring is paused.' : '',
            outlineTitle: 'Workflow outline',
            direction: compact ? 'DOWN' : 'RIGHT',
            fitPadding: compact ? 18 : 56,
            nodeSpacing: compact ? 20 : 30,
            layerSpacing: compact ? 36 : 68,
            graph: { nodes, edges: edges.filter((edge) => edge.from && edge.to) },
            focusIds: nodes.map((node) => String(node.id || '')),
        };
    }

    function _workflowData() {
        const projection = _buildWorkflowProjection(draft.document);
        const progress = _workflowProgress(draft.document);
        const nodeStates = rehearsal.runId ? _rehearsalNodeStates() : {};
        const activeSegmentId = _selectionSegmentId(projection);
        const activeSegment = projection.segmentsById.get(activeSegmentId) || null;
        const compact = _isCompactViewport();
        const scene = activeSegment
            ? _focusedWorkflowScene(projection, nodeStates, activeSegment, { compact })
            : _workflowStoryScene(projection, { compact });
        return {
            projection,
            progress,
            nodeStates,
            firstRun: _firstRunState(progress),
            toolbarActions: _workflowToolbarActions(progress, projection),
            viewState: {
                title: scene.title,
                subtitle: scene.subtitle,
                hint: scene.hint,
            },
            scene: {
                ...scene,
                key: [
                    String(activeSegmentId || ''),
                    ...((scene.graph?.nodes || []).map((item) => String(item.id || ''))),
                    ...((scene.graph?.edges || []).map((item) => String(item.id || ''))),
                ].join('|'),
                outline: _sceneOutline(projection, nodeStates, activeSegmentId),
                keyboardOrder: [
                    ...projection.segments.map((segment) => ({ kind: 'segment', id: String(segment.id || '') })),
                    ...projection.segments.flatMap((segment) => (segment.stages || []).map((stage) => ({
                        kind: 'stage',
                        id: String(stage.stage_key || ''),
                    }))),
                ],
            },
        };
    }

    function _rehearsalNodeStates() {
        const states = {};
        (rehearsal.runDetail?.stage_executions || []).forEach((stage) => {
            const key = String(stage.stage_key || '').trim();
            if (!key) return;
            states[key] = String(stage.status || '').trim() || 'queued';
        });
        (rehearsal.sessions || []).forEach((session) => {
            const key = String(session.stage_key || '').trim();
            if (!key) return;
            states[key] = session.state || 'awaiting response';
        });
        return states;
    }

    function _surfaceSelection() {
        return {
            kind: selection.sectionKey === 'segments'
                ? 'segment'
                : selection.sectionKey === 'transitions'
                    ? 'transition'
                    : selection.sectionKey === 'participants'
                        ? 'participant'
                        : selection.sectionKey === 'artifacts'
                            ? 'artifact'
                            : selection.sectionKey === 'stages'
                                ? 'stage'
                                : 'overview',
            id: selection.nodeKey,
        };
    }

    function _surfaceSelect(workflow, kind, id) {
        if (kind === 'segment') {
            selection = _normalizeSelectionForProjection({ sectionKey: 'segments', nodeKey: id }, workflow.projection);
        } else if (kind === 'transition') {
            selection = { sectionKey: 'transitions', nodeKey: id };
        } else if (kind === 'stage') {
            selection = { sectionKey: 'stages', nodeKey: id };
        } else if (kind === 'participant') {
            selection = { sectionKey: 'participants', nodeKey: id };
        } else if (kind === 'artifact') {
            selection = { sectionKey: 'artifacts', nodeKey: id };
        } else {
            selection = { sectionKey: 'overview', nodeKey: '' };
        }
        render();
    }

    function _workflowMapEl(workflow) {
        return Kit.workflowCanvas({
            scene: workflow.scene,
            mode: 'graph',
            editorMode,
            viewportState: { zoom: _canvasZoomValue() },
            mapVisible: true,
            showOutline: false,
            onViewportChange: (zoom) => _setCanvasViewport(zoom),
            selection: _surfaceSelection(),
            onSelect: ({ kind, id }) => _surfaceSelect(workflow, kind, id),
            onMutate: ({ type }) => {
                if (type === 'undo') {
                    _restoreHistory('undo');
                    return;
                }
                if (type === 'redo') {
                    _restoreHistory('redo');
                }
            },
        });
    }

    function _workflowMapPanelEl(workflow) {
        const panel = document.createElement('section');
        panel.className = 'kit-protocol-inline-card kit-authoring-map-panel';
        panel.dataset.key = 'protocol-authoring-map-panel';

        const head = document.createElement('div');
        head.className = 'kit-authoring-map-head';

        const copy = document.createElement('div');
        copy.className = 'kit-authoring-map-copy';
        const title = document.createElement('h3');
        title.className = 'kit-stage-editor-hero-title';
        title.textContent = 'Workflow map';
        copy.appendChild(title);
        const note = document.createElement('p');
        note.className = 'kit-stage-editor-hero-note';
        note.textContent = 'Use the map for route context and structure review. It stays fully interactive here: click a step to jump back into the inline editor, zoom when needed, then close it to continue authoring.';
        copy.appendChild(note);
        head.appendChild(copy);

        panel.appendChild(head);
        panel.appendChild(_workflowMapEl(workflow));
        return panel;
    }

    function _editorContext(workflow = null) {
        const doc = draft.document;
        const projection = workflow?.projection || _buildWorkflowProjection(doc);
        const readOnly = editorMode.kind === 'rehearse';
        const applyReadOnly = (schema) => (!readOnly
            ? schema
            : schema.map((field) => ({
                ...field,
                disabled: field.kind === 'checkbox' || field.kind === 'select' ? true : field.disabled,
                readOnly: field.kind !== 'checkbox' && field.kind !== 'select' ? true : field.readOnly,
            })));
        const participantOptions = [
            { value: '', label: '(choose an owner role)' },
            ...((doc.participants || []).map((p) => ({
                value: String(p.participant_key || ''),
                label: String(p.display_name || p.participant_key || ''),
            }))),
        ];
        const stageParticipantOptions = [...participantOptions, { value: '__new__', label: 'Create new role…' }];
        const kindOptions = _manifestStageKindOptions().map((value) => ({
            value,
            label: Kit.dict.label(`protocol.stage.kind.${value}`, value),
        }));
        const artifactOptions = (doc.artifacts || []).map((item) => ({
            value: String(item.artifact_key || ''),
            label: _artifactOptionLabel(item),
        }));
        return {
            doc,
            projection,
            readOnly,
            applyReadOnly,
            participantOptions,
            stageParticipantOptions,
            kindOptions,
            artifactOptions,
        };
    }

    function _protocolSettingsPanelEl(context) {
        return Kit.detailsPanel({
            target: {
                description: draft.description,
                single_active_writer: Boolean(draft.document.policies?.single_active_writer ?? true),
                max_review_rounds: Number(draft.document.policies?.max_review_rounds || 5) || 5,
            },
            surfaceKey: 'protocol',
            onCommit: context.readOnly ? null : _commitOverview,
            schema: context.applyReadOnly([
                { key: 'description', kind: 'textarea', rows: 4 },
                ...((draft.document.stages || []).length ? [
                    { key: 'single_active_writer', kind: 'checkbox', labelKey: 'protocol.policy.single_active_writer.label', helpKey: 'protocol.policy.single_active_writer.help' },
                    { key: 'max_review_rounds', kind: 'text', labelKey: 'protocol.policy.max_review_rounds.label', helpKey: 'protocol.policy.max_review_rounds.help' },
                ] : []),
            ]),
        });
    }

    function _selectionArtifact(doc = draft.document) {
        if (selection.sectionKey !== 'artifacts') return null;
        return (doc.artifacts || []).find((item) => String(item.artifact_key || '') === String(selection.nodeKey || '')) || null;
    }

    function _deleteArtifact(artifactKey) {
        const normalizedArtifactKey = String(artifactKey || '').trim();
        if (!normalizedArtifactKey) return;
        const doc = _cloneDoc(draft.document);
        doc.artifacts = (doc.artifacts || []).filter((item) => String(item.artifact_key || '') !== normalizedArtifactKey);
        doc.stages = (doc.stages || []).map((stage) => ({
            ...stage,
            inputs: (stage.inputs || []).filter((item) => String(item || '') !== normalizedArtifactKey),
            outputs: (stage.outputs || []).filter((item) => String(item || '') !== normalizedArtifactKey),
        }));
        _commitDocument(doc, { nextSelection: { sectionKey: 'protocol', nodeKey: '' } });
    }

    function _confirmArtifactDelete(artifactKey) {
        const artifact = (draft.document.artifacts || []).find((item) => String(item.artifact_key || '') === String(artifactKey || ''));
        if (!artifact) return;
        const artifactLabel = String(artifact.display_name || artifact.artifact_key || 'this artifact');
        UI.showConfirm(
            'Delete artifact',
            `Delete ${artifactLabel}? Any step inputs or outputs referencing it will be cleared.`,
            async () => { _deleteArtifact(artifactKey); },
        );
    }

    function _artifactEditorEl(artifact, context) {
        const artifactKey = String(artifact?.artifact_key || '').trim();
        const shell = document.createElement('div');
        shell.className = 'kit-stage-editor';
        shell.dataset.key = `protocol-artifact-editor:${artifactKey}`;

        const guide = document.createElement('div');
        guide.className = 'kit-artifact-guide';
        const guideNote = document.createElement('p');
        guideNote.className = 'kit-stage-editor-hero-note';
        guideNote.textContent = 'Artifacts are the concrete files or text that steps pass between each other. Use workspace files for datasets, code, documents, PDFs, and reports. Use run-carried text only for small notes or structured text that should not live in the workspace.';
        guide.appendChild(guideNote);

        const facts = document.createElement('div');
        facts.className = 'kit-artifact-guide-facts';
        [
            {
                label: 'Represents',
                value: _artifactPurposeLabel(artifact),
            },
            {
                label: 'Stored at',
                value: _artifactDefinitionPath(artifact) || (String(artifact?.kind || '').trim().toLowerCase() === 'control_plane_text'
                    ? 'In the run record instead of the workspace'
                    : 'Pick a workspace-relative path'),
            },
            {
                label: 'Verification',
                value: artifact?.verify === false ? 'Optional' : 'Required before a writing step can complete',
            },
        ].forEach((item) => {
            const stat = document.createElement('div');
            stat.className = 'kit-artifact-guide-fact';
            const statLabel = document.createElement('strong');
            statLabel.className = 'kit-artifact-guide-fact-label';
            statLabel.textContent = String(item.label || '');
            stat.appendChild(statLabel);
            const statValue = document.createElement('span');
            statValue.className = 'kit-artifact-guide-fact-value';
            statValue.textContent = String(item.value || '');
            stat.appendChild(statValue);
            facts.appendChild(stat);
        });
        guide.appendChild(facts);
        shell.appendChild(guide);

        const kindOptions = _manifestArtifactKindOptions().map((value) => ({
            value,
            label: Kit.dict.label(`protocol.artifact.kind.${value}`, value),
        }));
        const onCommit = context.readOnly
            ? null
            : (_target, key, value) => {
                const activeArtifactKey = String(
                    selection.sectionKey === 'artifacts'
                        ? selection.nodeKey || artifactKey
                        : artifactKey,
                ).trim();
                _commitNodeField('artifact', activeArtifactKey, key, value);
            };

        const basics = Kit.detailsPanel({
            target: artifact,
            surfaceKey: 'protocol.artifact',
            onCommit,
            schema: context.applyReadOnly([
                { key: 'display_name', kind: 'text', label: 'Name', required: true },
                { key: 'kind', kind: 'select', label: 'What it represents', options: kindOptions, help: 'Most datasets, code files, documents, and reports should stay as workspace files.' },
                ...(String(artifact?.kind || 'workspace_file').trim().toLowerCase() === 'control_plane_text'
                    ? []
                    : [{ key: 'path', kind: 'text', label: 'Workspace path', help: 'Relative to the workspace root. Examples: data/source.csv, src/analyze.py, reports/final.pdf.' }]),
            ]),
            actions: context.readOnly
                ? []
                : [{ label: 'Delete artifact', tone: 'btn-danger', onClick: () => _confirmArtifactDelete(artifactKey) }],
        });
        shell.appendChild(_stageEditorSection('Artifact basics', basics));

        const details = Kit.detailsPanel({
            target: artifact,
            surfaceKey: 'protocol.artifact',
            onCommit,
            schema: context.applyReadOnly([
                { key: 'description', kind: 'textarea', rows: 4 },
                {
                    key: 'verify',
                    kind: 'checkbox',
                    label: 'Require verification',
                    help: 'Keep this enabled when a writing step should not complete until the artifact is observed or verified.',
                },
            ]),
        });
        shell.appendChild(_stageEditorSection('Details', details, {
            wide: true,
            collapsible: true,
            open: Boolean(String(artifact?.description || '').trim()),
        }));

        const usage = _artifactUsage(context.doc, artifactKey);
        const usagePanel = document.createElement('div');
        usagePanel.className = 'kit-artifact-usage';
        if (!usage.reads.length && !usage.writes.length) {
            usagePanel.appendChild(UI.renderEmptyState('This artifact is not attached to any step yet. Define it here first, then attach it in a step’s inputs and outputs section.', true));
        } else {
            [
                { label: 'Needed by', items: usage.reads },
                { label: 'Produced by', items: usage.writes },
            ].forEach((group) => {
                if (!group.items.length) return;
                const groupEl = document.createElement('div');
                groupEl.className = 'kit-artifact-usage-group';
                const groupLabel = document.createElement('strong');
                groupLabel.className = 'kit-artifact-usage-label';
                groupLabel.textContent = String(group.label || '');
                groupEl.appendChild(groupLabel);
                const list = document.createElement('div');
                list.className = 'kit-artifact-usage-list';
                group.items.forEach((item) => {
                    const chip = document.createElement('span');
                    chip.className = 'badge';
                    chip.textContent = String(item || '');
                    list.appendChild(chip);
                });
                groupEl.appendChild(list);
                usagePanel.appendChild(groupEl);
            });
        }
        shell.appendChild(_stageEditorSection('Used by steps', usagePanel, {
            wide: true,
            collapsible: true,
            open: Boolean(usage.reads.length || usage.writes.length),
        }));
        return shell;
    }

    function _artifactCatalogEl(context) {
        const panel = document.createElement('section');
        panel.className = 'kit-protocol-inline-card';
        const title = document.createElement('h3');
        title.className = 'kit-stage-editor-hero-title';
        title.textContent = 'Workflow files and outputs';
        panel.appendChild(title);
        const subtitle = document.createElement('p');
        subtitle.className = 'kit-stage-editor-hero-note';
        subtitle.textContent = 'Define shared datasets, code files, documents, reports, or run-carried text once here. Steps only attach reads and writes to these definitions later.';
        panel.appendChild(subtitle);

        const actions = document.createElement('div');
        actions.className = 'kit-protocol-segment-step-actions';
        if (!context.readOnly) {
            const add = document.createElement('button');
            add.type = 'button';
            add.className = 'btn btn-small';
            add.textContent = 'Add artifact';
            add.addEventListener('click', _addArtifact);
            actions.appendChild(add);
        }
        if (actions.childElementCount) panel.appendChild(actions);

        const list = document.createElement('div');
        list.className = 'kit-protocol-stage-stack';
        const selectedArtifactKey = String(selection.sectionKey === 'artifacts' ? selection.nodeKey || '' : '');
        (context.doc.artifacts || []).forEach((artifact) => {
            const artifactKey = String(artifact.artifact_key || '');
            const entry = document.createElement('div');
            entry.className = 'kit-protocol-segment-entry';
            entry.dataset.key = `protocol-artifact-entry:${artifactKey}`;

            const row = document.createElement('button');
            row.type = 'button';
            row.className = `kit-protocol-segment-step${selectedArtifactKey === artifactKey ? ' is-selected' : ''}`;
            row.dataset.testid = `workflow-artifact-${artifactKey}`;
            row.dataset.key = `protocol-artifact-row:${artifactKey}`;
            row.addEventListener('click', () => {
                selection = { sectionKey: 'artifacts', nodeKey: artifactKey };
                render();
            });

            const titleRow = document.createElement('div');
            titleRow.className = 'kit-protocol-segment-step-head';
            const label = document.createElement('strong');
            label.className = 'kit-protocol-segment-step-title';
            label.textContent = String(artifact.display_name || artifact.artifact_key || 'Untitled artifact');
            titleRow.appendChild(label);
            row.appendChild(titleRow);

            const summary = document.createElement('div');
            summary.className = 'kit-protocol-segment-step-meta';
            summary.textContent = [
                _artifactPurposeLabel(artifact),
                _artifactDefinitionPath(artifact),
                _artifactUsageSummary(context.doc, artifactKey),
            ].filter(Boolean).join(' · ');
            row.appendChild(summary);
            entry.appendChild(row);

            if (selectedArtifactKey === artifactKey) {
                const inline = document.createElement('div');
                inline.className = 'kit-protocol-inline-editor';
                inline.dataset.key = `protocol-artifact-inline:${artifactKey}`;
                inline.appendChild(_artifactEditorEl(artifact, context));
                entry.appendChild(inline);
            }

            list.appendChild(entry);
        });
        if (!list.childElementCount) {
            list.appendChild(UI.renderEmptyState('No shared files or outputs yet. Add one here, then attach it from a step’s inputs and outputs section.', true));
        }
        panel.appendChild(list);
        return panel;
    }

    function _stageEditorTarget(stage) {
        return {
            ...stage,
            selector_mode: _currentStageAssignmentMode(String(stage?.stage_key || ''), String(stage?.selector?.kind || '')),
            selector_kind: String(stage?.selector?.kind || ''),
            selector_value: String(stage?.selector?.value || ''),
            selector_preferred_agent_id: String(stage?.selector?.preferred_agent_id || ''),
        };
    }

    function _activeStageKey() {
        if (editorMode.kind === 'create-route') {
            return String(pendingRoute.source_stage_key || '');
        }
        if (editorMode.kind === 'insert-stage') {
            return String(editorMode.sourceStageKey || '');
        }
        if (selection.sectionKey === 'stages' && selection.nodeKey) {
            return String(selection.nodeKey || '');
        }
        if (selection.sectionKey === 'transitions' && selection.nodeKey) {
            return String(selection.nodeKey || '').split('::')[0] || '';
        }
        return '';
    }

    function _toggleStageSelection(stageKey) {
        const nextKey = String(stageKey || '');
        if (!nextKey) return;
        if (selection.sectionKey === 'stages' && String(selection.nodeKey || '') === nextKey && editorMode.kind === 'idle') {
            selection = { sectionKey: 'overview', nodeKey: '' };
        } else {
            selection = { sectionKey: 'stages', nodeKey: nextKey };
        }
        render();
    }

    function _stageInsertMatchesDefaultAnchor(stage, projection) {
        if (editorMode.kind !== 'insert-stage') return false;
        const anchor = _insertAnchorForStage(stage, projection);
        return Boolean(anchor
            && String(anchor.sourceStageKey || '') === String(editorMode.sourceStageKey || '')
            && String(anchor.decision || '') === String(editorMode.decision || ''));
    }

    function _inlineStageInsertEl(context) {
        const shell = _stageEditorShell({
            target: pendingStage,
            participantOptions: context.stageParticipantOptions,
            kindOptions: context.kindOptions,
            artifactOptions: context.artifactOptions,
            onCommit: _commitPendingStageField,
            createAction: _confirmStageInsert,
            cancelAction: _cancelStageInsert,
            createHint: _workflowInsertHint(),
        });
        shell.dataset.key = [
            'protocol-inline-insert',
            String(editorMode.sessionKey || ''),
            String(editorMode.sourceStageKey || ''),
            String(editorMode.decision || ''),
            String(pendingStage.display_name || ''),
            String(pendingStage.stage_kind || ''),
            String(pendingStage.participant_key || ''),
            String(pendingStage.selector_mode || ''),
            String(pendingStage.selector_kind || ''),
            String(pendingStage.selector_value || ''),
            String(pendingStage.selector_preferred_agent_id || ''),
            String(pendingStage.role_display_name || ''),
            String(pendingStage.role_participant_key || ''),
        ].join(':');
        return shell;
    }

    function _inlineRouteEditorEl(stageKey, context) {
        const stage = (context.doc.stages || []).find((item) => String(item.stage_key || '') === String(stageKey || ''));
        if (!stage) return null;
        if (editorMode.kind === 'create-route' && String(pendingRoute.source_stage_key || '') === String(stageKey || '')) {
            return _routeEditorPanel({
                target: {
                    source_stage: String(stage.display_name || stage.stage_key || ''),
                    decision: String(pendingRoute.decision || ''),
                    target_key: String(pendingRoute.target_key || ''),
                },
                sourceStage: stage,
                projection: context.projection,
                onCommit: _commitPendingRouteField,
                createAction: _confirmRouteInsert,
                cancelAction: _cancelRouteInsert,
            });
        }
        if (selection.sectionKey !== 'transitions') return null;
        const target = _transitionEntries(context.doc).find((item) => String(item.id || '') === String(selection.nodeKey || ''));
        if (!target || String(target.from_stage_key || '') !== String(stageKey || '')) return null;
        return _routeEditorPanel({
            target: {
                source_stage: String(stage.display_name || stage.stage_key || target.from_stage_key || ''),
                decision: String(target.decision || ''),
                target_key: String(target.target_key || ''),
            },
            sourceStage: stage,
            projection: context.projection,
            readOnly: context.readOnly,
            onCommit: context.readOnly ? null : (_t, key, value) => _commitTransitionField(selection.nodeKey, key, value),
            insertAction: context.readOnly ? null : () => _startStageInsert({
                sourceStageKey: target.from_stage_key,
                decision: target.decision,
            }),
            deleteAction: context.readOnly ? null : () => UI.showConfirm(
                'Remove transition',
                'Remove this transition from the workflow?',
                async () => { _deleteTransition(selection.nodeKey); },
            ),
        });
    }

    function _stageEditorEl(stage, context) {
        const shell = _stageEditorShell({
            target: _stageEditorTarget(stage),
            readOnly: context.readOnly,
            participantOptions: context.participantOptions,
            kindOptions: context.kindOptions,
            artifactOptions: context.artifactOptions,
            onCommit: context.readOnly
                ? null
                : (_t, key, value) => _commitNodeField('stage', String(stage.stage_key || ''), key, value),
            connectAction: context.readOnly ? null : () => _startRouteInsert(String(stage.stage_key || '')),
            deleteAction: context.readOnly ? null : () => _confirmStageDelete(String(stage.stage_key || '')),
        });
        shell.dataset.key = `protocol-stage-editor:${String(stage.stage_key || '')}`;
        return shell;
    }

    function _protocolSettingsSectionEl(context) {
        const card = document.createElement('section');
        card.className = 'kit-protocol-inline-card';
        const title = document.createElement('h3');
        title.className = 'kit-stage-editor-hero-title';
        title.textContent = 'Protocol settings';
        card.appendChild(title);
        const subtitle = document.createElement('p');
        subtitle.className = 'kit-stage-editor-hero-note';
        subtitle.textContent = 'Adjust protocol-wide description, policies, and shared artifacts here. Stage editing stays inline below.';
        card.appendChild(subtitle);
        card.appendChild(_protocolSettingsPanelEl(context));
        card.appendChild(_artifactCatalogEl(context));
        return card;
    }

    function _segmentPanelEl(segment, workflow, context) {
        const panel = document.createElement('section');
        panel.className = 'kit-protocol-segment-panel';
        panel.dataset.key = `protocol-segment-panel:${String(segment.id || '')}`;
        panel.dataset.testid = `workflow-segment-${String(segment.id || '')}`;

        const head = document.createElement('div');
        head.className = 'kit-protocol-segment-head';
        const firstStageLabel = String(segment?.stages?.[0]?.display_name || segment?.stages?.[0]?.stage_key || '').trim().toLowerCase();
        const segmentLabel = String(segment?.label || 'Section');
        const showSegmentTitle = Boolean(segmentLabel.trim()) && segmentLabel.trim().toLowerCase() !== firstStageLabel;
        const title = document.createElement('h3');
        title.className = 'kit-protocol-segment-step-title';
        title.textContent = segmentLabel;
        if (showSegmentTitle) {
            head.appendChild(title);
        }
        const subtitle = document.createElement('p');
        subtitle.className = 'kit-protocol-segment-step-meta';
        subtitle.textContent = `${Array.isArray(segment?.stages) ? segment.stages.length : 0} step${segment?.stages?.length === 1 ? '' : 's'} in this section.`;
        head.appendChild(subtitle);
        panel.appendChild(head);

        const activeStageKey = _activeStageKey();
        const selectedTransition = selection.sectionKey === 'transitions'
            ? _selectionTransition(context.doc)
            : null;
        const list = document.createElement('div');
        list.className = 'kit-protocol-segment-steps';

        (Array.isArray(segment?.stages) ? segment.stages : []).forEach((stage) => {
            const stageKey = String(stage.stage_key || '');
            const entry = document.createElement('div');
            entry.className = 'kit-protocol-segment-entry';
            entry.dataset.key = `protocol-segment-entry:${stageKey}`;

            const row = document.createElement('button');
            row.type = 'button';
            row.className = `kit-protocol-segment-step${activeStageKey === stageKey ? ' is-selected' : ''}`;
            row.dataset.testid = `workflow-stage-${stageKey}`;
            row.addEventListener('click', () => _toggleStageSelection(stageKey));

            const titleRow = document.createElement('div');
            titleRow.className = 'kit-protocol-segment-step-head';
            const label = document.createElement('strong');
            label.className = 'kit-protocol-segment-step-title';
            label.textContent = String(stage.display_name || stage.stage_key || 'Untitled step');
            titleRow.appendChild(label);
            const state = String(workflow?.nodeStates?.[stageKey] || '');
            if (state) {
                const badge = document.createElement('span');
                badge.className = 'kit-workflow-node-state';
                badge.textContent = state;
                titleRow.appendChild(badge);
            }
            row.appendChild(titleRow);

            const summary = document.createElement('div');
            summary.className = 'kit-protocol-segment-step-meta';
            summary.textContent = [
                _participantDisplayName(stage.participant_key, context.doc) || 'Unassigned',
                _stageAssignmentSummary(stage, { empty: 'Unassigned' }),
            ].filter(Boolean).join(' · ');
            row.appendChild(summary);
            entry.appendChild(row);

            if (!context.readOnly && activeStageKey === stageKey) {
                const actions = document.createElement('div');
                actions.className = 'kit-protocol-segment-step-actions';
                const add = document.createElement('button');
                add.type = 'button';
                add.className = 'btn btn-small';
                add.textContent = 'Add below';
                add.addEventListener('click', () => {
                    const anchor = _insertAnchorForStage(stage, context.projection);
                    _startStageInsert(anchor || {});
                });
                actions.appendChild(add);
                entry.appendChild(actions);
            }

            if (activeStageKey === stageKey) {
                const inline = document.createElement('div');
                inline.className = 'kit-protocol-inline-editor';
                const routeEditor = _inlineRouteEditorEl(stageKey, context);
                const showPendingInsert = editorMode.kind === 'insert-stage'
                    && String(editorMode.sourceStageKey || '') === stageKey
                    && (
                        (selectedTransition
                            && String(selectedTransition.from_stage_key || '') === stageKey
                            && String(selectedTransition.decision || '') === String(editorMode.decision || ''))
                        || _stageInsertMatchesDefaultAnchor(stage, context.projection)
                    );
                if (!showPendingInsert) {
                    inline.appendChild(_stageEditorEl(stage, context));
                }
                if (routeEditor) {
                    inline.appendChild(routeEditor);
                }
                if (showPendingInsert) {
                    inline.appendChild(_inlineStageInsertEl(context));
                }
                entry.appendChild(inline);
            }

            list.appendChild(entry);
        });

        if (!list.childElementCount && editorMode.kind === 'insert-stage') {
            list.appendChild(_inlineStageInsertEl(context));
        }
        panel.appendChild(list);
        return panel;
    }

    function _progressiveWorkflowEl(workflow) {
        const context = _editorContext(workflow);
        const root = document.createElement('div');
        root.className = 'kit-authoring-primary-column';
        root.dataset.key = 'protocol-authoring-primary-column';
        root.appendChild(Kit.workflowHeaderBar({
            firstRun: workflow.firstRun,
            editorMode,
            viewState: workflow.viewState,
            toolbarActions: workflow.toolbarActions,
        }));

        if (_workflowMapVisible()) {
            root.appendChild(_workflowMapPanelEl(workflow));
        }

        if (selection.sectionKey === 'protocol' || selection.sectionKey === 'artifacts') {
            root.appendChild(_protocolSettingsSectionEl(context));
        }

        const stack = document.createElement('div');
        stack.className = 'kit-protocol-stage-stack';
        stack.dataset.selection = String(selection.sectionKey || 'overview');
        workflow.projection.segments.forEach((segment) => {
            stack.appendChild(_segmentPanelEl(segment, workflow, context));
        });
        if (!workflow.projection.segments.length && editorMode.kind === 'insert-stage') {
            stack.appendChild(_inlineStageInsertEl(context));
        }
        root.appendChild(stack);

        const validation = editorMode.kind === 'rehearse' ? null : _validationEl();
        if (validation) {
            root.appendChild(validation);
        }
        if (editorMode.kind === 'rehearse' || rehearsal.runId) {
            root.appendChild(Kit.rehearsalPanel({
                runId: rehearsal.runId,
                sessions: rehearsal.sessions,
                scenarios: rehearsal.scenarios,
                onRespond: (payload) => { void _respondRehearsal(payload); },
            }));
        }
        return root;
    }

    function _stageEditorSection(title, panel, { wide = false, collapsible = false, open = true } = {}) {
        const section = document.createElement(collapsible ? 'details' : 'section');
        section.className = `kit-stage-editor-section${wide ? ' is-wide' : ''}${collapsible ? ' is-collapsible' : ''}`;
        if (collapsible) {
            section.open = Boolean(open);
            const summary = document.createElement('summary');
            summary.className = 'kit-stage-editor-summary';
            const heading = document.createElement('h4');
            heading.className = 'kit-stage-editor-title';
            heading.textContent = String(title || '');
            summary.appendChild(heading);
            section.appendChild(summary);
        } else {
            const heading = document.createElement('h4');
            heading.className = 'kit-stage-editor-title';
            heading.textContent = String(title || '');
            section.appendChild(heading);
        }
        section.appendChild(panel);
        return section;
    }

    function _stageArtifactsEditor({
        target,
        readOnly = false,
        onCommit = null,
        artifactOptions = [],
    } = {}) {
        const shell = document.createElement('div');
        shell.className = 'kit-stage-artifacts';

        const note = document.createElement('p');
        note.className = 'kit-stage-editor-hero-note';
        note.textContent = 'Attach the shared files or text this step needs and produces. Define them once in Workflow files and outputs, then connect them here.';
        shell.appendChild(note);

        if (!artifactOptions.length) {
            shell.appendChild(UI.renderEmptyState('No workflow files or outputs are defined yet.', true));
            if (!readOnly) {
                const actions = document.createElement('div');
                actions.className = 'kit-stage-routing-actions';
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'btn btn-small';
                button.textContent = 'Open workflow files and outputs';
                button.addEventListener('click', () => _openArtifactCatalog());
                actions.appendChild(button);
                shell.appendChild(actions);
            }
            return shell;
        }

        shell.appendChild(Kit.detailsPanel({
            target,
            surfaceKey: 'protocol.stage',
            onCommit,
            schema: [
                { key: 'inputs', kind: 'checklist', options: artifactOptions, label: 'Needs from earlier steps', help: 'Check the shared files or text this step reads before it can run.', disabled: readOnly },
                { key: 'outputs', kind: 'checklist', options: artifactOptions, label: 'Produces for later steps', help: 'Check the shared files or text this step should create or update for later steps.', disabled: readOnly },
            ],
        }));
        if (!readOnly) {
            const actions = document.createElement('div');
            actions.className = 'kit-stage-routing-actions';
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'btn btn-small';
            button.textContent = 'Edit workflow files and outputs';
            button.addEventListener('click', () => _openArtifactCatalog());
            actions.appendChild(button);
            shell.appendChild(actions);
        }
        return shell;
    }

    function _stageRoutingPanel(stage, { readOnly = false, connectAction = null } = {}) {
        const panel = document.createElement('div');
        panel.className = 'kit-stage-routing';

        const head = document.createElement('div');
        head.className = 'kit-stage-routing-head';

        const intro = document.createElement('p');
        intro.className = 'kit-stage-routing-copy';
        intro.textContent = 'Use branches only when this step can go to different next steps or finish outcomes.';
        head.appendChild(intro);

        if (!readOnly && typeof connectAction === 'function') {
            const add = document.createElement('button');
            add.type = 'button';
            add.className = 'btn btn-small';
            add.textContent = 'Add branch or finish';
            add.addEventListener('click', connectAction);
            head.appendChild(add);
        }
        panel.appendChild(head);

        const routes = _transitionEntries(draft.document)
            .filter((item) => String(item.from_stage_key || '') === String(stage?.stage_key || ''))
            .map((item) => ({
                ...item,
                decisionLabel: _protocolDecisionLabel(item.decision),
                targetLabel: _transitionTargetLabel(item.target_key, draft.document),
            }));

        if (!routes.length) {
            const empty = document.createElement('div');
            empty.className = 'kit-stage-routing-empty';
            empty.textContent = readOnly
                ? 'No routes are defined for this step yet.'
                : 'No branches yet. Add a finish outcome or another next step from here when this step can split.';
            panel.appendChild(empty);
            return panel;
        }

        const list = document.createElement('div');
        list.className = 'kit-stage-routing-list';
        routes.forEach((route) => {
            const entry = document.createElement('div');
            entry.className = 'kit-stage-routing-entry';

            const row = document.createElement('button');
            row.type = 'button';
            row.className = `kit-stage-routing-item${selection.sectionKey === 'transitions' && selection.nodeKey === route.id ? ' is-selected' : ''}`;
            row.dataset.testid = `stage-route-${String(route.id || '')}`;
            row.addEventListener('click', () => {
                selection = { sectionKey: 'transitions', nodeKey: route.id };
                render();
            });

            const badge = document.createElement('span');
            badge.className = 'kit-stage-routing-badge';
            badge.textContent = String(route.decisionLabel || route.decision || '');
            row.appendChild(badge);

            const body = document.createElement('div');
            body.className = 'kit-stage-routing-body';

            const title = document.createElement('strong');
            title.className = 'kit-stage-routing-target';
            title.textContent = String(route.targetLabel || route.target_key || '');
            body.appendChild(title);

            const meta = document.createElement('span');
            meta.className = 'kit-stage-routing-meta';
            meta.textContent = PROTOCOL_TERMINAL_TARGETS.some((item) => item.key === route.target_key)
                ? 'Finish outcome'
                : 'Open route details';
            body.appendChild(meta);

            row.appendChild(body);
            entry.appendChild(row);

            if (!readOnly) {
                const actions = document.createElement('div');
                actions.className = 'kit-stage-routing-actions';
                const insert = document.createElement('button');
                insert.type = 'button';
                insert.className = 'btn btn-small';
                insert.textContent = `Insert before ${String(route.targetLabel || route.target_key || 'this target')}`;
                insert.addEventListener('click', () => _startStageInsert({
                    sourceStageKey: String(stage?.stage_key || ''),
                    decision: String(route.decision || ''),
                }));
                actions.appendChild(insert);
                entry.appendChild(actions);
            }

            list.appendChild(entry);
        });
        panel.appendChild(list);
        return panel;
    }

    function _stageEditorShell({
        target,
        readOnly = false,
        participantOptions = [],
        kindOptions = [],
        artifactOptions = [],
        onCommit = null,
        connectAction = null,
        createAction = null,
        cancelAction = null,
        deleteAction = null,
        createHint = '',
    } = {}) {
        const applyReadOnly = (schema) => (!readOnly
            ? schema
            : schema.map((field) => ({
                ...field,
                disabled: field.kind === 'checkbox' || field.kind === 'select' ? true : field.disabled,
                readOnly: field.kind !== 'checkbox' && field.kind !== 'select' ? true : field.readOnly,
            })));
        const operatorSurface = _currentAuthoringSurface() === 'operator';
        const shell = document.createElement('div');
        shell.className = 'kit-stage-editor';
        if (createAction && createHint) {
            const note = document.createElement('p');
            note.className = 'kit-stage-editor-hero-note';
            note.textContent = String(createHint || '');
            shell.appendChild(note);
        }

        const grid = document.createElement('div');
        grid.className = 'kit-stage-editor-grid';

        const summaryActions = [];
        if (createAction) {
            summaryActions.push({ label: 'Create step', tone: 'btn-primary', onClick: createAction });
        }
        if (deleteAction && !createAction) {
            summaryActions.push({ label: 'Delete step', tone: 'btn-danger', onClick: deleteAction });
        }
        if (cancelAction) {
            summaryActions.push({ label: 'Cancel', onClick: cancelAction });
        }
        const summaryPanel = Kit.detailsPanel({
            target,
            surfaceKey: 'protocol.stage',
            onCommit,
            schema: applyReadOnly([
                { key: 'display_name', kind: 'text', required: true, commitOnInput: Boolean(createAction) },
                { key: 'participant_key', kind: 'select', options: participantOptions },
                { key: 'stage_kind', kind: 'select', options: kindOptions },
            ]),
            actions: summaryActions,
        });
        grid.appendChild(_stageEditorSection('Step basics', summaryPanel));
        if (createAction || String(target?.participant_key || '') === '__new__') {
            const rolePanel = Kit.detailsPanel({
                target,
                surfaceKey: 'protocol.participant',
                onCommit,
                schema: applyReadOnly([
                    { key: 'role_display_name', kind: 'text', label: 'Role name', help: 'Fill this in when this step should create a new reusable role instead of reusing the selected owner role.', commitOnInput: true },
                    { key: 'role_participant_key', kind: 'text', label: 'Role key', help: 'Internal reference for this role. It is generated from the role name.', commitOnInput: true },
                    { key: 'role_instructions', kind: 'textarea', rows: 3, label: 'Shared instructions', help: 'Optional guidance shared by every step that uses this role.', commitOnInput: true },
                ]),
            });
            const roleSection = _stageEditorSection('New owner role', rolePanel, { wide: true });
            roleSection.classList.add('kit-stage-editor-new-role');
            grid.appendChild(roleSection);
        }
        grid.appendChild(_stageEditorSection('Assignment', _selectorEditor({
            stageKey: createAction ? '' : String(target?.stage_key || ''),
            selectorMode: String(target?.selector_mode || ''),
            selectorKind: String(target?.selector_kind || ''),
            selectorValue: String(target?.selector_value || ''),
            selectorPreferredAgentId: String(target?.selector_preferred_agent_id || ''),
            readOnly,
            onChange: createAction ? _commitPendingStageField : onCommit,
            onSelectorChange: createAction
                ? (kind, value, preferredAgentId) => _commitPendingStageSelector(kind, value, preferredAgentId)
                : (typeof onCommit === 'function' && target?.stage_key
                    ? (kind, value, preferredAgentId) => _commitStageSelector(String(target.stage_key || ''), kind, value, preferredAgentId)
                    : null),
        }), { wide: true }));

        if (!createAction) {
            grid.appendChild(_stageEditorSection('Routing', _stageRoutingPanel(target, { readOnly, connectAction }), {
                wide: true,
                collapsible: _isCompactViewport(),
                open: !_isCompactViewport(),
            }));
        }

        const instructionsPanel = Kit.detailsPanel({
            target,
            surfaceKey: 'protocol.stage',
            onCommit,
            schema: applyReadOnly([
                { key: 'instructions', kind: 'textarea', rows: 6 },
            ]),
        });
        grid.appendChild(_stageEditorSection('Instructions', instructionsPanel, {
            wide: true,
            collapsible: !createAction,
            open: Boolean(createAction),
        }));

        const artifactsPanel = _stageArtifactsEditor({
            target,
            readOnly,
            onCommit,
            artifactOptions,
        });
        grid.appendChild(_stageEditorSection('Inputs and outputs', artifactsPanel, {
            wide: true,
            collapsible: !createAction,
            open: Boolean(createAction),
        }));

        if (operatorSurface) {
            const advancedActions = cancelAction ? [{ label: 'Cancel', onClick: cancelAction }] : [];
            const advancedPanel = Kit.detailsPanel({
                target,
                surfaceKey: 'protocol.stage',
                onCommit,
                schema: applyReadOnly([
                    { key: 'stage_key', kind: 'text' },
                    { key: 'max_rounds', kind: 'text' },
                    { key: 'timeout_seconds', kind: 'text' },
                ]),
                actions: advancedActions,
            });
            grid.appendChild(_stageEditorSection('Advanced', advancedPanel, { collapsible: true, open: false }));
        }
        shell.appendChild(grid);
        return shell;
    }

    function _validationEl() {
        const normalized = [];
        if (saveState.state === 'conflict' && draftConflict?.serverDetail?.protocol) {
            normalized.push({
                severity: 'error',
                message: 'This draft changed in another tab or client. Reload the latest server copy before validating, publishing, archiving, or rehearsing.',
                action: { label: 'Reload', onClick: _reloadServerDraftConflict },
            });
            normalized.push({
                severity: 'warning',
                message: 'If your local edits should win, reload the latest server draft first and then explicitly overwrite it.',
                action: {
                    label: 'Overwrite',
                    onClick: () => UI.showConfirm(
                        'Overwrite server draft',
                        'This reloads the latest server draft revision and immediately reapplies your current local edits on top of it.',
                        async () => { await _overwriteServerDraftConflict(); },
                    ),
                },
            });
        }
        if ((draft.document.stages || []).length === 0) {
            return normalized.length ? Kit.validationSurface({ issues: normalized, layout: 'summary' }) : null;
        }
        const validation = currentProtocol?.validation;
        if (!validation && !normalized.length) return null;
        const issues = Array.isArray(validation?.issues) ? validation.issues : [];
        const filteredIssues = issues.filter((item) => {
            const code = String(item.code || '');
            if (!(draft.document.stages || []).length && ["metadata.slug_required", "participants.required", "stages.required"].includes(code)) {
                return false;
            }
            return true;
        });
        normalized.push(...(filteredIssues.length
            ? filteredIssues.map((item) => ({
                severity: String(item.severity || 'error'),
                message: String(item.message || ''),
                path: String(item.path || ''),
            }))
            : (Array.isArray(validation?.errors) ? validation.errors : []).map((text) => ({
                severity: 'error',
                message: String(text || ''),
            }))));
        if (!normalized.length) {
            return null;
        }
        return Kit.validationSurface({ issues: normalized, layout: 'summary' });
    }

    function _manifestStageKindOptions() {
        return Array.isArray(authoringManifest?.stage_kind_options) && authoringManifest.stage_kind_options.length
            ? authoringManifest.stage_kind_options
            : ['work', 'review', 'acceptance'];
    }

    function _manifestArtifactKindOptions() {
        return Array.isArray(authoringManifest?.artifact_kind_options) && authoringManifest.artifact_kind_options.length
            ? authoringManifest.artifact_kind_options
            : ['workspace_file', 'control_plane_text'];
    }

    function _catalogEl() {
        return Kit.authoredCatalog({
            records: protocols,
            surfaceKey: 'protocol',
            onOpen: (record) => {
                currentProtocolId = String(record.protocol_id || '');
                currentProtocol = null;
                protocolDetailLoading = true;
                _writeState({ push: true });
                render();
                void loadProtocolDetail();
            },
            createAction: {
                label: 'New protocol',
                onClick: () => void _createBlankDraft(),
            },
            secondaryAction: {
                label: Kit.dict.label('protocol.catalog.gallery'),
                onClick: () => Router.navigate('/ui/gallery'),
            },
        });
    }

    function render() {
        if (renderInFlight) {
            renderQueued = true;
            return;
        }
        renderInFlight = true;
        try {
        if (!currentProtocolId) {
            header.hidden = false;
            _writeState();
            UI.reconcileChildren(contentEl, [_catalogEl()]);
            _lifecycleHeaderRef = null;
            return;
        }

        if (protocolDetailLoading) {
            header.hidden = true;
            _writeState();
            UI.reconcileChildren(contentEl, [UI.renderEmptyState('Loading protocol detail…', true)]);
            _lifecycleHeaderRef = null;
            return;
        }

        header.hidden = true;
        _writeState();
        const headerEl = _lifecycleHeaderEl();
        headerEl.dataset.key = 'protocol-lifecycle-header';
        const workflow = _workflowData();

        const workspace = document.createElement('div');
        workspace.className = 'kit-authoring-workspace';
        workspace.dataset.key = 'protocol-authoring-workspace';
        workspace.dataset.selection = String(selection.sectionKey || 'overview');
        workspace.dataset.editorMode = String(editorMode.kind || 'idle');
        workspace.dataset.mapVisible = _workflowMapVisible() ? 'true' : 'false';
        workspace.appendChild(_progressiveWorkflowEl(workflow));

        const previousCanvasRoot = contentEl.__workflowCanvasRoot || null;
        UI.reconcileChildren(contentEl, [headerEl, workspace]);
        if (editorMode.kind === 'insert-stage') {
            const activeInsertEditor = contentEl.querySelector('.kit-stage-editor[data-key^="protocol-inline-insert:"]');
            if (activeInsertEditor instanceof Element) {
                _bindPendingStageEditorControls(activeInsertEditor);
            }
        }
        const activeCanvasRoot = contentEl.querySelector('.kit-workflow-canvas');
        if (activeCanvasRoot && typeof activeCanvasRoot.__workflowCanvasSync === 'function') {
            activeCanvasRoot.__workflowCanvasSync({
                scene: workflow.scene,
                selection: _surfaceSelection(),
                viewportState: { zoom: _canvasZoomValue() },
                mapVisible: true,
            });
        }
        if (previousCanvasRoot && previousCanvasRoot !== activeCanvasRoot && typeof previousCanvasRoot.__workflowCanvasCleanup === 'function') {
            previousCanvasRoot.__workflowCanvasCleanup();
        }
        contentEl.__workflowCanvasRoot = activeCanvasRoot || null;
        _lifecycleHeaderRef = contentEl.querySelector('.kit-lifecycle-header');
        } finally {
            renderInFlight = false;
            if (renderQueued) {
                renderQueued = false;
                queueMicrotask(() => render());
            }
        }
    }

    async function loadProtocols({ quiet = false } = {}) {
        const next = await API.listProtocols({ limit: 200 });
        protocols = next;
        if (currentProtocolId && !protocols.some((item) => item.protocol_id === currentProtocolId)) {
            currentProtocolId = '';
            currentProtocol = null;
        }
        _writeState();
        if (!quiet) render();
    }

    async function loadAuthoringManifest() {
        authoringManifest = await API.getProtocolAuthoringManifest();
    }

    async function loadAssignmentCatalog({ quiet = true } = {}) {
        try {
            const [agentData, skillData] = await Promise.all([
                API.listAgents({ limit: 100 }),
                API.listRoutingSkills(),
            ]);
            availableAgents = Array.isArray(agentData?.agents) ? agentData.agents : (Array.isArray(agentData) ? agentData : []);
            connectedAgents = availableAgents.filter((agent) =>
                String(agent?.connectivity_state || '').trim().toLowerCase() === 'connected',
            );
            availableRoutingSkills = (Array.isArray(skillData?.routing_skills) ? skillData.routing_skills : (Array.isArray(skillData) ? skillData : []))
                .filter((item) => _isAuthoringRoutingSkill(item));
            if (currentProtocol && !protocolDetailLoading) {
                render();
            }
        } catch (err) {
            availableAgents = [];
            connectedAgents = [];
            availableRoutingSkills = [];
            if (!quiet) {
                UI.reportError('Failed to load assignment options', err);
            }
        }
    }

    async function loadProtocolDetail() {
        if (!currentProtocolId) {
            currentProtocol = null;
            protocolDetailLoading = false;
            _writeState();
            render();
            return;
        }
        protocolDetailLoading = true;
        render();
        currentProtocol = await API.getProtocol(currentProtocolId);
        _applyServerDetail(currentProtocol);
        protocolDetailLoading = false;
        _writeState();
        render();
    }

    async function bootstrap() {
        UI.reconcileChildren(contentEl, [UI.renderEmptyState('Loading protocols…', true)]);
        try {
            await Promise.all([loadProtocols({ quiet: true }), loadAuthoringManifest(), loadAssignmentCatalog({ quiet: true })]);
            if (currentProtocolId) {
                await loadProtocolDetail();
            } else {
                render();
            }
        } catch (err) {
            UI.reconcileChildren(contentEl, [UI.createErrorCard('Failed to load protocols: ' + err.message, bootstrap)]);
        }
    }

    cleanups.add(() => {
        _clearAutosaveTimer();
        if (contentEl.__workflowCanvasRoot?.__workflowCanvasCleanup) {
            contentEl.__workflowCanvasRoot.__workflowCanvasCleanup();
        }
        currentProtocol = null;
        _lifecycleHeaderRef = null;
    });
    const onResize = () => render();
    window.addEventListener('resize', onResize);
    cleanups.add(() => window.removeEventListener('resize', onResize));

    UI.subscribeWithRefresh(cleanups, 'protocols', () => loadProtocols({ quiet: false }), 350);
    container.__routeReady = bootstrap();
}

function renderProtocolRuns(container) {
    const cleanups = UI.beginCleanupScope();
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }

    let runs = [];
    let protocolIssues = [];
    let currentRunId = UI.readQueryParam('run_id', '');
    let currentRun = null;
    let currentIssues = [];
    let lastRunEvent = null;
    let runDetailLoading = false;
    let runSearch = '';
    let runStatusFilter = UI.readQueryParam('status', '');
    let issueKindFilter = _protocolIssueFilterValue(UI.readQueryParam('issue_kind', ''));
    let timelineParticipantFilter = '';
    let currentRunSubscription = null;

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Runs</h2><p>Inspect live workflow execution, issue triage, artifacts, and operator actions without the authoring surface mixed in.</p>';
    container.appendChild(header);

    const shell = document.createElement('section');
    shell.className = 'admin-shell protocol-route-shell';
    container.appendChild(shell);

    const contentEl = document.createElement('div');
    contentEl.className = 'protocol-surface-shell';
    shell.appendChild(contentEl);

    function _writeState({ push = false } = {}) {
        UI.updateQueryParams({
            protocol_id: '',
            run_id: currentRunId || '',
            status: runStatusFilter || '',
            issue_kind: issueKindFilter || '',
            entry_agent_id: '',
        }, { replace: !push });
    }

    function _bindRunSubscription() {
        if (currentRunSubscription) {
            currentRunSubscription();
            currentRunSubscription = null;
        }
        if (!currentRunId || typeof WS === 'undefined' || !WS || typeof WS.subscribe !== 'function') {
            return;
        }
        currentRunSubscription = WS.subscribe(`protocol-run:${currentRunId}`, (msg) => {
            if (msg && msg.type === 'event' && msg.data && msg.data.event_kind) {
                lastRunEvent = msg.data;
            }
            void Promise.all([
                loadRunDetail({ soft: true }),
                loadRuns(),
                loadIssues({ rerender: true }),
            ]);
        });
    }

    function _filteredIssues() {
        return (protocolIssues || []).filter((item) => {
            const haystack = [
                item.protocol_display_name || '',
                item.protocol_id || '',
                item.issue_detail || '',
                item.issue_code || '',
                item.issue_kind || '',
                item.stage_key || '',
                item.protocol_run_id || '',
            ].join(' ').toLowerCase();
            return !runSearch || haystack.includes(runSearch.toLowerCase());
        });
    }

    function _issueRows() {
        return _filteredIssues().map((item) => UI.renderListRow({
            label: `${String(item.issue_kind || '').replace(/_/g, ' ')} · ${item.protocol_display_name || item.protocol_id || 'Protocol issue'}`,
            sublabel: [
                item.stage_key ? `stage ${item.stage_key}` : '',
                item.issue_detail || item.issue_code || '',
            ].filter(Boolean).join(' · '),
            badgeText: item.issue_code || item.stage_key || '',
            className: item.protocol_run_id === currentRunId ? 'is-selected' : '',
            onClick: () => {
                currentRunId = item.protocol_run_id;
                currentRun = null;
                currentIssues = [];
                lastRunEvent = null;
                runDetailLoading = true;
                _writeState({ push: true });
                renderRunsRoute();
                void loadRunDetail();
            },
        }));
    }

    function _buildRunSummaryGrid() {
        const run = currentRun.run;
        const maxRounds = Number(run.max_review_rounds || 0);
        return Kit.runSummary({
            run: {
                id: run.protocol_run_id,
                status: run.status,
                version: run.version || 1,
                current_stage_key: run.current_stage_key,
                review_loop: `${Number(run.current_review_rounds || 0)} / ${maxRounds || 'n/a'}`,
                workspace_ref: run.workspace_ref || 'default',
                root_conversation_id: run.root_conversation_id,
                notes: run.termination_summary || run.blocked_detail || '',
            },
            liveEventText: (lastRunEvent && String(lastRunEvent.protocol_run_id || '') === String(run.protocol_run_id || ''))
                ? `Live update: ${String(lastRunEvent.event_kind || '').replace(/_/g, ' ')} · ${lastRunEvent.reason || ''}`
                : '',
        });
    }

    function _runActionSpecs() {
        return [
            {
                action: 'retry',
                label: 'Retry',
                note: 'Retry creates a new execution of the current stage using the same protocol definition and workspace context.',
                confirmLabel: 'Retry run',
                successMessage: 'Protocol run retry submitted.',
                requireReason: false,
                enabled: ['blocked', 'failed', 'cancelled'].includes(String(currentRun?.run.status || '')),
            },
            {
                action: 'accept',
                label: 'Accept',
                note: 'Accept forces the current review or acceptance stage forward using the reason you provide as audit context.',
                confirmLabel: 'Accept run',
                successMessage: 'Protocol run accepted.',
                requireReason: false,
                enabled: !['completed', 'failed', 'cancelled'].includes(String(currentRun?.run.status || '')),
            },
            {
                action: 'send-back',
                label: 'Send back',
                note: 'Send back forces a revise decision and requires a short reason that explains what needs to change.',
                confirmLabel: 'Send back',
                successMessage: 'Protocol run sent back.',
                requireReason: true,
                enabled: !['completed', 'failed', 'cancelled'].includes(String(currentRun?.run.status || '')),
            },
            {
                action: 'cancel',
                label: 'Cancel',
                note: 'Cancel is destructive for the current run lifecycle and requires a short audit reason.',
                confirmLabel: 'Cancel run',
                successMessage: 'Protocol run cancelled.',
                requireReason: true,
                enabled: !['completed', 'failed', 'cancelled'].includes(String(currentRun?.run.status || '')),
            },
        ];
    }

    function _openRunActionDialog(spec) {
        if (!currentRun) {
            return;
        }
        const form = document.createElement('div');
        form.className = 'studio-dialog-form';

        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = spec.note;
        form.appendChild(note);

        const reasonInput = document.createElement('textarea');
        reasonInput.className = 'guidance-textarea';
        reasonInput.rows = 6;
        reasonInput.placeholder = 'Short reason recorded in the protocol audit trail';
        form.appendChild(reasonInput);

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn';
        cancelBtn.textContent = 'Cancel';
        const confirmBtn = document.createElement('button');
        confirmBtn.type = 'button';
        confirmBtn.className = spec.action === 'cancel' ? 'btn' : 'btn btn-primary';
        confirmBtn.textContent = spec.confirmLabel;
        const view = UI.showDialog(spec.title, form, {
            actions: [cancelBtn, confirmBtn],
            role: 'alertdialog',
            initialFocus: reasonInput,
            maxWidth: '680px',
        });
        cancelBtn.addEventListener('click', () => view.close());
        confirmBtn.addEventListener('click', async () => {
            const reason = String(reasonInput.value || '').trim();
            if (spec.requireReason && !reason) {
                reasonInput.focus();
                return;
            }
            confirmBtn.disabled = true;
            try {
                await API.actOnProtocolRun(
                    currentRun.run.protocol_run_id,
                    spec.action,
                    { reason },
                    {
                        expectedVersion: currentRun.run.version || 1,
                        idempotencyKey: (window.crypto && typeof window.crypto.randomUUID === 'function')
                            ? window.crypto.randomUUID().replace(/-/g, '')
                            : `${Date.now()}${Math.random().toString(16).slice(2)}`,
                    },
                );
                view.close();
                await loadRuns();
                await loadIssues({ rerender: false });
                await loadRunDetail();
                UI.notify(spec.successMessage, 'success');
            } catch (err) {
                if (String(err && err.message || '').includes('409:')) {
                    await loadRunDetail();
                    UI.notify('The run changed before this action was applied. Review the refreshed state and try again.', 'warning');
                } else {
                    UI.reportError(`Failed to ${spec.action.replace('-', ' ')} the protocol run`, err, {
                        context: 'Protocol run action failed',
                    });
                }
            }
            confirmBtn.disabled = false;
        });
    }

    function _buildRunActionBar() {
        const runActionBar = document.createElement('div');
        runActionBar.className = 'editor-actions protocol-sticky-actions';
        _runActionSpecs().forEach((spec) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = spec.action === 'cancel' ? 'btn' : 'btn btn-primary';
            btn.textContent = spec.label;
            btn.disabled = !spec.enabled;
            btn.addEventListener('click', () => _openRunActionDialog({
                title: spec.label,
                action: spec.action,
                note: spec.note,
                confirmLabel: spec.confirmLabel,
                successMessage: spec.successMessage,
                requireReason: spec.requireReason,
            }));
            runActionBar.appendChild(btn);
        });

        const exportRunButton = document.createElement('button');
        exportRunButton.type = 'button';
        exportRunButton.className = 'btn';
        exportRunButton.textContent = 'Export run';
        exportRunButton.addEventListener('click', async () => {
            if (!currentRun) {
                return;
            }
            try {
                const exported = await API.exportProtocolRun(currentRun.run.protocol_run_id);
                _downloadProtocolText(
                    `${UI.safeFilename(currentRun.definition?.slug || currentRun.run.protocol_run_id || 'protocol-run')}.protocol-run.json`,
                    JSON.stringify(exported, null, 2),
                    'application/json',
                );
            } catch (err) {
                UI.reportError('Failed to export the protocol run', err, {
                    context: 'Protocol run export failed',
                });
            }
        });
        runActionBar.appendChild(exportRunButton);

        return runActionBar;
    }

    function _buildRunNavigatorPanel() {
        const issueListActive = Boolean(issueKindFilter);
        const panel = document.createElement('section');
        panel.className = 'editor-panel protocol-panel';

        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = issueListActive ? 'Protocol issues' : Kit.dict.label('runs.list.title', 'Runs');
        panel.appendChild(title);

        const issueFilterControl = UI.createSegmentedControl(
            PROTOCOL_ISSUE_FILTER_OPTIONS,
            (value) => {
                issueKindFilter = _protocolIssueFilterValue(value);
                _writeState({ push: true });
                if (issueKindFilter) {
                    void loadIssues({ rerender: true });
                } else {
                    renderRunsRoute();
                }
            },
            { label: 'Run triage focus', value: issueKindFilter || '' },
        );
        panel.appendChild(issueFilterControl.element);

        if (issueListActive) {
            const searchInput = document.createElement('input');
            searchInput.className = 'search-input';
            searchInput.placeholder = 'Search issues';
            searchInput.value = runSearch;
            searchInput.addEventListener('input', () => {
                runSearch = searchInput.value;
                renderRunsRoute();
            });
            panel.appendChild(searchInput);

            const list = document.createElement('div');
            list.className = 'protocol-scroll';
            const rows = _issueRows();
            UI.reconcileChildren(
                list,
                rows.length
                    ? rows
                    : [UI.renderEmptyState(
                        'No blocked runs, lease issues, contract failures, or expired timeouts match this filter.',
                        true,
                    )],
            );
            panel.appendChild(list);
            return panel;
        }

        const listRuns = (runs || []).filter((item) => {
            if (runStatusFilter && String(item.status || '') !== runStatusFilter) return false;
            if (!runSearch) return true;
            const haystack = [
                item.problem_statement || '',
                item.protocol_run_id || '',
                item.current_stage_key || '',
                item.status || '',
                item.protocol_id || '',
            ].join(' ').toLowerCase();
            return haystack.includes(runSearch.toLowerCase());
        }).map((item) => ({
            id: item.protocol_run_id,
            status: item.status,
            title: item.current_stage_key
                ? `${item.current_stage_key} · ${item.status}`
                : (item.status || 'queued'),
            subtitle: item.problem_statement || item.protocol_run_id,
            badge: item.protocol_id || '',
            raw: item,
        }));

        panel.appendChild(Kit.runsList({
            runs: listRuns,
            search: runSearch,
            statusFilter: runStatusFilter,
            selectedId: currentRunId,
            onSearch: (value) => {
                runSearch = value;
                renderRunsRoute();
            },
            onStatusFilter: (value) => {
                runStatusFilter = value || '';
                _writeState({ push: true });
                renderRunsRoute();
            },
            onSelect: (run) => {
                currentRunId = run.id;
                currentRun = null;
                currentIssues = [];
                lastRunEvent = null;
                runDetailLoading = true;
                _writeState({ push: true });
                renderRunsRoute();
                void loadRunDetail();
            },
        }));
        return panel;
    }

    function _buildRunDetailPanel() {
        const issueListActive = Boolean(issueKindFilter);
        const detailPanel = document.createElement('section');
        detailPanel.className = 'editor-panel protocol-panel';

        const detailTitle = document.createElement('div');
        detailTitle.className = 'editor-section-title';
        detailTitle.textContent = issueListActive ? 'Issue detail' : 'Run detail';
        detailPanel.appendChild(detailTitle);

        if (runDetailLoading && currentRunId) {
            detailPanel.appendChild(UI.renderEmptyState('Loading run detail…', true));
            return detailPanel;
        }

        if (!currentRun) {
            detailPanel.appendChild(UI.renderEmptyState(
                issueListActive
                    ? 'Select an issue to inspect the affected run and operator actions.'
                    : 'Select a run to inspect state, timeline, artifacts, and operator actions.',
                true,
            ));
            return detailPanel;
        }

        detailPanel.appendChild(_buildRunSummaryGrid());
        detailPanel.appendChild(_buildRunActionBar());

        const { stageRows, transitionRows, participantOptions } = _filteredProtocolTimelineData(currentRun, timelineParticipantFilter);
        const participantControl = UI.createSegmentedControl(
            [{ value: '', label: 'All participants' }, ...participantOptions],
            (value) => {
                timelineParticipantFilter = value || '';
                renderRunsRoute();
            },
            { label: 'Timeline participant filter', value: timelineParticipantFilter || '' },
        );
        detailPanel.appendChild(participantControl.element);

        const stageTitle = document.createElement('div');
        stageTitle.className = 'editor-section-title';
        stageTitle.textContent = 'Stage executions';
        detailPanel.appendChild(stageTitle);

        const stageList = document.createElement('div');
        const stageNodes = stageRows.map((item) => UI.renderListRow({
            label: `${item.stage_key} · ${item.status}`,
            sublabel: [item.participant_key, item.decision_summary || item.failure_detail || item.routed_task_id || '']
                .filter(Boolean)
                .join(' · '),
            badgeText: item.decision || '',
        }));
        UI.reconcileChildren(stageList, stageNodes.length ? stageNodes : [UI.renderEmptyState('No stage executions match this participant filter.', true)]);
        detailPanel.appendChild(stageList);

        const participantTitle = document.createElement('div');
        participantTitle.className = 'editor-section-title';
        participantTitle.textContent = 'Participants';
        detailPanel.appendChild(participantTitle);

        const participantList = document.createElement('div');
        const participantRows = (currentRun.participants || []).map((item) => UI.renderListRow({
            label: `${item.display_name || item.participant_key} · ${item.state || item.resolution_outcome || 'queued'}`,
            sublabel: item.resolution_reason || item.resolved_agent_id || item.session_key || '',
            badgeText: item.resolution_outcome || '',
        }));
        UI.reconcileChildren(participantList, participantRows.length ? participantRows : [UI.renderEmptyState('No participants resolved yet.', true)]);
        detailPanel.appendChild(participantList);

        const artifactTitle = document.createElement('div');
        artifactTitle.className = 'editor-section-title';
        artifactTitle.textContent = 'Artifacts';
        detailPanel.appendChild(artifactTitle);

        const artifactList = document.createElement('div');
        const artifactRows = (currentRun.artifacts || []).map((item) => UI.renderListRow({
            label: `${item.artifact_key} · ${item.verification_state || item.state || 'declared'}`,
            sublabel: _protocolArtifactLabel(item),
            badgeText: item.exists ? 'present' : 'missing',
            badgeClass: item.exists ? 'badge-connected' : 'badge-blocked',
        }));
        UI.reconcileChildren(artifactList, artifactRows.length ? artifactRows : [UI.renderEmptyState('No artifacts recorded yet.', true)]);
        detailPanel.appendChild(artifactList);

        const transitionTitle = document.createElement('div');
        transitionTitle.className = 'editor-section-title';
        transitionTitle.textContent = 'Transitions';
        detailPanel.appendChild(transitionTitle);

        const transitionList = document.createElement('div');
        transitionList.setAttribute('aria-live', 'polite');
        const transitionNodes = transitionRows.map((item) => UI.renderListRow({
            label: `${item.transition_kind} · ${item.decision || 'n/a'}`,
            sublabel: [item.reason || item.actor_ref || '', item.error_code || ''].filter(Boolean).join(' · '),
            badgeText: String(item.metadata_json?.target_agent_id || ''),
        }));
        UI.reconcileChildren(transitionList, transitionNodes.length ? transitionNodes : [UI.renderEmptyState('No transitions match this participant filter.', true)]);
        detailPanel.appendChild(transitionList);

        const issueDetailTitle = document.createElement('div');
        issueDetailTitle.className = 'editor-section-title';
        issueDetailTitle.textContent = 'Support issues';
        detailPanel.appendChild(issueDetailTitle);

        const issueDetailList = document.createElement('div');
        const issueDetailRows = (currentIssues || []).map((item) => UI.renderListRow({
            label: `${String(item.issue_kind || '').replace(/_/g, ' ')} · ${item.issue_code || item.stage_key || 'issue'}`,
            sublabel: item.issue_detail || item.updated_at || '',
            badgeText: item.stage_key || '',
        }));
        UI.reconcileChildren(
            issueDetailList,
            issueDetailRows.length ? issueDetailRows : [UI.renderEmptyState('No protocol issues detected for this run.', true)],
        );
        detailPanel.appendChild(issueDetailList);
        return detailPanel;
    }

    function renderRunsRoute() {
        UI.memoizedRender(contentEl, {
            runs,
            protocolIssues,
            currentRunId,
            currentRun,
            currentIssues,
            lastRunEvent,
            issueKindFilter,
            runStatusFilter,
            runSearch,
            timelineParticipantFilter,
        }, () => {
            const compact = _isCompactViewport();
            const board = document.createElement('div');
            board.className = 'dashboard-board';
            board.dataset.route = 'protocol-runs';
            board.dataset.hasSelection = currentRunId ? 'true' : 'false';
            board.dataset.issueMode = issueKindFilter ? 'true' : 'false';

            const listColumn = document.createElement('div');
            listColumn.className = 'dashboard-column';
            listColumn.appendChild(_buildRunNavigatorPanel());

            const detailColumn = document.createElement('div');
            detailColumn.className = 'dashboard-column';
            detailColumn.appendChild(_buildRunDetailPanel());

            board.appendChild(listColumn);
            if (!compact || currentRunId) {
                board.appendChild(detailColumn);
            }
            return board;
        });
    }

    async function loadRuns() {
        const response = await API.listProtocolRuns({ limit: 50 });
        runs = response.runs || response || [];
        if (currentRunId && !runs.some((item) => item.protocol_run_id === currentRunId)) {
            currentRunId = '';
            currentRun = null;
            currentIssues = [];
            lastRunEvent = null;
        }
        _writeState();
        renderRunsRoute();
    }

    async function loadIssues({ rerender = true } = {}) {
        const response = await API.listProtocolIssues({
            limit: 50,
            issue_kind: _protocolIssueApiValue(issueKindFilter),
        });
        protocolIssues = response.issues || response || [];
        if (rerender) {
            renderRunsRoute();
        }
    }

    async function loadRunDetail({ soft = false } = {}) {
        if (!currentRunId) {
            currentRun = null;
            currentIssues = [];
            lastRunEvent = null;
            runDetailLoading = false;
            _writeState();
            _bindRunSubscription();
            renderRunsRoute();
            return;
        }
        try {
            runDetailLoading = true;
            const [runDetail, issues] = await Promise.all([
                API.getProtocolRun(currentRunId),
                API.listProtocolIssues({ protocol_run_id: currentRunId, limit: 50 }),
            ]);
            currentRun = runDetail;
            currentIssues = issues.issues || issues || [];
            runDetailLoading = false;
            _writeState();
            _bindRunSubscription();
            renderRunsRoute();
        } catch (err) {
            runDetailLoading = false;
            if (soft && currentRun) {
                UI.reportError('Failed to refresh the protocol run detail', err, {
                    context: 'Protocol run detail refresh failed',
                });
                return;
            }
            throw err;
        }
    }

    async function bootstrap() {
        UI.reconcileChildren(contentEl, [UI.renderEmptyState('Loading protocol runs…', true)]);
        try {
            await Promise.all([loadRuns(), loadIssues({ rerender: false })]);
            if (currentRunId) {
                await loadRunDetail();
            } else {
                renderRunsRoute();
            }
        } catch (err) {
            UI.reconcileChildren(contentEl, [UI.createErrorCard('Failed to load protocol runs: ' + err.message, bootstrap)]);
        }
    }

    cleanups.add(() => {
        if (currentRunSubscription) {
            currentRunSubscription();
            currentRunSubscription = null;
        }
        currentRun = null;
        currentIssues = [];
        protocolIssues = [];
    });

    UI.subscribeWithRefresh(cleanups, 'summary', () => Promise.all([
        loadRuns(),
        loadIssues({ rerender: true }),
    ]), 400);
    UI.subscribeWithRefresh(cleanups, 'agents', async () => {
        await loadAssignmentCatalog({ quiet: true });
        render();
    }, 400);
    UI.subscribeWithRefresh(cleanups, 'protocols', () => Promise.all([
        loadRuns(),
        currentRunId ? loadRunDetail({ soft: true }) : Promise.resolve(),
    ]), 350);

    container.__routeReady = bootstrap();
}
