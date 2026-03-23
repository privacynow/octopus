/**
 * Agent list — home view showing all enrolled agents with pagination.
 */
function renderAgentList(container) {
    let cursor = 0;
    const limit = 25;
    let cursorStack = []; // stack of previous cursors for "prev"
    let nameFilter = '';
    let stateFilter = '';
    const cleanups = [];

    // Shell
    const header = document.createElement('div');
    header.className = 'page-header';
    header.innerHTML = '<h2>Agents</h2><p>Enrolled bots and their current status</p>';
    container.appendChild(header);

    // Filter bar
    const filterBar = document.createElement('div');
    filterBar.className = 'filter-bar';

    const searchInput = document.createElement('input');
    searchInput.className = 'search-input';
    searchInput.placeholder = 'Filter by name...';
    searchInput.type = 'text';
    filterBar.appendChild(searchInput);

    const stateSelect = document.createElement('select');
    stateSelect.innerHTML = '<option value="">All states</option>' +
        '<option value="connected">Connected</option>' +
        '<option value="degraded">Degraded</option>' +
        '<option value="stopped">Stopped</option>';
    filterBar.appendChild(stateSelect);

    container.appendChild(filterBar);

    const listEl = document.createElement('div');
    listEl.id = 'agent-list-content';
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
        _renderSkeletons(listEl, 5, 'card');

        API.listAgents({ cursor, limit }).then(data => {
            lastData = data;
            const agents = data.agents || data || [];
            renderCards(agents, data.has_more, data.next_cursor);
        }).catch(err => {
            listEl.textContent = '';
            _renderError(listEl, 'Failed to load agents: ' + err.message, loadPage);
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
            const empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.textContent = agents.length === 0 ? 'No agents enrolled' : 'No agents match filters';
            listEl.appendChild(empty);
            return;
        }

        filtered.forEach(a => {
            const card = document.createElement('div');
            card.className = 'card clickable';
            card.addEventListener('click', () => Router.navigate('/ui/agents/' + a.agent_id));

            const row = document.createElement('div');
            row.className = 'card-row';

            const info = document.createElement('div');
            const title = document.createElement('div');
            title.className = 'card-title';
            title.textContent = a.display_name || a.slug;
            info.appendChild(title);

            const sub = document.createElement('div');
            sub.className = 'card-subtitle';
            const parts = [a.role || 'agent', a.provider || '', a.slug].filter(Boolean);
            sub.textContent = parts.join(' \u00b7 ');
            info.appendChild(sub);

            const heartbeat = document.createElement('div');
            heartbeat.className = 'card-subtitle';
            heartbeat.setAttribute('data-timestamp', a.last_heartbeat_at || '');
            heartbeat.textContent = a.last_heartbeat_at ? _relativeTime(a.last_heartbeat_at) : '';
            info.appendChild(heartbeat);

            row.appendChild(info);

            const badge = document.createElement('span');
            badge.className = 'badge badge-' + (a.connectivity_state || 'stopped');
            badge.id = 'agent-badge-' + a.agent_id;
            badge.textContent = a.connectivity_state || 'unknown';
            row.appendChild(badge);

            card.appendChild(row);
            listEl.appendChild(card);
        });

        // Pagination
        _renderPagination(pagEl, {
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

    // WS: subscribe to * for heartbeat updates
    const unsub = WS.subscribe('*', (msg) => {
        if (msg.type === 'heartbeat' && msg.data) {
            const badge = document.getElementById('agent-badge-' + msg.data.agent_id);
            if (badge && msg.data.connectivity_state) {
                badge.className = 'badge badge-' + msg.data.connectivity_state;
                badge.textContent = msg.data.connectivity_state;
            }
        }
    });
    cleanups.push(unsub);

    loadPage();

    return function cleanup() {
        clearTimeout(searchTimeout);
        cleanups.forEach(fn => fn());
    };
}
