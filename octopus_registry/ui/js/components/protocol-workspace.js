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
    let connectState = { fromStageKey: '', decision: '' };
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
        currentProtocol = detail;
        draftRevision = Number(detail?.protocol?.draft_revision || 0) || 0;
        draftConflict = null;
        connectState = { fromStageKey: '', decision: '' };
        documentHistory = { undo: [], redo: [] };
        selectorPreview = { participantKey: '', query: '', candidates: [], busy: false, message: '' };
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
        if (!currentProtocolId) {
            await _saveNew();
            if (!currentProtocolId) return;
        } else if (saveState.state === 'editing' || saveState.state === 'saving') {
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
        if (!currentProtocolId) {
            await _saveNew();
            if (!currentProtocolId) return;
        } else if (saveState.state === 'editing' || saveState.state === 'saving') {
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
        connectState = { fromStageKey: '', decision: '' };
        documentHistory = { undo: [], redo: [] };
        selectorPreview = { participantKey: '', query: '', candidates: [], busy: false, message: '' };
        draft = { slug: '', display_name: '', description: '', document: _blankDocument() };
        selection = { sectionKey: 'overview', nodeKey: '' };
        saveState = { state: 'idle', lastSavedAt: '', error: '' };
    }

    async function _saveNew() {
        saveState = { state: 'saving', lastSavedAt: '', error: '' };
        _syncLifecycleChip();
        const result = await API.createProtocol({
            slug: draft.slug,
            display_name: draft.display_name,
            description: draft.description,
            definition_json: _docFromDraft(),
        });
        currentProtocolId = result.protocol?.protocol_id || '';
        _applyServerDetail(result);
        _writeState({ push: true });
        await loadProtocols({ quiet: true });
        render();
        UI.notify('Protocol draft saved.', 'success');
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
        connectState = { fromStageKey: '', decision: '' };
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
            if (connectState.fromStageKey === sourceKey) {
                connectState = { ...connectState, fromStageKey: nextKey };
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
        if (connectState.fromStageKey && !(nextDoc.stages || []).some((stage) => String(stage.stage_key || '') === connectState.fromStageKey)) {
            connectState = { fromStageKey: '', decision: '' };
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

    function _addNode(sectionKey) {
        const doc = _cloneDoc(draft.document);
        if (sectionKey === 'participants') {
            const n = (doc.participants || []).length + 1;
            const key = `participant_${n}`;
            doc.participants = [...(doc.participants || []), {
                participant_key: key,
                display_name: '',
                selector: null,
                instructions: '',
            }];
            _commitDocument(doc, { nextSelection: { sectionKey: 'participants', nodeKey: key } });
            return;
        } else if (sectionKey === 'stages') {
            if (!(doc.participants || []).length) {
                UI.notify('Add a participant before adding a stage.', 'warning');
                selection = { sectionKey: 'overview', nodeKey: '' };
                render();
                return;
            }
            const n = (doc.stages || []).length + 1;
            const key = `stage_${n}`;
            const firstParticipant = String(doc.participants?.[0]?.participant_key || '');
            doc.stages = [...(doc.stages || []), {
                stage_key: key,
                display_name: '',
                participant_key: firstParticipant,
                stage_kind: 'work',
                instructions: '',
                inputs: [],
                outputs: [],
                transitions: {},
            }];
            _commitDocument(doc, { nextSelection: { sectionKey: 'stages', nodeKey: key } });
            return;
        } else if (sectionKey === 'artifacts') {
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
            return;
        }
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

    function _beginTransitionFromStage(stageKey, decision = '') {
        const doc = draft.document;
        const stage = (doc.stages || []).find((item) => String(item.stage_key || '') === String(stageKey || ''));
        if (!stage) return;
        const defaultDecision = String(decision || Object.keys(stage.transitions || {})[0] || (stage.stage_kind === 'work' ? 'completed' : 'accept')).trim().toLowerCase();
        connectState = { fromStageKey: String(stage.stage_key || ''), decision: defaultDecision || 'completed' };
        selection = { sectionKey: 'stages', nodeKey: String(stage.stage_key || '') };
        render();
    }

    function _cancelTransitionConnect() {
        connectState = { fromStageKey: '', decision: '' };
        render();
    }

    function _connectTransitionTarget(targetKey) {
        if (!connectState.fromStageKey) return;
        const doc = _cloneDoc(draft.document);
        const items = [...(doc.stages || [])];
        const idx = items.findIndex((item) => String(item.stage_key || '') === connectState.fromStageKey);
        if (idx < 0) {
            _cancelTransitionConnect();
            return;
        }
        const stage = { ...items[idx] };
        const transitions = Object.assign({}, stage.transitions || {});
        transitions[connectState.decision || 'completed'] = String(targetKey || '');
        stage.transitions = transitions;
        items[idx] = stage;
        doc.stages = items;
        const edgeId = _stageTransitionId(stage.stage_key, connectState.decision || 'completed');
        connectState = { fromStageKey: '', decision: '' };
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
        (connectedAgents || []).slice(0, 6).forEach((agent) => {
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
        if (!suggestions.length) {
            [
                {
                    label: 'Anyone with planning',
                    value: '@skill:planning',
                    selectorKind: 'skill',
                    selectorValue: 'planning',
                    displayName: 'Planner',
                    preferredKey: 'planner',
                },
                {
                    label: 'Any reviewer',
                    value: '@role:reviewer',
                    selectorKind: 'role',
                    selectorValue: 'reviewer',
                    displayName: 'Reviewer',
                    preferredKey: 'reviewer',
                },
            ].forEach(pushSuggestion);
        }
        return suggestions;
    }

    async function _addParticipantFromSuggestion(suggestion) {
        const doc = _cloneDoc(draft.document);
        const n = (doc.participants || []).length + 1;
        const key = `participant_${n}`;
        doc.participants = [...(doc.participants || []), {
            participant_key: key,
            display_name: '',
            selector: null,
            instructions: '',
        }];
        _commitDocument(doc, { nextSelection: { sectionKey: 'participants', nodeKey: key } });
        await _applyParticipantSuggestion(key, suggestion);
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

    function _workflowData() {
        const doc = draft.document;
        const progress = _workflowProgress(doc);
        const participantCount = progress.participantCount;
        const stageCounts = new Map();
        (doc.stages || []).forEach((item) => {
            const key = String(item.participant_key || '').trim();
            stageCounts.set(key, Number(stageCounts.get(key) || 0) + 1);
        });
        const participantMap = new Map((doc.participants || []).map((item) => [
            String(item.participant_key || ''),
            String(item.display_name || item.participant_key || ''),
        ]));
        const stageCount = progress.stageCount;
        const hasStages = stageCount > 0;
        const lanes = [
            ...(doc.participants || []).map((item) => ({
                key: String(item.participant_key || ''),
                label: String(item.display_name || item.participant_key || 'Participant'),
                sublabel: _selectorString(item.selector || null)
                    || `${Number(stageCounts.get(String(item.participant_key || '')) || 0)} stage${Number(stageCounts.get(String(item.participant_key || '')) || 0) === 1 ? '' : 's'}`,
                empty: Kit.dict.label('protocol.stages.firstrun'),
            })),
            ...(hasStages ? [{
                key: '__outcomes__',
                label: Kit.dict.label('protocol.workflow.outcomes'),
                sublabel: Kit.dict.label('protocol.workflow.outcomes_hint'),
            }] : []),
        ];
        const nodes = [
            ...(doc.stages || []).map((item, index) => ({
                id: String(item.stage_key || ''),
                kind: 'stage',
                laneKey: String(item.participant_key || ''),
                column: index,
                label: String(item.display_name || item.stage_key || 'New stage'),
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
            ...(hasStages ? PROTOCOL_TERMINAL_TARGETS.map((item, index) => ({
                id: item.key,
                kind: 'terminal',
                laneKey: '__outcomes__',
                column: stageCount + index,
                label: item.label,
                sublabel: 'Workflow stops here',
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
        const firstRunActions = [];
        if (!participantCount) {
            firstRunActions.push({ label: Kit.dict.label('protocol.participants.add'), onClick: () => _addNode('participants') });
            firstRunActions.push({ label: Kit.dict.label('protocol.catalog.gallery'), tone: '', onClick: () => Router.navigate('/ui/gallery') });
        } else if (!stageCount) {
            firstRunActions.push({ label: Kit.dict.label('protocol.stages.add'), onClick: () => _addNode('stages') });
        } else if (!edges.length) {
            firstRunActions.push({
                label: Kit.dict.label('protocol.stage.connect'),
                onClick: () => _beginTransitionFromStage(doc.stages[0]?.stage_key || ''),
            });
        }
        return {
            lanes,
            nodes,
            edges,
            toolbarActions: progress.nextStep === 'participant' ? [] : [
                {
                    label: Kit.dict.label('protocol.participants.add'),
                    tone: 'btn-small',
                    onClick: () => _addNode('participants'),
                },
                {
                    label: Kit.dict.label('protocol.stages.add'),
                    tone: 'btn-small',
                    onClick: () => _addNode('stages'),
                },
            ],
            accessorySections: (artifactItems.length || hasStages || participantCount > 0)
                ? [
                    {
                        key: 'artifacts',
                        title: Kit.dict.label('protocol.workflow.artifacts'),
                        addLabel: Kit.dict.label('protocol.artifacts.add'),
                        onAdd: () => _addNode('artifacts'),
                        onSelect: (item) => {
                            selection = { sectionKey: 'artifacts', nodeKey: item.id };
                            render();
                        },
                        empty: Kit.dict.label('protocol.artifacts.firstrun'),
                        items: artifactItems,
                    },
                ]
                : [],
            firstRun: {
                active: Boolean(firstRunActions.length),
                title: Kit.dict.label('protocol.canvas.empty.title'),
                body: !participantCount
                    ? Kit.dict.label('protocol.firstrun.participant')
                    : !stageCount
                        ? Kit.dict.label('protocol.firstrun.stage')
                        : Kit.dict.label('protocol.firstrun.transition'),
                steps: [
                    {
                        label: 'Add the role or agent you need first.',
                        state: participantCount ? 'complete' : 'active',
                    },
                    {
                        label: 'Add the first stage that role is responsible for.',
                        state: stageCount ? 'complete' : participantCount ? 'active' : 'pending',
                    },
                    {
                        label: 'Connect the stage to the next step or a finish outcome.',
                        state: progress.edgeCount ? 'complete' : stageCount ? 'active' : 'pending',
                    },
                ],
                actions: firstRunActions,
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
            connectState,
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
                if (connectState.fromStageKey && (kind === 'stage' || kind === 'terminal')) {
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
            onBeginConnect: (stageId) => _beginTransitionFromStage(stageId),
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
        const workflow = _workflowData();
        if (selection.sectionKey === 'overview' || !selection.nodeKey) {
            if (workflow.firstRun?.active) {
                return _starterPanelEl(workflow);
            }
            return Kit.detailsPanel({
                target: {
                    description: draft.description,
                    single_active_writer: Boolean(doc.policies?.single_active_writer ?? true),
                    max_review_rounds: Number(doc.policies?.max_review_rounds || 5) || 5,
                },
                surfaceKey: 'protocol',
                onCommit: _commitOverview,
                schema: [
                    { key: 'description', kind: 'textarea', rows: 4 },
                    { key: 'single_active_writer', kind: 'checkbox', labelKey: 'protocol.policy.single_active_writer.label', helpKey: 'protocol.policy.single_active_writer.help' },
                    { key: 'max_review_rounds', kind: 'text', labelKey: 'protocol.policy.max_review_rounds.label', helpKey: 'protocol.policy.max_review_rounds.help' },
                ],
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
                onCommit: (_t, key, value) => _commitNodeField('participant', selection.nodeKey, key, value),
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
                onSuggestionSelect: (value) => { void _applyParticipantSuggestion(selection.nodeKey, value); },
                onResolve: (value) => { void _resolveSelectorPreview(selection.nodeKey, value); },
            }));
            return wrap;
        }
        if (selection.sectionKey === 'stages') {
            const target = (doc.stages || []).find((item) => String(item.stage_key) === selection.nodeKey);
            if (!target) return Kit.detailsPanel({ target: null, surfaceKey: 'protocol' });
            const participantOptions = [
                { value: '', label: '(none yet)' },
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
            return Kit.detailsPanel({
                target,
                surfaceKey: 'protocol.stage',
                onCommit: (_t, key, value) => _commitNodeField('stage', selection.nodeKey, key, value),
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
                    {
                        label: Kit.dict.label('protocol.stage.connect'),
                        onClick: () => _beginTransitionFromStage(selection.nodeKey),
                    },
                ],
            });
        }
        if (selection.sectionKey === 'transitions') {
            const target = _transitionEntries(doc).find((item) => String(item.id || '') === selection.nodeKey);
            if (!target) return Kit.detailsPanel({ target: null, surfaceKey: 'protocol', emptyHint: Kit.dict.label('protocol.details.transition.empty') });
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
                onCommit: (_t, key, value) => _commitTransitionField(selection.nodeKey, key, value),
                schema: [
                    { key: 'source_stage', kind: 'text', label: 'From stage', help: 'This transition leaves the selected stage.', readOnly: true },
                    { key: 'decision', kind: 'text', labelKey: 'protocol.transition.decision.label', helpKey: 'protocol.transition.decision.help', placeholderKey: 'protocol.transition.decision.placeholder' },
                    { key: 'target_key', kind: 'select', options: targetOptions, labelKey: 'protocol.transition.target.label', helpKey: 'protocol.transition.target.help' },
                ],
                actions: [
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
                onCommit: (_t, key, value) => _commitNodeField('artifact', selection.nodeKey, key, value),
                schema: [
                    { key: 'display_name', kind: 'text', required: true },
                    { key: 'artifact_key', kind: 'text' },
                    { key: 'kind', kind: 'select', options: kindOptions },
                    { key: 'path', kind: 'text', labelKey: 'protocol.artifact.path.label', helpKey: 'protocol.artifact.path.help', placeholderKey: 'protocol.artifact.path.placeholder' },
                    { key: 'description', kind: 'textarea', rows: 3 },
                    { key: 'verify', kind: 'checkbox', labelKey: 'protocol.artifact.verify.label', helpKey: 'protocol.artifact.verify.help' },
                ],
            });
        }
        return Kit.detailsPanel({ target: null, surfaceKey: 'protocol' });
    }

    function _starterPanelEl(workflow) {
        const progress = _workflowProgress();
        const panel = document.createElement('aside');
        panel.className = 'kit-details-panel protocol-starter-panel';

        const eyebrow = document.createElement('div');
        eyebrow.className = 'protocol-starter-eyebrow';
        eyebrow.textContent = progress.participantCount ? 'Next up' : 'Blank workflow';
        panel.appendChild(eyebrow);

        const title = document.createElement('h3');
        title.className = 'protocol-starter-title';
        title.textContent = progress.nextStep === 'participant'
            ? 'Start with the first role in this workflow'
            : progress.nextStep === 'stage'
                ? 'Add the first step that role should handle'
                : 'Connect the workflow so it can finish clearly';
        panel.appendChild(title);

        const body = document.createElement('p');
        body.className = 'protocol-starter-body';
        body.textContent = progress.nextStep === 'participant'
            ? 'Pick a participant first. You can use a connected agent, a role, or a skill-based rule, then refine it in the details panel.'
            : progress.nextStep === 'stage'
                ? 'Stages are the visible workflow steps. Start with one concrete step, then connect later steps only when you need them.'
                : 'Transitions describe what happens next after a stage completes. Connect to another stage or finish outcome to make the flow readable.';
        panel.appendChild(body);

        const steps = document.createElement('ol');
        steps.className = 'protocol-starter-steps';
        [
            { label: 'Participant', done: progress.participantCount > 0, active: progress.nextStep === 'participant' },
            { label: 'Stage', done: progress.stageCount > 0, active: progress.nextStep === 'stage' },
            { label: 'Transition', done: progress.edgeCount > 0, active: progress.nextStep === 'transition' },
        ].forEach((step) => {
            const item = document.createElement('li');
            item.className = `protocol-starter-step${step.done ? ' is-complete' : ''}${step.active ? ' is-active' : ''}`;
            const badge = document.createElement('span');
            badge.className = 'protocol-starter-step-badge';
            badge.textContent = step.done ? 'Done' : step.active ? 'Now' : 'Later';
            item.appendChild(badge);
            const text = document.createElement('span');
            text.className = 'protocol-starter-step-label';
            text.textContent = step.label;
            item.appendChild(text);
            steps.appendChild(item);
        });
        panel.appendChild(steps);

        if (!progress.participantCount) {
            const suggestions = _participantSelectorSuggestions().slice(0, 3);
            if (suggestions.length) {
                const suggestTitle = document.createElement('div');
                suggestTitle.className = 'protocol-starter-suggestions-title';
                suggestTitle.textContent = 'Quick starts';
                panel.appendChild(suggestTitle);
                const suggestRow = document.createElement('div');
                suggestRow.className = 'protocol-starter-suggestions';
                suggestions.forEach((suggestion) => {
                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'btn btn-small';
                    btn.textContent = String(suggestion.label || suggestion.displayName || 'Use this role');
                    btn.addEventListener('click', () => { void _addParticipantFromSuggestion(suggestion); });
                    suggestRow.appendChild(btn);
                });
                panel.appendChild(suggestRow);
            }
        }

        const foot = document.createElement('div');
        foot.className = 'protocol-starter-foot';
        foot.textContent = progress.participantCount
            ? 'You can still rename the workflow and edit description later.'
            : 'You can always switch to a Gallery template if a blank start feels too open-ended.';
        panel.appendChild(foot);
        return panel;
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
        const workflow = _workflowData();
        if (workflow.firstRun?.active && !normalized.length) {
            return null;
        }
        const validation = currentProtocol?.validation;
        if (!validation && !normalized.length) return null;
        const issues = Array.isArray(validation?.issues) ? validation.issues : [];
        normalized.push(...(issues.length
            ? issues.map((item) => ({
                severity: String(item.severity || 'error'),
                message: String(item.message || ''),
                path: String(item.path || ''),
            }))
            : (Array.isArray(validation?.errors) ? validation.errors : []).map((text) => ({
                severity: 'error',
                message: String(text || ''),
            }))));
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
        detailsColumn.appendChild(_detailsEl());
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
        workspace.appendChild(detailsColumn);

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
