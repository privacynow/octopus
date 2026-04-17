function renderProtocolWorkspace(container) {
    const cleanups = UI.beginCleanupScope();
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }

    let protocols = [];
    let runs = [];
    let agents = [];
    let currentProtocolId = UI.readQueryParam('protocol_id', '');
    let currentRunId = UI.readQueryParam('run_id', '');
    let currentProtocol = null;
    let currentRun = null;
    let defaultTemplate = null;
    let draft = {
        protocol_id: '',
        slug: '',
        display_name: '',
        description: '',
        definition_text: '',
    };

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Protocols</h2><p>Define reusable multi-stage workflows, publish versioned protocol definitions, and launch protocol runs against a bot workspace.</p>';
    container.appendChild(header);

    const shell = document.createElement('section');
    shell.className = 'admin-shell';
    container.appendChild(shell);

    const contentEl = document.createElement('div');
    contentEl.className = 'editor-shell';
    shell.appendChild(contentEl);

    function _writeState() {
        UI.updateQueryParams({
            protocol_id: currentProtocolId || '',
            run_id: currentRunId || '',
        });
    }

    function _defaultProtocolDocument() {
        return defaultTemplate || {
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

    function _applyDraftFromProtocol(detail) {
        const rawDraftDocument = detail && detail.draft_definition_json
            && Object.keys(detail.draft_definition_json).length
            ? detail.draft_definition_json
            : null;
        const draftDocument = rawDraftDocument || (detail && detail.draft_document)
            || _defaultProtocolDocument();
        draft = {
            protocol_id: detail?.protocol?.protocol_id || '',
            slug: detail?.protocol?.slug || draftDocument.metadata?.slug || '',
            display_name: detail?.protocol?.display_name || draftDocument.metadata?.display_name || '',
            description: detail?.protocol?.description || draftDocument.metadata?.description || '',
            definition_text: JSON.stringify(draftDocument, null, 2),
        };
    }

    function _protocolRows() {
        return protocols.map((item) => UI.renderListRow({
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
        return runs.map((item) => UI.renderListRow({
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

    function _managedAgents() {
        return (agents || []).filter((item) => ['connected', 'degraded'].includes(String(item.connectivity_state || '')));
    }

    function renderWorkspace() {
        const leftPanel = document.createElement('section');
        leftPanel.className = 'editor-panel';

        const leftTitle = document.createElement('div');
        leftTitle.className = 'editor-section-title';
        leftTitle.textContent = 'Definitions';
        leftPanel.appendChild(leftTitle);

        const leftActions = document.createElement('div');
        leftActions.className = 'editor-actions';
        const newButton = document.createElement('button');
        newButton.type = 'button';
        newButton.className = 'btn btn-primary';
        newButton.textContent = 'New protocol';
        newButton.addEventListener('click', async () => {
            try {
                if (!defaultTemplate) {
                    defaultTemplate = await API.getProtocolTemplate('software-engineering');
                }
            } catch (err) {
                UI.reportError('Failed to load the protocol template', err, {
                    context: 'Protocol template load failed',
                });
                return;
            }
            currentProtocolId = '';
            currentProtocol = null;
            currentRunId = '';
            currentRun = null;
            _applyDraftFromProtocol(null);
            _writeState();
            renderWorkspace();
        });
        leftActions.appendChild(newButton);
        leftPanel.appendChild(leftActions);

        const listWrap = document.createElement('div');
        if (protocols.length) {
            UI.reconcileChildren(listWrap, _protocolRows());
        } else {
            listWrap.appendChild(UI.renderEmptyState('No protocols yet. Start with the software engineering template.', true));
        }
        leftPanel.appendChild(listWrap);

        const runTitle = document.createElement('div');
        runTitle.className = 'editor-section-title';
        runTitle.textContent = 'Recent runs';
        leftPanel.appendChild(runTitle);

        const runWrap = document.createElement('div');
        if (runs.length) {
            UI.reconcileChildren(runWrap, _runRows());
        } else {
            runWrap.appendChild(UI.renderEmptyState('No protocol runs yet.', true));
        }
        leftPanel.appendChild(runWrap);

        const detailPanel = document.createElement('section');
        detailPanel.className = 'editor-panel';

        const detailTitle = document.createElement('div');
        detailTitle.className = 'editor-section-title';
        detailTitle.textContent = currentProtocolId ? 'Protocol detail' : 'New protocol';
        detailPanel.appendChild(detailTitle);

        const slugInput = document.createElement('input');
        slugInput.className = 'search-input';
        slugInput.placeholder = 'protocol-slug';
        slugInput.value = draft.slug || '';
        slugInput.addEventListener('input', () => {
            draft.slug = slugInput.value;
        });
        detailPanel.appendChild(UI.renderSettingsRow({ label: 'Slug', control: slugInput }));

        const nameInput = document.createElement('input');
        nameInput.className = 'search-input';
        nameInput.placeholder = 'Display name';
        nameInput.value = draft.display_name || '';
        nameInput.addEventListener('input', () => {
            draft.display_name = nameInput.value;
        });
        detailPanel.appendChild(UI.renderSettingsRow({ label: 'Display name', control: nameInput }));

        const descriptionInput = document.createElement('input');
        descriptionInput.className = 'search-input';
        descriptionInput.placeholder = 'Description';
        descriptionInput.value = draft.description || '';
        descriptionInput.addEventListener('input', () => {
            draft.description = descriptionInput.value;
        });
        detailPanel.appendChild(UI.renderSettingsRow({ label: 'Description', control: descriptionInput }));

        const definitionLabel = document.createElement('div');
        definitionLabel.className = 'editor-section-title';
        definitionLabel.textContent = 'Definition JSON';
        detailPanel.appendChild(definitionLabel);

        const definitionInput = document.createElement('textarea');
        definitionInput.className = 'guidance-textarea';
        definitionInput.value = draft.definition_text || JSON.stringify(_defaultProtocolDocument(), null, 2);
        definitionInput.addEventListener('input', () => {
            draft.definition_text = definitionInput.value;
        });
        detailPanel.appendChild(definitionInput);

        if (currentProtocol?.validation) {
            const validation = currentProtocol.validation;
            const note = document.createElement('div');
            note.className = 'quiet-note';
            if (validation.ok) {
                note.textContent = `Draft valid. Content hash: ${validation.content_hash || 'n/a'}`;
            } else {
                note.textContent = validation.errors.join(' · ') || 'Draft invalid.';
            }
            detailPanel.appendChild(note);
        }

        const actions = document.createElement('div');
        actions.className = 'editor-actions';

        const saveButton = document.createElement('button');
        saveButton.type = 'button';
        saveButton.className = 'btn btn-primary';
        saveButton.textContent = currentProtocolId ? 'Save draft' : 'Create protocol';
        saveButton.addEventListener('click', async () => {
            let parsed;
            try {
                parsed = JSON.parse(draft.definition_text || '{}');
            } catch (err) {
                UI.reportError('Protocol definition must be valid JSON before saving', err, {
                    context: 'Protocol draft JSON parse failed',
                });
                return;
            }
            try {
                const result = currentProtocolId
                    ? await API.saveProtocolDraft(currentProtocolId, {
                        slug: draft.slug,
                        display_name: draft.display_name,
                        description: draft.description,
                        definition_json: parsed,
                    })
                    : await API.createProtocol({
                        slug: draft.slug,
                        display_name: draft.display_name,
                        description: draft.description,
                        definition_json: parsed,
                    });
                currentProtocolId = result.protocol?.protocol_id || currentProtocolId;
                currentProtocol = result;
                _applyDraftFromProtocol(result);
                await loadProtocols();
                await loadProtocolDetail();
                UI.notify('Protocol draft saved.', 'success');
            } catch (err) {
                UI.reportError('Failed to save the protocol draft', err, {
                    context: 'Protocol save failed',
                });
            }
        });
        actions.appendChild(saveButton);

        if (currentProtocolId) {
            const validateButton = document.createElement('button');
            validateButton.type = 'button';
            validateButton.className = 'btn';
            validateButton.textContent = 'Validate';
            validateButton.addEventListener('click', async () => {
                try {
                    currentProtocol = await API.validateProtocol(currentProtocolId);
                    _applyDraftFromProtocol(currentProtocol);
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
            actions.appendChild(validateButton);

            const publishButton = document.createElement('button');
            publishButton.type = 'button';
            publishButton.className = 'btn';
            publishButton.textContent = 'Publish';
            publishButton.addEventListener('click', async () => {
                try {
                    currentProtocol = await API.publishProtocol(currentProtocolId);
                    _applyDraftFromProtocol(currentProtocol);
                    await loadProtocols();
                    renderWorkspace();
                    UI.notify('Protocol published.', 'success');
                } catch (err) {
                    UI.reportError('Failed to publish the protocol', err, {
                        context: 'Protocol publish failed',
                    });
                }
            });
            actions.appendChild(publishButton);
        }

        detailPanel.appendChild(actions);

        const runPanel = document.createElement('section');
        runPanel.className = 'editor-panel';

        const runTitleLabel = document.createElement('div');
        runTitleLabel.className = 'editor-section-title';
        runTitleLabel.textContent = 'Run protocol';
        runPanel.appendChild(runTitleLabel);

        const runNote = document.createElement('div');
        runNote.className = 'quiet-note';
        runNote.textContent = 'Only published protocol versions can start runs.';
        runPanel.appendChild(runNote);

        const agentDropdown = UI.createAgentManagementDropdown(
            _managedAgents(),
            _managedAgents()[0]?.agent_id || '',
            () => {},
            { label: 'Target bot' },
        );
        runPanel.appendChild(UI.renderSettingsRow({ label: 'Target bot', control: agentDropdown.element }));

        const workspaceInput = document.createElement('input');
        workspaceInput.className = 'search-input';
        workspaceInput.placeholder = 'Project name or workspace id';
        runPanel.appendChild(UI.renderSettingsRow({ label: 'Workspace', control: workspaceInput }));

        const problemInput = document.createElement('textarea');
        problemInput.className = 'guidance-textarea';
        problemInput.rows = 8;
        problemInput.placeholder = 'Problem statement';
        runPanel.appendChild(problemInput);

        const startRunButton = document.createElement('button');
        startRunButton.type = 'button';
        startRunButton.className = 'btn btn-primary';
        startRunButton.textContent = 'Start run';
        const runnableProtocol = Boolean(
            currentProtocolId
            && currentProtocol?.protocol?.lifecycle_state === 'published'
            && currentProtocol?.version?.protocol_definition_version_id
        );
        startRunButton.disabled = !runnableProtocol;
        startRunButton.addEventListener('click', async () => {
            if (!runnableProtocol) {
                UI.notify('Publish the protocol before starting a run.', 'warning');
                return;
            }
            try {
                const result = await API.createProtocolRun({
                    protocol_id: currentProtocolId,
                    entry_agent_id: agentDropdown.element.value,
                    origin_channel: 'registry',
                    workspace_ref: workspaceInput.value,
                    problem_statement: problemInput.value,
                    constraints_json: {},
                });
                currentRunId = result.run?.protocol_run_id || '';
                await loadRuns();
                await loadRunDetail();
                UI.notify('Protocol run started.', 'success');
            } catch (err) {
                UI.reportError('Failed to start the protocol run', err, {
                    context: 'Protocol run start failed',
                });
            }
        });
        runPanel.appendChild(startRunButton);

        const runDetailPanel = document.createElement('section');
        runDetailPanel.className = 'editor-panel';

        const runDetailTitle = document.createElement('div');
        runDetailTitle.className = 'editor-section-title';
        runDetailTitle.textContent = 'Run detail';
        runDetailPanel.appendChild(runDetailTitle);

        if (!currentRun) {
            runDetailPanel.appendChild(UI.renderEmptyState('Select a run to inspect its stages and transitions.', true));
        } else {
            const summary = document.createElement('div');
            summary.className = 'quiet-note';
            summary.textContent = `Status: ${currentRun.run.status} · Version: ${currentRun.run.version || 1} · Current stage: ${currentRun.run.current_stage_key || 'n/a'} · Workspace: ${currentRun.run.workspace_ref || 'default'}`;
            runDetailPanel.appendChild(summary);

            if (currentRun.run.termination_summary || currentRun.run.blocked_detail) {
                const outcomeNote = document.createElement('div');
                outcomeNote.className = 'quiet-note';
                outcomeNote.textContent = currentRun.run.termination_summary || currentRun.run.blocked_detail;
                runDetailPanel.appendChild(outcomeNote);
            }

            const runActions = document.createElement('div');
            runActions.className = 'editor-actions';
            const actionSpecs = [
                { action: 'cancel', label: 'Cancel', enabled: !['completed', 'failed', 'cancelled'].includes(String(currentRun.run.status || '')) },
                { action: 'retry', label: 'Retry', enabled: ['blocked', 'failed', 'cancelled'].includes(String(currentRun.run.status || '')) },
                { action: 'accept', label: 'Accept', enabled: !['completed', 'failed', 'cancelled'].includes(String(currentRun.run.status || '')) },
                { action: 'send-back', label: 'Send back', enabled: !['completed', 'failed', 'cancelled'].includes(String(currentRun.run.status || '')) },
            ];
            actionSpecs.forEach((spec) => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = spec.action === 'cancel' ? 'btn' : 'btn btn-primary';
                btn.textContent = spec.label;
                btn.disabled = !spec.enabled;
                btn.addEventListener('click', async () => {
                    const reason = window.prompt(`${spec.label} reason`, '');
                    if (reason === null) {
                        return;
                    }
                    try {
                        await API.actOnProtocolRun(
                            currentRun.run.protocol_run_id,
                            spec.action,
                            { reason: reason.trim() },
                            { expectedVersion: currentRun.run.version || 1 },
                        );
                        await loadRuns();
                        await loadRunDetail();
                        UI.notify(`Protocol run ${spec.label.toLowerCase()} applied.`, 'success');
                    } catch (err) {
                        UI.reportError(`Failed to ${spec.label.toLowerCase()} the protocol run`, err, {
                            context: 'Protocol run action failed',
                        });
                    }
                });
                runActions.appendChild(btn);
            });
            runDetailPanel.appendChild(runActions);

            const stageList = document.createElement('div');
            const stageRows = (currentRun.stage_executions || []).map((item) => UI.renderListRow({
                label: `${item.stage_key} · ${item.status}`,
                sublabel: item.decision_summary || item.failure_detail || item.routed_task_id || '',
                badgeText: item.decision || '',
            }));
            UI.reconcileChildren(stageList, stageRows.length ? stageRows : [UI.renderEmptyState('No stage executions yet.', true)]);
            runDetailPanel.appendChild(stageList);

            const participantTitle = document.createElement('div');
            participantTitle.className = 'editor-section-title';
            participantTitle.textContent = 'Participants';
            runDetailPanel.appendChild(participantTitle);

            const participantList = document.createElement('div');
            const participantRows = (currentRun.participants || []).map((item) => UI.renderListRow({
                label: `${item.display_name || item.participant_key} · ${item.state || item.resolution_outcome || 'queued'}`,
                sublabel: item.resolution_reason || item.resolved_agent_id || item.session_key || '',
                badgeText: item.resolution_outcome || '',
            }));
            UI.reconcileChildren(participantList, participantRows.length ? participantRows : [UI.renderEmptyState('No participants resolved yet.', true)]);
            runDetailPanel.appendChild(participantList);

            const artifactTitle = document.createElement('div');
            artifactTitle.className = 'editor-section-title';
            artifactTitle.textContent = 'Artifacts';
            runDetailPanel.appendChild(artifactTitle);

            const artifactList = document.createElement('div');
            const artifactRows = (currentRun.artifacts || []).map((item) => UI.renderListRow({
                label: `${item.artifact_key} · ${item.verification_state || item.state || 'declared'}`,
                sublabel: item.workspace_path || item.location || '',
                badgeText: item.content_hash ? item.content_hash.slice(0, 8) : '',
            }));
            UI.reconcileChildren(artifactList, artifactRows.length ? artifactRows : [UI.renderEmptyState('No artifacts recorded yet.', true)]);
            runDetailPanel.appendChild(artifactList);

            const transitionTitle = document.createElement('div');
            transitionTitle.className = 'editor-section-title';
            transitionTitle.textContent = 'Transitions';
            runDetailPanel.appendChild(transitionTitle);

            const transitionList = document.createElement('div');
            const transitionRows = (currentRun.transitions || []).map((item) => UI.renderListRow({
                label: `${item.transition_kind} · ${item.decision || 'n/a'}`,
                sublabel: item.reason || item.actor_ref || '',
            }));
            UI.reconcileChildren(transitionList, transitionRows.length ? transitionRows : [UI.renderEmptyState('No transitions yet.', true)]);
            runDetailPanel.appendChild(transitionList);
        }

        UI.reconcileChildren(contentEl, [leftPanel, detailPanel, runPanel, runDetailPanel]);
    }

    async function loadProtocols() {
        protocols = await API.listProtocols({ limit: 100 });
        if (!currentProtocolId && protocols.length) {
            currentProtocolId = protocols[0].protocol_id;
        }
        _writeState();
    }

    async function loadRuns() {
        const response = await API.listProtocolRuns({ limit: 25 });
        runs = response.runs || response || [];
    }

    async function loadDefaultTemplate() {
        defaultTemplate = await API.getProtocolTemplate('software-engineering');
    }

    async function loadAgents() {
        const response = await API.listAgents({ limit: 100 });
        agents = response.agents || response || [];
    }

    async function loadProtocolDetail() {
        if (!currentProtocolId) {
            currentProtocol = null;
            _applyDraftFromProtocol(null);
            _writeState();
            renderWorkspace();
            return;
        }
        currentProtocol = await API.getProtocol(currentProtocolId);
        _applyDraftFromProtocol(currentProtocol);
        _writeState();
        renderWorkspace();
    }

    async function loadRunDetail() {
        if (!currentRunId) {
            currentRun = null;
            _writeState();
            renderWorkspace();
            return;
        }
        currentRun = await API.getProtocolRun(currentRunId);
        _writeState();
        renderWorkspace();
    }

    async function bootstrap() {
        UI.reconcileChildren(contentEl, [UI.renderEmptyState('Loading protocols…', true)]);
        try {
            await Promise.all([loadProtocols(), loadRuns(), loadAgents(), loadDefaultTemplate()]);
            if (currentProtocolId) {
                await loadProtocolDetail();
            } else {
                _applyDraftFromProtocol(null);
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
        await Promise.all([loadProtocols(), loadRuns()]);
        if (currentProtocolId) {
            await loadProtocolDetail();
        } else {
            _applyDraftFromProtocol(null);
            renderWorkspace();
        }
        if (currentRunId) {
            await loadRunDetail();
        }
    }

    cleanups.add(() => {
        currentProtocol = null;
        currentRun = null;
    });

    UI.subscribeWithRefresh(cleanups, 'protocols', () => refreshWorkspace(), 350);

    void bootstrap();
}
