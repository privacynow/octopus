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

    const approvalsHost = document.createElement('div');
    approvalsHost.dataset.key = 'approvals-host';
    primaryColumn.appendChild(approvalsHost);

    const tasksHost = document.createElement('div');
    tasksHost.dataset.key = 'tasks-host';
    primaryColumn.appendChild(tasksHost);

    const conversationsHost = document.createElement('div');
    conversationsHost.dataset.key = 'open-conversations-host';
    secondaryColumn.appendChild(conversationsHost);

    const agentsHost = document.createElement('div');
    agentsHost.dataset.key = 'agents-host';
    secondaryColumn.appendChild(agentsHost);

    const protocolIssuesHost = document.createElement('div');
    protocolIssuesHost.dataset.key = 'protocol-issues-host';
    secondaryColumn.appendChild(protocolIssuesHost);

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

    function executionState(agent) {
        return String((agent && agent.execution_state) || 'healthy').trim() || 'healthy';
    }

    function executionFaultBadge(agent) {
        if (executionState(agent) !== 'faulted') {
            return null;
        }
        const badge = document.createElement('span');
        badge.className = 'badge badge-faulted';
        badge.textContent = 'faulted';
        if (agent && agent.execution_fault_detail) {
            badge.title = String(agent.execution_fault_detail);
        }
        return badge;
    }

    function createRow({ key, title, subtitle, badge, badgeClass = '', href, trailing = null }) {
        const row = UI.renderListRow({
            href,
            label: title,
            sublabel: subtitle,
            badgeText: badge,
            badgeClass,
            trailing,
        });
        if (key) row.dataset.key = key;
        return row;
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

    async function loadTasksByStatus(statuses) {
        const payloads = await Promise.all(
            (statuses || []).map((status) => API.listTasks({ limit: 6, status }).catch(() => ({ tasks: [] }))),
        );
        const seen = new Set();
        const tasks = sortTasks([
            ...payloads.flatMap((payload) => coerceTaskList(payload)),
        ]).filter((item) => {
            const taskId = String(item.routed_task_id || '');
            if (!taskId || seen.has(taskId)) {
                return false;
            }
            seen.add(taskId);
            return !item.protocol_run_id && !UI.isDefaultHiddenRecord(item);
        });
        return { tasks };
    }

    async function loadActiveTasks() {
        return loadTasksByStatus(['queued', 'submitted', 'leased', 'running']);
    }

    async function loadFollowUpTasks() {
        return loadTasksByStatus(['failed', 'cancelled', 'timed_out']);
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
            href: item.parent_conversation_id
                ? UI.conversationHref(item.parent_conversation_id, { operational: Boolean(item.protocol_run_id) })
                : '/ui/tasks',
        }));
    }

    let hasLoaded = false;
    const dashboardState = {
        summary: null,
        approvals: { approvals: [] },
        conversations: { conversations: [] },
        followUpTasks: { tasks: [] },
        activeTasks: { tasks: [] },
        recentCompletedTasks: { tasks: [] },
        agents: { agents: [] },
        protocolIssues: { issues: [] },
    };

    function recentCompletedSinceIso() {
        return new Date(Date.now() - RECENT_COMPLETED_WINDOW_MS).toISOString();
    }

    function renderSummaryRail(summary) {
        const promptTokens = Number(summary.usage_24h?.prompt_tokens || 0);
        const completionTokens = Number(summary.usage_24h?.completion_tokens || 0);
        const cachedPromptTokens = Number(summary.usage_24h?.cached_prompt_tokens || 0);
        const cachedCompletionTokens = Number(summary.usage_24h?.cached_completion_tokens || 0);
        const cachedPromptAvailable = summary.usage_24h?.cached_prompt_tokens_available === true;
        const cachedCompletionAvailable = summary.usage_24h?.cached_completion_tokens_available === true;
        const totalTokens = promptTokens + completionTokens;
        const unhealthyAgents = Number(summary.agents?.degraded || 0)
            + Number(summary.agents?.disconnected || 0)
            + Number(summary.agents?.execution_faulted || 0);
        const costAvailable = summary.usage_24h?.cost_available !== false;
        let tokenDetail = `${promptTokens.toLocaleString()} in · ${completionTokens.toLocaleString()} out`;
        if (cachedPromptAvailable || cachedCompletionAvailable) {
            const detailParts = [tokenDetail];
            if (cachedPromptAvailable) {
                detailParts.push(`${cachedPromptTokens.toLocaleString()} cached in`);
            }
            if (cachedCompletionAvailable) {
                detailParts.push(`${cachedCompletionTokens.toLocaleString()} cached out`);
            }
            tokenDetail = detailParts.join(' · ');
        }
        const items = [
            {
                key: 'queued-backlog',
                value: String(summary.tasks?.pending || 0),
                label: 'Queued backlog',
                detail: `${summary.tasks?.running || 0} running now`,
                href: '/ui/runs',
            },
            {
                key: 'unhealthy-agents',
                value: String(unhealthyAgents),
                label: 'Unhealthy agents',
                detail: `${summary.agents?.connected || 0} connected · ${summary.agents?.execution_faulted || 0} execution faulted`,
                href: '/ui/agents',
            },
            {
                key: 'protocol-runs',
                value: String(summary.protocols?.runs_active || 0),
                label: 'Active protocol runs',
                detail: [
                    `${summary.protocols?.runs_blocked || 0} blocked`,
                    `${summary.protocols?.runs_contract_invalid || 0} invalid contracts`,
                    `${summary.protocols?.overdue_timeouts || 0} overdue timeouts`,
                    `${Math.round(Number(summary.protocols?.completion_rate_24h || 0) * 100)}% completion · 24h`,
                    `${summary.protocols?.operator_interventions_24h || 0} interventions · 24h`,
                ].join(' · '),
                href: '/ui/runs',
            },
            {
                key: 'protocol-definitions',
                value: String(summary.protocols?.definitions_published || 0),
                label: 'Published protocols',
                detail: `${summary.protocols?.definitions_total || 0} total definitions`,
                href: '/ui/protocols',
            },
            {
                key: 'tokens-24h',
                value: totalTokens.toLocaleString(),
                label: 'Tokens · 24h',
                detail: tokenDetail,
                href: '/ui/usage',
            },
            {
                key: 'cost-24h',
                value: costAvailable ? ('$' + Number(summary.usage_24h?.cost_usd || 0).toFixed(4)) : '—',
                label: costAvailable ? 'Usage cost · 24h' : 'Usage cost unavailable',
                detail: costAvailable
                    ? `${summary.conversations?.active || 0} active conversations`
                    : 'Codex does not report execution cost',
                href: '/ui/usage',
            },
        ];
        UI.memoizedRender(summaryRailHost, items, (nextItems) => nextItems.map((item) => {
            const card = UI.renderStatCard(item);
            card.dataset.key = item.key;
            return card;
        }));
    }

    function renderApprovalSection() {
        const approvals = (dashboardState.approvals.approvals || []).slice(0, 6).map((item) => ({
            id: String(item.request_id || item.conversation_id || ''),
            title: String(item.conversation_title || ''),
            target: String(item.target_display_name || item.target_agent_id || ''),
            createdLabel: item.created_at ? UI.relativeTime(item.created_at) : '',
            expiresLabel: item.expires_at ? UI.formatApprovalTime(item.expires_at) : '',
        }));
        const approvalRows = (dashboardState.approvals.approvals || []).slice(0, 6).map((item) => createRow({
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
        if (!approvalRows.length) {
            UI.clearMemoizedRender(approvalsHost);
            UI.reconcileChildren(approvalsHost, []);
            return;
        }
        UI.memoizedRender(approvalsHost, approvals, () => [
            createSection(
                'approvals',
                'Approvals',
                '/ui/approvals',
                approvalRows,
                'Nothing waiting on review.',
            ),
        ]);
    }

    function renderConversationSection() {
        const conversationsData = {
            conversations: UI.defaultVisibleRecords(dashboardState.conversations.conversations || [], { includeHidden: false }),
        };
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
            href: UI.conversationHref(item.conversation_id, {
                conversationType: item.conversation_type,
            }),
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
        const visibleDelegations = (payload) => coerceTaskList(payload)
            .filter((item) => !item.protocol_run_id && !UI.isDefaultHiddenRecord(item));
        const activeTasks = visibleDelegations(dashboardState.activeTasks);
        const followUpTasks = visibleDelegations(dashboardState.followUpTasks);
        const recentCompletedTasks = visibleDelegations(dashboardState.recentCompletedTasks);
        const rowsState = {
            active: taskRowsState(activeTasks),
            followUp: taskRowsState(followUpTasks),
            completed: taskRowsState(recentCompletedTasks),
        };
        const groups = [
            {
                key: 'active',
                label: 'Active',
                rows: createTaskRows(activeTasks, 'Active task'),
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
                'Work needing attention',
                '/ui/runs',
                groups,
                'No recent task activity.',
            ),
        ]);
    }

    function renderAgentSection() {
        const agentsData = {
            agents: UI.defaultVisibleRecords(dashboardState.agents.agents || dashboardState.agents || [], { includeHidden: false }),
        };
        const rowsState = (agentsData.agents || agentsData || []).slice(0, 6).map((item) => ({
            id: String(item.agent_id || ''),
            display: String(item.display_name || item.slug || ''),
            state: String(item.connectivity_state || ''),
            execution: executionState(item),
            executionDetail: String(item.execution_fault_detail || ''),
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
                executionState(item) === 'faulted' ? 'execution faulted' : '',
            ].filter(Boolean).join(' · '),
            badge: item.connectivity_state || 'connected',
            badgeClass: 'badge-' + (item.connectivity_state || 'connected'),
            href: '/ui/agents/' + item.agent_id,
            trailing: executionFaultBadge(item),
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

    function renderProtocolIssuesSection() {
        const issues = UI.defaultVisibleRecords(dashboardState.protocolIssues.issues || [], { includeHidden: false }).slice(0, 6);
        const rowsState = issues.map((item) => ({
            runId: String(item.protocol_run_id || ''),
            kind: String(item.issue_kind || ''),
            code: String(item.issue_code || ''),
            stage: String(item.stage_key || ''),
            updatedLabel: item.updated_at ? UI.relativeTime(item.updated_at) : '',
        }));
        const issueRows = issues.map((item) => createRow({
            key: `protocol-issue:${item.protocol_run_id}:${item.issue_kind}:${item.stage_execution_id || ''}`,
            title: item.protocol_display_name || item.protocol_id || 'Protocol issue',
            subtitle: [
                item.stage_key ? `stage ${item.stage_key}` : '',
                item.issue_detail || item.issue_code || '',
            ].filter(Boolean).join(' · '),
            badge: item.issue_kind || 'issue',
            badgeClass: 'badge-blocked',
            href: item.protocol_run_id
                ? `/ui/runs?run_id=${encodeURIComponent(item.protocol_run_id)}&issue_kind=${encodeURIComponent(item.issue_kind || 'all')}`
                : '/ui/runs?issue_kind=all',
        }));
        UI.memoizedRender(protocolIssuesHost, rowsState, () => [
            createSection(
                'protocol-issues',
                'Protocol issues',
                '/ui/runs?issue_kind=all',
                issueRows,
                'No protocol issues detected.',
            ),
        ]);
    }

    function renderDashboardView() {
        const summary = dashboardState.summary || {};
        renderSummaryRail(summary);
        renderApprovalSection();
        renderTaskSection();
        renderConversationSection();
        renderAgentSection();
        renderProtocolIssuesSection();
    }

    function applySnapshot({ summary, approvals, conversations, followUpTasks, activeTasks, recentCompletedTasks, agents, protocolIssues }) {
        if (!dashboardGrid.isConnected) {
            UI.reconcileChildren(content, [dashboardGrid]);
        }
        dashboardState.summary = summary;
        dashboardState.approvals = approvals;
        dashboardState.conversations = conversations;
        dashboardState.followUpTasks = { tasks: followUpTasks.tasks || followUpTasks || [] };
        dashboardState.activeTasks = { tasks: activeTasks.tasks || activeTasks || [] };
        dashboardState.recentCompletedTasks = { tasks: recentCompletedTasks.tasks || recentCompletedTasks || [] };
        dashboardState.agents = agents;
        dashboardState.protocolIssues = { issues: protocolIssues.issues || protocolIssues || [] };
        renderDashboardView();
    }

    async function loadSnapshot({ soft = false } = {}) {
        try {
            const [summary, approvals, conversations, followUpTasks, activeTasks, recentCompletedTasks, agents, protocolIssues] = await Promise.all([
                API.getSummary(),
                API.listApprovals({ limit: 4 }),
                API.listConversations({ limit: 6, status: 'open' }),
                loadFollowUpTasks(),
                loadActiveTasks(),
                API.listTasks({ limit: 6, status: 'completed', completed_since_iso: recentCompletedSinceIso() }).catch(() => ({ tasks: [] })),
                API.listAgents({ limit: 8 }),
                API.listProtocolIssues({ limit: 6 }).catch(() => ({ issues: [] })),
            ]);
            applySnapshot({ summary, approvals, conversations, followUpTasks, activeTasks, recentCompletedTasks, agents, protocolIssues });
            hasLoaded = true;
        } catch (err) {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh dashboard', err, { context: 'Dashboard soft refresh failed' });
                return;
            }
            UI.clearMemoizedRender(summaryRailHost);
            UI.clearMemoizedRender(approvalsHost);
            UI.clearMemoizedRender(tasksHost);
            UI.clearMemoizedRender(conversationsHost);
            UI.clearMemoizedRender(agentsHost);
            UI.clearMemoizedRender(protocolIssuesHost);
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
    UI.subscribeWithRefresh(cleanups, 'protocols', () => refreshSnapshot({ soft: true }), 350);

    container.__routeReady = refreshSnapshot();
}
