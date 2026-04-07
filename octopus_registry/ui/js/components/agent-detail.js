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
    let resetBusy = false;
    let executionOverride = null;
    let resetNotice = '';

    const header = document.createElement('header');
    header.className = 'workspace-header workspace-header-compact';
    container.appendChild(header);

    const content = document.createElement('div');
    content.className = 'agent-detail-grid';
    container.appendChild(content);

    function executionSnapshot(agent) {
        if (executionOverride) {
            return executionOverride;
        }
        return {
            state: String((agent && agent.execution_state) || 'healthy').trim() || 'healthy',
            provider: String((agent && agent.execution_provider) || (agent && agent.provider) || '').trim(),
            faultKind: String((agent && agent.execution_fault_kind) || '').trim(),
            faultCode: String((agent && agent.execution_fault_code) || '').trim(),
            detail: String((agent && agent.execution_fault_detail) || '').trim(),
            faultedAt: String((agent && agent.execution_faulted_at) || '').trim(),
            resettable: Boolean(agent && agent.execution_resettable),
        };
    }

    function executionBadge(snapshot) {
        const badge = document.createElement('span');
        const faulted = snapshot.state === 'faulted';
        badge.className = `badge badge-${faulted ? 'faulted' : 'healthy'}`;
        badge.textContent = faulted ? 'execution faulted' : 'execution ready';
        if (faulted && snapshot.detail) {
            badge.title = snapshot.detail;
        }
        return badge;
    }

    function buildHeader(agent) {
        const execution = executionSnapshot(agent);
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
        const transportStatus = document.createElement('span');
        transportStatus.className = `badge badge-${agent.connectivity_state || 'stopped'}`;
        transportStatus.textContent = `transport ${agent.connectivity_state || 'unknown'}`;
        actions.appendChild(transportStatus);
        actions.appendChild(executionBadge(execution));

        const openConversationBtn = document.createElement('button');
        openConversationBtn.type = 'button';
        openConversationBtn.className = 'btn btn-sm btn-primary';
        openConversationBtn.textContent = execution.state === 'faulted' ? 'Execution faulted' : 'Open conversation';
        openConversationBtn.disabled = openConversationBusy || execution.state === 'faulted';
        if (execution.state === 'faulted' && execution.detail) {
            openConversationBtn.title = execution.detail;
        }
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

        if (execution.state === 'faulted' && execution.resettable) {
            const resetBtn = document.createElement('button');
            resetBtn.type = 'button';
            resetBtn.className = 'btn btn-sm';
            resetBtn.textContent = resetBusy ? 'Resetting…' : 'Reset execution';
            resetBtn.disabled = resetBusy;
            resetBtn.addEventListener('click', async () => {
                if (resetBusy) return;
                resetBusy = true;
                resetBtn.disabled = true;
                resetBtn.textContent = 'Resetting…';
                try {
                    const result = await API.resetAgentExecutionFault(agentId, {});
                    const state = (result && result.state) || {};
                    executionOverride = {
                        state: String(state.state || 'healthy'),
                        provider: String(state.provider || agent.provider || ''),
                        faultKind: String(state.fault_kind || ''),
                        faultCode: String(state.fault_code || ''),
                        detail: String(state.detail || ''),
                        faultedAt: String(state.faulted_at || ''),
                        resettable: Boolean(state.resettable),
                        staleFaultedAt: String(execution.faultedAt || ''),
                        staleDetail: String(execution.detail || ''),
                        until: Date.now() + 15000,
                    };
                    resetNotice = 'Execution fault reset. New requests are allowed again.';
                    void loadDetail({ soft: true });
                } catch (err) {
                    UI.reportError('Failed to reset execution fault', err, { context: 'Agent execution fault reset failed' });
                    resetBtn.disabled = false;
                    resetBtn.textContent = 'Reset execution';
                } finally {
                    resetBusy = false;
                }
            });
            actions.appendChild(resetBtn);
        }
        titleRow.appendChild(actions);

        UI.reconcileChildren(header, [titleRow]);
    }

    function buildOverviewCard(agent) {
        const execution = executionSnapshot(agent);
        const card = document.createElement('section');
        card.className = 'card workspace-section';
        card.dataset.key = 'overview';

        const head = document.createElement('div');
        head.className = 'section-header';
        head.innerHTML = '<strong>Overview</strong>';
        card.appendChild(head);

        const body = document.createElement('div');
        body.className = 'list-shell';

        const grid = UI.renderMetadataGrid([
            { label: 'Agent ID', value: agent.agent_id || '—' },
            { label: 'Scope', value: agent.registry_scope || '—' },
            { label: 'Version', value: agent.version || '—' },
            { label: 'Transport', value: agent.connectivity_state || 'unknown' },
            { label: 'Execution', value: execution.state || 'healthy' },
            { label: 'Last heartbeat', value: agent.last_heartbeat_at ? UI.relativeTime(agent.last_heartbeat_at) : 'never' },
            execution.faultedAt ? { label: 'Faulted at', value: UI.relativeTime(execution.faultedAt) } : null,
            execution.detail ? { label: 'Last failure', value: execution.detail } : null,
        ].filter(Boolean));
        body.appendChild(grid);

        if (resetNotice) {
            const note = document.createElement('div');
            note.className = 'agent-execution-note';
            note.textContent = resetNotice;
            body.appendChild(note);
        }

        card.appendChild(body);

        return card;
    }

    function skillsWorkspaceHref(skillName = '', options = {}) {
        const hub = window.RegistrySkillHub;
        if (hub && typeof hub.skillWorkspaceHref === 'function') {
            return hub.skillWorkspaceHref(agentId, skillName, options);
        }
        return `/ui/skills?agent_id=${encodeURIComponent(agentId)}`;
    }

    function openSkillsDrawer(agent) {
        const hub = window.RegistrySkillHub;
        if (!hub) {
            Router.navigate(skillsWorkspaceHref());
            return;
        }

        const shell = document.createElement('div');
        shell.className = 'studio-stack';

        const intro = document.createElement('p');
        intro.className = 'quiet-note';
        intro.textContent = 'Quick actions live here. Open the full Skills page for deep editing, lifecycle review, and package work.';
        shell.appendChild(intro);

        const controls = document.createElement('div');
        controls.className = 'route-controls';
        const search = document.createElement('input');
        search.type = 'text';
        search.className = 'search-input';
        search.placeholder = 'Search installed or store skills';
        controls.appendChild(search);
        shell.appendChild(controls);

        const listShell = document.createElement('div');
        listShell.className = 'list-shell';
        const list = document.createElement('div');
        list.className = 'list-container';
        listShell.appendChild(list);
        shell.appendChild(listShell);

        const openPageBtn = document.createElement('button');
        openPageBtn.type = 'button';
        openPageBtn.className = 'btn';
        openPageBtn.textContent = 'Open Skills page';
        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'btn btn-primary';
        closeBtn.textContent = 'Close';
        const view = UI.showDialog('Manage skills', shell, {
            actions: [openPageBtn, closeBtn],
            maxWidth: '760px',
        });
        view.overlay.classList.add('skills-drawer-overlay');
        view.dialog.classList.add('skills-drawer-dialog');
        closeBtn.addEventListener('click', () => view.close());
        openPageBtn.addEventListener('click', () => {
            view.close();
            Router.navigate(skillsWorkspaceHref());
        });

        let currentQ = '';
        let allSkills = [];
        let storeSkills = [];
        let registryError = '';

        function invalidateSkills() {
            UI.invalidateCachedData([
                hub.listCacheKey(agentId),
                `skills:search:${String(agentId || '').trim()}:`,
                `skills:detail:${String(agentId || '').trim()}:`,
                `skills:lifecycle:${String(agentId || '').trim()}:`,
            ]);
        }

        async function useSkillInConversation(skillName) {
            view.close();
            await hub.openConversationForSkill(agentId, skillName, {
                agentLabel: UI.visibleLabel(agent.display_name, agent.slug, agent.agent_id) || 'this bot',
            });
        }

        function renderDrawer(loading = false) {
            const sections = hub.buildSections(allSkills, storeSkills, currentQ);
            const appendOpenInSkillsButton = (actions, skill, origin) => {
                const openBtn = document.createElement('button');
                openBtn.type = 'button';
                openBtn.className = 'btn btn-sm list-row-action';
                openBtn.textContent = 'Open in Skills';
                openBtn.addEventListener('click', (event) => {
                    event.stopPropagation();
                    view.close();
                    Router.navigate(skillsWorkspaceHref(skill.name || '', {
                        origin,
                        tab: origin === 'local' && hub.isCustomSkill(skill) ? 'write' : '',
                    }));
                });
                actions.appendChild(openBtn);
            };
            UI.memoizedRender(list, {
                loading,
                q: currentQ,
                sections,
                registryError,
            }, (state) => {
                if (state.loading && !state.sections.length) {
                    return [UI.renderEmptyState('Loading skills…', true)];
                }
                if (!state.sections.length) {
                    return [UI.renderEmptyState(
                        state.q.length >= 2
                            ? 'No installed or store skills match this search.'
                            : 'No skills available for this bot.',
                        true,
                    )];
                }
                const nodes = [];
                (state.sections || []).forEach((section) => {
                    const label = document.createElement('div');
                    label.className = 'list-section-label';
                    label.dataset.key = `agent-skills-${section.key}`;
                    label.textContent = section.label;
                    nodes.push(label);
                    section.items.forEach((skill) => {
                        const meta = section.origin === 'store' ? hub.storeRowMeta(skill) : hub.localRowMeta(skill);
                        const shellRow = document.createElement('div');
                        shellRow.className = 'list-row-shell';
                        shellRow.dataset.key = `agent-skill:${section.origin}:${skill.name || ''}`;
                        shellRow.appendChild(UI.renderListRow({
                            label: meta.label,
                            sublabel: meta.sublabel,
                            badgeText: meta.badgeText,
                            onClick: () => {
                                view.close();
                                Router.navigate(skillsWorkspaceHref(skill.name || '', {
                                    origin: section.origin,
                                    tab: section.origin === 'local' && hub.isCustomSkill(skill) ? 'write' : '',
                                }));
                            },
                        }));
                        const actions = document.createElement('div');
                        actions.className = 'list-row-actions';

                        if (section.origin === 'store' && skill.can_import) {
                            const installBtn = document.createElement('button');
                            installBtn.type = 'button';
                            installBtn.className = 'btn btn-sm list-row-action';
                            installBtn.textContent = 'Install';
                            installBtn.addEventListener('click', async (event) => {
                                event.stopPropagation();
                                installBtn.disabled = true;
                                try {
                                    await API.installSkill(agentId, skill.name);
                                    invalidateSkills();
                                    view.close();
                                } catch (err) {
                                    UI.reportError('Failed to install the skill', err, { context: 'Agent drawer skill install failed' });
                                    installBtn.disabled = false;
                                }
                            });
                            actions.appendChild(installBtn);
                        } else if (section.origin === 'local' && hub.isCustomSkill(skill)) {
                            const editBtn = document.createElement('button');
                            editBtn.type = 'button';
                            editBtn.className = 'btn btn-sm list-row-action';
                            editBtn.textContent = 'Edit';
                            editBtn.addEventListener('click', (event) => {
                                event.stopPropagation();
                                view.close();
                                Router.navigate(skillsWorkspaceHref(skill.name || '', { tab: 'write' }));
                            });
                            actions.appendChild(editBtn);
                        }

                        if (section.origin === 'local' && skill.runtime_available) {
                            const useBtn = document.createElement('button');
                            useBtn.type = 'button';
                            useBtn.className = 'btn btn-sm btn-primary list-row-action';
                            useBtn.textContent = 'Open conversation and activate';
                            useBtn.addEventListener('click', async (event) => {
                                event.stopPropagation();
                                useBtn.disabled = true;
                                try {
                                    await useSkillInConversation(skill.name || '');
                                } catch (err) {
                                    UI.reportError('Failed to open a conversation for this skill', err, { context: 'Agent drawer use skill failed' });
                                    useBtn.disabled = false;
                                }
                            });
                            actions.appendChild(useBtn);
                        }

                        if (section.origin === 'store' || (section.origin === 'local' && !hub.isCustomSkill(skill))) {
                            appendOpenInSkillsButton(actions, skill, section.origin);
                        } else if (!actions.childElementCount) {
                            appendOpenInSkillsButton(actions, skill, section.origin);
                        }

                        shellRow.appendChild(actions);
                        nodes.push(shellRow);
                    });
                });
                if (state.registryError && state.q.length >= 2) {
                    nodes.push(UI.renderEmptyState(`Store search unavailable. ${state.registryError}`, true));
                }
                return nodes;
            }, {
                signatureFn(state) {
                    return {
                        loading: Boolean(state.loading),
                        q: String(state.q || ''),
                        sections: (state.sections || []).map((section) => ({
                            key: String(section.key || ''),
                            items: (section.items || []).map((skill) => ({
                                name: String(skill.name || ''),
                                runtime: Boolean(skill.runtime_available),
                                canImport: Boolean(skill.can_import),
                                source: String(skill.source_kind || ''),
                                version: String(skill.version || ''),
                            })),
                        })),
                        registryError: String(state.registryError || ''),
                    };
                },
            });
        }

        async function loadDrawerSkills({ soft = false } = {}) {
            const queryText = String(currentQ || '').trim();
            let hasCached = false;
            const cachedLocal = UI.peekCachedData(hub.listCacheKey(agentId));
            if (cachedLocal) {
                allSkills = Array.isArray(cachedLocal) ? cachedLocal : (cachedLocal.skills || []);
                hasCached = true;
            }
            if (hub.canSearchStore(agent) && queryText.length >= 2) {
                const cachedSearch = UI.peekCachedData(hub.searchCacheKey(agentId, queryText));
                if (cachedSearch) {
                    storeSkills = Array.isArray(cachedSearch.registry) ? cachedSearch.registry : [];
                    registryError = String(cachedSearch.registry_error || '');
                    hasCached = true;
                }
            } else {
                storeSkills = [];
                registryError = '';
            }
            if (hasCached || !soft) {
                renderDrawer(true);
            }
            try {
                const localData = await UI.loadCachedData(
                    hub.listCacheKey(agentId),
                    () => API.listSkills(agentId),
                    { ttlMs: 60000, errorTtlMs: 5000, forceRefresh: hasCached },
                );
                allSkills = Array.isArray(localData) ? localData : (localData.skills || []);
                if (hub.canSearchStore(agent) && queryText.length >= 2) {
                    const searchData = await UI.loadCachedData(
                        hub.searchCacheKey(agentId, queryText),
                        () => API.searchCatalogSkills(agentId, queryText),
                        { ttlMs: 30000, errorTtlMs: 5000, forceRefresh: hasCached },
                    );
                    storeSkills = Array.isArray(searchData.registry) ? searchData.registry : [];
                    registryError = String(searchData.registry_error || '');
                } else {
                    storeSkills = [];
                    registryError = '';
                }
                renderDrawer(false);
            } catch (err) {
                if (hasCached) {
                    UI.reportError('Failed to refresh skills', err, { context: 'Agent drawer skills refresh failed' });
                    renderDrawer(false);
                    return;
                }
                UI.clearMemoizedRender(list);
                UI.reconcileChildren(list, [UI.createErrorCard('Failed to load skills: ' + err.message, loadDrawerSkills)]);
            }
        }

        let searchTimeout = null;
        search.addEventListener('input', () => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                currentQ = String(search.value || '').trim();
                void loadDrawerSkills({ soft: true });
            }, 250);
        });

        void loadDrawerSkills();
    }

    function buildSkillsCard(agent) {
        const hub = window.RegistrySkillHub;
        const manageEnabled = Boolean(hub && (hub.canSearchStore(agent) || hub.canCreateCustom(agent)));
        const card = document.createElement('section');
        card.className = 'card workspace-section';
        card.dataset.key = 'skills';

        const head = document.createElement('div');
        head.className = 'section-header';
        head.innerHTML = '<strong>Skills</strong>';
        card.appendChild(head);

        const body = document.createElement('div');
        body.className = 'list-shell';
        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = manageEnabled
            ? 'Manage this bot’s skills from one workspace, then activate a skill inside a conversation when you want it in context.'
            : 'This bot does not currently advertise registry-backed skill management.';
        body.appendChild(note);

        if ((agent.routing_skills || []).length) {
            const label = document.createElement('div');
            label.className = 'detail-label';
            label.textContent = 'Advertised for routing';
            body.appendChild(label);
            const chips = document.createElement('div');
            chips.className = 'chip-row';
            (agent.routing_skills || []).slice(0, 4).forEach((skillName) => {
                const chip = document.createElement('span');
                chip.className = 'quickstart-chip static';
                chip.textContent = skillName;
                chips.appendChild(chip);
            });
            if ((agent.routing_skills || []).length > 4) {
                const more = document.createElement('span');
                more.className = 'quiet-note';
                more.textContent = `+${(agent.routing_skills || []).length - 4} more`;
                chips.appendChild(more);
            }
            body.appendChild(chips);
        }

        const actions = document.createElement('div');
        actions.className = 'editor-actions';
        const manageBtn = document.createElement('button');
        manageBtn.type = 'button';
        manageBtn.className = 'btn btn-sm btn-primary';
        manageBtn.textContent = 'Manage skills';
        manageBtn.disabled = !manageEnabled;
        manageBtn.addEventListener('click', () => openSkillsDrawer(agent));
        actions.appendChild(manageBtn);
        const openPageBtn = document.createElement('button');
        openPageBtn.type = 'button';
        openPageBtn.className = 'btn btn-sm';
        openPageBtn.textContent = 'Open Skills page';
        openPageBtn.disabled = !manageEnabled;
        openPageBtn.addEventListener('click', () => Router.navigate(skillsWorkspaceHref()));
        actions.appendChild(openPageBtn);
        body.appendChild(actions);

        card.appendChild(body);
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
                item.conversation_type === 'task_thread' ? 'operational task thread' : '',
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
            const actualExecutionState = String((agent && agent.execution_state) || 'healthy').trim() || 'healthy';
            if (executionOverride) {
                const overrideExpired = Date.now() > Number(executionOverride.until || 0);
                const sameStaleFault = actualExecutionState === 'faulted'
                    && String(agent.execution_faulted_at || '') === String(executionOverride.staleFaultedAt || '')
                    && String(agent.execution_fault_detail || '') === String(executionOverride.staleDetail || '');
                if (overrideExpired || (!sameStaleFault && actualExecutionState === 'faulted') || actualExecutionState !== 'faulted') {
                    executionOverride = null;
                    resetNotice = '';
                }
            }
            const workers = status.workers || [];
            const signature = UI.dataSignature({
                agent: {
                    id: String(agent.agent_id || ''),
                    display: String(agent.display_name || agent.slug || ''),
                    slug: String(agent.slug || ''),
                    role: String(agent.role || ''),
                    provider: String(agent.provider || ''),
                    connectivity: String(agent.connectivity_state || ''),
                    execution: executionOverride ? String(executionOverride.state || 'healthy') : actualExecutionState,
                    executionDetail: executionOverride ? String(executionOverride.detail || '') : String(agent.execution_fault_detail || ''),
                    executionNote: String(resetNotice || ''),
                    heartbeatLabel: agent.last_heartbeat_at ? UI.relativeTime(agent.last_heartbeat_at) : '',
                    scope: String(agent.registry_scope || ''),
                    version: String(agent.version || ''),
                    routingSkills: (agent.routing_skills || []).map((skillName) => String(skillName || '')),
                    capabilities: (agent.management_capabilities || []).map((capability) => String(capability || '')),
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
                buildSkillsCard(agent),
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
