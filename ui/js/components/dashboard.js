/**
 * Dashboard — action-first registry overview.
 */
function renderDashboard(container) {
    const cleanups = UI.beginCleanupScope();

    const header = document.createElement('div');
    header.className = 'page-header page-header-hero';
    header.innerHTML = '<h2>Registry</h2><p>Review blockers, check health, and keep active work moving.</p>';
    container.appendChild(header);

    const content = document.createElement('div');
    content.className = 'dashboard-shell';
    container.appendChild(content);

    function pickPrimaryAction(summary) {
        if ((summary.conversations?.pending_approvals || 0) > 0) {
            return ['/ui/approvals', 'Review approvals', 'Work is waiting for a decision.'];
        }
        if ((summary.agents?.degraded || 0) > 0 || (summary.agents?.disconnected || 0) > 0) {
            return ['/ui/agents', 'Check agent health', 'Some agents need attention.'];
        }
        if ((summary.tasks?.failed_24h || 0) > 0) {
            return ['/ui/tasks', 'Review failed work', 'A delegated task needs follow-up.'];
        }
        return ['/ui/conversations', 'Open conversations', 'See what is active and reply where needed.'];
    }

    function createAttentionCard({ title, value, detail, href, cta, tone = '' }) {
        const card = document.createElement('section');
        card.className = `card attention-card${tone ? ' attention-card-' + tone : ''}`;

        const valueEl = document.createElement('div');
        valueEl.className = 'attention-value';
        valueEl.textContent = String(value);
        card.appendChild(valueEl);

        const titleEl = document.createElement('div');
        titleEl.className = 'attention-title';
        titleEl.textContent = title;
        card.appendChild(titleEl);

        const detailEl = document.createElement('p');
        detailEl.className = 'attention-detail';
        detailEl.textContent = detail;
        card.appendChild(detailEl);

        const link = document.createElement('a');
        link.href = href;
        link.className = 'btn btn-primary';
        link.textContent = cta;
        card.appendChild(link);
        return card;
    }

    function createPreviewList(title, subtitle, emptyText, items, href) {
        const section = document.createElement('section');
        section.className = 'card dashboard-section';

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
            const empty = document.createElement('div');
            empty.className = 'empty-state empty-state-compact';
            empty.textContent = emptyText;
            section.appendChild(empty);
            return section;
        }

        const list = document.createElement('div');
        list.className = 'preview-list';
        items.forEach((item) => list.appendChild(item));
        section.appendChild(list);
        return section;
    }

    function createPreviewRow({ title, subtitle, badge, href, badgeClass = '' }) {
        const row = document.createElement('a');
        row.href = href;
        row.className = 'preview-row';

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

    function renderDashboardView(summary, approvalsData, conversationsData, failedTasksData) {
        content.textContent = '';
        const primaryAction = pickPrimaryAction(summary);

        const lead = document.createElement('section');
        lead.className = 'card dashboard-lead';
        lead.innerHTML = `
            <div class="dashboard-lead-copy">
                <h3>${UI.esc(primaryAction[1])}</h3>
                <p>${UI.esc(primaryAction[2])}</p>
            </div>
        `;
        const leadActions = document.createElement('div');
        leadActions.className = 'dashboard-lead-actions';
        const primary = document.createElement('a');
        primary.href = primaryAction[0];
        primary.className = 'btn btn-primary';
        primary.textContent = 'Open queue';
        const secondary = document.createElement('a');
        secondary.href = '/ui/conversations?status=open';
        secondary.className = 'btn';
        secondary.textContent = 'Open conversations';
        leadActions.appendChild(primary);
        leadActions.appendChild(secondary);
        lead.appendChild(leadActions);
        content.appendChild(lead);

        const attentionGrid = document.createElement('div');
        attentionGrid.className = 'attention-grid';
        attentionGrid.appendChild(createAttentionCard({
            title: 'Pending approvals',
            value: summary.conversations?.pending_approvals || 0,
            detail: 'Requests waiting for a decision before work can continue.',
            href: '/ui/approvals',
            cta: 'Review now',
            tone: 'warm',
        }));
        attentionGrid.appendChild(createAttentionCard({
            title: 'Agent health',
            value: (summary.agents?.degraded || 0) + (summary.agents?.disconnected || 0),
            detail: `${summary.agents?.degraded || 0} degraded · ${summary.agents?.disconnected || 0} offline`,
            href: '/ui/agents',
            cta: 'Inspect agents',
            tone: (summary.agents?.degraded || 0) + (summary.agents?.disconnected || 0) > 0 ? 'danger' : 'calm',
        }));
        attentionGrid.appendChild(createAttentionCard({
            title: 'Failed work',
            value: summary.tasks?.failed_24h || 0,
            detail: `${summary.tasks?.running || 0} running · ${summary.tasks?.pending || 0} queued or submitted`,
            href: '/ui/tasks',
            cta: 'Open tasks',
            tone: (summary.tasks?.failed_24h || 0) > 0 ? 'danger' : 'calm',
        }));
        content.appendChild(attentionGrid);

        const lowerGrid = document.createElement('div');
        lowerGrid.className = 'dashboard-grid dashboard-grid-wide';

        const approvalRows = (approvalsData.approvals || []).map((item) => createPreviewRow({
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
        lowerGrid.appendChild(createPreviewList(
            'Ready for review',
            'Decisions that are currently blocking work.',
            'Nothing is waiting for approval.',
            approvalRows,
            '/ui/approvals',
        ));

        const conversationRows = (conversationsData.conversations || []).map((item) => createPreviewRow({
            title: item.title || item.conversation_id,
            subtitle: [
                item.target_display_name || item.target_agent_id || 'agent',
                UI.relativeTime(item.updated_at || item.created_at),
            ].join(' · '),
            badge: item.status || 'open',
            badgeClass: `badge badge-${item.status || 'open'}`,
            href: '/ui/conversations/' + item.conversation_id,
        }));
        lowerGrid.appendChild(createPreviewList(
            'Ongoing conversations',
            'The most recently updated open threads.',
            'No open conversations right now.',
            conversationRows,
            '/ui/conversations?status=open',
        ));

        const taskRows = (failedTasksData.tasks || []).map((item) => createPreviewRow({
            title: item.title || item.routed_task_id,
            subtitle: [
                item.target_display_name || item.target_agent_id || 'agent',
                UI.relativeTime(item.updated_at || item.created_at),
            ].join(' · '),
            badge: item.status || 'failed',
            badgeClass: `badge badge-${item.status || 'failed'}`,
            href: item.parent_conversation_id ? '/ui/conversations/' + item.parent_conversation_id : '/ui/tasks',
        }));
        lowerGrid.appendChild(createPreviewList(
            'Recent failures',
            'Tasks that need follow-up or retry decisions.',
            'No failed tasks in the last page of work.',
            taskRows,
            '/ui/tasks?status=failed',
        ));

        content.appendChild(lowerGrid);
    }

    let hasLoaded = false;

    function loadSummary({ soft = false } = {}) {
        if (!soft || !hasLoaded) {
            content.textContent = '';
            const shell = document.createElement('div');
            shell.className = 'dashboard-shell';
            UI.renderSkeletons(shell, 4, 'card');
            content.appendChild(shell);
        }

        Promise.all([
            API.getSummary(),
            API.listApprovals({ limit: 4 }),
            API.listConversations({ limit: 4, status: 'open' }),
            API.listTasks({ limit: 4, status: 'failed' }),
        ]).then(([summary, approvals, conversations, failedTasks]) => {
            renderDashboardView(summary, approvals, conversations, failedTasks);
            hasLoaded = true;
        }).catch((err) => {
            content.textContent = '';
            UI.renderError(content, 'Failed to load dashboard: ' + err.message, loadSummary);
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
