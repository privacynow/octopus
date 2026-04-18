/**
 * Agent list — kit-driven presence roster with direct conversation entry.
 *
 * Uses Kit.agentsList for the list + filter chrome so the agents surface
 * shares the same design language as runs/protocols (plan §7, Step 8).
 */
function renderAgentList(container) {
    const cleanups = UI.beginCleanupScope();
    const limit = UI.DEFAULT_PAGE_LIMIT;
    let nameFilter = UI.readQueryParam('q', '');
    let presenceFilter = UI.readQueryParam('state', '');
    let hasLoaded = false;
    let searchTimeout = null;
    let currentAgents = [];
    let currentPagination = { hasMore: false, nextCursor: '' };
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Agents</h2><p>Inspect presence, workload, skills, and admin actions for every enrolled agent.</p>';
    container.appendChild(header);

    const shell = document.createElement('section');
    shell.className = 'admin-shell';
    container.appendChild(shell);

    const workbench = document.createElement('section');
    workbench.className = 'workbench-panel';
    shell.appendChild(workbench);

    const listHost = document.createElement('div');
    listHost.className = 'kit-agents-host';
    workbench.appendChild(listHost);

    const pagEl = document.createElement('div');
    pagEl.className = 'pagination-shell';
    workbench.appendChild(pagEl);
    const paginator = UI.createCursorPaginator(pagEl, () => loadPage());

    function _executionFaulted(agent) {
        return String(agent.execution_state || 'healthy') === 'faulted';
    }

    function _adaptAgent(agent) {
        return {
            id: String(agent.agent_id || ''),
            slug: String(agent.slug || ''),
            displayName: String(agent.display_name || agent.slug || agent.agent_id || ''),
            role: String(agent.role || ''),
            provider: String(agent.provider || ''),
            presence: String(agent.connectivity_state || 'stopped'),
            trustTier: String(agent.trust_tier || 'community'),
            currentCapacity: Number(agent.current_capacity || 0),
            maxCapacity: Number(agent.max_capacity || 1),
            routingSkills: Array.isArray(agent.routing_skills) ? agent.routing_skills : [],
            executionState: String(agent.execution_state || 'healthy'),
            executionFaulted: _executionFaulted(agent),
            lastHeartbeat: String(agent.last_heartbeat_at || ''),
            softDeletedAt: String(agent.soft_deleted_at || ''),
            _raw: agent,
        };
    }

    function _repaintList() {
        const adapted = currentAgents.map(_adaptAgent);
        const node = Kit.agentsList({
            agents: adapted,
            search: nameFilter,
            presenceFilter,
            onSearch: (value) => {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(() => {
                    nameFilter = value.trim();
                    paginator.reset();
                    UI.updateQueryParams({ q: nameFilter, state: presenceFilter });
                    loadPage();
                }, 250);
            },
            onPresenceFilter: (value) => {
                presenceFilter = value || '';
                paginator.reset();
                UI.updateQueryParams({ q: nameFilter, state: presenceFilter });
                loadPage();
            },
            onSelect: (agent) => {
                Router.navigate('/ui/agents/' + encodeURIComponent(agent.id));
            },
        });
        UI.reconcileChildren(listHost, [node]);
        paginator.render({
            hasMore: !!currentPagination.hasMore,
            nextCursor: currentPagination.nextCursor,
        });
    }

    async function loadPage({ soft = false } = {}) {
        try {
            const data = await API.listAgents({
                cursor: paginator.cursor,
                limit,
                q: nameFilter,
                state: presenceFilter,
            });
            currentAgents = data.agents || data || [];
            currentPagination = {
                hasMore: !!data.has_more,
                nextCursor: data.next_cursor || '',
            };
            _repaintList();
            hasLoaded = true;
        } catch (err) {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh agents', err, { context: 'Agent list soft refresh failed' });
                return;
            }
            UI.reconcileChildren(listHost, [UI.createErrorCard('Failed to load agents: ' + err.message, loadPage)]);
            paginator.clear();
        }
    }

    container.__routeReady = loadPage();

    cleanups.add(() => clearTimeout(searchTimeout));
    UI.subscribeWithRefresh(cleanups, 'agents', () => loadPage({ soft: true }), 350);
}
