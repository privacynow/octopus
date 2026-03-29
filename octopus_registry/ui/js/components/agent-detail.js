/**
 * Agent detail — compact profile with direct conversation entry.
 */
function renderAgentDetail(container, params) {
    const agentId = params.id;
    const cleanups = UI.beginCleanupScope();
    const convosLimit = UI.DEFAULT_PAGE_LIMIT;
    let detailLoaded = false;
    let conversationsLoaded = false;
    let agentDisplayName = '';
    let openConversationBusy = false;
    let conversationListEl = null;
    let taskThreadListEl = null;
    let taskThreadGroupEl = null;
    let conversationPaginationEl = null;
    let conversationPaginator = null;

    const header = document.createElement('header');
    header.className = 'workspace-header workspace-header-compact';
    container.appendChild(header);

    const content = document.createElement('div');
    content.className = 'agent-detail-grid';
    container.appendChild(content);

    function buildHeader(agent) {
        const titleRow = document.createElement('div');
        titleRow.className = 'workspace-header-main';

        const titleWrap = document.createElement('div');
        titleWrap.className = 'workspace-title-group';
        const title = document.createElement('h2');
        title.textContent = agent.display_name || agent.slug || 'Agent';
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

        const groups = document.createElement('div');
        groups.className = 'agent-detail-conversation-groups';

        const conversationsGroup = document.createElement('div');
        conversationsGroup.className = 'agent-detail-conversation-group';
        conversationsGroup.dataset.key = 'direct-conversations';
        const conversationsLabel = document.createElement('div');
        conversationsLabel.className = 'agent-detail-conversation-group-title';
        conversationsLabel.textContent = 'Conversations';
        conversationsGroup.appendChild(conversationsLabel);
        const list = document.createElement('div');
        list.className = 'list-container';
        conversationListEl = list;
        conversationsGroup.appendChild(list);
        groups.appendChild(conversationsGroup);

        const taskThreadsGroup = document.createElement('div');
        taskThreadsGroup.className = 'agent-detail-conversation-group';
        taskThreadsGroup.dataset.key = 'task-threads';
        taskThreadsGroup.hidden = true;
        taskThreadGroupEl = taskThreadsGroup;
        const taskThreadsLabel = document.createElement('div');
        taskThreadsLabel.className = 'agent-detail-conversation-group-title';
        taskThreadsLabel.textContent = 'Task threads';
        taskThreadsGroup.appendChild(taskThreadsLabel);
        const taskList = document.createElement('div');
        taskList.className = 'list-container';
        taskThreadListEl = taskList;
        taskThreadsGroup.appendChild(taskList);
        groups.appendChild(taskThreadsGroup);

        section.appendChild(groups);

        const pag = document.createElement('div');
        pag.className = 'pagination-shell';
        conversationPaginationEl = pag;
        section.appendChild(pag);
        conversationPaginator = UI.createCursorPaginator(pag, () => loadConversations());
        return section;
    }

    function renderConversationRows(conversations, data) {
        const list = conversationListEl;
        const taskList = taskThreadListEl;
        const taskThreadsGroup = taskThreadGroupEl;
        if (!list || !taskList || !taskThreadsGroup || !conversationPaginator) return;

        if (!conversations.length) {
            UI.clearMemoizedRender(list);
            UI.clearMemoizedRender(taskList);
            UI.reconcileChildren(list, [UI.renderEmptyState('No conversations.', true)]);
            UI.reconcileChildren(taskList, []);
            taskThreadsGroup.hidden = true;
            conversationPaginator.clear();
            return;
        }

        const buildRows = (items) => items.map((item) => {
            const rowSignature = UI.dataSignature({
                id: String(item.conversation_id || ''),
                type: String(item.conversation_type || 'conversation'),
                status: String(item.status || ''),
                updatedLabel: UI.relativeTime(item.updated_at || item.created_at),
                title: String(item.title || ''),
                origin: String(item.origin_channel || ''),
            });
            const sub = document.createElement('span');
            sub.textContent = [
                item.conversation_type === 'task_thread' ? 'task thread' : '',
                item.origin_channel || 'registry',
                UI.relativeTime(item.updated_at || item.created_at),
            ].filter(Boolean).join(' · ');
            const row = UI.renderListRow({
                href: '/ui/conversations/' + item.conversation_id,
                label: item.title || (item.conversation_type === 'task_thread' ? 'Task thread' : 'Conversation'),
                sublabelNode: sub,
                badgeText: item.status || 'open',
                badgeClass: 'badge-' + (item.status || 'open'),
                trailing: UI.buildConversationTypeBadge(item),
                className: item.conversation_type === 'task_thread' ? 'list-row-task-thread' : '',
                signature: rowSignature,
            });
            row.dataset.key = item.conversation_id;
            return row;
        });

        const directConversations = conversations.filter(
            (item) => String(item.conversation_type || 'conversation') !== 'task_thread',
        );
        const taskThreads = conversations.filter(
            (item) => String(item.conversation_type || 'conversation') === 'task_thread',
        );

        if (directConversations.length) {
            UI.memoizedRender(list, directConversations, buildRows, {
                signatureFn(items) {
                    return (items || []).map((item) => ({
                        id: String(item.conversation_id || ''),
                        type: String(item.conversation_type || 'conversation'),
                        status: String(item.status || ''),
                        updatedLabel: UI.relativeTime(item.updated_at || item.created_at),
                        title: String(item.title || ''),
                        origin: String(item.origin_channel || ''),
                    }));
                },
            });
        } else {
            UI.clearMemoizedRender(list);
            UI.reconcileChildren(list, [UI.renderEmptyState('No direct conversations.', true)]);
        }

        if (taskThreads.length) {
            taskThreadsGroup.hidden = false;
            UI.memoizedRender(taskList, taskThreads, buildRows, {
                signatureFn(items) {
                    return (items || []).map((item) => ({
                        id: String(item.conversation_id || ''),
                        type: String(item.conversation_type || 'conversation'),
                        status: String(item.status || ''),
                        updatedLabel: UI.relativeTime(item.updated_at || item.created_at),
                        title: String(item.title || ''),
                        origin: String(item.origin_channel || ''),
                    }));
                },
            });
        } else {
            taskThreadsGroup.hidden = true;
            UI.clearMemoizedRender(taskList);
            UI.reconcileChildren(taskList, []);
        }

        conversationPaginator.render({ hasMore: !!data.has_more, nextCursor: data.next_cursor });
        conversationsLoaded = true;
    }

    async function loadConversations({ soft = false } = {}) {
        const list = conversationListEl;
        if (!list || !conversationPaginator) return;
        try {
            const data = await API.getAgentConversations(agentId, { cursor: conversationPaginator.cursor, limit: convosLimit });
            renderConversationRows(data.conversations || data || [], data);
        } catch (err) {
            if (soft && conversationsLoaded) {
                UI.reportError('Failed to refresh agent conversations', err, { context: 'Agent detail conversation soft refresh failed' });
                return;
            }
            UI.clearMemoizedRender(list);
            UI.reconcileChildren(list, [UI.createErrorCard('Failed to load conversations: ' + err.message, loadConversations)]);
            conversationPaginator.clear();
        }
    }

    async function loadDetail({ soft = false } = {}) {
        try {
            const status = await API.getAgentStatus(agentId);
            if (!status) {
                UI.reconcileChildren(content, [UI.renderEmptyState('Agent not found.', true)]);
                return;
            }
            const agent = status.agent || status;
            const workers = status.workers || [];
            const signature = UI.dataSignature({
                agent: {
                    id: String(agent.agent_id || ''),
                    display: String(agent.display_name || agent.slug || ''),
                    slug: String(agent.slug || ''),
                    role: String(agent.role || ''),
                    provider: String(agent.provider || ''),
                    connectivity: String(agent.connectivity_state || ''),
                    heartbeatLabel: agent.last_heartbeat_at ? UI.relativeTime(agent.last_heartbeat_at) : '',
                    scope: String(agent.registry_scope || ''),
                    version: String(agent.version || ''),
                    capabilities: (agent.capabilities || []).map((capability) => String(capability || '')),
                },
                workers: workers.map((worker) => ({
                    id: String(worker.worker_id || ''),
                    role: String(worker.process_role || ''),
                    current: String(worker.current_item_id || ''),
                    lastSeenLabel: worker.last_seen_at ? UI.relativeTime(worker.last_seen_at) : '',
                })),
            });
            agentDisplayName = agent.display_name || agent.slug || 'Agent';
            openConversationBusy = false;

            buildHeader(agent);
            const detailRender = UI.memoizedRender(content, signature, () => [
                buildOverviewCard(agent),
                buildWorkersCard(workers),
                buildConversationsSection(),
            ], {
                signatureFn(value) {
                    return value;
                },
            });
            detailLoaded = true;
            if (detailRender.changed) {
                conversationsLoaded = false;
                UI.clearMemoizedRender(conversationListEl);
                UI.clearMemoizedRender(taskThreadListEl);
                if (conversationPaginator) {
                    conversationPaginator.reset();
                }
            }
            await loadConversations({ soft: detailRender.changed ? false : soft });
        } catch (err) {
            UI.clearMemoizedRender(content);
            UI.reconcileChildren(content, [UI.createErrorCard('Failed to load agent: ' + err.message, loadDetail)]);
        }
    }

    container.__routeReady = loadDetail();
    UI.subscribeWithRefresh(cleanups, `agent:${agentId}`, () => loadDetail({ soft: true }), 300);
    UI.subscribeWithRefresh(cleanups, 'conversations', () => loadConversations({ soft: true }), 350);
}

function renderAgentConversations(container, params) {
    return renderAgentDetail(container, params);
}
