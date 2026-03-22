/**
 * Task list — routed tasks across agents.
 */
function renderTaskList(container) {
    container.innerHTML = `
        <div class="page-header">
            <h2>Tasks</h2>
            <p>Routed tasks across agents</p>
        </div>
        <div id="task-list" class="loading">Loading tasks...</div>
    `;

    API.listTasks().then(tasks => {
        const el = document.getElementById('task-list');
        if (!tasks || tasks.length === 0) {
            el.innerHTML = '<div class="empty-state">No tasks</div>';
            return;
        }
        el.innerHTML = `
            <table class="data-table">
                <thead><tr>
                    <th>Title</th><th>Origin</th><th>Target</th><th>Status</th><th>Updated</th>
                </tr></thead>
                <tbody>
                    ${tasks.map(t => `
                        <tr onclick="Router.navigate('/ui/conversations/${t.parent_conversation_id || ''}')">
                            <td>${esc(t.title || t.routed_task_id)}</td>
                            <td>${esc(t.origin_display_name || t.origin_agent_id || '')}</td>
                            <td>${esc(t.target_display_name || t.target_agent_id || '')}</td>
                            <td><span class="badge badge-${t.status || 'queued'}">${esc(t.status || 'queued')}</span></td>
                            <td>${esc(_relativeTime(t.updated_at))}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    }).catch(err => {
        document.getElementById('task-list').innerHTML =
            `<div class="empty-state">Failed: ${esc(err.message)}</div>`;
    });
}
