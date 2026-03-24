/**
 * Dashboard — global registry overview from /v1/summary.
 */
function renderDashboard(container) {
    const cleanups = [];

    const header = document.createElement('div');
    header.className = 'page-header page-header-hero';
    header.innerHTML = '<h2>Registry Dashboard</h2><p>Global health, conversation activity, approvals, tasks, and spend from one canonical summary endpoint.</p>';
    container.appendChild(header);

    const content = document.createElement('div');
    content.className = 'dashboard-shell';
    container.appendChild(content);

    function renderSummary(summary) {
        content.textContent = '';

        const heroGrid = document.createElement('div');
        heroGrid.className = 'stat-grid stat-grid-hero';
        heroGrid.appendChild(_createStatCard(
            String(summary.agents?.connected || 0),
            'Connected Agents',
            `${summary.agents?.total || 0} total`
        ));
        heroGrid.appendChild(_createStatCard(
            String(summary.conversations?.active || 0),
            'Active Conversations',
            `${summary.conversations?.total || 0} total`
        ));
        heroGrid.appendChild(_createStatCard(
            String(summary.conversations?.pending_approvals || 0),
            'Pending Approvals',
            'Open approval state'
        ));
        heroGrid.appendChild(_createStatCard(
            String(summary.tasks?.running || 0),
            'Running Tasks',
            `${summary.tasks?.pending || 0} pending`
        ));
        heroGrid.appendChild(_createStatCard(
            `$${Number(summary.usage_24h?.cost_usd || 0).toFixed(2)}`,
            '24h Cost',
            `${Number(summary.usage_24h?.prompt_tokens || 0).toLocaleString()} prompt tokens`
        ));
        heroGrid.appendChild(_createStatCard(
            String(summary.agents?.degraded || 0),
            'Degraded Agents',
            `${summary.agents?.disconnected || 0} disconnected`
        ));
        content.appendChild(heroGrid);

        const grid = document.createElement('div');
        grid.className = 'dashboard-grid';

        const opsCard = document.createElement('section');
        opsCard.className = 'card feature-card';
        opsCard.innerHTML = '<div class="card-title">Operations</div><div class="card-subtitle">Current system state at a glance.</div>';
        const opsList = document.createElement('div');
        opsList.className = 'metric-list';
        [
            ['Connected', summary.agents?.connected || 0],
            ['Degraded', summary.agents?.degraded || 0],
            ['Disconnected', summary.agents?.disconnected || 0],
            ['Pending approvals', summary.conversations?.pending_approvals || 0],
            ['Failed tasks (24h)', summary.tasks?.failed_24h || 0],
        ].forEach(([label, value]) => {
            const row = document.createElement('div');
            row.className = 'metric-row';
            row.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
            opsList.appendChild(row);
        });
        opsCard.appendChild(opsList);
        grid.appendChild(opsCard);

        const usageCard = document.createElement('section');
        usageCard.className = 'card feature-card';
        usageCard.innerHTML = '<div class="card-title">Usage (24h)</div><div class="card-subtitle">Computed only from provider response events.</div>';
        const usageList = document.createElement('div');
        usageList.className = 'metric-list';
        [
            ['Prompt tokens', Number(summary.usage_24h?.prompt_tokens || 0).toLocaleString()],
            ['Completion tokens', Number(summary.usage_24h?.completion_tokens || 0).toLocaleString()],
            ['Cost', `$${Number(summary.usage_24h?.cost_usd || 0).toFixed(4)}`],
            ['Generated', _formatTime(summary.generated_at || '')],
        ].forEach(([label, value]) => {
            const row = document.createElement('div');
            row.className = 'metric-row';
            row.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
            usageList.appendChild(row);
        });
        usageCard.appendChild(usageList);
        grid.appendChild(usageCard);

        const quickCard = document.createElement('section');
        quickCard.className = 'card feature-card';
        quickCard.innerHTML = '<div class="card-title">Quick Access</div><div class="card-subtitle">Jump to the pages that act on the same canonical resources.</div>';
        const links = document.createElement('div');
        links.className = 'quick-links';
        [
            ['/ui/agents', 'Agents', 'Inspect registry members and current connectivity.'],
            ['/ui/conversations', 'Conversations', 'Browse active threads and approval state.'],
            ['/ui/tasks', 'Tasks', 'Track routed work and outcomes.'],
            ['/ui/usage', 'Usage', 'See token and cost distribution.'],
        ].forEach(([href, title, detail]) => {
            const link = document.createElement('a');
            link.href = href;
            link.className = 'quick-link-card';
            link.innerHTML = `<strong>${title}</strong><span>${detail}</span>`;
            links.appendChild(link);
        });
        quickCard.appendChild(links);
        grid.appendChild(quickCard);

        content.appendChild(grid);
    }

    function loadSummary() {
        content.textContent = '';
        const shell = document.createElement('div');
        shell.className = 'stat-grid stat-grid-hero';
        _renderSkeletons(shell, 6, 'card');
        content.appendChild(shell);

        API.getSummary().then(renderSummary).catch((err) => {
            content.textContent = '';
            _renderError(content, 'Failed to load dashboard summary: ' + err.message, loadSummary);
        });
    }

    let reloadDebounce = null;
    const unsub = WS.subscribe('*', (msg) => {
        if (msg.type === 'event' || msg.type === 'heartbeat') {
            clearTimeout(reloadDebounce);
            reloadDebounce = setTimeout(loadSummary, 2500);
        }
    });
    cleanups.push(unsub);

    loadSummary();

    return function cleanup() {
        clearTimeout(reloadDebounce);
        cleanups.forEach((fn) => fn());
    };
}
