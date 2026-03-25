/**
 * Agent detail — compact profile with direct conversation entry.
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

    const header = document.createElement('header');
    header.className = 'workspace-header workspace-header-compact';
    container.appendChild(header);

    const content = document.createElement('div');
    content.className = 'agent-detail-grid';
    container.appendChild(content);
    UI.reconcileChildren(content, UI.createSkeletonNodes(3, 'card'));

    function buildHeader(agent) {
        const titleRow = document.createElement('div');
        titleRow.className = 'workspace-header-main';

        const titleWrap = document.createElement('div');
        titleWrap.className = 'workspace-title-group';
        const title = document.createElement('h2');
        title.textContent = agent.display_name || agent.slug || agent.agent_id;
        titleWrap.appendChild(title);

        const meta = document.createElement('div');
        meta.className = 'meta-inline';
        [
            agent.role || 'agent',
            agent.provider || '',
            agent.slug || '',
            agent.last_heartbeat_at ? UI.relativeTime(agent.last_heartbeat_at) : '',
        ].filter(Boolean).forEach((text, index, arr) => {
            const span = document.createElement('span');
            span.textContent = text;
            meta.appendChild(span);
            if (index < arr.length - 1) meta.appendChild(document.createTextNode(' · '));
        });
        titleWrap.appendChild(meta);
        titleRow.appendChild(titleWrap);

        const actions = document.createElement('div');
        actions.className = 'workspace-actions';
        const status = document.createElement('span');
        status.className = `badge badge-${agent.connectivity_state || 'stopped'}`;
        status.textContent = agent.connectivity_state || 'unknown';
        actions.appendChild(status);

        const openConversationBtn = document.createElement('button');
        openConversationBtn.type = 'button';
        openConversationBtn.className = 'btn btn-sm btn-primary';
        openConversationBtn.textContent = 'Open conversation';
        openConversationBtn.disabled = openConversationBusy;
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
        actions.appendChild(openConversationBtn);
        titleRow.appendChild(actions);

        UI.reconcileChildren(header, [titleRow]);
    }

    function buildOverviewCard(agent) {
        const card = document.createElement('section');
        card.className = 'card workspace-section';
        card.dataset.key = 'overview';

        const head = document.createElement('div');
        head.className = 'section-header';
        head.innerHTML = '<strong>Overview</strong>';
        card.appendChild(head);

        const grid = document.createElement('div');
        grid.className = 'metadata-grid';
        [
            ['Agent ID', agent.agent_id || '—'],
            ['Scope', agent.registry_scope || '—'],
            ['Version', agent.version || '—'],
            ['Last heartbeat', agent.last_heartbeat_at ? UI.relativeTime(agent.last_heartbeat_at) : 'never'],
        ].forEach(([label, value]) => {
            const fact = document.createElement('div');
            fact.className = 'metadata-item';
            fact.innerHTML = `<span>${UI.esc(label)}</span><strong>${UI.esc(value)}</strong>`;
            grid.appendChild(fact);
        });
        card.appendChild(grid);

        if ((agent.capabilities || []).length) {
            const chips = document.createElement('div');
            chips.className = 'chip-row';
            agent.capabilities.forEach((capability) => {
                const chip = document.createElement('span');
                chip.className = 'quickstart-chip static';
                chip.textContent = capability;
                chips.appendChild(chip);
            });
            card.appendChild(chips);
        }

        return card;
    }

    function buildWorkersCard(workers) {
        const card = document.createElement('section');
        card.className = 'card workspace-section';
        card.dataset.key = 'workers';

        const head = document.createElement('div');
        head.className = 'section-header';
        head.innerHTML = '<strong>Workers</strong>';
        card.appendChild(head);

        if (!workers.length) {
            card.appendChild(UI.renderEmptyState('No worker processes.', true));
            return card;
        }

        const wrap = document.createElement('div');
        wrap.className = 'table-wrap';
        const table = document.createElement('table');
        table.className = 'data-table responsive';
        table.innerHTML = '<thead><tr><th>Worker</th><th>Role</th><th>Current</th><th>Last seen</th></tr></thead>';
        const tbody = document.createElement('tbody');
        workers.forEach((worker) => {
            const tr = document.createElement('tr');
            [
                ['Worker', worker.worker_id || '—'],
                ['Role', worker.process_role || '—'],
                ['Current', worker.current_item_id || 'idle'],
                ['Last seen', worker.last_seen_at ? UI.relativeTime(worker.last_seen_at) : '—'],
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
        card.appendChild(wrap);
        return card;
    }

    function buildConversationsSection() {
        const section = document.createElement('section');
        section.className = 'workspace-section';
        section.dataset.key = 'conversations';

        const head = document.createElement('div');
        head.className = 'section-header';
        head.innerHTML = '<strong>Conversations</strong>';
        section.appendChild(head);

        const list = document.createElement('div');
        list.id = 'agent-conversations-list';
        list.className = 'list-container';
        section.appendChild(list);

        const pag = document.createElement('div');
        pag.id = 'agent-conversations-pagination';
        pag.className = 'pagination-shell';
        section.appendChild(pag);
        return section;
    }

    function renderConversationRows(conversations, data) {
        const list = document.getElementById('agent-conversations-list');
        const pag = document.getElementById('agent-conversations-pagination');
        if (!list || !pag) return;

        if (!conversations.length) {
            UI.reconcileChildren(list, [UI.renderEmptyState('No conversations.', true)]);
            UI.reconcileChildren(pag, []);
            return;
        }

        const rows = conversations.map((item) => {
            const sub = document.createElement('span');
            sub.textContent = [
                item.origin_channel || 'registry',
                UI.relativeTime(item.updated_at || item.created_at),
            ].filter(Boolean).join(' · ');
            const row = UI.renderListRow({
                href: '/ui/conversations/' + item.conversation_id,
                label: item.title || item.conversation_id,
                sublabelNode: sub,
                badgeText: item.status || 'open',
                badgeClass: 'badge-' + (item.status || 'open'),
            });
            row.dataset.key = item.conversation_id;
            return row;
        });
        UI.reconcileChildren(list, rows);

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
        conversationsLoaded = true;
    }

    function loadConversations({ soft = false } = {}) {
        const list = document.getElementById('agent-conversations-list');
        const pag = document.getElementById('agent-conversations-pagination');
        if (!list || !pag) return;
        if (!soft || !conversationsLoaded) {
            UI.reconcileChildren(list, UI.createSkeletonNodes(4, 'row'));
            UI.reconcileChildren(pag, []);
        }
        API.getAgentConversations(agentId, { cursor: convosCursor, limit: convosLimit }).then((data) => {
            renderConversationRows(data.conversations || data || [], data);
        }).catch((err) => {
            if (soft && conversationsLoaded) {
                UI.reportError('Failed to refresh agent conversations', err, { context: 'Agent detail conversation soft refresh failed' });
                return;
            }
            UI.reconcileChildren(list, [UI.createErrorCard('Failed to load conversations: ' + err.message, loadConversations)]);
            UI.reconcileChildren(pag, []);
        });
    }

    function loadDetail({ soft = false } = {}) {
        if (!soft || !detailLoaded) {
            UI.reconcileChildren(content, UI.createSkeletonNodes(3, 'card'));
        }
        API.getAgentStatus(agentId).then((status) => {
            if (!status) {
                UI.reconcileChildren(content, [UI.renderEmptyState('Agent not found.', true)]);
                return;
            }
            const agent = status.agent || status;
            const workers = status.workers || [];
            agentDisplayName = agent.display_name || agent.slug || agent.agent_id || agentId;
            openConversationBusy = false;

            buildHeader(agent);
            UI.reconcileChildren(content, [
                buildOverviewCard(agent),
                buildWorkersCard(workers),
                buildConversationsSection(),
            ]);
            detailLoaded = true;
            loadConversations();
        }).catch((err) => {
            UI.reconcileChildren(content, [UI.createErrorCard('Failed to load agent: ' + err.message, loadDetail)]);
        });
    }

    let detailReload = null;
    let convosReload = null;
    cleanups.add(WS.subscribe(`agent:${agentId}`, () => {
        clearTimeout(detailReload);
        detailReload = setTimeout(() => loadDetail({ soft: true }), 300);
    }));
    cleanups.add(WS.subscribe('conversations', () => {
        clearTimeout(convosReload);
        convosReload = setTimeout(() => loadConversations({ soft: true }), 350);
    }));

    loadDetail();
    cleanups.add(() => clearTimeout(detailReload));
    cleanups.add(() => clearTimeout(convosReload));
}

function renderAgentConversations(container, params) {
    renderAgentDetail(container, params);
}
