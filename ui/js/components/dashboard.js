/**
 * Dashboard — compact operator landing page.
 */
function renderDashboard(container) {
    const cleanups = UI.beginCleanupScope();
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }

    const header = document.createElement('div');
    header.className = 'page-header page-header-tight';
    header.innerHTML = '<h2>Registry</h2>';
    container.appendChild(header);

    const content = document.createElement('div');
    content.className = 'dashboard-shell';
    container.appendChild(content);

    function createPreviewList(key, title, emptyText, items, href, count = null) {
        const section = document.createElement('section');
        section.className = 'card dashboard-section';
        section.dataset.key = key;

        const head = document.createElement('div');
        head.className = 'dashboard-section-header';
        const titleWrap = document.createElement('div');
        titleWrap.className = 'dashboard-section-title';
        titleWrap.innerHTML = `<strong>${UI.esc(title)}</strong>`;
        if (count !== null) {
            const countBadge = document.createElement('span');
            countBadge.className = 'dashboard-section-count';
            countBadge.textContent = String(count);
            titleWrap.appendChild(countBadge);
        }
        head.appendChild(titleWrap);
        if (href) {
            const link = document.createElement('a');
            link.href = href;
            link.className = 'section-link';
            link.textContent = 'Open';
            head.appendChild(link);
        }
        section.appendChild(head);

        if (!items.length) {
            section.appendChild(UI.renderEmptyState(emptyText, true));
            return section;
        }

        const list = document.createElement('div');
        list.className = 'preview-list';
        items.forEach((item) => list.appendChild(item));
        section.appendChild(list);
        return section;
    }

    function createPreviewRow({ key, title, subtitle, badge, href, badgeClass = '' }) {
        const row = document.createElement('a');
        row.href = href;
        row.className = 'preview-row';
        if (key) row.dataset.key = key;

        const text = document.createElement('div');
        text.className = 'preview-row-text';
        text.innerHTML = `<strong>${UI.esc(title)}</strong><span>${UI.esc(subtitle)}</span>`;
        row.appendChild(text);

        if (badge) {
            const badgeEl = document.createElement('span');
            badgeEl.className = badgeClass || 'badge';
            badgeEl.textContent = badge;
            row.appendChild(badgeEl);
        }
        return row;
    }

    function renderDashboardView(summary, approvalsData, conversationsData, tasksData, agentsData) {
        const summaryRail = document.createElement('div');
        summaryRail.className = 'dashboard-summary-rail';
        summaryRail.dataset.key = 'dashboard-summary';
        const approvalsCard = UI.renderStatCard({
            value: String(summary.conversations?.pending_approvals || 0),
            label: 'Approvals',
            detail: 'Waiting',
            href: '/ui/approvals',
        });
        approvalsCard.dataset.key = 'pending-approvals';
        summaryRail.appendChild(approvalsCard);
        const runningCard = UI.renderStatCard({
            value: String(summary.tasks?.running || 0),
            label: 'Running',
            detail: `${summary.tasks?.pending || 0} queued`,
            href: '/ui/tasks?status=running',
        });
        runningCard.dataset.key = 'running-tasks';
        summaryRail.appendChild(runningCard);
        const followUpCard = UI.renderStatCard({
            value: String(summary.tasks?.failed_24h || 0),
            label: 'Follow-up',
            detail: 'Last 24h',
            href: '/ui/tasks?status=failed',
        });
        followUpCard.dataset.key = 'needs-follow-up';
        summaryRail.appendChild(followUpCard);
        const healthCard = UI.renderStatCard({
            value: String((summary.agents?.degraded || 0) + (summary.agents?.disconnected || 0)),
            label: 'Agent health',
            detail: `${summary.agents?.connected || 0} connected`,
            href: '/ui/agents',
        });
        healthCard.dataset.key = 'agent-health';
        summaryRail.appendChild(healthCard);

        const workGrid = document.createElement('div');
        workGrid.className = 'dashboard-work-grid';
        workGrid.dataset.key = 'dashboard-work';

        const approvalRows = (approvalsData.approvals || []).map((item) => createPreviewRow({
            key: item.request_id || item.approval_id || item.conversation_id,
            title: item.conversation_title || item.conversation_id,
            subtitle: [
                item.target_display_name || item.target_agent_id || 'agent',
                item.request_kind || 'approval request',
                item.expires_at ? `expires ${UI.formatApprovalTime(item.expires_at)}` : UI.relativeTime(item.created_at),
            ].filter(Boolean).join(' · '),
            badge: 'Review',
            badgeClass: 'badge badge-queued',
            href: '/ui/approvals',
        }));
        if (approvalRows.length) {
            workGrid.appendChild(createPreviewList(
                'blocking-approvals',
                'Approvals',
                'Clear',
                approvalRows,
                '/ui/approvals',
                approvalsData.approvals ? approvalsData.approvals.length : approvalRows.length,
            ));
        }

        const conversationRows = (conversationsData.conversations || []).map((item) => createPreviewRow({
            key: item.conversation_id,
            title: item.title || item.conversation_id,
            subtitle: [
                item.target_display_name || item.target_agent_id || 'agent',
                UI.relativeTime(item.updated_at || item.created_at),
            ].join(' · '),
            badge: item.status || 'open',
            badgeClass: `badge badge-${item.status || 'open'}`,
            href: '/ui/conversations/' + item.conversation_id,
        }));
        if (conversationRows.length) {
            workGrid.appendChild(createPreviewList(
                'open-conversations',
                'Conversations',
                'Quiet',
                conversationRows,
                '/ui/conversations?status=open',
                conversationsData.conversations ? conversationsData.conversations.length : conversationRows.length,
            ));
        }

        const taskRows = (tasksData.tasks || []).map((item) => createPreviewRow({
            key: item.routed_task_id,
            title: item.title || item.routed_task_id,
            subtitle: [
                item.target_display_name || item.target_agent_id || 'agent',
                UI.relativeTime(item.updated_at || item.created_at),
            ].join(' · '),
            badge: item.status || 'failed',
            badgeClass: `badge badge-${item.status || 'failed'}`,
            href: item.parent_conversation_id ? '/ui/conversations/' + item.parent_conversation_id : '/ui/tasks',
        }));
        if (taskRows.length) {
            workGrid.appendChild(createPreviewList(
                'task-follow-up',
                'Tasks',
                'Clear',
                taskRows,
                '/ui/tasks',
                tasksData.tasks ? tasksData.tasks.length : taskRows.length,
            ));
        }

        const riskyAgents = (agentsData.agents || agentsData || []).filter((item) => ['degraded', 'disconnected', 'offline'].includes(item.connectivity_state || ''));
        const agentRows = riskyAgents.map((item) => createPreviewRow({
            key: item.agent_id,
            title: item.display_name || item.slug || item.agent_id,
            subtitle: [
                item.role || 'agent',
                item.provider || '',
                item.last_heartbeat_at ? UI.relativeTime(item.last_heartbeat_at) : '',
            ].filter(Boolean).join(' · '),
            badge: item.connectivity_state || 'connected',
            badgeClass: `badge badge-${item.connectivity_state || 'connected'}`,
            href: '/ui/agents/' + item.agent_id,
        }));
        if (agentRows.length) {
            workGrid.appendChild(createPreviewList(
                'agents-at-risk',
                'Agents',
                'Healthy',
                agentRows,
                '/ui/agents',
                riskyAgents.length,
            ));
        }

        if (!workGrid.childElementCount) {
            const quiet = document.createElement('section');
            quiet.className = 'card dashboard-section dashboard-section-quiet';
            quiet.dataset.key = 'dashboard-quiet';
            quiet.appendChild(UI.renderEmptyState('Quiet', true));
            workGrid.appendChild(quiet);
        }
        workGrid.classList.toggle('dashboard-work-grid-single', workGrid.childElementCount <= 1);

        UI.reconcileChildren(content, [summaryRail, workGrid]);
    }

    let hasLoaded = false;

    function loadSummary({ soft = false } = {}) {
        if (!soft || !hasLoaded) {
            UI.reconcileChildren(content, UI.createSkeletonNodes(5, 'card'));
        }
        Promise.all([
            API.getSummary(),
            API.listApprovals({ limit: 4 }),
            API.listConversations({ limit: 4, status: 'open' }),
            API.listTasks({ limit: 4, status: 'failed' }),
            API.listAgents({ limit: 8 }),
        ]).then(([summary, approvals, conversations, tasks, agents]) => {
            renderDashboardView(summary, approvals, conversations, tasks, agents);
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
            reloadDebounce = setTimeout(() => loadSummary({ soft: true }), 400);
        }));
    });

    loadSummary();
    cleanups.add(() => clearTimeout(reloadDebounce));
}
