/**
 * Usage view — compact rollup with conversation table.
 */
function renderUsageView(container) {
    const cleanups = UI.beginCleanupScope();
    let currentRange = '7d';
    let includeGenerated = UI.readQueryParam('include_generated', '') === '1';
    let hasLoaded = false;

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Usage</h2>';
    container.appendChild(header);

    const shell = document.createElement('section');
    shell.className = 'admin-shell';
    container.appendChild(shell);

    const controls = document.createElement('div');
    controls.className = 'route-controls';
    shell.appendChild(controls);

    const ranges = [
        { label: 'Today', value: '1d' },
        { label: '7 days', value: '7d' },
        { label: '30 days', value: '30d' },
    ];

    const rangeControl = UI.createSegmentedControl(ranges, (value) => {
        currentRange = value;
        loadUsage();
    }, {
        label: 'Usage date range',
        value: currentRange,
    });
    const rangeBar = rangeControl.element;
    controls.appendChild(rangeBar);

    const generatedToggle = document.createElement('a');
    generatedToggle.className = 'section-link';
    controls.appendChild(generatedToggle);

    const summaryEl = document.createElement('section');
    summaryEl.className = 'summary-rail';
    shell.appendChild(summaryEl);

    const tableShell = document.createElement('section');
    tableShell.className = 'list-shell';
    shell.appendChild(tableShell);

    const tableEl = document.createElement('div');
    tableEl.id = 'usage-table';
    tableShell.appendChild(tableEl);

    function tokenDetail(total, cached, available) {
        if (!available) {
            return '';
        }
        const uncached = Math.max(0, Number(total || 0) - Number(cached || 0));
        return `${uncached.toLocaleString()} uncached · ${Number(cached || 0).toLocaleString()} cached`;
    }

    function tokenCell(total, cached, available) {
        if (!available) {
            return Number(total || 0).toLocaleString();
        }
        const uncached = Math.max(0, Number(total || 0) - Number(cached || 0));
        return `${Number(total || 0).toLocaleString()} total · ${uncached.toLocaleString()} uncached · ${Number(cached || 0).toLocaleString()} cached`;
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
        const costAvailable = daily.cost_available !== false;
        const items = [
            {
                key: 'prompt',
                value: (daily.prompt_tokens || 0).toLocaleString(),
                label: 'Prompt tokens',
                detail: tokenDetail(
                    daily.prompt_tokens || 0,
                    daily.cached_prompt_tokens || 0,
                    daily.cached_prompt_tokens_available === true,
                ),
            },
            {
                key: 'completion',
                value: (daily.completion_tokens || 0).toLocaleString(),
                label: 'Completion tokens',
                detail: tokenDetail(
                    daily.completion_tokens || 0,
                    daily.cached_completion_tokens || 0,
                    daily.cached_completion_tokens_available === true,
                ),
            },
            {
                key: 'cost',
                value: costAvailable ? ('$' + (daily.cost_usd || 0).toFixed(4)) : '—',
                label: costAvailable ? 'Total cost' : 'Cost unavailable',
                detail: '',
            },
        ];
        UI.memoizedRender(summaryEl, items, (nextItems) => nextItems.map((item) => {
            const card = UI.renderStatCard(item);
            card.dataset.key = item.key;
            return card;
        }));
    }

    function updateGeneratedToggle() {
        const url = new URL(window.location.href);
        if (includeGenerated) {
            url.searchParams.delete('include_generated');
        } else {
            url.searchParams.set('include_generated', '1');
        }
        generatedToggle.href = `${url.pathname}${url.search}${url.hash}`;
        generatedToggle.textContent = includeGenerated ? 'Hide generated/audit usage' : 'Show generated/audit usage';
    }

    function visibleUsageRows(rows) {
        return UI.defaultVisibleRecords(rows || [], { includeHidden: includeGenerated });
    }

    function summarizeUsageRows(rows, fallback) {
        if (includeGenerated) {
            return fallback || {};
        }
        const summary = {
            prompt_tokens: 0,
            cached_prompt_tokens: 0,
            cached_prompt_tokens_available: rows.some((item) => item.cached_prompt_tokens_available === true),
            completion_tokens: 0,
            cached_completion_tokens: 0,
            cached_completion_tokens_available: rows.some((item) => item.cached_completion_tokens_available === true),
            cost_usd: 0,
            cost_available: rows.some((item) => item.cost_available !== false),
        };
        rows.forEach((item) => {
            summary.prompt_tokens += Number(item.prompt_tokens || 0);
            summary.cached_prompt_tokens += Number(item.cached_prompt_tokens || 0);
            summary.completion_tokens += Number(item.completion_tokens || 0);
            summary.cached_completion_tokens += Number(item.cached_completion_tokens || 0);
            if (item.cost_available !== false) {
                summary.cost_usd += Number(item.cost_usd || 0);
            }
        });
        return summary;
    }

    function renderTable(rows) {
        if (!rows.length) {
            UI.clearMemoizedRender(tableEl);
            UI.reconcileChildren(tableEl, [UI.renderEmptyState('No usage for this range.', true)]);
            return;
        }

        const showCost = rows.some((item) => item.cost_available !== false);
        UI.memoizedRender(tableEl, { rows, showCost }, (nextState) => {
        const nextRows = nextState.rows || [];
        const wrap = document.createElement('div');
        wrap.className = 'table-wrap';
        wrap.dataset.key = 'usage-table-wrap';

        const table = document.createElement('table');
        table.className = 'data-table responsive';

        const thead = document.createElement('thead');
        thead.innerHTML = nextState.showCost
            ? '<tr><th>Conversation</th><th>Prompt</th><th>Completion</th><th>Cost</th></tr>'
            : '<tr><th>Conversation</th><th>Prompt</th><th>Completion</th></tr>';
        table.appendChild(thead);

        const tbody = document.createElement('tbody');
        nextRows.forEach((item) => {
            const tr = document.createElement('tr');
            tr.dataset.key = item.conversation_id || '';

            const linkTd = document.createElement('td');
            linkTd.setAttribute('data-label', 'Conversation');
            const link = document.createElement('a');
            link.href = '/ui/conversations/' + encodeURIComponent(item.conversation_id || '');
            link.textContent = item.title || 'Conversation';
            linkTd.appendChild(link);
            tr.appendChild(linkTd);

            const cells = [
                ['Prompt', tokenCell(
                    item.prompt_tokens || 0,
                    item.cached_prompt_tokens || 0,
                    item.cached_prompt_tokens_available === true,
                )],
                ['Completion', tokenCell(
                    item.completion_tokens || 0,
                    item.cached_completion_tokens || 0,
                    item.cached_completion_tokens_available === true,
                )],
            ];
            if (nextState.showCost) {
                cells.push([
                    'Cost',
                    item.cost_available === false ? '—' : ('$' + (item.cost_usd || 0).toFixed(4)),
                ]);
            }
            cells.forEach(([label, value]) => {
                const td = document.createElement('td');
                td.setAttribute('data-label', label);
                td.textContent = value;
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        return [wrap];
        }, {
            signatureFn(nextRows) {
                const rows = nextRows?.rows || [];
                return {
                    showCost: !!nextRows?.showCost,
                    rows: rows.map((item) => ({
                        id: String(item.conversation_id || ''),
                        title: String(item.title || ''),
                        prompt: Number(item.prompt_tokens || 0),
                        cachedPrompt: Number(item.cached_prompt_tokens || 0),
                        cachedPromptAvailable: item.cached_prompt_tokens_available === true,
                        completion: Number(item.completion_tokens || 0),
                        cachedCompletion: Number(item.cached_completion_tokens || 0),
                        cachedCompletionAvailable: item.cached_completion_tokens_available === true,
                        cost: Number(item.cost_usd || 0),
                        costAvailable: item.cost_available !== false,
                    })),
                };
            },
        });
    }

    async function loadUsage({ soft = false } = {}) {
        try {
            const usage = await API.getUsage(_rangeToParams(currentRange));
            const daily = usage.daily_total || {};
            const rows = Array.isArray(usage) ? usage : (usage.by_conversation || []);
            const visibleRows = visibleUsageRows(rows);
            updateGeneratedToggle();
            renderSummary(summarizeUsageRows(visibleRows, daily));
            renderTable(visibleRows);
            hasLoaded = true;
        } catch (err) {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh usage', err, { context: 'Usage soft refresh failed' });
                return;
            }
            UI.clearMemoizedRender(summaryEl);
            UI.clearMemoizedRender(tableEl);
            UI.reconcileChildren(summaryEl, []);
            UI.reconcileChildren(tableEl, [UI.createErrorCard('Failed to load usage: ' + err.message, loadUsage)]);
        }
    }

    updateGeneratedToggle();
    UI.subscribeWithRefresh(cleanups, 'usage', () => loadUsage({ soft: true }), 500);
    container.__routeReady = loadUsage();
}
