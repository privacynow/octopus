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

function _selectorFieldsFromString(value) {
    const text = String(value || '').trim();
    if (!text) return { kind: '', value: '' };
    const normalized = text.startsWith('@') ? text.slice(1) : text;
    const divider = normalized.indexOf(':');
    if (divider < 0) {
        return { kind: 'agent', value: normalized };
    }
    return {
        kind: normalized.slice(0, divider).trim(),
        value: normalized.slice(divider + 1).trim(),
    };
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
 * Protocol authoring workspace — kit-driven surface.
 *
 * This route is the reference implementation of the authoring kit (see
 * telegram-agent-bot/protocol_kit_plan.md). The workflow graph is the primary
 * authoring surface; details, validation, and rehearsal hang off the same
 * selection model. No section-tab maze, no raw JSON tab, and no second canvas.
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
    let draftConflict = null;
    let selectorPreview = {
        participantKey: '',
        query: '',
        candidates: [],
        busy: false,
        message: '',
    };
    let editorMode = { kind: 'idle', sourceStageKey: '', decision: '' };
    let pendingRole = {
        display_name: '',
        participant_key: '',
        selector_kind: '',
        selector_value: '',
        instructions: '',
    };
    let pendingStage = {
        display_name: '',
        stage_key: '',
        participant_key: '',
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
    let workflowView = { kind: 'detail', segmentId: '' };
    let workflowViewport = { map: 'fit' };
    let workflowViewExplicit = false;

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

    function _workflowViewStorageKey(protocolId = currentProtocolId) {
        const key = String(protocolId || '').trim();
        return key ? `octopus.protocol.workflow-view:${key}` : '';
    }

    function _readWorkflowView(doc = draft.document, protocolId = currentProtocolId) {
        const storageKey = _workflowViewStorageKey(protocolId);
        const fallback = _defaultWorkflowView(doc);
        if (!storageKey) {
            workflowViewExplicit = false;
            return fallback;
        }
        try {
            const raw = window.localStorage.getItem(storageKey);
            if (!raw) {
                workflowViewExplicit = false;
                return fallback;
            }
            const parsed = JSON.parse(raw);
            const kind = String(parsed?.kind || fallback.kind);
            workflowViewExplicit = true;
            return {
                kind: kind === 'process' || kind === 'map' ? kind : 'detail',
                segmentId: String(parsed?.segmentId || ''),
            };
        } catch (_err) {
            workflowViewExplicit = false;
            return fallback;
        }
    }

    function _persistWorkflowView(protocolId = currentProtocolId) {
        const storageKey = _workflowViewStorageKey(protocolId);
        if (!storageKey) return;
        try {
            const kind = String(workflowView.kind || 'detail');
            window.localStorage.setItem(storageKey, JSON.stringify({
                kind: kind === 'process' || kind === 'map' ? kind : 'detail',
                segmentId: String(workflowView.segmentId || ''),
            }));
        } catch (_err) {
            // Best-effort only; workflow chrome must not block authoring.
        }
    }

    function _defaultWorkflowZoom(kind) {
        return String(kind || 'map') === 'map' ? 'fit' : 1;
    }

    function _workflowViewportValue(kind = workflowView.kind) {
        const key = String(kind || 'map');
        return Object.prototype.hasOwnProperty.call(workflowViewport, key)
            ? workflowViewport[key]
            : _defaultWorkflowZoom(key);
    }

    function _setWorkflowViewport(kind, zoom, { renderNow = false } = {}) {
        const key = String(kind || workflowView.kind || 'map');
        workflowViewport = {
            ...workflowViewport,
            [key]: zoom === 'fit' ? 'fit' : Math.max(0.55, Math.min(1.5, Number(zoom || 1) || 1)),
        };
        if (renderNow) render();
    }

    function _setWorkflowView(next, { renderNow = true, persist = true } = {}) {
        workflowView = {
            kind: 'detail',
            segmentId: '',
            ...(next || {}),
        };
        workflowView.kind = workflowView.kind === 'process' || workflowView.kind === 'map' ? workflowView.kind : 'detail';
        workflowView.segmentId = String(workflowView.segmentId || '');
        if (workflowView.kind === 'process') {
            selection = { sectionKey: 'overview', nodeKey: '' };
        }
        if (!Object.prototype.hasOwnProperty.call(workflowViewport, workflowView.kind)) {
            _setWorkflowViewport(workflowView.kind, _defaultWorkflowZoom(workflowView.kind));
        }
        workflowViewExplicit = true;
        if (persist) _persistWorkflowView();
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

    function _blankRoleDraft(seed = {}) {
        return {
            display_name: '',
            participant_key: '',
            selector_kind: '',
            selector_value: '',
            instructions: '',
            ...seed,
        };
    }

    function _blankStageDraft(participantKey = '', seed = {}) {
        return {
            display_name: '',
            stage_key: '',
            participant_key: String(participantKey || ''),
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
        pendingRole = _blankRoleDraft();
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

    function _defaultStageParticipantKey(doc = draft.document) {
        if (selection.sectionKey === 'participants' && selection.nodeKey) {
            return String(selection.nodeKey || '');
        }
        const selectedStage = _selectionStage(doc);
        if (selectedStage?.participant_key) {
            return String(selectedStage.participant_key || '');
        }
        return String(doc.participants?.[0]?.participant_key || '');
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
        if (!participantCount) nextStep = 'participant';
        else if (!stageCount) nextStep = 'stage';
        else if (!edgeCount) nextStep = 'transition';
        return { participantCount, stageCount, edgeCount, nextStep };
    }

    function _defaultWorkflowView(doc = draft.document) {
        const stageCount = Array.isArray(doc?.stages) ? doc.stages.length : 0;
        return {
            kind: stageCount >= 6 ? 'process' : 'detail',
            segmentId: '',
        };
    }

    function _participantDisplayName(participantKey, doc = draft.document) {
        const participant = (doc.participants || []).find((item) => String(item.participant_key || '') === String(participantKey || ''));
        return String(participant?.display_name || participant?.participant_key || participantKey || 'Role').trim();
    }

    function _segmentRoleSummary(roleLabels) {
        const labels = Array.isArray(roleLabels)
            ? roleLabels.map((item) => String(item || '').trim()).filter(Boolean)
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
            const roleKeys = Array.from(new Set(segmentStages.map((item) => String(item.participant_key || '')).filter(Boolean)));
            const roleLabels = roleKeys.map((key) => _participantDisplayName(key, doc));
            const primaryStage = segmentStages.find((item) => String(item.stage_kind || 'work') === 'work') || segmentStages[0] || stage;
            const stepSummary = `${stageKeys.length} step${stageKeys.length === 1 ? '' : 's'}`;
            const roleSummary = _segmentRoleSummary(roleLabels);
            const segment = {
                id: _segmentId(stageKeys[0]),
                startStageKey: stageKeys[0],
                endStageKey: stageKeys[stageKeys.length - 1],
                stageKeys,
                stages: segmentStages,
                roleKeys,
                primaryParticipantKey: String(primaryStage?.participant_key || segmentStages[0]?.participant_key || ''),
                label: String(primaryStage?.display_name || primaryStage?.stage_key || stageKeys[0] || 'Step'),
                sublabel: roleSummary,
                stepSummary,
                roleSummary,
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
        };
    }

    function _normalizeWorkflowView(projection, currentSelection = selection) {
        const segmentCount = projection.segments.length;
        const defaultView = _defaultWorkflowView(draft.document);
        if (!segmentCount) {
            return { kind: defaultView.kind, segmentId: '' };
        }
        let next = {
            kind: workflowView.kind === 'process' || workflowView.kind === 'map' ? workflowView.kind : 'detail',
            segmentId: String(workflowView.segmentId || ''),
        };
        const selectedSegmentId = currentSelection.sectionKey === 'stages'
            ? projection.stageToSegment.get(String(currentSelection.nodeKey || '')) || ''
            : currentSelection.sectionKey === 'transitions'
                ? projection.stageToSegment.get(String(currentSelection.nodeKey || '').split('::')[0] || '') || ''
                : '';
        if (selectedSegmentId && next.kind === 'detail') next.segmentId = selectedSegmentId;
        if (next.kind === 'detail' && !projection.segmentsById.has(next.segmentId)) {
            next.segmentId = selectedSegmentId || projection.segments[0]?.id || '';
        }
        if (next.kind === 'process' && segmentCount < 2) {
            next = { kind: 'detail', segmentId: projection.segments[0]?.id || '' };
        }
        if (next.kind === 'detail' && !next.segmentId) {
            next.segmentId = projection.segments[0]?.id || '';
        }
        if (next.kind !== 'detail') {
            next.segmentId = next.kind === 'map' ? String(next.segmentId || selectedSegmentId || projection.segments[0]?.id || '') : next.segmentId;
        }
        return next;
    }

    function _focusSegmentSelection(projection, segmentId) {
        const segment = projection.segmentsById.get(String(segmentId || ''));
        if (!segment) return { sectionKey: 'overview', nodeKey: '' };
        const stageKey = String(segment.stageKeys[0] || '');
        return stageKey ? { sectionKey: 'stages', nodeKey: stageKey } : { sectionKey: 'overview', nodeKey: '' };
    }

    function _setDetailSegment(projection, segmentId, { preserveSelection = false } = {}) {
        const nextSegmentId = String(segmentId || '');
        if (!nextSegmentId || !projection.segmentsById.has(nextSegmentId)) return;
        workflowView = { kind: 'detail', segmentId: nextSegmentId };
        workflowViewExplicit = true;
        _persistWorkflowView();
        if (!preserveSelection) {
            selection = _focusSegmentSelection(projection, nextSegmentId);
        }
        render();
    }

    function _applyServerDetail(detail) {
        const previousProtocolId = String(currentProtocol?.protocol?.protocol_id || '');
        currentProtocol = detail;
        draftRevision = Number(detail?.protocol?.draft_revision || 0) || 0;
        draftConflict = null;
        documentHistory = { undo: [], redo: [] };
        selectorPreview = { participantKey: '', query: '', candidates: [], busy: false, message: '' };
        workflowViewport = { map: 'fit' };
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
        selection = _repairSelection(selection, draft.document);
        workflowView = _readWorkflowView(draft.document, String(detail?.protocol?.protocol_id || ''));
        _resetEditorMode();
    }

    function _repairSelection(current, doc) {
        const key = current.sectionKey || 'overview';
        if (key === 'overview') return { sectionKey: 'overview', nodeKey: '' };
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

    // URL state (kept minimal — no protocol_view / section nav)
    function _writeState({ push = false } = {}) {
        UI.updateQueryParams({
            protocol_id: currentProtocolId || '',
            protocol_view: '',
            run_id: '',
            status: '',
            issue_kind: '',
            entry_agent_id: '',
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
            _applyServerDetail(result);
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
        selectorPreview = { participantKey: '', query: '', candidates: [], busy: false, message: '' };
        draft = { slug: '', display_name: '', description: '', document: _blankDocument() };
        selection = { sectionKey: 'overview', nodeKey: '' };
        saveState = { state: 'idle', lastSavedAt: '', error: '' };
        workflowView = _defaultWorkflowView(draft.document);
        workflowViewExplicit = false;
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
        workflowView = _normalizeWorkflowView(_buildWorkflowProjection(draft.document), selection);
        workflowView.kind = 'detail';
        _persistWorkflowView();
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
            if (editorMode.kind === 'connect' && editorMode.sourceStageKey === sourceKey) {
                editorMode = { ...editorMode, sourceStageKey: nextKey };
            }
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
        if (editorMode.kind === 'connect' && !(nextDoc.stages || []).some((stage) => String(stage.stage_key || '') === editorMode.sourceStageKey)) {
            _resetEditorMode();
        }
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
        if (key === 'selector_kind') {
            next.selector = _selectorFromFields(value, next.selector?.value || '');
        } else if (key === 'selector_value') {
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
        if (kind === 'participant' && String(nextNodeKey || '') === selectorPreview.participantKey) {
            selectorPreview.query = _selectorString(next.selector || null);
            selectorPreview.message = '';
        }
        _commitDocument(doc, {
            nextSelection: { sectionKey: plural, nodeKey: String(nextNodeKey || '') },
        });
    }

    async function _applyParticipantSuggestion(participantKey, suggestion) {
        const doc = _cloneDoc(draft.document);
        const items = [...(doc.participants || [])];
        const idx = items.findIndex((item) => String(item.participant_key || '') === String(participantKey || ''));
        if (idx < 0) return;

        const next = { ...items[idx] };
        const selectorKind = String(suggestion?.selectorKind || '').trim();
        const selectorValue = String(suggestion?.selectorValue || '').trim();
        const selector = _selectorFromFields(selectorKind, selectorValue);
        if (!selector) return;

        next.selector = selector;
        if (!String(next.display_name || '').trim()) {
            next.display_name = String(suggestion?.displayName || suggestion?.label || '').trim();
        }

        let nextParticipantKey = String(participantKey || '').trim();
        if (!nextParticipantKey || /^participant_\d+$/i.test(nextParticipantKey)) {
            const preferredKey = String(suggestion?.preferredKey || suggestion?.displayName || suggestion?.label || 'participant').trim();
            const rewritten = _nextAvailableKey(items, 'participant_key', preferredKey, nextParticipantKey);
            next.participant_key = rewritten;
            _rewriteKeyReferences(doc, 'participant', nextParticipantKey, rewritten);
            nextParticipantKey = rewritten;
        }

        items[idx] = next;
        doc.participants = items;
        selectorPreview = {
            participantKey: nextParticipantKey,
            query: _selectorString(selector),
            candidates: [],
            busy: false,
            message: '',
        };
        _commitDocument(doc, {
            nextSelection: { sectionKey: 'participants', nodeKey: nextParticipantKey },
        });
        await _resolveSelectorPreview(nextParticipantKey, _selectorString(selector));
    }

    function _roleDraftFromSuggestion(suggestion) {
        const displayName = String(suggestion?.displayName || suggestion?.label || '').trim();
        return _blankRoleDraft({
            display_name: displayName,
            participant_key: _slugSuggestion(String(suggestion?.preferredKey || displayName || 'role')),
            selector_kind: String(suggestion?.selectorKind || ''),
            selector_value: String(suggestion?.selectorValue || ''),
        });
    }

    function _commitPendingRoleField(_target, key, value) {
        if (key === 'display_name') {
            pendingRole.display_name = String(value || '');
            if (!String(pendingRole.participant_key || '').trim()) {
                pendingRole.participant_key = _slugSuggestion(pendingRole.display_name);
            }
        } else if (key === 'participant_key') {
            pendingRole.participant_key = _slugSuggestion(value);
        } else if (key === 'selector_kind' || key === 'selector_value') {
            pendingRole[key] = String(value || '');
        } else {
            pendingRole[key] = String(value || '');
        }
        render();
    }

    function _applyRoleDraftSuggestion(suggestion) {
        pendingRole = _roleDraftFromSuggestion(suggestion);
        render();
        const selectorText = _selectorString(_selectorFromFields(pendingRole.selector_kind, pendingRole.selector_value));
        if (selectorText) {
            void _resolveSelectorPreview('__draft__', selectorText);
        }
    }

    function _startRoleInsert(prefill = null) {
        pendingRole = prefill ? _roleDraftFromSuggestion(prefill) : _blankRoleDraft();
        selectorPreview = { participantKey: '', query: '', candidates: [], busy: false, message: '' };
        editorMode = { kind: 'insert-role', sourceStageKey: '', decision: '' };
        render();
        const selectorText = _selectorString(_selectorFromFields(pendingRole.selector_kind, pendingRole.selector_value));
        if (selectorText) {
            void _resolveSelectorPreview('__draft__', selectorText);
        }
    }

    function _confirmRoleInsert() {
        const displayName = String(pendingRole.display_name || '').trim();
        if (!displayName) {
            UI.notify('Give this role a name before adding it to the workflow.', 'warning');
            return;
        }
        const doc = _cloneDoc(draft.document);
        const items = [...(doc.participants || [])];
        const participantKey = _nextAvailableKey(
            items,
            'participant_key',
            String(pendingRole.participant_key || displayName || 'role'),
        );
        doc.participants = [...items, {
            participant_key: participantKey,
            display_name: displayName,
            selector: _selectorFromFields(pendingRole.selector_kind, pendingRole.selector_value),
            instructions: String(pendingRole.instructions || ''),
        }];
        selectorPreview = { participantKey: '', query: '', candidates: [], busy: false, message: '' };
        _resetEditorMode();
        _commitDocument(doc, {
            nextSelection: { sectionKey: 'participants', nodeKey: participantKey },
        });
    }

    function _cancelRoleInsert() {
        selectorPreview = { participantKey: '', query: '', candidates: [], busy: false, message: '' };
        _resetEditorMode();
        render();
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
        } else if (key === 'instructions') {
            pendingStage.instructions = String(value || '');
        } else if (key === 'inputs' || key === 'outputs') {
            pendingStage[key] = Array.isArray(value) ? value.map((item) => String(item || '').trim()).filter(Boolean) : [];
        } else if (key === 'max_rounds' || key === 'timeout_seconds') {
            pendingStage[key] = Number.parseInt(String(value || '0'), 10) || 0;
        }
        render();
    }

    function _startStageInsert() {
        if (!(draft.document.participants || []).length) {
            UI.notify('Add a role before adding a step.', 'warning');
            return;
        }
        pendingStage = _blankStageDraft(_defaultStageParticipantKey());
        editorMode = { kind: 'insert-stage', sourceStageKey: '', decision: '' };
        render();
    }

    function _confirmStageInsert() {
        const displayName = String(pendingStage.display_name || '').trim();
        if (!displayName) {
            UI.notify('Give this step a name before adding it to the workflow.', 'warning');
            return;
        }
        if (!String(pendingStage.participant_key || '').trim()) {
            UI.notify('Choose who owns this step before creating it.', 'warning');
            return;
        }
        const doc = _cloneDoc(draft.document);
        const stageKey = _nextAvailableKey(
            doc.stages || [],
            'stage_key',
            String(pendingStage.stage_key || displayName || 'step'),
        );
        doc.stages = [...(doc.stages || []), {
            stage_key: stageKey,
            display_name: displayName,
            participant_key: String(pendingStage.participant_key || ''),
            stage_kind: String(pendingStage.stage_kind || 'work') || 'work',
            instructions: String(pendingStage.instructions || ''),
            inputs: Array.isArray(pendingStage.inputs) ? pendingStage.inputs : [],
            outputs: Array.isArray(pendingStage.outputs) ? pendingStage.outputs : [],
            transitions: {},
            max_rounds: Number.parseInt(String(pendingStage.max_rounds || '0'), 10) || 0,
            timeout_seconds: Number.parseInt(String(pendingStage.timeout_seconds || '0'), 10) || 0,
        }];
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

    function _startConnectMode(stageKey, decision = '') {
        const doc = draft.document;
        const stage = (doc.stages || []).find((item) => String(item.stage_key || '') === String(stageKey || ''));
        if (!stage) return;
        editorMode = {
            kind: 'connect',
            sourceStageKey: String(stage.stage_key || ''),
            decision: String(decision || Object.keys(stage.transitions || {})[0] || _defaultDecisionForStageKind(stage.stage_kind)).trim().toLowerCase(),
        };
        selection = { sectionKey: 'stages', nodeKey: String(stage.stage_key || '') };
        render();
    }

    function _cancelTransitionConnect() {
        _resetEditorMode();
        render();
    }

    function _startRouteInsert(stageKey) {
        const stage = (draft.document.stages || []).find((item) => String(item.stage_key || '') === String(stageKey || ''));
        if (!stage) return;
        pendingRoute = _blankRouteDraft(stage.stage_key, stage.stage_kind);
        selection = { sectionKey: 'stages', nodeKey: String(stage.stage_key || '') };
        editorMode = { kind: 'create-route', sourceStageKey: String(stage.stage_key || ''), decision: String(pendingRoute.decision || '') };
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

    function _commitConnectField(_target, key, value) {
        if (key === 'decision') {
            editorMode = {
                ...editorMode,
                decision: String(value || '').trim().toLowerCase() || _defaultDecisionForStageKind(
                    _selectionStage()?.stage_kind || 'work',
                ),
            };
            render();
        }
    }

    function _connectTransitionTarget(targetKey) {
        if (editorMode.kind !== 'connect' || !editorMode.sourceStageKey) return;
        const doc = _cloneDoc(draft.document);
        const items = [...(doc.stages || [])];
        const idx = items.findIndex((item) => String(item.stage_key || '') === editorMode.sourceStageKey);
        if (idx < 0) {
            _cancelTransitionConnect();
            return;
        }
        const stage = { ...items[idx] };
        const transitions = Object.assign({}, stage.transitions || {});
        transitions[editorMode.decision || _defaultDecisionForStageKind(stage.stage_kind)] = String(targetKey || '');
        stage.transitions = transitions;
        items[idx] = stage;
        doc.stages = items;
        const edgeId = _stageTransitionId(stage.stage_key, editorMode.decision || _defaultDecisionForStageKind(stage.stage_kind));
        _resetEditorMode();
        _commitDocument(doc, { nextSelection: { sectionKey: 'transitions', nodeKey: edgeId } });
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

    async function _resolveSelectorPreview(participantKey, selectorValue) {
        selectorPreview = {
            participantKey: String(participantKey || ''),
            query: String(selectorValue || ''),
            candidates: [],
            busy: true,
            message: '',
        };
        render();
        try {
            const result = await API.previewSelectorResolution({ selector: selectorValue });
            selectorPreview.candidates = Array.isArray(result?.candidates) ? result.candidates : [];
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

    function _participantSelectorSuggestions() {
        const suggestions = [];
        const seen = new Set();
        const pushSuggestion = (entry) => {
            const value = String(entry?.value || '').trim();
            if (!value || seen.has(value)) return;
            seen.add(value);
            suggestions.push(entry);
        };
        (connectedAgents || []).forEach((agent) => {
            const selectorValue = String(agent?.selector || '').trim();
            const selectorRef = selectorValue.startsWith('@') ? selectorValue.slice(1) : selectorValue;
            const normalizedSelector = selectorRef.startsWith('agent:') ? selectorRef.slice('agent:'.length) : selectorRef;
            const agentSlug = String(agent?.slug || normalizedSelector || '').trim();
            const displayName = String(
                agent.display_name
                || (agentSlug ? _titleCaseWords(agentSlug) : '')
                || 'Assigned agent'
            ).trim();
            const selectorQuery = selectorValue || (agentSlug ? `@${agentSlug}` : '');
            if (!selectorQuery) return;
            pushSuggestion({
                label: displayName,
                value: selectorQuery,
                selectorKind: 'agent',
                selectorValue: agentSlug,
                displayName,
                preferredKey: agentSlug || _slugSuggestion(agent.display_name || ''),
            });
        });
        const roleMap = new Map();
        (connectedAgents || []).forEach((agent) => {
            const role = String(agent?.role || '').trim();
            if (!role || roleMap.has(role)) return;
            roleMap.set(role, agent);
        });
        Array.from(roleMap.entries()).slice(0, 4).forEach(([role, agent]) => {
            const roleSelector = String(agent?.role_selector || '').trim();
            if (!roleSelector) return;
            pushSuggestion({
                label: `Any ${_titleCaseWords(role)}`,
                value: roleSelector,
                selectorKind: 'role',
                selectorValue: role,
                displayName: _titleCaseWords(role),
                preferredKey: _slugSuggestion(role),
            });
        });
        [
            {
                label: 'Planner role',
                value: '@skill:planning',
                selectorKind: 'skill',
                selectorValue: 'planning',
                displayName: 'Planner',
                preferredKey: 'planner',
            },
            {
                label: 'Reviewer role',
                value: '@role:reviewer',
                selectorKind: 'role',
                selectorValue: 'reviewer',
                displayName: 'Reviewer',
                preferredKey: 'reviewer',
            },
        ].forEach(pushSuggestion);
        return suggestions;
    }

    function _selectorKindOptions() {
        return (authoringManifest?.selector_kind_options || ['skill', 'role', 'agent']).map((value) => ({
            value: String(value || ''),
            label: _titleCaseWords(value),
        }));
    }

    function _selectorCatalogEntries(kind) {
        const normalized = String(kind || '').trim().toLowerCase();
        const entries = [];
        const seen = new Set();
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
        if (normalized === 'agent') {
            (connectedAgents || []).forEach((agent) => {
                const slug = String(agent?.slug || '').trim();
                if (!slug) return;
                push(slug, String(agent?.display_name || _titleCaseWords(slug) || slug), String(agent?.role || ''));
            });
        } else if (normalized === 'skill') {
            (connectedAgents || []).forEach((agent) => {
                (agent?.routing_skills || []).forEach((skill) => push(skill, _titleCaseWords(skill)));
            });
        } else if (normalized === 'role') {
            (connectedAgents || []).forEach((agent) => {
                push(agent?.role, _titleCaseWords(agent?.role || ''));
            });
        }
        _participantSelectorSuggestions().forEach((suggestion) => {
            if (String(suggestion?.selectorKind || '') === normalized) {
                push(suggestion?.selectorValue, suggestion?.displayName || suggestion?.label || suggestion?.selectorValue);
            }
        });
        return entries.sort((left, right) => String(left.label || '').localeCompare(String(right.label || '')));
    }

    function _selectorEditor({
        selectorKind = '',
        selectorValue = '',
        participantKey = '',
        readOnly = false,
        onChange = null,
        onSuggestionSelect = null,
    } = {}) {
        const wrap = document.createElement('section');
        wrap.className = 'kit-selector-editor';

        const heading = document.createElement('div');
        heading.className = 'kit-selector-editor-head';
        const title = document.createElement('h4');
        title.className = 'kit-stage-editor-title';
        title.textContent = 'Assignment rule';
        heading.appendChild(title);
        const copy = document.createElement('p');
        copy.className = 'kit-stage-routing-copy';
        copy.textContent = 'Choose how this role resolves at run time. Start with known agents, skills, or roles; use manual override only when needed.';
        heading.appendChild(copy);
        wrap.appendChild(heading);

        const kindRow = document.createElement('div');
        kindRow.className = 'kit-details-row';
        const kindLabel = document.createElement('label');
        kindLabel.className = 'kit-details-label';
        kindLabel.textContent = Kit.dict.label('protocol.participant.selector_kind.label', 'Selector type');
        kindRow.appendChild(kindLabel);
        const kindControl = document.createElement('select');
        kindControl.className = 'kit-details-control';
        const blankKind = document.createElement('option');
        blankKind.value = '';
        blankKind.textContent = '(choose assignment type)';
        kindControl.appendChild(blankKind);
        _selectorKindOptions().forEach((item) => {
            const option = document.createElement('option');
            option.value = String(item.value || '');
            option.textContent = String(item.label || item.value || '');
            if (String(selectorKind || '') === String(item.value || '')) option.selected = true;
            kindControl.appendChild(option);
        });
        kindControl.disabled = Boolean(readOnly);
        if (typeof onChange === 'function' && !readOnly) {
            kindControl.addEventListener('change', () => {
                const nextKind = String(kindControl.value || '');
                onChange('selector_kind', nextKind);
                const catalog = _selectorCatalogEntries(nextKind);
                if (!catalog.some((item) => item.value === String(selectorValue || '')) && catalog.length) {
                    onChange('selector_value', catalog[0].value);
                } else if (!catalog.length) {
                    onChange('selector_value', '');
                }
            });
        }
        kindRow.appendChild(kindControl);
        wrap.appendChild(kindRow);

        const catalog = _selectorCatalogEntries(selectorKind);
        const valueRow = document.createElement('div');
        valueRow.className = 'kit-details-row';
        const valueLabel = document.createElement('label');
        valueLabel.className = 'kit-details-label';
        valueLabel.textContent = catalog.length
            ? `Choose ${String(selectorKind || 'value')}`
            : Kit.dict.label('protocol.participant.selector_value.label', 'Selector value');
        valueRow.appendChild(valueLabel);
        if (catalog.length) {
            const select = document.createElement('select');
            select.className = 'kit-details-control';
            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = `(choose ${String(selectorKind || 'value')})`;
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
                select.addEventListener('change', () => onChange('selector_value', select.value));
            }
            valueRow.appendChild(select);
        } else {
            const input = document.createElement('input');
            input.type = 'text';
            input.className = 'kit-details-control';
            input.placeholder = Kit.dict.label('protocol.participant.selector_value.placeholder', '@skill:name');
            input.value = String(selectorValue || '');
            input.readOnly = Boolean(readOnly);
            if (typeof onChange === 'function' && !readOnly) {
                const commit = () => onChange('selector_value', input.value);
                input.addEventListener('change', commit);
                input.addEventListener('blur', commit);
            }
            valueRow.appendChild(input);
        }
        wrap.appendChild(valueRow);

        const override = document.createElement('details');
        override.className = 'kit-selector-editor-override';
        override.open = Boolean(selectorValue && catalog.length && !catalog.some((item) => item.value === String(selectorValue || '')));
        const summary = document.createElement('summary');
        summary.className = 'kit-stage-editor-summary';
        const summaryTitle = document.createElement('h4');
        summaryTitle.className = 'kit-stage-editor-title';
        summaryTitle.textContent = 'Manual override';
        summary.appendChild(summaryTitle);
        override.appendChild(summary);
        const overrideBody = document.createElement('div');
        overrideBody.className = 'kit-selector-editor-override-body';
        const overrideRow = document.createElement('div');
        overrideRow.className = 'kit-details-row';
        const overrideLabel = document.createElement('label');
        overrideLabel.className = 'kit-details-label';
        overrideLabel.textContent = 'Custom selector value';
        overrideRow.appendChild(overrideLabel);
        const overrideInput = document.createElement('input');
        overrideInput.type = 'text';
        overrideInput.className = 'kit-details-control';
        overrideInput.placeholder = Kit.dict.label('protocol.participant.selector_value.placeholder', '@skill:name');
        overrideInput.value = String(selectorValue || '');
        overrideInput.readOnly = Boolean(readOnly);
        if (typeof onChange === 'function' && !readOnly) {
            const commit = () => onChange('selector_value', overrideInput.value);
            overrideInput.addEventListener('change', commit);
            overrideInput.addEventListener('blur', commit);
        }
        overrideRow.appendChild(overrideInput);
        overrideBody.appendChild(overrideRow);
        override.appendChild(overrideBody);
        wrap.appendChild(override);

        const query = participantKey && participantKey === selectorPreview.participantKey
            ? selectorPreview.query
            : _selectorString(_selectorFromFields(selectorKind, selectorValue));
        wrap.appendChild(Kit.selectorResolutionPreview({
            selector: query,
            candidates: participantKey && participantKey === selectorPreview.participantKey ? selectorPreview.candidates : [],
            busy: participantKey && participantKey === selectorPreview.participantKey ? selectorPreview.busy : false,
            message: participantKey && participantKey === selectorPreview.participantKey
                ? selectorPreview.message
                : Kit.dict.label('protocol.participant.selector_hint'),
            suggestions: _participantSelectorSuggestions(),
            onSuggestionSelect: readOnly ? null : onSuggestionSelect,
            onResolve: (value) => { void _resolveSelectorPreview(participantKey || '__draft__', value); },
        }));

        return wrap;
    }

    function _roleEditorShell({
        target,
        readOnly = false,
        onCommit = null,
        createAction = null,
        cancelAction = null,
        participantKey = '',
        onSuggestionSelect = null,
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
        shell.appendChild(_stageEditorSection('Role basics', basics));
        shell.appendChild(_stageEditorSection('Assignment', _selectorEditor({
            selectorKind: String(target?.selector_kind || ''),
            selectorValue: String(target?.selector_value || ''),
            participantKey,
            readOnly,
            onChange: onCommit,
            onSuggestionSelect,
        }), { wide: true }));
        const instructions = Kit.detailsPanel({
            target,
            surfaceKey: 'protocol.participant',
            onCommit,
            schema: [
                { key: 'instructions', kind: 'textarea', rows: 4, readOnly },
            ],
            actions: !createAction && cancelAction ? [{ label: 'Cancel', onClick: cancelAction }] : [],
        });
        shell.appendChild(_stageEditorSection('Instructions', instructions, { wide: true, collapsible: !createAction, open: Boolean(String(target?.instructions || '').trim()) }));
        return shell;
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
        deleteAction = null,
        cancelAction = null,
    } = {}) {
        return Kit.detailsPanel({
            target,
            surfaceKey: 'protocol.transition',
            onCommit,
            schema: [
                { key: 'source_stage', kind: 'text', label: 'From step', help: 'This route leaves the selected step.', readOnly: true },
                { key: 'decision', kind: 'select', options: _decisionOptionsForStage(sourceStage, target?.decision), disabled: readOnly, labelKey: 'protocol.transition.decision.label', helpKey: 'protocol.transition.decision.help' },
                { key: 'target_key', kind: 'select', options: _routeTargetOptions(sourceStage?.stage_key || target?.source_stage_key || '', projection), disabled: readOnly, labelKey: 'protocol.transition.target.label', helpKey: 'protocol.transition.target.help' },
            ],
            actions: [
                ...(createAction ? [{ label: 'Create route', tone: 'btn-primary', onClick: createAction }] : []),
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

    function _stageColumns(stageKeys, topology) {
        const orderedKeys = Array.isArray(stageKeys) ? stageKeys.map((item) => String(item || '').trim()).filter(Boolean) : [];
        const columns = new Map(orderedKeys.map((item) => [item, Number(topology.rank.get(item) || 0)]));
        const minimum = Math.min(...Array.from(columns.values()), 0);
        orderedKeys.forEach((stageKey) => {
            columns.set(stageKey, Math.max(0, Number(columns.get(stageKey) || 0) - minimum));
        });
        return columns;
    }

    function _stageNodeSublabel(stage) {
        const reads = Number((stage.inputs || []).length || 0);
        const writes = Number((stage.outputs || []).length || 0);
        const parts = [];
        if (reads) parts.push(`Reads ${reads}`);
        if (writes) parts.push(`Writes ${writes}`);
        if (!parts.length && String(stage.instructions || '').trim()) parts.push('Instructions ready');
        return parts.join(' · ');
    }

    function _stageNodeBadges(stage, viewKind = 'detail') {
        const stageKind = String(stage?.stage_kind || 'work');
        if (viewKind === 'map' && stageKind === 'work') {
            return [];
        }
        return [{
            tone: stageKind,
            label: Kit.dict.label(`protocol.stage.kind.${stageKind}`),
        }];
    }

    function _showEdgeLabel(edge, sourceStage, viewKind = 'detail') {
        if (viewKind !== 'map') {
            return false;
        }
        return false;
    }

    function _firstRunState(progress) {
        const participantCount = progress.participantCount;
        const stageCount = progress.stageCount;
        return editorMode.kind === 'idle' && !participantCount
            ? {
                active: true,
                title: Kit.dict.label('protocol.canvas.empty.title'),
                body: 'Start by adding the first role in this workflow. A role is the reusable owner for one or more steps.',
                actions: [
                    { label: Kit.dict.label('protocol.participants.add'), onClick: () => _startRoleInsert() },
                    { label: Kit.dict.label('protocol.catalog.gallery'), tone: '', onClick: () => Router.navigate('/ui/gallery') },
                ],
            }
            : editorMode.kind === 'idle' && participantCount && !stageCount
                ? {
                    active: true,
                    title: 'Add the first step',
                    body: 'Create the first step, choose which role owns it, and then connect it to the next step or an outcome.',
                    actions: [
                        { label: Kit.dict.label('protocol.stages.add'), onClick: () => _startStageInsert() },
                    ],
                }
                : null;
    }

    function _segmentStagePreview(segment) {
        const names = (segment?.stages || [])
            .map((item) => String(item.display_name || item.stage_key || '').trim())
            .filter(Boolean);
        if (names.length <= 3) {
            return names.join(' -> ');
        }
        return `${names.slice(0, 3).join(' -> ')} + ${names.length - 3} more`;
    }

    function _segmentProcessFootnote(segment) {
        const segmentTargets = (segment?.outgoingEdges || []).filter((edge) => edge.targetKind === 'segment').length;
        const terminalTargets = (segment?.outgoingEdges || []).filter((edge) => edge.targetKind === 'terminal').length;
        if (segmentTargets > 1) {
            return `${segmentTargets} next paths`;
        }
        if (segmentTargets === 1 && terminalTargets) {
            return `${terminalTargets} finish path${terminalTargets === 1 ? '' : 's'} available`;
        }
        if (terminalTargets > 0) {
            return `${terminalTargets} finish path${terminalTargets === 1 ? '' : 's'}`;
        }
        return 'Open detail';
    }

    function _surfaceToolbarActions(progress, resolvedView, projection) {
        const canMutate = saveState.state !== 'conflict' && editorMode.kind !== 'rehearse';
        const selectedStage = _selectionStage(draft.document);
        const activeSegmentId = String(resolvedView.segmentId || projection.segments[0]?.id || '');
        const returnSurface = projection.segments.length > 1 ? 'process' : 'detail';
        return [
            ...(resolvedView.kind === 'map' ? [{
                label: returnSurface === 'process' ? 'Back to phases' : 'Back to detail',
                tone: 'btn-small',
                onClick: () => _setWorkflowView({ kind: returnSurface, segmentId: activeSegmentId }),
            }] : []),
            ...(resolvedView.kind === 'process' && progress.stageCount ? [{
                label: 'Visual map',
                tone: 'btn-small',
                onClick: () => _setWorkflowView({ kind: 'map', segmentId: activeSegmentId }),
            }] : []),
            ...(resolvedView.kind === 'detail' && projection.segments.length > 1 ? [{
                label: 'Back to phases',
                tone: 'btn-small',
                onClick: () => _setWorkflowView({ kind: 'process', segmentId: activeSegmentId }),
            }] : []),
            {
                label: Kit.dict.label('protocol.participants.add'),
                tone: 'btn-small',
                onClick: () => _startRoleInsert(),
                disabled: !canMutate,
            },
            {
                label: Kit.dict.label('protocol.stages.add'),
                tone: 'btn-small',
                onClick: () => _startStageInsert(),
                disabled: !canMutate || !progress.participantCount,
            },
            ...(resolvedView.kind === 'map' && selectedStage && editorMode.kind === 'idle' && canMutate ? [{
                label: 'Connect in map',
                tone: 'btn-small',
                onClick: () => _startConnectMode(selectedStage.stage_key),
            }] : []),
            ...(rehearsal.runId ? [{
                label: editorMode.kind === 'rehearse' ? 'Back to authoring' : 'View rehearsal',
                tone: 'btn-small',
                onClick: () => {
                    _setEditorMode({ kind: editorMode.kind === 'rehearse' ? 'idle' : 'rehearse' });
                },
            }] : []),
        ];
    }

    function _processWorkflowData(projection, progress, resolvedView) {
        const nodes = projection.segments.map((segment) => {
            const terminalCount = segment.outgoingEdges.filter((edge) => edge.targetKind === 'terminal').length;
            return {
                id: segment.id,
                kind: 'segment',
                laneKey: '',
                row: Number(segment.row || 0),
                column: Number(segment.column || 0),
                label: segment.label,
                sublabel: segment.roleSummary,
                preview: _segmentStagePreview(segment),
                footnote: _segmentProcessFootnote(segment),
                badges: [
                    { tone: 'phase', label: segment.stepSummary },
                    ...(terminalCount ? [{ tone: 'context', label: `${terminalCount} finish path${terminalCount === 1 ? '' : 's'}` }] : []),
                ],
            };
        });
        return {
            lanes: [],
            nodes,
            edges: [],
            toolbarActions: _surfaceToolbarActions(progress, resolvedView, projection),
            accessorySections: [],
            firstRun: _firstRunState(progress),
            laneLabels: {},
            outcomes: null,
            viewState: {
                kind: 'process',
                title: 'Workflow phases',
                subtitle: 'Open a phase to build and edit its steps. Use Visual map only when you need the full topology.',
                canReturn: false,
            },
        };
    }

    function _mapWorkflowData(projection, progress, resolvedView) {
        const doc = draft.document;
        const stageCounts = new Map();
        (doc.stages || []).forEach((item) => {
            const key = String(item.participant_key || '').trim();
            stageCounts.set(key, Number(stageCounts.get(key) || 0) + 1);
        });
        const lanes = (doc.participants || []).map((item) => ({
            key: String(item.participant_key || ''),
            label: String(item.display_name || item.participant_key || 'Role'),
            sublabel: _selectorString(item.selector || null)
                || `${Number(stageCounts.get(String(item.participant_key || '')) || 0)} step${Number(stageCounts.get(String(item.participant_key || '')) || 0) === 1 ? '' : 's'}`,
            empty: 'No steps in this role yet.',
        }));
        const stageKeys = (doc.stages || []).map((item) => String(item.stage_key || ''));
        const columns = _stageColumns(stageKeys, projection.topology);
        const maxStageColumn = Math.max(0, ...Array.from(columns.values(), (value) => Number(value || 0)));
        return {
            lanes,
            nodes: [
                ...(doc.stages || []).map((item) => ({
                    id: String(item.stage_key || ''),
                    kind: 'stage',
                    laneKey: String(item.participant_key || ''),
                    row: _stageLaneRow(item.participant_key, doc),
                    column: Number(columns.get(String(item.stage_key || '')) || 0),
                    label: String(item.display_name || item.stage_key || 'Untitled step'),
                    sublabel: _stageNodeSublabel(item),
                    badges: _stageNodeBadges(item, 'map'),
                })),
                ...(progress.stageCount ? PROTOCOL_TERMINAL_TARGETS.map((item, index) => ({
                    id: item.key,
                    kind: 'terminal',
                    laneKey: '',
                    row: lanes.length + index,
                    column: maxStageColumn + 1,
                    label: item.label,
                    sublabel: 'Ends the workflow',
                    isTerminal: true,
                })) : []),
            ],
            edges: _transitionEntries(doc).map((edge) => {
                const sourceStage = (doc.stages || []).find((item) => String(item.stage_key || '') === String(edge.from_stage_key || ''));
                const sourceTransitionCount = Object.keys(sourceStage?.transitions || {}).length;
                return {
                    id: edge.id,
                    from: edge.from_stage_key,
                    to: edge.target_key,
                    label: _protocolDecisionLabel(edge.decision),
                    showLabel: _showEdgeLabel(edge, sourceStage, 'map'),
                    isBranch: sourceTransitionCount > 1,
                };
            }),
            toolbarActions: _surfaceToolbarActions(progress, resolvedView, projection),
            accessorySections: [],
            firstRun: _firstRunState(progress),
            laneLabels: Object.fromEntries(lanes.map((lane, index) => [lane.key, { ...lane, row: index }])),
            outcomes: progress.stageCount ? {
                startRow: lanes.length,
                count: PROTOCOL_TERMINAL_TARGETS.length,
                label: Kit.dict.label('protocol.workflow.outcomes'),
                hint: Kit.dict.label('protocol.workflow.outcomes_hint'),
            } : null,
            viewState: {
                kind: 'map',
                title: 'Visual map',
                subtitle: 'Inspect the full workflow topology here. Use Detail for ordinary editing and route authoring.',
                canReturn: false,
            },
        };
    }

    function _detailToolbarActions(progress, resolvedView, projection, segment) {
        const canMutate = saveState.state !== 'conflict' && editorMode.kind !== 'rehearse';
        const selectedStage = _selectionStage(draft.document);
        return [
            ...(projection.segments.length > 1 ? [{
                label: 'Back to phases',
                tone: 'btn-small',
                onClick: () => _setWorkflowView({ kind: 'process', segmentId: String(segment?.id || '') }),
            }] : []),
            ...(progress.stageCount ? [{
                label: 'Visual map',
                tone: 'btn-small',
                onClick: () => _setWorkflowView({ kind: 'map', segmentId: String(segment?.id || '') }),
            }] : []),
            {
                label: Kit.dict.label('protocol.participants.add'),
                tone: 'btn-small',
                onClick: () => _startRoleInsert(),
                disabled: !canMutate,
            },
            {
                label: Kit.dict.label('protocol.stages.add'),
                tone: 'btn-small',
                onClick: () => _startStageInsert(),
                disabled: !canMutate || !progress.participantCount,
            },
            ...(selectedStage && editorMode.kind === 'idle' && canMutate ? [{
                label: 'Add route',
                tone: 'btn-small',
                onClick: () => _startRouteInsert(selectedStage.stage_key),
            }] : []),
            ...(rehearsal.runId ? [{
                label: editorMode.kind === 'rehearse' ? 'Back to authoring' : 'View rehearsal',
                tone: 'btn-small',
                onClick: () => {
                    _setEditorMode({ kind: editorMode.kind === 'rehearse' ? 'idle' : 'rehearse' });
                },
            }] : []),
        ];
    }

    function _routeScopeLabel(targetKey, projection, currentSegmentId) {
        const normalized = String(targetKey || '').trim();
        if (!normalized) return '';
        if (PROTOCOL_TERMINAL_TARGETS.some((item) => item.key === normalized)) {
            return 'Finish outcome';
        }
        const targetSegmentId = projection.stageToSegment.get(normalized) || '';
        if (targetSegmentId && targetSegmentId === String(currentSegmentId || '')) {
            return 'This section';
        }
        const targetSegment = projection.segmentsById.get(targetSegmentId);
        return targetSegment ? `Other section · ${targetSegment.label}` : 'Other section';
    }

    function _detailRouteEntries(stage, projection, currentSegmentId) {
        return _transitionEntries(draft.document)
            .filter((item) => String(item.from_stage_key || '') === String(stage?.stage_key || ''))
            .map((item) => ({
                ...item,
                decisionLabel: _protocolDecisionLabel(item.decision),
                targetLabel: _transitionTargetLabel(item.target_key, draft.document),
                scopeLabel: _routeScopeLabel(item.target_key, projection, currentSegmentId),
            }));
    }

    function _detailSelectionInSegment(segment) {
        if (!segment) return false;
        if (selection.sectionKey === 'stages') {
            return segment.stageKeys.includes(String(selection.nodeKey || ''));
        }
        if (selection.sectionKey === 'transitions') {
            const sourceKey = String(selection.nodeKey || '').split('::')[0] || '';
            return segment.stageKeys.includes(sourceKey);
        }
        if (selection.sectionKey === 'participants') {
            return true;
        }
        return selection.sectionKey === 'artifacts';
    }

    function _detailWorkflowData(projection, progress, resolvedView) {
        const segment = projection.segmentsById.get(String(resolvedView.segmentId || '')) || projection.segments[0] || null;
        if (segment && editorMode.kind === 'idle' && !_detailSelectionInSegment(segment) && segment.stageKeys.length) {
            selection = { sectionKey: 'stages', nodeKey: String(segment.stageKeys[0] || '') };
        }
        return {
            segment,
            firstRun: _firstRunState(progress),
            toolbarActions: _detailToolbarActions(progress, resolvedView, projection, segment),
            viewState: {
                kind: 'detail',
                title: String(segment?.label || 'Workflow builder'),
                subtitle: segment ? `${segment.stepSummary} · ${segment.roleSummary}` : 'Build roles, steps, and routes here.',
            },
            roleChips: (segment?.roleKeys || []).map((roleKey) => ({
                key: String(roleKey || ''),
                label: _participantDisplayName(roleKey, draft.document),
                selected: selection.sectionKey === 'participants' && selection.nodeKey === String(roleKey || ''),
            })),
            incomingSections: (segment?.incomingSegments || [])
                .map((segmentId) => projection.segmentsById.get(segmentId))
                .filter(Boolean)
                .map((item) => String(item.label || '')),
            outgoingSections: Array.from(new Set((segment?.outgoingEdges || [])
                .filter((edge) => edge.targetKind === 'segment')
                .map((edge) => String(projection.segmentsById.get(edge.targetKey)?.label || ''))
                .filter(Boolean))),
            finishOutcomes: Array.from(new Set((segment?.outgoingEdges || [])
                .filter((edge) => edge.targetKind === 'terminal')
                .map((edge) => String(_transitionTargetLabel(edge.targetKey, draft.document) || ''))
                .filter(Boolean))),
            stepCards: (segment?.stages || []).map((stage, index) => {
                const stageKey = String(stage.stage_key || '');
                const routes = _detailRouteEntries(stage, projection, segment?.id || '');
                const expanded = (selection.sectionKey === 'stages' && selection.nodeKey === stageKey)
                    || (selection.sectionKey === 'transitions' && String(selection.nodeKey || '').startsWith(`${stageKey}::`))
                    || (editorMode.kind === 'create-route' && editorMode.sourceStageKey === stageKey);
                return {
                    stage,
                    order: index + 1,
                    routes,
                    expanded,
                    summary: routes.length
                        ? routes.map((route) => `${route.decisionLabel} → ${route.targetLabel}`).join(' · ')
                        : 'No routes yet',
                };
            }),
        };
    }

    function _workflowData() {
        const projection = _buildWorkflowProjection(draft.document);
        const resolvedView = _normalizeWorkflowView(projection);
        if (resolvedView.kind !== workflowView.kind || resolvedView.segmentId !== workflowView.segmentId) {
            workflowView = resolvedView;
            _persistWorkflowView();
        }
        const progress = _workflowProgress(draft.document);
        return {
            projection,
            progress,
            resolvedView,
            ...(
                resolvedView.kind === 'process'
                    ? _processWorkflowData(projection, progress, resolvedView)
                    : resolvedView.kind === 'map'
                        ? _mapWorkflowData(projection, progress, resolvedView)
                        : _detailWorkflowData(projection, progress, resolvedView)
            ),
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
            lanes: workflow.lanes,
            nodes: workflow.nodes,
            edges: workflow.edges,
            toolbarActions: workflow.toolbarActions,
            accessorySections: workflow.accessorySections,
            firstRun: workflow.firstRun,
            mode: 'graph',
            editorMode,
            laneLabels: workflow.laneLabels,
            outcomes: workflow.outcomes,
            viewState: workflow.viewState,
            viewportState: { zoom: _workflowViewportValue(workflow.viewState.kind) },
            onViewportChange: (zoom) => _setWorkflowViewport(workflow.viewState.kind, zoom),
            nodeStates: rehearsal.runId ? _rehearsalNodeStates() : {},
            selection: {
                kind: selection.sectionKey === 'transitions'
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
                if (editorMode.kind === 'connect' && (kind === 'stage' || kind === 'terminal')) {
                    _connectTransitionTarget(id);
                    return;
                }
                if (kind === 'segment') {
                    _setDetailSegment(workflow.projection, id);
                    return;
                }
                if (kind === 'participant') {
                    selection = { sectionKey: 'participants', nodeKey: id };
                } else if (kind === 'artifact') {
                    selection = { sectionKey: 'artifacts', nodeKey: id };
                } else if (kind === 'transition') {
                    selection = { sectionKey: 'transitions', nodeKey: id };
                } else if (kind === 'stage') {
                    selection = { sectionKey: 'stages', nodeKey: id };
                } else {
                    selection = { sectionKey: 'overview', nodeKey: '' };
                }
                render();
            },
            onBeginConnect: (stageId) => _startConnectMode(stageId),
            onCancelConnect: _cancelTransitionConnect,
            onMutate: ({ type, nodeId, targetId }) => {
                if (type === 'undo') {
                    _restoreHistory('undo');
                    return;
                }
                if (type === 'redo') {
                    _restoreHistory('redo');
                    return;
                }
                if (type === 'reorder' && nodeId && targetId) {
                    _moveStageBefore(nodeId, targetId);
                }
            },
        });
    }

    function _detailSurfaceEl(workflow) {
        const wrap = document.createElement('section');
        wrap.className = 'kit-protocol-detail';

        if (workflow.firstRun?.active) {
            const firstRun = document.createElement('div');
            firstRun.className = 'kit-workflow-first-run';
            const title = document.createElement('h3');
            title.className = 'kit-workflow-first-run-title';
            title.textContent = String(workflow.firstRun.title || '');
            firstRun.appendChild(title);
            const body = document.createElement('p');
            body.className = 'kit-workflow-first-run-body';
            body.textContent = String(workflow.firstRun.body || '');
            firstRun.appendChild(body);
            const actions = document.createElement('div');
            actions.className = 'kit-workflow-first-run-actions';
            (workflow.firstRun.actions || []).forEach((action) => {
                if (!action || typeof action.onClick !== 'function') return;
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = ['btn', action.tone || 'btn-primary'].filter(Boolean).join(' ');
                btn.textContent = String(action.label || '');
                btn.addEventListener('click', action.onClick);
                actions.appendChild(btn);
            });
            firstRun.appendChild(actions);
            wrap.appendChild(firstRun);
            return wrap;
        }

        const header = document.createElement('div');
        header.className = 'kit-protocol-detail-header';
        const titleRow = document.createElement('div');
        titleRow.className = 'kit-protocol-detail-header-top';
        const copy = document.createElement('div');
        copy.className = 'kit-protocol-detail-copy';
        const title = document.createElement('h3');
        title.className = 'kit-protocol-detail-title';
        title.textContent = String(workflow.viewState?.title || 'Workflow builder');
        copy.appendChild(title);
        const subtitle = document.createElement('p');
        subtitle.className = 'kit-protocol-detail-subtitle';
        subtitle.textContent = String(workflow.viewState?.subtitle || '');
        copy.appendChild(subtitle);
        titleRow.appendChild(copy);
        const actions = document.createElement('div');
        actions.className = 'kit-protocol-detail-actions';
        (workflow.toolbarActions || []).forEach((action) => {
            if (!action || typeof action.onClick !== 'function') return;
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = ['btn', action.tone || 'btn-small'].filter(Boolean).join(' ');
            btn.textContent = String(action.label || '');
            btn.disabled = Boolean(action.disabled);
            btn.addEventListener('click', action.onClick);
            actions.appendChild(btn);
        });
        titleRow.appendChild(actions);
        header.appendChild(titleRow);

        const meta = document.createElement('div');
        meta.className = 'kit-protocol-detail-meta';
        (workflow.roleChips || []).forEach((role) => {
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = `kit-protocol-detail-chip${role.selected ? ' is-selected' : ''}`;
            chip.textContent = String(role.label || '');
            chip.addEventListener('click', () => {
                selection = { sectionKey: 'participants', nodeKey: role.key };
                render();
            });
            meta.appendChild(chip);
        });
        (workflow.incomingSections || []).forEach((label) => {
            const chip = document.createElement('span');
            chip.className = 'kit-protocol-detail-chip is-muted';
            chip.textContent = `From ${label}`;
            meta.appendChild(chip);
        });
        (workflow.outgoingSections || []).forEach((label) => {
            const chip = document.createElement('span');
            chip.className = 'kit-protocol-detail-chip is-muted';
            chip.textContent = `Next ${label}`;
            meta.appendChild(chip);
        });
        (workflow.finishOutcomes || []).forEach((label) => {
            const chip = document.createElement('span');
            chip.className = 'kit-protocol-detail-chip is-success';
            chip.textContent = label;
            meta.appendChild(chip);
        });
        if (meta.childElementCount) {
            header.appendChild(meta);
        }
        wrap.appendChild(header);

        const list = document.createElement('div');
        list.className = 'kit-protocol-step-list';
        (workflow.stepCards || []).forEach((item) => {
            const stage = item.stage;
            const card = document.createElement('section');
            card.className = `kit-protocol-step-card${item.expanded ? ' is-selected' : ''}`;

            const main = document.createElement('button');
            main.type = 'button';
            main.className = 'kit-protocol-step-card-main';
            main.dataset.testid = `workflow-step-${String(stage.stage_key || '')}`;
            main.addEventListener('click', () => {
                selection = { sectionKey: 'stages', nodeKey: String(stage.stage_key || '') };
                render();
            });

            const eyebrow = document.createElement('div');
            eyebrow.className = 'kit-protocol-step-card-eyebrow';
            const order = document.createElement('span');
            order.className = 'kit-protocol-step-order';
            order.textContent = String(item.order).padStart(2, '0');
            eyebrow.appendChild(order);
            _stageNodeBadges(stage, 'detail').forEach((badge) => {
                const chip = document.createElement('span');
                chip.className = `kit-workflow-node-badge${badge?.tone ? ` is-${badge.tone}` : ''}`;
                chip.textContent = String(badge?.label || '');
                eyebrow.appendChild(chip);
            });
            const owner = document.createElement('button');
            owner.type = 'button';
            owner.className = 'kit-protocol-step-owner';
            owner.textContent = _participantDisplayName(stage.participant_key, draft.document);
            owner.addEventListener('click', (event) => {
                event.preventDefault();
                event.stopPropagation();
                selection = { sectionKey: 'participants', nodeKey: String(stage.participant_key || '') };
                render();
            });
            eyebrow.appendChild(owner);
            main.appendChild(eyebrow);

            const label = document.createElement('div');
            label.className = 'kit-protocol-step-title';
            label.textContent = String(stage.display_name || stage.stage_key || 'Untitled step');
            main.appendChild(label);

            const summary = document.createElement('div');
            summary.className = 'kit-protocol-step-summary';
            summary.textContent = String(item.summary || '');
            main.appendChild(summary);

            const stageMeta = document.createElement('div');
            stageMeta.className = 'kit-protocol-step-meta';
            stageMeta.textContent = _stageNodeSublabel(stage) || 'No artifacts or instructions yet.';
            main.appendChild(stageMeta);
            card.appendChild(main);

            if (item.expanded) {
                const body = document.createElement('div');
                body.className = 'kit-protocol-step-body';
                if (String(stage.instructions || '').trim()) {
                    const note = document.createElement('p');
                    note.className = 'kit-protocol-step-note';
                    note.textContent = String(stage.instructions || '');
                    body.appendChild(note);
                }
                const routes = document.createElement('div');
                routes.className = 'kit-protocol-step-routes';
                if (item.routes.length) {
                    item.routes.forEach((route) => {
                        const routeBtn = document.createElement('button');
                        routeBtn.type = 'button';
                        routeBtn.className = `kit-protocol-step-route${selection.sectionKey === 'transitions' && selection.nodeKey === route.id ? ' is-selected' : ''}`;
                        routeBtn.dataset.testid = `workflow-edge-${String(route.id || '')}`;
                        routeBtn.addEventListener('click', () => {
                            selection = { sectionKey: 'transitions', nodeKey: route.id };
                            render();
                        });
                        const decision = document.createElement('span');
                        decision.className = 'kit-stage-routing-badge';
                        decision.textContent = String(route.decisionLabel || route.decision || '');
                        routeBtn.appendChild(decision);
                        const routeBody = document.createElement('span');
                        routeBody.className = 'kit-protocol-step-route-body';
                        routeBody.textContent = `${route.targetLabel} · ${route.scopeLabel}`;
                        routeBtn.appendChild(routeBody);
                        routes.appendChild(routeBtn);
                    });
                } else {
                    const empty = document.createElement('div');
                    empty.className = 'kit-stage-routing-empty';
                    empty.textContent = 'No routes yet. Add the next step or finish outcome from here.';
                    routes.appendChild(empty);
                }
                body.appendChild(routes);
                if (saveState.state !== 'conflict' && editorMode.kind !== 'rehearse') {
                    const row = document.createElement('div');
                    row.className = 'kit-protocol-step-actions';
                    const addRoute = document.createElement('button');
                    addRoute.type = 'button';
                    addRoute.className = 'btn btn-small';
                    addRoute.textContent = 'Add route';
                    addRoute.addEventListener('click', () => _startRouteInsert(stage.stage_key));
                    row.appendChild(addRoute);
                    body.appendChild(row);
                }
                card.appendChild(body);
            }
            list.appendChild(card);
        });
        wrap.appendChild(list);
        return wrap;
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
            Kit.dict.label(`protocol.stage.kind.${String(target?.stage_kind || 'work')}`, _titleCaseWords(target?.stage_kind || 'work')),
            `${Object.keys(target?.transitions || {}).length} route${Object.keys(target?.transitions || {}).length === 1 ? '' : 's'}`,
            `${(target?.inputs || []).length} read${(target?.inputs || []).length === 1 ? '' : 's'} · ${(target?.outputs || []).length} write${(target?.outputs || []).length === 1 ? '' : 's'}`,
        ].filter(Boolean).forEach((item) => {
            const chip = document.createElement('span');
            chip.className = 'kit-stage-editor-hero-chip';
            chip.textContent = String(item || '');
            meta.appendChild(chip);
        });
        hero.appendChild(meta);

        const note = document.createElement('p');
        note.className = 'kit-stage-editor-hero-note';
        note.textContent = 'Edit this step here: ownership, instructions, artifacts, and routes. Open Visual map only when you need the full topology.';
        hero.appendChild(note);

        return hero;
    }

    function _stageRoutingPanel(stage, { readOnly = false, connectAction = null } = {}) {
        const panel = document.createElement('div');
        panel.className = 'kit-stage-routing';

        const head = document.createElement('div');
        head.className = 'kit-stage-routing-head';

        const intro = document.createElement('p');
        intro.className = 'kit-stage-routing-copy';
        intro.textContent = 'Routes control where this step sends the workflow next.';
        head.appendChild(intro);

        if (!readOnly && typeof connectAction === 'function') {
            const add = document.createElement('button');
            add.type = 'button';
            add.className = 'btn btn-small';
            add.textContent = 'Add route';
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
                : 'No routes yet. Add the next step or finish path from here.';
            panel.appendChild(empty);
            return panel;
        }

        const list = document.createElement('div');
        list.className = 'kit-stage-routing-list';
        routes.forEach((route) => {
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
            list.appendChild(row);
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
        }

        const grid = document.createElement('div');
        grid.className = 'kit-stage-editor-grid';

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
                { key: 'display_name', kind: 'text', required: true },
                { key: 'participant_key', kind: 'select', options: participantOptions },
                { key: 'stage_kind', kind: 'select', options: kindOptions },
            ]),
            actions: summaryActions,
        });
        grid.appendChild(_stageEditorSection('Step basics', summaryPanel));

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
            { value: '', label: '(choose a role)' },
            ...((doc.participants || []).map((p) => ({
                value: String(p.participant_key || ''),
                label: String(p.display_name || p.participant_key || ''),
            }))),
        ];
        const kindOptions = _manifestStageKindOptions().map((value) => ({
            value,
            label: Kit.dict.label(`protocol.stage.kind.${value}`, value),
        }));
        const artifactOptions = (doc.artifacts || []).map((item) => ({
            value: String(item.artifact_key || ''),
            label: String(item.display_name || item.artifact_key || ''),
        }));

        if (editorMode.kind === 'insert-role') {
            return _roleEditorShell({
                target: pendingRole,
                participantKey: '__draft__',
                onCommit: _commitPendingRoleField,
                createAction: _confirmRoleInsert,
                cancelAction: _cancelRoleInsert,
                onSuggestionSelect: (value) => { _applyRoleDraftSuggestion(value); },
            });
        }

        if (editorMode.kind === 'insert-stage') {
            return _stageEditorShell({
                target: pendingStage,
                participantOptions,
                kindOptions,
                artifactOptions,
                onCommit: _commitPendingStageField,
                createAction: _confirmStageInsert,
                cancelAction: _cancelStageInsert,
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

        if (editorMode.kind === 'connect') {
            const sourceStage = (doc.stages || []).find((item) => String(item.stage_key || '') === String(editorMode.sourceStageKey || ''));
            const wrap = document.createElement('div');
            wrap.className = 'kit-authoring-canvas-column';
            wrap.appendChild(Kit.detailsPanel({
                target: {
                    source_stage: String(sourceStage?.display_name || sourceStage?.stage_key || ''),
                    decision: String(editorMode.decision || ''),
                },
                surfaceKey: 'protocol.transition',
                onCommit: _commitConnectField,
                schema: [
                    { key: 'source_stage', kind: 'text', label: 'From step', help: 'This transition starts from the selected step.', readOnly: true },
                    { key: 'decision', kind: 'select', options: _decisionOptionsForStage(sourceStage, editorMode.decision), labelKey: 'protocol.transition.decision.label', helpKey: 'protocol.transition.decision.help' },
                ],
                actions: [
                    { label: 'Cancel', onClick: _cancelTransitionConnect },
                ],
            }));
            const hint = document.createElement('p');
            hint.className = 'quiet-note';
            hint.textContent = 'Choose the next step or a finish outcome in the graph to complete this transition.';
            wrap.appendChild(hint);
            return wrap;
        }
        if (selection.sectionKey === 'overview' || !selection.nodeKey) {
            return Kit.detailsPanel({
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
        }
        if (selection.sectionKey === 'participants') {
            const target = (doc.participants || []).find((item) => String(item.participant_key) === selection.nodeKey);
            if (!target) return Kit.detailsPanel({ target: null, surfaceKey: 'protocol' });
            return _roleEditorShell({
                target: {
                    ...target,
                    selector_kind: String(target.selector?.kind || ''),
                    selector_value: String(target.selector?.value || ''),
                },
                participantKey: String(selection.nodeKey || ''),
                readOnly,
                onCommit: readOnly ? null : (_t, key, value) => _commitNodeField('participant', selection.nodeKey, key, value),
                onSuggestionSelect: readOnly ? null : (value) => { void _applyParticipantSuggestion(selection.nodeKey, value); },
            });
        }
        if (selection.sectionKey === 'stages') {
            const target = (doc.stages || []).find((item) => String(item.stage_key) === selection.nodeKey);
            if (!target) return Kit.detailsPanel({ target: null, surfaceKey: 'protocol' });
            return _stageEditorShell({
                target,
                readOnly,
                participantOptions,
                kindOptions,
                artifactOptions,
                onCommit: readOnly
                    ? null
                    : (_t, key, value) => _commitNodeField('stage', selection.nodeKey, key, value),
                connectAction: readOnly ? null : () => _startRouteInsert(selection.nodeKey),
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
        if (!currentProtocolId) {
            header.hidden = false;
            UI.reconcileChildren(contentEl, [_catalogEl()]);
            _lifecycleHeaderRef = null;
            return;
        }

        if (protocolDetailLoading) {
            header.hidden = true;
            UI.reconcileChildren(contentEl, [UI.renderEmptyState('Loading protocol detail…', true)]);
            _lifecycleHeaderRef = null;
            return;
        }

        header.hidden = true;
        const headerEl = _lifecycleHeaderEl();
        const workflow = _workflowData();

        const workspace = document.createElement('div');
        workspace.className = `kit-authoring-workspace kit-authoring-workspace-${String(workflow.viewState?.kind || 'detail')}`;
        workspace.appendChild(
            workflow.viewState?.kind === 'detail'
                ? _detailSurfaceEl(workflow)
                : _surfaceCanvasEl(workflow),
        );

        const detailsColumn = document.createElement('div');
        detailsColumn.className = 'kit-authoring-details-column';
        const details = _detailsEl(workflow);
        if (details) {
            detailsColumn.appendChild(details);
        }
        const validation = _validationEl();
        if (validation) detailsColumn.appendChild(validation);
        if (rehearsal.runId) {
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

        contentEl.replaceChildren(headerEl, workspace);
        _lifecycleHeaderRef = headerEl;
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

    async function loadConnectedAgents({ quiet = true } = {}) {
        try {
            const data = await API.listAgents({ state: 'connected', limit: 24 });
            connectedAgents = Array.isArray(data?.agents) ? data.agents : (Array.isArray(data) ? data : []);
        } catch (err) {
            connectedAgents = [];
            if (!quiet) {
                UI.reportError('Failed to load connected agents', err);
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
            await Promise.all([loadProtocols({ quiet: true }), loadAuthoringManifest(), loadConnectedAgents({ quiet: true })]);
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
    UI.subscribeWithRefresh(cleanups, 'protocols', () => Promise.all([
        loadRuns(),
        currentRunId ? loadRunDetail({ soft: true }) : Promise.resolve(),
    ]), 350);

    container.__routeReady = bootstrap();
}
