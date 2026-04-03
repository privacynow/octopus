/**
 * Provider guidance editor — provider baseline policy with draft, published, and runtime preview views.
 */
function renderGuidanceEditor(container) {
    const cleanups = UI.beginCleanupScope();
    const GUIDANCE_CACHE_TTL_MS = 60000;
    const CACHE_ERROR_TTL_MS = 5000;

    function renderLoadingState(message = 'Loading guidance…') {
        UI.clearMemoizedRender(contentEl);
        UI.reconcileChildren(contentEl, [UI.renderEmptyState(message, true)]);
    }

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Guidance</h2><p>Baseline provider policy for this bot. Published guidance applies to every run for that provider; drafts stay local until you publish.</p>';
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
    let currentPreview = null;
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

    function _providerLabel(provider = currentProvider) {
        return providers.find(([value]) => value === provider)?.[1] || provider;
    }

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

    function _guidanceCacheKey(agentId = currentAgentId, provider = currentProvider) {
        return `guidance:${String(agentId || '').trim()}:${String(provider || '').trim()}:system:`;
    }

    function _invalidateGuidanceCache(agentId = currentAgentId, provider = currentProvider) {
        const normalizedAgentId = String(agentId || '').trim();
        const normalizedProvider = String(provider || '').trim();
        if (!normalizedAgentId || !normalizedProvider) return;
        UI.invalidateCachedData(_guidanceCacheKey(normalizedAgentId, normalizedProvider));
    }

    function _renderPolicyPanel(titleText, bodyText, emptyText, key) {
        const panel = document.createElement('section');
        panel.className = 'editor-panel';
        panel.dataset.key = key;

        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = titleText;
        panel.appendChild(title);

        const trimmed = String(bodyText || '').trim();
        if (!trimmed) {
            panel.appendChild(UI.renderEmptyState(emptyText, true));
            return panel;
        }

        const pre = document.createElement('pre');
        pre.className = 'event-pre';
        pre.style.whiteSpace = 'pre-wrap';
        pre.textContent = trimmed;
        panel.appendChild(pre);
        return panel;
    }

    function _guidanceStatus(currentGuidance) {
        return String(currentGuidance.status || currentGuidance.lifecycle_status || 'draft').replace(/_/g, ' ');
    }

    async function _runGuidanceMutation(button, actionLabel, op) {
        button.disabled = true;
        try {
            await op();
            _invalidateGuidanceCache();
            currentPreview = null;
            await loadGuidance({ soft: true });
        } catch (err) {
            UI.reportError(`Failed to ${actionLabel.toLowerCase()} the guidance`, err, {
                context: `Guidance ${actionLabel.toLowerCase()} failed`,
            });
            button.disabled = false;
        }
    }

    async function loadGuidance({ soft = false } = {}) {
        if (!currentAgentId) {
            UI.clearMemoizedRender(contentEl);
            UI.reconcileChildren(contentEl, [
                UI.renderEmptyState('No connected bot advertises provider guidance management.', true),
            ]);
            return;
        }
        currentPreview = null;
        const hadVisibleState = contentEl.childElementCount > 0;
        const cachedGuidance = UI.peekCachedData(_guidanceCacheKey());
        const hasCachedView = Boolean(cachedGuidance);
        if (cachedGuidance) {
            renderGuidanceContent(cachedGuidance.guidance || cachedGuidance, currentPreview);
        } else if (!soft) {
            renderLoadingState('Loading guidance…');
        }
        try {
            const data = await UI.loadCachedData(
                _guidanceCacheKey(),
                () => API.getGuidance(currentAgentId, currentProvider),
                {
                    ttlMs: GUIDANCE_CACHE_TTL_MS,
                    errorTtlMs: CACHE_ERROR_TTL_MS,
                    forceRefresh: hasCachedView,
                },
            );
            renderGuidanceContent(data.guidance || data, currentPreview);
        } catch (err) {
            if (hasCachedView || hadVisibleState) {
                UI.reportError('Failed to refresh guidance', err, { context: 'Guidance refresh failed' });
                return;
            }
            UI.clearMemoizedRender(contentEl);
            UI.reconcileChildren(contentEl, [UI.createErrorCard('Failed to load guidance: ' + err.message, loadGuidance)]);
        }
    }

    async function loadAgents({ soft = false } = {}) {
        if (!soft) {
            agentSelect.disabled = true;
        }
        try {
            const previousAgentId = currentAgentId;
            const data = await API.listAgents({ limit: 100 });
            availableAgents = Array.isArray(data) ? data : (data.agents || []);
            const requested = _readAgentId();
            if (requested) {
                currentAgentId = requested;
            }
            _renderAgentOptions();
            const agentChanged = previousAgentId !== currentAgentId;
            void loadGuidance({ soft: soft && !agentChanged });
        } catch (err) {
            UI.clearMemoizedRender(contentEl);
            UI.reconcileChildren(contentEl, [UI.createErrorCard('Failed to load managed bots: ' + err.message, loadAgents)]);
        }
    }

    function renderGuidanceContent(guidance, preview) {
        UI.memoizedRender(contentEl, {
            provider: currentProvider,
            agentId: currentAgentId,
            guidance,
            preview,
        }, (state) => {
            const nodes = [];
            const currentGuidance = state.guidance || {};
            const currentPreviewState = state.preview || null;
            const statusText = _guidanceStatus(currentGuidance);

            const statusPanel = document.createElement('section');
            statusPanel.className = 'editor-panel';
            statusPanel.dataset.key = 'guidance-status';

            const statusHead = document.createElement('div');
            statusHead.className = 'workspace-header-main';
            const titleWrap = document.createElement('div');
            titleWrap.className = 'workspace-title-group';
            const title = document.createElement('h3');
            title.className = 'editor-section-title';
            title.textContent = `${_providerLabel(state.provider)} guidance`;
            titleWrap.appendChild(title);
            statusHead.appendChild(titleWrap);
            const badge = document.createElement('span');
            badge.className = `badge badge-${String(currentGuidance.lifecycle_status || 'draft')}`;
            badge.textContent = statusText;
            statusHead.appendChild(badge);
            statusPanel.appendChild(statusHead);
            statusPanel.appendChild(UI.renderMetadataGrid([
                { label: 'Published policy', value: currentGuidance.published_body ? 'Live' : 'Not published' },
                { label: 'Published revision', value: currentGuidance.published_revision_id || '(none)' },
                { label: 'Draft revision', value: currentGuidance.active_revision_id || '(none)' },
                { label: 'Runtime behavior', value: `Applies to every ${_providerLabel(state.provider)} run on this bot` },
            ]));
            nodes.push(statusPanel);

            nodes.push(_renderPolicyPanel(
                'Published policy',
                currentGuidance.published_body || '',
                'Nothing is published for this provider yet.',
                'guidance-published',
            ));

            const draftPanel = document.createElement('section');
            draftPanel.className = 'editor-panel';
            draftPanel.dataset.key = 'guidance-editor';

            const draftTitle = document.createElement('div');
            draftTitle.className = 'editor-section-title';
            draftTitle.textContent = 'Draft policy';
            draftPanel.appendChild(draftTitle);

            const textarea = document.createElement('textarea');
            textarea.className = 'guidance-textarea';
            textarea.rows = 14;
            textarea.value = currentGuidance.draft_body || '';
            textarea.setAttribute('aria-label', 'Guidance draft');
            draftPanel.appendChild(textarea);

            const actions = document.createElement('div');
            actions.className = 'editor-actions';

            const saveBtn = document.createElement('button');
            saveBtn.className = 'btn btn-primary btn-sm';
            saveBtn.textContent = 'Save draft';
            saveBtn.addEventListener('click', async () => {
                saveBtn.disabled = true;
                try {
                    await API.updateGuidanceDraft(currentAgentId, currentProvider, { body: textarea.value });
                    _invalidateGuidanceCache();
                    currentPreview = null;
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
                    currentPreview = await API.previewGuidance(currentAgentId, currentProvider, {
                        use_draft: true,
                        body_override: textarea.value,
                    });
                    renderGuidanceContent(currentGuidance, currentPreview);
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
                await _runGuidanceMutation(submitBtn, 'Submit', () => API.submitGuidance(currentAgentId, currentProvider));
            });
            actions.appendChild(submitBtn);

            const approveBtn = document.createElement('button');
            approveBtn.className = 'btn btn-sm';
            approveBtn.textContent = 'Approve';
            approveBtn.addEventListener('click', async () => {
                await _runGuidanceMutation(approveBtn, 'Approve', () => API.approveGuidance(currentAgentId, currentProvider));
            });
            actions.appendChild(approveBtn);

            const rejectBtn = document.createElement('button');
            rejectBtn.className = 'btn btn-sm';
            rejectBtn.textContent = 'Reject';
            rejectBtn.addEventListener('click', async () => {
                await _runGuidanceMutation(rejectBtn, 'Reject', () => API.rejectGuidance(currentAgentId, currentProvider));
            });
            actions.appendChild(rejectBtn);

            const publishBtn = document.createElement('button');
            publishBtn.className = 'btn btn-sm btn-primary';
            publishBtn.textContent = 'Publish';
            publishBtn.addEventListener('click', async () => {
                UI.showConfirm(
                    'Publish guidance',
                    'Publish this provider policy for future runs on this bot?',
                    async () => {
                        await _runGuidanceMutation(publishBtn, 'Publish', () => API.publishGuidance(currentAgentId, currentProvider));
                    },
                );
            });
            actions.appendChild(publishBtn);

            const archiveBtn = document.createElement('button');
            archiveBtn.className = 'btn btn-sm';
            archiveBtn.textContent = 'Archive';
            archiveBtn.addEventListener('click', async () => {
                await _runGuidanceMutation(archiveBtn, 'Archive', () => API.archiveGuidance(currentAgentId, currentProvider));
            });
            actions.appendChild(archiveBtn);

            draftPanel.appendChild(actions);
            nodes.push(draftPanel);

            const previewPanel = document.createElement('section');
            previewPanel.className = 'editor-panel';
            previewPanel.dataset.key = 'guidance-preview';

            const previewTitle = document.createElement('div');
            previewTitle.className = 'editor-section-title';
            previewTitle.textContent = 'Runtime preview';
            previewPanel.appendChild(previewTitle);

            if (currentPreviewState) {
                previewPanel.appendChild(UI.renderMetadataGrid([
                    {
                        label: 'Preview source',
                        value: currentPreviewState.preview_source === 'draft' ? 'Current draft' : 'Published policy',
                    },
                    { label: 'Prompt weight', value: String(currentPreviewState.prompt_weight || 0) },
                ]));
                const previewBody = document.createElement('pre');
                previewBody.className = 'event-pre';
                previewBody.style.whiteSpace = 'pre-wrap';
                previewBody.textContent = String(currentPreviewState.composed_prompt || '').trim() || '(empty prompt)';
                previewPanel.appendChild(previewBody);
            } else {
                previewPanel.appendChild(
                    UI.renderEmptyState(
                        'Preview the current draft to see the composed provider prompt before publishing.',
                        true,
                    ),
                );
            }
            nodes.push(previewPanel);
            return nodes;
        }, {
            signatureFn(state) {
                const currentGuidance = state.guidance || {};
                const currentPreviewState = state.preview || {};
                return {
                    provider: String(state.provider || ''),
                    agentId: String(state.agentId || ''),
                    status: String(currentGuidance.lifecycle_status || 'draft'),
                    draft: String(currentGuidance.draft_body || ''),
                    published: String(currentGuidance.published_body || ''),
                    previewSource: String(currentPreviewState.preview_source || ''),
                    previewPrompt: String(currentPreviewState.composed_prompt || ''),
                };
            },
        });
    }

    container.__routeReady = loadAgents();
    providerControl.setActive(currentProvider);
    UI.subscribeWithRefresh(cleanups, 'agents', () => loadAgents({ soft: true }), 600);
}
