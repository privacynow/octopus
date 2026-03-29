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
    let suggestionMatches = [];
    let suggestionIndex = -1;
    let suggestionEngine = null;
    let relatedTasksReloadDebounce = null;

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
            label: 'Tasks',
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
        filterControl.setActive(activeView);
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
            updatedLabel: data.updated_at ? UI.relativeTime(data.updated_at) : '',
        }, () => {
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

        return [titleRow, metaRow, toolbar];
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

    function taskThreadTaskId(data) {
        const conversation = data || meta;
        if (!conversation || String(conversation.conversation_type || 'conversation') !== 'task_thread') {
            return '';
        }
        const externalRef = String(conversation.external_conversation_ref || '').trim();
        if (!externalRef.startsWith('routed-task:')) {
            return '';
        }
        return externalRef.slice('routed-task:'.length).trim();
    }

    async function loadRelatedTasks({ soft = false, silent = false } = {}) {
        try {
            const conversationData = meta || await API.getConversation(convoId);
            const taskId = taskThreadTaskId(conversationData);
            if (taskId) {
                const task = await API.getTask(taskId);
                relatedTasks = task ? [task] : [];
            } else {
                const data = await API.listTasks({
                    parent_conversation_id: convoId,
                    limit: 100,
                });
                relatedTasks = data.tasks || data || [];
            }
            tasksLoaded = true;
            if (meta) renderMetaCard(meta);
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
        if (UI.isBackgrounded()) return;
        if (msg.type === 'progress' && msg.data) {
            showProgressBanner(msg.data.content || '');
            liveRegion.textContent = 'Agent progress update';
            return;
        }
        if (msg.type !== 'event' || !msg.data) return;
        const event = msg.data;
        if (['delegation.proposed', 'delegation.submitted', 'delegation.completed', 'task.status'].includes(event.kind || '')) {
            scheduleRelatedTasksRefresh();
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
    updateComposerAssist();
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
