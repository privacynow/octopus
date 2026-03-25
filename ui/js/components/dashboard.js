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

    function createSection(key, title, href, rows, emptyText) {
        const section = document.createElement('section');
        section.className = 'workspace-section';
        section.dataset.key = key;

        const head = document.createElement('div');
        head.className = 'section-header';
        const titleEl = document.createElement('strong');
        titleEl.textContent = title;
        head.appendChild(titleEl);
        if (href) {
            const link = document.createElement('a');
            link.href = href;
            link.className = 'section-link';
            link.textContent = 'View all';
            head.appendChild(link);
        }
        section.appendChild(head);

        const body = document.createElement('div');
        body.className = 'list-container';
        if (!rows.length) {
            UI.reconcileChildren(body, [UI.renderEmptyState(emptyText, true)]);
        } else {
            UI.reconcileChildren(body, rows);
        }
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

    function buildNeedsAttention(summary, approvalsData, tasksData, agentsData) {
        const rows = [];
        (approvalsData.approvals || []).slice(0, 3).forEach((item) => {
            rows.push(createRow({
                key: `approval:${item.request_id || item.conversation_id}`,
                title: item.conversation_title || item.conversation_id,
                subtitle: [
                    item.target_display_name || item.target_agent_id || 'agent',
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
                title: item.title || item.routed_task_id,
                subtitle: [
                    item.target_display_name || item.target_agent_id || 'agent',
                    UI.relativeTime(item.updated_at || item.created_at),
                ].filter(Boolean).join(' · '),
                badge: item.status || 'failed',
                badgeClass: 'badge-' + (item.status || 'failed'),
                href: item.parent_conversation_id ? '/ui/conversations/' + item.parent_conversation_id : '/ui/tasks',
            }));
        });
        const riskyAgents = (agentsData.agents || agentsData || []).filter((agent) => ['degraded', 'disconnected', 'offline'].includes(agent.connectivity_state || ''));
        riskyAgents.slice(0, 2).forEach((item) => {
            rows.push(createRow({
                key: `agent:${item.agent_id}`,
                title: item.display_name || item.slug || item.agent_id,
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

        if (!rows.length && (summary.tasks?.running || 0) > 0) {
            rows.push(createRow({
                key: 'running-work',
                title: 'Running work looks healthy',
                subtitle: `${summary.tasks?.running || 0} routed task(s) currently running`,
                badge: 'Running',
                badgeClass: 'badge-running',
                href: '/ui/tasks?status=running',
            }));
        }

        return rows.slice(0, 6);
    }

    function renderDashboardView(summary, approvalsData, conversationsData, tasksData, agentsData) {
        const shell = document.createElement('div');
        shell.className = 'dashboard-grid';
        shell.dataset.key = 'dashboard-grid';

        const summaryRail = document.createElement('section');
        summaryRail.className = 'summary-rail';
        summaryRail.dataset.key = 'summary-rail';
        [
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
        ].forEach((item) => {
            const card = UI.renderStatCard(item);
            card.dataset.key = item.key;
            summaryRail.appendChild(card);
        });
        shell.appendChild(summaryRail);

        const workGrid = document.createElement('div');
        workGrid.className = 'dashboard-work-grid';
        workGrid.dataset.key = 'work-grid';

        workGrid.appendChild(createSection(
            'needs-attention',
            'Needs attention',
            '/ui/approvals',
            buildNeedsAttention(summary, approvalsData, tasksData, agentsData),
            'Nothing urgent right now.',
        ));

        const conversationRows = (conversationsData.conversations || []).slice(0, 6).map((item) => createRow({
            key: item.conversation_id,
            title: item.title || item.conversation_id,
            subtitle: [
                item.target_display_name || item.target_agent_id || 'agent',
                UI.relativeTime(item.updated_at || item.created_at),
            ].join(' · '),
            badge: item.status || 'open',
            badgeClass: 'badge-' + (item.status || 'open'),
            href: '/ui/conversations/' + item.conversation_id,
        }));
        workGrid.appendChild(createSection(
            'open-conversations',
            'Open conversations',
            '/ui/conversations?status=open',
            conversationRows,
            'No open conversations.',
        ));

        const runningRows = (tasksData.running_tasks || tasksData.tasks || []).slice(0, 6).map((item) => createRow({
            key: item.routed_task_id,
            title: item.title || item.routed_task_id,
            subtitle: [
                item.target_display_name || item.target_agent_id || 'agent',
                UI.relativeTime(item.updated_at || item.created_at),
            ].filter(Boolean).join(' · '),
            badge: item.status || 'running',
            badgeClass: 'badge-' + (item.status || 'running'),
            href: item.parent_conversation_id ? '/ui/conversations/' + item.parent_conversation_id : '/ui/tasks',
        }));
        workGrid.appendChild(createSection(
            'running-tasks',
            'Running tasks',
            '/ui/tasks?status=running',
            runningRows,
            'No running tasks.',
        ));

        const agentRows = (agentsData.agents || agentsData || []).slice(0, 6).map((item) => createRow({
            key: item.agent_id,
            title: item.display_name || item.slug || item.agent_id,
            subtitle: [
                item.role || 'agent',
                item.provider || '',
                item.last_heartbeat_at ? UI.relativeTime(item.last_heartbeat_at) : '',
            ].filter(Boolean).join(' · '),
            badge: item.connectivity_state || 'connected',
            badgeClass: 'badge-' + (item.connectivity_state || 'connected'),
            href: '/ui/agents/' + item.agent_id,
        }));
        workGrid.appendChild(createSection(
            'agents',
            'Agents',
            '/ui/agents',
            agentRows,
            'No agents available.',
        ));

        shell.appendChild(workGrid);
        UI.reconcileChildren(content, [shell]);
    }

    let hasLoaded = false;

    function loadSummary({ soft = false } = {}) {
        if (!soft || !hasLoaded) {
            UI.reconcileChildren(content, UI.createSkeletonNodes(5, 'card'));
        }
        Promise.all([
            API.getSummary(),
            API.listApprovals({ limit: 4 }),
            API.listConversations({ limit: 6, status: 'open' }),
            API.listTasks({ limit: 6, status: 'failed' }),
            API.listTasks({ limit: 6, status: 'running' }).catch(() => ({ tasks: [] })),
            API.listAgents({ limit: 8 }),
        ]).then(([summary, approvals, conversations, failedTasks, runningTasks, agents]) => {
            renderDashboardView(summary, approvals, conversations, {
                tasks: failedTasks.tasks || failedTasks || [],
                running_tasks: runningTasks.tasks || runningTasks || [],
            }, agents);
            hasLoaded = true;
        }).catch((err) => {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh dashboard', err, { context: 'Dashboard soft refresh failed' });
                return;
            }
            UI.reconcileChildren(content, [UI.createErrorCard('Failed to load dashboard: ' + err.message, loadSummary)]);
        });
    }

    let reloadDebounce = null;
    ['summary', 'agents', 'conversations', 'tasks', 'approvals', 'usage'].forEach((topic) => {
        cleanups.add(WS.subscribe(topic, () => {
            clearTimeout(reloadDebounce);
            reloadDebounce = setTimeout(() => loadSummary({ soft: true }), 350);
        }));
    });

    loadSummary();
    cleanups.add(() => clearTimeout(reloadDebounce));
}
