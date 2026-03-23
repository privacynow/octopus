/**
 * Conversation detail — chat timeline with compose box, actions, and WS live updates.
 */
function renderConversationDetail(container, params) {
    const convoId = params.id;
    const cleanups = [];
    let oldestCursor = null;
    let hasOlderEvents = false;
    let showAllEvents = true; // true = all events, false = messages only

    // Header
    const header = document.createElement('div');
    header.className = 'page-header';
    const h2 = document.createElement('h2');
    h2.textContent = 'Conversation';
    header.appendChild(h2);
    const backP = document.createElement('p');
    const backA = document.createElement('a');
    backA.href = '/ui/conversations';
    backA.textContent = '\u2190 All conversations';
    backP.appendChild(backA);
    header.appendChild(backP);
    container.appendChild(header);

    // Metadata card
    const metaCard = document.createElement('div');
    metaCard.className = 'card';
    metaCard.id = 'convo-meta';
    container.appendChild(metaCard);

    // Action bar
    const actionBar = document.createElement('div');
    actionBar.className = 'action-bar';

    // Filter toggle
    const filterBtn = document.createElement('button');
    filterBtn.className = 'btn btn-sm';
    filterBtn.textContent = 'Messages only';
    filterBtn.addEventListener('click', () => {
        showAllEvents = !showAllEvents;
        filterBtn.textContent = showAllEvents ? 'Messages only' : 'All events';
        reloadTimeline();
    });
    actionBar.appendChild(filterBtn);

    // Cancel button
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn btn-sm btn-danger';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', () => {
        _showConfirm('Cancel Conversation', 'Are you sure you want to cancel this conversation?', async () => {
            cancelBtn.disabled = true;
            try {
                await API.conversationAction(convoId, 'cancel');
            } catch (e) {
                console.error('Cancel failed', e);
            }
            cancelBtn.disabled = false;
        });
    });
    actionBar.appendChild(cancelBtn);

    // Export button
    const exportBtn = document.createElement('button');
    exportBtn.className = 'btn btn-sm';
    exportBtn.textContent = 'Export';
    exportBtn.addEventListener('click', async () => {
        exportBtn.disabled = true;
        try {
            const text = await API.exportConversation(convoId);
            const blob = new Blob([text], { type: 'text/markdown' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'conversation-' + convoId + '.md';
            a.click();
            URL.revokeObjectURL(url);
        } catch (e) {
            console.error('Export failed', e);
        }
        exportBtn.disabled = false;
    });
    actionBar.appendChild(exportBtn);

    container.appendChild(actionBar);

    // Timeline
    const timeline = document.createElement('div');
    timeline.className = 'chat-timeline';
    timeline.id = 'convo-timeline';
    container.appendChild(timeline);

    // Load older button (inserted at top of timeline)
    const loadOlderWrap = document.createElement('div');
    loadOlderWrap.className = 'load-older';
    loadOlderWrap.id = 'load-older-wrap';
    loadOlderWrap.style.display = 'none';
    const loadOlderBtn = document.createElement('button');
    loadOlderBtn.className = 'btn btn-sm';
    loadOlderBtn.textContent = 'Load older';
    loadOlderBtn.addEventListener('click', () => loadOlderEvents());
    loadOlderWrap.appendChild(loadOlderBtn);

    // Compose box
    const compose = document.createElement('div');
    compose.className = 'compose-box';

    const textarea = document.createElement('textarea');
    textarea.placeholder = 'Type a message...';
    textarea.rows = 1;
    compose.appendChild(textarea);

    const sendBtn = document.createElement('button');
    sendBtn.className = 'btn btn-primary';
    sendBtn.textContent = 'Send';
    sendBtn.addEventListener('click', sendMessage);
    compose.appendChild(sendBtn);

    container.appendChild(compose);

    // Enter to send (Shift+Enter for newline)
    textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    async function sendMessage() {
        const text = textarea.value.trim();
        if (!text) return;
        sendBtn.disabled = true;
        textarea.disabled = true;
        try {
            await API.sendMessage(convoId, text);
            textarea.value = '';
        } catch (e) {
            console.error('Send failed', e);
        }
        sendBtn.disabled = false;
        textarea.disabled = false;
        textarea.focus();
    }

    // Load metadata
    API.getConversation(convoId).then(c => {
        metaCard.textContent = '';
        const row = document.createElement('div');
        row.className = 'card-row';

        const info = document.createElement('div');
        const title = document.createElement('div');
        title.className = 'card-title';
        title.textContent = c.title || convoId;
        info.appendChild(title);

        const sub = document.createElement('div');
        sub.className = 'card-subtitle';
        const parts = [];
        if (c.target_display_name || c.target_agent_id) parts.push(c.target_display_name || c.target_agent_id);
        if (c.origin_channel) parts.push(c.origin_channel);
        parts.push('Created ' + _relativeTime(c.created_at));
        sub.textContent = parts.join(' \u00b7 ');
        info.appendChild(sub);

        row.appendChild(info);

        const badge = document.createElement('span');
        badge.className = 'badge badge-' + (c.status || 'open');
        badge.id = 'convo-status-badge';
        badge.textContent = c.status || 'open';
        row.appendChild(badge);

        metaCard.appendChild(row);
    }).catch(() => {
        metaCard.textContent = '';
        const p = document.createElement('div');
        p.className = 'card-subtitle';
        p.textContent = 'Could not load metadata';
        metaCard.appendChild(p);
    });

    // Load events
    function reloadTimeline() {
        timeline.textContent = '';
        oldestCursor = null;
        hasOlderEvents = false;
        loadOlderWrap.style.display = 'none';
        _renderSkeletons(timeline, 5, 'row');
        loadInitialEvents();
    }

    function loadInitialEvents() {
        const kindFilter = showAllEvents ? undefined : 'message.user,message.bot';
        API.getEvents(convoId, { limit: 50, kind: kindFilter }).then(result => {
            const events = result.events || result || [];
            timeline.textContent = '';

            if (result.next_cursor) {
                oldestCursor = result.next_cursor;
                hasOlderEvents = true;
            }

            if (hasOlderEvents) {
                timeline.appendChild(loadOlderWrap);
                loadOlderWrap.style.display = '';
            }

            if (events.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'empty-state';
                empty.textContent = 'No events yet';
                timeline.appendChild(empty);
                return;
            }

            events.forEach(e => {
                timeline.appendChild(_createEventElement(e));
            });

            timeline.scrollTop = timeline.scrollHeight;
        }).catch(err => {
            timeline.textContent = '';
            _renderError(timeline, 'Failed to load events: ' + err.message, reloadTimeline);
        });
    }

    function loadOlderEvents() {
        if (!oldestCursor) return;
        loadOlderBtn.disabled = true;
        const kindFilter = showAllEvents ? undefined : 'message.user,message.bot';
        API.getEvents(convoId, { cursor: oldestCursor, limit: 50, kind: kindFilter }).then(result => {
            const events = result.events || result || [];
            loadOlderBtn.disabled = false;

            if (result.next_cursor) {
                oldestCursor = result.next_cursor;
            } else {
                hasOlderEvents = false;
                loadOlderWrap.style.display = 'none';
            }

            // Insert events after the load-older button
            const refNode = loadOlderWrap.nextSibling;
            events.forEach(e => {
                const el = _createEventElement(e);
                timeline.insertBefore(el, refNode);
            });
        }).catch(err => {
            loadOlderBtn.disabled = false;
            console.error('Load older failed', err);
        });
    }

    // WS: subscribe to conversation events
    const unsub = WS.subscribe('conversation:' + convoId, (msg) => {
        if (msg.type === 'event' && msg.data) {
            const e = msg.data;
            // Respect filter
            if (!showAllEvents) {
                if (e.kind !== 'message.user' && e.kind !== 'message.bot') return;
            }
            // Remove empty-state if present
            const empty = timeline.querySelector('.empty-state');
            if (empty) empty.remove();
            timeline.appendChild(_createEventElement(e));
            // Auto-scroll if near bottom
            const isNearBottom = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 100;
            if (isNearBottom) {
                timeline.scrollTop = timeline.scrollHeight;
            }
        }
    });
    cleanups.push(unsub);

    reloadTimeline();

    return function cleanup() {
        cleanups.forEach(fn => fn());
    };
}

/**
 * Create a DOM element for an event (message bubble or event card).
 */
function _createEventElement(e) {
    const kind = e.kind || '';

    if (kind === 'message.user' || kind === 'message.bot') {
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble ' + (kind === 'message.user' ? 'user' : 'bot');

        const actor = document.createElement('div');
        actor.className = 'actor';
        actor.textContent = e.actor || (kind === 'message.user' ? 'User' : 'Bot');
        bubble.appendChild(actor);

        const body = document.createElement('div');
        body.className = 'md-content';
        const rendered = _renderContent(e.content || '');
        // Use a safe container for rendered markdown
        const temp = document.createElement('div');
        temp.innerHTML = rendered;
        while (temp.firstChild) body.appendChild(temp.firstChild);
        bubble.appendChild(body);

        const ts = document.createElement('div');
        ts.className = 'timestamp';
        ts.textContent = _formatTime(e.created_at);
        bubble.appendChild(ts);

        return bubble;
    }

    // Non-message events as collapsible cards
    const card = document.createElement('div');
    card.className = 'event-card ' + _eventCardClass(kind);

    const header = document.createElement('div');
    header.className = 'event-card-header';

    const kindSpan = document.createElement('span');
    kindSpan.className = 'kind';
    kindSpan.textContent = kind;
    header.appendChild(kindSpan);

    const timeSpan = document.createElement('span');
    timeSpan.style.fontSize = '10px';
    timeSpan.style.color = 'var(--text-muted)';
    timeSpan.textContent = _formatTime(e.created_at);
    header.appendChild(timeSpan);

    card.appendChild(header);

    const body = document.createElement('div');
    body.className = 'event-card-body';

    if (e.content) {
        const contentDiv = document.createElement('div');
        contentDiv.style.marginBottom = '8px';
        const rendered = _renderContent(e.content);
        const temp = document.createElement('div');
        temp.innerHTML = rendered;
        while (temp.firstChild) contentDiv.appendChild(temp.firstChild);
        body.appendChild(contentDiv);
    }

    const meta = e.metadata || e.metadata_json || {};
    const metaStr = typeof meta === 'string' ? meta : JSON.stringify(meta, null, 2);
    if (metaStr && metaStr !== '{}') {
        const pre = document.createElement('pre');
        pre.textContent = metaStr;
        body.appendChild(pre);
    }

    card.appendChild(body);

    // Toggle expand on header click
    header.addEventListener('click', () => {
        body.classList.toggle('expanded');
    });

    return card;
}

function _eventCardClass(kind) {
    if (kind.startsWith('provider.')) return 'provider';
    if (kind.startsWith('tool.')) return 'tool';
    if (kind.startsWith('approval.')) return 'approval';
    if (kind.startsWith('delegation.')) return 'delegation';
    if (kind === 'error') return 'error';
    return '';
}
