/**
 * Conversation detail — full-height chat and structured event timeline.
 */
function renderConversationDetail(container, params) {
    const convoId = params.id;
    const cleanups = UI.beginCleanupScope();
    container.classList.add('conversation-screen');
    cleanups.add(() => container.classList.remove('conversation-screen'));
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        contentInner.classList.add('conversation-route-shell');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
        cleanups.add(() => contentInner.classList.remove('conversation-route-shell'));
    }
    let meta = null;
    let beforeSeq = 0;
    let latestSeq = 0;
    let hasMoreBefore = false;
    let loadingOlder = false;
    let conversationDisposed = false;
    const initialViewState = _readConversationViewState();
    let activeView = initialViewState.value;
    let activeViewExplicit = initialViewState.explicit;
    let requestedManagementMode = _readManagementModeParam();
    let requestedActivationSkill = _readRequestedActivationSkillParam();
    let topObserver = null;
    const conversationLoadKinds = [
        'message.user',
        'message.bot',
        'approval.requested',
        'error',
    ];
    let relatedTasks = [];
    let tasksLoaded = false;
    let suggestionMatches = [];
    let suggestionIndex = -1;
    let suggestionEngine = null;
    let relatedTasksReloadDebounce = null;
    let conversationSkills = null;
    let conversationSettings = null;
    let availableConversationSkills = [];
    let availableConversationProtocols = [];
    let conversationProtocolsLoaded = false;
    let linkedProtocolRuns = [];
    const linkedRunSubscriptions = new Map();
    let selectedActivationSkill = requestedActivationSkill;
    let selectedProtocolId = '';
    let protocolProblemStatement = '';
    let protocolLaunchContext = {};
    let protocolLaunchFieldsByProtocolId = {};
    const protocolLaunchFieldLoads = new Set();
    let protocolSearchQuery = '';
    let managementReloadDebounce = null;
    let linkedRunsReloadDebounce = null;
    let pendingSkillSetup = null;
    let managementMode = 'closed';
    let managementIdleTimer = null;
    let managementSuccessTimer = null;
    let managementBusyCount = 0;
    let managementSupport = {
        skills: true,
        settings: true,
        protocols: true,
    };
    let skillsStatusMessage = '';
    let settingsStatusMessage = '';
    let protocolsStatusMessage = '';
    let latestConversationMessageCount = 0;
    let eventLoadRequestToken = 0;

    const page = document.createElement('section');
    page.className = 'conversation-page';
    container.appendChild(page);

    const shell = document.createElement('section');
    shell.className = 'conversation-shell';
    page.appendChild(shell);

    const metaCard = document.createElement('header');
    metaCard.className = 'workspace-header conversation-meta';
    shell.appendChild(metaCard);

    const toolbar = document.createElement('div');
    toolbar.className = 'conversation-toolbar conversation-toolbar-shell';
    metaCard.appendChild(toolbar);

    const filterControl = UI.createSegmentedControl([
        {
            key: 'conversation',
            value: 'conversation',
            label: 'Conversation',
            id: 'conversation-view-tab',
            controls: 'conversation-timeline-panel',
        },
        {
            key: 'tasks',
            value: 'tasks',
            label: 'Linked work',
            id: 'task-view-tab',
            controls: 'conversation-timeline-panel',
        },
        {
            key: 'activity',
            value: 'activity',
            label: 'Full activity',
            id: 'activity-view-tab',
            controls: 'conversation-timeline-panel',
        },
    ], (value) => applyFilter(value), {
        label: 'Conversation timeline view',
        value: activeView,
    });
    const filterGroup = filterControl.element;
    toolbar.appendChild(filterGroup);

    const allBtn = filterControl.buttons.get('conversation');
    const tasksBtn = filterControl.buttons.get('tasks');
    const messagesBtn = filterControl.buttons.get('activity');

    const actionGroup = document.createElement('div');
    actionGroup.className = 'workspace-actions';

    const exportBtn = document.createElement('button');
    exportBtn.className = 'btn btn-sm';
    exportBtn.textContent = 'Export';
    actionGroup.appendChild(exportBtn);

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn btn-sm btn-danger';
    cancelBtn.textContent = 'Cancel';
    actionGroup.appendChild(cancelBtn);

    const skillsManageBtn = document.createElement('button');
    skillsManageBtn.className = 'btn btn-sm conversation-manage-trigger';
    skillsManageBtn.type = 'button';
    skillsManageBtn.textContent = 'Skills';
    skillsManageBtn.hidden = true;
    actionGroup.appendChild(skillsManageBtn);

    const settingsManageBtn = document.createElement('button');
    settingsManageBtn.className = 'btn btn-sm conversation-manage-trigger';
    settingsManageBtn.type = 'button';
    settingsManageBtn.textContent = 'Settings';
    settingsManageBtn.hidden = true;
    actionGroup.appendChild(settingsManageBtn);

    const protocolsManageBtn = document.createElement('button');
    protocolsManageBtn.className = 'btn btn-sm conversation-manage-trigger';
    protocolsManageBtn.type = 'button';
    protocolsManageBtn.textContent = 'Protocols';
    protocolsManageBtn.hidden = true;
    actionGroup.appendChild(protocolsManageBtn);

    const managementPanel = document.createElement('section');
    managementPanel.className = 'conversation-management-grid';
    managementPanel.id = 'conversation-management-panel';
    managementPanel.hidden = true;
    shell.appendChild(managementPanel);

    const skillsPanel = document.createElement('section');
    skillsPanel.className = 'card conversation-management-card';
    managementPanel.appendChild(skillsPanel);

    const settingsPanel = document.createElement('section');
    settingsPanel.className = 'card conversation-management-card';
    managementPanel.appendChild(settingsPanel);
    const protocolsPanel = document.createElement('section');
    protocolsPanel.className = 'card conversation-management-card';
    managementPanel.appendChild(protocolsPanel);
    skillsManageBtn.setAttribute('aria-controls', managementPanel.id);
    settingsManageBtn.setAttribute('aria-controls', managementPanel.id);
    protocolsManageBtn.setAttribute('aria-controls', managementPanel.id);

    const layout = document.createElement('div');
    layout.className = 'conversation-layout';
    shell.appendChild(layout);

    const timelinePanel = document.createElement('div');
    timelinePanel.className = 'card conversation-panel';
    timelinePanel.id = 'conversation-timeline-panel';
    timelinePanel.setAttribute('role', 'tabpanel');
    timelinePanel.setAttribute('aria-labelledby', allBtn.id);
    layout.appendChild(timelinePanel);

    const timeline = document.createElement('div');
    timeline.className = 'chat-timeline';
    timelinePanel.appendChild(timeline);

    const taskView = document.createElement('div');
    taskView.className = 'conversation-task-view';
    taskView.hidden = true;
    timelinePanel.appendChild(taskView);

    const taskSummaryStrip = document.createElement('div');
    taskSummaryStrip.className = 'task-summary-strip';
    taskView.appendChild(taskSummaryStrip);

    const taskBoard = document.createElement('div');
    taskBoard.className = 'task-board task-board-conversation';
    taskView.appendChild(taskBoard);

    const liveRegion = document.createElement('div');
    liveRegion.className = 'sr-only';
    liveRegion.setAttribute('aria-live', 'polite');
    liveRegion.setAttribute('aria-atomic', 'true');
    timelinePanel.appendChild(liveRegion);

    const progressBanner = document.createElement('div');
    progressBanner.className = 'conversation-progress-banner';
    progressBanner.hidden = true;
    timelinePanel.appendChild(progressBanner);

    const sentinel = document.createElement('div');
    sentinel.className = 'history-sentinel';
    sentinel.setAttribute('aria-hidden', 'true');
    timeline.appendChild(sentinel);

    const historyStatus = document.createElement('div');
    historyStatus.className = 'history-status';
    timeline.appendChild(historyStatus);

    const eventList = document.createElement('div');
    eventList.className = 'timeline-events';
    timeline.appendChild(eventList);

    const composer = document.createElement('div');
    composer.className = 'compose-box';
    timelinePanel.appendChild(composer);

    const composeMeta = document.createElement('div');
    composeMeta.className = 'compose-meta';
    composer.appendChild(composeMeta);

    const composeHint = document.createElement('div');
    composeHint.className = 'compose-hint';
    composeHint.hidden = true;
    composeMeta.appendChild(composeHint);

    const targetPreview = document.createElement('div');
    targetPreview.className = 'compose-target-preview';
    targetPreview.hidden = true;
    composeMeta.appendChild(targetPreview);

    const textarea = document.createElement('textarea');
    textarea.placeholder = 'Reply in this conversation';
    textarea.setAttribute('aria-label', 'Message text');
    textarea.setAttribute('title', 'Enter sends. Shift+Enter adds a new line.');
    textarea.rows = 1;
    composer.appendChild(textarea);

    const sendBtn = document.createElement('button');
    sendBtn.className = 'btn btn-primary';
    sendBtn.type = 'button';
    sendBtn.textContent = 'Send';
    sendBtn.setAttribute('aria-label', 'Send message');
    composer.appendChild(sendBtn);

    const suggestionList = document.createElement('div');
    suggestionList.className = 'compose-suggestions';
    suggestionList.hidden = true;
    composer.appendChild(suggestionList);

    let progressTimer = null;
    let availableTargets = [];
    let latestSuggestionToken = '';

    async function loadTargetSuggestions() {
        try {
            const [agentData, routingData] = await Promise.all([
                API.listAgents({ state: 'connected', limit: 100 }),
                API.listRoutingSkills().catch(() => []),
            ]);
            const agents = agentData.agents || agentData || [];
            const routingSkills = routingData.routing_skills || routingData || [];
            const seen = new Set();
            availableTargets = [];
            function pushTarget(item) {
                const key = `${item.kind}:${String(item.key || item.label || '').toLowerCase()}`;
                if (seen.has(key)) return;
                seen.add(key);
                availableTargets.push(item);
            }
            agents.forEach((agent) => {
                if (String((agent && agent.execution_state) || 'healthy') === 'faulted') {
                    return;
                }
                const slug = (agent.slug || agent.agent_id || '').trim();
                if (!slug) return;
                const displayName = String(agent.display_name || '').trim();
                const preferredLabel = String(agent.selector || '').trim();
                const aliases = Array.from(new Set(
                    (agent.selector_aliases || []).map((value) => String(value || '').trim()).filter(Boolean)
                ));
                if (!preferredLabel || !aliases.length) return;
                const detail = [
                    displayName && preferredLabel.toLowerCase() !== '@' + slug.toLowerCase() ? slug : '',
                    agent.role || '',
                    (agent.routing_skills || []).slice(0, 2).join(', '),
                ].filter(Boolean).join(' · ');
                pushTarget({
                    key: agent.agent_id || slug,
                    label: preferredLabel,
                    kind: 'agent',
                    display: displayName || slug,
                    detail,
                    aliases,
                });
            });
            agents.forEach((agent) => {
                const role = String(agent.role || '').trim();
                const roleSelector = String(agent.role_selector || '').trim();
                if (!role || !roleSelector) return;
                pushTarget({
                    key: role,
                    label: roleSelector,
                    kind: 'role',
                    display: role,
                    detail: 'Role target',
                    aliases: [roleSelector],
                });
            });
            routingSkills.forEach((routingSkill) => {
                const value = String(routingSkill.name || routingSkill.skill_name || routingSkill || '').trim();
                const selector = String(routingSkill.selector || '').trim();
                if (!value || !selector) return;
                pushTarget({
                    key: value,
                    label: selector,
                    kind: 'skill',
                    display: value,
                    detail: 'Routing skill',
                    aliases: [selector],
                });
            });
            if (typeof Fuse === 'function') {
                suggestionEngine = new Fuse(availableTargets, {
                    includeScore: true,
                    threshold: 0.34,
                    ignoreLocation: true,
                    keys: [
                        { name: 'label', weight: 0.36 },
                        { name: 'aliases', weight: 0.30 },
                        { name: 'display', weight: 0.22 },
                        { name: 'detail', weight: 0.12 },
                    ],
                });
            } else {
                suggestionEngine = null;
            }
        } catch {
            availableTargets = [];
            suggestionEngine = null;
        }
        updateComposerAssist();
    }

    function managementAgentId() {
        return String((meta && meta.target_agent_id) || '').trim();
    }

    function managementConversationPath() {
        return convoId;
    }

    function managementAvailable() {
        return Boolean(managementAgentId());
    }

    function protocolWorkspaceRef() {
        return String((conversationSettings && conversationSettings.project_id) || '').trim();
    }

    function protocolRunHref(runId) {
        return `/ui/runs?run_id=${encodeURIComponent(String(runId || '').trim())}`;
    }

    function syncManagementQueryParams() {
        UI.updateQueryParams({
            manage: managementMode === 'closed' ? '' : managementMode,
            activate_skill: requestedActivationSkill || '',
        });
    }

    function clearRequestedActivationSkill() {
        if (!requestedActivationSkill) return;
        requestedActivationSkill = '';
        syncManagementQueryParams();
    }

    function clearManagementTimers() {
        clearTimeout(managementIdleTimer);
        clearTimeout(managementSuccessTimer);
    }

    function managementHasFocusedInput() {
        const active = document.activeElement;
        if (!active || !managementPanel.contains(active)) return false;
        return active.matches('input, textarea, select');
    }

    function canAutoCloseManagement() {
        return managementMode !== 'closed'
            && !pendingSkillSetup
            && managementBusyCount === 0
            && !managementHasFocusedInput();
    }

    function syncManagementControls() {
        const available = managementAvailable();
        skillsManageBtn.hidden = !available;
        settingsManageBtn.hidden = !available;
        protocolsManageBtn.hidden = !available;
        skillsManageBtn.className = managementMode === 'skills'
            ? 'btn btn-sm btn-primary conversation-manage-trigger'
            : 'btn btn-sm conversation-manage-trigger';
        settingsManageBtn.className = managementMode === 'settings'
            ? 'btn btn-sm btn-primary conversation-manage-trigger'
            : 'btn btn-sm conversation-manage-trigger';
        protocolsManageBtn.className = managementMode === 'protocols'
            ? 'btn btn-sm btn-primary conversation-manage-trigger'
            : 'btn btn-sm conversation-manage-trigger';
        skillsManageBtn.setAttribute('aria-pressed', String(managementMode === 'skills'));
        settingsManageBtn.setAttribute('aria-pressed', String(managementMode === 'settings'));
        protocolsManageBtn.setAttribute('aria-pressed', String(managementMode === 'protocols'));
        skillsManageBtn.setAttribute('aria-expanded', String(available && managementMode === 'skills'));
        settingsManageBtn.setAttribute('aria-expanded', String(available && managementMode === 'settings'));
        protocolsManageBtn.setAttribute('aria-expanded', String(available && managementMode === 'protocols'));
        managementPanel.hidden = !available || managementMode === 'closed';
        managementPanel.dataset.mode = managementMode;
        skillsPanel.hidden = managementMode !== 'skills';
        settingsPanel.hidden = managementMode !== 'settings';
        protocolsPanel.hidden = managementMode !== 'protocols';
    }

    function scheduleManagementIdleClose(timeoutMs = 10000) {
        clearTimeout(managementIdleTimer);
        if (managementMode === 'closed' || timeoutMs <= 0) return;
        managementIdleTimer = setTimeout(() => {
            if (canAutoCloseManagement()) {
                closeManagement();
                return;
            }
            if (managementMode !== 'closed' && !pendingSkillSetup) {
                scheduleManagementIdleClose(timeoutMs);
            }
        }, timeoutMs);
    }

    function scheduleManagementSuccessClose(timeoutMs = 2600) {
        clearTimeout(managementSuccessTimer);
        managementSuccessTimer = setTimeout(() => {
            if (canAutoCloseManagement()) {
                closeManagement();
            } else if (managementMode !== 'closed' && !pendingSkillSetup) {
                scheduleManagementIdleClose();
            }
        }, timeoutMs);
    }

    function markManagementInteraction() {
        if (managementMode !== 'closed' && !pendingSkillSetup) {
            scheduleManagementIdleClose();
        }
    }

    function openManagement(nextMode, { focus = false } = {}) {
        if (!managementAvailable()) return;
        if (nextMode === 'protocols' && !protocolProblemStatement && String(textarea.value || '').trim()) {
            protocolProblemStatement = String(textarea.value || '').trim();
        }
        managementMode = nextMode;
        requestedManagementMode = nextMode;
        syncManagementQueryParams();
        syncManagementControls();
        if (meta) renderMetaCard(meta);
        scheduleManagementIdleClose();
        if (nextMode === 'protocols') {
            renderProtocolsPanel();
            if (!conversationProtocolsLoaded) {
                void loadConversationProtocols({ soft: true });
            }
        }
        if (focus) {
            requestAnimationFrame(() => {
                const firstControl = managementPanel.querySelector('input, select, textarea')
                    || managementPanel.querySelector('button:not(.conversation-management-close)');
                if (firstControl instanceof HTMLElement) {
                    firstControl.focus();
                }
            });
        }
    }

    function closeManagement({ clearStatus = true } = {}) {
        clearManagementTimers();
        managementMode = 'closed';
        requestedManagementMode = 'closed';
        requestedActivationSkill = '';
        selectedActivationSkill = '';
        syncManagementQueryParams();
        if (clearStatus) {
            skillsStatusMessage = '';
            settingsStatusMessage = '';
            protocolsStatusMessage = '';
        }
        syncManagementControls();
        if (meta) renderMetaCard(meta);
        if (activeView !== 'tasks' && !textarea.disabled) {
            requestAnimationFrame(() => textarea.focus());
        }
    }

    async function runManagementRequest(task) {
        managementBusyCount += 1;
        clearTimeout(managementSuccessTimer);
        try {
            return await task();
        } finally {
            managementBusyCount = Math.max(0, managementBusyCount - 1);
            if (managementMode !== 'closed' && !pendingSkillSetup) {
                scheduleManagementIdleClose();
            }
        }
    }

    function isSkillUnavailableError(err) {
        const message = String((err && err.message) || '');
        return message.startsWith('409:');
    }

    function resetManagementView() {
        syncManagementControls();
        renderSkillsPanel();
        renderSettingsPanel();
        renderProtocolsPanel();
    }

    function activeConversationSkillDetails() {
        return Array.isArray(conversationSkills?.active_skill_details)
            ? conversationSkills.active_skill_details
            : [];
    }

    function activeConversationSkillNames() {
        return new Set(
            activeConversationSkillDetails()
                .map((item) => String(item?.name || '').trim())
                .filter(Boolean),
        );
    }

    function skillSemanticsLabel(skill) {
        return String(skill?.skill_kind || '').trim() === 'executable'
            ? 'executable workflow'
            : 'prompt instructions';
    }

    function activeSkillSemanticsNote(skills) {
        const items = Array.isArray(skills) ? skills : [];
        if (!items.length) return '';
        const hasExecutable = items.some((skill) => String(skill?.skill_kind || '').trim() === 'executable');
        const hasPrompt = items.some((skill) => String(skill?.skill_kind || '').trim() !== 'executable');
        if (hasPrompt && hasExecutable) {
            return 'Prompt skills apply as operator-selected instructions here. Executable skills run through Octopus runtime orchestration.';
        }
        if (hasExecutable) {
            return 'Executable skills run through Octopus runtime orchestration for this conversation.';
        }
        return 'Prompt skills apply as operator-selected instructions for this conversation until they are deactivated.';
    }

    async function refreshConversationSkillState({ soft = true } = {}) {
        await loadConversationSkills({ soft });
        if (meta) {
            renderMetaCard(meta);
        }
    }

    async function requestConversationSkillActivation(skillName, { fromRoute = false } = {}) {
        const normalizedSkill = String(skillName || '').trim();
        const agentId = managementAgentId();
        if (!normalizedSkill || !agentId) return;

        openManagement('skills');
        selectedActivationSkill = normalizedSkill;
        clearRequestedActivationSkill();

        const activeNames = activeConversationSkillNames();
        if (activeNames.has(normalizedSkill)) {
            skillsStatusMessage = `${normalizedSkill} is already active in this conversation.`;
            await refreshConversationSkillState();
            renderSkillsPanel();
            scheduleManagementIdleClose(12000);
            return;
        }

        const available = (availableConversationSkills || []).some((item) => item && item.can_activate && item.name === normalizedSkill);
        if (!available) {
            skillsStatusMessage = `${normalizedSkill} is not available to activate on this bot.`;
            renderSkillsPanel();
            scheduleManagementIdleClose(12000);
            return;
        }

        const runActivation = async (confirm) => API.activateConversationSkill(
            agentId,
            managementConversationPath(),
            normalizedSkill,
            confirm ? { confirm: true } : {},
        );

        const finalizeActivation = async (result) => {
            pendingSkillSetup = null;
            selectedActivationSkill = '';
            skillsStatusMessage = result.status === 'activated'
                ? `Activated ${normalizedSkill}.`
                : `${normalizedSkill} is already active in this conversation.`;
            await refreshConversationSkillState();
            renderSkillsPanel();
            scheduleManagementIdleClose(12000);
        };

        try {
            const result = await runManagementRequest(() => runActivation(false));
            if (result.status === 'needs_confirmation') {
                skillsStatusMessage = `Confirm activation for ${normalizedSkill}.`;
                renderSkillsPanel();
                UI.showConfirm('Activate Skill', 'This skill may increase prompt size. Continue?', async () => {
                    try {
                        const confirmed = await runManagementRequest(() => runActivation(true));
                        if (confirmed.status === 'needs_setup' && confirmed.first_requirement) {
                            pendingSkillSetup = {
                                skillName: normalizedSkill,
                                ownerActor: 'reg:registry-ui',
                                requirement: confirmed.first_requirement,
                                validationError: '',
                            };
                            skillsStatusMessage = `Setup required for ${normalizedSkill}.`;
                            renderSkillsPanel();
                            scheduleManagementIdleClose(12000);
                            return;
                        }
                        if (confirmed.status === 'foreign_setup') {
                            pendingSkillSetup = {
                                skillName: normalizedSkill,
                                ownerActor: String(confirmed.foreign_setup_user || ''),
                                requirement: null,
                                validationError: '',
                            };
                            skillsStatusMessage = `Setup already in progress for ${normalizedSkill}.`;
                            renderSkillsPanel();
                            scheduleManagementIdleClose(12000);
                            return;
                        }
                        await finalizeActivation(confirmed);
                    } catch (err) {
                        UI.reportError('Failed to activate the skill', err, { context: 'Conversation skill activation confirm failed' });
                    }
                });
                return;
            }
            if (result.status === 'needs_setup' && result.first_requirement) {
                pendingSkillSetup = {
                    skillName: normalizedSkill,
                    ownerActor: 'reg:registry-ui',
                    requirement: result.first_requirement,
                    validationError: '',
                };
                skillsStatusMessage = `Setup required for ${normalizedSkill}.`;
                renderSkillsPanel();
                scheduleManagementIdleClose(12000);
                return;
            }
            if (result.status === 'foreign_setup') {
                pendingSkillSetup = {
                    skillName: normalizedSkill,
                    ownerActor: String(result.foreign_setup_user || ''),
                    requirement: null,
                    validationError: '',
                };
                skillsStatusMessage = `Setup already in progress for ${normalizedSkill}.`;
                renderSkillsPanel();
                scheduleManagementIdleClose(12000);
                return;
            }
            await finalizeActivation(result);
        } catch (err) {
            if (fromRoute) {
                selectedActivationSkill = normalizedSkill;
            }
            UI.reportError('Failed to activate the skill', err, { context: 'Conversation skill activate failed' });
        }
    }

    async function handleRequestedSkillActivation() {
        const normalizedSkill = String(requestedActivationSkill || '').trim();
        if (!normalizedSkill || !managementAvailable() || pendingSkillSetup) {
            return;
        }
        await requestConversationSkillActivation(normalizedSkill, { fromRoute: true });
    }

    function syncPendingSetupFromState(skillsState) {
        const setup = skillsState && skillsState.pending_setup;
        if (!setup || !setup.requirement) {
            if (pendingSkillSetup && pendingSkillSetup.ownerActor === 'reg:registry-ui') {
                pendingSkillSetup = null;
            }
            return;
        }
        pendingSkillSetup = {
            skillName: String(setup.skill_name || ''),
            ownerActor: String(setup.actor_key || ''),
            requirement: setup.requirement,
            validationError: pendingSkillSetup ? String(pendingSkillSetup.validationError || '') : '',
        };
        openManagement('skills');
    }

    function createManagementHeader(title) {
        const header = document.createElement('div');
        header.className = 'workspace-header-main';
        const titleGroup = document.createElement('div');
        titleGroup.className = 'workspace-title-group';
        const titleEl = document.createElement('h3');
        titleEl.className = 'editor-section-title';
        titleEl.textContent = title;
        titleGroup.appendChild(titleEl);
        header.appendChild(titleGroup);
        const actions = document.createElement('div');
        actions.className = 'workspace-actions';
        const closeBtn = document.createElement('button');
        closeBtn.className = 'btn btn-sm conversation-management-close';
        closeBtn.type = 'button';
        closeBtn.setAttribute('aria-label', `Close ${title}`);
        closeBtn.textContent = '×';
        closeBtn.addEventListener('click', () => closeManagement());
        actions.appendChild(closeBtn);
        header.appendChild(actions);
        header._actionGroup = actions;
        return header;
    }

    function renderSkillsPanel() {
        const agentId = managementAgentId();
        syncManagementControls();
        if (!agentId) {
            UI.clearMemoizedRender(skillsPanel);
            UI.reconcileChildren(skillsPanel, []);
            return;
        }
        const skillState = conversationSkills || { active_skills: [], active_skill_details: [], pending_setup: null };
        const activeNames = new Set(skillState.active_skills || []);
        const activatable = (availableConversationSkills || []).filter((item) => item && item.can_activate && !activeNames.has(item.name));
        const pendingSetupSignature = pendingSkillSetup ? {
            skillName: String(pendingSkillSetup.skillName || ''),
            ownerActor: String(pendingSkillSetup.ownerActor || ''),
            requirementKey: String((pendingSkillSetup.requirement && pendingSkillSetup.requirement.key) || ''),
            validationError: String(pendingSkillSetup.validationError || ''),
        } : null;

        UI.memoizedRender(skillsPanel, {
            supported: managementSupport.skills,
            skillState,
            activatable,
            pendingSetup: pendingSetupSignature,
            statusMessage: String(skillsStatusMessage || ''),
        }, (state) => {
            const nodes = [];
            const header = createManagementHeader('Conversation skills');
            if (state.supported && (state.skillState.active_skills || []).length) {
                const clearBtn = document.createElement('button');
                clearBtn.className = 'btn btn-sm';
                clearBtn.type = 'button';
                clearBtn.textContent = 'Clear all';
                clearBtn.addEventListener('click', async () => {
                    clearBtn.disabled = true;
                    try {
                        const result = await runManagementRequest(() => API.clearConversationSkills(agentId, managementConversationPath()));
                        skillsStatusMessage = result.status === 'cleared' ? 'Cleared active skills.' : String(result.status || 'Updated');
                        pendingSkillSetup = null;
                        selectedActivationSkill = '';
                        await refreshConversationSkillState();
                        renderSkillsPanel();
                        scheduleManagementIdleClose(12000);
                    } catch (err) {
                        UI.reportError('Failed to clear conversation skills', err, { context: 'Conversation skill clear failed' });
                    }
                    clearBtn.disabled = false;
                });
                header._actionGroup.prepend(clearBtn);
            }
            nodes.push(header);

            if (!state.supported) {
                nodes.push(UI.renderEmptyState('This bot does not expose conversation skills in the registry.', true));
                return nodes;
            }

            if (state.statusMessage) {
                const status = document.createElement('div');
                status.className = 'conversation-management-status';
                status.textContent = state.statusMessage;
                nodes.push(status);
            }

            const explainer = document.createElement('p');
            explainer.className = 'quiet-note';
            explainer.textContent = 'Use this panel to choose what is active in this conversation. Prompt skills apply as conversation instructions here; executable skills run through runtime orchestration. To install, update, or edit skills for this bot, open the Skills page.';
            nodes.push(explainer);

            if (state.pendingSetup) {
                const foreignSetup = String(state.pendingSetup.ownerActor || '') && state.pendingSetup.ownerActor !== 'reg:registry-ui';
                const setupBox = document.createElement('div');
                setupBox.className = 'conversation-setup-box';
                const requirement = pendingSkillSetup && pendingSkillSetup.requirement ? pendingSkillSetup.requirement : null;
                setupBox.innerHTML = `<strong>${foreignSetup ? 'Credential setup in progress elsewhere' : 'Credential setup required'}</strong>`;
                const description = document.createElement('p');
                description.className = 'conversation-setup-copy';
                if (foreignSetup) {
                    description.textContent = `Another operator started setup for ${state.pendingSetup.skillName || 'this skill'} (${state.pendingSetup.ownerActor}). Finish it there or cancel the active setup first.`;
                    setupBox.appendChild(description);
                } else if (requirement) {
                    description.textContent = requirement.prompt || `Enter the next credential value for ${state.pendingSetup.skillName || 'this skill'}.`;
                    setupBox.appendChild(description);
                    if (requirement.help_url) {
                        const help = document.createElement('a');
                        help.className = 'section-link';
                        help.href = requirement.help_url;
                        help.target = '_blank';
                        help.rel = 'noreferrer';
                        help.textContent = 'Open setup help';
                        setupBox.appendChild(help);
                    }
                    const form = document.createElement('form');
                    form.className = 'conversation-setup-form';
                    const input = document.createElement('input');
                    input.type = 'password';
                    input.className = 'input';
                    input.placeholder = requirement.key || 'Credential value';
                    input.autocomplete = 'off';
                    form.appendChild(input);
                    const actions = document.createElement('div');
                    actions.className = 'event-card-actions';
                    const submit = document.createElement('button');
                    submit.className = 'btn btn-sm btn-primary';
                    submit.type = 'submit';
                    submit.textContent = 'Submit value';
                    actions.appendChild(submit);
                    const cancelSetup = document.createElement('button');
                    cancelSetup.className = 'btn btn-sm';
                    cancelSetup.type = 'button';
                    cancelSetup.textContent = 'Cancel setup';
                    cancelSetup.addEventListener('click', async () => {
                        cancelSetup.disabled = true;
                        try {
                            await runManagementRequest(() => API.conversationAction(convoId, 'cancel_conversation'));
                            pendingSkillSetup = null;
                            skillsStatusMessage = 'Cancelled pending credential setup.';
                            selectedActivationSkill = '';
                            await refreshConversationSkillState();
                            renderSkillsPanel();
                            scheduleManagementIdleClose(12000);
                        } catch (err) {
                            UI.reportError('Failed to cancel the setup', err, { context: 'Conversation skill setup cancel failed' });
                        }
                        cancelSetup.disabled = false;
                    });
                    actions.appendChild(cancelSetup);
                    if (state.pendingSetup.validationError) {
                        const error = document.createElement('span');
                        error.className = 'action-status';
                        error.textContent = state.pendingSetup.validationError;
                        actions.appendChild(error);
                    }
                    form.appendChild(actions);
                    form.addEventListener('submit', async (e) => {
                        e.preventDefault();
                        submit.disabled = true;
                        try {
                            const result = await runManagementRequest(() => API.submitConversationSkillCredential(
                                agentId,
                                managementConversationPath(),
                                state.pendingSetup.skillName,
                                { value: input.value },
                            ));
                            if (result.status === 'validation_failed') {
                                pendingSkillSetup = Object.assign({}, pendingSkillSetup || {}, {
                                    validationError: String(result.validation_error || 'Validation failed.'),
                                });
                                submit.disabled = false;
                                renderSkillsPanel();
                                return;
                            }
                            if (result.status === 'next_requirement' && result.next_requirement) {
                                pendingSkillSetup = {
                                    skillName: String(result.skill_name || state.pendingSetup.skillName || ''),
                                    ownerActor: 'reg:registry-ui',
                                    requirement: result.next_requirement,
                                    validationError: '',
                                };
                                submit.disabled = false;
                                renderSkillsPanel();
                                return;
                            }
                            pendingSkillSetup = null;
                            skillsStatusMessage = result.status === 'ready'
                                ? `Finished setup for ${result.skill_name || state.pendingSetup.skillName || 'the skill'}.`
                                : String(result.status || 'Updated');
                            selectedActivationSkill = '';
                            await refreshConversationSkillState();
                            renderSkillsPanel();
                            scheduleManagementIdleClose(12000);
                        } catch (err) {
                            UI.reportError('Failed to submit the credential value', err, { context: 'Conversation skill credential submit failed' });
                        }
                        submit.disabled = false;
                    });
                    setupBox.appendChild(form);
                }
                nodes.push(setupBox);
            }

            const activeSection = document.createElement('div');
            activeSection.className = 'conversation-management-section';
            const activeTitle = document.createElement('div');
            activeTitle.className = 'detail-label';
            activeTitle.textContent = 'Active in this conversation';
            activeSection.appendChild(activeTitle);
            const activeSkills = state.skillState.active_skill_details || [];
            if (!activeSkills.length) {
                activeSection.appendChild(UI.renderEmptyState('No active skills in this conversation.', true));
            } else {
                const list = document.createElement('div');
                list.className = 'conversation-skill-list';
                activeSkills.forEach((skill) => {
                    const row = document.createElement('div');
                    row.className = 'settings-row';
                    const summaryBits = [
                        skillSemanticsLabel(skill),
                        skill.description || '',
                        skill.source_label || skill.source_kind || '',
                        skill.requires_credentials ? 'setup required' : '',
                    ].filter(Boolean).join(' • ');
                    row.innerHTML = `<div class="settings-row-main"><strong class="settings-row-label">${UI.esc(skill.display_name || skill.name || 'Skill')}</strong><span class="settings-row-sublabel">${UI.esc(summaryBits || 'Skill active in this conversation')}</span></div>`;
                    const actions = document.createElement('div');
                    actions.className = 'event-card-actions';
                    const deactivate = document.createElement('button');
                    deactivate.className = 'btn btn-sm';
                    deactivate.type = 'button';
                    deactivate.textContent = 'Deactivate';
                    deactivate.addEventListener('click', async () => {
                        deactivate.disabled = true;
                        try {
                            const result = await runManagementRequest(() => API.deactivateConversationSkill(agentId, managementConversationPath(), skill.name));
                            skillsStatusMessage = result.status === 'removed'
                                ? `Deactivated ${skill.display_name || skill.name}.`
                                : String(result.status || 'Updated');
                            pendingSkillSetup = null;
                            selectedActivationSkill = '';
                            await refreshConversationSkillState();
                            renderSkillsPanel();
                            scheduleManagementIdleClose(12000);
                        } catch (err) {
                            UI.reportError('Failed to deactivate the skill', err, { context: 'Conversation skill deactivate failed' });
                        }
                        deactivate.disabled = false;
                    });
                    actions.appendChild(deactivate);
                    row.appendChild(actions);
                    list.appendChild(row);
                });
                activeSection.appendChild(list);
            }
            nodes.push(activeSection);

            const activateSection = document.createElement('div');
            activateSection.className = 'conversation-management-section';
            const activateTitle = document.createElement('div');
            activateTitle.className = 'detail-label';
            activateTitle.textContent = 'Available on this bot';
            activateSection.appendChild(activateTitle);
            if (!state.activatable.length) {
                activateSection.appendChild(UI.renderEmptyState('No additional available skills are ready to activate here.', true));
            } else {
                const controls = document.createElement('div');
                controls.className = 'conversation-management-form';
                const select = document.createElement('select');
                select.className = 'input';
                const placeholder = document.createElement('option');
                placeholder.value = '';
                placeholder.textContent = 'Choose an available skill';
                select.appendChild(placeholder);
                state.activatable.forEach((skill) => {
                    const option = document.createElement('option');
                    option.value = skill.name;
                    const setupLabel = skill.requires_credentials ? ' · needs setup' : '';
                    option.textContent = `${skill.display_name || skill.name}${setupLabel}`;
                    select.appendChild(option);
                });
                if (selectedActivationSkill && state.activatable.some((skill) => skill.name === selectedActivationSkill)) {
                    select.value = selectedActivationSkill;
                }
                select.addEventListener('change', () => {
                    selectedActivationSkill = String(select.value || '').trim();
                });
                controls.appendChild(select);
                const activateBtn = document.createElement('button');
                activateBtn.className = 'btn btn-sm btn-primary';
                activateBtn.type = 'button';
                activateBtn.textContent = 'Activate';
                activateBtn.addEventListener('click', async () => {
                    const skillName = select.value;
                    if (!skillName) return;
                    activateBtn.disabled = true;
                    try {
                        await requestConversationSkillActivation(skillName);
                    } finally {
                        activateBtn.disabled = false;
                    }
                });
                controls.appendChild(activateBtn);
                activateSection.appendChild(controls);
            }
            nodes.push(activateSection);
            return nodes;
        }, {
            signatureFn(state) {
                return {
                    supported: Boolean(state.supported),
                    active: (state.skillState.active_skills || []).join('|'),
                    available: (state.activatable || []).map((item) => `${item.name}:${item.lifecycle_status || ''}`).join('|'),
                    pending: state.pendingSetup,
                    statusMessage: String(state.statusMessage || ''),
                };
            },
        });
    }

    function renderSettingsPanel() {
        const agentId = managementAgentId();
        syncManagementControls();
        if (!agentId) {
            UI.clearMemoizedRender(settingsPanel);
            UI.reconcileChildren(settingsPanel, []);
            return;
        }

        UI.memoizedRender(settingsPanel, {
            supported: managementSupport.settings,
            settings: conversationSettings,
            statusMessage: String(settingsStatusMessage || ''),
        }, (state) => {
            const nodes = [];
            const header = createManagementHeader('Conversation settings');
            if (state.supported && state.settings) {
                const reset = document.createElement('button');
                reset.className = 'btn btn-sm btn-danger';
                reset.type = 'button';
                reset.textContent = 'Reset conversation';
                reset.addEventListener('click', () => {
                    UI.showConfirm('Reset Conversation', 'Start a fresh session in this conversation?', async () => {
                        reset.disabled = true;
                        try {
                            const result = await runManagementRequest(() => API.resetConversation(agentId, managementConversationPath()));
                            conversationSettings = result.state || conversationSettings;
                            settingsStatusMessage = String((result.result && result.result.message) || 'Conversation reset.');
                            pendingSkillSetup = null;
                            scheduleConversationManagementRefresh();
                            scheduleManagementSuccessClose();
                        } catch (err) {
                            UI.reportError('Failed to reset the conversation', err, { context: 'Conversation reset failed' });
                        }
                        reset.disabled = false;
                    });
                });
                header._actionGroup.prepend(reset);
            }
            nodes.push(header);

            if (!state.supported) {
                nodes.push(UI.renderEmptyState('This bot does not expose conversation settings in the registry.', true));
                return nodes;
            }
            if (!state.settings) {
                nodes.push(UI.renderEmptyState('Loading conversation settings…', true));
                return nodes;
            }
            if (state.statusMessage) {
                const status = document.createElement('div');
                status.className = 'conversation-management-status';
                status.textContent = state.statusMessage;
                nodes.push(status);
            }

            function buildSelectRow(label, sublabel, currentValue, options, onSave) {
                const row = document.createElement('div');
                row.className = 'settings-row';
                const copy = document.createElement('div');
                copy.className = 'settings-row-main';
                copy.innerHTML = `<strong class="settings-row-label">${UI.esc(label)}</strong><span class="settings-row-sublabel">${UI.esc(sublabel)}</span>`;
                row.appendChild(copy);
                const controls = document.createElement('div');
                controls.className = 'event-card-actions';
                const select = document.createElement('select');
                select.className = 'input input-compact';
                options.forEach((option) => {
                    const el = document.createElement('option');
                    el.value = option.value;
                    el.textContent = option.label;
                    if (option.value === currentValue) {
                        el.selected = true;
                    }
                    select.appendChild(el);
                });
                controls.appendChild(select);
                const save = document.createElement('button');
                save.className = 'btn btn-sm';
                save.type = 'button';
                save.textContent = 'Apply';
                save.addEventListener('click', async () => {
                    save.disabled = true;
                    try {
                        await onSave(select.value);
                    } finally {
                        save.disabled = false;
                    }
                });
                controls.appendChild(save);
                row.appendChild(controls);
                return row;
            }

            async function updateSetting(setting, value, successMessage) {
                try {
                    const response = await runManagementRequest(() => API.updateConversationSetting(agentId, managementConversationPath(), {
                        setting,
                        value,
                    }));
                    conversationSettings = response.state || conversationSettings;
                    settingsStatusMessage = String((response.result && response.result.message) || successMessage || 'Updated');
                    renderSettingsPanel();
                    scheduleManagementSuccessClose();
                } catch (err) {
                    UI.reportError(`Failed to update ${setting.replace(/_/g, ' ')}`, err, { context: 'Conversation setting update failed' });
                }
            }

            nodes.push(buildSelectRow(
                'Approval mode',
                'Control whether this conversation requires manual approval before running tool-heavy work.',
                state.settings.approval_mode || 'on',
                [
                    { value: 'on', label: 'On' },
                    { value: 'off', label: 'Off' },
                ],
                (value) => updateSetting('approval_mode', value, 'Approval mode updated.'),
            ));

            nodes.push(buildSelectRow(
                'Compact mode',
                'Choose whether replies should stay terse and compressed.',
                state.settings.effective_compact_mode ? 'on' : 'off',
                [
                    { value: 'on', label: 'On' },
                    { value: 'off', label: 'Off' },
                ],
                (value) => updateSetting('compact_mode', value, 'Compact mode updated.'),
            ));

            nodes.push(buildSelectRow(
                'Model profile',
                state.settings.effective_model
                    ? `Current effective model: ${state.settings.effective_model}`
                    : 'Use the inherited model or override it for this conversation.',
                state.settings.model_profile || 'inherit',
                [
                    { value: 'inherit', label: 'Inherit default' },
                    ...(state.settings.available_model_profiles || []).map((profile) => ({ value: profile, label: profile })),
                ],
                (value) => updateSetting('model_profile', value, 'Model profile updated.'),
            ));

            nodes.push(buildSelectRow(
                'File policy',
                `Current effective policy: ${state.settings.effective_file_policy || 'edit'}`,
                state.settings.file_policy || 'inherit',
                [
                    { value: 'inherit', label: 'Inherit default' },
                    { value: 'inspect', label: 'Inspect' },
                    { value: 'edit', label: 'Edit' },
                ],
                (value) => updateSetting('file_policy', value, 'File policy updated.'),
            ));

            nodes.push(buildSelectRow(
                'Project',
                'Switch the conversation into a configured project workspace.',
                state.settings.project_id || 'clear',
                [
                    { value: 'clear', label: 'No project' },
                    ...(state.settings.available_projects || []).map((project) => ({ value: project, label: project })),
                ],
                (value) => updateSetting('project', value, 'Project updated.'),
            ));

            const roleRow = document.createElement('div');
            roleRow.className = 'settings-row';
            roleRow.innerHTML = `<div class="settings-row-main"><strong class="settings-row-label">Role</strong><span class="settings-row-sublabel">Free-form role/persona text. Leave blank to inherit the instance default.</span></div>`;
            const roleControls = document.createElement('div');
            roleControls.className = 'event-card-actions';
            const roleInput = document.createElement('input');
            roleInput.type = 'text';
            roleInput.className = 'input input-compact';
            roleInput.value = state.settings.role || '';
            roleInput.placeholder = state.settings.default_role || 'Default role';
            roleControls.appendChild(roleInput);
            const roleSave = document.createElement('button');
            roleSave.className = 'btn btn-sm';
            roleSave.type = 'button';
            roleSave.textContent = 'Save';
            roleSave.addEventListener('click', async () => {
                roleSave.disabled = true;
                await updateSetting('role', roleInput.value, 'Role updated.');
                roleSave.disabled = false;
            });
            roleControls.appendChild(roleSave);
            const roleReset = document.createElement('button');
            roleReset.className = 'btn btn-sm';
            roleReset.type = 'button';
            roleReset.textContent = 'Reset';
            roleReset.addEventListener('click', async () => {
                roleReset.disabled = true;
                await updateSetting('role', '', 'Role reset.');
                roleReset.disabled = false;
            });
            roleControls.appendChild(roleReset);
            roleRow.appendChild(roleControls);
            nodes.push(roleRow);

            return nodes;
        }, {
            signatureFn(state) {
                const settings = state.settings || {};
                return {
                    supported: Boolean(state.supported),
                    role: String(settings.role || ''),
                    defaultRole: String(settings.default_role || ''),
                    approvalMode: String(settings.approval_mode || ''),
                    compactMode: String(settings.compact_mode),
                    effectiveCompactMode: Boolean(settings.effective_compact_mode),
                    modelProfile: String(settings.model_profile || ''),
                    currentProfile: String(settings.current_profile || ''),
                    effectiveModel: String(settings.effective_model || ''),
                    filePolicy: String(settings.file_policy || ''),
                    effectiveFilePolicy: String(settings.effective_file_policy || ''),
                    projectId: String(settings.project_id || ''),
                    availableProjects: (settings.available_projects || []).join('|'),
                    availableProfiles: (settings.available_model_profiles || []).join('|'),
                    statusMessage: String(state.statusMessage || ''),
                };
            },
        });
    }

    function conversationProtocolTimestamp(protocol) {
        return UI.generatedTimestamp(protocol?.display_name || '')
            || UI.generatedTimestamp(protocol?.slug || '');
    }

    function conversationProtocolLabel(protocol) {
        return UI.compactGeneratedName(
            protocol?.display_name || protocol?.slug || protocol?.protocol_id || '',
            { stripUiOnly: true },
        );
    }

    function conversationProtocolFamilyKey(protocol) {
        return UI.compactGeneratedName(
            protocol?.slug || protocol?.display_name || protocol?.protocol_id || '',
            { stripUiOnly: true },
        ).toLowerCase();
    }

    function conversationProtocolSearchMatches(protocol, queryText) {
        const query = String(queryText || '').trim().toLowerCase();
        if (!query) return true;
        const haystack = [
            protocol?.display_name || '',
            protocol?.slug || '',
            protocol?.protocol_id || '',
            conversationProtocolLabel(protocol),
        ].join(' ').toLowerCase();
        return haystack.includes(query);
    }

    function compareConversationProtocols(left, right) {
        const leftTimestamp = Number(conversationProtocolTimestamp(left) || 0);
        const rightTimestamp = Number(conversationProtocolTimestamp(right) || 0);
        if (leftTimestamp !== rightTimestamp) return rightTimestamp - leftTimestamp;
        return conversationProtocolLabel(left).localeCompare(conversationProtocolLabel(right));
    }

    function conversationProtocolOptions(protocols, queryText = '') {
        const query = String(queryText || '').trim();
        const matching = (protocols || [])
            .filter((item) => conversationProtocolSearchMatches(item, query))
            .sort(compareConversationProtocols);
        if (query) {
            return { protocols: matching, hiddenCount: 0, collapsedCount: 0 };
        }

        const byFamily = new Map();
        let collapsedCount = 0;
        matching.forEach((item) => {
            const familyKey = conversationProtocolFamilyKey(item);
            const existing = byFamily.get(familyKey);
            if (!existing) {
                byFamily.set(familyKey, item);
                return;
            }
            collapsedCount += 1;
            if (compareConversationProtocols(item, existing) < 0) {
                byFamily.set(familyKey, item);
            }
        });
        return {
            protocols: [...byFamily.values()].sort(compareConversationProtocols),
            hiddenCount: collapsedCount,
            collapsedCount,
        };
    }

    function protocolRunInputFieldsFromDefinitionJson(definitionJson) {
        const rawDocument = definitionJson && typeof definitionJson === 'object'
            ? definitionJson
            : {};
        const document = rawDocument.root && typeof rawDocument.root === 'object'
            ? rawDocument.root
            : rawDocument;
        const metadata = document.metadata && typeof document.metadata === 'object'
            ? document.metadata
            : {};
        const fields = metadata.run_inputs;
        return Array.isArray(fields) && fields.length
            ? fields
                .filter((field) => field && typeof field === 'object')
                .map((field) => ({ ...field }))
            : [];
    }

    function conversationProtocolLaunchFields(protocolId) {
        const key = String(protocolId || '').trim();
        const fields = key ? protocolLaunchFieldsByProtocolId[key] : null;
        return Array.isArray(fields) && fields.length
            ? fields.map((field) => ({ ...field }))
            : null;
    }

    async function ensureConversationProtocolLaunchFields(protocol) {
        const protocolId = String(protocol?.id || protocol?.protocol_id || '').trim();
        const versionId = String(protocol?.versionId || protocol?.current_version_id || '').trim();
        if (!protocolId || !versionId) return;
        if (Object.prototype.hasOwnProperty.call(protocolLaunchFieldsByProtocolId, protocolId)) return;
        if (protocolLaunchFieldLoads.has(protocolId)) return;
        protocolLaunchFieldLoads.add(protocolId);
        try {
            const version = await API.getProtocolVersion(protocolId, versionId);
            protocolLaunchFieldsByProtocolId = {
                ...protocolLaunchFieldsByProtocolId,
                [protocolId]: protocolRunInputFieldsFromDefinitionJson(version?.definition_json),
            };
        } catch (err) {
            protocolLaunchFieldsByProtocolId = {
                ...protocolLaunchFieldsByProtocolId,
                [protocolId]: [],
            };
            UI.reportError('Failed to load protocol run inputs', err, { context: 'Conversation protocol launch inputs failed' });
        } finally {
            protocolLaunchFieldLoads.delete(protocolId);
            renderProtocolsPanel();
        }
    }

    function renderProtocolsPanel() {
        const agentId = managementAgentId();
        syncManagementControls();
        if (!agentId) {
            UI.clearMemoizedRender(protocolsPanel);
            UI.reconcileChildren(protocolsPanel, []);
            return;
        }

        const protocolOptions = conversationProtocolOptions(availableConversationProtocols || [], protocolSearchQuery);
        const filteredProtocols = protocolOptions.protocols;
        if (selectedProtocolId && !filteredProtocols.some((item) => String(item.protocol_id || '') === selectedProtocolId)) {
            if (!protocolSearchQuery) {
                selectedProtocolId = filteredProtocols[0] ? String(filteredProtocols[0].protocol_id || '') : '';
            }
        } else if (!selectedProtocolId && filteredProtocols[0]) {
            selectedProtocolId = String(filteredProtocols[0].protocol_id || '');
        }

        UI.memoizedRender(protocolsPanel, {
            supported: managementSupport.protocols,
            statusMessage: String(protocolsStatusMessage || ''),
            search: String(protocolSearchQuery || ''),
            selectedProtocolId: String(selectedProtocolId || ''),
            problemStatement: String(protocolProblemStatement || ''),
            workspaceRef: protocolWorkspaceRef(),
            hiddenProtocolCount: Number(protocolOptions.hiddenCount || 0),
            availableProtocols: filteredProtocols.map((item) => ({
                id: String(item.protocol_id || ''),
                label: conversationProtocolLabel(item),
                rawLabel: String(item.display_name || item.slug || item.protocol_id || ''),
                slug: String(item.slug || ''),
                versionId: String(item.current_version_id || ''),
                generated: Boolean(conversationProtocolTimestamp(item)),
                timestamp: conversationProtocolTimestamp(item),
                launchFields: conversationProtocolLaunchFields(item.protocol_id),
            })),
            linkedRuns: (linkedProtocolRuns || []).map((run) => ({
                id: String(run.protocol_run_id || ''),
                protocolId: String(run.protocol_id || ''),
                status: String(run.status || ''),
                stage: String(run.current_stage_key || ''),
                updatedLabel: UI.relativeTime(run.updated_at || run.created_at),
            })),
        }, (state) => {
            const nodes = [];
            const header = createManagementHeader('Conversation protocols');
            nodes.push(header);

            if (!state.supported) {
                nodes.push(UI.renderEmptyState('Protocol launch is not available from this conversation.', true));
                return nodes;
            }

            if (state.statusMessage) {
                const status = document.createElement('div');
                status.className = 'conversation-management-status';
                status.textContent = state.statusMessage;
                nodes.push(status);
            }

            const explainer = document.createElement('p');
            explainer.className = 'quiet-note';
            explainer.textContent = 'Start a durable published workflow from this conversation. The run stays linked to this activity thread while using the current bot and project context.';
            nodes.push(explainer);

            const contextBox = document.createElement('div');
            contextBox.className = 'conversation-management-section';
            const contextTitle = document.createElement('div');
            contextTitle.className = 'detail-label';
            contextTitle.textContent = 'Launch context';
            contextBox.appendChild(contextTitle);
            const contextList = document.createElement('div');
            contextList.className = 'conversation-skill-list';
            const agentRow = document.createElement('div');
            agentRow.className = 'settings-row';
            agentRow.innerHTML = `<div class="settings-row-main"><strong class="settings-row-label">Entry agent</strong><span class="settings-row-sublabel">${UI.esc(UI.visibleLabel(meta?.target_display_name, agentId, 'Agent'))}</span></div>`;
            contextList.appendChild(agentRow);
            const projectRow = document.createElement('div');
            projectRow.className = 'settings-row';
            projectRow.innerHTML = `<div class="settings-row-main"><strong class="settings-row-label">Workspace</strong><span class="settings-row-sublabel">${UI.esc(state.workspaceRef || 'No project selected for this conversation')}</span></div>`;
            contextList.appendChild(projectRow);
            contextBox.appendChild(contextList);
            nodes.push(contextBox);

            const launchSection = document.createElement('div');
            launchSection.className = 'conversation-management-section';
            const launchTitle = document.createElement('div');
            launchTitle.className = 'detail-label';
            launchTitle.textContent = 'Start a published protocol';
            launchSection.appendChild(launchTitle);

            if (!state.availableProtocols.length) {
                const emptyMessage = state.search
                    ? 'No published protocols match this search.'
                    : 'No published protocols are available to launch.';
                launchSection.appendChild(UI.renderEmptyState(emptyMessage, true));
                nodes.push(launchSection);
                return nodes;
            }

            const form = document.createElement('div');
            form.className = 'conversation-management-form';
            const search = document.createElement('input');
            search.type = 'search';
            search.className = 'input';
            search.placeholder = 'Search published protocols';
            search.setAttribute('aria-label', 'Search published protocols');
            search.value = state.search;
            search.addEventListener('input', () => {
                protocolSearchQuery = String(search.value || '');
                renderProtocolsPanel();
            });
            form.appendChild(search);

            if (state.hiddenProtocolCount && !state.search) {
                const hiddenNote = document.createElement('p');
                hiddenNote.className = 'quiet-note';
                hiddenNote.textContent = `Showing the latest version of each generated protocol family. ${state.hiddenProtocolCount} older generated versions are hidden; search to inspect them.`;
                form.appendChild(hiddenNote);
            }

            const select = document.createElement('select');
            select.className = 'input';
            select.setAttribute('aria-label', 'Published protocol');
            state.availableProtocols.forEach((item) => {
                const option = document.createElement('option');
                option.value = item.id;
                const suffix = state.search && item.timestamp ? ` · generated ${item.timestamp}` : '';
                const showIdentifier = state.search || !item.generated;
                option.textContent = showIdentifier && item.slug ? `${item.label}${suffix} · ${item.slug}` : `${item.label}${suffix}`;
                if (item.id === state.selectedProtocolId) {
                    option.selected = true;
                }
                select.appendChild(option);
            });
            select.addEventListener('change', () => {
                selectedProtocolId = String(select.value || '').trim();
                renderProtocolsPanel();
            });
            form.appendChild(select);

            const selectedProtocol = state.availableProtocols.find((item) => item.id === state.selectedProtocolId) || state.availableProtocols[0] || null;
            if (selectedProtocol) {
                ensureConversationProtocolLaunchFields(selectedProtocol);
                const scope = document.createElement('div');
                scope.className = 'settings-row';
                let rawScope = '';
                if (selectedProtocol.generated) {
                    rawScope = `Generated protocol family${state.search && selectedProtocol.timestamp ? ` ${selectedProtocol.timestamp}` : ''}. `;
                } else if (selectedProtocol.rawLabel && selectedProtocol.rawLabel !== selectedProtocol.label) {
                    rawScope = `Published as ${selectedProtocol.rawLabel}. `;
                }
                scope.innerHTML = `<div class="settings-row-main"><strong class="settings-row-label">Protocol scope</strong><span class="settings-row-sublabel">${UI.esc(rawScope)}This run uses the protocol's published stage instructions and artifact paths. Write a problem statement that fits this workflow; it will not rewrite the workflow schema at launch time.</span></div>`;
                form.appendChild(scope);
            }

            const launchForm = Kit.protocolRunLaunchForm({
                values: {
                    problem_statement: state.problemStatement,
                    ...(protocolLaunchContext || {}),
                },
                fields: selectedProtocol?.launchFields || null,
                includeWorkspace: false,
                onInput: (key, value) => {
                    const text = String(value || '');
                    if (key === 'problem_statement') {
                        protocolProblemStatement = text;
                        return;
                    }
                    protocolLaunchContext = {
                        ...(protocolLaunchContext || {}),
                        [key]: text,
                    };
                },
            });
            form.appendChild(launchForm.element);

            const actions = document.createElement('div');
            actions.className = 'event-card-actions';
            const start = document.createElement('button');
            start.className = 'btn btn-sm btn-primary';
            start.type = 'button';
            start.textContent = 'Start protocol';
            start.addEventListener('click', async () => {
                const protocolId = String(select.value || selectedProtocolId || '').trim();
                const launchValues = launchForm.readValues();
                const problemStatement = String(launchValues.problem_statement || '').trim();
                if (!protocolId || !problemStatement) {
                    protocolsStatusMessage = 'Select a published protocol and describe the problem to solve.';
                    renderProtocolsPanel();
                    scheduleManagementIdleClose(12000);
                    return;
                }
                start.disabled = true;
                try {
                    const constraints = {};
                    Object.keys(launchValues).forEach((key) => {
                        if (['problem_statement', 'workspace_ref'].includes(key)) return;
                        const text = String(launchValues[key] || '').trim();
                        if (text) constraints[key] = text;
                    });
                    const response = await runManagementRequest(() => API.createProtocolRun({
                        protocol_id: protocolId,
                        entry_agent_id: agentId,
                        root_conversation_id: convoId,
                        origin_channel: String((meta && meta.origin_channel) || 'registry'),
                        workspace_ref: protocolWorkspaceRef(),
                        problem_statement: problemStatement,
                        constraints_json: constraints,
                    }));
                    const run = response.run || null;
                    const launched = state.availableProtocols.find((item) => item.id === protocolId);
                    protocolsStatusMessage = launched
                        ? `Started ${launched.label}.`
                        : 'Protocol run started.';
                    protocolProblemStatement = '';
                    if (run && String(run.protocol_run_id || '').trim()) {
                        linkedProtocolRuns = [
                            run,
                            ...(linkedProtocolRuns || []).filter((item) => String(item.protocol_run_id || '') !== String(run.protocol_run_id || '')),
                        ];
                        bindLinkedRunSubscriptions();
                        showProgressBanner(`Started protocol run ${String(run.protocol_run_id || '').slice(0, 8)}.`);
                    }
                    renderMetaCard(meta || {});
                    renderProtocolsPanel();
                    scheduleConversationManagementRefresh();
                    scheduleManagementSuccessClose();
                } catch (err) {
                    UI.reportError('Failed to start the protocol', err, { context: 'Conversation protocol launch failed' });
                }
                start.disabled = false;
            });
            actions.appendChild(start);
            form.appendChild(actions);
            launchSection.appendChild(form);
            nodes.push(launchSection);

            const linkedRunsSection = document.createElement('div');
            linkedRunsSection.className = 'conversation-management-section';
            const linkedTitle = document.createElement('div');
            linkedTitle.className = 'detail-label';
            linkedTitle.textContent = 'Recent linked runs';
            linkedRunsSection.appendChild(linkedTitle);
            if (!state.linkedRuns.length) {
                linkedRunsSection.appendChild(UI.renderEmptyState('No protocol runs have been started from this conversation yet.', true));
            } else {
                const list = document.createElement('div');
                list.className = 'conversation-skill-list';
                const visibleRuns = state.linkedRuns.slice(0, 3);
                visibleRuns.forEach((run) => {
                    const row = document.createElement('div');
                    row.className = 'settings-row';
                    row.innerHTML = `<div class="settings-row-main"><strong class="settings-row-label">${UI.esc(protocolDisplayName(run.protocolId))}</strong><span class="settings-row-sublabel">${UI.esc([protocolRunSummary({ current_stage_key: run.stage, status: run.status }), run.updatedLabel].filter(Boolean).join(' • ') || `run ${run.id.slice(0, 8)}`)}</span></div>`;
                    const main = row.querySelector('.settings-row-main');
                    if (main && run.stage) {
                        main.appendChild(Kit.runStageProgressRail({
                            stages: [{ stage_key: run.stage, display_name: run.stage }],
                            currentStageKey: run.stage,
                            runStatus: run.status,
                            compact: true,
                        }));
                    }
                    const actions = document.createElement('div');
                    actions.className = 'event-card-actions';
                    const openRun = document.createElement('a');
                    openRun.className = 'btn btn-sm';
                    openRun.href = protocolRunHref(run.id);
                    openRun.textContent = 'Open run';
                    actions.appendChild(openRun);
                    row.appendChild(actions);
                    list.appendChild(row);
                });
                linkedRunsSection.appendChild(list);
                if (state.linkedRuns.length > visibleRuns.length) {
                    const overflow = document.createElement('p');
                    overflow.className = 'quiet-note';
                    overflow.textContent = `Showing latest ${visibleRuns.length} of ${state.linkedRuns.length} linked runs. Use the Runs page or conversation activity to inspect older runs.`;
                    linkedRunsSection.appendChild(overflow);
                }
            }
            nodes.push(linkedRunsSection);

            return nodes;
        }, {
            signatureFn(state) {
                return state;
            },
        });
    }

    async function loadConversationSkills({ soft = false } = {}) {
        const agentId = managementAgentId();
        if (!agentId) {
            conversationSkills = null;
            availableConversationSkills = [];
            resetManagementView();
            return;
        }
        try {
            const [skillState, catalogData] = await Promise.all([
                API.getConversationSkills(agentId, managementConversationPath()),
                API.listSkills(agentId),
            ]);
            conversationSkills = skillState;
            availableConversationSkills = catalogData.skills || catalogData || [];
            managementSupport.skills = true;
            syncPendingSetupFromState(skillState);
            if (meta) {
                renderMetaCard(meta);
            }
            renderSkillsPanel();
            if (requestedActivationSkill) {
                void handleRequestedSkillActivation();
            }
        } catch (err) {
            if (isSkillUnavailableError(err)) {
                managementSupport.skills = false;
                conversationSkills = null;
                availableConversationSkills = [];
                pendingSkillSetup = null;
                renderSkillsPanel();
                return;
            }
            if (soft && conversationSkills) {
                UI.reportError('Failed to refresh conversation skills', err, { context: 'Conversation skill refresh failed' });
                return;
            }
            UI.clearMemoizedRender(skillsPanel);
            UI.reconcileChildren(skillsPanel, [UI.createErrorCard('Failed to load conversation skills: ' + err.message, loadConversationSkills)]);
        }
    }

    async function loadConversationSettings({ soft = false } = {}) {
        const agentId = managementAgentId();
        if (!agentId) {
            conversationSettings = null;
            resetManagementView();
            return;
        }
        try {
            conversationSettings = await API.getConversationSettings(agentId, managementConversationPath());
            managementSupport.settings = true;
            renderSettingsPanel();
        } catch (err) {
            if (isSkillUnavailableError(err)) {
                managementSupport.settings = false;
                conversationSettings = null;
                renderSettingsPanel();
                return;
            }
            if (soft && conversationSettings) {
                UI.reportError('Failed to refresh conversation settings', err, { context: 'Conversation settings refresh failed' });
                return;
            }
            UI.clearMemoizedRender(settingsPanel);
            UI.reconcileChildren(settingsPanel, [UI.createErrorCard('Failed to load conversation settings: ' + err.message, loadConversationSettings)]);
        }
    }

    async function loadConversationProtocols({ soft = false } = {}) {
        const agentId = managementAgentId();
        if (!agentId) {
            availableConversationProtocols = [];
            linkedProtocolRuns = [];
            managementSupport.protocols = true;
            renderProtocolsPanel();
            return;
        }
        try {
            const conversationData = meta || await API.getConversation(convoId);
            const [protocolData, runData] = await Promise.all([
                API.listProtocols({ lifecycle_state: 'published', limit: 100 }),
                API.listConversationProtocolRuns(convoId, conversationData, { limit: 25 }),
            ]);
            availableConversationProtocols = (protocolData.protocols || protocolData || []).filter((item) =>
                String(item.lifecycle_state || '') === 'published'
                && String(item.current_version_id || '').trim(),
            );
            linkedProtocolRuns = runData || [];
            bindLinkedRunSubscriptions();
            managementSupport.protocols = true;
            conversationProtocolsLoaded = true;
            renderProtocolsPanel();
            if (meta) {
                renderMetaCard(meta);
            }
        } catch (err) {
            if (soft && (availableConversationProtocols.length || linkedProtocolRuns.length)) {
                UI.reportError('Failed to refresh conversation protocols', err, { context: 'Conversation protocols refresh failed' });
                return;
            }
            UI.clearMemoizedRender(protocolsPanel);
            UI.reconcileChildren(protocolsPanel, [UI.createErrorCard('Failed to load conversation protocols: ' + err.message, loadConversationProtocols)]);
        }
    }

    async function loadConversationLinkedRuns({ soft = false } = {}) {
        try {
            const conversationData = meta || await API.getConversation(convoId);
            linkedProtocolRuns = await API.listConversationProtocolRuns(convoId, conversationData, { limit: 25 });
            bindLinkedRunSubscriptions();
            if (meta) renderMetaCard(meta);
            if (managementMode === 'protocols') {
                renderProtocolsPanel();
            }
        } catch (err) {
            if (!soft) {
                UI.reportError('Failed to load linked protocol runs', err, {
                    context: 'Conversation linked protocol runs failed',
                });
            }
        }
    }

    function scheduleConversationManagementRefresh() {
        if (UI.isBackgrounded()) return;
        clearTimeout(managementReloadDebounce);
        managementReloadDebounce = setTimeout(() => {
            void loadConversationSkills({ soft: true });
            void loadConversationSettings({ soft: true });
            void loadConversationProtocols({ soft: true });
            void loadConversation();
        }, 350);
    }

    function bindLinkedRunSubscriptions() {
        if (conversationDisposed) {
            clearLinkedRunSubscriptions();
            return;
        }
        const nextIds = new Set(
            (linkedProtocolRuns || [])
                .map((run) => String(run?.protocol_run_id || '').trim())
                .filter(Boolean),
        );
        Array.from(linkedRunSubscriptions.keys()).forEach((runId) => {
            if (nextIds.has(runId)) return;
            const unsubscribe = linkedRunSubscriptions.get(runId);
            if (typeof unsubscribe === 'function') unsubscribe();
            linkedRunSubscriptions.delete(runId);
        });
        nextIds.forEach((runId) => {
            if (linkedRunSubscriptions.has(runId)) return;
            const unsubscribe = WS.subscribe(`protocol-run:${runId}`, () => {
                scheduleLinkedRunsRefresh();
            });
            linkedRunSubscriptions.set(runId, unsubscribe);
        });
    }

    function clearLinkedRunSubscriptions() {
        linkedRunSubscriptions.forEach((unsubscribe) => {
            if (typeof unsubscribe === 'function') unsubscribe();
        });
        linkedRunSubscriptions.clear();
    }

    function scheduleLinkedRunsRefresh() {
        if (conversationDisposed || UI.isBackgrounded()) return;
        clearTimeout(linkedRunsReloadDebounce);
        linkedRunsReloadDebounce = setTimeout(() => {
            void loadConversationLinkedRuns({ soft: true });
            if (activeView === 'tasks') {
                void loadRelatedTasks({ soft: true, silent: true });
            }
        }, 350);
    }

    function clearProgressBanner() {
        progressBanner.hidden = true;
        progressBanner.textContent = '';
        clearTimeout(progressTimer);
    }

    function showProgressBanner(text) {
        if (!text) return;
        progressBanner.hidden = false;
        progressBanner.textContent = text;
        clearTimeout(progressTimer);
        progressTimer = setTimeout(clearProgressBanner, 15000);
    }

    function updateTimelineHeader() {
        filterControl.setActive(activeView);
        const labelledBy = activeView === 'tasks' ? tasksBtn.id : activeView === 'activity' ? messagesBtn.id : allBtn.id;
        timelinePanel.setAttribute('aria-labelledby', labelledBy);
        timelinePanel.dataset.view = activeView;
        timeline.hidden = activeView === 'tasks';
        taskView.hidden = activeView !== 'tasks';
        syncConversationDensityForCurrentView();
    }

    function defaultConversationView() {
        if (activeViewExplicit) return '';
        const conversationType = String(meta?.conversation_type || '').trim();
        if (conversationType === 'task_thread') {
            return 'tasks';
        }
        if (Number(meta?.event_count || 0) > 0 && latestConversationMessageCount === 0) {
            return 'activity';
        }
        return '';
    }

    function setActiveView(nextView, { explicit = false, persist = false, load = true } = {}) {
        const normalized = nextView === 'tasks' || nextView === 'activity' ? nextView : 'conversation';
        if (explicit) {
            activeViewExplicit = true;
        }
        const changed = activeView !== normalized;
        activeView = normalized;
        updateTimelineHeader();
        if (persist) {
            _writeConversationViewParam(activeView);
        }
        if (!load) {
            return changed;
        }
        if (activeView === 'tasks') {
            void loadRelatedTasks({ soft: true });
        } else {
            void reloadEvents();
        }
        return changed;
    }

    function maybeAdoptOperationalView({ load = true } = {}) {
        const nextView = defaultConversationView();
        if (!nextView || nextView === activeView) {
            return false;
        }
        setActiveView(nextView, { load });
        return true;
    }

    function applyFilter(nextView) {
        setActiveView(nextView, {
            explicit: true,
            persist: true,
        });
    }

    updateTimelineHeader();

    exportBtn.addEventListener('click', async () => {
        exportBtn.disabled = true;
        try {
            const text = await API.exportConversation(convoId);
            const blob = new Blob([text], { type: 'text/markdown' });
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            const fileBase = UI.safeFilename(meta && meta.title ? meta.title : `conversation-${convoId}`);
            link.download = `${fileBase}.md`;
            link.click();
            URL.revokeObjectURL(url);
        } catch (err) {
            UI.reportError('Failed to export conversation', err, { context: 'Conversation export failed' });
        }
        exportBtn.disabled = false;
    });

    cancelBtn.addEventListener('click', () => {
        UI.showConfirm('Cancel Conversation', 'Cancel further work on this conversation?', async () => {
            cancelBtn.disabled = true;
            try {
                await API.conversationAction(convoId, 'cancel_conversation');
            } catch (err) {
                UI.reportError('Failed to cancel the conversation', err, { context: 'Conversation cancel failed' });
            }
            cancelBtn.disabled = false;
        });
    });

    skillsManageBtn.addEventListener('click', () => {
        if (managementMode === 'skills') {
            closeManagement();
            return;
        }
        openManagement('skills', { focus: true });
    });

    settingsManageBtn.addEventListener('click', () => {
        if (managementMode === 'settings') {
            closeManagement();
            return;
        }
        openManagement('settings', { focus: true });
    });

    protocolsManageBtn.addEventListener('click', () => {
        if (managementMode === 'protocols') {
            closeManagement();
            return;
        }
        openManagement('protocols', { focus: true });
    });

    managementPanel.addEventListener('pointerdown', markManagementInteraction);
    managementPanel.addEventListener('input', markManagementInteraction);
    managementPanel.addEventListener('change', markManagementInteraction);
    managementPanel.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            event.preventDefault();
            closeManagement();
            return;
        }
        markManagementInteraction();
    });

    textarea.addEventListener('keydown', handleComposerKeydown);

    sendBtn.addEventListener('click', sendMessage);
    textarea.addEventListener('input', updateComposerAssist);

    async function sendMessage() {
        const text = textarea.value.trim();
        if (!text) return;
        const routingState = currentComposerRoutingState();
        if (activeView !== 'conversation') {
            setActiveView('conversation', {
                explicit: true,
                persist: true,
            });
        }
        sendBtn.disabled = true;
        textarea.disabled = true;
        clearSuggestions();
        suggestionList.hidden = true;
        try {
            if (routingState.exactSuggestionMatch && routingState.instructions) {
                await API.conversationAction(convoId, 'direct_assign', {
                    selector: directAssignSelector(routingState.exactSuggestionMatch),
                    title: directAssignTitle(routingState.instructions),
                    instructions: routingState.instructions,
                    message_text: routingState.text,
                });
                void loadRelatedTasks({ soft: true });
            } else {
                await API.sendMessage(convoId, text);
            }
            textarea.value = '';
            updateComposerAssist();
            await reloadEvents();
        } catch (err) {
            UI.reportError('Failed to send the message', err, { context: 'Conversation send failed' });
        }
        sendBtn.disabled = false;
        textarea.disabled = false;
        textarea.focus();
    }

    function currentComposerRoutingState() {
        const text = textarea.value.trim();
        const selectorToken = _leadingConversationTargetToken(text);
        return {
            text,
            selectorToken,
            selectorPrefix: selectorToken.startsWith('@'),
            exactSuggestionMatch: selectorMatchesAvailableTarget(selectorToken),
            instructions: selectorToken && text.startsWith(selectorToken)
                ? text.slice(selectorToken.length).trim()
                : '',
        };
    }

    function directAssignSelector(target) {
        const kind = String(target?.kind || 'agent').trim() || 'agent';
        const label = String(target?.label || '').trim().replace(/^@/, '');
        let value = label;
        if (kind === 'skill' && value.toLowerCase().startsWith('skill:')) {
            value = value.slice(6);
        } else if (kind === 'role' && value.toLowerCase().startsWith('role:')) {
            value = value.slice(5);
        }
        const selector = {
            kind,
            value: String(value || target?.key || '').trim(),
        };
        if (kind === 'agent' && target?.key) {
            selector.preferred_agent_id = String(target.key);
        }
        return selector;
    }

    function directAssignTitle(instructions) {
        const normalized = String(instructions || '').trim().replace(/\s+/g, ' ');
        if (!normalized) return 'Direct assignment';
        return normalized.length > 72 ? `${normalized.slice(0, 69)}...` : normalized;
    }

    function handleComposerKeydown(e) {
        const routingState = currentComposerRoutingState();
        if (e.key === 'Enter' && !e.shiftKey && routingState.exactSuggestionMatch && routingState.instructions) {
            e.preventDefault();
            sendMessage();
            return;
        }
        if (!suggestionList.hidden && suggestionMatches.length) {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                setSuggestionIndex((suggestionIndex + 1 + suggestionMatches.length) % suggestionMatches.length);
                return;
            }
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                setSuggestionIndex((suggestionIndex - 1 + suggestionMatches.length) % suggestionMatches.length);
                return;
            }
            if ((e.key === 'Enter' && !e.shiftKey) || e.key === 'Tab') {
                e.preventDefault();
                const chosen = suggestionMatches[suggestionIndex >= 0 ? suggestionIndex : 0];
                if (chosen) {
                    applyTargetSuggestion(chosen.label);
                }
                return;
            }
            if (e.key === 'Escape') {
                e.preventDefault();
                clearSuggestions();
                return;
            }
        }
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    }

    function applyTargetSuggestion(label) {
        textarea.value = _replaceLeadingConversationSelector(textarea.value, label);
        clearSuggestions();
        textarea.focus();
        updateComposerAssist();
    }

    function setComposeHint(text = '') {
        const normalized = String(text || '').trim();
        composeHint.hidden = !normalized;
        composeHint.textContent = normalized;
    }

    function selectorMatchesAvailableTarget(selectorToken) {
        const token = String(selectorToken || '').trim().toLowerCase();
        if (!token) return null;
        return availableTargets.find((item) => {
            if (String(item.label || '').trim().toLowerCase() === token) return true;
            return Array.isArray(item.aliases)
                && item.aliases.some((alias) => String(alias || '').trim().toLowerCase() === token);
        }) || null;
    }

    function clearSuggestions() {
        suggestionMatches = [];
        suggestionIndex = -1;
        suggestionList.textContent = '';
        suggestionList.hidden = true;
    }

    function setSuggestionIndex(nextIndex) {
        suggestionIndex = nextIndex;
        Array.from(suggestionList.children).forEach((child, index) => {
            const active = index === suggestionIndex;
            child.classList.toggle('active', active);
            child.setAttribute('aria-selected', String(active));
        });
    }

    function updateComposerAssist() {
        const {
            selectorToken,
            selectorPrefix,
            exactSuggestionMatch,
            instructions,
        } = currentComposerRoutingState();
        if (exactSuggestionMatch) {
            targetPreview.hidden = false;
            targetPreview.textContent = `Routing directly to ${exactSuggestionMatch.label}.`;
            setComposeHint(
                instructions
                    ? 'Direct assignment will create a routed task immediately.'
                    : 'Add instructions after the selector to route work directly.'
            );
            textarea.placeholder = 'Describe the delegated task';
            sendBtn.textContent = instructions ? 'Assign' : 'Send';
            sendBtn.setAttribute('aria-label', instructions ? 'Assign task' : 'Send message');
            renderTargetSuggestions(selectorToken);
            return;
        }
        if (selectorPrefix) {
            targetPreview.hidden = true;
            setComposeHint('Choose an agent, skill, or role from the suggestions to route work directly.');
            textarea.placeholder = 'Choose a target or keep typing';
            sendBtn.textContent = 'Send';
            sendBtn.setAttribute('aria-label', 'Send message');
            renderTargetSuggestions(selectorToken);
            if (!suggestionMatches.length) {
                setComposeHint('No connected agent, skill, or role matches that selector yet.');
            }
            return;
        }
        targetPreview.hidden = true;
        setComposeHint('');
        textarea.placeholder = 'Reply in this conversation';
        sendBtn.textContent = 'Send';
        sendBtn.setAttribute('aria-label', 'Send message');
        renderTargetSuggestions('');
        suggestionList.hidden = true;
    }

    function renderTargetSuggestions(token) {
        const normalizedToken = String(token || '').trim().toLowerCase();
        const query = normalizedToken.replace(/^@/, '');
        latestSuggestionToken = normalizedToken;
        clearSuggestions();
        if (!normalizedToken || !normalizedToken.startsWith('@')) {
            return;
        }
        if (suggestionEngine) {
            suggestionMatches = query
                ? suggestionEngine.search(query).map((match) => match.item).slice(0, 6)
                : availableTargets.slice(0, 6);
        } else {
            suggestionMatches = query
                ? availableTargets
                    .filter((item) => {
                        const haystack = [
                            item.label,
                            ...(Array.isArray(item.aliases) ? item.aliases : []),
                            item.display,
                            item.detail,
                        ].join(' ').toLowerCase();
                        return haystack.includes(normalizedToken) || haystack.includes(query);
                    })
                    .slice(0, 6)
                : availableTargets.slice(0, 6);
        }
        if (!suggestionMatches.length) {
            return;
        }
        suggestionMatches.forEach((item, index) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'compose-suggestion';
            button.setAttribute('role', 'option');
            button.setAttribute('aria-selected', 'false');
            button.innerHTML = `<strong>${UI.esc(item.label)}</strong><span>${UI.esc(item.display)}</span>${item.detail ? `<em>${UI.esc(item.detail)}</em>` : ''}`;
            button.addEventListener('click', () => {
                applyTargetSuggestion(item.label);
            });
            suggestionList.appendChild(button);
            if (index === 0) {
                suggestionIndex = 0;
            }
        });
        setSuggestionIndex(suggestionIndex >= 0 ? suggestionIndex : 0);
        suggestionList.setAttribute('role', 'listbox');
        suggestionList.hidden = false;
    }

    function currentKindFilter() {
        return activeView === 'conversation' ? conversationLoadKinds.join(',') : undefined;
    }

    function shouldRenderConversationEvent(event) {
        return ['message.user', 'message.bot', 'approval.requested', 'error'].includes(event.kind || '');
    }

    function visibleTimelineEvents(events) {
        if (activeView === 'activity') return events;
        if (activeView === 'conversation') {
            return events.filter(shouldRenderConversationEvent);
        }
        return [];
    }

    function eventRenderKey(event) {
        return String(event?.event_id || event?.seq || `${event?.kind || 'event'}:${event?.created_at || ''}`);
    }

    function isTerminalTaskEvent(event) {
        if (String(event?.kind || '') !== 'task.status') return false;
        const status = String(event?.metadata?.status || '').trim().toLowerCase();
        return ['completed', 'failed', 'cancelled', 'timed_out'].includes(status);
    }

    function eventShouldOpenByDefault(event) {
        const kind = String(event?.kind || '');
        if (kind === 'approval.requested' || kind === 'error') return true;
        if (isTerminalTaskEvent(event)) return Boolean(String(event?.content || '').trim());
        return false;
    }

    function activityExpansionState(events = []) {
        const expandedEventIds = new Set();
        if (activeView !== 'activity') return { expandedEventIds };

        const latestTerminalByTask = new Map();
        (Array.isArray(events) ? events : []).forEach((event) => {
            const key = eventRenderKey(event);
            if (!key) return;
            if (eventShouldOpenByDefault(event)) {
                expandedEventIds.add(key);
            }
            if (isTerminalTaskEvent(event) && String(event?.content || '').trim()) {
                const taskId = String(event?.metadata?.routed_task_id || '').trim();
                if (taskId) latestTerminalByTask.set(taskId, key);
            }
        });
        latestTerminalByTask.forEach((key) => expandedEventIds.add(key));

        if (!expandedEventIds.size) {
            const lastUsefulEvent = [...(Array.isArray(events) ? events : [])]
                .reverse()
                .find((event) => !['provider.request', 'provider.response'].includes(String(event?.kind || '')));
            const fallbackEvent = lastUsefulEvent || events[events.length - 1];
            if (fallbackEvent) {
                expandedEventIds.add(eventRenderKey(fallbackEvent));
            }
        }
        return { expandedEventIds };
    }

    function renderEventElement(event, options = {}) {
        return _createConversationEventElement(event, convoId, relatedTasks, {
            view: activeView,
            ...options,
        });
    }

    function protocolDisplayName(protocolId = '') {
        const target = String(protocolId || '').trim();
        if (!target) return 'Protocol run';
        const match = (availableConversationProtocols || []).find(
            (item) => String(item.protocol_id || '').trim() === target,
        );
        return conversationProtocolLabel(match || { display_name: target }) || target;
    }

    function protocolRunSummary(run) {
        const currentStage = String(run?.current_stage_key || '').trim();
        const status = String(run?.status || '').trim();
        return [currentStage, status].filter(Boolean).join(' · ');
    }

    function renderMetaCard(data) {
        meta = data;
        const conversationWith = UI.visibleLabel(data.target_display_name, data.target_agent_id);
        const assignedTo = _conversationAssignedTargetLabel(relatedTasks, conversationWith);
        UI.memoizedRender(metaCard, {
            title: String(data.title || convoId),
            status: String(data.status || 'open'),
            eventCount: Number(data.event_count || 0),
            externalRef: String(data.external_conversation_ref || ''),
            target: String(conversationWith || ''),
            assignedTo: String(assignedTo || ''),
            origin: String(data.origin_channel || 'registry'),
            type: String(data.conversation_type || 'conversation'),
            updatedLabel: data.updated_at ? UI.relativeTime(data.updated_at) : '',
            activeSkills: activeConversationSkillDetails()
                .map((item) => String(item?.name || '').trim())
                .filter(Boolean),
            linkedRuns: (linkedProtocolRuns || []).map((run) => ({
                id: String(run.protocol_run_id || ''),
                protocolLabel: protocolDisplayName(run.protocol_id),
                summary: protocolRunSummary(run),
            })),
            managementMode,
        }, () => {
        const title = data.title || convoId;
        const isTaskThread = String(data.conversation_type || 'conversation') === 'task_thread';
        const titleRow = document.createElement('div');
        titleRow.className = 'workspace-header-main';
        titleRow.dataset.key = 'meta-title-row';

        const info = document.createElement('div');
        info.className = 'workspace-title-group';

        const titleEl = document.createElement('h2');
        titleEl.className = 'conversation-meta-title';
        titleEl.textContent = title;
        info.appendChild(titleEl);

        titleRow.appendChild(info);
        titleRow.appendChild(actionGroup);

        const metaRow = document.createElement('div');
        metaRow.className = 'conversation-meta-row';
        metaRow.dataset.key = 'meta-inline';

        const statements = document.createElement('div');
        statements.className = 'meta-inline meta-inline-quiet';

        const metaParts = [];
        if (isTaskThread && conversationWith) {
            metaParts.push(`Operational task thread for ${conversationWith}`);
        } else if (isTaskThread) {
            metaParts.push('Operational task thread');
        } else if (conversationWith) {
            metaParts.push(`With ${conversationWith}`);
        }
        if (assignedTo) {
            metaParts.push(`Assigned to ${assignedTo}`);
        }
        const originLabel = _originChannelLabel(data.origin_channel || 'registry');
        if (originLabel) {
            metaParts.push(`Started in ${originLabel}`);
        }
        if (data.updated_at) {
            metaParts.push(`Updated ${UI.relativeTime(data.updated_at)}`);
        }

        metaParts.forEach((value, index) => {
            const item = document.createElement('span');
            item.className = 'meta-inline-item meta-inline-statement';
            item.textContent = value;
            statements.appendChild(item);
            if (index < metaParts.length - 1) {
                const sep = document.createElement('span');
                sep.className = 'meta-inline-separator';
                sep.textContent = '·';
                statements.appendChild(sep);
            }
        });

        metaRow.appendChild(statements);

        const actions = document.createElement('div');
        actions.className = 'meta-inline-actions';

        const status = document.createElement('span');
        status.className = `badge badge-${data.status || 'open'}`;
        status.textContent = _formatConversationStatusLabel(data.status || 'open');
        actions.appendChild(status);

        if (data.event_count !== undefined) {
            const activityBtn = document.createElement('button');
            activityBtn.type = 'button';
            activityBtn.className = 'meta-inline-action';
            activityBtn.textContent = `Activity (${String(data.event_count)})`;
            activityBtn.addEventListener('click', () => applyFilter('activity'));
            actions.appendChild(activityBtn);
        }
        if (data.external_conversation_ref) {
            const copyRefBtn = document.createElement('button');
            copyRefBtn.type = 'button';
            copyRefBtn.className = 'meta-inline-action meta-inline-action-mono';
            copyRefBtn.textContent = 'Copy ref';
            copyRefBtn.title = data.external_conversation_ref;
            copyRefBtn.addEventListener('click', async () => {
                const ref = String(data.external_conversation_ref || '').trim();
                if (!ref) return;
                try {
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        await navigator.clipboard.writeText(ref);
                        copyRefBtn.textContent = 'Copied';
                        setTimeout(() => {
                            copyRefBtn.textContent = 'Copy ref';
                        }, 1600);
                    }
                } catch {
                    copyRefBtn.textContent = ref;
                    setTimeout(() => {
                        copyRefBtn.textContent = 'Copy ref';
                    }, 2400);
                }
            });
            actions.appendChild(copyRefBtn);
        }

        if (actions.childElementCount) {
            metaRow.appendChild(actions);
        }
        if (managementMode !== 'closed') {
            return [titleRow, metaRow, toolbar];
        }

        const activeSkills = activeConversationSkillDetails();
        if (!activeSkills.length) {
            if (!(linkedProtocolRuns || []).length) {
                return [titleRow, metaRow, toolbar];
            }
        } else {
            const activeRow = document.createElement('div');
            activeRow.className = 'conversation-meta-row';
            activeRow.dataset.key = 'active-skills-inline';
            const label = document.createElement('span');
            label.className = 'detail-label';
                label.textContent = activeSkills.length === 1 ? 'Active skill' : 'Active skills';
            activeRow.appendChild(label);
            const chips = document.createElement('div');
            chips.className = 'chip-row';
            activeSkills.forEach((skill) => {
                const chip = document.createElement('span');
                chip.className = 'quickstart-chip static';
                chip.textContent = UI.visibleLabel(skill.display_name, skill.name, 'Skill');
                chips.appendChild(chip);
            });
            activeRow.appendChild(chips);
            const semantics = activeSkillSemanticsNote(activeSkills);
            if (semantics) {
                const note = document.createElement('p');
                note.className = 'quiet-note';
                note.textContent = semantics;
                activeRow.appendChild(note);
            }
            if (!(linkedProtocolRuns || []).length) {
                return [titleRow, metaRow, activeRow, toolbar];
            }
            const runsRow = document.createElement('div');
            runsRow.className = 'conversation-meta-row';
            runsRow.dataset.key = 'protocol-runs-inline';
            const runsLabel = document.createElement('span');
            runsLabel.className = 'detail-label';
            runsLabel.textContent = linkedProtocolRuns.length === 1 ? 'Linked run' : 'Linked runs';
            runsRow.appendChild(runsLabel);
            const runChips = document.createElement('div');
            runChips.className = 'chip-row';
            linkedProtocolRuns.slice(0, 3).forEach((run) => {
                const runLink = document.createElement('a');
                runLink.className = 'quickstart-chip static';
                runLink.href = protocolRunHref(run.protocol_run_id);
                runLink.textContent = `${protocolDisplayName(run.protocol_id)} · ${String(run.status || '').trim() || 'queued'}`;
                runChips.appendChild(runLink);
            });
            if (linkedProtocolRuns.length > 3) {
                const more = document.createElement('span');
                more.className = 'quickstart-chip static';
                more.textContent = `+${linkedProtocolRuns.length - 3} more`;
                runChips.appendChild(more);
            }
            runsRow.appendChild(runChips);
            return [titleRow, metaRow, activeRow, runsRow, toolbar];
        }
        const runsRow = document.createElement('div');
        runsRow.className = 'conversation-meta-row';
        runsRow.dataset.key = 'protocol-runs-inline';
        const runsLabel = document.createElement('span');
        runsLabel.className = 'detail-label';
        runsLabel.textContent = linkedProtocolRuns.length === 1 ? 'Linked run' : 'Linked runs';
        runsRow.appendChild(runsLabel);
        const runChips = document.createElement('div');
        runChips.className = 'chip-row';
        linkedProtocolRuns.slice(0, 3).forEach((run) => {
            const runLink = document.createElement('a');
            runLink.className = 'quickstart-chip static';
            runLink.href = protocolRunHref(run.protocol_run_id);
            runLink.textContent = `${protocolDisplayName(run.protocol_id)} · ${String(run.status || '').trim() || 'queued'}`;
            runChips.appendChild(runLink);
        });
        if (linkedProtocolRuns.length > 3) {
            const more = document.createElement('span');
            more.className = 'quickstart-chip static';
            more.textContent = `+${linkedProtocolRuns.length - 3} more`;
            runChips.appendChild(more);
        }
        runsRow.appendChild(runChips);
        return [titleRow, metaRow, runsRow, toolbar];
        });
    }

    function renderTaskSummaryStrip(tasks) {
        const counts = {
            total: tasks.length,
            running: tasks.filter((task) => task.status === 'running').length,
            queued: tasks.filter((task) => ['queued', 'submitted', 'leased'].includes(task.status || '')).length,
            attention: tasks.filter((task) => ['failed', 'cancelled', 'timed_out'].includes(task.status || '')).length,
            done: tasks.filter((task) => task.status === 'completed').length,
        };
        if (!tasks.length) {
            UI.clearMemoizedRender(taskSummaryStrip);
            UI.reconcileChildren(taskSummaryStrip, []);
            return;
        }
        UI.memoizedRender(taskSummaryStrip, counts, () => [
            ['Total', counts.total],
            ['Queued', counts.queued],
            ['Running', counts.running],
            ['Needs follow-up', counts.attention],
            ['Done', counts.done],
        ].map(([label, value]) => {
            const chip = document.createElement('div');
            chip.className = 'task-summary-chip';
            chip.dataset.key = String(label).toLowerCase().replace(/\s+/g, '-');
            chip.innerHTML = `<strong>${UI.esc(String(value))}</strong><span>${UI.esc(label)}</span>`;
            return chip;
        }));
    }

    function renderRelatedTasks(tasks) {
        const nextSignature = (tasks || []).map((task) => ({
            id: String(task.routed_task_id || ''),
            status: String(task.status || ''),
            updatedLabel: UI.relativeTime(task.updated_at || task.created_at),
            title: String(task.title || ''),
            summary: String(task.summary || task.result_summary || task.result_text || task.instructions || ''),
            target: String(task.target_display_name || task.target_agent_id || ''),
        }));
        renderTaskSummaryStrip(tasks);
        if (!tasks.length) {
            UI.clearMemoizedRender(taskBoard);
            UI.reconcileChildren(taskBoard, [UI.renderEmptyState('No delegated work yet.', true)]);
            delete taskBoard.dataset.laneCount;
            return;
        }
        const lanes = [
            ['queued', 'Queued', ['queued', 'submitted', 'leased']],
            ['running', 'Running', ['running']],
            ['attention', 'Needs follow-up', ['failed', 'cancelled', 'timed_out']],
            ['done', 'Done', ['completed']],
        ];
        UI.memoizedRender(taskBoard, nextSignature, () => {
        const laneNodes = lanes.flatMap(([key, title, statuses]) => {
            const laneTasks = tasks.filter((task) => statuses.includes(task.status || ''));
            if (!laneTasks.length) return [];
            const lane = document.createElement('section');
            lane.className = 'task-lane';
            lane.dataset.key = key;
            lane.dataset.lane = key;

            const laneHeader = document.createElement('div');
            laneHeader.className = 'task-lane-header';
            const titleEl = document.createElement('strong');
            titleEl.textContent = title;
            laneHeader.appendChild(titleEl);
            const countEl = document.createElement('span');
            countEl.textContent = String(laneTasks.length);
            laneHeader.appendChild(countEl);
            lane.appendChild(laneHeader);

            const laneBody = document.createElement('div');
            laneBody.className = 'task-lane-body';
            lane.appendChild(laneBody);
            UI.reconcileChildren(laneBody, laneTasks.map((task) => _createConversationTaskCard(task, convoId)));
            return [lane];
        });
        taskBoard.dataset.laneCount = String(laneNodes.length);
        return laneNodes;
        }, {
            signatureFn(value) {
                return value;
            },
        });
    }

    async function loadRelatedTasks({ soft = false, silent = false } = {}) {
        try {
            const conversationData = meta || await API.getConversation(convoId);
            const taskId = API.routedTaskIdFromConversation(conversationData);
            if (taskId) {
                const task = await API.getTask(taskId);
                relatedTasks = task ? [task] : [];
            } else {
                const data = await API.listTasks({
                    parent_conversation_id: convoId,
                    limit: 100,
                    include_generated: '1',
                });
                relatedTasks = data.tasks || data || [];
            }
            tasksLoaded = true;
            if (meta) renderMetaCard(meta);
            if (!activeViewExplicit && activeView !== 'tasks' && maybeAdoptOperationalView({ load: false })) {
                if (activeView === 'tasks') {
                    renderRelatedTasks(relatedTasks);
                }
                return;
            }
            if (activeView === 'tasks') {
                renderRelatedTasks(relatedTasks);
            }
        } catch (err) {
            if (activeView === 'tasks' && !silent) {
                UI.clearMemoizedRender(taskBoard);
                UI.reconcileChildren(taskBoard, [UI.createErrorCard('Failed to load conversation tasks: ' + err.message, loadRelatedTasks)]);
            }
        }
    }

    function scheduleRelatedTasksRefresh() {
        if (UI.isBackgrounded()) return;
        clearTimeout(relatedTasksReloadDebounce);
        relatedTasksReloadDebounce = setTimeout(() => {
            void loadRelatedTasks({ soft: true, silent: true });
        }, 350);
    }

    function clearTimelineForLoad() {
        beforeSeq = 0;
        latestSeq = 0;
        hasMoreBefore = false;
        loadingOlder = false;
        historyStatus.textContent = '';
    }

    function updateHistoryStatus() {
        if (loadingOlder) {
            historyStatus.textContent = 'Loading older activity…';
            return;
        }
        historyStatus.textContent = hasMoreBefore ? 'Scroll up to load older activity' : '';
    }

    function updateSequenceState(events) {
        if (!events.length) return;
        const seqs = events.map((item) => Number(item.seq || 0)).filter((value) => value > 0);
        if (!seqs.length) return;
        beforeSeq = beforeSeq ? Math.min(beforeSeq, seqs[0]) : seqs[0];
        latestSeq = Math.max(latestSeq, seqs[seqs.length - 1]);
    }

    async function loadConversation() {
        try {
            const data = await API.getConversation(convoId);
            renderMetaCard(data);
            maybeAdoptOperationalView();
            syncManagementControls();
            if (requestedActivationSkill && requestedManagementMode === 'closed') {
                openManagement('skills');
            } else if (
                requestedManagementMode === 'skills'
                || requestedManagementMode === 'settings'
                || requestedManagementMode === 'protocols'
            ) {
                openManagement(requestedManagementMode);
            }
            void loadConversationSkills({ soft: true });
            void loadConversationSettings({ soft: true });
            if (requestedManagementMode !== 'protocols') {
                void loadConversationLinkedRuns({ soft: true });
            }
        } catch (err) {
            UI.reconcileChildren(metaCard, [UI.createErrorCard('Failed to load conversation metadata', loadConversation)]);
        }
    }

    async function reloadEvents() {
        const requestToken = eventLoadRequestToken + 1;
        eventLoadRequestToken = requestToken;
        const requestView = activeView;
        if (topObserver) {
            topObserver.disconnect();
            topObserver = null;
        }
        clearTimelineForLoad();
        clearProgressBanner();
        try {
            const result = await API.getEvents(convoId, {
                limit: UI.EVENT_PAGE_LIMIT,
                kind: currentKindFilter(),
            });
            if (requestToken !== eventLoadRequestToken || requestView !== activeView) {
                return;
            }
            const events = result.events || [];
            latestConversationMessageCount = events.filter(shouldRenderConversationEvent).length;
            if (!activeViewExplicit && maybeAdoptOperationalView()) {
                return;
            }
            const visibleEvents = visibleTimelineEvents(events);
            hasMoreBefore = !!result.has_more_before;
            beforeSeq = Number(result.next_before_seq || (events[0] && events[0].seq) || 0);
            latestSeq = Number(result.next_after_seq || (events[events.length - 1] && events[events.length - 1].seq) || 0);
            if (!visibleEvents.length) {
                UI.reconcileChildren(eventList, [UI.renderEmptyState(
                    activeView === 'conversation'
                        ? 'No messages yet.'
                        : activeView === 'activity'
                            ? 'No activity yet.'
                            : 'No events yet.',
                    true,
                )]);
                syncConversationDensityForCurrentView();
            } else {
                const expansionState = activityExpansionState(visibleEvents);
                UI.reconcileChildren(eventList, visibleEvents.map((event) => renderEventElement(event, expansionState)));
                requestAnimationFrame(() => {
                    timeline.scrollTop = timeline.scrollHeight;
                });
                syncConversationDensityForCurrentView();
            }
            updateHistoryStatus();
            initHistoryObserver();
        } catch (err) {
            UI.reconcileChildren(eventList, [UI.createErrorCard('Failed to load events: ' + err.message, reloadEvents)]);
            syncConversationDensityForCurrentView();
        }
    }

    async function loadOlderEvents() {
        if (loadingOlder || !hasMoreBefore || !beforeSeq) return;
        loadingOlder = true;
        updateHistoryStatus();
        const anchor = eventList.firstElementChild;
        const previousTop = anchor ? anchor.getBoundingClientRect().top : timeline.scrollTop;
        const requestToken = eventLoadRequestToken;
        const requestView = activeView;
        try {
            const result = await API.getEvents(convoId, {
                before_seq: beforeSeq,
                limit: UI.EVENT_PAGE_LIMIT,
                kind: currentKindFilter(),
            });
            if (requestToken !== eventLoadRequestToken || requestView !== activeView) {
                return;
            }
            const events = result.events || [];
            const visibleEvents = visibleTimelineEvents(events);
            if (!events.length) {
                hasMoreBefore = false;
                updateHistoryStatus();
                return;
            }
            if (visibleEvents.length) {
                const empty = eventList.querySelector('.empty-state');
                if (empty) empty.remove();
                const fragment = document.createDocumentFragment();
                visibleEvents.forEach((event) => {
                    fragment.appendChild(renderEventElement(event));
                });
                eventList.prepend(fragment);
            }
            hasMoreBefore = !!result.has_more_before;
            beforeSeq = Number(result.next_before_seq || (events[0] && events[0].seq) || beforeSeq);
            updateSequenceState(events);
            requestAnimationFrame(() => {
                if (anchor && anchor.isConnected) {
                    const nextTop = anchor.getBoundingClientRect().top;
                    timeline.scrollTop += nextTop - previousTop;
                }
            });
        } catch (err) {
            UI.reportError('Failed to load older activity', err, { context: 'Conversation load older failed' });
        } finally {
            loadingOlder = false;
            updateHistoryStatus();
        }
    }

    function initHistoryObserver() {
        if (topObserver) topObserver.disconnect();
        if (typeof IntersectionObserver === 'undefined') return;
        topObserver = new IntersectionObserver((entries) => {
            const entry = entries[0];
            if (entry && entry.isIntersecting) {
                loadOlderEvents();
            }
        }, {
            root: timeline,
            rootMargin: '120px 0px 0px 0px',
            threshold: 0,
        });
        topObserver.observe(sentinel);
        cleanups.add(() => topObserver && topObserver.disconnect());
    }

    function isNearBottom() {
        return timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 96;
    }

    const unsub = WS.subscribe(`conversation:${convoId}`, (msg) => {
        if (UI.isBackgrounded()) return;
        if (msg.type === 'invalidate') {
            const invalidation = msg.data || {};
            if (!invalidation.conversation_id || String(invalidation.conversation_id) === String(convoId)) {
                scheduleConversationManagementRefresh();
                scheduleLinkedRunsRefresh();
                if (activeView === 'tasks') {
                    scheduleRelatedTasksRefresh();
                }
            }
            return;
        }
        if (msg.type === 'progress' && msg.data) {
            showProgressBanner(msg.data.content || '');
            liveRegion.textContent = 'Agent progress update';
            return;
        }
        if (msg.type !== 'event' || !msg.data) return;
        const event = msg.data;
        if (['delegation.proposed', 'delegation.submitted', 'delegation.completed', 'task.status'].includes(event.kind || '')) {
            scheduleRelatedTasksRefresh();
            scheduleLinkedRunsRefresh();
        }
        if (activeView === 'tasks') {
            if (meta) {
                meta.event_count = Number(meta.event_count || 0) + 1;
                meta.updated_at = event.created_at || meta.updated_at;
                renderMetaCard(meta);
            }
            return;
        }
        const seq = Number(event.seq || 0);
        if (seq && latestSeq && seq <= latestSeq) return;
        if (meta) {
            meta.event_count = Number(meta.event_count || 0) + 1;
            meta.updated_at = event.created_at || meta.updated_at;
            renderMetaCard(meta);
        }
        if (activeView === 'conversation' && !shouldRenderConversationEvent(event)) {
            if (seq) latestSeq = Math.max(latestSeq, seq);
            return;
        }
        const shouldStick = isNearBottom();
        const empty = eventList.querySelector('.empty-state');
        if (empty) empty.remove();
        eventList.appendChild(renderEventElement(event, {
            defaultExpanded: activeView === 'activity' && eventShouldOpenByDefault(event),
        }));
        syncConversationDensityForCurrentView();
        if (seq) latestSeq = Math.max(latestSeq, seq);
        if (
            event.kind === 'message.user'
            || event.kind === 'message.bot'
            || event.kind === 'approval.requested'
            || event.kind === 'delegation.submitted'
            || event.kind === 'delegation.completed'
            || event.kind === 'task.status'
        ) {
            liveRegion.textContent = `${_eventKindLabel(event.kind)} ${event.actor ? `from ${event.actor}` : ''}`;
        }
        if (
            event.kind === 'message.bot'
            || event.kind === 'error'
            || (event.kind === 'task.status' && ['completed', 'failed', 'cancelled'].includes((event.metadata && event.metadata.status) || ''))
        ) {
            clearProgressBanner();
        }
        if (shouldStick) {
            requestAnimationFrame(() => {
                timeline.scrollTop = timeline.scrollHeight;
            });
        }
    });
    cleanups.add(unsub);

    const initialLoads = [loadConversation(), loadTargetSuggestions()];
    if (activeView === 'tasks') {
        initialLoads.push(loadRelatedTasks());
    } else {
        initialLoads.push(loadRelatedTasks({ soft: true, silent: true }));
        initialLoads.push(reloadEvents());
    }
    cleanups.add(() => clearTimeout(progressTimer));
    cleanups.add(() => clearTimeout(relatedTasksReloadDebounce));
    cleanups.add(() => clearTimeout(managementReloadDebounce));
    cleanups.add(() => clearTimeout(linkedRunsReloadDebounce));
    cleanups.add(() => {
        conversationDisposed = true;
        clearLinkedRunSubscriptions();
    });
    cleanups.add(clearManagementTimers);
    updateComposerAssist();
    syncManagementControls();
    container.__routeReady = Promise.allSettled(initialLoads);

    function syncConversationDensity(compact) {
        page.classList.toggle('conversation-page-compact', Boolean(compact));
        timelinePanel.classList.toggle('conversation-panel-compact', Boolean(compact));
    }

    function syncConversationDensityForCurrentView() {
        const compact = activeView !== 'tasks' && eventList.childElementCount <= 4;
        syncConversationDensity(compact);
    }
}

function _readConversationViewState() {
    try {
        const url = new URL(window.location.href);
        const view = url.searchParams.get('view');
        return {
            value: view === 'tasks' || view === 'activity' ? view : 'conversation',
            explicit: Boolean(view),
        };
    } catch {
        return {
            value: 'conversation',
            explicit: false,
        };
    }
}

function _writeConversationViewParam(activeView) {
    try {
        const url = new URL(window.location.href);
        if (activeView === 'conversation') {
            url.searchParams.delete('view');
        } else {
            url.searchParams.set('view', activeView);
        }
        history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    } catch {
        // Ignore URL update issues; the toggle still works.
    }
}

function _readManagementModeParam() {
    try {
        const url = new URL(window.location.href);
        const value = url.searchParams.get('manage');
        return value === 'skills' || value === 'settings' || value === 'protocols' ? value : 'closed';
    } catch {
        return 'closed';
    }
}

function _readRequestedActivationSkillParam() {
    try {
        const url = new URL(window.location.href);
        return String(url.searchParams.get('activate_skill') || '').trim();
    } catch {
        return '';
    }
}
