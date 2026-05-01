/**
 * Shared skill catalog helpers used by the unified skill pipeline and agent launchers.
 */
const RegistrySkillHub = (() => {
    const SEARCHABLE_LOCAL_FIELDS = ['name', 'display_name', 'description', 'source_kind', 'lifecycle_status'];

    function supportsAdminOperation(agent, operation) {
        const operations = Array.isArray(agent?.supported_admin_operations) ? agent.supported_admin_operations : [];
        return operations.includes(operation);
    }

    function eligibleAgents(agents) {
        return (agents || []).filter((agent) => {
            const connectivity = String(agent?.connectivity_state || '').trim();
            return ['connected', 'degraded'].includes(connectivity)
                && !UI.isDefaultHiddenRecord(agent)
                && (supportsAdminOperation(agent, 'list_catalog_skills')
                    || supportsAdminOperation(agent, 'catalog_skill_lifecycle_detail'));
        });
    }

    function canCreateCustom(agent) {
        return supportsAdminOperation(agent, 'edit_catalog_skill_draft');
    }

    function canSearchStore(agent) {
        return supportsAdminOperation(agent, 'search_catalog_skills') || supportsAdminOperation(agent, 'list_catalog_skills');
    }

    function isCustomSkill(skill) {
        return String(skill?.source_kind || '') === 'custom';
    }

    function _matchesLocalQuery(skill, queryText) {
        const haystack = SEARCHABLE_LOCAL_FIELDS
            .map((field) => String(skill?.[field] || ''))
            .join(' ')
            .toLowerCase();
        return haystack.includes(queryText);
    }

    function _isGeneratedSkill(skill) {
        return UI.isGeneratedTimestampName(skill?.display_name || skill?.name || '');
    }

    function visibleLocalSkills(skills, queryText = '') {
        const normalized = String(queryText || '').trim().toLowerCase();
        const list = Array.isArray(skills) ? skills : [];
        if (!normalized) {
            return list.filter((skill) => !_isGeneratedSkill(skill));
        }
        return list.filter((skill) => _matchesLocalQuery(skill, normalized));
    }

    function visibleStoreSkills(skills, queryText = '') {
        const normalized = String(queryText || '').trim();
        if (normalized.length < 2) {
            return [];
        }
        return Array.isArray(skills) ? skills : [];
    }

    function buildSections(localSkills, storeSkills, queryText = '') {
        const visibleLocal = visibleLocalSkills(localSkills, queryText);
        const custom = visibleLocal.filter((skill) => isCustomSkill(skill));
        const installed = visibleLocal.filter((skill) => !isCustomSkill(skill));
        const visibleStore = visibleStoreSkills(storeSkills, queryText);
        return [
            { key: 'custom', label: 'Custom', items: custom, origin: 'local' },
            { key: 'installed', label: 'Installed on this bot', items: installed, origin: 'local' },
            { key: 'store', label: 'Store', items: visibleStore, origin: 'store' },
        ].filter((section) => section.items.length > 0);
    }

    function findSelectedSkill(localSkills, storeSkills, selectedSkillName) {
        const local = (localSkills || []).find((item) => item && item.name === selectedSkillName);
        if (local) {
            return { origin: 'local', skill: local };
        }
        const store = (storeSkills || []).find((item) => item && item.name === selectedSkillName);
        if (store) {
            return { origin: 'store', skill: store };
        }
        return null;
    }

    function localRowMeta(skill) {
        const lifecycle = lifecycleState(skill);
        const fragments = [];
        if (skill?.description) fragments.push(String(skill.description));
        if (skill?.runtime_available === false) fragments.push('not active until published');
        if (skill?.requires_credentials) fragments.push('setup required on activation');
        if (skill?.default_for_new_conversations) fragments.push('default for new conversations');
        if (lifecycle.label) fragments.push(lifecycle.label);
        if (skill?.has_unpublished_changes) fragments.push('unpublished changes');
        return {
            label: skill?.display_name || skill?.name || '',
            sublabel: fragments.join(' • ') || 'Available on this bot',
            badgeText: String(skill?.source_label || skill?.source_kind || 'Skill'),
        };
    }

    function storeRowMeta(skill) {
        const fragments = [];
        if (skill?.description) fragments.push(String(skill.description));
        if (skill?.publisher) fragments.push(`by ${String(skill.publisher)}`);
        if (skill?.version) fragments.push(`v${String(skill.version)}`);
        return {
            label: skill?.display_name || skill?.name || '',
            sublabel: fragments.join(' • ') || 'Available from the skill store',
            badgeText: String(skill?.source_label || 'Store'),
        };
    }

    function listCacheKey(agentId) {
        return `skills:list:${String(agentId || '').trim()}`;
    }

    function searchCacheKey(agentId, queryText) {
        return `skills:search:${String(agentId || '').trim()}:${String(queryText || '').trim().toLowerCase()}`;
    }

    function detailCacheKey(agentId, skillName) {
        return `skills:detail:${String(agentId || '').trim()}:${String(skillName || '').trim()}`;
    }

    function lifecycleCacheKey(agentId, skillName) {
        return `skills:lifecycle:${String(agentId || '').trim()}:${String(skillName || '').trim()}`;
    }

    function lifecycleState(item) {
        const rawStatus = String(item?.lifecycle_status || '').trim().toLowerCase() || 'draft';
        const approvals = Array.isArray(item?.approvals) ? item.approvals : [];
        const latestAction = String(approvals[0]?.action || '').trim().toLowerCase();
        const effectiveStatus = rawStatus === 'review' && latestAction === 'approved'
            ? 'approved'
            : rawStatus;
        return {
            rawStatus,
            latestAction,
            effectiveStatus,
            label: String(effectiveStatus || 'draft').replace(/_/g, ' '),
            canSubmit: rawStatus === 'draft',
            canApprove: rawStatus === 'review' && latestAction !== 'approved',
            canPublish: effectiveStatus === 'approved',
            isArchived: rawStatus === 'archived',
            isPublished: rawStatus === 'published',
        };
    }

    function skillWorkspaceHref(agentId, skillName = '', { origin = 'local', tab = '' } = {}) {
        const url = new URL('/ui/skills', window.location.origin);
        if (agentId) {
            url.searchParams.set('agent_id', String(agentId));
        }
        if (skillName) {
            url.searchParams.set('skill', String(skillName));
        }
        if (origin === 'store' && skillName) {
            url.searchParams.set('skill_source', 'store');
        }
        if (tab && origin === 'local') {
            url.searchParams.set('skill_tab', String(tab));
        }
        return `${url.pathname}${url.search}`;
    }

    function conversationActivationHref(conversationId, skillName) {
        const url = new URL(`/ui/conversations/${encodeURIComponent(conversationId)}`, window.location.origin);
        url.searchParams.set('manage', 'skills');
        if (skillName) {
            url.searchParams.set('activate_skill', String(skillName));
        }
        return `${url.pathname}${url.search}`;
    }

    async function openConversationForSkill(agentId, skillName, { agentLabel = '' } = {}) {
        const label = String(agentLabel || 'this bot');
        const conversation = await API.openConversationForAgent(agentId, {
            title: `Conversation with ${label}`,
        });
        const normalizedSkill = String(skillName || '').trim();
        if (!normalizedSkill) {
            Router.navigate(`/ui/conversations/${encodeURIComponent(conversation.conversation_id)}`);
            return conversation;
        }
        const activation = await API.activateConversationSkill(agentId, conversation.conversation_id, normalizedSkill, { confirm: true });
        if (activation.status === 'activated' || activation.status === 'already_active') {
            Router.navigate(`/ui/conversations/${encodeURIComponent(conversation.conversation_id)}`);
            return conversation;
        }
        Router.navigate(conversationActivationHref(conversation.conversation_id, normalizedSkill));
        return conversation;
    }

    return {
        supportsAdminOperation,
        eligibleAgents,
        canCreateCustom,
        canSearchStore,
        isCustomSkill,
        visibleLocalSkills,
        visibleStoreSkills,
        buildSections,
        findSelectedSkill,
        localRowMeta,
        storeRowMeta,
        lifecycleState,
        listCacheKey,
        searchCacheKey,
        detailCacheKey,
        lifecycleCacheKey,
        skillWorkspaceHref,
        conversationActivationHref,
        openConversationForSkill,
    };
})();

window.RegistrySkillHub = RegistrySkillHub;

/**
 * Skills catalog - unified bot-scoped skill management.
 */
function renderSkillCatalog(container) {
    const cleanups = UI.beginCleanupScope();
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }
    const SKILL_CACHE_TTL_MS = 60000;
    const SKILL_SEARCH_CACHE_TTL_MS = 30000;
    const SKILL_DETAIL_CACHE_TTL_MS = 60000;
    const CACHE_ERROR_TTL_MS = 5000;

    let searchTimeout = null;
    let currentQ = '';
    let currentAgentId = '';
    let selectedSkillName = _readSkillName();
    let selectedSkillOrigin = _readSkillOrigin();
    let currentStudioTab = _readStudioTab();
    let availableAgents = [];
    let allSkills = [];
    let registrySkills = [];
    let globalRoutingSkills = [];
    let registryError = '';
    let globalRoutingError = '';
    let selectedLocalDetail = null;
    let selectedLifecycle = null;
    let selectedGlobalDetail = null;
    let selectedGlobalDetailAgent = null;
    let selectedGlobalDetailError = null;
    let globalSelectionLoading = false;
    let selectionLoading = false;
    let draftBuffer = null;
    let draftDirty = false;
    let draftStatus = 'idle';
    let draftStatusMessage = '';
    let draftSnapshotKey = '';

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = [
        '<h2>Skills</h2>',
        '<p class="quiet-note">',
        'Find reusable skills for conversations and protocol stages. Choose a bot only when you need to manage installation or drafts.',
        '</p>',
    ].join('');
    container.appendChild(header);

    const shell = document.createElement('section');
    shell.className = 'admin-shell';
    container.appendChild(shell);

    const controlsPanel = document.createElement('section');
    controlsPanel.className = 'workbench-panel';
    shell.appendChild(controlsPanel);

    const controls = document.createElement('div');
    controls.className = 'route-controls';
    controlsPanel.appendChild(controls);

    const agentDropdown = UI.createAgentManagementDropdown([], '', (nextAgentId) => {
        _runWithDraftGuard(async () => {
            currentAgentId = nextAgentId;
            selectedLocalDetail = null;
            selectedLifecycle = null;
            selectionLoading = false;
            _clearDraftState();
            _writeState();
            await loadSkills({ forceCatalog: true });
        });
    }, {
        allowEmpty: true,
        emptyLabel: 'Choose a bot',
    });
    controls.appendChild(agentDropdown.element);

    const searchInput = document.createElement('input');
    searchInput.className = 'search-input';
    searchInput.placeholder = 'Search skills';
    searchInput.type = 'text';
    searchInput.setAttribute('aria-label', 'Search skills');
    controls.appendChild(searchInput);

    const controlsActions = document.createElement('div');
    controlsActions.className = 'editor-actions';
    const createDraftBtn = document.createElement('button');
    createDraftBtn.type = 'button';
    createDraftBtn.className = 'btn btn-sm btn-primary';
    createDraftBtn.textContent = 'New skill';
    createDraftBtn.addEventListener('click', () => _beginStudioDialog(_openCreateDraftDialog));
    controlsActions.appendChild(createDraftBtn);
    const importBtn = document.createElement('button');
    importBtn.type = 'button';
    importBtn.className = 'btn btn-sm';
    importBtn.textContent = 'Import';
    importBtn.addEventListener('click', () => _beginStudioDialog(_openImportDialog));
    controlsActions.appendChild(importBtn);
    controls.appendChild(controlsActions);

    const workspace = document.createElement('section');
    workspace.className = 'dashboard-board';
    shell.appendChild(workspace);

    const listWrap = document.createElement('section');
    listWrap.className = 'list-shell dashboard-column';
    workspace.appendChild(listWrap);

    const listEl = document.createElement('div');
    listEl.className = 'list-container';
    listWrap.appendChild(listEl);

    const detailEl = document.createElement('section');
    detailEl.className = 'editor-shell dashboard-column';
    workspace.appendChild(detailEl);

    function _readSkillName() {
        return UI.readQueryParam('skill', '');
    }

    function _readSkillOrigin() {
        const value = UI.readQueryParam('skill_source', 'local');
        if (value === 'store' || value === 'global') return value;
        return 'local';
    }

    function _readStudioTab() {
        const value = UI.readQueryParam('skill_tab', 'write');
        return ['write', 'setup', 'review', 'advanced'].includes(value) ? value : 'write';
    }

    function _writeState() {
        UI.updateQueryParams({
            agent_id: currentAgentId || '',
            skills_view: '',
            skill: selectedSkillName || '',
            skill_source: selectedSkillName && ['store', 'global'].includes(selectedSkillOrigin) ? selectedSkillOrigin : '',
            skill_tab: selectedSkillName && selectedSkillOrigin === 'local' && RegistrySkillHub.isCustomSkill(_findSelectedSkill()?.skill)
                ? currentStudioTab
                : '',
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
        return RegistrySkillHub.eligibleAgents(availableAgents);
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
            currentAgentId = agents.length === 1 ? String(agents[0].agent_id || '') : '';
        }
        agentDropdown.update(agents, currentAgentId);
        const agent = _currentAgent();
        const lifecycleCapable = RegistrySkillHub.canCreateCustom(agent);
        createDraftBtn.hidden = !lifecycleCapable;
        importBtn.hidden = !lifecycleCapable;
        _writeState();
    }

    function _queryText() {
        return String(currentQ || '').trim();
    }

    function _invalidateSkillCaches(agentId = currentAgentId, skillName = '') {
        const normalizedAgentId = String(agentId || '').trim();
        if (!normalizedAgentId) return;
        const prefixes = [
            RegistrySkillHub.listCacheKey(normalizedAgentId),
            `skills:search:${normalizedAgentId}:`,
        ];
        if (skillName) {
            prefixes.push(RegistrySkillHub.detailCacheKey(normalizedAgentId, skillName));
            prefixes.push(RegistrySkillHub.lifecycleCacheKey(normalizedAgentId, skillName));
        } else {
            prefixes.push(`skills:detail:${normalizedAgentId}:`);
            prefixes.push(`skills:lifecycle:${normalizedAgentId}:`);
        }
        UI.invalidateCachedData(prefixes);
    }

    function _cloneValue(value) {
        try {
            return JSON.parse(JSON.stringify(value));
        } catch {
            return value;
        }
    }

    function _packageState(detail, lifecycle) {
        return lifecycle || detail || {};
    }

    function _editableDraftState(detail, lifecycle) {
        const primary = detail || {};
        const fallback = lifecycle || {};
        return {
            skill_kind: String(primary.skill_kind || fallback.skill_kind || 'prompt'),
            body: String(primary.body || fallback.body || ''),
            requirements: Array.isArray(primary.requirements)
                ? primary.requirements
                : (Array.isArray(fallback.requirements) ? fallback.requirements : []),
            provider_config: (
                primary.provider_config && typeof primary.provider_config === 'object'
            )
                ? primary.provider_config
                : (
                    fallback.provider_config && typeof fallback.provider_config === 'object'
                        ? fallback.provider_config
                        : {}
                ),
            files: Array.isArray(primary.files)
                ? primary.files
                : (Array.isArray(fallback.files) ? fallback.files : []),
        };
    }

    function _draftSnapshot(detail, lifecycle) {
        const packageState = _packageState(detail, lifecycle);
        const editableState = _editableDraftState(detail, lifecycle);
        return JSON.stringify({
            name: detail?.name || '',
            display_name: detail?.display_name || '',
            description: detail?.description || '',
            skill_kind: editableState.skill_kind,
            body: editableState.body,
            lifecycle_status: String(packageState.lifecycle_status || detail?.lifecycle_status || ''),
            active_revision_id: String(lifecycle?.active_revision_id || ''),
            published_revision_id: String(lifecycle?.published_revision_id || ''),
            requirements: editableState.requirements,
            provider_config: editableState.provider_config,
            files: editableState.files,
        });
    }

    function _isSelectedCustom(summary, detail) {
        return String(summary?.source_kind || detail?.source_kind || '') === 'custom';
    }

    function _resetDraftState(detail, lifecycle) {
        const editableState = _editableDraftState(detail, lifecycle);
        draftBuffer = {
            name: detail?.name || '',
            display_name: detail?.display_name || '',
            description: detail?.description || '',
            skill_kind: editableState.skill_kind,
            body: editableState.body,
            changelog: '',
            requirements: Array.isArray(editableState.requirements)
                ? editableState.requirements.map((item) => ({
                    key: item.key || '',
                    prompt: item.prompt || '',
                    help_url: item.help_url || '',
                    validate: item.validate || null,
                }))
                : [],
            provider_config: _cloneValue(
                editableState.provider_config && typeof editableState.provider_config === 'object'
                    ? editableState.provider_config
                    : {}
            ),
            files: Array.isArray(editableState.files)
                ? editableState.files.map((item) => ({
                    relative_path: item.relative_path || '',
                    content_text: item.content_text || '',
                    content_type: item.content_type || '',
                    executable: Boolean(item.executable),
                }))
                : [],
        };
        draftDirty = false;
        draftStatus = 'idle';
        draftStatusMessage = '';
        draftSnapshotKey = _draftSnapshot(detail, lifecycle);
    }

    function _clearDraftState() {
        draftBuffer = null;
        draftDirty = false;
        draftStatus = 'idle';
        draftStatusMessage = '';
        draftSnapshotKey = '';
    }

    function _mergeSkillDetailIntoRecords(records, detail) {
        const normalizedName = String(detail?.name || '').trim();
        if (!normalizedName) return Array.isArray(records) ? [...records] : [];
        const currentRecords = Array.isArray(records) ? records : [];
        const current = currentRecords.find((item) => String(item?.name || '').trim() === normalizedName) || null;
        const nextLifecycle = RegistrySkillHub.lifecycleState(detail);
        const merged = {
            ...(current || {}),
            ...detail,
            lifecycle_status: nextLifecycle.effectiveStatus || detail.lifecycle_status || current?.lifecycle_status || '',
            runtime_available: Boolean(detail?.runtime_available ?? current?.runtime_available),
            has_unpublished_changes: Boolean(detail?.published_revision_id)
                && String(detail?.published_revision_id || '') !== String(detail?.active_revision_id || ''),
        };
        const nextRecords = currentRecords.filter((item) => String(item?.name || '').trim() !== normalizedName);
        nextRecords.push(merged);
        return nextRecords;
    }

    function _preserveSelectedCustomDraft(records) {
        const normalizedSelectedName = String(selectedSkillName || '').trim();
        if (selectedSkillOrigin !== 'local' || !normalizedSelectedName) {
            return Array.isArray(records) ? records : [];
        }
        const candidate = (selectedLocalDetail && String(selectedLocalDetail.name || '').trim() === normalizedSelectedName)
            ? selectedLocalDetail
            : (draftBuffer && String(draftBuffer.name || '').trim() === normalizedSelectedName
                ? draftBuffer
                : null);
        if (!candidate || !RegistrySkillHub.isCustomSkill(candidate)) {
            return Array.isArray(records) ? records : [];
        }
        return _mergeSkillDetailIntoRecords(records, candidate);
    }

    function _applyStudioMutationDetail(detail) {
        if (!detail || !detail.name) {
            return false;
        }
        const selected = _findSelectedSkill();
        if (!selected || String(selected.skill?.name || '') !== String(detail.name || '')) {
            return false;
        }
        if (selected.origin === 'local') {
            selectedLocalDetail = {
                ...(selectedLocalDetail && selectedLocalDetail.name === detail.name ? selectedLocalDetail : selected.skill || {}),
                ...detail,
            };
            selectedLifecycle = detail;
            allSkills = _mergeSkillDetailIntoRecords(allSkills, selectedLocalDetail);
            selectionLoading = false;
            if (_isSelectedCustom(selected.skill, selectedLocalDetail || detail)) {
                _resetDraftState(selectedLocalDetail || detail, detail);
            } else {
                _clearDraftState();
            }
            renderList();
            return true;
        }
        return false;
    }

    function _hasUnsavedDraft() {
        return draftDirty && Boolean(draftBuffer && draftBuffer.name);
    }

    function _isActiveSkillsWorkspace() {
        try {
            return String(window.location.pathname || '') === '/ui/skills';
        } catch {
            return false;
        }
    }

    function _runWithDraftGuard(action) {
        if (!_hasUnsavedDraft()) {
            void action();
            return;
        }
        UI.showConfirm(
            'Discard unsaved changes?',
            'The current draft has unsaved changes. Discard them and continue?',
            async () => {
                _clearDraftState();
                await action();
            },
        );
    }

    function _resetStudioSelection() {
        selectedSkillName = '';
        selectedSkillOrigin = 'local';
        currentStudioTab = 'write';
        selectedLocalDetail = null;
        selectedLifecycle = null;
        selectionLoading = false;
        _clearDraftState();
        _writeState();
        renderList();
    }

    function _beginStudioDialog(openDialog) {
        _runWithDraftGuard(async () => {
            _resetStudioSelection();
            openDialog();
        });
    }

    function _visibleLocalSkills() {
        return RegistrySkillHub.visibleLocalSkills(allSkills, _queryText());
    }

    function _visibleStoreSkills() {
        if (!RegistrySkillHub.canSearchStore(_currentAgent()) || _queryText().length < 2) {
            return [];
        }
        return RegistrySkillHub.visibleStoreSkills(registrySkills, _queryText());
    }

    function _visibleGlobalSkills() {
        const normalized = _queryText();
        return (Array.isArray(globalRoutingSkills) ? globalRoutingSkills : [])
            .filter((item) => {
                const name = String(item?.skill_name || '').trim();
                if (!UI.isHumanAssignableSkillName(name)) return false;
                if (!normalized) return true;
                return [name, ...(Array.isArray(item?.advertised_by_agents) ? item.advertised_by_agents : [])]
                    .join(' ')
                    .toLowerCase()
                    .includes(normalized);
            })
            .sort((left, right) => String(left.skill_name || '').localeCompare(String(right.skill_name || '')));
    }

    function _globalSkillLabel(item) {
        return String(item?.skill_name || '')
            .trim()
            .replace(/[-_]+/g, ' ')
            .replace(/\b\w/g, (letter) => letter.toUpperCase());
    }

    function _findSelectedGlobalSkill() {
        const normalized = String(selectedSkillName || '').trim().toLowerCase();
        if (!normalized || selectedSkillOrigin !== 'global') return null;
        return _visibleGlobalSkills().find((item) =>
            String(item?.skill_name || '').trim().toLowerCase() === normalized) || null;
    }

    function _globalSkillAdvertisers(item) {
        return Array.isArray(item?.advertised_by_agents) ? item.advertised_by_agents : [];
    }

    function _globalSkillAgents(item) {
        const advertisers = _globalSkillAdvertisers(item)
            .map((value) => String(value || '').trim().toLowerCase())
            .filter(Boolean);
        if (!advertisers.length) return [];
        return _eligibleAgents().filter((agent) => {
            const names = [
                agent.agent_id,
                agent.slug,
                agent.display_name,
                UI.visibleLabel(agent.display_name, agent.slug, agent.agent_id),
            ].map((value) => String(value || '').trim().toLowerCase()).filter(Boolean);
            return names.some((value) => advertisers.includes(value));
        });
    }

    function _findSelectedSkill() {
        return RegistrySkillHub.findSelectedSkill(_visibleLocalSkills(), _visibleStoreSkills(), selectedSkillName);
    }

    function _ensureSelection() {
        const current = _findSelectedSkill();
        if (current) {
            selectedSkillOrigin = current.origin;
            return;
        }
        selectedSkillName = '';
        selectedSkillOrigin = 'local';
        _writeState();
    }

    function renderLoadingState(message = 'Loading skills…') {
        UI.clearMemoizedRender(listEl);
        UI.reconcileChildren(listEl, [UI.renderEmptyState(message, true)]);
    }

    async function _selectSkill(skillName, origin) {
        selectedSkillName = String(skillName || '').trim();
        selectedSkillOrigin = origin === 'store' || origin === 'global' ? origin : 'local';
        const selected = _findSelectedSkill();
        if (selectedSkillOrigin === 'local' && RegistrySkillHub.isCustomSkill(selected?.skill)) {
            currentStudioTab = 'write';
        }
        selectedLocalDetail = null;
        selectedLifecycle = null;
        selectedGlobalDetail = null;
        selectedGlobalDetailAgent = null;
        selectedGlobalDetailError = null;
        globalSelectionLoading = selectedSkillOrigin === 'global' && Boolean(selectedSkillName);
        selectionLoading = selectedSkillOrigin === 'local' && Boolean(selectedSkillName);
        if (selectedSkillOrigin !== 'local') {
            _clearDraftState();
        }
        _writeState();
        renderList();
        if (selectedSkillOrigin === 'global' || selectedSkillOrigin === 'local') {
            await loadSelectionData();
        }
    }

    function renderList() {
        _syncCatalogLayout();
        if (!currentAgentId) {
            UI.clearMemoizedRender(listEl);
            const skills = _visibleGlobalSkills();
            if (skills.length) {
                UI.reconcileChildren(listEl, [
                    _renderGlobalCatalogIntro(),
                    _sectionLabel('Available skills', 'skills-global-heading'),
                    ...skills.map((item) => _renderGlobalSkillRow(item, {
                        selected: String(selectedSkillOrigin || '') === 'global'
                            && String(selectedSkillName || '').trim().toLowerCase() === String(item?.skill_name || '').trim().toLowerCase(),
                        detail: selectedGlobalDetail,
                        detailAgent: selectedGlobalDetailAgent,
                        detailError: selectedGlobalDetailError,
                        loading: globalSelectionLoading,
                    })),
                    ...(globalRoutingError ? [UI.renderEmptyState(`Skill catalog is incomplete. ${globalRoutingError}`, true)] : []),
                ]);
            } else {
                const hasEligibleAgents = _eligibleAgents().length > 0;
                UI.reconcileChildren(listEl, [
                    _renderGlobalCatalogIntro(),
                    UI.renderEmptyState(
                        hasEligibleAgents
                            ? 'No skills match this search. Choose a bot to manage installation or drafts.'
                            : 'No connected bot advertises skill management.',
                        true,
                    ),
                ]);
            }
            return;
        }
        const visibleLocal = _visibleLocalSkills();
        const visibleStore = _visibleStoreSkills();
        const sections = RegistrySkillHub.buildSections(visibleLocal, visibleStore, _queryText());
        _ensureSelection();

        if (!sections.length) {
            UI.clearMemoizedRender(listEl);
            const message = _queryText()
                ? 'No installed or store skills match this search.'
                : 'No skills are available on this bot yet. Create a custom skill or import one to get started.';
            UI.reconcileChildren(listEl, [UI.renderEmptyState(message, true)]);
            return;
        }

        UI.memoizedRender(listEl, {
            selectedSkillName,
            selectedSkillOrigin,
            detailSignature: _selectedSkillDetailSignature(),
            sections,
            registryError,
        }, (state) => {
            const nodes = [];
            if (!state.selectedSkillName) {
                nodes.push(_renderAgentSkillIntro(_currentAgentLabel()));
            }
            (state.sections || []).forEach((section) => {
                nodes.push(_sectionLabel(section.label, `skills-${section.key}-heading`));
                nodes.push(...section.items.map((skill) => (
                    section.origin === 'store'
                        ? _renderRegistrySkillRow(skill, {
                            selected: state.selectedSkillOrigin === 'store' && state.selectedSkillName === skill.name,
                        })
                        : _renderLocalSkillRow(skill, {
                            selected: state.selectedSkillOrigin === 'local' && state.selectedSkillName === skill.name,
                        })
                )));
            });
            if (state.registryError && _queryText().length >= 2) {
                const notice = UI.renderEmptyState(`Store search unavailable. ${state.registryError}`, true);
                notice.dataset.key = 'skill-store-error';
                nodes.push(notice);
            }
            return nodes;
        }, {
            signatureFn(state) {
                return {
                    selectedSkillName: String(state.selectedSkillName || ''),
                    selectedSkillOrigin: String(state.selectedSkillOrigin || ''),
                    sections: (state.sections || []).map((section) => ({
                        key: String(section.key || ''),
                        label: String(section.label || ''),
                        items: (section.items || []).map((skill) => ({
                            name: String(skill.name || ''),
                            source: String(skill.source_label || skill.source_kind || ''),
                            lifecycle: String(skill.lifecycle_status || ''),
                            runtime: Boolean(skill.runtime_available),
                            publisher: String(skill.publisher || ''),
                            version: String(skill.version || ''),
                        })),
                    })),
                    registryError: String(state.registryError || ''),
                    detailSignature: String(state.detailSignature || ''),
                };
            },
        });
    }

    function _syncCatalogLayout() {
        workspace.classList.add('dashboard-board-stacked');
        detailEl.hidden = true;
    }

    function _renderGlobalCatalogIntro() {
        const panel = document.createElement('section');
        panel.className = 'editor-panel';
        panel.dataset.key = 'skill-catalog-intro';
        const title = document.createElement('h3');
        title.textContent = 'Skill catalog';
        panel.appendChild(title);
        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = 'This default view shows skills available for assignment. Choose a bot only when you need to install, draft, import, or review skill implementation.';
        panel.appendChild(note);
        if (_eligibleAgents().length) {
            const manage = document.createElement('p');
            manage.className = 'quiet-note';
            manage.textContent = 'Bot management is available from the selector above.';
            panel.appendChild(manage);
        }
        return panel;
    }

    function _renderAgentSkillIntro(agentLabel) {
        const panel = document.createElement('section');
        panel.className = 'editor-panel';
        panel.dataset.key = 'agent-skill-intro';
        const title = document.createElement('h3');
        title.textContent = 'Skills';
        panel.appendChild(title);
        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = `Select a skill for ${agentLabel}, create a new custom skill, or import a package to start editing.`;
        panel.appendChild(note);
        return panel;
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

    function _renderGlobalSkillRow(item, {
        selected = false,
        detail = null,
        detailAgent = null,
        detailError = null,
        loading = false,
    } = {}) {
        const name = String(item?.skill_name || '').trim();
        const shellRow = document.createElement('article');
        shellRow.className = 'conversation-list-entry skill-list-entry';
        shellRow.dataset.key = `global:${name}:${selected ? 'open' : 'closed'}`;
        if (selected) shellRow.classList.add('is-selected');
        const advertisers = _globalSkillAdvertisers(item);
        const row = UI.renderListRow({
            label: _globalSkillLabel(item),
            sublabel: advertisers.length
                ? `Available from ${advertisers.join(', ')}`
                : 'Declared skill; choose a bot to manage installation or drafts.',
            badgeText: item?.enabled === false ? 'Disabled' : 'Skill',
            badgeClass: item?.enabled === false ? 'badge-warning' : '',
            onClick: () => {
                _runWithDraftGuard(async () => {
                    if (selected) {
                        await _selectSkill('', 'global');
                        return;
                    }
                    await _selectSkill(name, 'global');
                });
            },
            className: selected ? 'is-selected' : '',
        });
        row.setAttribute('aria-expanded', String(selected));
        shellRow.appendChild(row);
        if (selected) {
            shellRow.appendChild(_renderGlobalSkillDetail(item, {
                detail,
                detailAgent,
                detailError,
                loading,
            }));
        }
        return shellRow;
    }

    function _renderLocalSkillRow(skill, { selected = false } = {}) {
        const shellRow = document.createElement('div');
        shellRow.className = 'list-row-shell skill-list-entry';
        shellRow.dataset.key = `local:${skill.name || ''}:${selected ? 'open' : 'closed'}`;
        const meta = RegistrySkillHub.localRowMeta(skill);
        const row = UI.renderListRow({
            label: meta.label,
            sublabel: meta.sublabel,
            badgeText: meta.badgeText,
            onClick: () => {
                _runWithDraftGuard(async () => {
                    if (selected) {
                        await _selectSkill('', 'local');
                        return;
                    }
                    await _selectSkill(skill.name || '', 'local');
                });
            },
            className: selected ? 'is-selected' : '',
        });
        row.setAttribute('aria-expanded', String(selected));
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
        if (selected) {
            shellRow.appendChild(_renderSelectedSkillInlineDetail({
                origin: 'local',
                skill,
            }));
        }
        return shellRow;
    }

    function _renderRegistrySkillRow(skill, { selected = false } = {}) {
        const shellRow = document.createElement('div');
        shellRow.className = 'list-row-shell skill-list-entry';
        shellRow.dataset.key = `store:${skill.name || ''}:${selected ? 'open' : 'closed'}`;
        const meta = RegistrySkillHub.storeRowMeta(skill);
        const row = UI.renderListRow({
            label: meta.label,
            sublabel: meta.sublabel,
            badgeText: meta.badgeText,
            onClick: () => {
                _runWithDraftGuard(async () => {
                    if (selected) {
                        await _selectSkill('', 'store');
                        return;
                    }
                    await _selectSkill(skill.name || '', 'store');
                });
            },
            className: selected ? 'is-selected' : '',
        });
        row.setAttribute('aria-expanded', String(selected));
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
        if (selected) {
            shellRow.appendChild(_renderSelectedSkillInlineDetail({
                origin: 'store',
                skill,
            }));
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
        if (!currentAgentId && selectedSkillOrigin === 'global') {
            await loadGlobalSelectionData({ soft });
            return;
        }
        const selected = _findSelectedSkill();
        if (!currentAgentId || !selected || selected.origin !== 'local') {
            selectedLocalDetail = null;
            selectedLifecycle = null;
            selectedGlobalDetail = null;
            selectedGlobalDetailAgent = null;
            selectedGlobalDetailError = null;
            globalSelectionLoading = false;
            selectionLoading = false;
            _clearDraftState();
            renderDetail();
            return;
        }
        const skillName = selected.skill.name || '';
        const hadVisibleState = detailEl.childElementCount > 0;
        const cachedDetail = UI.peekCachedData(RegistrySkillHub.detailCacheKey(currentAgentId, skillName));
        const cachedLifecycle = RegistrySkillHub.isCustomSkill(selected.skill)
            ? UI.peekCachedData(RegistrySkillHub.lifecycleCacheKey(currentAgentId, skillName))
            : null;
        const hasCachedView = Boolean(cachedDetail) || Boolean(cachedLifecycle);
        if (cachedDetail) {
            selectedLocalDetail = cachedDetail;
        }
        if (cachedLifecycle) {
            selectedLifecycle = cachedLifecycle;
        }
        selectionLoading = true;
        renderDetail();
        try {
            const detailPromise = UI.loadCachedData(
                RegistrySkillHub.detailCacheKey(currentAgentId, skillName),
                () => API.getSkillDetail(currentAgentId, skillName),
                {
                    ttlMs: SKILL_DETAIL_CACHE_TTL_MS,
                    errorTtlMs: CACHE_ERROR_TTL_MS,
                    forceRefresh: hasCachedView,
                },
            );
            const lifecyclePromise = RegistrySkillHub.isCustomSkill(selected.skill)
                ? UI.loadCachedData(
                    RegistrySkillHub.lifecycleCacheKey(currentAgentId, skillName),
                    () => API.getSkillLifecycle(currentAgentId, skillName),
                    {
                        ttlMs: SKILL_DETAIL_CACHE_TTL_MS,
                        errorTtlMs: CACHE_ERROR_TTL_MS,
                        forceRefresh: hasCachedView,
                    },
                )
                : Promise.resolve(null);
            selectedLocalDetail = await detailPromise;
            selectedLifecycle = await lifecyclePromise;
            if (_isSelectedCustom(selected.skill, selectedLocalDetail || selected.skill)) {
                _resetDraftState(selectedLocalDetail || selected.skill, selectedLifecycle);
            } else {
                _clearDraftState();
            }
            selectionLoading = false;
            renderDetail();
        } catch (err) {
            selectionLoading = false;
            if (hasCachedView || hadVisibleState) {
                UI.reportError('Failed to refresh skill details', err, { context: 'Skill detail refresh failed' });
                renderDetail();
                return;
            }
            UI.clearMemoizedRender(detailEl);
            UI.reconcileChildren(detailEl, [UI.createErrorCard('Failed to load skill details: ' + err.message, loadSelectionData)]);
        }
    }

    async function loadGlobalSelectionData({ soft = false } = {}) {
        const selectedGlobal = _findSelectedGlobalSkill();
        if (!selectedGlobal) {
            selectedGlobalDetail = null;
            selectedGlobalDetailAgent = null;
            selectedGlobalDetailError = null;
            globalSelectionLoading = false;
            renderList();
            return;
        }
        const skillName = String(selectedGlobal.skill_name || '').trim();
        const candidates = _globalSkillAgents(selectedGlobal);
        if (!skillName || !candidates.length) {
            selectedGlobalDetail = null;
            selectedGlobalDetailAgent = null;
            selectedGlobalDetailError = null;
            globalSelectionLoading = false;
            renderList();
            return;
        }
        globalSelectionLoading = true;
        selectedGlobalDetailError = null;
        renderList();
        let lastError = null;
        for (const agent of candidates) {
            try {
                const detail = await UI.loadCachedData(
                    RegistrySkillHub.detailCacheKey(agent.agent_id, skillName),
                    () => API.getSkillDetail(agent.agent_id, skillName),
                    {
                        ttlMs: SKILL_DETAIL_CACHE_TTL_MS,
                        errorTtlMs: CACHE_ERROR_TTL_MS,
                        forceRefresh: false,
                    },
                );
                if (String(selectedSkillName || '').trim().toLowerCase() !== skillName.toLowerCase()
                    || selectedSkillOrigin !== 'global'
                    || currentAgentId) {
                    return;
                }
                selectedGlobalDetail = detail || null;
                selectedGlobalDetailAgent = agent;
                globalSelectionLoading = false;
                renderList();
                return;
            } catch (err) {
                lastError = err;
            }
        }
        selectedGlobalDetail = null;
        selectedGlobalDetailAgent = null;
        selectedGlobalDetailError = lastError;
        globalSelectionLoading = false;
        if (lastError && !soft) {
            UI.reportError('Failed to load skill instructions', lastError, {
                context: 'Global skill detail load failed',
            });
        }
        renderList();
    }

    function _selectedSkillDetailSignature() {
        const selected = _findSelectedSkill();
        if (!selected) return '';
        if (selected.origin === 'store') {
            return UI.dataSignature({
                origin: 'store',
                name: String(selected.skill?.name || ''),
                version: String(selected.skill?.version || ''),
            });
        }
        const detail = selectedLocalDetail && selectedLocalDetail.name === selected.skill.name
            ? selectedLocalDetail
            : selected.skill;
        const lifecycle = selectedLifecycle && selectedLifecycle.name === selected.skill.name
            ? selectedLifecycle
            : null;
        return UI.dataSignature({
            origin: selected.origin,
            name: String(selected.skill?.name || ''),
            loading: Boolean(selectionLoading),
            detailLoaded: Boolean(selectedLocalDetail && selectedLocalDetail.name === selected.skill.name),
            detailSnapshot: _draftSnapshot(detail, lifecycle),
            studioTab: currentStudioTab,
            draftStatus,
            draftDirty,
        });
    }

    function _buildSelectedSkillDetailNodes(selected) {
        if (!currentAgentId || !selected) {
            return _buildStudioHome(_currentAgentLabel());
        }
        if (selected.origin === 'store') {
            return _buildStoreDetailNodes(selected.skill);
        }
        if (RegistrySkillHub.isCustomSkill(selected.skill)) {
            return _buildStudioDetailNodes(selected);
        }
        const detail = selectedLocalDetail && selectedLocalDetail.name === selected.skill.name
            ? selectedLocalDetail
            : selected.skill;
        const lifecycle = selectedLifecycle && selectedLifecycle.name === selected.skill.name
            ? selectedLifecycle
            : null;
        return _buildLocalDetailNodes(selected.skill, detail, lifecycle, {
            loading: selectionLoading,
            detailLoaded: Boolean(selectedLocalDetail && selectedLocalDetail.name === selected.skill.name),
        });
    }

    function _renderSelectedSkillInlineDetail(selected) {
        const panel = document.createElement('section');
        panel.className = 'conversation-inline-detail skill-inline-detail';
        panel.dataset.key = `skill-inline-detail:${selected?.origin || ''}:${selected?.skill?.name || ''}`;
        _buildSelectedSkillDetailNodes(selected).forEach((node) => {
            if (node instanceof Node) panel.appendChild(node);
        });
        return panel;
    }

    function renderDetail() {
        UI.clearMemoizedRender(detailEl);
        UI.reconcileChildren(detailEl, []);
        if (!currentAgentId) return;
        renderList();
    }

    function _renderGlobalSkillDetail(item, {
        detail = null,
        detailAgent = null,
        detailError = null,
        loading = false,
    } = {}) {
        const panel = document.createElement('section');
        panel.className = 'conversation-inline-detail skill-inline-detail';
        panel.dataset.key = `global-detail:${item?.skill_name || ''}`;
        const title = document.createElement('h3');
        title.textContent = _globalSkillLabel(item) || 'Skill';
        panel.appendChild(title);
        const advertisers = _globalSkillAdvertisers(item);
        if (detail?.description) {
            const desc = document.createElement('p');
            desc.className = 'quiet-note';
            desc.textContent = detail.description;
            panel.appendChild(desc);
        }
        panel.appendChild(UI.renderMetadataGrid([
            { label: 'Assignment slug', value: String(item?.skill_name || '') },
            { label: 'Available from', value: advertisers.length ? advertisers.join(', ') : 'No connected bot currently advertises this skill' },
            detailAgent ? {
                label: 'Instructions from',
                value: UI.visibleLabel(detailAgent.display_name, detailAgent.slug, detailAgent.agent_id) || detailAgent.agent_id,
            } : null,
            { label: 'Routing state', value: item?.enabled === false ? 'Disabled' : 'Enabled' },
        ].filter(Boolean), { compact: true }));
        const bodyText = String(detail?.body || '').trim();
        if (loading && !bodyText) {
            panel.appendChild(UI.renderEmptyState('Loading skill instructions…', true));
        } else if (bodyText) {
            const bodyLabel = document.createElement('div');
            bodyLabel.className = 'detail-label';
            bodyLabel.textContent = 'Instructions preview';
            panel.appendChild(bodyLabel);
            const preview = document.createElement('div');
            preview.className = 'task-item-summary';
            preview.innerHTML = UI.renderContent(bodyText);
            panel.appendChild(preview);
        } else if (detailError) {
            panel.appendChild(UI.renderEmptyState('Skill metadata is available, but instructions could not be loaded from an advertising bot.', true));
        } else {
            panel.appendChild(UI.renderEmptyState('Skill metadata is available. Choose a bot to inspect implementation details.', true));
        }
        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = 'Use this in a protocol stage by choosing Assignment, then Existing skill. Choose a bot above only when you need to install, draft, import, or review implementation.';
        panel.appendChild(note);
        return panel;
    }

    function renderStoreDetail(skill) {
        UI.memoizedRender(detailEl, {
            origin: 'store',
            skill,
        }, (state) => {
            return _buildStoreDetailNodes(state.skill);
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

    function _buildStoreDetailNodes(skill) {
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
        title.textContent = skill.display_name || skill.name || 'Skill';
        titleWrap.appendChild(title);
        if (skill.description) {
            const description = document.createElement('p');
            description.className = 'quiet-note';
            description.textContent = skill.description;
            titleWrap.appendChild(description);
        }
        headerRow.appendChild(titleWrap);
        const badge = document.createElement('span');
        badge.className = 'badge';
        badge.textContent = skill.source_label || 'Store';
        headerRow.appendChild(badge);
        overview.appendChild(headerRow);
        overview.appendChild(UI.renderMetadataGrid([
            { label: 'State', value: 'Available from the skill store' },
            { label: 'Publisher', value: skill.publisher || 'Unknown' },
            { label: 'Version', value: skill.version || 'Unknown' },
        ], { compact: true }));
        const actions = document.createElement('div');
        actions.className = 'editor-actions';
        if (skill.can_import) {
            actions.appendChild(_actionButton('Install on bot', async () => {
                await API.installSkill(currentAgentId, skill.name);
                _invalidateSkillCaches(currentAgentId, skill.name);
                selectedSkillOrigin = 'local';
                selectedSkillName = skill.name;
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
            'Install this skill on the bot first. Then open a conversation and use the conversation Skills panel to activate it in that chat.',
            '</p>',
        ].join('');
        nodes.push(help);
        return nodes;
    }

    function renderStudioDetail(selected) {
        const summary = selected && selected.origin === 'local' ? selected.skill : {};
        const detail = selectedLocalDetail && selected && selectedLocalDetail.name === selected.skill.name
            ? selectedLocalDetail
            : summary;
        const lifecycle = selectedLifecycle && selected && selectedLifecycle.name === selected.skill.name
            ? selectedLifecycle
            : null;
        const lifecycleState = RegistrySkillHub.lifecycleState(lifecycle || detail);
        UI.memoizedRender(detailEl, {
            agentId: currentAgentId,
            agentLabel: _currentAgentLabel(),
            selectedOrigin: selected?.origin || '',
            skillName: selected?.skill?.name || '',
            loading: selectionLoading,
            detailLoaded: Boolean(selectedLocalDetail && selected && selectedLocalDetail.name === selected.skill.name),
            detailSnapshot: _draftSnapshot(detail, lifecycle),
            skillKind: String(lifecycle?.skill_kind || detail?.skill_kind || ''),
            lifecycleStatus: String(lifecycleState.rawStatus || ''),
            lifecycleEffectiveStatus: String(lifecycleState.effectiveStatus || ''),
            lifecycleAction: String(lifecycleState.latestAction || ''),
            revisionId: String(lifecycle?.active_revision_id || ''),
            draftStatus,
            draftDirty,
            studioTab: currentStudioTab,
        }, (state) => {
            return _buildStudioDetailNodes(selected);
        });
    }

    function _buildStudioDetailNodes(selected) {
        const summary = selected && selected.origin === 'local' ? selected.skill : {};
        const detail = selectedLocalDetail && selected && selectedLocalDetail.name === selected.skill.name
            ? selectedLocalDetail
            : summary;
        const lifecycle = selectedLifecycle && selected && selectedLifecycle.name === selected.skill.name
            ? selectedLifecycle
            : null;
        if (!selected?.skill?.name) {
            return _buildStudioHome(_currentAgentLabel());
        }
        if (selected.origin === 'store' || !_isSelectedCustom(summary, detail)) {
            return _buildStudioHome(_currentAgentLabel(), selected);
        }
        if (selectionLoading && !selectedLocalDetail) {
            return _buildStudioLoading(detail);
        }
        return _buildStudioWorkspace(summary, detail, lifecycle, { loading: Boolean(selectionLoading) });
    }

    function renderLocalDetail(summary, detail, lifecycle, { loading = false, detailLoaded = false } = {}) {
        UI.memoizedRender(detailEl, {
            agentId: currentAgentId,
            agentLabel: _currentAgentLabel(),
            summary,
            detail,
            lifecycle,
            loading,
            detailLoaded,
            detailSnapshot: _draftSnapshot(detail, lifecycle),
        }, (state) => {
            return _buildLocalDetailNodes(state.summary, state.detail, state.lifecycle, {
                loading: state.loading,
                detailLoaded: state.detailLoaded,
                agentLabel: state.agentLabel,
            });
        }, {
            signatureFn(state) {
                return {
                    agentId: String(state.agentId || ''),
                    agentLabel: String(state.agentLabel || ''),
                    name: String((state.summary && state.summary.name) || ''),
                    lifecycle: String((state.detail && state.detail.lifecycle_status) || ''),
                    lifecycleAction: String((state.lifecycle && state.lifecycle.approvals && state.lifecycle.approvals[0] && state.lifecycle.approvals[0].action) || ''),
                    runtimeAvailable: Boolean(state.detail && state.detail.runtime_available),
                    source: String((state.detail && state.detail.source_kind) || ''),
                    activeRevisionId: String((state.lifecycle && state.lifecycle.active_revision_id) || ''),
                    loading: Boolean(state.loading),
                    detailLoaded: Boolean(state.detailLoaded),
                    detailSnapshot: String(state.detailSnapshot || ''),
                };
            },
        });
    }

    function _buildLocalDetailNodes(summary, detail, lifecycle, { loading = false, detailLoaded = false, agentLabel = '' } = {}) {
        if (loading && !detailLoaded) {
            return _buildLoadingPanel(detail, {
                keyPrefix: 'skill-loading',
                message: 'Loading skill details…',
            });
        }
        return [
            _buildOverviewPanel(summary, detail, lifecycle),
            _buildCatalogHelpPanel(summary, detail, agentLabel || _currentAgentLabel()),
        ];
    }

    function _buildOverviewPanel(summary, detail, lifecycle) {
        const panel = document.createElement('section');
        panel.className = 'editor-panel';
        panel.dataset.key = `skill-overview:${summary.name || detail.name || ''}`;

        const packageState = lifecycle || detail;
        const lifecycleState = RegistrySkillHub.lifecycleState(packageState);
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
                value: lifecycleState.label,
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
                    await RegistrySkillHub.openConversationForSkill(
                        currentAgentId,
                        detail.name || summary.name || '',
                        { agentLabel: label },
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

    function _buildLoadingPanel(detail, { keyPrefix = 'skill-loading', message = 'Loading…' } = {}) {
        const panel = document.createElement('section');
        panel.className = 'editor-panel';
        panel.dataset.key = `${keyPrefix}:${detail?.name || ''}`;
        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = detail?.display_name || detail?.name || 'Skill';
        panel.appendChild(title);
        panel.appendChild(UI.renderEmptyState(message, true));
        return [panel];
    }

    function _buildStudioLoading(detail) {
        return _buildLoadingPanel(detail, {
            keyPrefix: 'studio-loading',
            message: 'Loading draft…',
        });
    }

    function _buildStudioHome(agentLabel, selected) {
        const intro = document.createElement('section');
        intro.className = 'editor-panel';
        intro.dataset.key = 'studio-home';
        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = 'Skills';
        intro.appendChild(title);
        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = selected && selected.origin === 'store'
            ? `Install this skill on ${agentLabel}, or pick a custom skill to edit it here.`
            : `Select a skill for ${agentLabel}, create a new custom skill, or import a package to start editing.`;
        intro.appendChild(note);
        const actions = document.createElement('div');
        actions.className = 'editor-actions';
        const createBtn = document.createElement('button');
        createBtn.type = 'button';
        createBtn.className = 'btn btn-primary';
        createBtn.textContent = 'New skill';
        createBtn.hidden = !RegistrySkillHub.canCreateCustom(_currentAgent());
        createBtn.addEventListener('click', () => _beginStudioDialog(_openCreateDraftDialog));
        actions.appendChild(createBtn);
        const importBtn = document.createElement('button');
        importBtn.type = 'button';
        importBtn.className = 'btn';
        importBtn.textContent = 'Import';
        importBtn.hidden = !RegistrySkillHub.canCreateCustom(_currentAgent());
        importBtn.addEventListener('click', () => _beginStudioDialog(_openImportDialog));
        actions.appendChild(importBtn);
        intro.appendChild(actions);
        return [intro];
    }

    function _openCreateDraftDialog() {
        const form = document.createElement('div');
        form.className = 'studio-dialog-form';
        const slugId = `skill-draft-slug-${Date.now()}`;
        const descriptionId = `skill-draft-description-${Date.now()}`;

        const nameLabel = document.createElement('label');
        nameLabel.className = 'detail-label';
        nameLabel.htmlFor = slugId;
        nameLabel.textContent = 'Skill slug';
        form.appendChild(nameLabel);
        const nameInput = document.createElement('input');
        nameInput.id = slugId;
        nameInput.className = 'input';
        nameInput.placeholder = 'skill-slug';
        nameInput.autocomplete = 'off';
        form.appendChild(nameInput);

        const descriptionLabel = document.createElement('label');
        descriptionLabel.className = 'detail-label';
        descriptionLabel.htmlFor = descriptionId;
        descriptionLabel.textContent = 'Short description';
        form.appendChild(descriptionLabel);
        const descriptionInput = document.createElement('input');
        descriptionInput.id = descriptionId;
        descriptionInput.className = 'input';
        descriptionInput.placeholder = 'Short description';
        descriptionInput.autocomplete = 'off';
        form.appendChild(descriptionInput);
        const createBtn = document.createElement('button');
        createBtn.type = 'button';
        createBtn.className = 'btn btn-primary';
        createBtn.textContent = 'Create draft';
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn';
        cancelBtn.textContent = 'Cancel';
        const view = UI.showDialog('Create custom draft', form, {
            actions: [cancelBtn, createBtn],
            maxWidth: '520px',
            initialFocus: nameInput,
        });
        cancelBtn.addEventListener('click', () => view.close());
        createBtn.addEventListener('click', async () => {
            const skillName = String(nameInput.value || '').trim();
            if (!skillName) {
                nameInput.focus();
                return;
            }
            createBtn.disabled = true;
            try {
                const result = await API.saveSkillDraft(currentAgentId, skillName, {
                    body: 'Add your instructions here.',
                    display_name: skillName.replace(/-/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()),
                    description: String(descriptionInput.value || '').trim(),
                    changelog: 'Initial draft',
                });
                selectedLocalDetail = result?.detail || {
                    name: skillName,
                    display_name: skillName.replace(/-/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()),
                    description: String(descriptionInput.value || '').trim(),
                    lifecycle_status: 'draft',
                    skill_kind: 'custom',
                    runtime_available: false,
                };
                allSkills = _mergeSkillDetailIntoRecords(allSkills, selectedLocalDetail);
                _invalidateSkillCaches(currentAgentId, skillName);
                view.close();
                await _selectSkill(skillName, 'local');
                void loadSkills({ soft: true, forceCatalog: true });
            } catch (err) {
                UI.reportError('Failed to create the custom draft', err, { context: 'Custom skill draft create failed' });
            }
            createBtn.disabled = false;
        });
    }

    async function _readFileText(file) {
        return file.text();
    }

    function _downloadPackageArtifact(artifact) {
        const blob = new Blob([String(artifact.document_text || '')], { type: artifact.content_type || 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = artifact.file_name || `${UI.safeFilename(artifact.name || 'skill')}.skill.${artifact.format || 'json'}`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 500);
    }

    function _openImportDialog() {
        const form = document.createElement('div');
        form.className = 'studio-dialog-form';
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.className = 'input';
        fileInput.accept = '.json,.yaml,.yml,application/json,application/x-yaml,text/yaml';
        form.appendChild(fileInput);
        const targetInput = document.createElement('input');
        targetInput.className = 'input';
        targetInput.placeholder = 'Replace existing draft (optional)';
        targetInput.value = _isSelectedCustom(_findSelectedSkill()?.skill, selectedLocalDetail) ? (selectedSkillName || '') : '';
        form.appendChild(targetInput);
        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = 'Leave the target blank to import using the package skill name. Set a target to replace or create a specific custom draft.';
        form.appendChild(note);
        const importBtn = document.createElement('button');
        importBtn.type = 'button';
        importBtn.className = 'btn btn-primary';
        importBtn.textContent = 'Import package';
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn';
        cancelBtn.textContent = 'Cancel';
        const view = UI.showDialog('Import skill package', form, {
            actions: [cancelBtn, importBtn],
            maxWidth: '560px',
        });
        cancelBtn.addEventListener('click', () => view.close());
        importBtn.addEventListener('click', async () => {
            const file = fileInput.files && fileInput.files[0];
            if (!file) {
                fileInput.focus();
                return;
            }
            importBtn.disabled = true;
            try {
                const documentText = await _readFileText(file);
                const fileName = String(file.name || '');
                const format = /\.ya?ml$/i.test(fileName) ? 'yaml' : 'json';
                const result = await API.importSkillPackage(currentAgentId, {
                    file_name: file.name,
                    target_skill_name: String(targetInput.value || '').trim(),
                    format,
                    document_text: documentText,
                });
                const nextSkillName = result.detail?.name || String(targetInput.value || '').trim() || selectedSkillName || '';
                _invalidateSkillCaches(currentAgentId, nextSkillName);
                view.close();
                await loadSkills({ soft: true, forceCatalog: true });
                if (nextSkillName) {
                    await _selectSkill(nextSkillName, 'local');
                }
            } catch (err) {
                UI.reportError('Failed to import the skill package', err, { context: 'Skill package import failed' });
            }
            importBtn.disabled = false;
        });
    }

    function _buildStudioWorkspace(summary, detail, lifecycle, { loading = false } = {}) {
        const packageState = _packageState(detail, lifecycle);
        const nextDraftSnapshot = _draftSnapshot(detail, lifecycle);
        if (!draftBuffer || draftBuffer.name !== detail.name || (!draftDirty && draftSnapshotKey !== nextDraftSnapshot)) {
            _resetDraftState(detail, lifecycle);
        }
        const lifecycleState = RegistrySkillHub.lifecycleState(packageState);
        const lifecycleStatus = lifecycleState.rawStatus;
        const lifecycleLabel = lifecycleState.label;
        const validationProblems = Array.isArray(packageState.validation_problems) ? packageState.validation_problems : [];
        const nodes = [];

        const header = document.createElement('section');
        header.className = 'editor-panel';
        header.dataset.key = `studio-header:${detail.name || ''}`;
        const headerRow = document.createElement('div');
        headerRow.className = 'workspace-header-main';
        const titleWrap = document.createElement('div');
        titleWrap.className = 'workspace-title-group';
        const title = document.createElement('h3');
        title.className = 'editor-section-title';
        title.textContent = detail.display_name || detail.name || 'Custom skill';
        titleWrap.appendChild(title);
        const subtitle = document.createElement('p');
        subtitle.className = 'quiet-note';
        subtitle.textContent = loading
            ? 'Refreshing draft…'
            : (packageState.publish_ready
                ? 'Ready for the next lifecycle step.'
                : 'Finish the draft and use Review before publishing.');
        titleWrap.appendChild(subtitle);
        headerRow.appendChild(titleWrap);
        const badge = document.createElement('span');
        badge.className = `badge badge-${lifecycleState.effectiveStatus || lifecycleStatus}`;
        badge.textContent = lifecycleLabel;
        headerRow.appendChild(badge);
        header.appendChild(headerRow);
        header.appendChild(UI.renderMetadataGrid([
            { label: 'Save state', value: draftStatusMessage || (draftDirty ? 'Unsaved changes' : 'All changes saved') },
            { label: 'Publish readiness', value: packageState.publish_ready ? 'Ready' : 'Needs review' },
            { label: 'Validation', value: validationProblems.length ? `${validationProblems.length} issue${validationProblems.length === 1 ? '' : 's'}` : 'No open issues' },
        ], { compact: true }));

        const actions = document.createElement('div');
        actions.className = 'editor-actions';
        const refreshChrome = () => {
            saveBtn.disabled = loading || draftStatus === 'saving';
            saveBtn.textContent = draftStatus === 'saving' ? 'Saving…' : 'Save draft';
            submitBtn.hidden = currentStudioTab !== 'review' || !lifecycleState.canSubmit;
            submitBtn.disabled = loading || draftStatus === 'saving' || !packageState.publish_ready;
            approveBtn.hidden = currentStudioTab !== 'review' || !lifecycleState.canApprove;
            approveBtn.disabled = loading || draftStatus === 'saving';
            rejectBtn.hidden = currentStudioTab !== 'review' || !lifecycleState.canApprove;
            rejectBtn.disabled = loading || draftStatus === 'saving';
            publishBtn.hidden = currentStudioTab !== 'review' || !lifecycleState.canPublish || lifecycleState.isPublished;
            publishBtn.disabled = loading || draftStatus === 'saving';
            archiveBtn.hidden = currentStudioTab !== 'review' || lifecycleState.isArchived;
            archiveBtn.disabled = loading || draftStatus === 'saving';
        };
        const saveBtn = document.createElement('button');
        saveBtn.type = 'button';
        saveBtn.className = 'btn btn-primary';
        saveBtn.textContent = 'Save draft';
        const submitBtn = document.createElement('button');
        submitBtn.type = 'button';
        submitBtn.className = 'btn btn-primary';
        submitBtn.textContent = 'Submit';
        const approveBtn = document.createElement('button');
        approveBtn.type = 'button';
        approveBtn.className = 'btn btn-primary';
        approveBtn.textContent = 'Approve';
        const rejectBtn = document.createElement('button');
        rejectBtn.type = 'button';
        rejectBtn.className = 'btn';
        rejectBtn.textContent = 'Reject';
        const publishBtn = document.createElement('button');
        publishBtn.type = 'button';
        publishBtn.className = 'btn btn-primary';
        publishBtn.textContent = 'Publish';
        const archiveBtn = document.createElement('button');
        archiveBtn.type = 'button';
        archiveBtn.className = 'btn btn-danger';
        archiveBtn.textContent = 'Archive';
        actions.appendChild(saveBtn);
        header.appendChild(actions);
        const workspaceTabs = UI.createSegmentedControl(
            [
                { key: 'write', value: 'write', label: 'Write' },
                { key: 'setup', value: 'setup', label: 'Setup' },
                { key: 'review', value: 'review', label: 'Review' },
                { key: 'advanced', value: 'advanced', label: 'Advanced' },
            ],
            (nextTab) => {
                currentStudioTab = nextTab;
                _writeState();
                renderDetail();
            },
            {
                label: 'Skill workspace',
                value: currentStudioTab,
            },
        );
        const tabRow = document.createElement('div');
        tabRow.className = 'route-controls';
        tabRow.appendChild(workspaceTabs.element);
        header.appendChild(tabRow);
        nodes.push(header);

        const markDirty = () => {
            draftDirty = true;
            draftStatus = 'dirty';
            draftStatusMessage = 'Unsaved changes';
            refreshChrome();
        };

        const persistDraft = async ({ quiet = false } = {}) => {
            draftStatus = 'saving';
            draftStatusMessage = 'Saving draft…';
            refreshChrome();
            try {
                await API.saveSkillDraft(currentAgentId, detail.name, {
                    body: draftBuffer.body,
                    display_name: draftBuffer.display_name,
                    description: draftBuffer.description,
                    skill_kind: draftBuffer.skill_kind,
                    requirements: draftBuffer.requirements,
                    provider_config: draftBuffer.provider_config,
                    files: draftBuffer.files,
                    changelog: draftBuffer.changelog,
                });
                _invalidateSkillCaches(currentAgentId, detail.name);
                await loadSkills({ soft: true, forceCatalog: true });
                await loadSelectionData({ soft: true });
                return true;
            } catch (err) {
                draftStatus = 'error';
                draftStatusMessage = 'Save failed';
                refreshChrome();
                if (!quiet) {
                    UI.reportError('Failed to save the draft', err, { context: 'Skill draft save failed' });
                } else {
                    UI.reportError('Failed to save the draft before continuing', err, { context: 'Skill draft pre-save failed' });
                }
                return false;
            }
        };

        const lifecycleAction = async (op, successLabel) => {
            if (draftDirty) {
                const saved = await persistDraft({ quiet: true });
                if (!saved) {
                    return;
                }
            }
            draftStatus = 'saving';
            draftStatusMessage = successLabel;
            refreshChrome();
            try {
                const result = await op();
                _invalidateSkillCaches(currentAgentId, detail.name);
                const appliedMutationDetail = _applyStudioMutationDetail(result?.detail || null);
                if (!appliedMutationDetail) {
                    await loadSkills({ soft: true, forceCatalog: true });
                    await loadSelectionData({ soft: true });
                }
            } catch (err) {
                draftStatus = 'error';
                draftStatusMessage = 'Action failed';
                refreshChrome();
                if (successLabel === 'Publishing') {
                    try {
                        await loadSelectionData({ soft: true });
                        const recoveredState = RegistrySkillHub.lifecycleState(selectedLifecycle || selectedLocalDetail || detail);
                        if (recoveredState.isPublished || Boolean((selectedLifecycle || selectedLocalDetail || detail)?.runtime_available)) {
                            draftStatus = 'idle';
                            draftStatusMessage = 'Published';
                            refreshChrome();
                            return;
                        }
                    } catch {
                        // Fall through to the normal error path when the recovery refresh also fails.
                    }
                }
                if (!_isActiveSkillsWorkspace()) {
                    return;
                }
                UI.reportError(`Failed to ${successLabel.toLowerCase()}`, err, { context: `Skill studio ${successLabel.toLowerCase()} failed` });
            }
        };

        saveBtn.addEventListener('click', async () => {
            await persistDraft();
        });
        submitBtn.addEventListener('click', async () => lifecycleAction(
            () => API.submitSkillDraft(currentAgentId, detail.name, {}),
            'Submitting',
        ));
        approveBtn.addEventListener('click', async () => lifecycleAction(
            () => API.approveSkillDraft(currentAgentId, detail.name, {}),
            'Approving',
        ));
        rejectBtn.addEventListener('click', async () => lifecycleAction(
            () => API.rejectSkillDraft(currentAgentId, detail.name, {}),
            'Rejecting',
        ));
        publishBtn.addEventListener('click', async () => lifecycleAction(
            () => API.publishSkillDraft(currentAgentId, detail.name, {}),
            'Publishing',
        ));
        archiveBtn.addEventListener('click', async () => lifecycleAction(
            () => API.archiveSkillDraft(currentAgentId, detail.name, {}),
            'Archiving',
        ));

        const renderRequirementsEditor = (container) => {
            const list = document.createElement('div');
            list.className = 'studio-stack';
            container.appendChild(list);
            const renderRows = () => {
                list.replaceChildren(...draftBuffer.requirements.map((item, index) => {
                    const card = document.createElement('section');
                    card.className = 'editor-panel';
                    const keyInput = document.createElement('input');
                    keyInput.className = 'input';
                    keyInput.placeholder = 'Credential key';
                    keyInput.value = item.key || '';
                    keyInput.addEventListener('input', () => {
                        draftBuffer.requirements[index].key = keyInput.value;
                        markDirty();
                    });
                    card.appendChild(keyInput);
                    const promptInput = document.createElement('input');
                    promptInput.className = 'input';
                    promptInput.placeholder = 'Prompt shown during setup';
                    promptInput.value = item.prompt || '';
                    promptInput.addEventListener('input', () => {
                        draftBuffer.requirements[index].prompt = promptInput.value;
                        markDirty();
                    });
                    card.appendChild(promptInput);
                    const helpInput = document.createElement('input');
                    helpInput.className = 'input';
                    helpInput.placeholder = 'Help URL (optional)';
                    helpInput.value = item.help_url || '';
                    helpInput.addEventListener('input', () => {
                        draftBuffer.requirements[index].help_url = helpInput.value;
                        markDirty();
                    });
                    card.appendChild(helpInput);
                    const validationInput = document.createElement('textarea');
                    validationInput.className = 'guidance-textarea';
                    validationInput.rows = 4;
                    validationInput.placeholder = 'Validation JSON (optional)';
                    validationInput.value = item.validate ? JSON.stringify(item.validate, null, 2) : '';
                    validationInput.addEventListener('change', () => {
                        const text = String(validationInput.value || '').trim();
                        if (!text) {
                            draftBuffer.requirements[index].validate = null;
                            markDirty();
                            return;
                        }
                        try {
                            draftBuffer.requirements[index].validate = JSON.parse(text);
                            markDirty();
                        } catch (err) {
                            UI.reportError('Requirement validation JSON must be valid', err, { context: 'Skill requirement validation JSON failed' });
                        }
                    });
                    card.appendChild(validationInput);
                    const actionsRow = document.createElement('div');
                    actionsRow.className = 'editor-actions';
                    const removeBtn = document.createElement('button');
                    removeBtn.type = 'button';
                    removeBtn.className = 'btn btn-danger btn-sm';
                    removeBtn.textContent = 'Remove requirement';
                    removeBtn.addEventListener('click', () => {
                        draftBuffer.requirements.splice(index, 1);
                        markDirty();
                        renderRows();
                    });
                    actionsRow.appendChild(removeBtn);
                    card.appendChild(actionsRow);
                    return card;
                }));
            };
            renderRows();
            const addBtn = document.createElement('button');
            addBtn.type = 'button';
            addBtn.className = 'btn btn-sm';
            addBtn.textContent = 'Add requirement';
            addBtn.addEventListener('click', () => {
                draftBuffer.requirements.push({ key: '', prompt: '', help_url: '', validate: null });
                markDirty();
                renderRows();
            });
            container.appendChild(addBtn);
        };

        const renderProviderEditor = (container) => {
            const list = document.createElement('div');
            list.className = 'studio-stack';
            container.appendChild(list);
            const renderProviders = () => {
                list.replaceChildren(...Object.keys(draftBuffer.provider_config || {}).sort().map((providerName) => {
                    const card = document.createElement('section');
                    card.className = 'editor-panel';
                    const titleEl = document.createElement('div');
                    titleEl.className = 'editor-section-title';
                    titleEl.textContent = providerName;
                    card.appendChild(titleEl);
                    const textarea = document.createElement('textarea');
                    textarea.className = 'guidance-textarea';
                    textarea.rows = 8;
                    textarea.value = JSON.stringify(draftBuffer.provider_config[providerName] || {}, null, 2);
                    textarea.addEventListener('change', () => {
                        const text = String(textarea.value || '').trim();
                        if (!text) {
                            delete draftBuffer.provider_config[providerName];
                            markDirty();
                            renderProviders();
                            return;
                        }
                        try {
                            const parsed = JSON.parse(text);
                            if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
                                throw new Error('Provider config must be an object.');
                            }
                            draftBuffer.provider_config[providerName] = parsed;
                            markDirty();
                        } catch (err) {
                            UI.reportError(`Provider config for '${providerName}' must be valid JSON`, err, { context: 'Skill provider config JSON failed' });
                        }
                    });
                    card.appendChild(textarea);
                    const actionsRow = document.createElement('div');
                    actionsRow.className = 'editor-actions';
                    const removeBtn = document.createElement('button');
                    removeBtn.type = 'button';
                    removeBtn.className = 'btn btn-danger btn-sm';
                    removeBtn.textContent = 'Remove provider config';
                    removeBtn.addEventListener('click', () => {
                        delete draftBuffer.provider_config[providerName];
                        markDirty();
                        renderProviders();
                    });
                    actionsRow.appendChild(removeBtn);
                    card.appendChild(actionsRow);
                    return card;
                }));
            };
            renderProviders();
            const controls = document.createElement('div');
            controls.className = 'route-controls';
            const input = document.createElement('input');
            input.className = 'input';
            input.placeholder = 'Provider name';
            controls.appendChild(input);
            const addBtn = document.createElement('button');
            addBtn.type = 'button';
            addBtn.className = 'btn btn-sm';
            addBtn.textContent = 'Add provider config';
            addBtn.addEventListener('click', () => {
                const normalized = String(input.value || '').trim();
                if (!normalized) return;
                if (!draftBuffer.provider_config[normalized]) {
                    draftBuffer.provider_config[normalized] = {};
                    markDirty();
                    renderProviders();
                }
                input.value = '';
            });
            controls.appendChild(addBtn);
            container.appendChild(controls);
        };

        const renderFilesEditor = (container) => {
            const list = document.createElement('div');
            list.className = 'studio-stack';
            container.appendChild(list);
            const renderFiles = () => {
                list.replaceChildren(...draftBuffer.files.map((item, index) => {
                    const card = document.createElement('section');
                    card.className = 'editor-panel';
                    const pathInput = document.createElement('input');
                    pathInput.className = 'input';
                    pathInput.placeholder = 'relative/path.ext';
                    pathInput.value = item.relative_path || '';
                    pathInput.addEventListener('input', () => {
                        draftBuffer.files[index].relative_path = pathInput.value;
                        markDirty();
                    });
                    card.appendChild(pathInput);
                    const typeInput = document.createElement('input');
                    typeInput.className = 'input';
                    typeInput.placeholder = 'Content type';
                    typeInput.value = item.content_type || '';
                    typeInput.addEventListener('input', () => {
                        draftBuffer.files[index].content_type = typeInput.value;
                        markDirty();
                    });
                    card.appendChild(typeInput);
                    const execLabel = document.createElement('label');
                    execLabel.className = 'quiet-note';
                    const execInput = document.createElement('input');
                    execInput.type = 'checkbox';
                    execInput.checked = Boolean(item.executable);
                    execInput.addEventListener('change', () => {
                        draftBuffer.files[index].executable = Boolean(execInput.checked);
                        markDirty();
                    });
                    execLabel.appendChild(execInput);
                    execLabel.appendChild(document.createTextNode(' Executable'));
                    card.appendChild(execLabel);
                    const contentInput = document.createElement('textarea');
                    contentInput.className = 'guidance-textarea';
                    contentInput.rows = 10;
                    contentInput.placeholder = 'File contents';
                    contentInput.value = item.content_text || '';
                    contentInput.addEventListener('input', () => {
                        draftBuffer.files[index].content_text = contentInput.value;
                        markDirty();
                    });
                    card.appendChild(contentInput);
                    const actionsRow = document.createElement('div');
                    actionsRow.className = 'editor-actions';
                    const removeBtn = document.createElement('button');
                    removeBtn.type = 'button';
                    removeBtn.className = 'btn btn-danger btn-sm';
                    removeBtn.textContent = 'Remove file';
                    removeBtn.addEventListener('click', () => {
                        draftBuffer.files.splice(index, 1);
                        markDirty();
                        renderFiles();
                    });
                    actionsRow.appendChild(removeBtn);
                    card.appendChild(actionsRow);
                    return card;
                }));
            };
            renderFiles();
            const addBtn = document.createElement('button');
            addBtn.type = 'button';
            addBtn.className = 'btn btn-sm';
            addBtn.textContent = 'Add file';
            addBtn.addEventListener('click', () => {
                draftBuffer.files.push({ relative_path: '', content_text: '', content_type: '', executable: false });
                markDirty();
                renderFiles();
            });
            container.appendChild(addBtn);
        };

        const basicsPanel = document.createElement('section');
        basicsPanel.className = 'editor-panel';
        basicsPanel.dataset.key = `studio-basics:${detail.name || ''}`;
        const basicsTitle = document.createElement('div');
        basicsTitle.className = 'editor-section-title';
        basicsTitle.textContent = 'Write';
        basicsPanel.appendChild(basicsTitle);
        const basicsNote = document.createElement('p');
        basicsNote.className = 'quiet-note';
        basicsNote.textContent = 'Set the title and short description people will see, then write the instructions this skill should follow at runtime.';
        basicsPanel.appendChild(basicsNote);
        const displayNameInput = document.createElement('input');
        displayNameInput.className = 'input';
        displayNameInput.placeholder = 'Display name';
        displayNameInput.value = draftBuffer.display_name || '';
        displayNameInput.addEventListener('input', () => {
            draftBuffer.display_name = displayNameInput.value;
            markDirty();
        });
        basicsPanel.appendChild(displayNameInput);
        const descriptionInput = document.createElement('input');
        descriptionInput.className = 'input';
        descriptionInput.placeholder = 'Short description';
        descriptionInput.value = draftBuffer.description || '';
        descriptionInput.addEventListener('input', () => {
            draftBuffer.description = descriptionInput.value;
            markDirty();
        });
        basicsPanel.appendChild(descriptionInput);

        const instructionsPanel = document.createElement('section');
        instructionsPanel.className = 'editor-panel';
        instructionsPanel.dataset.key = `studio-instructions:${detail.name || ''}`;
        const instructionsTitle = document.createElement('div');
        instructionsTitle.className = 'editor-section-title';
        instructionsTitle.textContent = 'Instructions';
        instructionsPanel.appendChild(instructionsTitle);
        const instructionsNote = document.createElement('p');
        instructionsNote.className = 'quiet-note';
        instructionsNote.textContent = 'Write the runtime instructions this skill should follow.';
        instructionsPanel.appendChild(instructionsNote);
        const bodyInput = document.createElement('textarea');
        bodyInput.className = 'guidance-textarea';
        bodyInput.rows = 20;
        bodyInput.value = draftBuffer.body || '';
        bodyInput.placeholder = 'Draft instructions';
        bodyInput.addEventListener('input', () => {
            draftBuffer.body = bodyInput.value;
            markDirty();
        });
        instructionsPanel.appendChild(bodyInput);

        const requirementsPanel = document.createElement('section');
        requirementsPanel.className = 'editor-panel';
        requirementsPanel.dataset.key = `studio-requirements:${detail.name || ''}`;
        const requirementsTitle = document.createElement('div');
        requirementsTitle.className = 'editor-section-title';
        requirementsTitle.textContent = 'Setup requirements';
        requirementsPanel.appendChild(requirementsTitle);
        const requirementsNote = document.createElement('p');
        requirementsNote.className = 'quiet-note';
        requirementsNote.textContent = 'Add only the credentials or setup prompts people must satisfy before this skill can run.';
        requirementsPanel.appendChild(requirementsNote);
        renderRequirementsEditor(requirementsPanel);

        const providersPanel = document.createElement('section');
        providersPanel.className = 'editor-panel';
        providersPanel.dataset.key = `studio-providers:${detail.name || ''}`;
        const providersTitle = document.createElement('div');
        providersTitle.className = 'editor-section-title';
        providersTitle.textContent = 'Provider config';
        providersPanel.appendChild(providersTitle);
        const providersNote = document.createElement('p');
        providersNote.className = 'quiet-note';
        providersNote.textContent = 'Advanced provider-specific overrides. Leave this empty unless the skill truly needs provider-specific behavior.';
        providersPanel.appendChild(providersNote);
        renderProviderEditor(providersPanel);

        const filesPanel = document.createElement('section');
        filesPanel.className = 'editor-panel';
        filesPanel.dataset.key = `studio-files:${detail.name || ''}`;
        const filesTitle = document.createElement('div');
        filesTitle.className = 'editor-section-title';
        filesTitle.textContent = 'Attached files';
        filesPanel.appendChild(filesTitle);
        const filesNote = document.createElement('p');
        filesNote.className = 'quiet-note';
        filesNote.textContent = 'Attach extra runtime files only when the skill depends on them. Most skills should not need this section.';
        filesPanel.appendChild(filesNote);
        renderFilesEditor(filesPanel);

        const reviewPanel = document.createElement('section');
        reviewPanel.className = 'editor-panel';
        reviewPanel.dataset.key = `studio-review:${detail.name || ''}`;
        const reviewTitle = document.createElement('div');
        reviewTitle.className = 'editor-section-title';
        reviewTitle.textContent = 'Review';
        reviewPanel.appendChild(reviewTitle);
        reviewPanel.appendChild(UI.renderMetadataGrid([
            { label: 'Lifecycle', value: lifecycleLabel },
            { label: 'Runtime available', value: packageState.runtime_available ? 'Yes' : 'No' },
            { label: 'Publish ready', value: packageState.publish_ready ? 'Yes' : 'No' },
            { label: 'Requirements', value: String((draftBuffer.requirements || []).length) },
        ], { compact: true }));
        const changelogInput = document.createElement('input');
        changelogInput.className = 'input';
        changelogInput.placeholder = 'Release note (optional)';
        changelogInput.value = draftBuffer.changelog || '';
        changelogInput.addEventListener('input', () => {
            draftBuffer.changelog = changelogInput.value;
            markDirty();
        });
        reviewPanel.appendChild(changelogInput);
        const previewLabel = document.createElement('div');
        previewLabel.className = 'detail-label';
        previewLabel.textContent = 'Instructions preview';
        reviewPanel.appendChild(previewLabel);
        const preview = document.createElement('div');
        preview.className = 'task-item-summary';
        preview.innerHTML = UI.renderContent(draftBuffer.body || '');
        reviewPanel.appendChild(preview);
        if (validationProblems.length) {
            const validationLabel = document.createElement('div');
            validationLabel.className = 'detail-label';
            validationLabel.textContent = 'Validation problems';
            reviewPanel.appendChild(validationLabel);
            const problems = document.createElement('ul');
            problems.className = 'change-list';
            validationProblems.forEach((problem) => {
                const item = document.createElement('li');
                item.innerHTML = [
                    `<strong>${UI.esc(problem.field_path || problem.code || 'problem')}</strong>`,
                    `<div>${UI.esc(problem.message || '')}</div>`,
                ].join('');
                problems.appendChild(item);
            });
            reviewPanel.appendChild(problems);
        } else {
            reviewPanel.appendChild(UI.renderEmptyState('No validation problems. This draft is ready for the next lifecycle step.', true));
        }
        if ((lifecycle?.approvals || []).length) {
            const activityLabel = document.createElement('div');
            activityLabel.className = 'detail-label';
            activityLabel.textContent = 'Recent review activity';
            reviewPanel.appendChild(activityLabel);
            const approvals = document.createElement('ul');
            approvals.className = 'change-list';
            lifecycle.approvals.slice(0, 5).forEach((item) => {
                const li = document.createElement('li');
                li.innerHTML = [
                    `<strong>${UI.esc(item.action || 'update')}</strong>`,
                    `<div class="quiet-note">${UI.esc(item.actor || 'unknown')}</div>`,
                    item.note ? `<div>${UI.esc(item.note)}</div>` : '',
                ].join('');
                approvals.appendChild(li);
            });
            reviewPanel.appendChild(approvals);
        }
        const nextStepLabel = document.createElement('div');
        nextStepLabel.className = 'detail-label';
        nextStepLabel.textContent = 'Next step';
        reviewPanel.appendChild(nextStepLabel);
        const nextStepNote = document.createElement('p');
        nextStepNote.className = 'quiet-note';
        if (lifecycleState.canSubmit) {
            nextStepNote.textContent = packageState.publish_ready
                ? 'Submit this draft for review when you are ready.'
                : 'Fix the validation issues above, then submit this draft for review.';
        } else if (lifecycleState.canApprove) {
            nextStepNote.textContent = 'Approve this draft to make it publishable, or reject it if it still needs changes.';
        } else if (lifecycleState.canPublish && !lifecycleState.isPublished) {
            nextStepNote.textContent = 'Publish this approved draft when you are ready for it to become active on the bot.';
        } else if (lifecycleState.isArchived) {
            nextStepNote.textContent = 'This draft is archived.';
        } else {
            nextStepNote.textContent = 'This revision is already live. Archive it only if you want to retire it.';
        }
        reviewPanel.appendChild(nextStepNote);
        const reviewActions = document.createElement('div');
        reviewActions.className = 'editor-actions';
        [submitBtn, approveBtn, rejectBtn, publishBtn, archiveBtn].forEach((button) => reviewActions.appendChild(button));
        reviewPanel.appendChild(reviewActions);

        const advancedPanel = document.createElement('section');
        advancedPanel.className = 'editor-panel';
        advancedPanel.dataset.key = `studio-advanced:${detail.name || ''}`;
        const advancedTitle = document.createElement('div');
        advancedTitle.className = 'editor-section-title';
        advancedTitle.textContent = 'Advanced';
        advancedPanel.appendChild(advancedTitle);
        advancedPanel.appendChild(UI.renderMetadataGrid([
            { label: 'Skill slug', value: detail.name || '(unnamed)' },
            { label: 'Visibility', value: detail.visibility || 'private' },
            { label: 'Draft revision', value: lifecycle?.active_revision_id || '(none)' },
            { label: 'Published revision', value: lifecycle?.published_revision_id || '(none)' },
        ]));
        const kindSelect = document.createElement('select');
        kindSelect.className = 'input';
        [['prompt', 'Prompt skill'], ['executable', 'Executable skill']].forEach(([value, label]) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            option.selected = draftBuffer.skill_kind === value;
            kindSelect.appendChild(option);
        });
        kindSelect.addEventListener('change', () => {
            draftBuffer.skill_kind = kindSelect.value;
            markDirty();
        });
        advancedPanel.appendChild(kindSelect);

        const exportPanel = document.createElement('section');
        exportPanel.className = 'editor-panel';
        exportPanel.dataset.key = `studio-package:${detail.name || ''}`;
        exportPanel.innerHTML = '<div class="editor-section-title">Package</div><p class="quiet-note">Export the draft you are editing, or the published revision currently active on this bot.</p>';
        const exportActions = document.createElement('div');
        exportActions.className = 'editor-actions';
        const exportDraftBtn = document.createElement('button');
        exportDraftBtn.type = 'button';
        exportDraftBtn.className = 'btn btn-sm';
        exportDraftBtn.textContent = 'Export draft';
        exportDraftBtn.addEventListener('click', async () => {
            try {
                const artifact = await API.exportSkillPackage(currentAgentId, detail.name, { revision: 'draft' });
                _downloadPackageArtifact(artifact);
            } catch (err) {
                UI.reportError('Failed to export the draft package', err, { context: 'Skill draft export failed' });
            }
        });
        exportActions.appendChild(exportDraftBtn);
        if (lifecycle?.published_revision_id) {
            const exportPublishedBtn = document.createElement('button');
            exportPublishedBtn.type = 'button';
            exportPublishedBtn.className = 'btn btn-sm';
            exportPublishedBtn.textContent = 'Export published';
            exportPublishedBtn.addEventListener('click', async () => {
                try {
                    const artifact = await API.exportSkillPackage(currentAgentId, detail.name, { revision: 'published' });
                    _downloadPackageArtifact(artifact);
                } catch (err) {
                    UI.reportError('Failed to export the published package', err, { context: 'Skill published export failed' });
                }
            });
            exportActions.appendChild(exportPublishedBtn);
        }
        const importBtn = document.createElement('button');
        importBtn.type = 'button';
        importBtn.className = 'btn btn-sm';
        importBtn.textContent = 'Import package';
        importBtn.addEventListener('click', () => _openImportDialog());
        exportActions.appendChild(importBtn);
        exportPanel.appendChild(exportActions);

        const history = document.createElement('section');
        history.className = 'editor-panel';
        history.dataset.key = `studio-history:${detail.name || ''}`;
        history.innerHTML = '<div class="editor-section-title">Revision history</div>';
        if ((lifecycle?.revisions || []).length) {
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
            history.appendChild(revisions);
        } else {
            history.appendChild(UI.renderEmptyState('No revisions recorded yet.', true));
        }

        if (currentStudioTab === 'write') {
            nodes.push(basicsPanel, instructionsPanel);
        } else if (currentStudioTab === 'setup') {
            nodes.push(requirementsPanel);
        } else if (currentStudioTab === 'review') {
            nodes.push(reviewPanel);
        } else {
            nodes.push(advancedPanel, providersPanel, filesPanel, exportPanel, history);
        }

        refreshChrome();
        return nodes;
    }

    async function loadSkills({ soft = false, forceCatalog = false } = {}) {
        if (!currentAgentId) {
            allSkills = [];
            registrySkills = [];
            registryError = '';
            selectedLocalDetail = null;
            selectedLifecycle = null;
            renderList();
            void loadSelectionData({ soft: true });
            return;
        }
        const queryText = _queryText();
        const shouldLoadCatalog = forceCatalog || !allSkills.length;
        const hadVisibleState = listEl.childElementCount > 0;
        let hasCachedView = false;
        if (shouldLoadCatalog) {
            const cachedCatalog = UI.peekCachedData(RegistrySkillHub.listCacheKey(currentAgentId));
            if (cachedCatalog) {
                const data = Array.isArray(cachedCatalog) ? cachedCatalog : (cachedCatalog.skills || []);
                allSkills = _preserveSelectedCustomDraft(Array.isArray(data) ? data : []);
                hasCachedView = true;
            }
        }
        if (RegistrySkillHub.canSearchStore(_currentAgent()) && queryText.length >= 2) {
            const cachedSearch = UI.peekCachedData(RegistrySkillHub.searchCacheKey(currentAgentId, queryText));
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
        if (!soft && !hasCachedView && (shouldLoadCatalog || queryText.length >= 2)) {
            renderLoadingState(queryText.length >= 2 ? 'Searching skills…' : 'Loading skills…');
        }
        try {
            if (shouldLoadCatalog) {
                const data = await UI.loadCachedData(
                    RegistrySkillHub.listCacheKey(currentAgentId),
                    () => API.listSkills(currentAgentId),
                    {
                        ttlMs: SKILL_CACHE_TTL_MS,
                        errorTtlMs: CACHE_ERROR_TTL_MS,
                        forceRefresh: hasCachedView || forceCatalog,
                    },
                );
                allSkills = _preserveSelectedCustomDraft(Array.isArray(data) ? data : (data.skills || []));
            }
            if (RegistrySkillHub.canSearchStore(_currentAgent()) && queryText.length >= 2) {
                const search = await UI.loadCachedData(
                    RegistrySkillHub.searchCacheKey(currentAgentId, queryText),
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
                UI.reportError('Failed to refresh skills', err, { context: 'Skill refresh failed' });
                return;
            }
            UI.clearMemoizedRender(listEl);
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load skills: ' + err.message, loadSkills)]);
        }
    }

    async function loadAgents({ soft = false } = {}) {
        try {
            const previousAgentId = currentAgentId;
            let routingError = '';
            const [data, routingSkills] = await Promise.all([
                API.listAgents({ limit: 100 }),
                API.listRoutingSkills().catch((err) => {
                    routingError = err.message || String(err);
                    return [];
                }),
            ]);
            globalRoutingError = routingError;
            availableAgents = Array.isArray(data) ? data : (data.agents || []);
            globalRoutingSkills = Array.isArray(routingSkills) ? routingSkills : [];
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
            void loadSkills({ soft: true });
        }, 250);
    });

    const beforeUnload = (event) => {
        if (!_hasUnsavedDraft()) return;
        event.preventDefault();
        event.returnValue = '';
    };
    window.addEventListener('beforeunload', beforeUnload);

    container.__routeReady = loadAgents();

    cleanups.add(() => clearTimeout(searchTimeout));
    cleanups.add(() => window.removeEventListener('beforeunload', beforeUnload));
    UI.subscribeWithRefresh(cleanups, 'agents', () => loadAgents({ soft: true }), 600);
}
