/**
 * Conversation list — all conversations with search/filter.
 */
function renderConversationList(container) {
    container.innerHTML = `
        <div class="page-header">
            <h2>Conversations</h2>
            <p>All conversations across agents</p>
        </div>
        <input class="search-bar" id="convo-search" placeholder="Search conversations (3+ chars)..." />
        <div id="convo-list" class="loading">Loading...</div>
    `;

    let searchTimeout = null;
    document.getElementById('convo-search').addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            const q = e.target.value.trim();
            _loadConversations(q.length >= 3 ? q : '');
        }, 300);
    });

    _loadConversations('');
}

function _loadConversations(q) {
    const el = document.getElementById('convo-list');
    if (!el) return;
    el.innerHTML = '<div class="loading">Loading...</div>';

    API.listConversations({ q }).then(convos => {
        if (!convos || convos.length === 0) {
            el.innerHTML = '<div class="empty-state">No conversations found</div>';
            return;
        }
        el.innerHTML = convos.map(c => `
            <div class="card" onclick="Router.navigate('/ui/conversations/${c.conversation_id}')">
                <div style="display:flex;justify-content:space-between">
                    <div>
                        <div class="card-title">${esc(c.title || c.conversation_id)}</div>
                        <div class="card-subtitle">
                            ${esc(c.target_display_name || c.target_agent_id || '')}
                            &middot; ${esc(c.origin_channel || '')}
                            &middot; ${esc(_relativeTime(c.updated_at || c.created_at))}
                        </div>
                    </div>
                    <span class="badge badge-${c.status || 'open'}">${esc(c.status || 'open')}</span>
                </div>
            </div>
        `).join('');
    }).catch(err => {
        el.innerHTML = `<div class="empty-state">Failed: ${esc(err.message)}</div>`;
    });
}
