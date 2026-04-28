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
    let currentProtocolRunId = UI.readQueryParam('protocol_run_id', '');
    let currentTaskId = UI.readQueryParam('task_id', '');
    let includeGenerated = UI.readQueryParam('include_generated', '') === '1';
    let summaryLoaded = false;
    let listLoaded = false;
    const expandedTaskIds = new Set(currentTaskId ? [currentTaskId] : []);
    const taskDetails = new Map();
    const taskDetailErrors = new Map();
    const taskDetailsLoading = new Set();
    let currentTasks = [];
    let currentListData = null;

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = currentProtocolRunId
        ? '<h2>Run stage tasks</h2><p>Protocol-generated tasks are shown as children of this run.</p>'
        : '<h2>Delegations</h2><p>Standalone work delegated from one agent or collaborator to another.</p>';
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

    const lineageBanner = document.createElement('div');
    lineageBanner.className = 'task-lineage-banner';
    workbench.appendChild(lineageBanner);

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
    const generatedToggle = document.createElement('a');
    UI.updateGeneratedAuditToggleLink(generatedToggle, includeGenerated, 'delegations');
    controls.appendChild(generatedToggle);

    function applyStatusFilter(value) {
        currentStatus = value;
        paginator.reset();
        statusControl.setActive(currentStatus);
        _writeState();
        loadList();
    }

    function _writeState() {
        UI.updateQueryParams({
            status: currentStatus || '',
            protocol_run_id: currentProtocolRunId || '',
            task_id: currentTaskId || '',
            include_generated: includeGenerated ? '1' : '',
        });
        UI.updateGeneratedAuditToggleLink(generatedToggle, includeGenerated, 'delegations');
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

    function _taskStatusHref(status) {
        const params = new URLSearchParams();
        if (status) params.set('status', status);
        if (currentProtocolRunId) params.set('protocol_run_id', currentProtocolRunId);
        const query = params.toString();
        return query ? `/ui/tasks?${query}` : '/ui/tasks';
    }

    function renderSummary(summary) {
        const items = [
            {
                key: 'pending',
                value: String(summary.tasks?.pending || 0),
                label: 'Pending',
                detail: 'queued or submitted',
                href: _taskStatusHref('queued'),
            },
            {
                key: 'running',
                value: String(summary.tasks?.running || 0),
                label: 'Running',
                detail: 'currently active',
                href: _taskStatusHref('running'),
            },
            {
                key: 'failed',
                value: String(summary.tasks?.failed_24h || 0),
                label: 'Needs follow-up',
                detail: 'failed in the last day',
                href: _taskStatusHref('failed'),
            },
        ];
        UI.memoizedRender(summaryRail, items, (nextItems) => nextItems.map((item) => {
            const card = UI.renderStatCard(item);
            card.dataset.key = item.key;
            return card;
        }));
    }

    function _taskSummary(task) {
        return UI.compactMarkdownReferences(task.result_summary || task.result_text || task.summary || task.instructions || '');
    }

    function _taskRunHref(task) {
        const runId = String(task.protocol_run_id || '').trim();
        if (!runId) return '';
        return `/ui/runs?run_id=${encodeURIComponent(runId)}`;
    }

    function _renderProtocolLineageBanner() {
        if (!currentProtocolRunId) {
            UI.reconcileChildren(lineageBanner, []);
            lineageBanner.hidden = true;
            return;
        }
        lineageBanner.hidden = false;
        const note = document.createElement('div');
        note.className = 'task-lineage-banner-copy';
        note.innerHTML = [
            '<strong>Run filter active</strong>',
            `<span>Showing only routed tasks generated by run ${UI.esc(currentProtocolRunId)}.</span>`,
            '<span>Each task below is one stage execution inside that run, with its outputs and file evidence when available.</span>',
        ].join('');
        const actions = document.createElement('div');
        actions.className = 'task-action-row';
        const openRun = document.createElement('a');
        openRun.href = `/ui/runs?run_id=${encodeURIComponent(currentProtocolRunId)}`;
        openRun.className = 'btn btn-sm';
        openRun.textContent = 'Open run';
        actions.appendChild(openRun);
        const clearFilter = document.createElement('button');
        clearFilter.type = 'button';
        clearFilter.className = 'btn btn-sm';
        clearFilter.textContent = 'Clear filter';
        clearFilter.addEventListener('click', () => {
            currentProtocolRunId = '';
            currentTaskId = '';
            expandedTaskIds.clear();
            paginator.reset();
            _writeState();
            loadSummary();
            loadList();
        });
        actions.appendChild(clearFilter);
        UI.reconcileChildren(lineageBanner, [note, actions]);
    }

    async function loadTaskDetail(taskId) {
        if (!taskId || taskDetailsLoading.has(taskId) || taskDetails.has(taskId)) return;
        taskDetailsLoading.add(taskId);
        taskDetailErrors.delete(taskId);
        try {
            const detail = await API.getTask(taskId);
            taskDetails.set(taskId, detail);
        } catch (err) {
            taskDetailErrors.set(taskId, err);
            UI.reportError('Failed to load task detail', err, {
                context: 'Task detail load failed',
            });
        } finally {
            taskDetailsLoading.delete(taskId);
            renderList(currentTasks, currentListData);
        }
    }

    function _taskLabel(task) {
        return task.title || (task.instructions ? String(task.instructions).trim().slice(0, 72) : '') || 'Untitled task';
    }

    function _taskListSignature(tasks, data) {
        return UI.dataSignature({
            status: currentStatus,
            protocolRunId: currentProtocolRunId,
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
                protocolRunId: String(task.protocol_run_id || ''),
                stageKey: String(task.stage_key || ''),
                expanded: expandedTaskIds.has(String(task.routed_task_id || '')),
                detailState: _taskDetailStateSignature(String(task.routed_task_id || '')),
            })),
        });
    }

    function _taskDetailStateSignature(taskId) {
        if (taskDetailsLoading.has(taskId)) return 'loading';
        if (taskDetailErrors.has(taskId)) return 'error';
        if (taskDetails.has(taskId)) return UI.dataSignature(taskDetails.get(taskId));
        return '';
    }

    function createTaskItem(task) {
        const item = document.createElement('article');
        item.className = 'task-item';
        item.dataset.key = task.routed_task_id;
        const taskId = String(task.routed_task_id || '');
        const isExpanded = expandedTaskIds.has(taskId);
        item.dataset.signature = UI.dataSignature({
            id: taskId,
            status: String(task.status || ''),
            updatedLabel: UI.relativeTime(task.updated_at || task.created_at),
            title: String(_taskLabel(task) || ''),
            summary: String(_taskSummary(task) || ''),
            origin: String(task.origin_display_name || task.origin_agent_id || ''),
            target: String(task.target_display_name || task.target_agent_id || ''),
            conversation: String(task.parent_conversation_title || task.parent_conversation_id || ''),
            protocolRunId: String(task.protocol_run_id || ''),
            stageKey: String(task.stage_key || ''),
            expanded: isExpanded,
            detailState: _taskDetailStateSignature(taskId),
        });

        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'task-item-row';
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
            task.stage_key ? `stage ${task.stage_key}` : '',
            task.protocol_run_id ? `run ${String(task.protocol_run_id).slice(0, 8)}` : '',
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

        const detailTask = taskDetails.get(taskId) || task;
        const facts = UI.renderMetadataGrid([
            { label: 'Origin', value: UI.visibleLabel(task.origin_display_name, task.origin_agent_id) || '—' },
            { label: 'Target', value: UI.visibleLabel(task.target_display_name, task.target_agent_id) || '—' },
            { label: 'Conversation', value: UI.visibleLabel(task.parent_conversation_title) || 'Current thread' },
            ...(task.protocol_run_id
                ? [
                    { label: 'Run', value: task.protocol_run_id },
                    { label: 'Stage', value: task.stage_key || '—' },
                    { label: 'Participant', value: task.participant_key || '—' },
                    { label: 'Workspace', value: detailTask.working_dir || detailTask.project_id_override || 'Default bot workspace' },
                ]
                : []),
        ], { compact: true });
        detail.appendChild(facts);

        if (task.protocol_run_id) {
            const lineageSummary = document.createElement('div');
            lineageSummary.className = 'task-item-summary';
            lineageSummary.textContent = [
                `Run ${task.protocol_run_id}`,
                task.stage_key ? `stage ${task.stage_key}` : '',
                task.participant_key ? `participant ${task.participant_key}` : '',
            ].filter(Boolean).join(' · ');
            detail.appendChild(lineageSummary);
        }

        const inlineDetailPayload = taskDetails.get(taskId) || (task.request || task.result ? task : null);
        if (isExpanded) {
            if (!inlineDetailPayload && !taskDetailsLoading.has(taskId)) {
                void loadTaskDetail(taskId);
            }
            const detailError = taskDetailErrors.get(taskId);
            if (detailError) {
                detail.appendChild(UI.createErrorCard('Failed to load artifact evidence for this task.', () => {
                    taskDetails.delete(taskId);
                    taskDetailErrors.delete(taskId);
                    void loadTaskDetail(taskId);
                }));
            } else if (taskDetailsLoading.has(taskId) && !inlineDetailPayload) {
                detail.appendChild(UI.renderEmptyState('Loading task lineage…', true));
            } else if (inlineDetailPayload) {
                const detailPayload = inlineDetailPayload;
                const artifactEvidence = UI.taskArtifactEvidence(detailPayload);
                const expectedOutputs = artifactEvidence?.expectedOutputs || [];
                const recordedArtifacts = artifactEvidence?.recordedArtifacts || [];
                const recordedByKey = new Set(recordedArtifacts.map((artifact) => String(artifact?.artifact_key || '').trim()).filter(Boolean));
                const pendingExpected = expectedOutputs.filter((item) => {
                    const artifactKey = String(item?.artifact_key || '').trim();
                    return artifactKey && !recordedByKey.has(artifactKey);
                });

                if (recordedArtifacts.length) {
                    const outputsLabel = document.createElement('div');
                    outputsLabel.className = 'detail-label';
                    outputsLabel.textContent = 'Outputs';
                    detail.appendChild(outputsLabel);

                    const outputsList = document.createElement('div');
                    outputsList.className = 'task-artifact-list';
                    const outputNodes = recordedArtifacts.map((artifact) =>
                        UI.createTaskArtifactListRow(detailPayload, artifact, UI.taskExpectedOutput(expectedOutputs, artifact?.artifact_key)));
                    UI.reconcileChildren(outputsList, outputNodes);
                    detail.appendChild(outputsList);
                }

                if (pendingExpected.length) {
                    const expectedLabel = document.createElement('div');
                    expectedLabel.className = 'detail-label';
                    expectedLabel.textContent = 'Declared outputs';
                    detail.appendChild(expectedLabel);

                    const expectedList = document.createElement('div');
                    const expectedNodes = pendingExpected.map((artifact) =>
                        UI.createPendingTaskArtifactListRow(detailPayload, artifact));
                    UI.reconcileChildren(expectedList, expectedNodes);
                    detail.appendChild(expectedList);
                }
            }
        }

        const actions = document.createElement('div');
        actions.className = 'task-action-row';
        const openLink = document.createElement('a');
        openLink.href = task.parent_conversation_id
            ? UI.conversationHref(task.parent_conversation_id, { operational: Boolean(task.protocol_run_id) })
            : '/ui/tasks';
        openLink.className = 'btn btn-sm';
        openLink.textContent = task.protocol_run_id ? 'Open activity' : 'Open conversation';
        openLink.addEventListener('click', (e) => {
            e.stopPropagation();
        });
        actions.appendChild(openLink);
        if (task.protocol_run_id) {
            const runLink = document.createElement('a');
            runLink.href = _taskRunHref(task);
            runLink.className = 'btn btn-sm';
            runLink.textContent = 'Open run';
            actions.appendChild(runLink);
        }
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
            if (nextExpanded) {
                Array.from(listEl.querySelectorAll('.task-item-row[aria-expanded="true"]')).forEach((expandedRow) => {
                    if (expandedRow === row) return;
                    expandedRow.setAttribute('aria-expanded', 'false');
                    const expandedDetail = expandedRow.closest('.task-item')?.querySelector('.task-item-detail');
                    if (expandedDetail) expandedDetail.hidden = true;
                });
                detail.hidden = false;
                row.setAttribute('aria-expanded', 'true');
                expandedTaskIds.clear();
                expandedTaskIds.add(taskId);
                currentTaskId = taskId;
                _writeState();
                if (!taskDetails.has(taskId) && !(task.request || task.result)) {
                    void loadTaskDetail(taskId);
                }
                renderList(currentTasks, currentListData);
            } else {
                detail.hidden = true;
                row.setAttribute('aria-expanded', 'false');
                expandedTaskIds.delete(taskId);
                if (currentTaskId === taskId) {
                    currentTaskId = '';
                    _writeState();
                }
                renderList(currentTasks, currentListData);
            }
        });

        return item;
    }

    function _visibleTask(task) {
        if (currentProtocolRunId) {
            return String(task.protocol_run_id || '') === String(currentProtocolRunId || '');
        }
        return !task.protocol_run_id && !UI.isDefaultHiddenRecord(task);
    }

    function _coerceTaskRows(payload) {
        return Array.isArray(payload?.tasks) ? payload.tasks : (Array.isArray(payload) ? payload : []);
    }

    function renderList(tasks, data) {
        currentTasks = Array.isArray(tasks) ? tasks : [];
        currentListData = data;
        const nextSignature = _taskListSignature(tasks, data);
        _renderProtocolLineageBanner();

        if (!tasks.length) {
            expandedTaskIds.clear();
            UI.clearMemoizedRender(listEl);
            UI.reconcileChildren(listEl, [UI.renderEmptyState(
                currentProtocolRunId
                    ? 'No tasks recorded for this run yet.'
                    : currentStatus
                        ? 'No standalone delegations in this state.'
                        : 'No standalone delegations yet.',
                true,
            )]);
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
            const statusGroups = {
                pending: ['queued', 'submitted', 'leased'],
                running: ['running'],
                failed_24h: ['failed', 'timed_out'],
            };
            const entries = await Promise.all(Object.entries(statusGroups).map(async ([key, statuses]) => {
                const payloads = await Promise.all(statuses.map((status) => {
                    const params = {
                        limit: UI.DEFAULT_PAGE_LIMIT,
                        status,
                        include_generated: currentProtocolRunId || includeGenerated ? '1' : '0',
                    };
                    if (currentProtocolRunId) params.protocol_run_id = currentProtocolRunId;
                    return API.listTasks(params).catch(() => ({ tasks: [] }));
                }));
                const seen = new Set();
                const tasks = payloads
                    .flatMap((payload) => _coerceTaskRows(payload))
                    .filter((task) => {
                        const taskId = String(task.routed_task_id || '');
                        if (!taskId || seen.has(taskId) || !_visibleTask(task)) return false;
                        seen.add(taskId);
                        return true;
                    });
                return [key, tasks.length];
            }));
            renderSummary({ tasks: Object.fromEntries(entries) });
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
        const params = {
            cursor: paginator.cursor,
            limit,
            include_generated: currentProtocolRunId || includeGenerated ? '1' : '0',
        };
        if (currentStatus) params.status = currentStatus;
        if (currentProtocolRunId) params.protocol_run_id = currentProtocolRunId;
        try {
            const data = await API.listTasks(params);
            const rawTasks = data.tasks || data || [];
            const visibleTasks = rawTasks.filter((task) => _visibleTask(task));
            if (currentTaskId && !visibleTasks.some((task) => String(task.routed_task_id || '') === String(currentTaskId || ''))) {
                const selectedHidden = rawTasks.find((task) => String(task.routed_task_id || '') === String(currentTaskId || ''));
                if (selectedHidden) visibleTasks.unshift(selectedHidden);
            }
            renderList(visibleTasks, { ...data, tasks: visibleTasks });
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
