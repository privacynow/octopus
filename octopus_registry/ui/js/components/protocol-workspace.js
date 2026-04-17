function renderProtocolWorkspace(container) {
    const cleanups = UI.beginCleanupScope();
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }

    const ISSUE_KIND_OPTIONS = [
        { value: '', label: 'All issues' },
        { value: 'blocked_run', label: 'Blocked runs' },
        { value: 'invalid_contract', label: 'Contract errors' },
        { value: 'stuck_lease', label: 'Stuck leases' },
        { value: 'expired_timeout', label: 'Expired timeouts' },
    ];
    const RUN_STATUS_OPTIONS = [
        { value: '', label: 'All runs' },
        { value: 'running', label: 'Running' },
        { value: 'blocked', label: 'Blocked' },
        { value: 'completed', label: 'Completed' },
        { value: 'failed', label: 'Failed' },
        { value: 'cancelled', label: 'Cancelled' },
    ];

    let protocols = [];
    let runs = [];
    let protocolIssues = [];
    let agents = [];
    let currentProtocolId = UI.readQueryParam('protocol_id', '');
    let currentRunId = UI.readQueryParam('run_id', '');
    let currentProtocol = null;
    let currentRun = null;
    let currentIssues = [];
    let defaultTemplate = null;
    let lastRunEvent = null;
    let editorFormat = 'json';
    let protocolSearch = '';
    let runSearch = '';
    let issueKindFilter = '';
    let runStatusFilter = '';
    let timelineParticipantFilter = '';
    let runLauncherEntryAgentId = UI.readQueryParam('entry_agent_id', '');
    let runLauncherWorkspaceRef = '';
    let runLauncherProblemStatement = '';
    let currentRunSubscription = null;
    let agentListSignature = '';
    let protocolIssueSignature = '';
    let draft = {
        protocol_id: '',
        slug: '',
        display_name: '',
        description: '',
        definition_text: '',
        document_json: null,
        parse_error: '',
    };
    const structuredInputDrafts = new Map();

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Protocols</h2><p>Define reusable, versioned workflows, publish them once, and operate live protocol runs from the same control plane.</p>';
    container.appendChild(header);

    const shell = document.createElement('section');
    shell.className = 'admin-shell protocol-workspace-shell';
    container.appendChild(shell);

    const contentEl = document.createElement('div');
    contentEl.className = 'protocol-workspace-grid';
    shell.appendChild(contentEl);

    function _writeState() {
        UI.updateQueryParams({
            protocol_id: currentProtocolId || '',
            run_id: currentRunId || '',
            entry_agent_id: runLauncherEntryAgentId || '',
        });
    }

    const runLauncherAgentDropdown = UI.createAgentManagementDropdown(
        [],
        runLauncherEntryAgentId,
        (nextAgentId) => {
            runLauncherEntryAgentId = String(nextAgentId || '');
            _writeState();
            renderWorkspace();
        },
        { label: 'Target bot' },
    );

    function _downloadText(filename, text, contentType) {
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

    async function _readFileText(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onerror = () => reject(reader.error || new Error('Failed to read file'));
            reader.onload = () => resolve(String(reader.result || ''));
            reader.readAsText(file);
        });
    }

    function _reconcileRunLauncherSelection() {
        const eligibleAgents = UI.filterManagedAgents(agents || []);
        if (!eligibleAgents.length) {
            runLauncherEntryAgentId = '';
        } else if (!eligibleAgents.some((agent) => agent.agent_id === runLauncherEntryAgentId)) {
            runLauncherEntryAgentId = eligibleAgents[0].agent_id || '';
        }
        runLauncherAgentDropdown.update(eligibleAgents, runLauncherEntryAgentId);
        _writeState();
        return eligibleAgents;
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

    function _rememberStructuredDraftValue(draftKey, value) {
        if (!draftKey) {
            return;
        }
        structuredInputDrafts.set(draftKey, value);
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

    function _defaultProtocolDocument() {
        return defaultTemplate || {
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

    async function _serializeProtocolDocument(document, format = editorFormat) {
        const normalized = _applyDraftMetadataToDocument(document);
        if (format === 'json') {
            return JSON.stringify(normalized, null, 2);
        }
        const parsed = await API.parseProtocolDocument({
            definition_text: JSON.stringify(normalized, null, 2),
            format,
        });
        return String(parsed.text || '');
    }

    async function _parseDraftDocument({ report = false } = {}) {
        const result = await API.parseProtocolDocument({
            definition_text: draft.definition_text || '',
            format: editorFormat,
        });
        if (!result.document || !(result.validation && result.validation.ok)) {
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
        return document;
    }

    async function _commitDraftDocument(document, { rerender = true } = {}) {
        const normalized = _applyDraftMetadataToDocument(document);
        draft.document_json = normalized;
        draft.parse_error = '';
        _syncDraftFieldsFromDocument(normalized);
        draft.definition_text = await _serializeProtocolDocument(normalized, editorFormat);
        if (rerender) {
            renderWorkspace();
        }
        return normalized;
    }

    async function _applyStructuredChange(mutator) {
        try {
            const document = await _parseDraftDocument() || _draftDocument();
            const working = _cloneDocument(document);
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
    }

    async function _refreshDraftTextForCurrentFormat() {
        if (!currentProtocol && !draft.definition_text) {
            draft.document_json = _cloneDocument(_defaultProtocolDocument());
            draft.definition_text = editorFormat === 'yaml'
                ? String((await API.parseProtocolDocument({
                    definition_text: JSON.stringify(_defaultProtocolDocument(), null, 2),
                    format: 'yaml',
                })).text || '')
                : JSON.stringify(_defaultProtocolDocument(), null, 2);
            return;
        }
        const source = currentProtocol?.draft_document || currentProtocol?.draft_definition_json || draft.document_json || _defaultProtocolDocument();
        const parsed = await API.parseProtocolDocument({
            definition_text: JSON.stringify(source, null, 2),
            format: editorFormat,
        });
        draft.document_json = _cloneDocument(source);
        draft.parse_error = '';
        draft.definition_text = String(parsed.text || '');
    }

    function _protocolRows() {
        const filtered = (protocols || []).filter((item) => {
            const haystack = [
                item.display_name || '',
                item.slug || '',
                item.protocol_id || '',
                item.description || '',
            ].join(' ').toLowerCase();
            return !protocolSearch || haystack.includes(protocolSearch.toLowerCase());
        });
        return filtered.map((item) => UI.renderListRow({
            label: item.display_name || item.slug || item.protocol_id,
            sublabel: item.description || item.slug || item.protocol_id,
            badgeText: item.lifecycle_state || 'draft',
            className: item.protocol_id === currentProtocolId ? 'is-selected' : '',
            onClick: () => {
                currentProtocolId = item.protocol_id;
                currentRunId = '';
                void loadProtocolDetail();
            },
        }));
    }

    function _runRows() {
        const filtered = (runs || []).filter((item) => {
            if (runStatusFilter && String(item.status || '') !== runStatusFilter) {
                return false;
            }
            const haystack = [
                item.problem_statement || '',
                item.protocol_run_id || '',
                item.current_stage_key || '',
                item.status || '',
            ].join(' ').toLowerCase();
            return !runSearch || haystack.includes(runSearch.toLowerCase());
        });
        return filtered.map((item) => UI.renderListRow({
            label: item.current_stage_key
                ? `${item.current_stage_key} · ${item.status}`
                : (item.status || 'queued'),
            sublabel: item.problem_statement || item.protocol_run_id,
            badgeText: item.protocol_id || '',
            className: item.protocol_run_id === currentRunId ? 'is-selected' : '',
            onClick: () => {
                currentRunId = item.protocol_run_id;
                void loadRunDetail();
            },
        }));
    }

    function _issueRows() {
        return (protocolIssues || []).map((item) => UI.renderListRow({
            label: `${String(item.issue_kind || '').replace(/_/g, ' ')} · ${item.protocol_display_name || item.protocol_id || 'Protocol issue'}`,
            sublabel: [
                item.stage_key ? `stage ${item.stage_key}` : '',
                item.issue_detail || item.issue_code || '',
            ].filter(Boolean).join(' · '),
            badgeText: item.issue_code || item.stage_key || '',
            className: item.protocol_run_id === currentRunId ? 'is-selected' : '',
            onClick: () => {
                currentRunId = item.protocol_run_id;
                void loadRunDetail();
            },
        }));
    }

    function _runDeepLink(run) {
        const token = String(run?.protocol_run_id || '').trim();
        if (!token) {
            return '/ui/protocols';
        }
        return `/ui/protocols?run_id=${encodeURIComponent(token)}`;
    }

    function _artifactLabel(item) {
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

    function _transitionParticipantKey(transition, stageById) {
        const toStage = stageById.get(String(transition.to_stage_execution_id || ''));
        if (toStage && toStage.participant_key) {
            return String(toStage.participant_key || '');
        }
        const fromStage = stageById.get(String(transition.from_stage_execution_id || ''));
        return fromStage ? String(fromStage.participant_key || '') : '';
    }

    function _filteredTimelineData() {
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
            !timelineParticipantFilter || _transitionParticipantKey(item, stageById) === timelineParticipantFilter,
        );
        return { stageRows, transitionRows, participantOptions };
    }

    function _renderValidationGutter(parent) {
        const validation = currentProtocol?.validation;
        const parseError = String(draft.parse_error || '');
        if (!validation && !parseError) {
            return;
        }
        const ok = Boolean(validation && validation.ok && !parseError);
        const gutter = document.createElement('section');
        gutter.className = `protocol-validation-gutter ${ok ? 'is-valid' : 'is-invalid'}`;
        gutter.setAttribute('role', ok ? 'status' : 'alert');
        const title = document.createElement('strong');
        title.textContent = ok ? 'Validation passed' : 'Validation issues';
        gutter.appendChild(title);
        const summary = document.createElement('div');
        summary.className = 'quiet-note';
        summary.textContent = ok
            ? `Draft valid. Content hash: ${validation?.content_hash || 'n/a'}`
            : parseError || `${validation?.errors.length || 0} issue(s) found.`;
        gutter.appendChild(summary);
        if (!ok && validation?.errors.length) {
            const list = document.createElement('ul');
            list.className = 'protocol-validation-list';
            validation.errors.forEach((item) => {
                const li = document.createElement('li');
                li.textContent = item;
                list.appendChild(li);
            });
            gutter.appendChild(list);
        }
        parent.appendChild(gutter);
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
        note.textContent = 'Import uses the same canonical validator as save/publish. JSON and YAML both normalize to the shared protocol document model.';
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
                    definitionText = await _readFileText(file);
                }
                if (!definitionText) {
                    textarea.focus();
                    return;
                }
                const parsed = await API.parseProtocolDocument({
                    definition_text: definitionText,
                    format: formatValue,
                });
                const document = _applyDraftMetadataToDocument(parsed.document || _defaultProtocolDocument());
                draft.document_json = document;
                draft.slug = document.metadata?.slug || draft.slug || '';
                draft.display_name = document.metadata?.display_name || draft.display_name || '';
                draft.description = document.metadata?.description || draft.description || '';
                editorFormat = formatValue;
                draft.definition_text = String(parsed.text || definitionText);
                draft.parse_error = '';
                _clearStructuredDrafts();
                currentProtocol = null;
                currentProtocolId = '';
                currentRunId = '';
                currentRun = null;
                lastRunEvent = null;
                _writeState();
                renderWorkspace();
                view.close();
                UI.notify('Protocol definition imported into the editor.', 'success');
            } catch (err) {
                UI.reportError('Failed to import the protocol definition', err, {
                    context: 'Protocol import failed',
                });
            }
            importBtn.disabled = false;
        });
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
            _downloadText(
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

    async function _downloadRunExport() {
        if (!currentRun) {
            return;
        }
        try {
            const exported = await API.exportProtocolRun(currentRun.run.protocol_run_id);
            _downloadText(
                `${UI.safeFilename(currentRun.definition?.slug || currentRun.run.protocol_run_id || 'protocol-run')}.protocol-run.json`,
                JSON.stringify(exported, null, 2),
                'application/json',
            );
        } catch (err) {
            UI.reportError('Failed to export the protocol run', err, {
                context: 'Protocol run export failed',
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

    function _renderStructuredEditor(parent) {
        const protocolDoc = _draftDocument();
        const fieldKey = (...parts) => parts.join(':');
        const wrapper = document.createElement('section');
        wrapper.className = 'protocol-structured-editor';
        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = 'Structured editor';
        wrapper.appendChild(title);

        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = draft.parse_error
            ? `Raw editor has unsynced errors. Structured controls are using the last valid document: ${draft.parse_error}`
            : 'Participants, artifacts, stages, and policies edit the same shared protocol document model as the raw JSON/YAML editor.';
        wrapper.appendChild(note);

        const section = (headingText, addAction) => {
            const block = document.createElement('section');
            block.className = 'protocol-structured-section';
            const header = document.createElement('div');
            header.className = 'protocol-structured-header';
            const heading = document.createElement('strong');
            heading.textContent = headingText;
            header.appendChild(heading);
            if (addAction) {
                const addButton = document.createElement('button');
                addButton.type = 'button';
                addButton.className = 'btn';
                addButton.textContent = addAction.label;
                addButton.addEventListener('click', addAction.onClick);
                header.appendChild(addButton);
            }
            block.appendChild(header);
            return block;
        };

        const participantSection = section('Participants', {
            label: 'Add participant',
            onClick: () => void _applyStructuredChange((next) => {
                _clearStructuredDrafts();
                const index = (next.participants || []).length + 1;
                next.participants = [...(next.participants || []), {
                    participant_key: `participant_${index}`,
                    display_name: `Participant ${index}`,
                    required_skills: [],
                    instructions: '',
                }];
            }),
        });
        (protocolDoc.participants || []).forEach((item, index) => {
            const card = document.createElement('div');
            card.className = 'protocol-structured-card';
            card.appendChild(UI.renderSettingsRow({
                label: 'Key',
                control: _textInput(item.participant_key, (value) => void _applyStructuredChange((next) => {
                    next.participants[index].participant_key = value;
                }), { placeholder: 'participant_key', ariaLabel: 'Participant key', draftKey: fieldKey('participant', index, 'participant_key') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Display name',
                control: _textInput(item.display_name, (value) => void _applyStructuredChange((next) => {
                    next.participants[index].display_name = value;
                }), { placeholder: 'Display name', ariaLabel: 'Participant display name', draftKey: fieldKey('participant', index, 'display_name') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Required skills',
                control: _textInput((item.required_skills || []).join(', '), (value) => void _applyStructuredChange((next) => {
                    next.participants[index].required_skills = _commaList(value);
                }), { placeholder: 'skill-a, skill-b', ariaLabel: 'Participant required skills', draftKey: fieldKey('participant', index, 'required_skills') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Selector kind',
                control: _selectInput([
                    { value: '', label: 'None' },
                    { value: 'agent', label: 'Agent' },
                    { value: 'skill', label: 'Skill' },
                    { value: 'role', label: 'Role' },
                ], item.selector?.kind || '', (value) => void _applyStructuredChange((next) => {
                    next.participants[index].selector = value
                        ? Object.assign({}, next.participants[index].selector || {}, { kind: value })
                        : null;
                }), { ariaLabel: 'Participant selector kind', draftKey: fieldKey('participant', index, 'selector_kind') }),
            }));
            if (item.selector?.kind) {
                card.appendChild(UI.renderSettingsRow({
                    label: 'Selector value',
                    control: _textInput(item.selector?.value || '', (value) => void _applyStructuredChange((next) => {
                        next.participants[index].selector = Object.assign({}, next.participants[index].selector || {}, { value });
                    }), { placeholder: 'selector value', ariaLabel: 'Participant selector value', draftKey: fieldKey('participant', index, 'selector_value') }),
                }));
                card.appendChild(UI.renderSettingsRow({
                    label: 'Preferred agent',
                    control: _textInput(item.selector?.preferred_agent_id || '', (value) => void _applyStructuredChange((next) => {
                        next.participants[index].selector = Object.assign({}, next.participants[index].selector || {}, { preferred_agent_id: value });
                    }), { placeholder: 'agent id (optional)', ariaLabel: 'Participant preferred agent', draftKey: fieldKey('participant', index, 'preferred_agent_id') }),
                }));
            }
            card.appendChild(UI.renderSettingsRow({
                label: 'Instructions',
                control: _textAreaInput(item.instructions || '', (value) => void _applyStructuredChange((next) => {
                    next.participants[index].instructions = value;
                }), { placeholder: 'Participant-specific instructions', rows: 3, ariaLabel: 'Participant instructions', draftKey: fieldKey('participant', index, 'instructions') }),
            }));
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'btn';
            remove.textContent = 'Remove participant';
            remove.addEventListener('click', () => void _applyStructuredChange((next) => {
                _clearStructuredDrafts();
                next.participants.splice(index, 1);
            }));
            card.appendChild(remove);
            participantSection.appendChild(card);
        });
        if (!(protocolDoc.participants || []).length) {
            participantSection.appendChild(UI.renderEmptyState('No participants defined yet.', true));
        }
        wrapper.appendChild(participantSection);

        const artifactSection = section('Artifacts', {
            label: 'Add artifact',
            onClick: () => void _applyStructuredChange((next) => {
                _clearStructuredDrafts();
                const index = (next.artifacts || []).length + 1;
                next.artifacts = [...(next.artifacts || []), {
                    artifact_key: `artifact_${index}`,
                    display_name: `Artifact ${index}`,
                    description: '',
                    kind: 'workspace_file',
                    path: `docs/artifact-${index}.md`,
                    verify: true,
                }];
            }),
        });
        (protocolDoc.artifacts || []).forEach((item, index) => {
            const card = document.createElement('div');
            card.className = 'protocol-structured-card';
            card.appendChild(UI.renderSettingsRow({
                label: 'Key',
                control: _textInput(item.artifact_key, (value) => void _applyStructuredChange((next) => {
                    next.artifacts[index].artifact_key = value;
                }), { placeholder: 'artifact_key', ariaLabel: 'Artifact key', draftKey: fieldKey('artifact', index, 'artifact_key') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Display name',
                control: _textInput(item.display_name, (value) => void _applyStructuredChange((next) => {
                    next.artifacts[index].display_name = value;
                }), { placeholder: 'Display name', ariaLabel: 'Artifact display name', draftKey: fieldKey('artifact', index, 'display_name') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Kind',
                control: _selectInput([
                    { value: 'workspace_file', label: 'Workspace file' },
                    { value: 'control_plane_text', label: 'Control-plane text' },
                ], item.kind || 'workspace_file', (value) => void _applyStructuredChange((next) => {
                    next.artifacts[index].kind = value || 'workspace_file';
                }), { ariaLabel: 'Artifact kind', draftKey: fieldKey('artifact', index, 'kind') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Path',
                control: _textInput(item.path || '', (value) => void _applyStructuredChange((next) => {
                    next.artifacts[index].path = value;
                }), { placeholder: 'relative/path.md', ariaLabel: 'Artifact path', draftKey: fieldKey('artifact', index, 'path') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Description',
                control: _textAreaInput(item.description || '', (value) => void _applyStructuredChange((next) => {
                    next.artifacts[index].description = value;
                }), { placeholder: 'Artifact description', rows: 2, ariaLabel: 'Artifact description', draftKey: fieldKey('artifact', index, 'description') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Verification',
                control: _checkboxInput(Boolean(item.verify !== false), 'Require verification', (checked) => void _applyStructuredChange((next) => {
                    next.artifacts[index].verify = checked;
                }), { ariaLabel: 'Artifact verification required', draftKey: fieldKey('artifact', index, 'verify') }),
            }));
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'btn';
            remove.textContent = 'Remove artifact';
            remove.addEventListener('click', () => void _applyStructuredChange((next) => {
                _clearStructuredDrafts();
                next.artifacts.splice(index, 1);
            }));
            card.appendChild(remove);
            artifactSection.appendChild(card);
        });
        if (!(protocolDoc.artifacts || []).length) {
            artifactSection.appendChild(UI.renderEmptyState('No artifacts defined yet.', true));
        }
        wrapper.appendChild(artifactSection);

        const participantOptions = [{ value: '', label: 'Select participant' }].concat(
            (protocolDoc.participants || []).map((item) => ({
                value: String(item.participant_key || ''),
                label: item.display_name || item.participant_key || '',
            })),
        );
        const artifactOptions = (protocolDoc.artifacts || []).map((item) => String(item.artifact_key || '')).filter(Boolean);
        const stageSection = section('Stages', {
            label: 'Add stage',
            onClick: () => void _applyStructuredChange((next) => {
                _clearStructuredDrafts();
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
            }),
        });
        (protocolDoc.stages || []).forEach((item, index) => {
            const card = document.createElement('div');
            card.className = 'protocol-structured-card';
            card.appendChild(UI.renderSettingsRow({
                label: 'Key',
                control: _textInput(item.stage_key, (value) => void _applyStructuredChange((next) => {
                    next.stages[index].stage_key = value;
                }), { placeholder: 'stage_key', ariaLabel: 'Stage key', draftKey: fieldKey('stage', index, 'stage_key') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Display name',
                control: _textInput(item.display_name, (value) => void _applyStructuredChange((next) => {
                    next.stages[index].display_name = value;
                }), { placeholder: 'Display name', ariaLabel: 'Stage display name', draftKey: fieldKey('stage', index, 'display_name') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Participant',
                control: _selectInput(participantOptions, item.participant_key || '', (value) => void _applyStructuredChange((next) => {
                    next.stages[index].participant_key = value;
                }), { ariaLabel: 'Stage participant', draftKey: fieldKey('stage', index, 'participant_key') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Kind',
                control: _selectInput([
                    { value: 'work', label: 'Work' },
                    { value: 'review', label: 'Review' },
                    { value: 'acceptance', label: 'Acceptance' },
                ], item.stage_kind || 'work', (value) => void _applyStructuredChange((next) => {
                    next.stages[index].stage_kind = value || 'work';
                }), { ariaLabel: 'Stage kind', draftKey: fieldKey('stage', index, 'stage_kind') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Instructions',
                control: _textAreaInput(item.instructions || '', (value) => void _applyStructuredChange((next) => {
                    next.stages[index].instructions = value;
                }), { placeholder: 'Stage instructions', rows: 4, ariaLabel: 'Stage instructions', draftKey: fieldKey('stage', index, 'instructions') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Inputs',
                control: _textInput((item.inputs || []).join(', '), (value) => void _applyStructuredChange((next) => {
                    next.stages[index].inputs = _commaList(value);
                }), { placeholder: artifactOptions.join(', ') || 'artifact keys', ariaLabel: 'Stage inputs', draftKey: fieldKey('stage', index, 'inputs') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Outputs',
                control: _textInput((item.outputs || []).join(', '), (value) => void _applyStructuredChange((next) => {
                    next.stages[index].outputs = _commaList(value);
                }), { placeholder: artifactOptions.join(', ') || 'artifact keys', ariaLabel: 'Stage outputs', draftKey: fieldKey('stage', index, 'outputs') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Transitions',
                control: _textAreaInput(JSON.stringify(item.transitions || {}, null, 2), (value) => {
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
                }, { placeholder: '{"completed":"next_stage"}', rows: 4, ariaLabel: 'Stage transitions JSON', draftKey: fieldKey('stage', index, 'transitions') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Write lease',
                control: _checkboxInput(Boolean(item.write_capable), 'Write-capable stage', (checked) => void _applyStructuredChange((next) => {
                    next.stages[index].write_capable = checked;
                }), { ariaLabel: 'Stage write capable', draftKey: fieldKey('stage', index, 'write_capable') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Strict completion',
                control: _checkboxInput(Boolean(item.strict_completion), 'Require protocol control lines', (checked) => void _applyStructuredChange((next) => {
                    next.stages[index].strict_completion = checked;
                }), { ariaLabel: 'Stage strict completion', draftKey: fieldKey('stage', index, 'strict_completion') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Output verification',
                control: _selectInput([
                    { value: '', label: 'Inherit default' },
                    { value: 'true', label: 'Required' },
                    { value: 'false', label: 'Not required' },
                ], item.require_output_verification === null || item.require_output_verification === undefined
                    ? ''
                    : String(Boolean(item.require_output_verification)), (value) => void _applyStructuredChange((next) => {
                    next.stages[index].require_output_verification = value === ''
                        ? null
                        : value === 'true';
                }), { ariaLabel: 'Stage output verification', draftKey: fieldKey('stage', index, 'require_output_verification') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Max rounds',
                control: _numberInput(item.max_rounds || 0, (value) => void _applyStructuredChange((next) => {
                    next.stages[index].max_rounds = value;
                }), { min: 0, ariaLabel: 'Stage max rounds', draftKey: fieldKey('stage', index, 'max_rounds') }),
            }));
            card.appendChild(UI.renderSettingsRow({
                label: 'Timeout seconds',
                control: _numberInput(item.timeout_seconds || 0, (value) => void _applyStructuredChange((next) => {
                    next.stages[index].timeout_seconds = value;
                }), { min: 0, ariaLabel: 'Stage timeout seconds', draftKey: fieldKey('stage', index, 'timeout_seconds') }),
            }));
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'btn';
            remove.textContent = 'Remove stage';
            remove.addEventListener('click', () => void _applyStructuredChange((next) => {
                _clearStructuredDrafts();
                next.stages.splice(index, 1);
            }));
            card.appendChild(remove);
            stageSection.appendChild(card);
        });
        if (!(protocolDoc.stages || []).length) {
            stageSection.appendChild(UI.renderEmptyState('No stages defined yet.', true));
        }
        wrapper.appendChild(stageSection);

        const policySection = section('Policies');
        const policyCard = document.createElement('div');
        policyCard.className = 'protocol-structured-card';
        policyCard.appendChild(UI.renderSettingsRow({
            label: 'Single active writer',
            control: _checkboxInput(Boolean(protocolDoc.policies?.single_active_writer !== false), 'Enforce one write lease at a time', (checked) => void _applyStructuredChange((next) => {
                next.policies.single_active_writer = checked;
            }), { ariaLabel: 'Single active writer', draftKey: fieldKey('policy', 'single_active_writer') }),
        }));
        policyCard.appendChild(UI.renderSettingsRow({
            label: 'Max review rounds',
            control: _numberInput(protocolDoc.policies?.max_review_rounds || 5, (value) => void _applyStructuredChange((next) => {
                next.policies.max_review_rounds = Math.max(value, 1);
            }), { min: 1, ariaLabel: 'Max review rounds', draftKey: fieldKey('policy', 'max_review_rounds') }),
        }));
        policySection.appendChild(policyCard);
        wrapper.appendChild(policySection);

        parent.appendChild(wrapper);
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
            void loadRunDetail({ soft: true });
        });
    }

    function renderWorkspace() {
        const definitionPanel = document.createElement('section');
        definitionPanel.className = 'editor-panel protocol-panel protocol-panel-list';

        const definitionTitle = document.createElement('div');
        definitionTitle.className = 'editor-section-title';
        definitionTitle.textContent = 'Definitions';
        definitionPanel.appendChild(definitionTitle);

        const definitionSearch = document.createElement('input');
        definitionSearch.className = 'search-input';
        definitionSearch.placeholder = 'Search definitions';
        definitionSearch.value = protocolSearch;
        definitionSearch.addEventListener('input', () => {
            protocolSearch = definitionSearch.value;
            renderWorkspace();
        });
        definitionPanel.appendChild(definitionSearch);

        const definitionActions = document.createElement('div');
        definitionActions.className = 'editor-actions protocol-sticky-actions';
        const newButton = document.createElement('button');
        newButton.type = 'button';
        newButton.className = 'btn btn-primary';
        newButton.textContent = 'New protocol';
        newButton.addEventListener('click', async () => {
            try {
                if (!defaultTemplate) {
                    defaultTemplate = await API.getProtocolTemplate('software-engineering');
                }
                editorFormat = 'json';
                currentProtocolId = '';
                currentProtocol = null;
                currentRunId = '';
                currentRun = null;
                lastRunEvent = null;
                _clearStructuredDrafts();
                draft = {
                    protocol_id: '',
                    slug: defaultTemplate.metadata?.slug || '',
                    display_name: defaultTemplate.metadata?.display_name || '',
                    description: defaultTemplate.metadata?.description || '',
                    definition_text: JSON.stringify(defaultTemplate, null, 2),
                    document_json: _cloneDocument(defaultTemplate),
                    parse_error: '',
                };
                _writeState();
                renderWorkspace();
            } catch (err) {
                UI.reportError('Failed to load the default protocol template', err, {
                    context: 'Protocol template load failed',
                });
            }
        });
        definitionActions.appendChild(newButton);

        const importButton = document.createElement('button');
        importButton.type = 'button';
        importButton.className = 'btn';
        importButton.textContent = 'Import';
        importButton.addEventListener('click', _openImportDialog);
        definitionActions.appendChild(importButton);
        definitionPanel.appendChild(definitionActions);

        const definitionList = document.createElement('div');
        definitionList.className = 'protocol-scroll';
        const definitionRows = _protocolRows();
        UI.reconcileChildren(
            definitionList,
            definitionRows.length
                ? definitionRows
                : [UI.renderEmptyState('No protocols yet. Start from the software engineering template or import one.', true)],
        );
        definitionPanel.appendChild(definitionList);

        const issueTitle = document.createElement('div');
        issueTitle.className = 'editor-section-title';
        issueTitle.textContent = 'Support issues';
        definitionPanel.appendChild(issueTitle);

        const issueFilterControl = UI.createSegmentedControl(
            ISSUE_KIND_OPTIONS,
            (value) => {
                issueKindFilter = value || '';
                void loadIssues();
            },
            { label: 'Issue filter', value: issueKindFilter || '' },
        );
        definitionPanel.appendChild(issueFilterControl.element);

        const issueList = document.createElement('div');
        issueList.className = 'protocol-scroll';
        const issueRows = _issueRows();
        UI.reconcileChildren(
            issueList,
            issueRows.length
                ? issueRows
                : [UI.renderEmptyState('No blocked runs, lease issues, contract failures, or expired timeouts are visible right now.', true)],
        );
        definitionPanel.appendChild(issueList);

        const editorPanel = document.createElement('section');
        editorPanel.className = 'editor-panel protocol-panel protocol-panel-editor';

        const editorTitle = document.createElement('div');
        editorTitle.className = 'editor-section-title';
        editorTitle.textContent = currentProtocolId ? 'Protocol detail' : 'Protocol editor';
        editorPanel.appendChild(editorTitle);

        if (!currentProtocolId && !protocols.length && !draft.definition_text) {
            const empty = document.createElement('div');
            empty.className = 'protocol-first-run';
            empty.appendChild(UI.renderEmptyState('First run: create a draft from the template, validate it, publish it, then start a run against a connected bot.', false));
            editorPanel.appendChild(empty);
        }

        const slugInput = document.createElement('input');
        slugInput.className = 'search-input';
        slugInput.placeholder = 'protocol-slug';
        slugInput.value = draft.slug || '';
        slugInput.addEventListener('input', () => {
            draft.slug = slugInput.value;
        });
        slugInput.addEventListener('change', () => {
            void _commitDraftDocument(_draftDocument());
        });
        editorPanel.appendChild(UI.renderSettingsRow({ label: 'Slug', control: slugInput }));

        const nameInput = document.createElement('input');
        nameInput.className = 'search-input';
        nameInput.placeholder = 'Display name';
        nameInput.value = draft.display_name || '';
        nameInput.addEventListener('input', () => {
            draft.display_name = nameInput.value;
        });
        nameInput.addEventListener('change', () => {
            void _commitDraftDocument(_draftDocument());
        });
        editorPanel.appendChild(UI.renderSettingsRow({ label: 'Display name', control: nameInput }));

        const descriptionInput = document.createElement('input');
        descriptionInput.className = 'search-input';
        descriptionInput.placeholder = 'Description';
        descriptionInput.value = draft.description || '';
        descriptionInput.addEventListener('input', () => {
            draft.description = descriptionInput.value;
        });
        descriptionInput.addEventListener('change', () => {
            void _commitDraftDocument(_draftDocument());
        });
        editorPanel.appendChild(UI.renderSettingsRow({ label: 'Description', control: descriptionInput }));

        const metaNote = document.createElement('div');
        metaNote.className = 'quiet-note';
        metaNote.textContent = currentProtocol?.protocol
            ? [
                currentProtocol.protocol.lifecycle_state || 'draft',
                currentProtocol.version ? `version ${currentProtocol.version.version || 0}` : '',
                currentProtocol.protocol.current_version_id ? 'published version available' : 'not yet published',
              ].filter(Boolean).join(' · ')
            : 'Draft metadata becomes the protocol catalog row once saved.';
        editorPanel.appendChild(metaNote);

        const formatControl = UI.createSegmentedControl(
            [
                { value: 'json', label: 'JSON' },
                { value: 'yaml', label: 'YAML' },
            ],
            (value) => {
                void _syncEditorFormat(value || 'json').then(renderWorkspace).catch((err) => {
                    UI.reportError('Failed to switch the protocol editor format', err, {
                        context: 'Protocol editor format switch failed',
                    });
                });
            },
            { label: 'Editor format', value: editorFormat },
        );
        editorPanel.appendChild(formatControl.element);

        _renderValidationGutter(editorPanel);
        _renderStructuredEditor(editorPanel);

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
                    renderWorkspace();
                }
            });
        });
        editorPanel.appendChild(definitionInput);

        const editorActions = document.createElement('div');
        editorActions.className = 'editor-actions protocol-sticky-actions';

        const saveButton = document.createElement('button');
        saveButton.type = 'button';
        saveButton.className = 'btn btn-primary';
        saveButton.textContent = currentProtocolId ? 'Save draft' : 'Create protocol';
        saveButton.addEventListener('click', async () => {
            try {
                const parsed = await _parseDraftDocument({ report: true });
                const payload = {
                    slug: draft.slug,
                    display_name: draft.display_name,
                    description: draft.description,
                    definition_json: parsed,
                };
                const result = currentProtocolId
                    ? await API.saveProtocolDraft(currentProtocolId, payload)
                    : await API.createProtocol(payload);
                currentProtocolId = result.protocol?.protocol_id || currentProtocolId;
                currentProtocol = result;
                _applyDraftFromProtocol(result);
                await _refreshDraftTextForCurrentFormat();
                await loadProtocols();
                await loadProtocolDetail();
                UI.notify('Protocol draft saved.', 'success');
            } catch (err) {
                UI.reportError('Failed to save the protocol draft', err, {
                    context: 'Protocol save failed',
                });
            }
        });
        editorActions.appendChild(saveButton);

        if (currentProtocolId) {
            const validateButton = document.createElement('button');
            validateButton.type = 'button';
            validateButton.className = 'btn';
            validateButton.textContent = 'Validate';
            validateButton.addEventListener('click', async () => {
                try {
                    currentProtocol = await API.validateProtocol(currentProtocolId);
                    _applyDraftFromProtocol(currentProtocol);
                    await _refreshDraftTextForCurrentFormat();
                    renderWorkspace();
                    UI.notify(
                        currentProtocol.validation?.ok ? 'Protocol validated.' : 'Protocol validation found issues.',
                        currentProtocol.validation?.ok ? 'success' : 'warning',
                    );
                } catch (err) {
                    UI.reportError('Failed to validate the protocol draft', err, {
                        context: 'Protocol validate failed',
                    });
                }
            });
            editorActions.appendChild(validateButton);

            const diffButton = document.createElement('button');
            diffButton.type = 'button';
            diffButton.className = 'btn';
            diffButton.textContent = 'Diff';
            diffButton.addEventListener('click', () => {
                void _showDraftDiff();
            });
            editorActions.appendChild(diffButton);

            const publishButton = document.createElement('button');
            publishButton.type = 'button';
            publishButton.className = 'btn';
            publishButton.textContent = 'Publish';
            publishButton.addEventListener('click', async () => {
                try {
                    currentProtocol = await API.publishProtocol(currentProtocolId);
                    _applyDraftFromProtocol(currentProtocol);
                    await _refreshDraftTextForCurrentFormat();
                    await loadProtocols();
                    renderWorkspace();
                    UI.notify('Protocol published.', 'success');
                } catch (err) {
                    UI.reportError('Failed to publish the protocol', err, {
                        context: 'Protocol publish failed',
                    });
                }
            });
            editorActions.appendChild(publishButton);

            const archiveButton = document.createElement('button');
            archiveButton.type = 'button';
            archiveButton.className = 'btn';
            archiveButton.textContent = 'Archive';
            archiveButton.disabled = String(currentProtocol?.protocol?.lifecycle_state || '') === 'archived';
            archiveButton.addEventListener('click', () => {
                UI.showConfirm(
                    'Archive protocol',
                    'Archive this protocol definition? Published versions remain immutable, but the definition will no longer be offered for new runs.',
                    async () => {
                        try {
                            currentProtocol = await API.archiveProtocol(currentProtocolId);
                            _applyDraftFromProtocol(currentProtocol);
                            await _refreshDraftTextForCurrentFormat();
                            await loadProtocols();
                            renderWorkspace();
                            UI.notify('Protocol archived.', 'success');
                        } catch (err) {
                            UI.reportError('Failed to archive the protocol', err, {
                                context: 'Protocol archive failed',
                            });
                        }
                    },
                );
            });
            editorActions.appendChild(archiveButton);
        }

        const exportJsonBtn = document.createElement('button');
        exportJsonBtn.type = 'button';
        exportJsonBtn.className = 'btn';
        exportJsonBtn.textContent = 'Export JSON';
        exportJsonBtn.addEventListener('click', () => {
            void _downloadDraft('json');
        });
        editorActions.appendChild(exportJsonBtn);

        const exportYamlBtn = document.createElement('button');
        exportYamlBtn.type = 'button';
        exportYamlBtn.className = 'btn';
        exportYamlBtn.textContent = 'Export YAML';
        exportYamlBtn.addEventListener('click', () => {
            void _downloadDraft('yaml');
        });
        editorActions.appendChild(exportYamlBtn);

        editorPanel.appendChild(editorActions);

        const runPanel = document.createElement('section');
        runPanel.className = 'editor-panel protocol-panel protocol-panel-runs';

        const runTitle = document.createElement('div');
        runTitle.className = 'editor-section-title';
        runTitle.textContent = 'Runs';
        runPanel.appendChild(runTitle);

        const runStatusControl = UI.createSegmentedControl(
            RUN_STATUS_OPTIONS,
            (value) => {
                runStatusFilter = value || '';
                renderWorkspace();
            },
            { label: 'Run status filter', value: runStatusFilter || '' },
        );
        runPanel.appendChild(runStatusControl.element);

        const runSearchInput = document.createElement('input');
        runSearchInput.className = 'search-input';
        runSearchInput.placeholder = 'Search runs';
        runSearchInput.value = runSearch;
        runSearchInput.addEventListener('input', () => {
            runSearch = runSearchInput.value;
            renderWorkspace();
        });
        runPanel.appendChild(runSearchInput);

        const runLauncher = document.createElement('div');
        runLauncher.className = 'protocol-run-launcher';
        const runNote = document.createElement('div');
        runNote.className = 'quiet-note';
        runNote.textContent = 'Only published protocol versions can start runs.';
        runLauncher.appendChild(runNote);
        const eligibleRunAgents = _reconcileRunLauncherSelection();

        runLauncher.appendChild(UI.renderSettingsRow({ label: 'Target bot', control: runLauncherAgentDropdown.element }));
        if (!eligibleRunAgents.length) {
            const emptyNote = document.createElement('div');
            emptyNote.className = 'quiet-note';
            emptyNote.textContent = 'No connected bot is currently eligible to host a protocol run.';
            runLauncher.appendChild(emptyNote);
        }

        const workspaceInput = document.createElement('input');
        workspaceInput.className = 'search-input';
        workspaceInput.placeholder = 'Project name or workspace id';
        workspaceInput.value = runLauncherWorkspaceRef;
        workspaceInput.addEventListener('input', () => {
            runLauncherWorkspaceRef = workspaceInput.value;
        });
        runLauncher.appendChild(UI.renderSettingsRow({ label: 'Workspace', control: workspaceInput }));

        const problemInput = document.createElement('textarea');
        problemInput.className = 'guidance-textarea';
        problemInput.rows = 8;
        problemInput.placeholder = 'Problem statement';
        problemInput.value = runLauncherProblemStatement;
        problemInput.addEventListener('input', () => {
            runLauncherProblemStatement = problemInput.value;
        });
        runLauncher.appendChild(problemInput);

        const startRunButton = document.createElement('button');
        startRunButton.type = 'button';
        startRunButton.className = 'btn btn-primary';
        startRunButton.textContent = 'Start run';
        const runnableProtocol = Boolean(
            currentProtocolId
            && currentProtocol?.protocol?.lifecycle_state === 'published'
            && currentProtocol?.version?.protocol_definition_version_id
        );
        const canStartRun = runnableProtocol && eligibleRunAgents.some((agent) => agent.agent_id === runLauncherEntryAgentId);
        startRunButton.disabled = !canStartRun;
        startRunButton.addEventListener('click', async () => {
            if (!runnableProtocol) {
                UI.notify('Publish the protocol before starting a run.', 'warning');
                return;
            }
            if (!runLauncherEntryAgentId) {
                UI.notify('Choose a connected target bot before starting a run.', 'warning');
                return;
            }
            try {
                const result = await API.createProtocolRun({
                    protocol_id: currentProtocolId,
                    entry_agent_id: runLauncherEntryAgentId,
                    origin_channel: 'registry',
                    workspace_ref: runLauncherWorkspaceRef,
                    problem_statement: runLauncherProblemStatement,
                    constraints_json: {},
                }, {
                    idempotencyKey: (window.crypto && typeof window.crypto.randomUUID === 'function')
                        ? window.crypto.randomUUID().replace(/-/g, '')
                        : `${Date.now()}${Math.random().toString(16).slice(2)}`,
                });
                currentRunId = result.run?.protocol_run_id || '';
                lastRunEvent = null;
                await loadRuns();
                await loadRunDetail();
                UI.notify('Protocol run started.', 'success');
            } catch (err) {
                UI.reportError('Failed to start the protocol run', err, {
                    context: 'Protocol run start failed',
                });
            }
        });
        runLauncher.appendChild(startRunButton);
        runPanel.appendChild(runLauncher);

        const runList = document.createElement('div');
        runList.className = 'protocol-scroll';
        const runRows = _runRows();
        UI.reconcileChildren(
            runList,
            runRows.length ? runRows : [UI.renderEmptyState('No protocol runs match the current filter.', true)],
        );
        runPanel.appendChild(runList);

        const detailPanel = document.createElement('section');
        detailPanel.className = 'editor-panel protocol-panel protocol-panel-detail';

        const detailTitle = document.createElement('div');
        detailTitle.className = 'editor-section-title';
        detailTitle.textContent = 'Run detail';
        detailPanel.appendChild(detailTitle);

        if (!currentRun) {
            detailPanel.appendChild(UI.renderEmptyState('Select a run to inspect its state, timeline, artifacts, and operator actions.', true));
        } else {
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
            detailPanel.appendChild(summaryGrid);

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
            if (detailNotes.childNodes.length) {
                detailPanel.appendChild(detailNotes);
            }

            const runActionBar = document.createElement('div');
            runActionBar.className = 'editor-actions protocol-sticky-actions';
            [
                {
                    action: 'retry',
                    label: 'Retry',
                    note: 'Retry creates a new execution of the current stage using the same protocol definition and workspace context.',
                    confirmLabel: 'Retry run',
                    successMessage: 'Protocol run retry submitted.',
                    requireReason: false,
                    enabled: ['blocked', 'failed', 'cancelled'].includes(String(currentRun.run.status || '')),
                },
                {
                    action: 'accept',
                    label: 'Accept',
                    note: 'Accept forces the current review or acceptance stage forward using the reason you provide as audit context.',
                    confirmLabel: 'Accept run',
                    successMessage: 'Protocol run accepted.',
                    requireReason: false,
                    enabled: !['completed', 'failed', 'cancelled'].includes(String(currentRun.run.status || '')),
                },
                {
                    action: 'send-back',
                    label: 'Send back',
                    note: 'Send back forces a revise decision and requires a short reason that explains what needs to change.',
                    confirmLabel: 'Send back',
                    successMessage: 'Protocol run sent back.',
                    requireReason: true,
                    enabled: !['completed', 'failed', 'cancelled'].includes(String(currentRun.run.status || '')),
                },
                {
                    action: 'cancel',
                    label: 'Cancel',
                    note: 'Cancel is destructive for the current run lifecycle and requires a short audit reason.',
                    confirmLabel: 'Cancel run',
                    successMessage: 'Protocol run cancelled.',
                    requireReason: true,
                    enabled: !['completed', 'failed', 'cancelled'].includes(String(currentRun.run.status || '')),
                },
            ].forEach((spec) => {
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
            exportRunButton.addEventListener('click', () => {
                void _downloadRunExport();
            });
            runActionBar.appendChild(exportRunButton);

            const openButton = document.createElement('a');
            openButton.className = 'btn';
            openButton.href = _runDeepLink(currentRun.run);
            openButton.textContent = 'Open route';
            runActionBar.appendChild(openButton);
            detailPanel.appendChild(runActionBar);

            const { stageRows, transitionRows, participantOptions } = _filteredTimelineData();
            const participantControl = UI.createSegmentedControl(
                [{ value: '', label: 'All participants' }, ...participantOptions],
                (value) => {
                    timelineParticipantFilter = value || '';
                    renderWorkspace();
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
                sublabel: _artifactLabel(item),
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
            UI.reconcileChildren(issueDetailList, issueDetailRows.length ? issueDetailRows : [UI.renderEmptyState('No protocol issues detected for this run.', true)]);
            detailPanel.appendChild(issueDetailList);
        }

        UI.reconcileChildren(contentEl, [definitionPanel, editorPanel, runPanel, detailPanel]);
    }

    async function loadProtocols() {
        protocols = await API.listProtocols({ limit: 100 });
        if (currentProtocolId && !protocols.some((item) => item.protocol_id === currentProtocolId)) {
            currentProtocolId = protocols[0]?.protocol_id || '';
        }
        if (!currentProtocolId && protocols.length) {
            currentProtocolId = protocols[0].protocol_id;
        }
        _writeState();
    }

    async function loadRuns() {
        const response = await API.listProtocolRuns({ limit: 50 });
        runs = response.runs || response || [];
        if (currentRunId && !runs.some((item) => item.protocol_run_id === currentRunId)) {
            currentRunId = '';
            currentRun = null;
            currentIssues = [];
        }
    }

    async function loadIssues({ rerender = true } = {}) {
        const response = await API.listProtocolIssues({
            limit: 50,
            issue_kind: issueKindFilter,
        });
        protocolIssues = response.issues || response || [];
        const nextSignature = UI.dataSignature({
            issue_kind: issueKindFilter,
            issues: protocolIssues,
        });
        const issuesChanged = nextSignature !== protocolIssueSignature;
        protocolIssueSignature = nextSignature;
        if (rerender && issuesChanged) {
            renderWorkspace();
        }
    }

    async function loadDefaultTemplate() {
        defaultTemplate = await API.getProtocolTemplate('software-engineering');
    }

    async function loadAgents({ rerender = false } = {}) {
        const response = await API.listAgents({ limit: 100 });
        const nextAgents = response.agents || response || [];
        const nextSignature = UI.dataSignature(nextAgents);
        const previousSelection = runLauncherEntryAgentId;
        agents = nextAgents;
        const requestedEntryAgentId = UI.readQueryParam('entry_agent_id', '');
        if (requestedEntryAgentId) {
            runLauncherEntryAgentId = requestedEntryAgentId;
        }
        _reconcileRunLauncherSelection();
        const agentListChanged = nextSignature !== agentListSignature;
        const selectionChanged = previousSelection !== runLauncherEntryAgentId;
        agentListSignature = nextSignature;
        if (rerender && (agentListChanged || selectionChanged)) {
            renderWorkspace();
        }
    }

    async function loadProtocolDetail() {
        if (!currentProtocolId) {
            currentProtocol = null;
            _clearStructuredDrafts();
            if (!draft.definition_text) {
                draft = {
                    protocol_id: '',
                    slug: '',
                    display_name: '',
                    description: '',
                    definition_text: '',
                    document_json: null,
                    parse_error: '',
                };
            }
            await _refreshDraftTextForCurrentFormat();
            _writeState();
            renderWorkspace();
            return;
        }
        currentProtocol = await API.getProtocol(currentProtocolId);
        _applyDraftFromProtocol(currentProtocol);
        await _refreshDraftTextForCurrentFormat();
        _writeState();
        renderWorkspace();
    }

    async function loadRunDetail({ soft = false } = {}) {
        if (!currentRunId) {
            currentRun = null;
            currentIssues = [];
            lastRunEvent = null;
            _writeState();
            _bindRunSubscription();
            renderWorkspace();
            return;
        }
        try {
            const [runDetail, issues] = await Promise.all([
                API.getProtocolRun(currentRunId),
                API.listProtocolIssues({ protocol_run_id: currentRunId, limit: 50 }),
            ]);
            currentRun = runDetail;
            currentIssues = issues.issues || issues || [];
            _writeState();
            _bindRunSubscription();
            renderWorkspace();
        } catch (err) {
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
        UI.reconcileChildren(contentEl, [UI.renderEmptyState('Loading protocols…', true)]);
        try {
            await Promise.all([loadProtocols(), loadRuns(), loadAgents(), loadDefaultTemplate()]);
            await loadIssues({ rerender: false });
            if (currentProtocolId) {
                await loadProtocolDetail();
            } else {
                await _refreshDraftTextForCurrentFormat();
                renderWorkspace();
            }
            if (currentRunId) {
                await loadRunDetail();
            }
        } catch (err) {
            UI.reconcileChildren(contentEl, [UI.createErrorCard('Failed to load protocols: ' + err.message, bootstrap)]);
        }
    }

    async function refreshWorkspace() {
        await Promise.all([
            loadProtocols(),
            loadRuns(),
            loadIssues({ rerender: false }),
            loadAgents(),
        ]);
        if (currentProtocolId) {
            await loadProtocolDetail();
        } else {
            await _refreshDraftTextForCurrentFormat();
            renderWorkspace();
        }
        if (currentRunId) {
            await loadRunDetail({ soft: true });
        }
    }

    cleanups.add(() => {
        if (currentRunSubscription) {
            currentRunSubscription();
            currentRunSubscription = null;
        }
        currentProtocol = null;
        currentRun = null;
        currentIssues = [];
        protocolIssues = [];
    });

    UI.subscribeWithRefresh(cleanups, 'protocols', () => refreshWorkspace(), 350);
    UI.subscribeWithRefresh(cleanups, 'summary', () => loadIssues({ rerender: true }), 400);
    UI.subscribeWithRefresh(cleanups, 'agents', () => loadAgents({ rerender: true }), 600);

    container.__routeReady = bootstrap();
}
