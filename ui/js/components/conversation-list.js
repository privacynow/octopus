/**
 * Conversation list — all conversations with search/filter and pagination.
 */
function renderConversationList(container) {
    const cleanups = UI.beginCleanupScope();
    let cursor = 0;
    let cursorStack = [];
    const limit = UI.DEFAULT_PAGE_LIMIT;
    let currentQ = '';
    let currentStatus = '';
    let searchTimeout = null;

    // Header
    const header = document.createElement('div');
    header.className = 'page-header';
    header.innerHTML = '<h2>Conversations</h2><p>Follow active threads, send replies, and jump into work that still needs a decision.</p>';
    container.appendChild(header);

    const actions = document.createElement('div');
    actions.className = 'action-bar';
    const newBtn = document.createElement('button');
    newBtn.className = 'btn btn-primary';
    newBtn.textContent = 'Start a conversation';
    newBtn.addEventListener('click', () => _showNewConversationDialog());
    actions.appendChild(newBtn);

    const approvalLink = document.createElement('a');
    approvalLink.href = '/ui/approvals';
    approvalLink.className = 'btn';
    approvalLink.textContent = 'Review approvals';
    actions.appendChild(approvalLink);
    container.appendChild(actions);

    // Filter bar
    const filterBar = document.createElement('div');
    filterBar.className = 'filter-bar';

    const searchInput = document.createElement('input');
    searchInput.className = 'search-input';
    searchInput.placeholder = 'Search conversations';
    searchInput.type = 'text';
    searchInput.setAttribute('aria-label', 'Search conversations');
    searchInput.setAttribute('title', 'Press / to focus search');
    filterBar.appendChild(searchInput);

    const searchHint = document.createElement('span');
    searchHint.className = 'search-shortcut-hint';
    searchHint.textContent = 'Shortcut: /';
    filterBar.appendChild(searchHint);

    const statusSelect = document.createElement('select');
    statusSelect.setAttribute('aria-label', 'Filter conversations by status');
    statusSelect.innerHTML =
        '<option value="">All statuses</option>' +
        '<option value="open">Open</option>' +
        '<option value="running">Running</option>' +
        '<option value="completed">Completed</option>' +
        '<option value="failed">Failed</option>';
    filterBar.appendChild(statusSelect);

    container.appendChild(filterBar);

    const listEl = document.createElement('div');
    listEl.className = 'list-container';
    container.appendChild(listEl);

    const pagEl = document.createElement('div');
    container.appendChild(pagEl);

    // Debounced search
    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            const q = searchInput.value.trim();
            currentQ = q.length >= 3 ? q : '';
            cursor = 0;
            cursorStack = [];
            loadPage();
        }, 300);
    });

    statusSelect.addEventListener('change', () => {
        currentStatus = statusSelect.value;
        cursor = 0;
        cursorStack = [];
        loadPage();
    });

    function loadPage() {
        listEl.textContent = '';
        UI.renderSkeletons(listEl, 5, 'row');
        pagEl.textContent = '';

        const params = { cursor, limit };
        if (currentQ) params.q = currentQ;
        if (currentStatus) params.status = currentStatus;

        API.listConversations(params).then(data => {
            const convos = data.conversations || data || [];
            listEl.textContent = '';

            if (convos.length === 0) {
                listEl.appendChild(UI.renderEmptyState('No conversations found'));
                pagEl.textContent = '';
                return;
            }

            convos.forEach(c => {
                const sub = document.createElement('span');
                const prefixParts = [];
                if (c.target_display_name || c.target_agent_id) {
                    prefixParts.push(c.target_display_name || c.target_agent_id);
                }
                if (c.origin_channel) prefixParts.push(c.origin_channel);
                if (prefixParts.length > 0) {
                    sub.appendChild(document.createTextNode(prefixParts.join(' \u00b7 ') + ' \u00b7 '));
                }
                const timeSpan = document.createElement('span');
                timeSpan.setAttribute('data-timestamp', c.updated_at || c.created_at || '');
                timeSpan.textContent = UI.relativeTime(c.updated_at || c.created_at);
                sub.appendChild(timeSpan);
                if (c.event_count !== undefined) {
                    sub.appendChild(document.createTextNode(' \u00b7 ' + c.event_count + ' events'));
                }
                listEl.appendChild(UI.renderListRow({
                    href: '/ui/conversations/' + c.conversation_id,
                    label: c.title || c.conversation_id,
                    sublabelNode: sub,
                    badgeText: c.status || 'open',
                    badgeClass: 'badge-' + (c.status || 'open'),
                }));
            });

            pagEl.textContent = '';
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

    // WS: reload on any new event (new conversations, status changes)
    let reloadDebounce = null;
    const unsub = WS.subscribe('*', (msg) => {
        if (msg.type === 'event' || msg.type === 'heartbeat') {
            clearTimeout(reloadDebounce);
            reloadDebounce = setTimeout(loadPage, 2000);
        }
    });
    cleanups.add(unsub);

    function _showNewConversationDialog() {
        const overlay = document.createElement('div');
        overlay.className = 'confirm-overlay';

        const dialog = document.createElement('div');
        dialog.className = 'confirm-dialog';
        dialog.setAttribute('role', 'dialog');
        dialog.setAttribute('aria-modal', 'true');

        const h3 = document.createElement('h3');
        h3.id = 'new-conversation-title';
        h3.textContent = 'New Conversation';
        dialog.setAttribute('aria-labelledby', h3.id);
        dialog.appendChild(h3);

        const agentLabel = document.createElement('label');
        agentLabel.htmlFor = 'new-conversation-agent';
        agentLabel.textContent = 'Target Agent';
        agentLabel.style.display = 'block';
        agentLabel.style.marginBottom = '4px';
        agentLabel.style.fontSize = '12px';
        agentLabel.style.color = 'var(--text-secondary)';
        dialog.appendChild(agentLabel);

        const agentSelect = document.createElement('select');
        agentSelect.id = 'new-conversation-agent';
        agentSelect.setAttribute('aria-label', 'Target agent');
        agentSelect.style.width = '100%';
        agentSelect.style.marginBottom = '12px';
        agentSelect.style.padding = '8px';
        agentSelect.innerHTML = '<option value="">Loading agents...</option>';
        dialog.appendChild(agentSelect);

        // Load agents
        API.listAgents().then(data => {
            const agents = data.agents || data || [];
            agentSelect.innerHTML = '';
            if (agents.length === 0) {
                agentSelect.innerHTML = '<option value="">No agents available</option>';
                return;
            }
            agents.forEach(a => {
                const opt = document.createElement('option');
                opt.value = a.agent_id;
                opt.textContent = a.display_name || a.slug || a.agent_id;
                agentSelect.appendChild(opt);
            });
        }).catch((err) => {
            agentSelect.innerHTML = '<option value="">Failed to load agents</option>';
            UI.reportError('Failed to load agents for a new conversation', err, { context: 'Load conversation agents failed' });
        });

        const actions = document.createElement('div');
        actions.className = 'confirm-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn';
        cancelBtn.type = 'button';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', () => overlay.remove());

        const createBtn = document.createElement('button');
        createBtn.className = 'btn btn-primary';
        createBtn.type = 'button';
        createBtn.textContent = 'Create';
        createBtn.addEventListener('click', async () => {
            const agentId = agentSelect.value;
            if (!agentId) return;
            createBtn.disabled = true;
            createBtn.textContent = 'Creating...';
            try {
                const result = await API.createConversation(agentId);
                overlay.remove();
                Router.navigate('/ui/conversations/' + result.conversation_id);
            } catch (err) {
                createBtn.disabled = false;
                createBtn.textContent = 'Create';
                UI.reportError('Failed to start the conversation', err, { context: 'Create conversation failed' });
            }
        });

        actions.appendChild(cancelBtn);
        actions.appendChild(createBtn);
        dialog.appendChild(actions);
        overlay.appendChild(dialog);
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) overlay.remove();
        });
        document.body.appendChild(overlay);
        requestAnimationFrame(() => agentSelect.focus());
    }

    cleanups.add(() => clearTimeout(searchTimeout));
    cleanups.add(() => clearTimeout(reloadDebounce));
}
