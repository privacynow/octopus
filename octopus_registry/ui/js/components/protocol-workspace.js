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

/*
 * Protocol authoring workspace — kit-driven surface.
 *
 * This route is the reference implementation of the authoring kit (see
 * telegram-agent-bot/protocol_kit_plan.md). It is intentionally short: all
 * visuals go through Kit.lifecycleHeader, Kit.authoredCatalog, Kit.canvas,
 * Kit.detailsPanel, and Kit.validationSurface. No bespoke section tabs, no
 * raw-JSON tab, no server-seeded defaults — the canvas starts blank and the
 * user adds the first participant/stage/artifact from there.
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

    function _applyServerDetail(detail) {
        currentProtocol = detail;
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
        const items = doc[key] || [];
        const hit = items.find((item) => String(
            key === 'participants' ? item.participant_key
                : key === 'stages' ? item.stage_key
                    : item.artifact_key,
        ) === current.nodeKey);
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
            });
            _applyServerDetail(result);
            saveState = { state: 'saved', lastSavedAt: new Date().toISOString(), error: '' };
            _syncLifecycleChip();
            await loadProtocols({ quiet: true });
            render();
        } catch (err) {
            saveState = { state: 'error', lastSavedAt: saveState.lastSavedAt, error: err.message || String(err) };
            _syncLifecycleChip();
            UI.reportError('Failed to save the protocol draft', err, { context: 'Protocol autosave failed' });
        }
    }

    async function _validateNow() {
        if (!currentProtocolId) {
            await _saveNew();
            if (!currentProtocolId) return;
        } else if (saveState.state === 'editing' || saveState.state === 'saving') {
            await _autosave();
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
        if (!currentProtocolId) {
            await _saveNew();
            if (!currentProtocolId) return;
        } else if (saveState.state === 'editing' || saveState.state === 'saving') {
            await _autosave();
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
            const [sessionsResp, scenariosResp] = await Promise.all([
                API.listRehearsalSessions(rehearsal.runId),
                API.listProtocolScenarios({ protocol_id: currentProtocolId || '' }),
            ]);
            rehearsal.sessions = Array.isArray(sessionsResp?.sessions) ? sessionsResp.sessions : [];
            rehearsal.scenarios = Array.isArray(scenariosResp?.scenarios) ? scenariosResp.scenarios : [];
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
        if (!currentProtocolId) return;
        const run = await API.createProtocolRun({
            protocol_id: currentProtocolId,
            is_rehearsal: true,
            entry_authority_ref: 'rehearsal',
        });
        rehearsal.runId = String(run?.protocol_run?.protocol_run_id || run?.protocol_run_id || '');
        rehearsal.sessions = [];
        rehearsal.scenarios = [];
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
        }
        _scheduleAutosave();
        _syncLifecycleHeaderInputs();
    }

    function _commitNodeField(kind, nodeKey, key, value) {
        const plural = kind + 's';
        const doc = _cloneDoc(draft.document);
        const items = Array.isArray(doc[plural]) ? doc[plural] : [];
        const idField = kind === 'participant' ? 'participant_key' : kind === 'stage' ? 'stage_key' : 'artifact_key';
        const idx = items.findIndex((item) => String(item[idField] || '') === nodeKey);
        if (idx < 0) return;
        const next = Object.assign({}, items[idx]);
        if (key === 'required_skills') {
            next.required_skills = String(value || '').split(',').map((item) => item.trim()).filter(Boolean);
        } else if (key === 'max_rounds' || key === 'timeout_seconds') {
            next[key] = Number.parseInt(String(value || '0'), 10) || 0;
        } else {
            next[key] = value;
        }
        // slug-style rekey when editing the identity field
        if (key === idField) {
            next[idField] = _slugSuggestion(value) || nodeKey;
        }
        items[idx] = next;
        doc[plural] = items;
        draft.document = doc;
        if (key === idField && next[idField] !== nodeKey) {
            selection = { sectionKey: plural, nodeKey: String(next[idField]) };
        }
        _scheduleAutosave();
        render();
    }

    function _addNode(sectionKey) {
        const doc = _cloneDoc(draft.document);
        if (sectionKey === 'participants') {
            const n = (doc.participants || []).length + 1;
            const key = `participant_${n}`;
            doc.participants = [...(doc.participants || []), {
                participant_key: key,
                display_name: '',
                required_skills: [],
                instructions: '',
            }];
            selection = { sectionKey: 'participants', nodeKey: key };
        } else if (sectionKey === 'stages') {
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
            selection = { sectionKey: 'stages', nodeKey: key };
        } else if (sectionKey === 'artifacts') {
            const n = (doc.artifacts || []).length + 1;
            const key = `artifact_${n}`;
            doc.artifacts = [...(doc.artifacts || []), {
                artifact_key: key,
                display_name: '',
                kind: 'workspace_file',
                description: '',
            }];
            selection = { sectionKey: 'artifacts', nodeKey: key };
        }
        draft.document = doc;
        _scheduleAutosave();
        render();
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
        const hasPublishedVersion = Boolean(currentProtocol?.protocol?.current_version_id)
            || (Array.isArray(currentProtocol?.versions)
                && currentProtocol.versions.some((v) => String(v.lifecycle_state || '') === 'published'));
        const permissions = {
            canPublish: Boolean(currentProtocolId),
            canArchive: Boolean(currentProtocolId) && lifecycleState !== 'archived',
            canRehearse: Boolean(currentProtocolId) && hasPublishedVersion && lifecycleState !== 'archived',
            canDiscard: Boolean(currentProtocolId),
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

    function _canvasEl() {
        const doc = draft.document;
        const participantNodes = (doc.participants || []).map((item) => ({
            key: String(item.participant_key || ''),
            label: String(item.display_name || item.participant_key || 'New participant'),
            sublabel: (item.required_skills || []).join(', '),
        }));
        const stageNodes = (doc.stages || []).map((item) => ({
            key: String(item.stage_key || ''),
            label: String(item.display_name || item.stage_key || 'New stage'),
            sublabel: [
                Kit.dict.label(`protocol.stage.kind.${item.stage_kind || 'work'}`),
                item.participant_key || '',
            ].filter(Boolean).join(' · '),
        }));
        const artifactNodes = (doc.artifacts || []).map((item) => ({
            key: String(item.artifact_key || ''),
            label: String(item.display_name || item.artifact_key || 'New artifact'),
            sublabel: String(item.kind || ''),
        }));

        return Kit.canvas({
            selection,
            onSelect: ({ sectionKey, nodeKey }) => {
                selection = { sectionKey, nodeKey };
                render();
            },
            sections: [
                {
                    key: 'participants',
                    title: Kit.dict.label('protocol.participants.section'),
                    addLabel: Kit.dict.label('protocol.participants.add'),
                    firstRunHint: Kit.dict.label('protocol.participants.firstrun'),
                    onAdd: () => _addNode('participants'),
                    nodes: participantNodes,
                },
                {
                    key: 'stages',
                    title: Kit.dict.label('protocol.stages.section'),
                    addLabel: Kit.dict.label('protocol.stages.add'),
                    firstRunHint: Kit.dict.label('protocol.stages.firstrun'),
                    onAdd: () => _addNode('stages'),
                    nodes: stageNodes,
                },
                {
                    key: 'artifacts',
                    title: Kit.dict.label('protocol.artifacts.section'),
                    addLabel: Kit.dict.label('protocol.artifacts.add'),
                    firstRunHint: Kit.dict.label('protocol.artifacts.firstrun'),
                    onAdd: () => _addNode('artifacts'),
                    nodes: artifactNodes,
                },
            ],
        });
    }

    function _detailsEl() {
        const doc = draft.document;
        if (selection.sectionKey === 'overview' || !selection.nodeKey) {
            return Kit.detailsPanel({
                target: { display_name: draft.display_name, slug: draft.slug, description: draft.description },
                surfaceKey: 'protocol',
                onCommit: _commitOverview,
                schema: [
                    { key: 'display_name', kind: 'text', required: true },
                    { key: 'slug', kind: 'text' },
                    { key: 'description', kind: 'textarea', rows: 4 },
                ],
            });
        }
        if (selection.sectionKey === 'participants') {
            const target = (doc.participants || []).find((item) => String(item.participant_key) === selection.nodeKey);
            if (!target) return Kit.detailsPanel({ target: null, surfaceKey: 'protocol' });
            const view = { ...target, required_skills: (target.required_skills || []).join(', ') };
            return Kit.detailsPanel({
                target: view,
                surfaceKey: 'protocol.participant',
                onCommit: (_t, key, value) => _commitNodeField('participant', selection.nodeKey, key, value),
                schema: [
                    { key: 'display_name', kind: 'text', required: true },
                    { key: 'participant_key', kind: 'text' },
                    { key: 'instructions', kind: 'textarea', rows: 4 },
                    { key: 'required_skills', kind: 'text' },
                ],
            });
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
            return Kit.detailsPanel({
                target,
                surfaceKey: 'protocol.stage',
                onCommit: (_t, key, value) => _commitNodeField('stage', selection.nodeKey, key, value),
                schema: [
                    { key: 'display_name', kind: 'text', required: true },
                    { key: 'stage_key', kind: 'text' },
                    { key: 'participant_key', kind: 'select', options: participantOptions },
                    { key: 'stage_kind', kind: 'select', options: kindOptions },
                    { key: 'instructions', kind: 'textarea', rows: 4 },
                    { key: 'max_rounds', kind: 'text' },
                    { key: 'timeout_seconds', kind: 'text' },
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
                    { key: 'description', kind: 'textarea', rows: 3 },
                ],
            });
        }
        return Kit.detailsPanel({ target: null, surfaceKey: 'protocol' });
    }

    function _validationEl() {
        const validation = currentProtocol?.validation;
        if (!validation) return null;
        const issues = Array.isArray(validation.issues) ? validation.issues : [];
        const normalized = issues.length
            ? issues.map((item) => ({
                severity: String(item.severity || 'error'),
                message: String(item.message || ''),
                path: String(item.path || ''),
            }))
            : (Array.isArray(validation.errors) ? validation.errors : []).map((text) => ({
                severity: 'error',
                message: String(text || ''),
            }));
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
        });
    }

    function render() {
        if (!currentProtocolId) {
            const catalog = _catalogEl();
            const galleryCta = document.createElement('div');
            galleryCta.className = 'kit-catalog-tertiary';
            const galleryButton = document.createElement('button');
            galleryButton.type = 'button';
            galleryButton.className = 'btn';
            galleryButton.textContent = 'Browse template gallery';
            galleryButton.addEventListener('click', () => Router.navigate('/ui/gallery'));
            galleryCta.appendChild(galleryButton);
            UI.reconcileChildren(contentEl, [catalog, galleryCta]);
            _lifecycleHeaderRef = null;
            return;
        }

        if (protocolDetailLoading) {
            UI.reconcileChildren(contentEl, [UI.renderEmptyState('Loading protocol detail…', true)]);
            _lifecycleHeaderRef = null;
            return;
        }

        const headerEl = _lifecycleHeaderEl();
        _lifecycleHeaderRef = headerEl;

        const workspace = document.createElement('div');
        workspace.className = 'kit-authoring-workspace';
        const canvasColumn = document.createElement('div');
        canvasColumn.className = 'kit-authoring-canvas-column';
        canvasColumn.appendChild(_canvasEl());
        const validation = _validationEl();
        if (validation) canvasColumn.appendChild(validation);
        workspace.appendChild(canvasColumn);

        const detailsColumn = document.createElement('div');
        detailsColumn.className = 'kit-authoring-details-column';
        detailsColumn.appendChild(_detailsEl());
        if (rehearsal.runId) {
            detailsColumn.appendChild(Kit.rehearsalPanel({
                runId: rehearsal.runId,
                sessions: rehearsal.sessions,
                scenarios: rehearsal.scenarios,
                onRespond: (payload) => { void _respondRehearsal(payload); },
            }));
        }
        workspace.appendChild(detailsColumn);

        UI.reconcileChildren(contentEl, [headerEl, workspace]);
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
            await Promise.all([loadProtocols({ quiet: true }), loadAuthoringManifest()]);
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
