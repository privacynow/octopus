/**
 * Skills hub — bot-scoped skill catalog plus custom skill studio.
 */
function renderSkillCatalog(container) {
    const cleanups = UI.beginCleanupScope();
    const SKILL_CACHE_TTL_MS = 60000;
    const SKILL_SEARCH_CACHE_TTL_MS = 30000;
    const SKILL_DETAIL_CACHE_TTL_MS = 60000;
    const CACHE_ERROR_TTL_MS = 5000;

    let searchTimeout = null;
    let currentQ = '';
    let currentMode = _readMode();
    let currentAgentId = '';
    let selectedSkillName = _readSkillName();
    let selectedSkillOrigin = _readSkillOrigin();
    let availableAgents = [];
    let allSkills = [];
    let registrySkills = [];
    let registryError = '';
    let selectedLocalDetail = null;
    let selectedLifecycle = null;

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = [
        '<h2>Skills</h2>',
        '<p class="quiet-note">',
        'Choose a bot to browse the skills available there. Skills affect prompt context only when they are active in a conversation or set as defaults for new conversations.',
        '</p>',
    ].join('');
    container.appendChild(header);

    const shell = document.createElement('section');
    shell.className = 'admin-shell';
    container.appendChild(shell);

    const controlsPanel = document.createElement('section');
    controlsPanel.className = 'workbench-panel';
    shell.appendChild(controlsPanel);

    const modeControl = UI.createSegmentedControl(
        [
            { key: 'catalog', value: 'catalog', label: 'Bot catalog' },
            { key: 'studio', value: 'studio', label: 'Studio' },
        ],
        (nextMode) => {
            currentMode = nextMode;
            searchInput.placeholder = currentMode === 'studio' ? 'Filter custom skills' : 'Search available skills or store';
            _writeState();
            _renderAgentOptions();
            void loadSkills({ forceCatalog: true });
        },
        {
            label: 'Skills view',
            value: currentMode,
        },
    );
    controlsPanel.appendChild(modeControl.element);

    const controls = document.createElement('div');
    controls.className = 'route-controls';
    controlsPanel.appendChild(controls);

    const agentDropdown = UI.createAgentManagementDropdown([], '', (nextAgentId) => {
        currentAgentId = nextAgentId;
        selectedLocalDetail = null;
        selectedLifecycle = null;
        _writeState();
        void loadSkills({ forceCatalog: true });
    }, {
        allowEmpty: true,
        emptyLabel: 'Choose a bot',
    });
    controls.appendChild(agentDropdown.element);

    const searchInput = document.createElement('input');
    searchInput.className = 'search-input';
    searchInput.placeholder = currentMode === 'studio' ? 'Filter custom skills' : 'Search available skills or store';
    searchInput.type = 'text';
    searchInput.setAttribute('aria-label', 'Search skills');
    controls.appendChild(searchInput);

    const workspace = document.createElement('section');
    workspace.className = 'dashboard-board';
    shell.appendChild(workspace);

    const listWrap = document.createElement('section');
    listWrap.className = 'list-shell';
    workspace.appendChild(listWrap);

    const listEl = document.createElement('div');
    listEl.className = 'list-container';
    listWrap.appendChild(listEl);

    const detailEl = document.createElement('section');
    detailEl.className = 'editor-shell';
    workspace.appendChild(detailEl);

    function _readMode() {
        const value = UI.readQueryParam('skills_view', 'catalog');
        return value === 'studio' ? 'studio' : 'catalog';
    }

    function _readSkillName() {
        return UI.readQueryParam('skill', '');
    }

    function _readSkillOrigin() {
        const value = UI.readQueryParam('skill_source', 'local');
        return value === 'store' ? 'store' : 'local';
    }

    function _writeState() {
        UI.updateQueryParams({
            agent_id: currentAgentId || '',
            skills_view: currentMode === 'studio' ? 'studio' : '',
            skill: selectedSkillName || '',
            skill_source: selectedSkillName && selectedSkillOrigin === 'store' ? 'store' : '',
        });
    }

    function _currentAgent() {
        return availableAgents.find((agent) => agent.agent_id === currentAgentId) || null;
    }

    function _currentAgentLabel() {
        const agent = _currentAgent();
        if (!agent) return 'this bot';
        return UI.visibleLabel(agent.display_name, agent.slug, agent.agent_id) || 'this bot';
    }

    function _eligibleAgents() {
        const needed = currentMode === 'studio' ? 'skill_lifecycle' : 'skill_catalog';
        return UI.filterManagedAgents(availableAgents, needed);
    }

    function _renderAgentOptions() {
        const agents = _eligibleAgents();
        if (!agents.length) {
            currentAgentId = '';
            selectedSkillName = '';
            selectedSkillOrigin = 'local';
            selectedLocalDetail = null;
            selectedLifecycle = null;
            agentDropdown.update([], '');
            return;
        }
        if (!agents.some((agent) => agent.agent_id === currentAgentId)) {
            currentAgentId = '';
        }
        agentDropdown.update(agents, currentAgentId);
        _writeState();
    }

    function _queryText() {
        return String(currentQ || '').trim();
    }

    function _skillCacheKey(agentId) {
        return `skills:list:${String(agentId || '').trim()}`;
    }

    function _skillSearchCacheKey(agentId, queryText) {
        return `skills:search:${String(agentId || '').trim()}:${String(queryText || '').trim().toLowerCase()}`;
    }

    function _skillDetailCacheKey(agentId, skillName) {
        return `skills:detail:${String(agentId || '').trim()}:${String(skillName || '').trim()}`;
    }

    function _skillLifecycleCacheKey(agentId, skillName) {
        return `skills:lifecycle:${String(agentId || '').trim()}:${String(skillName || '').trim()}`;
    }

    function _invalidateSkillCaches(agentId = currentAgentId, skillName = '') {
        const normalizedAgentId = String(agentId || '').trim();
        if (!normalizedAgentId) return;
        const prefixes = [
            _skillCacheKey(normalizedAgentId),
            `skills:search:${normalizedAgentId}:`,
        ];
        if (skillName) {
            prefixes.push(_skillDetailCacheKey(normalizedAgentId, skillName));
            prefixes.push(_skillLifecycleCacheKey(normalizedAgentId, skillName));
        } else {
            prefixes.push(`skills:detail:${normalizedAgentId}:`);
            prefixes.push(`skills:lifecycle:${normalizedAgentId}:`);
        }
        UI.invalidateCachedData(prefixes);
    }

    function _visibleLocalSkills() {
        const queryText = _queryText().toLowerCase();
        const base = currentMode === 'studio'
            ? (allSkills || []).filter((skill) => String(skill.source_kind || '') === 'custom')
            : allSkills;
        if (!queryText) {
            return base;
        }
        return base.filter((skill) => {
            const haystack = [
                skill.name || '',
                skill.display_name || '',
                skill.description || '',
                skill.source_kind || '',
                skill.lifecycle_status || '',
            ].join(' ').toLowerCase();
            return haystack.includes(queryText);
        });
    }

    function _visibleStoreSkills() {
        if (currentMode !== 'catalog' || _queryText().length < 2) {
            return [];
        }
        return registrySkills;
    }

    function _findSelectedSkill() {
        const local = _visibleLocalSkills().find((item) => item && item.name === selectedSkillName);
        if (local) {
            return { origin: 'local', skill: local };
        }
        const store = _visibleStoreSkills().find((item) => item && item.name === selectedSkillName);
        if (store) {
            return { origin: 'store', skill: store };
        }
        return null;
    }

    function _ensureSelection() {
        const local = _visibleLocalSkills();
        const store = _visibleStoreSkills();
        const current = _findSelectedSkill();
        if (current) {
            selectedSkillOrigin = current.origin;
            return;
        }
        if (local.length) {
            selectedSkillName = local[0].name || '';
            selectedSkillOrigin = 'local';
        } else if (store.length) {
            selectedSkillName = store[0].name || '';
            selectedSkillOrigin = 'store';
        } else {
            selectedSkillName = '';
            selectedSkillOrigin = 'local';
        }
        _writeState();
    }

    function renderLoadingState(message = 'Loading skills…') {
        UI.clearMemoizedRender(listEl);
        UI.reconcileChildren(listEl, [UI.renderEmptyState(message, true)]);
    }

    function renderList() {
        if (!currentAgentId) {
            UI.clearMemoizedRender(listEl);
            const hasEligibleAgents = _eligibleAgents().length > 0;
            UI.reconcileChildren(listEl, [
                UI.renderEmptyState(
                    hasEligibleAgents
                        ? (currentMode === 'studio'
                            ? 'Choose a bot to create or edit custom skills.'
                            : 'Choose a bot to browse available skills.')
                        : (currentMode === 'studio'
                            ? 'No connected bot advertises custom skill lifecycle management.'
                            : 'No connected bot advertises skill catalog management.'),
                    true,
                ),
            ]);
            renderDetail();
            return;
        }
        const visibleLocal = _visibleLocalSkills();
        const visibleStore = _visibleStoreSkills();
        _ensureSelection();

        if (!visibleLocal.length && !visibleStore.length) {
            UI.clearMemoizedRender(listEl);
            const message = currentMode === 'studio'
                ? (_queryText()
                    ? 'No custom skills match this filter.'
                    : 'No custom skills yet for this bot. Create a draft to get started.')
                : (allSkills.length ? 'No available or store skills match this search.' : 'No skills are available on this bot yet.');
            UI.reconcileChildren(listEl, [UI.renderEmptyState(message, true)]);
            renderDetail();
            return;
        }

        UI.memoizedRender(listEl, {
            mode: currentMode,
            selectedSkillName,
            selectedSkillOrigin,
            local: visibleLocal,
            store: visibleStore,
            registryError,
        }, (state) => {
            const nodes = [];
            if (state.mode === 'catalog') {
                nodes.push(_sectionLabel('Available on this bot', 'skills-available-heading'));
            } else {
                nodes.push(_sectionLabel('Custom skills', 'skills-studio-heading'));
            }
            nodes.push(...(state.local || []).map((skill) => _renderLocalSkillRow(skill, {
                selected: state.selectedSkillOrigin === 'local' && state.selectedSkillName === skill.name,
            })));
            if (state.mode === 'catalog' && (state.store || []).length) {
                nodes.push(_sectionLabel('Skill store', 'skills-store-heading'));
                nodes.push(...state.store.map((skill) => _renderRegistrySkillRow(skill, {
                    selected: state.selectedSkillOrigin === 'store' && state.selectedSkillName === skill.name,
                })));
            }
            if (state.mode === 'catalog' && state.registryError && _queryText().length >= 2) {
                const notice = UI.renderEmptyState(`Store search unavailable. ${state.registryError}`, true);
                notice.dataset.key = 'skill-store-error';
                nodes.push(notice);
            }
            return nodes;
        }, {
            signatureFn(state) {
                return {
                    mode: String(state.mode || ''),
                    selectedSkillName: String(state.selectedSkillName || ''),
                    selectedSkillOrigin: String(state.selectedSkillOrigin || ''),
                    local: (state.local || []).map((skill) => ({
                        name: String(skill.name || ''),
                        source: String(skill.source_label || skill.source_kind || ''),
                        lifecycle: String(skill.lifecycle_status || ''),
                        runtime: Boolean(skill.runtime_available),
                        defaultForNewConversations: Boolean(skill.default_for_new_conversations),
                        install: Boolean(skill.can_update || skill.can_uninstall || skill.can_activate),
                    })),
                    store: (state.store || []).map((skill) => ({
                        name: String(skill.name || ''),
                        publisher: String(skill.publisher || ''),
                        version: String(skill.version || ''),
                    })),
                    registryError: String(state.registryError || ''),
                };
            },
        });
        renderDetail();
    }

    function _sectionLabel(text, key) {
        const el = document.createElement('div');
        el.className = 'list-section-label';
        el.dataset.key = key;
        el.textContent = text;
        return el;
    }

    function _sourceBadgeText(skill) {
        return String(skill.source_label || skill.source_kind || 'Skill');
    }

    function _renderLocalSkillRow(skill, { selected = false } = {}) {
        const shellRow = document.createElement('div');
        shellRow.className = 'list-row-shell';
        shellRow.dataset.key = `local:${skill.name || ''}`;

        const fragments = [];
        if (skill.description) fragments.push(String(skill.description));
        if (skill.runtime_available === false) fragments.push('not active until published');
        if (skill.requires_credentials) fragments.push('setup required on activation');
        if (skill.default_for_new_conversations) fragments.push('default for new conversations');
        if (skill.lifecycle_status) fragments.push(String(skill.lifecycle_status).replace(/_/g, ' '));
        if (skill.has_unpublished_changes) fragments.push('unpublished changes');
        const row = UI.renderListRow({
            label: skill.display_name || skill.name || '',
            sublabel: fragments.join(' • ') || 'Available on this bot',
            badgeText: _sourceBadgeText(skill),
            onClick: () => {
                selectedSkillName = skill.name || '';
                selectedSkillOrigin = 'local';
                selectedLocalDetail = null;
                selectedLifecycle = null;
                _writeState();
                void loadSelectionData({ soft: true });
                renderList();
            },
            className: selected ? 'is-selected' : '',
        });
        shellRow.appendChild(row);
        const actions = document.createElement('div');
        actions.className = 'list-row-actions';
        if (skill.can_update) {
            actions.appendChild(_actionButton('Update', async () => {
                await API.updateSkill(currentAgentId, skill.name);
                _invalidateSkillCaches(currentAgentId, skill.name);
                await loadSkills({ soft: true, forceCatalog: true });
            }));
            actions.appendChild(_actionButton('Diff', async () => {
                const result = await API.diffSkill(currentAgentId, skill.name);
                UI.showTextDialog(`Store diff · ${skill.display_name || skill.name}`, result.diff || 'No differences.');
            }));
        }
        if (skill.can_uninstall) {
            actions.appendChild(_dangerActionButton('Uninstall', async () => {
                await API.uninstallSkill(currentAgentId, skill.name);
                _invalidateSkillCaches(currentAgentId, skill.name);
                await loadSkills({ soft: true, forceCatalog: true });
            }));
        }
        if (actions.childElementCount) {
            shellRow.appendChild(actions);
        }
        return shellRow;
    }

    function _renderRegistrySkillRow(skill, { selected = false } = {}) {
        const shellRow = document.createElement('div');
        shellRow.className = 'list-row-shell';
        shellRow.dataset.key = `store:${skill.name || ''}`;
        const fragments = [];
        if (skill.description) fragments.push(String(skill.description));
        if (skill.publisher) fragments.push(`by ${String(skill.publisher)}`);
        if (skill.version) fragments.push(`v${String(skill.version)}`);
        const row = UI.renderListRow({
            label: skill.display_name || skill.name || '',
            sublabel: fragments.join(' • ') || 'Available from the skill store',
            badgeText: String(skill.source_label || 'Store'),
            onClick: () => {
                selectedSkillName = skill.name || '';
                selectedSkillOrigin = 'store';
                selectedLocalDetail = null;
                selectedLifecycle = null;
                _writeState();
                renderList();
            },
            className: selected ? 'is-selected' : '',
        });
        shellRow.appendChild(row);
        const actions = document.createElement('div');
        actions.className = 'list-row-actions';
        if (skill.can_import) {
            actions.appendChild(_actionButton('Install', async () => {
                await API.installSkill(currentAgentId, skill.name);
                _invalidateSkillCaches(currentAgentId, skill.name);
                selectedSkillName = skill.name || '';
                selectedSkillOrigin = 'local';
                _writeState();
                await loadSkills({ soft: true, forceCatalog: true });
            }, 'Installing…'));
        }
        if (actions.childElementCount) {
            shellRow.appendChild(actions);
        }
        return shellRow;
    }

    function _actionButton(label, onClick, pendingLabel = `${label}…`) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-sm list-row-action';
        btn.textContent = label;
        btn.addEventListener('click', async (event) => {
            event.stopPropagation();
            btn.disabled = true;
            const original = btn.textContent;
            btn.textContent = pendingLabel;
            try {
                await onClick();
            } catch (err) {
                UI.reportError(`Failed to ${label.toLowerCase()} the skill`, err, { context: `Skill ${label.toLowerCase()} failed` });
            }
            btn.disabled = false;
            btn.textContent = original;
        });
        return btn;
    }

    function _dangerActionButton(label, onClick) {
        const btn = _actionButton(label, onClick, `${label}ing…`);
        btn.className = 'btn btn-sm btn-danger list-row-action';
        return btn;
    }

    async function loadSelectionData({ soft = false } = {}) {
        const selected = _findSelectedSkill();
        if (!currentAgentId || !selected || selected.origin !== 'local') {
            selectedLocalDetail = null;
            selectedLifecycle = null;
            renderDetail();
            return;
        }
        const skillName = selected.skill.name || '';
        const hadVisibleState = detailEl.childElementCount > 0;
        const cachedDetail = UI.peekCachedData(_skillDetailCacheKey(currentAgentId, skillName));
        const cachedLifecycle = currentMode === 'studio'
            ? UI.peekCachedData(_skillLifecycleCacheKey(currentAgentId, skillName))
            : null;
        const hasCachedView = Boolean(cachedDetail) || Boolean(cachedLifecycle);
        if (cachedDetail) {
            selectedLocalDetail = cachedDetail;
        }
        if (cachedLifecycle) {
            selectedLifecycle = cachedLifecycle;
        }
        if (hasCachedView) {
            renderDetail();
        } else if (!soft) {
            UI.clearMemoizedRender(detailEl);
            UI.reconcileChildren(detailEl, [UI.renderEmptyState('Loading skill details…', true)]);
        }
        try {
            selectedLocalDetail = await UI.loadCachedData(
                _skillDetailCacheKey(currentAgentId, skillName),
                () => API.getSkillDetail(currentAgentId, skillName),
                {
                    ttlMs: SKILL_DETAIL_CACHE_TTL_MS,
                    errorTtlMs: CACHE_ERROR_TTL_MS,
                    forceRefresh: hasCachedView,
                },
            );
            if (currentMode === 'studio' && String(selected.skill.source_kind || '') === 'custom') {
                selectedLifecycle = await UI.loadCachedData(
                    _skillLifecycleCacheKey(currentAgentId, skillName),
                    () => API.getSkillLifecycle(currentAgentId, skillName),
                    {
                        ttlMs: SKILL_DETAIL_CACHE_TTL_MS,
                        errorTtlMs: CACHE_ERROR_TTL_MS,
                        forceRefresh: hasCachedView,
                    },
                );
            } else {
                selectedLifecycle = null;
            }
            renderDetail();
        } catch (err) {
            if (hasCachedView || hadVisibleState) {
                UI.reportError('Failed to refresh skill details', err, { context: 'Skill detail refresh failed' });
                return;
            }
            UI.clearMemoizedRender(detailEl);
            UI.reconcileChildren(detailEl, [UI.createErrorCard('Failed to load skill details: ' + err.message, loadSelectionData)]);
        }
    }

    function renderDetail() {
        if (!currentAgentId) {
            UI.clearMemoizedRender(detailEl);
            UI.reconcileChildren(detailEl, []);
            return;
        }
        const selected = _findSelectedSkill();
        if (!selected) {
            UI.clearMemoizedRender(detailEl);
            if (currentMode === 'studio') {
                UI.reconcileChildren(detailEl, [_buildStudioPanel({}, {}, null)]);
            } else {
                UI.reconcileChildren(detailEl, [
                    UI.renderEmptyState('Select an available skill or a store match to inspect it.', true),
                ]);
            }
            return;
        }
        if (selected.origin === 'store') {
            renderStoreDetail(selected.skill);
            return;
        }
        const detail = selectedLocalDetail && selectedLocalDetail.name === selected.skill.name
            ? selectedLocalDetail
            : selected.skill;
        const lifecycle = selectedLifecycle && selectedLifecycle.name === selected.skill.name
            ? selectedLifecycle
            : null;
        renderLocalDetail(selected.skill, detail, lifecycle);
    }

    function renderStoreDetail(skill) {
        UI.memoizedRender(detailEl, {
            mode: currentMode,
            origin: 'store',
            skill,
        }, (state) => {
            const nodes = [];
            const overview = document.createElement('section');
            overview.className = 'editor-panel';
            overview.dataset.key = 'store-overview';
            const headerRow = document.createElement('div');
            headerRow.className = 'workspace-header-main';
            const titleWrap = document.createElement('div');
            titleWrap.className = 'workspace-title-group';
            const title = document.createElement('h3');
            title.className = 'editor-section-title';
            title.textContent = state.skill.display_name || state.skill.name || 'Skill';
            titleWrap.appendChild(title);
            if (state.skill.description) {
                const description = document.createElement('p');
                description.className = 'quiet-note';
                description.textContent = state.skill.description;
                titleWrap.appendChild(description);
            }
            headerRow.appendChild(titleWrap);
            const badge = document.createElement('span');
            badge.className = 'badge';
            badge.textContent = state.skill.source_label || 'Store';
            headerRow.appendChild(badge);
            overview.appendChild(headerRow);
            overview.appendChild(UI.renderMetadataGrid([
                { label: 'State', value: 'Available from the skill store' },
                { label: 'Publisher', value: state.skill.publisher || 'Unknown' },
                { label: 'Version', value: state.skill.version || 'Unknown' },
            ], { compact: true }));
            const actions = document.createElement('div');
            actions.className = 'editor-actions';
            if (state.skill.can_import) {
                actions.appendChild(_actionButton('Install on bot', async () => {
                    await API.installSkill(currentAgentId, state.skill.name);
                    _invalidateSkillCaches(currentAgentId, state.skill.name);
                    selectedSkillOrigin = 'local';
                    selectedSkillName = state.skill.name;
                    _writeState();
                    await loadSkills({ soft: true, forceCatalog: true });
                }, 'Installing…'));
            }
            overview.appendChild(actions);
            nodes.push(overview);

            const help = document.createElement('section');
            help.className = 'editor-panel';
            help.dataset.key = 'store-help';
            help.innerHTML = [
                '<div class="editor-section-title">How to use this skill</div>',
                '<p class="quiet-note">',
                'Install the skill on this bot first. Then open a conversation and use the conversation Skills panel to activate it in that chat.',
                '</p>',
            ].join('');
            nodes.push(help);
            return nodes;
        }, {
            signatureFn(state) {
                return {
                    origin: String(state.origin || ''),
                    name: String((state.skill && state.skill.name) || ''),
                    version: String((state.skill && state.skill.version) || ''),
                };
            },
        });
    }

    function renderLocalDetail(summary, detail, lifecycle) {
        UI.memoizedRender(detailEl, {
            mode: currentMode,
            agentId: currentAgentId,
            agentLabel: _currentAgentLabel(),
            summary,
            detail,
            lifecycle,
        }, (state) => {
            const nodes = [];
            nodes.push(_buildOverviewPanel(state.summary, state.detail, state.lifecycle));
            if (state.mode === 'catalog') {
                nodes.push(_buildCatalogHelpPanel(state.summary, state.detail, state.agentLabel));
            }
            if (String(state.summary.source_kind || '') === 'custom' || state.mode === 'studio') {
                nodes.push(_buildStudioPanel(state.summary, state.detail, state.lifecycle));
            }
            return nodes;
        }, {
            signatureFn(state) {
                return {
                    mode: String(state.mode || ''),
                    agentId: String(state.agentId || ''),
                    agentLabel: String(state.agentLabel || ''),
                    name: String((state.summary && state.summary.name) || ''),
                    lifecycle: String((state.detail && state.detail.lifecycle_status) || ''),
                    runtimeAvailable: Boolean(state.detail && state.detail.runtime_available),
                    source: String((state.detail && state.detail.source_kind) || ''),
                    activeRevisionId: String((state.lifecycle && state.lifecycle.active_revision_id) || ''),
                };
            },
        });
    }

    function _buildOverviewPanel(summary, detail, lifecycle) {
        const panel = document.createElement('section');
        panel.className = 'editor-panel';
        panel.dataset.key = `skill-overview:${summary.name || detail.name || ''}`;

        const packageState = lifecycle || detail;
        const requirements = Array.isArray(packageState.requirements) && packageState.requirements.length
            ? packageState.requirements
            : (detail.requirements || []).map((item) => ({
                key: item.key,
                prompt: item.prompt,
                help_url: item.help_url,
                validate: item.validate,
            }));
        const providerConfig = packageState.provider_config || detail.provider_config || {};
        const files = Array.isArray(packageState.files) ? packageState.files : (detail.files || []);
        const validationProblems = Array.isArray(packageState.validation_problems)
            ? packageState.validation_problems
            : [];

        const headerRow = document.createElement('div');
        headerRow.className = 'workspace-header-main';
        const titleWrap = document.createElement('div');
        titleWrap.className = 'workspace-title-group';
        const title = document.createElement('h3');
        title.className = 'editor-section-title';
        title.textContent = detail.display_name || detail.name || summary.display_name || summary.name || 'Skill';
        titleWrap.appendChild(title);
        if (detail.description) {
            const desc = document.createElement('p');
            desc.className = 'quiet-note';
            desc.textContent = detail.description;
            titleWrap.appendChild(desc);
        }
        headerRow.appendChild(titleWrap);
        const badge = document.createElement('span');
        badge.className = 'badge';
        badge.textContent = detail.source_label || detail.source_kind || 'Skill';
        headerRow.appendChild(badge);
        panel.appendChild(headerRow);

        panel.appendChild(UI.renderMetadataGrid([
            { label: 'Available on this bot', value: 'Yes' },
            {
                label: 'Default for new conversations',
                value: detail.default_for_new_conversations ? 'Yes' : 'No',
            },
            {
                label: 'Runtime availability',
                value: detail.runtime_available ? 'Ready to activate' : 'Publish before activation',
            },
            {
                label: 'Setup',
                value: requirements.length
                    ? `Needs setup (${requirements.map((item) => item.key).join(', ')})`
                    : 'No credentials required',
            },
            {
                label: 'Providers',
                value: (detail.providers || []).length ? detail.providers.join(', ') : 'All',
            },
            {
                label: 'Lifecycle',
                value: String(detail.lifecycle_status || 'published').replace(/_/g, ' '),
            },
            detail.visibility ? { label: 'Visibility', value: detail.visibility } : null,
            detail.has_unpublished_changes ? { label: 'Draft state', value: 'Unpublished changes' } : null,
            typeof packageState.publish_ready === 'boolean'
                ? { label: 'Publish readiness', value: packageState.publish_ready ? 'Ready' : 'Needs fixes' }
                : null,
        ].filter(Boolean), { compact: true }));

        const actions = document.createElement('div');
        actions.className = 'editor-actions';
        if (detail.can_update) {
            actions.appendChild(_actionButton('Update from store', async () => {
                await API.updateSkill(currentAgentId, detail.name);
                _invalidateSkillCaches(currentAgentId, detail.name);
                await loadSkills({ soft: true, forceCatalog: true });
            }, 'Updating…'));
            actions.appendChild(_actionButton('View store diff', async () => {
                const result = await API.diffSkill(currentAgentId, detail.name);
                UI.showTextDialog(`Store diff · ${detail.display_name || detail.name}`, result.diff || 'No differences.');
            }));
        }
        if (detail.can_uninstall) {
            actions.appendChild(_dangerActionButton('Uninstall', async () => {
                await API.uninstallSkill(currentAgentId, detail.name);
                _invalidateSkillCaches(currentAgentId, detail.name);
                await loadSkills({ soft: true, forceCatalog: true });
            }));
        }
        if (actions.childElementCount) {
            panel.appendChild(actions);
        }

        if (validationProblems.length) {
            const label = document.createElement('div');
            label.className = 'detail-label';
            label.textContent = 'Validation problems';
            panel.appendChild(label);

            const list = document.createElement('ul');
            list.className = 'change-list';
            validationProblems.forEach((problem) => {
                const item = document.createElement('li');
                item.innerHTML = [
                    `<strong>${UI.esc(problem.field_path || problem.code || 'problem')}</strong>`,
                    `<div>${UI.esc(problem.message || '')}</div>`,
                ].join('');
                list.appendChild(item);
            });
            panel.appendChild(list);
        }

        const bodyLabel = document.createElement('div');
        bodyLabel.className = 'detail-label';
        bodyLabel.textContent = 'Instructions preview';
        panel.appendChild(bodyLabel);
        const preview = document.createElement('div');
        preview.className = 'task-item-summary';
        preview.innerHTML = UI.renderContent(detail.body || '');
        panel.appendChild(preview);

        if (requirements.length) {
            const requirementsLabel = document.createElement('div');
            requirementsLabel.className = 'detail-label';
            requirementsLabel.textContent = 'Setup requirements';
            panel.appendChild(requirementsLabel);
            panel.appendChild(UI.renderMetadataGrid(
                requirements.map((item) => ({
                    label: item.key || 'credential',
                    value: item.help_url
                        ? `${item.prompt || ''} · ${item.help_url}`
                        : (item.prompt || 'Credential required'),
                })),
                { compact: true },
            ));
        }

        if (providerConfig && Object.keys(providerConfig).length) {
            const configLabel = document.createElement('div');
            configLabel.className = 'detail-label';
            configLabel.textContent = 'Provider config';
            panel.appendChild(configLabel);
            const configActions = document.createElement('div');
            configActions.className = 'editor-actions';
            Object.keys(providerConfig).sort().forEach((providerName) => {
                configActions.appendChild(_actionButton(`View ${providerName}`, async () => {
                    UI.showTextDialog(
                        `${providerName} config · ${detail.display_name || detail.name}`,
                        JSON.stringify(providerConfig[providerName] || {}, null, 2),
                    );
                }));
            });
            panel.appendChild(configActions);
        }

        if (files.length) {
            const filesLabel = document.createElement('div');
            filesLabel.className = 'detail-label';
            filesLabel.textContent = 'Attached files';
            panel.appendChild(filesLabel);
            const fileList = document.createElement('div');
            fileList.className = 'list-container';
            files.forEach((item) => {
                const trailing = document.createElement('div');
                trailing.className = 'editor-actions';
                trailing.appendChild(_actionButton('View', async () => {
                    UI.showTextDialog(
                        `${item.relative_path} · ${detail.display_name || detail.name}`,
                        item.content_text || '',
                    );
                }));
                fileList.appendChild(UI.renderListRow({
                    label: item.relative_path || 'file',
                    sublabel: [
                        item.content_type || 'text/plain',
                        item.executable ? 'executable' : '',
                    ].filter(Boolean).join(' • '),
                    trailing,
                }));
            });
            panel.appendChild(fileList);
        }

        return panel;
    }

    function _buildCatalogHelpPanel(summary, detail, agentLabel) {
        const panel = document.createElement('section');
        panel.className = 'editor-panel';
        panel.dataset.key = `skill-help:${detail.name || summary.name || ''}`;
        const heading = document.createElement('div');
        heading.className = 'editor-section-title';
        heading.textContent = 'Use in conversations';
        panel.appendChild(heading);
        const copy = document.createElement('p');
        copy.className = 'quiet-note';
        const label = agentLabel || _currentAgentLabel();
        copy.textContent = detail.runtime_available
            ? `This skill is available on ${label}. Open a conversation with that bot and use its Skills panel to activate it there.`
            : `This skill is available on ${label}, but it must be published before it can be activated in a conversation.`;
        panel.appendChild(copy);
        if (detail.default_for_new_conversations) {
            const defaultsNote = document.createElement('p');
            defaultsNote.className = 'quiet-note';
            defaultsNote.textContent = `This skill is also a default for new conversations on ${label}. Existing conversations still require activation here.`;
            panel.appendChild(defaultsNote);
        }
        if (detail.runtime_available) {
            const openBtn = document.createElement('button');
            openBtn.type = 'button';
            openBtn.className = 'btn btn-sm';
            openBtn.textContent = `Open a conversation with ${label}`;
            openBtn.addEventListener('click', async () => {
                openBtn.disabled = true;
                try {
                    const conversation = await API.openConversationForAgent(currentAgentId, {
                        title: `Conversation with ${label}`,
                    });
                    Router.navigate(
                        `/ui/conversations/${encodeURIComponent(conversation.conversation_id)}?manage=skills&activate_skill=${encodeURIComponent(detail.name || summary.name || '')}`,
                    );
                } catch (err) {
                    UI.reportError('Failed to open a conversation for skill activation', err, {
                        context: 'Skill activation conversation open failed',
                    });
                }
                openBtn.disabled = false;
            });
            panel.appendChild(openBtn);
        }
        return panel;
    }

    function _buildStudioPanel(summary, detail, lifecycle) {
        const panel = document.createElement('section');
        panel.className = 'editor-panel';
        panel.dataset.key = `skill-studio:${detail.name || summary.name || ''}`;

        const heading = document.createElement('div');
        heading.className = 'editor-section-title';
        heading.textContent = String(summary.source_kind || detail.source_kind) === 'custom'
            ? 'Skill studio'
            : 'Custom skill studio';
        panel.appendChild(heading);

        if (!detail || !detail.name) {
            const note = document.createElement('p');
            note.className = 'quiet-note';
            note.textContent = `Create a custom draft for ${_currentAgentLabel()}. Publish it before activating it in a conversation.`;
            panel.appendChild(note);
            panel.appendChild(_buildDraftCreateForm());
            return panel;
        }

        if (String(summary.source_kind || detail.source_kind) !== 'custom') {
            const note = document.createElement('p');
            note.className = 'quiet-note';
            note.textContent = 'Studio is available for custom skills. Create a draft below or select an existing custom skill.';
            panel.appendChild(note);
            panel.appendChild(_buildDraftCreateForm());
            return panel;
        }

        panel.appendChild(_buildDraftCreateForm());
        panel.appendChild(_buildDraftEditor(detail, lifecycle));
        if (lifecycle) {
            panel.appendChild(_buildLifecycleHistory(lifecycle));
        }
        return panel;
    }

    function _buildDraftCreateForm() {
        const section = document.createElement('section');
        section.className = 'editor-panel';
        section.dataset.key = 'skill-draft-create';

        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = 'Create custom draft';
        section.appendChild(title);

        const form = document.createElement('form');
        form.className = 'route-controls';
        const nameInput = document.createElement('input');
        nameInput.className = 'input';
        nameInput.placeholder = 'skill-slug';
        nameInput.required = true;
        form.appendChild(nameInput);
        const descriptionInput = document.createElement('input');
        descriptionInput.className = 'input';
        descriptionInput.placeholder = 'Short description';
        form.appendChild(descriptionInput);
        const createBtn = document.createElement('button');
        createBtn.type = 'submit';
        createBtn.className = 'btn btn-sm btn-primary';
        createBtn.textContent = 'Create draft';
        form.appendChild(createBtn);
        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const skillName = String(nameInput.value || '').trim();
            if (!skillName) return;
            createBtn.disabled = true;
            try {
                await API.saveSkillDraft(currentAgentId, skillName, {
                    body: 'Add your instructions here.',
                    display_name: skillName.replace(/-/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()),
                    description: String(descriptionInput.value || '').trim(),
                    changelog: 'Initial draft',
                });
                _invalidateSkillCaches(currentAgentId, skillName);
                currentMode = 'studio';
                selectedSkillName = skillName;
                selectedSkillOrigin = 'local';
                _writeState();
                await loadSkills({ soft: true, forceCatalog: true });
            } catch (err) {
                UI.reportError('Failed to create the custom draft', err, { context: 'Custom skill draft create failed' });
            }
            createBtn.disabled = false;
        });
        section.appendChild(form);

        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = `Custom drafts become available on ${_currentAgentLabel()} conversations only after submit, approval, and publish.`;
        section.appendChild(note);
        return section;
    }

    function _buildDraftEditor(detail, lifecycle) {
        const section = document.createElement('section');
        section.className = 'editor-panel';
        section.dataset.key = `skill-draft-editor:${detail.name || ''}`;

        const packageState = lifecycle || detail;
        const requirements = Array.isArray(packageState.requirements)
            ? packageState.requirements.map((item) => ({
                key: item.key || '',
                prompt: item.prompt || '',
                help_url: item.help_url || '',
                validate: item.validate || {},
            }))
            : [];
        const providerConfig = packageState.provider_config || {};
        const files = Array.isArray(packageState.files)
            ? packageState.files.map((item) => ({
                relative_path: item.relative_path || '',
                content_text: item.content_text || '',
                content_type: item.content_type || '',
                executable: Boolean(item.executable),
            }))
            : [];

        const status = document.createElement('div');
        status.className = 'workspace-header-main';
        status.innerHTML = `<div class="workspace-title-group"><strong>${UI.esc(detail.display_name || detail.name || 'Custom skill')}</strong></div>`;
        const badge = document.createElement('span');
        badge.className = `badge badge-${String((lifecycle && lifecycle.lifecycle_status) || detail.lifecycle_status || 'draft')}`;
        badge.textContent = String((lifecycle && lifecycle.lifecycle_status) || detail.lifecycle_status || 'draft').replace(/_/g, ' ');
        status.appendChild(badge);
        section.appendChild(status);

        const readiness = document.createElement('p');
        readiness.className = 'quiet-note';
        readiness.textContent = packageState.publish_ready
            ? 'This draft is structurally ready for submit and publish.'
            : 'This draft still has validation problems. Fix them before submitting or publishing.';
        section.appendChild(readiness);

        const displayNameInput = document.createElement('input');
        displayNameInput.className = 'input';
        displayNameInput.value = detail.display_name || '';
        displayNameInput.placeholder = 'Display name';
        section.appendChild(displayNameInput);

        const descriptionInput = document.createElement('input');
        descriptionInput.className = 'input';
        descriptionInput.value = detail.description || '';
        descriptionInput.placeholder = 'Short description';
        section.appendChild(descriptionInput);

        const changelogInput = document.createElement('input');
        changelogInput.className = 'input';
        changelogInput.placeholder = 'Changelog (optional)';
        section.appendChild(changelogInput);

        const bodyInput = document.createElement('textarea');
        bodyInput.className = 'guidance-textarea';
        bodyInput.rows = 14;
        bodyInput.value = detail.body || '';
        section.appendChild(bodyInput);

        const requirementsLabel = document.createElement('div');
        requirementsLabel.className = 'detail-label';
        requirementsLabel.textContent = 'Setup requirements';
        section.appendChild(requirementsLabel);
        const requirementsList = document.createElement('div');
        requirementsList.className = 'list-shell';
        section.appendChild(requirementsList);

        function addRequirementRow(requirement = {}) {
            const card = document.createElement('div');
            card.className = 'editor-panel';
            const inputs = document.createElement('div');
            inputs.className = 'route-controls';

            const keyInput = document.createElement('input');
            keyInput.className = 'input';
            keyInput.placeholder = 'Credential key';
            keyInput.value = requirement.key || '';
            inputs.appendChild(keyInput);

            const promptInput = document.createElement('input');
            promptInput.className = 'input';
            promptInput.placeholder = 'Prompt shown during setup';
            promptInput.value = requirement.prompt || '';
            inputs.appendChild(promptInput);
            card.appendChild(inputs);

            const helpUrlInput = document.createElement('input');
            helpUrlInput.className = 'input';
            helpUrlInput.placeholder = 'Help URL (optional)';
            helpUrlInput.value = requirement.help_url || '';
            card.appendChild(helpUrlInput);

            const validationInput = document.createElement('textarea');
            validationInput.className = 'guidance-textarea';
            validationInput.rows = 4;
            validationInput.placeholder = 'Validation JSON (optional)';
            validationInput.value = requirement.validate && Object.keys(requirement.validate).length
                ? JSON.stringify(requirement.validate, null, 2)
                : '';
            card.appendChild(validationInput);

            const remove = _dangerActionButton('Remove requirement', async () => {
                card.remove();
            });
            const actionsRow = document.createElement('div');
            actionsRow.className = 'editor-actions';
            actionsRow.appendChild(remove);
            card.appendChild(actionsRow);
            requirementsList.appendChild(card);
        }

        requirements.forEach((item) => addRequirementRow(item));
        const addRequirement = _actionButton('Add requirement', async () => addRequirementRow());
        section.appendChild(addRequirement);

        const providerLabel = document.createElement('div');
        providerLabel.className = 'detail-label';
        providerLabel.textContent = 'Provider config';
        section.appendChild(providerLabel);
        const providerEditors = new Map();
        const providerList = document.createElement('div');
        providerList.className = 'list-shell';
        section.appendChild(providerList);

        function ensureProviderEditor(providerName, initialValue = {}) {
            const normalized = String(providerName || '').trim();
            if (!normalized || providerEditors.has(normalized)) {
                return;
            }
            const card = document.createElement('div');
            card.className = 'editor-panel';
            card.dataset.provider = normalized;
            const heading = document.createElement('div');
            heading.className = 'editor-section-title';
            heading.textContent = normalized;
            card.appendChild(heading);
            const textarea = document.createElement('textarea');
            textarea.className = 'guidance-textarea';
            textarea.rows = 6;
            textarea.value = initialValue && Object.keys(initialValue).length
                ? JSON.stringify(initialValue, null, 2)
                : '';
            card.appendChild(textarea);
            const actionsRow = document.createElement('div');
            actionsRow.className = 'editor-actions';
            actionsRow.appendChild(_dangerActionButton('Remove provider config', async () => {
                providerEditors.delete(normalized);
                card.remove();
            }));
            card.appendChild(actionsRow);
            providerList.appendChild(card);
            providerEditors.set(normalized, textarea);
        }

        ['claude', 'codex'].forEach((providerName) => ensureProviderEditor(providerName, providerConfig[providerName] || {}));
        Object.keys(providerConfig).sort().forEach((providerName) => ensureProviderEditor(providerName, providerConfig[providerName] || {}));
        const providerControls = document.createElement('div');
        providerControls.className = 'route-controls';
        const providerInput = document.createElement('input');
        providerInput.className = 'input';
        providerInput.placeholder = 'Provider name';
        providerControls.appendChild(providerInput);
        const addProvider = _actionButton('Add provider config', async () => {
            ensureProviderEditor(providerInput.value, {});
            providerInput.value = '';
        });
        providerControls.appendChild(addProvider);
        section.appendChild(providerControls);

        const filesLabel = document.createElement('div');
        filesLabel.className = 'detail-label';
        filesLabel.textContent = 'Attached files';
        section.appendChild(filesLabel);
        const filesList = document.createElement('div');
        filesList.className = 'list-shell';
        section.appendChild(filesList);

        function addFileRow(fileState = {}) {
            const card = document.createElement('div');
            card.className = 'editor-panel';

            const pathInput = document.createElement('input');
            pathInput.className = 'input';
            pathInput.placeholder = 'relative/path.ext';
            pathInput.value = fileState.relative_path || '';
            card.appendChild(pathInput);

            const fileMeta = document.createElement('div');
            fileMeta.className = 'route-controls';
            const typeInput = document.createElement('input');
            typeInput.className = 'input';
            typeInput.placeholder = 'Content type';
            typeInput.value = fileState.content_type || '';
            fileMeta.appendChild(typeInput);
            const execWrap = document.createElement('label');
            execWrap.className = 'toggle-switch';
            const execInput = document.createElement('input');
            execInput.type = 'checkbox';
            execInput.checked = Boolean(fileState.executable);
            const execSlider = document.createElement('span');
            execSlider.className = 'slider';
            execWrap.appendChild(execInput);
            execWrap.appendChild(execSlider);
            fileMeta.appendChild(execWrap);
            card.appendChild(fileMeta);

            const contentInput = document.createElement('textarea');
            contentInput.className = 'guidance-textarea';
            contentInput.rows = 8;
            contentInput.placeholder = 'File contents';
            contentInput.value = fileState.content_text || '';
            card.appendChild(contentInput);

            const actionsRow = document.createElement('div');
            actionsRow.className = 'editor-actions';
            actionsRow.appendChild(_dangerActionButton('Remove file', async () => {
                card.remove();
            }));
            card.appendChild(actionsRow);

            card.__stateInputs = { pathInput, typeInput, execInput, contentInput };
            filesList.appendChild(card);
        }

        files.forEach((item) => addFileRow(item));
        const addFile = _actionButton('Add file', async () => addFileRow());
        section.appendChild(addFile);

        function collectRequirements() {
            return Array.from(requirementsList.children).map((card) => {
                const inputs = card.querySelectorAll('input, textarea');
                const key = String(inputs[0]?.value || '').trim();
                const prompt = String(inputs[1]?.value || '').trim();
                const helpUrl = String(inputs[2]?.value || '').trim();
                const validationText = String(inputs[3]?.value || '').trim();
                let validate = null;
                if (validationText) {
                    try {
                        validate = JSON.parse(validationText);
                    } catch (error) {
                        throw new Error(`Requirement '${key || 'credential'}' has invalid validation JSON.`);
                    }
                }
                return {
                    key,
                    prompt,
                    help_url: helpUrl,
                    validate,
                };
            });
        }

        function collectProviderConfig() {
            const nextConfig = {};
            for (const [providerName, textarea] of providerEditors.entries()) {
                const text = String(textarea.value || '').trim();
                if (!text) continue;
                let parsed;
                try {
                    parsed = JSON.parse(text);
                } catch (error) {
                    throw new Error(`Provider config for '${providerName}' must be valid JSON.`);
                }
                if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
                    throw new Error(`Provider config for '${providerName}' must be a JSON object.`);
                }
                nextConfig[providerName] = parsed;
            }
            return nextConfig;
        }

        function collectFiles() {
            return Array.from(filesList.children).map((card) => {
                const state = card.__stateInputs || {};
                return {
                    relative_path: String(state.pathInput?.value || '').trim(),
                    content_type: String(state.typeInput?.value || '').trim(),
                    executable: Boolean(state.execInput?.checked),
                    content_text: String(state.contentInput?.value || ''),
                };
            });
        }

        const actions = document.createElement('div');
        actions.className = 'editor-actions';
        actions.appendChild(_actionButton('Save draft', async () => {
            const requirementsPayload = collectRequirements();
            const providerConfigPayload = collectProviderConfig();
            const filesPayload = collectFiles();
            await API.saveSkillDraft(currentAgentId, detail.name, {
                body: bodyInput.value,
                display_name: displayNameInput.value,
                description: descriptionInput.value,
                requirements: requirementsPayload,
                provider_config: providerConfigPayload,
                files: filesPayload,
                changelog: changelogInput.value,
            });
            _invalidateSkillCaches(currentAgentId, detail.name);
            await loadSelectionData({ soft: true });
            await loadSkills({ soft: true, forceCatalog: true });
        }, 'Saving…'));
        actions.appendChild(_actionButton('Submit', async () => {
            await API.submitSkillDraft(currentAgentId, detail.name, {});
            _invalidateSkillCaches(currentAgentId, detail.name);
            await loadSelectionData({ soft: true });
            await loadSkills({ soft: true, forceCatalog: true });
        }));
        actions.appendChild(_actionButton('Approve', async () => {
            await API.approveSkillDraft(currentAgentId, detail.name, {});
            _invalidateSkillCaches(currentAgentId, detail.name);
            await loadSelectionData({ soft: true });
            await loadSkills({ soft: true, forceCatalog: true });
        }));
        actions.appendChild(_actionButton('Reject', async () => {
            await API.rejectSkillDraft(currentAgentId, detail.name, {});
            _invalidateSkillCaches(currentAgentId, detail.name);
            await loadSelectionData({ soft: true });
            await loadSkills({ soft: true, forceCatalog: true });
        }));
        actions.appendChild(_actionButton('Publish', async () => {
            await API.publishSkillDraft(currentAgentId, detail.name, {});
            _invalidateSkillCaches(currentAgentId, detail.name);
            await loadSelectionData({ soft: true });
            await loadSkills({ soft: true, forceCatalog: true });
        }));
        actions.appendChild(_dangerActionButton('Archive', async () => {
            await API.archiveSkillDraft(currentAgentId, detail.name, {});
            _invalidateSkillCaches(currentAgentId, detail.name);
            await loadSelectionData({ soft: true });
            await loadSkills({ soft: true, forceCatalog: true });
        }));
        section.appendChild(actions);

        if (Array.isArray(packageState.validation_problems) && packageState.validation_problems.length) {
            const validationLabel = document.createElement('div');
            validationLabel.className = 'detail-label';
            validationLabel.textContent = 'Validation problems';
            section.appendChild(validationLabel);
            const list = document.createElement('ul');
            list.className = 'change-list';
            packageState.validation_problems.forEach((problem) => {
                const item = document.createElement('li');
                item.innerHTML = [
                    `<strong>${UI.esc(problem.field_path || problem.code || 'problem')}</strong>`,
                    `<div>${UI.esc(problem.message || '')}</div>`,
                ].join('');
                list.appendChild(item);
            });
            section.appendChild(list);
        }

        return section;
    }

    function _buildLifecycleHistory(lifecycle) {
        const section = document.createElement('section');
        section.className = 'editor-panel';
        section.dataset.key = `skill-history:${lifecycle.name || ''}`;

        const revisionsLabel = document.createElement('div');
        revisionsLabel.className = 'detail-label';
        revisionsLabel.textContent = 'Revision history';
        section.appendChild(revisionsLabel);

        if ((lifecycle.revisions || []).length) {
            const revisions = document.createElement('ul');
            revisions.className = 'change-list';
            lifecycle.revisions.slice(0, 8).forEach((item) => {
                const li = document.createElement('li');
                li.innerHTML = [
                    `<strong>${UI.esc(item.version_label || item.revision_id.slice(0, 12))}</strong>`,
                    `<div class="quiet-note">${UI.esc(String(item.status || '').replace(/_/g, ' '))}${item.is_published ? ' · published' : ''}</div>`,
                    item.changelog ? `<div>${UI.esc(item.changelog)}</div>` : '',
                ].join('');
                revisions.appendChild(li);
            });
            section.appendChild(revisions);
        } else {
            section.appendChild(UI.renderEmptyState('No revisions recorded yet.', true));
        }

        const approvalsLabel = document.createElement('div');
        approvalsLabel.className = 'detail-label';
        approvalsLabel.textContent = 'Lifecycle activity';
        section.appendChild(approvalsLabel);
        if ((lifecycle.approvals || []).length) {
            const approvals = document.createElement('ul');
            approvals.className = 'change-list';
            lifecycle.approvals.slice(0, 8).forEach((item) => {
                const li = document.createElement('li');
                li.innerHTML = [
                    `<strong>${UI.esc(item.action || 'update')}</strong>`,
                    `<div class="quiet-note">${UI.esc(item.actor || 'unknown')}</div>`,
                    item.note ? `<div>${UI.esc(item.note)}</div>` : '',
                ].join('');
                approvals.appendChild(li);
            });
            section.appendChild(approvals);
        } else {
            section.appendChild(UI.renderEmptyState('No lifecycle activity yet.', true));
        }
        return section;
    }

    async function loadSkills({ soft = false, forceCatalog = false } = {}) {
        if (!currentAgentId) {
            allSkills = [];
            registrySkills = [];
            registryError = '';
            selectedLocalDetail = null;
            selectedLifecycle = null;
            renderList();
            return;
        }
        const queryText = _queryText();
        const shouldLoadCatalog = forceCatalog || !allSkills.length;
        const hadVisibleState = listEl.childElementCount > 0;
        let hasCachedView = false;
        if (shouldLoadCatalog) {
            const cachedCatalog = UI.peekCachedData(_skillCacheKey(currentAgentId));
            if (cachedCatalog) {
                const data = Array.isArray(cachedCatalog) ? cachedCatalog : (cachedCatalog.skills || []);
                allSkills = Array.isArray(data) ? data : [];
                hasCachedView = true;
            }
        }
        if (currentMode === 'catalog' && queryText.length >= 2) {
            const cachedSearch = UI.peekCachedData(_skillSearchCacheKey(currentAgentId, queryText));
            if (cachedSearch) {
                registrySkills = Array.isArray(cachedSearch.registry) ? cachedSearch.registry : [];
                registryError = String(cachedSearch.registry_error || '');
                hasCachedView = true;
            }
        } else {
            registrySkills = [];
            registryError = '';
        }
        if (hasCachedView) {
            renderList();
            void loadSelectionData({ soft: true });
        }
        if (!soft && !hasCachedView && (shouldLoadCatalog || (currentMode === 'catalog' && queryText.length >= 2))) {
            renderLoadingState(currentMode === 'catalog' && queryText.length >= 2 ? 'Searching skills…' : 'Loading skills…');
        }
        try {
            if (shouldLoadCatalog) {
                const data = await UI.loadCachedData(
                    _skillCacheKey(currentAgentId),
                    () => API.listSkills(currentAgentId),
                    {
                        ttlMs: SKILL_CACHE_TTL_MS,
                        errorTtlMs: CACHE_ERROR_TTL_MS,
                        forceRefresh: hasCachedView || forceCatalog,
                    },
                );
                allSkills = Array.isArray(data) ? data : (data.skills || []);
            }
            if (currentMode === 'catalog' && queryText.length >= 2) {
                const search = await UI.loadCachedData(
                    _skillSearchCacheKey(currentAgentId, queryText),
                    () => API.searchCatalogSkills(currentAgentId, queryText),
                    {
                        ttlMs: SKILL_SEARCH_CACHE_TTL_MS,
                        errorTtlMs: CACHE_ERROR_TTL_MS,
                        forceRefresh: hasCachedView,
                    },
                );
                registrySkills = Array.isArray(search.registry) ? search.registry : [];
                registryError = String(search.registry_error || '');
            } else {
                registrySkills = [];
                registryError = '';
            }
            renderList();
            await loadSelectionData({ soft: true });
        } catch (err) {
            if (hasCachedView || hadVisibleState) {
                UI.reportError('Failed to refresh skills', err, { context: 'Skills refresh failed' });
                return;
            }
            UI.clearMemoizedRender(listEl);
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load skills: ' + err.message, loadSkills)]);
        }
    }

    async function loadAgents({ soft = false } = {}) {
        try {
            const previousAgentId = currentAgentId;
            const data = await API.listAgents({ limit: 100 });
            availableAgents = Array.isArray(data) ? data : (data.agents || []);
            const requestedAgentId = UI.readQueryParam('agent_id', '');
            if (requestedAgentId) {
                currentAgentId = requestedAgentId;
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
            if (selectedSkillOrigin === 'store' && currentMode !== 'catalog') {
                selectedSkillOrigin = 'local';
            }
            void loadSkills({ soft: true });
        }, 250);
    });

    container.__routeReady = loadAgents();
    modeControl.setActive(currentMode);

    cleanups.add(() => clearTimeout(searchTimeout));
    UI.subscribeWithRefresh(cleanups, 'agents', () => loadAgents({ soft: true }), 600);
}
