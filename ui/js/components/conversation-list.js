/**
 * Conversation list — all conversations with search/filter and pagination.
 */
function renderConversationList(container) {
    let cursor = 0;
    let cursorStack = [];
    const limit = 25;
    let currentQ = '';
    let currentStatus = '';
    let searchTimeout = null;
    const cleanups = [];

    // Header
    const header = document.createElement('div');
    header.className = 'page-header';
    header.innerHTML = '<h2>Conversations</h2><p>All conversations across agents</p>';
    container.appendChild(header);

    // New conversation button
    const newBtn = document.createElement('button');
    newBtn.className = 'btn btn-primary btn-sm';
    newBtn.textContent = '+ New Conversation';
    newBtn.style.marginBottom = '12px';
    newBtn.addEventListener('click', () => _showNewConversationDialog());
    container.appendChild(newBtn);

    // Filter bar
    const filterBar = document.createElement('div');
    filterBar.className = 'filter-bar';

    const searchInput = document.createElement('input');
    searchInput.className = 'search-input';
    searchInput.placeholder = 'Search conversations (3+ chars)...';
    searchInput.type = 'text';
    filterBar.appendChild(searchInput);

    const statusSelect = document.createElement('select');
    statusSelect.innerHTML =
        '<option value="">All statuses</option>' +
        '<option value="open">Open</option>' +
        '<option value="running">Running</option>' +
        '<option value="completed">Completed</option>' +
        '<option value="failed">Failed</option>';
    filterBar.appendChild(statusSelect);

    container.appendChild(filterBar);

    const listEl = document.createElement('div');
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
        _renderSkeletons(listEl, 5, 'card');
        pagEl.textContent = '';

        const params = { cursor, limit };
        if (currentQ) params.q = currentQ;
        if (currentStatus) params.status = currentStatus;

        API.listConversations(params).then(data => {
            const convos = data.conversations || data || [];
            listEl.textContent = '';

            if (convos.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'empty-state';
                empty.textContent = 'No conversations found';
                listEl.appendChild(empty);
                pagEl.textContent = '';
                return;
            }

            convos.forEach(c => {
                const card = document.createElement('div');
                card.className = 'card clickable';
                card.addEventListener('click', () => Router.navigate('/ui/conversations/' + c.conversation_id));

                const row = document.createElement('div');
                row.className = 'card-row';

                const info = document.createElement('div');
                const title = document.createElement('div');
                title.className = 'card-title';
                title.textContent = c.title || c.conversation_id;
                info.appendChild(title);

                const sub = document.createElement('div');
                sub.className = 'card-subtitle';
                const prefixParts = [];
                if (c.target_display_name || c.target_agent_id) {
                    prefixParts.push(c.target_display_name || c.target_agent_id);
                }
                if (c.origin_channel) prefixParts.push(c.origin_channel);
                if (prefixParts.length > 0) {
                    sub.textContent = prefixParts.join(' \u00b7 ') + ' \u00b7 ';
                }
                const timeSpan = document.createElement('span');
                timeSpan.setAttribute('data-timestamp', c.updated_at || c.created_at || '');
                timeSpan.textContent = _relativeTime(c.updated_at || c.created_at);
                sub.appendChild(timeSpan);
                if (c.event_count !== undefined) {
                    const evtSpan = document.createTextNode(' \u00b7 ' + c.event_count + ' events');
                    sub.appendChild(evtSpan);
                }
                info.appendChild(sub);

                row.appendChild(info);

                const badge = document.createElement('span');
                badge.className = 'badge badge-' + (c.status || 'open');
                badge.textContent = c.status || 'open';
                row.appendChild(badge);

                card.appendChild(row);
                listEl.appendChild(card);
            });

            pagEl.textContent = '';
            _renderPagination(pagEl, {
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
            _renderError(listEl, 'Failed: ' + err.message, loadPage);
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
    cleanups.push(unsub);

    function _showNewConversationDialog() {
        const overlay = document.createElement('div');
        overlay.className = 'confirm-overlay';

        const dialog = document.createElement('div');
        dialog.className = 'confirm-dialog';

        const h3 = document.createElement('h3');
        h3.textContent = 'New Conversation';
        dialog.appendChild(h3);

        const agentLabel = document.createElement('label');
        agentLabel.textContent = 'Target Agent';
        agentLabel.style.display = 'block';
        agentLabel.style.marginBottom = '4px';
        agentLabel.style.fontSize = '12px';
        agentLabel.style.color = 'var(--text-secondary)';
        dialog.appendChild(agentLabel);

        const agentSelect = document.createElement('select');
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
        });

        const actions = document.createElement('div');
        actions.className = 'confirm-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', () => overlay.remove());

        const createBtn = document.createElement('button');
        createBtn.className = 'btn btn-primary';
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
                console.error('Create conversation failed', err);
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
    }

    return function cleanup() {
        clearTimeout(searchTimeout);
        clearTimeout(reloadDebounce);
        cleanups.forEach(fn => fn());
    };
}
