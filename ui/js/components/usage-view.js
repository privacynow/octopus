/**
 * Usage view — token/cost summary with date range selection.
 */
function renderUsageView(container) {
    let currentRange = '7d';

    // Header
    const header = document.createElement('div');
    header.className = 'page-header';
    header.innerHTML = '<h2>Usage</h2><p>Token usage and cost summary</p>';
    container.appendChild(header);

    // Date range bar
    const rangeBar = document.createElement('div');
    rangeBar.className = 'date-range-bar';

    const ranges = [
        { label: 'Today', value: '1d' },
        { label: '7 days', value: '7d' },
        { label: '30 days', value: '30d' },
    ];

    ranges.forEach(r => {
        const btn = document.createElement('button');
        btn.className = 'btn btn-sm' + (r.value === currentRange ? ' active' : '');
        btn.textContent = r.label;
        btn.setAttribute('data-range', r.value);
        btn.addEventListener('click', () => {
            currentRange = r.value;
            rangeBar.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
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
            since.setDate(since.getDate() - 7);
            since.setHours(0, 0, 0, 0);
        } else {
            since.setDate(since.getDate() - 30);
            since.setHours(0, 0, 0, 0);
        }
        return {
            since: since.toISOString(),
            until: now.toISOString(),
        };
    }

    function loadUsage() {
        summaryEl.textContent = '';
        tableEl.textContent = '';
        _renderSkeletons(summaryEl, 1, 'card');
        _renderSkeletons(tableEl, 3, 'row');

        const params = _rangeToParams(currentRange);
        API.getUsage(params).then(usage => {
            summaryEl.textContent = '';
            tableEl.textContent = '';

            const daily = usage.daily_total || {};
            const rows = Array.isArray(usage)
                ? usage
                : (usage.by_conversation || []);

            // Summary card
            const card = document.createElement('div');
            card.className = 'summary-card';

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

            summaryEl.appendChild(card);

            // Per-conversation table
            if (rows.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'empty-state';
                empty.textContent = 'No usage data for this period';
                tableEl.appendChild(empty);
                return;
            }

            const wrap = document.createElement('div');
            wrap.className = 'table-wrap';
            const tbl = document.createElement('table');
            tbl.className = 'data-table responsive';

            const thead = document.createElement('thead');
            thead.innerHTML = '<tr><th>Conversation</th><th>Prompt Tokens</th><th>Completion Tokens</th><th>Cost</th></tr>';
            tbl.appendChild(thead);

            const tbody = document.createElement('tbody');
            rows.forEach(u => {
                const tr = document.createElement('tr');

                const cells = [
                    ['Conversation', u.conversation_id || u.title || ''],
                    ['Prompt Tokens', (u.prompt_tokens || 0).toLocaleString()],
                    ['Completion Tokens', (u.completion_tokens || 0).toLocaleString()],
                    ['Cost', '$' + (u.cost_usd || 0).toFixed(4)],
                ];
                cells.forEach(([label, val]) => {
                    const td = document.createElement('td');
                    td.setAttribute('data-label', label);
                    td.textContent = val;
                    tr.appendChild(td);
                });

                tbody.appendChild(tr);
            });
            tbl.appendChild(tbody);
            wrap.appendChild(tbl);
            tableEl.appendChild(wrap);

        }).catch(err => {
            summaryEl.textContent = '';
            tableEl.textContent = '';
            _renderError(tableEl, 'Failed: ' + err.message, loadUsage);
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

    return function cleanup() {};
}
