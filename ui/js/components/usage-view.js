/**
 * Usage view — token/cost summary (operator only).
 */
function renderUsageView(container) {
    container.innerHTML = `
        <div class="page-header">
            <h2>Usage</h2>
            <p>Token usage and cost summary</p>
        </div>
        <div id="usage-content" class="loading">Loading usage data...</div>
    `;

    API.getUsage().then(usage => {
        const el = document.getElementById('usage-content');
        if (!usage || usage.length === 0) {
            el.innerHTML = '<div class="empty-state">No usage data yet</div>';
            return;
        }
        el.innerHTML = `
            <table class="data-table">
                <thead><tr>
                    <th>Date</th><th>Conversation</th><th>Tokens</th><th>Cost</th>
                </tr></thead>
                <tbody>
                    ${usage.map(u => `
                        <tr>
                            <td>${esc(u.date || u.day || '')}</td>
                            <td>${esc(u.conversation_id || u.title || 'aggregate')}</td>
                            <td>${(u.total_tokens || 0).toLocaleString()}</td>
                            <td>$${(u.cost_usd || 0).toFixed(4)}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    }).catch(err => {
        document.getElementById('usage-content').innerHTML =
            `<div class="empty-state">Failed: ${esc(err.message)}</div>`;
    });
}
