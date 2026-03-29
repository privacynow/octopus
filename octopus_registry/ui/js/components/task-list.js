/**
 * Task view — compact routed-work queue with status filters.
 */
function renderTaskList(container) {
    const cleanups = UI.beginCleanupScope();
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }

    const limit = UI.DEFAULT_PAGE_LIMIT;
    let currentStatus = UI.readQueryParam('status', '');
    let summaryLoaded = false;
    let listLoaded = false;
    const expandedTaskIds = new Set();

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Tasks</h2>';
    container.appendChild(header);

    const summaryRail = document.createElement('section');
    summaryRail.className = 'summary-rail';
    container.appendChild(summaryRail);

    const shell = document.createElement('section');
    shell.className = 'admin-shell';
    container.appendChild(shell);

    const workbench = document.createElement('section');
    workbench.className = 'workbench-panel';
    shell.appendChild(workbench);

    const controls = document.createElement('div');
    controls.className = 'route-controls';
    workbench.appendChild(controls);

    const statuses = [
        { key: 'all', value: '', label: 'All' },
        { key: 'queued', value: 'queued', label: 'Queued' },
        { key: 'running', value: 'running', label: 'Running' },
        { key: 'completed', value: 'completed', label: 'Done' },
        { key: 'failed', value: 'failed', label: 'Needs follow-up' },
        { key: 'cancelled', value: 'cancelled', label: 'Cancelled' },
    ];
    const statusControl = UI.createSegmentedControl(statuses, (value) => applyStatusFilter(value), {
        label: 'Task status filter',
        value: currentStatus,
    });
    const statusBar = statusControl.element;
    controls.appendChild(statusBar);

    function applyStatusFilter(value) {
        currentStatus = value;
        paginator.reset();
        statusControl.setActive(currentStatus);
        UI.updateQueryParams({ status: currentStatus });
        loadList();
    }

    const listShell = document.createElement('section');
    listShell.className = 'list-shell';
    shell.appendChild(listShell);

    const listEl = document.createElement('div');
    listEl.className = 'list-container list-container-loose';
    listShell.appendChild(listEl);

    const pagEl = document.createElement('div');
    pagEl.className = 'pagination-shell';
    listShell.appendChild(pagEl);
    const paginator = UI.createCursorPaginator(pagEl, () => loadList());

    function renderSummary(summary) {
        const items = [
            {
                key: 'pending',
                value: String(summary.tasks?.pending || 0),
                label: 'Pending',
                detail: 'queued or submitted',
                href: '/ui/tasks?status=queued',
            },
            {
                key: 'running',
                value: String(summary.tasks?.running || 0),
                label: 'Running',
                detail: 'currently active',
                href: '/ui/tasks?status=running',
            },
            {
                key: 'failed',
                value: String(summary.tasks?.failed_24h || 0),
                label: 'Needs follow-up',
                detail: 'failed in the last day',
                href: '/ui/tasks?status=failed',
            },
        ];
        UI.memoizedRender(summaryRail, items, (nextItems) => nextItems.map((item) => {
            const card = UI.renderStatCard(item);
            card.dataset.key = item.key;
            return card;
        }));
    }

    function _taskSummary(task) {
        return task.result_summary || task.result_text || task.summary || task.instructions || '';
    }

    function _taskLabel(task) {
        return task.title || (task.instructions ? String(task.instructions).trim().slice(0, 72) : '') || 'Untitled task';
    }

    function _taskListSignature(tasks, data) {
        return UI.dataSignature({
            status: currentStatus,
            cursor: paginator.cursor,
            hasMore: !!(data && data.has_more),
            nextCursor: data && data.next_cursor ? String(data.next_cursor) : '',
            tasks: (tasks || []).map((task) => ({
                id: String(task.routed_task_id || ''),
                status: String(task.status || ''),
                updatedLabel: UI.relativeTime(task.updated_at || task.created_at),
                summary: String(_taskSummary(task) || ''),
                title: String(_taskLabel(task) || ''),
                origin: String(task.origin_display_name || task.origin_agent_id || ''),
                target: String(task.target_display_name || task.target_agent_id || ''),
                conversation: String(task.parent_conversation_title || task.parent_conversation_id || ''),
            })),
        });
    }

    function createTaskItem(task) {
        const item = document.createElement('article');
        item.className = 'task-item';
        item.dataset.key = task.routed_task_id;
        item.dataset.signature = UI.dataSignature({
            id: String(task.routed_task_id || ''),
            status: String(task.status || ''),
            updatedLabel: UI.relativeTime(task.updated_at || task.created_at),
            title: String(_taskLabel(task) || ''),
            summary: String(_taskSummary(task) || ''),
            origin: String(task.origin_display_name || task.origin_agent_id || ''),
            target: String(task.target_display_name || task.target_agent_id || ''),
            conversation: String(task.parent_conversation_title || task.parent_conversation_id || ''),
        });

        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'task-item-row';
        const taskId = String(task.routed_task_id || '');
        const isExpanded = expandedTaskIds.has(taskId);
        row.setAttribute('aria-expanded', String(isExpanded));

        const primary = document.createElement('div');
        primary.className = 'task-item-main';

        const title = document.createElement('strong');
        title.className = 'task-item-title';
        title.textContent = _taskLabel(task);
        primary.appendChild(title);

        const meta = document.createElement('span');
        meta.className = 'task-item-meta';
        meta.textContent = [
            UI.visibleLabel(task.target_display_name, task.target_agent_id) || 'Assigned agent',
            UI.visibleLabel(task.parent_conversation_title),
            UI.relativeTime(task.updated_at || task.created_at),
        ].filter(Boolean).join(' · ');
        primary.appendChild(meta);

        const summary = _taskSummary(task);
        if (summary && ['completed', 'failed', 'cancelled', 'timed_out'].includes(task.status || '')) {
            const preview = document.createElement('span');
            preview.className = 'task-item-preview';
            preview.textContent = summary;
            primary.appendChild(preview);
        }

        row.appendChild(primary);

        const trailing = document.createElement('div');
        trailing.className = 'task-item-trailing';
        const badge = document.createElement('span');
        badge.className = `badge badge-${task.status || 'queued'}`;
        badge.textContent = task.status || 'queued';
        trailing.appendChild(badge);
        row.appendChild(trailing);

        item.appendChild(row);

        const detail = document.createElement('div');
        detail.className = 'task-item-detail';
        detail.hidden = !isExpanded;

        if (summary) {
            const summaryBlock = document.createElement('div');
            summaryBlock.className = 'task-item-summary';
            summaryBlock.textContent = summary;
            detail.appendChild(summaryBlock);
        }

        const facts = document.createElement('div');
        facts.className = 'metadata-grid';
        [
            ['Origin', UI.visibleLabel(task.origin_display_name, task.origin_agent_id) || '—'],
            ['Target', UI.visibleLabel(task.target_display_name, task.target_agent_id) || '—'],
            ['Conversation', UI.visibleLabel(task.parent_conversation_title) || 'Current thread'],
        ].forEach(([label, value]) => {
            const fact = document.createElement('div');
            fact.className = 'metadata-item';
            fact.innerHTML = `<span>${UI.esc(label)}</span><strong>${UI.esc(value)}</strong>`;
            facts.appendChild(fact);
        });
        detail.appendChild(facts);

        const actions = document.createElement('div');
        actions.className = 'task-action-row';
        const openLink = document.createElement('a');
        openLink.href = task.parent_conversation_id ? '/ui/conversations/' + task.parent_conversation_id : '/ui/tasks';
        openLink.className = 'btn btn-sm';
        openLink.textContent = 'Open conversation';
        openLink.addEventListener('click', (e) => {
            e.stopPropagation();
        });
        actions.appendChild(openLink);
        const taskActions = UI.createTaskActionButtons(
            task.routed_task_id,
            task.parent_conversation_id,
            task.status || '',
            null,
        );
        if (taskActions.element.childElementCount > 1) {
            Array.from(taskActions.element.childNodes).forEach((node) => actions.appendChild(node));
        }
        detail.appendChild(actions);

        item.appendChild(detail);

        row.addEventListener('click', () => {
            const nextExpanded = detail.hidden;
            detail.hidden = !nextExpanded;
            row.setAttribute('aria-expanded', String(nextExpanded));
            if (nextExpanded) {
                expandedTaskIds.add(taskId);
            } else {
                expandedTaskIds.delete(taskId);
            }
        });

        return item;
    }

    function renderList(tasks, data) {
        const nextSignature = _taskListSignature(tasks, data);

        if (!tasks.length) {
            expandedTaskIds.clear();
            UI.clearMemoizedRender(listEl);
            UI.reconcileChildren(listEl, [UI.renderEmptyState(currentStatus ? 'No tasks in this state.' : 'No tasks yet.', true)]);
            paginator.clear();
            return;
        }

        const visibleTaskIds = new Set(tasks.map((task) => String(task.routed_task_id || '')));
        Array.from(expandedTaskIds).forEach((taskId) => {
            if (!visibleTaskIds.has(taskId)) expandedTaskIds.delete(taskId);
        });

        UI.memoizedRender(listEl, { signature: nextSignature, tasks }, (state) => state.tasks.map(createTaskItem), {
            signatureFn(state) {
                return state.signature;
            },
        });
        paginator.render({ hasMore: !!data.has_more, nextCursor: data.next_cursor });
        listLoaded = true;
    }

    async function loadSummary({ soft = false } = {}) {
        try {
            const summary = await API.getSummary();
            renderSummary(summary);
            summaryLoaded = true;
        } catch (err) {
            if (soft && summaryLoaded) {
                UI.reportError('Failed to refresh task summary', err, { context: 'Task summary soft refresh failed' });
                return;
            }
            UI.clearMemoizedRender(summaryRail);
            UI.reconcileChildren(summaryRail, [UI.createErrorCard('Failed to load task summary: ' + err.message, loadSummary)]);
        }
    }

    async function loadList({ soft = false } = {}) {
        const params = { cursor: paginator.cursor, limit };
        if (currentStatus) params.status = currentStatus;
        try {
            const data = await API.listTasks(params);
            renderList(data.tasks || data || [], data);
        } catch (err) {
            if (soft && listLoaded) {
                UI.reportError('Failed to refresh tasks', err, { context: 'Task list soft refresh failed' });
                return;
            }
            UI.clearMemoizedRender(listEl);
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load tasks: ' + err.message, loadList)]);
            paginator.clear();
        }
    }

    UI.subscribeWithRefresh(cleanups, 'tasks', () => {
        loadSummary({ soft: true });
        loadList({ soft: true });
    }, 350);

    statusControl.setActive(currentStatus);
    container.__routeReady = Promise.allSettled([loadSummary(), loadList()]);
}
