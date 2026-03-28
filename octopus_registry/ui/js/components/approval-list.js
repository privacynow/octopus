/**
 * Approvals — compact decision queue.
 */
async function renderApprovalList(container) {
    const cleanups = UI.beginCleanupScope();
    let cursor = 0;
    let cursorStack = [];
    const limit = UI.DEFAULT_PAGE_LIMIT;
    let hasLoaded = false;

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Approvals</h2>';
    container.appendChild(header);

    const shellWrap = document.createElement('section');
    shellWrap.className = 'admin-shell';
    container.appendChild(shellWrap);

    const shell = document.createElement('section');
    shell.className = 'list-shell';
    shellWrap.appendChild(shell);

    const listEl = document.createElement('div');
    listEl.className = 'approval-list';
    shell.appendChild(listEl);

    const pagEl = document.createElement('div');
    pagEl.className = 'pagination-shell';
    shell.appendChild(pagEl);

    function setLoading() {
        UI.reconcileChildren(listEl, UI.createSkeletonNodes(4, 'card'));
        UI.reconcileChildren(pagEl, []);
    }

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

    function renderRows(data) {
        const approvals = data.approvals || data || [];
        if (!approvals.length) {
            UI.reconcileChildren(listEl, [UI.renderEmptyState('No approvals waiting.', true)]);
            UI.reconcileChildren(pagEl, []);
            return;
        }

        const cards = approvals.map((item) => {
            const card = document.createElement('article');
            card.className = 'approval-card';
            card.dataset.key = item.request_id || item.approval_id || item.conversation_id;

            const headerRow = document.createElement('div');
            headerRow.className = 'approval-card-header';

            const titleWrap = document.createElement('div');
            titleWrap.className = 'approval-card-copy';

            const title = document.createElement('strong');
            title.className = 'approval-card-title';
            title.textContent = item.conversation_title || UI.visibleLabel(item.target_display_name, item.target_agent_id) || 'Conversation awaiting review';
            titleWrap.appendChild(title);

            const subtitle = document.createElement('span');
            subtitle.className = 'approval-card-subtitle';
            subtitle.textContent = [
                item.target_display_name || item.target_agent_id || 'agent',
                item.request_kind || 'approval request',
                item.created_at ? UI.relativeTime(item.created_at) : '',
            ].filter(Boolean).join(' · ');
            titleWrap.appendChild(subtitle);
            headerRow.appendChild(titleWrap);

            const badge = document.createElement('span');
            badge.className = 'badge badge-queued';
            badge.textContent = 'Needs review';
            headerRow.appendChild(badge);
            card.appendChild(headerRow);

            const summary = document.createElement('p');
            summary.className = 'approval-summary';
            summary.textContent = item.content || 'Approval required before work can continue.';
            card.appendChild(summary);

            const facts = document.createElement('div');
            facts.className = 'approval-facts';
            [
                ['Requested by', item.actor || 'agent'],
                ['Trust', item.trust_tier || '—'],
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
            openBtn.className = 'btn btn-sm';
            openBtn.type = 'button';
            openBtn.textContent = 'Open';
            openBtn.setAttribute('aria-label', `Open conversation ${item.conversation_title || item.conversation_id}`);
            openBtn.addEventListener('click', () => {
                Router.navigate('/ui/conversations/' + item.conversation_id);
            });
            actions.appendChild(openBtn);

            const approveBtn = document.createElement('button');
            approveBtn.className = 'btn btn-sm btn-primary';
            approveBtn.type = 'button';
            approveBtn.textContent = 'Approve';
            approveBtn.setAttribute('aria-label', `Approve request for ${item.conversation_title || item.conversation_id}`);

            const rejectBtn = document.createElement('button');
            rejectBtn.className = 'btn btn-sm btn-danger';
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
            return card;
        });

        UI.reconcileChildren(listEl, cards);
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
    }

    async function loadPage({ soft = false } = {}) {
        if (!soft || !hasLoaded) setLoading();
        try {
            const data = await API.listApprovals({ cursor, limit });
            renderRows(data);
        } catch (err) {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh approvals', err, { context: 'Approval list soft refresh failed' });
                return;
            }
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load approvals: ' + err.message, loadPage)]);
            UI.reconcileChildren(pagEl, []);
        }
    }

    let reloadDebounce = null;
    cleanups.add(WS.subscribe('approvals', () => {
        clearTimeout(reloadDebounce);
        reloadDebounce = setTimeout(() => loadPage({ soft: true }), 350);
    }));

    await loadPage();
    cleanups.add(() => clearTimeout(reloadDebounce));
}
