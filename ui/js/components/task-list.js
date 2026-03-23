/**
 * Task list — routed tasks across agents with pagination, status filter, and inline detail.
 */
function renderTaskList(container) {
    let cursor = 0;
    let cursorStack = [];
    const limit = 25;
    let currentStatus = '';

    // Header
    const header = document.createElement('div');
    header.className = 'page-header';
    header.innerHTML = '<h2>Tasks</h2><p>Routed tasks across agents</p>';
    container.appendChild(header);

    // Filter bar
    const filterBar = document.createElement('div');
    filterBar.className = 'filter-bar';

    const statusSelect = document.createElement('select');
    statusSelect.innerHTML =
        '<option value="">All statuses</option>' +
        '<option value="queued">Queued</option>' +
        '<option value="running">Running</option>' +
        '<option value="completed">Completed</option>' +
        '<option value="failed">Failed</option>';
    filterBar.appendChild(statusSelect);
    container.appendChild(filterBar);

    const listEl = document.createElement('div');
    container.appendChild(listEl);

    const pagEl = document.createElement('div');
    container.appendChild(pagEl);

    statusSelect.addEventListener('change', () => {
        currentStatus = statusSelect.value;
        cursor = 0;
        cursorStack = [];
        loadPage();
    });

    function loadPage() {
        listEl.textContent = '';
        _renderSkeletons(listEl, 5, 'row');
        pagEl.textContent = '';

        const params = { cursor, limit };
        if (currentStatus) params.status = currentStatus;

        API.listTasks(params).then(data => {
            const tasks = data.tasks || data || [];
            listEl.textContent = '';

            if (tasks.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'empty-state';
                empty.textContent = 'No tasks';
                listEl.appendChild(empty);
                return;
            }

            tasks.forEach(t => {
                const card = document.createElement('div');
                card.className = 'card task-card';

                // Summary row
                const row = document.createElement('div');
                row.className = 'card-row clickable';

                const info = document.createElement('div');
                const title = document.createElement('div');
                title.className = 'card-title';
                title.textContent = t.title || t.routed_task_id;
                info.appendChild(title);

                const sub = document.createElement('div');
                sub.className = 'card-subtitle';
                const parts = [];
                if (t.origin_display_name || t.origin_agent_id) {
                    parts.push('From: ' + (t.origin_display_name || t.origin_agent_id));
                }
                if (t.target_display_name || t.target_agent_id) {
                    parts.push('To: ' + (t.target_display_name || t.target_agent_id));
                }
                if (t.updated_at) {
                    parts.push(_relativeTime(t.updated_at));
                }
                sub.textContent = parts.join(' \u00b7 ');
                info.appendChild(sub);

                row.appendChild(info);

                const badge = document.createElement('span');
                badge.className = 'badge badge-' + (t.status || 'queued');
                badge.textContent = t.status || 'queued';
                row.appendChild(badge);

                card.appendChild(row);

                // Detail section (collapsed by default)
                const detail = document.createElement('div');
                detail.className = 'task-detail';
                detail.style.display = 'none';

                if (t.instructions) {
                    const instrLabel = document.createElement('div');
                    instrLabel.className = 'detail-label';
                    instrLabel.textContent = 'Instructions';
                    detail.appendChild(instrLabel);
                    const instrBody = document.createElement('div');
                    instrBody.className = 'detail-body';
                    instrBody.textContent = t.instructions;
                    detail.appendChild(instrBody);
                }

                if (t.result_summary || t.result_text) {
                    const resultLabel = document.createElement('div');
                    resultLabel.className = 'detail-label';
                    resultLabel.textContent = 'Result';
                    detail.appendChild(resultLabel);
                    const resultBody = document.createElement('div');
                    resultBody.className = 'detail-body';
                    resultBody.textContent = t.result_summary || t.result_text || '';
                    detail.appendChild(resultBody);
                }

                if (t.parent_conversation_id) {
                    const linkWrap = document.createElement('div');
                    linkWrap.style.marginTop = '8px';
                    const link = document.createElement('a');
                    link.href = '/ui/conversations/' + t.parent_conversation_id;
                    link.textContent = 'View parent conversation';
                    link.addEventListener('click', (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        Router.navigate('/ui/conversations/' + t.parent_conversation_id);
                    });
                    linkWrap.appendChild(link);
                    detail.appendChild(linkWrap);
                }

                card.appendChild(detail);

                // Toggle detail on click
                row.addEventListener('click', () => {
                    detail.style.display = detail.style.display === 'none' ? 'block' : 'none';
                });

                listEl.appendChild(card);
            });

            pagEl.textContent = '';
            _renderPagination(pagEl, {
                hasPrev: cursorStack.length > 0,
                hasNext: !!data.has_more,
                info: '',
                onPrev: () => {
                    cursor = cursorStack.pop() || 0;
                    loadPage();
                },
                onNext: () => {
                    cursorStack.push(cursor);
                    cursor = data.next_cursor;
                    loadPage();
                },
            });
        }).catch(err => {
            listEl.textContent = '';
            _renderError(listEl, 'Failed: ' + err.message, loadPage);
        });
    }

    loadPage();

    // WS: subscribe for live task updates (task.status, new tasks, completions)
    let reloadDebounce = null;
    const unsub = WS.subscribe('*', (msg) => {
        if (msg.type === 'event') {
            clearTimeout(reloadDebounce);
            reloadDebounce = setTimeout(loadPage, 2000);
        }
    });

    return function cleanup() { clearTimeout(reloadDebounce); unsub(); };
}
