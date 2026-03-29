/**
 * Skill catalog — dense installable runtime skill roster.
 */
function renderSkillCatalog(container) {
    const cleanups = UI.beginCleanupScope();
    let searchTimeout = null;
    let currentQ = '';
    let allSkills = [];
    let registrySkills = [];
    let registryError = '';
    let availableAgents = [];
    let currentAgentId = '';

    function renderLoadingState(message = 'Loading skills…') {
        UI.clearMemoizedRender(listEl);
        UI.reconcileChildren(listEl, [UI.renderEmptyState(message, true)]);
    }

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

    function _queryText() {
        return String(currentQ || '').trim();
    }

    function _filteredCatalogSkills() {
        const queryText = _queryText().toLowerCase();
        if (!queryText) {
            return allSkills;
        }
        return allSkills.filter((skill) => {
            const haystack = [
                skill.name || '',
                skill.display_name || '',
                skill.description || '',
                skill.source_kind || '',
            ].join(' ').toLowerCase();
            return haystack.includes(queryText);
        });
    }

    function _sectionLabel(text, key) {
        const el = document.createElement('div');
        el.className = 'list-section-label';
        el.dataset.key = key;
        el.textContent = text;
        return el;
    }

    function _buildActionButton({ label, pendingLabel, className, onClick, errorMessage }) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = className;
        btn.textContent = label;
        btn.addEventListener('click', async () => {
            btn.disabled = true;
            btn.textContent = pendingLabel;
            try {
                await onClick();
            } catch (err) {
                btn.disabled = false;
                btn.textContent = label;
                UI.reportError(errorMessage, err, { context: 'Skill action failed' });
            }
        });
        return btn;
    }

    function _localSkillActions(skillName, skill) {
        const actions = document.createElement('div');
        actions.className = 'list-row-actions';

        if (skill.can_update) {
            actions.appendChild(_buildActionButton({
                label: 'Update',
                pendingLabel: 'Updating…',
                className: 'btn btn-sm list-row-action',
                errorMessage: 'Failed to update the skill',
                onClick: async () => {
                    await API.updateSkill(currentAgentId, skillName);
                    await loadSkills({ soft: true, forceCatalog: true });
                },
            }));
        }

        if (skill.can_uninstall) {
            actions.appendChild(_buildActionButton({
                label: 'Uninstall',
                pendingLabel: 'Uninstalling…',
                className: 'btn btn-sm btn-danger list-row-action',
                errorMessage: 'Failed to uninstall the skill',
                onClick: async () => {
                    await API.uninstallSkill(currentAgentId, skillName);
                    await loadSkills({ soft: true, forceCatalog: true });
                },
            }));
        }

        return actions.childElementCount ? actions : null;
    }

    function _registrySkillActions(skillName, skill) {
        if (!skill.can_import) {
            return null;
        }
        const actions = document.createElement('div');
        actions.className = 'list-row-actions';
        actions.appendChild(_buildActionButton({
            label: 'Install',
            pendingLabel: 'Installing…',
            className: 'btn btn-sm btn-primary list-row-action',
            errorMessage: 'Failed to install the skill',
            onClick: async () => {
                await API.installSkill(currentAgentId, skillName);
                await loadSkills({ soft: true, forceCatalog: true });
            },
        }));
        return actions;
    }

    function _renderLocalSkillRow(skill) {
        const shellRow = document.createElement('div');
        shellRow.className = 'list-row-shell';
        shellRow.dataset.key = `local:${skill.name || skill.display_name || ''}`;

        const sub = document.createElement('span');
        const fragments = [];
        if (skill.description) {
            fragments.push(String(skill.description));
        }
        if (skill.source_kind) {
            fragments.push(String(skill.source_kind).replace(/_/g, ' '));
        }
        if (skill.lifecycle_status) {
            fragments.push(String(skill.lifecycle_status).replace(/_/g, ' '));
        }
        sub.textContent = fragments.join(' • ') || 'Runtime skill';

        const row = UI.renderListRow({
            label: skill.display_name || skill.name || '',
            sublabelNode: sub,
            badgeText: String(skill.source_kind || '').replace(/_/g, ' '),
        });
        shellRow.appendChild(row);

        const actions = _localSkillActions(skill.name || '', skill);
        if (actions) {
            shellRow.appendChild(actions);
        }
        return shellRow;
    }

    function _renderRegistrySkillRow(skill) {
        const shellRow = document.createElement('div');
        shellRow.className = 'list-row-shell';
        shellRow.dataset.key = `registry:${skill.name || skill.display_name || ''}`;

        const sub = document.createElement('span');
        const fragments = [];
        if (skill.description) {
            fragments.push(String(skill.description));
        }
        if (skill.publisher) {
            fragments.push(String(skill.publisher));
        }
        if (skill.version) {
            fragments.push(`v${skill.version}`);
        }
        sub.textContent = fragments.join(' • ') || 'Registry skill';

        const row = UI.renderListRow({
            label: skill.display_name || skill.name || '',
            sublabelNode: sub,
            badgeText: 'registry',
        });
        shellRow.appendChild(row);

        const actions = _registrySkillActions(skill.name || '', skill);
        if (actions) {
            shellRow.appendChild(actions);
        }
        return shellRow;
    }

    function renderList() {
        if (!currentAgentId) {
            UI.reconcileChildren(listEl, [
                UI.renderEmptyState('No connected bot advertises skill catalog management.', true),
            ]);
            return;
        }
        const queryText = _queryText();
        const filteredCatalog = _filteredCatalogSkills();
        const visibleRegistry = queryText.length >= 2 ? registrySkills : [];

        if (!filteredCatalog.length && !visibleRegistry.length) {
            UI.clearMemoizedRender(listEl);
            if (queryText.length >= 2 && registryError) {
                UI.reconcileChildren(listEl, [
                    UI.createErrorCard(`Registry search unavailable: ${registryError}`, () => loadSkills({ soft: true })),
                ]);
            } else {
                UI.reconcileChildren(listEl, [
                    UI.renderEmptyState(allSkills.length ? 'No skills match this search.' : 'No runtime skills available.', true),
                ]);
            }
            return;
        }

        UI.memoizedRender(listEl, {
            agentId: currentAgentId,
            query: queryText,
            localSkills: filteredCatalog,
            registrySkills: visibleRegistry,
            registryError: queryText.length >= 2 ? registryError : '',
        }, (state) => {
            const nodes = [];
            if (state.localSkills.length) {
                if (state.registrySkills.length) {
                    nodes.push(_sectionLabel('Local skills', 'skills-local-heading'));
                }
                nodes.push(...state.localSkills.map((skill) => _renderLocalSkillRow(skill)));
            }
            if (state.registrySkills.length) {
                if (state.localSkills.length) {
                    nodes.push(_sectionLabel('Registry matches', 'skills-registry-heading'));
                }
                nodes.push(...state.registrySkills.map((skill) => _renderRegistrySkillRow(skill)));
            }
            if (state.registryError) {
                const notice = UI.renderEmptyState(`Registry search unavailable. ${state.registryError}`, true);
                notice.dataset.key = 'registry-search-error';
                nodes.push(notice);
            }
            return nodes;
        }, {
            signatureFn(state) {
                return {
                    agentId: String(state.agentId || ''),
                    query: String(state.query || ''),
                    localSkills: (state.localSkills || []).map((skill) => ({
                        name: String(skill.name || skill.display_name || ''),
                        description: String(skill.description || ''),
                        sourceKind: String(skill.source_kind || ''),
                        lifecycle: String(skill.lifecycle_status || ''),
                        canUpdate: Boolean(skill.can_update),
                        canUninstall: Boolean(skill.can_uninstall),
                    })),
                    registrySkills: (state.registrySkills || []).map((skill) => ({
                        name: String(skill.name || skill.display_name || ''),
                        description: String(skill.description || ''),
                        publisher: String(skill.publisher || ''),
                        version: String(skill.version || ''),
                        canImport: Boolean(skill.can_import),
                    })),
                    registryError: String(state.registryError || ''),
                };
            },
        });
    }

    async function loadSkills({ soft = false, forceCatalog = false } = {}) {
        if (!currentAgentId) {
            allSkills = [];
            registrySkills = [];
            registryError = '';
            renderList();
            return;
        }
        const queryText = _queryText();
        const shouldLoadCatalog = forceCatalog || !allSkills.length;
        if (!soft && (shouldLoadCatalog || queryText.length >= 2)) {
            renderLoadingState(queryText.length >= 2 ? 'Searching skills…' : 'Loading skills…');
        }
        try {
            if (shouldLoadCatalog) {
                const data = await API.listSkills(currentAgentId);
                allSkills = Array.isArray(data) ? data : (data.skills || []);
            }
            if (queryText.length >= 2) {
                const search = await API.searchCatalogSkills(currentAgentId, queryText);
                registrySkills = Array.isArray(search.registry) ? search.registry : [];
                registryError = String(search.registry_error || '');
            } else {
                registrySkills = [];
                registryError = '';
            }
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
            const previousAgentId = currentAgentId;
            const data = await API.listAgents({ limit: 100 });
            availableAgents = Array.isArray(data) ? data : (data.agents || []);
            const requested = _readAgentId();
            if (requested) {
                currentAgentId = requested;
            }
            _renderAgentOptions();
            const agentChanged = previousAgentId !== currentAgentId;
            void loadSkills({ soft: soft && !agentChanged, forceCatalog: agentChanged || !allSkills.length });
        } catch (err) {
            UI.clearMemoizedRender(listEl);
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load managed bots: ' + err.message, loadAgents)]);
        }
    }

    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            currentQ = searchInput.value.trim();
            void loadSkills({ soft: true });
        }, 250);
    });

    container.__routeReady = loadAgents();

    cleanups.add(() => clearTimeout(searchTimeout));
    UI.subscribeWithRefresh(cleanups, 'agents', () => loadAgents({ soft: true }), 600);
}
