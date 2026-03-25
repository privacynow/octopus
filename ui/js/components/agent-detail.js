/**
 * Agent detail — status, capabilities, workers, conversations sub-list.
 */
function renderAgentDetail(container, params) {
    const agentId = params.id;
    const cleanups = UI.beginCleanupScope();
    let convosCursor = 0;
    let convosCursorStack = [];
    const convosLimit = UI.DEFAULT_PAGE_LIMIT;
    let detailLoaded = false;
    let conversationsLoaded = false;
    let agentDisplayName = '';
    let openConversationBusy = false;

    // Shell
    const header = document.createElement('div');
    header.className = 'page-header';
    header.innerHTML = '<h2>Agent Detail</h2><p>Loading...</p>';
    container.appendChild(header);

    const headerActions = document.createElement('div');
    headerActions.className = 'page-header-actions';
    container.appendChild(headerActions);

    const openConversationBtn = document.createElement('button');
    openConversationBtn.type = 'button';
    openConversationBtn.className = 'btn btn-primary';
    openConversationBtn.textContent = 'Open conversation';
    openConversationBtn.disabled = true;
    openConversationBtn.addEventListener('click', async () => {
        if (openConversationBusy) return;
        openConversationBusy = true;
        openConversationBtn.disabled = true;
        openConversationBtn.textContent = 'Opening…';
        try {
            const conversation = await API.openConversationForAgent(agentId, {
                title: `Conversation with ${agentDisplayName || agentId}`,
            });
            Router.navigate('/ui/conversations/' + conversation.conversation_id);
        } catch (err) {
            UI.reportError('Failed to open a conversation for this agent', err, { context: 'Agent detail open conversation failed' });
            openConversationBusy = false;
            openConversationBtn.disabled = false;
            openConversationBtn.textContent = 'Open conversation';
        }
    });
    headerActions.appendChild(openConversationBtn);

    const content = document.createElement('div');
    content.id = 'agent-detail-content';
    container.appendChild(content);
    UI.reconcileChildren(content, UI.createSkeletonNodes(3, 'card'));

    function loadDetail({ soft = false } = {}) {
        if (!soft || !detailLoaded) {
            UI.reconcileChildren(content, UI.createSkeletonNodes(3, 'card'));
        }
        API.getAgentStatus(agentId).then(status => {
            if (!status) {
                UI.reconcileChildren(content, [UI.renderEmptyState('Agent not found')]);
                return;
            }
            const a = status.agent || status;
            agentDisplayName = a.display_name || a.slug || a.agent_id || agentId;
            openConversationBusy = false;
            openConversationBtn.disabled = false;
            openConversationBtn.textContent = 'Open conversation';
            const workers = status.workers || [];

            // Update header
            const h2 = document.createElement('h2');
            h2.textContent = a.display_name || a.slug;

            const p = document.createElement('p');
            const badge = document.createElement('span');
            badge.className = 'badge badge-' + (a.connectivity_state || 'stopped');
            badge.id = 'agent-status-badge';
            badge.textContent = a.connectivity_state || 'unknown';
            p.textContent = (a.role || 'agent') + ' \u00b7 ' + (a.provider || '') + ' ';
            p.appendChild(badge);
            UI.reconcileChildren(header, [h2, p]);

            // Info card
            const infoCard = document.createElement('div');
            infoCard.className = 'card';
            infoCard.dataset.key = 'agent-info';
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

            // Workers table
            const sections = [infoCard];
            if (workers.length > 0) {
                const wCard = document.createElement('div');
                wCard.className = 'card';
                wCard.dataset.key = 'agent-workers';
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
                sections.push(wCard);
            }

            // Conversations sub-list
            const convosSection = document.createElement('div');
            convosSection.dataset.key = 'agent-conversations';
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
            sections.push(convosSection);
            UI.reconcileChildren(content, sections);

            loadConversations();
            detailLoaded = true;

        }).catch(err => {
            UI.reconcileChildren(content, [UI.createErrorCard('Failed to load agent: ' + err.message, loadDetail)]);
        });
    }

    function loadConversations({ soft = false } = {}) {
        const list = document.getElementById('agent-convos-list');
        const pag = document.getElementById('agent-convos-pag');
        if (!list) return;
        if (!soft || !conversationsLoaded) {
            list.className = 'list-container';
            UI.reconcileChildren(list, UI.createSkeletonNodes(3, 'row'));
            if (pag) UI.reconcileChildren(pag, []);
        }

        API.getAgentConversations(agentId, { cursor: convosCursor, limit: convosLimit }).then(data => {
            const convos = data.conversations || data || [];
            if (pag) UI.reconcileChildren(pag, []);

            if (convos.length === 0) {
                UI.reconcileChildren(list, [UI.renderEmptyState('No conversations')]);
                return;
            }

            const rows = convos.map((c) => {
                const sub = document.createElement('span');
                const ts = document.createElement('span');
                ts.setAttribute('data-timestamp', c.created_at || '');
                ts.textContent = UI.relativeTime(c.created_at);
                sub.appendChild(document.createTextNode((c.origin_channel || '') + ' \u00b7 '));
                sub.appendChild(ts);
                const row = UI.renderListRow({
                    href: '/ui/conversations/' + c.conversation_id,
                    label: c.title || c.conversation_id,
                    sublabelNode: sub,
                    badgeText: c.status || 'open',
                    badgeClass: 'badge-' + (c.status || 'open'),
                });
                row.dataset.key = c.conversation_id;
                return row;
            });
            UI.reconcileChildren(list, rows);

            if (pag) {
                const wrapper = document.createElement('div');
                UI.renderPagination(wrapper, {
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
                UI.reconcileChildren(pag, Array.from(wrapper.childNodes));
            }
            conversationsLoaded = true;
        }).catch(err => {
            UI.reconcileChildren(list, [UI.createErrorCard('Failed to load conversations: ' + err.message, loadConversations)]);
            if (pag) UI.reconcileChildren(pag, []);
        });
    }

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

    const unsubEvents = WS.subscribe('conversations', () => {
        clearTimeout(reloadDebounce);
        reloadDebounce = setTimeout(() => loadConversations({ soft: true }), 400);
    });
    cleanups.add(unsubEvents);
    cleanups.add(WS.subscribe('agents', () => {
        clearTimeout(reloadDebounce);
        reloadDebounce = setTimeout(() => loadDetail({ soft: true }), 400);
    }));

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
        listEl.className = 'list-container';
        UI.reconcileChildren(listEl, UI.createSkeletonNodes(5, 'row'));
        UI.reconcileChildren(pagEl, []);

        API.getAgentConversations(agentId, { cursor, limit }).then(data => {
            const convos = data.conversations || data || [];

            if (convos.length === 0) {
                UI.reconcileChildren(listEl, [UI.renderEmptyState('No conversations')]);
                return;
            }

            const rows = convos.map((c) => {
                const sub = document.createElement('span');
                const ts = document.createElement('span');
                ts.setAttribute('data-timestamp', c.created_at || '');
                ts.textContent = UI.relativeTime(c.created_at);
                sub.appendChild(document.createTextNode((c.origin_channel || '') + ' \u00b7 '));
                sub.appendChild(ts);
                const row = UI.renderListRow({
                    href: '/ui/conversations/' + c.conversation_id,
                    label: c.title || c.conversation_id,
                    sublabelNode: sub,
                    badgeText: c.status || 'open',
                    badgeClass: 'badge-' + (c.status || 'open'),
                });
                row.dataset.key = c.conversation_id;
                return row;
            });
            UI.reconcileChildren(listEl, rows);

            const wrapper = document.createElement('div');
            UI.renderPagination(wrapper, {
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
            UI.reconcileChildren(pagEl, Array.from(wrapper.childNodes));
        }).catch(err => {
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed: ' + err.message, loadPage)]);
            UI.reconcileChildren(pagEl, []);
        });
    }

    loadPage();

}
