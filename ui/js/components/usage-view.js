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
        const rows = Array.isArray(usage)
            ? usage
            : (usage && usage.by_conversation) ? usage.by_conversation : [];
        if (!rows || rows.length === 0) {
            el.innerHTML = '<div class="empty-state">No usage data yet</div>';
            return;
        }
        el.innerHTML = `
            <table class="data-table">
                <thead><tr>
                    <th>Conversation</th><th>Prompt tok</th><th>Completion tok</th><th>Cost</th>
                </tr></thead>
                <tbody>
                    ${rows.map(u => {
                        const pt = u.prompt_tokens || 0;
                        const ct = u.completion_tokens || 0;
                        return `
                        <tr>
                            <td>${esc(u.conversation_id || u.title || '')}</td>
                            <td>${pt.toLocaleString()}</td>
                            <td>${ct.toLocaleString()}</td>
                            <td>$${(u.cost_usd || 0).toFixed(4)}</td>
                        </tr>
                    `;}).join('')}
                </tbody>
            </table>
        `;
    }).catch(err => {
        document.getElementById('usage-content').innerHTML =
            `<div class="empty-state">Failed: ${esc(err.message)}</div>`;
    });
}
