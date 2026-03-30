function _createConversationEventElement(event, convoId, taskContext = []) {
    const kind = event.kind || '';
    if (kind === 'message.user' || kind === 'message.bot') {
        return _renderMessageBubble(event, kind);
    }

    const card = document.createElement('article');
    card.className = `event-card ${_eventCardClass(kind)}`;
    card.dataset.key = event.event_id || String(event.seq || `${kind}:${event.created_at || ''}`);

    const header = document.createElement('button');
    header.className = 'event-card-header';
    header.type = 'button';

    const titleGroup = document.createElement('div');
    titleGroup.className = 'event-card-heading';
    const title = document.createElement('span');
    title.className = 'kind';
    title.textContent = _eventPrimaryLabel(event);
    titleGroup.appendChild(title);
    const actorLabel = _eventActorLabel(event);
    if (actorLabel) {
        const actor = document.createElement('span');
        actor.className = 'event-card-actor';
        actor.textContent = actorLabel;
        titleGroup.appendChild(actor);
    }
    header.appendChild(titleGroup);

    const summary = document.createElement('span');
    summary.className = 'event-summary';
    summary.textContent = _eventSummary(kind, event, taskContext);
    header.appendChild(summary);

    const time = document.createElement('span');
    time.className = 'event-card-time';
    time.textContent = UI.formatTime(event.created_at);
    header.appendChild(time);
    card.appendChild(header);

    const body = document.createElement('div');
    body.className = 'event-card-body';
    body.id = `event-body-${UI.safeFilename(event.event_id || `${kind}-${event.seq || Date.now()}`)}`;
    header.setAttribute('aria-controls', body.id);
    const metadata = event.metadata || {};

    switch (kind) {
        case 'provider.request':
            _renderProviderRequestCard(body, event, metadata);
            break;
        case 'provider.response':
            _renderProviderResponseCard(body, metadata);
            break;
        case 'tool.execution':
            _renderToolExecutionCard(body, metadata);
            break;
        case 'approval.requested':
            _renderApprovalRequestedCard(body, event, metadata, convoId);
            break;
        case 'approval.decided':
            _renderApprovalDecidedCard(body, metadata);
            break;
        case 'delegation.proposed':
        case 'delegation.submitted':
        case 'delegation.completed':
            _renderDelegationCard(body, kind, metadata, taskContext);
            break;
        case 'task.status':
            _renderTaskStatusCard(body, event, metadata, convoId);
            break;
        case 'error':
            _renderErrorCard(body, event, metadata);
            break;
        default:
            _renderGenericEventCard(body, event);
            break;
    }

    const startExpanded = kind === 'approval.requested' || _shouldStartExpanded(kind, event);
    if (_shouldStackSummary(kind, event)) {
        header.classList.add('event-card-header-stacked');
        summary.classList.add('event-summary-stacked');
    }
    body.classList.toggle('expanded', startExpanded);
    header.setAttribute('aria-expanded', String(startExpanded));
    header.addEventListener('click', () => {
        const expanded = body.classList.toggle('expanded');
        header.setAttribute('aria-expanded', String(expanded));
    });

    card.appendChild(body);
    return card;
}

function _renderMessageBubble(event, kind) {
    const bubble = document.createElement('article');
    bubble.className = `chat-bubble ${kind === 'message.user' ? 'user' : 'bot'}`;
    bubble.dataset.key = event.event_id || String(event.seq || `${kind}:${event.created_at || ''}`);

    const actor = document.createElement('div');
    actor.className = 'actor';
    actor.textContent = event.actor || (kind === 'message.user' ? 'Operator' : 'Bot');
    bubble.appendChild(actor);

    const body = document.createElement('div');
    body.className = 'md-content';
    const temp = document.createElement('div');
    temp.innerHTML = UI.renderContent(event.content || '');
    while (temp.firstChild) body.appendChild(temp.firstChild);
    bubble.appendChild(body);

    const attachments = (event.metadata && event.metadata.attachments) || [];
    if (attachments.length) {
        const list = document.createElement('ul');
        list.className = 'attachment-list';
        attachments.forEach((item) => {
            const li = document.createElement('li');
            li.textContent = item;
            list.appendChild(li);
        });
        bubble.appendChild(list);
    }

    const timestamp = document.createElement('div');
    timestamp.className = 'timestamp';
    timestamp.textContent = UI.formatTime(event.created_at);
    bubble.appendChild(timestamp);
    return bubble;
}

function _renderProviderRequestCard(body, event, metadata) {
    body.appendChild(_metadataGrid([
        ['Provider', metadata.provider || ''],
        ['Model', metadata.model || ''],
        ['Mode', metadata.execution_mode || ''],
        ['Working dir', metadata.working_dir || ''],
        ['Files', metadata.file_policy || ''],
        ['Images', String(metadata.image_count || 0)],
        ['Prompt chars', Number(metadata.prompt_char_count || 0).toLocaleString()],
    ]));

    if (event.content) {
        const details = document.createElement('details');
        details.className = 'event-details';
        details.open = false;
        const summary = document.createElement('summary');
        summary.textContent = 'View full prompt';
        details.appendChild(summary);
        const pre = document.createElement('pre');
        pre.className = 'event-pre';
        pre.textContent = event.content;
        details.appendChild(pre);
        body.appendChild(details);
    }
}

function _renderProviderResponseCard(body, metadata) {
    const metrics = document.createElement('div');
    metrics.className = 'inline-metrics';
    metrics.appendChild(_createInlineMetric(Number(metadata.prompt_tokens || 0).toLocaleString(), 'Input'));
    metrics.appendChild(_createInlineMetric(Number(metadata.completion_tokens || 0).toLocaleString(), 'Reply'));
    metrics.appendChild(_createInlineMetric(`$${Number(metadata.cost_usd || 0).toFixed(4)}`, 'Cost'));
    metrics.appendChild(_createInlineMetric(metadata.provider || 'unknown', 'Provider'));
    body.appendChild(metrics);
}

function _renderToolExecutionCard(body, metadata) {
    body.appendChild(_metadataGrid([
        ['Tool', metadata.tool_name || ''],
        ['Status', metadata.status || ''],
        ['Duration', metadata.duration_ms !== null && metadata.duration_ms !== undefined ? `${metadata.duration_ms} ms` : '—'],
        ['Call ID', metadata.call_id || ''],
    ]));

    if (metadata.input_summary) {
        const input = document.createElement('div');
        input.className = 'event-text-block';
        input.innerHTML = `<strong>Input</strong><p>${UI.esc(metadata.input_summary)}</p>`;
        body.appendChild(input);
    }

    if (metadata.output_summary) {
        const output = document.createElement('div');
        output.className = 'event-text-block';
        output.innerHTML = `<strong>Output</strong><p>${UI.esc(metadata.output_summary)}</p>`;
        body.appendChild(output);
    }

    const changes = Array.isArray(metadata.file_changes) ? metadata.file_changes : [];
    if (changes.length) {
        const list = document.createElement('ul');
        list.className = 'change-list';
        changes.forEach((change) => {
            const item = document.createElement('li');
            item.innerHTML = `<strong>${UI.esc(change.change_type || 'changed')}</strong> <code>${UI.esc(change.path || '')}</code><span>${UI.esc(change.summary || '')}</span>`;
            list.appendChild(item);
        });
        body.appendChild(list);
    }
}

function _renderApprovalRequestedCard(body, event, metadata, convoId) {
    const requestKind = String(metadata.request_kind || 'approval').trim();
    body.appendChild(_metadataGrid([
        ['Request', requestKind || 'approval'],
        ['Requested by', metadata.actor_key || event.actor || 'agent'],
        ['Trust tier', metadata.trust_tier || ''],
        ['Expires', metadata.expires_at ? UI.formatApprovalTime(metadata.expires_at) : 'No deadline'],
    ]));

    if (event.content) {
        const content = document.createElement('div');
        content.className = 'event-text-block';
        const heading = requestKind === 'recovery'
            ? 'Recovery available'
            : requestKind === 'retry'
                ? 'Retry decision'
                : 'Needs a decision';
        content.innerHTML = `<strong>${UI.esc(heading)}</strong><p>${UI.esc(event.content)}</p>`;
        body.appendChild(content);
    }

    const expired = metadata.expires_at ? new Date(metadata.expires_at) < new Date() : false;
    const actions = document.createElement('div');
    actions.className = 'event-card-actions';

    const primary = document.createElement('button');
    primary.className = 'btn btn-sm btn-primary';

    const secondary = document.createElement('button');
    secondary.className = 'btn btn-sm btn-danger';

    const status = document.createElement('span');
    status.className = 'action-status';
    if (expired && requestKind !== 'recovery') status.textContent = 'Expired';

    let primaryAction = 'approve';
    let secondaryAction = 'reject';
    let payloadForAction = () => ({ request_id: event.event_id });

    if (requestKind === 'retry') {
        primary.textContent = 'Retry';
        secondary.textContent = 'Skip';
        primaryAction = 'retry_allow';
        secondaryAction = 'retry_skip';
    } else if (requestKind === 'recovery') {
        primary.textContent = 'Replay';
        secondary.textContent = 'Discard';
        const recoveryId = String(metadata.recovery_id || '').trim();
        payloadForAction = () => ({ recovery_id: recoveryId });
        if (!recoveryId) {
            primary.disabled = true;
            secondary.disabled = true;
            status.textContent = 'Recovery action unavailable';
        }
    } else {
        primary.textContent = 'Approve';
        secondary.textContent = 'Reject';
    }

    if (requestKind !== 'recovery') {
        primary.disabled = expired;
        secondary.disabled = expired;
    }

    async function act(action) {
        primary.disabled = true;
        secondary.disabled = true;
        try {
            await API.conversationAction(convoId, action, payloadForAction());
            if (action === 'approve') status.textContent = 'Approved';
            else if (action === 'reject') status.textContent = 'Rejected';
            else if (action === 'retry_allow') status.textContent = 'Retrying';
            else if (action === 'retry_skip') status.textContent = 'Skipped';
            else if (action === 'recovery_replay') status.textContent = 'Replaying';
            else if (action === 'recovery_discard') status.textContent = 'Discarded';
            else status.textContent = 'Updated';
        } catch (err) {
            UI.reportError('Failed to update the request', err, { context: 'Conversation request action failed' });
            primary.disabled = requestKind !== 'recovery' && expired;
            secondary.disabled = requestKind !== 'recovery' && expired;
            status.textContent = 'Action failed';
        }
    }

    primary.addEventListener('click', () => act(primaryAction));
    secondary.addEventListener('click', () => act(secondaryAction));

    actions.appendChild(primary);
    actions.appendChild(secondary);
    actions.appendChild(status);
    body.appendChild(actions);
}

function _renderApprovalDecidedCard(body, metadata) {
    body.appendChild(_metadataGrid([
        ['Decision', metadata.decision || ''],
        ['Action', metadata.action || ''],
        ['Handled by', metadata.decided_by || ''],
    ]));
}

function _renderDelegationCard(body, kind, metadata, taskContext = []) {
    const tasks = Array.isArray(metadata.tasks) ? metadata.tasks : [];
    if (!tasks.length) {
        _renderGenericMetadata(body, metadata);
        return;
    }
    const list = document.createElement('div');
    list.className = 'delegation-milestone-list';
    tasks.forEach((task) => {
        const item = document.createElement('div');
        item.className = 'delegation-milestone-item';
        const title = document.createElement('strong');
        title.textContent = task.title || 'Delegated task';
        item.appendChild(title);
        const meta = document.createElement('span');
        meta.className = 'delegation-milestone-meta';
        const parts = [];
        const target = _delegationTaskTargetLabel(task, taskContext);
        if (target) {
            parts.push(kind === 'delegation.completed' ? `Handled by ${target}` : `Assigned to ${target}`);
        }
        const status = _taskStatusPhrase(task.status || '');
        if (kind === 'delegation.completed' && status) {
            parts.push(status);
        }
        meta.textContent = parts.join(' · ');
        if (meta.textContent) {
            item.appendChild(meta);
        }
        list.appendChild(item);
    });
    body.appendChild(list);
}

function _renderTaskStatusCard(body, event, metadata, convoId) {
    const status = String(metadata.status || '').trim();
    const terminalWithOutcome = ['completed', 'failed', 'cancelled', 'timed_out'].includes(status) && Boolean(String(event.content || '').trim());
    const progressValue = metadata.progress !== null && metadata.progress !== undefined ? `${metadata.progress}%` : '';
    const facts = [];
    if (progressValue) facts.push(['Progress', progressValue]);
    if (status && !['completed', 'failed', 'cancelled', 'timed_out'].includes(status)) {
        facts.push(['State', _taskStatusPhrase(status)]);
    }
    if (facts.length) {
        body.appendChild(_metadataGrid(facts));
    }
    if (metadata.progress !== null && metadata.progress !== undefined) {
        const progress = document.createElement('div');
        progress.className = 'progress-track';
        const fill = document.createElement('div');
        fill.className = 'progress-fill';
        fill.style.width = `${Math.max(0, Math.min(100, Number(metadata.progress || 0)))}%`;
        progress.appendChild(fill);
        body.appendChild(progress);
    }
    if (event.content) {
        const content = document.createElement('div');
        content.className = terminalWithOutcome ? 'event-text-block event-text-block-outcome' : 'event-text-block';
        content.innerHTML = `<p>${UI.esc(event.content)}</p>`;
        body.appendChild(content);
    }
    const taskId = String(metadata.routed_task_id || '').trim();
    if (taskId && convoId) {
        const taskActions = UI.createTaskActionButtons(
            taskId,
            convoId,
            status,
            null,
            { cancelLabel: 'Cancel task', retryLabel: 'Retry task' },
        );
        if (taskActions.element.childElementCount > 1) {
            body.appendChild(taskActions.element);
        }
    }
}

function _renderErrorCard(body, event, metadata) {
    body.appendChild(_metadataGrid([
        ['Problem type', metadata.error_type || 'execution'],
        ['Message', metadata.message || event.content || ''],
    ]));
    if (event.content && event.content !== metadata.message) {
        const block = document.createElement('div');
        block.className = 'event-text-block';
        block.innerHTML = `<strong>Content</strong><p>${UI.esc(event.content)}</p>`;
        body.appendChild(block);
    }
}

function _renderGenericEventCard(body, event) {
    if (event.content) {
        const content = document.createElement('div');
        content.className = 'event-text-block';
        const temp = document.createElement('div');
        temp.innerHTML = UI.renderContent(event.content);
        while (temp.firstChild) content.appendChild(temp.firstChild);
        body.appendChild(content);
    }
    _renderGenericMetadata(body, event.metadata || {});
}

function _renderGenericMetadata(body, metadata) {
    const meta = JSON.stringify(metadata || {}, null, 2);
    if (!meta || meta === '{}') return;
    const pre = document.createElement('pre');
    pre.className = 'event-pre';
    pre.textContent = meta;
    body.appendChild(pre);
}

function _metadataGrid(entries) {
    const grid = document.createElement('div');
    grid.className = 'metadata-grid';
    entries.forEach(([label, value]) => {
        if (value === '' || value === null || value === undefined) return;
        const item = document.createElement('div');
        item.className = 'metadata-item';
        item.innerHTML = `<span>${UI.esc(label)}</span><strong>${UI.esc(String(value))}</strong>`;
        grid.appendChild(item);
    });
    return grid;
}

function _createInlineMetric(value, label) {
    const metric = document.createElement('div');
    metric.className = 'inline-metric';
    metric.innerHTML = `<strong>${UI.esc(String(value))}</strong><span>${UI.esc(label)}</span>`;
    return metric;
}

function _eventSummary(kind, event, taskContext = []) {
    const metadata = event.metadata || {};
    switch (kind) {
        case 'provider.request':
            return [
                metadata.provider || metadata.model || 'Provider',
                metadata.execution_mode || 'run',
                `${Number(metadata.prompt_char_count || (event.content || '').length || 0).toLocaleString()} chars`,
            ].filter(Boolean).join(' · ');
        case 'provider.response':
            return [
                `${Number((metadata.prompt_tokens || 0) + (metadata.completion_tokens || 0)).toLocaleString()} tokens`,
                `$${Number(metadata.cost_usd || 0).toFixed(4)}`,
            ].join(' · ');
        case 'tool.execution':
            return [
                metadata.tool_name || 'Tool',
                metadata.status || 'completed',
                metadata.duration_ms !== null && metadata.duration_ms !== undefined ? `${metadata.duration_ms} ms` : '',
            ].filter(Boolean).join(' · ');
        case 'delegation.proposed':
        case 'delegation.submitted':
        case 'delegation.completed': {
            const tasks = Array.isArray(metadata.tasks) ? metadata.tasks : [];
            const targets = _uniqueDelegationTargets(tasks, taskContext);
            if (kind === 'delegation.submitted' && targets.length === 1) {
                return `Assigned to ${targets[0]}`;
            }
            if (kind === 'delegation.completed' && targets.length === 1) {
                return `Finished by ${targets[0]}`;
            }
            const taskCount = tasks.length;
            if (taskCount) {
                const label = kind === 'delegation.completed' ? 'finished' : kind === 'delegation.proposed' ? 'proposed' : 'submitted';
                return `${taskCount} task${taskCount === 1 ? '' : 's'} ${label}`;
            }
            return '';
        }
        case 'task.status':
            return [
                _taskStatusPhrase(metadata.status || 'update'),
                metadata.progress !== null && metadata.progress !== undefined ? `${metadata.progress}%` : '',
            ].filter(Boolean).join(' · ');
        case 'error':
            return (metadata.message || event.content || 'Execution problem').split('\n')[0].slice(0, 80);
        case 'approval.decided':
            return `${metadata.decision || 'handled'}${metadata.decided_by ? ` by ${metadata.decided_by}` : ''}`;
        case 'approval.requested':
            if (metadata.request_kind === 'retry') return 'Retry decision';
            if (metadata.request_kind === 'recovery') return 'Recovery decision';
            if (metadata.request_kind === 'delegation') return 'Delegation decision';
            return metadata.request_kind || 'Approval needed';
        default:
            return event.actor || '';
    }
}

function _eventKindLabel(kind) {
    const labels = {
        'provider.request': 'Agent started work',
        'provider.response': 'Agent finished work',
        'tool.execution': 'Used a tool',
        'approval.requested': 'Approval needed',
        'approval.decided': 'Approval recorded',
        'delegation.proposed': 'Plan proposed',
        'delegation.submitted': 'Delegated work started',
        'delegation.completed': 'Delegated work finished',
        'task.status': 'Work update',
        'error': 'Problem reported',
        'message.user': 'Operator message',
        'message.bot': 'Agent message',
    };
    return labels[kind] || (kind || 'event').replace(/\./g, ' · ');
}

function _eventCardClass(kind) {
    if (kind.startsWith('provider.')) return 'provider';
    if (kind.startsWith('tool.')) return 'tool';
    if (kind.startsWith('approval.')) return 'approval';
    if (kind.startsWith('delegation.')) return 'delegation';
    if (kind === 'task.status') return 'task';
    if (kind === 'error') return 'error';
    return 'generic';
}

function _eventPrimaryLabel(event) {
    const kind = event.kind || '';
    const metadata = event.metadata || {};
    if (kind === 'delegation.submitted') return 'Task submitted';
    if (kind === 'delegation.completed') return 'Delegated work finished';
    if (kind === 'delegation.proposed') return 'Delegation proposed';
    if (kind === 'task.status') {
        const status = String(metadata.status || '').trim();
        if (status === 'completed') return 'Task completed';
        if (['failed', 'cancelled', 'timed_out'].includes(status)) return 'Task needs follow-up';
        if (status === 'running') return 'Task in progress';
        if (['queued', 'submitted', 'leased'].includes(status)) return 'Task queued';
    }
    return _eventKindLabel(kind);
}

function _eventActorLabel(event) {
    const kind = event.kind || '';
    if (['delegation.proposed', 'delegation.submitted', 'delegation.completed', 'task.status'].includes(kind)) {
        return '';
    }
    return event.actor || '';
}

function _delegationTaskTargetLabel(task, taskContext = []) {
    const routedTaskId = String(task.routed_task_id || '').trim();
    if (routedTaskId) {
        const match = (Array.isArray(taskContext) ? taskContext : []).find((candidate) => String(candidate.routed_task_id || '').trim() === routedTaskId);
        if (match) {
            return UI.visibleLabel(
                match.target_display_name
                || match.target
                || match.target_agent_id
                || ''
            );
        }
    }
    const targetAgentId = String(task.target_agent_id || task.target || '').trim();
    if (targetAgentId) {
        const matchByTarget = (Array.isArray(taskContext) ? taskContext : []).find((candidate) => {
            const candidateTarget = String(candidate.target_agent_id || candidate.target || '').trim();
            return candidateTarget && candidateTarget === targetAgentId;
        });
        if (matchByTarget) {
            return UI.visibleLabel(
                matchByTarget.target_display_name
                || matchByTarget.target
                || matchByTarget.target_agent_id
                || ''
            );
        }
    }
    return UI.visibleLabel(
        task.target_display_name
        || task.target
        || task.target_agent_id
        || task.authority_ref
        || ''
    );
}

function _uniqueDelegationTargets(tasks, taskContext = []) {
    return Array.from(new Set(
        (Array.isArray(tasks) ? tasks : [])
            .map((task) => _delegationTaskTargetLabel(task, taskContext))
            .filter(Boolean)
    ));
}

function _taskStatusPhrase(status) {
    const value = String(status || '').trim().toLowerCase();
    switch (value) {
        case 'queued':
            return 'Queued';
        case 'submitted':
            return 'Submitted';
        case 'leased':
            return 'Leased';
        case 'running':
            return 'Running';
        case 'completed':
            return 'Completed';
        case 'failed':
            return 'Failed';
        case 'cancelled':
            return 'Cancelled';
        case 'timed_out':
            return 'Timed out';
        default:
            return value ? value.charAt(0).toUpperCase() + value.slice(1) : '';
    }
}

function _originChannelLabel(originChannel) {
    const value = String(originChannel || '').trim();
    return value || '';
}

function _formatConversationStatusLabel(status) {
    const value = String(status || '').trim().toLowerCase();
    if (!value) return 'Open';
    return value.replace(/_/g, ' ').replace(/\b\w/g, (match) => match.toUpperCase());
}

function _shouldStartExpanded(kind, event) {
    if (kind !== 'task.status') return false;
    return false;
}

function _shouldStackSummary(kind, event) {
    if (kind !== 'task.status') return false;
    const status = String((event.metadata && event.metadata.status) || '').trim().toLowerCase();
    return Boolean(String(event.content || '').trim()) && ['completed', 'failed', 'cancelled', 'timed_out'].includes(status);
}
