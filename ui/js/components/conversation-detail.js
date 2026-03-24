/**
 * Conversation detail — full-height chat and structured event timeline.
 */
function renderConversationDetail(container, params) {
    const convoId = params.id;
    const cleanups = [];
    let meta = null;
    let beforeSeq = 0;
    let latestSeq = 0;
    let hasMoreBefore = false;
    let loadingOlder = false;
    let showConversationView = true;
    let topObserver = null;
    const conversationKinds = [
        'message.user',
        'message.bot',
        'approval.requested',
        'approval.decided',
        'delegation.proposed',
        'delegation.submitted',
        'delegation.completed',
        'task.status',
        'error',
    ];

    const header = document.createElement('div');
    header.className = 'page-header page-header-tight';
    header.innerHTML = `<h2>Conversation</h2><p><a href="/ui/conversations">\u2190 Back to conversations</a></p>`;
    container.appendChild(header);

    const page = document.createElement('section');
    page.className = 'conversation-page';
    container.appendChild(page);

    const metaCard = document.createElement('div');
    metaCard.className = 'card conversation-meta';
    page.appendChild(metaCard);

    const toolbar = document.createElement('div');
    toolbar.className = 'conversation-toolbar';
    page.appendChild(toolbar);

    const filterGroup = document.createElement('div');
    filterGroup.className = 'segmented-control';
    toolbar.appendChild(filterGroup);

    const allBtn = document.createElement('button');
    allBtn.className = 'segmented-control-btn active';
    allBtn.textContent = 'Conversation';
    filterGroup.appendChild(allBtn);

    const messagesBtn = document.createElement('button');
    messagesBtn.className = 'segmented-control-btn';
    messagesBtn.textContent = 'Full activity';
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
    layout.appendChild(timelinePanel);

    const timelineHeader = document.createElement('div');
    timelineHeader.className = 'conversation-panel-header';
    timelineHeader.innerHTML = '<div><strong>Conversation</strong><span>Replies, approvals, and progress updates</span></div>';
    timelinePanel.appendChild(timelineHeader);

    const timeline = document.createElement('div');
    timeline.className = 'chat-timeline';
    timelinePanel.appendChild(timeline);

    const sentinel = document.createElement('div');
    sentinel.className = 'history-sentinel';
    sentinel.textContent = 'Older activity loads as you scroll up';
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

    const textarea = document.createElement('textarea');
    textarea.placeholder = 'Send a message to this conversation';
    textarea.rows = 1;
    composer.appendChild(textarea);

    const sendBtn = document.createElement('button');
    sendBtn.className = 'btn btn-primary';
    sendBtn.textContent = 'Send';
    composer.appendChild(sendBtn);

    function updateTimelineHeader() {
        const label = showConversationView ? 'Conversation' : 'Full activity';
        const subtitle = showConversationView
            ? 'Replies, approvals, and progress updates'
            : 'Every stored event, including provider and tool activity';
        timelineHeader.innerHTML = `<div><strong>${esc(label)}</strong><span>${esc(subtitle)}</span></div>`;
    }

    function applyFilter(nextConversationView) {
        showConversationView = nextConversationView;
        allBtn.classList.toggle('active', showConversationView);
        messagesBtn.classList.toggle('active', !showConversationView);
        updateTimelineHeader();
        reloadEvents();
    }

    allBtn.addEventListener('click', () => applyFilter(true));
    messagesBtn.addEventListener('click', () => applyFilter(false));

    exportBtn.addEventListener('click', async () => {
        exportBtn.disabled = true;
        try {
            const text = await API.exportConversation(convoId);
            const blob = new Blob([text], { type: 'text/markdown' });
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `conversation-${convoId}.md`;
            link.click();
            URL.revokeObjectURL(url);
        } catch (err) {
            console.error('Export failed', err);
        }
        exportBtn.disabled = false;
    });

    cancelBtn.addEventListener('click', () => {
        _showConfirm('Cancel Conversation', 'Cancel further work on this conversation?', async () => {
            cancelBtn.disabled = true;
            try {
                await API.conversationAction(convoId, 'cancel_conversation');
            } catch (err) {
                console.error('Cancel failed', err);
            }
            cancelBtn.disabled = false;
        });
    });

    textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    sendBtn.addEventListener('click', sendMessage);

    async function sendMessage() {
        const text = textarea.value.trim();
        if (!text) return;
        sendBtn.disabled = true;
        textarea.disabled = true;
        try {
            await API.sendMessage(convoId, text);
            textarea.value = '';
        } catch (err) {
            console.error('Send failed', err);
        }
        sendBtn.disabled = false;
        textarea.disabled = false;
        textarea.focus();
    }

    function currentKindFilter() {
        return showConversationView ? conversationKinds.join(',') : undefined;
    }

    function renderMetaCard(data) {
        meta = data;
        metaCard.textContent = '';
        const title = data.title || convoId;
        header.innerHTML = `<h2>${esc(title)}</h2><p><a href="/ui/conversations">\u2190 Back to conversations</a></p>`;

        const hero = document.createElement('div');
        hero.className = 'conversation-meta-hero';

        const info = document.createElement('div');
        const titleEl = document.createElement('div');
        titleEl.className = 'card-title';
        titleEl.textContent = title;
        info.appendChild(titleEl);

        const sub = document.createElement('div');
        sub.className = 'card-subtitle';
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
            updated.textContent = _relativeTime(data.updated_at);
            statusWrap.appendChild(updated);
        }
        hero.appendChild(statusWrap);

        const facts = document.createElement('div');
        facts.className = 'conversation-meta-facts';
        [
            ['Agent', data.target_display_name || data.target_agent_id || '—'],
            ['Source', data.origin_channel || 'registry'],
            ['Reference', data.external_conversation_ref || '—'],
            ['Events', data.event_count !== undefined ? String(data.event_count) : '—'],
        ].forEach(([label, value]) => {
            const item = document.createElement('div');
            item.className = 'conversation-meta-fact';
            item.innerHTML = `<span>${esc(label)}</span><strong>${esc(value)}</strong>`;
            facts.appendChild(item);
        });

        metaCard.appendChild(hero);
        metaCard.appendChild(facts);
    }

    function clearTimelineForLoad() {
        beforeSeq = 0;
        latestSeq = 0;
        hasMoreBefore = false;
        loadingOlder = false;
        historyStatus.textContent = '';
        eventList.textContent = '';
        _renderSkeletons(eventList, 4, 'card');
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
            metaCard.textContent = '';
            _renderError(metaCard, 'Failed to load conversation metadata', loadConversation);
        }
    }

    async function reloadEvents() {
        if (topObserver) {
            topObserver.disconnect();
            topObserver = null;
        }
        clearTimelineForLoad();
        try {
            const result = await API.getEvents(convoId, {
                limit: 50,
                kind: currentKindFilter(),
            });
            const events = result.events || [];
            hasMoreBefore = !!result.has_more_before;
            beforeSeq = Number(result.next_before_seq || (events[0] && events[0].seq) || 0);
            latestSeq = Number(result.next_after_seq || (events[events.length - 1] && events[events.length - 1].seq) || 0);
            eventList.textContent = '';
            if (!events.length) {
                const empty = document.createElement('div');
                empty.className = 'empty-state';
                empty.textContent = 'No events yet';
                eventList.appendChild(empty);
            } else {
                events.forEach((event) => {
                    eventList.appendChild(_createConversationEventElement(event, convoId));
                });
                requestAnimationFrame(() => {
                    timeline.scrollTop = timeline.scrollHeight;
                });
            }
            updateHistoryStatus();
            initHistoryObserver();
        } catch (err) {
            eventList.textContent = '';
            _renderError(eventList, 'Failed to load events: ' + err.message, reloadEvents);
        }
    }

    async function loadOlderEvents() {
        if (loadingOlder || !hasMoreBefore || !beforeSeq) return;
        loadingOlder = true;
        updateHistoryStatus();
        const previousHeight = timeline.scrollHeight;
        const previousTop = timeline.scrollTop;
        try {
            const result = await API.getEvents(convoId, {
                before_seq: beforeSeq,
                limit: 50,
                kind: currentKindFilter(),
            });
            const events = result.events || [];
            if (!events.length) {
                hasMoreBefore = false;
                updateHistoryStatus();
                return;
            }
            const empty = eventList.querySelector('.empty-state');
            if (empty) empty.remove();
            const fragment = document.createDocumentFragment();
            events.forEach((event) => {
                fragment.appendChild(_createConversationEventElement(event, convoId));
            });
            eventList.prepend(fragment);
            hasMoreBefore = !!result.has_more_before;
            beforeSeq = Number(result.next_before_seq || (events[0] && events[0].seq) || beforeSeq);
            updateSequenceState(events);
            requestAnimationFrame(() => {
                const heightDelta = timeline.scrollHeight - previousHeight;
                timeline.scrollTop = previousTop + heightDelta;
            });
        } catch (err) {
            console.error('Load older failed', err);
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
        cleanups.push(() => topObserver && topObserver.disconnect());
    }

    function isNearBottom() {
        return timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 96;
    }

    const unsub = WS.subscribe(`conversation:${convoId}`, (msg) => {
        if (msg.type !== 'event' || !msg.data) return;
        const event = msg.data;
        if (showConversationView && !conversationKinds.includes(event.kind || '')) return;
        const seq = Number(event.seq || 0);
        if (seq && latestSeq && seq <= latestSeq) return;
        const shouldStick = isNearBottom();
        const empty = eventList.querySelector('.empty-state');
        if (empty) empty.remove();
        eventList.appendChild(_createConversationEventElement(event, convoId));
        if (seq) latestSeq = Math.max(latestSeq, seq);
        if (shouldStick) {
            requestAnimationFrame(() => {
                timeline.scrollTop = timeline.scrollHeight;
            });
        }
    });
    cleanups.push(unsub);

    loadConversation();
    reloadEvents();

    return function cleanup() {
        cleanups.forEach((fn) => fn());
    };
}

function _createConversationEventElement(event, convoId) {
    const kind = event.kind || '';
    if (kind === 'message.user' || kind === 'message.bot') {
        return _renderMessageBubble(event, kind);
    }

    const card = document.createElement('article');
    card.className = `event-card ${_eventCardClass(kind)}`;

    const header = document.createElement('div');
    header.className = 'event-card-header';

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

    const time = document.createElement('span');
    time.className = 'event-card-time';
    time.textContent = _formatTime(event.created_at);
    header.appendChild(time);
    card.appendChild(header);

    const body = document.createElement('div');
    body.className = 'event-card-body expanded';
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
            _renderTaskStatusCard(body, event, metadata);
            break;
        case 'error':
            _renderErrorCard(body, event, metadata);
            break;
        default:
            _renderGenericEventCard(body, event);
            break;
    }

    card.appendChild(body);
    return card;
}

function _renderMessageBubble(event, kind) {
    const bubble = document.createElement('article');
    bubble.className = `chat-bubble ${kind === 'message.user' ? 'user' : 'bot'}`;

    const actor = document.createElement('div');
    actor.className = 'actor';
    actor.textContent = event.actor || (kind === 'message.user' ? 'Operator' : 'Bot');
    bubble.appendChild(actor);

    const body = document.createElement('div');
    body.className = 'md-content';
    const temp = document.createElement('div');
    temp.innerHTML = _renderContent(event.content || '');
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
    timestamp.textContent = _formatTime(event.created_at);
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
        input.innerHTML = `<strong>Input</strong><p>${esc(metadata.input_summary)}</p>`;
        body.appendChild(input);
    }

    if (metadata.output_summary) {
        const output = document.createElement('div');
        output.className = 'event-text-block';
        output.innerHTML = `<strong>Output</strong><p>${esc(metadata.output_summary)}</p>`;
        body.appendChild(output);
    }

    const changes = Array.isArray(metadata.file_changes) ? metadata.file_changes : [];
    if (changes.length) {
        const list = document.createElement('ul');
        list.className = 'change-list';
        changes.forEach((change) => {
            const item = document.createElement('li');
            item.innerHTML = `<strong>${esc(change.change_type || 'changed')}</strong> <code>${esc(change.path || '')}</code><span>${esc(change.summary || '')}</span>`;
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
        ['Expires', metadata.expires_at ? _formatApprovalTime(metadata.expires_at) : 'No deadline'],
    ]));

    if (event.content) {
        const content = document.createElement('div');
        content.className = 'event-text-block';
        content.innerHTML = `<strong>Needs a decision</strong><p>${esc(event.content)}</p>`;
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
            console.error('Approval action failed', err);
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
        item.innerHTML = `<strong>${esc(task.title || '')}</strong><span>${esc(task.target || '')}</span><em>${esc(task.status || '')}</em>`;
        list.appendChild(item);
    });
    body.appendChild(list);
}

function _renderTaskStatusCard(body, event, metadata) {
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
        content.innerHTML = `<strong>Update</strong><p>${esc(event.content)}</p>`;
        body.appendChild(content);
    }
}

function _renderErrorCard(body, event, metadata) {
    body.appendChild(_metadataGrid([
        ['Problem type', metadata.error_type || 'execution'],
        ['Message', metadata.message || event.content || ''],
    ]));
    if (event.content && event.content !== metadata.message) {
        const block = document.createElement('div');
        block.className = 'event-text-block';
        block.innerHTML = `<strong>Content</strong><p>${esc(event.content)}</p>`;
        body.appendChild(block);
    }
}

function _renderGenericEventCard(body, event) {
    if (event.content) {
        const content = document.createElement('div');
        content.className = 'event-text-block';
        const temp = document.createElement('div');
        temp.innerHTML = _renderContent(event.content);
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
        item.innerHTML = `<span>${esc(label)}</span><strong>${esc(String(value))}</strong>`;
        grid.appendChild(item);
    });
    return grid;
}

function _createInlineMetric(value, label) {
    const metric = document.createElement('div');
    metric.className = 'inline-metric';
    metric.innerHTML = `<strong>${esc(String(value))}</strong><span>${esc(label)}</span>`;
    return metric;
}

function _formatApprovalTime(iso) {
    try {
        return new Date(iso).toLocaleString();
    } catch {
        return iso;
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
