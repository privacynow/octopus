/**
 * Agent list — dense roster with direct conversation entry.
 */
function renderAgentList(container) {
    const cleanups = UI.beginCleanupScope();
    const limit = UI.DEFAULT_PAGE_LIMIT;
    let nameFilter = UI.readQueryParam('q', '');
    let stateFilter = UI.readQueryParam('state', '');
    let hasLoaded = false;
    let activeConversationOpen = '';
    let searchTimeout = null;
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Agents</h2>';
    container.appendChild(header);

    const shell = document.createElement('section');
    shell.className = 'admin-shell';
    container.appendChild(shell);

    const workbench = document.createElement('section');
    workbench.className = 'workbench-panel';
    shell.appendChild(workbench);

    const controls = document.createElement('div');
    controls.className = 'route-controls';
    workbench.appendChild(controls);

    const searchInput = document.createElement('input');
    searchInput.className = 'search-input';
    searchInput.placeholder = 'Search agents';
    searchInput.type = 'text';
    searchInput.setAttribute('aria-label', 'Filter agents by name');
    searchInput.setAttribute('title', 'Press / to focus search');
    controls.appendChild(searchInput);

    const states = [
        { key: 'all', value: '', label: 'All' },
        { key: 'connected', value: 'connected', label: 'Connected' },
        { key: 'degraded', value: 'degraded', label: 'Degraded' },
        { key: 'disconnected', value: 'disconnected', label: 'Disconnected' },
    ];
    const stateControl = UI.createSegmentedControl(states, (value) => applyStateFilter(value), {
        label: 'Agent state filter',
        value: stateFilter,
    });
    const stateBar = stateControl.element;
    controls.appendChild(stateBar);

    function applyStateFilter(value) {
        stateFilter = value;
        paginator.reset();
        stateControl.setActive(stateFilter);
        UI.updateQueryParams({ q: nameFilter, state: stateFilter });
        loadPage();
    }

    const listShell = document.createElement('section');
    listShell.className = 'list-shell';
    shell.appendChild(listShell);

    const listEl = document.createElement('div');
    listEl.id = 'agent-list-content';
    listEl.className = 'list-container';
    listShell.appendChild(listEl);

    const pagEl = document.createElement('div');
    pagEl.id = 'agent-list-pagination';
    pagEl.className = 'pagination-shell';
    listShell.appendChild(pagEl);
    const paginator = UI.createCursorPaginator(pagEl, () => loadPage());

    searchInput.value = nameFilter;

    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            nameFilter = searchInput.value.trim();
            paginator.reset();
            UI.updateQueryParams({ q: nameFilter, state: stateFilter });
            loadPage();
        }, 250);
    });

    function renderRows(agents, hasMore, nextCursor) {
        if (!agents.length) {
            const emptyMessage = nameFilter || stateFilter ? 'No agents match this view.' : 'No agents enrolled.';
            UI.clearMemoizedRender(listEl);
            UI.reconcileChildren(listEl, [UI.renderEmptyState(emptyMessage, true)]);
            paginator.clear();
            return;
        }

        UI.memoizedRender(listEl, {
            q: nameFilter,
            state: stateFilter,
            cursor: paginator.cursor,
            agents,
        }, (state) => state.agents.map((agent) => {
            const shell = document.createElement('div');
            shell.className = 'list-row-shell';
            shell.dataset.key = agent.agent_id;
            shell.dataset.signature = UI.dataSignature({
                id: String(agent.agent_id || ''),
                display: String(agent.display_name || agent.slug || ''),
                state: String(agent.connectivity_state || ''),
                heartbeatLabel: agent.last_heartbeat_at ? UI.relativeTime(agent.last_heartbeat_at) : '',
                role: String(agent.role || ''),
                provider: String(agent.provider || ''),
            });

            const sub = document.createElement('span');
            sub.textContent = [
                agent.role || 'agent',
                agent.provider || '',
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
        }), {
            signatureFn(state) {
                return {
                    q: String(state.q || ''),
                    state: String(state.state || ''),
                    cursor: state.cursor,
                    agents: (state.agents || []).map((agent) => ({
                        id: String(agent.agent_id || ''),
                        state: String(agent.connectivity_state || ''),
                        heartbeatLabel: agent.last_heartbeat_at ? UI.relativeTime(agent.last_heartbeat_at) : '',
                        display: String(agent.display_name || agent.slug || ''),
                        role: String(agent.role || ''),
                        provider: String(agent.provider || ''),
                    })),
                };
            },
        });
        paginator.render({ hasMore: !!hasMore, nextCursor });
    }

    async function loadPage({ soft = false } = {}) {
        try {
            const data = await API.listAgents({ cursor: paginator.cursor, limit, q: nameFilter, state: stateFilter });
            renderRows(data.agents || data || [], data.has_more, data.next_cursor);
            hasLoaded = true;
        } catch (err) {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh agents', err, { context: 'Agent list soft refresh failed' });
                return;
            }
            UI.clearMemoizedRender(listEl);
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load agents: ' + err.message, loadPage)]);
            paginator.clear();
        }
    }

    stateControl.setActive(stateFilter);
    container.__routeReady = loadPage();

    cleanups.add(() => clearTimeout(searchTimeout));
    UI.subscribeWithRefresh(cleanups, 'agents', () => loadPage({ soft: true }), 350);
}
