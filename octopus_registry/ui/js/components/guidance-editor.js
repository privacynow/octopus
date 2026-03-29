/**
 * Provider guidance editor — compact provider-scoped draft and publish workflow.
 */
function renderGuidanceEditor(container) {
    const cleanups = UI.beginCleanupScope();
    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Guidance</h2>';
    container.appendChild(header);

    const shell = document.createElement('section');
    shell.className = 'admin-shell';
    container.appendChild(shell);

    const providerPanel = document.createElement('section');
    providerPanel.className = 'workbench-panel';
    shell.appendChild(providerPanel);

    const agentBar = document.createElement('div');
    agentBar.className = 'route-controls';
    providerPanel.appendChild(agentBar);

    const agentDropdown = UI.createAgentManagementDropdown([], '', (nextAgentId) => {
        currentAgentId = nextAgentId;
        _writeAgentId(currentAgentId);
        loadGuidance();
    });
    const agentSelect = agentDropdown.element;
    agentBar.appendChild(agentSelect);

    const contentEl = document.createElement('div');
    contentEl.className = 'editor-shell';
    shell.appendChild(contentEl);

    let currentProvider = 'claude';
    let currentAgentId = '';
    let availableAgents = [];
    const providers = [
        ['claude', 'Claude'],
        ['codex', 'Codex'],
    ];
    const providerControl = UI.createSegmentedControl(
        providers.map(([value, label]) => ({ key: value, value, label })),
        (provider) => {
            currentProvider = provider;
            loadGuidance();
        },
        {
            label: 'Guidance provider',
            value: currentProvider,
        },
    );
    const providerBar = providerControl.element;
    providerPanel.appendChild(providerBar);

    function _readAgentId() {
        try {
            return new URL(window.location.href).searchParams.get('agent_id') || '';
        } catch {
            return '';
        }
    }

    function _writeAgentId(agentId) {
        try {
            const url = new URL(window.location.href);
            if (agentId) {
                url.searchParams.set('agent_id', agentId);
            } else {
                url.searchParams.delete('agent_id');
            }
            history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
        } catch {
            // Ignore URL update failures.
        }
    }

    function _managementAgents(capability) {
        return availableAgents.filter((agent) => {
            const connectivity = String(agent.connectivity_state || '').trim();
            const capabilities = Array.isArray(agent.management_capabilities)
                ? agent.management_capabilities
                : [];
            return ['connected', 'degraded'].includes(connectivity) && capabilities.includes(capability);
        });
    }

    function _renderAgentOptions() {
        const agents = _managementAgents('provider_guidance');
        if (!agents.length) {
            currentAgentId = '';
            agentDropdown.update([], '');
            return;
        }
        if (!agents.some((agent) => agent.agent_id === currentAgentId)) {
            currentAgentId = agents[0].agent_id || '';
            _writeAgentId(currentAgentId);
        }
        agentDropdown.update(agents, currentAgentId);
    }

    async function loadGuidance() {
        if (!currentAgentId) {
            UI.clearMemoizedRender(contentEl);
            UI.reconcileChildren(contentEl, [
                UI.renderEmptyState('No connected bot advertises provider guidance management.', true),
            ]);
            return;
        }
        try {
            const data = await API.getGuidance(currentAgentId, currentProvider);
            renderGuidanceContent(data.guidance || data);
        } catch (err) {
            UI.clearMemoizedRender(contentEl);
            UI.reconcileChildren(contentEl, [UI.createErrorCard('Failed to load guidance: ' + err.message, loadGuidance)]);
        }
    }

    async function loadAgents({ soft = false } = {}) {
        if (!soft) {
            agentSelect.disabled = true;
        }
        try {
            const data = await API.listAgents({ limit: 200 });
            availableAgents = Array.isArray(data) ? data : (data.agents || []);
            const requested = _readAgentId();
            if (requested) {
                currentAgentId = requested;
            }
            _renderAgentOptions();
            await loadGuidance();
        } catch (err) {
            UI.clearMemoizedRender(contentEl);
            UI.reconcileChildren(contentEl, [UI.createErrorCard('Failed to load managed bots: ' + err.message, loadAgents)]);
        }
    }

    function renderGuidanceContent(guidance) {
        UI.memoizedRender(contentEl, {
            provider: currentProvider,
            agentId: currentAgentId,
            guidance,
        }, (state) => {
        const nodes = [];
        const currentGuidance = state.guidance || {};

        const statusPanel = document.createElement('section');
        statusPanel.className = 'editor-panel';
        statusPanel.dataset.key = 'guidance-status';

        const statusHead = document.createElement('div');
        statusHead.className = 'workspace-header-main';
        const titleWrap = document.createElement('div');
        titleWrap.className = 'workspace-title-group';
        const title = document.createElement('h3');
        title.className = 'editor-section-title';
        title.textContent = `${providers.find(([value]) => value === currentProvider)?.[1] || currentProvider} guidance`;
        titleWrap.appendChild(title);
        statusHead.appendChild(titleWrap);
        const badge = document.createElement('span');
        badge.className = `badge badge-${currentGuidance.status || currentGuidance.lifecycle_status || 'draft'}`;
        badge.textContent = String(currentGuidance.status || currentGuidance.lifecycle_status || 'draft').replace(/_/g, ' ');
        statusHead.appendChild(badge);
        statusPanel.appendChild(statusHead);
        nodes.push(statusPanel);

        const editorPanel = document.createElement('section');
        editorPanel.className = 'editor-panel';
        editorPanel.dataset.key = 'guidance-editor';

        const editorTitle = document.createElement('div');
        editorTitle.className = 'editor-section-title';
        editorTitle.textContent = 'System prompt draft';
        editorPanel.appendChild(editorTitle);

        const textarea = document.createElement('textarea');
        textarea.className = 'guidance-textarea';
        textarea.rows = 14;
        textarea.value = currentGuidance.draft_body || currentGuidance.instruction_body || currentGuidance.body || '';
        textarea.setAttribute('aria-label', 'Guidance draft');
        editorPanel.appendChild(textarea);

        const actions = document.createElement('div');
        actions.className = 'editor-actions';

        const saveBtn = document.createElement('button');
        saveBtn.className = 'btn btn-primary btn-sm';
        saveBtn.textContent = 'Save draft';
        saveBtn.addEventListener('click', async () => {
            saveBtn.disabled = true;
            try {
                await API.updateGuidanceDraft(currentAgentId, currentProvider, { body: textarea.value });
                saveBtn.textContent = 'Saved';
                setTimeout(() => { saveBtn.textContent = 'Save draft'; }, 1600);
            } catch (err) {
                UI.reportError('Failed to save the guidance draft', err, { context: 'Guidance save draft failed' });
            }
            saveBtn.disabled = false;
        });
        actions.appendChild(saveBtn);

        const previewBtn = document.createElement('button');
        previewBtn.className = 'btn btn-sm';
        previewBtn.textContent = 'Preview';
        previewBtn.addEventListener('click', async () => {
            previewBtn.disabled = true;
            try {
                const result = await API.previewGuidance(currentAgentId, currentProvider);
                const previewText = result.preview || result.system_prompt || JSON.stringify(result, null, 2);
                showPreview(previewText);
            } catch (err) {
                UI.reportError('Failed to preview the guidance', err, { context: 'Guidance preview failed' });
            }
            previewBtn.disabled = false;
        });
        actions.appendChild(previewBtn);

        const submitBtn = document.createElement('button');
        submitBtn.className = 'btn btn-sm';
        submitBtn.textContent = 'Submit';
        submitBtn.addEventListener('click', async () => {
            submitBtn.disabled = true;
            try {
                await API.submitGuidance(currentAgentId, currentProvider);
                loadGuidance();
            } catch (err) {
                UI.reportError('Failed to submit the guidance', err, { context: 'Guidance submit failed' });
                submitBtn.disabled = false;
            }
        });
        actions.appendChild(submitBtn);

        const publishBtn = document.createElement('button');
        publishBtn.className = 'btn btn-sm btn-primary';
        publishBtn.textContent = 'Publish';
        publishBtn.addEventListener('click', async () => {
            UI.showConfirm('Publish guidance', 'Publish this guidance to active conversations?', async () => {
                publishBtn.disabled = true;
                try {
                    await API.publishGuidance(currentAgentId, currentProvider);
                    loadGuidance();
                } catch (err) {
                    UI.reportError('Failed to publish the guidance', err, { context: 'Guidance publish failed' });
                    publishBtn.disabled = false;
                }
            });
        });
        actions.appendChild(publishBtn);

        editorPanel.appendChild(actions);
        nodes.push(editorPanel);
        return nodes;
        }, {
            signatureFn(state) {
                const currentGuidance = state.guidance || {};
                return {
                    provider: String(state.provider || ''),
                    agentId: String(state.agentId || ''),
                    status: String(currentGuidance.status || currentGuidance.lifecycle_status || 'draft'),
                    draft: String(currentGuidance.draft_body || currentGuidance.instruction_body || currentGuidance.body || ''),
                };
            },
        });
    }

    function showPreview(text) {
        const overlay = document.createElement('div');
        overlay.className = 'confirm-overlay';

        const dialog = document.createElement('div');
        dialog.className = 'confirm-dialog';
        dialog.style.maxWidth = '720px';
        dialog.style.maxHeight = '80vh';
        dialog.style.overflow = 'auto';

        const h3 = document.createElement('h3');
        h3.textContent = 'Guidance preview';
        dialog.appendChild(h3);

        const pre = document.createElement('pre');
        pre.className = 'event-pre';
        pre.style.whiteSpace = 'pre-wrap';
        pre.textContent = text;
        dialog.appendChild(pre);

        const closeBtn = document.createElement('button');
        closeBtn.className = 'btn';
        closeBtn.textContent = 'Close';
        closeBtn.addEventListener('click', () => overlay.remove());
        dialog.appendChild(closeBtn);

        overlay.appendChild(dialog);
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) overlay.remove();
        });
        document.body.appendChild(overlay);
    }

    container.__routeReady = loadAgents();
    providerControl.setActive(currentProvider);
    UI.subscribeWithRefresh(cleanups, 'agents', () => loadAgents({ soft: true }), 600);
}
