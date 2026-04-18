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
    let documentHistory = { undo: [], redo: [] };

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

    function _currentWorkflowMode() {
        return window.innerWidth <= 960 ? 'narrow' : 'graph';
    }

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

    function _applyServerDetail(detail) {
        const previousProtocolId = String(currentProtocol?.protocol?.protocol_id || '');
        currentProtocol = detail;
        draftRevision = Number(detail?.protocol?.draft_revision || 0) || 0;
        draftConflict = null;
        documentHistory = { undo: [], redo: [] };
        selectorPreview = { participantKey: '', query: '', candidates: [], busy: false, message: '' };
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

    function _stageColumns(doc) {
        const stages = Array.isArray(doc?.stages) ? doc.stages : [];
        const orderIndex = new Map(stages.map((item, index) => [String(item.stage_key || ''), index]));
        const columns = new Map(stages.map((item) => [String(item.stage_key || ''), 0]));

        stages.forEach((stage) => {
            const sourceKey = String(stage.stage_key || '');
            const sourceColumn = Number(columns.get(sourceKey) || 0);
            Object.values(stage.transitions || {}).forEach((target) => {
                const targetKey = String(target || '').trim();
                if (!targetKey || !orderIndex.has(targetKey)) return;
                const sourceIndex = Number(orderIndex.get(sourceKey) || 0);
                const targetIndex = Number(orderIndex.get(targetKey) || 0);
                if (targetIndex <= sourceIndex) return;
                columns.set(targetKey, Math.max(Number(columns.get(targetKey) || 0), sourceColumn + 1));
            });
        });

        const laneOrder = new Map();
        stages.forEach((stage) => {
            const laneKey = String(stage.participant_key || '');
            const items = laneOrder.get(laneKey) || [];
            items.push(stage);
            laneOrder.set(laneKey, items);
        });
        laneOrder.forEach((items) => {
            let previous = -1;
            items.forEach((stage) => {
                const key = String(stage.stage_key || '');
                const nextColumn = Math.max(Number(columns.get(key) || 0), previous + 1);
                columns.set(key, nextColumn);
                previous = nextColumn;
            });
        });
        return columns;
    }

    function _workflowData() {
        const doc = draft.document;
        const progress = _workflowProgress(doc);
        const participantCount = progress.participantCount;
        const stageCount = progress.stageCount;
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
        const columns = _stageColumns(doc);
        const maxStageColumn = Math.max(0, ...Array.from(columns.values(), (value) => Number(value || 0)));
        const nodes = [
            ...(doc.stages || []).map((item) => ({
                id: String(item.stage_key || ''),
                kind: 'stage',
                laneKey: String(item.participant_key || ''),
                row: _stageLaneRow(item.participant_key, doc),
                column: Number(columns.get(String(item.stage_key || '')) || 0),
                label: String(item.display_name || item.stage_key || 'Untitled step'),
                sublabel: [
                    (item.inputs || []).length ? `Reads ${(item.inputs || []).length}` : '',
                    (item.outputs || []).length ? `Writes ${(item.outputs || []).length}` : '',
                    String(item.instructions || '').trim() ? 'Instructions ready' : '',
                ].filter(Boolean).join(' · '),
                badges: [
                    {
                        tone: String(item.stage_kind || 'work'),
                        label: Kit.dict.label(`protocol.stage.kind.${item.stage_kind || 'work'}`),
                    },
                ],
            })),
            ...(stageCount ? PROTOCOL_TERMINAL_TARGETS.map((item, index) => ({
                id: item.key,
                kind: 'terminal',
                laneKey: '',
                row: lanes.length + index,
                column: maxStageColumn + 1,
                label: item.label,
                sublabel: 'Ends the workflow',
                isTerminal: true,
            })) : []),
        ];
        const edges = _transitionEntries(doc).map((edge) => ({
            id: edge.id,
            from: edge.from_stage_key,
            to: edge.target_key,
            label: _protocolDecisionLabel(edge.decision),
        }));
        const artifactItems = (doc.artifacts || []).map((item) => ({
            id: String(item.artifact_key || ''),
            kind: 'artifact',
            label: String(item.display_name || item.artifact_key || 'Artifact'),
        }));
        const selectedStage = _selectionStage(doc);
        const canMutate = saveState.state !== 'conflict' && editorMode.kind !== 'rehearse';
        const toolbarActions = [
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
                disabled: !canMutate || !participantCount,
            },
            ...(stageCount ? [{
                label: Kit.dict.label('protocol.artifacts.add'),
                tone: 'btn-small',
                onClick: () => _addArtifact(),
                disabled: !canMutate,
            }] : []),
            ...(selectedStage && editorMode.kind === 'idle' && canMutate ? [{
                label: Kit.dict.label('protocol.stage.connect'),
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
        const firstRun = editorMode.kind === 'idle' && !participantCount
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
        return {
            lanes,
            nodes,
            edges,
            toolbarActions,
            accessorySections: artifactItems.length
                ? [
                    {
                        key: 'artifacts',
                        title: Kit.dict.label('protocol.workflow.artifacts'),
                        addLabel: Kit.dict.label('protocol.artifacts.add'),
                        onAdd: () => _addArtifact(),
                        onSelect: (item) => {
                            selection = { sectionKey: 'artifacts', nodeKey: item.id };
                            render();
                        },
                        empty: Kit.dict.label('protocol.artifacts.firstrun'),
                        items: artifactItems,
                    },
                ]
                : [],
            firstRun,
            laneLabels: Object.fromEntries(lanes.map((lane, index) => [lane.key, { ...lane, row: index }])),
            outcomes: stageCount ? {
                startRow: lanes.length,
                count: PROTOCOL_TERMINAL_TARGETS.length,
                label: Kit.dict.label('protocol.workflow.outcomes'),
                hint: Kit.dict.label('protocol.workflow.outcomes_hint'),
            } : null,
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

    function _canvasEl() {
        const workflow = _workflowData();
        return Kit.workflowCanvas({
            lanes: workflow.lanes,
            nodes: workflow.nodes,
            edges: workflow.edges,
            toolbarActions: workflow.toolbarActions,
            accessorySections: workflow.accessorySections,
            firstRun: workflow.firstRun,
            mode: _currentWorkflowMode(),
            editorMode,
            laneLabels: workflow.laneLabels,
            outcomes: workflow.outcomes,
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

    function _detailsEl() {
        const doc = draft.document;
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
            const wrap = document.createElement('div');
            wrap.className = 'kit-authoring-canvas-column';
            wrap.appendChild(Kit.detailsPanel({
                target: pendingRole,
                surfaceKey: 'protocol.participant',
                onCommit: _commitPendingRoleField,
                schema: [
                    { key: 'display_name', kind: 'text', required: true },
                    { key: 'participant_key', kind: 'text' },
                    {
                        key: 'selector_kind',
                        kind: 'select',
                        options: (authoringManifest?.selector_kind_options || ['skill', 'role', 'agent']).map((value) => ({
                            value,
                            label: String(value || '').charAt(0).toUpperCase() + String(value || '').slice(1),
                        })),
                        labelKey: 'protocol.participant.selector_kind.label',
                        helpKey: 'protocol.participant.selector_kind.help',
                    },
                    { key: 'selector_value', kind: 'text', labelKey: 'protocol.participant.selector_value.label', helpKey: 'protocol.participant.selector_value.help', placeholderKey: 'protocol.participant.selector_value.placeholder' },
                    { key: 'instructions', kind: 'textarea', rows: 4 },
                ],
                actions: [
                    { label: 'Create role', tone: 'btn-primary', onClick: _confirmRoleInsert },
                    { label: 'Cancel', onClick: _cancelRoleInsert },
                ],
            }));
            wrap.appendChild(Kit.selectorResolutionPreview({
                selector: selectorPreview.participantKey === '__draft__'
                    ? selectorPreview.query
                    : _selectorString(_selectorFromFields(pendingRole.selector_kind, pendingRole.selector_value)),
                candidates: selectorPreview.participantKey === '__draft__' ? selectorPreview.candidates : [],
                busy: selectorPreview.participantKey === '__draft__' ? selectorPreview.busy : false,
                message: selectorPreview.participantKey === '__draft__'
                    ? selectorPreview.message
                    : 'Preview who would match this role before you add it.',
                suggestions: _participantSelectorSuggestions(),
                onSuggestionSelect: (value) => { _applyRoleDraftSuggestion(value); },
                onResolve: (value) => {
                    const parsed = _selectorFieldsFromString(value);
                    pendingRole.selector_kind = parsed.kind;
                    pendingRole.selector_value = parsed.value;
                    render();
                    void _resolveSelectorPreview('__draft__', value);
                },
            }));
            return wrap;
        }

        if (editorMode.kind === 'insert-stage') {
            return Kit.detailsPanel({
                target: pendingStage,
                surfaceKey: 'protocol.stage',
                onCommit: _commitPendingStageField,
                schema: [
                    { key: 'display_name', kind: 'text', required: true },
                    { key: 'stage_key', kind: 'text' },
                    { key: 'participant_key', kind: 'select', options: participantOptions },
                    { key: 'stage_kind', kind: 'select', options: kindOptions },
                    { key: 'inputs', kind: 'checklist', options: artifactOptions, labelKey: 'protocol.stage.inputs.label', helpKey: 'protocol.stage.inputs.help' },
                    { key: 'outputs', kind: 'checklist', options: artifactOptions, labelKey: 'protocol.stage.outputs.label', helpKey: 'protocol.stage.outputs.help' },
                    { key: 'instructions', kind: 'textarea', rows: 4 },
                    { key: 'max_rounds', kind: 'text' },
                    { key: 'timeout_seconds', kind: 'text' },
                ],
                actions: [
                    { label: 'Create step', tone: 'btn-primary', onClick: _confirmStageInsert },
                    { label: 'Cancel', onClick: _cancelStageInsert },
                ],
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

        if ((selection.sectionKey === 'overview' || !selection.nodeKey) && !participantCount && !stageCount) {
            return null;
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
            const selectorTarget = {
                ...target,
                selector_kind: String(target.selector?.kind || ''),
                selector_value: String(target.selector?.value || ''),
            };
            const wrap = document.createElement('div');
            wrap.className = 'kit-authoring-canvas-column';
            wrap.appendChild(Kit.detailsPanel({
                target: selectorTarget,
                surfaceKey: 'protocol.participant',
                onCommit: readOnly ? null : (_t, key, value) => _commitNodeField('participant', selection.nodeKey, key, value),
                schema: applyReadOnly([
                    { key: 'display_name', kind: 'text', required: true },
                    { key: 'participant_key', kind: 'text' },
                    {
                        key: 'selector_kind',
                        kind: 'select',
                        options: (authoringManifest?.selector_kind_options || ['skill', 'role', 'agent']).map((value) => ({
                            value,
                            label: String(value || '').charAt(0).toUpperCase() + String(value || '').slice(1),
                        })),
                        labelKey: 'protocol.participant.selector_kind.label',
                        helpKey: 'protocol.participant.selector_kind.help',
                    },
                    { key: 'selector_value', kind: 'text', labelKey: 'protocol.participant.selector_value.label', helpKey: 'protocol.participant.selector_value.help', placeholderKey: 'protocol.participant.selector_value.placeholder' },
                    { key: 'instructions', kind: 'textarea', rows: 4 },
                ]),
            }));
            const currentQuery = selection.nodeKey === selectorPreview.participantKey
                ? selectorPreview.query
                : _selectorString(target.selector || null);
            wrap.appendChild(Kit.selectorResolutionPreview({
                selector: currentQuery,
                candidates: selection.nodeKey === selectorPreview.participantKey ? selectorPreview.candidates : [],
                busy: selection.nodeKey === selectorPreview.participantKey ? selectorPreview.busy : false,
                message: selection.nodeKey === selectorPreview.participantKey
                    ? selectorPreview.message
                    : Kit.dict.label('protocol.participant.selector_hint'),
                suggestions: _participantSelectorSuggestions(target),
                onSuggestionSelect: readOnly ? null : (value) => { void _applyParticipantSuggestion(selection.nodeKey, value); },
                onResolve: (value) => { void _resolveSelectorPreview(selection.nodeKey, value); },
            }));
            return wrap;
        }
        if (selection.sectionKey === 'stages') {
            const target = (doc.stages || []).find((item) => String(item.stage_key) === selection.nodeKey);
            if (!target) return Kit.detailsPanel({ target: null, surfaceKey: 'protocol' });
            return Kit.detailsPanel({
                target,
                surfaceKey: 'protocol.stage',
                onCommit: readOnly ? null : (_t, key, value) => _commitNodeField('stage', selection.nodeKey, key, value),
                schema: applyReadOnly([
                    { key: 'display_name', kind: 'text', required: true },
                    { key: 'stage_key', kind: 'text' },
                    { key: 'participant_key', kind: 'select', options: participantOptions },
                    { key: 'stage_kind', kind: 'select', options: kindOptions },
                    { key: 'inputs', kind: 'checklist', options: artifactOptions, labelKey: 'protocol.stage.inputs.label', helpKey: 'protocol.stage.inputs.help' },
                    { key: 'outputs', kind: 'checklist', options: artifactOptions, labelKey: 'protocol.stage.outputs.label', helpKey: 'protocol.stage.outputs.help' },
                    { key: 'instructions', kind: 'textarea', rows: 4 },
                    { key: 'max_rounds', kind: 'text' },
                    { key: 'timeout_seconds', kind: 'text' },
                ]),
                actions: readOnly ? [] : [
                    {
                        label: Kit.dict.label('protocol.stage.connect'),
                        onClick: () => _startConnectMode(selection.nodeKey),
                    },
                ],
            });
        }
        if (selection.sectionKey === 'transitions') {
            const target = _transitionEntries(doc).find((item) => String(item.id || '') === selection.nodeKey);
            if (!target) return Kit.detailsPanel({ target: null, surfaceKey: 'protocol', emptyHint: Kit.dict.label('protocol.details.transition.empty') });
            const sourceStage = (doc.stages || []).find((stage) => String(stage.stage_key || '') === String(target.from_stage_key || ''));
            const targetOptions = [
                ...((doc.stages || []).map((stage) => ({
                    value: String(stage.stage_key || ''),
                    label: String(stage.display_name || stage.stage_key || ''),
                }))),
                ...PROTOCOL_TERMINAL_TARGETS.map((item) => ({
                    value: item.key,
                    label: item.label,
                })),
            ];
            return Kit.detailsPanel({
                target: {
                    source_stage: String(target.from_stage_key || ''),
                    decision: String(target.decision || ''),
                    target_key: String(target.target_key || ''),
                },
                surfaceKey: 'protocol.transition',
                onCommit: readOnly ? null : (_t, key, value) => _commitTransitionField(selection.nodeKey, key, value),
                schema: applyReadOnly([
                    { key: 'source_stage', kind: 'text', label: 'From stage', help: 'This transition leaves the selected stage.', readOnly: true },
                    { key: 'decision', kind: 'select', options: _decisionOptionsForStage(sourceStage, target.decision), labelKey: 'protocol.transition.decision.label', helpKey: 'protocol.transition.decision.help' },
                    { key: 'target_key', kind: 'select', options: targetOptions, labelKey: 'protocol.transition.target.label', helpKey: 'protocol.transition.target.help' },
                ]),
                actions: readOnly ? [] : [
                    {
                        label: Kit.dict.label('protocol.transition.delete'),
                        tone: 'btn-danger',
                        onClick: () => UI.showConfirm(
                            'Remove transition',
                            'Remove this transition from the workflow?',
                            async () => { _deleteTransition(selection.nodeKey); },
                        ),
                    },
                ],
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
            UI.reconcileChildren(contentEl, [_catalogEl()]);
            _lifecycleHeaderRef = null;
            return;
        }

        if (protocolDetailLoading) {
            UI.reconcileChildren(contentEl, [UI.renderEmptyState('Loading protocol detail…', true)]);
            _lifecycleHeaderRef = null;
            return;
        }

        const headerEl = _lifecycleHeaderEl();

        const workspace = document.createElement('div');
        workspace.className = 'kit-authoring-workspace';
        workspace.appendChild(_canvasEl());

        const detailsColumn = document.createElement('div');
        detailsColumn.className = 'kit-authoring-details-column';
        const details = _detailsEl();
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
