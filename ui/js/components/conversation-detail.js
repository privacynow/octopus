/**
 * Conversation detail — chat-like timeline with rich event rendering.
 */
function renderConversationDetail(container, params) {
    const convoId = params.id;
    container.innerHTML = `
        <div class="page-header">
            <h2>Conversation</h2>
            <p><a href="/ui/conversations">&larr; All conversations</a></p>
        </div>
        <div id="convo-meta" class="card" style="cursor:default"></div>
        <div id="convo-timeline" class="chat-timeline loading">Loading events...</div>
    `;

    // Load metadata
    API.getConversation(convoId).then(c => {
        document.getElementById('convo-meta').innerHTML = `
            <div style="display:flex;justify-content:space-between">
                <div>
                    <div class="card-title">${esc(c.title || convoId)}</div>
                    <div class="card-subtitle">
                        ${esc(c.target_display_name || c.target_agent_id || '')}
                        &middot; ${esc(c.origin_channel || '')}
                        &middot; Created ${esc(_relativeTime(c.created_at))}
                    </div>
                </div>
                <span class="badge badge-${c.status || 'open'}">${esc(c.status || 'open')}</span>
            </div>
        `;
    }).catch(() => {});

    // Load events
    _loadEvents(convoId);

    // Subscribe to live updates
    const unsub = WS.subscribe(`conversation:${convoId}`, (msg) => {
        if (msg.type === 'event') {
            _appendEvent(msg.data);
        }
    });
}

function _loadEvents(convoId) {
    const el = document.getElementById('convo-timeline');
    if (!el) return;

    API.getEvents(convoId, { limit: 100 }).then(result => {
        const events = result.events || result || [];
        el.classList.remove('loading');
        if (events.length === 0) {
            el.innerHTML = '<div class="empty-state">No events yet</div>';
            return;
        }
        el.innerHTML = events.map(e => _renderEvent(e)).join('');
        el.scrollTop = el.scrollHeight;
    }).catch(err => {
        el.innerHTML = `<div class="empty-state">Failed: ${esc(err.message)}</div>`;
    });
}

function _appendEvent(eventData) {
    const el = document.getElementById('convo-timeline');
    if (!el) return;
    const empty = el.querySelector('.empty-state');
    if (empty) empty.remove();
    el.insertAdjacentHTML('beforeend', _renderEvent(eventData));
    el.scrollTop = el.scrollHeight;
}

function _renderEvent(e) {
    const kind = e.kind || '';
    if (kind === 'message.user') {
        return `
            <div class="chat-bubble user">
                <div class="actor">${esc(e.actor || 'User')}</div>
                <div>${_renderContent(e.content || '')}</div>
                <div class="timestamp">${esc(_formatTime(e.created_at || e.timestamp))}</div>
            </div>
        `;
    }
    if (kind === 'message.bot') {
        return `
            <div class="chat-bubble bot">
                <div class="actor">${esc(e.actor || 'Bot')}</div>
                <div>${_renderContent(e.content || '')}</div>
                <div class="timestamp">${esc(_formatTime(e.created_at || e.timestamp))}</div>
            </div>
        `;
    }
    // Non-message events as collapsible cards
    const cls = _eventCardClass(kind);
    const meta = e.metadata || e.metadata_json || {};
    const metaStr = typeof meta === 'string' ? meta : JSON.stringify(meta, null, 2);
    return `
        <div class="event-card ${cls}">
            <div class="event-card-header" onclick="this.nextElementSibling.classList.toggle('expanded')">
                <span class="kind">${esc(kind)}</span>
                <span style="font-size:10px;color:var(--text-muted)">${esc(_formatTime(e.created_at || e.timestamp))}</span>
            </div>
            <div class="event-card-body">
                ${e.content ? `<div style="margin-bottom:8px">${_renderContent(e.content)}</div>` : ''}
                ${metaStr && metaStr !== '{}' ? `<pre>${esc(metaStr)}</pre>` : ''}
            </div>
        </div>
    `;
}

function _eventCardClass(kind) {
    if (kind.startsWith('provider.')) return 'provider';
    if (kind.startsWith('tool.')) return 'tool';
    if (kind.startsWith('approval.')) return 'approval';
    if (kind.startsWith('delegation.')) return 'delegation';
    if (kind === 'error') return 'error';
    return '';
}
