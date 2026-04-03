/**
 * Approvals — compact decision queue.
 */
function renderApprovalList(container) {
    const cleanups = UI.beginCleanupScope();
    const limit = UI.DEFAULT_PAGE_LIMIT;
    let hasLoaded = false;
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }

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
    listEl.className = 'list-container';
    shell.appendChild(listEl);

    const pagEl = document.createElement('div');
    pagEl.className = 'pagination-shell';
    shell.appendChild(pagEl);
    const paginator = UI.createCursorPaginator(pagEl, () => loadPage());

    function renderRows(data) {
        const approvals = data.approvals || data || [];
        if (!approvals.length) {
            UI.clearMemoizedRender(listEl);
            UI.reconcileChildren(listEl, [UI.renderEmptyState('No approvals waiting.', true)]);
            paginator.clear();
            return;
        }

        UI.memoizedRender(listEl, {
            cursor: paginator.cursor,
            approvals,
        }, (state) => {
            const cards = state.approvals.map((item) => {
                const card = document.createElement('article');
                card.className = 'approval-card';
                card.dataset.key = item.request_id || item.approval_id || item.conversation_id;
                card.dataset.signature = UI.dataSignature({
                    id: String(item.request_id || item.approval_id || item.conversation_id || ''),
                    title: String(item.conversation_title || ''),
                    target: String(item.target_display_name || item.target_agent_id || ''),
                    requestKind: String(item.request_kind || ''),
                    recoveryId: String(item.recovery_id || ''),
                    actor: String(item.actor || ''),
                    trust: String(item.trust_tier || ''),
                    createdLabel: item.created_at ? UI.relativeTime(item.created_at) : '',
                    expiresLabel: item.expires_at ? UI.formatApprovalTime(item.expires_at) : '',
                    content: String(item.content || ''),
                });

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

            const rejectBtn = document.createElement('button');
            rejectBtn.className = 'btn btn-sm btn-danger';
            rejectBtn.type = 'button';

            let primaryAction = 'approve_pending';
            let secondaryAction = 'reject_pending';
            let actionPayload = () => ({ request_id: item.request_id });
            const requestKind = String(item.request_kind || '').trim();
            if (requestKind === 'retry') {
                approveBtn.textContent = 'Retry';
                rejectBtn.textContent = 'Skip';
                primaryAction = 'retry_allow';
                secondaryAction = 'retry_skip';
            } else if (requestKind === 'recovery') {
                approveBtn.textContent = 'Replay';
                rejectBtn.textContent = 'Discard';
                primaryAction = 'recovery_replay';
                secondaryAction = 'recovery_discard';
                actionPayload = () => ({ recovery_id: String(item.recovery_id || '').trim() });
            } else {
                approveBtn.textContent = 'Approve';
                rejectBtn.textContent = 'Reject';
            }
            approveBtn.setAttribute('aria-label', `${approveBtn.textContent} request for ${item.conversation_title || item.conversation_id}`);
            rejectBtn.setAttribute('aria-label', `${rejectBtn.textContent} request for ${item.conversation_title || item.conversation_id}`);

            const expired = item.expires_at ? new Date(item.expires_at) < new Date() : false;
            approveBtn.disabled = requestKind === 'recovery' ? !String(item.recovery_id || '').trim() : expired;
            rejectBtn.disabled = requestKind === 'recovery' ? !String(item.recovery_id || '').trim() : expired;

            async function act(action) {
                approveBtn.disabled = true;
                rejectBtn.disabled = true;
                try {
                    await API.conversationAction(item.conversation_id, action, actionPayload());
                    loadPage();
                } catch (err) {
                    UI.reportError('Failed to update the approval', err, { context: 'Approval list action failed' });
                    approveBtn.disabled = requestKind === 'recovery' ? !String(item.recovery_id || '').trim() : expired;
                    rejectBtn.disabled = requestKind === 'recovery' ? !String(item.recovery_id || '').trim() : expired;
                }
            }

            approveBtn.addEventListener('click', () => act(primaryAction));
            rejectBtn.addEventListener('click', () => act(secondaryAction));
            actions.appendChild(approveBtn);
            actions.appendChild(rejectBtn);
            card.appendChild(actions);
                return card;
            });
            const grid = document.createElement('div');
            grid.className = 'approval-list';
            grid.dataset.key = 'approval-list';
            UI.reconcileChildren(grid, cards);
            return [grid];
        }, {
            signatureFn(state) {
                return {
                    cursor: state.cursor,
                    approvals: (state.approvals || []).map((item) => ({
                        id: String(item.request_id || item.approval_id || item.conversation_id || ''),
                        title: String(item.conversation_title || ''),
                        target: String(item.target_display_name || item.target_agent_id || ''),
                        requestKind: String(item.request_kind || ''),
                        recoveryId: String(item.recovery_id || '').trim(),
                        actor: String(item.actor || ''),
                        trust: String(item.trust_tier || ''),
                        createdLabel: item.created_at ? UI.relativeTime(item.created_at) : '',
                        expiresLabel: item.expires_at ? UI.formatApprovalTime(item.expires_at) : '',
                        content: String(item.content || ''),
                    })),
                };
            },
        });
        paginator.render({ hasMore: !!data.has_more, nextCursor: data.next_cursor });
        hasLoaded = true;
    }

    async function loadPage({ soft = false } = {}) {
        try {
            const data = await API.listApprovals({ cursor: paginator.cursor, limit });
            renderRows(data);
        } catch (err) {
            if (soft && hasLoaded) {
                UI.reportError('Failed to refresh approvals', err, { context: 'Approval list soft refresh failed' });
                return;
            }
            UI.clearMemoizedRender(listEl);
            UI.reconcileChildren(listEl, [UI.createErrorCard('Failed to load approvals: ' + err.message, loadPage)]);
            paginator.clear();
        }
    }

    container.__routeReady = loadPage();
    UI.subscribeWithRefresh(cleanups, 'approvals', () => loadPage({ soft: true }), 350);
}
