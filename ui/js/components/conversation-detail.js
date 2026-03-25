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
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
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
    let suggestionMatches = [];
    let suggestionIndex = -1;
    let suggestionEngine = null;

    const page = document.createElement('section');
    page.className = 'conversation-page';
    container.appendChild(page);

    const shell = document.createElement('section');
    shell.className = 'card conversation-shell';
    page.appendChild(shell);

    const metaCard = document.createElement('div');
    metaCard.className = 'conversation-meta';
    shell.appendChild(metaCard);

    const toolbar = document.createElement('div');
    toolbar.className = 'conversation-toolbar conversation-toolbar-shell';
    shell.appendChild(toolbar);

    const filterGroup = document.createElement('div');
    filterGroup.className = 'segmented-control';
    filterGroup.setAttribute('role', 'tablist');
    filterGroup.setAttribute('aria-label', 'Conversation timeline view');
    toolbar.appendChild(filterGroup);

    const allBtn = document.createElement('button');
    allBtn.className = 'segmented-control-btn';
    allBtn.type = 'button';
    allBtn.id = 'conversation-view-tab';
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
    messagesBtn.textContent = 'Full activity';
    messagesBtn.setAttribute('role', 'tab');
    messagesBtn.setAttribute('aria-selected', 'false');
    messagesBtn.setAttribute('aria-controls', 'conversation-timeline-panel');
    messagesBtn.tabIndex = -1;
    filterGroup.appendChild(messagesBtn);

    const actionGroup = document.createElement('div');
    actionGroup.className = 'toolbar-actions';
    toolbar.appendChild(actionGroup);

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
    page.appendChild(layout);

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
    textarea.placeholder = 'Send a message to this conversation';
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
                const key = `${item.kind}:${String(item.label || '').toLowerCase()}`;
                if (seen.has(key)) return;
                seen.add(key);
                availableTargets.push(item);
            }
            agents.forEach((agent) => {
                const slug = (agent.slug || agent.agent_id || '').trim();
                if (!slug) return;
                const detail = [agent.role || '', (agent.capabilities || []).slice(0, 2).join(', ')].filter(Boolean).join(' · ');
                pushTarget({
                    label: '@' + slug,
                    kind: 'agent',
                    display: agent.display_name || slug,
                    detail,
                });
                const displayName = String(agent.display_name || '').trim();
                if (displayName && !/\s/.test(displayName) && displayName.toLowerCase() !== slug.toLowerCase()) {
                    pushTarget({
                        label: '@' + displayName,
                        kind: 'agent',
                        display: displayName,
                        detail,
                    });
                }
            });
            agents.forEach((agent) => {
                const role = String(agent.role || '').trim();
                if (!role) return;
                pushTarget({
                    label: '@role:' + role,
                    kind: 'role',
                    display: role,
                    detail: 'Role target',
                });
            });
            capabilities.forEach((capability) => {
                const value = String(capability.name || capability.capability || capability || '').trim();
                if (!value) return;
                pushTarget({
                    label: '@cap:' + value,
                    kind: 'capability',
                    display: value,
                    detail: 'Capability target',
                });
            });
            if (typeof Fuse === 'function') {
                suggestionEngine = new Fuse(availableTargets, {
                    includeScore: true,
                    threshold: 0.34,
                    ignoreLocation: true,
                    keys: [
                        { name: 'label', weight: 0.45 },
                        { name: 'display', weight: 0.35 },
                        { name: 'detail', weight: 0.20 },
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
        syncConversationDensity(activeView !== 'tasks' && !eventList.childElementCount);
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
    filterGroup.addEventListener('keydown', (e) => {
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
        e.preventDefault();
        const tabs = [allBtn, tasksBtn, messagesBtn];
        const currentIndex = tabs.indexOf(document.activeElement);
        if (currentIndex >= 0) {
            const delta = e.key === 'ArrowRight' ? 1 : -1;
            const target = tabs[(currentIndex + delta + tabs.length) % tabs.length];
            target.focus();
            applyFilter(target === allBtn ? 'conversation' : target === tasksBtn ? 'tasks' : 'activity');
        }
    });
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
        return availableTargets.some((item) => String(item.label || '').trim().toLowerCase() === token);
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
            textarea.placeholder = 'Choose a routing target or keep typing';
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
        textarea.placeholder = 'Send a message to this conversation';
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
        const hero = document.createElement('div');
        hero.className = 'conversation-meta-hero';
        hero.dataset.key = 'meta-hero';

        const info = document.createElement('div');
        info.className = 'conversation-meta-copy';

        const backLink = document.createElement('a');
        backLink.href = '/ui/conversations';
        backLink.className = 'conversation-back-link';
        backLink.textContent = 'All conversations';
        info.appendChild(backLink);

        const titleEl = document.createElement('h2');
        titleEl.className = 'conversation-meta-title';
        titleEl.textContent = title;
        info.appendChild(titleEl);

        const sub = document.createElement('div');
        sub.className = 'conversation-meta-subtitle';
        const parts = [];
        if (data.target_display_name || data.target_agent_id) {
            parts.push(`With ${data.target_display_name || data.target_agent_id}`);
        }
        if (data.origin_channel) parts.push(`Started on ${data.origin_channel}`);
        sub.textContent = parts.join(' \u00b7 ');
        info.appendChild(sub);
        hero.appendChild(info);

        const statusWrap = document.createElement('div');
        statusWrap.className = 'meta-badge-stack';
        const status = document.createElement('span');
        status.className = `badge badge-${data.status || 'open'}`;
        status.textContent = data.status || 'open';
        statusWrap.appendChild(status);

        if (data.updated_at) {
            const updated = document.createElement('span');
            updated.className = 'meta-timestamp';
            updated.setAttribute('data-timestamp', data.updated_at);
            updated.textContent = UI.relativeTime(data.updated_at);
            statusWrap.appendChild(updated);
        }
        hero.appendChild(statusWrap);

        const facts = document.createElement('div');
        facts.className = 'conversation-meta-facts';
        facts.dataset.key = 'meta-facts';
        [
            ['Agent', data.target_display_name || data.target_agent_id || '—'],
            ['Source', data.origin_channel || 'registry'],
            ['Reference', data.external_conversation_ref || '—'],
            ['Events', data.event_count !== undefined ? String(data.event_count) : '—'],
        ].forEach(([label, value]) => {
            const item = document.createElement('div');
            item.className = 'conversation-meta-fact';
            item.innerHTML = `<span>${UI.esc(label)}</span><strong>${UI.esc(value)}</strong>`;
            facts.appendChild(item);
        });

        UI.reconcileChildren(metaCard, [hero, facts]);
    }

    function renderTaskSummaryStrip(tasks) {
        const counts = {
            total: tasks.length,
            running: tasks.filter((task) => task.status === 'running').length,
            queued: tasks.filter((task) => ['queued', 'submitted', 'leased'].includes(task.status || '')).length,
            attention: tasks.filter((task) => ['failed', 'cancelled', 'timed_out'].includes(task.status || '')).length,
            done: tasks.filter((task) => task.status === 'completed').length,
        };
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
        renderTaskSummaryStrip(tasks);
        if (!tasks.length) {
            UI.reconcileChildren(taskBoard, [UI.renderEmptyState('No delegated tasks for this conversation yet.', true)]);
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
            laneHeader.innerHTML = `<strong>${UI.esc(title)}</strong><span>${laneTasks.length}</span>`;
            lane.appendChild(laneHeader);
            const laneBody = document.createElement('div');
            laneBody.className = 'task-lane-body';
            laneTasks.forEach((task) => laneBody.appendChild(_createConversationTaskCard(task, convoId)));
            lane.appendChild(laneBody);
            return [lane];
        });
        taskBoard.dataset.laneCount = String(laneNodes.length);
        UI.reconcileChildren(taskBoard, laneNodes);
    }

    async function loadRelatedTasks({ soft = false } = {}) {
        if (!soft || !tasksLoaded) {
            UI.reconcileChildren(taskBoard, UI.createSkeletonNodes(4, 'card'));
        }
        try {
            const data = await API.listTasks({
                parent_conversation_id: convoId,
                limit: 100,
            });
            relatedTasks = data.tasks || data || [];
            renderRelatedTasks(relatedTasks);
            tasksLoaded = true;
        } catch (err) {
            UI.reconcileChildren(taskBoard, [UI.createErrorCard('Failed to load conversation tasks: ' + err.message, loadRelatedTasks)]);
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
                        ? 'No messages or routed-work milestones yet. Start below.'
                        : activeView === 'activity'
                            ? 'No activity yet.'
                            : 'No events yet.',
                    true,
                )]);
                syncConversationDensity(activeView === 'conversation');
            } else {
                UI.reconcileChildren(eventList, visibleEvents.map((event) => _createConversationEventElement(event, convoId)));
                requestAnimationFrame(() => {
                    timeline.scrollTop = timeline.scrollHeight;
                });
                syncConversationDensity(false);
            }
            updateHistoryStatus();
            initHistoryObserver();
        } catch (err) {
            UI.reconcileChildren(eventList, [UI.createErrorCard('Failed to load events: ' + err.message, reloadEvents)]);
            syncConversationDensity(false);
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
                    fragment.appendChild(_createConversationEventElement(event, convoId));
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
        eventList.appendChild(_createConversationEventElement(event, convoId));
        syncConversationDensity(false);
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
        reloadEvents();
    }
    cleanups.add(() => clearTimeout(progressTimer));
    updateComposerAssist();

    function syncConversationDensity(compact) {
        page.classList.toggle('conversation-page-compact', Boolean(compact));
        timelinePanel.classList.toggle('conversation-panel-compact', Boolean(compact));
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

function _createConversationEventElement(event, convoId) {
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
    title.textContent = _eventKindLabel(kind);
    titleGroup.appendChild(title);
    if (event.actor) {
        const actor = document.createElement('span');
        actor.className = 'event-card-actor';
        actor.textContent = event.actor;
        titleGroup.appendChild(actor);
    }
    header.appendChild(titleGroup);

    const summary = document.createElement('span');
    summary.className = 'event-summary';
    summary.textContent = _eventSummary(kind, event);
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
            _renderDelegationCard(body, metadata);
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

    const startExpanded = kind === 'approval.requested' || kind === 'delegation.submitted';
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

function _renderDelegationCard(body, metadata) {
    const tasks = Array.isArray(metadata.tasks) ? metadata.tasks : [];
    if (!tasks.length) {
        _renderGenericMetadata(body, metadata);
        return;
    }
    const list = document.createElement('ul');
    list.className = 'delegation-list';
    tasks.forEach((task) => {
        const item = document.createElement('li');
        item.innerHTML = `<strong>${UI.esc(task.title || '')}</strong><span>${UI.esc(task.target || '')}</span><em>${UI.esc(task.status || '')}</em>`;
        list.appendChild(item);
    });
    body.appendChild(list);
}

function _renderTaskStatusCard(body, event, metadata, convoId) {
    body.appendChild(_metadataGrid([
        ['Status', metadata.status || ''],
        ['Progress', metadata.progress !== null && metadata.progress !== undefined ? `${metadata.progress}%` : '—'],
    ]));
    if (metadata.progress !== null && metadata.progress !== undefined) {
        const progress = document.createElement('div');
        progress.className = 'progress-track';
        const fill = document.createElement('div');
        fill.className = 'progress-fill';
        fill.style.width = `${Math.max(0, Math.min(100, Number(metadata.progress || 0)))}%`;
        progress.appendChild(fill);
        body.appendChild(progress);
    }
    if (event.content) {
        const content = document.createElement('div');
        content.className = 'event-text-block';
        content.innerHTML = `<strong>Update</strong><p>${UI.esc(event.content)}</p>`;
        body.appendChild(content);
    }
    const taskId = String(metadata.routed_task_id || '').trim();
    const status = String(metadata.status || '').trim();
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
        parts.push(`To ${task.target_display_name || task.target_agent_id}`);
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

function _eventSummary(kind, event) {
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
            const tasks = Array.isArray(metadata.tasks) ? metadata.tasks.length : 0;
            const label = kind.split('.')[1];
            return `${tasks} task${tasks === 1 ? '' : 's'} ${label}`;
        }
        case 'task.status':
            return [
                metadata.status || 'update',
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
