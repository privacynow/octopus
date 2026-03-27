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
    let activeView = _readConversationViewParam();
    let topObserver = null;
    const conversationLoadKinds = [
        'message.user',
        'message.bot',
        'approval.requested',
        'delegation.submitted',
        'delegation.completed',
        'error',
        'task.status',
    ];
    let relatedTasks = [];
    let tasksLoaded = false;
    let lastRelatedTaskSignature = '';
    let suggestionMatches = [];
    let suggestionIndex = -1;
    let suggestionEngine = null;

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

    const filterGroup = document.createElement('div');
    filterGroup.className = 'segmented-control';
    filterGroup.setAttribute('role', 'tablist');
    filterGroup.setAttribute('aria-label', 'Conversation timeline view');
    toolbar.appendChild(filterGroup);

    const allBtn = document.createElement('button');
    allBtn.className = 'segmented-control-btn';
    allBtn.type = 'button';
    allBtn.id = 'conversation-view-tab';
    allBtn.dataset.view = 'conversation';
    allBtn.textContent = 'Conversation';
    allBtn.setAttribute('role', 'tab');
    allBtn.setAttribute('aria-selected', 'true');
    allBtn.setAttribute('aria-controls', 'conversation-timeline-panel');
    allBtn.tabIndex = 0;
    filterGroup.appendChild(allBtn);

    const tasksBtn = document.createElement('button');
    tasksBtn.className = 'segmented-control-btn';
    tasksBtn.type = 'button';
    tasksBtn.id = 'task-view-tab';
    tasksBtn.dataset.view = 'tasks';
    tasksBtn.textContent = 'Tasks';
    tasksBtn.setAttribute('role', 'tab');
    tasksBtn.setAttribute('aria-selected', 'false');
    tasksBtn.setAttribute('aria-controls', 'conversation-timeline-panel');
    tasksBtn.tabIndex = -1;
    filterGroup.appendChild(tasksBtn);

    const messagesBtn = document.createElement('button');
    messagesBtn.className = 'segmented-control-btn';
    messagesBtn.type = 'button';
    messagesBtn.id = 'activity-view-tab';
    messagesBtn.dataset.view = 'activity';
    messagesBtn.textContent = 'Full activity';
    messagesBtn.setAttribute('role', 'tab');
    messagesBtn.setAttribute('aria-selected', 'false');
    messagesBtn.setAttribute('aria-controls', 'conversation-timeline-panel');
    messagesBtn.tabIndex = -1;
    filterGroup.appendChild(messagesBtn);

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
            const [agentData, capabilityData] = await Promise.all([
                API.listAgents({ state: 'connected', limit: 100 }),
                API.listCapabilities().catch(() => []),
            ]);
            const agents = agentData.agents || agentData || [];
            const capabilities = capabilityData.capabilities || capabilityData || [];
            const seen = new Set();
            availableTargets = [];
            function pushTarget(item) {
                const key = `${item.kind}:${String(item.key || item.label || '').toLowerCase()}`;
                if (seen.has(key)) return;
                seen.add(key);
                availableTargets.push(item);
            }
            agents.forEach((agent) => {
                const slug = (agent.slug || agent.agent_id || '').trim();
                if (!slug) return;
                const displayName = String(agent.display_name || '').trim();
                const compactDisplayName = displayName && !/\s/.test(displayName) ? displayName : '';
                const preferredLabel = '@' + (compactDisplayName || slug);
                const aliases = Array.from(new Set([
                    preferredLabel,
                    '@' + slug,
                    compactDisplayName ? '@' + compactDisplayName : '',
                ].filter(Boolean)));
                const detail = [
                    compactDisplayName && compactDisplayName.toLowerCase() !== slug.toLowerCase() ? slug : '',
                    agent.role || '',
                    (agent.capabilities || []).slice(0, 2).join(', '),
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
                if (!role) return;
                pushTarget({
                    key: role,
                    label: '@role:' + role,
                    kind: 'role',
                    display: role,
                    detail: 'Role target',
                    aliases: ['@role:' + role],
                });
            });
            capabilities.forEach((capability) => {
                const value = String(capability.name || capability.capability || capability || '').trim();
                if (!value) return;
                pushTarget({
                    key: value,
                    label: '@cap:' + value,
                    kind: 'capability',
                    display: value,
                    detail: 'Capability target',
                    aliases: ['@cap:' + value],
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
        allBtn.classList.toggle('active', activeView === 'conversation');
        tasksBtn.classList.toggle('active', activeView === 'tasks');
        messagesBtn.classList.toggle('active', activeView === 'activity');
        allBtn.setAttribute('aria-selected', String(activeView === 'conversation'));
        allBtn.tabIndex = activeView === 'conversation' ? 0 : -1;
        tasksBtn.setAttribute('aria-selected', String(activeView === 'tasks'));
        tasksBtn.tabIndex = activeView === 'tasks' ? 0 : -1;
        messagesBtn.setAttribute('aria-selected', String(activeView === 'activity'));
        messagesBtn.tabIndex = activeView === 'activity' ? 0 : -1;
        const labelledBy = activeView === 'tasks' ? tasksBtn.id : activeView === 'activity' ? messagesBtn.id : allBtn.id;
        timelinePanel.setAttribute('aria-labelledby', labelledBy);
        timelinePanel.dataset.view = activeView;
        timeline.hidden = activeView === 'tasks';
        taskView.hidden = activeView !== 'tasks';
        syncConversationDensityForCurrentView();
    }

    function applyFilter(nextView) {
        activeView = nextView;
        updateTimelineHeader();
        _writeConversationViewParam(activeView);
        if (activeView === 'tasks') {
            loadRelatedTasks({ soft: true });
            return;
        }
        reloadEvents();
    }

    allBtn.addEventListener('click', () => applyFilter('conversation'));
    tasksBtn.addEventListener('click', () => applyFilter('tasks'));
    messagesBtn.addEventListener('click', () => applyFilter('activity'));
    UI.bindSegmentedControlKeyboard(filterGroup, (target) => applyFilter(target.dataset.view || 'conversation'));
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

    textarea.addEventListener('keydown', handleComposerKeydown);

    sendBtn.addEventListener('click', sendMessage);
    textarea.addEventListener('input', updateComposerAssist);

    async function sendMessage() {
        const text = textarea.value.trim();
        if (!text) return;
        const directAssignment = _extractConversationTargetSelectorMessage(text);
        const selectorOnly = !directAssignment && _parseConversationTargetSelector(_leadingConversationTargetToken(text));
        sendBtn.disabled = true;
        textarea.disabled = true;
        clearSuggestions();
        suggestionList.hidden = true;
        try {
            if (directAssignment) {
                await API.conversationAction(convoId, 'direct_assign', {
                    selector: directAssignment.selector,
                    title: directAssignment.instructions.slice(0, 120),
                    instructions: directAssignment.instructions,
                    message_text: text,
                });
            } else if (selectorOnly) {
                throw new Error('Add instructions after the target selector to route work directly.');
            } else {
                await API.sendMessage(convoId, text);
            }
            textarea.value = '';
            updateComposerAssist();
        } catch (err) {
            UI.reportError('Failed to send the message', err, { context: 'Conversation send failed' });
        }
        sendBtn.disabled = false;
        textarea.disabled = false;
        textarea.focus();
    }

    function handleComposerKeydown(e) {
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
        if (!token) return false;
        return availableTargets.some((item) => {
            if (String(item.label || '').trim().toLowerCase() === token) return true;
            return Array.isArray(item.aliases)
                && item.aliases.some((alias) => String(alias || '').trim().toLowerCase() === token);
        });
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
        const text = textarea.value.trim();
        const directAssignment = _extractConversationTargetSelectorMessage(text);
        const selectorToken = _leadingConversationTargetToken(text);
        const selector = selectorToken ? _parseConversationTargetSelector(selectorToken) : null;
        const selectorPrefix = selectorToken.startsWith('@');
        const exactSuggestionMatch = selectorMatchesAvailableTarget(selectorToken);
        if (directAssignment) {
            targetPreview.hidden = false;
            targetPreview.textContent = `Routing directly to ${_formatConversationTargetLabel(directAssignment.selector)}.`;
            setComposeHint('Direct assignment will create a routed task immediately.');
            textarea.placeholder = 'Describe the delegated task';
            sendBtn.textContent = 'Assign';
            sendBtn.setAttribute('aria-label', 'Assign task');
            renderTargetSuggestions('');
            return;
        }
        if (selector) {
            targetPreview.hidden = !exactSuggestionMatch;
            if (exactSuggestionMatch) {
                targetPreview.textContent = `Routing directly to ${_formatConversationTargetLabel(selector)}.`;
                setComposeHint('Add instructions after the selector to assign work directly.');
            } else if (selectorToken.startsWith('@')) {
                setComposeHint('Choose an agent, capability, or role from the suggestions to route work directly.');
            }
            textarea.placeholder = 'Describe the delegated task';
            sendBtn.textContent = 'Assign';
            sendBtn.setAttribute('aria-label', 'Assign task');
            renderTargetSuggestions(selectorToken);
            if (!suggestionMatches.length && selectorToken.startsWith('@') && !exactSuggestionMatch) {
                setComposeHint('No connected agent, capability, or role matches that selector yet.');
            }
            return;
        }
        if (selectorPrefix) {
            targetPreview.hidden = true;
            setComposeHint('Choose an agent, capability, or role from the suggestions to route work directly.');
            textarea.placeholder = 'Choose a target or keep typing';
            sendBtn.textContent = 'Send';
            sendBtn.setAttribute('aria-label', 'Send message');
            renderTargetSuggestions(selectorToken);
            if (!suggestionMatches.length) {
                setComposeHint('No connected agent, capability, or role matches that selector yet.');
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
        const kind = event.kind || '';
        if (kind === 'task.status') {
            const status = String((event.metadata && event.metadata.status) || '');
            return ['completed', 'failed', 'cancelled', 'timed_out'].includes(status);
        }
        return ['message.user', 'message.bot', 'approval.requested', 'delegation.submitted', 'delegation.completed', 'error'].includes(kind);
    }

    function visibleTimelineEvents(events) {
        if (activeView === 'activity') return events;
        if (activeView === 'conversation') {
            return events.filter(shouldRenderConversationEvent);
        }
        return [];
    }

    function renderMetaCard(data) {
        meta = data;
        const title = data.title || convoId;
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
        const conversationWith = _visibleOperatorLabel(data.target_display_name, data.target_agent_id);
        const assignedTo = _conversationAssignedTargetLabel(relatedTasks, conversationWith);
        if (conversationWith) {
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

        UI.reconcileChildren(metaCard, [titleRow, metaRow, toolbar]);
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
            UI.reconcileChildren(taskSummaryStrip, []);
            return;
        }
        const chips = [
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
        });
        UI.reconcileChildren(taskSummaryStrip, chips);
    }

    function renderRelatedTasks(tasks) {
        const nextSignature = JSON.stringify((tasks || []).map((task) => ({
            id: String(task.routed_task_id || ''),
            status: String(task.status || ''),
            updatedAt: String(task.updated_at || ''),
            createdAt: String(task.created_at || ''),
            title: String(task.title || ''),
            summary: String(task.summary || task.result_summary || task.result_text || task.instructions || ''),
            target: String(task.target_display_name || task.target_agent_id || ''),
        })));
        renderTaskSummaryStrip(tasks);
        if (!tasks.length) {
            UI.reconcileChildren(taskBoard, [UI.renderEmptyState('No delegated work yet.', true)]);
            delete taskBoard.dataset.laneCount;
            lastRelatedTaskSignature = nextSignature;
            return;
        }
        if (tasksLoaded && nextSignature === lastRelatedTaskSignature) {
            return;
        }
        const lanes = [
            ['queued', 'Queued', ['queued', 'submitted', 'leased']],
            ['running', 'Running', ['running']],
            ['attention', 'Needs follow-up', ['failed', 'cancelled', 'timed_out']],
            ['done', 'Done', ['completed']],
        ];
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
        UI.reconcileChildren(taskBoard, laneNodes);
        lastRelatedTaskSignature = nextSignature;
    }

    async function loadRelatedTasks({ soft = false, silent = false } = {}) {
        if (activeView === 'tasks' && (!soft || !tasksLoaded)) {
            UI.reconcileChildren(taskBoard, UI.createSkeletonNodes(4, 'card'));
        }
        try {
            const data = await API.listTasks({
                parent_conversation_id: convoId,
                limit: 100,
            });
            relatedTasks = data.tasks || data || [];
            tasksLoaded = true;
            if (meta) renderMetaCard(meta);
            if (activeView === 'tasks') {
                renderRelatedTasks(relatedTasks);
            } else if (eventList.childElementCount) {
                reloadEvents();
            }
        } catch (err) {
            if (activeView === 'tasks' && !silent) {
                UI.reconcileChildren(taskBoard, [UI.createErrorCard('Failed to load conversation tasks: ' + err.message, loadRelatedTasks)]);
            }
        }
    }

    function clearTimelineForLoad() {
        beforeSeq = 0;
        latestSeq = 0;
        hasMoreBefore = false;
        loadingOlder = false;
        historyStatus.textContent = '';
        UI.reconcileChildren(eventList, UI.createSkeletonNodes(4, 'card'));
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
        } catch (err) {
            UI.reconcileChildren(metaCard, [UI.createErrorCard('Failed to load conversation metadata', loadConversation)]);
        }
    }

    async function reloadEvents() {
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
            const events = result.events || [];
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
                UI.reconcileChildren(eventList, visibleEvents.map((event) => _createConversationEventElement(event, convoId, relatedTasks)));
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
        try {
            const result = await API.getEvents(convoId, {
                before_seq: beforeSeq,
                limit: UI.EVENT_PAGE_LIMIT,
                kind: currentKindFilter(),
            });
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
                    fragment.appendChild(_createConversationEventElement(event, convoId, relatedTasks));
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
        }
        loadingOlder = false;
        updateHistoryStatus();
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
        if (msg.type === 'progress' && msg.data) {
            showProgressBanner(msg.data.content || '');
            liveRegion.textContent = 'Agent progress update';
            return;
        }
        if (msg.type !== 'event' || !msg.data) return;
        const event = msg.data;
        if (['delegation.proposed', 'delegation.submitted', 'delegation.completed', 'task.status'].includes(event.kind || '')) {
            loadRelatedTasks({ soft: true });
        }
        if (activeView === 'tasks') {
            if (meta) {
                meta.event_count = Number(meta.event_count || 0) + 1;
                meta.updated_at = event.created_at || meta.updated_at;
                renderMetaCard(meta);
            }
            return;
        }
        if (activeView === 'conversation' && !shouldRenderConversationEvent(event)) return;
        const seq = Number(event.seq || 0);
        if (seq && latestSeq && seq <= latestSeq) return;
        const shouldStick = isNearBottom();
        const empty = eventList.querySelector('.empty-state');
        if (empty) empty.remove();
        eventList.appendChild(_createConversationEventElement(event, convoId, relatedTasks));
        syncConversationDensityForCurrentView();
        if (seq) latestSeq = Math.max(latestSeq, seq);
        if (meta) {
            meta.event_count = Number(meta.event_count || 0) + 1;
            meta.updated_at = event.created_at || meta.updated_at;
            renderMetaCard(meta);
        }
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
        if (['delegation.submitted', 'delegation.completed', 'task.status'].includes(event.kind || '')) {
            loadRelatedTasks({ soft: true, silent: true });
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

    loadConversation();
    loadTargetSuggestions();
    if (activeView === 'tasks') {
        loadRelatedTasks();
    } else {
        loadRelatedTasks({ soft: true, silent: true });
        reloadEvents();
    }
    cleanups.add(() => clearTimeout(progressTimer));
    updateComposerAssist();

    function syncConversationDensity(compact) {
        page.classList.toggle('conversation-page-compact', Boolean(compact));
        timelinePanel.classList.toggle('conversation-panel-compact', Boolean(compact));
    }

    function syncConversationDensityForCurrentView() {
        const compact = activeView !== 'tasks' && eventList.childElementCount <= 4;
        syncConversationDensity(compact);
    }
}

function _parseConversationTargetSelector(raw) {
    const text = String(raw || '').trim();
    if (!text.startsWith('@')) return null;
    const body = text.slice(1);
    if (body.startsWith('cap:')) {
        const value = body.slice(4).trim();
        return value ? { kind: 'capability', value } : null;
    }
    if (body.startsWith('role:')) {
        const value = body.slice(5).trim();
        return value ? { kind: 'role', value } : null;
    }
    const value = body.trim();
    if (!value) return null;
    return { kind: 'agent', value };
}

function _leadingConversationTargetToken(raw) {
    const text = String(raw || '').trim();
    if (!text.startsWith('@')) return '';
    const token = text.split(/\s+/, 1)[0] || '';
    return token.trim();
}

function _extractConversationTargetSelectorMessage(raw) {
    const text = String(raw || '').trim();
    const selectorToken = _leadingConversationTargetToken(text);
    if (!selectorToken) return null;
    const selector = _parseConversationTargetSelector(selectorToken);
    if (!selector) return null;
    const instructions = text.slice(selectorToken.length).trim();
    if (!instructions) return null;
    return { selector, instructions };
}

function _replaceLeadingConversationSelector(raw, selectorLabel) {
    const text = String(raw || '').trimStart();
    const token = _leadingConversationTargetToken(text);
    if (!token) return selectorLabel + ' ';
    const remainder = text.slice(token.length).trimStart();
    return selectorLabel + (remainder ? ` ${remainder}` : ' ');
}

function _formatConversationTargetLabel(selector) {
    if (!selector) return '';
    if (selector.kind === 'agent') {
        return '@' + (selector.preferred_agent_id || selector.value);
    }
    return '@' + selector.kind + ':' + selector.value;
}

function _readConversationViewParam() {
    try {
        const url = new URL(window.location.href);
        const view = url.searchParams.get('view');
        return view === 'tasks' || view === 'activity' ? view : 'conversation';
    } catch {
        return 'conversation';
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

function _createConversationEventElement(event, convoId, taskContext = []) {
    const kind = event.kind || '';
    if (kind === 'message.user' || kind === 'message.bot') {
        return _renderMessageBubble(event, kind);
    }

    const card = document.createElement('article');
    card.className = `event-card ${_eventCardClass(kind)}`;
    card.dataset.key = event.event_id || String(event.seq || `${kind}:${event.created_at || ''}`);

    const header = document.createElement('button');
    header.className = 'event-card-header';
    header.type = 'button';

    const titleGroup = document.createElement('div');
    titleGroup.className = 'event-card-heading';
    const title = document.createElement('span');
    title.className = 'kind';
    title.textContent = _eventPrimaryLabel(event);
    titleGroup.appendChild(title);
    const actorLabel = _eventActorLabel(event);
    if (actorLabel) {
        const actor = document.createElement('span');
        actor.className = 'event-card-actor';
        actor.textContent = actorLabel;
        titleGroup.appendChild(actor);
    }
    header.appendChild(titleGroup);

    const summary = document.createElement('span');
    summary.className = 'event-summary';
    summary.textContent = _eventSummary(kind, event, taskContext);
    header.appendChild(summary);

    const time = document.createElement('span');
    time.className = 'event-card-time';
    time.textContent = UI.formatTime(event.created_at);
    header.appendChild(time);
    card.appendChild(header);

    const body = document.createElement('div');
    body.className = 'event-card-body';
    body.id = `event-body-${UI.safeFilename(event.event_id || `${kind}-${event.seq || Date.now()}`)}`;
    header.setAttribute('aria-controls', body.id);
    const metadata = event.metadata || {};

    switch (kind) {
        case 'provider.request':
            _renderProviderRequestCard(body, event, metadata);
            break;
        case 'provider.response':
            _renderProviderResponseCard(body, metadata);
            break;
        case 'tool.execution':
            _renderToolExecutionCard(body, metadata);
            break;
        case 'approval.requested':
            _renderApprovalRequestedCard(body, event, metadata, convoId);
            break;
        case 'approval.decided':
            _renderApprovalDecidedCard(body, metadata);
            break;
        case 'delegation.proposed':
        case 'delegation.submitted':
        case 'delegation.completed':
            _renderDelegationCard(body, kind, metadata, taskContext);
            break;
        case 'task.status':
            _renderTaskStatusCard(body, event, metadata, convoId);
            break;
        case 'error':
            _renderErrorCard(body, event, metadata);
            break;
        default:
            _renderGenericEventCard(body, event);
            break;
    }

    const leadText = _eventLeadText(kind, event, taskContext);
    if (leadText) {
        const lead = document.createElement('div');
        lead.className = 'event-card-lead';
        lead.textContent = leadText;
        card.appendChild(lead);
    }

    const startExpanded = kind === 'approval.requested' || _shouldStartExpanded(kind, event);
    if (_shouldStackSummary(kind, event)) {
        header.classList.add('event-card-header-stacked');
        summary.classList.add('event-summary-stacked');
    }
    body.classList.toggle('expanded', startExpanded);
    header.setAttribute('aria-expanded', String(startExpanded));
    header.addEventListener('click', () => {
        const expanded = body.classList.toggle('expanded');
        header.setAttribute('aria-expanded', String(expanded));
    });

    card.appendChild(body);
    return card;
}

function _renderMessageBubble(event, kind) {
    const bubble = document.createElement('article');
    bubble.className = `chat-bubble ${kind === 'message.user' ? 'user' : 'bot'}`;
    bubble.dataset.key = event.event_id || String(event.seq || `${kind}:${event.created_at || ''}`);

    const actor = document.createElement('div');
    actor.className = 'actor';
    actor.textContent = event.actor || (kind === 'message.user' ? 'Operator' : 'Bot');
    bubble.appendChild(actor);

    const body = document.createElement('div');
    body.className = 'md-content';
    const temp = document.createElement('div');
    temp.innerHTML = UI.renderContent(event.content || '');
    while (temp.firstChild) body.appendChild(temp.firstChild);
    bubble.appendChild(body);

    const attachments = (event.metadata && event.metadata.attachments) || [];
    if (attachments.length) {
        const list = document.createElement('ul');
        list.className = 'attachment-list';
        attachments.forEach((item) => {
            const li = document.createElement('li');
            li.textContent = item;
            list.appendChild(li);
        });
        bubble.appendChild(list);
    }

    const timestamp = document.createElement('div');
    timestamp.className = 'timestamp';
    timestamp.textContent = UI.formatTime(event.created_at);
    bubble.appendChild(timestamp);
    return bubble;
}

function _renderProviderRequestCard(body, event, metadata) {
    body.appendChild(_metadataGrid([
        ['Provider', metadata.provider || ''],
        ['Model', metadata.model || ''],
        ['Mode', metadata.execution_mode || ''],
        ['Working dir', metadata.working_dir || ''],
        ['Files', metadata.file_policy || ''],
        ['Images', String(metadata.image_count || 0)],
        ['Prompt chars', Number(metadata.prompt_char_count || 0).toLocaleString()],
    ]));

    if (event.content) {
        const details = document.createElement('details');
        details.className = 'event-details';
        details.open = false;
        const summary = document.createElement('summary');
        summary.textContent = 'View full prompt';
        details.appendChild(summary);
        const pre = document.createElement('pre');
        pre.className = 'event-pre';
        pre.textContent = event.content;
        details.appendChild(pre);
        body.appendChild(details);
    }
}

function _renderProviderResponseCard(body, metadata) {
    const metrics = document.createElement('div');
    metrics.className = 'inline-metrics';
    metrics.appendChild(_createInlineMetric(Number(metadata.prompt_tokens || 0).toLocaleString(), 'Input'));
    metrics.appendChild(_createInlineMetric(Number(metadata.completion_tokens || 0).toLocaleString(), 'Reply'));
    metrics.appendChild(_createInlineMetric(`$${Number(metadata.cost_usd || 0).toFixed(4)}`, 'Cost'));
    metrics.appendChild(_createInlineMetric(metadata.provider || 'unknown', 'Provider'));
    body.appendChild(metrics);
}

function _renderToolExecutionCard(body, metadata) {
    body.appendChild(_metadataGrid([
        ['Tool', metadata.tool_name || ''],
        ['Status', metadata.status || ''],
        ['Duration', metadata.duration_ms !== null && metadata.duration_ms !== undefined ? `${metadata.duration_ms} ms` : '—'],
        ['Call ID', metadata.call_id || ''],
    ]));

    if (metadata.input_summary) {
        const input = document.createElement('div');
        input.className = 'event-text-block';
        input.innerHTML = `<strong>Input</strong><p>${UI.esc(metadata.input_summary)}</p>`;
        body.appendChild(input);
    }

    if (metadata.output_summary) {
        const output = document.createElement('div');
        output.className = 'event-text-block';
        output.innerHTML = `<strong>Output</strong><p>${UI.esc(metadata.output_summary)}</p>`;
        body.appendChild(output);
    }

    const changes = Array.isArray(metadata.file_changes) ? metadata.file_changes : [];
    if (changes.length) {
        const list = document.createElement('ul');
        list.className = 'change-list';
        changes.forEach((change) => {
            const item = document.createElement('li');
            item.innerHTML = `<strong>${UI.esc(change.change_type || 'changed')}</strong> <code>${UI.esc(change.path || '')}</code><span>${UI.esc(change.summary || '')}</span>`;
            list.appendChild(item);
        });
        body.appendChild(list);
    }
}

function _renderApprovalRequestedCard(body, event, metadata, convoId) {
    body.appendChild(_metadataGrid([
        ['Request', metadata.request_kind || 'approval'],
        ['Requested by', metadata.actor_key || event.actor || 'agent'],
        ['Trust tier', metadata.trust_tier || ''],
        ['Expires', metadata.expires_at ? UI.formatApprovalTime(metadata.expires_at) : 'No deadline'],
    ]));

    if (event.content) {
        const content = document.createElement('div');
        content.className = 'event-text-block';
        content.innerHTML = `<strong>Needs a decision</strong><p>${UI.esc(event.content)}</p>`;
        body.appendChild(content);
    }

    const expired = metadata.expires_at ? new Date(metadata.expires_at) < new Date() : false;
    const actions = document.createElement('div');
    actions.className = 'event-card-actions';

    const approve = document.createElement('button');
    approve.className = 'btn btn-sm btn-primary';
    approve.textContent = 'Approve';
    approve.disabled = expired;

    const reject = document.createElement('button');
    reject.className = 'btn btn-sm btn-danger';
    reject.textContent = 'Reject';
    reject.disabled = expired;

    const status = document.createElement('span');
    status.className = 'action-status';
    if (expired) status.textContent = 'Expired';

    async function act(action) {
        approve.disabled = true;
        reject.disabled = true;
        try {
            await API.conversationAction(convoId, action, { request_id: event.event_id });
            status.textContent = action === 'approve' ? 'Approved' : 'Rejected';
        } catch (err) {
            UI.reportError('Failed to update the approval', err, { context: 'Conversation approval action failed' });
            approve.disabled = expired;
            reject.disabled = expired;
            status.textContent = 'Action failed';
        }
    }

    approve.addEventListener('click', () => act('approve'));
    reject.addEventListener('click', () => act('reject'));

    actions.appendChild(approve);
    actions.appendChild(reject);
    actions.appendChild(status);
    body.appendChild(actions);
}

function _renderApprovalDecidedCard(body, metadata) {
    body.appendChild(_metadataGrid([
        ['Decision', metadata.decision || ''],
        ['Action', metadata.action || ''],
        ['Handled by', metadata.decided_by || ''],
    ]));
}

function _renderDelegationCard(body, kind, metadata, taskContext = []) {
    const tasks = Array.isArray(metadata.tasks) ? metadata.tasks : [];
    if (!tasks.length) {
        _renderGenericMetadata(body, metadata);
        return;
    }
    const list = document.createElement('div');
    list.className = 'delegation-milestone-list';
    tasks.forEach((task) => {
        const item = document.createElement('div');
        item.className = 'delegation-milestone-item';
        const title = document.createElement('strong');
        title.textContent = task.title || 'Delegated task';
        item.appendChild(title);
        const meta = document.createElement('span');
        meta.className = 'delegation-milestone-meta';
        const parts = [];
        const target = _delegationTaskTargetLabel(task, taskContext);
        if (target) {
            parts.push(kind === 'delegation.completed' ? `Handled by ${target}` : `Assigned to ${target}`);
        }
        const status = _taskStatusPhrase(task.status || '');
        if (kind === 'delegation.completed' && status) {
            parts.push(status);
        }
        meta.textContent = parts.join(' · ');
        if (meta.textContent) {
            item.appendChild(meta);
        }
        list.appendChild(item);
    });
    body.appendChild(list);
}

function _renderTaskStatusCard(body, event, metadata, convoId) {
    const status = String(metadata.status || '').trim();
    const terminalWithOutcome = ['completed', 'failed', 'cancelled', 'timed_out'].includes(status) && Boolean(String(event.content || '').trim());
    const progressValue = metadata.progress !== null && metadata.progress !== undefined ? `${metadata.progress}%` : '';
    const facts = [];
    if (progressValue) facts.push(['Progress', progressValue]);
    if (status && !['completed', 'failed', 'cancelled', 'timed_out'].includes(status)) {
        facts.push(['State', _taskStatusPhrase(status)]);
    }
    if (facts.length) {
        body.appendChild(_metadataGrid(facts));
    }
    if (metadata.progress !== null && metadata.progress !== undefined) {
        const progress = document.createElement('div');
        progress.className = 'progress-track';
        const fill = document.createElement('div');
        fill.className = 'progress-fill';
        fill.style.width = `${Math.max(0, Math.min(100, Number(metadata.progress || 0)))}%`;
        progress.appendChild(fill);
        body.appendChild(progress);
    }
    if (event.content && !terminalWithOutcome) {
        const content = document.createElement('div');
        content.className = 'event-text-block';
        content.innerHTML = `<p>${UI.esc(event.content)}</p>`;
        body.appendChild(content);
    }
    const taskId = String(metadata.routed_task_id || '').trim();
    if (taskId && ['queued', 'submitted', 'leased', 'running', 'failed', 'cancelled', 'timed_out'].includes(status)) {
        const actions = document.createElement('div');
        actions.className = 'task-action-row';
        const statusText = document.createElement('span');
        statusText.className = 'task-action-status';
        actions.appendChild(statusText);
        if (['queued', 'submitted', 'leased', 'running'].includes(status)) {
            const cancelBtn = document.createElement('button');
            cancelBtn.type = 'button';
            cancelBtn.className = 'btn btn-sm btn-danger';
            cancelBtn.textContent = 'Cancel task';
            cancelBtn.addEventListener('click', async () => {
                cancelBtn.disabled = true;
                statusText.textContent = 'Cancelling…';
                try {
                    await API.conversationAction(convoId, 'cancel_task', { routed_task_id: taskId });
                    statusText.textContent = 'Cancel requested.';
                } catch (err) {
                    cancelBtn.disabled = false;
                    statusText.textContent = 'Cancel failed.';
                    UI.reportError('Failed to cancel the task', err, { context: 'Task cancel failed' });
                }
            });
            actions.appendChild(cancelBtn);
        }
        if (['failed', 'cancelled', 'timed_out'].includes(status)) {
            const retryBtn = document.createElement('button');
            retryBtn.type = 'button';
            retryBtn.className = 'btn btn-sm';
            retryBtn.textContent = 'Retry task';
            retryBtn.addEventListener('click', async () => {
                retryBtn.disabled = true;
                statusText.textContent = 'Retrying…';
                try {
                    await API.conversationAction(convoId, 'retry_task', { routed_task_id: taskId });
                    statusText.textContent = 'Retry queued.';
                } catch (err) {
                    retryBtn.disabled = false;
                    statusText.textContent = 'Retry failed.';
                    UI.reportError('Failed to retry the task', err, { context: 'Task retry failed' });
                }
            });
            actions.appendChild(retryBtn);
        }
        if (actions.childElementCount > 1) {
            body.appendChild(actions);
        }
    }
}

function _createConversationTaskCard(task, convoId, { compact = false } = {}) {
    const card = document.createElement('article');
    card.className = `conversation-task-card${compact ? ' compact' : ''}`;
    card.dataset.key = `${compact ? 'compact:' : 'full:'}${task.routed_task_id}`;

    const header = document.createElement('div');
    header.className = 'conversation-task-card-header';
    const title = document.createElement('div');
    title.className = 'conversation-task-card-title';
    title.textContent = task.title || task.routed_task_id;
    header.appendChild(title);
    const badge = document.createElement('span');
    badge.className = `badge badge-${task.status || 'queued'}`;
    badge.textContent = task.status || 'queued';
    header.appendChild(badge);
    card.appendChild(header);

    const meta = document.createElement('div');
    meta.className = 'conversation-task-card-meta';
    const parts = [];
    if (task.target_display_name || task.target_agent_id) {
        const targetLabel = _visibleOperatorLabel(task.target_display_name, task.target_agent_id);
        if (targetLabel) {
            parts.push(`To ${targetLabel}`);
        }
    }
    if (task.updated_at || task.created_at) {
        const stamp = document.createElement('span');
        stamp.setAttribute('data-timestamp', task.updated_at || task.created_at || '');
        stamp.textContent = UI.relativeTime(task.updated_at || task.created_at || '');
        const label = document.createElement('span');
        label.textContent = parts.join(' · ');
        if (parts.length) {
            meta.appendChild(label);
            meta.appendChild(stamp);
        } else {
            meta.appendChild(stamp);
        }
    } else if (parts.length) {
        meta.textContent = parts.join(' · ');
    }
    if (meta.childElementCount || meta.textContent) {
        card.appendChild(meta);
    }

    const summary = task.summary
        || task.result_summary
        || task.result_text
        || task.instructions
        || '';
    if (summary) {
        const summaryBlock = document.createElement('p');
        summaryBlock.className = 'conversation-task-card-summary';
        summaryBlock.textContent = compact ? summary.slice(0, 180) : summary;
        card.appendChild(summaryBlock);
    }

    const actions = document.createElement('div');
    actions.className = 'task-action-row';
    const statusText = document.createElement('span');
    statusText.className = 'task-action-status';
    actions.appendChild(statusText);
    if (['queued', 'submitted', 'leased', 'running'].includes(task.status || '')) {
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn btn-sm btn-danger';
        cancelBtn.textContent = 'Cancel task';
        cancelBtn.addEventListener('click', async () => {
            cancelBtn.disabled = true;
            statusText.textContent = 'Cancelling…';
            try {
                await API.conversationAction(convoId, 'cancel_task', { routed_task_id: task.routed_task_id });
                statusText.textContent = 'Cancel requested.';
            } catch (err) {
                cancelBtn.disabled = false;
                statusText.textContent = 'Cancel failed.';
                UI.reportError('Failed to cancel the task', err, { context: 'Task cancel failed' });
            }
        });
        actions.appendChild(cancelBtn);
    }
    if (['failed', 'cancelled', 'timed_out'].includes(task.status || '')) {
        const retryBtn = document.createElement('button');
        retryBtn.type = 'button';
        retryBtn.className = 'btn btn-sm';
        retryBtn.textContent = 'Retry task';
        retryBtn.addEventListener('click', async () => {
            retryBtn.disabled = true;
            statusText.textContent = 'Retrying…';
            try {
                await API.conversationAction(convoId, 'retry_task', { routed_task_id: task.routed_task_id });
                statusText.textContent = 'Retry queued.';
            } catch (err) {
                retryBtn.disabled = false;
                statusText.textContent = 'Retry failed.';
                UI.reportError('Failed to retry the task', err, { context: 'Task retry failed' });
            }
        });
        actions.appendChild(retryBtn);
    }
    if (actions.childElementCount > 1) {
        card.appendChild(actions);
    }

    return card;
}

function _renderErrorCard(body, event, metadata) {
    body.appendChild(_metadataGrid([
        ['Problem type', metadata.error_type || 'execution'],
        ['Message', metadata.message || event.content || ''],
    ]));
    if (event.content && event.content !== metadata.message) {
        const block = document.createElement('div');
        block.className = 'event-text-block';
        block.innerHTML = `<strong>Content</strong><p>${UI.esc(event.content)}</p>`;
        body.appendChild(block);
    }
}

function _renderGenericEventCard(body, event) {
    if (event.content) {
        const content = document.createElement('div');
        content.className = 'event-text-block';
        const temp = document.createElement('div');
        temp.innerHTML = UI.renderContent(event.content);
        while (temp.firstChild) content.appendChild(temp.firstChild);
        body.appendChild(content);
    }
    _renderGenericMetadata(body, event.metadata || {});
}

function _renderGenericMetadata(body, metadata) {
    const meta = JSON.stringify(metadata || {}, null, 2);
    if (!meta || meta === '{}') return;
    const pre = document.createElement('pre');
    pre.className = 'event-pre';
    pre.textContent = meta;
    body.appendChild(pre);
}

function _metadataGrid(entries) {
    const grid = document.createElement('div');
    grid.className = 'metadata-grid';
    entries.forEach(([label, value]) => {
        if (value === '' || value === null || value === undefined) return;
        const item = document.createElement('div');
        item.className = 'metadata-item';
        item.innerHTML = `<span>${UI.esc(label)}</span><strong>${UI.esc(String(value))}</strong>`;
        grid.appendChild(item);
    });
    return grid;
}

function _createInlineMetric(value, label) {
    const metric = document.createElement('div');
    metric.className = 'inline-metric';
    metric.innerHTML = `<strong>${UI.esc(String(value))}</strong><span>${UI.esc(label)}</span>`;
    return metric;
}

function _eventSummary(kind, event, taskContext = []) {
    const metadata = event.metadata || {};
    switch (kind) {
        case 'provider.request':
            return [
                metadata.provider || metadata.model || 'Provider',
                metadata.execution_mode || 'run',
                `${Number(metadata.prompt_char_count || (event.content || '').length || 0).toLocaleString()} chars`,
            ].filter(Boolean).join(' · ');
        case 'provider.response':
            return [
                `${Number((metadata.prompt_tokens || 0) + (metadata.completion_tokens || 0)).toLocaleString()} tokens`,
                `$${Number(metadata.cost_usd || 0).toFixed(4)}`,
            ].join(' · ');
        case 'tool.execution':
            return [
                metadata.tool_name || 'Tool',
                metadata.status || 'completed',
                metadata.duration_ms !== null && metadata.duration_ms !== undefined ? `${metadata.duration_ms} ms` : '',
            ].filter(Boolean).join(' · ');
        case 'delegation.proposed':
        case 'delegation.submitted':
        case 'delegation.completed': {
            const tasks = Array.isArray(metadata.tasks) ? metadata.tasks : [];
            const targets = _uniqueDelegationTargets(tasks, taskContext);
            if (kind === 'delegation.submitted' && targets.length === 1) {
                return `Assigned to ${targets[0]}`;
            }
            if (kind === 'delegation.completed' && targets.length === 1) {
                return `Finished by ${targets[0]}`;
            }
            const taskCount = tasks.length;
            if (taskCount) {
                const label = kind === 'delegation.completed' ? 'finished' : kind === 'delegation.proposed' ? 'proposed' : 'submitted';
                return `${taskCount} task${taskCount === 1 ? '' : 's'} ${label}`;
            }
            return '';
        }
        case 'task.status':
            return [
                _taskStatusPhrase(metadata.status || 'update'),
                metadata.progress !== null && metadata.progress !== undefined ? `${metadata.progress}%` : '',
            ].filter(Boolean).join(' · ');
        case 'error':
            return (metadata.message || event.content || 'Execution problem').split('\n')[0].slice(0, 80);
        case 'approval.decided':
            return `${metadata.decision || 'handled'}${metadata.decided_by ? ` by ${metadata.decided_by}` : ''}`;
        case 'approval.requested':
            return metadata.request_kind || 'Approval needed';
        default:
            return event.actor || '';
    }
}

function _eventKindLabel(kind) {
    const labels = {
        'provider.request': 'Agent started work',
        'provider.response': 'Agent finished work',
        'tool.execution': 'Used a tool',
        'approval.requested': 'Approval needed',
        'approval.decided': 'Approval recorded',
        'delegation.proposed': 'Plan proposed',
        'delegation.submitted': 'Delegated work started',
        'delegation.completed': 'Delegated work finished',
        'task.status': 'Work update',
        'error': 'Problem reported',
        'message.user': 'Operator message',
        'message.bot': 'Agent message',
    };
    return labels[kind] || (kind || 'event').replace(/\./g, ' \u00b7 ');
}

function _eventCardClass(kind) {
    if (kind.startsWith('provider.')) return 'provider';
    if (kind.startsWith('tool.')) return 'tool';
    if (kind.startsWith('approval.')) return 'approval';
    if (kind.startsWith('delegation.')) return 'delegation';
    if (kind === 'task.status') return 'task';
    if (kind === 'error') return 'error';
    return 'generic';
}

function _eventPrimaryLabel(event) {
    const kind = event.kind || '';
    const metadata = event.metadata || {};
    if (kind === 'delegation.submitted') return 'Task submitted';
    if (kind === 'delegation.completed') return 'Delegated work finished';
    if (kind === 'delegation.proposed') return 'Delegation proposed';
    if (kind === 'task.status') {
        const status = String(metadata.status || '').trim();
        if (status === 'completed') return 'Task completed';
        if (['failed', 'cancelled', 'timed_out'].includes(status)) return 'Task needs follow-up';
        if (status === 'running') return 'Task in progress';
        if (['queued', 'submitted', 'leased'].includes(status)) return 'Task queued';
    }
    return _eventKindLabel(kind);
}

function _eventActorLabel(event) {
    const kind = event.kind || '';
    if (['delegation.proposed', 'delegation.submitted', 'delegation.completed', 'task.status'].includes(kind)) {
        return '';
    }
    return event.actor || '';
}

function _isOpaqueIdentifier(value) {
    const text = String(value || '').trim();
    if (!text) return false;
    if (/^[0-9a-f]{24,}$/i.test(text)) return true;
    if (/^[0-9a-f]{8,}-[0-9a-f-]{12,}$/i.test(text)) return true;
    if (text.length >= 24 && !/[A-Z]/.test(text) && /^[a-z0-9._:-]+$/i.test(text)) return true;
    return false;
}

function _visibleOperatorLabel(...candidates) {
    for (const candidate of candidates) {
        const text = String(candidate || '').trim();
        if (!text || _isOpaqueIdentifier(text)) continue;
        return text;
    }
    return '';
}

function _delegationTaskTargetLabel(task, taskContext = []) {
    const routedTaskId = String(task.routed_task_id || '').trim();
    if (routedTaskId) {
        const match = (Array.isArray(taskContext) ? taskContext : []).find((candidate) => String(candidate.routed_task_id || '').trim() === routedTaskId);
        if (match) {
            return _visibleOperatorLabel(
                match.target_display_name
                || match.target
                || match.target_agent_id
                || ''
            );
        }
    }
    const targetAgentId = String(task.target_agent_id || task.target || '').trim();
    if (targetAgentId) {
        const matchByTarget = (Array.isArray(taskContext) ? taskContext : []).find((candidate) => {
            const candidateTarget = String(candidate.target_agent_id || candidate.target || '').trim();
            return candidateTarget && candidateTarget === targetAgentId;
        });
        if (matchByTarget) {
            return _visibleOperatorLabel(
                matchByTarget.target_display_name
                || matchByTarget.target
                || matchByTarget.target_agent_id
                || ''
            );
        }
    }
    return _visibleOperatorLabel(
        task.target_display_name
        || task.target
        || task.target_agent_id
        || task.authority_ref
        || ''
    );
}

function _uniqueDelegationTargets(tasks, taskContext = []) {
    return Array.from(new Set(
        (Array.isArray(tasks) ? tasks : [])
            .map((task) => _delegationTaskTargetLabel(task, taskContext))
            .filter(Boolean)
    ));
}

function _taskStatusPhrase(status) {
    const value = String(status || '').trim().toLowerCase();
    switch (value) {
        case 'queued':
            return 'Queued';
        case 'submitted':
            return 'Submitted';
        case 'leased':
            return 'Leased';
        case 'running':
            return 'Running';
        case 'completed':
            return 'Completed';
        case 'failed':
            return 'Failed';
        case 'cancelled':
            return 'Cancelled';
        case 'timed_out':
            return 'Timed out';
        default:
            return value ? value.charAt(0).toUpperCase() + value.slice(1) : '';
    }
}

function _taskStatusSummary(event) {
    const metadata = event.metadata || {};
    const status = String(metadata.status || '').trim().toLowerCase();
    const content = String(event.content || '').trim().split('\n')[0].trim();
    if (status === 'completed' && content) {
        return content.slice(0, 96);
    }
    return _taskStatusPhrase(status || 'update');
}

function _eventLeadText(kind, event, taskContext = []) {
    const metadata = event.metadata || {};
    if (kind === 'task.status') {
        const status = String(metadata.status || '').trim().toLowerCase();
        const content = String(event.content || '').trim();
        if (content && ['completed', 'failed', 'cancelled', 'timed_out'].includes(status)) {
            return content;
        }
        return '';
    }
    if (kind === 'delegation.submitted' || kind === 'delegation.completed') {
        const tasks = Array.isArray(metadata.tasks) ? metadata.tasks : [];
        if (!tasks.length) return '';
        if (tasks.length === 1) {
            const task = tasks[0];
            const target = _delegationTaskTargetLabel(task, taskContext);
            const title = String(task.title || '').trim();
            if (title && target) {
                return `${kind === 'delegation.completed' ? 'Handled by' : 'Assigned to'} ${target}: ${title}`;
            }
            if (title) return title;
        }
    }
    return '';
}

function _originChannelLabel(originChannel) {
    const value = String(originChannel || '').trim();
    return value || '';
}

function _formatConversationStatusLabel(status) {
    const value = String(status || '').trim().toLowerCase();
    if (!value) return 'Open';
    return value.replace(/_/g, ' ').replace(/\b\w/g, (match) => match.toUpperCase());
}

function _conversationAssignedTargetLabel(tasks, conversationWith) {
    const normalizedWith = String(conversationWith || '').trim().toLowerCase();
    const sorted = (Array.isArray(tasks) ? tasks.slice() : []).sort((left, right) => {
        const leftStamp = Date.parse(String(left.updated_at || left.created_at || '')) || 0;
        const rightStamp = Date.parse(String(right.updated_at || right.created_at || '')) || 0;
        return rightStamp - leftStamp;
    });
    const preferred = sorted.find((task) => ['queued', 'submitted', 'leased', 'running'].includes(String(task.status || '')))
        || sorted[0];
    if (!preferred) return '';
    const label = _delegationTaskTargetLabel(preferred);
    if (!label) return '';
    if (normalizedWith && label.toLowerCase() === normalizedWith) return '';
    return label;
}

function _shouldStartExpanded(kind, event) {
    if (kind !== 'task.status') return false;
    const status = String((event.metadata && event.metadata.status) || '').trim().toLowerCase();
    const hasOutcome = Boolean(String(event.content || '').trim());
    return hasOutcome && ['completed', 'failed', 'cancelled', 'timed_out'].includes(status);
}

function _shouldStackSummary(kind, event) {
    if (kind !== 'task.status') return false;
    const status = String((event.metadata && event.metadata.status) || '').trim().toLowerCase();
    return Boolean(String(event.content || '').trim()) && ['completed', 'failed', 'cancelled', 'timed_out'].includes(status);
}
