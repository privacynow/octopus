const PROTOCOL_RUN_STATUS_OPTIONS = [
    { value: '', label: 'All runs' },
    { value: 'running', label: 'Running' },
    { value: 'blocked', label: 'Blocked' },
    { value: 'completed', label: 'Completed' },
    { value: 'failed', label: 'Failed' },
    { value: 'cancelled', label: 'Cancelled' },
];

const PROTOCOL_ISSUE_FILTER_OPTIONS = [
    { value: '', label: 'Runs' },
    { value: 'all', label: 'All issues' },
    { value: 'blocked_run', label: 'Blocked runs' },
    { value: 'invalid_contract', label: 'Contract errors' },
    { value: 'stuck_lease', label: 'Stuck leases' },
    { value: 'expired_timeout', label: 'Expired timeouts' },
];

const PROTOCOL_AUTHORING_SECTION_OPTIONS = [
    { value: 'overview', label: 'Overview' },
    { value: 'participants', label: 'Participants' },
    { value: 'stages', label: 'Stages' },
    { value: 'artifacts', label: 'Artifacts' },
    { value: 'policies', label: 'Policies' },
    { value: 'review', label: 'Review' },
    { value: 'advanced', label: 'Advanced' },
];

const PROTOCOL_CATALOG_STATUS_OPTIONS = [
    { value: '', label: 'All statuses' },
    { value: 'draft', label: 'Drafts' },
    { value: 'published', label: 'Published' },
    { value: 'archived', label: 'Archived' },
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

function _readProtocolFileText(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(reader.error || new Error('Failed to read file'));
        reader.onload = () => resolve(String(reader.result || ''));
        reader.readAsText(file);
    });
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

function _protocolRunDeepLink(run, params = {}) {
    const search = new URLSearchParams();
    const runId = String(run?.protocol_run_id || params.run_id || '').trim();
    if (runId) {
        search.set('run_id', runId);
    }
    const status = String(params.status || '').trim();
    if (status) {
        search.set('status', status);
    }
    const issueKind = _protocolIssueFilterValue(params.issue_kind || '');
    if (issueKind) {
        search.set('issue_kind', issueKind);
    }
    const suffix = search.toString();
    return suffix ? `/ui/protocol-runs?${suffix}` : '/ui/protocol-runs';
}

function renderProtocolWorkspace(container) {
    const cleanups = UI.beginCleanupScope();
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }

    let protocols = [];
    let currentProtocolId = UI.readQueryParam('protocol_id', '');
    let currentProtocol = null;
    let protocolDetailLoading = false;
    let authoringManifest = null;
    let editorFormat = 'json';
    let protocolSearch = '';
    let protocolLifecycleFilter = '';
    let currentSection = '';
    let selectedParticipantKey = '';
    let selectedArtifactKey = '';
    let selectedStageKey = '';
    let draftSaveState = 'idle';
    let autosaveTimer = 0;
    const structuredInputDrafts = new Map();
    let draft = {
        protocol_id: '',
        slug: '',
        display_name: '',
        description: '',
        definition_text: '',
        document_json: null,
        parse_error: '',
    };

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Protocols</h2><p>Author reusable, versioned workflow definitions without the live run console in the way.</p>';
    container.appendChild(header);

    const shell = document.createElement('section');
    shell.className = 'admin-shell protocol-route-shell';
    container.appendChild(shell);

    const contentEl = document.createElement('div');
    contentEl.className = 'protocol-surface-shell';
    shell.appendChild(contentEl);
    const authorBoard = document.createElement('div');
    authorBoard.className = 'dashboard-board protocol-author-board';
    const listColumnEl = document.createElement('div');
    listColumnEl.className = 'dashboard-column';
    const editorColumnEl = document.createElement('div');
    editorColumnEl.className = 'dashboard-column';
    authorBoard.appendChild(listColumnEl);
    authorBoard.appendChild(editorColumnEl);

    const _validSectionValues = new Set(PROTOCOL_AUTHORING_SECTION_OPTIONS.map((item) => item.value));

    function _normalizeAuthorSection(value) {
        const normalized = String(value || '').trim().toLowerCase();
        return _validSectionValues.has(normalized) ? normalized : 'overview';
    }

    function _sectionLabel(value) {
        return PROTOCOL_AUTHORING_SECTION_OPTIONS.find((item) => item.value === value)?.label || 'Overview';
    }

    function _readAuthorSection() {
        return _normalizeAuthorSection(UI.readQueryParam('protocol_section', 'overview'));
    }

    currentSection = _readAuthorSection();

    function _writeState({ push = false } = {}) {
        UI.updateQueryParams({
            protocol_id: currentProtocolId || '',
            protocol_section: currentProtocolId ? currentSection : '',
            run_id: '',
            status: '',
            issue_kind: '',
            entry_agent_id: '',
        }, { replace: !push });
    }

    function _resetDraftState() {
        _clearAutosaveTimer();
        currentProtocolId = '';
        currentProtocol = null;
        protocolDetailLoading = false;
        currentSection = 'overview';
        selectedParticipantKey = '';
        selectedArtifactKey = '';
        selectedStageKey = '';
        draftSaveState = 'idle';
        draft = {
            protocol_id: '',
            slug: '',
            display_name: '',
            description: '',
            definition_text: '',
            document_json: _cloneDocument(_defaultProtocolDocument()),
            parse_error: '',
        };
        _clearStructuredDrafts();
    }

    function _revealEditorSurface() {
        requestAnimationFrame(() => {
            editorColumnEl.scrollIntoView({ block: 'start', behavior: 'smooth' });
        });
    }

    function _defaultProtocolDocument() {
        return {
            schema_version: 1,
            metadata: {},
            participants: [],
            artifacts: [],
            stages: [],
            policies: {
                single_active_writer: true,
                max_review_rounds: 5,
            },
        };
    }

    function _cloneDocument(value) {
        return JSON.parse(JSON.stringify(value || _defaultProtocolDocument()));
    }

    function _draftDocument() {
        return _cloneDocument(draft.document_json || _defaultProtocolDocument());
    }

    function _syncDraftFieldsFromDocument(document) {
        const metadata = (document && document.metadata) || {};
        draft.slug = String(metadata.slug || draft.slug || '');
        draft.display_name = String(metadata.display_name || draft.display_name || '');
        draft.description = String(metadata.description || draft.description || '');
    }

    function _clearStructuredDrafts(prefix = '') {
        if (!prefix) {
            structuredInputDrafts.clear();
            return;
        }
        Array.from(structuredInputDrafts.keys()).forEach((key) => {
            if (String(key || '').startsWith(prefix)) {
                structuredInputDrafts.delete(key);
            }
        });
    }

    function _rememberStructuredDraftValue(draftKey, value) {
        if (!draftKey) {
            return;
        }
        structuredInputDrafts.set(draftKey, value);
    }

    function _resolveStructuredDraftValue(draftKey, committedValue, normalize) {
        if (!draftKey || !structuredInputDrafts.has(draftKey)) {
            return committedValue;
        }
        const pendingValue = structuredInputDrafts.get(draftKey);
        if (normalize(pendingValue) === normalize(committedValue)) {
            structuredInputDrafts.delete(draftKey);
            return committedValue;
        }
        return pendingValue;
    }

    function _applyDraftMetadataToDocument(document) {
        const next = _cloneDocument(document);
        next.schema_version = Number(next.schema_version || 1) || 1;
        next.metadata = Object.assign({}, next.metadata || {}, {
            slug: String(draft.slug || next.metadata?.slug || '').trim(),
            display_name: String(draft.display_name || next.metadata?.display_name || '').trim(),
            description: String(draft.description || next.metadata?.description || '').trim(),
        });
        next.participants = Array.isArray(next.participants) ? next.participants : [];
        next.artifacts = Array.isArray(next.artifacts) ? next.artifacts : [];
        next.stages = Array.isArray(next.stages) ? next.stages : [];
        next.policies = Object.assign({
            single_active_writer: true,
            max_review_rounds: 5,
        }, next.policies || {});
        return next;
    }

    function _mergeProtocolMutation(detail) {
        if (!detail) {
            return;
        }
        currentProtocol = Object.assign({}, currentProtocol || {}, detail, {
            protocol: detail.protocol || currentProtocol?.protocol || null,
            version: detail.version || currentProtocol?.version || null,
            validation: detail.validation || currentProtocol?.validation || null,
            draft_definition_json: detail.draft_definition_json || currentProtocol?.draft_definition_json || null,
            draft_document: Object.prototype.hasOwnProperty.call(detail, 'draft_document')
                ? detail.draft_document
                : (currentProtocol?.draft_document || null),
        });
    }

    function _clearAutosaveTimer() {
        if (autosaveTimer) {
            clearTimeout(autosaveTimer);
            autosaveTimer = 0;
        }
    }

    function _savePayloadFromDraft() {
        if (draft.parse_error) {
            throw new Error('Fix the Advanced raw editor syntax before saving this draft.');
        }
        const document = _applyDraftMetadataToDocument(_draftDocument());
        return {
            slug: draft.slug,
            display_name: draft.display_name,
            description: draft.description,
            definition_json: document,
        };
    }

    async function _serializeProtocolDocument(document, format = editorFormat) {
        const normalized = _applyDraftMetadataToDocument(document);
        if (format === 'json') {
            return JSON.stringify(normalized, null, 2);
        }
        const parsed = await API.parseProtocolDocument({
            definition_text: JSON.stringify(normalized, null, 2),
            format,
            validation_mode: 'draft',
        });
        return String(parsed.text || '');
    }

    async function _parseDraftDocument({ report = false } = {}) {
        const result = await API.parseProtocolDocument({
            definition_text: draft.definition_text || '',
            format: editorFormat,
            validation_mode: 'draft',
        });
        if (!result.document) {
            const message = (result.validation && result.validation.errors && result.validation.errors.join(' · '))
                || 'Protocol draft is invalid.';
            draft.parse_error = message;
            if (report) {
                throw new Error(message);
            }
            return null;
        }
        const document = _applyDraftMetadataToDocument(result.document);
        draft.document_json = document;
        draft.parse_error = '';
        _syncDraftFieldsFromDocument(document);
        _mergeProtocolMutation({ validation: result.validation || null });
        return document;
    }

    async function _autosaveCurrentDraft() {
        if (!currentProtocolId) {
            return;
        }
        const payload = _savePayloadFromDraft();
        draftSaveState = 'saving';
        renderAuthorRoute();
        try {
            const result = await API.saveProtocolDraft(currentProtocolId, payload);
            _mergeProtocolMutation(result);
            draftSaveState = 'saved';
            await loadProtocols();
            renderAuthorRoute();
        } catch (err) {
            draftSaveState = 'error';
            renderAuthorRoute();
            UI.reportError('Failed to save the protocol draft', err, {
                context: 'Protocol autosave failed',
            });
        }
    }

    function _scheduleAutosave() {
        if (!currentProtocolId || draft.parse_error) {
            return;
        }
        _clearAutosaveTimer();
        draftSaveState = 'dirty';
        autosaveTimer = setTimeout(() => {
            autosaveTimer = 0;
            void _autosaveCurrentDraft();
        }, 450);
    }

    async function _commitDraftDocument(document, { rerender = true, autosave = true } = {}) {
        const normalized = _applyDraftMetadataToDocument(document);
        draft.document_json = normalized;
        draft.parse_error = '';
        _syncDraftFieldsFromDocument(normalized);
        draft.definition_text = await _serializeProtocolDocument(normalized, editorFormat);
        _mergeProtocolMutation({
            draft_definition_json: normalized,
            draft_document: null,
            validation: currentProtocol?.validation || null,
        });
        if (autosave) {
            _scheduleAutosave();
        }
        if (rerender) {
            renderAuthorRoute();
        }
        return normalized;
    }

    async function _applyStructuredChange(mutator) {
        try {
            const working = _draftDocument();
            mutator(working);
            await _commitDraftDocument(working);
        } catch (err) {
            UI.reportError('Failed to update the structured protocol editor', err, {
                context: 'Protocol structured editor update failed',
            });
        }
    }

    async function _syncEditorFormat(nextFormat) {
        const parsed = await _parseDraftDocument({ report: true }) || _draftDocument();
        editorFormat = nextFormat;
        draft.definition_text = await _serializeProtocolDocument(parsed, nextFormat);
    }

    function _applyDraftFromProtocol(detail) {
        currentProtocol = detail;
        _clearStructuredDrafts();
        selectedParticipantKey = '';
        selectedArtifactKey = '';
        selectedStageKey = '';
        const rawDraftDocument = detail && detail.draft_definition_json
            && Object.keys(detail.draft_definition_json).length
            ? detail.draft_definition_json
            : null;
        const draftDocument = rawDraftDocument || (detail && detail.draft_document) || _defaultProtocolDocument();
        draft = {
            protocol_id: detail?.protocol?.protocol_id || '',
            slug: detail?.protocol?.slug || draftDocument.metadata?.slug || '',
            display_name: detail?.protocol?.display_name || draftDocument.metadata?.display_name || '',
            description: detail?.protocol?.description || draftDocument.metadata?.description || '',
            definition_text: editorFormat === 'yaml'
                ? ''
                : JSON.stringify(draftDocument, null, 2),
            document_json: _cloneDocument(draftDocument),
            parse_error: '',
        };
        draftSaveState = 'idle';
        _clearAutosaveTimer();
        _setSelectedEntityDefaults(draft.document_json);
    }

    async function _refreshDraftTextForCurrentFormat() {
        if (!currentProtocol && !draft.definition_text) {
            draft.document_json = _cloneDocument(_defaultProtocolDocument());
            draft.definition_text = editorFormat === 'yaml'
                ? String((await API.parseProtocolDocument({
                    definition_text: JSON.stringify(_defaultProtocolDocument(), null, 2),
                    format: 'yaml',
                    validation_mode: 'draft',
                })).text || '')
                : JSON.stringify(_defaultProtocolDocument(), null, 2);
            return;
        }
        const source = currentProtocol?.draft_document || currentProtocol?.draft_definition_json || draft.document_json || _defaultProtocolDocument();
        draft.document_json = _cloneDocument(source);
        draft.parse_error = '';
        if (editorFormat === 'json') {
            draft.definition_text = JSON.stringify(source, null, 2);
            return;
        }
        const parsed = await API.parseProtocolDocument({
            definition_text: JSON.stringify(source, null, 2),
            format: editorFormat,
            validation_mode: 'draft',
        });
        draft.definition_text = String(parsed.text || '');
    }

    function _renderValidationGutter(parent) {
        const validation = currentProtocol?.validation;
        const parseError = String(draft.parse_error || '');
        if (!validation && !parseError) {
            return;
        }
        const ok = Boolean(validation && validation.ok && !parseError);
        const issueMessages = Array.isArray(validation?.issues)
            ? validation.issues.map((item) => String(item.message || '').trim()).filter(Boolean)
            : [];
        const gutter = document.createElement('section');
        gutter.className = `protocol-validation-gutter ${ok ? 'is-valid' : 'is-invalid'}`;
        gutter.setAttribute('role', ok ? 'status' : 'alert');
        const title = document.createElement('strong');
        title.textContent = ok
            ? (String(validation?.mode || 'strict') === 'draft' ? 'Draft looks healthy' : 'Validation passed')
            : 'Validation issues';
        gutter.appendChild(title);
        const summary = document.createElement('div');
        summary.className = 'quiet-note';
        summary.textContent = ok
            ? `Draft valid. Content hash: ${validation?.content_hash || 'n/a'}`
            : parseError || `${issueMessages.length || validation?.errors.length || 0} issue(s) found.`;
        gutter.appendChild(summary);
        if (!ok && (issueMessages.length || validation?.errors.length)) {
            const list = document.createElement('ul');
            list.className = 'protocol-validation-list';
            (issueMessages.length ? issueMessages : validation.errors).forEach((item) => {
                const li = document.createElement('li');
                li.textContent = item;
                list.appendChild(li);
            });
            gutter.appendChild(list);
        }
        parent.appendChild(gutter);
    }

    function _textInput(value, onCommit, { placeholder = '', ariaLabel = '', draftKey = '' } = {}) {
        const input = document.createElement('input');
        input.className = 'search-input';
        input.placeholder = placeholder;
        input.value = String(_resolveStructuredDraftValue(
            draftKey,
            String(value || ''),
            (item) => String(item || ''),
        ) || '');
        if (ariaLabel) {
            input.setAttribute('aria-label', ariaLabel);
        }
        input.addEventListener('input', () => _rememberStructuredDraftValue(draftKey, String(input.value || '')));
        input.addEventListener('change', () => {
            const nextValue = String(input.value || '');
            _rememberStructuredDraftValue(draftKey, nextValue);
            onCommit(nextValue);
        });
        return input;
    }

    function _numberInput(value, onCommit, { min = 0, placeholder = '', ariaLabel = '', draftKey = '' } = {}) {
        const input = document.createElement('input');
        input.type = 'number';
        input.className = 'search-input';
        input.min = String(min);
        input.placeholder = placeholder;
        input.value = String(_resolveStructuredDraftValue(
            draftKey,
            String(value ?? ''),
            (item) => String(item ?? ''),
        ) ?? '');
        if (ariaLabel) {
            input.setAttribute('aria-label', ariaLabel);
        }
        input.addEventListener('input', () => _rememberStructuredDraftValue(draftKey, String(input.value ?? '')));
        input.addEventListener('change', () => {
            const nextValue = String(input.value ?? '');
            _rememberStructuredDraftValue(draftKey, nextValue);
            onCommit(Number.parseInt(nextValue || '0', 10) || 0);
        });
        return input;
    }

    function _textAreaInput(value, onCommit, { placeholder = '', rows = 3, ariaLabel = '', draftKey = '' } = {}) {
        const area = document.createElement('textarea');
        area.className = 'guidance-textarea protocol-structured-textarea';
        area.rows = rows;
        area.placeholder = placeholder;
        area.value = String(_resolveStructuredDraftValue(
            draftKey,
            String(value || ''),
            (item) => String(item || ''),
        ) || '');
        if (ariaLabel) {
            area.setAttribute('aria-label', ariaLabel);
        }
        area.addEventListener('input', () => _rememberStructuredDraftValue(draftKey, String(area.value || '')));
        area.addEventListener('change', () => {
            const nextValue = String(area.value || '');
            _rememberStructuredDraftValue(draftKey, nextValue);
            onCommit(nextValue);
        });
        return area;
    }

    function _selectInput(options, value, onCommit, { ariaLabel = '', draftKey = '' } = {}) {
        const select = document.createElement('select');
        select.className = 'search-input';
        const selectedValue = String(_resolveStructuredDraftValue(
            draftKey,
            String(value || ''),
            (item) => String(item || ''),
        ) || '');
        if (ariaLabel) {
            select.setAttribute('aria-label', ariaLabel);
        }
        options.forEach((item) => {
            const option = document.createElement('option');
            option.value = String(item.value || '');
            option.textContent = String(item.label || item.value || '');
            option.selected = String(item.value || '') === selectedValue;
            select.appendChild(option);
        });
        select.addEventListener('change', () => {
            const nextValue = String(select.value || '');
            _rememberStructuredDraftValue(draftKey, nextValue);
            onCommit(nextValue);
        });
        return select;
    }

    function _checkboxInput(checked, labelText, onCommit, { ariaLabel = '', draftKey = '' } = {}) {
        const label = document.createElement('label');
        label.className = 'protocol-inline-checkbox';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.checked = Boolean(_resolveStructuredDraftValue(
            draftKey,
            Boolean(checked),
            (item) => Boolean(item),
        ));
        if (ariaLabel) {
            input.setAttribute('aria-label', ariaLabel);
        }
        input.addEventListener('change', () => {
            const nextValue = Boolean(input.checked);
            _rememberStructuredDraftValue(draftKey, nextValue);
            onCommit(nextValue);
        });
        const text = document.createElement('span');
        text.textContent = labelText;
        label.appendChild(input);
        label.appendChild(text);
        return label;
    }

    function _commaList(value) {
        return String(value || '')
            .split(',')
            .map((item) => item.trim())
            .filter(Boolean);
    }


    async function _downloadDraft(format) {
        const normalized = format === 'yaml' ? 'yaml' : 'json';
        try {
            let exported;
            if (currentProtocolId) {
                exported = await API.exportProtocolDraft(currentProtocolId, normalized);
            } else {
                const document = await _parseDraftDocument({ report: true }) || _draftDocument();
                exported = {
                    text: await _serializeProtocolDocument(document, normalized),
                };
            }
            _downloadProtocolText(
                `${UI.safeFilename(draft.slug || currentProtocol?.protocol?.slug || 'protocol')}.${normalized === 'yaml' ? 'yaml' : 'json'}`,
                String(exported.text || ''),
                normalized === 'yaml' ? 'text/yaml' : 'application/json',
            );
        } catch (err) {
            UI.reportError('Failed to export the protocol draft', err, {
                context: 'Protocol draft export failed',
            });
        }
    }

    async function _showDraftDiff() {
        if (!currentProtocolId) {
            UI.notify('Create and publish the protocol before requesting a diff.', 'warning');
            return;
        }
        try {
            const result = await API.diffProtocolDraft(currentProtocolId, editorFormat);
            UI.showTextDialog(
                `Protocol diff · ${draft.display_name || draft.slug || currentProtocolId}`,
                result.diff || 'No differences.',
                { maxWidth: '960px' },
            );
        } catch (err) {
            UI.reportError('Failed to generate the protocol diff', err, {
                context: 'Protocol diff failed',
            });
        }
    }

    function _manifestTemplates() {
        return Array.isArray(authoringManifest?.templates) ? authoringManifest.templates : [];
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

    function _manifestSelectorKindOptions() {
        return Array.isArray(authoringManifest?.selector_kind_options) && authoringManifest.selector_kind_options.length
            ? authoringManifest.selector_kind_options
            : ['agent', 'skill', 'role'];
    }

    function _setSelectedEntityDefaults(document = _draftDocument()) {
        if (!selectedParticipantKey && document.participants?.length) {
            selectedParticipantKey = String(document.participants[0].participant_key || '');
        }
        if (!selectedArtifactKey && document.artifacts?.length) {
            selectedArtifactKey = String(document.artifacts[0].artifact_key || '');
        }
        if (!selectedStageKey && document.stages?.length) {
            selectedStageKey = String(document.stages[0].stage_key || '');
        }
    }

    async function _saveCurrentDraft() {
        _clearAutosaveTimer();
        draftSaveState = 'saving';
        renderAuthorRoute();
        const payload = _savePayloadFromDraft();
        const result = currentProtocolId
            ? await API.saveProtocolDraft(currentProtocolId, payload)
            : await API.createProtocol(payload);
        currentProtocolId = result.protocol?.protocol_id || currentProtocolId;
        currentProtocol = result;
        _applyDraftFromProtocol(result);
        await _refreshDraftTextForCurrentFormat();
        await loadProtocols();
        if (currentProtocolId) {
            await loadProtocolDetail();
        } else {
            renderAuthorRoute();
        }
        draftSaveState = 'saved';
        UI.notify('Protocol draft saved.', 'success');
    }

    async function _validateCurrentDraft() {
        if (!currentProtocolId) {
            await _saveCurrentDraft();
        } else if (draftSaveState === 'dirty' || draftSaveState === 'saving') {
            await _saveCurrentDraft();
        }
        draftSaveState = 'saving';
        renderAuthorRoute();
        currentProtocol = await API.validateProtocol(currentProtocolId);
        _applyDraftFromProtocol(currentProtocol);
        await _refreshDraftTextForCurrentFormat();
        draftSaveState = 'saved';
        renderAuthorRoute();
        UI.notify(
            currentProtocol.validation?.ok ? 'Protocol validated.' : 'Protocol validation found issues.',
            currentProtocol.validation?.ok ? 'success' : 'warning',
        );
    }

    async function _publishCurrentDraft() {
        if (!currentProtocolId) {
            await _saveCurrentDraft();
        } else if (draftSaveState === 'dirty' || draftSaveState === 'saving') {
            await _saveCurrentDraft();
        }
        _clearAutosaveTimer();
        draftSaveState = 'saving';
        renderAuthorRoute();
        currentProtocol = await API.publishProtocol(currentProtocolId);
        _applyDraftFromProtocol(currentProtocol);
        await _refreshDraftTextForCurrentFormat();
        await loadProtocols();
        draftSaveState = 'saved';
        renderAuthorRoute();
        UI.notify('Protocol published.', 'success');
    }

    async function _archiveCurrentDraft() {
        _clearAutosaveTimer();
        draftSaveState = 'saving';
        renderAuthorRoute();
        currentProtocol = await API.archiveProtocol(currentProtocolId);
        _applyDraftFromProtocol(currentProtocol);
        await _refreshDraftTextForCurrentFormat();
        await loadProtocols();
        draftSaveState = 'saved';
        renderAuthorRoute();
        UI.notify('Protocol archived.', 'success');
    }

    async function _createDraftFromSource(payload) {
        const result = await API.createProtocolDraft(payload);
        currentProtocolId = result.protocol?.protocol_id || '';
        currentProtocol = result;
        _applyDraftFromProtocol(result);
        currentSection = 'overview';
        _writeState({ push: true });
        await _refreshDraftTextForCurrentFormat();
        await loadProtocols();
        draftSaveState = 'idle';
        renderAuthorRoute();
        _revealEditorSurface();
        UI.notify('Protocol draft created.', 'success');
    }

    async function _discardCurrentDraft() {
        _clearAutosaveTimer();
        if (!currentProtocolId) {
            _resetDraftState();
            _writeState({ push: true });
            renderAuthorRoute();
            _revealEditorSurface();
            return;
        }
        await API.deleteProtocol(currentProtocolId);
        _resetDraftState();
        _writeState({ push: true });
        await loadProtocols();
        renderAuthorRoute();
        _revealEditorSurface();
        UI.notify('Protocol draft discarded.', 'success');
    }

    async function _duplicateCurrentProtocol() {
        if (!currentProtocolId) {
            return;
        }
        await _createDraftFromSource({
            source_kind: 'protocol',
            source_protocol_id: currentProtocolId,
        });
    }

    function _validationIssues() {
        return Array.isArray(currentProtocol?.validation?.issues) ? currentProtocol.validation.issues : [];
    }

    function _nextRequiredActionLabels() {
        const actions = Array.isArray(currentProtocol?.validation?.next_required_actions)
            ? currentProtocol.validation.next_required_actions
            : [];
        return actions.map((item) => {
            if (item === 'overview.complete_slug') return 'Set a protocol slug in Overview.';
            if (item === 'participants.add_first') return 'Add the first participant.';
            if (item === 'stages.add_first') return 'Add the first workflow stage.';
            if (item === 'stages.assign_participant') return 'Assign a participant to each stage.';
            return String(item || '').trim();
        }).filter(Boolean);
    }

    function _sectionIssues(section) {
        const issues = _validationIssues();
        const parseError = String(draft.parse_error || '').trim();
        if (issues.length) {
            const sectionIssues = issues.filter((item) =>
                section === 'review'
                    ? true
                    : String(item.section || '').trim().toLowerCase() === section,
            ).map((item) => String(item.message || '').trim()).filter(Boolean);
            return parseError ? [parseError, ...sectionIssues] : sectionIssues;
        }
        const errors = Array.isArray(currentProtocol?.validation?.errors) ? currentProtocol.validation.errors : [];
        if (section === 'review') {
            return parseError ? [parseError, ...errors] : errors;
        }
        return errors.filter((item) => {
            const text = String(item || '').toLowerCase();
            if (section === 'participants') return text.includes('participant');
            if (section === 'artifacts') return text.includes('artifact') || text.includes('workspace_file');
            if (section === 'stages') return text.includes('stage') || text.includes('transition');
            if (section === 'policies') return text.includes('review') || text.includes('policy');
            if (section === 'overview') {
                return !text.includes('participant') && !text.includes('artifact') && !text.includes('stage') && !text.includes('transition');
            }
            return false;
        });
    }

    function _canAddStages(document) {
        return Boolean(document.participants?.length);
    }

    function _sectionSummary(document) {
        return PROTOCOL_AUTHORING_SECTION_OPTIONS.map((item) => {
            const issues = _sectionIssues(item.value);
            let count = 0;
            if (item.value === 'participants') count = document.participants?.length || 0;
            if (item.value === 'artifacts') count = document.artifacts?.length || 0;
            if (item.value === 'stages') count = document.stages?.length || 0;
            if (item.value === 'review') count = issues.length;
            return {
                value: item.value,
                label: item.label,
                count,
                hasIssues: issues.length > 0,
            };
        });
    }

    function _filteredProtocols() {
        return (protocols || []).filter((item) => {
            const haystack = [
                item.display_name || '',
                item.slug || '',
                item.protocol_id || '',
                item.description || '',
                item.visibility || '',
                item.lifecycle_state || '',
            ].join(' ').toLowerCase();
            if (protocolSearch && !haystack.includes(protocolSearch.toLowerCase())) {
                return false;
            }
            if (protocolLifecycleFilter && String(item.lifecycle_state || '') !== protocolLifecycleFilter) {
                return false;
            }
            return true;
        });
    }

    function _protocolCatalogGroups() {
        const filtered = _filteredProtocols();
        return {
            authored: filtered.filter((item) => String(item.visibility || '') !== 'registry_template'),
            builtin: filtered.filter((item) => String(item.visibility || '') === 'registry_template'),
        };
    }

    function _protocolRows(items, { builtin = false } = {}) {
        return (items || []).map((item) => UI.renderListRow({
            label: item.display_name || item.slug || item.protocol_id,
            sublabel: [
                builtin ? 'Built-in example' : '',
                item.description || '',
                item.slug || item.protocol_id,
                item.updated_at ? `updated ${UI.relativeTime(item.updated_at)}` : '',
            ].filter(Boolean).join(' · '),
            badgeText: builtin ? 'example' : (item.lifecycle_state || 'draft'),
            className: item.protocol_id === currentProtocolId ? 'is-selected' : '',
            onClick: () => {
                currentProtocolId = item.protocol_id;
                currentProtocol = null;
                currentSection = 'overview';
                protocolDetailLoading = true;
                selectedParticipantKey = '';
                selectedArtifactKey = '';
                selectedStageKey = '';
                _writeState({ push: true });
                renderAuthorRoute();
                _revealEditorSurface();
                void loadProtocolDetail();
            },
        }));
    }

    function _buildCatalogGroup(titleText, rows, emptyMessage, { tone = '' } = {}) {
        const section = document.createElement('section');
        section.className = `protocol-catalog-group${tone ? ` ${tone}` : ''}`;
        const heading = document.createElement('div');
        heading.className = 'protocol-catalog-heading';
        heading.textContent = titleText;
        section.appendChild(heading);
        const body = document.createElement('div');
        body.className = 'protocol-scroll protocol-catalog-list';
        UI.reconcileChildren(
            body,
            rows.length ? rows : [UI.renderEmptyState(emptyMessage, true)],
        );
        section.appendChild(body);
        return section;
    }

    function _openImportDialog() {
        const form = document.createElement('div');
        form.className = 'studio-dialog-form';

        const formatControl = UI.createSegmentedControl(
            [
                { value: 'json', label: 'JSON' },
                { value: 'yaml', label: 'YAML' },
            ],
            (value) => {
                formatValue = value || 'json';
            },
            { label: 'Import format', value: 'yaml' },
        );
        let formatValue = 'yaml';
        form.appendChild(formatControl.element);

        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.className = 'input';
        fileInput.accept = '.json,.yaml,.yml,application/json,text/yaml,text/x-yaml';
        form.appendChild(fileInput);

        const textarea = document.createElement('textarea');
        textarea.className = 'guidance-textarea';
        textarea.rows = 12;
        textarea.placeholder = 'Paste protocol JSON or YAML here';
        form.appendChild(textarea);

        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = 'Import normalizes JSON or YAML into the shared protocol draft model. Incomplete drafts stay editable and Review handles strict publish validation.';
        form.appendChild(note);

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn';
        cancelBtn.textContent = 'Cancel';
        const importBtn = document.createElement('button');
        importBtn.type = 'button';
        importBtn.className = 'btn btn-primary';
        importBtn.textContent = 'Import';
        const view = UI.showDialog('Import protocol definition', form, {
            actions: [cancelBtn, importBtn],
            maxWidth: '760px',
            initialFocus: textarea,
        });
        cancelBtn.addEventListener('click', () => view.close());
        importBtn.addEventListener('click', async () => {
            importBtn.disabled = true;
            try {
                let definitionText = String(textarea.value || '').trim();
                const file = fileInput.files && fileInput.files[0];
                if (!definitionText && file) {
                    definitionText = await _readProtocolFileText(file);
                }
                if (!definitionText) {
                    textarea.focus();
                    return;
                }
                const parsed = await API.parseProtocolDocument({
                    definition_text: definitionText,
                    format: formatValue,
                    validation_mode: 'draft',
                });
                const document = _applyDraftMetadataToDocument(parsed.document || _defaultProtocolDocument());
                const result = await API.createProtocol({
                    slug: document.metadata?.slug || '',
                    display_name: document.metadata?.display_name || 'Imported Protocol',
                    description: document.metadata?.description || '',
                    definition_json: document,
                });
                currentProtocolId = result.protocol?.protocol_id || '';
                currentProtocol = result;
                _applyDraftFromProtocol(result);
                currentSection = 'overview';
                editorFormat = formatValue;
                await _refreshDraftTextForCurrentFormat();
                await loadProtocols();
                _writeState({ push: true });
                renderAuthorRoute();
                _revealEditorSurface();
                view.close();
                UI.notify('Protocol definition imported into a new draft.', 'success');
            } catch (err) {
                UI.reportError('Failed to import the protocol definition', err, {
                    context: 'Protocol import failed',
                });
            }
            importBtn.disabled = false;
        });
    }

    function _buildDefinitionPanel() {
        const definitionPanel = document.createElement('section');
        definitionPanel.className = 'editor-panel protocol-panel';

        const definitionTitle = document.createElement('div');
        definitionTitle.className = 'editor-section-title';
        definitionTitle.textContent = 'Definitions';
        definitionPanel.appendChild(definitionTitle);

        const definitionSearch = document.createElement('input');
        definitionSearch.className = 'search-input';
        definitionSearch.placeholder = 'Search definitions and examples';
        definitionSearch.value = protocolSearch;
        definitionSearch.addEventListener('input', () => {
            protocolSearch = definitionSearch.value;
            renderAuthorRoute();
        });
        definitionPanel.appendChild(definitionSearch);

        const statusControl = UI.createSegmentedControl(
            PROTOCOL_CATALOG_STATUS_OPTIONS,
            (value) => {
                protocolLifecycleFilter = String(value || '');
                renderAuthorRoute();
            },
            {
                label: 'Protocol lifecycle filter',
                value: protocolLifecycleFilter,
            },
        );
        const toolbar = document.createElement('div');
        toolbar.className = 'protocol-catalog-toolbar';
        toolbar.appendChild(statusControl.element);
        definitionPanel.appendChild(toolbar);

        const definitionActions = document.createElement('div');
        definitionActions.className = 'editor-actions';

        const newButton = document.createElement('button');
        newButton.type = 'button';
        newButton.className = 'btn btn-primary';
        newButton.textContent = 'New protocol';
        newButton.addEventListener('click', () => {
            _resetDraftState();
            _writeState({ push: true });
            renderAuthorRoute();
            _revealEditorSurface();
        });
        definitionActions.appendChild(newButton);

        const importButton = document.createElement('button');
        importButton.type = 'button';
        importButton.className = 'btn';
        importButton.textContent = 'Import';
        importButton.addEventListener('click', _openImportDialog);
        definitionActions.appendChild(importButton);
        definitionPanel.appendChild(definitionActions);

        const groups = _protocolCatalogGroups();
        const catalogGroups = document.createElement('div');
        catalogGroups.className = 'protocol-catalog-groups';
        catalogGroups.appendChild(_buildCatalogGroup(
            'Your definitions',
            _protocolRows(groups.authored),
            'No authored protocols yet. Start a blank draft, use a starter template, or import an existing definition.',
        ));
        if (groups.builtin.length) {
            catalogGroups.appendChild(_buildCatalogGroup(
                'Built-in examples',
                _protocolRows(groups.builtin, { builtin: true }),
                'No built-in protocol examples are available in this registry.',
                { tone: 'protocol-catalog-group-subtle' },
            ));
        }
        definitionPanel.appendChild(catalogGroups);
        return definitionPanel;
    }

    function _buildStageFlow(protocolDocument, { compact = false, preview = false } = {}) {
        const stages = protocolDocument.stages || [];
        if (preview) {
            const previewFlow = document.createElement('div');
            previewFlow.className = 'protocol-stage-flow protocol-stage-flow-preview';
            stages.forEach((stage, index) => {
                if (index > 0) {
                    const arrow = document.createElement('span');
                    arrow.className = 'protocol-stage-preview-arrow';
                    arrow.textContent = '→';
                    previewFlow.appendChild(arrow);
                }
                const previewNode = document.createElement('button');
                previewNode.type = 'button';
                previewNode.className = `protocol-stage-preview-node ${String(stage.stage_key || '') === selectedStageKey ? 'is-selected' : ''}`;
                previewNode.addEventListener('click', () => {
                    selectedStageKey = String(stage.stage_key || '');
                    currentSection = 'stages';
                    _writeState({ push: true });
                    renderAuthorRoute();
                    _revealEditorSurface();
                });
                const title = document.createElement('strong');
                title.textContent = stage.display_name || stage.stage_key || 'Stage';
                previewNode.appendChild(title);
                const meta = document.createElement('span');
                meta.className = 'protocol-stage-preview-meta';
                meta.textContent = [
                    stage.stage_kind || 'work',
                    stage.participant_key || '',
                ].filter(Boolean).join(' · ');
                previewNode.appendChild(meta);
                previewFlow.appendChild(previewNode);
            });
            if (!stages.length) {
                previewFlow.appendChild(UI.renderEmptyState('No stages defined yet.', true));
            }
            return previewFlow;
        }
        const flow = document.createElement('div');
        flow.className = compact ? 'protocol-stage-flow protocol-stage-flow-compact' : 'protocol-stage-flow';
        stages.forEach((stage) => {
            const card = document.createElement('button');
            card.type = 'button';
            card.className = `protocol-stage-node ${String(stage.stage_key || '') === selectedStageKey ? 'is-selected' : ''}`;
            card.addEventListener('click', () => {
                selectedStageKey = String(stage.stage_key || '');
                currentSection = 'stages';
                _writeState();
                renderAuthorRoute();
                _revealEditorSurface();
            });

            const title = document.createElement('strong');
            title.textContent = stage.display_name || stage.stage_key || 'Stage';
            card.appendChild(title);

            const meta = document.createElement('div');
            meta.className = 'protocol-stage-node-meta';
            meta.textContent = [
                stage.stage_kind || 'work',
                stage.participant_key || '',
            ].filter(Boolean).join(' · ');
            card.appendChild(meta);

            const transitionText = Object.entries(stage.transitions || {})
                .map(([decision, target]) => `${decision} → ${target}`)
                .join(' · ');
            if (transitionText) {
                const transitions = document.createElement('div');
                transitions.className = 'quiet-note';
                transitions.textContent = transitionText;
                card.appendChild(transitions);
            }
            flow.appendChild(card);
        });
        if (!stages.length) {
            flow.appendChild(UI.renderEmptyState('No stages defined yet.', true));
        }
        return flow;
    }

    function _selectedParticipant(protocolDocument) {
        _setSelectedEntityDefaults(protocolDocument);
        return (protocolDocument.participants || []).find((item) => String(item.participant_key || '') === selectedParticipantKey) || null;
    }

    function _selectedArtifact(protocolDocument) {
        _setSelectedEntityDefaults(protocolDocument);
        return (protocolDocument.artifacts || []).find((item) => String(item.artifact_key || '') === selectedArtifactKey) || null;
    }

    function _selectedStage(protocolDocument) {
        _setSelectedEntityDefaults(protocolDocument);
        return (protocolDocument.stages || []).find((item) => String(item.stage_key || '') === selectedStageKey) || null;
    }

    function _buildStarterPanel() {
        const panel = document.createElement('section');
        panel.className = 'editor-panel protocol-panel protocol-starter-panel';
        panel.dataset.key = 'protocol-author:starter';

        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = 'New protocol';
        panel.appendChild(title);

        const intro = document.createElement('p');
        intro.className = 'quiet-note';
        intro.textContent = 'Start from a blank workflow, choose a reusable template, or import a definition. New and existing protocols use the same progressive editor.';
        panel.appendChild(intro);

        const cards = document.createElement('div');
        cards.className = 'protocol-template-grid';

        const blankCard = document.createElement('section');
        blankCard.className = 'protocol-template-card';
        blankCard.innerHTML = '<strong>Blank protocol</strong><p>Start with an empty workflow and add participants, stages, artifacts, and policies step by step.</p>';
        const blankBtn = document.createElement('button');
        blankBtn.type = 'button';
        blankBtn.className = 'btn btn-primary';
        blankBtn.textContent = 'Start blank';
        blankBtn.addEventListener('click', () => {
            void _createDraftFromSource({ source_kind: 'blank' }).catch((err) => {
                UI.reportError('Failed to create a blank protocol draft', err, {
                    context: 'Protocol draft create failed',
                });
            });
        });
        blankCard.appendChild(blankBtn);
        cards.appendChild(blankCard);

        _manifestTemplates().forEach((template) => {
            const card = document.createElement('section');
            card.className = 'protocol-template-card';
            card.innerHTML = `<strong>${template.display_name || template.slug}</strong><p>${template.description || 'Reusable protocol template.'}</p>`;
            const stats = document.createElement('div');
            stats.className = 'protocol-template-meta';
            stats.textContent = [
                `${template.participant_count || 0} participants`,
                `${template.stage_count || 0} stages`,
                `${template.artifact_count || 0} artifacts`,
            ].join(' · ');
            card.appendChild(stats);
            const useBtn = document.createElement('button');
            useBtn.type = 'button';
            useBtn.className = 'btn';
            useBtn.textContent = 'Use template';
            useBtn.addEventListener('click', () => {
                void _createDraftFromSource({
                    source_kind: 'template',
                    template_slug: template.slug,
                }).catch((err) => {
                    UI.reportError('Failed to create a template-based protocol draft', err, {
                        context: 'Protocol template draft create failed',
                    });
                });
            });
            card.appendChild(useBtn);
            cards.appendChild(card);
        });

        const importCard = document.createElement('section');
        importCard.className = 'protocol-template-card protocol-template-card-subtle';
        importCard.innerHTML = '<strong>Import JSON or YAML</strong><p>Bring in an existing definition and continue editing it in the same authoring workflow.</p>';
        const importBtn = document.createElement('button');
        importBtn.type = 'button';
        importBtn.className = 'btn';
        importBtn.textContent = 'Import definition';
        importBtn.addEventListener('click', _openImportDialog);
        importCard.appendChild(importBtn);
        cards.appendChild(importCard);

        panel.appendChild(cards);
        return panel;
    }

    function _buildAuthorHeader(protocolDocument) {
        const header = document.createElement('div');
        header.className = 'protocol-author-header';

        const titleWrap = document.createElement('div');
        titleWrap.className = 'protocol-author-title';
        const title = document.createElement('h3');
        title.textContent = draft.display_name || draft.slug || 'Untitled protocol';
        titleWrap.appendChild(title);
        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = currentProtocol?.protocol
            ? [
                currentProtocol.protocol.lifecycle_state || 'draft',
                currentProtocol.version ? `version ${currentProtocol.version.version || 0}` : '',
                currentProtocol.protocol.current_version_id ? 'published version available' : 'not yet published',
                draftSaveState === 'saving'
                    ? 'saving'
                    : draftSaveState === 'dirty'
                        ? 'unsaved changes'
                        : draftSaveState === 'error'
                            ? 'save failed'
                            : 'saved',
            ].filter(Boolean).join(' · ')
            : 'Edit the workflow progressively. Advanced raw JSON/YAML stays behind the Advanced section.';
        titleWrap.appendChild(note);
        header.appendChild(titleWrap);

        const actions = document.createElement('div');
        actions.className = 'editor-actions';

        const saveButton = document.createElement('button');
        saveButton.type = 'button';
        saveButton.className = 'btn btn-primary';
        saveButton.textContent = 'Save draft';
        saveButton.addEventListener('click', () => {
            void _saveCurrentDraft().catch((err) => {
                UI.reportError('Failed to save the protocol draft', err, {
                    context: 'Protocol save failed',
                });
            });
        });
        actions.appendChild(saveButton);

        if (currentProtocolId) {
            const duplicateButton = document.createElement('button');
            duplicateButton.type = 'button';
            duplicateButton.className = 'btn';
            duplicateButton.textContent = 'Duplicate';
            duplicateButton.addEventListener('click', () => {
                void _duplicateCurrentProtocol().catch((err) => {
                    UI.reportError('Failed to duplicate the protocol draft', err, {
                        context: 'Protocol duplicate failed',
                    });
                });
            });
            actions.appendChild(duplicateButton);
        }

        const reviewButton = document.createElement('button');
        reviewButton.type = 'button';
        reviewButton.className = 'btn';
        reviewButton.textContent = 'Review';
        reviewButton.addEventListener('click', () => {
            currentSection = 'review';
            _writeState({ push: true });
            renderAuthorRoute();
            _revealEditorSurface();
        });
        actions.appendChild(reviewButton);
        header.appendChild(actions);
        return header;
    }

    function _buildSectionNav(protocolDocument) {
        const options = _sectionSummary(protocolDocument).map((item) => ({
            value: item.value,
            label: item.hasIssues
                ? `${item.label}${item.count ? ` (${item.count})` : ''} !`
                : item.count
                    ? `${item.label} (${item.count})`
                    : item.label,
        }));
        return UI.createSegmentedControl(
            options,
            (value) => {
                currentSection = _normalizeAuthorSection(value);
                _writeState({ push: true });
                renderAuthorRoute();
            },
            {
                label: 'Protocol authoring section',
                value: currentSection,
            },
        ).element;
    }

    function _buildOverviewCanvas(protocolDocument) {
        const main = document.createElement('div');
        main.className = 'protocol-author-main';
        main.dataset.key = 'protocol-author:overview:main';
        const nextSteps = _nextRequiredActionLabels();

        const summaryCard = document.createElement('section');
        summaryCard.className = 'editor-panel protocol-panel';
        const summaryTitle = document.createElement('div');
        summaryTitle.className = 'editor-section-title';
        summaryTitle.textContent = 'Workflow summary';
        summaryCard.appendChild(summaryTitle);
        summaryCard.appendChild(UI.renderMetadataGrid([
            { label: 'Participants', value: String(protocolDocument.participants?.length || 0) },
            { label: 'Stages', value: String(protocolDocument.stages?.length || 0) },
            { label: 'Artifacts', value: String(protocolDocument.artifacts?.length || 0) },
            {
                label: 'Save state',
                value: draftSaveState === 'saving'
                    ? 'Saving…'
                    : draftSaveState === 'dirty'
                        ? 'Unsaved changes'
                        : draftSaveState === 'error'
                            ? 'Save failed'
                            : 'Saved',
            },
        ], { compact: true }));
        const summaryNote = document.createElement('p');
        summaryNote.className = 'quiet-note';
        summaryNote.textContent = draft.description || 'Describe the intent of this workflow, then refine the participants, stages, artifacts, and policies in the sections below.';
        summaryCard.appendChild(summaryNote);
        if (nextSteps.length) {
            const checklist = document.createElement('div');
            checklist.className = 'protocol-next-steps';
            const checklistTitle = document.createElement('div');
            checklistTitle.className = 'detail-label';
            checklistTitle.textContent = 'Recommended next steps';
            checklist.appendChild(checklistTitle);
            const list = document.createElement('ul');
            list.className = 'protocol-validation-list';
            nextSteps.forEach((item) => {
                const li = document.createElement('li');
                li.textContent = item;
                list.appendChild(li);
            });
            checklist.appendChild(list);
            summaryCard.appendChild(checklist);
        }
        main.appendChild(summaryCard);

        const flowCard = document.createElement('section');
        flowCard.className = 'editor-panel protocol-panel';
        const flowTitle = document.createElement('div');
        flowTitle.className = 'editor-section-title';
        flowTitle.textContent = 'Workflow map';
        flowCard.appendChild(flowTitle);
        flowCard.appendChild(_buildStageFlow(protocolDocument, { preview: true }));
        main.appendChild(flowCard);
        return main;
    }

    function _buildOverviewInspector(protocolDocument) {
        const inspector = document.createElement('section');
        inspector.className = 'editor-panel protocol-panel protocol-inspector-panel';
        inspector.dataset.key = 'protocol-author:overview:inspector';
        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = 'Protocol basics';
        inspector.appendChild(title);

        inspector.appendChild(UI.renderSettingsRow({
            label: 'Slug',
            control: _textInput(draft.slug || '', (value) => {
                draft.slug = value;
                void _commitDraftDocument(_draftDocument());
            }, { placeholder: 'protocol-slug', ariaLabel: 'Protocol slug', draftKey: 'meta:slug' }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Display name',
            control: _textInput(draft.display_name || '', (value) => {
                draft.display_name = value;
                void _commitDraftDocument(_draftDocument());
            }, { placeholder: 'Display name', ariaLabel: 'Protocol display name', draftKey: 'meta:display_name' }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Description',
            control: _textAreaInput(draft.description || '', (value) => {
                draft.description = value;
                void _commitDraftDocument(_draftDocument());
            }, { placeholder: 'Purpose and constraints', rows: 4, ariaLabel: 'Protocol description', draftKey: 'meta:description' }),
        }));

        const helper = document.createElement('p');
        helper.className = 'quiet-note';
        helper.textContent = 'Use Overview to set the protocol identity, then work section by section instead of editing the full document at once.';
        inspector.appendChild(helper);
        return inspector;
    }

    function _buildParticipantsCanvas(protocolDocument) {
        const main = document.createElement('div');
        main.className = 'protocol-author-main';
        main.dataset.key = 'protocol-author:participants:main';
        const panel = document.createElement('section');
        panel.className = 'editor-panel protocol-panel';
        const headerRow = document.createElement('div');
        headerRow.className = 'protocol-structured-header';
        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = 'Participants';
        headerRow.appendChild(title);
        const addButton = document.createElement('button');
        addButton.type = 'button';
        addButton.className = 'btn';
        addButton.textContent = 'Add participant';
        addButton.addEventListener('click', () => {
            void _applyStructuredChange((next) => {
                const index = (next.participants || []).length + 1;
                next.participants = [...(next.participants || []), {
                    participant_key: `participant_${index}`,
                    display_name: `Participant ${index}`,
                    required_skills: [],
                    instructions: '',
                }];
                selectedParticipantKey = `participant_${index}`;
            });
        });
        headerRow.appendChild(addButton);
        panel.appendChild(headerRow);

        const list = document.createElement('div');
        list.className = 'protocol-stage-flow protocol-entity-flow';
        (protocolDocument.participants || []).forEach((item) => {
            const card = document.createElement('button');
            card.type = 'button';
            card.className = `protocol-stage-node ${String(item.participant_key || '') === selectedParticipantKey ? 'is-selected' : ''}`;
            card.addEventListener('click', () => {
                selectedParticipantKey = String(item.participant_key || '');
                renderAuthorRoute();
            });
            const name = document.createElement('strong');
            name.textContent = item.display_name || item.participant_key || 'Participant';
            card.appendChild(name);
            const meta = document.createElement('div');
            meta.className = 'protocol-stage-node-meta';
            meta.textContent = (item.required_skills || []).join(', ') || 'No required skills';
            card.appendChild(meta);
            if (item.instructions) {
                const summary = document.createElement('div');
                summary.className = 'quiet-note';
                summary.textContent = String(item.instructions || '').slice(0, 100);
                card.appendChild(summary);
            }
            list.appendChild(card);
        });
        if (!(protocolDocument.participants || []).length) {
            list.appendChild(UI.renderEmptyState('No participants defined yet.', true));
        }
        panel.appendChild(list);
        main.appendChild(panel);
        return main;
    }

    function _buildParticipantsInspector(protocolDocument) {
        const selected = _selectedParticipant(protocolDocument);
        const inspector = document.createElement('section');
        inspector.className = 'editor-panel protocol-panel protocol-inspector-panel';
        inspector.dataset.key = 'protocol-author:participants:inspector';
        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = 'Participant details';
        inspector.appendChild(title);
        if (!selected) {
            inspector.appendChild(UI.renderEmptyState('Select a participant to edit it.', true));
            return inspector;
        }
        const index = (protocolDocument.participants || []).findIndex((item) => String(item.participant_key || '') === String(selected.participant_key || ''));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Key',
            control: _textInput(selected.participant_key, (value) => void _applyStructuredChange((next) => {
                next.participants[index].participant_key = value;
                selectedParticipantKey = value;
            }), { placeholder: 'participant_key', ariaLabel: 'Participant key', draftKey: `participant:${index}:participant_key` }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Display name',
            control: _textInput(selected.display_name, (value) => void _applyStructuredChange((next) => {
                next.participants[index].display_name = value;
            }), { placeholder: 'Display name', ariaLabel: 'Participant display name', draftKey: `participant:${index}:display_name` }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Required skills',
            control: _textInput((selected.required_skills || []).join(', '), (value) => void _applyStructuredChange((next) => {
                next.participants[index].required_skills = _commaList(value);
            }), { placeholder: 'review, implementation', ariaLabel: 'Participant skills', draftKey: `participant:${index}:required_skills` }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Selector kind',
            control: _selectInput(
                [{ value: '', label: 'None' }].concat(_manifestSelectorKindOptions().map((value) => ({ value, label: value[0].toUpperCase() + value.slice(1) }))),
                selected.selector?.kind || '',
                (value) => void _applyStructuredChange((next) => {
                    next.participants[index].selector = value
                        ? Object.assign({}, next.participants[index].selector || {}, { kind: value })
                        : null;
                }),
                { ariaLabel: 'Participant selector kind', draftKey: `participant:${index}:selector_kind` },
            ),
        }));
        if (selected.selector?.kind) {
            inspector.appendChild(UI.renderSettingsRow({
                label: 'Selector value',
                control: _textInput(selected.selector?.value || '', (value) => void _applyStructuredChange((next) => {
                    next.participants[index].selector = Object.assign({}, next.participants[index].selector || {}, { value });
                }), { placeholder: 'Selector value', ariaLabel: 'Participant selector value', draftKey: `participant:${index}:selector_value` }),
            }));
        }
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Instructions',
            control: _textAreaInput(selected.instructions || '', (value) => void _applyStructuredChange((next) => {
                next.participants[index].instructions = value;
            }), { placeholder: 'Participant-specific instructions', rows: 5, ariaLabel: 'Participant instructions', draftKey: `participant:${index}:instructions` }),
        }));
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'btn btn-sm btn-danger';
        remove.textContent = 'Remove participant';
        remove.addEventListener('click', () => void _applyStructuredChange((next) => {
            next.participants.splice(index, 1);
            selectedParticipantKey = '';
        }));
        inspector.appendChild(remove);
        return inspector;
    }

    function _buildArtifactsCanvas(protocolDocument) {
        const main = document.createElement('div');
        main.className = 'protocol-author-main';
        main.dataset.key = 'protocol-author:artifacts:main';
        const panel = document.createElement('section');
        panel.className = 'editor-panel protocol-panel';
        const headerRow = document.createElement('div');
        headerRow.className = 'protocol-structured-header';
        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = 'Artifacts';
        headerRow.appendChild(title);
        const addButton = document.createElement('button');
        addButton.type = 'button';
        addButton.className = 'btn';
        addButton.textContent = 'Add artifact';
        addButton.addEventListener('click', () => {
            void _applyStructuredChange((next) => {
                const index = (next.artifacts || []).length + 1;
                next.artifacts = [...(next.artifacts || []), {
                    artifact_key: `artifact_${index}`,
                    display_name: `Artifact ${index}`,
                    description: '',
                    kind: 'workspace_file',
                    path: `protocol/artifact-${index}.md`,
                    verify: true,
                }];
                selectedArtifactKey = `artifact_${index}`;
            });
        });
        headerRow.appendChild(addButton);
        panel.appendChild(headerRow);

        const list = document.createElement('div');
        list.className = 'protocol-stage-flow protocol-entity-flow';
        (protocolDocument.artifacts || []).forEach((item) => {
            const card = document.createElement('button');
            card.type = 'button';
            card.className = `protocol-stage-node ${String(item.artifact_key || '') === selectedArtifactKey ? 'is-selected' : ''}`;
            card.addEventListener('click', () => {
                selectedArtifactKey = String(item.artifact_key || '');
                renderAuthorRoute();
            });
            const name = document.createElement('strong');
            name.textContent = item.display_name || item.artifact_key || 'Artifact';
            card.appendChild(name);
            const meta = document.createElement('div');
            meta.className = 'protocol-stage-node-meta';
            meta.textContent = [item.kind || 'workspace_file', item.path || ''].filter(Boolean).join(' · ');
            card.appendChild(meta);
            if (item.description) {
                const summary = document.createElement('div');
                summary.className = 'quiet-note';
                summary.textContent = item.description;
                card.appendChild(summary);
            }
            list.appendChild(card);
        });
        if (!(protocolDocument.artifacts || []).length) {
            list.appendChild(UI.renderEmptyState('No artifacts defined yet.', true));
        }
        panel.appendChild(list);
        main.appendChild(panel);
        return main;
    }

    function _buildArtifactsInspector(protocolDocument) {
        const selected = _selectedArtifact(protocolDocument);
        const inspector = document.createElement('section');
        inspector.className = 'editor-panel protocol-panel protocol-inspector-panel';
        inspector.dataset.key = 'protocol-author:artifacts:inspector';
        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = 'Artifact details';
        inspector.appendChild(title);
        if (!selected) {
            inspector.appendChild(UI.renderEmptyState('Select an artifact to edit it.', true));
            return inspector;
        }
        const index = (protocolDocument.artifacts || []).findIndex((item) => String(item.artifact_key || '') === String(selected.artifact_key || ''));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Key',
            control: _textInput(selected.artifact_key, (value) => void _applyStructuredChange((next) => {
                next.artifacts[index].artifact_key = value;
                selectedArtifactKey = value;
            }), { placeholder: 'artifact_key', ariaLabel: 'Artifact key', draftKey: `artifact:${index}:artifact_key` }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Display name',
            control: _textInput(selected.display_name, (value) => void _applyStructuredChange((next) => {
                next.artifacts[index].display_name = value;
            }), { placeholder: 'Display name', ariaLabel: 'Artifact display name', draftKey: `artifact:${index}:display_name` }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Kind',
            control: _selectInput(
                _manifestArtifactKindOptions().map((value) => ({ value, label: value.replace(/_/g, ' ') })),
                selected.kind || 'workspace_file',
                (value) => void _applyStructuredChange((next) => {
                    next.artifacts[index].kind = value || 'workspace_file';
                }),
                { ariaLabel: 'Artifact kind', draftKey: `artifact:${index}:kind` },
            ),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Path',
            control: _textInput(selected.path || '', (value) => void _applyStructuredChange((next) => {
                next.artifacts[index].path = value;
            }), { placeholder: 'relative/path.md', ariaLabel: 'Artifact path', draftKey: `artifact:${index}:path` }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Description',
            control: _textAreaInput(selected.description || '', (value) => void _applyStructuredChange((next) => {
                next.artifacts[index].description = value;
            }), { placeholder: 'Artifact description', rows: 4, ariaLabel: 'Artifact description', draftKey: `artifact:${index}:description` }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Verification',
            control: _checkboxInput(Boolean(selected.verify !== false), 'Require verification', (checked) => void _applyStructuredChange((next) => {
                next.artifacts[index].verify = checked;
            }), { ariaLabel: 'Artifact verification required', draftKey: `artifact:${index}:verify` }),
        }));
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'btn btn-sm btn-danger';
        remove.textContent = 'Remove artifact';
        remove.addEventListener('click', () => void _applyStructuredChange((next) => {
            next.artifacts.splice(index, 1);
            selectedArtifactKey = '';
        }));
        inspector.appendChild(remove);
        return inspector;
    }

    function _buildStagesCanvas(protocolDocument) {
        const main = document.createElement('div');
        main.className = 'protocol-author-main';
        main.dataset.key = 'protocol-author:stages:main';
        const canAddStages = _canAddStages(protocolDocument);
        const panel = document.createElement('section');
        panel.className = 'editor-panel protocol-panel';
        const headerRow = document.createElement('div');
        headerRow.className = 'protocol-structured-header';
        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = 'Workflow stages';
        headerRow.appendChild(title);
        const addButton = document.createElement('button');
        addButton.type = 'button';
        addButton.className = 'btn';
        addButton.textContent = 'Add stage';
        addButton.disabled = !canAddStages;
        addButton.addEventListener('click', () => {
            void _applyStructuredChange((next) => {
                const index = (next.stages || []).length + 1;
                next.stages = [...(next.stages || []), {
                    stage_key: `stage_${index}`,
                    display_name: `Stage ${index}`,
                    participant_key: String(next.participants?.[0]?.participant_key || ''),
                    stage_kind: 'work',
                    instructions: '',
                    inputs: [],
                    outputs: [],
                    transitions: { completed: '__complete__' },
                    write_capable: false,
                    max_rounds: 0,
                    strict_completion: false,
                    require_output_verification: null,
                    timeout_seconds: 0,
                }];
                selectedStageKey = `stage_${index}`;
            });
        });
        headerRow.appendChild(addButton);
        panel.appendChild(headerRow);
        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = canAddStages
            ? 'Add and order stages here. Each stage should point at one participant and describe its transitions.'
            : 'Add at least one participant before creating workflow stages.';
        panel.appendChild(note);
        if (!canAddStages) {
            const jumpButton = document.createElement('button');
            jumpButton.type = 'button';
            jumpButton.className = 'btn';
            jumpButton.textContent = 'Go to Participants';
            jumpButton.addEventListener('click', () => {
                currentSection = 'participants';
                _writeState({ push: true });
                renderAuthorRoute();
            });
            panel.appendChild(jumpButton);
        }
        panel.appendChild(_buildStageFlow(protocolDocument));
        main.appendChild(panel);
        return main;
    }

    function _buildStagesInspector(protocolDocument) {
        const selected = _selectedStage(protocolDocument);
        const inspector = document.createElement('section');
        inspector.className = 'editor-panel protocol-panel protocol-inspector-panel';
        inspector.dataset.key = 'protocol-author:stages:inspector';
        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = 'Stage details';
        inspector.appendChild(title);
        if (!selected) {
            inspector.appendChild(UI.renderEmptyState('Select a stage to edit it.', true));
            return inspector;
        }
        const index = (protocolDocument.stages || []).findIndex((item) => String(item.stage_key || '') === String(selected.stage_key || ''));
        const participantOptions = [{ value: '', label: 'Select participant' }].concat(
            (protocolDocument.participants || []).map((item) => ({
                value: String(item.participant_key || ''),
                label: item.display_name || item.participant_key || '',
            })),
        );
        const artifactOptions = (protocolDocument.artifacts || []).map((item) => String(item.artifact_key || '')).filter(Boolean);

        inspector.appendChild(UI.renderSettingsRow({
            label: 'Key',
            control: _textInput(selected.stage_key, (value) => void _applyStructuredChange((next) => {
                next.stages[index].stage_key = value;
                selectedStageKey = value;
            }), { placeholder: 'stage_key', ariaLabel: 'Stage key', draftKey: `stage:${index}:stage_key` }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Display name',
            control: _textInput(selected.display_name, (value) => void _applyStructuredChange((next) => {
                next.stages[index].display_name = value;
            }), { placeholder: 'Display name', ariaLabel: 'Stage display name', draftKey: `stage:${index}:display_name` }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Participant',
            control: _selectInput(participantOptions, selected.participant_key || '', (value) => void _applyStructuredChange((next) => {
                next.stages[index].participant_key = value;
            }), { ariaLabel: 'Stage participant', draftKey: `stage:${index}:participant_key` }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Kind',
            control: _selectInput(
                _manifestStageKindOptions().map((value) => ({ value, label: value[0].toUpperCase() + value.slice(1) })),
                selected.stage_kind || 'work',
                (value) => void _applyStructuredChange((next) => {
                    next.stages[index].stage_kind = value || 'work';
                }),
                { ariaLabel: 'Stage kind', draftKey: `stage:${index}:stage_kind` },
            ),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Instructions',
            control: _textAreaInput(selected.instructions || '', (value) => void _applyStructuredChange((next) => {
                next.stages[index].instructions = value;
            }), { placeholder: 'Stage instructions', rows: 5, ariaLabel: 'Stage instructions', draftKey: `stage:${index}:instructions` }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Inputs',
            control: _textInput((selected.inputs || []).join(', '), (value) => void _applyStructuredChange((next) => {
                next.stages[index].inputs = _commaList(value);
            }), { placeholder: artifactOptions.join(', ') || 'artifact keys', ariaLabel: 'Stage inputs', draftKey: `stage:${index}:inputs` }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Outputs',
            control: _textInput((selected.outputs || []).join(', '), (value) => void _applyStructuredChange((next) => {
                next.stages[index].outputs = _commaList(value);
            }), { placeholder: artifactOptions.join(', ') || 'artifact keys', ariaLabel: 'Stage outputs', draftKey: `stage:${index}:outputs` }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Transitions',
            control: _textAreaInput(JSON.stringify(selected.transitions || {}, null, 2), (value) => {
                try {
                    const transitions = value.trim() ? JSON.parse(value) : {};
                    void _applyStructuredChange((next) => {
                        next.stages[index].transitions = transitions;
                    });
                } catch (err) {
                    UI.reportError('Transitions must be valid JSON', err, {
                        context: 'Protocol stage transitions invalid',
                    });
                }
            }, { placeholder: '{"completed":"next_stage"}', rows: 5, ariaLabel: 'Stage transitions JSON', draftKey: `stage:${index}:transitions` }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Write lease',
            control: _checkboxInput(Boolean(selected.write_capable), 'Write-capable stage', (checked) => void _applyStructuredChange((next) => {
                next.stages[index].write_capable = checked;
            }), { ariaLabel: 'Stage write capable', draftKey: `stage:${index}:write_capable` }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Strict completion',
            control: _checkboxInput(Boolean(selected.strict_completion), 'Require protocol control lines', (checked) => void _applyStructuredChange((next) => {
                next.stages[index].strict_completion = checked;
            }), { ariaLabel: 'Stage strict completion', draftKey: `stage:${index}:strict_completion` }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Output verification',
            control: _selectInput(
                [
                    { value: '', label: 'Inherit default' },
                    { value: 'true', label: 'Required' },
                    { value: 'false', label: 'Not required' },
                ],
                selected.require_output_verification === null || selected.require_output_verification === undefined
                    ? ''
                    : String(Boolean(selected.require_output_verification)),
                (value) => void _applyStructuredChange((next) => {
                    next.stages[index].require_output_verification = value === ''
                        ? null
                        : value === 'true';
                }),
                { ariaLabel: 'Stage output verification', draftKey: `stage:${index}:require_output_verification` },
            ),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Max rounds',
            control: _numberInput(selected.max_rounds || 0, (value) => void _applyStructuredChange((next) => {
                next.stages[index].max_rounds = value;
            }), { min: 0, ariaLabel: 'Stage max rounds', draftKey: `stage:${index}:max_rounds` }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Timeout seconds',
            control: _numberInput(selected.timeout_seconds || 0, (value) => void _applyStructuredChange((next) => {
                next.stages[index].timeout_seconds = value;
            }), { min: 0, ariaLabel: 'Stage timeout seconds', draftKey: `stage:${index}:timeout_seconds` }),
        }));
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'btn btn-sm btn-danger';
        remove.textContent = 'Remove stage';
        remove.addEventListener('click', () => void _applyStructuredChange((next) => {
            next.stages.splice(index, 1);
            selectedStageKey = '';
        }));
        inspector.appendChild(remove);
        return inspector;
    }

    function _buildPoliciesCanvas(protocolDocument) {
        const main = document.createElement('div');
        main.className = 'protocol-author-main';
        main.dataset.key = 'protocol-author:policies:main';
        const panel = document.createElement('section');
        panel.className = 'editor-panel protocol-panel';
        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = 'Policies';
        panel.appendChild(title);
        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = 'Policies define how strict the workflow is about write ownership and review loops. Keep them lightweight unless the workflow needs stronger controls.';
        panel.appendChild(note);
        panel.appendChild(UI.renderMetadataGrid([
            { label: 'Single active writer', value: protocolDocument.policies?.single_active_writer !== false ? 'Enabled' : 'Disabled' },
            { label: 'Max review rounds', value: String(protocolDocument.policies?.max_review_rounds || 5) },
        ], { compact: true }));
        main.appendChild(panel);
        return main;
    }

    function _buildPoliciesInspector(protocolDocument) {
        const inspector = document.createElement('section');
        inspector.className = 'editor-panel protocol-panel protocol-inspector-panel';
        inspector.dataset.key = 'protocol-author:policies:inspector';
        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = 'Policy details';
        inspector.appendChild(title);
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Single active writer',
            control: _checkboxInput(Boolean(protocolDocument.policies?.single_active_writer !== false), 'Enforce one write lease at a time', (checked) => void _applyStructuredChange((next) => {
                next.policies.single_active_writer = checked;
            }), { ariaLabel: 'Single active writer', draftKey: 'policy:single_active_writer' }),
        }));
        inspector.appendChild(UI.renderSettingsRow({
            label: 'Max review rounds',
            control: _numberInput(protocolDocument.policies?.max_review_rounds || 5, (value) => void _applyStructuredChange((next) => {
                next.policies.max_review_rounds = Math.max(value, 1);
            }), { min: 1, ariaLabel: 'Max review rounds', draftKey: 'policy:max_review_rounds' }),
        }));
        return inspector;
    }

    function _buildReviewCanvas(protocolDocument) {
        const main = document.createElement('div');
        main.className = 'protocol-author-main';
        main.dataset.key = 'protocol-author:review:main';
        const panel = document.createElement('section');
        panel.className = 'editor-panel protocol-panel';
        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = 'Review & publish';
        panel.appendChild(title);
        _renderValidationGutter(panel);
        const nextSteps = document.createElement('p');
        nextSteps.className = 'quiet-note';
        nextSteps.textContent = currentProtocol?.validation?.ok
            ? 'The draft validates. Review the workflow map and publish when ready.'
            : 'Fix the issues called out here or in the relevant sections before publishing.';
        panel.appendChild(nextSteps);
        panel.appendChild(_buildStageFlow(protocolDocument, { compact: true }));
        main.appendChild(panel);
        return main;
    }

    function _buildReviewInspector() {
        const inspector = document.createElement('section');
        inspector.className = 'editor-panel protocol-panel protocol-inspector-panel';
        inspector.dataset.key = 'protocol-author:review:inspector';
        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = 'Actions';
        inspector.appendChild(title);

        inspector.appendChild(UI.renderMetadataGrid([
            {
                label: 'Lifecycle',
                value: String(currentProtocol?.protocol?.lifecycle_state || 'draft').replace(/_/g, ' '),
            },
            {
                label: 'Save state',
                value: draftSaveState === 'saving'
                    ? 'Saving…'
                    : draftSaveState === 'dirty'
                        ? 'Unsaved changes'
                        : draftSaveState === 'error'
                            ? 'Save failed'
                            : 'Saved',
            },
            {
                label: 'Validation mode',
                value: String(currentProtocol?.validation?.mode || 'draft'),
            },
        ], { compact: true }));

        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = String(currentProtocol?.validation?.mode || 'draft') === 'strict'
            ? 'Strict validation is active in Review. Save changes in the other sections first, then validate or publish here.'
            : 'Review uses publish-ready validation. Save the draft, then validate before publishing.';
        inspector.appendChild(note);

        const validateButton = document.createElement('button');
        validateButton.type = 'button';
        validateButton.className = 'btn btn-primary';
        validateButton.textContent = 'Validate';
        validateButton.addEventListener('click', () => {
            void _validateCurrentDraft().catch((err) => {
                UI.reportError('Failed to validate the protocol draft', err, {
                    context: 'Protocol validate failed',
                });
            });
        });
        inspector.appendChild(validateButton);

        const publishButton = document.createElement('button');
        publishButton.type = 'button';
        publishButton.className = 'btn btn-primary';
        publishButton.textContent = 'Publish';
        publishButton.disabled = !currentProtocolId;
        publishButton.addEventListener('click', () => {
            void _publishCurrentDraft().catch((err) => {
                UI.reportError('Failed to publish the protocol', err, {
                    context: 'Protocol publish failed',
                });
            });
        });
        inspector.appendChild(publishButton);

        const diffButton = document.createElement('button');
        diffButton.type = 'button';
        diffButton.className = 'btn';
        diffButton.textContent = 'Diff';
        diffButton.disabled = !currentProtocolId;
        diffButton.addEventListener('click', () => {
            void _showDraftDiff();
        });
        inspector.appendChild(diffButton);

        const exportJsonBtn = document.createElement('button');
        exportJsonBtn.type = 'button';
        exportJsonBtn.className = 'btn';
        exportJsonBtn.textContent = 'Export JSON';
        exportJsonBtn.addEventListener('click', () => {
            void _downloadDraft('json');
        });
        inspector.appendChild(exportJsonBtn);

        const exportYamlBtn = document.createElement('button');
        exportYamlBtn.type = 'button';
        exportYamlBtn.className = 'btn';
        exportYamlBtn.textContent = 'Export YAML';
        exportYamlBtn.addEventListener('click', () => {
            void _downloadDraft('yaml');
        });
        inspector.appendChild(exportYamlBtn);

        const isDiscardableDraft = Boolean(
            currentProtocolId
            && String(currentProtocol?.protocol?.lifecycle_state || '') === 'draft'
            && !String(currentProtocol?.protocol?.current_version_id || '').trim(),
        );
        if (isDiscardableDraft) {
            const discardButton = document.createElement('button');
            discardButton.type = 'button';
            discardButton.className = 'btn btn-danger';
            discardButton.textContent = 'Discard draft';
            discardButton.addEventListener('click', () => {
                UI.showConfirm(
                    'Discard protocol draft?',
                    'This permanently deletes the unpublished draft. Published protocols must be archived instead.',
                    async () => {
                        await _discardCurrentDraft();
                    },
                );
            });
            inspector.appendChild(discardButton);
        }

        if (currentProtocolId) {
            const archiveButton = document.createElement('button');
            archiveButton.type = 'button';
            archiveButton.className = 'btn btn-danger';
            archiveButton.textContent = 'Archive';
            archiveButton.disabled = String(currentProtocol?.protocol?.lifecycle_state || '') === 'archived';
            archiveButton.addEventListener('click', () => {
                UI.showConfirm(
                    'Archive protocol',
                    'Archive this protocol definition? Published versions remain immutable, but the definition will no longer be offered for new runs.',
                    async () => {
                        try {
                            await _archiveCurrentDraft();
                        } catch (err) {
                            UI.reportError('Failed to archive the protocol', err, {
                                context: 'Protocol archive failed',
                            });
                        }
                    },
                );
            });
            inspector.appendChild(archiveButton);
        }
        return inspector;
    }

    function _buildAdvancedCanvas() {
        const panel = document.createElement('section');
        panel.className = 'editor-panel protocol-panel protocol-advanced-panel';
        panel.dataset.key = 'protocol-author:advanced:main';
        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = 'Advanced raw editor';
        panel.appendChild(title);

        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = draft.parse_error
            ? `Raw editor has unsynced errors. Structured sections are using the last valid draft: ${draft.parse_error}`
            : 'Use the raw editor for bulk edits, import/export, or exact JSON/YAML control. The rest of the authoring flow stays section-based.';
        panel.appendChild(note);

        const formatControl = UI.createSegmentedControl(
            [
                { value: 'json', label: 'JSON' },
                { value: 'yaml', label: 'YAML' },
            ],
            (value) => {
                void _syncEditorFormat(value || 'json').then(renderAuthorRoute).catch((err) => {
                    UI.reportError('Failed to switch the protocol editor format', err, {
                        context: 'Protocol editor format switch failed',
                    });
                });
            },
            { label: 'Editor format', value: editorFormat },
        );
        panel.appendChild(formatControl.element);

        const definitionInput = document.createElement('textarea');
        definitionInput.className = 'guidance-textarea';
        definitionInput.value = draft.definition_text || '';
        definitionInput.addEventListener('input', () => {
            draft.definition_text = definitionInput.value;
        });
        definitionInput.addEventListener('change', () => {
            void _parseDraftDocument().then((document) => {
                if (document) {
                    _clearStructuredDrafts();
                    renderAuthorRoute();
                }
            });
        });
        panel.appendChild(definitionInput);
        return panel;
    }

    function _buildAdvancedInspector() {
        const inspector = document.createElement('section');
        inspector.className = 'editor-panel protocol-panel protocol-inspector-panel';
        inspector.dataset.key = 'protocol-author:advanced:inspector';
        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = 'Advanced actions';
        inspector.appendChild(title);

        const saveButton = document.createElement('button');
        saveButton.type = 'button';
        saveButton.className = 'btn btn-primary';
        saveButton.textContent = 'Save draft';
        saveButton.addEventListener('click', () => {
            void _saveCurrentDraft().catch((err) => {
                UI.reportError('Failed to save the protocol draft', err, {
                    context: 'Protocol save failed',
                });
            });
        });
        inspector.appendChild(saveButton);

        const importButton = document.createElement('button');
        importButton.type = 'button';
        importButton.className = 'btn';
        importButton.textContent = 'Import';
        importButton.addEventListener('click', _openImportDialog);
        inspector.appendChild(importButton);

        return inspector;
    }

    function _buildEditorPanel() {
        const editorPanel = document.createElement('section');
        editorPanel.className = 'editor-panel protocol-panel protocol-editor-panel';
        editorPanel.dataset.key = currentProtocolId
            ? `protocol-author:${currentProtocolId}:${currentSection}`
            : 'protocol-author:starter';

        if (protocolDetailLoading && currentProtocolId) {
            editorPanel.appendChild(UI.renderEmptyState('Loading protocol detail…', true));
            return editorPanel;
        }

        if (!currentProtocolId) {
            editorPanel.appendChild(_buildStarterPanel());
            return editorPanel;
        }

        const protocolDocument = _draftDocument();
        _setSelectedEntityDefaults(protocolDocument);

        editorPanel.appendChild(_buildAuthorHeader(protocolDocument));
        editorPanel.appendChild(_buildSectionNav(protocolDocument));

        const workspace = document.createElement('div');
        workspace.className = 'protocol-author-workspace';
        let main = null;
        let inspector = null;
        if (currentSection === 'participants') {
            main = _buildParticipantsCanvas(protocolDocument);
            inspector = _buildParticipantsInspector(protocolDocument);
        } else if (currentSection === 'stages') {
            main = _buildStagesCanvas(protocolDocument);
            inspector = _buildStagesInspector(protocolDocument);
        } else if (currentSection === 'artifacts') {
            main = _buildArtifactsCanvas(protocolDocument);
            inspector = _buildArtifactsInspector(protocolDocument);
        } else if (currentSection === 'policies') {
            main = _buildPoliciesCanvas(protocolDocument);
            inspector = _buildPoliciesInspector(protocolDocument);
        } else if (currentSection === 'review') {
            main = _buildReviewCanvas(protocolDocument);
            inspector = _buildReviewInspector();
        } else if (currentSection === 'advanced') {
            main = _buildAdvancedCanvas(protocolDocument);
            inspector = _buildAdvancedInspector();
        } else {
            main = _buildOverviewCanvas(protocolDocument);
            inspector = _buildOverviewInspector(protocolDocument);
        }
        workspace.appendChild(main);
        workspace.appendChild(inspector);
        editorPanel.appendChild(workspace);
        return editorPanel;
    }

    function renderAuthorRoute() {
        if (authorBoard.firstChild !== listColumnEl || authorBoard.childNodes.length !== 2) {
            authorBoard.replaceChildren(listColumnEl, editorColumnEl);
        }
        if (contentEl.firstChild !== authorBoard || contentEl.childNodes.length !== 1) {
            contentEl.replaceChildren(authorBoard);
        }
        UI.memoizedRender(
            listColumnEl,
            { protocols, protocolSearch, protocolLifecycleFilter, currentProtocolId },
            () => _buildDefinitionPanel(),
            { signatureFields: ['protocols', 'protocolSearch', 'protocolLifecycleFilter', 'currentProtocolId'] },
        );
        UI.reconcileChildren(editorColumnEl, [_buildEditorPanel()]);
    }

    async function loadProtocols() {
        const nextProtocols = await API.listProtocols({ limit: 200 });
        protocols = nextProtocols;
        if (currentProtocolId && !protocols.some((item) => item.protocol_id === currentProtocolId)) {
            currentProtocolId = '';
            currentProtocol = null;
        }
        _writeState();
        renderAuthorRoute();
    }

    async function loadAuthoringManifest() {
        authoringManifest = await API.getProtocolAuthoringManifest();
    }

    async function loadProtocolDetail() {
        if (!currentProtocolId) {
            currentProtocol = null;
            protocolDetailLoading = false;
            _clearStructuredDrafts();
            if (!draft.definition_text) {
                await _refreshDraftTextForCurrentFormat();
            }
            _writeState();
            renderAuthorRoute();
            return;
        }
        protocolDetailLoading = true;
        currentProtocol = await API.getProtocol(currentProtocolId);
        _applyDraftFromProtocol(currentProtocol);
        await _refreshDraftTextForCurrentFormat();
        protocolDetailLoading = false;
        _writeState();
        renderAuthorRoute();
    }

    async function bootstrap() {
        UI.reconcileChildren(contentEl, [UI.renderEmptyState('Loading protocols…', true)]);
        try {
            await Promise.all([loadProtocols(), loadAuthoringManifest()]);
            if (currentProtocolId) {
                await loadProtocolDetail();
            } else {
                await _refreshDraftTextForCurrentFormat();
                renderAuthorRoute();
            }
        } catch (err) {
            UI.reconcileChildren(contentEl, [UI.createErrorCard('Failed to load protocols: ' + err.message, bootstrap)]);
        }
    }

    cleanups.add(() => {
        _clearAutosaveTimer();
        currentProtocol = null;
    });

    UI.subscribeWithRefresh(cleanups, 'protocols', () => loadProtocols(), 350);
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
    header.innerHTML = '<h2>Protocol runs</h2><p>Inspect live protocol execution, issue triage, artifacts, and operator actions without the authoring surface mixed in.</p>';
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

    function _filteredRuns() {
        return (runs || []).filter((item) => {
            if (runStatusFilter && String(item.status || '') !== runStatusFilter) {
                return false;
            }
            const haystack = [
                item.problem_statement || '',
                item.protocol_run_id || '',
                item.current_stage_key || '',
                item.status || '',
                item.protocol_id || '',
            ].join(' ').toLowerCase();
            return !runSearch || haystack.includes(runSearch.toLowerCase());
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

    function _runRows() {
        return _filteredRuns().map((item) => UI.renderListRow({
            label: item.current_stage_key
                ? `${item.current_stage_key} · ${item.status}`
                : (item.status || 'queued'),
            sublabel: item.problem_statement || item.protocol_run_id,
            badgeText: item.protocol_id || '',
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
        const summaryGrid = document.createElement('div');
        summaryGrid.className = 'protocol-run-summary-grid';
        UI.reconcileChildren(summaryGrid, [
            UI.renderMetadataGrid([
                { label: 'Run id', value: currentRun.run.protocol_run_id },
                { label: 'Status', value: currentRun.run.status },
                { label: 'Version', value: String(currentRun.run.version || 1) },
                { label: 'Current stage', value: currentRun.run.current_stage_key || 'n/a' },
                {
                    label: 'Review loop',
                    value: `${Number(currentRun.run.current_review_rounds || 0)} / ${Number(currentRun.run.max_review_rounds || 0) || 'n/a'}`,
                },
                { label: 'Workspace', value: currentRun.run.workspace_ref || 'default' },
                { label: 'Root conversation', value: currentRun.run.root_conversation_id || 'n/a' },
            ]),
        ]);
        return summaryGrid;
    }

    function _buildRunNotes() {
        const detailNotes = document.createElement('div');
        detailNotes.className = 'protocol-run-notes';
        if (currentRun.run.termination_summary || currentRun.run.blocked_detail) {
            const outcomeNote = document.createElement('div');
            outcomeNote.className = 'quiet-note';
            outcomeNote.textContent = currentRun.run.termination_summary || currentRun.run.blocked_detail;
            detailNotes.appendChild(outcomeNote);
        }
        if (lastRunEvent && String(lastRunEvent.protocol_run_id || '') === String(currentRun.run.protocol_run_id || '')) {
            const liveNote = document.createElement('div');
            liveNote.className = 'quiet-note';
            liveNote.textContent = `Live update: ${String(lastRunEvent.event_kind || '').replace(/_/g, ' ')} · ${lastRunEvent.reason || ''}`;
            detailNotes.appendChild(liveNote);
        }
        return detailNotes.childNodes.length ? detailNotes : null;
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
        title.textContent = issueListActive ? 'Protocol issues' : 'Runs';
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

        if (!issueListActive) {
            const runStatusControl = UI.createSegmentedControl(
                PROTOCOL_RUN_STATUS_OPTIONS,
                (value) => {
                    runStatusFilter = value || '';
                    _writeState({ push: true });
                    renderRunsRoute();
                },
                { label: 'Run status filter', value: runStatusFilter || '' },
            );
            panel.appendChild(runStatusControl.element);
        }

        const searchInput = document.createElement('input');
        searchInput.className = 'search-input';
        searchInput.placeholder = issueListActive ? 'Search issues' : 'Search runs';
        searchInput.value = runSearch;
        searchInput.addEventListener('input', () => {
            runSearch = searchInput.value;
            renderRunsRoute();
        });
        panel.appendChild(searchInput);

        const list = document.createElement('div');
        list.className = 'protocol-scroll';
        const rows = issueListActive ? _issueRows() : _runRows();
        UI.reconcileChildren(
            list,
            rows.length
                ? rows
                : [UI.renderEmptyState(
                    issueListActive
                        ? 'No blocked runs, lease issues, contract failures, or expired timeouts match this filter.'
                        : 'No protocol runs match the current filter.',
                    true,
                )],
        );
        panel.appendChild(list);
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
        const detailNotes = _buildRunNotes();
        if (detailNotes) {
            detailPanel.appendChild(detailNotes);
        }
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
