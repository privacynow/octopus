/**
 * Conversation list — direct work start plus active thread roster.
 */
function renderConversationList(container) {
    const cleanups = UI.beginCleanupScope();
    const QUICK_START_INLINE_LIMIT = 8;
    const CONVERSATION_TYPES = [
        { key: 'all', value: '', label: 'All' },
        { key: 'conversation', value: 'conversation', label: 'Conversations' },
        { key: 'task_thread', value: 'task_thread', label: 'Delegation threads' },
    ];
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        contentInner.classList.add('conversation-list-route-shell');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
        cleanups.add(() => contentInner.classList.remove('conversation-list-route-shell'));
    }
    const limit = UI.DEFAULT_PAGE_LIMIT;
    let currentQ = UI.readQueryParam('q', '');
    let currentStatus = UI.readQueryParam('status', '');
    let currentType = UI.readQueryParam('type', 'conversation');
    let includeGenerated = UI.readQueryParam('include_generated', '') === '1';
    const initialCursor = Math.max(0, Number.parseInt(UI.readQueryParam('cursor', '0'), 10) || 0);
    const initialCursorStack = [];
    for (let value = 0; value < initialCursor; value += limit) {
        initialCursorStack.push(value);
    }
    let searchTimeout = null;
    let hasLoaded = false;
    let quickStartLoaded = false;
    let openingConversationFor = '';
    let currentConversationId = UI.readQueryParam('conversation_id', '');
    let currentConversations = [];
    let currentListData = null;
    const conversationPreviews = new Map();
    const conversationPreviewErrors = new Map();
    const conversationPreviewLoading = new Set();
    let paginator = null;

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Conversations</h2>';
    container.appendChild(header);

    const shell = document.createElement('section');
    shell.className = 'admin-shell';
    container.appendChild(shell);

    const workbench = document.createElement('section');
    workbench.className = 'workbench-panel';
    shell.appendChild(workbench);

    const quickStart = document.createElement('section');
    quickStart.className = 'quickstart-strip';
    workbench.appendChild(quickStart);

    const controls = document.createElement('div');
    controls.className = 'route-controls';
    workbench.appendChild(controls);

    const searchInput = document.createElement('input');
    searchInput.className = 'search-input';
    searchInput.placeholder = 'Search conversations';
    searchInput.type = 'text';
    searchInput.setAttribute('aria-label', 'Search conversations');
    searchInput.setAttribute('title', 'Press / to focus search');
    controls.appendChild(searchInput);

    const statuses = [
        { key: 'all', value: '', label: 'All' },
        { key: 'open', value: 'open', label: 'Open' },
        { key: 'running', value: 'running', label: 'Running' },
        { key: 'completed', value: 'completed', label: 'Done' },
        { key: 'failed', value: 'failed', label: 'Needs follow-up' },
    ];
    const statusControl = UI.createSegmentedControl(statuses, (value) => applyStatus(value), {
        label: 'Conversation status filter',
        value: currentStatus,
    });
    const statusBar = statusControl.element;
    controls.appendChild(statusBar);
    const typeControl = UI.createSegmentedControl(CONVERSATION_TYPES, (value) => applyType(value), {
        label: 'Conversation type filter',
        value: currentType,
    });
    const typeBar = typeControl.element;
    controls.appendChild(typeBar);
    const generatedToggle = document.createElement('a');
    generatedToggle.className = 'section-link';
    controls.appendChild(generatedToggle);

    function applyStatus(value) {
        currentStatus = value;
        paginator.reset(0);
        statusControl.setActive(currentStatus);
        _writeState();
        loadPage();
    }

    function applyType(value) {
        currentType = value;
        paginator.reset(0);
        typeControl.setActive(currentType);
        _writeState();
        loadPage();
    }

    function _writeState() {
        UI.updateQueryParams({
            q: currentQ,
            status: currentStatus,
            type: currentType,
            include_generated: includeGenerated ? '1' : '',
            cursor: paginator && Number(paginator.cursor) > 0 ? paginator.cursor : '',
            conversation_id: currentConversationId || '',
        });
        _updateGeneratedToggle();
    }

    function _updateGeneratedToggle() {
        const url = new URL(window.location.href);
        if (includeGenerated) {
            url.searchParams.delete('include_generated');
        } else {
            url.searchParams.set('include_generated', '1');
        }
        generatedToggle.href = `${url.pathname}${url.search}${url.hash}`;
        generatedToggle.textContent = includeGenerated ? 'Hide generated/audit work' : 'Show generated/audit work';
    }
    _updateGeneratedToggle();

    const listShell = document.createElement('section');
    listShell.className = 'list-shell';
    shell.appendChild(listShell);

    const listEl = document.createElement('div');
    listEl.className = 'list-container';
    listShell.appendChild(listEl);

    const pagEl = document.createElement('div');
    pagEl.className = 'pagination-shell';
    listShell.appendChild(pagEl);
    paginator = UI.createCursorPaginator(pagEl, () => loadPage(), {
        initialCursor,
        initialStack: initialCursorStack,
        onChange: () => {
            currentConversationId = '';
            _writeState();
        },
    });

    searchInput.value = currentQ;

    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentQ = searchInput.value.trim();
            paginator.reset(0);
            _writeState();
            loadPage();
        }, 250);
    });

    function renderQuickStart(agents, { hasOverflow = false } = {}) {
        UI.memoizedRender(quickStart, {
            hasOverflow: !!hasOverflow,
            agents: agents || [],
        }, (state) => {
        const quickShell = document.createElement('div');
        quickShell.className = 'quickstart-shell';
        quickShell.dataset.key = 'quickstart-shell';

        const head = document.createElement('div');
        head.className = 'workbench-row';

        const links = document.createElement('div');
        links.className = 'quickstart-links';

        const agentsLink = document.createElement('a');
        agentsLink.href = '/ui/agents';
        agentsLink.className = 'section-link';
        agentsLink.textContent = 'Agents';
        links.appendChild(agentsLink);

        head.appendChild(links);
        quickShell.appendChild(head);

        const row = document.createElement('div');
        row.className = 'quickstart-row';
        row.dataset.key = 'quickstart-row';

        if (!state.agents.length) {
            row.appendChild(UI.renderEmptyState('No execution-ready agents.', true));
        } else {
            state.agents.forEach((agent) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'quickstart-chip';
                button.dataset.key = agent.agent_id;
                button.setAttribute('aria-label', `Open or start a conversation with ${agent.display_name || agent.slug || agent.agent_id}`);
                button.textContent = agent.display_name || agent.slug || agent.agent_id;
                button.addEventListener('click', async () => {
                    if (openingConversationFor === agent.agent_id) return;
                    openingConversationFor = agent.agent_id;
                    button.disabled = true;
                    button.classList.add('busy');
                    try {
                        const conversation = await API.openConversationForAgent(agent.agent_id, {
                            title: `Conversation with ${agent.display_name || agent.slug || agent.agent_id}`,
                        });
                        Router.navigate(UI.conversationHref(conversation.conversation_id, {
                            conversationType: conversation.conversation_type,
                        }));
                    } catch (err) {
                        openingConversationFor = '';
                        button.disabled = false;
                        button.classList.remove('busy');
                        UI.reportError('Failed to open a conversation for this agent', err, { context: 'Conversation quick start failed' });
                    }
                });
                row.appendChild(button);
            });

            if (state.hasOverflow) {
                const moreLink = document.createElement('a');
                moreLink.href = '/ui/agents?state=connected';
                moreLink.className = 'quickstart-chip';
                moreLink.dataset.key = 'quickstart-overflow';
                moreLink.textContent = 'More agents';
                row.appendChild(moreLink);
            }
        }

        quickShell.appendChild(row);
        return [quickShell];
        }, {
            signatureFn(state) {
                return {
                    hasOverflow: !!state.hasOverflow,
                    agents: (state.agents || []).map((agent) => ({
                        id: String(agent.agent_id || ''),
                        label: String(agent.display_name || agent.slug || agent.agent_id || ''),
                    })),
                };
            },
        });
    }

    async function loadQuickStart({ soft = false } = {}) {
        try {
            const data = await API.listAgents({ state: 'connected', limit: QUICK_START_INLINE_LIMIT + 1 });
            const agents = (data.agents || data || []).filter(
                (agent) => String((agent && agent.execution_state) || 'healthy') !== 'faulted'
                    && !UI.isDefaultHiddenRecord(agent),
            );
            renderQuickStart(agents.slice(0, QUICK_START_INLINE_LIMIT), {
                hasOverflow: !!data.has_more || agents.length > QUICK_START_INLINE_LIMIT,
            });
            quickStartLoaded = true;
        } catch (err) {
            if (soft && quickStartLoaded) {
                UI.reportError('Failed to refresh connected agents', err, { context: 'Conversation quick start soft refresh failed' });
                return;
            }
            UI.clearMemoizedRender(quickStart);
            UI.reconcileChildren(quickStart, [UI.createErrorCard('Failed to load connected agents: ' + err.message, loadQuickStart)]);
        }
    }

    function _conversationHref(item, view = '') {
        return UI.conversationHref(item.conversation_id, {
            view,
            conversationType: item.conversation_type,
            operational: item.conversation_type === 'task_thread',
        });
    }

    function _conversationPreviewSignature(conversationId) {
        const key = String(conversationId || '');
        const preview = conversationPreviews.get(key);
        const error = conversationPreviewErrors.get(key);
        return {
            loading: conversationPreviewLoading.has(key),
            error: error ? String(error.message || error) : '',
            meta: preview?.meta ? String(preview.meta.updated_at || preview.meta.status || '') : '',
            runs: (preview?.runs || []).map((run) => [
                String(run.protocol_run_id || ''),
                String(run.status || ''),
                String(run.current_stage_key || ''),
            ].join(':')),
        };
    }

    async function loadConversationPreview(conversationId) {
        const key = String(conversationId || '').trim();
        if (!key || conversationPreviewLoading.has(key) || conversationPreviews.has(key)) return;
        conversationPreviewLoading.add(key);
        conversationPreviewErrors.delete(key);
        try {
            const [meta, runData] = await Promise.all([
                API.getConversation(key),
                API.listProtocolRuns({ root_conversation_id: key, limit: 5 }),
            ]);
            conversationPreviews.set(key, {
                meta,
                runs: runData.runs || runData || [],
            });
        } catch (err) {
            conversationPreviewErrors.set(key, err);
            UI.reportError('Failed to load conversation context', err, {
                context: 'Conversation list preview load failed',
            });
        } finally {
            conversationPreviewLoading.delete(key);
            renderRows(currentConversations, currentListData || {});
        }
    }

    function _renderConversationInlineDetail(item) {
        const conversationId = String(item.conversation_id || '');
        const panel = document.createElement('section');
        panel.className = 'conversation-inline-detail';

        if (conversationPreviewLoading.has(conversationId) && !conversationPreviews.has(conversationId)) {
            panel.appendChild(UI.renderEmptyState('Loading conversation context…', true));
            return panel;
        }

        const error = conversationPreviewErrors.get(conversationId);
        if (error) {
            panel.appendChild(UI.createErrorCard('Failed to load conversation context.', () => {
                conversationPreviews.delete(conversationId);
                conversationPreviewErrors.delete(conversationId);
                void loadConversationPreview(conversationId);
            }));
        }

        const preview = conversationPreviews.get(conversationId) || {};
        const meta = preview.meta || item;
        const actions = document.createElement('div');
        actions.className = 'task-action-row';
        const openConversation = document.createElement('a');
        openConversation.href = _conversationHref(item);
        openConversation.className = 'btn btn-sm btn-primary';
        openConversation.textContent = 'Open full conversation';
        actions.appendChild(openConversation);
        const openTasks = document.createElement('a');
        openTasks.href = _conversationHref(item, 'tasks');
        openTasks.className = 'btn btn-sm';
        openTasks.textContent = 'Open linked work';
        actions.appendChild(openTasks);
        panel.appendChild(actions);

        const facts = UI.renderMetadataGrid([
            { label: 'Status', value: meta.status || item.status || 'open' },
            { label: 'Agent', value: UI.visibleLabel(meta.target_display_name, meta.target_agent_id, item.target_display_name, item.target_agent_id) || '—' },
            { label: 'Origin', value: meta.origin_channel || item.origin_channel || 'registry' },
            { label: 'Updated', value: UI.relativeTime(meta.updated_at || item.updated_at || item.created_at) || '—' },
        ], { compact: true });
        panel.appendChild(facts);

        const linkedRuns = preview.runs || [];
        const linkedLabel = document.createElement('div');
        linkedLabel.className = 'detail-label';
        linkedLabel.textContent = 'Linked runs';
        panel.appendChild(linkedLabel);

        const runList = document.createElement('div');
        runList.className = 'task-artifact-list';
        const runRows = linkedRuns.map((run) => UI.renderListRow({
            href: `/ui/runs?run_id=${encodeURIComponent(run.protocol_run_id || '')}`,
            label: [
                run.protocol_display_name || run.protocol_name || 'Protocol run',
                run.current_stage_key || '',
            ].filter(Boolean).join(' · '),
            sublabel: [
                run.problem_statement || '',
                run.protocol_run_id ? `run ${String(run.protocol_run_id).slice(0, 8)}` : '',
            ].filter(Boolean).join(' · '),
            badgeText: run.status || '',
            badgeClass: `badge-${run.status || 'open'}`,
        }));
        UI.reconcileChildren(runList, runRows.length ? runRows : [UI.renderEmptyState('No protocol runs linked to this conversation yet.', true)]);
        panel.appendChild(runList);
        return panel;
    }

    function renderRows(conversations, data) {
        currentConversations = Array.isArray(conversations) ? conversations : [];
        currentListData = data || {};
        if (!conversations.length) {
            const emptyMessage = currentQ || currentStatus || currentType ? 'No conversations match this view.' : 'Nothing here yet.';
            UI.clearMemoizedRender(listEl);
            UI.reconcileChildren(listEl, [UI.renderEmptyState(emptyMessage, true)]);
            paginator.clear();
            return;
        }

        UI.memoizedRender(listEl, {
            q: currentQ,
            status: currentStatus,
            type: currentType,
            cursor: paginator.cursor,
            selectedId: currentConversationId,
            previews: (conversations || []).map((item) => _conversationPreviewSignature(item.conversation_id)),
            conversations,
        }, (state) => state.conversations.map((item) => {
            const rowSignature = UI.dataSignature({
                id: String(item.conversation_id || ''),
                type: String(item.conversation_type || 'conversation'),
                status: String(item.status || ''),
                updatedLabel: UI.relativeTime(item.updated_at || item.created_at),
                title: String(item.title || ''),
                target: String(item.target_display_name || item.target_agent_id || ''),
                origin: String(item.origin_channel || ''),
                selected: String(item.conversation_id || '') === String(currentConversationId || ''),
                preview: _conversationPreviewSignature(item.conversation_id),
            });
            const selected = String(item.conversation_id || '') === String(currentConversationId || '');
            const sub = document.createElement('span');
            const parts = [];
            const targetLabel = UI.visibleLabel(item.target_display_name, item.target_agent_id);
            if (targetLabel) parts.push(targetLabel);
            if (item.conversation_type === 'task_thread') parts.push('delegation thread');
            if (item.origin_channel) parts.push(item.origin_channel);
            if (item.updated_at || item.created_at) parts.push(UI.relativeTime(item.updated_at || item.created_at));
            sub.textContent = parts.join(' · ');

            const shell = document.createElement('article');
            shell.className = 'conversation-list-entry';
            if (selected) shell.classList.add('is-selected');
            shell.dataset.key = item.conversation_id;
            shell.dataset.signature = rowSignature;

            const row = UI.renderListRow({
                label: item.title || (item.conversation_type === 'task_thread' ? 'Delegation thread' : targetLabel) || 'Untitled conversation',
                sublabelNode: sub,
                badgeText: item.status || 'open',
                badgeClass: 'badge-' + (item.status || 'open'),
                trailing: UI.buildConversationTypeBadge(item),
                className: [
                    item.conversation_type === 'task_thread' ? 'list-row-task-thread' : '',
                    selected ? 'is-selected' : '',
                ].filter(Boolean).join(' '),
                signature: rowSignature,
                onClick: () => {
                    const conversationId = String(item.conversation_id || '');
                    if (conversationId && String(currentConversationId || '') === conversationId) {
                        currentConversationId = '';
                        _writeState();
                        renderRows(currentConversations, currentListData || {});
                        return;
                    }
                    currentConversationId = conversationId;
                    _writeState();
                    renderRows(currentConversations, currentListData || {});
                    void loadConversationPreview(currentConversationId);
                },
            });
            row.setAttribute('aria-expanded', String(selected));
            shell.appendChild(row);
            if (selected) {
                shell.appendChild(_renderConversationInlineDetail(item));
            }
            return shell;
        }), {
            signatureFn(state) {
                return {
                    q: String(state.q || ''),
                    status: String(state.status || ''),
                    type: String(state.type || ''),
                    cursor: state.cursor,
                    selectedId: String(state.selectedId || ''),
                    previews: state.previews || [],
                    conversations: (state.conversations || []).map((item) => ({
                        id: String(item.conversation_id || ''),
                        type: String(item.conversation_type || 'conversation'),
                        status: String(item.status || ''),
                        updatedLabel: UI.relativeTime(item.updated_at || item.created_at),
                        title: String(item.title || ''),
                        target: String(item.target_display_name || item.target_agent_id || ''),
                        origin: String(item.origin_channel || ''),
                    })),
                };
            },
        });

        paginator.render({
            hasMore: !!data.has_more,
            nextCursor: data.next_cursor,
            info: `Page ${paginator.stackLength + 1}`,
        });
        hasLoaded = true;
        if (currentConversationId && conversations.some((item) => String(item.conversation_id || '') === String(currentConversationId || ''))) {
            void loadConversationPreview(currentConversationId);
        }
    }

    async function loadPage({ soft = false } = {}) {
        const params = { cursor: paginator.cursor, limit };
        if (currentQ) params.q = currentQ;
        if (currentStatus) params.status = currentStatus;
        if (currentType) params.conversation_type = currentType;
        try {
            const data = await API.listConversations(params);
            const rawRows = data.conversations || data || [];
            const rows = UI.defaultVisibleRecords(rawRows, { includeHidden: includeGenerated });
            if (currentConversationId && !rows.some((item) => String(item.conversation_id || '') === String(currentConversationId || ''))) {
                const selectedHidden = rawRows.find((item) => String(item.conversation_id || '') === String(currentConversationId || ''));
                if (selectedHidden) rows.unshift(selectedHidden);
            }
            renderRows(rows, { ...data, conversations: rows });
        } catch (err) {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh conversations', err, { context: 'Conversation list soft refresh failed' });
                return;
            }
            UI.clearMemoizedRender(listEl);
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load conversations: ' + err.message, loadPage)]);
            paginator.clear();
        }
    }

    statusControl.setActive(currentStatus);
    typeControl.setActive(currentType);
    container.__routeReady = Promise.allSettled([loadQuickStart(), loadPage()]);

    cleanups.add(() => clearTimeout(searchTimeout));
    UI.subscribeWithRefresh(cleanups, 'agents', () => loadQuickStart({ soft: true }), 350);
    UI.subscribeWithRefresh(cleanups, 'conversations', () => loadPage({ soft: true }), 350);
}
