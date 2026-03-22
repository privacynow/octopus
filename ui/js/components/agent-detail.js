/**
 * Agent detail — status, capabilities, health, conversations.
 */
function renderAgentDetail(container, params) {
    const agentId = params.id;
    container.innerHTML = `
        <div class="page-header">
            <h2>Agent Detail</h2>
            <p>Loading...</p>
        </div>
        <div id="agent-detail-content" class="loading">Loading agent status...</div>
    `;

    API.getAgentStatus(agentId).then(status => {
        if (!status) {
            container.innerHTML = '<div class="empty-state">Agent not found</div>';
            return;
        }
        const a = status.agent || status;
        const workers = status.workers || [];
        const header = container.querySelector('.page-header');
        header.innerHTML = `
            <h2>${esc(a.display_name || a.slug)}</h2>
            <p>${esc(a.role || 'agent')} &middot; ${esc(a.provider || '')} &middot;
            <span class="badge badge-${a.connectivity_state || 'stopped'}">${esc(a.connectivity_state || 'unknown')}</span></p>
        `;
        const content = document.getElementById('agent-detail-content');
        content.innerHTML = `
            <div class="card">
                <div class="card-title">Info</div>
                <table class="data-table">
                    <tr><td>Agent ID</td><td>${esc(a.agent_id)}</td></tr>
                    <tr><td>Slug</td><td>${esc(a.slug)}</td></tr>
                    <tr><td>Scope</td><td>${esc(a.registry_scope || '')}</td></tr>
                    <tr><td>Version</td><td>${esc(a.version || '')}</td></tr>
                    <tr><td>Last Heartbeat</td><td>${esc(a.last_heartbeat_at || 'never')}</td></tr>
                    <tr><td>Capabilities</td><td>${esc((a.capabilities || []).join(', ') || 'none')}</td></tr>
                    <tr><td>Tags</td><td>${esc((a.tags || []).join(', ') || 'none')}</td></tr>
                </table>
            </div>
            ${workers.length > 0 ? `
            <div class="card">
                <div class="card-title">Workers</div>
                <table class="data-table">
                    <thead><tr><th>Worker</th><th>Role</th><th>Current</th><th>Last Seen</th></tr></thead>
                    <tbody>
                        ${workers.map(w => `
                            <tr>
                                <td>${esc(w.worker_id || '')}</td>
                                <td>${esc(w.process_role || '')}</td>
                                <td>${esc(w.current_item_id || 'idle')}</td>
                                <td>${esc(w.last_seen_at || '')}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
            ` : ''}
            <div class="card" style="cursor:pointer" onclick="Router.navigate('/ui/agents/${agentId}/conversations')">
                <div class="card-title">Conversations &rarr;</div>
                <div class="card-subtitle">View conversations for this agent</div>
            </div>
        `;

        // Subscribe to live updates
        WS.subscribe(`agent:${agentId}`, (msg) => {
            if (msg.type === 'heartbeat') {
                // Refresh the page
                renderAgentDetail(container, params);
            }
        });
    }).catch(err => {
        document.getElementById('agent-detail-content').innerHTML =
            `<div class="empty-state">Failed to load agent: ${esc(err.message)}</div>`;
    });
}

function renderAgentConversations(container, params) {
    const agentId = params.id;
    container.innerHTML = `
        <div class="page-header">
            <h2>Agent Conversations</h2>
            <p><a href="/ui/agents/${agentId}">&larr; Back to agent</a></p>
        </div>
        <div id="agent-convos" class="loading">Loading...</div>
    `;

    API.getAgentConversations(agentId).then(convos => {
        const el = document.getElementById('agent-convos');
        if (!convos || convos.length === 0) {
            el.innerHTML = '<div class="empty-state">No conversations</div>';
            return;
        }
        el.innerHTML = convos.map(c => `
            <div class="card" onclick="Router.navigate('/ui/conversations/${c.conversation_id}')">
                <div style="display:flex;justify-content:space-between">
                    <div>
                        <div class="card-title">${esc(c.title || c.conversation_id)}</div>
                        <div class="card-subtitle">${esc(c.origin_channel || '')} &middot; ${esc(c.created_at || '')}</div>
                    </div>
                    <span class="badge badge-${c.status || 'open'}">${esc(c.status || 'open')}</span>
                </div>
            </div>
        `).join('');
    }).catch(err => {
        document.getElementById('agent-convos').innerHTML =
            `<div class="empty-state">Failed: ${esc(err.message)}</div>`;
    });
}
