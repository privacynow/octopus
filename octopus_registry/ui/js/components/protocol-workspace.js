const PROTOCOL_ISSUE_FILTER_OPTIONS = [
    { value: '', label: 'Runs' },
    { value: 'all', label: 'All issues' },
    { value: 'blocked_run', label: 'Blocked runs' },
    { value: 'invalid_contract', label: 'Contract errors' },
    { value: 'stuck_lease', label: 'Stuck leases' },
    { value: 'expired_timeout', label: 'Expired timeouts' },
];

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

function _selectorFromFields(kind, value) {
    const selectorKind = String(kind || '').trim();
    const selectorValue = String(value || '').trim();
    if (!selectorKind || !selectorValue) return null;
    return { kind: selectorKind, value: selectorValue };
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
 * Protocol authoring workspace — one semantic workflow canvas, one inspector,
 * and one synced outline. The old overview/detail/topology split is gone.
 *
 * The canvas carries workflow comprehension. The inspector edits the selected
 * entity. The outline mirrors the same scene and selection model for keyboard
 * and accessibility paths. Roles own steps; assignment rules resolve steps to
 * runtime agents. No raw JSON tab, no viewport-specific editor fork, and no
 * second authoring pipeline.
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
    let selectorPreview = {
        ownerKey: '',
        query: '',
        candidates: [],
        busy: false,
        message: '',
    };
    let renderInFlight = false;
    let renderQueued = false;
    let editorMode = { kind: 'idle', sourceStageKey: '', decision: '' };
    let editorSessionNonce = 0;
    let pendingStage = {
        display_name: '',
        stage_key: '',
        participant_key: '__new__',
        selector_kind: '',
        selector_value: '',
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

    function _isCompactViewport() {
        return window.innerWidth <= 960;
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
            selector_kind: '',
            selector_value: '',
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
        const stageCount = Array.isArray(normalized.stages) ? normalized.stages.length : 0;
        const edgeCount = _transitionEntries(normalized).length;
        let nextStep = '';
        if (!stageCount) nextStep = 'stage';
        else if (!edgeCount) nextStep = 'transition';
        return { participantCount, stageCount, edgeCount, nextStep };
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
        const label = `${_selectorKindLabel(kind)} · ${valueLabel}`;
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
        const previousPendingStage = pendingStage;
        const previousPendingRoute = pendingRoute;
        const previousSelectorPreview = selectorPreview;
        currentProtocol = detail;
        draftRevision = Number(detail?.protocol?.draft_revision || 0) || 0;
        draftConflict = null;
        documentHistory = { undo: [], redo: [] };
        if (!preserveLocalState) {
            _resetSelectorPreview('', '');
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
            pendingStage = previousPendingStage;
            pendingRoute = previousPendingRoute;
            selectorPreview = previousSelectorPreview;
        } else {
            selection = _repairSelection(_selectionFromQuery(draft.document), draft.document);
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
            }, { ifMatch: draftRevision });
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
        _resetSelectorPreview('', '');
        draft = { slug: '', display_name: '', description: '', document: _blankDocument() };
        selection = { sectionKey: 'overview', nodeKey: '' };
        saveState = { state: 'idle', lastSavedAt: '', error: '' };
        canvasViewport = { zoom: 'fit' };
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

    async function _respondRehearsal({ routedTaskId, responseText, stageKey, participantKey }) {
        if (!rehearsal.runId || !routedTaskId) return;
        try {
            await API.respondRehearsalSession(rehearsal.runId, {
                routed_task_id: routedTaskId,
                response_text: String(responseText || ''),
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
            next.selector = _selectorFromFields(value, next.selector?.value || '');
        } else if (kind === 'stage' && key === 'selector_value') {
            next.selector = _selectorFromFields(next.selector?.kind || '', value);
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
        const previewTracksOwner = kind === 'stage' && String(selectorPreview.ownerKey || '') === String(nodeKey || '');
        if (previewTracksOwner) {
            selectorPreview.ownerKey = String(nextNodeKey || '');
            selectorPreview.query = _selectorString(next.selector || null);
            selectorPreview.message = '';
        }
        _commitDocument(doc, {
            nextSelection: { sectionKey: plural, nodeKey: String(nextNodeKey || '') },
        });
        if (kind === 'stage' && (key === 'selector_kind' || key === 'selector_value')) {
            _syncSelectorPreview(String(nextNodeKey || ''), String(next.selector?.kind || ''), String(next.selector?.value || ''));
        }
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
        } else if (key === 'selector_kind' || key === 'selector_value') {
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
        if (['participant_key', 'selector_kind', 'selector_value', 'stage_kind'].includes(String(key || ''))) {
            queueMicrotask(() => render());
        }
        if (key === 'selector_kind' || key === 'selector_value') {
            _syncSelectorPreview('__draft__', pendingStage.selector_kind, pendingStage.selector_value);
        }
    }

    function _commitPendingStageSelector(selectorKind, selectorValue) {
        pendingStage.selector_kind = String(selectorKind || '');
        pendingStage.selector_value = String(selectorValue || '');
        queueMicrotask(() => render());
        _syncSelectorPreview('__draft__', pendingStage.selector_kind, pendingStage.selector_value);
    }

    function _syncPendingStageFromMountedEditor() {
        const editor = contentEl.querySelector('.kit-stage-editor-grid');
        if (!(editor instanceof Element)) return;
        const readValue = (selector) => {
            const control = editor.querySelector(selector);
            return control instanceof HTMLInputElement || control instanceof HTMLTextAreaElement || control instanceof HTMLSelectElement
                ? String(control.value || '')
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
        const advancedKind = readValue('select[aria-label="Advanced strategy"]');
        const primaryKind = readValue('select[aria-label="Strategy"]');
        const selectorKind = String(advancedKind || primaryKind || '').trim().toLowerCase();
        let selectorValue = '';
        if (selectorKind === 'agent') {
            selectorValue = readValue('[aria-label="Choose agent"]');
        } else if (selectorKind === 'skill') {
            selectorValue = readValue('[aria-label="Choose skill"]');
        } else if (selectorKind === 'role') {
            selectorValue = readValue('[aria-label="Choose runtime role tag"]') || readValue('[aria-label="Custom value"]');
        } else {
            selectorValue = readValue('[aria-label="Custom value"]');
        }
        pendingStage.selector_kind = selectorKind;
        pendingStage.selector_value = selectorValue;
    }

    function _bindPendingStageEditorControls(root) {
        if (!(root instanceof Element) || root.dataset.pendingStageBindings === 'true') return;
        root.dataset.pendingStageBindings = 'true';
        const bindText = (selector, key) => {
            const control = root.querySelector(selector);
            if (!(control instanceof HTMLInputElement) && !(control instanceof HTMLTextAreaElement)) return;
            const commit = () => _commitPendingStageField(null, key, control.value);
            control.addEventListener('input', commit);
            control.addEventListener('change', commit);
            control.addEventListener('blur', commit);
        };
        const bindSelect = (selector, key) => {
            const control = root.querySelector(selector);
            if (!(control instanceof HTMLSelectElement)) return;
            control.addEventListener('change', () => _commitPendingStageField(null, key, control.value));
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

        const strategy = root.querySelector('select[aria-label="Strategy"]');
        if (strategy instanceof HTMLSelectElement) {
            strategy.addEventListener('change', () => {
                const nextKind = String(strategy.value || '');
                _commitPendingStageSelector(
                    nextKind,
                    _nextSelectorValueForKind(nextKind, nextKind === String(pendingStage.selector_kind || '') ? pendingStage.selector_value : ''),
                );
            });
        }
        const advancedStrategy = root.querySelector('select[aria-label="Advanced strategy"]');
        if (advancedStrategy instanceof HTMLSelectElement) {
            advancedStrategy.addEventListener('change', () => {
                const nextKind = String(advancedStrategy.value || '').trim();
                const fallbackKind = String(pendingStage.selector_kind || '') || _selectorPrimaryKinds()[0] || '';
                const targetKind = nextKind || fallbackKind;
                _commitPendingStageSelector(
                    targetKind,
                    _nextSelectorValueForKind(targetKind, targetKind === String(pendingStage.selector_kind || '') ? pendingStage.selector_value : ''),
                );
            });
        }
        Array.from(root.querySelectorAll('select[aria-label="Choose agent"], select[aria-label="Choose skill"], select[aria-label="Choose runtime role tag"], input[aria-label="Choose agent"], input[aria-label="Choose skill"], input[aria-label="Choose runtime role tag"], input[aria-label="Custom value"]'))
            .forEach((control) => {
                const commit = () => {
                    const value = control instanceof HTMLInputElement || control instanceof HTMLSelectElement ? control.value : '';
                    _commitPendingStageSelector(String(pendingStage.selector_kind || ''), value);
                };
                control.addEventListener('change', commit);
                if (control instanceof HTMLInputElement) {
                    control.addEventListener('input', commit);
                    control.addEventListener('blur', commit);
                }
            });
    }

    function _commitStageSelector(nodeKey, selectorKind, selectorValue) {
        const doc = _cloneDoc(draft.document);
        const items = [...(doc.stages || [])];
        const idx = items.findIndex((item) => String(item.stage_key || '') === String(nodeKey || ''));
        if (idx < 0) return;
        const next = Object.assign({}, items[idx], {
            selector: _selectorFromFields(selectorKind, selectorValue),
        });
        items[idx] = next;
        doc.stages = items;
        const nextNodeKey = String(nodeKey || '');
        if (String(selectorPreview.ownerKey || '') === nextNodeKey) {
            selectorPreview.ownerKey = nextNodeKey;
            selectorPreview.query = _selectorString(next.selector || null);
            selectorPreview.message = '';
        }
        _commitDocument(doc, {
            nextSelection: { sectionKey: 'stages', nodeKey: nextNodeKey },
        });
        _syncSelectorPreview(nextNodeKey, String(next.selector?.kind || ''), String(next.selector?.value || ''));
    }

    function _startStageInsert({ sourceStageKey = '', decision = '' } = {}) {
        pendingStage = _blankStageDraft(_defaultStageParticipantKey());
        _syncSelectorPreview('__draft__', pendingStage.selector_kind, pendingStage.selector_value);
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
        const creatingRole = String(pendingStage.participant_key || '') === '__new__';
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
            selector: _selectorFromFields(pendingStage.selector_kind, pendingStage.selector_value),
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
        _resetSelectorPreview('', '');
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

    async function _resolveSelectorPreview(ownerKey, selectorValue) {
        selectorPreview = {
            ownerKey: String(ownerKey || ''),
            query: String(selectorValue || ''),
            candidates: [],
            busy: true,
            message: '',
        };
        render();
        try {
            const result = await API.previewSelectorResolution({ selector: selectorValue });
            selectorPreview.candidates = _authoringAssignableCandidates(result?.candidates);
            selectorPreview.message = selectorPreview.candidates.length
                ? ''
                : Kit.dict.label('agents.selector.no_matches');
        } catch (err) {
            selectorPreview.message = err.message || String(err);
        } finally {
            selectorPreview.busy = false;
            render();
        }
    }

    function _resetSelectorPreview(ownerKey = '', query = '') {
        selectorPreview = {
            ownerKey: String(ownerKey || ''),
            query: String(query || ''),
            candidates: [],
            busy: false,
            message: '',
        };
    }

    function _syncSelectorPreview(ownerKey, selectorKind, selectorValue) {
        const query = _selectorString(_selectorFromFields(selectorKind, selectorValue));
        if (!query) {
            _resetSelectorPreview(ownerKey, '');
            render();
            return;
        }
        void _resolveSelectorPreview(ownerKey || '__draft__', query);
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

    function _selectorAvailableKinds() {
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

    function _selectorPreviewState(ownerKey, query) {
        if (String(ownerKey || '') === String(selectorPreview.ownerKey || '')) {
            return {
                query: String(selectorPreview.query || query || ''),
                candidates: selectorPreview.candidates || [],
                busy: Boolean(selectorPreview.busy),
                message: String(selectorPreview.message || ''),
            };
        }
        return {
            query: String(query || ''),
            candidates: [],
            busy: false,
            message: query ? Kit.dict.label('protocol.participant.selector_hint') : '',
        };
    }

    function _selectorPreviewSummary(previewState) {
        if (!previewState?.query) return 'Choose an assignment rule first, then check who currently matches it.';
        if (previewState.busy) return 'Checking current matches…';
        if (Array.isArray(previewState.candidates) && previewState.candidates.length) {
            const count = previewState.candidates.length;
            return `${count} connected agent${count === 1 ? '' : 's'} match right now.`;
        }
        if (previewState.message) return String(previewState.message || '');
        return Kit.dict.label('protocol.participant.selector_hint');
    }

    function _buildSelectorValueField({
        selectorKind = '',
        selectorValue = '',
        readOnly = false,
        onChange = null,
        label = '',
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
        const catalog = _selectorCatalogEntries(normalized);
        if (catalog.length || normalized === 'agent' || normalized === 'skill') {
            const select = document.createElement('select');
            select.className = 'kit-details-control';
            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = `(choose ${_selectorValueLabel(normalized)})`;
            select.appendChild(placeholder);
            catalog.forEach((item) => {
                const option = document.createElement('option');
                option.value = String(item.value || '');
                option.textContent = item.meta ? `${item.label} · ${item.meta}` : item.label;
                if (String(selectorValue || '') === String(item.value || '')) option.selected = true;
                select.appendChild(option);
            });
            if (selectorValue && !catalog.some((item) => item.value === String(selectorValue || ''))) {
                const custom = document.createElement('option');
                custom.value = String(selectorValue || '');
                custom.textContent = `Custom · ${String(selectorValue || '')}`;
                custom.selected = true;
                select.appendChild(custom);
            }
            select.disabled = Boolean(readOnly);
            if (typeof onChange === 'function' && !readOnly) {
                select.addEventListener('change', () => onChange(null, 'selector_value', select.value));
            }
            select.setAttribute('aria-label', valueLabel.textContent);
            row.appendChild(select);
            if (!catalog.length) {
                const hint = document.createElement('p');
                hint.className = 'kit-selector-editor-note';
                hint.textContent = _selectorCatalogEmptyHint(normalized);
                block.appendChild(hint);
            }
        } else {
            const input = document.createElement('input');
            input.type = 'text';
            input.className = 'kit-details-control';
            input.placeholder = Kit.dict.label('protocol.participant.selector_value.placeholder', 'e.g. legal-review, approver, m1');
            input.value = String(selectorValue || '');
            input.readOnly = Boolean(readOnly);
            if (typeof onChange === 'function' && !readOnly) {
                const commit = () => onChange(null, 'selector_value', input.value);
                input.addEventListener('change', commit);
                input.addEventListener('blur', commit);
            }
            input.setAttribute('aria-label', valueLabel.textContent);
            row.appendChild(input);
            const hint = document.createElement('p');
            hint.className = 'kit-selector-editor-note';
            hint.textContent = _selectorCatalogEmptyHint(normalized);
            block.appendChild(hint);
        }
        block.prepend(row);
        return { element: block, catalog };
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
        selectorKind = '',
        selectorValue = '',
        previewKey = '',
        readOnly = false,
        onChange = null,
        onSelectorChange = null,
        showAllPrimaryValues = false,
    } = {}) {
        const wrap = document.createElement('section');
        wrap.className = 'kit-selector-editor';
        if (showAllPrimaryValues) wrap.dataset.showAllPrimary = 'true';
        const emit = (key, value) => {
            if (typeof onChange === 'function') onChange(null, key, value);
        };
        const emitSelector = (kind, value) => {
            if (typeof onSelectorChange === 'function') {
                onSelectorChange(String(kind || ''), String(value || ''));
                return;
            }
            emit('selector_kind', kind);
            emit('selector_value', value);
        };

        const heading = document.createElement('div');
        heading.className = 'kit-selector-editor-head';
        const copy = document.createElement('p');
        copy.className = 'kit-stage-routing-copy';
        copy.textContent = 'Choose how this step resolves at run time. Start with the available agent or skill list, then use Advanced assignment only when the default path is not enough.';
        heading.appendChild(copy);
        wrap.appendChild(heading);

        const normalizedKind = String(selectorKind || '').trim().toLowerCase();
        const primaryKinds = _selectorPrimaryKinds();
        const advancedKinds = _selectorAdvancedKinds();
        const primaryKind = _isPrimarySelectorKind(normalizedKind) ? normalizedKind : '';
        const primaryCatalog = primaryKind ? _selectorCatalogEntries(primaryKind) : [];

        const strategyRow = document.createElement('div');
        strategyRow.className = 'kit-details-row';
        const strategyLabel = document.createElement('label');
        strategyLabel.className = 'kit-details-label';
        strategyLabel.textContent = Kit.dict.label('protocol.participant.selector_strategy.label', 'Strategy');
        strategyRow.appendChild(strategyLabel);
        const strategyControl = document.createElement('select');
        strategyControl.className = 'kit-details-control';
        const blankStrategy = document.createElement('option');
        blankStrategy.value = '';
        blankStrategy.textContent = '(choose assignment strategy)';
        strategyControl.appendChild(blankStrategy);
        _selectorKindOptions(primaryKinds).forEach((item) => {
            const option = document.createElement('option');
            option.value = String(item.value || '');
            option.textContent = String(item.label || item.value || '');
            if (primaryKind === String(item.value || '')) option.selected = true;
            strategyControl.appendChild(option);
        });
        strategyControl.disabled = Boolean(readOnly);
        strategyControl.setAttribute('aria-label', strategyLabel.textContent);
        if ((typeof onChange === 'function' || typeof onSelectorChange === 'function') && !readOnly) {
            strategyControl.addEventListener('change', () => {
                const nextKind = String(strategyControl.value || '');
                emitSelector(nextKind, _nextSelectorValueForKind(nextKind, nextKind === normalizedKind ? selectorValue : ''));
            });
        }
        strategyRow.appendChild(strategyControl);
        wrap.appendChild(strategyRow);

        if (showAllPrimaryValues) {
            primaryKinds.forEach((kind) => {
                const { element } = _buildSelectorValueField({
                    selectorKind: kind,
                    selectorValue: String(normalizedKind || '') === String(kind || '') ? selectorValue : '',
                    readOnly,
                    onChange,
                    label: `Choose ${_selectorValueLabel(kind)}`,
                });
                element.dataset.selectorKind = String(kind || '');
                wrap.appendChild(element);
            });
        } else if (primaryKind) {
            const { element } = _buildSelectorValueField({
                selectorKind: primaryKind,
                selectorValue,
                readOnly,
                onChange,
                label: `Choose ${_selectorValueLabel(primaryKind)}`,
            });
            wrap.appendChild(element);
        } else {
            const note = document.createElement('p');
            note.className = 'kit-selector-editor-note';
            note.textContent = normalizedKind
                ? 'This step currently uses an advanced assignment. Edit it below.'
                : 'Choose a strategy above to start assigning this step.';
            wrap.appendChild(note);
        }

        const advanced = document.createElement('details');
        advanced.className = 'kit-selector-editor-override';
        advanced.open = Boolean(
            (normalizedKind && !_isPrimarySelectorKind(normalizedKind))
            || (primaryCatalog.length && selectorValue && !primaryCatalog.some((item) => item.value === String(selectorValue || ''))),
        );
        const advancedSummary = document.createElement('summary');
        advancedSummary.className = 'kit-stage-editor-summary';
        const advancedTitle = document.createElement('h4');
        advancedTitle.className = 'kit-stage-editor-title';
        advancedTitle.textContent = Kit.dict.label('protocol.participant.selector_advanced.label', 'Advanced assignment');
        advancedSummary.appendChild(advancedTitle);
        advanced.appendChild(advancedSummary);
        const advancedBody = document.createElement('div');
        advancedBody.className = 'kit-selector-editor-override-body';
        const advancedNote = document.createElement('p');
        advancedNote.className = 'kit-selector-editor-note';
        advancedNote.textContent = 'Use this only when you need a runtime role tag or a custom value that is not in the default picker.';
        advancedBody.appendChild(advancedNote);

        if (advancedKinds.length) {
            const advancedKindRow = document.createElement('div');
            advancedKindRow.className = 'kit-details-row';
            const advancedKindLabel = document.createElement('label');
            advancedKindLabel.className = 'kit-details-label';
            advancedKindLabel.textContent = Kit.dict.label('protocol.participant.selector_advanced.strategy', 'Advanced strategy');
            advancedKindRow.appendChild(advancedKindLabel);
            const advancedKindControl = document.createElement('select');
            advancedKindControl.className = 'kit-details-control';
            const defaultOption = document.createElement('option');
            defaultOption.value = '';
            defaultOption.textContent = '(use the default strategy above)';
            advancedKindControl.appendChild(defaultOption);
            _selectorKindOptions(advancedKinds).forEach((item) => {
                const option = document.createElement('option');
                option.value = String(item.value || '');
                option.textContent = String(item.label || item.value || '');
                if (String(normalizedKind || '') === String(item.value || '')) option.selected = true;
                advancedKindControl.appendChild(option);
            });
            advancedKindControl.disabled = Boolean(readOnly);
            advancedKindControl.setAttribute('aria-label', advancedKindLabel.textContent);
            if ((typeof onChange === 'function' || typeof onSelectorChange === 'function') && !readOnly) {
                advancedKindControl.addEventListener('change', () => {
                    const nextKind = String(advancedKindControl.value || '').trim();
                    const fallbackKind = primaryKind || _selectorPrimaryKinds()[0] || '';
                    const targetKind = nextKind || fallbackKind;
                    emitSelector(targetKind, _nextSelectorValueForKind(targetKind, targetKind === normalizedKind ? selectorValue : ''));
                });
            }
            advancedKindRow.appendChild(advancedKindControl);
            advancedBody.appendChild(advancedKindRow);
        }

        const advancedKind = normalizedKind && !_isPrimarySelectorKind(normalizedKind) ? normalizedKind : '';
        if (advancedKind) {
            const { element, catalog } = _buildSelectorValueField({
                selectorKind: advancedKind,
                selectorValue,
                readOnly,
                onChange,
                label: `Choose ${_selectorValueLabel(advancedKind)}`,
            });
            advancedBody.appendChild(element);
            if (catalog.length) {
                advancedBody.appendChild(_buildSelectorManualOverrideField({
                    selectorValue,
                    readOnly,
                    onChange,
                    label: Kit.dict.label('protocol.participant.selector_override.label', 'Custom value'),
                }));
            }
        } else if (primaryKind && primaryCatalog.length) {
            advancedBody.appendChild(_buildSelectorManualOverrideField({
                selectorValue,
                readOnly,
                onChange,
                label: Kit.dict.label('protocol.participant.selector_override.label', 'Custom value'),
            }));
        }
        advanced.appendChild(advancedBody);
        wrap.appendChild(advanced);

        const query = _selectorString(_selectorFromFields(selectorKind, selectorValue));
        if (query) {
            const previewState = _selectorPreviewState(previewKey || '__draft__', query);
            const previewWrap = document.createElement('details');
            previewWrap.className = 'kit-selector-editor-preview';
            previewWrap.open = Boolean(!readOnly && normalizedKind === 'skill');
            const previewSummary = document.createElement('summary');
            previewSummary.className = 'kit-stage-editor-summary';
            const previewTitle = document.createElement('h4');
            previewTitle.className = 'kit-stage-editor-title';
            previewTitle.textContent = Kit.dict.label('protocol.participant.selector_preview.label', 'Who matches right now');
            previewSummary.appendChild(previewTitle);
            const previewStatus = document.createElement('p');
            previewStatus.className = 'kit-selector-editor-note';
            previewStatus.textContent = _selectorPreviewSummary(previewState);
            previewSummary.appendChild(previewStatus);
            previewWrap.appendChild(previewSummary);
            const handleCandidateSelect = !readOnly && normalizedKind === 'skill'
                ? (candidate) => {
                    const targetValue = String(candidate?.slug || candidate?.agent_id || '').trim();
                    if (!targetValue) return;
                    emit('selector_kind', 'agent');
                    emit('selector_value', targetValue);
                }
                : null;
            previewWrap.appendChild(Kit.selectorResolutionPreview({
                selector: previewState.query,
                candidates: previewState.candidates,
                busy: previewState.busy,
                message: previewState.message,
                onSuggestionSelect: handleCandidateSelect,
                showForm: false,
                showSuggestions: false,
                title: Kit.dict.label('protocol.participant.selector_preview.label', 'Who matches right now'),
                help: Kit.dict.help('protocol.participant.selector_preview.help')
                    || 'Matches update after you choose an agent or skill value.',
                emptyHint: Kit.dict.label('protocol.participant.selector_hint'),
                resultTitle: handleCandidateSelect ? 'Matching agents — choose one to pin this step' : 'Matching agents',
            }));
            wrap.appendChild(previewWrap);
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
        return editorMode.kind === 'idle' && !stageCount
            ? {
                active: true,
                title: Kit.dict.label('protocol.canvas.empty.title'),
                body: 'Start by adding the first step. Choose an existing owner role or create a new role inline as part of the step.',
                actions: [
                    { label: Kit.dict.label('protocol.stages.add'), onClick: () => _startStageInsert() },
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
            selectedStageAnchor = _defaultStageInsertAnchor(anchorStage, projection);
        } else if (selection.sectionKey === 'segments' && activeSegment?.endStageKey) {
            const anchorStage = (draft.document.stages || []).find((item) =>
                String(item.stage_key || '') === String(activeSegment.endStageKey || ''),
            ) || null;
            selectedStageAnchor = anchorStage ? _defaultStageInsertAnchor(anchorStage, projection) : null;
            insertLabel = `Insert after ${String(activeSegment.label || 'section')}`;
        }
        const insertAnchor = selectedTransition
            ? {
                sourceStageKey: selectedTransition.from_stage_key,
                decision: selectedTransition.decision,
            }
            : selectedStageAnchor;
        return [
            ...(selection.sectionKey !== 'overview' ? [{
                label: 'Show full workflow',
                tone: 'btn-small',
                onClick: () => {
                    selection = { sectionKey: 'overview', nodeKey: '' };
                    render();
                },
            }] : []),
            {
                label: insertAnchor ? insertLabel : Kit.dict.label('protocol.stages.add'),
                tone: 'btn-small',
                onClick: () => _startStageInsert(insertAnchor || {}),
                disabled: !canMutate,
            },
            ...(rehearsal.runId ? [{
                label: editorMode.kind === 'rehearse' ? 'Back to authoring' : 'View rehearsal',
                tone: 'btn-small',
                onClick: () => _setEditorMode({ kind: editorMode.kind === 'rehearse' ? 'idle' : 'rehearse' }),
            }] : []),
        ];
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
            title: 'Workflow canvas',
            subtitle: 'Read the workflow here. Select a section or step to inspect local routes and edit in the inspector.',
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
            title: 'Workflow canvas',
            subtitle: `Focused on ${String(activeSegment?.label || 'section')}. Inspect local routes here and edit the selected item in the inspector.`,
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

    function _surfaceCanvasEl(workflow) {
        return Kit.workflowCanvas({
            scene: workflow.scene,
            toolbarActions: workflow.toolbarActions,
            firstRun: workflow.firstRun,
            mode: 'graph',
            editorMode,
            viewState: workflow.viewState,
            viewportState: { zoom: _canvasZoomValue() },
            onViewportChange: (zoom) => _setCanvasViewport(zoom),
            selection: {
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
            },
            onSelect: ({ kind, id }) => {
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
            },
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

    function _stageEditorHero(target) {
        const hero = document.createElement('section');
        hero.className = 'kit-stage-editor-hero';

        const title = document.createElement('h3');
        title.className = 'kit-stage-editor-hero-title';
        title.textContent = String(target?.display_name || target?.stage_key || 'Untitled step');
        hero.appendChild(title);

        const meta = document.createElement('div');
        meta.className = 'kit-stage-editor-hero-meta';

        [
            _participantDisplayName(target?.participant_key, draft.document),
            _stageAssignmentSummary(target),
            String(target?.stage_kind || 'work') !== 'work'
                ? Kit.dict.label(`protocol.stage.kind.${String(target?.stage_kind || 'work')}`, _titleCaseWords(target?.stage_kind || 'work'))
                : '',
            `${Object.keys(target?.transitions || {}).length} route${Object.keys(target?.transitions || {}).length === 1 ? '' : 's'}`,
            ((target?.inputs || []).length || (target?.outputs || []).length)
                ? `${(target?.inputs || []).length} read · ${(target?.outputs || []).length} write`
                : '',
        ].filter(Boolean).forEach((item) => {
            const chip = document.createElement('span');
            chip.className = 'kit-stage-editor-hero-chip';
            chip.textContent = String(item || '');
            meta.appendChild(chip);
        });
        hero.appendChild(meta);

        const note = document.createElement('p');
        note.className = 'kit-stage-editor-hero-note';
        note.textContent = 'Edit ownership, routing, artifacts, and instructions here. The canvas stays in sync.';
        hero.appendChild(note);

        return hero;
    }

    function _segmentInspectorEl(segment, projection, nodeStates = {}) {
        const visibleStages = _segmentStageList(segment);
        const panel = document.createElement('section');
        panel.className = 'kit-protocol-segment-panel';

        const head = document.createElement('div');
        head.className = 'kit-protocol-segment-head';
        const title = document.createElement('h3');
        title.className = 'kit-stage-editor-hero-title';
        title.textContent = String(segment?.label || 'Section');
        head.appendChild(title);
        const subtitle = document.createElement('p');
        subtitle.className = 'kit-stage-editor-hero-note';
        subtitle.textContent = visibleStages.length
            ? 'Select a supporting step below to edit it or inspect its routes.'
            : 'This section currently resolves through its primary step.';
        head.appendChild(subtitle);
        panel.appendChild(head);

        const meta = document.createElement('div');
        meta.className = 'kit-stage-editor-hero-meta';
        [
            ...(segment?.incomingSegments || []).map((segmentId) => {
                const source = projection.segmentsById.get(String(segmentId || ''));
                return source ? `From ${source.label}` : '';
            }),
            ...Array.from(new Set((segment?.outgoingEdges || [])
                .filter((edge) => edge.targetKind === 'segment')
                .map((edge) => String(projection.segmentsById.get(edge.targetKey)?.label || ''))
                .filter(Boolean)))
                .map((label) => `Next ${label}`),
            ..._segmentFinishLabels(segment),
        ].filter(Boolean).forEach((label) => {
            const chip = document.createElement('span');
            chip.className = 'kit-stage-editor-hero-chip';
            chip.textContent = String(label || '');
            meta.appendChild(chip);
        });
        if (meta.childElementCount) {
            panel.appendChild(meta);
        }

        const list = document.createElement('div');
        list.className = 'kit-protocol-segment-steps';
        visibleStages.forEach((stage) => {
            const row = document.createElement('button');
            row.type = 'button';
            row.className = `kit-protocol-segment-step${selection.sectionKey === 'stages' && selection.nodeKey === String(stage.stage_key || '') ? ' is-selected' : ''}`;
            row.dataset.testid = `workflow-segment-step-${String(stage.stage_key || '')}`;
            row.addEventListener('click', () => {
                selection = { sectionKey: 'stages', nodeKey: String(stage.stage_key || '') };
                render();
            });

            const titleRow = document.createElement('div');
            titleRow.className = 'kit-protocol-segment-step-head';
            const label = document.createElement('strong');
            label.className = 'kit-protocol-segment-step-title';
            label.textContent = _segmentStageDisplayLabel(segment, stage);
            titleRow.appendChild(label);
            const state = String(nodeStates?.[String(stage.stage_key || '')] || '');
            if (state) {
                const badge = document.createElement('span');
                badge.className = 'kit-workflow-node-state';
                badge.textContent = state;
                titleRow.appendChild(badge);
            }
            row.appendChild(titleRow);

            const summary = document.createElement('div');
            summary.className = 'kit-protocol-segment-step-meta';
            summary.textContent = _participantDisplayName(stage.participant_key, draft.document) || 'Unassigned';
            row.appendChild(summary);

            list.appendChild(row);
        });
        if (list.childElementCount) {
            panel.appendChild(list);
        }
        return panel;
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
        const shell = document.createElement('div');
        shell.className = 'kit-stage-editor';
        if (!createAction) {
            shell.appendChild(_stageEditorHero(target));
        } else if (createHint) {
            const note = document.createElement('p');
            note.className = 'kit-stage-editor-hero-note';
            note.textContent = String(createHint || '');
            shell.appendChild(note);
        }

        const grid = document.createElement('div');
        grid.className = 'kit-stage-editor-grid';
        if (createAction) {
            grid.dataset.createMode = 'true';
        }

        const summaryActions = [];
        if (createAction) {
            summaryActions.push({ label: 'Create step', tone: 'btn-primary', onClick: createAction });
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
                    { key: 'role_display_name', kind: 'text', required: true, label: 'Role name', help: 'Name the reusable role this step belongs to.', commitOnInput: true },
                    { key: 'role_participant_key', kind: 'text', label: 'Role key', help: 'Internal reference for this role. It is generated from the role name.', commitOnInput: true },
                    { key: 'role_instructions', kind: 'textarea', rows: 3, label: 'Shared instructions', help: 'Optional guidance shared by every step that uses this role.', commitOnInput: true },
                ]),
            });
            const roleSection = _stageEditorSection('New owner role', rolePanel, { wide: true });
            roleSection.classList.add('kit-stage-editor-new-role');
            grid.appendChild(roleSection);
        }
        grid.appendChild(_stageEditorSection('Assignment', _selectorEditor({
            selectorKind: String(target?.selector_kind || ''),
            selectorValue: String(target?.selector_value || ''),
            previewKey: String(target?.stage_key || '__draft__'),
            readOnly,
            onChange: onCommit,
            onSelectorChange: createAction
                ? _commitPendingStageSelector
                : (typeof onCommit === 'function' && target?.stage_key
                    ? (kind, value) => _commitStageSelector(String(target.stage_key || ''), kind, value)
                    : null),
            showAllPrimaryValues: Boolean(createAction),
        }), { wide: true }));

        if (!createAction) {
            grid.appendChild(_stageEditorSection('Routing', _stageRoutingPanel(target, { readOnly, connectAction }), { wide: true }));
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
            open: createAction || Boolean(String(target?.instructions || '').trim()),
        }));

        const artifactsPanel = Kit.detailsPanel({
            target,
            surfaceKey: 'protocol.stage',
            onCommit,
            schema: applyReadOnly([
                { key: 'inputs', kind: 'checklist', options: artifactOptions, labelKey: 'protocol.stage.inputs.label', helpKey: 'protocol.stage.inputs.help' },
                { key: 'outputs', kind: 'checklist', options: artifactOptions, labelKey: 'protocol.stage.outputs.label', helpKey: 'protocol.stage.outputs.help' },
            ]),
        });
        grid.appendChild(_stageEditorSection('Artifacts', artifactsPanel, {
            wide: true,
            collapsible: !createAction,
            open: createAction || Boolean((target?.inputs || []).length || (target?.outputs || []).length),
        }));

        const advancedActions = [];
        if (deleteAction) {
            advancedActions.push({ label: 'Delete step', tone: 'btn-danger', onClick: deleteAction });
        }
        if (cancelAction) {
            advancedActions.push({ label: 'Cancel', onClick: cancelAction });
        }
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
        shell.appendChild(grid);
        return shell;
    }

    function _detailsEl(workflow = null) {
        const doc = draft.document;
        const projection = workflow?.projection || _buildWorkflowProjection(doc);
        const participantCount = Array.isArray(doc.participants) ? doc.participants.length : 0;
        const stageCount = Array.isArray(doc.stages) ? doc.stages.length : 0;
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
        const stageParticipantOptions = editorMode.kind === 'insert-stage'
            ? [...participantOptions, { value: '__new__', label: 'Create new role…' }]
            : participantOptions;
        const kindOptions = _manifestStageKindOptions().map((value) => ({
            value,
            label: Kit.dict.label(`protocol.stage.kind.${value}`, value),
        }));
        const artifactOptions = (doc.artifacts || []).map((item) => ({
            value: String(item.artifact_key || ''),
            label: String(item.display_name || item.artifact_key || ''),
        }));

        const protocolSettingsPanel = () => Kit.detailsPanel({
            target: {
                description: draft.description,
                single_active_writer: Boolean(doc.policies?.single_active_writer ?? true),
                max_review_rounds: Number(doc.policies?.max_review_rounds || 5) || 5,
            },
            surfaceKey: 'protocol',
            onCommit: readOnly ? null : _commitOverview,
            schema: applyReadOnly([
                { key: 'description', kind: 'textarea', rows: 4 },
                ...((doc.stages || []).length ? [
                    { key: 'single_active_writer', kind: 'checkbox', labelKey: 'protocol.policy.single_active_writer.label', helpKey: 'protocol.policy.single_active_writer.help' },
                    { key: 'max_review_rounds', kind: 'text', labelKey: 'protocol.policy.max_review_rounds.label', helpKey: 'protocol.policy.max_review_rounds.help' },
                ] : []),
            ]),
        });

        if (editorMode.kind === 'insert-stage') {
            return _stageEditorShell({
                target: pendingStage,
                participantOptions: stageParticipantOptions,
                kindOptions,
                artifactOptions,
                onCommit: _commitPendingStageField,
                createAction: _confirmStageInsert,
                cancelAction: _cancelStageInsert,
                createHint: _workflowInsertHint(),
            });
        }

        if (editorMode.kind === 'create-route') {
            const sourceStage = (doc.stages || []).find((item) => String(item.stage_key || '') === String(pendingRoute.source_stage_key || ''));
            return _routeEditorPanel({
                target: {
                    source_stage: String(sourceStage?.display_name || sourceStage?.stage_key || ''),
                    decision: String(pendingRoute.decision || ''),
                    target_key: String(pendingRoute.target_key || ''),
                },
                sourceStage,
                projection,
                onCommit: _commitPendingRouteField,
                createAction: _confirmRouteInsert,
                cancelAction: _cancelRouteInsert,
            });
        }

        if (selection.sectionKey === 'protocol') {
            return protocolSettingsPanel();
        }

        if (selection.sectionKey === 'overview' || !selection.nodeKey) {
            return null;
        }
        if (selection.sectionKey === 'segments') {
            const segment = projection.segmentsById.get(String(selection.nodeKey || ''));
            if (!segment) return Kit.detailsPanel({ target: null, surfaceKey: 'protocol' });
            if (segment.stages?.length === 1) {
                const primaryStageKey = _segmentPrimaryStageKey(segment);
                const target = (doc.stages || []).find((item) => String(item.stage_key) === primaryStageKey);
                if (!target) return Kit.detailsPanel({ target: null, surfaceKey: 'protocol' });
                if (target.selector && String(selectorPreview.ownerKey || '') !== String(primaryStageKey || '')) {
                    _syncSelectorPreview(String(primaryStageKey || ''), String(target.selector.kind || ''), String(target.selector.value || ''));
                }
                return _stageEditorShell({
                    target: {
                        ...target,
                        selector_kind: String(target.selector?.kind || ''),
                        selector_value: String(target.selector?.value || ''),
                    },
                    readOnly,
                    participantOptions,
                    kindOptions,
                    artifactOptions,
                    onCommit: readOnly
                        ? null
                        : (_t, key, value) => _commitNodeField('stage', primaryStageKey, key, value),
                    connectAction: readOnly ? null : () => _startRouteInsert(primaryStageKey),
                    deleteAction: readOnly ? null : () => _confirmStageDelete(primaryStageKey),
                });
            }
            return _segmentInspectorEl(segment, projection, workflow?.nodeStates || {});
        }
        if (selection.sectionKey === 'participants') {
            const target = (doc.participants || []).find((item) => String(item.participant_key) === selection.nodeKey);
            if (!target) return Kit.detailsPanel({ target: null, surfaceKey: 'protocol' });
            return _participantEditorShell({
                target,
                readOnly,
                onCommit: readOnly ? null : (_t, key, value) => _commitNodeField('participant', selection.nodeKey, key, value),
            });
        }
        if (selection.sectionKey === 'stages') {
            const target = (doc.stages || []).find((item) => String(item.stage_key) === selection.nodeKey);
            if (!target) return Kit.detailsPanel({ target: null, surfaceKey: 'protocol' });
            if (target.selector && String(selectorPreview.ownerKey || '') !== String(selection.nodeKey || '')) {
                _syncSelectorPreview(String(selection.nodeKey || ''), String(target.selector.kind || ''), String(target.selector.value || ''));
            }
            return _stageEditorShell({
                target: {
                    ...target,
                    selector_kind: String(target.selector?.kind || ''),
                    selector_value: String(target.selector?.value || ''),
                },
                readOnly,
                participantOptions,
                kindOptions,
                artifactOptions,
                onCommit: readOnly
                    ? null
                    : (_t, key, value) => _commitNodeField('stage', selection.nodeKey, key, value),
                connectAction: readOnly ? null : () => _startRouteInsert(selection.nodeKey),
                deleteAction: readOnly ? null : () => _confirmStageDelete(selection.nodeKey),
            });
        }
        if (selection.sectionKey === 'transitions') {
            const target = _transitionEntries(doc).find((item) => String(item.id || '') === selection.nodeKey);
            if (!target) return Kit.detailsPanel({ target: null, surfaceKey: 'protocol', emptyHint: Kit.dict.label('protocol.details.transition.empty') });
            const sourceStage = (doc.stages || []).find((stage) => String(stage.stage_key || '') === String(target.from_stage_key || ''));
            return _routeEditorPanel({
                target: {
                    source_stage: String(sourceStage?.display_name || sourceStage?.stage_key || target.from_stage_key || ''),
                    decision: String(target.decision || ''),
                    target_key: String(target.target_key || ''),
                },
                sourceStage,
                projection,
                readOnly,
                onCommit: readOnly ? null : (_t, key, value) => _commitTransitionField(selection.nodeKey, key, value),
                insertAction: readOnly ? null : () => _startStageInsert({
                    sourceStageKey: target.from_stage_key,
                    decision: target.decision,
                }),
                deleteAction: readOnly ? null : () => UI.showConfirm(
                    'Remove transition',
                    'Remove this transition from the workflow?',
                    async () => { _deleteTransition(selection.nodeKey); },
                ),
            });
        }
        if (selection.sectionKey === 'artifacts') {
            const target = (doc.artifacts || []).find((item) => String(item.artifact_key) === selection.nodeKey);
            if (!target) return Kit.detailsPanel({ target: null, surfaceKey: 'protocol' });
            const kindOptions = _manifestArtifactKindOptions().map((value) => ({ value, label: String(value) }));
            return Kit.detailsPanel({
                target,
                surfaceKey: 'protocol.artifact',
                onCommit: readOnly ? null : (_t, key, value) => _commitNodeField('artifact', selection.nodeKey, key, value),
                schema: applyReadOnly([
                    { key: 'display_name', kind: 'text', required: true },
                    { key: 'artifact_key', kind: 'text' },
                    { key: 'kind', kind: 'select', options: kindOptions },
                    { key: 'path', kind: 'text', labelKey: 'protocol.artifact.path.label', helpKey: 'protocol.artifact.path.help', placeholderKey: 'protocol.artifact.path.placeholder' },
                    { key: 'description', kind: 'textarea', rows: 3 },
                    { key: 'verify', kind: 'checkbox', labelKey: 'protocol.artifact.verify.label', helpKey: 'protocol.artifact.verify.help' },
                ]),
            });
        }
        return Kit.detailsPanel({ target: null, surfaceKey: 'protocol' });
    }

    function _detailsKey() {
        if (editorMode.kind === 'insert-stage') {
            return `protocol-details:new-stage:${String(editorMode.sourceStageKey || '')}:${String(editorMode.decision || '')}:${String(editorMode.sessionKey || '')}`;
        }
        if (editorMode.kind === 'create-route') {
            return `protocol-details:new-route:${String(pendingRoute.source_stage_key || '')}:${String(pendingRoute.decision || '')}:${String(editorMode.sessionKey || '')}`;
        }
        return `protocol-details:${String(selection.sectionKey || 'overview')}:${String(selection.nodeKey || '')}`;
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

        const canvasColumn = document.createElement('div');
        canvasColumn.className = 'kit-authoring-canvas-column';
        canvasColumn.dataset.key = 'protocol-authoring-canvas-column';
        const canvasRoot = _surfaceCanvasEl(workflow);
        canvasColumn.appendChild(canvasRoot);
        workspace.appendChild(canvasColumn);

        const detailsColumn = document.createElement('div');
        detailsColumn.className = 'kit-authoring-details-column';
        detailsColumn.dataset.key = 'protocol-authoring-details-column';
        const details = _detailsEl(workflow);
        if (details) {
            const detailsKey = _detailsKey();
            details.dataset.key = detailsKey;
            detailsColumn.dataset.key = `protocol-authoring-details-column:${detailsKey}`;
            detailsColumn.appendChild(details);
            workspace.dataset.hasInspector = 'true';
        }
        const validation = _validationEl();
        if (validation) detailsColumn.appendChild(validation);
        if (editorMode.kind === 'rehearse' || rehearsal.runId) {
            detailsColumn.appendChild(Kit.rehearsalPanel({
                runId: rehearsal.runId,
                sessions: rehearsal.sessions,
                scenarios: rehearsal.scenarios,
                onRespond: (payload) => { void _respondRehearsal(payload); },
            }));
        }
        if (detailsColumn.childElementCount) {
            workspace.appendChild(detailsColumn);
        }

        const previousCanvasRoot = contentEl.__workflowCanvasRoot || null;
        UI.reconcileChildren(contentEl, [headerEl, workspace]);
        const activeWorkspace = contentEl.querySelector('.kit-authoring-workspace');
        if (activeWorkspace instanceof Element) {
            const activeDetailsColumn = activeWorkspace.querySelector('.kit-authoring-details-column');
            if (activeDetailsColumn instanceof Element) {
                activeDetailsColumn.remove();
            }
            if (detailsColumn.childElementCount) {
                activeWorkspace.appendChild(detailsColumn);
                if (editorMode.kind === 'insert-stage') {
                    _bindPendingStageEditorControls(detailsColumn);
                }
            }
        }
        const activeCanvasRoot = contentEl.querySelector('.kit-workflow-canvas');
        if (activeCanvasRoot && typeof activeCanvasRoot.__workflowCanvasSync === 'function') {
            activeCanvasRoot.__workflowCanvasSync({
                scene: workflow.scene,
                selection: {
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
                },
                viewportState: { zoom: _canvasZoomValue() },
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
            board.appendChild(detailColumn);
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
