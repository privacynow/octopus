/**
 * Usage view — compact rollup with conversation table.
 */
function renderUsageView(container) {
    const cleanups = UI.beginCleanupScope();
    let currentRange = '7d';
    let hasLoaded = false;

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Usage</h2>';
    container.appendChild(header);

    const controls = document.createElement('div');
    controls.className = 'route-controls';
    container.appendChild(controls);

    const rangeBar = document.createElement('div');
    rangeBar.className = 'segmented-control';
    rangeBar.setAttribute('role', 'tablist');
    rangeBar.setAttribute('aria-label', 'Usage date range');
    controls.appendChild(rangeBar);

    const ranges = [
        { label: 'Today', value: '1d' },
        { label: '7 days', value: '7d' },
        { label: '30 days', value: '30d' },
    ];

    ranges.forEach((range) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'segmented-control-btn' + (range.value === currentRange ? ' active' : '');
        btn.textContent = range.label;
        btn.dataset.value = range.value;
        btn.setAttribute('role', 'tab');
        btn.setAttribute('aria-selected', String(range.value === currentRange));
        btn.tabIndex = range.value === currentRange ? 0 : -1;
        btn.addEventListener('click', () => {
            currentRange = range.value;
            syncRangeButtons();
            loadUsage();
        });
        rangeBar.appendChild(btn);
    });

    const summaryEl = document.createElement('section');
    summaryEl.className = 'summary-rail';
    container.appendChild(summaryEl);

    const tableShell = document.createElement('section');
    tableShell.className = 'list-shell';
    container.appendChild(tableShell);

    const tableEl = document.createElement('div');
    tableEl.id = 'usage-table';
    tableShell.appendChild(tableEl);

    function syncRangeButtons() {
        rangeBar.querySelectorAll('.segmented-control-btn').forEach((btn) => {
            const active = btn.dataset.value === currentRange;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-selected', String(active));
            btn.tabIndex = active ? 0 : -1;
        });
    }

    function _rangeToParams(range) {
        const now = new Date();
        const since = new Date(now);
        if (range === '1d') {
            since.setHours(0, 0, 0, 0);
        } else if (range === '7d') {
            since.setDate(since.getDate() - 6);
            since.setHours(0, 0, 0, 0);
        } else {
            since.setDate(since.getDate() - 29);
            since.setHours(0, 0, 0, 0);
        }
        return {
            since: since.toISOString(),
            until: now.toISOString(),
        };
    }

    function renderSummary(daily) {
        const items = [
            ['prompt', (daily.prompt_tokens || 0).toLocaleString(), 'Prompt tokens'],
            ['completion', (daily.completion_tokens || 0).toLocaleString(), 'Completion tokens'],
            ['cost', '$' + (daily.cost_usd || 0).toFixed(4), 'Total cost'],
        ];
        UI.reconcileChildren(summaryEl, items.map(([key, value, label]) => {
            const card = UI.renderStatCard({ value, label });
            card.dataset.key = key;
            return card;
        }));
    }

    function renderTable(rows) {
        if (!rows.length) {
            UI.reconcileChildren(tableEl, [UI.renderEmptyState('No usage for this range.', true)]);
            return;
        }

        const wrap = document.createElement('div');
        wrap.className = 'table-wrap';
        wrap.dataset.key = 'usage-table-wrap';

        const table = document.createElement('table');
        table.className = 'data-table responsive';

        const thead = document.createElement('thead');
        thead.innerHTML = '<tr><th>Conversation</th><th>Prompt</th><th>Completion</th><th>Cost</th></tr>';
        table.appendChild(thead);

        const tbody = document.createElement('tbody');
        rows.forEach((item) => {
            const tr = document.createElement('tr');
            tr.dataset.key = item.conversation_id || '';

            const linkTd = document.createElement('td');
            linkTd.setAttribute('data-label', 'Conversation');
            const link = document.createElement('a');
            link.href = '/ui/conversations/' + encodeURIComponent(item.conversation_id || '');
            link.textContent = item.title || item.conversation_id || '';
            linkTd.appendChild(link);
            tr.appendChild(linkTd);

            [
                ['Prompt', (item.prompt_tokens || 0).toLocaleString()],
                ['Completion', (item.completion_tokens || 0).toLocaleString()],
                ['Cost', '$' + (item.cost_usd || 0).toFixed(4)],
            ].forEach(([label, value]) => {
                const td = document.createElement('td');
                td.setAttribute('data-label', label);
                td.textContent = value;
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        UI.reconcileChildren(tableEl, [wrap]);
    }

    function loadUsage({ soft = false } = {}) {
        if (!soft || !hasLoaded) {
            UI.reconcileChildren(summaryEl, UI.createSkeletonNodes(3, 'card'));
            UI.reconcileChildren(tableEl, UI.createSkeletonNodes(4, 'row'));
        }
        API.getUsage(_rangeToParams(currentRange)).then((usage) => {
            const daily = usage.daily_total || {};
            const rows = Array.isArray(usage) ? usage : (usage.by_conversation || []);
            renderSummary(daily);
            renderTable(rows);
            hasLoaded = true;
        }).catch((err) => {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh usage', err, { context: 'Usage soft refresh failed' });
                return;
            }
            UI.reconcileChildren(summaryEl, []);
            UI.reconcileChildren(tableEl, [UI.createErrorCard('Failed to load usage: ' + err.message, loadUsage)]);
        });
    }

    let reloadDebounce = null;
    cleanups.add(WS.subscribe('usage', () => {
        clearTimeout(reloadDebounce);
        reloadDebounce = setTimeout(() => loadUsage({ soft: true }), 500);
    }));

    syncRangeButtons();
    loadUsage();
    cleanups.add(() => clearTimeout(reloadDebounce));
}
