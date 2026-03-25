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
    header.className = 'page-header page-header-hero';
    header.innerHTML = '<h2>Registry</h2><p>Start with the next blocked decision, then move the active work queues.</p>';
    container.appendChild(header);

    const content = document.createElement('div');
    content.className = 'dashboard-shell';
    container.appendChild(content);

    function pickPrimaryAction(summary) {
        if ((summary.conversations?.pending_approvals || 0) > 0) {
            return ['/ui/approvals', 'Approvals are blocking work.'];
        }
        if ((summary.tasks?.failed_24h || 0) > 0) {
            return ['/ui/tasks', 'Failed delegated work needs follow-up.'];
        }
        if ((summary.agents?.degraded || 0) > 0 || (summary.agents?.disconnected || 0) > 0) {
            return ['/ui/agents', 'Agent health needs review.'];
        }
        return ['/ui/conversations', 'Active conversations need operator attention.'];
    }

    function createPreviewList(key, title, subtitle, emptyText, items, href) {
        const section = document.createElement('section');
        section.className = 'card dashboard-section';
        section.dataset.key = key;

        const head = document.createElement('div');
        head.className = 'dashboard-section-header';
        head.innerHTML = `<div><strong>${UI.esc(title)}</strong><span>${UI.esc(subtitle)}</span></div>`;
        if (href) {
            const link = document.createElement('a');
            link.href = href;
            link.className = 'section-link';
            link.textContent = 'View all';
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
        const [primaryHref, primaryCopy] = pickPrimaryAction(summary);

        const commandCard = document.createElement('section');
        commandCard.className = 'card dashboard-command';
        commandCard.dataset.key = 'dashboard-command';
        commandCard.innerHTML = `
            <div class="dashboard-command-copy">
                <h3>Operator workspace</h3>
                <p>${UI.esc(primaryCopy)}</p>
            </div>
        `;
        const commandActions = document.createElement('div');
        commandActions.className = 'dashboard-command-actions';
        const primaryAction = document.createElement('a');
        primaryAction.href = primaryHref;
        primaryAction.className = 'btn btn-primary';
        primaryAction.textContent = 'Open next queue';
        const secondaryAction = document.createElement('a');
        secondaryAction.href = '/ui/conversations?status=open';
        secondaryAction.className = 'btn';
        secondaryAction.textContent = 'Open conversations';
        commandActions.appendChild(primaryAction);
        commandActions.appendChild(secondaryAction);
        commandCard.appendChild(commandActions);

        const summaryRail = document.createElement('div');
        summaryRail.className = 'dashboard-summary-rail';
        summaryRail.dataset.key = 'dashboard-summary';
        const approvalsCard = UI.renderStatCard({
            value: String(summary.conversations?.pending_approvals || 0),
            label: 'Pending approvals',
            detail: 'Blocking decisions',
            href: '/ui/approvals',
        });
        approvalsCard.dataset.key = 'pending-approvals';
        summaryRail.appendChild(approvalsCard);
        const runningCard = UI.renderStatCard({
            value: String(summary.tasks?.running || 0),
            label: 'Running tasks',
            detail: `${summary.tasks?.pending || 0} queued or submitted`,
            href: '/ui/tasks?status=running',
        });
        runningCard.dataset.key = 'running-tasks';
        summaryRail.appendChild(runningCard);
        const followUpCard = UI.renderStatCard({
            value: String(summary.tasks?.failed_24h || 0),
            label: 'Needs follow-up',
            detail: 'Failed in the last 24h',
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
        workGrid.appendChild(createPreviewList(
            'blocking-approvals',
            'Blocking approvals',
            'Requests that need an operator decision right now.',
            'Nothing is blocked on approval.',
            approvalRows,
            '/ui/approvals',
        ));

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
        workGrid.appendChild(createPreviewList(
            'open-conversations',
            'Open conversations',
            'The most recently updated live threads.',
            'No open conversations right now.',
            conversationRows,
            '/ui/conversations?status=open',
        ));

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
        workGrid.appendChild(createPreviewList(
            'task-follow-up',
            'Task follow-up',
            'Failed or stalled work that needs a next step.',
            'No failed delegated work right now.',
            taskRows,
            '/ui/tasks',
        ));

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
        workGrid.appendChild(createPreviewList(
            'agents-at-risk',
            'Agents at risk',
            'Connectivity or health problems that can stall work.',
            'All visible agents look healthy.',
            agentRows,
            '/ui/agents',
        ));

        UI.reconcileChildren(content, [commandCard, summaryRail, workGrid]);
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
