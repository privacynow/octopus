/**
 * Dashboard — dense operator overview with immediate follow-up paths.
 */
function renderDashboard(container) {
    const cleanups = UI.beginCleanupScope();
    const RECENT_COMPLETED_WINDOW_MS = 24 * 60 * 60 * 1000;
    const TASK_GROUP_LIMIT = 3;
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Dashboard</h2>';
    container.appendChild(header);

    const content = document.createElement('div');
    content.className = 'dashboard-shell';
    container.appendChild(content);

    const dashboardGrid = document.createElement('div');
    dashboardGrid.className = 'dashboard-grid';
    dashboardGrid.dataset.key = 'dashboard-grid';
    content.appendChild(dashboardGrid);

    const summaryRailHost = document.createElement('section');
    summaryRailHost.className = 'summary-rail';
    summaryRailHost.dataset.key = 'summary-rail';
    dashboardGrid.appendChild(summaryRailHost);

    const dashboardBoard = document.createElement('div');
    dashboardBoard.className = 'dashboard-board';
    dashboardBoard.dataset.key = 'dashboard-board';
    dashboardGrid.appendChild(dashboardBoard);

    const primaryColumn = document.createElement('div');
    primaryColumn.className = 'dashboard-column';
    primaryColumn.dataset.key = 'dashboard-column-primary';
    dashboardBoard.appendChild(primaryColumn);

    const secondaryColumn = document.createElement('div');
    secondaryColumn.className = 'dashboard-column';
    secondaryColumn.dataset.key = 'dashboard-column-secondary';
    dashboardBoard.appendChild(secondaryColumn);

    const needsAttentionHost = document.createElement('div');
    needsAttentionHost.dataset.key = 'needs-attention-host';
    primaryColumn.appendChild(needsAttentionHost);

    const tasksHost = document.createElement('div');
    tasksHost.dataset.key = 'tasks-host';
    primaryColumn.appendChild(tasksHost);

    const conversationsHost = document.createElement('div');
    conversationsHost.dataset.key = 'open-conversations-host';
    secondaryColumn.appendChild(conversationsHost);

    const agentsHost = document.createElement('div');
    agentsHost.dataset.key = 'agents-host';
    secondaryColumn.appendChild(agentsHost);

    function createSection(key, title, href, rows, emptyText) {
        const section = document.createElement('section');
        section.className = 'workspace-section';
        section.dataset.key = key;

        const head = document.createElement('div');
        head.className = 'section-header';
        const titleEl = document.createElement('strong');
        titleEl.textContent = title;
        head.appendChild(titleEl);
        if (href && rows.length) {
            const link = document.createElement('a');
            link.href = href;
            link.className = 'section-link';
            link.textContent = 'View all';
            head.appendChild(link);
        }
        section.appendChild(head);

        const body = document.createElement('div');
        body.className = 'list-container';
        UI.reconcileChildren(body, rows.length ? rows : [UI.renderEmptyState(emptyText, true)]);
        section.appendChild(body);
        return section;
    }

    function createGroupedSection(key, title, href, groups, emptyText) {
        const section = document.createElement('section');
        section.className = 'workspace-section';
        section.dataset.key = key;

        const head = document.createElement('div');
        head.className = 'section-header';
        const titleEl = document.createElement('strong');
        titleEl.textContent = title;
        head.appendChild(titleEl);
        if (href && (groups || []).some((group) => (group.rows || []).length)) {
            const link = document.createElement('a');
            link.href = href;
            link.className = 'section-link';
            link.textContent = 'View all';
            head.appendChild(link);
        }
        section.appendChild(head);

        const body = document.createElement('div');
        body.className = 'list-container';
        const nodes = [];
        (groups || []).forEach((group) => {
            const rows = group.rows || [];
            if (!rows.length) {
                return;
            }
            const label = document.createElement('div');
            label.className = 'list-section-label';
            label.dataset.key = `${key}-${group.key}-label`;
            label.textContent = group.label;
            nodes.push(label, ...rows);
        });
        UI.reconcileChildren(body, nodes.length ? nodes : [UI.renderEmptyState(emptyText, true)]);
        section.appendChild(body);
        return section;
    }

    function createRow({ key, title, subtitle, badge, badgeClass = '', href }) {
        const row = UI.renderListRow({
            href,
            label: title,
            sublabel: subtitle,
            badgeText: badge,
            badgeClass,
        });
        if (key) row.dataset.key = key;
        return row;
    }

    function buildNeedsAttention(approvalsData, tasksData, agentsData) {
        const rows = [];
        (approvalsData.approvals || []).slice(0, 3).forEach((item) => {
            rows.push(createRow({
                key: `approval:${item.request_id || item.conversation_id}`,
                title: item.conversation_title || UI.visibleLabel(item.target_display_name, item.target_agent_id) || 'Approval waiting',
                subtitle: [
                    UI.visibleLabel(item.target_display_name, item.target_agent_id) || 'agent',
                    item.expires_at ? `expires ${UI.formatApprovalTime(item.expires_at)}` : UI.relativeTime(item.created_at),
                ].filter(Boolean).join(' · '),
                badge: 'Approval',
                badgeClass: 'badge-queued',
                href: '/ui/approvals',
            }));
        });
        (tasksData.tasks || []).slice(0, 3).forEach((item) => {
            rows.push(createRow({
                key: `task:${item.routed_task_id}`,
                title: item.title || 'Task needs follow-up',
                subtitle: [
                    UI.visibleLabel(item.target_display_name, item.target_agent_id) || 'agent',
                    UI.relativeTime(item.updated_at || item.created_at),
                ].filter(Boolean).join(' · '),
                badge: item.status || 'failed',
                badgeClass: 'badge-' + (item.status || 'failed'),
                href: item.parent_conversation_id ? '/ui/conversations/' + item.parent_conversation_id : '/ui/tasks',
            }));
        });
        const riskyAgents = (agentsData.agents || agentsData || []).filter((agent) => ['degraded', 'disconnected'].includes(agent.connectivity_state || ''));
        riskyAgents.slice(0, 2).forEach((item) => {
            rows.push(createRow({
                key: `agent:${item.agent_id}`,
                title: item.display_name || item.slug || 'Agent',
                subtitle: [
                    item.role || 'agent',
                    item.provider || '',
                    item.last_heartbeat_at ? UI.relativeTime(item.last_heartbeat_at) : '',
                ].filter(Boolean).join(' · '),
                badge: item.connectivity_state || 'connected',
                badgeClass: 'badge-' + (item.connectivity_state || 'connected'),
                href: '/ui/agents/' + item.agent_id,
            }));
        });

        return rows.slice(0, 6);
    }

    function coerceTaskList(payload) {
        return payload && Array.isArray(payload.tasks)
            ? payload.tasks
            : Array.isArray(payload)
                ? payload
                : [];
    }

    function sortTasks(items) {
        return [...(items || [])].sort((a, b) => String(b.updated_at || b.created_at || '').localeCompare(String(a.updated_at || a.created_at || '')));
    }

    async function loadFollowUpTasks() {
        const [failed, cancelled, timedOut] = await Promise.all([
            API.listTasks({ limit: 6, status: 'failed' }),
            API.listTasks({ limit: 6, status: 'cancelled' }).catch(() => ({ tasks: [] })),
            API.listTasks({ limit: 6, status: 'timed_out' }).catch(() => ({ tasks: [] })),
        ]);
        const seen = new Set();
        const tasks = sortTasks([
            ...coerceTaskList(failed),
            ...coerceTaskList(cancelled),
            ...coerceTaskList(timedOut),
        ]).filter((item) => {
            const taskId = String(item.routed_task_id || '');
            if (!taskId || seen.has(taskId)) {
                return false;
            }
            seen.add(taskId);
            return true;
        });
        return { tasks };
    }

    function taskRowsState(items) {
        return (items || []).slice(0, TASK_GROUP_LIMIT).map((item) => ({
            id: String(item.routed_task_id || ''),
            title: String(item.title || ''),
            status: String(item.status || ''),
            updatedLabel: UI.relativeTime(item.updated_at || item.created_at),
            target: String(item.target_display_name || item.target_agent_id || ''),
            conversation: String(item.parent_conversation_id || ''),
        }));
    }

    function createTaskRows(items, fallbackTitle) {
        return (items || []).slice(0, TASK_GROUP_LIMIT).map((item) => createRow({
            key: item.routed_task_id,
            title: item.title || fallbackTitle,
            subtitle: [
                UI.visibleLabel(item.target_display_name, item.target_agent_id) || 'agent',
                UI.relativeTime(item.updated_at || item.created_at),
            ].filter(Boolean).join(' · '),
            badge: item.status || 'task',
            badgeClass: 'badge-' + (item.status || 'task'),
            href: item.parent_conversation_id ? '/ui/conversations/' + item.parent_conversation_id : '/ui/tasks',
        }));
    }

    let hasLoaded = false;
    const dashboardState = {
        summary: null,
        approvals: { approvals: [] },
        conversations: { conversations: [] },
        followUpTasks: { tasks: [] },
        runningTasks: { tasks: [] },
        recentCompletedTasks: { tasks: [] },
        agents: { agents: [] },
    };

    function recentCompletedSinceIso() {
        return new Date(Date.now() - RECENT_COMPLETED_WINDOW_MS).toISOString();
    }

    function renderSummaryRail(summary) {
        const items = [
            {
                key: 'open-conversations',
                value: String(summary.conversations?.open || 0),
                label: 'Open conversations',
                detail: `${summary.conversations?.pending_approvals || 0} waiting on review`,
                href: '/ui/conversations?status=open',
            },
            {
                key: 'running-tasks',
                value: String(summary.tasks?.running || 0),
                label: 'Running tasks',
                detail: `${summary.tasks?.pending || 0} pending`,
                href: '/ui/tasks?status=running',
            },
            {
                key: 'needs-follow-up',
                value: String(summary.tasks?.failed_24h || 0),
                label: 'Needs follow-up',
                detail: 'failed in the last day',
                href: '/ui/tasks?status=failed',
            },
            {
                key: 'connected-agents',
                value: String(summary.agents?.connected || 0),
                label: 'Connected agents',
                detail: `${(summary.agents?.degraded || 0) + (summary.agents?.disconnected || 0)} unhealthy`,
                href: '/ui/agents',
            },
        ];
        UI.memoizedRender(summaryRailHost, items, (nextItems) => nextItems.map((item) => {
            const card = UI.renderStatCard(item);
            card.dataset.key = item.key;
            return card;
        }));
    }

    function renderNeedsAttentionSection() {
        const approvals = (dashboardState.approvals.approvals || []).slice(0, 3).map((item) => ({
            id: String(item.request_id || item.conversation_id || ''),
            title: String(item.conversation_title || ''),
            target: String(item.target_display_name || item.target_agent_id || ''),
            createdLabel: item.created_at ? UI.relativeTime(item.created_at) : '',
            expiresLabel: item.expires_at ? UI.formatApprovalTime(item.expires_at) : '',
        }));
        const failedTasks = (dashboardState.followUpTasks.tasks || []).slice(0, 3).map((item) => ({
            id: String(item.routed_task_id || ''),
            title: String(item.title || ''),
            target: String(item.target_display_name || item.target_agent_id || ''),
            status: String(item.status || ''),
            updatedLabel: UI.relativeTime(item.updated_at || item.created_at),
        }));
        const riskyAgents = ((dashboardState.agents.agents || dashboardState.agents || []).filter(
            (agent) => ['degraded', 'disconnected'].includes(agent.connectivity_state || ''),
        )).slice(0, 2).map((item) => ({
            id: String(item.agent_id || ''),
            display: String(item.display_name || item.slug || ''),
            status: String(item.connectivity_state || ''),
            heartbeatLabel: item.last_heartbeat_at ? UI.relativeTime(item.last_heartbeat_at) : '',
        }));
        const needsAttentionRows = buildNeedsAttention(
            dashboardState.approvals,
            { tasks: dashboardState.followUpTasks.tasks || dashboardState.followUpTasks || [] },
            dashboardState.agents,
        );
        UI.memoizedRender(needsAttentionHost, { approvals, failedTasks, riskyAgents }, () => [
            createSection(
                'needs-attention',
                'Needs attention',
                '/ui/approvals',
                needsAttentionRows,
                'Nothing urgent right now.',
            ),
        ]);
    }

    function renderConversationSection() {
        const conversationsData = dashboardState.conversations;
        const rowsState = (conversationsData.conversations || []).slice(0, 6).map((item) => ({
            id: String(item.conversation_id || ''),
            title: String(item.title || ''),
            status: String(item.status || ''),
            updatedLabel: UI.relativeTime(item.updated_at || item.created_at),
            target: String(item.target_display_name || item.target_agent_id || ''),
            type: String(item.conversation_type || 'conversation'),
        }));
        const conversationRows = (conversationsData.conversations || []).slice(0, 6).map((item) => createRow({
            key: item.conversation_id,
            title: item.title || UI.visibleLabel(item.target_display_name, item.target_agent_id) || 'Conversation',
            subtitle: [
                UI.visibleLabel(item.target_display_name, item.target_agent_id) || 'agent',
                UI.relativeTime(item.updated_at || item.created_at),
            ].join(' · '),
            badge: item.status || 'open',
            badgeClass: 'badge-' + (item.status || 'open'),
            href: '/ui/conversations/' + item.conversation_id,
        }));
        UI.memoizedRender(conversationsHost, rowsState, () => [
            createSection(
                'open-conversations',
                'Open conversations',
                '/ui/conversations?status=open',
                conversationRows,
                'No open conversations.',
            ),
        ]);
    }

    function renderTaskSection() {
        const runningTasks = coerceTaskList(dashboardState.runningTasks);
        const followUpTasks = coerceTaskList(dashboardState.followUpTasks);
        const recentCompletedTasks = coerceTaskList(dashboardState.recentCompletedTasks);
        const rowsState = {
            running: taskRowsState(runningTasks),
            followUp: taskRowsState(followUpTasks),
            completed: taskRowsState(recentCompletedTasks),
        };
        const groups = [
            {
                key: 'running',
                label: 'Active',
                rows: createTaskRows(runningTasks, 'Running task'),
            },
            {
                key: 'follow-up',
                label: 'Needs follow-up',
                rows: createTaskRows(followUpTasks, 'Task needs follow-up'),
            },
            {
                key: 'completed',
                label: 'Recently completed',
                rows: createTaskRows(recentCompletedTasks, 'Completed task'),
            },
        ];
        UI.memoizedRender(tasksHost, rowsState, () => [
            createGroupedSection(
                'tasks',
                'Tasks',
                '/ui/tasks',
                groups,
                'No recent task activity.',
            ),
        ]);
    }

    function renderAgentSection() {
        const agentsData = dashboardState.agents;
        const rowsState = (agentsData.agents || agentsData || []).slice(0, 6).map((item) => ({
            id: String(item.agent_id || ''),
            display: String(item.display_name || item.slug || ''),
            state: String(item.connectivity_state || ''),
            heartbeatLabel: item.last_heartbeat_at ? UI.relativeTime(item.last_heartbeat_at) : '',
            role: String(item.role || ''),
            provider: String(item.provider || ''),
        }));
        const agentRows = (agentsData.agents || agentsData || []).slice(0, 6).map((item) => createRow({
            key: item.agent_id,
            title: item.display_name || item.slug || 'Agent',
            subtitle: [
                item.role || 'agent',
                item.provider || '',
                item.last_heartbeat_at ? UI.relativeTime(item.last_heartbeat_at) : '',
            ].filter(Boolean).join(' · '),
            badge: item.connectivity_state || 'connected',
            badgeClass: 'badge-' + (item.connectivity_state || 'connected'),
            href: '/ui/agents/' + item.agent_id,
        }));
        UI.memoizedRender(agentsHost, rowsState, () => [
            createSection(
                'agents',
                'Agents',
                '/ui/agents',
                agentRows,
                'No agents available.',
            ),
        ]);
    }

    function renderDashboardView() {
        const summary = dashboardState.summary || {};
        renderSummaryRail(summary);
        renderNeedsAttentionSection();
        renderTaskSection();
        renderConversationSection();
        renderAgentSection();
    }

    function applySnapshot({ summary, approvals, conversations, followUpTasks, runningTasks, recentCompletedTasks, agents }) {
        if (!dashboardGrid.isConnected) {
            UI.reconcileChildren(content, [dashboardGrid]);
        }
        dashboardState.summary = summary;
        dashboardState.approvals = approvals;
        dashboardState.conversations = conversations;
        dashboardState.followUpTasks = { tasks: followUpTasks.tasks || followUpTasks || [] };
        dashboardState.runningTasks = { tasks: runningTasks.tasks || runningTasks || [] };
        dashboardState.recentCompletedTasks = { tasks: recentCompletedTasks.tasks || recentCompletedTasks || [] };
        dashboardState.agents = agents;
        renderDashboardView();
    }

    async function loadSnapshot({ soft = false } = {}) {
        try {
            const [summary, approvals, conversations, followUpTasks, runningTasks, recentCompletedTasks, agents] = await Promise.all([
                API.getSummary(),
                API.listApprovals({ limit: 4 }),
                API.listConversations({ limit: 6, status: 'open' }),
                loadFollowUpTasks(),
                API.listTasks({ limit: 6, status: 'running' }).catch(() => ({ tasks: [] })),
                API.listTasks({ limit: 6, status: 'completed', completed_since_iso: recentCompletedSinceIso() }).catch(() => ({ tasks: [] })),
                API.listAgents({ limit: 8 }),
            ]);
            applySnapshot({ summary, approvals, conversations, followUpTasks, runningTasks, recentCompletedTasks, agents });
            hasLoaded = true;
        } catch (err) {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh dashboard', err, { context: 'Dashboard soft refresh failed' });
                return;
            }
            UI.clearMemoizedRender(summaryRailHost);
            UI.clearMemoizedRender(needsAttentionHost);
            UI.clearMemoizedRender(tasksHost);
            UI.clearMemoizedRender(conversationsHost);
            UI.clearMemoizedRender(agentsHost);
            UI.reconcileChildren(content, [UI.createErrorCard('Failed to load dashboard: ' + err.message, loadSnapshot)]);
        }
    }

    let snapshotRefreshInflight = null;
    let snapshotRefreshQueued = false;
    function refreshSnapshot({ soft = false } = {}) {
        if (snapshotRefreshInflight) {
            snapshotRefreshQueued = true;
            return snapshotRefreshInflight;
        }
        snapshotRefreshInflight = loadSnapshot({ soft }).finally(() => {
            snapshotRefreshInflight = null;
            if (snapshotRefreshQueued) {
                snapshotRefreshQueued = false;
                void refreshSnapshot({ soft: true });
            }
        });
        return snapshotRefreshInflight;
    }

    UI.subscribeWithRefresh(cleanups, 'summary', () => refreshSnapshot({ soft: true }), 350);
    UI.subscribeWithRefresh(cleanups, 'agents', () => refreshSnapshot({ soft: true }), 350);
    UI.subscribeWithRefresh(cleanups, 'conversations', () => refreshSnapshot({ soft: true }), 350);
    UI.subscribeWithRefresh(cleanups, 'tasks', () => refreshSnapshot({ soft: true }), 350);
    UI.subscribeWithRefresh(cleanups, 'approvals', () => refreshSnapshot({ soft: true }), 350);

    container.__routeReady = refreshSnapshot();
}
