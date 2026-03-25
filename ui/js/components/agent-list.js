/**
 * Agent list — dense roster with direct conversation entry.
 */
function renderAgentList(container) {
    const cleanups = UI.beginCleanupScope();
    let cursor = 0;
    const limit = UI.DEFAULT_PAGE_LIMIT;
    let cursorStack = [];
    let nameFilter = UI.readQueryParam('q', '');
    let stateFilter = UI.readQueryParam('state', '');
    let hasLoaded = false;
    let activeConversationOpen = '';
    let searchTimeout = null;

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Agents</h2>';
    container.appendChild(header);

    const controls = document.createElement('div');
    controls.className = 'route-controls';
    container.appendChild(controls);

    const searchInput = document.createElement('input');
    searchInput.className = 'search-input';
    searchInput.placeholder = 'Search agents';
    searchInput.type = 'text';
    searchInput.setAttribute('aria-label', 'Filter agents by name');
    searchInput.setAttribute('title', 'Press / to focus search');
    controls.appendChild(searchInput);

    const stateBar = document.createElement('div');
    stateBar.className = 'segmented-control';
    stateBar.setAttribute('role', 'tablist');
    stateBar.setAttribute('aria-label', 'Agent state filter');
    controls.appendChild(stateBar);

    const states = [
        ['all', '', 'All'],
        ['connected', 'connected', 'Connected'],
        ['degraded', 'degraded', 'Degraded'],
        ['disconnected', 'disconnected', 'Disconnected'],
        ['offline', 'offline', 'Offline'],
    ];

    function applyStateFilter(value) {
        stateFilter = value;
        cursor = 0;
        cursorStack = [];
        syncStateButtons();
        UI.updateQueryParams({ q: nameFilter, state: stateFilter });
        loadPage();
    }

    states.forEach(([key, value, label]) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'segmented-control-btn';
        btn.dataset.key = key;
        btn.dataset.value = value;
        btn.textContent = label;
        btn.setAttribute('role', 'tab');
        btn.setAttribute('aria-selected', String(stateFilter === value));
        btn.tabIndex = stateFilter === value ? 0 : -1;
        if (stateFilter === value) btn.classList.add('active');
        btn.addEventListener('click', () => applyStateFilter(value));
        stateBar.appendChild(btn);
    });
    UI.bindSegmentedControlKeyboard(stateBar, (target) => applyStateFilter(target.dataset.value || ''));

    const listShell = document.createElement('section');
    listShell.className = 'list-shell';
    container.appendChild(listShell);

    const listEl = document.createElement('div');
    listEl.id = 'agent-list-content';
    listEl.className = 'list-container';
    listShell.appendChild(listEl);

    const pagEl = document.createElement('div');
    pagEl.id = 'agent-list-pagination';
    pagEl.className = 'pagination-shell';
    listShell.appendChild(pagEl);

    searchInput.value = nameFilter;

    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            nameFilter = searchInput.value.trim();
            cursor = 0;
            cursorStack = [];
            UI.updateQueryParams({ q: nameFilter, state: stateFilter });
            loadPage();
        }, 250);
    });

    function syncStateButtons() {
        stateBar.querySelectorAll('.segmented-control-btn').forEach((btn) => {
            const match = states.find(([key]) => key === btn.dataset.key);
            const active = !!match && stateFilter === match[1];
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

    function renderRows(agents, hasMore, nextCursor) {
        if (!agents.length) {
            const emptyMessage = nameFilter || stateFilter ? 'No agents match this view.' : 'No agents enrolled.';
            UI.reconcileChildren(listEl, [UI.renderEmptyState(emptyMessage, true)]);
            UI.reconcileChildren(pagEl, []);
            return;
        }

        const rows = agents.map((agent) => {
            const shell = document.createElement('div');
            shell.className = 'list-row-shell';
            shell.dataset.key = agent.agent_id;

            const sub = document.createElement('span');
            sub.textContent = [
                agent.role || 'agent',
                agent.provider || '',
                agent.slug || '',
                agent.last_heartbeat_at ? UI.relativeTime(agent.last_heartbeat_at) : '',
            ].filter(Boolean).join(' · ');

            const row = UI.renderListRow({
                href: '/ui/agents/' + agent.agent_id,
                label: agent.display_name || agent.slug || agent.agent_id,
                sublabelNode: sub,
                badgeText: agent.connectivity_state || 'unknown',
                badgeClass: 'badge-' + (agent.connectivity_state || 'stopped'),
            });
            shell.appendChild(row);

            const actionBtn = document.createElement('button');
            actionBtn.type = 'button';
            actionBtn.className = 'btn btn-sm list-row-action';
            actionBtn.textContent = 'Open';
            actionBtn.setAttribute('aria-label', `Open or start a conversation with ${agent.display_name || agent.slug || agent.agent_id}`);
            actionBtn.addEventListener('click', async () => {
                if (activeConversationOpen === agent.agent_id) return;
                activeConversationOpen = agent.agent_id;
                actionBtn.disabled = true;
                actionBtn.textContent = 'Opening…';
                try {
                    const conversation = await API.openConversationForAgent(agent.agent_id, {
                        title: `Conversation with ${agent.display_name || agent.slug || agent.agent_id}`,
                    });
                    Router.navigate('/ui/conversations/' + conversation.conversation_id);
                } catch (err) {
                    UI.reportError('Failed to open a conversation for this agent', err, { context: 'Agent list open conversation failed' });
                    actionBtn.disabled = false;
                    actionBtn.textContent = 'Open';
                    activeConversationOpen = '';
                }
            });
            shell.appendChild(actionBtn);

            return shell;
        });
        UI.reconcileChildren(listEl, rows);

        renderPaginationState({
            hasPrev: cursorStack.length > 0,
            hasNext: !!hasMore,
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

    function loadPage({ soft = false } = {}) {
        if (!soft || !hasLoaded) {
            UI.reconcileChildren(listEl, UI.createSkeletonNodes(6, 'row'));
            UI.reconcileChildren(pagEl, []);
        }
        API.listAgents({ cursor, limit, q: nameFilter, state: stateFilter }).then((data) => {
            renderRows(data.agents || data || [], data.has_more, data.next_cursor);
            hasLoaded = true;
        }).catch((err) => {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh agents', err, { context: 'Agent list soft refresh failed' });
                return;
            }
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load agents: ' + err.message, loadPage)]);
            UI.reconcileChildren(pagEl, []);
        });
    }

    let reloadDebounce = null;
    cleanups.add(WS.subscribe('agents', () => {
        clearTimeout(reloadDebounce);
        reloadDebounce = setTimeout(() => loadPage({ soft: true }), 350);
    }));

    syncStateButtons();
    loadPage();

    cleanups.add(() => clearTimeout(searchTimeout));
    cleanups.add(() => clearTimeout(reloadDebounce));
}
