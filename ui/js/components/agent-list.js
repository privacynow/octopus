/**
 * Agent list — home view showing all enrolled agents.
 */
function renderAgentList(container) {
    container.innerHTML = `
        <div class="page-header">
            <h2>Agents</h2>
            <p>Enrolled bots and their current status</p>
        </div>
        <div id="agent-list-content" class="loading">Loading agents...</div>
    `;

    API.listAgents().then(agents => {
        const el = document.getElementById('agent-list-content');
        if (!agents || agents.length === 0) {
            el.innerHTML = '<div class="empty-state">No agents enrolled</div>';
            return;
        }
        el.innerHTML = agents.map(a => `
            <div class="card" onclick="Router.navigate('/ui/agents/${a.agent_id}')">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <div>
                        <div class="card-title">${esc(a.display_name || a.slug)}</div>
                        <div class="card-subtitle">
                            ${esc(a.role || 'agent')} &middot; ${esc(a.provider || '')} &middot; ${esc(a.slug)}
                        </div>
                    </div>
                    <span class="badge badge-${a.connectivity_state || 'stopped'}">
                        ${esc(a.connectivity_state || 'unknown')}
                    </span>
                </div>
            </div>
        `).join('');
    }).catch(err => {
        document.getElementById('agent-list-content').innerHTML =
            `<div class="empty-state">Failed to load agents: ${esc(err.message)}</div>`;
    });
}
