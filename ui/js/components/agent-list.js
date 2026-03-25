/**
 * Agent list — home view showing all enrolled agents with pagination.
 */
function renderAgentList(container) {
    const cleanups = UI.beginCleanupScope();
    let cursor = 0;
    const limit = UI.DEFAULT_PAGE_LIMIT;
    let cursorStack = []; // stack of previous cursors for "prev"
    let nameFilter = UI.readQueryParam('q', '');
    let stateFilter = UI.readQueryParam('state', '');
    let hasLoaded = false;
    let activeConversationOpen = '';

    // Shell
    const header = document.createElement('div');
    header.className = 'page-header';
    header.innerHTML = '<h2>Agents</h2><p>See which agents are healthy, which ones are struggling, and where to drill in when work slows down.</p>';
    container.appendChild(header);

    // Filter bar
    const filterBar = document.createElement('div');
    filterBar.className = 'filter-bar';

    const searchInput = document.createElement('input');
    searchInput.className = 'search-input';
    searchInput.placeholder = 'Search agents';
    searchInput.type = 'text';
    searchInput.setAttribute('aria-label', 'Filter agents by name');
    searchInput.setAttribute('title', 'Press / to focus search');
    filterBar.appendChild(searchInput);

    const searchHint = document.createElement('span');
    searchHint.className = 'search-shortcut-hint';
    searchHint.textContent = 'Shortcut: /';
    filterBar.appendChild(searchHint);

    const stateSelect = document.createElement('select');
    stateSelect.setAttribute('aria-label', 'Filter agents by connectivity state');
    stateSelect.innerHTML = '<option value="">All states</option>' +
        '<option value="connected">Connected</option>' +
        '<option value="degraded">Degraded</option>' +
        '<option value="disconnected">Disconnected</option>' +
        '<option value="offline">Offline</option>';
    filterBar.appendChild(stateSelect);

    container.appendChild(filterBar);

    const listEl = document.createElement('div');
    listEl.id = 'agent-list-content';
    listEl.className = 'list-container';
    container.appendChild(listEl);

    const pagEl = document.createElement('div');
    pagEl.id = 'agent-list-pagination';
    container.appendChild(pagEl);

    // Debounced search (client-side filter on current page)
    let searchTimeout = null;
    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            nameFilter = searchInput.value.trim();
            cursor = 0;
            cursorStack = [];
            UI.updateQueryParams({ q: nameFilter, state: stateFilter });
            loadPage();
        }, 300);
    });

    stateSelect.addEventListener('change', () => {
        stateFilter = stateSelect.value;
        cursor = 0;
        cursorStack = [];
        UI.updateQueryParams({ q: nameFilter, state: stateFilter });
        loadPage();
    });
    searchInput.value = nameFilter;
    stateSelect.value = stateFilter;

    function loadPage({ soft = false } = {}) {
        if (!soft || !hasLoaded) {
            UI.reconcileChildren(listEl, UI.createSkeletonNodes(5, 'row'));
            UI.reconcileChildren(pagEl, []);
        }

        API.listAgents({ cursor, limit, q: nameFilter, state: stateFilter }).then(data => {
            const agents = data.agents || data || [];
            renderCards(agents, data.has_more, data.next_cursor);
            hasLoaded = true;
        }).catch(err => {
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load agents: ' + err.message, loadPage)]);
            UI.reconcileChildren(pagEl, []);
        });
    }

    function renderCards(agents, hasMore, nextCursor) {
        if (agents.length === 0) {
            UI.reconcileChildren(listEl, [UI.renderEmptyState(nameFilter || stateFilter ? 'No agents match filters' : 'No agents enrolled')]);
            UI.reconcileChildren(pagEl, []);
            return;
        }

        const rows = agents.map((a) => {
            const shell = document.createElement('div');
            shell.className = 'list-row-shell';
            shell.dataset.key = a.agent_id;

            const sub = document.createElement('span');
            const parts = [a.role || 'agent', a.provider || '', a.slug].filter(Boolean);
            sub.appendChild(document.createTextNode(parts.join(' \u00b7 ')));
            const heartbeat = document.createElement('span');
            heartbeat.setAttribute('data-timestamp', a.last_heartbeat_at || '');
            heartbeat.textContent = a.last_heartbeat_at ? UI.relativeTime(a.last_heartbeat_at) : '';
            if (parts.length && heartbeat.textContent) {
                sub.appendChild(document.createTextNode(' \u00b7 '));
            }
            if (heartbeat.textContent) {
                sub.appendChild(heartbeat);
            }

            const row = UI.renderListRow({
                href: '/ui/agents/' + a.agent_id,
                label: a.display_name || a.slug,
                sublabelNode: sub,
                badgeText: a.connectivity_state || 'unknown',
                badgeClass: 'badge-' + (a.connectivity_state || 'stopped'),
            });
            row.id = 'agent-badge-' + a.agent_id;
            shell.appendChild(row);

            const actionBtn = document.createElement('button');
            actionBtn.type = 'button';
            actionBtn.className = 'btn btn-sm list-row-action';
            actionBtn.textContent = 'Open conversation';
            actionBtn.setAttribute('aria-label', `Open or start a conversation with ${a.display_name || a.slug || a.agent_id}`);
            actionBtn.addEventListener('click', async () => {
                if (activeConversationOpen === a.agent_id) return;
                activeConversationOpen = a.agent_id;
                actionBtn.disabled = true;
                actionBtn.textContent = 'Opening…';
                try {
                    const conversation = await API.openConversationForAgent(a.agent_id, {
                        title: `Conversation with ${a.display_name || a.slug || a.agent_id}`,
                    });
                    Router.navigate('/ui/conversations/' + conversation.conversation_id);
                } catch (err) {
                    UI.reportError('Failed to open a conversation for this agent', err, { context: 'Agent list open conversation failed' });
                    actionBtn.disabled = false;
                    actionBtn.textContent = 'Open conversation';
                    activeConversationOpen = '';
                }
            });
            shell.appendChild(actionBtn);
            return shell;
        });
        UI.reconcileChildren(listEl, rows);

        // Pagination
        const wrapper = document.createElement('div');
        UI.renderPagination(wrapper, {
            hasPrev: cursorStack.length > 0,
            hasNext: !!hasMore,
            info: '',
            onPrev: () => {
                cursor = cursorStack.pop() || 0;
                loadPage();
            },
            onNext: () => {
                cursorStack.push(cursor);
                cursor = nextCursor;
                loadPage();
            },
        });
        UI.reconcileChildren(pagEl, Array.from(wrapper.childNodes));
    }

    let reloadDebounce = null;
    cleanups.add(WS.subscribe('agents', () => {
        clearTimeout(reloadDebounce);
        reloadDebounce = setTimeout(() => loadPage({ soft: true }), 400);
    }));

    loadPage();
    cleanups.add(() => clearTimeout(searchTimeout));
    cleanups.add(() => clearTimeout(reloadDebounce));
}
