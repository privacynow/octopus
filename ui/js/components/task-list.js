/**
 * Task list — routed tasks across agents with pagination and status filter.
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

            const wrap = document.createElement('div');
            wrap.className = 'table-wrap';
            const tbl = document.createElement('table');
            tbl.className = 'data-table responsive';

            const thead = document.createElement('thead');
            thead.innerHTML = '<tr><th>Title</th><th>Origin</th><th>Target</th><th>Status</th><th>Updated</th></tr>';
            tbl.appendChild(thead);

            const tbody = document.createElement('tbody');
            tasks.forEach(t => {
                const tr = document.createElement('tr');
                tr.className = 'clickable';
                tr.addEventListener('click', () => {
                    if (t.parent_conversation_id) {
                        Router.navigate('/ui/conversations/' + t.parent_conversation_id);
                    }
                });

                const cells = [
                    ['Title', t.title || t.routed_task_id],
                    ['Origin', t.origin_display_name || t.origin_agent_id || ''],
                    ['Target', t.target_display_name || t.target_agent_id || ''],
                ];
                cells.forEach(([label, val]) => {
                    const td = document.createElement('td');
                    td.setAttribute('data-label', label);
                    td.textContent = val;
                    tr.appendChild(td);
                });

                // Status badge
                const statusTd = document.createElement('td');
                statusTd.setAttribute('data-label', 'Status');
                const badge = document.createElement('span');
                badge.className = 'badge badge-' + (t.status || 'queued');
                badge.textContent = t.status || 'queued';
                statusTd.appendChild(badge);
                tr.appendChild(statusTd);

                // Updated time
                const updTd = document.createElement('td');
                updTd.setAttribute('data-label', 'Updated');
                updTd.setAttribute('data-timestamp', t.updated_at || '');
                updTd.textContent = _relativeTime(t.updated_at);
                tr.appendChild(updTd);

                tbody.appendChild(tr);
            });
            tbl.appendChild(tbody);
            wrap.appendChild(tbl);
            listEl.appendChild(wrap);

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
