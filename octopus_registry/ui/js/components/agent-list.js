/**
 * Agent list - kit-driven roster with direct conversation entry.
 *
 * Uses Kit.agentsList for the list + filter chrome so the agents surface
 * shares the same design language as runs/protocols (plan §7, Step 8).
 */
function renderAgentList(container) {
    const cleanups = UI.beginCleanupScope();
    const limit = UI.DEFAULT_PAGE_LIMIT;
    let nameFilter = UI.readQueryParam('q', '');
    let presenceFilter = UI.readQueryParam('state', '');
    let includeGenerated = UI.readQueryParam('include_generated', '') === '1';
    let selectedAgentId = UI.readQueryParam('agent_id', '');
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
    header.innerHTML = '<h2>Agents</h2><p>Start work with a real enrolled agent, inspect its skills, or open recent activity.</p>';
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
    const generatedToggle = document.createElement('a');
    controls.appendChild(generatedToggle);

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

    function _updateGeneratedToggle() {
        UI.updateGeneratedAuditToggleLink(generatedToggle, includeGenerated, 'agents');
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

    function _selectedAgentVisible(agents) {
        if (!selectedAgentId) return true;
        return (agents || []).some((agent) => String(agent.id || '') === String(selectedAgentId || ''));
    }

    function _agentWorkspaceHref(agent) {
        return '/ui/agents/' + encodeURIComponent(agent.id || agent.agent_id || '');
    }

    function _agentSkillsHref(agent) {
        return '/ui/skills?agent_id=' + encodeURIComponent(agent.id || agent.agent_id || '');
    }

    function _renderAgentInlineDetail(agent) {
        const raw = agent?._raw || agent || {};
        const panel = document.createElement('section');
        panel.className = 'conversation-inline-detail';
        panel.dataset.key = `agent-inline-detail:${String(agent?.id || raw.agent_id || '')}`;

        const title = document.createElement('h3');
        title.textContent = String(agent?.displayName || raw.display_name || raw.slug || 'Agent');
        panel.appendChild(title);

        panel.appendChild(Kit.agentSummary({ agent: raw }));

        const actions = document.createElement('div');
        actions.className = 'editor-actions';

        const openProfile = document.createElement('a');
        openProfile.className = 'btn btn-sm';
        openProfile.href = _agentWorkspaceHref(agent || raw);
        openProfile.textContent = 'Open agent workspace';
        actions.appendChild(openProfile);

        const openSkills = document.createElement('a');
        openSkills.className = 'btn btn-sm';
        openSkills.href = _agentSkillsHref(agent || raw);
        openSkills.textContent = 'Open skills';
        actions.appendChild(openSkills);

        panel.appendChild(actions);
        return panel;
    }

    function _repaintList() {
        _updateGeneratedToggle();
        const adapted = UI.defaultVisibleRecords(currentAgents, { includeHidden: includeGenerated }).map(_adaptAgent);
        if (!_selectedAgentVisible(adapted)) {
            selectedAgentId = '';
            UI.updateQueryParams({ q: nameFilter, state: presenceFilter, include_generated: includeGenerated ? '1' : '', agent_id: '' });
        }
        const node = Kit.agentsList({
            agents: adapted,
            search: nameFilter,
            presenceFilter,
            selectedId: selectedAgentId,
            onSearch: (value) => {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(() => {
                    nameFilter = value.trim();
                    paginator.reset();
                    UI.updateQueryParams({ q: nameFilter, state: presenceFilter, include_generated: includeGenerated ? '1' : '', agent_id: selectedAgentId || '' });
                    loadPage();
                }, 250);
            },
            onPresenceFilter: (value) => {
                presenceFilter = value || '';
                paginator.reset();
                UI.updateQueryParams({ q: nameFilter, state: presenceFilter, include_generated: includeGenerated ? '1' : '', agent_id: selectedAgentId || '' });
                loadPage();
            },
            onSelect: (agent) => {
                selectedAgentId = String(selectedAgentId || '') === String(agent.id || '') ? '' : String(agent.id || '');
                UI.updateQueryParams({ q: nameFilter, state: presenceFilter, include_generated: includeGenerated ? '1' : '', agent_id: selectedAgentId || '' });
                _repaintList();
            },
            onStartConversation: async (agent) => {
                try {
                    const result = await API.openConversationForAgent(agent.id, { preferExisting: false });
                    const conversationId = String(result.conversation_id || result.id || '');
                    if (conversationId) {
                        Router.navigate('/ui/conversations/' + encodeURIComponent(conversationId));
                    }
                } catch (err) {
                    UI.reportError('Failed to open conversation', err, { context: 'Agent conversation open failed' });
                }
            },
            renderExpanded: _renderAgentInlineDetail,
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
