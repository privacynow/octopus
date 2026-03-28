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

    let cursor = 0;
    let cursorStack = [];
    const limit = UI.DEFAULT_PAGE_LIMIT;
    let currentStatus = UI.readQueryParam('status', '');
    let summaryLoaded = false;
    let listLoaded = false;
    let lastSummarySignature = '';
    let lastTaskListSignature = '';
    const expandedTaskIds = new Set();

    function isOpaqueIdentifier(value) {
        const text = String(value || '').trim();
        if (!text) return false;
        if (/^[0-9a-f]{24,}$/i.test(text)) return true;
        if (/^[0-9a-f]{8,}-[0-9a-f-]{12,}$/i.test(text)) return true;
        if (text.length >= 24 && !/[A-Z]/.test(text) && /^[a-z0-9._:-]+$/i.test(text)) return true;
        return false;
    }

    function visibleLabel(...candidates) {
        for (const candidate of candidates) {
            const text = String(candidate || '').trim();
            if (!text) continue;
            if (isOpaqueIdentifier(text)) continue;
            return text;
        }
        return '';
    }

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Tasks</h2>';
    container.appendChild(header);

    const summaryRail = document.createElement('section');
    summaryRail.className = 'summary-rail';
    container.appendChild(summaryRail);

    const workbench = document.createElement('section');
    workbench.className = 'workbench-panel';
    container.appendChild(workbench);

    const controls = document.createElement('div');
    controls.className = 'route-controls';
    workbench.appendChild(controls);

    const statusBar = document.createElement('div');
    statusBar.className = 'segmented-control';
    statusBar.setAttribute('role', 'tablist');
    statusBar.setAttribute('aria-label', 'Task status filter');
    controls.appendChild(statusBar);

    const statuses = [
        ['all', '', 'All'],
        ['queued', 'queued', 'Queued'],
        ['running', 'running', 'Running'],
        ['completed', 'completed', 'Done'],
        ['failed', 'failed', 'Needs follow-up'],
        ['cancelled', 'cancelled', 'Cancelled'],
    ];

    function applyStatusFilter(value) {
        currentStatus = value;
        cursor = 0;
        cursorStack = [];
        syncStatusButtons();
        UI.updateQueryParams({ status: currentStatus });
        loadList();
    }

    statuses.forEach(([key, value, label]) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'segmented-control-btn';
        btn.dataset.key = key;
        btn.dataset.value = value;
        btn.textContent = label;
        btn.setAttribute('role', 'tab');
        btn.setAttribute('aria-selected', String(currentStatus === value));
        btn.tabIndex = currentStatus === value ? 0 : -1;
        if (currentStatus === value) btn.classList.add('active');
        btn.addEventListener('click', () => applyStatusFilter(value));
        statusBar.appendChild(btn);
    });
    UI.bindSegmentedControlKeyboard(statusBar, (target) => applyStatusFilter(target.dataset.value || ''));

    const listShell = document.createElement('section');
    listShell.className = 'list-shell';
    workbench.appendChild(listShell);

    const listEl = document.createElement('div');
    listEl.className = 'list-container list-container-loose';
    listShell.appendChild(listEl);

    const pagEl = document.createElement('div');
    pagEl.className = 'pagination-shell';
    listShell.appendChild(pagEl);

    function syncStatusButtons() {
        statusBar.querySelectorAll('.segmented-control-btn').forEach((btn) => {
            const match = statuses.find(([key]) => key === btn.dataset.key);
            const active = !!match && currentStatus === match[1];
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-selected', String(active));
            btn.tabIndex = active ? 0 : -1;
        });
    }

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
        const signature = UI.dataSignature(items);
        if (summaryLoaded && signature === lastSummarySignature) {
            return;
        }
        UI.reconcileChildren(summaryRail, items.map((item) => {
            const card = UI.renderStatCard(item);
            card.dataset.key = item.key;
            return card;
        }));
        lastSummarySignature = signature;
    }

    function _taskSummary(task) {
        return task.result_summary || task.result_text || task.summary || task.instructions || '';
    }

    function _taskLabel(task) {
        return task.title || (task.instructions ? String(task.instructions).trim().slice(0, 72) : '') || 'Untitled task';
    }

    function _taskListSignature(tasks, data) {
        return JSON.stringify({
            status: currentStatus,
            cursor,
            hasMore: !!(data && data.has_more),
            nextCursor: data && data.next_cursor ? String(data.next_cursor) : '',
            tasks: (tasks || []).map((task) => ({
                id: String(task.routed_task_id || ''),
                status: String(task.status || ''),
                updatedAt: String(task.updated_at || ''),
                createdAt: String(task.created_at || ''),
                summary: String(_taskSummary(task) || ''),
                title: String(_taskLabel(task) || ''),
                origin: String(task.origin_display_name || task.origin_agent_id || ''),
                target: String(task.target_display_name || task.target_agent_id || ''),
                conversation: String(task.parent_conversation_title || task.parent_conversation_id || ''),
            })),
        });
    }

    function _attachTaskActions(actions, task, statusText) {
        if (['queued', 'submitted', 'leased', 'running'].includes(task.status || '')) {
            const cancelBtn = document.createElement('button');
            cancelBtn.type = 'button';
            cancelBtn.className = 'btn btn-sm btn-danger';
            cancelBtn.textContent = 'Cancel';
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
            retryBtn.textContent = 'Retry';
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

    function createTaskItem(task) {
        const item = document.createElement('article');
        item.className = 'task-item';
        item.dataset.key = task.routed_task_id;

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
            visibleLabel(task.target_display_name, task.target_agent_id) || 'Assigned agent',
            visibleLabel(task.parent_conversation_title),
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
            ['Origin', visibleLabel(task.origin_display_name, task.origin_agent_id) || '—'],
            ['Target', visibleLabel(task.target_display_name, task.target_agent_id) || '—'],
            ['Conversation', visibleLabel(task.parent_conversation_title) || 'Current thread'],
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

        const statusText = document.createElement('span');
        statusText.className = 'task-action-status';
        actions.appendChild(statusText);
        _attachTaskActions(actions, task, statusText);
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

    function renderPaginationState({ hasPrev, hasNext, onPrev, onNext }) {
        const wrapper = document.createElement('div');
        UI.renderPagination(wrapper, {
            hasPrev,
            hasNext,
            info: '',
            onPrev,
            onNext,
        });
        UI.reconcileChildren(pagEl, Array.from(wrapper.childNodes));
    }

    function renderList(tasks, data) {
        const nextSignature = _taskListSignature(tasks, data);
        if (listLoaded && nextSignature === lastTaskListSignature) {
            renderPaginationState({
                hasPrev: cursorStack.length > 0,
                hasNext: !!data.has_more,
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
            return;
        }

        if (!tasks.length) {
            expandedTaskIds.clear();
            UI.reconcileChildren(listEl, [UI.renderEmptyState(currentStatus ? 'No tasks in this state.' : 'No tasks yet.', true)]);
            UI.reconcileChildren(pagEl, []);
            lastTaskListSignature = nextSignature;
            return;
        }

        const visibleTaskIds = new Set(tasks.map((task) => String(task.routed_task_id || '')));
        Array.from(expandedTaskIds).forEach((taskId) => {
            if (!visibleTaskIds.has(taskId)) expandedTaskIds.delete(taskId);
        });

        UI.reconcileChildren(listEl, tasks.map(createTaskItem));
        renderPaginationState({
            hasPrev: cursorStack.length > 0,
            hasNext: !!data.has_more,
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
        listLoaded = true;
        lastTaskListSignature = nextSignature;
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
            UI.reconcileChildren(summaryRail, [UI.createErrorCard('Failed to load task summary: ' + err.message, loadSummary)]);
        }
    }

    async function loadList({ soft = false } = {}) {
        const params = { cursor, limit };
        if (currentStatus) params.status = currentStatus;
        try {
            const data = await API.listTasks(params);
            renderList(data.tasks || data || [], data);
        } catch (err) {
            if (soft && listLoaded) {
                UI.reportError('Failed to refresh tasks', err, { context: 'Task list soft refresh failed' });
                return;
            }
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load tasks: ' + err.message, loadList)]);
            UI.reconcileChildren(pagEl, []);
        }
    }

    let reloadDebounce = null;
    cleanups.add(WS.subscribe('tasks', () => {
        if (UI.isBackgrounded()) return;
        clearTimeout(reloadDebounce);
        reloadDebounce = setTimeout(() => {
            loadSummary({ soft: true });
            loadList({ soft: true });
        }, 350);
    }));

    syncStatusButtons();
    container.__routeReady = Promise.allSettled([loadSummary(), loadList()]);

    cleanups.add(() => clearTimeout(reloadDebounce));
}
