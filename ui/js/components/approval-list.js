/**
 * Approvals — pending conversation approvals that still need operator action.
 */
function renderApprovalList(container) {
    const cleanups = UI.beginCleanupScope();
    let cursor = 0;
    let cursorStack = [];
    const limit = UI.DEFAULT_PAGE_LIMIT;

    const header = document.createElement('div');
    header.className = 'page-header';
    header.innerHTML = '<h2>Approvals</h2><p>Review requests that need a decision before work can continue.</p>';
    container.appendChild(header);

    const listEl = document.createElement('div');
    listEl.className = 'approval-list';
    container.appendChild(listEl);

    const pagEl = document.createElement('div');
    container.appendChild(pagEl);

    function setLoading() {
        listEl.textContent = '';
        UI.renderSkeletons(listEl, 4, 'card');
        pagEl.textContent = '';
    }

    function renderRows(data) {
        const approvals = data.approvals || data || [];
        listEl.textContent = '';
        pagEl.textContent = '';

        if (!approvals.length) {
            listEl.appendChild(UI.renderEmptyState('No approvals waiting right now'));
            return;
        }

        approvals.forEach((item) => {
            const card = document.createElement('article');
            card.className = 'card approval-card';

            const headerRow = document.createElement('div');
            headerRow.className = 'approval-card-header';

            const titleWrap = document.createElement('div');
            const title = document.createElement('div');
            title.className = 'card-title';
            title.textContent = item.conversation_title || item.conversation_id;
            titleWrap.appendChild(title);

            const subtitle = document.createElement('div');
            subtitle.className = 'card-subtitle';
            const subtitleParts = [];
            if (item.target_display_name || item.target_agent_id) {
                subtitleParts.push(item.target_display_name || item.target_agent_id);
            }
            if (item.request_kind) subtitleParts.push(item.request_kind);
            if (item.created_at) subtitleParts.push(UI.relativeTime(item.created_at));
            subtitle.textContent = subtitleParts.join(' · ');
            titleWrap.appendChild(subtitle);
            headerRow.appendChild(titleWrap);

            const badge = document.createElement('span');
            badge.className = 'badge badge-queued';
            badge.textContent = 'Needs review';
            headerRow.appendChild(badge);
            card.appendChild(headerRow);

            const summary = document.createElement('div');
            summary.className = 'approval-summary';
            summary.textContent = item.content || 'Approval required before the agent can continue.';
            card.appendChild(summary);

            const facts = document.createElement('div');
            facts.className = 'approval-facts';
            [
                ['Requested by', item.actor || 'agent'],
                ['Trust tier', item.trust_tier || '—'],
                ['Expires', item.expires_at ? UI.formatApprovalTime(item.expires_at) : 'No deadline'],
            ].forEach(([label, value]) => {
                const fact = document.createElement('div');
                fact.className = 'approval-fact';
                fact.innerHTML = `<span>${UI.esc(label)}</span><strong>${UI.esc(value)}</strong>`;
                facts.appendChild(fact);
            });
            card.appendChild(facts);

            const actions = document.createElement('div');
            actions.className = 'approval-actions';

            const openBtn = document.createElement('button');
            openBtn.className = 'btn';
            openBtn.type = 'button';
            openBtn.textContent = 'Open conversation';
            openBtn.setAttribute('aria-label', `Open conversation ${item.conversation_title || item.conversation_id}`);
            openBtn.addEventListener('click', () => {
                Router.navigate('/ui/conversations/' + item.conversation_id);
            });
            actions.appendChild(openBtn);

            const approveBtn = document.createElement('button');
            approveBtn.className = 'btn btn-primary';
            approveBtn.type = 'button';
            approveBtn.textContent = 'Approve';
            approveBtn.setAttribute('aria-label', `Approve request for ${item.conversation_title || item.conversation_id}`);

            const rejectBtn = document.createElement('button');
            rejectBtn.className = 'btn btn-danger';
            rejectBtn.type = 'button';
            rejectBtn.textContent = 'Reject';
            rejectBtn.setAttribute('aria-label', `Reject request for ${item.conversation_title || item.conversation_id}`);

            const expired = item.expires_at ? new Date(item.expires_at) < new Date() : false;
            approveBtn.disabled = expired;
            rejectBtn.disabled = expired;

            async function act(action) {
                approveBtn.disabled = true;
                rejectBtn.disabled = true;
                try {
                    await API.conversationAction(item.conversation_id, action, { request_id: item.request_id });
                    loadPage();
                } catch (err) {
                    UI.reportError('Failed to update the approval', err, { context: 'Approval list action failed' });
                    approveBtn.disabled = expired;
                    rejectBtn.disabled = expired;
                }
            }

            approveBtn.addEventListener('click', () => act('approve'));
            rejectBtn.addEventListener('click', () => act('reject'));
            actions.appendChild(approveBtn);
            actions.appendChild(rejectBtn);
            card.appendChild(actions);

            listEl.appendChild(card);
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
    }

    function loadPage() {
        setLoading();
        API.listApprovals({ cursor, limit }).then(renderRows).catch((err) => {
            listEl.textContent = '';
            UI.renderError(listEl, 'Failed to load approvals: ' + err.message, loadPage);
        });
    }

    let reloadDebounce = null;
    const unsub = WS.subscribe('*', (msg) => {
        if (msg.type === 'event') {
            clearTimeout(reloadDebounce);
            reloadDebounce = setTimeout(loadPage, 1500);
        }
    });
    cleanups.add(unsub);

    loadPage();
    cleanups.add(() => clearTimeout(reloadDebounce));
}
