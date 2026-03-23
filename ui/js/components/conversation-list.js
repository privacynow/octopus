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

    return function cleanup() {
        clearTimeout(searchTimeout);
        clearTimeout(reloadDebounce);
        cleanups.forEach(fn => fn());
    };
}
