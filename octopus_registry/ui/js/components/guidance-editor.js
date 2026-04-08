/**
 * Provider guidance editor — progressive provider policy workflow for drafts, review, and publish.
 */
function renderGuidanceEditor(container) {
    const cleanups = UI.beginCleanupScope();
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }
    const GUIDANCE_CACHE_TTL_MS = 60000;
    const CACHE_ERROR_TTL_MS = 5000;

    let currentProvider = 'claude';
    let currentAgentId = '';
    let currentGuidance = null;
    let currentPreview = null;
    let currentGuidanceTab = _readGuidanceTab();
    let availableAgents = [];
    let guidanceLoading = false;
    let guidanceDraftBody = '';
    let guidanceDirty = false;
    let guidanceStatus = 'idle';
    let guidanceStatusMessage = '';
    let guidanceSnapshotKey = '';

    const providers = [
        ['claude', 'Claude'],
        ['codex', 'Codex'],
    ];

    function renderLoadingState(message = 'Loading guidance…') {
        UI.clearMemoizedRender(contentEl);
        UI.reconcileChildren(contentEl, [UI.renderEmptyState(message, true)]);
    }

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Guidance</h2><p>Baseline provider policy for this bot. Published guidance applies to every run for that provider; drafts stay local until you review and publish.</p>';
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
        _runWithDraftGuard(async () => {
            currentAgentId = nextAgentId;
            currentPreview = null;
            guidanceLoading = false;
            _clearDraftState();
            _writeState();
            await loadGuidance();
        });
    });
    const agentSelect = agentDropdown.element;
    agentBar.appendChild(agentSelect);

    const providerControl = UI.createSegmentedControl(
        providers.map(([value, label]) => ({ key: value, value, label })),
        (provider) => {
            _runWithDraftGuard(async () => {
                currentProvider = provider;
                currentGuidanceTab = 'write';
                currentPreview = null;
                guidanceLoading = false;
                _clearDraftState();
                _writeState();
                await loadGuidance();
            });
        },
        {
            label: 'Guidance provider',
            value: currentProvider,
        },
    );
    providerPanel.appendChild(providerControl.element);

    const contentEl = document.createElement('div');
    contentEl.className = 'editor-shell';
    shell.appendChild(contentEl);

    function _providerLabel(provider = currentProvider) {
        return providers.find(([value]) => value === provider)?.[1] || provider;
    }

    function _readAgentId() {
        return UI.readQueryParam('agent_id', '');
    }

    function _readGuidanceTab() {
        const value = UI.readQueryParam('guidance_tab', 'write');
        return ['write', 'review', 'advanced'].includes(value) ? value : 'write';
    }

    function _writeState() {
        UI.updateQueryParams({
            agent_id: currentAgentId || '',
            guidance_tab: currentGuidanceTab || '',
        });
    }

    function _renderAgentOptions() {
        const agents = UI.filterManagedAgents(availableAgents, 'provider_guidance');
        if (!agents.length) {
            currentAgentId = '';
            agentDropdown.update([], '');
            _writeState();
            return;
        }
        if (!agents.some((agent) => agent.agent_id === currentAgentId)) {
            currentAgentId = agents[0].agent_id || '';
        }
        agentDropdown.update(agents, currentAgentId);
        _writeState();
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

    function _guidanceStatus(currentGuidanceState) {
        return String(currentGuidanceState?.lifecycle_status || 'draft').replace(/_/g, ' ');
    }

    function _guidanceSnapshot(currentGuidanceState) {
        return JSON.stringify({
            draft_body: String(currentGuidanceState?.draft_body || ''),
            published_body: String(currentGuidanceState?.published_body || ''),
            lifecycle_status: String(currentGuidanceState?.lifecycle_status || ''),
            active_revision_id: String(currentGuidanceState?.active_revision_id || ''),
            published_revision_id: String(currentGuidanceState?.published_revision_id || ''),
        });
    }

    function _resetDraftState(currentGuidanceState) {
        guidanceDraftBody = String(currentGuidanceState?.draft_body || '');
        guidanceDirty = false;
        guidanceStatus = 'idle';
        guidanceStatusMessage = '';
        guidanceSnapshotKey = _guidanceSnapshot(currentGuidanceState);
    }

    function _clearDraftState() {
        guidanceDraftBody = '';
        guidanceDirty = false;
        guidanceStatus = 'idle';
        guidanceStatusMessage = '';
        guidanceSnapshotKey = '';
    }

    function _hasUnsavedDraft() {
        return guidanceDirty && Boolean(currentAgentId && currentGuidance);
    }

    function _runWithDraftGuard(action) {
        if (!_hasUnsavedDraft()) {
            void action();
            return;
        }
        UI.showConfirm(
            'Discard unsaved guidance changes?',
            'The current guidance draft has unsaved changes. Discard them and continue?',
            async () => {
                _clearDraftState();
                await action();
            },
        );
    }

    async function persistGuidanceDraft({ quiet = false } = {}) {
        if (!currentAgentId || !currentGuidance) {
            return false;
        }
        guidanceStatus = 'saving';
        guidanceStatusMessage = 'Saving draft…';
        renderGuidanceContent(currentGuidance, currentPreview);
        try {
            await API.updateGuidanceDraft(currentAgentId, currentProvider, { body: guidanceDraftBody });
            _invalidateGuidanceCache();
            currentPreview = null;
            await loadGuidance({ soft: true });
            return true;
        } catch (err) {
            guidanceStatus = 'error';
            guidanceStatusMessage = 'Save failed';
            renderGuidanceContent(currentGuidance, currentPreview);
            UI.reportError(
                quiet ? 'Failed to save the guidance draft before continuing' : 'Failed to save the guidance draft',
                err,
                { context: quiet ? 'Guidance pre-save failed' : 'Guidance save draft failed' },
            );
            return false;
        }
    }

    async function _runGuidanceLifecycle(actionLabel, op) {
        if (guidanceDirty) {
            const saved = await persistGuidanceDraft({ quiet: true });
            if (!saved) {
                return;
            }
        }
        guidanceStatus = 'saving';
        guidanceStatusMessage = `${actionLabel}…`;
        renderGuidanceContent(currentGuidance, currentPreview);
        try {
            await op();
            _invalidateGuidanceCache();
            currentPreview = null;
            await loadGuidance({ soft: true });
        } catch (err) {
            guidanceStatus = 'error';
            guidanceStatusMessage = 'Action failed';
            renderGuidanceContent(currentGuidance, currentPreview);
            UI.reportError(`Failed to ${actionLabel.toLowerCase()} the guidance`, err, {
                context: `Guidance ${actionLabel.toLowerCase()} failed`,
            });
        }
    }

    async function loadGuidance({ soft = false } = {}) {
        if (!currentAgentId) {
            currentGuidance = null;
            currentPreview = null;
            guidanceLoading = false;
            _clearDraftState();
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
            currentGuidance = cachedGuidance.guidance || cachedGuidance;
            guidanceLoading = true;
            renderGuidanceContent(currentGuidance, currentPreview);
        } else if (!soft) {
            renderLoadingState('Loading guidance…');
        }
        try {
            guidanceLoading = true;
            const data = await UI.loadCachedData(
                _guidanceCacheKey(),
                () => API.getGuidance(currentAgentId, currentProvider),
                {
                    ttlMs: GUIDANCE_CACHE_TTL_MS,
                    errorTtlMs: CACHE_ERROR_TTL_MS,
                    forceRefresh: hasCachedView,
                },
            );
            currentGuidance = data.guidance || data;
            guidanceLoading = false;
            renderGuidanceContent(currentGuidance, currentPreview);
        } catch (err) {
            guidanceLoading = false;
            if (hasCachedView || hadVisibleState) {
                UI.reportError('Failed to refresh guidance', err, { context: 'Guidance refresh failed' });
                renderGuidanceContent(currentGuidance, currentPreview);
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
        } finally {
            agentSelect.disabled = false;
        }
    }

    function renderGuidanceContent(guidance, preview) {
        const currentGuidanceState = guidance || {};
        const nextSnapshot = _guidanceSnapshot(currentGuidanceState);
        if (!guidanceDirty && guidanceSnapshotKey !== nextSnapshot) {
            _resetDraftState(currentGuidanceState);
        }
        UI.memoizedRender(contentEl, {
            provider: currentProvider,
            agentId: currentAgentId,
            guidance: currentGuidanceState,
            preview,
            loading: guidanceLoading,
            guidanceDraftBody,
            guidanceDirty,
            guidanceStatus,
            guidanceStatusMessage,
            guidanceTab: currentGuidanceTab,
        }, (state) => {
            const nodes = [];
            const currentGuidanceView = state.guidance || {};
            const currentPreviewState = state.preview || null;
            const lifecycleStatus = String(currentGuidanceView.lifecycle_status || 'draft');
            const lifecycleLabel = _guidanceStatus(currentGuidanceView);

            const headerPanel = document.createElement('section');
            headerPanel.className = 'editor-panel';
            headerPanel.dataset.key = 'guidance-header';

            const headerRow = document.createElement('div');
            headerRow.className = 'workspace-header-main';
            const titleWrap = document.createElement('div');
            titleWrap.className = 'workspace-title-group';
            const title = document.createElement('h3');
            title.className = 'editor-section-title';
            title.textContent = `${_providerLabel(state.provider)} guidance`;
            titleWrap.appendChild(title);
            const subtitle = document.createElement('p');
            subtitle.className = 'quiet-note';
            subtitle.textContent = state.loading
                ? 'Refreshing guidance…'
                : (state.guidanceDirty
                    ? 'You have unsaved changes in this draft.'
                    : 'Edit the provider baseline, review it, then publish it when ready.');
            titleWrap.appendChild(subtitle);
            headerRow.appendChild(titleWrap);
            const badge = document.createElement('span');
            badge.className = `badge badge-${lifecycleStatus}`;
            badge.textContent = lifecycleLabel;
            headerRow.appendChild(badge);
            headerPanel.appendChild(headerRow);
            headerPanel.appendChild(UI.renderMetadataGrid([
                { label: 'Save state', value: state.guidanceStatusMessage || (state.guidanceDirty ? 'Unsaved changes' : 'All changes saved') },
                { label: 'Published policy', value: currentGuidanceView.published_body ? 'Live' : 'Not published' },
                { label: 'Runtime behavior', value: `Applies to every ${_providerLabel(state.provider)} run on this bot` },
            ], { compact: true }));

            const headerActions = document.createElement('div');
            headerActions.className = 'editor-actions';
            const saveBtn = document.createElement('button');
            saveBtn.type = 'button';
            saveBtn.className = 'btn btn-primary';
            saveBtn.textContent = 'Save draft';
            saveBtn.addEventListener('click', async () => {
                await persistGuidanceDraft();
            });
            headerActions.appendChild(saveBtn);
            headerPanel.appendChild(headerActions);

            const workspaceTabs = UI.createSegmentedControl(
                [
                    { key: 'write', value: 'write', label: 'Write' },
                    { key: 'review', value: 'review', label: 'Review' },
                    { key: 'advanced', value: 'advanced', label: 'Advanced' },
                ],
                (nextTab) => {
                    currentGuidanceTab = nextTab;
                    _writeState();
                    renderGuidanceContent(currentGuidance, currentPreview);
                },
                {
                    label: 'Guidance workspace',
                    value: currentGuidanceTab,
                },
            );
            const tabRow = document.createElement('div');
            tabRow.className = 'route-controls';
            tabRow.appendChild(workspaceTabs.element);
            headerPanel.appendChild(tabRow);
            nodes.push(headerPanel);

            const writePanel = document.createElement('section');
            writePanel.className = 'editor-panel';
            writePanel.dataset.key = 'guidance-write';
            const writeTitle = document.createElement('div');
            writeTitle.className = 'editor-section-title';
            writeTitle.textContent = 'Draft policy';
            writePanel.appendChild(writeTitle);
            const writeNote = document.createElement('p');
            writeNote.className = 'quiet-note';
            writeNote.textContent = `Write the baseline instructions ${_providerLabel(state.provider)} should receive on every run for this bot.`;
            writePanel.appendChild(writeNote);
            const textarea = document.createElement('textarea');
            textarea.className = 'guidance-textarea';
            textarea.rows = 18;
            textarea.value = state.guidanceDraftBody || '';
            textarea.setAttribute('aria-label', 'Guidance draft');
            textarea.addEventListener('input', () => {
                guidanceDraftBody = textarea.value;
                markDirty();
            });
            writePanel.appendChild(textarea);

            const reviewPanel = document.createElement('section');
            reviewPanel.className = 'editor-panel';
            reviewPanel.dataset.key = 'guidance-review';
            const reviewTitle = document.createElement('div');
            reviewTitle.className = 'editor-section-title';
            reviewTitle.textContent = 'Review';
            reviewPanel.appendChild(reviewTitle);
            reviewPanel.appendChild(UI.renderMetadataGrid([
                { label: 'Lifecycle', value: lifecycleLabel },
                { label: 'Draft size', value: state.guidanceDraftBody.trim() ? `${state.guidanceDraftBody.trim().length} chars` : 'Empty draft' },
                { label: 'Published policy', value: currentGuidanceView.published_body ? 'Live' : 'Nothing published yet' },
            ], { compact: true }));

            const nextStepLabel = document.createElement('div');
            nextStepLabel.className = 'detail-label';
            nextStepLabel.textContent = 'Next step';
            reviewPanel.appendChild(nextStepLabel);
            const nextStepNote = document.createElement('p');
            nextStepNote.className = 'quiet-note';
            if (state.guidanceDirty) {
                nextStepNote.textContent = 'Save the draft to refresh the review state. Review actions will save first if needed.';
            } else if (lifecycleStatus === 'draft') {
                nextStepNote.textContent = 'Submit this guidance draft for review when you are ready.';
            } else if (lifecycleStatus === 'review') {
                nextStepNote.textContent = 'Approve this draft to make it publishable, or reject it if it still needs changes.';
            } else if (lifecycleStatus === 'approved') {
                nextStepNote.textContent = 'Publish this approved policy when you are ready for it to become active on the bot.';
            } else if (lifecycleStatus === 'archived') {
                nextStepNote.textContent = 'This guidance draft is archived.';
            } else {
                nextStepNote.textContent = 'This policy is live. Archive it only if you need to retire it.';
            }
            reviewPanel.appendChild(nextStepNote);

            const reviewActions = document.createElement('div');
            reviewActions.className = 'editor-actions';
            const previewBtn = document.createElement('button');
            previewBtn.type = 'button';
            previewBtn.className = 'btn btn-sm';
            previewBtn.textContent = 'Preview runtime';
            previewBtn.addEventListener('click', async () => {
                previewBtn.disabled = true;
                try {
                    currentPreview = await API.previewGuidance(currentAgentId, currentProvider, {
                        use_draft: true,
                        body_override: guidanceDraftBody,
                    });
                    renderGuidanceContent(currentGuidance, currentPreview);
                } catch (err) {
                    UI.reportError('Failed to preview the guidance', err, { context: 'Guidance preview failed' });
                }
                previewBtn.disabled = false;
            });
            reviewActions.appendChild(previewBtn);

            const submitBtn = document.createElement('button');
            submitBtn.type = 'button';
            submitBtn.className = 'btn btn-sm btn-primary';
            submitBtn.textContent = 'Submit';
            submitBtn.addEventListener('click', async () => {
                await _runGuidanceLifecycle('Submit', () => API.submitGuidance(currentAgentId, currentProvider));
            });
            reviewActions.appendChild(submitBtn);

            const approveBtn = document.createElement('button');
            approveBtn.type = 'button';
            approveBtn.className = 'btn btn-sm btn-primary';
            approveBtn.textContent = 'Approve';
            approveBtn.addEventListener('click', async () => {
                await _runGuidanceLifecycle('Approve', () => API.approveGuidance(currentAgentId, currentProvider));
            });
            reviewActions.appendChild(approveBtn);

            const rejectBtn = document.createElement('button');
            rejectBtn.type = 'button';
            rejectBtn.className = 'btn btn-sm';
            rejectBtn.textContent = 'Reject';
            rejectBtn.addEventListener('click', async () => {
                await _runGuidanceLifecycle('Reject', () => API.rejectGuidance(currentAgentId, currentProvider));
            });
            reviewActions.appendChild(rejectBtn);

            const publishBtn = document.createElement('button');
            publishBtn.type = 'button';
            publishBtn.className = 'btn btn-sm btn-primary';
            publishBtn.textContent = 'Publish';
            publishBtn.addEventListener('click', async () => {
                UI.showConfirm(
                    'Publish guidance',
                    'Publish this provider policy for future runs on this bot?',
                    async () => {
                        await _runGuidanceLifecycle('Publish', () => API.publishGuidance(currentAgentId, currentProvider));
                    },
                );
            });
            reviewActions.appendChild(publishBtn);

            const archiveBtn = document.createElement('button');
            archiveBtn.type = 'button';
            archiveBtn.className = 'btn btn-sm btn-danger';
            archiveBtn.textContent = 'Archive';
            archiveBtn.addEventListener('click', async () => {
                await _runGuidanceLifecycle('Archive', () => API.archiveGuidance(currentAgentId, currentProvider));
            });
            reviewActions.appendChild(archiveBtn);
            reviewPanel.appendChild(reviewActions);

            const refreshChrome = () => {
                saveBtn.disabled = guidanceLoading || guidanceStatus === 'saving';
                saveBtn.textContent = guidanceStatus === 'saving' ? 'Saving…' : 'Save draft';
                previewBtn.disabled = guidanceLoading || guidanceStatus === 'saving';
                previewBtn.textContent = currentPreview ? 'Refresh runtime preview' : 'Preview runtime';
                submitBtn.hidden = lifecycleStatus !== 'draft';
                submitBtn.disabled = guidanceLoading || guidanceStatus === 'saving' || !guidanceDraftBody.trim();
                approveBtn.hidden = lifecycleStatus !== 'review';
                approveBtn.disabled = guidanceLoading || guidanceStatus === 'saving';
                rejectBtn.hidden = lifecycleStatus !== 'review';
                rejectBtn.disabled = guidanceLoading || guidanceStatus === 'saving';
                publishBtn.hidden = lifecycleStatus !== 'approved';
                publishBtn.disabled = guidanceLoading || guidanceStatus === 'saving';
                archiveBtn.hidden = lifecycleStatus === 'archived';
                archiveBtn.disabled = guidanceLoading || guidanceStatus === 'saving';
            };

            const markDirty = () => {
                guidanceDirty = true;
                guidanceStatus = 'dirty';
                guidanceStatusMessage = 'Unsaved changes';
                currentPreview = null;
                refreshChrome();
            };

            const draftPreviewLabel = document.createElement('div');
            draftPreviewLabel.className = 'detail-label';
            draftPreviewLabel.textContent = 'Draft preview';
            reviewPanel.appendChild(draftPreviewLabel);
            const draftPreview = document.createElement('div');
            draftPreview.className = 'task-item-summary';
            draftPreview.innerHTML = state.guidanceDraftBody.trim()
                ? UI.renderContent(state.guidanceDraftBody)
                : UI.renderEmptyState('Draft policy is empty.', true).outerHTML;
            reviewPanel.appendChild(draftPreview);

            const runtimePreviewLabel = document.createElement('div');
            runtimePreviewLabel.className = 'detail-label';
            runtimePreviewLabel.textContent = 'Runtime preview';
            reviewPanel.appendChild(runtimePreviewLabel);
            if (currentPreviewState) {
                reviewPanel.appendChild(UI.renderMetadataGrid([
                    {
                        label: 'Preview source',
                        value: currentPreviewState.preview_source === 'draft' ? 'Current draft' : 'Published policy',
                    },
                    { label: 'Prompt weight', value: String(currentPreviewState.prompt_weight || 0) },
                ], { compact: true }));
                const runtimePreview = document.createElement('pre');
                runtimePreview.className = 'event-pre';
                runtimePreview.style.whiteSpace = 'pre-wrap';
                runtimePreview.textContent = String(currentPreviewState.composed_prompt || '').trim() || '(empty prompt)';
                reviewPanel.appendChild(runtimePreview);
            } else {
                reviewPanel.appendChild(
                    UI.renderEmptyState(
                        'Preview the current draft to see the composed provider prompt before publishing.',
                        true,
                    ),
                );
            }

            const publishedLabel = document.createElement('div');
            publishedLabel.className = 'detail-label';
            publishedLabel.textContent = 'Published policy';
            reviewPanel.appendChild(publishedLabel);
            const publishedPreview = document.createElement('div');
            publishedPreview.className = 'task-item-summary';
            publishedPreview.innerHTML = currentGuidanceView.published_body
                ? UI.renderContent(currentGuidanceView.published_body)
                : UI.renderEmptyState('Nothing is published for this provider yet.', true).outerHTML;
            reviewPanel.appendChild(publishedPreview);

            const advancedPanel = document.createElement('section');
            advancedPanel.className = 'editor-panel';
            advancedPanel.dataset.key = 'guidance-advanced';
            const advancedTitle = document.createElement('div');
            advancedTitle.className = 'editor-section-title';
            advancedTitle.textContent = 'Advanced';
            advancedPanel.appendChild(advancedTitle);
            advancedPanel.appendChild(UI.renderMetadataGrid([
                { label: 'Provider', value: _providerLabel(state.provider) },
                { label: 'Draft revision', value: currentGuidanceView.active_revision_id || '(none)' },
                { label: 'Published revision', value: currentGuidanceView.published_revision_id || '(none)' },
                { label: 'Status', value: lifecycleLabel },
            ]));

            if (state.guidanceTab === 'write') {
                nodes.push(writePanel);
            } else if (state.guidanceTab === 'review') {
                nodes.push(reviewPanel);
            } else {
                nodes.push(advancedPanel);
            }
            refreshChrome();
            return nodes;
        }, {
            signatureFn(state) {
                const currentGuidanceView = state.guidance || {};
                const currentPreviewState = state.preview || {};
                return {
                    provider: String(state.provider || ''),
                    agentId: String(state.agentId || ''),
                    status: String(currentGuidanceView.lifecycle_status || 'draft'),
                    draftBody: String(state.guidanceDraftBody || ''),
                    publishedBody: String(currentGuidanceView.published_body || ''),
                    previewSource: String(currentPreviewState.preview_source || ''),
                    previewPrompt: String(currentPreviewState.composed_prompt || ''),
                    guidanceStatus: String(state.guidanceStatus || ''),
                    guidanceStatusMessage: String(state.guidanceStatusMessage || ''),
                    guidanceDirty: Boolean(state.guidanceDirty),
                    guidanceTab: String(state.guidanceTab || ''),
                    loading: Boolean(state.loading),
                    activeRevisionId: String(currentGuidanceView.active_revision_id || ''),
                    publishedRevisionId: String(currentGuidanceView.published_revision_id || ''),
                };
            },
        });
    }

    const beforeUnload = (event) => {
        if (!_hasUnsavedDraft()) return;
        event.preventDefault();
        event.returnValue = '';
    };
    window.addEventListener('beforeunload', beforeUnload);

    currentAgentId = _readAgentId();
    _writeState();
    container.__routeReady = loadAgents();
    providerControl.setActive(currentProvider);

    cleanups.add(() => window.removeEventListener('beforeunload', beforeUnload));
    UI.subscribeWithRefresh(cleanups, 'agents', () => loadAgents({ soft: true }), 600);
}
