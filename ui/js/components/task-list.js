/**
 * Task view — status board plus detailed task log.
 */
function renderTaskList(container) {
    const cleanups = UI.beginCleanupScope();
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }
    let cursor = 0;
    let cursorStack = [];
    const limit = UI.DEFAULT_PAGE_LIMIT;
    let currentStatus = UI.readQueryParam('status', '');
    let boardLoaded = false;
    let listLoaded = false;

    const header = document.createElement('div');
    header.className = 'page-header';
    header.innerHTML = '<h2>Tasks</h2><p>See queued, active, blocked, and completed delegated work without digging through raw activity.</p>';
    container.appendChild(header);

    const boardShell = document.createElement('section');
    boardShell.className = 'task-board-shell';
    container.appendChild(boardShell);

    const filterBar = document.createElement('div');
    filterBar.className = 'filter-bar';

    const statusSelect = document.createElement('select');
    statusSelect.setAttribute('aria-label', 'Filter task log by status');
    statusSelect.innerHTML =
        '<option value="">All statuses</option>' +
        '<option value="queued">Queued</option>' +
        '<option value="running">Running</option>' +
        '<option value="completed">Completed</option>' +
        '<option value="failed">Failed</option>' +
        '<option value="cancelled">Cancelled</option>';
    filterBar.appendChild(statusSelect);
    container.appendChild(filterBar);

    const listSection = document.createElement('section');
    listSection.className = 'task-log-shell';
    container.appendChild(listSection);

    const listHeader = document.createElement('div');
    listHeader.className = 'task-feed-header';
    listHeader.innerHTML = '<strong>Task log</strong><span>Recent routed work with details, actions, and parent conversation links.</span>';
    listSection.appendChild(listHeader);

    const listEl = document.createElement('div');
    listEl.className = 'list-container list-container-loose';
    listSection.appendChild(listEl);

    const pagEl = document.createElement('div');
    listSection.appendChild(pagEl);

    statusSelect.addEventListener('change', () => {
        currentStatus = statusSelect.value;
        cursor = 0;
        cursorStack = [];
        UI.updateQueryParams({ status: currentStatus });
        loadList();
    });
    statusSelect.value = currentStatus;

    function _taskSummary(task) {
        return task.result_summary || task.result_text || task.summary || task.instructions || '';
    }

    function _attachTaskActions(actions, task, statusText) {
        if (['queued', 'submitted', 'leased', 'running'].includes(task.status || '')) {
            const cancelBtn = document.createElement('button');
            cancelBtn.type = 'button';
            cancelBtn.className = 'btn btn-sm btn-danger';
            cancelBtn.textContent = 'Cancel task';
            cancelBtn.addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();
                cancelBtn.disabled = true;
                statusText.textContent = 'Cancelling…';
                try {
                    await API.conversationAction(task.parent_conversation_id, 'cancel_task', {
                        routed_task_id: task.routed_task_id,
                    });
                    statusText.textContent = 'Cancel requested.';
                } catch (err) {
                    cancelBtn.disabled = false;
                    statusText.textContent = 'Cancel failed.';
                    UI.reportError('Failed to cancel the task', err, { context: 'Task cancel failed' });
                }
            });
            actions.appendChild(cancelBtn);
        }
        if (['failed', 'cancelled', 'timed_out'].includes(task.status || '')) {
            const retryBtn = document.createElement('button');
            retryBtn.type = 'button';
            retryBtn.className = 'btn btn-sm';
            retryBtn.textContent = 'Retry task';
            retryBtn.addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();
                retryBtn.disabled = true;
                statusText.textContent = 'Retrying…';
                try {
                    await API.conversationAction(task.parent_conversation_id, 'retry_task', {
                        routed_task_id: task.routed_task_id,
                    });
                    statusText.textContent = 'Retry queued.';
                } catch (err) {
                    retryBtn.disabled = false;
                    statusText.textContent = 'Retry failed.';
                    UI.reportError('Failed to retry the task', err, { context: 'Task retry failed' });
                }
            });
            actions.appendChild(retryBtn);
        }
    }

    function _createBoardTaskCard(task) {
        const card = document.createElement('article');
        card.className = 'task-board-card';
        card.dataset.key = task.routed_task_id;

        const head = document.createElement('div');
        head.className = 'task-board-card-header';
        head.innerHTML = `<strong>${UI.esc(task.title || task.routed_task_id)}</strong><span class="badge badge-${UI.esc(task.status || 'queued')}">${UI.esc(task.status || 'queued')}</span>`;
        card.appendChild(head);

        const meta = document.createElement('div');
        meta.className = 'task-board-card-meta';
        meta.innerHTML = `<span>${UI.esc(task.target_display_name || task.target_agent_id || 'agent')}</span>`;
        const stamp = document.createElement('span');
        stamp.setAttribute('data-timestamp', task.updated_at || task.created_at || '');
        stamp.textContent = UI.relativeTime(task.updated_at || task.created_at || '');
        meta.appendChild(stamp);
        card.appendChild(meta);

        const summary = _taskSummary(task);
        if (summary) {
            const body = document.createElement('p');
            body.className = 'task-board-card-summary';
            body.textContent = summary.slice(0, 180);
            card.appendChild(body);
        }

        const footer = document.createElement('div');
        footer.className = 'task-board-card-footer';
        const openLink = document.createElement('a');
        openLink.href = task.parent_conversation_id ? '/ui/conversations/' + task.parent_conversation_id : '/ui/tasks';
        openLink.textContent = 'Open conversation';
        openLink.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            Router.navigate(openLink.href);
        });
        footer.appendChild(openLink);
        card.appendChild(footer);

        return card;
    }

    function renderBoard(tasks) {
        const head = document.createElement('div');
        head.className = 'task-feed-header';
        head.dataset.key = 'board-header';
        head.innerHTML = '<strong>Task board</strong><span>Grouped by current status so you can spot stalled or unhealthy work at a glance.</span>';

        const counts = {
            total: tasks.length,
            queued: tasks.filter((task) => ['queued', 'submitted', 'leased'].includes(task.status || '')).length,
            running: tasks.filter((task) => task.status === 'running').length,
            attention: tasks.filter((task) => ['failed', 'cancelled', 'timed_out'].includes(task.status || '')).length,
            done: tasks.filter((task) => task.status === 'completed').length,
        };
        const summaryStrip = document.createElement('div');
        summaryStrip.className = 'task-summary-strip';
        summaryStrip.dataset.key = 'board-summary';
        [
            ['Total', counts.total],
            ['Queued', counts.queued],
            ['Running', counts.running],
            ['Needs follow-up', counts.attention],
            ['Done', counts.done],
        ].forEach(([label, value]) => {
            const chip = document.createElement('div');
            chip.className = 'task-summary-chip';
            chip.dataset.key = String(label).toLowerCase().replace(/\s+/g, '-');
            chip.innerHTML = `<strong>${UI.esc(String(value))}</strong><span>${UI.esc(label)}</span>`;
            summaryStrip.appendChild(chip);
        });

        const board = document.createElement('div');
        board.className = 'task-board';
        board.dataset.key = 'task-board';
        const lanes = [
            ['queued', 'Queued', ['queued', 'submitted', 'leased']],
            ['running', 'Running', ['running']],
            ['attention', 'Needs follow-up', ['failed', 'cancelled', 'timed_out']],
            ['done', 'Done', ['completed']],
        ];
        lanes.forEach(([laneKey, title, statuses]) => {
            const lane = document.createElement('section');
            lane.className = 'task-lane';
            lane.dataset.key = laneKey;
            lane.dataset.lane = laneKey;

            const laneHeader = document.createElement('div');
            laneHeader.className = 'task-lane-header';
            const laneTasks = tasks.filter((task) => statuses.includes(task.status || ''));
            laneHeader.innerHTML = `<strong>${UI.esc(title)}</strong><span>${laneTasks.length}</span>`;
            lane.appendChild(laneHeader);

            const laneBody = document.createElement('div');
            laneBody.className = 'task-lane-body';
            if (!laneTasks.length) {
                laneBody.appendChild(UI.renderEmptyState('Nothing here right now.', true));
            } else {
                laneTasks.slice(0, 12).forEach((task) => laneBody.appendChild(_createBoardTaskCard(task)));
            }
            lane.appendChild(laneBody);
            board.appendChild(lane);
        });
        UI.reconcileChildren(boardShell, [head, summaryStrip, board]);
    }

    function renderList(tasks, data) {
        if (tasks.length === 0) {
            UI.reconcileChildren(listEl, [UI.renderEmptyState('No tasks match this filter.')]);
            UI.reconcileChildren(pagEl, []);
            return;
        }

        const items = tasks.map((task) => {
            const item = document.createElement('div');
            item.className = 'task-list-item';
            item.dataset.key = task.routed_task_id;

            const sub = document.createElement('span');
            const parts = [];
            if (task.origin_display_name || task.origin_agent_id) {
                parts.push('From ' + (task.origin_display_name || task.origin_agent_id));
            }
            if (task.target_display_name || task.target_agent_id) {
                parts.push('To ' + (task.target_display_name || task.target_agent_id));
            }
            if (task.updated_at) {
                parts.push(UI.relativeTime(task.updated_at));
            }
            sub.textContent = parts.join(' · ');

            const row = UI.renderListRow({
                label: task.title || task.routed_task_id,
                sublabelNode: sub,
                badgeText: task.status || 'queued',
                badgeClass: 'badge-' + (task.status || 'queued'),
                onClick: () => {
                    const nextExpanded = detail.hidden;
                    detail.hidden = !nextExpanded;
                    row.setAttribute('aria-expanded', String(nextExpanded));
                },
                className: 'task-summary-row',
            });
            row.setAttribute('aria-expanded', 'false');
            item.appendChild(row);

            const detail = document.createElement('div');
            detail.className = 'task-detail';
            detail.hidden = true;

            if (task.instructions) {
                const instrLabel = document.createElement('div');
                instrLabel.className = 'detail-label';
                instrLabel.textContent = 'Instructions';
                detail.appendChild(instrLabel);
                const instrBody = document.createElement('div');
                instrBody.className = 'detail-body';
                instrBody.textContent = task.instructions;
                detail.appendChild(instrBody);
            }

            const resultText = task.result_summary || task.result_text || task.summary || '';
            if (resultText) {
                const resultLabel = document.createElement('div');
                resultLabel.className = 'detail-label';
                resultLabel.textContent = 'Latest result';
                detail.appendChild(resultLabel);
                const resultBody = document.createElement('div');
                resultBody.className = 'detail-body';
                resultBody.textContent = resultText;
                detail.appendChild(resultBody);
            }

            if (task.parent_conversation_id) {
                const linkWrap = document.createElement('div');
                linkWrap.style.marginTop = '8px';
                const link = document.createElement('a');
                link.href = '/ui/conversations/' + task.parent_conversation_id;
                link.textContent = 'View parent conversation';
                link.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    Router.navigate('/ui/conversations/' + task.parent_conversation_id);
                });
                linkWrap.appendChild(link);
                detail.appendChild(linkWrap);
            }

            const actions = document.createElement('div');
            actions.className = 'task-action-row';
            const statusText = document.createElement('span');
            statusText.className = 'task-action-status';
            actions.appendChild(statusText);
            _attachTaskActions(actions, task, statusText);
            if (actions.childElementCount > 1) {
                detail.appendChild(actions);
            }

            item.appendChild(detail);
            return item;
        });
        UI.reconcileChildren(listEl, items);

        const wrapper = document.createElement('div');
        UI.renderPagination(wrapper, {
            hasPrev: cursorStack.length > 0,
            hasNext: !!data.has_more,
            info: '',
            onPrev: () => {
                cursor = cursorStack.pop() || 0;
                loadList();
            },
            onNext: () => {
                cursorStack.push(cursor);
                cursor = data.next_cursor;
                loadList();
            },
        });
        UI.reconcileChildren(pagEl, Array.from(wrapper.childNodes));
    }

    function loadBoard({ soft = false } = {}) {
        if (!soft || !boardLoaded) {
            UI.reconcileChildren(boardShell, UI.createSkeletonNodes(4, 'card'));
        }
        API.listTasks({ limit: 100 }).then((data) => {
            renderBoard(data.tasks || data || []);
            boardLoaded = true;
        }).catch((err) => {
            UI.reconcileChildren(boardShell, [UI.createErrorCard('Failed to load task board: ' + err.message, loadBoard)]);
        });
    }

    function loadList({ soft = false } = {}) {
        if (!soft || !listLoaded) {
            UI.reconcileChildren(listEl, UI.createSkeletonNodes(5, 'row'));
            UI.reconcileChildren(pagEl, []);
        }

        const params = { cursor, limit };
        if (currentStatus) params.status = currentStatus;

        API.listTasks(params).then((data) => {
            renderList(data.tasks || data || [], data);
            listLoaded = true;
        }).catch((err) => {
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load tasks: ' + err.message, loadList)]);
            UI.reconcileChildren(pagEl, []);
        });
    }

    loadBoard();
    loadList();

    let reloadDebounce = null;
    const unsub = WS.subscribe('tasks', () => {
        clearTimeout(reloadDebounce);
        reloadDebounce = setTimeout(() => {
            loadBoard({ soft: true });
            loadList({ soft: true });
        }, 400);
    });
    cleanups.add(() => clearTimeout(reloadDebounce));
    cleanups.add(unsub);
}
