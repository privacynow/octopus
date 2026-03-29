function _createConversationTaskCard(task, convoId, { compact = false } = {}) {
    const card = document.createElement('article');
    card.className = `conversation-task-card${compact ? ' compact' : ''}`;
    card.dataset.key = `${compact ? 'compact:' : 'full:'}${task.routed_task_id}`;
    card.dataset.signature = UI.dataSignature({
        id: String(task.routed_task_id || ''),
        compact: Boolean(compact),
        status: String(task.status || ''),
        updatedLabel: UI.relativeTime(task.updated_at || task.created_at),
        title: String(task.title || task.routed_task_id || ''),
        summary: String(task.summary || task.result_summary || task.result_text || task.instructions || ''),
        target: String(task.target_display_name || task.target_agent_id || ''),
    });

    const header = document.createElement('div');
    header.className = 'conversation-task-card-header';
    const title = document.createElement('div');
    title.className = 'conversation-task-card-title';
    title.textContent = task.title || task.routed_task_id;
    header.appendChild(title);
    const badge = document.createElement('span');
    badge.className = `badge badge-${task.status || 'queued'}`;
    badge.textContent = task.status || 'queued';
    header.appendChild(badge);
    card.appendChild(header);

    const meta = document.createElement('div');
    meta.className = 'conversation-task-card-meta';
    const parts = [];
    if (task.target_display_name || task.target_agent_id) {
        const targetLabel = UI.visibleLabel(task.target_display_name, task.target_agent_id);
        if (targetLabel) {
            parts.push(`To ${targetLabel}`);
        }
    }
    if (task.updated_at || task.created_at) {
        const stamp = document.createElement('span');
        stamp.setAttribute('data-timestamp', task.updated_at || task.created_at || '');
        stamp.textContent = UI.relativeTime(task.updated_at || task.created_at || '');
        const label = document.createElement('span');
        label.textContent = parts.join(' · ');
        if (parts.length) {
            meta.appendChild(label);
            meta.appendChild(stamp);
        } else {
            meta.appendChild(stamp);
        }
    } else if (parts.length) {
        meta.textContent = parts.join(' · ');
    }
    if (meta.childElementCount || meta.textContent) {
        card.appendChild(meta);
    }

    const summary = task.summary
        || task.result_summary
        || task.result_text
        || task.instructions
        || '';
    if (summary) {
        const summaryBlock = document.createElement('p');
        summaryBlock.className = 'conversation-task-card-summary';
        summaryBlock.textContent = compact ? summary.slice(0, 180) : summary;
        card.appendChild(summaryBlock);
    }

    const taskActions = UI.createTaskActionButtons(
        task.routed_task_id,
        convoId,
        task.status || '',
        null,
        {
            cancelLabel: 'Cancel task',
            retryLabel: 'Retry task',
        },
    );
    if (taskActions.element.childElementCount > 1) {
        card.appendChild(taskActions.element);
    }

    return card;
}

function _conversationAssignedTargetLabel(tasks, conversationWith) {
    const normalizedWith = String(conversationWith || '').trim().toLowerCase();
    const sorted = (Array.isArray(tasks) ? tasks.slice() : []).sort((left, right) => {
        const leftStamp = Date.parse(String(left.updated_at || left.created_at || '')) || 0;
        const rightStamp = Date.parse(String(right.updated_at || right.created_at || '')) || 0;
        return rightStamp - leftStamp;
    });
    const preferred = sorted.find((task) => ['queued', 'submitted', 'leased', 'running'].includes(String(task.status || '')))
        || sorted[0];
    if (!preferred) return '';
    const label = _delegationTaskTargetLabel(preferred);
    if (!label) return '';
    if (normalizedWith && label.toLowerCase() === normalizedWith) return '';
    return label;
}
