/**
 * Conversation list — all conversations with search/filter and pagination.
 */
function renderConversationList(container) {
    const cleanups = UI.beginCleanupScope();
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }
    let cursor = 0;
    let cursorStack = [];
    const limit = UI.DEFAULT_PAGE_LIMIT;
    let currentQ = UI.readQueryParam('q', '');
    let currentStatus = UI.readQueryParam('status', '');
    let searchTimeout = null;
    let hasLoaded = false;
    let quickStartLoaded = false;
    let openingConversationFor = '';
    const statusOptions = [
        { label: 'All', value: '' },
        { label: 'Open', value: 'open' },
        { label: 'Running', value: 'running' },
        { label: 'Done', value: 'completed' },
        { label: 'Failed', value: 'failed' },
    ];

    // Header
    const header = document.createElement('div');
    header.className = 'page-header page-header-inline page-header-tight';
    const titleWrap = document.createElement('div');
    titleWrap.className = 'page-header-title-wrap';
    titleWrap.innerHTML = '<h2>Conversations</h2>';
    header.appendChild(titleWrap);

    const headerActions = document.createElement('div');
    headerActions.className = 'page-header-actions page-header-actions-inline';
    const allAgents = document.createElement('a');
    allAgents.href = '/ui/agents';
    allAgents.className = 'section-link';
    allAgents.textContent = 'Agents';
    headerActions.appendChild(allAgents);
    const approvalsLink = document.createElement('a');
    approvalsLink.href = '/ui/approvals';
    approvalsLink.className = 'section-link';
    approvalsLink.textContent = 'Approvals';
    headerActions.appendChild(approvalsLink);
    header.appendChild(headerActions);
    container.appendChild(header);

    const quickStart = document.createElement('section');
    quickStart.className = 'conversation-launcher-panel conversation-launcher-panel-compact';
    container.appendChild(quickStart);

    // Filter bar
    const filterBar = document.createElement('div');
    filterBar.className = 'filter-bar';

    const searchInput = document.createElement('input');
    searchInput.className = 'search-input';
    searchInput.placeholder = 'Search';
    searchInput.type = 'text';
    searchInput.setAttribute('aria-label', 'Search conversations');
    filterBar.appendChild(searchInput);

    const statusBar = document.createElement('div');
    statusBar.className = 'segmented-control';
    statusBar.setAttribute('role', 'tablist');
    statusBar.setAttribute('aria-label', 'Filter conversations by status');
    filterBar.appendChild(statusBar);

    container.appendChild(filterBar);

    const listEl = document.createElement('div');
    listEl.className = 'list-container';
    container.appendChild(listEl);

    const pagEl = document.createElement('div');
    container.appendChild(pagEl);

    // Debounced search
    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            const q = searchInput.value.trim();
            currentQ = q;
            cursor = 0;
            cursorStack = [];
            UI.updateQueryParams({ q: currentQ, status: currentStatus });
            loadPage();
        }, 300);
    });

    searchInput.value = currentQ;

    function renderStatusFilters() {
        const buttons = statusOptions.map((option) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = `segmented-control-btn${option.value === currentStatus ? ' active' : ''}`;
            btn.textContent = option.label;
            btn.setAttribute('role', 'tab');
            btn.setAttribute('aria-selected', String(option.value === currentStatus));
            btn.tabIndex = option.value === currentStatus ? 0 : -1;
            btn.dataset.key = option.value || 'all';
            btn.addEventListener('click', () => {
                if (option.value === currentStatus) return;
                currentStatus = option.value;
                cursor = 0;
                cursorStack = [];
                UI.updateQueryParams({ q: currentQ, status: currentStatus });
                renderStatusFilters();
                loadPage();
            });
            return btn;
        });
        UI.reconcileChildren(statusBar, buttons);
    }
    renderStatusFilters();

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

    function renderQuickStart(agents) {
        const connected = [...agents].sort((a, b) =>
            String(a.display_name || a.slug || a.agent_id).localeCompare(String(b.display_name || b.slug || b.agent_id))
        );
        if (!connected.length) {
            UI.reconcileChildren(quickStart, []);
            return;
        }
        const shell = document.createElement('div');
        shell.className = 'conversation-launcher conversation-launcher-compact';
        shell.dataset.key = 'launcher-shell';

        const launcherList = document.createElement('div');
        launcherList.className = 'conversation-launcher-list';
        launcherList.dataset.key = 'launcher-list';

        connected.slice(0, 16).forEach((agent) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'conversation-launcher-chip';
            button.dataset.key = agent.agent_id;
            button.setAttribute('aria-label', `Open or start a conversation with ${agent.display_name || agent.slug || agent.agent_id}`);
            button.title = [agent.role || 'agent', agent.provider || '', agent.slug || ''].filter(Boolean).join(' · ');
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
                    UI.reportError('Failed to open a conversation for this agent', err, { context: 'Conversation list quick start failed' });
                }
            });

            launcherList.appendChild(button);
        });
        if (connected.length > 16) {
            const moreLink = document.createElement('a');
            moreLink.href = '/ui/agents';
            moreLink.className = 'conversation-launcher-chip conversation-launcher-chip-link';
            moreLink.textContent = `+${connected.length - 16}`;
            launcherList.appendChild(moreLink);
        }

        shell.appendChild(launcherList);
        UI.reconcileChildren(quickStart, [shell]);
    }

    function loadQuickStart({ soft = false } = {}) {
        API.listAgents({ state: 'connected', limit: 32 }).then((data) => {
            renderQuickStart(data.agents || data || []);
            quickStartLoaded = true;
        }).catch((err) => {
            if (soft && quickStartLoaded) {
                UI.reportError('Failed to refresh connected agents', err, { context: 'Conversation quick start soft refresh failed' });
                return;
            }
            UI.reconcileChildren(quickStart, []);
        });
    }

    function loadPage({ soft = false } = {}) {
        if (!soft || !hasLoaded) {
            UI.reconcileChildren(listEl, UI.createSkeletonNodes(5, 'row'));
            UI.reconcileChildren(pagEl, []);
        }

        const params = { cursor, limit };
        if (currentQ) params.q = currentQ;
        if (currentStatus) params.status = currentStatus;

        API.listConversations(params).then(data => {
            const convos = data.conversations || data || [];

            if (convos.length === 0) {
                UI.reconcileChildren(listEl, [UI.renderEmptyState(currentQ || currentStatus ? 'No matches.' : 'No conversations yet.', true)]);
                UI.reconcileChildren(pagEl, []);
                return;
            }

            const rows = convos.map(c => {
                const sub = document.createElement('span');
                const prefixParts = [];
                if (c.target_display_name || c.target_agent_id) {
                    prefixParts.push(c.target_display_name || c.target_agent_id);
                }
                if (c.origin_channel) prefixParts.push(c.origin_channel);
                if (prefixParts.length > 0) {
                    sub.appendChild(document.createTextNode(prefixParts.join(' \u00b7 ') + ' \u00b7 '));
                }
                const timeSpan = document.createElement('span');
                timeSpan.setAttribute('data-timestamp', c.updated_at || c.created_at || '');
                timeSpan.textContent = UI.relativeTime(c.updated_at || c.created_at);
                sub.appendChild(timeSpan);
                if (c.event_count !== undefined) {
                    sub.appendChild(document.createTextNode(' \u00b7 ' + c.event_count + ' events'));
                }
                const row = UI.renderListRow({
                    href: '/ui/conversations/' + c.conversation_id,
                    label: c.title || c.conversation_id,
                    sublabelNode: sub,
                    badgeText: c.status || 'open',
                    badgeClass: 'badge-' + (c.status || 'open'),
                });
                row.dataset.key = c.conversation_id;
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
        }).catch(err => {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh conversations', err, { context: 'Conversation list soft refresh failed' });
                return;
            }
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed: ' + err.message, loadPage)]);
            UI.reconcileChildren(pagEl, []);
        });
    }

    loadQuickStart();
    loadPage();

    let reloadDebounce = null;
    cleanups.add(WS.subscribe('conversations', () => {
        clearTimeout(reloadDebounce);
        reloadDebounce = setTimeout(() => loadPage({ soft: true }), 400);
    }));
    cleanups.add(WS.subscribe('agents', () => {
        clearTimeout(reloadDebounce);
        reloadDebounce = setTimeout(() => loadQuickStart({ soft: true }), 400);
    }));

    cleanups.add(() => clearTimeout(searchTimeout));
    cleanups.add(() => clearTimeout(reloadDebounce));
}
