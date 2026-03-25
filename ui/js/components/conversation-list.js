/**
 * Conversation list — all conversations with search/filter and pagination.
 */
function renderConversationList(container) {
    const cleanups = UI.beginCleanupScope();
    let cursor = 0;
    let cursorStack = [];
    const limit = UI.DEFAULT_PAGE_LIMIT;
    let currentQ = UI.readQueryParam('q', '');
    let currentStatus = UI.readQueryParam('status', '');
    let searchTimeout = null;
    let hasLoaded = false;
    let quickStartLoaded = false;
    let openingConversationFor = '';

    // Header
    const header = document.createElement('div');
    header.className = 'page-header';
    header.innerHTML = '<h2>Conversations</h2><p>Follow active threads, send replies, and jump into work that still needs a decision.</p>';
    container.appendChild(header);

    const quickStart = document.createElement('section');
    quickStart.className = 'card conversation-launcher-panel';
    container.appendChild(quickStart);

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
            currentQ = q;
            cursor = 0;
            cursorStack = [];
            UI.updateQueryParams({ q: currentQ, status: currentStatus });
            loadPage();
        }, 300);
    });

    statusSelect.addEventListener('change', () => {
        currentStatus = statusSelect.value;
        cursor = 0;
        cursorStack = [];
        UI.updateQueryParams({ q: currentQ, status: currentStatus });
        loadPage();
    });
    searchInput.value = currentQ;
    statusSelect.value = currentStatus;

    function renderPaginationState({ hasPrev, hasNext, onPrev, onNext }) {
        const wrapper = document.createElement('div');
        UI.renderPagination(wrapper, {
            hasPrev,
            hasNext,
            info: '',
            onPrev,
            onNext,
        });
        UI.reconcileChildren(pagEl, Array.from(wrapper.childNodes));
    }

    function renderQuickStart(agents) {
        const shell = document.createElement('div');
        shell.className = 'conversation-launcher';
        shell.dataset.key = 'launcher-shell';

        const head = document.createElement('div');
        head.className = 'conversation-launcher-head';
        head.innerHTML = '<div><strong>Start or reopen with</strong><span>Jump straight into a conversation with a connected agent.</span></div>';
        const links = document.createElement('div');
        links.className = 'conversation-launcher-links';

        const allAgents = document.createElement('a');
        allAgents.href = '/ui/agents';
        allAgents.className = 'section-link';
        allAgents.textContent = 'All agents';
        links.appendChild(allAgents);

        const approvals = document.createElement('a');
        approvals.href = '/ui/approvals';
        approvals.className = 'section-link';
        approvals.textContent = 'Review approvals';
        links.appendChild(approvals);

        head.appendChild(links);
        shell.appendChild(head);

        const launcherList = document.createElement('div');
        launcherList.className = 'conversation-launcher-list';
        launcherList.dataset.key = 'launcher-list';

        if (!agents.length) {
            launcherList.appendChild(UI.renderEmptyState('No connected agents are ready right now.', true));
        } else {
            agents.forEach((agent) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'conversation-launcher-button';
                button.dataset.key = agent.agent_id;
                button.setAttribute('aria-label', `Open or start a conversation with ${agent.display_name || agent.slug || agent.agent_id}`);

                const title = document.createElement('strong');
                title.textContent = agent.display_name || agent.slug || agent.agent_id;
                button.appendChild(title);

                const subtitle = document.createElement('span');
                subtitle.textContent = [
                    agent.role || 'agent',
                    agent.provider || '',
                    agent.slug || '',
                ].filter(Boolean).join(' · ');
                button.appendChild(subtitle);

                button.addEventListener('click', async () => {
                    if (openingConversationFor === agent.agent_id) return;
                    openingConversationFor = agent.agent_id;
                    button.disabled = true;
                    button.classList.add('busy');
                    try {
                        const conversation = await API.openConversationForAgent(agent.agent_id, {
                            title: `Conversation with ${agent.display_name || agent.slug || agent.agent_id}`,
                        });
                        Router.navigate('/ui/conversations/' + conversation.conversation_id);
                    } catch (err) {
                        openingConversationFor = '';
                        button.disabled = false;
                        button.classList.remove('busy');
                        UI.reportError('Failed to open a conversation for this agent', err, { context: 'Conversation list quick start failed' });
                    }
                });

                launcherList.appendChild(button);
            });
        }

        shell.appendChild(launcherList);
        UI.reconcileChildren(quickStart, [shell]);
    }

    function loadQuickStart({ soft = false } = {}) {
        if (!soft || !quickStartLoaded) {
            UI.reconcileChildren(quickStart, UI.createSkeletonNodes(1, 'card'));
        }
        API.listAgents({ state: 'connected', limit: 8 }).then((data) => {
            renderQuickStart(data.agents || data || []);
            quickStartLoaded = true;
        }).catch((err) => {
            if (soft && quickStartLoaded) {
                UI.reportError('Failed to refresh connected agents', err, { context: 'Conversation quick start soft refresh failed' });
                return;
            }
            UI.reconcileChildren(quickStart, [UI.createErrorCard('Failed to load connected agents: ' + err.message, loadQuickStart)]);
        });
    }

    function loadPage({ soft = false } = {}) {
        if (!soft || !hasLoaded) {
            UI.reconcileChildren(listEl, UI.createSkeletonNodes(5, 'row'));
            UI.reconcileChildren(pagEl, []);
        }

        const params = { cursor, limit };
        if (currentQ) params.q = currentQ;
        if (currentStatus) params.status = currentStatus;

        API.listConversations(params).then(data => {
            const convos = data.conversations || data || [];

            if (convos.length === 0) {
                UI.reconcileChildren(listEl, [UI.renderEmptyState('No conversations found')]);
                UI.reconcileChildren(pagEl, []);
                return;
            }

            const rows = convos.map(c => {
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

            renderPaginationState({
                hasPrev: cursorStack.length > 0,
                hasNext: !!data.has_more,
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
            hasLoaded = true;
        }).catch(err => {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh conversations', err, { context: 'Conversation list soft refresh failed' });
                return;
            }
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed: ' + err.message, loadPage)]);
            UI.reconcileChildren(pagEl, []);
        });
    }

    loadQuickStart();
    loadPage();

    let reloadDebounce = null;
    cleanups.add(WS.subscribe('conversations', () => {
        clearTimeout(reloadDebounce);
        reloadDebounce = setTimeout(() => loadPage({ soft: true }), 400);
    }));
    cleanups.add(WS.subscribe('agents', () => {
        clearTimeout(reloadDebounce);
        reloadDebounce = setTimeout(() => loadQuickStart({ soft: true }), 400);
    }));

    cleanups.add(() => clearTimeout(searchTimeout));
    cleanups.add(() => clearTimeout(reloadDebounce));
}
