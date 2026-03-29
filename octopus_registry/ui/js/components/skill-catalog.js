/**
 * Skill catalog — dense installable runtime skill roster.
 */
function renderSkillCatalog(container) {
    const cleanups = UI.beginCleanupScope();
    let searchTimeout = null;
    let currentQ = '';
    let allSkills = [];
    let availableAgents = [];
    let currentAgentId = '';

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Skills</h2>';
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

    const agentDropdown = UI.createAgentManagementDropdown([], '', (nextAgentId) => {
        currentAgentId = nextAgentId;
        _writeAgentId(currentAgentId);
        loadSkills();
    });
    const agentSelect = agentDropdown.element;
    controls.appendChild(agentSelect);

    const searchInput = document.createElement('input');
    searchInput.className = 'search-input';
    searchInput.placeholder = 'Search skills';
    searchInput.type = 'text';
    searchInput.setAttribute('aria-label', 'Search skills');
    controls.appendChild(searchInput);

    const listWrap = document.createElement('section');
    listWrap.className = 'list-shell';
    shell.appendChild(listWrap);

    const listEl = document.createElement('div');
    listEl.className = 'list-container';
    listWrap.appendChild(listEl);

    function _readAgentId() {
        try {
            return new URL(window.location.href).searchParams.get('agent_id') || '';
        } catch {
            return '';
        }
    }

    function _writeAgentId(agentId) {
        try {
            const url = new URL(window.location.href);
            if (agentId) {
                url.searchParams.set('agent_id', agentId);
            } else {
                url.searchParams.delete('agent_id');
            }
            history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
        } catch {
            // Ignore URL update failures.
        }
    }

    function _managementAgents(capability) {
        return availableAgents.filter((agent) => {
            const connectivity = String(agent.connectivity_state || '').trim();
            const capabilities = Array.isArray(agent.management_capabilities)
                ? agent.management_capabilities
                : [];
            return ['connected', 'degraded'].includes(connectivity) && capabilities.includes(capability);
        });
    }

    function _renderAgentOptions() {
        const agents = _managementAgents('skill_catalog');
        if (!agents.length) {
            currentAgentId = '';
            allSkills = [];
            agentDropdown.update([], '');
            return;
        }
        if (!agents.some((agent) => agent.agent_id === currentAgentId)) {
            currentAgentId = agents[0].agent_id || '';
            _writeAgentId(currentAgentId);
        }
        agentDropdown.update(agents, currentAgentId);
    }

    function renderList() {
        if (!currentAgentId) {
            UI.reconcileChildren(listEl, [
                UI.renderEmptyState('No connected bot advertises skill catalog management.', true),
            ]);
            return;
        }
        let filtered = allSkills;
        if (currentQ) {
            filtered = allSkills.filter((skill) => {
                const haystack = [
                    skill.slug || skill.name || '',
                    skill.description || skill.display_name || '',
                ].join(' ').toLowerCase();
                return haystack.includes(currentQ);
            });
        }

        if (!filtered.length) {
            UI.clearMemoizedRender(listEl);
            UI.reconcileChildren(listEl, [
                UI.renderEmptyState(allSkills.length ? 'No skills match this search.' : 'No runtime skills available.', true),
            ]);
            return;
        }

        UI.memoizedRender(listEl, {
            agentId: currentAgentId,
            query: currentQ,
            skills: filtered,
        }, (state) => state.skills.map((skill) => {
            const shellRow = document.createElement('div');
            shellRow.className = 'list-row-shell';
            shellRow.dataset.key = skill.slug || skill.name || skill.display_name || '';

            const sub = document.createElement('span');
            sub.textContent = skill.description || skill.display_name || 'Runtime skill';

            const row = UI.renderListRow({
                label: skill.slug || skill.name || '',
                sublabelNode: sub,
                badgeText: (skill.status || '').trim() || '',
                badgeClass: skill.status ? 'badge-' + skill.status : '',
            });
            shellRow.appendChild(row);

            const skillName = skill.slug || skill.name || '';
            const isInstalled = ['installed', 'published', 'active'].includes(String(skill.status || '').trim());
            const actionBtn = document.createElement('button');
            actionBtn.type = 'button';
            actionBtn.className = `btn btn-sm list-row-action${isInstalled ? ' btn-danger' : ' btn-primary'}`;
            actionBtn.textContent = isInstalled ? 'Uninstall' : 'Install';
            actionBtn.addEventListener('click', async () => {
                actionBtn.disabled = true;
                actionBtn.textContent = isInstalled ? 'Uninstalling…' : 'Installing…';
                try {
                    if (isInstalled) {
                        await API.uninstallSkill(currentAgentId, skillName);
                    } else {
                        await API.installSkill(currentAgentId, skillName);
                    }
                    loadSkills();
                } catch (err) {
                    actionBtn.disabled = false;
                    actionBtn.textContent = isInstalled ? 'Uninstall' : 'Install';
                    UI.reportError('Failed to update the skill', err, { context: 'Skill action failed' });
                }
            });
            shellRow.appendChild(actionBtn);
            return shellRow;
        }), {
            signatureFn(state) {
                return {
                    agentId: String(state.agentId || ''),
                    query: String(state.query || ''),
                    skills: (state.skills || []).map((skill) => ({
                        slug: String(skill.slug || skill.name || skill.display_name || ''),
                        description: String(skill.description || skill.display_name || ''),
                        status: String(skill.status || ''),
                    })),
                };
            },
        });
    }

    async function loadSkills({ soft = false } = {}) {
        if (!currentAgentId) {
            allSkills = [];
            renderList();
            return;
        }
        try {
            const data = await API.listSkills(currentAgentId);
            allSkills = Array.isArray(data) ? data : (data.skills || []);
            renderList();
        } catch (err) {
            UI.clearMemoizedRender(listEl);
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load skills: ' + err.message, loadSkills)]);
        }
    }

    async function loadAgents({ soft = false } = {}) {
        if (!soft) {
            agentSelect.disabled = true;
        }
        try {
            const data = await API.listAgents({ limit: 200 });
            availableAgents = Array.isArray(data) ? data : (data.agents || []);
            const requested = _readAgentId();
            if (requested) {
                currentAgentId = requested;
            }
            _renderAgentOptions();
            await loadSkills({ soft: true });
        } catch (err) {
            UI.clearMemoizedRender(listEl);
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load managed bots: ' + err.message, loadAgents)]);
        }
    }

    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentQ = searchInput.value.trim().toLowerCase();
            renderList();
        }, 250);
    });

    container.__routeReady = loadAgents();

    cleanups.add(() => clearTimeout(searchTimeout));
    UI.subscribeWithRefresh(cleanups, 'agents', () => loadAgents({ soft: true }), 600);
}
