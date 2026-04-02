/**
 * Conversation list — direct work start plus active thread roster.
 */
function renderConversationList(container) {
    const cleanups = UI.beginCleanupScope();
    const QUICK_START_INLINE_LIMIT = 8;
    const CONVERSATION_TYPES = [
        { key: 'all', value: '', label: 'All' },
        { key: 'conversation', value: 'conversation', label: 'Conversations' },
        { key: 'task_thread', value: 'task_thread', label: 'Task threads' },
    ];
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }
    const limit = UI.DEFAULT_PAGE_LIMIT;
    let currentQ = UI.readQueryParam('q', '');
    let currentStatus = UI.readQueryParam('status', '');
    let currentType = UI.readQueryParam('type', '');
    let searchTimeout = null;
    let hasLoaded = false;
    let quickStartLoaded = false;
    let openingConversationFor = '';

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

    function applyStatus(value) {
        currentStatus = value;
        paginator.reset();
        statusControl.setActive(currentStatus);
        UI.updateQueryParams({ q: currentQ, status: currentStatus, type: currentType });
        loadPage();
    }

    function applyType(value) {
        currentType = value;
        paginator.reset();
        typeControl.setActive(currentType);
        UI.updateQueryParams({ q: currentQ, status: currentStatus, type: currentType });
        loadPage();
    }

    const listShell = document.createElement('section');
    listShell.className = 'list-shell';
    shell.appendChild(listShell);

    const listEl = document.createElement('div');
    listEl.className = 'list-container';
    listShell.appendChild(listEl);

    const pagEl = document.createElement('div');
    pagEl.className = 'pagination-shell';
    listShell.appendChild(pagEl);
    const paginator = UI.createCursorPaginator(pagEl, () => loadPage());

    searchInput.value = currentQ;

    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentQ = searchInput.value.trim();
            paginator.reset();
            UI.updateQueryParams({ q: currentQ, status: currentStatus, type: currentType });
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

        const approvalsLink = document.createElement('a');
        approvalsLink.href = '/ui/approvals';
        approvalsLink.className = 'section-link';
        approvalsLink.textContent = 'Approvals';
        links.appendChild(approvalsLink);

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
                        Router.navigate('/ui/conversations/' + conversation.conversation_id);
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
                (agent) => String((agent && agent.execution_state) || 'healthy') !== 'faulted',
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

    function renderRows(conversations, data) {
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
            });
            const sub = document.createElement('span');
            const parts = [];
            const targetLabel = UI.visibleLabel(item.target_display_name, item.target_agent_id);
            if (targetLabel) parts.push(targetLabel);
            if (item.conversation_type === 'task_thread') parts.push('task thread');
            if (item.origin_channel) parts.push(item.origin_channel);
            if (item.updated_at || item.created_at) parts.push(UI.relativeTime(item.updated_at || item.created_at));
            sub.textContent = parts.join(' · ');

            const row = UI.renderListRow({
                href: '/ui/conversations/' + item.conversation_id,
                label: item.title || (item.conversation_type === 'task_thread' ? 'Task thread' : targetLabel) || 'Untitled conversation',
                sublabelNode: sub,
                badgeText: item.status || 'open',
                badgeClass: 'badge-' + (item.status || 'open'),
                trailing: UI.buildConversationTypeBadge(item),
                className: item.conversation_type === 'task_thread' ? 'list-row-task-thread' : '',
                signature: rowSignature,
            });
            row.dataset.key = item.conversation_id;
            return row;
        }), {
            signatureFn(state) {
                return {
                    q: String(state.q || ''),
                    status: String(state.status || ''),
                    type: String(state.type || ''),
                    cursor: state.cursor,
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

        paginator.render({ hasMore: !!data.has_more, nextCursor: data.next_cursor });
        hasLoaded = true;
    }

    async function loadPage({ soft = false } = {}) {
        const params = { cursor: paginator.cursor, limit };
        if (currentQ) params.q = currentQ;
        if (currentStatus) params.status = currentStatus;
        if (currentType) params.conversation_type = currentType;
        try {
            const data = await API.listConversations(params);
            renderRows(data.conversations || data || [], data);
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
