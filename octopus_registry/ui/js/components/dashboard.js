/**
 * Dashboard — dense operator overview with immediate follow-up paths.
 */
function renderDashboard(container) {
    const cleanups = UI.beginCleanupScope();
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

    const workGrid = document.createElement('div');
    workGrid.className = 'dashboard-work-grid';
    workGrid.dataset.key = 'work-grid';
    dashboardGrid.appendChild(workGrid);

    const needsAttentionHost = document.createElement('div');
    needsAttentionHost.dataset.key = 'needs-attention-host';
    workGrid.appendChild(needsAttentionHost);

    const conversationsHost = document.createElement('div');
    conversationsHost.dataset.key = 'open-conversations-host';
    workGrid.appendChild(conversationsHost);

    const runningTasksHost = document.createElement('div');
    runningTasksHost.dataset.key = 'running-tasks-host';
    workGrid.appendChild(runningTasksHost);

    const agentsHost = document.createElement('div');
    agentsHost.dataset.key = 'agents-host';
    workGrid.appendChild(agentsHost);

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

    let hasLoaded = false;
    let lastSummarySignature = '';
    let lastNeedsAttentionSignature = '';
    let lastConversationSignature = '';
    let lastRunningSignature = '';
    let lastAgentSignature = '';
    const dashboardState = {
        summary: null,
        approvals: { approvals: [] },
        conversations: { conversations: [] },
        failedTasks: { tasks: [] },
        runningTasks: { tasks: [] },
        agents: { agents: [] },
    };

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
        const signature = UI.dataSignature(items);
        if (signature === lastSummarySignature) return;
        UI.reconcileChildren(summaryRailHost, items.map((item) => {
            const card = UI.renderStatCard(item);
            card.dataset.key = item.key;
            return card;
        }));
        lastSummarySignature = signature;
    }

    function renderNeedsAttentionSection() {
        const approvals = (dashboardState.approvals.approvals || []).slice(0, 3).map((item) => ({
            id: String(item.request_id || item.conversation_id || ''),
            title: String(item.conversation_title || ''),
            target: String(item.target_display_name || item.target_agent_id || ''),
            createdLabel: item.created_at ? UI.relativeTime(item.created_at) : '',
            expiresLabel: item.expires_at ? UI.formatApprovalTime(item.expires_at) : '',
        }));
        const failedTasks = (dashboardState.failedTasks.tasks || []).slice(0, 3).map((item) => ({
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
            { tasks: dashboardState.failedTasks.tasks || dashboardState.failedTasks || [] },
            dashboardState.agents,
        );
        const signature = UI.dataSignature({ approvals, failedTasks, riskyAgents });
        if (signature === lastNeedsAttentionSignature) return;
        UI.reconcileChildren(needsAttentionHost, needsAttentionRows.length ? [createSection(
                'needs-attention',
                'Needs attention',
                '/ui/approvals',
                needsAttentionRows,
                'Nothing urgent right now.',
            )] : []);
        lastNeedsAttentionSignature = signature;
    }

    function renderConversationSection() {
        const conversationsData = dashboardState.conversations;
        const signature = UI.dataSignature((conversationsData.conversations || []).slice(0, 6).map((item) => ({
            id: String(item.conversation_id || ''),
            title: String(item.title || ''),
            status: String(item.status || ''),
            updatedLabel: UI.relativeTime(item.updated_at || item.created_at),
            target: String(item.target_display_name || item.target_agent_id || ''),
            type: String(item.conversation_type || 'conversation'),
        })));
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
        if (signature === lastConversationSignature) return;
        UI.reconcileChildren(conversationsHost, conversationRows.length ? [createSection(
                'open-conversations',
                'Open conversations',
                '/ui/conversations?status=open',
                conversationRows,
                'No open conversations.',
            )] : []);
        lastConversationSignature = signature;
    }

    function renderRunningSection() {
        const tasksData = {
            tasks: dashboardState.runningTasks.tasks || dashboardState.runningTasks || [],
            running_tasks: dashboardState.runningTasks.tasks || dashboardState.runningTasks || [],
        };
        const signature = UI.dataSignature((tasksData.running_tasks || tasksData.tasks || []).slice(0, 6).map((item) => ({
            id: String(item.routed_task_id || ''),
            title: String(item.title || ''),
            status: String(item.status || ''),
            updatedLabel: UI.relativeTime(item.updated_at || item.created_at),
            target: String(item.target_display_name || item.target_agent_id || ''),
            conversation: String(item.parent_conversation_id || ''),
        })));
        const runningRows = (tasksData.running_tasks || tasksData.tasks || []).slice(0, 6).map((item) => createRow({
            key: item.routed_task_id,
            title: item.title || 'Running task',
            subtitle: [
                UI.visibleLabel(item.target_display_name, item.target_agent_id) || 'agent',
                UI.relativeTime(item.updated_at || item.created_at),
            ].filter(Boolean).join(' · '),
            badge: item.status || 'running',
            badgeClass: 'badge-' + (item.status || 'running'),
            href: item.parent_conversation_id ? '/ui/conversations/' + item.parent_conversation_id : '/ui/tasks',
        }));
        if (signature === lastRunningSignature) return;
        UI.reconcileChildren(runningTasksHost, runningRows.length ? [createSection(
                'running-tasks',
                'Running tasks',
                '/ui/tasks?status=running',
                runningRows,
                'No running tasks.',
            )] : []);
        lastRunningSignature = signature;
    }

    function renderAgentSection() {
        const agentsData = dashboardState.agents;
        const signature = UI.dataSignature((agentsData.agents || agentsData || []).slice(0, 6).map((item) => ({
            id: String(item.agent_id || ''),
            display: String(item.display_name || item.slug || ''),
            state: String(item.connectivity_state || ''),
            heartbeatLabel: item.last_heartbeat_at ? UI.relativeTime(item.last_heartbeat_at) : '',
            role: String(item.role || ''),
            provider: String(item.provider || ''),
        })));
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
        if (signature === lastAgentSignature) return;
        UI.reconcileChildren(agentsHost, agentRows.length ? [createSection(
                'agents',
                'Agents',
                '/ui/agents',
                agentRows,
                'No agents available.',
            )] : []);
        lastAgentSignature = signature;
    }

    function renderDashboardView() {
        const summary = dashboardState.summary || {};
        renderSummaryRail(summary);
        renderNeedsAttentionSection();
        renderConversationSection();
        renderRunningSection();
        renderAgentSection();
    }

    function applySnapshot({ summary, approvals, conversations, failedTasks, runningTasks, agents }) {
        if (!dashboardGrid.isConnected) {
            UI.reconcileChildren(content, [dashboardGrid]);
        }
        dashboardState.summary = summary;
        dashboardState.approvals = approvals;
        dashboardState.conversations = conversations;
        dashboardState.failedTasks = { tasks: failedTasks.tasks || failedTasks || [] };
        dashboardState.runningTasks = { tasks: runningTasks.tasks || runningTasks || [] };
        dashboardState.agents = agents;
        renderDashboardView();
    }

    async function loadSnapshot({ soft = false } = {}) {
        try {
            const [summary, approvals, conversations, failedTasks, runningTasks, agents] = await Promise.all([
                API.getSummary(),
                API.listApprovals({ limit: 4 }),
                API.listConversations({ limit: 6, status: 'open' }),
                API.listTasks({ limit: 6, status: 'failed' }),
                API.listTasks({ limit: 6, status: 'running' }).catch(() => ({ tasks: [] })),
                API.listAgents({ limit: 8 }),
            ]);
            applySnapshot({ summary, approvals, conversations, failedTasks, runningTasks, agents });
            hasLoaded = true;
        } catch (err) {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh dashboard', err, { context: 'Dashboard soft refresh failed' });
                return;
            }
            UI.reconcileChildren(content, [UI.createErrorCard('Failed to load dashboard: ' + err.message, loadSnapshot)]);
        }
    }

    async function refreshSummaryOnly({ soft = false } = {}) {
        try {
            dashboardState.summary = await API.getSummary();
            renderSummaryRail(dashboardState.summary);
        } catch (err) {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh dashboard summary', err, { context: 'Dashboard summary refresh failed' });
            }
        }
    }

    async function refreshAgents({ soft = false } = {}) {
        try {
            const [summary, agents] = await Promise.all([
                API.getSummary(),
                API.listAgents({ limit: 8 }),
            ]);
            dashboardState.summary = summary;
            dashboardState.agents = agents;
            renderSummaryRail(summary);
            renderNeedsAttentionSection();
            renderAgentSection();
        } catch (err) {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh dashboard agents', err, { context: 'Dashboard agent refresh failed' });
            }
        }
    }

    async function refreshConversations({ soft = false } = {}) {
        try {
            const [summary, conversations] = await Promise.all([
                API.getSummary(),
                API.listConversations({ limit: 6, status: 'open' }),
            ]);
            dashboardState.summary = summary;
            dashboardState.conversations = conversations;
            renderSummaryRail(summary);
            renderConversationSection();
        } catch (err) {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh dashboard conversations', err, { context: 'Dashboard conversation refresh failed' });
            }
        }
    }

    async function refreshTasks({ soft = false } = {}) {
        try {
            const [summary, failedTasks, runningTasks] = await Promise.all([
                API.getSummary(),
                API.listTasks({ limit: 6, status: 'failed' }),
                API.listTasks({ limit: 6, status: 'running' }).catch(() => ({ tasks: [] })),
            ]);
            dashboardState.summary = summary;
            dashboardState.failedTasks = { tasks: failedTasks.tasks || failedTasks || [] };
            dashboardState.runningTasks = { tasks: runningTasks.tasks || runningTasks || [] };
            renderSummaryRail(summary);
            renderNeedsAttentionSection();
            renderRunningSection();
        } catch (err) {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh dashboard tasks', err, { context: 'Dashboard task refresh failed' });
            }
        }
    }

    async function refreshApprovals({ soft = false } = {}) {
        try {
            const [summary, approvals] = await Promise.all([
                API.getSummary(),
                API.listApprovals({ limit: 4 }),
            ]);
            dashboardState.summary = summary;
            dashboardState.approvals = approvals;
            renderSummaryRail(summary);
            renderNeedsAttentionSection();
        } catch (err) {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh dashboard approvals', err, { context: 'Dashboard approval refresh failed' });
            }
        }
    }

    const reloadDebounces = Object.create(null);

    function scheduleRefresh(key, loader) {
        if (UI.isBackgrounded()) return;
        clearTimeout(reloadDebounces[key]);
        reloadDebounces[key] = setTimeout(() => {
            void loader({ soft: true });
        }, 350);
    }

    cleanups.add(WS.subscribe('summary', () => scheduleRefresh('summary', refreshSummaryOnly)));
    cleanups.add(WS.subscribe('agents', () => scheduleRefresh('agents', refreshAgents)));
    cleanups.add(WS.subscribe('conversations', () => scheduleRefresh('conversations', refreshConversations)));
    cleanups.add(WS.subscribe('tasks', () => scheduleRefresh('tasks', refreshTasks)));
    cleanups.add(WS.subscribe('approvals', () => scheduleRefresh('approvals', refreshApprovals)));

    container.__routeReady = loadSnapshot();
    cleanups.add(() => {
        Object.values(reloadDebounces).forEach((timer) => clearTimeout(timer));
    });
}
