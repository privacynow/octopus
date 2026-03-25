/**
 * Usage view — token/cost summary with date range selection.
 */
function renderUsageView(container) {
    const cleanups = UI.beginCleanupScope();
    let currentRange = '7d';
    let hasLoaded = false;

    // Header
    const header = document.createElement('div');
    header.className = 'page-header page-header-tight';
    header.innerHTML = '<h2>Usage</h2>';
    container.appendChild(header);

    // Date range bar
    const rangeBar = document.createElement('div');
    rangeBar.className = 'segmented-control';
    rangeBar.setAttribute('role', 'tablist');
    rangeBar.setAttribute('aria-label', 'Usage range');

    const ranges = [
        { label: 'Today', value: '1d' },
        { label: '7 days', value: '7d' },
        { label: '30 days', value: '30d' },
    ];

    ranges.forEach(r => {
        const btn = document.createElement('button');
        btn.className = 'segmented-control-btn' + (r.value === currentRange ? ' active' : '');
        btn.textContent = r.label;
        btn.setAttribute('data-range', r.value);
        btn.setAttribute('role', 'tab');
        btn.setAttribute('aria-selected', String(r.value === currentRange));
        btn.addEventListener('click', () => {
            currentRange = r.value;
            rangeBar.querySelectorAll('.segmented-control-btn').forEach((button) => {
                button.classList.toggle('active', button === btn);
                button.setAttribute('aria-selected', String(button === btn));
            });
            loadUsage();
        });
        rangeBar.appendChild(btn);
    });

    container.appendChild(rangeBar);

    // Summary card
    const summaryEl = document.createElement('div');
    summaryEl.id = 'usage-summary';
    container.appendChild(summaryEl);

    // Table
    const tableEl = document.createElement('div');
    tableEl.id = 'usage-table';
    container.appendChild(tableEl);

    function _rangeToParams(range) {
        const now = new Date();
        const since = new Date(now);
        if (range === '1d') {
            // Calendar midnight today (not 24h ago)
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

    function loadUsage({ soft = false } = {}) {
        if (!soft || !hasLoaded) {
            UI.reconcileChildren(summaryEl, UI.createSkeletonNodes(1, 'card'));
            UI.reconcileChildren(tableEl, UI.createSkeletonNodes(3, 'row'));
        }

        const params = _rangeToParams(currentRange);
        API.getUsage(params).then(usage => {
            const daily = usage.daily_total || {};
            const rows = Array.isArray(usage)
                ? usage
                : (usage.by_conversation || []);

            // Summary card
            const card = document.createElement('div');
            card.className = 'summary-card';
            card.dataset.key = 'usage-summary-card';

            const promptStat = _createStat(
                (daily.prompt_tokens || 0).toLocaleString(),
                'Prompt Tokens'
            );
            card.appendChild(promptStat);

            const compStat = _createStat(
                (daily.completion_tokens || 0).toLocaleString(),
                'Completion Tokens'
            );
            card.appendChild(compStat);

            const costStat = _createStat(
                '$' + (daily.cost_usd || 0).toFixed(4),
                'Total Cost'
            );
            card.appendChild(costStat);

            UI.reconcileChildren(summaryEl, [card]);

            // Per-conversation table
            if (rows.length === 0) {
                UI.reconcileChildren(tableEl, [UI.renderEmptyState('No usage data for this period')]);
                hasLoaded = true;
                return;
            }

            const wrap = document.createElement('div');
            wrap.className = 'table-wrap';
            wrap.dataset.key = 'usage-table-wrap';
            const tbl = document.createElement('table');
            tbl.className = 'data-table responsive';

            const thead = document.createElement('thead');
            thead.innerHTML = '<tr><th>Conversation</th><th>Prompt Tokens</th><th>Completion Tokens</th><th>Cost</th></tr>';
            tbl.appendChild(thead);

            const tbody = document.createElement('tbody');
            rows.forEach(u => {
                const tr = document.createElement('tr');
                tr.dataset.key = u.conversation_id || '';

                const conversationTd = document.createElement('td');
                conversationTd.setAttribute('data-label', 'Conversation');
                const conversationLink = document.createElement('a');
                conversationLink.href = '/ui/conversations/' + encodeURIComponent(u.conversation_id || '');
                conversationLink.textContent = u.title || u.conversation_id || '';
                conversationTd.appendChild(conversationLink);
                tr.appendChild(conversationTd);

                [
                    ['Prompt Tokens', (u.prompt_tokens || 0).toLocaleString()],
                    ['Completion Tokens', (u.completion_tokens || 0).toLocaleString()],
                    ['Cost', '$' + (u.cost_usd || 0).toFixed(4)],
                ].forEach(([label, val]) => {
                    const td = document.createElement('td');
                    td.setAttribute('data-label', label);
                    td.textContent = val;
                    tr.appendChild(td);
                });

                tbody.appendChild(tr);
            });
            tbl.appendChild(tbody);
            wrap.appendChild(tbl);
            UI.reconcileChildren(tableEl, [wrap]);
            hasLoaded = true;

        }).catch(err => {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh usage', err, { context: 'Usage soft refresh failed' });
                return;
            }
            UI.reconcileChildren(summaryEl, []);
            UI.reconcileChildren(tableEl, [UI.createErrorCard('Failed: ' + err.message, loadUsage)]);
        });
    }

    function _createStat(value, label) {
        const stat = document.createElement('div');
        stat.className = 'summary-stat';
        const val = document.createElement('span');
        val.className = 'stat-value';
        val.textContent = value;
        stat.appendChild(val);
        const lbl = document.createElement('span');
        lbl.className = 'stat-label';
        lbl.textContent = label;
        stat.appendChild(lbl);
        return stat;
    }

    loadUsage();

    // WS: reload usage on new events (token costs update)
    let reloadDebounce = null;
    const unsub = WS.subscribe('usage', () => {
        clearTimeout(reloadDebounce);
        reloadDebounce = setTimeout(() => loadUsage({ soft: true }), 600);
    });
    cleanups.add(() => clearTimeout(reloadDebounce));
    cleanups.add(unsub);
}
