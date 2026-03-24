/**
 * Task list — routed tasks across agents with pagination, status filter, and inline detail.
 */
function renderTaskList(container) {
    const cleanups = UI.beginCleanupScope();
    let cursor = 0;
    let cursorStack = [];
    const limit = UI.DEFAULT_PAGE_LIMIT;
    let currentStatus = UI.readQueryParam('status', '');

    // Header
    const header = document.createElement('div');
    header.className = 'page-header';
    header.innerHTML = '<h2>Tasks</h2><p>Track delegated work, see what is stalled, and open the parent conversation when you need context.</p>';
    container.appendChild(header);

    // Filter bar
    const filterBar = document.createElement('div');
    filterBar.className = 'filter-bar';

    const statusSelect = document.createElement('select');
    statusSelect.setAttribute('aria-label', 'Filter tasks by status');
    statusSelect.innerHTML =
        '<option value="">All statuses</option>' +
        '<option value="queued">Queued</option>' +
        '<option value="running">Running</option>' +
        '<option value="completed">Completed</option>' +
        '<option value="failed">Failed</option>';
    filterBar.appendChild(statusSelect);
    container.appendChild(filterBar);

    const listEl = document.createElement('div');
    listEl.className = 'list-container list-container-loose';
    container.appendChild(listEl);

    const pagEl = document.createElement('div');
    container.appendChild(pagEl);

    statusSelect.addEventListener('change', () => {
        currentStatus = statusSelect.value;
        cursor = 0;
        cursorStack = [];
        UI.updateQueryParams({ status: currentStatus });
        loadPage();
    });
    statusSelect.value = currentStatus;

    function loadPage() {
        listEl.textContent = '';
        UI.renderSkeletons(listEl, 5, 'row');
        pagEl.textContent = '';

        const params = { cursor, limit };
        if (currentStatus) params.status = currentStatus;

        API.listTasks(params).then(data => {
            const tasks = data.tasks || data || [];
            listEl.textContent = '';

            if (tasks.length === 0) {
                listEl.appendChild(UI.renderEmptyState('No tasks'));
                return;
            }

            tasks.forEach(t => {
                const item = document.createElement('div');
                item.className = 'task-list-item';

                const sub = document.createElement('span');
                const parts = [];
                if (t.origin_display_name || t.origin_agent_id) {
                    parts.push('From: ' + (t.origin_display_name || t.origin_agent_id));
                }
                if (t.target_display_name || t.target_agent_id) {
                    parts.push('To: ' + (t.target_display_name || t.target_agent_id));
                }
                if (t.updated_at) {
                    parts.push(UI.relativeTime(t.updated_at));
                }
                sub.textContent = parts.join(' \u00b7 ');

                const row = UI.renderListRow({
                    label: t.title || t.routed_task_id,
                    sublabelNode: sub,
                    badgeText: t.status || 'queued',
                    badgeClass: 'badge-' + (t.status || 'queued'),
                    onClick: () => {
                        const nextExpanded = detail.hidden;
                        detail.hidden = !nextExpanded;
                        row.setAttribute('aria-expanded', String(nextExpanded));
                    },
                    className: 'task-summary-row',
                });
                row.setAttribute('aria-expanded', 'false');
                item.appendChild(row);

                // Detail section (collapsed by default)
                const detail = document.createElement('div');
                detail.className = 'task-detail';
                detail.hidden = true;

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

                item.appendChild(detail);
                listEl.appendChild(item);
            });

            pagEl.textContent = '';
            UI.renderPagination(pagEl, {
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
            UI.renderError(listEl, 'Failed: ' + err.message, loadPage);
        });
    }

    loadPage();

    let reloadDebounce = null;
    const unsub = WS.subscribe('tasks', () => {
        clearTimeout(reloadDebounce);
        reloadDebounce = setTimeout(loadPage, 400);
    });
    cleanups.add(() => clearTimeout(reloadDebounce));
    cleanups.add(unsub);
}
