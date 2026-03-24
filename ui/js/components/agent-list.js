/**
 * Agent list — home view showing all enrolled agents with pagination.
 */
function renderAgentList(container) {
    const cleanups = UI.beginCleanupScope();
    let cursor = 0;
    const limit = UI.DEFAULT_PAGE_LIMIT;
    let cursorStack = []; // stack of previous cursors for "prev"
    let nameFilter = '';
    let stateFilter = '';

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
        '<option value="stopped">Stopped</option>';
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
            nameFilter = searchInput.value.trim().toLowerCase();
            cursor = 0;
            cursorStack = [];
            loadPage();
        }, 300);
    });

    stateSelect.addEventListener('change', () => {
        stateFilter = stateSelect.value;
        cursor = 0;
        cursorStack = [];
        loadPage();
    });

    let lastData = null;

    function loadPage() {
        listEl.textContent = '';
        UI.renderSkeletons(listEl, 5, 'row');

        API.listAgents({ cursor, limit }).then(data => {
            lastData = data;
            const agents = data.agents || data || [];
            renderCards(agents, data.has_more, data.next_cursor);
        }).catch(err => {
            listEl.textContent = '';
            UI.renderError(listEl, 'Failed to load agents: ' + err.message, loadPage);
        });
    }

    function renderCards(agents, hasMore, nextCursor) {
        listEl.textContent = '';
        pagEl.textContent = '';

        // Client-side name filter
        let filtered = agents;
        if (nameFilter) {
            filtered = agents.filter(a => {
                const name = (a.display_name || a.slug || '').toLowerCase();
                return name.includes(nameFilter);
            });
        }
        if (stateFilter) {
            filtered = filtered.filter(a => a.connectivity_state === stateFilter);
        }

        if (filtered.length === 0) {
            listEl.appendChild(UI.renderEmptyState(agents.length === 0 ? 'No agents enrolled' : 'No agents match filters'));
            return;
        }

        filtered.forEach(a => {
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
            listEl.appendChild(row);
        });

        // Pagination
        UI.renderPagination(pagEl, {
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
    }

    // WS: subscribe to * for heartbeat + event updates
    let reloadDebounce = null;
    const unsub = WS.subscribe('*', (msg) => {
        if (msg.type === 'heartbeat' && msg.data) {
            const row = document.getElementById('agent-badge-' + msg.data.agent_id);
            const badge = row && row.querySelector('.badge');
            if (badge && msg.data.connectivity_state) {
                badge.className = 'badge badge-' + msg.data.connectivity_state;
                badge.textContent = msg.data.connectivity_state;
            }
        }
        // Reload agent list on any event (new conversations change counts)
        if (msg.type === 'event') {
            clearTimeout(reloadDebounce);
            reloadDebounce = setTimeout(loadPage, 2000);
        }
    });
    cleanups.add(unsub);

    loadPage();
    cleanups.add(() => clearTimeout(searchTimeout));
    cleanups.add(() => clearTimeout(reloadDebounce));
}
