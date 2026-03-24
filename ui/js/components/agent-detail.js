/**
 * Agent detail — status, capabilities, workers, conversations sub-list.
 */
function renderAgentDetail(container, params) {
    const agentId = params.id;
    const cleanups = UI.beginCleanupScope();
    let convosCursor = 0;
    let convosCursorStack = [];
    const convosLimit = UI.DEFAULT_PAGE_LIMIT;

    // Shell
    const header = document.createElement('div');
    header.className = 'page-header';
    header.innerHTML = '<h2>Agent Detail</h2><p>Loading...</p>';
    container.appendChild(header);

    const content = document.createElement('div');
    content.id = 'agent-detail-content';
    container.appendChild(content);
    UI.renderSkeletons(content, 3, 'card');

    function loadDetail() {
        API.getAgentStatus(agentId).then(status => {
            if (!status) {
                content.textContent = '';
                const empty = document.createElement('div');
                empty.className = 'empty-state';
                empty.textContent = 'Agent not found';
                content.appendChild(empty);
                return;
            }
            const a = status.agent || status;
            const workers = status.workers || [];

            // Update header
            header.textContent = '';
            const h2 = document.createElement('h2');
            h2.textContent = a.display_name || a.slug;
            header.appendChild(h2);

            const p = document.createElement('p');
            const badge = document.createElement('span');
            badge.className = 'badge badge-' + (a.connectivity_state || 'stopped');
            badge.id = 'agent-status-badge';
            badge.textContent = a.connectivity_state || 'unknown';
            p.textContent = (a.role || 'agent') + ' \u00b7 ' + (a.provider || '') + ' ';
            p.appendChild(badge);
            header.appendChild(p);

            content.textContent = '';

            // Info card
            const infoCard = document.createElement('div');
            infoCard.className = 'card';
            const infoTitle = document.createElement('div');
            infoTitle.className = 'card-title';
            infoTitle.textContent = 'Info';
            infoCard.appendChild(infoTitle);

            const wrap = document.createElement('div');
            wrap.className = 'table-wrap';
            const tbl = document.createElement('table');
            tbl.className = 'data-table';
            const rows = [
                ['Agent ID', a.agent_id],
                ['Slug', a.slug],
                ['Scope', a.registry_scope || ''],
                ['Version', a.version || ''],
                ['Last Heartbeat', a.last_heartbeat_at || 'never'],
            ];
            rows.forEach(([label, val]) => {
                const tr = document.createElement('tr');
                const tdL = document.createElement('td');
                tdL.textContent = label;
                const tdV = document.createElement('td');
                if (label === 'Last Heartbeat' && a.last_heartbeat_at) {
                    tdV.setAttribute('data-timestamp', a.last_heartbeat_at);
                    tdV.textContent = UI.relativeTime(a.last_heartbeat_at);
                } else {
                    tdV.textContent = val;
                }
                tr.appendChild(tdL);
                tr.appendChild(tdV);
                tbl.appendChild(tr);
            });
            wrap.appendChild(tbl);
            infoCard.appendChild(wrap);

            // Capabilities as badges
            if (a.capabilities && a.capabilities.length > 0) {
                const capRow = document.createElement('div');
                capRow.style.marginTop = '8px';
                a.capabilities.forEach(c => {
                    const b = document.createElement('span');
                    b.className = 'badge badge-open';
                    b.textContent = c;
                    b.style.marginRight = '4px';
                    capRow.appendChild(b);
                });
                infoCard.appendChild(capRow);
            }

            // Tags as badges
            if (a.tags && a.tags.length > 0) {
                const tagRow = document.createElement('div');
                tagRow.style.marginTop = '8px';
                a.tags.forEach(t => {
                    const b = document.createElement('span');
                    b.className = 'badge badge-completed';
                    b.textContent = t;
                    b.style.marginRight = '4px';
                    tagRow.appendChild(b);
                });
                infoCard.appendChild(tagRow);
            }

            content.appendChild(infoCard);

            // Workers table
            if (workers.length > 0) {
                const wCard = document.createElement('div');
                wCard.className = 'card';
                const wTitle = document.createElement('div');
                wTitle.className = 'card-title';
                wTitle.textContent = 'Workers';
                wCard.appendChild(wTitle);

                const wWrap = document.createElement('div');
                wWrap.className = 'table-wrap';
                const wTbl = document.createElement('table');
                wTbl.className = 'data-table responsive';

                const thead = document.createElement('thead');
                thead.innerHTML = '<tr><th>Worker</th><th>Role</th><th>Current</th><th>Last Seen</th></tr>';
                wTbl.appendChild(thead);

                const tbody = document.createElement('tbody');
                workers.forEach(w => {
                    const tr = document.createElement('tr');
                    const cells = [
                        ['Worker', w.worker_id || ''],
                        ['Role', w.process_role || ''],
                        ['Current', w.current_item_id || 'idle'],
                        ['Last Seen', w.last_seen_at ? UI.relativeTime(w.last_seen_at) : ''],
                    ];
                    cells.forEach(([label, val]) => {
                        const td = document.createElement('td');
                        td.setAttribute('data-label', label);
                        td.textContent = val;
                        tr.appendChild(td);
                    });
                    tbody.appendChild(tr);
                });
                wTbl.appendChild(tbody);
                wWrap.appendChild(wTbl);
                wCard.appendChild(wWrap);
                content.appendChild(wCard);
            }

            // Conversations sub-list
            const convosSection = document.createElement('div');
            convosSection.id = 'agent-convos-section';
            const convosTitle = document.createElement('div');
            convosTitle.className = 'card-title';
            convosTitle.textContent = 'Conversations';
            convosTitle.style.marginTop = '16px';
            convosTitle.style.marginBottom = '12px';
            convosSection.appendChild(convosTitle);
            const convosList = document.createElement('div');
            convosList.id = 'agent-convos-list';
            convosSection.appendChild(convosList);
            const convosPag = document.createElement('div');
            convosPag.id = 'agent-convos-pag';
            convosSection.appendChild(convosPag);
            content.appendChild(convosSection);

            loadConversations();

        }).catch(err => {
            content.textContent = '';
            UI.renderError(content, 'Failed to load agent: ' + err.message, loadDetail);
        });
    }

    function loadConversations() {
        const list = document.getElementById('agent-convos-list');
        const pag = document.getElementById('agent-convos-pag');
        if (!list) return;
        list.textContent = '';
        list.className = 'list-container';
        UI.renderSkeletons(list, 3, 'row');

        API.getAgentConversations(agentId, { cursor: convosCursor, limit: convosLimit }).then(data => {
            const convos = data.conversations || data || [];
            list.textContent = '';
            if (pag) pag.textContent = '';

            if (convos.length === 0) {
                list.appendChild(UI.renderEmptyState('No conversations'));
                return;
            }

            convos.forEach(c => {
                const sub = document.createElement('span');
                const ts = document.createElement('span');
                ts.setAttribute('data-timestamp', c.created_at || '');
                ts.textContent = UI.relativeTime(c.created_at);
                sub.appendChild(document.createTextNode((c.origin_channel || '') + ' \u00b7 '));
                sub.appendChild(ts);
                list.appendChild(UI.renderListRow({
                    href: '/ui/conversations/' + c.conversation_id,
                    label: c.title || c.conversation_id,
                    sublabelNode: sub,
                    badgeText: c.status || 'open',
                    badgeClass: 'badge-' + (c.status || 'open'),
                }));
            });

            if (pag) {
                UI.renderPagination(pag, {
                    hasPrev: convosCursorStack.length > 0,
                    hasNext: !!data.has_more,
                    info: '',
                    onPrev: () => {
                        convosCursor = convosCursorStack.pop() || 0;
                        loadConversations();
                    },
                    onNext: () => {
                        convosCursorStack.push(convosCursor);
                        convosCursor = data.next_cursor;
                        loadConversations();
                    },
                });
            }
        }).catch(err => {
            list.textContent = '';
            UI.renderError(list, 'Failed to load conversations: ' + err.message, loadConversations);
        });
    }

    // WS: subscribe to agent-specific + wildcard for full live updates
    let reloadDebounce = null;
    const unsub = WS.subscribe('agent:' + agentId, (msg) => {
        if (msg.type === 'heartbeat' && msg.data) {
            const badge = document.getElementById('agent-status-badge');
            if (badge && msg.data.connectivity_state) {
                badge.className = 'badge badge-' + msg.data.connectivity_state;
                badge.textContent = msg.data.connectivity_state;
            }
        }
    });
    cleanups.add(unsub);

    // Also reload conversations sub-list on any event for this agent
    const unsubEvents = WS.subscribe('*', (msg) => {
        if (msg.type === 'event' && msg.data && msg.data.agent_id === agentId) {
            clearTimeout(reloadDebounce);
            reloadDebounce = setTimeout(loadConversations, 2000);
        }
    });
    cleanups.add(unsubEvents);

    loadDetail();
    cleanups.add(() => clearTimeout(reloadDebounce));
}

/**
 * Agent conversations — dedicated page (kept for route compatibility).
 */
function renderAgentConversations(container, params) {
    const agentId = params.id;
    let cursor = 0;
    let cursorStack = [];
    const limit = UI.DEFAULT_PAGE_LIMIT;

    const header = document.createElement('div');
    header.className = 'page-header';
    const h2 = document.createElement('h2');
    h2.textContent = 'Agent Conversations';
    header.appendChild(h2);
    const backLink = document.createElement('p');
    const a = document.createElement('a');
    a.href = '/ui/agents/' + agentId;
    a.textContent = '\u2190 Back to agent';
    backLink.appendChild(a);
    header.appendChild(backLink);
    container.appendChild(header);

    const listEl = document.createElement('div');
    listEl.id = 'agent-convos';
    container.appendChild(listEl);

    const pagEl = document.createElement('div');
    container.appendChild(pagEl);

    function loadPage() {
        listEl.textContent = '';
        listEl.className = 'list-container';
        UI.renderSkeletons(listEl, 5, 'row');

        API.getAgentConversations(agentId, { cursor, limit }).then(data => {
            const convos = data.conversations || data || [];
            listEl.textContent = '';
            pagEl.textContent = '';

            if (convos.length === 0) {
                listEl.appendChild(UI.renderEmptyState('No conversations'));
                return;
            }

            convos.forEach(c => {
                const sub = document.createElement('span');
                const ts = document.createElement('span');
                ts.setAttribute('data-timestamp', c.created_at || '');
                ts.textContent = UI.relativeTime(c.created_at);
                sub.appendChild(document.createTextNode((c.origin_channel || '') + ' \u00b7 '));
                sub.appendChild(ts);
                listEl.appendChild(UI.renderListRow({
                    href: '/ui/conversations/' + c.conversation_id,
                    label: c.title || c.conversation_id,
                    sublabelNode: sub,
                    badgeText: c.status || 'open',
                    badgeClass: 'badge-' + (c.status || 'open'),
                }));
            });

            UI.renderPagination(pagEl, {
                hasPrev: cursorStack.length > 0,
                hasNext: !!data.has_more,
                info: '',
                onPrev: () => {
                    cursor = cursorStack.pop() || 0;
                    loadPage();
                },
                onNext: () => {
                    cursorStack.push(cursor);
                    cursor = data.next_cursor;
                    loadPage();
                },
            });
        }).catch(err => {
            listEl.textContent = '';
            UI.renderError(listEl, 'Failed: ' + err.message, loadPage);
        });
    }

    loadPage();

}
