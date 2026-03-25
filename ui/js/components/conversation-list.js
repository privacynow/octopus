/**
 * Conversation list — direct work start plus active thread roster.
 */
function renderConversationList(container) {
    const cleanups = UI.beginCleanupScope();
    const QUICK_START_INLINE_LIMIT = 8;
    let cursor = 0;
    let cursorStack = [];
    const limit = UI.DEFAULT_PAGE_LIMIT;
    let currentQ = UI.readQueryParam('q', '');
    let currentStatus = UI.readQueryParam('status', '');
    let searchTimeout = null;
    let hasLoaded = false;
    let quickStartLoaded = false;
    let openingConversationFor = '';

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Conversations</h2>';
    container.appendChild(header);

    const quickStart = document.createElement('section');
    quickStart.className = 'quickstart-strip';
    container.appendChild(quickStart);

    const controls = document.createElement('div');
    controls.className = 'route-controls';
    container.appendChild(controls);

    const searchInput = document.createElement('input');
    searchInput.className = 'search-input';
    searchInput.placeholder = 'Search conversations';
    searchInput.type = 'text';
    searchInput.setAttribute('aria-label', 'Search conversations');
    searchInput.setAttribute('title', 'Press / to focus search');
    controls.appendChild(searchInput);

    const statusBar = document.createElement('div');
    statusBar.className = 'segmented-control';
    statusBar.setAttribute('role', 'tablist');
    statusBar.setAttribute('aria-label', 'Conversation status filter');
    controls.appendChild(statusBar);

    const statuses = [
        ['all', '', 'All'],
        ['open', 'open', 'Open'],
        ['running', 'running', 'Running'],
        ['completed', 'completed', 'Done'],
        ['failed', 'failed', 'Needs follow-up'],
    ];

    function applyStatus(value) {
        currentStatus = value;
        cursor = 0;
        cursorStack = [];
        syncStatusButtons();
        UI.updateQueryParams({ q: currentQ, status: currentStatus });
        loadPage();
    }

    statuses.forEach(([key, value, label]) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'segmented-control-btn';
        btn.dataset.key = key;
        btn.dataset.value = value;
        btn.textContent = label;
        btn.setAttribute('role', 'tab');
        btn.setAttribute('aria-selected', String(currentStatus === value));
        btn.tabIndex = currentStatus === value ? 0 : -1;
        if (currentStatus === value) btn.classList.add('active');
        btn.addEventListener('click', () => applyStatus(value));
        statusBar.appendChild(btn);
    });
    UI.bindSegmentedControlKeyboard(statusBar, (target) => applyStatus(target.dataset.value || ''));

    const listShell = document.createElement('section');
    listShell.className = 'list-shell';
    container.appendChild(listShell);

    const listEl = document.createElement('div');
    listEl.className = 'list-container';
    listShell.appendChild(listEl);

    const pagEl = document.createElement('div');
    pagEl.className = 'pagination-shell';
    listShell.appendChild(pagEl);

    searchInput.value = currentQ;

    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentQ = searchInput.value.trim();
            cursor = 0;
            cursorStack = [];
            UI.updateQueryParams({ q: currentQ, status: currentStatus });
            loadPage();
        }, 250);
    });

    function syncStatusButtons() {
        statusBar.querySelectorAll('.segmented-control-btn').forEach((btn) => {
            const match = statuses.find(([key]) => key === btn.dataset.key);
            const active = !!match && currentStatus === match[1];
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-selected', String(active));
            btn.tabIndex = active ? 0 : -1;
        });
    }

    function renderPaginationState({ hasPrev, hasNext, onPrev, onNext }) {
        const wrapper = document.createElement('div');
        UI.renderPagination(wrapper, {
            hasPrev,
            hasNext,
            info: '',
            onPrev,
            onNext,
        });
        UI.reconcileChildren(pagEl, Array.from(wrapper.childNodes));
    }

    function renderQuickStart(agents, { hasOverflow = false } = {}) {
        const shell = document.createElement('div');
        shell.className = 'quickstart-shell';
        shell.dataset.key = 'quickstart-shell';

        const head = document.createElement('div');
        head.className = 'quickstart-header';

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
        shell.appendChild(head);

        const row = document.createElement('div');
        row.className = 'quickstart-row';
        row.dataset.key = 'quickstart-row';

        if (!agents.length) {
            row.appendChild(UI.renderEmptyState('No connected agents.', true));
        } else {
            agents.forEach((agent) => {
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

            if (hasOverflow) {
                const moreLink = document.createElement('a');
                moreLink.href = '/ui/agents?state=connected';
                moreLink.className = 'quickstart-chip';
                moreLink.dataset.key = 'quickstart-overflow';
                moreLink.textContent = 'All agents';
                row.appendChild(moreLink);
            }
        }

        shell.appendChild(row);
        UI.reconcileChildren(quickStart, [shell]);
    }

    function loadQuickStart({ soft = false } = {}) {
        if (!soft || !quickStartLoaded) {
            UI.reconcileChildren(quickStart, UI.createSkeletonNodes(1, 'card'));
        }
        API.listAgents({ state: 'connected', limit: QUICK_START_INLINE_LIMIT + 1 }).then((data) => {
            const agents = data.agents || data || [];
            renderQuickStart(agents.slice(0, QUICK_START_INLINE_LIMIT), {
                hasOverflow: !!data.has_more || agents.length > QUICK_START_INLINE_LIMIT,
            });
            quickStartLoaded = true;
        }).catch((err) => {
            if (soft && quickStartLoaded) {
                UI.reportError('Failed to refresh connected agents', err, { context: 'Conversation quick start soft refresh failed' });
                return;
            }
            UI.reconcileChildren(quickStart, [UI.createErrorCard('Failed to load connected agents: ' + err.message, loadQuickStart)]);
        });
    }

    function renderRows(conversations, data) {
        if (!conversations.length) {
            const emptyMessage = currentQ || currentStatus ? 'No conversations match this view.' : 'No conversations yet.';
            UI.reconcileChildren(listEl, [UI.renderEmptyState(emptyMessage, true)]);
            UI.reconcileChildren(pagEl, []);
            return;
        }

        const rows = conversations.map((item) => {
            const sub = document.createElement('span');
            const parts = [];
            if (item.target_display_name || item.target_agent_id) parts.push(item.target_display_name || item.target_agent_id);
            if (item.origin_channel) parts.push(item.origin_channel);
            if (item.updated_at || item.created_at) parts.push(UI.relativeTime(item.updated_at || item.created_at));
            if (item.event_count !== undefined) parts.push(`${item.event_count} ${item.event_count === 1 ? 'event' : 'events'}`);
            sub.textContent = parts.join(' · ');

            const row = UI.renderListRow({
                href: '/ui/conversations/' + item.conversation_id,
                label: item.title || item.conversation_id,
                sublabelNode: sub,
                badgeText: item.status || 'open',
                badgeClass: 'badge-' + (item.status || 'open'),
            });
            row.dataset.key = item.conversation_id;
            return row;
        });
        UI.reconcileChildren(listEl, rows);

        renderPaginationState({
            hasPrev: cursorStack.length > 0,
            hasNext: !!data.has_more,
            onPrev: () => {
                cursor = cursorStack.pop() || 0;
                loadPage();
            },
            onNext: () => {
                cursorStack.push(cursor);
                cursor = data.next_cursor;
                loadPage();
            },
        });
        hasLoaded = true;
    }

    function loadPage({ soft = false } = {}) {
        if (!soft || !hasLoaded) {
            UI.reconcileChildren(listEl, UI.createSkeletonNodes(6, 'row'));
            UI.reconcileChildren(pagEl, []);
        }
        const params = { cursor, limit };
        if (currentQ) params.q = currentQ;
        if (currentStatus) params.status = currentStatus;
        API.listConversations(params).then((data) => {
            renderRows(data.conversations || data || [], data);
        }).catch((err) => {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh conversations', err, { context: 'Conversation list soft refresh failed' });
                return;
            }
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load conversations: ' + err.message, loadPage)]);
            UI.reconcileChildren(pagEl, []);
        });
    }

    let quickStartReload = null;
    let listReload = null;
    cleanups.add(WS.subscribe('agents', () => {
        clearTimeout(quickStartReload);
        quickStartReload = setTimeout(() => loadQuickStart({ soft: true }), 350);
    }));
    cleanups.add(WS.subscribe('conversations', () => {
        clearTimeout(listReload);
        listReload = setTimeout(() => loadPage({ soft: true }), 350);
    }));

    syncStatusButtons();
    loadQuickStart();
    loadPage();

    cleanups.add(() => clearTimeout(searchTimeout));
    cleanups.add(() => clearTimeout(quickStartReload));
    cleanups.add(() => clearTimeout(listReload));
}
