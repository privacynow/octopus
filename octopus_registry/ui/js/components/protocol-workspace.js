const PROTOCOL_ISSUE_FILTER_OPTIONS = [
    { value: '', label: 'Runs' },
    { value: 'all', label: 'All issues' },
    { value: 'blocked_run', label: 'Blocked runs' },
    { value: 'invalid_contract', label: 'Contract errors' },
    { value: 'stuck_lease', label: 'Expired write lease' },
    { value: 'runtime_evidence_required', label: 'Runtime evidence' },
    { value: 'operator_interrupted', label: 'Operator interrupted' },
    { value: 'acceptance_contract_invalid', label: 'Invalid acceptance contract' },
    { value: 'expired_timeout', label: 'Expired timeouts' },
];

const PROTOCOL_RUN_VIEW_FILTER_OPTIONS = [
    { value: 'recent', label: 'Recent' },
    { value: 'attention', label: 'Needs attention' },
    { value: 'running', label: 'Running' },
    { value: 'completed', label: 'Completed' },
    { value: 'outcomes', label: 'With outcomes' },
    { value: 'archived', label: 'Archived' },
    { value: 'deleted', label: 'Deleted' },
    { value: 'telegram', label: 'From Telegram' },
    { value: 'registry', label: 'From Registry' },
];

const AUTO_PROTOCOL_ACTIVE_SESSION_KEY = 'octopus.protocolAuto.activeSessionId';
let activeAutoProtocolSessionId = '';

function _isCompactViewport() {
    return window.innerWidth <= 960;
}

function _compactProtocolRunViewOptions() {
    if (!_isCompactViewport()) return PROTOCOL_RUN_VIEW_FILTER_OPTIONS;
    const compactLabels = {
        attention: 'Attention',
        outcomes: 'Outcomes',
        telegram: 'Telegram',
        registry: 'Registry',
    };
    return PROTOCOL_RUN_VIEW_FILTER_OPTIONS.map((item) => ({
        ...item,
        label: compactLabels[item.value] || item.label,
    }));
}

function _downloadProtocolText(filename, text, contentType) {
    const blob = new Blob([text], { type: contentType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 500);
}

function _autoProtocolErrorMessage(label, err) {
    const detail = err && err.message ? err.message : String(err || 'Unknown error');
    const code = String(err?.errorCode || '').trim();
    const prefix = code ? `${label} [${code}]` : label;
    return detail && detail !== label ? `${prefix}: ${detail}` : prefix;
}

function _autoProtocolErrorEl(label, err, retryFn) {
    const status = Number(err?.status || 0);
    const code = String(err?.errorCode || '').trim().toUpperCase();
    const retryable = Boolean(retryFn)
        && (!status
            || status === 408
            || status === 429
            || status >= 500
            || (status === 409 && code === 'CONCURRENT_MODIFICATION'));
    let retrying = false;
    const retryOnce = retryable
        ? async (event) => {
            if (retrying) return;
            retrying = true;
            const target = event?.currentTarget;
            if (target) target.disabled = true;
            try {
                await retryFn();
            } finally {
                retrying = false;
                if (target?.isConnected) target.disabled = false;
            }
        }
        : null;
    const card = UI.createErrorCard(_autoProtocolErrorMessage(label, err), retryOnce);
    card.classList.add('protocol-auto-error');
    card.setAttribute('role', 'alert');
    if (!retryable && Boolean(retryFn)) {
        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = 'Retry will not change this condition. Refresh or resolve the requested action before trying again.';
        card.appendChild(note);
    }
    return card;
}

function _setAutoProtocolStatus(status, message) {
    status.className = 'quiet-note';
    status.textContent = message;
}

function _setAutoProtocolDialogError(preview, status, label, err, retryFn) {
    status.className = 'quiet-note protocol-auto-error-note';
    status.textContent = 'The operation did not complete. Review the error details below.';
    UI.reconcileChildren(preview, [_autoProtocolErrorEl(label, err, retryFn)]);
    console.error(label, err);
}

function _autoProtocolPlanningError(err) {
    const code = String(err?.errorCode || '').trim().toUpperCase();
    return Number(err?.status) === 409 && code === 'PROTOCOL_AUTO_PLANNING';
}

function _rememberAutoProtocolSession(sessionId) {
    const normalized = String(sessionId || '').trim();
    try {
        if (normalized) {
            window.localStorage?.setItem(AUTO_PROTOCOL_ACTIVE_SESSION_KEY, normalized);
        } else {
            window.localStorage?.removeItem(AUTO_PROTOCOL_ACTIVE_SESSION_KEY);
        }
    } catch (err) {
        void err;
    }
}

function _rememberActiveAutoProtocolSession(session) {
    const sessionId = String(session?.session_id || '').trim();
    if (sessionId && _autoProtocolPlanning(session)) {
        activeAutoProtocolSessionId = sessionId;
        _rememberAutoProtocolSession(sessionId);
        return;
    }
    if (!sessionId || sessionId === activeAutoProtocolSessionId || sessionId === _rememberedAutoProtocolSessionId()) {
        activeAutoProtocolSessionId = '';
        _rememberAutoProtocolSession('');
    }
}

function _rememberedAutoProtocolSessionId() {
    try {
        return String(window.localStorage?.getItem(AUTO_PROTOCOL_ACTIVE_SESSION_KEY) || '').trim();
    } catch (err) {
        void err;
        return '';
    }
}

function _subscribeAutoProtocolSession(sessionId, onUpdate) {
    const normalized = String(sessionId || '').trim();
    if (!normalized || typeof WS === 'undefined' || !WS || typeof WS.subscribe !== 'function') {
        return () => {};
    }
    let timer = null;
    const unsubscribe = WS.subscribe(`protocol-auto-session:${normalized}`, () => {
        clearTimeout(timer);
        timer = window.setTimeout(async () => {
            try {
                const updated = await API.getProtocolAutoSession(normalized);
                await onUpdate(updated);
            } catch (err) {
                console.warn('Failed to refresh Auto Protocol session after websocket update', err);
            }
        }, 250);
    });
    return () => {
        clearTimeout(timer);
        if (typeof unsubscribe === 'function') unsubscribe();
    };
}

function _autoProtocolSleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function _autoProtocolPlanning(session) {
    return String(session?.status || '') === 'planning';
}

function _autoProtocolErrorSessionId(err) {
    const details = err?.details && typeof err.details === 'object' ? err.details : {};
    const payloadDetail = err?.payload?.detail && typeof err.payload.detail === 'object'
        ? err.payload.detail
        : {};
    return String(
        details.session_id
        || payloadDetail.session_id
        || payloadDetail.details?.session_id
        || '',
    ).trim();
}

function _autoProtocolSelectedAgentLabel(session, catalog = []) {
    const plannerState = session?.planner_state || {};
    const selectedAgent = plannerState.selected_agent || {};
    const agentId = String(
        plannerState.selected_agent_id
        || session?.planner_agent_id
        || selectedAgent.agent_id
        || '',
    ).trim();
    const unique = new Map();
    (Array.isArray(catalog) ? catalog : []).forEach((agent) => {
        const id = String(agent?.agent_id || '').trim();
        if (id && !unique.has(id)) unique.set(id, agent);
    });
    const catalogAgent = agentId ? unique.get(agentId) : null;
    return String(
        plannerState.selected_agent_display_name
        || selectedAgent.display_name
        || selectedAgent.slug
        || catalogAgent?.display_name
        || catalogAgent?.slug
        || agentId
        || 'Auto-selecting planner',
    ).trim();
}

function _autoProtocolTargetProtocolId(session) {
    return String(
        session?.target_protocol_id
        || session?.applied_protocol?.protocol?.protocol_id
        || session?.protocol?.protocol_id
        || '',
    ).trim();
}

function _autoProtocolPlannerAgentsFrom(agents = []) {
    return (Array.isArray(agents) ? agents : []).filter((agent) =>
        (Array.isArray(agent?.supported_admin_operations) ? agent.supported_admin_operations : [])
            .some((operation) => String(operation || '').trim() === 'design_auto_protocol'));
}

function _populateAutoProtocolPlannerSelect(select, agents = []) {
    if (!select) return;
    const currentValue = String(select.value || '').trim();
    select.disabled = false;
    select.textContent = '';
    const auto = document.createElement('option');
    auto.value = '';
    auto.textContent = 'Auto-select available planner';
    select.appendChild(auto);
    _autoProtocolPlannerAgentsFrom(agents).forEach((agent) => {
        const option = document.createElement('option');
        option.value = String(agent.agent_id || '');
        option.textContent = UI.visibleLabel(agent.display_name, agent.slug || agent.agent_id, 'Agent');
        select.appendChild(option);
    });
    if (currentValue && Array.from(select.options).some((option) => option.value === currentValue)) {
        select.value = currentValue;
    }
}

function _setAutoProtocolPlannerSelectLoading(select) {
    if (!select) return;
    select.disabled = true;
    select.textContent = '';
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'Loading planner agents...';
    option.selected = true;
    select.appendChild(option);
}

function _createAutoProtocolPlannerField(agents = [], { loading = false } = {}) {
    const label = document.createElement('label');
    label.className = 'kit-details-field';
    const title = document.createElement('span');
    title.className = 'kit-details-label';
    title.textContent = 'Planner agent';
    label.appendChild(title);
    const select = document.createElement('select');
    select.className = 'input';
    select.setAttribute('aria-label', 'Planner agent');
    if (loading) {
        _setAutoProtocolPlannerSelectLoading(select);
    } else {
        _populateAutoProtocolPlannerSelect(select, agents);
    }
    label.appendChild(select);
    const help = document.createElement('span');
    help.className = 'kit-details-help';
    help.textContent = 'Auto uses the planner queue and rotates across capable connected agents. Choose an agent only when you need to target one explicitly.';
    label.appendChild(help);
    return { element: label, select };
}

function _autoProtocolRunAttemptKey(sessionId) {
    const normalized = String(sessionId || '').trim();
    const uuid = window.crypto?.randomUUID ? window.crypto.randomUUID().replace(/-/g, '') : '';
    const nonce = uuid || `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
    return `auto-protocol-session:${normalized}:run:${nonce}`;
}

function _autoProtocolSessionSourceRunId(session) {
    return String(session?.source_run_id || '').trim();
}

function _autoProtocolSessionMatchesRememberedContext(session, { mode = 'create', targetProtocolId = '', sourceRunId = '' } = {}) {
    if (!session?.session_id) return false;
    const expectedRunId = String(sourceRunId || '').trim();
    const sessionRunId = _autoProtocolSessionSourceRunId(session);
    if (expectedRunId) {
        return sessionRunId === expectedRunId;
    }
    if (sessionRunId) return false;
    const expectedProtocolId = String(targetProtocolId || '').trim();
    const sessionProtocolId = _autoProtocolTargetProtocolId(session);
    if (String(mode || '') === 'revise') {
        return Boolean(expectedProtocolId && sessionProtocolId === expectedProtocolId);
    }
    return !sessionProtocolId;
}

function _setAutoProtocolButtonBusy(button, busy) {
    if (!button) return;
    if (busy) {
        button.dataset.autoProtocolBusy = '1';
        button.disabled = true;
        return;
    }
    delete button.dataset.autoProtocolBusy;
}

function _setAutoProtocolButtonState(button, { visible = true, disabled = false } = {}) {
    if (!button) return;
    const shown = Boolean(visible);
    button.hidden = !shown;
    if (!shown) {
        button.disabled = true;
        button.tabIndex = -1;
        button.setAttribute('aria-hidden', 'true');
        return;
    }
    button.removeAttribute('aria-hidden');
    button.removeAttribute('tabindex');
    button.disabled = button.dataset.autoProtocolBusy === '1' || Boolean(disabled);
}

function _autoProtocolHasDraft(session) {
    const draft = session?.draft_definition_json || {};
    return Boolean(draft.metadata && Array.isArray(draft.stages));
}

function _autoProtocolFinishedMessage(session, readyMessage) {
    const status = String(session?.status || '');
    if (status === 'failed') return 'Planning failed. Review the details below, adjust the request, and retry.';
    if (status === 'blocked') return 'Planning finished with blockers. Review the required decisions before publishing or running.';
    return readyMessage;
}

function _autoProtocolPlannerFact(label, value) {
    const row = document.createElement('div');
    row.className = 'kit-details-row';
    const key = document.createElement('div');
    key.className = 'kit-details-label';
    key.textContent = label;
    const val = document.createElement('div');
    val.className = 'kit-artifact-guide-fact-value';
    val.textContent = value || 'Not recorded';
    row.appendChild(key);
    row.appendChild(val);
    return row;
}

function _autoProtocolProgressEl(session = null) {
    const plannerState = session?.planner_state || {};
    const promptDiagnostics = session?.prompt_diagnostics || {};
    const panel = document.createElement('div');
    panel.className = 'protocol-auto-progress';
    const title = document.createElement('strong');
    title.textContent = 'Designing the protocol';
    panel.appendChild(title);
    const note = document.createElement('p');
    const state = String(plannerState.planner_status || session?.status || 'planning').replace(/_/g, ' ');
    const quiet = plannerState.last_progress_at
        ? ` Last progress ${UI.relativeTime(plannerState.last_progress_at)}.`
        : '';
    note.textContent = `Planner state: ${state}.${quiet} Heavy design and revision inputs can take tens of minutes; the planner is kept queued and observable instead of timing out the UI.`;
    panel.appendChild(note);
    const facts = document.createElement('div');
    facts.className = 'kit-details-grid';
    facts.appendChild(_autoProtocolPlannerFact('Planner agent', _autoProtocolSelectedAgentLabel(session)));
    if (session?.planner_policy) {
        facts.appendChild(_autoProtocolPlannerFact('Planner policy', String(session.planner_policy).replace(/_/g, ' ')));
    }
    if (session?.planner_task_id || session?.planner_request_id) {
        facts.appendChild(_autoProtocolPlannerFact('Planner job', session.planner_task_id || session.planner_request_id));
    }
    if (plannerState.started_at) {
        facts.appendChild(_autoProtocolPlannerFact('Started', UI.relativeTime(plannerState.started_at)));
    }
    if (plannerState.last_progress_at) {
        facts.appendChild(_autoProtocolPlannerFact('Last progress', UI.relativeTime(plannerState.last_progress_at)));
    }
    if (plannerState.timeout_at) {
        facts.appendChild(_autoProtocolPlannerFact('Timeout', UI.relativeTime(plannerState.timeout_at)));
    }
    if (Number.isFinite(Number(plannerState.queue_position))) {
        facts.appendChild(_autoProtocolPlannerFact('Queue position', String(Number(plannerState.queue_position) + 1)));
    }
    if (promptDiagnostics.large_input) {
        facts.appendChild(_autoProtocolPlannerFact('Input size', 'Large design input'));
    }
    if (Number.isFinite(Number(promptDiagnostics.requirement_chars))) {
        facts.appendChild(_autoProtocolPlannerFact('Requirement', `${Number(promptDiagnostics.requirement_chars).toLocaleString()} chars`));
    }
    if (Number.isFinite(Number(promptDiagnostics.source_document_chars)) && Number(promptDiagnostics.source_document_chars) > 0) {
        facts.appendChild(_autoProtocolPlannerFact('Source draft', `${Number(promptDiagnostics.source_document_chars).toLocaleString()} chars`));
    }
    if (Number.isFinite(Number(promptDiagnostics.lesson_count)) && Number(promptDiagnostics.lesson_count) > 0) {
        facts.appendChild(_autoProtocolPlannerFact('Lessons', String(Number(promptDiagnostics.lesson_count))));
    }
    panel.appendChild(facts);
    const progressText = String(plannerState.progress_summary || '').trim();
    if (progressText) {
        const progress = document.createElement('p');
        progress.className = 'quiet-note';
        progress.textContent = progressText;
        panel.appendChild(progress);
    }
    const steps = document.createElement('ol');
    [
        'Analyze the requested outcome',
        'Design work packages and review gates',
        'Compile a normal protocol draft',
        'Validate readiness and assignment blockers',
    ].forEach((label) => {
        const item = document.createElement('li');
        item.textContent = label;
        steps.appendChild(item);
    });
    panel.appendChild(steps);
    return panel;
}

function _protocolArtifactLabel(item) {
    const parts = [];
    if (item.content_hash) {
        parts.push(`sha256 ${String(item.content_hash).slice(0, 12)}`);
    }
    if (Number.isFinite(Number(item.size_bytes || 0)) && Number(item.size_bytes || 0) > 0) {
        parts.push(`${Number(item.size_bytes || 0).toLocaleString()} bytes`);
    }
    return parts.join(' · ');
}

function _protocolRunTaskHref(runId, routedTaskId) {
    const params = new URLSearchParams();
    if (runId) params.set('protocol_run_id', String(runId));
    if (routedTaskId) params.set('task_id', String(routedTaskId));
    const query = params.toString();
    return query ? `/ui/tasks?${query}` : '/ui/tasks';
}

function _protocolRunHref(runId) {
    const params = new URLSearchParams();
    if (runId) params.set('run_id', String(runId));
    const query = params.toString();
    return query ? `/ui/runs?${query}` : '/ui/runs';
}

function _protocolArtifactDisplayPath(item) {
    return String(item?.location || item?.workspace_path || '').trim();
}

function _protocolArtifactDisplayLabel(item, definition = null) {
    const label = String(definition?.display_name || '').trim();
    if (label) return label;
    const pathLabel = UI.basenameDisplayPath(_protocolArtifactDisplayPath(item) || _artifactDefinitionPath(item));
    if (pathLabel) return pathLabel;
    return String(item?.artifact_key || 'Artifact').trim();
}

function _protocolArtifactPreviewable(item) {
    return UI.isPreviewableFilePath(_protocolArtifactDisplayPath(item));
}

function _runtimeStatusLabel(runtime = {}) {
    const status = String(runtime?.status || '').trim().toLowerCase();
    if (!status) return 'Unknown';
    return _titleCaseWords(status.replace(/_/g, ' '));
}

function _runtimeEndpoint(runtime = {}, key = '') {
    const manifest = runtime?.manifest || {};
    if (key === 'api_docs') {
        const docsEndpoint = (Array.isArray(manifest.endpoints) ? manifest.endpoints : [])
            .find((item) => String(item?.endpoint_kind || '').toLowerCase() === 'docs');
        return _runtimeApiProxyPath(runtime, docsEndpoint?.path || '');
    }
    return '';
}

function _runtimeHttpPath(value = '', fallback = '') {
    let text = String(value || fallback || '').trim();
    if (!text) return '';
    if (!text.startsWith('/')) text = `/${text}`;
    return text;
}

function _runtimeApiProxyPath(runtime = {}, path = '') {
    const manifest = runtime?.manifest || {};
    const text = _runtimeHttpPath(path);
    if (!text) return '';
    const apiBase = _runtimeHttpPath(manifest.api_base_path || '/api', '/api').replace(/\/+$/, '') || '/api';
    if (text === apiBase) return '';
    if (text.startsWith(`${apiBase}/`)) return text.slice(apiBase.length).replace(/^\/+/, '');
    return text.replace(/^\/+/, '');
}

function _runtimeFact(label, value, { link = false } = {}) {
    const row = document.createElement('div');
    row.className = 'kit-details-row';
    const labelEl = document.createElement('div');
    labelEl.className = 'kit-details-label';
    labelEl.textContent = label;
    row.appendChild(labelEl);
    const valueEl = link && value ? document.createElement('a') : document.createElement('div');
    valueEl.className = 'kit-artifact-guide-fact-value';
    if (link && value) {
        valueEl.href = String(value);
        valueEl.target = '_blank';
        valueEl.rel = 'noreferrer noopener';
        valueEl.textContent = String(value);
    } else {
        valueEl.textContent = String(value || 'Not available');
    }
    row.appendChild(valueEl);
    return row;
}

async function _artifactRuntimeSnapshot(runId, artifactKey) {
    const [status, events] = await Promise.all([
        API.getProtocolRunArtifactRuntime(runId, artifactKey),
        API.getProtocolRunArtifactRuntimeEvents(runId, artifactKey, 12).catch(() => ({ items: [] })),
    ]);
    return {
        runtime: status?.runtime || null,
        health: status?.health || null,
        manifestAvailable: Boolean(status?.manifest_available),
        packageUrl: status?.package_url || '',
        browseUrl: status?.browse_url || '',
        events: Array.isArray(events?.items) ? events.items : [],
    };
}

function _contractJourneyKeysForArtifact(artifactKey) {
    const key = String(artifactKey || '').trim();
    const autoMeta = currentRun?.version?.definition_json?.metadata?.auto_protocol || {};
    const primaryKey = String(autoMeta.primary_artifact?.artifact_key || autoMeta.primary_artifact_key || '').trim();
    if (primaryKey && key && primaryKey !== key) return [];
    const contract = autoMeta.acceptance_contract || {};
    const journeys = Array.isArray(contract.required_journeys) ? contract.required_journeys : [];
    return journeys
        .map((item) => String(item?.journey_key || '').trim())
        .filter(Boolean);
}

function _renderArtifactRuntimeDialogBody({
    runId,
    artifactKey,
    artifactLabel,
    snapshot,
    health = null,
    logs = null,
} = {}) {
    const runtime = snapshot?.runtime || {};
    const manifest = runtime?.manifest || {};
    const status = String(runtime?.status || '').toLowerCase();
    const healthReady = !health || health.ok === true;
    const appUrl = API.protocolRunArtifactRuntimeAppUrl(runId, artifactKey);
    const apiUrl = API.protocolRunArtifactRuntimeApiUrl(runId, artifactKey);
    const docsPath = _runtimeEndpoint(runtime, 'api_docs');
    const docsUrl = docsPath ? API.protocolRunArtifactRuntimeApiUrl(runId, artifactKey, docsPath) : '';

    const body = document.createElement('div');
    body.className = 'artifact-runtime-dialog';

    const intro = document.createElement('p');
    intro.className = 'quiet-note';
    intro.textContent = snapshot?.manifestAvailable
        ? `App controls for ${artifactLabel || artifactKey}. Octopus updates this panel while the app starts; Open app appears after the health check passes.`
        : 'This artifact does not declare a runtime. You can still browse files or download the package.';
    body.appendChild(intro);

    const facts = document.createElement('div');
    facts.className = 'kit-details-panel artifact-runtime-facts';
    facts.appendChild(_runtimeFact('Status', status === 'running' && !healthReady ? 'Starting · health pending' : _runtimeStatusLabel(runtime)));
    facts.appendChild(_runtimeFact('Kind', manifest.runtime_kind || 'Not declared'));
    facts.appendChild(_runtimeFact('Started', runtime.started_at ? UI.formatTime(runtime.started_at) : 'Not started'));
    facts.appendChild(_runtimeFact('Updated', runtime.updated_at ? UI.relativeTime(runtime.updated_at) : 'Not recorded'));
    facts.appendChild(_runtimeFact('Owning agent', runtime.agent_id || 'Not resolved'));
    if (runtime.ui_url || snapshot?.manifestAvailable) {
        facts.appendChild(_runtimeFact('App URL', appUrl, { link: true }));
    }
    if (manifest.api_base_path || String(manifest.runtime_kind || '') !== 'static') {
        facts.appendChild(_runtimeFact('API URL', apiUrl, { link: true }));
    }
    if (docsUrl) {
        facts.appendChild(_runtimeFact('API docs', docsUrl, { link: true }));
    }
    body.appendChild(facts);

    if (health) {
        const healthPanel = document.createElement('div');
        healthPanel.className = 'kit-details-panel artifact-runtime-section';
        const title = document.createElement('div');
        title.className = 'detail-label';
        title.textContent = 'Latest health check';
        healthPanel.appendChild(title);
        healthPanel.appendChild(_runtimeFact('Result', health.ok ? 'Healthy' : 'Not healthy'));
        healthPanel.appendChild(_runtimeFact('HTTP status', health.status_code || 'No response'));
        healthPanel.appendChild(_runtimeFact('Message', health.message || 'No health message'));
        body.appendChild(healthPanel);
    }

    if (['starting', 'running'].includes(status) && health && !health.ok) {
        const pending = document.createElement('p');
        pending.className = 'quiet-note';
        pending.textContent = 'The app process is running, but the health check has not passed yet. This panel will keep checking automatically.';
        body.appendChild(pending);
    }

    const events = Array.isArray(snapshot?.events) ? snapshot.events : [];
    const eventPanel = document.createElement('details');
    eventPanel.className = 'kit-stage-editor-section is-collapsible artifact-runtime-section';
    eventPanel.open = events.length > 0;
    const eventSummary = document.createElement('summary');
    eventSummary.className = 'kit-stage-editor-summary';
    eventSummary.textContent = `Runtime events (${events.length})`;
    eventPanel.appendChild(eventSummary);
    const eventList = document.createElement('div');
    eventList.className = 'task-artifact-list';
    UI.reconcileChildren(eventList, events.length
        ? events.map((event) => UI.renderListRow({
            label: _titleCaseWords(String(event.event_kind || 'event').replace(/_/g, ' ')),
            sublabel: [
                event.summary || '',
                event.created_at ? UI.relativeTime(event.created_at) : '',
            ].filter(Boolean).join(' · '),
            badgeText: event.actor_ref || '',
        }))
        : [UI.renderEmptyState('No runtime events have been recorded yet.', true)]);
    eventPanel.appendChild(eventList);
    body.appendChild(eventPanel);

    const logPanel = document.createElement('details');
    logPanel.className = 'kit-stage-editor-section is-collapsible artifact-runtime-section';
    logPanel.open = Boolean(logs?.log_tail);
    const logSummary = document.createElement('summary');
    logSummary.className = 'kit-stage-editor-summary';
    logSummary.textContent = 'Runtime logs';
    logPanel.appendChild(logSummary);
    const logPre = document.createElement('pre');
    logPre.className = 'event-pre artifact-runtime-log';
    logPre.textContent = String(logs?.log_tail || runtime.log_tail || 'Logs are not available for this runtime state.').trim();
    logPanel.appendChild(logPre);
    body.appendChild(logPanel);

    if (runtime.failure_detail) {
        const failure = document.createElement('p');
        failure.className = 'error-card';
        failure.textContent = runtime.failure_detail;
        body.appendChild(failure);
    }

    body.dataset.runtimeStatus = status;
    body.dataset.manifestAvailable = snapshot?.manifestAvailable ? 'true' : 'false';
    body.dataset.docsUrl = docsUrl;
    return body;
}

async function _openArtifactRuntimeDialog(runId, artifactKey, artifactLabel = '') {
    const body = document.createElement('div');
    body.appendChild(UI.renderEmptyState('Loading runtime status…', true));

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'btn';
    closeBtn.textContent = 'Close';
    const healthBtn = document.createElement('button');
    healthBtn.type = 'button';
    healthBtn.className = 'btn';
    healthBtn.textContent = 'Check health';
    const logsBtn = document.createElement('button');
    logsBtn.type = 'button';
    logsBtn.className = 'btn';
    logsBtn.textContent = 'Logs';
    const journeyBtn = document.createElement('button');
    journeyBtn.type = 'button';
    journeyBtn.className = 'btn';
    journeyBtn.textContent = 'Re-run journeys';
    const startBtn = document.createElement('button');
    startBtn.type = 'button';
    startBtn.className = 'btn btn-primary';
    startBtn.textContent = 'Start app';
    const stopBtn = document.createElement('button');
    stopBtn.type = 'button';
    stopBtn.className = 'btn';
    stopBtn.textContent = 'Stop app';
    const openBtn = document.createElement('a');
    openBtn.className = 'btn btn-primary';
    openBtn.textContent = 'Open app';
    openBtn.target = '_blank';
    openBtn.rel = 'noreferrer noopener';
    openBtn.href = API.protocolRunArtifactRuntimeAppUrl(runId, artifactKey);
    const archiveBtn = document.createElement('button');
    archiveBtn.type = 'button';
    archiveBtn.className = 'btn';
    archiveBtn.textContent = 'Archive';
    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'btn btn-danger';
    deleteBtn.textContent = 'Delete';
    for (const action of [startBtn, healthBtn, logsBtn, journeyBtn, stopBtn, archiveBtn, deleteBtn]) {
        action.hidden = true;
    }
    openBtn.hidden = true;

    const view = UI.showDialog(`Runtime: ${artifactLabel || artifactKey}`, body, {
        actions: [startBtn, openBtn, healthBtn, logsBtn, journeyBtn, stopBtn, archiveBtn, deleteBtn, closeBtn],
        maxWidth: '820px',
    });

    let latestSnapshot = null;
    let latestHealth = null;
    let latestLogs = null;
    let refreshInFlight = false;
    let autoPollTimer = null;

    const dialogOpen = () => document.body.contains(view.overlay);

    const runtimeNeedsPolling = () => {
        const status = String(latestSnapshot?.runtime?.status || '').toLowerCase();
        if (status === 'starting') return true;
        if (status === 'running' && (!latestHealth || latestHealth.ok !== true)) return true;
        return false;
    };

    const stopAutoPoll = () => {
        if (autoPollTimer) {
            window.clearInterval(autoPollTimer);
            autoPollTimer = null;
        }
    };

    const originalClose = view.close;
    view.close = () => {
        stopAutoPoll();
        originalClose();
    };
    closeBtn.addEventListener('click', () => view.close());

    const render = () => {
        const nextBody = _renderArtifactRuntimeDialogBody({
            runId,
            artifactKey,
            artifactLabel,
            snapshot: latestSnapshot || {},
            health: latestHealth,
            logs: latestLogs,
        });
        body.replaceChildren(...Array.from(nextBody.childNodes));
        body.dataset.runtimeStatus = nextBody.dataset.runtimeStatus || '';
        body.dataset.manifestAvailable = nextBody.dataset.manifestAvailable || '';
        body.dataset.docsUrl = nextBody.dataset.docsUrl || '';
        const status = body.dataset.runtimeStatus;
        const manifestAvailable = body.dataset.manifestAvailable === 'true';
        const ready = status === 'running' && latestHealth?.ok === true;
        startBtn.hidden = !manifestAvailable || ['running', 'starting', 'archived', 'deleted'].includes(status);
        openBtn.hidden = !ready;
        stopBtn.hidden = !['running', 'starting'].includes(status);
        healthBtn.hidden = !manifestAvailable || !['running', 'starting'].includes(status);
        logsBtn.hidden = !manifestAvailable;
        journeyBtn.hidden = !_contractJourneyKeysForArtifact(artifactKey).length || !['running', 'starting'].includes(status);
        archiveBtn.hidden = !manifestAvailable || status === 'running';
        deleteBtn.hidden = !manifestAvailable || status === 'running';
        if (!runtimeNeedsPolling()) stopAutoPoll();
    };

    const refresh = async ({ health = false, logs = false } = {}) => {
        if (refreshInFlight || !dialogOpen()) return;
        refreshInFlight = true;
        healthBtn.disabled = true;
        startBtn.disabled = true;
        try {
            latestSnapshot = await _artifactRuntimeSnapshot(runId, artifactKey);
            if (latestSnapshot?.health) {
                latestHealth = latestSnapshot.health;
            }
            const status = String(latestSnapshot?.runtime?.status || '').toLowerCase();
            const shouldCheckHealth = health || (status === 'running' && !latestHealth);
            if (shouldCheckHealth && latestSnapshot?.runtime) {
                latestHealth = await API.getProtocolRunArtifactRuntimeHealth(runId, artifactKey);
                latestSnapshot = await _artifactRuntimeSnapshot(runId, artifactKey);
            }
            if (logs && latestSnapshot?.runtime) {
                latestLogs = await API.getProtocolRunArtifactRuntimeLogs(runId, artifactKey);
            }
            render();
        } catch (err) {
            body.replaceChildren(UI.createErrorCard('Failed to load runtime status.', () => refresh()));
            UI.reportError('Failed to load runtime status', err, { context: 'Artifact runtime status failed' });
        } finally {
            refreshInFlight = false;
            healthBtn.disabled = false;
            startBtn.disabled = false;
        }
    };

    healthBtn.addEventListener('click', () => void refresh({ health: true }));
    logsBtn.addEventListener('click', () => void refresh({ logs: true }));
    journeyBtn.addEventListener('click', async () => {
        const journeys = _contractJourneyKeysForArtifact(artifactKey);
        if (!journeys.length) {
            UI.notify('This artifact has no declared runtime journeys.', 'warning');
            return;
        }
        journeyBtn.disabled = true;
        try {
            for (const journeyKey of journeys) {
                await API.runProtocolRunArtifactRuntimeJourney(runId, artifactKey, journeyKey);
            }
            UI.notify(`${journeys.length} journey${journeys.length === 1 ? '' : 'ies'} queued. Results will appear in runtime events.`, 'success');
            await refresh();
        } catch (err) {
            UI.reportError('Failed to queue runtime journey', err, { context: 'Artifact runtime journey failed' });
        } finally {
            journeyBtn.disabled = false;
        }
    });
    startBtn.addEventListener('click', async () => {
        startBtn.disabled = true;
        try {
            await API.startProtocolRunArtifactRuntime(runId, artifactKey);
            UI.notify('App is starting. Status updates automatically.', 'success');
            latestHealth = null;
            latestLogs = null;
            await refresh();
            startAutoPoll();
        } catch (err) {
            UI.reportError('Failed to start artifact runtime', err, { context: 'Artifact runtime start failed' });
        } finally {
            startBtn.disabled = false;
        }
    });
    stopBtn.addEventListener('click', async () => {
        stopBtn.disabled = true;
        try {
            await API.stopProtocolRunArtifactRuntime(runId, artifactKey);
            UI.notify('Runtime stopped.', 'success');
            await refresh();
        } catch (err) {
            UI.reportError('Failed to stop artifact runtime', err, { context: 'Artifact runtime stop failed' });
        } finally {
            stopBtn.disabled = false;
        }
    });
    archiveBtn.addEventListener('click', async () => {
        archiveBtn.disabled = true;
        try {
            await API.archiveProtocolRunArtifactRuntime(runId, artifactKey);
            UI.notify('Runtime archived.', 'success');
            await refresh();
        } catch (err) {
            UI.reportError('Failed to archive artifact runtime', err, { context: 'Artifact runtime archive failed' });
        } finally {
            archiveBtn.disabled = false;
        }
    });
    deleteBtn.addEventListener('click', async () => {
        const confirmed = window.confirm('Delete this runtime instance record? The artifact package remains available.');
        if (!confirmed) return;
        deleteBtn.disabled = true;
        try {
            await API.deleteProtocolRunArtifactRuntime(runId, artifactKey);
            UI.notify('Runtime deleted.', 'success');
            view.close();
        } catch (err) {
            UI.reportError('Failed to delete artifact runtime', err, { context: 'Artifact runtime delete failed' });
        } finally {
            deleteBtn.disabled = false;
        }
    });

    const startAutoPoll = () => {
        if (autoPollTimer || !dialogOpen()) return;
        autoPollTimer = window.setInterval(() => {
            if (!dialogOpen()) {
                stopAutoPoll();
                return;
            }
            if (!runtimeNeedsPolling()) {
                stopAutoPoll();
                return;
            }
            void refresh({ logs: Boolean(latestLogs?.log_tail) });
        }, 5000);
    };

    await refresh();
    startAutoPoll();
}

function _protocolArtifactActionRow(runId, artifact, definition = null, {
    missing = false,
    runtimeExpected = false,
    prominentRuntime = false,
} = {}) {
    const displayPath = _protocolArtifactDisplayPath(artifact) || _artifactDefinitionPath(definition || artifact);
    const available = !missing && artifact?.exists !== false;
    const browsable = available && UI.isLikelyDirectoryArtifactPath(displayPath);
    const showStorageOpen = !runtimeExpected;
    const actionRow = UI.createArtifactActionRow({
        previewable: showStorageOpen && available && _protocolArtifactPreviewable(artifact),
        previewHref: showStorageOpen && available && _protocolArtifactPreviewable(artifact)
            ? API.protocolRunArtifactContentUrl(runId, artifact.artifact_key, { preview: true })
            : '',
        previewTitle: `${artifact.artifact_key || 'artifact'} preview`,
        openHref: showStorageOpen && available ? API.protocolRunArtifactContentUrl(runId, artifact.artifact_key) : '',
        browseHref: browsable ? API.protocolRunArtifactContentUrl(runId, artifact.artifact_key, { browse: true }) : '',
        downloadHref: available ? API.protocolRunArtifactContentUrl(runId, artifact.artifact_key, { download: true }) : '',
        downloadLabel: runtimeExpected ? 'Download zip' : 'Download',
        copyPathText: prominentRuntime || runtimeExpected ? '' : displayPath,
        available,
        unavailableReason: missing ? 'Declared artifact, not produced yet.' : 'Artifact path is not available on this host.',
    });
    if (!missing && artifact?.artifact_key && !prominentRuntime && !runtimeExpected) {
        const snapshotBtn = document.createElement('button');
        snapshotBtn.type = 'button';
        snapshotBtn.className = 'btn btn-sm';
        snapshotBtn.textContent = 'Retain package';
        snapshotBtn.hidden = !available;
        const retainedLink = document.createElement('a');
        retainedLink.className = 'btn btn-sm';
        retainedLink.target = '_blank';
        retainedLink.rel = 'noreferrer noopener';
        retainedLink.textContent = 'Download retained';
        retainedLink.href = API.protocolRunArtifactSnapshotContentUrl(runId, artifact.artifact_key, { download: true });
        retainedLink.hidden = true;
        retainedLink.addEventListener('click', (event) => event.stopPropagation());
        const snapshotState = document.createElement('span');
        snapshotState.className = 'muted microcopy';
        snapshotState.textContent = '';
        const refreshSnapshotState = async () => {
            try {
                const snapshot = await API.getProtocolRunArtifactSnapshot(runId, artifact.artifact_key);
                const hasSnapshot = Boolean(snapshot?.snapshot && snapshot?.available !== false);
                retainedLink.hidden = !hasSnapshot;
                snapshotState.textContent = hasSnapshot ? 'retained' : (available ? '' : 'not retained');
            } catch (_err) {
                retainedLink.hidden = true;
                snapshotState.textContent = available ? '' : 'not retained';
            }
        };
        snapshotBtn.addEventListener('click', async (event) => {
            event.stopPropagation();
            snapshotBtn.disabled = true;
            snapshotBtn.textContent = 'Retaining...';
            try {
                await API.createProtocolRunArtifactSnapshot(runId, artifact.artifact_key);
                UI.notify('Artifact package retained.', 'success');
                await refreshSnapshotState();
            } catch (err) {
                UI.reportError('Failed to retain artifact package', err, { context: 'Artifact snapshot failed' });
            } finally {
                snapshotBtn.disabled = false;
                snapshotBtn.textContent = 'Retain package';
            }
        });
        actionRow.appendChild(snapshotBtn);
        actionRow.appendChild(retainedLink);
        actionRow.appendChild(snapshotState);
        void refreshSnapshotState();
    }
    const runtimeEligible = browsable || Boolean(runtimeExpected);
    if (runtimeEligible) {
        actionRow.classList.add('artifact-action-row-runtime');
        if (prominentRuntime) actionRow.classList.add('artifact-action-row-primary-runtime');
        const runtimeBtn = document.createElement('button');
        runtimeBtn.type = 'button';
        runtimeBtn.className = prominentRuntime ? 'btn btn-sm btn-primary is-primary-artifact-action' : 'btn btn-sm btn-primary';
        runtimeBtn.classList.add('artifact-app-primary-action');
        runtimeBtn.textContent = 'Start app';
        runtimeBtn.hidden = !runtimeExpected;
        const runtimeStatus = document.createElement('button');
        runtimeStatus.type = 'button';
        runtimeStatus.className = 'btn btn-sm';
        runtimeStatus.classList.add('artifact-app-detail-action');
        runtimeStatus.textContent = 'Manage app';
        runtimeStatus.hidden = !runtimeExpected;
        const stopRuntime = document.createElement('button');
        stopRuntime.type = 'button';
        stopRuntime.className = 'btn btn-sm';
        stopRuntime.classList.add('artifact-app-stop-action');
        stopRuntime.textContent = 'Stop app';
        stopRuntime.hidden = true;
        const openRuntime = document.createElement('a');
        openRuntime.href = API.protocolRunArtifactRuntimeAppUrl(runId, artifact.artifact_key);
        openRuntime.className = 'btn btn-sm';
        openRuntime.classList.add('artifact-app-primary-action');
        openRuntime.target = '_blank';
        openRuntime.rel = 'noreferrer noopener';
        openRuntime.textContent = 'Open app';
        openRuntime.hidden = true;
        openRuntime.addEventListener('click', (event) => event.stopPropagation());
        const runtimeHint = document.createElement('span');
        runtimeHint.className = 'artifact-runtime-inline-status muted microcopy';
        runtimeHint.hidden = !runtimeExpected;
        let currentRuntimeStatus = '';
        let currentRuntimeReady = false;
        let runtimePollTimer = null;
        let runtimePollInFlight = false;
        const stopRuntimePoll = () => {
            if (runtimePollTimer) {
                window.clearInterval(runtimePollTimer);
                runtimePollTimer = null;
            }
        };
        const scheduleRuntimePoll = () => {
            if (!['starting', 'running'].includes(currentRuntimeStatus)) {
                stopRuntimePoll();
                return;
            }
            if (currentRuntimeStatus === 'running' && currentRuntimeReady) {
                stopRuntimePoll();
                return;
            }
            if (runtimePollTimer) return;
            runtimePollTimer = window.setInterval(() => {
                if (!document.body.contains(actionRow)) {
                    stopRuntimePoll();
                    return;
                }
                void refreshRuntimeState();
            }, 5000);
        };
        const setRuntimeState = (runtime = {}, health = null) => {
            const status = String(runtime?.status || '').toLowerCase();
            currentRuntimeStatus = status;
            currentRuntimeReady = status === 'running' && health?.ok === true;
            const configured = status && status !== 'not_configured';
            runtimeStatus.hidden = !configured && !runtimeExpected;
            runtimeBtn.hidden = (!configured && !runtimeExpected) || (currentRuntimeReady || ['archived', 'deleted'].includes(status));
            runtimeBtn.disabled = ['starting', 'running'].includes(status) && !currentRuntimeReady;
            if (status === 'starting') {
                runtimeBtn.textContent = 'Starting...';
            } else if (status === 'running' && !currentRuntimeReady) {
                runtimeBtn.textContent = 'Checking app...';
            } else {
                runtimeBtn.textContent = status === 'failed' ? 'Restart app' : 'Start app';
            }
            runtimeHint.hidden = !runtimeExpected && !configured;
            if (currentRuntimeReady) {
                runtimeHint.textContent = 'Ready. Open the app to exercise the outcome.';
            } else if (status === 'starting') {
                runtimeHint.textContent = 'Starting. Health check pending; Manage app shows status and logs.';
            } else if (status === 'running') {
                runtimeHint.textContent = health?.message
                    ? `Health pending: ${String(health.message).slice(0, 140)}`
                    : 'Process is running; waiting for health to pass.';
            } else if (status === 'failed') {
                runtimeHint.textContent = runtime?.failure_detail
                    ? `Start failed: ${String(runtime.failure_detail).slice(0, 160)}`
                    : 'Start failed. Manage app shows the failure and logs.';
            } else if (status === 'stopped') {
                runtimeHint.textContent = runtimeExpected ? 'Stopped. Start the app to exercise this outcome.' : '';
            } else {
                runtimeHint.textContent = runtimeExpected ? 'Runtime declared. Start the app to exercise this outcome.' : '';
            }
            openRuntime.hidden = !currentRuntimeReady;
            openRuntime.className = prominentRuntime
                ? 'btn btn-sm btn-primary is-primary-artifact-action artifact-app-primary-action'
                : 'btn btn-sm btn-primary artifact-app-primary-action';
            stopRuntime.hidden = prominentRuntime || !['running', 'starting'].includes(status);
            scheduleRuntimePoll();
        };
        const runtimeActionErrorMessage = (err, fallback = 'Runtime action failed.') => {
            const payloadDetail = err?.payload?.detail && typeof err.payload.detail === 'object'
                ? err.payload.detail
                : {};
            const details = err?.details && typeof err.details === 'object' ? err.details : {};
            const blocker = Array.isArray(details.blockers)
                ? details.blockers.map((item) => String(item || '').trim()).find(Boolean)
                : '';
            const message = blocker || payloadDetail.message || err?.message || fallback;
            const needsRevise = err?.errorCode === 'PROTOCOL_ARTIFACT_RUNTIME_MANIFEST_NOT_RUN_READY'
                && !/revise/i.test(message);
            const expanded = needsRevise ? `${message}. Revise the artifact package first.` : message;
            return String(expanded || fallback).slice(0, 220);
        };
        const setRuntimeActionableFailure = (message) => {
            currentRuntimeReady = false;
            runtimeBtn.hidden = !runtimeExpected || ['archived', 'deleted'].includes(currentRuntimeStatus);
            runtimeBtn.disabled = false;
            runtimeBtn.textContent = currentRuntimeStatus === 'failed' ? 'Restart app' : 'Start app';
            runtimeStatus.hidden = !runtimeExpected;
            openRuntime.hidden = true;
            stopRuntime.hidden = true;
            runtimeHint.hidden = !runtimeExpected;
            runtimeHint.textContent = message || 'Runtime action failed. Try again or manage app.';
            stopRuntimePoll();
        };
        const refreshRuntimeState = async () => {
            if (runtimePollInFlight) return;
            runtimePollInFlight = true;
            try {
                const status = await API.getProtocolRunArtifactRuntime(runId, artifact.artifact_key);
                setRuntimeState(status?.runtime || {}, status?.health || null);
            } catch (err) {
                setRuntimeActionableFailure(
                    `Could not check current app status: ${runtimeActionErrorMessage(err, 'Try again or manage app.')}`,
                );
            } finally {
                runtimePollInFlight = false;
            }
        };
        runtimeBtn.addEventListener('click', async (event) => {
            event.stopPropagation();
            runtimeBtn.disabled = true;
            runtimeBtn.textContent = 'Starting...';
            try {
                const result = await API.startProtocolRunArtifactRuntime(runId, artifact.artifact_key);
                const runtime = result?.runtime || {};
                UI.notify(result?.message || 'App is starting. Open app appears when it is running.', result?.ok === false ? 'warning' : 'success');
                setRuntimeState(runtime);
            } catch (err) {
                UI.reportError('Failed to start artifact app', err, { context: 'Artifact runtime start failed' });
                setRuntimeActionableFailure(`Start failed: ${runtimeActionErrorMessage(err, 'Try again or manage app.')}`);
            }
        });
        actionRow.insertBefore(runtimeBtn, actionRow.firstChild);
        actionRow.insertBefore(openRuntime, runtimeBtn.nextSibling);
        runtimeStatus.addEventListener('click', (event) => {
            event.stopPropagation();
            void _openArtifactRuntimeDialog(
                runId,
                artifact.artifact_key,
                _protocolArtifactDisplayLabel(artifact, definition),
            );
        });
        actionRow.insertBefore(runtimeStatus, openRuntime.nextSibling);
        actionRow.insertBefore(runtimeHint, runtimeStatus.nextSibling);
        stopRuntime.addEventListener('click', async (event) => {
            event.stopPropagation();
            stopRuntime.disabled = true;
            stopRuntime.textContent = 'Stopping...';
            try {
                const result = await API.stopProtocolRunArtifactRuntime(runId, artifact.artifact_key);
                UI.notify(result?.message || 'Artifact runtime stopped.', result?.ok === false ? 'warning' : 'success');
                setRuntimeState(result?.runtime || { status: result?.status || 'stopped' });
            } catch (err) {
                UI.reportError('Failed to stop artifact app', err, { context: 'Artifact runtime stop failed' });
            } finally {
                stopRuntime.disabled = false;
                stopRuntime.textContent = 'Stop app';
            }
        });
        actionRow.insertBefore(stopRuntime, runtimeStatus.nextSibling);
        if (runtimeExpected) {
            runtimeBtn.textContent = 'Start app';
            runtimeBtn.disabled = false;
            runtimeHint.textContent = 'Runtime declared. Start the app to exercise this outcome.';
        }
        void refreshRuntimeState();
    }
    return actionRow;
}

function _artifactDefinitionPath(item) {
    return String(item?.path || item?.workspace_path || item?.location || '').trim();
}

function _artifactPurposeLabel(item) {
    const normalizedKind = String(item?.kind || 'workspace_file').trim().toLowerCase();
    const normalizedPath = _artifactDefinitionPath(item).toLowerCase();
    if (normalizedKind === 'control_plane_text') {
        return 'Notes or structured text carried with the run';
    }
    if (/\.(csv|tsv|xls|xlsx|json|jsonl|parquet)$/i.test(normalizedPath)) {
        return 'Dataset or structured data file';
    }
    if (/\.(py|js|mjs|cjs|ts|tsx|jsx|sh|sql|rb|go|java|rs|php)$/i.test(normalizedPath)) {
        return 'Code file or script';
    }
    if (/\.(pdf|md|txt|doc|docx|html)$/i.test(normalizedPath)) {
        return 'Document or report';
    }
    if (/(^|\/)(src|app|lib|scripts|reports|docs|data)\//i.test(normalizedPath)) {
        return 'Workspace file or folder';
    }
    return 'Workspace file or folder';
}

function _artifactUsage(doc, artifactKey) {
    const normalizedArtifactKey = String(artifactKey || '').trim();
    const reads = [];
    const writes = [];
    (doc?.stages || []).forEach((stage) => {
        const stageLabel = String(stage?.display_name || stage?.stage_key || 'Untitled step').trim();
        if ((stage?.inputs || []).includes(normalizedArtifactKey)) reads.push(stageLabel);
        if ((stage?.outputs || []).includes(normalizedArtifactKey)) writes.push(stageLabel);
    });
    return { reads, writes };
}

function _artifactUsageSummary(doc, artifactKey) {
    const usage = _artifactUsage(doc, artifactKey);
    const parts = [];
    if (usage.writes.length) parts.push(`${usage.writes.length} producer${usage.writes.length === 1 ? '' : 's'}`);
    if (usage.reads.length) parts.push(`${usage.reads.length} consumer${usage.reads.length === 1 ? '' : 's'}`);
    return parts.join(' · ');
}

function _artifactOptionLabel(item) {
    const label = String(item?.display_name || item?.artifact_key || 'Untitled artifact').trim();
    const pathLabel = _artifactDefinitionPath(item);
    if (pathLabel) return `${label} · ${pathLabel}`;
    if (String(item?.kind || '').trim().toLowerCase() === 'control_plane_text') {
        return `${label} · text carried with the run`;
    }
    return label;
}

function _protocolTransitionParticipantKey(transition, stageById) {
    const toStage = stageById.get(String(transition.to_stage_execution_id || ''));
    if (toStage && toStage.participant_key) {
        return String(toStage.participant_key || '');
    }
    const fromStage = stageById.get(String(transition.from_stage_execution_id || ''));
    return fromStage ? String(fromStage.participant_key || '') : '';
}

function _filteredProtocolTimelineData(currentRun, timelineParticipantFilter) {
    if (!currentRun) {
        return {
            stageRows: [],
            transitionRows: [],
            participantOptions: [],
        };
    }
    const stageById = new Map((currentRun.stage_executions || []).map((item) => [String(item.protocol_stage_execution_id || ''), item]));
    const participantOptions = Array.from(
        new Map((currentRun.participants || []).map((item) => [
            String(item.participant_key || ''),
            item.display_name || item.participant_key || '',
        ])).entries(),
    ).map(([value, label]) => ({ value, label }));
    const stageRows = (currentRun.stage_executions || []).filter((item) =>
        !timelineParticipantFilter || String(item.participant_key || '') === timelineParticipantFilter,
    );
    const transitionRows = (currentRun.transitions || []).filter((item) =>
        !timelineParticipantFilter || _protocolTransitionParticipantKey(item, stageById) === timelineParticipantFilter,
    );
    return { stageRows, transitionRows, participantOptions };
}

function _protocolIssueFilterValue(value) {
    const normalized = String(value || '').trim();
    if (!normalized) {
        return '';
    }
    if (normalized === 'all') {
        return 'all';
    }
    return PROTOCOL_ISSUE_FILTER_OPTIONS.some((item) => item.value === normalized) ? normalized : '';
}

function _protocolRunViewFilterValue(value) {
    const normalized = String(value || '').trim();
    if (!normalized) {
        return 'recent';
    }
    return PROTOCOL_RUN_VIEW_FILTER_OPTIONS.some((item) => item.value === normalized) ? normalized : 'recent';
}

function _protocolIssueApiValue(value) {
    return value === 'all' ? '' : String(value || '');
}

function _slugSuggestion(value) {
    return String(value || '')
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
}

const PROTOCOL_TERMINAL_TARGETS = [
    { key: '__complete__', label: 'Finish successfully' },
    { key: '__failed__', label: 'Finish as failed' },
    { key: '__cancelled__', label: 'Finish as cancelled' },
];

const PRIMARY_SELECTOR_KINDS = ['agent', 'skill'];

function _selectorString(selector) {
    if (!selector || !selector.kind || !selector.value) return '';
    const kind = String(selector.kind || '').trim();
    const value = String(selector.value || '').trim();
    if (!kind || !value) return '';
    return kind === 'agent' ? `@${value}` : `@${kind}:${value}`;
}

function _selectorFromFields(kind, value, preferredAgentId = '') {
    const selectorKind = String(kind || '').trim();
    const selectorValue = String(value || '').trim();
    if (!selectorKind || !selectorValue) return null;
    const selector = { kind: selectorKind, value: selectorValue };
    if (selectorKind === 'skill') {
        const preferred = String(preferredAgentId || '').trim();
        if (preferred) selector.preferred_agent_id = preferred;
    }
    return selector;
}

function _selectorModeFromKind(kind, fallback = 'skill') {
    const normalized = String(kind || '').trim().toLowerCase();
    if (normalized === 'unassigned') return 'unassigned';
    if (
        normalized === 'new_skill'
        || normalized === 'new-skill'
        || normalized === 'new_capability'
        || normalized === 'new-capability'
    ) return 'new_skill';
    if (normalized === 'agent' || normalized === 'skill') return normalized;
    if (normalized) return 'advanced';
    return String(fallback || 'skill');
}

function _protocolDecisionLabel(value) {
    const key = String(value || '').trim().toLowerCase();
    if (!key) return '';
    return Kit.dict.label(`protocol.stage.decision.${key}`, value);
}

function _transitionTargetLabel(targetKey, doc) {
    const key = String(targetKey || '').trim();
    if (!key) return '';
    const stage = (doc?.stages || []).find((item) => String(item.stage_key || '') === key);
    if (stage) {
        return String(stage.display_name || stage.stage_key || key);
    }
    const terminal = PROTOCOL_TERMINAL_TARGETS.find((item) => String(item.key || '') === key);
    return String(terminal?.label || key);
}

function _titleCaseWords(value) {
    return String(value || '')
        .trim()
        .split(/[\s_-]+/)
        .filter(Boolean)
        .map((item) => item.charAt(0).toUpperCase() + item.slice(1))
        .join(' ');
}

function _protocolEventKindLabel(value) {
    const normalized = String(value || '').trim().toLowerCase();
    const labels = {
        'protocol_run.updated': 'Run updated',
        'protocol_run.terminal': 'Run finished',
        'protocol.run.accept': 'Operator accepted',
        'protocol.run.send-back': 'Operator sent back',
        'protocol.run.send_back': 'Operator sent back',
        'protocol.run.cancel': 'Run cancelled',
        'protocol.run.retry': 'Run retried',
        'protocol.run.interrupt': 'Stage interrupted',
        operator_accept: 'Operator accepted',
        operator_send_back: 'Operator sent back',
        operator_cancel: 'Run cancelled',
        operator_retry: 'Run retried',
        operator_interrupt: 'Stage interrupted',
    };
    if (labels[normalized]) return labels[normalized];
    return _titleCaseWords(normalized.replace(/[._]+/g, ' ')) || 'Runtime event';
}

function _protocolEventText(event) {
    if (!event) return '';
    const kind = _protocolEventKindLabel(event.event_kind);
    const reason = String(event.reason || '').trim();
    const reasonLabel = reason && /^protocol[._]run[._-]/i.test(reason)
        ? _protocolEventKindLabel(reason)
        : reason;
    return [
        kind,
        reasonLabel && reasonLabel !== kind ? reasonLabel : '',
        event.created_at ? UI.relativeTime(event.created_at) : '',
    ].filter(Boolean).join(' · ');
}

/*
 * Protocol authoring workspace — one progressive workflow stage stack and one
 * optional map. The old overview/detail/topology split is gone.
 *
 * The primary surface is the stage stack; the selected stage expands inline.
 * The map is a secondary reference surface that can be shown on demand.
 * Roles own steps; assignment rules resolve steps to runtime agents. No raw
 * JSON tab, no viewport-specific editor fork, and no second authoring pipeline.
 */
function renderProtocolWorkspace(container) {
    const cleanups = UI.beginCleanupScope();
    const designSessionsRoute = window.location.pathname === '/ui/design-sessions';
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
    }

    let protocols = [];
    let authoringOptions = null;
    let protocolTemplates = [];
    let autoProtocolSessions = [];
    let autoProtocolSessionsLoading = false;
    let autoProtocolSessionsNextCursor = null;
    let autoProtocolStatusFilter = designSessionsRoute ? String(UI.readQueryParam('status', '') || '').trim() : '';
    let autoProtocolCursor = designSessionsRoute ? Math.max(0, Number.parseInt(UI.readQueryParam('cursor', '0'), 10) || 0) : 0;
    let selectedAutoProtocolSessionId = designSessionsRoute
        ? String(UI.readQueryParam('session_id', '') || _rememberedAutoProtocolSessionId()).trim()
        : '';
    let selectedAutoProtocolSession = null;
    let selectedAutoProtocolEvents = [];
    let autoProtocolDetailLoading = false;
    let autoProtocolQueueActionError = null;
    let autoProtocolQueueRetryAction = '';
    let autoProtocolQueueActionInFlight = '';
    let selectedAutoProtocolSubscription = null;
    let currentProtocolId = designSessionsRoute ? '' : UI.readQueryParam('protocol_id', '');
    let templateChooserMode = String(UI.readQueryParam('new', '') || '').trim().toLowerCase() === 'template' ? 'template' : '';
    let includeGeneratedCatalog = UI.readQueryParam('include_generated', '') === '1';
    let currentProtocol = null;
    let protocolDetailLoading = false;
    let draftRevision = 0;
    let connectedAgents = [];
    let availableAgents = [];
    let availableRoutingSkills = [];
    let availableCatalogSkills = [];
    let draftConflict = null;
    let renderInFlight = false;
    let renderQueued = false;
    let editorMode = { kind: 'idle', sourceStageKey: '', decision: '' };
    let editorSessionNonce = 0;
    let pendingStage = _blankStageDraft();
    let pendingRoute = _blankRouteDraft();
    let documentHistory = { undo: [], redo: [] };
    let canvasViewport = { zoom: 'fit' };
    let workflowMapMode = _workflowMapModeFromQuery();
    let stageAssignmentEditor = { stageKey: '', mode: '' };
    let collapsibleSectionState = {};
    let stageWorkspacePanelState = {};
    let pendingStageViewportAnchor = null;

    function _operatorSurfaceAvailable() {
        return Boolean(authoringOptions?.operator_surface_available);
    }

    function _currentAuthoringSurface() {
        const requested = String(UI.readQueryParam('authoring_surface', '') || '').trim().toLowerCase();
        if (requested === 'operator' && _operatorSurfaceAvailable()) return 'operator';
        return String(authoringOptions?.default_surface || 'standard').trim().toLowerCase() === 'operator'
            && _operatorSurfaceAvailable()
            ? 'operator'
            : 'standard';
    }

    function _selectionSourceStageKey(current = selection) {
        const sourceStageKey = String(current?.sourceStageKey || '').trim();
        return sourceStageKey;
    }

    function _workflowAnchorSelection(current = selection) {
        const sourceStageKey = _selectionSourceStageKey(current);
        if (sourceStageKey) {
            return { sectionKey: 'stages', nodeKey: sourceStageKey };
        }
        return { sectionKey: 'overview', nodeKey: '' };
    }

    function _focusedSecondarySurfaceKey(current = selection) {
        const key = String(current?.sectionKey || 'overview');
        if (key === 'map' || key === 'protocol') return key;
        if (key === 'artifacts' && String(current?.surfaceKey || 'secondary') !== 'local') return key;
        return '';
    }

    function _openArtifactCatalog(nodeKey = '', { stageKey = '', surfaceKey = 'secondary' } = {}) {
        const normalizedStageKey = String(stageKey || '').trim();
        if (normalizedStageKey && String(surfaceKey || 'secondary') === 'local') {
            _setStageWorkspacePanelValue(normalizedStageKey, 'artifacts');
            _queueStageViewportAnchor(normalizedStageKey, { panelKey: 'artifacts' });
        }
        selection = {
            sectionKey: 'artifacts',
            nodeKey: String(nodeKey || ''),
            sourceStageKey: normalizedStageKey,
            surfaceKey: String(surfaceKey || 'secondary') === 'local' ? 'local' : 'secondary',
        };
        render();
    }

    function _openProtocolSettings() {
        selection = {
            sectionKey: 'protocol',
            nodeKey: '',
            sourceStageKey: _activeStageKey(),
        };
        render();
    }

    function _openWorkflowMap() {
        selection = {
            sectionKey: 'map',
            nodeKey: '',
            sourceStageKey: _activeStageKey(),
        };
        _setWorkflowMapMode('visible', { rerender: false });
        render();
    }

    function _closeFocusedSurface(current = selection) {
        const nextSelection = _workflowAnchorSelection(current);
        if (String(current?.sectionKey || '') === 'map') {
            _setWorkflowMapMode('hidden', { rerender: false });
        }
        if (nextSelection.sectionKey === 'stages' && String(nextSelection.nodeKey || '').trim()) {
            _queueStageViewportAnchor(String(nextSelection.nodeKey || '').trim());
        }
        selection = nextSelection;
        render();
    }

    function _sectionStateValue(stateKey, fallback = false) {
        const normalizedKey = String(stateKey || '').trim();
        if (!normalizedKey) return Boolean(fallback);
        if (Object.prototype.hasOwnProperty.call(collapsibleSectionState, normalizedKey)) {
            return Boolean(collapsibleSectionState[normalizedKey]);
        }
        return Boolean(fallback);
    }

    function _setSectionStateValue(stateKey, isOpen) {
        const normalizedKey = String(stateKey || '').trim();
        if (!normalizedKey) return;
        collapsibleSectionState = {
            ...(collapsibleSectionState || {}),
            [normalizedKey]: Boolean(isOpen),
        };
    }

    function _captureCollapsibleSectionState(root = contentEl) {
        if (!(root instanceof Element)) return;
        root.querySelectorAll('details.kit-stage-editor-section.is-collapsible[data-section-state-key]').forEach((section) => {
            _setSectionStateValue(section.dataset.sectionStateKey || '', section.open);
        });
    }

    function _stageWorkspacePanelKeys({ includeRouting = true, includeAdvanced = false } = {}) {
        const panels = includeRouting
            ? ['basics', 'assignment', 'routing', 'instructions', 'artifacts']
            : ['basics', 'assignment', 'instructions', 'artifacts'];
        if (includeAdvanced) panels.push('advanced');
        return panels;
    }

    function _stageWorkspaceDefaultPanel(stageKey = '', { includeRouting = true, createAction = false } = {}) {
        const normalizedStageKey = String(stageKey || '').trim();
        if (normalizedStageKey && selection.sectionKey === 'artifacts' && _selectionSourceStageKey() === normalizedStageKey) {
            return 'artifacts';
        }
        if (normalizedStageKey && selection.sectionKey === 'transitions' && String(selection.nodeKey || '').startsWith(`${normalizedStageKey}::`)) {
            return 'routing';
        }
        return createAction ? 'basics' : 'assignment';
    }

    function _stageWorkspacePanelValue(workspaceKey = '', fallback = 'basics', { includeRouting = true, includeAdvanced = false } = {}) {
        const normalizedWorkspaceKey = String(workspaceKey || '').trim();
        const availablePanels = _stageWorkspacePanelKeys({ includeRouting, includeAdvanced });
        if (!normalizedWorkspaceKey) {
            return availablePanels.includes(String(fallback || '').trim()) ? String(fallback || '').trim() : availablePanels[0];
        }
        const currentValue = String(stageWorkspacePanelState?.[normalizedWorkspaceKey] || '').trim();
        if (availablePanels.includes(currentValue)) {
            return currentValue;
        }
        return availablePanels.includes(String(fallback || '').trim()) ? String(fallback || '').trim() : availablePanels[0];
    }

    function _setStageWorkspacePanelValue(workspaceKey = '', panelKey = '', { includeRouting = true, includeAdvanced = false } = {}) {
        const normalizedWorkspaceKey = String(workspaceKey || '').trim();
        const normalizedPanelKey = String(panelKey || '').trim();
        if (!normalizedWorkspaceKey || !_stageWorkspacePanelKeys({ includeRouting, includeAdvanced }).includes(normalizedPanelKey)) return;
        stageWorkspacePanelState = {
            ...(stageWorkspacePanelState || {}),
            [normalizedWorkspaceKey]: normalizedPanelKey,
        };
    }

    function _queueStageViewportAnchor(stageKey = '', { panelKey = '' } = {}) {
        const normalizedStageKey = String(stageKey || '').trim();
        if (!normalizedStageKey) return;
        pendingStageViewportAnchor = {
            stageKey: normalizedStageKey,
            panelKey: String(panelKey || '').trim(),
        };
    }

    function _applyPendingStageViewportAnchor(root = contentEl) {
        const pending = pendingStageViewportAnchor;
        if (!pending || !(root instanceof Element)) return;
        pendingStageViewportAnchor = null;
        const normalizedStageKey = String(pending.stageKey || '').trim();
        if (!normalizedStageKey) return;
        requestAnimationFrame(() => {
            const selector = `[data-stage-workspace-anchor="${normalizedStageKey}"]`;
            const anchor = root.querySelector(selector)
                || root.querySelector(`[data-stage-row="${normalizedStageKey}"]`);
            if (!(anchor instanceof Element)) return;
            anchor.scrollIntoView({ block: 'start', inline: 'nearest', behavior: 'auto' });
        });
    }

    // Single coherent draft snapshot. No mirrored raw-text; no parse_error.
    let draft = {
        slug: '',
        display_name: '',
        description: '',
        document: _blankDocument(),
    };

    // The canvas/details interaction works off one selection.
    let selection = _selectionFromQuery(_blankDocument());

    let saveState = { state: 'idle', lastSavedAt: '', error: '' };
    let autosaveTimer = 0;

    // Rehearsal state. Present only while a rehearsal run is active.
    let rehearsal = {
        runId: '',
        sessions: [],
        scenarios: [],
        runDetail: null,
        pollTimer: 0,
        refreshSeq: 0,
        drafts: {},
    };

    function _canvasZoomValue() {
        return canvasViewport.zoom === 'fit'
            ? 'fit'
            : Math.max(0.35, Math.min(2.25, Number(canvasViewport.zoom || 1) || 1));
    }

    function _defaultWorkflowMapVisible(current = selection) {
        return false;
    }

    function _workflowMapModeFromQuery() {
        const value = String(UI.readQueryParam('workflow_map', '') || '').trim().toLowerCase();
        if (value === 'visible' || value === 'hidden' || value === 'auto') return value;
        return 'auto';
    }

    function _workflowMapVisible(current = selection) {
        if (workflowMapMode === 'visible') return true;
        if (workflowMapMode === 'hidden') return false;
        return _defaultWorkflowMapVisible(current);
    }

    function _setWorkflowMapMode(mode, { rerender = true } = {}) {
        workflowMapMode = ['auto', 'visible', 'hidden'].includes(String(mode || ''))
            ? String(mode || '')
            : 'auto';
        _writeState();
        if (rerender) render();
    }

    function _setCanvasViewport(zoom, { renderNow = false } = {}) {
        canvasViewport = {
            zoom: zoom === 'fit'
                ? 'fit'
                : Math.max(0.35, Math.min(2.25, Number(zoom || 1) || 1)),
        };
        if (renderNow) render();
    }

    // Layout shell
    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Protocols</h2><p>Author reusable, versioned workflow definitions. Runs live under their own tab.</p>';
    container.appendChild(header);

    const shell = document.createElement('section');
    shell.className = 'admin-shell protocol-route-shell';
    container.appendChild(shell);

    const contentEl = document.createElement('div');
    contentEl.className = 'protocol-surface-shell protocol-authoring-shell';
    shell.appendChild(contentEl);

    function _blankDocument() {
        return {
            schema_version: 1,
            metadata: {},
            participants: [],
            artifacts: [],
            stages: [],
            // policies intentionally omitted — server defaults apply until the
            // user edits them explicitly via the details panel.
        };
    }

    function _blankStageDraft(participantKey = '', seed = {}) {
        return {
            display_name: '',
            stage_key: '',
            participant_key: String(participantKey || ''),
            selector_mode: 'unassigned',
            selector_kind: '',
            selector_value: '',
            selector_preferred_agent_id: '',
            role_display_name: '',
            role_participant_key: '',
            role_instructions: '',
            stage_kind: 'work',
            instructions: '',
            inputs: [],
            outputs: [],
            max_rounds: 0,
            timeout_seconds: 0,
            ...seed,
        };
    }

    function _blankRouteDraft(stageKey = '', stageKind = 'work', seed = {}) {
        return {
            source_stage_key: String(stageKey || ''),
            decision: _defaultDecisionForStageKind(stageKind),
            target_key: '',
            ...seed,
        };
    }

    function _baseEditorModeKind() {
        return rehearsal.runId ? 'rehearse' : 'idle';
    }

    function _setEditorMode(next) {
        editorMode = {
            kind: _baseEditorModeKind(),
            sourceStageKey: '',
            decision: '',
            ...(next || {}),
        };
        render();
    }

    function _resetEditorMode() {
        editorMode = { kind: _baseEditorModeKind(), sourceStageKey: '', decision: '' };
        pendingStage = _blankStageDraft();
        pendingRoute = _blankRouteDraft();
    }

    function _defaultDecisionForStageKind(stageKind) {
        return String(stageKind || '') === 'work' ? 'completed' : 'accept';
    }

    function _decisionOptionsForStage(stage, currentDecision = '') {
        const stageKind = String(stage?.stage_kind || 'work');
        const defaults = stageKind === 'work'
            ? ['completed']
            : stageKind === 'acceptance'
                ? ['accept', 'fail']
                : ['accept', 'revise', 'fail'];
        const current = String(currentDecision || '').trim().toLowerCase();
        const values = Array.from(new Set([
            ...defaults,
            ...Object.keys(stage?.transitions || {}).map((item) => String(item || '').trim().toLowerCase()).filter(Boolean),
            current,
        ].filter(Boolean)));
        return values.map((value) => ({
            value,
            label: _protocolDecisionLabel(value),
        }));
    }

    function _selectionStage(doc = draft.document) {
        if (selection.sectionKey !== 'stages' || !selection.nodeKey) return null;
        return (doc.stages || []).find((item) => String(item.stage_key || '') === String(selection.nodeKey || '')) || null;
    }

    function _selectionTransition(doc = draft.document) {
        if (selection.sectionKey !== 'transitions' || !selection.nodeKey) return null;
        return _transitionEntries(doc).find((item) => String(item.id || '') === String(selection.nodeKey || '')) || null;
    }

    function _segmentPrimaryStageKey(segment) {
        return String(segment?.primaryStageKey || segment?.stageKeys?.[0] || '');
    }

    function _segmentHasHiddenPrimaryStage(segment) {
        return Boolean(segment?.stages?.length > 1 && _segmentPrimaryStageKey(segment));
    }

    function _segmentStageList(segment) {
        const primaryStageKey = _segmentPrimaryStageKey(segment);
        const stages = Array.isArray(segment?.stages) ? segment.stages : [];
        if (!_segmentHasHiddenPrimaryStage(segment)) {
            return stages;
        }
        return stages.filter((stage) => String(stage?.stage_key || '') !== primaryStageKey);
    }

    function _normalizeSelectionForProjection(current, projection) {
        const key = String(current?.sectionKey || 'overview');
        if (key !== 'segments') return current;
        const segment = projection?.segmentsById?.get(String(current?.nodeKey || ''));
        if (!segment) return current;
        const primaryStageKey = _segmentPrimaryStageKey(segment);
        if (primaryStageKey) {
            return { sectionKey: 'stages', nodeKey: primaryStageKey };
        }
        return current;
    }

    function _defaultStageInsertAnchor(stage, projection) {
        const sourceStageKey = String(stage?.stage_key || '');
        const transitions = Object.entries(stage?.transitions || {})
            .map(([decision, target]) => ({
                decision: String(decision || '').trim().toLowerCase(),
                target: String(target || '').trim(),
            }))
            .filter((item) => item.decision && item.target);
        const stageOrder = new Map((draft.document.stages || []).map((item, index) => [String(item.stage_key || ''), index]));
        const sourceIndex = Number(stageOrder.get(sourceStageKey) || 0);
        const sourceSegmentId = String(projection?.stageToSegment?.get(sourceStageKey) || '');
        const sourceColumn = Number(projection?.segmentsById?.get(sourceSegmentId)?.column || 0);
        const forward = transitions.filter((item) => {
            if (PROTOCOL_TERMINAL_TARGETS.some((terminal) => terminal.key === item.target)) return false;
            const targetSegmentId = String(projection?.stageToSegment?.get(item.target) || '');
            const targetColumn = Number(projection?.segmentsById?.get(targetSegmentId)?.column || sourceColumn);
            if (targetColumn > sourceColumn) return true;
            if (targetColumn < sourceColumn) return false;
            return Number(stageOrder.get(item.target) || -1) > sourceIndex;
        });
        const nonTerminal = transitions.filter((item) => !PROTOCOL_TERMINAL_TARGETS.some((terminal) => terminal.key === item.target));
        const anchor = forward.length === 1
            ? forward[0]
            : nonTerminal.length === 1
                ? nonTerminal[0]
                : transitions.length === 1
                    ? transitions[0]
                    : null;
        if (!anchor) return null;
        return {
            sourceStageKey: String(stage?.stage_key || ''),
            decision: String(anchor.decision || ''),
        };
    }

    function _insertAnchorForStage(stage, projection) {
        const anchor = _defaultStageInsertAnchor(stage, projection);
        if (anchor) return anchor;
        return {
            sourceStageKey: String(stage?.stage_key || ''),
            decision: _defaultDecisionForStageKind(stage?.stage_kind || 'work'),
        };
    }

    function _appendStageInsertAnchor(projection) {
        const stages = Array.isArray(draft.document?.stages) ? draft.document.stages : [];
        if (!stages.length) return null;
        const segments = Array.isArray(projection?.segments) ? projection.segments : [];
        const lastSegment = segments.length ? segments[segments.length - 1] : null;
        const lastStageKey = String(lastSegment?.endStageKey || stages[stages.length - 1]?.stage_key || '');
        const lastStage = stages.find((item) => String(item?.stage_key || '') === lastStageKey)
            || stages[stages.length - 1]
            || null;
        return lastStage ? _insertAnchorForStage(lastStage, projection) : null;
    }

    function _defaultStageParticipantKey(doc = draft.document) {
        if (selection.sectionKey === 'participants' && selection.nodeKey) {
            return String(selection.nodeKey || '');
        }
        const selectedStage = _selectionStage(doc);
        if (selectedStage?.participant_key) {
            return String(selectedStage.participant_key || '');
        }
        return String(doc.participants?.[0]?.participant_key || '');
    }

    function _stageLaneRow(participantKey, doc = draft.document) {
        const laneIndex = (doc.participants || []).findIndex((item) => String(item.participant_key || '') === String(participantKey || ''));
        return laneIndex >= 0 ? laneIndex : 0;
    }

    function _cloneDoc(doc) {
        return JSON.parse(JSON.stringify(doc || _blankDocument()));
    }

    function _normalizeStageWriteAccess(stage) {
        const outputs = Array.isArray(stage?.outputs) ? stage.outputs.filter(Boolean) : [];
        return {
            ...stage,
            write_capable: Boolean(stage?.write_capable || outputs.length),
        };
    }

    function _assignmentParticipantKey(selector) {
        const kind = String(selector?.kind || '').trim().toLowerCase();
        const value = String(selector?.value || '').trim();
        if (!kind || !value || !PRIMARY_SELECTOR_KINDS.includes(kind)) return '';
        return _slugSuggestion(`${kind}-${value}`) || '';
    }

    function _assignmentParticipantLabel(selector) {
        const kind = String(selector?.kind || '').trim().toLowerCase();
        const value = String(selector?.value || '').trim();
        if (!kind || !value) return '';
        if (kind === 'agent') {
            const agent = _selectorAgentRecord(value);
            return UI.visibleLabel(agent?.display_name, agent?.slug || value, value);
        }
        if (kind === 'skill') {
            return `${_titleCaseWords(value)} skill`;
        }
        return _titleCaseWords(value);
    }

    function _ensureStageAssignmentParticipants(doc) {
        const normalized = _cloneDoc(doc || _blankDocument());
        const participants = Array.isArray(normalized.participants) ? [...normalized.participants] : [];
        const participantKeys = new Set(
            participants.map((item) => String(item?.participant_key || '').trim()).filter(Boolean),
        );
        normalized.stages = (Array.isArray(normalized.stages) ? normalized.stages : [])
            .map((stage) => {
                const nextStage = _normalizeStageWriteAccess(stage);
                if (String(nextStage.participant_key || '').trim()) return nextStage;
                const participantKey = _assignmentParticipantKey(nextStage.selector);
                if (!participantKey) return nextStage;
                if (!participantKeys.has(participantKey)) {
                    participants.push({
                        participant_key: participantKey,
                        display_name: _assignmentParticipantLabel(nextStage.selector) || participantKey,
                        instructions: '',
                    });
                    participantKeys.add(participantKey);
                }
                return {
                    ...nextStage,
                    participant_key: participantKey,
                };
            });
        normalized.participants = participants;
        return normalized;
    }

    function _docFromDraft() {
        const doc = _ensureStageAssignmentParticipants(draft.document);
        doc.schema_version = Number(doc.schema_version || 1) || 1;
        doc.metadata = Object.assign({}, doc.metadata || {}, {
            slug: String(draft.slug || '').trim(),
            display_name: String(draft.display_name || '').trim(),
            description: String(draft.description || '').trim(),
        });
        doc.participants = Array.isArray(doc.participants) ? doc.participants : [];
        doc.artifacts = Array.isArray(doc.artifacts) ? doc.artifacts : [];
        doc.stages = Array.isArray(doc.stages) ? doc.stages.map((stage) => _normalizeStageWriteAccess(stage)) : [];
        return doc;
    }

    function _workflowProgress(doc = draft.document) {
        const normalized = doc || _blankDocument();
        const participantCount = Array.isArray(normalized.participants) ? normalized.participants.length : 0;
        const artifactCount = Array.isArray(normalized.artifacts) ? normalized.artifacts.length : 0;
        const stageCount = Array.isArray(normalized.stages) ? normalized.stages.length : 0;
        const edgeCount = _transitionEntries(normalized).length;
        let nextStep = '';
        if (!stageCount) nextStep = 'stage';
        else if (!edgeCount) nextStep = 'transition';
        else if (!artifactCount) nextStep = 'artifact';
        return { participantCount, artifactCount, stageCount, edgeCount, nextStep };
    }

    function _participantDisplayName(participantKey, doc = draft.document) {
        const participant = (doc.participants || []).find((item) => String(item.participant_key || '') === String(participantKey || ''));
        return String(participant?.display_name || participant?.participant_key || participantKey || '').trim();
    }

    function _participantRecord(participantKey, doc = draft.document) {
        return (doc.participants || []).find((item) => String(item.participant_key || '') === String(participantKey || '')) || null;
    }

    function _selectorSummary(selector, { empty = 'Unassigned', prefix = '' } = {}) {
        if (!selector || !selector.kind || !selector.value) {
            return prefix ? `${prefix}${empty}` : empty;
        }
        const kind = String(selector.kind || '').trim().toLowerCase();
        const value = String(selector.value || '').trim();
        const valueLabel = kind === 'skill' || kind === 'role' ? _titleCaseWords(value) : value;
        const preferredAgent = kind === 'skill'
            ? _selectorAgentRecord(selector.preferred_agent_id || '')
            : null;
        const preferredLabel = preferredAgent
            ? String(preferredAgent.display_name || preferredAgent.slug || selector.preferred_agent_id || '').trim()
            : '';
        const label = preferredLabel
            ? `${_selectorKindLabel(kind)} · ${valueLabel} · prefer ${preferredLabel}`
            : `${_selectorKindLabel(kind)} · ${valueLabel}`;
        return prefix ? `${prefix}${label}` : label;
    }

    function _stageAssignmentSummary(stage, options = {}) {
        return _selectorSummary(stage?.selector || null, options);
    }

    function _workflowDensityProfile(projection) {
        const topology = projection?.topology || {};
        const stages = Array.isArray(topology?.stages) ? topology.stages : [];
        const stageCount = stages.length;
        const branchStageCount = stages.filter((stage) => {
            const stageKey = String(stage?.stage_key || '');
            if (!stageKey) return false;
            return ((topology.outgoingStage?.get(stageKey) || []).length + (topology.outgoingTerminal?.get(stageKey) || []).length) > 1;
        }).length;
        const nonWorkStageCount = stages.filter((stage) => String(stage?.stage_kind || 'work') !== 'work').length;
        const compactViewport = _isCompactViewport();
        let band = 'comfortable';
        if (compactViewport || stageCount >= 8 || branchStageCount >= 2 || (stageCount >= 6 && branchStageCount >= 1)) {
            band = 'dense';
        } else if (stageCount >= 5 || branchStageCount >= 1 || nonWorkStageCount >= 2) {
            band = 'balanced';
        }
        return {
            band,
            compactViewport,
            stageCount,
            branchStageCount,
            nonWorkStageCount,
            compactCopy: band !== 'comfortable',
            showSegmentSubtitle: band === 'comfortable',
            showNonSelectedMeta: band !== 'dense',
            showSelectedMeta: true,
        };
    }

    function _stageRowSummary(stage, doc, density, { selected = false } = {}) {
        const roleLabel = _participantDisplayName(stage?.participant_key, doc) || '';
        const assignmentLabel = _stageAssignmentSummary(stage, { empty: '' });
        const labels = [];
        if (density?.band === 'comfortable') {
            labels.push(roleLabel || 'Unassigned');
            if (assignmentLabel && assignmentLabel !== roleLabel) labels.push(assignmentLabel);
        } else {
            labels.push(assignmentLabel || roleLabel || 'Unassigned');
        }
        const normalized = labels
            .map((item) => String(item || '').trim())
            .filter((item, index, items) => item && items.indexOf(item) === index);
        if (!normalized.length) return '';
        if (!selected && density && !density.showNonSelectedMeta) return '';
        return normalized.join(' · ');
    }

    function _segmentParticipantSummary(participantLabels) {
        const labels = Array.isArray(participantLabels)
            ? participantLabels.map((item) => String(item || '').trim()).filter(Boolean)
            : [];
        if (!labels.length) return 'Unassigned role';
        if (labels.length === 1) return labels[0];
        if (labels.length === 2) return `${labels[0]} + ${labels[1]}`;
        return `${labels[0]} + ${labels.length - 1} more roles`;
    }

    function _segmentId(stageKey) {
        return `segment:${String(stageKey || '').trim()}`;
    }

    function _sortedGraphKeys(keys, documentIndex) {
        return [...keys].sort((left, right) =>
            Number(documentIndex.get(String(left || '')) || 0) - Number(documentIndex.get(String(right || '')) || 0));
    }

    function _stageTopology(doc = draft.document) {
        const stages = Array.isArray(doc?.stages) ? doc.stages : [];
        const stageByKey = new Map(stages.map((item) => [String(item.stage_key || ''), item]));
        const documentIndex = new Map(stages.map((item, index) => [String(item.stage_key || ''), index]));
        const outgoingStage = new Map();
        const incomingStage = new Map();
        const outgoingTerminal = new Map();
        stages.forEach((item) => {
            const key = String(item.stage_key || '');
            outgoingStage.set(key, []);
            incomingStage.set(key, []);
            outgoingTerminal.set(key, []);
        });
        stages.forEach((stage) => {
            const sourceKey = String(stage.stage_key || '');
            Object.entries(stage.transitions || {}).forEach(([decision, target]) => {
                const decisionKey = String(decision || '').trim().toLowerCase();
                const targetKey = String(target || '').trim();
                if (!decisionKey || !targetKey) return;
                const edge = {
                    id: _stageTransitionId(sourceKey, decisionKey),
                    from: sourceKey,
                    to: targetKey,
                    decision: decisionKey,
                };
                if (stageByKey.has(targetKey)) {
                    outgoingStage.get(sourceKey)?.push(edge);
                    incomingStage.get(targetKey)?.push(edge);
                } else if (PROTOCOL_TERMINAL_TARGETS.some((item) => item.key === targetKey)) {
                    outgoingTerminal.get(sourceKey)?.push(edge);
                }
            });
        });
        const orderedStageKeys = _sortedGraphKeys(stageByKey.keys(), documentIndex);
        const visitState = new Map();
        const backEdgeIds = new Set();
        function walk(stageKey) {
            visitState.set(stageKey, 'visiting');
            const outgoing = _sortedGraphKeys(
                (outgoingStage.get(stageKey) || []).map((edge) => String(edge.to || '')),
                documentIndex,
            ).map((targetKey) => (outgoingStage.get(stageKey) || []).find((edge) => String(edge.to || '') === targetKey)).filter(Boolean);
            outgoing.forEach((edge) => {
                const targetKey = String(edge.to || '');
                const state = visitState.get(targetKey);
                if (state === 'visiting') {
                    backEdgeIds.add(String(edge.id || ''));
                    return;
                }
                if (state === 'done') return;
                if (!stageByKey.has(targetKey)) return;
                walk(targetKey);
            });
            visitState.set(stageKey, 'done');
        }
        orderedStageKeys.forEach((stageKey) => {
            if (!visitState.has(stageKey)) walk(stageKey);
        });

        const forwardOutgoingStage = new Map(stages.map((item) => [String(item.stage_key || ''), []]));
        const forwardIncomingStage = new Map(stages.map((item) => [String(item.stage_key || ''), []]));
        stages.forEach((stage) => {
            const sourceKey = String(stage.stage_key || '');
            (outgoingStage.get(sourceKey) || []).forEach((edge) => {
                if (backEdgeIds.has(String(edge.id || ''))) return;
                forwardOutgoingStage.get(sourceKey)?.push(edge);
                forwardIncomingStage.get(String(edge.to || ''))?.push(edge);
            });
        });

        const rank = new Map(orderedStageKeys.map((stageKey) => [stageKey, 0]));
        const indegree = new Map(orderedStageKeys.map((stageKey) => [stageKey, Number((forwardIncomingStage.get(stageKey) || []).length)]));
        const queue = orderedStageKeys.filter((stageKey) => Number(indegree.get(stageKey) || 0) === 0);
        while (queue.length) {
            const stageKey = queue.shift();
            const sourceRank = Number(rank.get(stageKey) || 0);
            const outgoing = _sortedGraphKeys(
                (forwardOutgoingStage.get(stageKey) || []).map((edge) => String(edge.to || '')),
                documentIndex,
            ).map((targetKey) => (forwardOutgoingStage.get(stageKey) || []).find((edge) => String(edge.to || '') === targetKey)).filter(Boolean);
            outgoing.forEach((edge) => {
                const targetKey = String(edge.to || '');
                rank.set(targetKey, Math.max(Number(rank.get(targetKey) || 0), sourceRank + 1));
                indegree.set(targetKey, Math.max(0, Number(indegree.get(targetKey) || 0) - 1));
                if (Number(indegree.get(targetKey) || 0) === 0 && !queue.includes(targetKey)) {
                    queue.push(targetKey);
                    queue.sort((left, right) =>
                        Number(documentIndex.get(String(left || '')) || 0) - Number(documentIndex.get(String(right || '')) || 0));
                }
            });
        }
        return {
            stages,
            stageByKey,
            documentIndex,
            outgoingStage,
            incomingStage,
            outgoingTerminal,
            forwardOutgoingStage,
            forwardIncomingStage,
            backEdgeIds,
            rank,
        };
    }

    function _singleForwardStageTarget(stage, topology) {
        const sourceKey = String(stage?.stage_key || '');
        if (!sourceKey) return '';
        const targets = (topology.forwardOutgoingStage.get(sourceKey) || [])
            .map((edge) => String(edge.to || '').trim())
            .filter((targetKey, index, items) =>
                targetKey
                && items.indexOf(targetKey) === index);
        return targets.length === 1 ? targets[0] : '';
    }

    function _canAbsorbLinearSuccessor(currentStage, nextStage, topology) {
        if (!currentStage || !nextStage) return false;
        if (String(currentStage.stage_kind || 'work') !== 'work') return false;
        if ((topology.outgoingTerminal.get(String(currentStage.stage_key || '')) || []).length) return false;
        if (_singleForwardStageTarget(currentStage, topology) !== String(nextStage.stage_key || '')) return false;
        const incoming = topology.forwardIncomingStage.get(String(nextStage.stage_key || '')) || [];
        if (incoming.length !== 1 || String(incoming[0]?.from || '') !== String(currentStage.stage_key || '')) return false;
        return (
            String(currentStage.participant_key || '') === String(nextStage.participant_key || '')
            && String(nextStage.stage_kind || 'work') === 'work'
        );
    }

    function _canAbsorbReviewGate(currentStage, nextStage, chainStageKeys, topology) {
        if (!currentStage || !nextStage) return false;
        if (String(currentStage.stage_kind || 'work') !== 'work') return false;
        if (String(nextStage.stage_kind || 'work') === 'work') return false;
        if ((topology.outgoingTerminal.get(String(currentStage.stage_key || '')) || []).length) return false;
        if (_singleForwardStageTarget(currentStage, topology) !== String(nextStage.stage_key || '')) return false;
        const incoming = topology.forwardIncomingStage.get(String(nextStage.stage_key || '')) || [];
        if (incoming.length !== 1 || String(incoming[0]?.from || '') !== String(currentStage.stage_key || '')) return false;
        const chainKeys = new Set(chainStageKeys.map((item) => String(item || '').trim()).filter(Boolean));
        const stageEdges = topology.forwardOutgoingStage.get(String(nextStage.stage_key || '')) || [];
        const externalTargets = Array.from(new Set(stageEdges
            .map((edge) => String(edge.to || '').trim())
            .filter((targetKey) => targetKey && !chainKeys.has(targetKey))));
        if (externalTargets.length > 1) return false;
        return stageEdges.every((edge) => {
            const targetKey = String(edge.to || '').trim();
            if (!targetKey) return false;
            if (chainKeys.has(targetKey)) return true;
            return Number(topology.rank.get(targetKey) || 0) >= Number(topology.rank.get(String(nextStage.stage_key || '')) || 0);
        });
    }

    function _segmentRows(segmentsById, segmentOrder) {
        const usedByColumn = new Map();
        segmentOrder.forEach((segmentId) => {
            const segment = segmentsById.get(segmentId);
            if (!segment) return;
            const column = Number(segment.column || 0);
            const used = usedByColumn.get(column) || new Set();
            let preferred = -1;
            if (segment.incomingSegments.length === 1) {
                preferred = Number(segmentsById.get(segment.incomingSegments[0])?.row ?? -1);
            }
            let row = preferred >= 0 && !used.has(preferred) ? preferred : 0;
            while (used.has(row)) row += 1;
            segment.row = row;
            used.add(row);
            usedByColumn.set(column, used);
        });
    }

    function _buildWorkflowProjection(doc = draft.document) {
        const topology = _stageTopology(doc);
        const assigned = new Set();
        const segments = [];
        const stageToSegment = new Map();

        topology.stages.forEach((stage) => {
            const stageKey = String(stage.stage_key || '');
            if (!stageKey || assigned.has(stageKey)) return;
            const stageKeys = [stageKey];
            assigned.add(stageKey);
            let currentStage = stage;

            while (true) {
                const nextKey = _singleForwardStageTarget(currentStage, topology);
                const nextStage = nextKey ? topology.stageByKey.get(nextKey) : null;
                if (!nextStage || assigned.has(nextKey)) break;
                if (_canAbsorbLinearSuccessor(currentStage, nextStage, topology)) {
                    stageKeys.push(nextKey);
                    assigned.add(nextKey);
                    currentStage = nextStage;
                    continue;
                }
                if (_canAbsorbReviewGate(currentStage, nextStage, stageKeys, topology)) {
                    stageKeys.push(nextKey);
                    assigned.add(nextKey);
                }
                break;
            }

            const segmentStages = stageKeys
                .map((key) => topology.stageByKey.get(key))
                .filter(Boolean);
            const participantKeys = Array.from(new Set(segmentStages.map((item) => String(item.participant_key || '')).filter(Boolean)));
            const participantLabels = participantKeys.map((key) => _participantDisplayName(key, doc));
            const primaryStage = segmentStages.find((item) => String(item.stage_kind || 'work') === 'work') || segmentStages[0] || stage;
            const stepSummary = `${stageKeys.length} step${stageKeys.length === 1 ? '' : 's'}`;
            const participantSummary = _segmentParticipantSummary(participantLabels);
            const segment = {
                id: _segmentId(stageKeys[0]),
                startStageKey: stageKeys[0],
                endStageKey: stageKeys[stageKeys.length - 1],
                stageKeys,
                stages: segmentStages,
                primaryStageKey: String(primaryStage?.stage_key || segmentStages[0]?.stage_key || stageKeys[0] || ''),
                participantKeys,
                primaryParticipantKey: String(primaryStage?.participant_key || segmentStages[0]?.participant_key || ''),
                label: String(primaryStage?.display_name || primaryStage?.stage_key || stageKeys[0] || 'Step'),
                sublabel: participantSummary,
                stepSummary,
                participantSummary,
                badges: [
                    {
                        tone: 'phase',
                        label: stepSummary,
                    },
                ],
                outgoingEdges: [],
                incomingSegments: [],
                column: 0,
                row: 0,
            };
            segments.push(segment);
            stageKeys.forEach((key) => stageToSegment.set(key, segment.id));
        });

        const segmentsById = new Map(segments.map((segment) => [segment.id, segment]));
        segments.forEach((segment) => {
            const grouped = new Map();
            segment.stageKeys.forEach((stageKey) => {
                (topology.outgoingStage.get(stageKey) || []).forEach((edge) => {
                    const targetSegmentId = stageToSegment.get(String(edge.to || ''));
                    if (!targetSegmentId || targetSegmentId === segment.id) return;
                    const groupKey = `segment:${targetSegmentId}`;
                    const current = grouped.get(groupKey) || {
                        id: `${segment.id}::${targetSegmentId}`,
                        from: segment.id,
                        to: targetSegmentId,
                        labels: [],
                        targetKind: 'segment',
                        targetKey: targetSegmentId,
                    };
                    current.labels.push(_protocolDecisionLabel(edge.decision));
                    grouped.set(groupKey, current);
                });
                (topology.outgoingTerminal.get(stageKey) || []).forEach((edge) => {
                    const groupKey = `terminal:${edge.to}`;
                    const current = grouped.get(groupKey) || {
                        id: `${segment.id}::${String(edge.to || '')}`,
                        from: segment.id,
                        to: String(edge.to || ''),
                        labels: [],
                        targetKind: 'terminal',
                        targetKey: String(edge.to || ''),
                    };
                    current.labels.push(_protocolDecisionLabel(edge.decision));
                    grouped.set(groupKey, current);
                });
            });
            segment.outgoingEdges = Array.from(grouped.values()).map((edge) => ({
                ...edge,
                label: Array.from(new Set(edge.labels)).join(' / '),
            }));
        });

        segments.forEach((segment) => {
            segment.outgoingEdges
                .filter((edge) => edge.targetKind === 'segment')
                .forEach((edge) => {
                    const target = segmentsById.get(edge.targetKey);
                    if (!target) return;
                    target.incomingSegments.push(segment.id);
                });
        });

        segments.forEach((segment) => {
            segment.column = Number(topology.rank.get(segment.startStageKey) || 0);
        });
        const minColumn = Math.min(...segments.map((segment) => Number(segment.column || 0)), 0);
        segments.forEach((segment) => {
            segment.column = Math.max(0, Number(segment.column || 0) - minColumn);
        });
        const segmentOrder = segments
            .slice()
            .sort((a, b) =>
                Number(topology.rank.get(a.startStageKey) || 0) - Number(topology.rank.get(b.startStageKey) || 0)
                || Number(topology.documentIndex.get(a.startStageKey) || 0) - Number(topology.documentIndex.get(b.startStageKey) || 0))
            .map((segment) => segment.id);
        segmentOrder.forEach((segmentId) => {
            const segment = segmentsById.get(segmentId);
            if (!segment) return;
            segment.outgoingEdges
                .filter((edge) => edge.targetKind === 'segment')
                .forEach((edge) => {
                    const target = segmentsById.get(edge.targetKey);
                    if (!target) return;
                    const sourceIndex = Number(topology.rank.get(segment.endStageKey) || 0);
                    const targetIndex = Number(topology.rank.get(target.startStageKey) || 0);
                    if (targetIndex < sourceIndex) return;
                    target.column = Math.max(Number(target.column || 0), Number(segment.column || 0) + 1);
                });
        });
        _segmentRows(segmentsById, segmentOrder);

        return {
            topology,
            segments,
            segmentsById,
            stageToSegment,
            segmentOrder,
        };
    }

    function _applyServerDetail(detail, { preserveTransient = false } = {}) {
        const previousProtocolId = String(currentProtocol?.protocol?.protocol_id || '');
        const nextProtocolId = String(detail?.protocol?.protocol_id || '');
        const preserveLocalState = preserveTransient && previousProtocolId && previousProtocolId === nextProtocolId;
        const previousSelection = selection;
        const previousEditorMode = editorMode;
        const previousCanvasViewport = canvasViewport;
        const previousWorkflowMapMode = workflowMapMode;
        const previousPendingStage = pendingStage;
        const previousPendingRoute = pendingRoute;
        currentProtocol = detail;
        draftRevision = Number(detail?.protocol?.draft_revision || 0) || 0;
        draftConflict = null;
        documentHistory = { undo: [], redo: [] };
        if (!preserveLocalState) {
            canvasViewport = { zoom: 'fit' };
        }
        if (previousProtocolId && previousProtocolId !== String(detail?.protocol?.protocol_id || '')) {
            _stopRehearsalPolling();
            rehearsal.runId = '';
            rehearsal.sessions = [];
            rehearsal.scenarios = [];
            rehearsal.runDetail = null;
            rehearsal.refreshSeq += 1;
            rehearsal.drafts = {};
        }
        const docFromServer = (detail && detail.draft_definition_json && Object.keys(detail.draft_definition_json).length)
            ? detail.draft_definition_json
            : (detail && detail.draft_document) || _blankDocument();
        const metadata = docFromServer.metadata || {};
        draft = {
            slug: metadata.slug !== undefined ? String(metadata.slug || '') : String(detail?.protocol?.slug || ''),
            display_name: metadata.display_name !== undefined
                ? String(metadata.display_name || '')
                : String(detail?.protocol?.display_name || ''),
            description: metadata.description !== undefined
                ? String(metadata.description || '')
                : String(detail?.protocol?.description || ''),
            document: _cloneDoc(docFromServer),
        };
        saveState = { state: 'idle', lastSavedAt: detail?.protocol?.updated_at || '', error: '' };
        if (preserveLocalState) {
            selection = _repairSelection(previousSelection, draft.document);
            editorMode = previousEditorMode;
            canvasViewport = previousCanvasViewport;
            workflowMapMode = previousWorkflowMapMode;
            pendingStage = previousPendingStage;
            pendingRoute = previousPendingRoute;
        } else {
            selection = _repairSelection(_selectionFromQuery(draft.document), draft.document);
            workflowMapMode = _workflowMapModeFromQuery();
            collapsibleSectionState = {};
            stageWorkspacePanelState = {};
            pendingStageViewportAnchor = null;
            _resetEditorMode();
        }
    }

    function _repairSelection(current, doc) {
        const key = current.sectionKey || 'overview';
        if (key === 'overview') return { sectionKey: 'overview', nodeKey: '' };
        if (key === 'map') {
            return {
                sectionKey: 'map',
                nodeKey: '',
                sourceStageKey: (doc.stages || []).some((item) => String(item.stage_key || '') === _selectionSourceStageKey(current))
                    ? _selectionSourceStageKey(current)
                    : '',
            };
        }
        if (key === 'protocol') {
            return {
                sectionKey: 'protocol',
                nodeKey: '',
                sourceStageKey: (doc.stages || []).some((item) => String(item.stage_key || '') === _selectionSourceStageKey(current))
                    ? _selectionSourceStageKey(current)
                    : '',
            };
        }
        if (key === 'segments') {
            const projection = _buildWorkflowProjection(doc);
            const next = projection.segmentsById.has(String(current.nodeKey || ''))
                ? { sectionKey: 'segments', nodeKey: String(current.nodeKey || '') }
                : { sectionKey: 'overview', nodeKey: '' };
            return _normalizeSelectionForProjection(next, projection);
        }
        if (key === 'transitions') {
            const hit = _transitionEntries(doc).some((item) => String(item.id || '') === String(current.nodeKey || ''));
            return hit ? current : { sectionKey: 'overview', nodeKey: '' };
        }
        const items = key === 'participants'
            ? (doc.participants || [])
            : key === 'stages'
                ? (doc.stages || [])
                : key === 'artifacts'
                    ? (doc.artifacts || [])
                    : [];
        if (key === 'artifacts' && !String(current.nodeKey || '').trim()) {
            return {
                sectionKey: 'artifacts',
                nodeKey: '',
                sourceStageKey: (doc.stages || []).some((item) => String(item.stage_key || '') === _selectionSourceStageKey(current))
                    ? _selectionSourceStageKey(current)
                    : '',
                surfaceKey: String(current?.surfaceKey || 'secondary') === 'local' ? 'local' : 'secondary',
            };
        }
        const hit = items.find((item) => String(
            key === 'participants' ? item.participant_key
                : key === 'stages' ? item.stage_key
                    : item.artifact_key,
        ) === String(current.nodeKey || ''));
        if (hit) {
            if (key === 'artifacts') {
                return {
                    ...current,
                    sourceStageKey: (doc.stages || []).some((item) => String(item.stage_key || '') === _selectionSourceStageKey(current))
                        ? _selectionSourceStageKey(current)
                        : '',
                    surfaceKey: String(current?.surfaceKey || 'secondary') === 'local' ? 'local' : 'secondary',
                };
            }
            return current;
        }
        return { sectionKey: 'overview', nodeKey: '' };
    }

    function _selectionFromQuery(doc = draft.document) {
        const panel = String(UI.readQueryParam('panel', '') || '').trim().toLowerCase();
        const stageKey = UI.readQueryParam('stage_key', '');
        const artifactKey = UI.readQueryParam('artifact_key', '');
        if (panel === 'map') {
            return { sectionKey: 'map', nodeKey: '', sourceStageKey: stageKey };
        }
        if (panel === 'protocol') {
            return { sectionKey: 'protocol', nodeKey: '', sourceStageKey: stageKey };
        }
        if (panel === 'artifact') {
            return {
                sectionKey: 'artifacts',
                nodeKey: artifactKey,
                sourceStageKey: stageKey,
                surfaceKey: String(UI.readQueryParam('artifact_surface', '') || '').trim().toLowerCase() === 'local'
                    ? 'local'
                    : 'secondary',
            };
        }
        const segmentId = UI.readQueryParam('segment_id', '');
        if (segmentId) return { sectionKey: 'segments', nodeKey: segmentId };
        if (stageKey) return { sectionKey: 'stages', nodeKey: stageKey };
        const participantKey = UI.readQueryParam('participant_key', '');
        if (participantKey) return { sectionKey: 'participants', nodeKey: participantKey };
        const transitionId = UI.readQueryParam('transition_id', '');
        if (transitionId) return { sectionKey: 'transitions', nodeKey: transitionId };
        if (artifactKey) return { sectionKey: 'artifacts', nodeKey: artifactKey };
        return { sectionKey: 'overview', nodeKey: '' };
    }

    function _selectionQueryState(current = selection) {
        const next = {
            segment_id: '',
            stage_key: '',
            participant_key: '',
            transition_id: '',
            artifact_key: '',
            artifact_surface: '',
            panel: '',
            workflow_map: workflowMapMode,
        };
        const key = String(current?.sectionKey || 'overview');
        const nodeKey = String(current?.nodeKey || '');
        const sourceStageKey = _selectionSourceStageKey(current);
        if (key === 'map') {
            next.panel = 'map';
            next.stage_key = sourceStageKey;
            next.workflow_map = 'visible';
        } else if (key === 'protocol') {
            next.panel = 'protocol';
            next.stage_key = sourceStageKey;
        } else if (key === 'segments' && nodeKey) {
            next.segment_id = nodeKey;
            next.panel = 'segment';
        } else if (key === 'stages' && nodeKey) {
            next.stage_key = nodeKey;
            next.panel = 'stage';
        } else if (key === 'participants' && nodeKey) {
            next.participant_key = nodeKey;
            next.panel = 'participant';
        } else if (key === 'transitions' && nodeKey) {
            next.transition_id = nodeKey;
            next.panel = 'transition';
        } else if (key === 'artifacts') {
            next.artifact_key = nodeKey;
            next.artifact_surface = String(current?.surfaceKey || 'secondary') === 'local' ? 'local' : 'secondary';
            next.panel = 'artifact';
            next.stage_key = sourceStageKey;
        }
        if (editorMode.kind === 'insert-stage') next.panel = 'new-stage';
        if (editorMode.kind === 'create-route') next.panel = 'new-route';
        if (editorMode.kind === 'rehearse') next.panel = 'rehearsal';
        return next;
    }

    function _writeState({ push = false } = {}) {
        if (designSessionsRoute) {
            UI.updateQueryParams({
                session_id: selectedAutoProtocolSessionId || '',
                status: autoProtocolStatusFilter || '',
                cursor: autoProtocolCursor > 0 ? autoProtocolCursor : '',
                protocol_id: '',
                new: '',
                run_id: '',
                issue_kind: '',
                entry_agent_id: '',
                protocol_view: '',
                include_generated: '',
            }, { replace: !push });
            return;
        }
        UI.updateQueryParams({
            protocol_id: currentProtocolId || '',
            new: !currentProtocolId && templateChooserMode === 'template' && protocolTemplates.length ? 'template' : '',
            run_id: '',
            status: '',
            issue_kind: '',
            entry_agent_id: '',
            protocol_view: '',
            include_generated: includeGeneratedCatalog ? '1' : '',
            ..._selectionQueryState(),
        }, { replace: !push });
    }

    // -------------------------------------------------------------------
    // Persistence
    // -------------------------------------------------------------------
    function _clearAutosaveTimer() {
        if (autosaveTimer) {
            clearTimeout(autosaveTimer);
            autosaveTimer = 0;
        }
    }

    function _scheduleAutosave() {
        if (!currentProtocolId) return;
        if (saveState.state === 'conflict') return;
        _clearAutosaveTimer();
        saveState = { state: 'editing', lastSavedAt: saveState.lastSavedAt, error: '' };
        _syncLifecycleChip();
        autosaveTimer = setTimeout(() => {
            autosaveTimer = 0;
            void _autosave();
        }, 450);
    }

    async function _autosave() {
        if (!currentProtocolId) return;
        saveState = { state: 'saving', lastSavedAt: saveState.lastSavedAt, error: '' };
        _syncLifecycleChip();
        try {
            const result = await API.saveProtocolDraft(currentProtocolId, {
                slug: draft.slug,
                display_name: draft.display_name,
                description: draft.description,
                definition_json: _docFromDraft(),
            }, {
                ifMatch: draftRevision,
                authoringSurface: _currentAuthoringSurface(),
            });
            _applyServerDetail(result, { preserveTransient: true });
            saveState = { state: 'saved', lastSavedAt: result?.protocol?.updated_at || new Date().toISOString(), error: '' };
            _syncLifecycleChip();
            await loadProtocols({ quiet: true });
            render();
            return true;
        } catch (err) {
            if (err?.status === 409 && err?.errorCode === 'PROTOCOL_DRAFT_CONFLICT') {
                draftConflict = {
                    serverDetail: {
                        protocol: err?.details?.protocol || null,
                        draft_definition_json: err?.details?.draft_definition_json || {},
                        draft_document: err?.details?.draft_document || null,
                        validation: err?.details?.validation || null,
                    },
                };
                saveState = {
                    state: 'conflict',
                    lastSavedAt: err?.details?.protocol?.updated_at || saveState.lastSavedAt,
                    error: err.message || String(err),
                };
                _syncLifecycleChip();
                render();
                UI.notify('Protocol draft changed in another tab or client. Reload or overwrite to continue.', 'warning');
                return false;
            }
            saveState = { state: 'error', lastSavedAt: saveState.lastSavedAt, error: err.message || String(err) };
            _syncLifecycleChip();
            UI.reportError('Failed to save the protocol draft', err, { context: 'Protocol autosave failed' });
            return false;
        }
    }

    function _blockConflictAction(actionLabel) {
        if (saveState.state !== 'conflict' || !draftConflict?.serverDetail?.protocol) {
            return false;
        }
        UI.notify(`${actionLabel} is blocked until you reload or overwrite the latest server draft.`, 'warning');
        return true;
    }

    function _reloadServerDraftConflict() {
        if (!draftConflict?.serverDetail?.protocol) return;
        _applyServerDetail(draftConflict.serverDetail);
        saveState = { state: 'saved', lastSavedAt: currentProtocol?.protocol?.updated_at || '', error: '' };
        render();
        UI.notify('Reloaded the latest server draft.', 'success');
    }

    async function _overwriteServerDraftConflict() {
        if (!draftConflict?.serverDetail?.protocol) return;
        const localDraft = {
            slug: draft.slug,
            display_name: draft.display_name,
            description: draft.description,
            document: _cloneDoc(draft.document),
        };
        const localSelection = selection;
        _applyServerDetail(draftConflict.serverDetail);
        draft = localDraft;
        selection = _repairSelection(localSelection, draft.document);
        saveState = { state: 'editing', lastSavedAt: currentProtocol?.protocol?.updated_at || '', error: '' };
        _syncLifecycleChip();
        render();
        const saved = await _autosave();
        if (saved) {
            UI.notify('Overwrote the server draft with your local changes.', 'success');
        }
    }

    function _agentOptionLabel(agent) {
        return [
            String(agent?.display_name || agent?.slug || agent?.agent_id || 'Bot').trim(),
            String(agent?.provider || '').trim(),
            String(agent?.role || '').trim(),
        ].filter(Boolean).join(' · ');
    }

    function _appendPackageSummary(containerEl, plan, mappingState) {
        containerEl.replaceChildren();
        if (!plan) return;
        const protocol = plan.protocol || {};
        const summary = document.createElement('div');
        summary.className = 'protocol-package-summary';
        const title = document.createElement('h4');
        title.textContent = protocol.display_name || protocol.slug || 'Protocol package';
        summary.appendChild(title);
        const meta = document.createElement('p');
        meta.className = 'quiet-note';
        meta.textContent = protocol.exists
            ? 'A protocol with this slug already exists. Import as copy is selected by default.'
            : 'This package can be imported as a new protocol draft.';
        summary.appendChild(meta);
        containerEl.appendChild(summary);

        const warnings = [...(plan.warnings || []), ...(plan.blocking_issues || [])];
        if (warnings.length) {
            const list = document.createElement('div');
            list.className = 'protocol-package-message-list';
            warnings.forEach((item) => {
                const row = document.createElement('div');
                row.className = `protocol-package-message ${item.blocking ? 'is-blocking' : ''}`;
                row.textContent = item.message || item.code || 'Package warning';
                list.appendChild(row);
            });
            containerEl.appendChild(list);
        }

        if ((plan.skills || []).length) {
            const skillGrid = document.createElement('div');
            skillGrid.className = 'protocol-package-grid';
            (plan.skills || []).forEach((skill) => {
                const row = document.createElement('div');
                row.className = 'protocol-package-row';
                const label = document.createElement('div');
                const name = document.createElement('strong');
                name.textContent = skill.name || 'Skill';
                const status = document.createElement('span');
                status.textContent = skill.status || 'pending';
                label.append(name, status);
                row.appendChild(label);
                skillGrid.appendChild(row);
            });
            containerEl.appendChild(skillGrid);
        }

        const mappings = (plan.stage_mappings || []).filter((item) => item.status === 'requires_mapping' || item.status === 'mapped' || item.status === 'auto_resolved');
        if (mappings.length) {
            const mappingWrap = document.createElement('div');
            mappingWrap.className = 'protocol-package-mappings';
            const heading = document.createElement('h4');
            heading.textContent = 'Stage routing';
            mappingWrap.appendChild(heading);
            mappings.forEach((item) => {
                const row = document.createElement('label');
                row.className = 'protocol-package-mapping-row';
                const text = document.createElement('span');
                text.textContent = item.stage_key || 'Stage';
                row.appendChild(text);
                const select = document.createElement('select');
                select.className = 'input';
                const empty = document.createElement('option');
                empty.value = '';
                empty.textContent = 'Choose bot';
                select.appendChild(empty);
                const candidateIds = new Set((item.candidates || []).map((agent) => String(agent.agent_id || '')));
                const options = (candidateIds.size ? (item.candidates || []) : connectedAgents).filter((agent) => String(agent?.agent_id || '').trim());
                options.forEach((agent) => {
                    const option = document.createElement('option');
                    option.value = String(agent.agent_id || '');
                    option.textContent = _agentOptionLabel(agent);
                    select.appendChild(option);
                });
                select.value = mappingState[item.stage_key] || item.target_agent_id || '';
                if (select.value) mappingState[item.stage_key] = select.value;
                select.addEventListener('change', () => {
                    mappingState[item.stage_key] = select.value;
                });
                row.appendChild(select);
                mappingWrap.appendChild(row);
            });
            containerEl.appendChild(mappingWrap);
        }
    }

    function _openExportProtocolPackageDialog() {
        if (!currentProtocolId) return;
        const form = document.createElement('div');
        form.className = 'protocol-package-dialog';
        const formatSelect = document.createElement('select');
        formatSelect.className = 'input';
        formatSelect.innerHTML = '<option value="json">JSON</option><option value="yaml">YAML</option>';
        form.appendChild(formatSelect);
        const revisionSelect = document.createElement('select');
        revisionSelect.className = 'input';
        const hasPublishedVersion = Boolean(currentProtocol?.protocol?.current_version_id || currentProtocol?.version);
        revisionSelect.innerHTML = `${hasPublishedVersion ? '<option value="published">Published version</option>' : ''}<option value="draft">Draft</option>`;
        form.appendChild(revisionSelect);
        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = 'The exported package includes this protocol and the skills required by its stages.';
        form.appendChild(note);
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn';
        cancelBtn.textContent = 'Cancel';
        const exportBtn = document.createElement('button');
        exportBtn.type = 'button';
        exportBtn.className = 'btn btn-primary';
        exportBtn.textContent = 'Export package';
        const view = UI.showDialog('Export protocol package', form, {
            actions: [cancelBtn, exportBtn],
            maxWidth: '520px',
        });
        cancelBtn.addEventListener('click', () => view.close());
        exportBtn.addEventListener('click', async () => {
            exportBtn.disabled = true;
            try {
                const result = await API.exportProtocolPackage(currentProtocolId, {
                    format: formatSelect.value,
                    revision: revisionSelect.value,
                });
                _downloadProtocolText(
                    result.file_name || `${UI.safeFilename(draft.slug || 'protocol')}.octopus-protocol.${formatSelect.value}`,
                    result.text || '',
                    result.content_type || 'application/json',
                );
                view.close();
                UI.notify('Protocol package exported.', 'success');
            } catch (err) {
                UI.reportError('Failed to export the protocol package', err, { context: 'Protocol package export failed' });
            }
            exportBtn.disabled = false;
        });
    }

    function _openImportProtocolPackageDialog() {
        const state = { text: '', format: 'json', plan: null, mappings: {} };
        const form = document.createElement('div');
        form.className = 'protocol-package-dialog';
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.className = 'input';
        fileInput.accept = '.json,.yaml,.yml,application/json,application/x-yaml,text/yaml';
        form.appendChild(fileInput);
        const textArea = document.createElement('textarea');
        textArea.className = 'input protocol-package-textarea';
        textArea.placeholder = 'Paste protocol package JSON or YAML';
        form.appendChild(textArea);
        const formatSelect = document.createElement('select');
        formatSelect.className = 'input';
        formatSelect.innerHTML = '<option value="json">JSON</option><option value="yaml">YAML</option>';
        form.appendChild(formatSelect);
        const policySelect = document.createElement('select');
        policySelect.className = 'input';
        policySelect.innerHTML = '<option value="create_new">Create new</option><option value="import_copy">Import as copy</option><option value="overwrite_existing">Overwrite existing draft</option><option value="fail_if_exists">Fail if exists</option>';
        policySelect.value = 'create_new';
        policySelect.hidden = true;
        form.appendChild(policySelect);
        const copySlugInput = document.createElement('input');
        copySlugInput.className = 'input';
        copySlugInput.placeholder = 'Copy slug';
        form.appendChild(copySlugInput);
        const copyNameInput = document.createElement('input');
        copyNameInput.className = 'input';
        copyNameInput.placeholder = 'Copy display name';
        form.appendChild(copyNameInput);
        const planEl = document.createElement('div');
        planEl.className = 'protocol-package-plan';
        form.appendChild(planEl);
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn';
        cancelBtn.textContent = 'Cancel';
        const planBtn = document.createElement('button');
        planBtn.type = 'button';
        planBtn.className = 'btn';
        planBtn.textContent = 'Review import';
        const applyBtn = document.createElement('button');
        applyBtn.type = 'button';
        applyBtn.className = 'btn btn-primary';
        applyBtn.textContent = 'Import';
        applyBtn.disabled = true;
        const view = UI.showDialog('Import protocol package', form, {
            actions: [cancelBtn, planBtn, applyBtn],
            maxWidth: '760px',
        });
        function invalidatePlan() {
            state.text = '';
            state.plan = null;
            state.mappings = {};
            planEl.replaceChildren();
            applyBtn.disabled = true;
            policySelect.hidden = true;
            policySelect.value = 'create_new';
            copySlugInput.value = '';
            copyNameInput.value = '';
            copySlugInput.dataset.suggested = '';
            copyNameInput.dataset.suggested = '';
            syncCopyInputs();
        }
        function syncCopyInputs() {
            const isCopy = policySelect.value === 'import_copy';
            copySlugInput.hidden = !isCopy;
            copyNameInput.hidden = !isCopy;
            if (isCopy) {
                if (!copySlugInput.value && copySlugInput.dataset.suggested) copySlugInput.value = copySlugInput.dataset.suggested;
                if (!copyNameInput.value && copyNameInput.dataset.suggested) copyNameInput.value = copyNameInput.dataset.suggested;
            }
        }
        policySelect.addEventListener('change', syncCopyInputs);
        syncCopyInputs();
        cancelBtn.addEventListener('click', () => view.close());
        fileInput.addEventListener('change', async () => {
            const file = fileInput.files && fileInput.files[0];
            if (!file) return;
            textArea.value = await file.text();
            formatSelect.value = /\.ya?ml$/i.test(String(file.name || '')) ? 'yaml' : 'json';
            invalidatePlan();
        });
        textArea.addEventListener('input', invalidatePlan);
        formatSelect.addEventListener('change', invalidatePlan);
        planBtn.addEventListener('click', async () => {
            planBtn.disabled = true;
            applyBtn.disabled = true;
            try {
                if (!connectedAgents.length) await loadAssignmentCatalog({ quiet: true });
                state.text = String(textArea.value || '').trim();
                state.format = formatSelect.value;
                state.plan = await API.planProtocolPackageImport({
                    text: state.text,
                    format: state.format,
                    stage_mappings: Object.entries(state.mappings).map(([stage_key, target_agent_id]) => ({ stage_key, target_agent_id })),
                });
                copySlugInput.dataset.suggested = state.plan?.protocol?.suggested_copy_slug || '';
                copyNameInput.dataset.suggested = state.plan?.protocol?.suggested_copy_display_name || '';
                policySelect.value = state.plan?.protocol?.exists ? 'import_copy' : 'create_new';
                policySelect.hidden = false;
                if (policySelect.value === 'import_copy') {
                    if (copySlugInput.dataset.suggested && !copySlugInput.value) copySlugInput.value = copySlugInput.dataset.suggested;
                    if (copyNameInput.dataset.suggested && !copyNameInput.value) copyNameInput.value = copyNameInput.dataset.suggested;
                } else {
                    copySlugInput.value = '';
                    copyNameInput.value = '';
                }
                syncCopyInputs();
                _appendPackageSummary(planEl, state.plan, state.mappings);
                applyBtn.disabled = Boolean(state.plan?.blocking_issues?.length);
                UI.notify(state.plan?.blocking_issues?.length ? 'Choose required mappings before import.' : 'Import plan ready.', state.plan?.blocking_issues?.length ? 'warning' : 'success');
            } catch (err) {
                UI.reportError('Failed to review the protocol package', err, { context: 'Protocol package import plan failed' });
            }
            planBtn.disabled = false;
        });
        applyBtn.addEventListener('click', async () => {
            applyBtn.disabled = true;
            try {
                const result = await API.applyProtocolPackageImport({
                    text: state.text || String(textArea.value || '').trim(),
                    format: state.format || formatSelect.value,
                    protocol_policy: policySelect.value,
                    copy_slug: String(copySlugInput.value || '').trim(),
                    copy_display_name: String(copyNameInput.value || '').trim(),
                    stage_mappings: Object.entries(state.mappings).map(([stage_key, target_agent_id]) => ({ stage_key, target_agent_id })),
                    publish: false,
                });
                const nextId = String(result?.protocol?.protocol_id || result?.mutation?.protocol?.protocol_id || '');
                if (nextId) currentProtocolId = nextId;
                view.close();
                await loadProtocols({ quiet: true });
                if (currentProtocolId) await loadProtocolDetail();
                UI.notify('Protocol package imported.', 'success');
            } catch (err) {
                UI.reportError('Failed to import the protocol package', err, { context: 'Protocol package import apply failed' });
            }
            applyBtn.disabled = false;
        });
    }

    async function _validateNow() {
        if (_blockConflictAction('Validate')) return;
        if (!currentProtocolId) return;
        if (saveState.state === 'editing' || saveState.state === 'saving') {
            const saved = await _autosave();
            if (!saved) return;
        }
        saveState = { state: 'saving', lastSavedAt: saveState.lastSavedAt, error: '' };
        _syncLifecycleChip();
        currentProtocol = await API.validateProtocol(currentProtocolId);
        _applyServerDetail(currentProtocol);
        saveState = { state: 'saved', lastSavedAt: new Date().toISOString(), error: '' };
        render();
        UI.notify(
            currentProtocol.validation?.ok ? 'Protocol validated.' : 'Protocol validation found issues.',
            currentProtocol.validation?.ok ? 'success' : 'warning',
        );
    }

    async function _publishNow() {
        if (_blockConflictAction('Publish')) return;
        if (!currentProtocolId) return;
        if (saveState.state === 'editing' || saveState.state === 'saving') {
            const saved = await _autosave();
            if (!saved) return;
        }
        _clearAutosaveTimer();
        saveState = { state: 'saving', lastSavedAt: saveState.lastSavedAt, error: '' };
        _syncLifecycleChip();
        currentProtocol = await API.publishProtocol(currentProtocolId);
        _applyServerDetail(currentProtocol);
        await loadProtocols({ quiet: true });
        saveState = { state: 'saved', lastSavedAt: new Date().toISOString(), error: '' };
        render();
        UI.notify('Protocol published.', 'success');
    }

    async function _archiveNow() {
        if (_blockConflictAction('Archive')) return;
        _clearAutosaveTimer();
        saveState = { state: 'saving', lastSavedAt: saveState.lastSavedAt, error: '' };
        _syncLifecycleChip();
        currentProtocol = await API.archiveProtocol(currentProtocolId);
        _applyServerDetail(currentProtocol);
        await loadProtocols({ quiet: true });
        saveState = { state: 'saved', lastSavedAt: new Date().toISOString(), error: '' };
        render();
        UI.notify('Protocol archived.', 'success');
    }

    async function _discardNow() {
        if (_blockConflictAction('Discard')) return;
        _clearAutosaveTimer();
        if (!currentProtocolId) {
            _resetDraft();
            _writeState({ push: true });
            render();
            return;
        }
        await API.deleteProtocol(currentProtocolId);
        _resetDraft();
        _writeState({ push: true });
        await loadProtocols({ quiet: true });
        render();
        UI.notify('Protocol draft discarded.', 'success');
    }

    function _resetDraft() {
        _clearAutosaveTimer();
        currentProtocolId = '';
        currentProtocol = null;
        protocolDetailLoading = false;
        draftRevision = 0;
        draftConflict = null;
        _stopRehearsalPolling();
        rehearsal.runId = '';
        rehearsal.sessions = [];
        rehearsal.scenarios = [];
        rehearsal.runDetail = null;
        rehearsal.refreshSeq += 1;
        documentHistory = { undo: [], redo: [] };
        draft = { slug: '', display_name: '', description: '', document: _blankDocument() };
        selection = { sectionKey: 'overview', nodeKey: '' };
        saveState = { state: 'idle', lastSavedAt: '', error: '' };
        canvasViewport = { zoom: 'fit' };
        workflowMapMode = 'auto';
        stageAssignmentEditor = { stageKey: '', mode: '' };
        _resetEditorMode();
    }

    async function _createBlankDraft() {
        try {
            const result = await API.createProtocolDraft({ source_kind: 'blank' });
            currentProtocolId = result.protocol?.protocol_id || '';
            templateChooserMode = '';
            _applyServerDetail(result);
            _writeState({ push: true });
            await loadProtocols({ quiet: true });
            render();
            UI.notify('Protocol draft created.', 'success');
        } catch (err) {
            UI.reportError('Failed to create a blank protocol draft', err, {
                context: 'Protocol draft create failed',
            });
        }
    }

    function _autoProtocolSummaryEl(session) {
        const panel = document.createElement('div');
        panel.className = 'protocol-auto-summary protocol-auto-review';
        const plan = session?.plan || {};
        const analysis = session?.analysis || {};
        const validation = session?.validation || {};
        const stagesForSummary = Array.isArray(plan.stages) ? plan.stages : [];
        const artifactsForSummary = Array.isArray(plan.artifacts) ? plan.artifacts : [];
        const workPackagesForSummary = Array.isArray(analysis.work_packages) ? analysis.work_packages : [];
        const primaryArtifact = plan.primary_artifact || session?.draft_definition_json?.metadata?.auto_protocol?.primary_artifact || {};
        const unresolved = Array.isArray(session?.unresolved_decisions) ? session.unresolved_decisions : [];
        const warningItems = Array.isArray(session?.warnings) ? session.warnings : [];
        const reviewCount = stagesForSummary.filter((stage) => String(stage?.stage_kind || '') === 'review').length;
        const ready = Boolean(session?.session_id && validation.ok && !unresolved.length);
        const header = document.createElement('div');
        header.className = 'protocol-auto-review-header';
        const title = document.createElement('h4');
        title.textContent = String(plan.protocol_name || 'Generated protocol');
        header.appendChild(title);
        const summary = document.createElement('p');
        summary.textContent = String(analysis.goal || plan.description || 'Review the generated workflow before applying it.');
        header.appendChild(summary);
        const readiness = document.createElement('span');
        readiness.className = ready ? 'protocol-auto-readiness is-ready' : 'protocol-auto-readiness';
        readiness.textContent = ready ? 'Ready to apply, publish, or run' : 'Needs attention before publishing';
        header.appendChild(readiness);
        panel.appendChild(header);
        const facts = document.createElement('div');
        facts.className = 'kit-catalog-card-meta';
        [
            `${workPackagesForSummary.length} work packages`,
            `${reviewCount} reviews`,
            `${stagesForSummary.length} stages`,
            `${artifactsForSummary.length} artifacts`,
            plan.contract_required ? 'Full product/system contract' : 'Lightweight contract',
            String(plan.product_class || '').trim() ? `Product class: ${plan.product_class}` : '',
            validation.ok ? 'Validation ready' : 'Validation needs attention',
        ].filter(Boolean).forEach((label) => {
            const item = document.createElement('span');
            item.className = 'kit-catalog-card-meta-item';
            item.textContent = label;
            facts.appendChild(item);
        });
        if (Array.isArray(analysis.skills) && analysis.skills.length) {
            const skill = document.createElement('span');
            skill.className = 'kit-catalog-card-meta-item';
            skill.textContent = `Skills: ${analysis.skills.slice(0, 5).join(', ')}`;
            facts.appendChild(skill);
        }
        panel.appendChild(facts);
        const primary = document.createElement('div');
        primary.className = 'protocol-auto-primary';
        const primaryTitle = document.createElement('strong');
        primaryTitle.textContent = `Primary outcome: ${String(primaryArtifact.display_name || primaryArtifact.artifact_key || 'Produced Outcome')}`;
        primary.appendChild(primaryTitle);
        const primaryMeta = document.createElement('span');
        primaryMeta.textContent = [
            String(primaryArtifact.artifact_key || '').trim() ? `Artifact ${primaryArtifact.artifact_key}` : '',
            String(primaryArtifact.produced_by_stage_key || '').trim() ? `Produced by ${primaryArtifact.produced_by_stage_key}` : '',
            String(primaryArtifact.expected_path || '').trim() ? String(primaryArtifact.expected_path) : '',
        ].filter(Boolean).join(' · ');
        primary.appendChild(primaryMeta);
        panel.appendChild(primary);

        const makeDetails = (label, count, children, { open = false, emptyText = 'Nothing to show.' } = {}) => {
            const details = document.createElement('details');
            details.className = 'protocol-auto-detail';
            details.open = open;
            const summaryEl = document.createElement('summary');
            summaryEl.textContent = `${label}${Number.isFinite(count) ? ` (${count})` : ''}`;
            details.appendChild(summaryEl);
            const body = document.createElement('div');
            body.className = 'protocol-auto-detail-body';
            if (children.length) {
                children.forEach((child) => body.appendChild(child));
            } else {
                const empty = document.createElement('p');
                empty.className = 'quiet-note';
                empty.textContent = emptyText;
                body.appendChild(empty);
            }
            details.appendChild(body);
            return details;
        };

        if (workPackagesForSummary.length) {
            const packages = document.createElement('div');
            packages.className = 'protocol-auto-packages';
            workPackagesForSummary.forEach((pkg) => {
                const item = document.createElement('div');
                item.className = 'protocol-auto-package';
                const name = document.createElement('strong');
                name.textContent = String(pkg.display_name || pkg.package_key || 'Work package');
                item.appendChild(name);
                const rationale = document.createElement('span');
                rationale.textContent = String(pkg.rationale || pkg.purpose || '').replace(/\s+/g, ' ').trim();
                item.appendChild(rationale);
                packages.appendChild(item);
            });
            panel.appendChild(makeDetails('Work packages', workPackagesForSummary.length, [packages], { open: false }));
        }
        const stages = document.createElement('ol');
        stages.className = 'protocol-auto-stage-list';
        (Array.isArray(plan.stages) ? plan.stages : []).forEach((stage) => {
            const item = document.createElement('li');
            const label = document.createElement('strong');
            label.textContent = `${String(stage.display_name || stage.stage_key || 'Stage')} - ${String(stage.stage_kind || 'work')}`;
            item.appendChild(label);
            const purpose = String(stage.purpose || '').replace(/\s+/g, ' ').trim();
            if (purpose) {
                const detail = document.createElement('span');
                detail.textContent = purpose.length > 220 ? `${purpose.slice(0, 217).trim()}...` : purpose;
                item.appendChild(detail);
            }
            const outputs = Array.isArray(stage.outputs)
                ? stage.outputs.map((value) => String(value || '').trim()).filter(Boolean)
                : [];
            const output = document.createElement('small');
            output.textContent = `Outputs: ${outputs.length ? outputs.join(', ') : 'none'}`;
            item.appendChild(output);
            stages.appendChild(item);
        });
        panel.appendChild(makeDetails('Stage map', stagesForSummary.length, [stages], { open: false }));
        const warnings = [...unresolved, ...warningItems];
        if (warnings.length) {
            const warningList = document.createElement('div');
            warningList.className = 'validation-list';
            warnings.forEach((warning) => {
                const row = document.createElement('div');
                row.className = 'validation-item';
                row.textContent = String(warning.message || warning.code || '');
                warningList.appendChild(row);
            });
            panel.appendChild(makeDetails('Warnings and blockers', warnings.length, [warningList], { open: true }));
        }
        return panel;
    }

    function _autoProtocolReady(session) {
        const validation = session?.validation || {};
        const unresolved = Array.isArray(session?.unresolved_decisions) ? session.unresolved_decisions : [];
        return Boolean(session?.session_id && validation.ok && !unresolved.length);
    }

    function _autoProtocolRunId(session) {
        return String(session?.run_result?.run?.protocol_run_id || '').trim();
    }

    async function _adoptAutoProtocolSession(session, { push = true } = {}) {
        const protocolId = _autoProtocolTargetProtocolId(session);
        if (!protocolId) return false;
        if (designSessionsRoute) {
            Router.navigate(`/ui/protocols?protocol_id=${encodeURIComponent(protocolId)}`);
            return true;
        }
        currentProtocolId = protocolId;
        templateChooserMode = '';
        currentProtocol = null;
        protocolDetailLoading = true;
        _writeState({ push });
        await loadProtocols({ quiet: true });
        await loadProtocolDetail();
        return true;
    }

    function _openAutoProtocolDialog({ mode = 'create', sessionId = '', ignoreRememberedSession = false } = {}) {
        const isRevision = mode === 'revise' && currentProtocolId;
        const form = document.createElement('div');
        form.className = 'protocol-package-dialog protocol-auto-dialog';
        const requirement = document.createElement('textarea');
        requirement.className = 'input';
        requirement.rows = 7;
        requirement.placeholder = isRevision
            ? 'Describe how this protocol should change.'
            : 'Describe the outcome you want. Auto Protocol will infer stages, roles, artifacts, review loops, and run inputs.';
        form.appendChild(requirement);
        const constraints = document.createElement('textarea');
        constraints.className = 'input';
        constraints.rows = 3;
        constraints.placeholder = 'Optional constraints, data sources, delivery expectations, or acceptance notes.';
        form.appendChild(constraints);
        const resourcePicker = Kit.resourceAttachmentPicker({
            label: 'Attach files',
            help: 'Add source files, datasets, assets, zips, screenshots, or documents.',
            sourceRef: isRevision ? `protocol:${currentProtocolId}` : 'protocol-auto:create',
            relation: 'context',
        });
        form.appendChild(resourcePicker.element);
        const plannerField = _createAutoProtocolPlannerField(_availableAuthoringAgents());
        form.appendChild(plannerField.element);
        const status = document.createElement('p');
        status.className = 'quiet-note';
        status.textContent = 'Generated output becomes a normal editable protocol draft.';
        form.appendChild(status);
        const preview = document.createElement('div');
        preview.className = 'protocol-auto-preview';
        form.appendChild(preview);
        const revise = document.createElement('textarea');
        revise.className = 'input';
        revise.rows = 3;
        revise.placeholder = 'Optional: ask for a modification after generation.';
        revise.hidden = true;
        const reviseWrap = document.createElement('details');
        reviseWrap.className = 'protocol-auto-modify';
        reviseWrap.hidden = true;
        const reviseSummary = document.createElement('summary');
        reviseSummary.textContent = 'Ask Auto Protocol to change the draft';
        reviseWrap.appendChild(reviseSummary);
        reviseWrap.appendChild(revise);
        form.appendChild(reviseWrap);

        let session = null;
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn';
        cancelBtn.textContent = 'Cancel';
        const generateBtn = document.createElement('button');
        generateBtn.type = 'button';
        generateBtn.className = 'btn btn-primary';
        generateBtn.textContent = isRevision ? 'Preview changes' : 'Generate protocol';
        const reviseBtn = document.createElement('button');
        reviseBtn.type = 'button';
        reviseBtn.className = 'btn';
        reviseBtn.textContent = 'Modify';
        reviseBtn.hidden = true;
        const applyBtn = document.createElement('button');
        applyBtn.type = 'button';
        applyBtn.className = 'btn btn-primary';
        applyBtn.textContent = 'Apply draft';
        applyBtn.hidden = true;
        const publishBtn = document.createElement('button');
        publishBtn.type = 'button';
        publishBtn.className = 'btn';
        publishBtn.textContent = 'Publish';
        publishBtn.hidden = true;
        const runBtn = document.createElement('button');
        runBtn.type = 'button';
        runBtn.className = 'btn btn-primary';
        runBtn.textContent = 'Publish & Run';
        runBtn.hidden = true;
        const queueBtn = document.createElement('button');
        queueBtn.type = 'button';
        queueBtn.className = 'btn';
        queueBtn.textContent = 'View in queue';
        queueBtn.hidden = true;
        const view = UI.showDialog(isRevision ? 'Improve with Auto Protocol' : 'Auto protocol', form, {
            actions: [cancelBtn, generateBtn, reviseBtn, applyBtn, publishBtn, runBtn, queueBtn],
            maxWidth: '760px',
            initialFocus: requirement,
            closeOnOverlay: false,
            closeOnEscape: false,
        });
        view.dialog.classList.add('protocol-auto-modal');
        let sessionSubscription = null;
        let planningWaitSeq = 0;
        const originalClose = view.close;
        view.close = () => {
            if (sessionSubscription) {
                sessionSubscription();
                sessionSubscription = null;
            }
            originalClose();
        };
        const syncActions = () => {
            const hasSession = Boolean(session?.session_id);
            const planning = _autoProtocolPlanning(session);
            const hasDraft = _autoProtocolHasDraft(session);
            const actionable = hasSession && !planning && hasDraft;
            const ready = _autoProtocolReady(session);
            cancelBtn.textContent = hasSession ? 'Close' : 'Cancel';
            _setAutoProtocolButtonState(generateBtn, { visible: !(hasSession && (planning || hasDraft)) });
            _setAutoProtocolButtonState(reviseBtn, { visible: actionable, disabled: !actionable || !revise.value.trim() });
            _setAutoProtocolButtonState(applyBtn, { visible: actionable });
            _setAutoProtocolButtonState(publishBtn, { visible: actionable, disabled: planning || !ready });
            _setAutoProtocolButtonState(runBtn, { visible: actionable, disabled: planning || !ready });
            _setAutoProtocolButtonState(queueBtn, { visible: hasSession });
            reviseWrap.hidden = !actionable;
            revise.hidden = !actionable;
            applyBtn.className = ready || planning ? 'btn' : 'btn btn-primary';
            runBtn.className = ready ? 'btn btn-primary' : 'btn';
            runBtn.style.order = hasSession && ready ? '0' : '3';
            applyBtn.style.order = hasSession ? (ready ? '1' : '0') : '';
            publishBtn.style.order = hasSession ? '2' : '';
            reviseBtn.style.order = hasSession ? '3' : '';
            queueBtn.style.order = hasSession ? '4' : '';
            cancelBtn.style.order = hasSession ? '5' : '';
            const gateTitle = ready ? '' : 'Resolve validation and assignment warnings before publishing or running.';
            publishBtn.title = gateTitle;
            runBtn.title = gateTitle;
        };
        const renderSessionState = (nextSession, { progressMessage = 'Designing protocol…', readyMessage = 'Review the generated structure. Apply it to continue in the normal editor.' } = {}) => {
            session = nextSession;
            if (session?.session_id) {
                _rememberActiveAutoProtocolSession(session);
                if (designSessionsRoute) {
                    selectedAutoProtocolSessionId = String(session.session_id || '');
                    selectedAutoProtocolSession = session;
                    _writeState({ push: true });
                    void loadAutoProtocolSessions({ quiet: true })
                        .then(() => {
                            if (designSessionsRoute) render();
                        })
                        .catch((err) => {
                            console.warn('Failed to refresh Auto Protocol design sessions after dialog update', err);
                        });
                }
            }
            if (_autoProtocolPlanning(session)) {
                _setAutoProtocolStatus(status, progressMessage);
                UI.reconcileChildren(preview, [_autoProtocolProgressEl(session)]);
            } else if (session?.session_id) {
                UI.reconcileChildren(preview, [_autoProtocolSummaryEl(session)]);
                _setAutoProtocolStatus(status, _autoProtocolFinishedMessage(session, readyMessage));
            }
            syncActions();
        };
        const subscribeToSession = () => {
            if (sessionSubscription) {
                sessionSubscription();
                sessionSubscription = null;
            }
            if (!session?.session_id || !_autoProtocolPlanning(session)) return;
            sessionSubscription = _subscribeAutoProtocolSession(session.session_id, async (updated) => {
                if (!view.dialog.isConnected) return;
                renderSessionState(updated);
            });
        };
        const refreshSessionState = async (options = {}) => {
            if (!session?.session_id) return null;
            const updated = await API.getProtocolAutoSession(session.session_id);
            renderSessionState(updated, options);
            subscribeToSession();
            return session;
        };
        const attachSession = async (sessionId, options = {}) => {
            const id = String(sessionId || '').trim();
            if (!id) return null;
            const updated = await API.getProtocolAutoSession(id);
            if (options.requirePlanning && !_autoProtocolPlanning(updated)) {
                _rememberActiveAutoProtocolSession(null);
                return null;
            }
            if (options.rememberedContext && !_autoProtocolSessionMatchesRememberedContext(updated, options.rememberedContext)) {
                _rememberActiveAutoProtocolSession(null);
                return null;
            }
            renderSessionState(updated, options);
            subscribeToSession();
            return session;
        };
        const waitForPlanning = async (options = {}) => {
            const seq = ++planningWaitSeq;
            subscribeToSession();
            let current = session;
            let polls = 0;
            while (_autoProtocolPlanning(current) && view.dialog.isConnected && seq === planningWaitSeq) {
                await _autoProtocolSleep(sessionSubscription ? 30000 : Math.min(10000, polls < 10 ? 3000 : 5000));
                if (!view.dialog.isConnected || seq !== planningWaitSeq) return session;
                current = await API.getProtocolAutoSession(current.session_id);
                renderSessionState(current, options);
                subscribeToSession();
                polls += 1;
            }
            return session;
        };
        const handlePlanningError = async (err, options = {}) => {
            if (!_autoProtocolPlanningError(err)) return false;
            try {
                await refreshSessionState(options);
            } catch (refreshErr) {
                console.warn('Failed to refresh Auto Protocol session after planning error', refreshErr);
            }
            UI.notify('Auto Protocol is still designing. The dialog reattached to the active planner job.', 'warning', { timeout: 0 });
            return true;
        };
        const ensureSessionReadyForAction = async (options = {}) => {
            if (!session?.session_id) return false;
            await refreshSessionState(options);
            if (_autoProtocolPlanning(session)) {
                UI.notify('Auto Protocol is still designing. Wait for planning to finish before applying, publishing, or running.', 'warning', { timeout: 0 });
                return false;
            }
            return true;
        };
        revise.addEventListener('input', syncActions);
        cancelBtn.addEventListener('click', () => view.close());
        queueBtn.addEventListener('click', () => {
            if (!session?.session_id) return;
            view.close();
            Router.navigate(`/ui/design-sessions?session_id=${encodeURIComponent(session.session_id)}`);
        });
        const explicitSessionId = String(sessionId || '').trim();
        const implicitSessionId = ignoreRememberedSession ? '' : (activeAutoProtocolSessionId || _rememberedAutoProtocolSessionId());
        const rememberedSessionId = explicitSessionId || implicitSessionId;
        if (rememberedSessionId) {
            void attachSession(rememberedSessionId, {
                requirePlanning: !explicitSessionId,
                rememberedContext: explicitSessionId
                    ? null
                    : {
                        mode: isRevision ? 'revise' : 'create',
                        targetProtocolId: isRevision ? currentProtocolId : '',
                    },
            }).catch((err) => {
                console.warn('Could not reattach Auto Protocol session', err);
            });
        }
        const runGenerate = async () => {
            const text = requirement.value.trim();
            if (!text) {
                status.textContent = 'Describe what the protocol should accomplish.';
                return;
            }
            _setAutoProtocolButtonBusy(generateBtn, true);
            _setAutoProtocolStatus(status, 'Designing protocol…');
            UI.reconcileChildren(preview, [_autoProtocolProgressEl()]);
            try {
                session = await API.createProtocolAutoSession({
                    mode: isRevision ? 'revise' : 'create',
                    surface: 'registry',
                    target_protocol_id: isRevision ? currentProtocolId : '',
                    requirement_text: text,
                    constraints_text: constraints.value.trim(),
                    resource_refs: resourcePicker.resourceRefs(),
                    workspace_ref: '',
                    preferred_design_agent_id: plannerField.select.value,
                });
                renderSessionState(session, { progressMessage: 'Designing protocol…' });
                if (_autoProtocolPlanning(session)) {
                    await waitForPlanning({
                        progressMessage: 'Designing protocol…',
                        readyMessage: 'Review the generated structure. Apply it to continue in the normal editor.',
                    });
                } else {
                    renderSessionState(session, { readyMessage: 'Review the generated structure. Apply it to continue in the normal editor.' });
                }
                syncActions();
            } catch (err) {
                const attachedSessionId = _autoProtocolErrorSessionId(err);
                if (attachedSessionId) {
                    try {
                        await attachSession(attachedSessionId);
                    } catch (attachErr) {
                        console.warn('Could not attach partially-created Auto Protocol session', attachErr);
                    }
                }
                const retry = (session?.session_id || attachedSessionId)
                    ? () => refreshSessionState()
                    : () => runGenerate();
                _setAutoProtocolDialogError(preview, status, 'Failed to generate protocol', err, retry);
            }
            _setAutoProtocolButtonBusy(generateBtn, false);
            syncActions();
        };
        generateBtn.addEventListener('click', () => void runGenerate());
        const runRevise = async () => {
            if (!session?.session_id || !revise.value.trim()) return;
            _setAutoProtocolButtonBusy(reviseBtn, true);
            _setAutoProtocolStatus(status, 'Updating generated protocol…');
            try {
                session = await API.reviseProtocolAutoSession(session.session_id, {
                    mode: 'revise',
                    surface: 'registry',
                    target_protocol_id: isRevision ? currentProtocolId : '',
                    requirement_text: revise.value.trim(),
                    constraints_text: constraints.value.trim(),
                    resource_refs: resourcePicker.resourceRefs(),
                    preferred_design_agent_id: plannerField.select.value,
                });
                renderSessionState(session, { progressMessage: 'Updating generated protocol…' });
                if (_autoProtocolPlanning(session)) {
                    await waitForPlanning({
                        progressMessage: 'Updating generated protocol…',
                        readyMessage: 'Updated. Review the changes, then apply the draft.',
                    });
                } else {
                    renderSessionState(session, { readyMessage: 'Updated. Review the changes, then apply the draft.' });
                }
                revise.value = '';
                syncActions();
            } catch (err) {
                const attachedSessionId = _autoProtocolErrorSessionId(err);
                if (attachedSessionId) {
                    try {
                        await attachSession(attachedSessionId, { progressMessage: 'Updating generated protocol…', readyMessage: 'Updated. Review the changes, then apply the draft.' });
                    } catch (attachErr) {
                        console.warn('Could not attach partially-revised Auto Protocol session', attachErr);
                    }
                }
                const retry = (session?.session_id || attachedSessionId)
                    ? () => refreshSessionState({ progressMessage: 'Updating generated protocol…', readyMessage: 'Updated. Review the changes, then apply the draft.' })
                    : () => runRevise();
                _setAutoProtocolDialogError(preview, status, 'Failed to modify generated protocol', err, retry);
            }
            _setAutoProtocolButtonBusy(reviseBtn, false);
            syncActions();
        };
        reviseBtn.addEventListener('click', () => void runRevise());
        const runApply = async () => {
            if (!session?.session_id) return;
            _setAutoProtocolButtonBusy(applyBtn, true);
            _setAutoProtocolStatus(status, 'Applying generated draft…');
            try {
                if (!await ensureSessionReadyForAction()) {
                    _setAutoProtocolButtonBusy(applyBtn, false);
                    syncActions();
                    return;
                }
                const applied = await API.applyProtocolAutoSession(session.session_id);
                session = applied;
                UI.reconcileChildren(preview, [_autoProtocolSummaryEl(session)]);
                if (await _adoptAutoProtocolSession(applied)) {
                    view.close();
                    UI.notify('Auto Protocol draft applied.', 'success');
                    return;
                }
                _setAutoProtocolStatus(status, 'Draft applied, but the protocol id was not returned.');
            } catch (err) {
                if (await handlePlanningError(err)) {
                    _setAutoProtocolButtonBusy(applyBtn, false);
                    syncActions();
                    return;
                }
                _setAutoProtocolDialogError(preview, status, 'Failed to apply generated protocol', err, () => runApply());
            }
            _setAutoProtocolButtonBusy(applyBtn, false);
            syncActions();
        };
        applyBtn.addEventListener('click', () => void runApply());
        const runPublish = async () => {
            if (!session?.session_id) return;
            _setAutoProtocolButtonBusy(publishBtn, true);
            _setAutoProtocolStatus(status, 'Publishing generated protocol…');
            try {
                if (!await ensureSessionReadyForAction()) {
                    _setAutoProtocolButtonBusy(publishBtn, false);
                    syncActions();
                    return;
                }
                session = await API.publishProtocolAutoSession(session.session_id);
                UI.reconcileChildren(preview, [_autoProtocolSummaryEl(session)]);
                await _adoptAutoProtocolSession(session);
                _setAutoProtocolStatus(status, 'Published. You can run it now or continue editing a draft revision later.');
                UI.notify('Auto Protocol published.', 'success');
                syncActions();
            } catch (err) {
                if (await handlePlanningError(err)) {
                    _setAutoProtocolButtonBusy(publishBtn, false);
                    syncActions();
                    return;
                }
                _setAutoProtocolDialogError(preview, status, 'Failed to publish generated protocol', err, () => runPublish());
            }
            _setAutoProtocolButtonBusy(publishBtn, false);
            syncActions();
        };
        publishBtn.addEventListener('click', () => void runPublish());
        const runStart = async () => {
            if (!session?.session_id) return;
            _setAutoProtocolButtonBusy(runBtn, true);
            _setAutoProtocolStatus(status, 'Publishing and starting the run…');
            try {
                if (!await ensureSessionReadyForAction()) {
                    _setAutoProtocolButtonBusy(runBtn, false);
                    syncActions();
                    return;
                }
                session = await API.runProtocolAutoSession(session.session_id, {
                    origin_channel: 'registry',
                    idempotency_key: _autoProtocolRunAttemptKey(session.session_id),
                });
                UI.reconcileChildren(preview, [_autoProtocolSummaryEl(session)]);
                await _adoptAutoProtocolSession(session);
                const runId = _autoProtocolRunId(session);
                view.close();
                if (runId) {
                    UI.notify('Protocol run started.', 'success');
                    Router.navigate(`/ui/runs?run_id=${encodeURIComponent(runId)}`);
                    return;
                }
                UI.notify('Protocol run started, but no run id was returned.', 'success');
            } catch (err) {
                if (await handlePlanningError(err)) {
                    _setAutoProtocolButtonBusy(runBtn, false);
                    syncActions();
                    return;
                }
                _setAutoProtocolDialogError(preview, status, 'Failed to run generated protocol', err, () => runStart());
            }
            _setAutoProtocolButtonBusy(runBtn, false);
            syncActions();
        };
        runBtn.addEventListener('click', () => void runStart());
        syncActions();
    }

    async function _createTemplateDraft(template) {
        const templateSlug = String(template?.slug || '').trim();
        if (!templateSlug) return;
        try {
            const result = await API.createProtocolDraft({
                source_kind: 'template',
                template_slug: templateSlug,
            });
            currentProtocolId = result.protocol?.protocol_id || '';
            templateChooserMode = '';
            _applyServerDetail(result);
            _writeState({ push: true });
            await loadProtocols({ quiet: true });
            render();
            UI.notify('Protocol draft created from template.', 'success');
        } catch (err) {
            UI.reportError('Failed to create a template-based protocol draft', err, {
                context: 'Template protocol draft create failed',
            });
        }
    }

    async function _openTemplateReviewDialog(template) {
        const templateSlug = String(template?.slug || '').trim();
        if (!templateSlug) return;
        const body = document.createElement('div');
        body.className = 'conversation-management-form';
        body.appendChild(UI.renderEmptyState('Loading template…', true));
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn';
        cancelBtn.textContent = 'Cancel';
        const createBtn = document.createElement('button');
        createBtn.type = 'button';
        createBtn.className = 'btn btn-primary';
        createBtn.textContent = 'Create editable draft';
        createBtn.disabled = true;
        const view = UI.showDialog('Review template', body, {
            actions: [cancelBtn, createBtn],
            maxWidth: '780px',
        });
        cancelBtn.addEventListener('click', () => view.close());
        try {
            const documentRecord = await API.getProtocolTemplate(templateSlug);
            const metadata = documentRecord?.metadata || {};
            const stages = Array.isArray(documentRecord?.stages) ? documentRecord.stages : [];
            const artifacts = Array.isArray(documentRecord?.artifacts) ? documentRecord.artifacts : [];
            body.textContent = '';
            const summary = document.createElement('p');
            summary.className = 'quiet-note';
            summary.textContent = `${metadata.display_name || template?.display_name || templateSlug} will be copied into a separate editable protocol. The template is not changed; the new protocol can be changed, published, and run from the UI.`;
            body.appendChild(summary);
            const stageList = document.createElement('div');
            stageList.className = 'protocol-lineage-list';
            UI.reconcileChildren(stageList, stages.slice(0, 8).map((stage, index) => UI.renderListRow({
                label: `${index + 1}. ${stage.display_name || stage.stage_key || 'Stage'}`,
                sublabel: [
                    stage.stage_kind || 'work',
                    (stage.outputs || []).length ? `${stage.outputs.length} output${stage.outputs.length === 1 ? '' : 's'}` : 'no declared outputs',
                ].join(' · '),
                badgeText: stage.participant_key || '',
            })));
            const stageHead = document.createElement('div');
            stageHead.className = 'detail-label';
            stageHead.textContent = `Stages (${stages.length})`;
            body.appendChild(stageHead);
            body.appendChild(stageList);
            const artifactList = document.createElement('div');
            artifactList.className = 'task-artifact-list';
            UI.reconcileChildren(artifactList, artifacts.slice(0, 10).map((artifact) => UI.createArtifactListRow({
                label: artifact.description || artifact.artifact_key || 'Artifact',
                sublabelParts: [
                    artifact.path || artifact.location || '',
                    artifact.kind || '',
                    artifact.verify ? 'verified output' : '',
                ],
                badgeText: artifact.artifact_key || '',
            })));
            const artifactHead = document.createElement('div');
            artifactHead.className = 'detail-label';
            artifactHead.textContent = `Artifacts (${artifacts.length})`;
            body.appendChild(artifactHead);
            body.appendChild(artifactList);
            if (artifacts.length > 10 || stages.length > 8) {
                const note = document.createElement('p');
                note.className = 'quiet-note';
                note.textContent = 'Only the first items are shown here; the full draft opens after creation.';
                body.appendChild(note);
            }
            createBtn.disabled = false;
            createBtn.addEventListener('click', async () => {
                createBtn.disabled = true;
                await _createTemplateDraft(template || { slug: templateSlug });
                view.close();
            });
        } catch (err) {
            body.textContent = '';
            body.appendChild(UI.createErrorCard(`Failed to load template: ${err.message}`, () => _openTemplateReviewDialog(template)));
        }
    }

    function _openTemplateChooser() {
        currentProtocolId = '';
        currentProtocol = null;
        protocolDetailLoading = false;
        templateChooserMode = 'template';
        _writeState({ push: true });
        render();
    }

    function _closeTemplateChooser() {
        templateChooserMode = '';
        _writeState({ push: true });
        render();
    }

    function _bindTemplateChooserControls(root) {
        const chooser = root?.querySelector?.('[data-testid="protocol-template-chooser"]');
        if (!(chooser instanceof Element)) return;

        const blank = chooser.querySelector('[data-protocol-template-chooser-action="blank"]');
        if (blank instanceof HTMLButtonElement) {
            blank.onclick = () => void _createBlankDraft();
        }

        const close = chooser.querySelector('[data-protocol-template-chooser-action="close"]');
        if (close instanceof HTMLButtonElement) {
            close.onclick = _closeTemplateChooser;
        }

        chooser.querySelectorAll('[data-protocol-template-slug]').forEach((button) => {
            if (!(button instanceof HTMLButtonElement)) return;
            const templateSlug = String(button.dataset.protocolTemplateSlug || '').trim();
            button.onclick = () => {
                const template = (Array.isArray(protocolTemplates) ? protocolTemplates : [])
                    .find((item) => String(item?.slug || '').trim() === templateSlug);
                void _openTemplateReviewDialog(template || { slug: templateSlug });
            };
        });
    }

    async function _publishTemplateNow() {
        if (_blockConflictAction('Publish as template')) return;
        if (!currentProtocolId) return;
        if (saveState.state === 'editing' || saveState.state === 'saving') {
            const saved = await _autosave();
            if (!saved) return;
        }
        _clearAutosaveTimer();
        saveState = { state: 'saving', lastSavedAt: saveState.lastSavedAt, error: '' };
        _syncLifecycleChip();
        const result = await API.createProtocolTemplate({ source_protocol_id: currentProtocolId });
        await loadAuthoringOptions();
        await loadProtocols({ quiet: true });
        saveState = { state: 'saved', lastSavedAt: new Date().toISOString(), error: '' };
        render();
        UI.notify(`Template published: ${result?.protocol?.display_name || result?.protocol?.slug || 'Reusable template'}.`, 'success');
    }

    // -------------------------------------------------------------------
    // Rehearsal
    // -------------------------------------------------------------------
    function _stopRehearsalPolling() {
        if (rehearsal.pollTimer) {
            clearTimeout(rehearsal.pollTimer);
            rehearsal.pollTimer = 0;
        }
    }

    async function _refreshRehearsalSessions() {
        if (!rehearsal.runId) return;
        const refreshRunId = rehearsal.runId;
        const refreshSeq = (rehearsal.refreshSeq || 0) + 1;
        rehearsal.refreshSeq = refreshSeq;
        try {
            const [sessionsResp, scenariosResp, runDetail] = await Promise.all([
                API.listRehearsalSessions(refreshRunId),
                API.listProtocolScenarios({ protocol_id: currentProtocolId || '' }),
                API.getProtocolRun(refreshRunId),
            ]);
            if (refreshSeq !== rehearsal.refreshSeq || refreshRunId !== rehearsal.runId) return;
            rehearsal.sessions = Array.isArray(sessionsResp?.sessions) ? sessionsResp.sessions : [];
            rehearsal.scenarios = Array.isArray(scenariosResp?.scenarios) ? scenariosResp.scenarios : [];
            rehearsal.runDetail = runDetail || null;
            const activeDrafts = {};
            (rehearsal.sessions || []).forEach((session) => {
                const routedTaskId = String(session?.routed_task_id || '').trim();
                if (routedTaskId && rehearsal.drafts[routedTaskId]) {
                    activeDrafts[routedTaskId] = rehearsal.drafts[routedTaskId];
                }
            });
            rehearsal.drafts = activeDrafts;
            render();
        } catch (err) {
            if (refreshSeq === rehearsal.refreshSeq && refreshRunId === rehearsal.runId) {
                UI.reportError('Failed to refresh rehearsal state', err);
            }
        } finally {
            if (refreshSeq === rehearsal.refreshSeq && refreshRunId === rehearsal.runId && rehearsal.runId) {
                _stopRehearsalPolling();
                rehearsal.pollTimer = setTimeout(() => { void _refreshRehearsalSessions(); }, 1500);
            }
        }
    }

    async function _startRehearsal() {
        if (_blockConflictAction('Rehearsal')) return;
        if (!currentProtocolId) return;
        const created = await API.createProtocolRun({
            protocol_id: currentProtocolId,
            is_rehearsal: true,
            entry_authority_ref: 'rehearsal',
        });
        rehearsal.runId = String(created?.run?.protocol_run_id || '');
        rehearsal.sessions = [];
        rehearsal.scenarios = [];
        rehearsal.runDetail = null;
        rehearsal.refreshSeq += 1;
        rehearsal.drafts = {};
        if (!rehearsal.runId) {
            UI.notify('Rehearsal could not be started.', 'error');
            return;
        }
        editorMode = { kind: 'rehearse', sourceStageKey: '', decision: '' };
        UI.notify('Rehearsal started — dry run, external transports gated.', 'success');
        render();
        await _refreshRehearsalSessions();
    }

    function _defaultProtocolRunAgentId() {
        const agents = _authoringAssignableAgents();
        const preferred = agents.find((agent) => {
            const execution = String(agent?.execution_state || agent?.execution_status || '').trim().toLowerCase();
            const connectivity = String(agent?.connectivity_state || '').trim().toLowerCase();
            return connectivity === 'connected' && !['faulted', 'stopped', 'disconnected'].includes(execution);
        }) || agents[0] || _availableAuthoringAgents()[0] || null;
        return String(preferred?.agent_id || '').trim();
    }

    function _protocolRunLaunchFields() {
        const fields = draft?.document?.metadata?.run_inputs;
        return Array.isArray(fields) && fields.length
            ? fields
            : Kit.protocolRunLaunchFields();
    }

    function _openRunProtocolDialog() {
        if (_blockConflictAction('Run protocol')) return;
        if (!currentProtocolId) return;
        const agents = _authoringAssignableAgents();
        const defaultAgentId = _defaultProtocolRunAgentId();
        const body = document.createElement('div');
        body.className = 'conversation-management-form';

        const summary = document.createElement('p');
        summary.className = 'quiet-note';
        summary.textContent = 'Start a real run from the latest published version. Rehearsal is the dry-run path; this dispatches work to runtime agents and records produced artifacts.';
        body.appendChild(summary);

        if (saveState.state === 'editing' || saveState.state === 'saving') {
            const draftNote = document.createElement('p');
            draftNote.className = 'quiet-note';
            draftNote.textContent = 'You have unpublished draft edits. This run uses the latest published protocol, not unsaved or unpublished changes.';
            body.appendChild(draftNote);
        }

        const agentLabel = document.createElement('label');
        agentLabel.className = 'kit-details-field';
        const agentTitle = document.createElement('span');
        agentTitle.className = 'kit-details-label';
        agentTitle.textContent = 'Entry agent';
        agentLabel.appendChild(agentTitle);
        const agentSelect = document.createElement('select');
        agentSelect.className = 'input';
        agentSelect.setAttribute('aria-label', 'Entry agent');
        if (!agents.length) {
            const option = document.createElement('option');
            option.value = '';
            option.textContent = 'No connected agents available';
            agentSelect.appendChild(option);
            agentSelect.disabled = true;
        } else {
            agents.forEach((agent) => {
                const option = document.createElement('option');
                option.value = String(agent.agent_id || '');
                option.textContent = UI.visibleLabel(agent.display_name, agent.slug || agent.agent_id, 'Agent');
                if (String(agent.agent_id || '') === defaultAgentId) option.selected = true;
                agentSelect.appendChild(option);
            });
        }
        agentLabel.appendChild(agentSelect);
        const agentHelp = document.createElement('span');
        agentHelp.className = 'kit-details-help';
        agentHelp.textContent = 'The entry agent owns the root conversation for this run. Stage assignment rules still decide which agent receives each step.';
        agentLabel.appendChild(agentHelp);
        body.appendChild(agentLabel);

        const artifactContractPanel = Kit.protocolArtifactContractPanel(draft.document);
        if (artifactContractPanel) body.appendChild(artifactContractPanel);

        const launchForm = Kit.protocolRunLaunchForm({
            values: {
                problem_statement: draft.description,
            },
            fields: _protocolRunLaunchFields(),
            includeWorkspace: true,
        });
        body.appendChild(launchForm.element);
        const resourcePicker = Kit.resourceAttachmentPicker({
            label: 'Attach run files',
            help: 'Add input files for this run.',
            sourceRef: `protocol:${currentProtocolId}:run`,
            relation: 'input',
        });
        body.appendChild(resourcePicker.element);

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn';
        cancelBtn.textContent = 'Cancel';
        const startBtn = document.createElement('button');
        startBtn.type = 'button';
        startBtn.className = 'btn btn-primary';
        startBtn.textContent = 'Start run';
        startBtn.disabled = !agents.length;

        const view = UI.showDialog('Run protocol', body, {
            actions: [cancelBtn, startBtn],
            maxWidth: '720px',
            initialFocus: launchForm.focusTarget,
        });
        cancelBtn.addEventListener('click', () => view.close());
        startBtn.addEventListener('click', async () => {
            const entryAgentId = String(agentSelect.value || '').trim();
            const values = launchForm.readValues();
            if (!entryAgentId || !values.problem_statement) {
                UI.notify('Choose an entry agent and describe what this run should accomplish.', 'error');
                return;
            }
            startBtn.disabled = true;
            try {
                const constraints = {};
                Object.keys(values).forEach((key) => {
                    if (['problem_statement', 'workspace_ref'].includes(key)) return;
                    if (String(values[key] || '').trim()) constraints[key] = String(values[key] || '').trim();
                });
                const created = await API.createProtocolRun({
                    protocol_id: currentProtocolId,
                    entry_agent_id: entryAgentId,
                    origin_channel: 'registry',
                    workspace_ref: String(values.workspace_ref || ''),
                    problem_statement: String(values.problem_statement || ''),
                    resource_refs: resourcePicker.resourceRefs(),
                    constraints_json: constraints,
                });
                const runId = String(created?.run?.protocol_run_id || '').trim();
                view.close();
                if (runId) {
                    UI.notify('Protocol run started.', 'success');
                    Router.navigate(`/ui/runs?run_id=${encodeURIComponent(runId)}`);
                } else {
                    UI.notify('Protocol run started, but no run id was returned.', 'success');
                }
            } catch (err) {
                UI.reportError('Failed to start protocol run', err, { context: 'Protocol authoring run launch failed' });
                startBtn.disabled = false;
            }
        });
    }

    function _updateRehearsalDraft({ routedTaskId, responseText, decision, decisionSummary, scenarioId, artifactContents = {} } = {}) {
        const taskId = String(routedTaskId || '').trim();
        if (!taskId) return;
        rehearsal.drafts = {
            ...(rehearsal.drafts || {}),
            [taskId]: {
                responseText: String(responseText || ''),
                decision: String(decision || ''),
                decisionSummary: String(decisionSummary || ''),
                scenarioId: String(scenarioId || ''),
                artifactContents: artifactContents && typeof artifactContents === 'object'
                    ? { ...artifactContents }
                    : {},
            },
        };
    }

    async function _respondRehearsal({ routedTaskId, responseText, decision, decisionSummary, artifactContents = [], stageKey, participantKey }) {
        if (!rehearsal.runId || !routedTaskId) return;
        try {
            await API.respondRehearsalSession(rehearsal.runId, {
                routed_task_id: routedTaskId,
                response_text: String(responseText || ''),
                decision: String(decision || ''),
                decision_summary: String(decisionSummary || ''),
                artifact_contents: Array.isArray(artifactContents) ? artifactContents : [],
                stage_key: stageKey || '',
                participant_key: participantKey || '',
            });
            if (rehearsal.drafts[String(routedTaskId || '')]) {
                const nextDrafts = { ...(rehearsal.drafts || {}) };
                delete nextDrafts[String(routedTaskId || '')];
                rehearsal.drafts = nextDrafts;
            }
            await _refreshRehearsalSessions();
        } catch (err) {
            UI.reportError('Failed to submit rehearsal response', err);
        }
    }

    cleanups.add(_stopRehearsalPolling);

    // -------------------------------------------------------------------
    // Details panel field commits
    // -------------------------------------------------------------------
    function _commitOverview(_target, key, value) {
        if (key === 'display_name') {
            draft.display_name = String(value || '');
            if (!draft.slug) draft.slug = _slugSuggestion(draft.display_name);
        } else if (key === 'slug') {
            draft.slug = _slugSuggestion(value);
        } else if (key === 'description') {
            draft.description = String(value || '');
        } else if (key === 'single_active_writer') {
            draft.document.policies = Object.assign({}, draft.document.policies || {}, { single_active_writer: Boolean(value) });
        } else if (key === 'max_review_rounds') {
            draft.document.policies = Object.assign({}, draft.document.policies || {}, {
                max_review_rounds: Number.parseInt(String(value || '5'), 10) || 5,
            });
        }
        _scheduleAutosave();
        _syncLifecycleHeaderInputs();
        render();
    }

    function _historySnapshot() {
        return {
            draft: {
                slug: draft.slug,
                display_name: draft.display_name,
                description: draft.description,
                document: _cloneDoc(draft.document),
            },
            selection: { ...selection },
        };
    }

    function _pushHistory() {
        documentHistory.undo.push(_historySnapshot());
        if (documentHistory.undo.length > 40) {
            documentHistory.undo.shift();
        }
        documentHistory.redo = [];
    }

    function _restoreHistory(direction) {
        const source = direction === 'redo' ? documentHistory.redo : documentHistory.undo;
        const target = direction === 'redo' ? documentHistory.undo : documentHistory.redo;
        const snapshot = source.pop();
        if (!snapshot) return;
        target.push(_historySnapshot());
        draft = {
            slug: String(snapshot.draft.slug || ''),
            display_name: String(snapshot.draft.display_name || ''),
            description: String(snapshot.draft.description || ''),
            document: _cloneDoc(snapshot.draft.document),
        };
        selection = _repairSelection(snapshot.selection, draft.document);
        _resetEditorMode();
        _scheduleAutosave();
        render();
    }

    function _stageTransitionId(stageKey, decision) {
        return `${String(stageKey || '').trim()}::${String(decision || '').trim().toLowerCase()}`;
    }

    function _transitionEntries(doc) {
        const entries = [];
        (doc.stages || []).forEach((stage) => {
            const transitions = stage.transitions || {};
            Object.entries(transitions).forEach(([decision, target]) => {
                const decisionKey = String(decision || '').trim().toLowerCase();
                const targetKey = String(target || '').trim();
                if (!decisionKey || !targetKey) return;
                entries.push({
                    id: _stageTransitionId(stage.stage_key, decisionKey),
                    from_stage_key: String(stage.stage_key || ''),
                    decision: decisionKey,
                    target_key: targetKey,
                });
            });
        });
        return entries;
    }

    function _rewriteKeyReferences(doc, kind, fromKey, toKey) {
        const sourceKey = String(fromKey || '').trim();
        const nextKey = String(toKey || '').trim();
        if (!sourceKey || !nextKey || sourceKey === nextKey) return;
        if (kind === 'participant') {
            doc.stages = (doc.stages || []).map((stage) => (
                String(stage.participant_key || '') === sourceKey
                    ? { ...stage, participant_key: nextKey }
                    : stage
            ));
            return;
        }
        if (kind === 'stage') {
            doc.stages = (doc.stages || []).map((stage) => {
                const transitions = Object.fromEntries(
                    Object.entries(stage.transitions || {}).map(([decision, target]) => [
                        decision,
                        String(target || '') === sourceKey ? nextKey : target,
                    ]),
                );
                return { ...stage, transitions };
            });
            return;
        }
        if (kind === 'artifact') {
            doc.stages = (doc.stages || []).map((stage) => ({
                ...stage,
                inputs: (stage.inputs || []).map((item) => (String(item || '') === sourceKey ? nextKey : item)),
                outputs: (stage.outputs || []).map((item) => (String(item || '') === sourceKey ? nextKey : item)),
            }));
        }
    }

    function _nextAvailableKey(items, field, preferred, currentKey = '') {
        const normalized = _slugSuggestion(preferred) || String(field || '').replace(/_key$/, '');
        const current = String(currentKey || '').trim();
        const seen = new Set((items || []).map((item) => String(item?.[field] || '').trim()).filter(Boolean));
        if (current) seen.delete(current);
        if (!seen.has(normalized)) return normalized;
        let index = 2;
        while (seen.has(`${normalized}_${index}`)) {
            index += 1;
        }
        return `${normalized}_${index}`;
    }

    function _commitDocument(nextDoc, { nextSelection = selection, pushHistory = true } = {}) {
        if (pushHistory) _pushHistory();
        draft.document = nextDoc;
        selection = _repairSelection(nextSelection, nextDoc);
        _scheduleAutosave();
        render();
    }

    function _commitNodeField(kind, nodeKey, key, value) {
        const plural = kind + 's';
        const doc = _cloneDoc(draft.document);
        const items = Array.isArray(doc[plural]) ? doc[plural] : [];
        const idField = kind === 'participant' ? 'participant_key' : kind === 'stage' ? 'stage_key' : 'artifact_key';
        const idx = items.findIndex((item) => String(item[idField] || '') === nodeKey);
        if (idx < 0) return;
        const next = Object.assign({}, items[idx]);
        if (kind === 'stage' && key === 'selector_kind') {
            next.selector = _selectorFromFields(value, next.selector?.value || '', next.selector?.preferred_agent_id || '');
        } else if (kind === 'stage' && key === 'selector_value') {
            next.selector = _selectorFromFields(next.selector?.kind || '', value, next.selector?.preferred_agent_id || '');
        } else if (kind === 'stage' && key === 'selector_preferred_agent_id') {
            next.selector = _selectorFromFields(next.selector?.kind || '', next.selector?.value || '', value);
        } else if (key === 'inputs' || key === 'outputs') {
            next[key] = Array.isArray(value) ? value.map((item) => String(item || '').trim()).filter(Boolean) : [];
            if (kind === 'stage') {
                Object.assign(next, _normalizeStageWriteAccess(next));
            }
        } else if (key === 'max_rounds' || key === 'timeout_seconds') {
            next[key] = Number.parseInt(String(value || '0'), 10) || 0;
        } else if (key === 'verify') {
            next.verify = Boolean(value);
        } else {
            next[key] = value;
        }
        let nextNodeKey = nodeKey;
        if (key === idField) {
            const rewritten = _slugSuggestion(value) || nodeKey;
            next[idField] = rewritten;
            _rewriteKeyReferences(doc, kind, nodeKey, rewritten);
            nextNodeKey = rewritten;
        }
        items[idx] = next;
        doc[plural] = items;
        _commitDocument(doc, {
            nextSelection: { sectionKey: plural, nodeKey: String(nextNodeKey || '') },
        });
    }

    function _commitPendingStageField(_target, key, value) {
        if (key === 'display_name') {
            pendingStage.display_name = String(value || '');
            pendingStage.stage_key = _slugSuggestion(pendingStage.display_name);
        } else if (key === 'stage_key') {
            pendingStage.stage_key = _slugSuggestion(value);
        } else if (key === 'stage_kind') {
            pendingStage.stage_kind = String(value || 'work') || 'work';
        } else if (key === 'participant_key') {
            pendingStage.participant_key = String(value || '');
            if (String(value || '') !== '__new__') {
                pendingStage.role_display_name = '';
                pendingStage.role_participant_key = '';
                pendingStage.role_instructions = '';
            }
        } else if (key === 'selector_mode') {
            pendingStage.selector_mode = _selectorModeFromKind(value, pendingStage.selector_mode || 'unassigned');
        } else if (key === 'selector_kind' || key === 'selector_value' || key === 'selector_preferred_agent_id') {
            pendingStage[key] = String(value || '');
        } else if (key === 'role_display_name') {
            pendingStage.role_display_name = String(value || '');
            if (!String(pendingStage.role_participant_key || '').trim()) {
                pendingStage.role_participant_key = _slugSuggestion(pendingStage.role_display_name);
            }
        } else if (key === 'role_participant_key') {
            pendingStage.role_participant_key = _slugSuggestion(value);
        } else if (key === 'role_instructions') {
            pendingStage.role_instructions = String(value || '');
        } else if (key === 'instructions') {
            pendingStage.instructions = String(value || '');
        } else if (key === 'inputs' || key === 'outputs') {
            pendingStage[key] = Array.isArray(value) ? value.map((item) => String(item || '').trim()).filter(Boolean) : [];
        } else if (key === 'max_rounds' || key === 'timeout_seconds') {
            pendingStage[key] = Number.parseInt(String(value || '0'), 10) || 0;
        }
        if (['participant_key', 'selector_mode', 'selector_kind', 'selector_value', 'selector_preferred_agent_id', 'stage_kind'].includes(String(key || ''))) {
            queueMicrotask(() => render());
        }
    }

    function _commitPendingStageSelector(selectorKind, selectorValue, selectorPreferredAgentId = '') {
        const normalizedKind = String(selectorKind || '').trim().toLowerCase();
        const keepNeededSkillMode = normalizedKind === 'skill'
            && String(pendingStage.selector_mode || '') === 'new_skill';
        if (normalizedKind && !keepNeededSkillMode) {
            pendingStage.selector_mode = _selectorModeFromKind(selectorKind, pendingStage.selector_mode || 'skill');
        }
        pendingStage.selector_kind = String(selectorKind || '');
        pendingStage.selector_value = String(selectorValue || '');
        pendingStage.selector_preferred_agent_id = String(selectorPreferredAgentId || '');
        queueMicrotask(() => render());
    }

    function _syncPendingStageFromMountedEditor() {
        const editor = contentEl.querySelector('.kit-stage-editor-grid[data-pending-stage-editor="true"]')
            || contentEl.querySelector('.kit-stage-editor-grid');
        if (!(editor instanceof Element)) return;
        const readValue = (selector, fallback = '') => {
            const control = editor.querySelector(selector);
            if (control instanceof HTMLInputElement || control instanceof HTMLTextAreaElement || control instanceof HTMLSelectElement) {
                return String(control.value || '');
            }
            if (control instanceof Element && control.dataset?.selectorPillGroup === 'true') {
                const pressed = control.querySelector('.quickstart-chip[aria-pressed="true"]');
                return pressed instanceof HTMLElement
                    ? String(pressed.dataset.value || '')
                    : String(control.dataset.value || '');
            }
            if (control instanceof Element && control.dataset?.value !== undefined) {
                return String(control.dataset.value || '');
            }
            return String(fallback || '');
        };
        pendingStage.display_name = readValue('#kit-details-display_name', pendingStage.display_name);
        pendingStage.participant_key = readValue('#kit-details-participant_key', pendingStage.participant_key);
        pendingStage.stage_kind = readValue('#kit-details-stage_kind', pendingStage.stage_kind || 'work') || 'work';
        pendingStage.role_display_name = readValue('#kit-details-role_display_name', pendingStage.role_display_name);
        pendingStage.role_participant_key = _slugSuggestion(readValue('#kit-details-role_participant_key', pendingStage.role_participant_key));
        pendingStage.role_instructions = readValue('#kit-details-role_instructions', pendingStage.role_instructions);
        pendingStage.instructions = readValue('#kit-details-instructions', pendingStage.instructions);
        pendingStage.max_rounds = Number.parseInt(readValue('#kit-details-max_rounds', pendingStage.max_rounds || 0) || '0', 10) || 0;
        pendingStage.timeout_seconds = Number.parseInt(readValue('#kit-details-timeout_seconds', pendingStage.timeout_seconds || 0) || '0', 10) || 0;
        const activeModeButton = editor.querySelector('.segmented-control[aria-label="Assignment mode"] .segmented-control-btn.active');
        pendingStage.selector_mode = _selectorModeFromKind(
            activeModeButton instanceof HTMLButtonElement ? activeModeButton.dataset.value || '' : pendingStage.selector_mode,
            pendingStage.selector_mode || 'unassigned',
        );
        const advancedKind = readValue('select[aria-label="Custom selector type"]', pendingStage.selector_kind);
        const selector = _selectorFromEditorFields({
            requiredSkill: readValue(
                '[aria-label="Required skill"]',
                pendingStage.selector_kind === 'skill' ? pendingStage.selector_value : '',
            ),
            pinnedAgent: readValue('[aria-label="Pin matching agent (optional)"]')
                || readValue('[aria-label="Pinned agent"]')
                || readValue('[aria-label="Agent"]', _selectorAgentControlValue(
                    pendingStage.selector_kind === 'agent'
                        ? pendingStage.selector_value
                        : pendingStage.selector_preferred_agent_id,
                )),
            neededSkill: readValue(
                '[aria-label="Needed skill"]',
                pendingStage.selector_mode === 'new_skill' && pendingStage.selector_kind === 'skill'
                    ? pendingStage.selector_value
                    : '',
            ),
            advancedKind,
            advancedValue: advancedKind === 'role'
                ? (readValue('[aria-label="Choose runtime role tag"]', pendingStage.selector_value) || readValue('[aria-label="Custom value"]', pendingStage.selector_value))
                : readValue('[aria-label="Custom value"]', pendingStage.selector_value),
        });
        pendingStage.selector_kind = String(selector?.kind || '');
        pendingStage.selector_value = String(selector?.value || '');
        pendingStage.selector_preferred_agent_id = String(selector?.preferred_agent_id || '');
    }

    function _bindPendingStageEditorControls(root) {
        if (!(root instanceof Element)) return;
        const bindText = (selector, key) => {
            const control = root.querySelector(selector);
            if (!(control instanceof HTMLInputElement) && !(control instanceof HTMLTextAreaElement)) return;
            if (control.__pendingStageBound === true) return;
            control.__pendingStageBound = true;
            const commit = () => _commitPendingStageField(null, key, control.value);
            control.addEventListener('input', commit);
            control.addEventListener('change', commit);
        };
        const bindSelect = (selector, key) => {
            const control = root.querySelector(selector);
            if (!(control instanceof HTMLSelectElement)) return;
            if (control.__pendingStageBound === true) return;
            control.__pendingStageBound = true;
            control.addEventListener('change', () => _commitPendingStageField(null, key, control.value));
        };
        bindText('#kit-details-display_name', 'display_name');
        bindSelect('#kit-details-participant_key', 'participant_key');
        bindSelect('#kit-details-stage_kind', 'stage_kind');
        bindText('#kit-details-role_display_name', 'role_display_name');
        bindText('#kit-details-role_participant_key', 'role_participant_key');
        bindText('#kit-details-role_instructions', 'role_instructions');
        bindText('#kit-details-instructions', 'instructions');
        bindText('#kit-details-max_rounds', 'max_rounds');
        bindText('#kit-details-timeout_seconds', 'timeout_seconds');
        root.querySelectorAll('.segmented-control[aria-label="Assignment mode"] .segmented-control-btn').forEach((button) => {
            if (!(button instanceof HTMLButtonElement) || button.__pendingStageBound === true) return;
            button.__pendingStageBound = true;
            button.addEventListener('click', () => _commitPendingStageField(null, 'selector_mode', button.dataset.value || ''));
        });
    }

    function _bindStageWorkspacePanelControls(root) {
        if (!(root instanceof Element)) return;
        root.querySelectorAll('.kit-stage-workspace-nav[data-stage-workspace-nav="true"]').forEach((group) => {
            if (!(group instanceof Element) || group.__stageWorkspaceBound === true) return;
            group.__stageWorkspaceBound = true;
            group.addEventListener('click', (event) => {
                const button = event.target instanceof Element
                    ? event.target.closest('.segmented-control-btn')
                    : null;
                if (!(button instanceof HTMLButtonElement) || !group.contains(button)) return;
                const workspaceKey = String(group.dataset.workspaceKey || '').trim();
                const panelKey = String(button.dataset.value || '').trim();
                if (!workspaceKey || !panelKey) return;
                const includeRouting = String(group.dataset.includeRouting || 'true') !== 'false';
                const includeAdvanced = String(group.dataset.includeAdvanced || 'false') === 'true';
                _setStageWorkspacePanelValue(workspaceKey, panelKey, {
                    includeRouting,
                    includeAdvanced,
                });
                render();
            });
        });
    }

    function _commitStageSelector(nodeKey, selectorKind, selectorValue, selectorPreferredAgentId = '') {
        const doc = _cloneDoc(draft.document);
        const items = [...(doc.stages || [])];
        const idx = items.findIndex((item) => String(item.stage_key || '') === String(nodeKey || ''));
        if (idx < 0) return;
        const normalizedKind = String(selectorKind || '').trim().toLowerCase();
        const keepNeededSkillMode = normalizedKind === 'skill'
            && String(stageAssignmentEditor.mode || '') === 'new_skill';
        stageAssignmentEditor = {
            stageKey: String(nodeKey || ''),
            mode: keepNeededSkillMode
                ? 'new_skill'
                : _selectorModeFromKind(selectorKind, stageAssignmentEditor.mode || 'unassigned'),
        };
        const next = Object.assign({}, items[idx], {
            selector: _selectorFromFields(selectorKind, selectorValue, selectorPreferredAgentId),
        });
        items[idx] = next;
        doc.stages = items;
        const nextNodeKey = String(nodeKey || '');
        _commitDocument(doc, {
            nextSelection: { sectionKey: 'stages', nodeKey: nextNodeKey },
        });
    }

    function _pendingStageHasDraftContent(stage = pendingStage) {
        return Boolean(
            String(stage?.display_name || '').trim()
            || String(stage?.stage_key || '').trim()
            || String(stage?.participant_key || '').trim()
            || String(stage?.selector_kind || '').trim()
            || String(stage?.selector_value || '').trim()
            || String(stage?.selector_preferred_agent_id || '').trim()
            || String(stage?.role_display_name || '').trim()
            || String(stage?.role_participant_key || '').trim()
            || String(stage?.role_instructions || '').trim()
            || String(stage?.instructions || '').trim()
            || (Array.isArray(stage?.inputs) && stage.inputs.length)
            || (Array.isArray(stage?.outputs) && stage.outputs.length)
        );
    }

    function _setStageInsertAnchor(sourceStageKey = '', decision = '', { keepDraft = true } = {}) {
        if (!keepDraft) {
            pendingStage = _blankStageDraft();
        }
        editorMode = {
            kind: 'insert-stage',
            sourceStageKey: String(sourceStageKey || ''),
            decision: String(decision || '').trim().toLowerCase(),
            sessionKey: String(++editorSessionNonce),
        };
        render();
    }

    function _showPendingStageInsertChoice(sourceStageKey = '', decision = '') {
        const currentSourceStageKey = String(editorMode.sourceStageKey || '');
        const currentDecision = String(editorMode.decision || '').trim().toLowerCase();
        const body = document.createElement('div');
        body.className = 'kit-selector-editor-note';
        body.textContent = 'You already have an unfinished step draft. Continue it, move it to this position, or discard it and start a new step here.';
        const continueBtn = document.createElement('button');
        continueBtn.type = 'button';
        continueBtn.className = 'btn';
        continueBtn.textContent = 'Continue current draft';
        const moveBtn = document.createElement('button');
        moveBtn.type = 'button';
        moveBtn.className = 'btn btn-primary';
        moveBtn.textContent = 'Move draft here';
        const discardBtn = document.createElement('button');
        discardBtn.type = 'button';
        discardBtn.className = 'btn btn-danger';
        discardBtn.textContent = 'Discard and start here';
        const dialog = UI.showDialog('Unfinished step draft', body, {
            actions: [continueBtn, moveBtn, discardBtn],
            initialFocus: continueBtn,
        });
        continueBtn.addEventListener('click', () => {
            dialog.close();
            _setStageInsertAnchor(currentSourceStageKey, currentDecision, { keepDraft: true });
        });
        moveBtn.addEventListener('click', () => {
            dialog.close();
            _setStageInsertAnchor(sourceStageKey, decision, { keepDraft: true });
        });
        discardBtn.addEventListener('click', () => {
            dialog.close();
            _setStageInsertAnchor(sourceStageKey, decision, { keepDraft: false });
        });
    }

    function _startStageInsert({ sourceStageKey = '', decision = '' } = {}) {
        const nextSourceStageKey = String(sourceStageKey || '');
        const nextDecision = String(decision || '').trim().toLowerCase();
        const sameInsert = editorMode.kind === 'insert-stage'
            && String(editorMode.sourceStageKey || '') === nextSourceStageKey
            && String(editorMode.decision || '') === nextDecision;
        if (sameInsert) {
            _setStageInsertAnchor(nextSourceStageKey, nextDecision, { keepDraft: true });
            return;
        }
        if (editorMode.kind === 'insert-stage') {
            _syncPendingStageFromMountedEditor();
            if (_pendingStageHasDraftContent()) {
                _showPendingStageInsertChoice(nextSourceStageKey, nextDecision);
                return;
            }
        }
        _setStageInsertAnchor(nextSourceStageKey, nextDecision, { keepDraft: false });
    }

    function _confirmStageInsert() {
        const committedSelectorBeforeSync = {
            kind: String(pendingStage.selector_kind || ''),
            value: String(pendingStage.selector_value || ''),
            preferredAgentId: String(pendingStage.selector_preferred_agent_id || ''),
        };
        _syncPendingStageFromMountedEditor();
        if (
            committedSelectorBeforeSync.preferredAgentId
            && String(pendingStage.selector_kind || '') === committedSelectorBeforeSync.kind
            && String(pendingStage.selector_value || '') === committedSelectorBeforeSync.value
            && !String(pendingStage.selector_preferred_agent_id || '').trim()
        ) {
            pendingStage.selector_preferred_agent_id = committedSelectorBeforeSync.preferredAgentId;
        }
        const displayName = String(pendingStage.display_name || '').trim();
        if (!displayName) {
            UI.notify('Give this step a name before adding it to the workflow.', 'warning');
            return;
        }
        const creatingRole = String(pendingStage.participant_key || '') === '__new__'
            || Boolean(String(pendingStage.role_display_name || '').trim());
        if (creatingRole && !String(pendingStage.role_display_name || '').trim()) {
            UI.notify('Name the owner role before creating this step.', 'warning');
            return;
        }
        const doc = _cloneDoc(draft.document);
        let participantKey = String(pendingStage.participant_key || '').trim();
        if (creatingRole) {
            const roleKey = _nextAvailableKey(
                doc.participants || [],
                'participant_key',
                String(pendingStage.role_participant_key || pendingStage.role_display_name || 'role'),
            );
            doc.participants = [...(doc.participants || []), {
                participant_key: roleKey,
                display_name: String(pendingStage.role_display_name || '').trim(),
                instructions: String(pendingStage.role_instructions || ''),
            }];
            participantKey = roleKey;
        }
        const stageKey = _nextAvailableKey(
            doc.stages || [],
            'stage_key',
            String(_slugSuggestion(displayName) || pendingStage.stage_key || 'step'),
        );
        const nextStage = _normalizeStageWriteAccess({
            stage_key: stageKey,
            display_name: displayName,
            participant_key: participantKey,
            selector: _selectorFromFields(
                pendingStage.selector_kind,
                pendingStage.selector_value,
                pendingStage.selector_preferred_agent_id,
            ),
            stage_kind: String(pendingStage.stage_kind || 'work') || 'work',
            instructions: String(pendingStage.instructions || ''),
            inputs: Array.isArray(pendingStage.inputs) ? pendingStage.inputs : [],
            outputs: Array.isArray(pendingStage.outputs) ? pendingStage.outputs : [],
            transitions: {},
            max_rounds: Number.parseInt(String(pendingStage.max_rounds || '0'), 10) || 0,
            timeout_seconds: Number.parseInt(String(pendingStage.timeout_seconds || '0'), 10) || 0,
        });
        const items = [...(doc.stages || [])];
        const sourceStageKey = String(editorMode.sourceStageKey || '').trim();
        const decision = String(editorMode.decision || '').trim().toLowerCase();
        if (sourceStageKey && decision) {
            const sourceIndex = items.findIndex((item) => String(item.stage_key || '') === sourceStageKey);
            if (sourceIndex >= 0) {
                const sourceStage = { ...items[sourceIndex] };
                const priorTarget = String(sourceStage.transitions?.[decision] || '').trim();
                sourceStage.transitions = Object.assign({}, sourceStage.transitions || {}, {
                    [decision]: stageKey,
                });
                if (priorTarget) {
                    nextStage.transitions = { completed: priorTarget };
                }
                items[sourceIndex] = sourceStage;
                const targetIndex = items.findIndex((item) => String(item.stage_key || '') === priorTarget);
                const insertIndex = targetIndex > sourceIndex ? targetIndex : sourceIndex + 1;
                items.splice(insertIndex, 0, nextStage);
                doc.stages = items;
            } else {
                doc.stages = [...items, nextStage];
            }
        } else {
            doc.stages = [...items, nextStage];
        }
        _resetEditorMode();
        _commitDocument(doc, {
            nextSelection: { sectionKey: 'stages', nodeKey: stageKey },
        });
    }

    function _cancelStageInsert() {
        _resetEditorMode();
        render();
    }

    function _addArtifact(sourceStageKey = '', surfaceKey = 'secondary') {
        const doc = _cloneDoc(draft.document);
        const n = (doc.artifacts || []).length + 1;
        const key = `artifact_${n}`;
        doc.artifacts = [...(doc.artifacts || []), {
            artifact_key: key,
            display_name: '',
            kind: 'workspace_file',
            description: '',
            path: '',
            verify: true,
        }];
        _commitDocument(doc, {
            nextSelection: {
                sectionKey: 'artifacts',
                nodeKey: key,
                sourceStageKey: String(sourceStageKey || '').trim(),
                surfaceKey: String(surfaceKey || 'secondary') === 'local' ? 'local' : 'secondary',
            },
        });
    }

    function _moveStageBefore(nodeId, targetId) {
        const doc = _cloneDoc(draft.document);
        const items = [...(doc.stages || [])];
        const fromIndex = items.findIndex((item) => String(item.stage_key || '') === String(nodeId || ''));
        const toIndex = items.findIndex((item) => String(item.stage_key || '') === String(targetId || ''));
        if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) return;
        const [moved] = items.splice(fromIndex, 1);
        items.splice(toIndex, 0, moved);
        doc.stages = items;
        _commitDocument(doc, { nextSelection: { sectionKey: 'stages', nodeKey: String(nodeId || '') } });
    }

    function _startRouteInsert(stageKey) {
        const stage = (draft.document.stages || []).find((item) => String(item.stage_key || '') === String(stageKey || ''));
        if (!stage) return;
        pendingRoute = _blankRouteDraft(stage.stage_key, stage.stage_kind);
        _setStageWorkspacePanelValue(String(stage.stage_key || ''), 'routing');
        _queueStageViewportAnchor(String(stage.stage_key || ''), { panelKey: 'routing' });
        selection = { sectionKey: 'stages', nodeKey: String(stage.stage_key || '') };
        editorMode = {
            kind: 'create-route',
            sourceStageKey: String(stage.stage_key || ''),
            decision: String(pendingRoute.decision || ''),
            sessionKey: String(++editorSessionNonce),
        };
        render();
    }

    function _commitPendingRouteField(_target, key, value) {
        if (key === 'decision') {
            pendingRoute.decision = String(value || '').trim().toLowerCase();
        } else if (key === 'target_key') {
            pendingRoute.target_key = String(value || '').trim();
        }
        render();
    }

    function _confirmRouteInsert() {
        const sourceStageKey = String(pendingRoute.source_stage_key || '').trim();
        const decision = String(pendingRoute.decision || '').trim().toLowerCase();
        const targetKey = String(pendingRoute.target_key || '').trim();
        if (!sourceStageKey || !decision || !targetKey) {
            UI.notify('Choose a decision and a next step or finish outcome before adding this route.', 'warning');
            return;
        }
        const doc = _cloneDoc(draft.document);
        const items = [...(doc.stages || [])];
        const idx = items.findIndex((item) => String(item.stage_key || '') === sourceStageKey);
        if (idx < 0) return;
        const stage = { ...items[idx] };
        stage.transitions = Object.assign({}, stage.transitions || {}, {
            [decision]: targetKey,
        });
        items[idx] = stage;
        doc.stages = items;
        const edgeId = _stageTransitionId(sourceStageKey, decision);
        _resetEditorMode();
        _commitDocument(doc, {
            nextSelection: { sectionKey: 'transitions', nodeKey: edgeId },
        });
    }

    function _cancelRouteInsert() {
        _resetEditorMode();
        render();
    }

    function _commitTransitionField(edgeId, key, value) {
        const [fromStageKey, currentDecision] = String(edgeId || '').split('::');
        const doc = _cloneDoc(draft.document);
        const items = [...(doc.stages || [])];
        const idx = items.findIndex((item) => String(item.stage_key || '') === fromStageKey);
        if (idx < 0) return;
        const stage = { ...items[idx] };
        const transitions = Object.assign({}, stage.transitions || {});
        const existingTarget = String(transitions[currentDecision] || '').trim();
        if (!existingTarget) return;
        let nextDecision = currentDecision;
        let nextTarget = existingTarget;
        if (key === 'decision') {
            nextDecision = String(value || '').trim().toLowerCase() || currentDecision;
            delete transitions[currentDecision];
            transitions[nextDecision] = existingTarget;
        } else if (key === 'target_key') {
            nextTarget = String(value || '').trim();
            transitions[currentDecision] = nextTarget;
        }
        stage.transitions = transitions;
        items[idx] = stage;
        doc.stages = items;
        _commitDocument(doc, {
            nextSelection: { sectionKey: 'transitions', nodeKey: _stageTransitionId(fromStageKey, nextDecision) },
        });
    }

    function _deleteTransition(edgeId) {
        const [fromStageKey, decision] = String(edgeId || '').split('::');
        const doc = _cloneDoc(draft.document);
        const items = [...(doc.stages || [])];
        const idx = items.findIndex((item) => String(item.stage_key || '') === fromStageKey);
        if (idx < 0) return;
        const stage = { ...items[idx] };
        const transitions = Object.assign({}, stage.transitions || {});
        delete transitions[decision];
        stage.transitions = transitions;
        items[idx] = stage;
        doc.stages = items;
        _commitDocument(doc, { nextSelection: { sectionKey: 'stages', nodeKey: fromStageKey } });
    }

    function _stageDeletionPlan(stageKey, doc = draft.document) {
        const normalizedStageKey = String(stageKey || '').trim();
        if (!normalizedStageKey) return null;
        const stages = Array.isArray(doc?.stages) ? doc.stages : [];
        const stageIndex = stages.findIndex((item) => String(item.stage_key || '') === normalizedStageKey);
        if (stageIndex < 0) return null;
        const stage = stages[stageIndex];
        const outgoing = Object.entries(stage.transitions || {})
            .map(([decision, target]) => ({
                decision: String(decision || '').trim().toLowerCase(),
                target: String(target || '').trim(),
            }))
            .filter((item) => item.decision && item.target);
        const successorTargets = Array.from(new Set(outgoing
            .map((item) => item.target)
            .filter((item) => item && item !== normalizedStageKey)));
        const redirectTarget = successorTargets.length === 1 ? successorTargets[0] : '';
        const incoming = stages.flatMap((source) => Object.entries(source.transitions || {})
            .filter(([, target]) => String(target || '').trim() === normalizedStageKey)
            .map(([decision]) => ({
                sourceStageKey: String(source.stage_key || ''),
                decision: String(decision || '').trim().toLowerCase(),
            })))
            .filter((item) => item.sourceStageKey && item.sourceStageKey !== normalizedStageKey);
        const siblingFallback = stages[stageIndex + 1]?.stage_key || stages[stageIndex - 1]?.stage_key || '';
        const nextSelection = redirectTarget && !PROTOCOL_TERMINAL_TARGETS.some((item) => item.key === redirectTarget)
            ? { sectionKey: 'stages', nodeKey: redirectTarget }
            : siblingFallback
                ? { sectionKey: 'stages', nodeKey: String(siblingFallback || '') }
                : { sectionKey: 'overview', nodeKey: '' };
        return {
            stage,
            stageIndex,
            outgoing,
            incoming,
            redirectTarget,
            nextSelection,
        };
    }

    function _deleteStage(stageKey) {
        const plan = _stageDeletionPlan(stageKey, draft.document);
        if (!plan) return;
        const doc = _cloneDoc(draft.document);
        doc.stages = (doc.stages || [])
            .filter((item) => String(item.stage_key || '') !== String(stageKey || ''))
            .map((item) => {
                const transitions = {};
                Object.entries(item.transitions || {}).forEach(([decision, target]) => {
                    const normalizedTarget = String(target || '').trim();
                    if (normalizedTarget !== String(stageKey || '').trim()) {
                        transitions[decision] = target;
                        return;
                    }
                    if (plan.redirectTarget) {
                        transitions[decision] = plan.redirectTarget;
                    }
                });
                return { ...item, transitions };
            });
        _commitDocument(doc, { nextSelection: plan.nextSelection });
    }

    function _confirmStageDelete(stageKey) {
        const plan = _stageDeletionPlan(stageKey, draft.document);
        if (!plan) return;
        const stageLabel = String(plan.stage?.display_name || plan.stage?.stage_key || 'this step');
        const consequences = [];
        if (plan.redirectTarget) {
            consequences.push(`Incoming routes will be rewired to ${_transitionTargetLabel(plan.redirectTarget, draft.document) || plan.redirectTarget}.`);
        } else if (plan.incoming.length) {
            consequences.push('Incoming routes to this step will be removed.');
        }
        if (plan.outgoing.length > 1) {
            consequences.push('This step fans out to multiple branches, so deleting it also removes those outgoing branches.');
        } else if (!plan.outgoing.length) {
            consequences.push('This step has no outgoing branch; deleting it simply removes it from the workflow.');
        }
        UI.showConfirm(
            'Delete step',
            [`Delete ${stageLabel}?`, ...consequences].join(' '),
            async () => { _deleteStage(stageKey); },
        );
    }

    function _isAuthoringAssignableAgent(agent) {
        const slug = String(agent?.slug || '').trim().toLowerCase();
        const role = String(agent?.role || '').trim().toLowerCase();
        const botKey = String(agent?.bot_key || '').trim().toLowerCase();
        const tags = Array.isArray(agent?.tags)
            ? agent.tags.map((item) => String(item || '').trim().toLowerCase()).filter(Boolean)
            : [];
        if (tags.includes('rehearsal') || tags.includes('system')) return false;
        return slug !== 'rehearsal' && role !== 'rehearsal' && botKey !== 'registry.rehearsal';
    }

    function _authoringAssignableAgents() {
        return (connectedAgents || []).filter((agent) => _isAuthoringAssignableAgent(agent));
    }

    function _authoringAssignableCandidates(candidates) {
        return (Array.isArray(candidates) ? candidates : []).filter((candidate) => _isAuthoringAssignableAgent(candidate));
    }

    function _availableAuthoringAgents() {
        return (availableAgents || []).filter((agent) => _isAuthoringAssignableAgent(agent));
    }

    function _isAuthoringRoutingSkill(item) {
        return UI.isHumanAssignableSkillName(item?.skill_name || item);
    }

    function _supportsSkillCatalog(agent) {
        const operations = Array.isArray(agent?.supported_admin_operations) ? agent.supported_admin_operations : [];
        return operations.includes('list_catalog_skills') || operations.includes('catalog_skill_lifecycle_detail');
    }

    function _skillCatalogSummary(skillName = '') {
        const normalized = String(skillName || '').trim().toLowerCase();
        if (!normalized) return null;
        return (availableCatalogSkills || []).find((item) => String(item?.name || '').trim().toLowerCase() === normalized) || null;
    }

    function _isKnownAuthoringSkill(skillName = '') {
        const normalized = String(skillName || '').trim().toLowerCase();
        if (!normalized) return false;
        if (_skillCatalogSummary(normalized)) return true;
        if ((availableRoutingSkills || []).some((item) =>
            String(item?.skill_name || item || '').trim().toLowerCase() === normalized && _isAuthoringRoutingSkill(item))) {
            return true;
        }
        return _availableAuthoringAgents().some((agent) =>
            (Array.isArray(agent?.routing_skills) ? agent.routing_skills : []).some((item) =>
                String(item?.skill_name || item || '').trim().toLowerCase() === normalized && _isAuthoringRoutingSkill(item)));
    }

    function _generatedSkillStem(value = '') {
        const normalized = String(value || '').trim();
        if (!normalized) return '';
        const stem = normalized.replace(/(?:[\s_-]+)?\d{10,}$/, '').trim();
        return stem && stem !== normalized ? stem : '';
    }

    function _generatedSkillTimestamp(entry = null) {
        const candidates = [
            String(entry?.name || '').trim(),
            String(entry?.display_name || '').trim(),
            String(entry?.label || '').trim(),
            String(entry?.value || '').trim(),
        ];
        for (const candidate of candidates) {
            const match = candidate.match(/(\d{10,})$/);
            if (match) return Number(match[1] || 0);
        }
        return 0;
    }

    function _isVisibleStandardSkill(entry = null) {
        const lifecycle = String(entry?.lifecycle_status || '').trim().toLowerCase();
        if (lifecycle === 'archived') return false;
        if (Object.prototype.hasOwnProperty.call(entry || {}, 'runtime_available') && entry.runtime_available === false) {
            return false;
        }
        return true;
    }

    function _standardSkillGroupKey(entry = null) {
        const sourceKind = String(entry?.source_kind || '').trim().toLowerCase();
        const rawName = String(entry?.name || entry?.value || '').trim().toLowerCase();
        const generatedStem = sourceKind === 'custom'
            ? (_generatedSkillStem(String(entry?.name || '')) || _generatedSkillStem(String(entry?.display_name || '')))
            : '';
        return generatedStem
            ? `custom:${generatedStem.toLowerCase()}`
            : `${sourceKind || 'skill'}:${rawName}`;
    }

    function _standardSkillLabel(entry = null) {
        const summary = entry && entry.name ? _skillCatalogSummary(entry.name) : null;
        const sourceKind = String(entry?.source_kind || summary?.source_kind || '').trim().toLowerCase();
        const rawLabel = String(entry?.display_name || summary?.display_name || entry?.label || entry?.name || entry?.value || '').trim();
        if (!rawLabel) return '';
        if (sourceKind === 'custom') {
            const stem = _generatedSkillStem(rawLabel);
            if (stem) return _titleCaseWords(stem);
        }
        return rawLabel.includes(' ') ? rawLabel : _titleCaseWords(rawLabel);
    }

    function _skillSourcePrecedence(sourceKind = '') {
        const normalized = String(sourceKind || '').trim().toLowerCase();
        if (normalized === 'custom') return 30;
        if (normalized === 'imported') return 20;
        if (normalized === 'builtin') return 10;
        return 0;
    }

    function _compareSkillEntries(left, right, includedValues = new Set()) {
        const leftIncluded = includedValues.has(String(left?.value || left?.name || '').trim().toLowerCase());
        const rightIncluded = includedValues.has(String(right?.value || right?.name || '').trim().toLowerCase());
        if (leftIncluded !== rightIncluded) return leftIncluded ? -1 : 1;
        const leftVisible = _isVisibleStandardSkill(left);
        const rightVisible = _isVisibleStandardSkill(right);
        if (leftVisible !== rightVisible) return leftVisible ? -1 : 1;
        const leftTimestamp = _generatedSkillTimestamp(left);
        const rightTimestamp = _generatedSkillTimestamp(right);
        if (leftTimestamp !== rightTimestamp) return rightTimestamp - leftTimestamp;
        const leftLabel = _standardSkillLabel(left).toLowerCase();
        const rightLabel = _standardSkillLabel(right).toLowerCase();
        return leftLabel.localeCompare(rightLabel);
    }

    function _curatedStandardSkillEntries(rows = [], { includeValues = [] } = {}) {
        const includedValues = new Set((includeValues || []).map((value) => String(value || '').trim().toLowerCase()).filter(Boolean));
        const groups = new Map();
        (rows || []).forEach((row) => {
            const value = String(row?.value || row?.name || '').trim();
            if (!value) return;
            const summary = _skillCatalogSummary(value);
            const enriched = {
                ...summary,
                ...row,
                name: value,
                value,
                display_name: String(row?.display_name || summary?.display_name || '').trim(),
                source_kind: String(row?.source_kind || summary?.source_kind || '').trim().toLowerCase(),
                lifecycle_status: String(row?.lifecycle_status || summary?.lifecycle_status || '').trim().toLowerCase(),
                runtime_available: row?.runtime_available ?? summary?.runtime_available,
            };
            if (!_isVisibleStandardSkill(enriched) && !includedValues.has(value.toLowerCase())) return;
            const key = _standardSkillGroupKey(enriched);
            const bucket = groups.get(key) || [];
            bucket.push(enriched);
            groups.set(key, bucket);
        });
        return Array.from(groups.values())
            .map((bucket) => {
                const sorted = [...bucket].sort((left, right) => _compareSkillEntries(left, right, includedValues));
                const chosen = sorted[0] || null;
                if (!chosen) return null;
                return {
                    value: String(chosen.value || chosen.name || '').trim(),
                    label: _standardSkillLabel(chosen),
                    meta: String(chosen.meta || '').trim(),
                    source_kind: String(chosen.source_kind || '').trim().toLowerCase(),
                };
            })
            .filter(Boolean)
            .sort((left, right) => String(left.label || '').localeCompare(String(right.label || '')));
    }

    function _selectorKindLabel(kind) {
        const normalized = String(kind || '').trim().toLowerCase();
        if (normalized === 'agent') return 'Specific agent';
        if (normalized === 'skill') return 'Required skill';
        if (normalized === 'role') return 'Runtime role tag';
        return _titleCaseWords(normalized);
    }

    function _selectorValueLabel(kind) {
        const normalized = String(kind || '').trim().toLowerCase();
        if (normalized === 'agent') return 'agent';
        if (normalized === 'skill') return 'skill';
        if (normalized === 'role') return 'runtime role tag';
        return normalized || 'value';
    }

    function _selectorOptionKinds() {
        const optionKinds = Array.isArray(authoringOptions?.selector_kind_options) && authoringOptions.selector_kind_options.length
            ? authoringOptions.selector_kind_options
            : ['agent', 'skill', 'role'];
        const seen = new Set();
        const ordered = [];
        [...PRIMARY_SELECTOR_KINDS, ...optionKinds].forEach((value) => {
            const normalized = String(value || '').trim().toLowerCase();
            if (!normalized || seen.has(normalized)) return;
            seen.add(normalized);
            ordered.push(normalized);
        });
        return ordered;
    }

    function _selectorAvailableKinds() {
        const available = _selectorOptionKinds();
        if (_currentAuthoringSurface() === 'operator') {
            return available;
        }
        const primary = available.filter((value) => PRIMARY_SELECTOR_KINDS.includes(value));
        return primary.length ? primary : available;
    }

    function _selectorPrimaryKinds() {
        const available = _selectorAvailableKinds();
        const primary = available.filter((value) => PRIMARY_SELECTOR_KINDS.includes(value));
        return primary.length ? primary : available;
    }

    function _selectorAdvancedKinds() {
        const primary = new Set(_selectorPrimaryKinds());
        return _selectorAvailableKinds().filter((value) => !primary.has(value));
    }

    function _isPrimarySelectorKind(kind) {
        return _selectorPrimaryKinds().includes(String(kind || '').trim().toLowerCase());
    }

    function _selectorKindOptions(kinds = _selectorAvailableKinds()) {
        return kinds.map((value) => ({
            value: String(value || ''),
            label: _selectorKindLabel(value),
        }));
    }

    function _nextSelectorValueForKind(kind, currentValue = '') {
        const normalized = String(kind || '').trim().toLowerCase();
        if (!normalized) return '';
        const catalog = _selectorCatalogEntries(normalized);
        const current = String(currentValue || '').trim();
        if (catalog.some((item) => item.value === current)) return current;
        if (catalog.length) return String(catalog[0].value || '');
        return current;
    }

    function _documentSelectorValues(kind) {
        const normalized = String(kind || '').trim().toLowerCase();
        if (!normalized) return [];
        return Array.from(new Set((draft.document?.stages || [])
            .map((stage) => stage?.selector)
            .filter((selector) => String(selector?.kind || '').trim().toLowerCase() === normalized)
            .map((selector) => String(selector?.value || '').trim())
            .filter(Boolean)));
    }

    function _selectorCatalogEntries(kind) {
        const normalized = String(kind || '').trim().toLowerCase();
        const entries = [];
        const seen = new Set();
        const agentSkillCounts = new Map();
        const push = (value, label, meta = '') => {
            const nextValue = String(value || '').trim();
            if (!nextValue || seen.has(nextValue)) return;
            seen.add(nextValue);
            entries.push({
                value: nextValue,
                label: String(label || nextValue).trim() || nextValue,
                meta: String(meta || '').trim(),
            });
        };
        _availableAuthoringAgents().forEach((agent) => {
            (Array.isArray(agent?.routing_skills) ? agent.routing_skills : [])
                .filter((item) => _isAuthoringRoutingSkill(item))
                .forEach((item) => {
                    const skillName = String(item?.skill_name || item || '').trim();
                    if (!skillName) return;
                    agentSkillCounts.set(skillName, Number(agentSkillCounts.get(skillName) || 0) + 1);
                });
        });
        if (normalized === 'agent') {
            _availableAuthoringAgents().forEach((agent) => {
                const slug = String(agent?.slug || '').trim();
                if (!slug) return;
                const meta = [
                    String(agent?.role || '').trim(),
                    String(agent?.connectivity_state || '').trim().toLowerCase() === 'connected'
                        ? ''
                        : String(agent?.connectivity_state || '').trim(),
                ].filter(Boolean).join(' · ');
                push(slug, String(agent?.display_name || _titleCaseWords(slug) || slug), meta);
            });
            _documentSelectorValues('agent').forEach((value) => {
                push(value, value, 'Used in workflow');
            });
        } else if (normalized === 'skill') {
            (availableRoutingSkills || []).filter((item) => _isAuthoringRoutingSkill(item)).forEach((item) => {
                const skillName = String(item?.skill_name || item || '').trim();
                if (!skillName || item?.enabled === false) return;
                const advertisedBy = Array.isArray(item?.advertised_by_agents)
                    ? item.advertised_by_agents.length
                    : Number(agentSkillCounts.get(skillName) || 0);
                push(
                    skillName,
                    _titleCaseWords(skillName),
                    advertisedBy > 0 ? `${advertisedBy} agent${advertisedBy === 1 ? '' : 's'}` : '',
                );
            });
            Array.from(agentSkillCounts.entries()).forEach(([skillName, advertisedBy]) => {
                push(
                    skillName,
                    _titleCaseWords(skillName),
                    advertisedBy > 0 ? `${advertisedBy} agent${advertisedBy === 1 ? '' : 's'}` : '',
                );
            });
            _documentSelectorValues('skill').forEach((value) => {
                push(value, _titleCaseWords(value), 'Used in workflow');
            });
            return _curatedStandardSkillEntries(entries, {
                includeValues: _documentSelectorValues('skill'),
            });
        } else if (normalized === 'role') {
            _availableAuthoringAgents().forEach((agent) => {
                push(agent?.role, _titleCaseWords(agent?.role || ''));
            });
            _documentSelectorValues('role').forEach((value) => {
                push(value, _titleCaseWords(value), 'Used in workflow');
            });
        }
        return entries.sort((left, right) => String(left.label || '').localeCompare(String(right.label || '')));
    }

    function _selectorCatalogEmptyHint(kind) {
        const normalized = String(kind || '').trim().toLowerCase();
        if (normalized === 'agent') {
            return 'No available agents were loaded from the registry. Enter an agent slug only if you need to pin one anyway.';
        }
        if (normalized === 'skill') {
            return 'No available skills were loaded from the registry. Use New skill needed if the skill does not exist yet.';
        }
        if (normalized === 'role') {
            return 'No runtime role tags were loaded from the registry. Enter one manually only if you need this advanced path.';
        }
        return 'Enter the exact value you want to match at runtime.';
    }

    function _selectorAgentRecord(selectorValue = '') {
        const normalized = String(selectorValue || '').trim().toLowerCase();
        if (!normalized) return null;
        return _availableAuthoringAgents().find((agent) => {
            const slug = String(agent?.slug || '').trim().toLowerCase();
            const agentId = String(agent?.agent_id || '').trim().toLowerCase();
            return normalized === slug || normalized === agentId;
        }) || null;
    }

    function _selectorAgentSkills(agent) {
        const values = Array.isArray(agent?.routing_skills) ? agent.routing_skills : [];
        const rows = Array.from(new Set(values
            .map((item) => String(item || '').trim())
            .filter((item) => _isAuthoringRoutingSkill({ skill_name: item }))))
            .map((value) => ({ value, label: _titleCaseWords(value) }));
        return _curatedStandardSkillEntries(rows).map((item) => String(item.value || '').trim());
    }

    function _selectorAgentControlValue(selectorValue = '') {
        const agent = _selectorAgentRecord(selectorValue);
        return String(agent?.slug || selectorValue || '').trim();
    }

    function _preferredAgentForSkill(skillName = '', preferredAgentId = '') {
        const normalizedSkill = String(skillName || '').trim().toLowerCase();
        const preferred = String(preferredAgentId || '').trim();
        if (!normalizedSkill || !preferred) return '';
        const agent = _selectorAgentRecord(preferred);
        if (!agent) return '';
        const supportsSkill = _selectorAgentSkills(agent)
            .map((item) => String(item || '').trim().toLowerCase())
            .includes(normalizedSkill);
        return supportsSkill ? String(agent.agent_id || '').trim() : '';
    }

    function _currentStageAssignmentMode(stageKey = '', selectorKind = '') {
        const normalizedStageKey = String(stageKey || '').trim();
        if (normalizedStageKey
            && normalizedStageKey === String(stageAssignmentEditor.stageKey || '').trim()
            && String(stageAssignmentEditor.mode || '').trim()) {
            return _selectorModeFromKind(stageAssignmentEditor.mode, 'unassigned');
        }
        const derived = _selectorModeFromKind(selectorKind, selectorKind ? 'skill' : 'unassigned');
        return derived === 'advanced' ? 'skill' : derived;
    }

    function _setStageAssignmentMode(stageKey = '', mode = '') {
        stageAssignmentEditor = {
            stageKey: String(stageKey || '').trim(),
            mode: _selectorModeFromKind(mode, 'unassigned'),
        };
        render();
    }

    function _selectorEditorState({
        selectorMode = '',
        selectorKind = '',
        selectorValue = '',
        selectorPreferredAgentId = '',
    } = {}) {
        const normalizedKind = String(selectorKind || '').trim().toLowerCase();
        const requestedMode = _selectorModeFromKind(selectorMode || normalizedKind, normalizedKind ? 'skill' : 'unassigned');
        const primaryMode = requestedMode === 'advanced' ? 'skill' : requestedMode;
        if (normalizedKind === 'skill') {
            const skillValue = String(selectorValue || '').trim();
            const skillMode = primaryMode === 'new_skill' || primaryMode === 'agent'
                ? primaryMode
                : skillValue
                    ? 'skill'
                    : primaryMode;
            return {
                mode: skillMode,
                requiredSkill: skillMode === 'new_skill' ? '' : skillValue,
                neededSkill: skillMode === 'new_skill' ? skillValue : '',
                pinnedAgent: _selectorAgentControlValue(selectorPreferredAgentId),
                advancedKind: '',
                advancedValue: '',
            };
        }
        if (normalizedKind === 'agent') {
            return {
                mode: primaryMode,
                requiredSkill: '',
                neededSkill: '',
                pinnedAgent: _selectorAgentControlValue(selectorValue),
                advancedKind: '',
                advancedValue: '',
            };
        }
        return {
            mode: primaryMode,
            requiredSkill: '',
            neededSkill: '',
            pinnedAgent: '',
            advancedKind: normalizedKind,
            advancedValue: String(selectorValue || '').trim(),
        };
    }

    function _selectorFromEditorFields({
        requiredSkill = '',
        pinnedAgent = '',
        neededSkill = '',
        advancedKind = '',
        advancedValue = '',
    } = {}) {
        const nextAdvancedKind = String(advancedKind || '').trim().toLowerCase();
        const nextAdvancedValue = String(advancedValue || '').trim();
        if (nextAdvancedKind && nextAdvancedValue) {
            return _selectorFromFields(nextAdvancedKind, nextAdvancedValue);
        }
        const skillName = String(requiredSkill || '').trim();
        const agentKey = String(pinnedAgent || '').trim();
        if (skillName) {
            const agent = _selectorAgentRecord(agentKey);
            return _selectorFromFields('skill', skillName, String(agent?.agent_id || '').trim());
        }
        if (agentKey) {
            return _selectorFromFields('agent', agentKey);
        }
        const neededSkillSlug = _slugSuggestion(neededSkill) || String(neededSkill || '').trim();
        if (neededSkillSlug) {
            return _selectorFromFields('skill', neededSkillSlug);
        }
        return null;
    }

    function _selectorSkillAgentMismatch(requiredSkill = '', pinnedAgent = '') {
        const skillName = String(requiredSkill || '').trim();
        const agent = _selectorAgentRecord(pinnedAgent);
        const agentId = String(agent?.agent_id || '').trim();
        if (!skillName || !agentId) return false;
        return !_preferredAgentForSkill(skillName, agentId);
    }

    function _agentsAdvertisingSkill(selectorValue = '') {
        const normalized = String(selectorValue || '').trim().toLowerCase();
        if (!normalized) return [];
        const seen = new Set();
        const rows = [];
        const push = ({ agentId = '', slug = '', displayName = '', role = '', connectivityState = '' } = {}) => {
            const normalizedSlug = String(slug || '').trim().toLowerCase();
            if (!normalizedSlug || seen.has(normalizedSlug)) return;
            seen.add(normalizedSlug);
            rows.push({
                agent_id: String(agentId || '').trim(),
                slug: normalizedSlug,
                display_name: String(displayName || '').trim() || _titleCaseWords(normalizedSlug) || normalizedSlug,
                role: String(role || '').trim(),
                connectivity_state: String(connectivityState || '').trim(),
            });
        };
        const availableBySlug = new Map(_availableAuthoringAgents().map((agent) => [
            String(agent?.slug || '').trim().toLowerCase(),
            agent,
        ]));
        const advertised = (availableRoutingSkills || []).find((item) =>
            String(item?.skill_name || item || '').trim().toLowerCase() === normalized,
        );
        (Array.isArray(advertised?.advertised_by_agents) ? advertised.advertised_by_agents : []).forEach((slug) => {
            const normalizedSlug = String(slug || '').trim().toLowerCase();
            const agent = availableBySlug.get(normalizedSlug);
            push({
                agentId: String(agent?.agent_id || '').trim(),
                slug: normalizedSlug,
                displayName: String(agent?.display_name || '').trim() || _titleCaseWords(normalizedSlug) || normalizedSlug,
                role: String(agent?.role || '').trim(),
                connectivityState: String(agent?.connectivity_state || '').trim(),
            });
        });
        _availableAuthoringAgents().forEach((agent) => {
            const skills = _selectorAgentSkills(agent).map((item) => item.toLowerCase());
            if (skills.includes(normalized)) {
                push({
                    agentId: String(agent?.agent_id || '').trim(),
                    slug: String(agent?.slug || '').trim(),
                    displayName: String(agent?.display_name || '').trim(),
                    role: String(agent?.role || '').trim(),
                    connectivityState: String(agent?.connectivity_state || '').trim(),
                });
            }
        });
        return rows.sort((left, right) =>
            String(left?.display_name || left?.slug || '').localeCompare(String(right?.display_name || right?.slug || '')));
    }

    function _selectorSkillMatchSection({
        selectorValue = '',
        preferredAgentId = '',
        readOnly = false,
        compact = false,
    } = {}) {
        if (!selectorValue) return null;
        const matches = _agentsAdvertisingSkill(selectorValue);
        if (compact || (!matches.length && !preferredAgentId)) return null;
        const preferredAgent = _selectorAgentRecord(preferredAgentId || '');
        const matchLabels = matches.map((candidate) => String(candidate?.display_name || candidate?.slug || '').trim()).filter(Boolean);
        let help = '';
        if (matchLabels.length) {
            help = `Available now: ${matchLabels.join(', ')}.`;
        } else {
            help = readOnly
                ? 'No connected agents currently advertise this skill.'
                : 'No connected agents currently advertise this skill yet.';
        }
        if (preferredAgent) {
            help += ` Preferred agent: ${String(preferredAgent.display_name || preferredAgent.slug || preferredAgentId || '').trim()}.`;
        }
        const preview = Kit.selectorResolutionPreview({
            selector: `@skill:${String(selectorValue || '').trim()}`,
            candidates: matches,
            currentAgentId: String(preferredAgent?.agent_id || preferredAgentId || '').trim(),
            message: help,
            title: 'Matching agents',
            help: 'This preview uses the same assignment resolution presentation as the agent tooling.',
            showForm: false,
            showSuggestions: false,
            emptyHint: help,
            resultTitle: 'Available now',
        });
        preview.classList.add('kit-selector-editor-context');
        preview.dataset.key = `selector-skill-match:${String(selectorValue || '').trim().toLowerCase()}`;
        return preview;
    }

    function _selectorAgentSkillsSection({
        selectorValue = '',
        selectedSkill = '',
        readOnly = false,
        compact = false,
    } = {}) {
        const agent = _selectorAgentRecord(selectorValue);
        const skills = _selectorAgentSkills(agent);
        if (!selectorValue || compact || (!skills.length && !selectedSkill)) return null;
        const section = document.createElement('section');
        section.className = 'kit-selector-editor-context';
        section.dataset.key = `selector-agent-skills:${String(selectorValue || '').trim().toLowerCase()}`;
        const title = document.createElement('strong');
        title.className = 'kit-selector-editor-context-title';
        title.dataset.key = `${section.dataset.key}:title`;
        title.textContent = 'Available skills';
        section.appendChild(title);
        const note = document.createElement('p');
        note.className = 'kit-selector-editor-note';
        note.dataset.key = `${section.dataset.key}:note`;
        const agentLabel = String(agent?.display_name || agent?.slug || selectorValue || '').trim();
        const selectedSkillLabel = String(selectedSkill || '').trim()
            ? _standardSkillLabel({ value: selectedSkill, name: selectedSkill })
            : '';
        if (skills.length) {
            note.textContent = agentLabel
                ? `${agentLabel} currently advertises these skills.`
                : 'This agent currently advertises these skills.';
        } else {
            note.textContent = readOnly
                ? 'No advertised skills are currently available for this agent.'
                : 'No advertised skills are currently available for this agent right now.';
        }
        if (agentLabel && selectedSkillLabel) {
            note.textContent += ` Selected: ${selectedSkillLabel} on ${agentLabel}.`;
        }
        section.appendChild(note);
        if (skills.length) {
            const chips = document.createElement('div');
            chips.className = 'chip-row';
            skills.slice(0, 6).forEach((skillName) => {
                const chip = document.createElement('span');
                chip.className = 'quickstart-chip static';
                chip.textContent = _standardSkillLabel({ value: skillName, name: skillName });
                chips.appendChild(chip);
            });
            if (skills.length > 6) {
                const more = document.createElement('span');
                more.className = 'quiet-note';
                more.textContent = `+${skills.length - 6} more`;
                chips.appendChild(more);
            }
            section.appendChild(chips);
        }
        return section;
    }

    function _buildSelectorValueField({
        selectorKind = '',
        selectorValue = '',
        readOnly = false,
        onChange = null,
        onSelectorChange = null,
        label = '',
        catalogEntries = null,
        emptyHint = '',
        placeholderText = '',
        disabled = false,
        allowCustom = true,
        preferPillsWhenCountAtMost = 0,
        emptyChoiceLabel = '',
    } = {}) {
        const normalized = String(selectorKind || '').trim().toLowerCase();
        const block = document.createElement('div');
        block.className = 'kit-selector-editor-field';
        const row = document.createElement('div');
        row.className = 'kit-details-row';
        let preControlRow = null;
        const valueLabel = document.createElement('label');
        valueLabel.className = 'kit-details-label';
        valueLabel.textContent = label || `Choose ${_selectorValueLabel(normalized)}`;
        row.appendChild(valueLabel);
        const catalog = Array.isArray(catalogEntries) ? catalogEntries : _selectorCatalogEntries(normalized);
        const shouldRenderSelect = Array.isArray(catalogEntries) || normalized === 'agent' || normalized === 'skill';
        const canRenderPills = !readOnly
            && !disabled
            && !allowCustom
            && shouldRenderSelect
            && Number(preferPillsWhenCountAtMost || 0) > 0
            && catalog.length > 0
            && catalog.length <= Number(preferPillsWhenCountAtMost || 0);
        if (canRenderPills) {
            const chips = document.createElement('div');
            chips.className = 'chip-row kit-selector-pill-group';
            chips.dataset.selectorPillGroup = 'true';
            chips.dataset.value = String(selectorValue || '');
            chips.setAttribute('role', 'group');
            chips.setAttribute('aria-label', valueLabel.textContent);
            const entries = [
                {
                    value: '',
                    label: String(emptyChoiceLabel || placeholderText || '(none)').replace(/^\(|\)$/g, ''),
                    meta: '',
                },
                ...catalog,
            ];
            const updateSelection = (nextValue) => {
                chips.dataset.value = String(nextValue || '');
                chips.querySelectorAll('.quickstart-chip').forEach((chip) => {
                    if (!(chip instanceof HTMLButtonElement)) return;
                    const isSelected = String(chip.dataset.value || '') === String(nextValue || '');
                    chip.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
                    chip.classList.toggle('is-selected', isSelected);
                });
            };
            entries.forEach((item) => {
                const chip = document.createElement('button');
                chip.type = 'button';
                chip.className = 'quickstart-chip';
                chip.dataset.value = String(item.value || '');
                chip.textContent = String(item.label || '');
                chip.title = String(item.meta || '').trim()
                    ? `${String(item.label || '')} · ${String(item.meta || '').trim()}`
                    : String(item.label || '');
                chips.appendChild(chip);
                chip.addEventListener('click', () => {
                    const nextValue = String(item.value || '');
                    updateSelection(nextValue);
                    if (typeof onSelectorChange === 'function') {
                        onSelectorChange(normalized, nextValue);
                    } else if (typeof onChange === 'function') {
                        onChange(null, 'selector_value', nextValue);
                    }
                });
            });
            updateSelection(selectorValue);
            row.appendChild(chips);
        } else if (catalog.length || shouldRenderSelect) {
            const select = document.createElement('select');
            select.className = 'kit-details-control';
            const searchable = normalized === 'skill' && catalog.length > 8 && !readOnly && !disabled;
            let searchInput = null;
            const appendOption = (item) => {
                const option = document.createElement('option');
                option.value = String(item.value || '');
                option.textContent = item.meta ? `${item.label} · ${item.meta}` : item.label;
                if (String(selectorValue || '') === String(item.value || '')) option.selected = true;
                select.appendChild(option);
            };
            const renderOptions = (filterText = '') => {
                const filter = String(filterText || '').trim().toLowerCase();
                select.replaceChildren();
                const placeholder = document.createElement('option');
                placeholder.value = '';
                placeholder.textContent = placeholderText || `(choose ${_selectorValueLabel(normalized)})`;
                select.appendChild(placeholder);
                catalog
                    .filter((item) => {
                        const value = String(item.value || '');
                        if (value === String(selectorValue || '')) return true;
                        if (!filter) return true;
                        return [
                            value,
                            String(item.label || ''),
                            String(item.meta || ''),
                        ].join(' ').toLowerCase().includes(filter);
                    })
                    .forEach(appendOption);
                if (allowCustom && selectorValue && !catalog.some((item) => item.value === String(selectorValue || ''))) {
                    const custom = document.createElement('option');
                    custom.value = String(selectorValue || '');
                    custom.textContent = `Custom · ${String(selectorValue || '')}`;
                    custom.selected = true;
                    select.appendChild(custom);
                }
                select.value = String(selectorValue || '');
            };
            renderOptions('');
            if (searchable) {
                const searchRow = document.createElement('div');
                searchRow.className = 'kit-details-row';
                const searchLabel = document.createElement('label');
                searchLabel.className = 'kit-details-label';
                searchLabel.textContent = 'Search skills';
                searchRow.appendChild(searchLabel);
                searchInput = document.createElement('input');
                searchInput.type = 'search';
                searchInput.className = 'kit-details-control';
                searchInput.placeholder = 'Type to filter available skills';
                searchInput.setAttribute('aria-label', searchLabel.textContent);
                searchInput.addEventListener('input', () => renderOptions(searchInput.value));
                searchRow.appendChild(searchInput);
                preControlRow = searchRow;
            }
            select.disabled = Boolean(readOnly || disabled);
            if (!readOnly) {
                const commitSelect = () => {
                    if (typeof onSelectorChange === 'function') {
                        onSelectorChange(normalized, select.value);
                    } else if (typeof onChange === 'function') {
                        onChange(null, 'selector_value', select.value);
                    }
                };
                if (typeof onSelectorChange === 'function') {
                    select.addEventListener('input', commitSelect);
                    select.addEventListener('change', commitSelect);
                } else if (typeof onChange === 'function') {
                    select.addEventListener('input', commitSelect);
                    select.addEventListener('change', commitSelect);
                }
            }
            select.setAttribute('aria-label', valueLabel.textContent);
            row.appendChild(select);
            if (!catalog.length) {
                const hint = document.createElement('p');
                hint.className = 'kit-selector-editor-note';
                hint.textContent = emptyHint || _selectorCatalogEmptyHint(normalized);
                block.appendChild(hint);
            }
        } else {
            const input = document.createElement('input');
            input.type = 'text';
            input.className = 'kit-details-control';
            input.placeholder = placeholderText || Kit.dict.label('protocol.participant.selector_value.placeholder', 'e.g. legal-review, approver, m1');
            input.value = String(selectorValue || '');
            input.readOnly = Boolean(readOnly || disabled);
            if (!readOnly) {
                if (typeof onSelectorChange === 'function') {
                    const commit = () => onSelectorChange(normalized, input.value);
                    input.addEventListener('change', commit);
                    input.addEventListener('blur', commit);
                } else if (typeof onChange === 'function') {
                    const commit = () => onChange(null, 'selector_value', input.value);
                    input.addEventListener('change', commit);
                    input.addEventListener('blur', commit);
                }
            }
            input.setAttribute('aria-label', valueLabel.textContent);
            row.appendChild(input);
            const hint = document.createElement('p');
            hint.className = 'kit-selector-editor-note';
            hint.textContent = emptyHint || _selectorCatalogEmptyHint(normalized);
            block.appendChild(hint);
        }
        block.prepend(row);
        if (preControlRow) block.prepend(preControlRow);
        return { element: block, catalog, presentation: canRenderPills ? 'pills' : (catalog.length || shouldRenderSelect ? 'select' : 'input') };
    }

    function _buildSelectorManualOverrideField({
        selectorValue = '',
        readOnly = false,
        onChange = null,
        label = 'Custom value',
    } = {}) {
        const row = document.createElement('div');
        row.className = 'kit-details-row';
        const overrideLabel = document.createElement('label');
        overrideLabel.className = 'kit-details-label';
        overrideLabel.textContent = label;
        row.appendChild(overrideLabel);
        const overrideInput = document.createElement('input');
        overrideInput.type = 'text';
        overrideInput.className = 'kit-details-control';
        overrideInput.placeholder = Kit.dict.label('protocol.participant.selector_value.placeholder', 'e.g. legal-review, approver, m1');
        overrideInput.value = String(selectorValue || '');
        overrideInput.readOnly = Boolean(readOnly);
        if (typeof onChange === 'function' && !readOnly) {
            const commit = () => onChange(null, 'selector_value', overrideInput.value);
            overrideInput.addEventListener('change', commit);
            overrideInput.addEventListener('blur', commit);
        }
        overrideInput.setAttribute('aria-label', overrideLabel.textContent);
        row.appendChild(overrideInput);
        return row;
    }

    function _selectorEditor({
        stageKey = '',
        selectorMode = '',
        selectorKind = '',
        selectorValue = '',
        selectorPreferredAgentId = '',
        readOnly = false,
        onChange = null,
        onSelectorChange = null,
        density = null,
    } = {}) {
        const wrap = document.createElement('section');
        wrap.className = 'kit-selector-editor';
        const operatorSurface = _currentAuthoringSurface() === 'operator';
        const emit = (key, value) => {
            if (typeof onChange === 'function') onChange(null, key, value);
        };
        const emitMode = (mode) => {
            const nextMode = _selectorModeFromKind(mode, 'unassigned');
            if (stageKey) {
                _setStageAssignmentMode(stageKey, nextMode);
            } else {
                emit('selector_mode', nextMode);
            }
        };
        const emitSelector = (kind, value, preferredAgentId = '') => {
            if (typeof onSelectorChange === 'function') {
                onSelectorChange(String(kind || ''), String(value || ''), String(preferredAgentId || ''));
                return;
            }
            emit('selector_kind', kind);
            emit('selector_value', value);
            emit('selector_preferred_agent_id', preferredAgentId);
        };

        const {
            mode,
            requiredSkill,
            neededSkill,
            pinnedAgent,
            advancedKind,
            advancedValue,
        } = _selectorEditorState({
            selectorMode,
            selectorKind,
            selectorValue,
            selectorPreferredAgentId,
        });
        wrap.dataset.key = [
            'selector-editor',
            String(stageKey || 'new'),
            String(mode || ''),
            String(requiredSkill || '').trim().toLowerCase(),
            String(neededSkill || '').trim().toLowerCase(),
            String(pinnedAgent || '').trim().toLowerCase(),
            String(advancedKind || '').trim().toLowerCase(),
            String(advancedValue || '').trim().toLowerCase(),
        ].join(':');
        const advancedKinds = _selectorAdvancedKinds();
        const activeAgent = _selectorAgentRecord(pinnedAgent);
        const activeAgentId = String(activeAgent?.agent_id || '').trim();
        const activeAgentLabel = String(activeAgent?.display_name || activeAgent?.slug || pinnedAgent || '').trim();
        const operatorManagedSelector = !operatorSurface && Boolean(advancedKind && advancedValue);
        const requiredSkillMatches = _agentsAdvertisingSkill(requiredSkill).map((candidate) => ({
            value: String(candidate?.slug || '').trim(),
            label: String(candidate?.display_name || candidate?.slug || '').trim(),
            meta: String(candidate?.role || '').trim(),
        })).filter((item) => item.value);
        const agentSkillEntries = _selectorAgentSkills(activeAgent).map((skillName) => ({
            value: String(skillName || '').trim(),
            label: _standardSkillLabel({ value: skillName, name: skillName }),
            meta: '',
        }));
        const emitAssignment = ({
            nextSkill = requiredSkill,
            nextAgent = pinnedAgent,
            nextNeededSkill = neededSkill,
            nextAdvancedKind = '',
            nextAdvancedValue = '',
        } = {}) => {
            const selector = _selectorFromEditorFields({
                requiredSkill: nextSkill,
                pinnedAgent: nextAgent,
                neededSkill: nextNeededSkill,
                advancedKind: nextAdvancedKind,
                advancedValue: nextAdvancedValue,
            });
            emitSelector(
                String(selector?.kind || ''),
                String(selector?.value || ''),
                String(selector?.preferred_agent_id || ''),
            );
        };
        if (operatorManagedSelector) {
            const note = document.createElement('p');
            note.className = 'kit-selector-editor-note';
            note.textContent = 'This step uses an operator-managed assignment. Normal authoring keeps it intact but does not expose the internal selector controls.';
            wrap.appendChild(note);
            const summary = document.createElement('p');
            summary.className = 'kit-selector-editor-note';
            summary.textContent = `Current assignment: ${_selectorSummary(
                { kind: advancedKind, value: advancedValue },
                { empty: 'Operator-managed runtime selector' },
            )}.`;
            wrap.appendChild(summary);
            return wrap;
        }
        const modeControl = UI.createSegmentedControl([
            { value: 'unassigned', label: 'No assignment yet' },
            { value: 'skill', label: 'Existing skill' },
            { value: 'agent', label: 'Specific agent' },
            { value: 'new_skill', label: 'New skill needed' },
        ], (nextMode) => {
            emitMode(nextMode);
            if (nextMode === 'unassigned') {
                emitAssignment({
                    nextSkill: '',
                    nextAgent: '',
                    nextNeededSkill: '',
                    nextAdvancedKind: '',
                    nextAdvancedValue: '',
                });
            } else if (nextMode === 'new_skill') {
                emitAssignment({
                    nextSkill: '',
                    nextAgent: '',
                    nextNeededSkill: neededSkill,
                    nextAdvancedKind: '',
                    nextAdvancedValue: '',
                });
            } else if (nextMode === 'skill' && advancedKind && advancedValue) {
                emitAssignment({
                    nextSkill: '',
                    nextAgent: '',
                    nextNeededSkill: '',
                    nextAdvancedKind: '',
                    nextAdvancedValue: '',
                });
            } else if (nextMode === 'agent' && advancedKind && advancedValue) {
                emitAssignment({
                    nextSkill: '',
                    nextAgent: '',
                    nextNeededSkill: '',
                    nextAdvancedKind: '',
                    nextAdvancedValue: '',
                });
            }
        }, { label: 'Assignment mode', value: mode });
        modeControl.element.dataset.key = 'selector-assignment-mode';
        wrap.appendChild(modeControl.element);

        if (advancedKind && advancedValue) {
            const note = document.createElement('p');
            note.className = 'kit-selector-editor-note';
            note.textContent = 'This step currently uses a custom runtime selector. Choosing one of the primary modes below will replace it.';
            wrap.appendChild(note);
        }

        let skillField = null;
        let agentField = null;
        if (mode === 'unassigned') {
            const note = document.createElement('p');
            note.className = 'kit-selector-editor-note';
            note.textContent = 'Leave this step unassigned while shaping the workflow. Choose a skill or a specific agent before publishing when this step needs to execute.';
            wrap.appendChild(note);
        } else if (mode === 'skill') {
            skillField = _buildSelectorValueField({
                selectorKind: 'skill',
                selectorValue: requiredSkill,
                readOnly,
                onSelectorChange: (_kind, nextValue) => emitAssignment({
                    nextSkill: String(nextValue || ''),
                    nextAgent: requiredSkillMatches.some((item) => item.value === pinnedAgent) ? pinnedAgent : '',
                    nextNeededSkill: '',
                }),
                label: 'Required skill',
                allowCustom: false,
            });
            skillField.element.dataset.key = `selector-field:${String(stageKey || 'new')}:skill:required`;
            wrap.appendChild(skillField.element);

            agentField = _buildSelectorValueField({
                selectorKind: 'agent',
                selectorValue: pinnedAgent,
                readOnly,
                onSelectorChange: (_kind, nextValue) => emitAssignment({
                    nextSkill: requiredSkill,
                    nextAgent: String(nextValue || ''),
                    nextNeededSkill: '',
                }),
                label: 'Pin matching agent (optional)',
                catalogEntries: requiredSkillMatches,
                emptyHint: requiredSkill
                    ? 'No matching agents available right now.'
                    : 'Choose a required skill first.',
                placeholderText: requiredSkill ? '(leave dynamic)' : '(choose a skill first)',
                disabled: !requiredSkill,
                allowCustom: false,
                preferPillsWhenCountAtMost: 5,
                emptyChoiceLabel: 'Dynamic',
            });
            agentField.element.dataset.key = [
                'selector-field',
                String(stageKey || 'new'),
                'skill',
                'agent-refinement',
                String(requiredSkill || '').trim().toLowerCase(),
            ].join(':');
            wrap.appendChild(agentField.element);
        } else if (mode === 'agent') {
            agentField = _buildSelectorValueField({
                selectorKind: 'agent',
                selectorValue: pinnedAgent,
                readOnly,
                onSelectorChange: (_kind, nextValue) => emitAssignment({
                    nextSkill: pinnedAgent === String(nextValue || '') ? requiredSkill : '',
                    nextAgent: String(nextValue || ''),
                    nextNeededSkill: '',
                }),
                label: 'Agent',
                allowCustom: false,
            });
            agentField.element.dataset.key = `selector-field:${String(stageKey || 'new')}:agent:pinned`;
            wrap.appendChild(agentField.element);

            skillField = _buildSelectorValueField({
                selectorKind: 'skill',
                selectorValue: requiredSkill,
                readOnly,
                onSelectorChange: (_kind, nextValue) => emitAssignment({
                    nextSkill: String(nextValue || ''),
                    nextAgent: pinnedAgent,
                    nextNeededSkill: '',
                }),
                label: 'Limit to one of this agent\'s skills (optional)',
                catalogEntries: agentSkillEntries,
                emptyHint: pinnedAgent
                    ? 'No advertised skills are available for this agent right now.'
                    : 'Choose an agent first.',
                placeholderText: pinnedAgent ? '(leave agent-only)' : '(choose an agent first)',
                disabled: !pinnedAgent,
                allowCustom: false,
                preferPillsWhenCountAtMost: 5,
                emptyChoiceLabel: 'Agent only',
            });
            skillField.element.dataset.key = [
                'selector-field',
                String(stageKey || 'new'),
                'agent',
                'skill-refinement',
                String(pinnedAgent || '').trim().toLowerCase(),
            ].join(':');
            wrap.appendChild(skillField.element);
        } else if (mode === 'new_skill') {
            const row = document.createElement('div');
            row.className = 'kit-details-row';
            const label = document.createElement('label');
            label.className = 'kit-details-label';
            label.textContent = 'Needed skill';
            row.appendChild(label);
            const input = document.createElement('input');
            input.type = 'text';
            input.className = 'kit-details-control';
            input.placeholder = 'e.g. dependency-upgrade, data-quality-review';
            input.value = String(neededSkill || '');
            input.readOnly = Boolean(readOnly);
            input.setAttribute('aria-label', label.textContent);
            if (!readOnly) {
                const commit = () => emitAssignment({
                    nextSkill: '',
                    nextAgent: '',
                    nextNeededSkill: input.value,
                });
                input.addEventListener('input', commit);
                input.addEventListener('change', commit);
                input.addEventListener('blur', commit);
            }
            row.appendChild(input);
            wrap.appendChild(row);
            const note = document.createElement('p');
            note.className = 'kit-selector-editor-note';
            note.textContent = 'Use this when the workflow needs a skill that is not available yet. The step can be authored now and resolved before execution.';
            wrap.appendChild(note);
        }

        if (requiredSkill || pinnedAgent || neededSkill) {
            const summary = document.createElement('p');
            summary.className = 'kit-selector-editor-note';
            const requiredSkillLabel = _standardSkillLabel({ value: requiredSkill, name: requiredSkill });
            const neededSkillLabel = _standardSkillLabel({ value: neededSkill, name: neededSkill });
            if (neededSkill) {
                summary.textContent = `Current assignment: needs new skill ${neededSkillLabel || neededSkill}.`;
            } else if (requiredSkill && activeAgentLabel) {
                summary.textContent = `Current assignment: requires ${requiredSkillLabel} and pins the step to ${activeAgentLabel}.`;
            } else if (requiredSkill) {
                summary.textContent = `Current assignment: requires ${requiredSkillLabel} and stays dynamic across matching agents.`;
            } else {
                summary.textContent = `Current assignment: pins the step to ${activeAgentLabel || 'the selected agent'}.`;
            }
            wrap.appendChild(summary);
        }

        if (_selectorSkillAgentMismatch(requiredSkill, pinnedAgent)) {
            const warning = document.createElement('p');
            warning.className = 'kit-selector-editor-note';
            warning.textContent = `Pinned agent ${activeAgentLabel || 'the selected agent'} does not currently advertise ${_standardSkillLabel({ value: requiredSkill, name: requiredSkill })}.`;
            wrap.appendChild(warning);
        }

        if (mode === 'skill' && requiredSkill) {
            const matchesSection = _selectorSkillMatchSection({
                selectorValue: requiredSkill,
                preferredAgentId: activeAgentId,
                readOnly,
                compact: agentField.presentation === 'pills',
            });
            if (matchesSection) wrap.appendChild(matchesSection);
        }
        if (mode === 'agent' && pinnedAgent) {
            const skillsSection = _selectorAgentSkillsSection({
                selectorValue: pinnedAgent,
                selectedSkill: requiredSkill,
                readOnly,
                compact: skillField.presentation === 'pills',
            });
            if (skillsSection) wrap.appendChild(skillsSection);
        }

        if (operatorSurface && advancedKinds.length) {
            const advanced = document.createElement('details');
            advanced.className = 'kit-selector-editor-override';
            advanced.open = Boolean(advancedKind && advancedValue);
            const advancedSummary = document.createElement('summary');
            advancedSummary.className = 'kit-stage-editor-summary';
            const advancedTitle = document.createElement('h4');
            advancedTitle.className = 'kit-stage-editor-title';
            advancedTitle.textContent = Kit.dict.label('protocol.participant.selector_advanced.label', 'Custom runtime selector');
            advancedSummary.appendChild(advancedTitle);
            advanced.appendChild(advancedSummary);
            const advancedBody = document.createElement('div');
            advancedBody.className = 'kit-selector-editor-override-body';
            const advancedNote = document.createElement('p');
            advancedNote.className = 'kit-selector-editor-note';
            advancedNote.textContent = 'Use this only for a runtime role tag or another selector value that the normal skill and agent modes cannot express.';
            advancedBody.appendChild(advancedNote);

            const advancedKindRow = document.createElement('div');
            advancedKindRow.className = 'kit-details-row';
            const advancedKindLabel = document.createElement('label');
            advancedKindLabel.className = 'kit-details-label';
            advancedKindLabel.textContent = Kit.dict.label('protocol.participant.selector_advanced.strategy', 'Custom selector type');
            advancedKindRow.appendChild(advancedKindLabel);
            const advancedKindControl = document.createElement('select');
            advancedKindControl.className = 'kit-details-control';
            const defaultOption = document.createElement('option');
            defaultOption.value = '';
            defaultOption.textContent = '(none)';
            advancedKindControl.appendChild(defaultOption);
            _selectorKindOptions(advancedKinds).forEach((item) => {
                const option = document.createElement('option');
                option.value = String(item.value || '');
                option.textContent = String(item.label || item.value || '');
                if (String(advancedKind || '') === String(item.value || '')) option.selected = true;
                advancedKindControl.appendChild(option);
            });
            advancedKindControl.disabled = Boolean(readOnly);
            advancedKindControl.setAttribute('aria-label', advancedKindLabel.textContent);
            if ((typeof onChange === 'function' || typeof onSelectorChange === 'function') && !readOnly) {
                advancedKindControl.addEventListener('change', () => {
                    const nextKind = String(advancedKindControl.value || '').trim();
                    if (!nextKind) {
                        emitAssignment({
                            nextSkill: requiredSkill,
                            nextAgent: pinnedAgent,
                        });
                        return;
                    }
                    emitAssignment({
                        nextSkill: '',
                        nextAgent: '',
                        nextAdvancedKind: nextKind,
                        nextAdvancedValue: _nextSelectorValueForKind(nextKind, nextKind === advancedKind ? advancedValue : ''),
                    });
                });
            }
            advancedKindRow.appendChild(advancedKindControl);
            advancedBody.appendChild(advancedKindRow);

            if (advancedKind) {
                const { element, catalog } = _buildSelectorValueField({
                    selectorKind: advancedKind,
                    selectorValue: advancedValue,
                    readOnly,
                    onChange,
                    onSelectorChange: (nextKind, nextValue) => emitAssignment({
                        nextSkill: '',
                        nextAgent: '',
                        nextAdvancedKind: nextKind,
                        nextAdvancedValue: nextValue,
                    }),
                    label: `Choose ${_selectorValueLabel(advancedKind)}`,
                });
                advancedBody.appendChild(element);
                if (catalog.length) {
                    advancedBody.appendChild(_buildSelectorManualOverrideField({
                        selectorValue: advancedValue,
                        readOnly,
                        onChange: typeof onSelectorChange === 'function'
                            ? (_target, _key, nextValue) => emitAssignment({
                                nextSkill: '',
                                nextAgent: '',
                                nextAdvancedKind: advancedKind,
                                nextAdvancedValue: nextValue,
                            })
                            : onChange,
                        label: Kit.dict.label('protocol.participant.selector_override.label', 'Custom value'),
                    }));
                }
            }
            advanced.appendChild(advancedBody);
            wrap.appendChild(advanced);
        }

        return wrap;
    }

    function _participantEditorShell({
        target,
        readOnly = false,
        onCommit = null,
        createAction = null,
        cancelAction = null,
    } = {}) {
        const shell = document.createElement('div');
        shell.className = 'kit-stage-editor';
        const basics = Kit.detailsPanel({
            target,
            surfaceKey: 'protocol.participant',
            onCommit,
            schema: [
                { key: 'display_name', kind: 'text', required: true, readOnly },
                { key: 'participant_key', kind: 'text', readOnly },
            ],
            actions: createAction ? [
                { label: 'Create role', tone: 'btn-primary', onClick: createAction },
                ...(cancelAction ? [{ label: 'Cancel', onClick: cancelAction }] : []),
            ] : [],
        });
        shell.appendChild(_stageEditorSection('Role', basics));
        const instructions = Kit.detailsPanel({
            target,
            surfaceKey: 'protocol.participant',
            onCommit,
            schema: [
                { key: 'instructions', kind: 'textarea', rows: 4, readOnly },
            ],
            actions: !createAction && cancelAction ? [{ label: 'Cancel', onClick: cancelAction }] : [],
        });
        shell.appendChild(_stageEditorSection('Shared instructions', instructions, { wide: true, collapsible: !createAction, open: Boolean(String(target?.instructions || '').trim()) }));
        return shell;
    }

    function _routeScopeLabel(stageKey, projection, currentSegmentId = '') {
        const segmentId = String(projection?.stageToSegment?.get(String(stageKey || '')) || '');
        if (!segmentId) return 'Workflow';
        if (segmentId === String(currentSegmentId || '')) return 'This section';
        const segment = projection?.segmentsById?.get(segmentId);
        return String(segment?.label || 'Another section');
    }

    function _routeTargetOptions(sourceStageKey, projection) {
        const currentSegmentId = projection.stageToSegment.get(String(sourceStageKey || '')) || '';
        const options = [
            { value: '', label: '(choose next step or finish outcome)' },
            ...(draft.document.stages || []).map((stage) => ({
                value: String(stage.stage_key || ''),
                label: `${_routeScopeLabel(stage.stage_key, projection, currentSegmentId)} · ${String(stage.display_name || stage.stage_key || '')}`,
            })),
            ...PROTOCOL_TERMINAL_TARGETS.map((item) => ({
                value: item.key,
                label: `Finish outcome · ${item.label}`,
            })),
        ];
        return options;
    }

    function _routeEditorPanel({
        target,
        sourceStage,
        projection,
        readOnly = false,
        onCommit = null,
        createAction = null,
        insertAction = null,
        deleteAction = null,
        cancelAction = null,
        cancelLabel = 'Cancel',
    } = {}) {
        return Kit.detailsPanel({
            target,
            surfaceKey: 'protocol.transition',
            onCommit,
            schema: [
                { key: 'source_stage', kind: 'text', label: 'From step', help: 'This branch leaves the selected step.', readOnly: true },
                { key: 'decision', kind: 'select', options: _decisionOptionsForStage(sourceStage, target?.decision), disabled: readOnly, label: 'When', help: 'Name the outcome or decision that triggers this branch.' },
                { key: 'target_key', kind: 'select', options: _routeTargetOptions(sourceStage?.stage_key || target?.source_stage_key || '', projection), disabled: readOnly, label: 'Go to', help: 'Choose the next step or a finish outcome for this branch.' },
            ],
            actions: [
                ...(createAction ? [{ label: 'Save branch', tone: 'btn-primary', onClick: createAction }] : []),
                ...(insertAction ? [{ label: 'Insert step here', onClick: insertAction }] : []),
                ...(deleteAction ? [{ label: Kit.dict.label('protocol.transition.delete'), tone: 'btn-danger', onClick: deleteAction }] : []),
                ...(cancelAction ? [{ label: cancelLabel, onClick: cancelAction }] : []),
            ],
        });
    }

    // -------------------------------------------------------------------
    // Rendering
    // -------------------------------------------------------------------
    function _lifecycleHeaderEl() {
        const record = {
            display_name: draft.display_name,
            slug: draft.slug,
            lifecycle_state: String(currentProtocol?.protocol?.lifecycle_state || 'draft'),
        };
        const lifecycleState = String(currentProtocol?.protocol?.lifecycle_state || '');
        const progress = _workflowProgress();
        const hasPublishedVersion = Boolean(currentProtocol?.protocol?.current_version_id)
            || (Array.isArray(currentProtocol?.versions)
                && currentProtocol.versions.some((v) => String(v.lifecycle_state || '') === 'published'));
        const permissions = {
            canValidate: Boolean(currentProtocolId) && progress.stageCount > 0 && saveState.state !== 'conflict',
            canPublish: Boolean(currentProtocolId) && progress.stageCount > 0 && saveState.state !== 'conflict',
            canArchive: Boolean(currentProtocolId) && hasPublishedVersion && lifecycleState !== 'archived' && saveState.state !== 'conflict',
            canRun: Boolean(currentProtocolId) && hasPublishedVersion && lifecycleState === 'published' && saveState.state !== 'conflict',
            canRehearse: Boolean(currentProtocolId) && hasPublishedVersion && lifecycleState !== 'archived' && saveState.state !== 'conflict',
            canDiscard: Boolean(currentProtocolId) && !hasPublishedVersion && saveState.state !== 'conflict',
        };
        const utilityActions = [{
            label: 'Improve with Auto Protocol',
            onClick: () => _openAutoProtocolDialog({ mode: 'revise' }),
        }, {
            label: 'Protocol settings',
            onClick: () => _openProtocolSettings(),
        }, {
            label: 'Export package',
            onClick: () => _openExportProtocolPackageDialog(),
        }, {
            label: 'Import package',
            onClick: () => _openImportProtocolPackageDialog(),
        }];
        if (hasPublishedVersion && lifecycleState === 'published' && saveState.state !== 'conflict') {
            utilityActions.push({
                label: 'Publish as template',
                onClick: () => UI.showConfirm(
                    'Publish template',
                    'Create a reusable template snapshot from the currently published protocol version?',
                    async () => { await _publishTemplateNow(); },
                ),
            });
            utilityActions.push({
                label: 'Dry-run rehearsal',
                onClick: () => void _startRehearsal().catch((err) => UI.reportError('Rehearsal failed to start', err)),
            });
        }
        return Kit.lifecycleHeader({
            surfaceKey: 'protocol',
            record,
            saveState,
            permissions,
            compact: true,
            primaryActions: ['validate', 'publish', 'run'],
            secondaryActions: ['archive', 'discard'],
            utilityActions,
            actions: {
                validate: () => void _validateNow().catch((err) => UI.reportError('Validation failed', err)),
                publish: () => void _publishNow().catch((err) => UI.reportError('Publish failed', err)),
                run: () => _openRunProtocolDialog(),
                rehearse: () => void _startRehearsal().catch((err) => UI.reportError('Rehearsal failed to start', err)),
                archive: () => UI.showConfirm(
                    'Archive protocol',
                    'Archive this protocol definition? Published versions remain immutable, but the definition will no longer be offered for new runs.',
                    async () => { await _archiveNow(); },
                ),
                discard: () => UI.showConfirm(
                    'Delete protocol draft?',
                    'This permanently deletes the unpublished draft. Published protocols must be archived instead.',
                    async () => { await _discardNow(); },
                ),
            },
            onTitleCommit: (value) => _commitOverview(null, 'display_name', value),
            onSlugCommit: (value) => _commitOverview(null, 'slug', value),
        });
    }

    // Refs maintained across renders so we can sync inputs without blurring
    // the user's caret.
    let _lifecycleHeaderRef = null;
    function _syncLifecycleChip() {
        if (_lifecycleHeaderRef && typeof _lifecycleHeaderRef.updateSaveState === 'function') {
            _lifecycleHeaderRef.updateSaveState(saveState);
        }
    }
    function _syncLifecycleHeaderInputs() {
        if (_lifecycleHeaderRef && typeof _lifecycleHeaderRef.syncRecord === 'function') {
            _lifecycleHeaderRef.syncRecord({
                display_name: draft.display_name,
                slug: draft.slug,
                lifecycle_state: String(currentProtocol?.protocol?.lifecycle_state || 'draft'),
            });
        }
    }

    function _stageNodeSublabel(stage) {
        const reads = Number((stage.inputs || []).length || 0);
        const writes = Number((stage.outputs || []).length || 0);
        const parts = [];
        const assignment = _stageAssignmentSummary(stage, { empty: '' });
        if (assignment) parts.push(assignment);
        if (reads) parts.push(`Reads ${reads}`);
        if (writes) parts.push(`Writes ${writes}`);
        if (!parts.length && String(stage.instructions || '').trim()) parts.push('Instructions ready');
        return parts.join(' · ');
    }

    function _stageNodeBadges(stage, viewKind = 'detail') {
        const stageKind = String(stage?.stage_kind || 'work');
        if (viewKind === 'topology' && stageKind === 'work') {
            return [];
        }
        return [{
            tone: stageKind,
            label: Kit.dict.label(`protocol.stage.kind.${stageKind}`),
        }];
    }

    function _showEdgeLabel(edge, sourceStage, viewKind = 'detail') {
        if (viewKind !== 'topology') {
            return false;
        }
        const decision = String(edge?.decision || '').trim().toLowerCase();
        const transitionCount = Object.keys(sourceStage?.transitions || {}).length;
        return transitionCount > 1 || decision !== 'completed';
    }

    function _firstRunState(progress) {
        const stageCount = progress.stageCount;
        const artifactCount = progress.artifactCount;
        return editorMode.kind === 'idle' && !stageCount
            ? {
                active: true,
                title: Kit.dict.label('protocol.canvas.empty.title'),
                body: 'Start with the first step, then define any shared files, datasets, code, or reports that later steps should read or produce.',
                steps: [
                    {
                        badge: '1',
                        text: 'Add the first step and create its owner role inline if you need a new one.',
                        state: 'active',
                    },
                    {
                        badge: '2',
                        text: 'Define shared workflow files and outputs once, then attach them to step inputs and outputs.',
                        state: artifactCount ? 'complete' : '',
                    },
                    {
                        badge: '3',
                        text: 'Open the workflow map only when you want route context or a spatial review of the whole flow.',
                    },
                ],
                note: 'Use the Assignment panel on each step to choose an existing skill, pin a specific agent, or mark a new skill needed without leaving the workflow.',
                actions: [
                    { label: Kit.dict.label('protocol.stages.add'), onClick: () => _startStageInsert() },
                    { label: 'Define shared files', tone: '', onClick: () => _openArtifactCatalog() },
                    ...(protocolTemplates.length
                        ? [{ label: Kit.dict.label('protocol.catalog.template'), tone: '', onClick: _openTemplateChooser }]
                        : []),
                ],
            }
            : null;
    }

    function _selectionSegmentId(projection) {
        if (selection.sectionKey === 'segments' && projection.segmentsById.has(String(selection.nodeKey || ''))) {
            return String(selection.nodeKey || '');
        }
        const sourceStageKey = _selectionSourceStageKey();
        if (sourceStageKey) {
            return String(projection.stageToSegment.get(sourceStageKey) || '');
        }
        if (selection.sectionKey === 'stages') {
            return String(projection.stageToSegment.get(String(selection.nodeKey || '')) || '');
        }
        if (selection.sectionKey === 'transitions') {
            return String(projection.stageToSegment.get(String(selection.nodeKey || '').split('::')[0] || '') || '');
        }
        if (selection.sectionKey === 'participants') {
            return String(projection.segments.find((segment) =>
                segment.participantKeys.includes(String(selection.nodeKey || '')),
            )?.id || '');
        }
        if (selection.sectionKey === 'artifacts') {
            const artifactKey = String(selection.nodeKey || '');
            const ownerStage = (draft.document.stages || []).find((stage) =>
                (stage.inputs || []).includes(artifactKey) || (stage.outputs || []).includes(artifactKey));
            return String(projection.stageToSegment.get(String(ownerStage?.stage_key || '')) || '');
        }
        return '';
    }

    function _segmentStageDisplayLabel(segment, stage) {
        const stageLabel = String(stage?.display_name || stage?.stage_key || '').trim();
        return stageLabel || 'Untitled step';
    }

    function _workflowInsertHint() {
        if (editorMode.kind !== 'insert-stage' || !editorMode.sourceStageKey || !editorMode.decision) return '';
        const sourceStage = (draft.document.stages || []).find((item) => String(item.stage_key || '') === String(editorMode.sourceStageKey || ''));
        if (!sourceStage) return '';
        const targetKey = String(sourceStage.transitions?.[String(editorMode.decision || '').trim().toLowerCase()] || '').trim();
        const decisionLabel = _protocolDecisionLabel(editorMode.decision);
        const sourceLabel = String(sourceStage.display_name || sourceStage.stage_key || 'Selected step');
        if (!targetKey) {
            return `This step will be inserted on ${decisionLabel} after ${sourceLabel}.`;
        }
        const targetLabel = _transitionTargetLabel(targetKey, draft.document) || 'the current destination';
        return `This step will be inserted on ${decisionLabel} from ${sourceLabel} before ${targetLabel}.`;
    }

    function _focusStageKey(projection, segment) {
        if (selection.sectionKey === 'stages') {
            return String(selection.nodeKey || '');
        }
        if (selection.sectionKey === 'transitions') {
            return String(selection.nodeKey || '').split('::')[0] || '';
        }
        return String(segment?.stageKeys?.[0] || '');
    }

    function _segmentFinishLabels(segment) {
        return Array.from(new Set((segment?.outgoingEdges || [])
            .filter((edge) => edge.targetKind === 'terminal')
            .map((edge) => String(_transitionTargetLabel(edge.targetKey, draft.document) || ''))
            .filter(Boolean)));
    }

    function _workflowToolbarActions(progress, projection) {
        const canMutate = saveState.state !== 'conflict' && editorMode.kind !== 'rehearse';
        const selectedStage = _selectionStage(draft.document)
            || (draft.document.stages || []).find((item) => String(item.stage_key || '') === String(_activeStageKey() || ''))
            || null;
        const selectedTransition = _selectionTransition(draft.document);
        const activeSegmentId = _selectionSegmentId(projection);
        const activeSegment = projection.segmentsById.get(String(activeSegmentId || '')) || null;
        let selectedStageAnchor = null;
        let insertLabel = 'Insert step here';
        if (selectedStage) {
            let anchorStage = selectedStage;
            if (
                activeSegment
                && Array.isArray(activeSegment.stageKeys)
                && activeSegment.stageKeys.includes(String(selectedStage.stage_key || ''))
                && String(activeSegment.endStageKey || '') !== String(selectedStage.stage_key || '')
            ) {
                anchorStage = (draft.document.stages || []).find((item) =>
                    String(item.stage_key || '') === String(activeSegment.endStageKey || ''),
                ) || selectedStage;
                insertLabel = `Insert after ${String(activeSegment.label || 'section')}`;
            }
            selectedStageAnchor = _insertAnchorForStage(anchorStage, projection);
        } else if (selection.sectionKey === 'segments' && activeSegment?.endStageKey) {
            const anchorStage = (draft.document.stages || []).find((item) =>
                String(item.stage_key || '') === String(activeSegment.endStageKey || ''),
            ) || null;
            selectedStageAnchor = anchorStage ? _insertAnchorForStage(anchorStage, projection) : null;
            insertLabel = `Insert after ${String(activeSegment.label || 'section')}`;
        }
        const insertAnchor = selectedTransition
            ? {
                sourceStageKey: selectedTransition.from_stage_key,
                decision: selectedTransition.decision,
            }
            : selectedStageAnchor;
        const defaultAddAnchor = insertAnchor || (progress.stageCount ? _appendStageInsertAnchor(projection) : null);
        const focusedSurface = _focusedSecondarySurfaceKey();
        const mapVisible = focusedSurface === 'map';
        const settingsVisible = focusedSurface === 'protocol' || focusedSurface === 'artifacts';
        const actions = [
            {
                label: settingsVisible ? 'Back to workflow' : 'Protocol settings',
                tone: 'btn-small',
                onClick: () => (settingsVisible ? _closeFocusedSurface() : _openProtocolSettings()),
            },
            {
                label: mapVisible ? 'Hide workflow map' : 'Show workflow map',
                tone: 'btn-small',
                onClick: () => (mapVisible ? _closeFocusedSurface() : _openWorkflowMap()),
            },
            ...(rehearsal.runId ? [{
                label: editorMode.kind === 'rehearse' ? 'Back to authoring' : 'View rehearsal',
                tone: 'btn-small',
                onClick: () => _setEditorMode({ kind: editorMode.kind === 'rehearse' ? 'idle' : 'rehearse' }),
            }] : []),
        ];
        if (!selectedStage && !selectedTransition && !activeSegmentId) {
            actions.splice(2, 0, {
                label: progress.stageCount ? Kit.dict.label('protocol.stages.add') : 'Add first step',
                tone: 'btn-small',
                onClick: () => _startStageInsert(defaultAddAnchor || {}),
                disabled: !canMutate,
            });
        }
        return actions;
    }

    function _sceneOutline(projection, nodeStates, activeSegmentId = '') {
        return projection.segments.map((segment) => ({
            id: String(segment.id || ''),
            kind: 'segment',
            label: String(segment.label || 'Untitled section'),
            meta: '',
            expanded: String(segment.id || '') === String(activeSegmentId || ''),
            items: _segmentStageList(segment).map((stage) => ({
                id: String(stage.stage_key || ''),
                kind: 'stage',
                label: _segmentStageDisplayLabel(segment, stage),
                meta: String(nodeStates?.[String(stage.stage_key || '')] || ''),
            })),
        }));
    }

    function _workflowStoryScene(projection, { compact = false } = {}) {
        const orderedSegments = (Array.isArray(projection.segmentOrder) && projection.segmentOrder.length
            ? projection.segmentOrder.map((segmentId) => projection.segmentsById.get(String(segmentId || '')))
            : projection.segments)
            .filter(Boolean);
        const nodes = orderedSegments.map((segment) => ({
            id: String(segment.id || ''),
            kind: 'segment',
            label: String(segment.label || 'Untitled section'),
            meta: '',
            secondary: '',
            width: compact ? 144 : 168,
            height: compact ? 44 : 48,
        }));
        const edges = orderedSegments.slice(1).map((segment, index) => ({
            id: `story:${String(orderedSegments[index]?.id || '')}::${String(segment.id || '')}`,
            from: String(orderedSegments[index]?.id || ''),
            to: String(segment.id || ''),
            label: '',
            primary: true,
        }));
        return {
            title: 'Workflow stages',
            subtitle: 'Build the workflow from the stage stack. Open the map only when you want spatial context.',
            hint: editorMode.kind === 'rehearse' ? 'Rehearsal is active. Workflow state is annotated on the same canvas while authoring is paused.' : '',
            outlineTitle: 'Workflow outline',
            direction: 'DOWN',
            fitPadding: compact ? 14 : 40,
            nodeSpacing: compact ? 14 : 24,
            layerSpacing: compact ? 22 : 54,
            emptyHint: 'Add the first step to start shaping the workflow.',
            graph: { nodes, edges },
            focusIds: nodes.map((node) => node.id),
        };
    }

    function _focusedWorkflowScene(projection, nodeStates, activeSegment, { compact = false } = {}) {
        const focusStageKey = _focusStageKey(projection, activeSegment);
        const doc = draft.document;
        const nodes = [];
        const edges = [];
        const nodeIds = new Set();
        const stageKeys = new Set((activeSegment?.stageKeys || []).map((item) => String(item || '')));

        function pushNode(node) {
            if (!node || nodeIds.has(String(node.id || ''))) return;
            nodeIds.add(String(node.id || ''));
            nodes.push(node);
        }

        function pushExternalSegment(segmentId, labelOverride = '') {
            const target = projection.segmentsById.get(String(segmentId || ''));
            if (!target) return;
            pushNode({
                id: String(target.id || ''),
                kind: 'segment',
                label: String(labelOverride || target.label || 'Section'),
                meta: '',
                secondary: '',
                width: compact ? 144 : 168,
                height: compact ? 48 : 54,
                context: true,
            });
        }

        (activeSegment?.stages || []).forEach((stage) => {
            pushNode({
                id: String(stage.stage_key || ''),
                kind: 'stage',
                label: String(stage.display_name || stage.stage_key || 'Untitled step'),
                meta: String(nodeStates?.[String(stage.stage_key || '')] || ''),
                secondary: '',
                width: compact ? 168 : 188,
                height: compact ? 74 : 84,
            });
        });

        (activeSegment?.incomingSegments || []).forEach((segmentId) => pushExternalSegment(segmentId));
        (activeSegment?.outgoingEdges || []).forEach((edge) => {
            if (edge.targetKind === 'segment') pushExternalSegment(edge.targetKey);
        });

        _segmentFinishLabels(activeSegment).forEach((label, index) => {
            pushNode({
                id: `outcome:${index}:${String(label || '')}`,
                kind: 'outcome',
                label: String(label || 'Finish'),
                meta: '',
                width: compact ? 138 : 148,
                height: compact ? 52 : 56,
            });
        });

        (activeSegment?.stages || []).forEach((stage) => {
            Object.entries(stage.transitions || {}).forEach(([decision, target]) => {
                const decisionKey = String(decision || '').trim().toLowerCase();
                const targetKey = String(target || '').trim();
                if (!targetKey) return;
                const transitionId = _stageTransitionId(stage.stage_key, decisionKey);
                if (stageKeys.has(targetKey)) {
                    edges.push({
                        id: transitionId,
                        from: String(stage.stage_key || ''),
                        to: targetKey,
                        label: _showEdgeLabel({ decision: decisionKey }, stage, 'topology')
                            ? _protocolDecisionLabel(decisionKey)
                            : '',
                        primary: String(stage.stage_key || '') === focusStageKey || targetKey === focusStageKey,
                        muted: String(stage.stage_key || '') !== focusStageKey && targetKey !== focusStageKey,
                    });
                    return;
                }
                if (PROTOCOL_TERMINAL_TARGETS.some((item) => item.key === targetKey)) {
                    const label = _transitionTargetLabel(targetKey, doc);
                    edges.push({
                        id: transitionId,
                        from: String(stage.stage_key || ''),
                        to: nodes.find((node) => node.kind === 'outcome' && node.label === label)?.id || '',
                        label: _protocolDecisionLabel(decisionKey),
                        primary: true,
                    });
                    return;
                }
                const targetSegmentId = String(projection.stageToSegment.get(targetKey) || '');
                if (!targetSegmentId) return;
                edges.push({
                    id: transitionId,
                    from: String(stage.stage_key || ''),
                    to: targetSegmentId,
                    label: _protocolDecisionLabel(decisionKey),
                    primary: Number(projection.segmentsById.get(targetSegmentId)?.column || 0) > Number(activeSegment?.column || 0),
                    muted: Number(projection.segmentsById.get(targetSegmentId)?.column || 0) <= Number(activeSegment?.column || 0),
                });
            });
        });

        (activeSegment?.incomingSegments || []).forEach((segmentId) => {
            const sourceSegment = projection.segmentsById.get(segmentId);
            if (!sourceSegment) return;
            const inboundEdges = (sourceSegment.outgoingEdges || []).filter((edge) => String(edge.targetKey || '') === String(activeSegment?.id || ''));
            inboundEdges.forEach((edge) => {
                edges.push({
                    id: `context:${String(edge.id || '')}`,
                    from: String(sourceSegment.id || ''),
                    to: String(activeSegment?.stageKeys?.[0] || ''),
                    label: String(edge.label || ''),
                    muted: true,
                });
            });
        });

        const selectedStage = _selectionStage(draft.document)
            || (draft.document.stages || []).find((item) => String(item.stage_key || '') === String(_activeStageKey() || ''))
            || null;
        const focusLabel = selectedStage
            ? _segmentStageDisplayLabel(activeSegment, selectedStage)
            : String(activeSegment?.label || 'section');

        return {
            title: 'Workflow stages',
            subtitle: `Focused on ${focusLabel}. Edit the selected step inline and open the map only when you need route context.`,
            hint: editorMode.kind === 'rehearse' ? 'Rehearsal is active. Workflow state is annotated on the same canvas while authoring is paused.' : '',
            outlineTitle: 'Workflow outline',
            direction: compact ? 'DOWN' : 'RIGHT',
            fitPadding: compact ? 18 : 56,
            nodeSpacing: compact ? 20 : 30,
            layerSpacing: compact ? 36 : 68,
            graph: { nodes, edges: edges.filter((edge) => edge.from && edge.to) },
            focusIds: nodes.map((node) => String(node.id || '')),
        };
    }

    function _workflowData() {
        const projection = _buildWorkflowProjection(draft.document);
        const progress = _workflowProgress(draft.document);
        const nodeStates = rehearsal.runId ? _rehearsalNodeStates() : {};
        const activeSegmentId = _selectionSegmentId(projection);
        const activeSegment = projection.segmentsById.get(activeSegmentId) || null;
        const density = _workflowDensityProfile(projection);
        const compact = _isCompactViewport();
        const scene = activeSegment
            ? _focusedWorkflowScene(projection, nodeStates, activeSegment, { compact })
            : _workflowStoryScene(projection, { compact });
        return {
            projection,
            progress,
            density,
            nodeStates,
            firstRun: _firstRunState(progress),
            toolbarActions: _workflowToolbarActions(progress, projection),
            viewState: {
                title: scene.title,
                subtitle: scene.subtitle,
                hint: scene.hint,
            },
            scene: {
                ...scene,
                key: [
                    String(activeSegmentId || ''),
                    ...((scene.graph?.nodes || []).map((item) => String(item.id || ''))),
                    ...((scene.graph?.edges || []).map((item) => String(item.id || ''))),
                ].join('|'),
                outline: _sceneOutline(projection, nodeStates, activeSegmentId),
                keyboardOrder: [
                    ...projection.segments.map((segment) => ({ kind: 'segment', id: String(segment.id || '') })),
                    ...projection.segments.flatMap((segment) => (segment.stages || []).map((stage) => ({
                        kind: 'stage',
                        id: String(stage.stage_key || ''),
                    }))),
                ],
            },
        };
    }

    function _rehearsalNodeStates() {
        const states = {};
        (rehearsal.runDetail?.stage_executions || []).forEach((stage) => {
            const key = String(stage.stage_key || '').trim();
            if (!key) return;
            states[key] = String(stage.status || '').trim() || 'queued';
        });
        (rehearsal.sessions || []).forEach((session) => {
            const key = String(session.stage_key || '').trim();
            if (!key) return;
            states[key] = session.state || 'awaiting response';
        });
        return states;
    }

    function _surfaceSelection() {
        const sourceStageKey = _selectionSourceStageKey();
        return {
            kind: selection.sectionKey === 'segments'
                ? 'segment'
                : selection.sectionKey === 'transitions'
                    ? 'transition'
                    : selection.sectionKey === 'participants'
                        ? 'participant'
                        : selection.sectionKey === 'artifacts'
                            ? 'artifact'
                        : selection.sectionKey === 'stages' || sourceStageKey
                            ? 'stage'
                            : 'overview',
            id: selection.sectionKey === 'stages' ? selection.nodeKey : (sourceStageKey || selection.nodeKey),
        };
    }

    function _surfaceSelect(workflow, kind, id) {
        const currentSurface = _focusedSecondarySurfaceKey();
        if (kind === 'segment') {
            selection = _normalizeSelectionForProjection({ sectionKey: 'segments', nodeKey: id }, workflow.projection);
        } else if (kind === 'transition') {
            selection = { sectionKey: 'transitions', nodeKey: id };
        } else if (kind === 'stage') {
            _queueStageViewportAnchor(String(id || ''));
            selection = { sectionKey: 'stages', nodeKey: id };
        } else if (kind === 'participant') {
            selection = { sectionKey: 'participants', nodeKey: id };
        } else if (kind === 'artifact') {
            selection = { sectionKey: 'artifacts', nodeKey: id };
        } else {
            selection = { sectionKey: 'overview', nodeKey: '' };
        }
        if (currentSurface === 'map') {
            _setWorkflowMapMode('hidden', { rerender: false });
        }
        render();
    }

    function _surfaceHeaderEl({ title = '', note = '', actions = [] } = {}) {
        const head = document.createElement('div');
        head.className = 'kit-authoring-surface-head';

        const copy = document.createElement('div');
        copy.className = 'kit-authoring-surface-copy';
        const heading = document.createElement('h3');
        heading.className = 'kit-stage-editor-hero-title';
        heading.textContent = String(title || '');
        copy.appendChild(heading);
        if (String(note || '').trim()) {
            const noteEl = document.createElement('p');
            noteEl.className = 'kit-stage-editor-hero-note';
            noteEl.textContent = String(note || '');
            copy.appendChild(noteEl);
        }
        head.appendChild(copy);

        const actionRow = document.createElement('div');
        actionRow.className = 'kit-protocol-segment-step-actions';
        (Array.isArray(actions) ? actions : []).forEach((item) => {
            if (!item || typeof item.onClick !== 'function') return;
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `btn${String(item.tone || '').trim() ? ` ${String(item.tone || '').trim()}` : ''}`;
            button.textContent = String(item.label || '');
            button.addEventListener('click', item.onClick);
            actionRow.appendChild(button);
        });
        if (actionRow.childElementCount) {
            head.appendChild(actionRow);
        }
        return head;
    }

    function _workflowMapEl(workflow) {
        return Kit.workflowCanvas({
            scene: workflow.scene,
            mode: 'graph',
            editorMode,
            viewportState: { zoom: _canvasZoomValue() },
            mapVisible: true,
            showOutline: false,
            onViewportChange: (zoom) => _setCanvasViewport(zoom),
            selection: _surfaceSelection(),
            onSelect: ({ kind, id }) => _surfaceSelect(workflow, kind, id),
            onMutate: ({ type }) => {
                if (type === 'undo') {
                    _restoreHistory('undo');
                    return;
                }
                if (type === 'redo') {
                    _restoreHistory('redo');
                }
            },
        });
    }

    function _workflowMapPanelEl(workflow, { closeAction = null } = {}) {
        const panel = document.createElement('section');
        panel.className = 'kit-protocol-inline-card kit-authoring-map-panel kit-authoring-secondary-surface';
        panel.dataset.key = 'protocol-authoring-map-panel';
        panel.appendChild(_surfaceHeaderEl({
            title: 'Workflow map',
            note: 'Use the map for route context and structure review. It stays fully interactive here: click a step to jump back into the inline editor, zoom when needed, then close it to continue authoring.',
            actions: closeAction ? [{ label: 'Back to workflow', onClick: closeAction }] : [],
        }));
        panel.appendChild(_workflowMapEl(workflow));
        return panel;
    }

    function _editorContext(workflow = null) {
        const doc = draft.document;
        const projection = workflow?.projection || _buildWorkflowProjection(doc);
        const density = workflow?.density || _workflowDensityProfile(projection);
        const readOnly = editorMode.kind === 'rehearse';
        const applyReadOnly = (schema) => (!readOnly
            ? schema
            : schema.map((field) => ({
                ...field,
                disabled: field.kind === 'checkbox' || field.kind === 'select' ? true : field.disabled,
                readOnly: field.kind !== 'checkbox' && field.kind !== 'select' ? true : field.readOnly,
            })));
        const participantOptions = [
            { value: '', label: 'Unassigned for now' },
            ...((doc.participants || []).map((p) => ({
                value: String(p.participant_key || ''),
                label: String(p.display_name || p.participant_key || ''),
            }))),
        ];
        const stageParticipantOptions = [...participantOptions, { value: '__new__', label: 'Create new role…' }];
        const kindOptions = _manifestStageKindOptions().map((value) => ({
            value,
            label: Kit.dict.label(`protocol.stage.kind.${value}`, value),
        }));
        const artifactOptions = (doc.artifacts || []).map((item) => ({
            value: String(item.artifact_key || ''),
            label: _artifactOptionLabel(item),
        }));
        return {
            doc,
            projection,
            readOnly,
            applyReadOnly,
            participantOptions,
            stageParticipantOptions,
            kindOptions,
            artifactOptions,
            density,
        };
    }

    function _protocolSettingsPanelEl(context) {
        return Kit.detailsPanel({
            target: {
                description: draft.description,
                single_active_writer: Boolean(draft.document.policies?.single_active_writer ?? true),
                max_review_rounds: Number(draft.document.policies?.max_review_rounds || 5) || 5,
            },
            surfaceKey: 'protocol',
            onCommit: context.readOnly ? null : _commitOverview,
            schema: context.applyReadOnly([
                { key: 'description', kind: 'textarea', rows: 4 },
                ...((draft.document.stages || []).length ? [
                    { key: 'single_active_writer', kind: 'checkbox', labelKey: 'protocol.policy.single_active_writer.label', helpKey: 'protocol.policy.single_active_writer.help' },
                    { key: 'max_review_rounds', kind: 'text', labelKey: 'protocol.policy.max_review_rounds.label', helpKey: 'protocol.policy.max_review_rounds.help' },
                ] : []),
            ]),
        });
    }

    function _selectionArtifact(doc = draft.document) {
        if (selection.sectionKey !== 'artifacts') return null;
        return (doc.artifacts || []).find((item) => String(item.artifact_key || '') === String(selection.nodeKey || '')) || null;
    }

    function _deleteArtifact(artifactKey) {
        const normalizedArtifactKey = String(artifactKey || '').trim();
        if (!normalizedArtifactKey) return;
        const doc = _cloneDoc(draft.document);
        doc.artifacts = (doc.artifacts || []).filter((item) => String(item.artifact_key || '') !== normalizedArtifactKey);
        doc.stages = (doc.stages || []).map((stage) => ({
            ...stage,
            inputs: (stage.inputs || []).filter((item) => String(item || '') !== normalizedArtifactKey),
            outputs: (stage.outputs || []).filter((item) => String(item || '') !== normalizedArtifactKey),
        }));
        const sourceStageKey = _selectionSourceStageKey();
        _commitDocument(doc, {
            nextSelection: sourceStageKey
                ? {
                    sectionKey: 'artifacts',
                    nodeKey: '',
                    sourceStageKey,
                    surfaceKey: String(selection?.surfaceKey || 'secondary') === 'local' ? 'local' : 'secondary',
                }
                : {
                    sectionKey: 'artifacts',
                    nodeKey: '',
                    sourceStageKey: '',
                    surfaceKey: String(selection?.surfaceKey || 'secondary') === 'local' ? 'local' : 'secondary',
                },
        });
    }

    function _confirmArtifactDelete(artifactKey) {
        const artifact = (draft.document.artifacts || []).find((item) => String(item.artifact_key || '') === String(artifactKey || ''));
        if (!artifact) return;
        const artifactLabel = String(artifact.display_name || artifact.artifact_key || 'this artifact');
        UI.showConfirm(
            'Delete artifact',
            `Delete ${artifactLabel}? Any step inputs or outputs referencing it will be cleared.`,
            async () => { _deleteArtifact(artifactKey); },
        );
    }

    function _artifactEditorEl(artifact, context) {
        const artifactKey = String(artifact?.artifact_key || '').trim();
        const shell = document.createElement('div');
        shell.className = 'kit-stage-editor';
        shell.dataset.key = `protocol-artifact-editor:${artifactKey}`;

        const guide = document.createElement('div');
        guide.className = 'kit-artifact-guide';
        const guideNote = document.createElement('p');
        guideNote.className = 'kit-stage-editor-hero-note';
        guideNote.textContent = 'Artifacts are the concrete files or text that steps pass between each other. Use workspace files for datasets, code, documents, PDFs, and reports. Use run-carried text only for small notes or structured text that should not live in the workspace.';
        guide.appendChild(guideNote);

        const facts = document.createElement('div');
        facts.className = 'kit-artifact-guide-facts';
        [
            {
                label: 'Represents',
                value: _artifactPurposeLabel(artifact),
            },
            {
                label: 'Stored at',
                value: _artifactDefinitionPath(artifact) || (String(artifact?.kind || '').trim().toLowerCase() === 'control_plane_text'
                    ? 'In the run record instead of the workspace'
                    : 'Pick a workspace-relative path'),
            },
            {
                label: 'Verification',
                value: artifact?.verify === false ? 'Optional' : 'Required before a writing step can complete',
            },
        ].forEach((item) => {
            const stat = document.createElement('div');
            stat.className = 'kit-artifact-guide-fact';
            const statLabel = document.createElement('strong');
            statLabel.className = 'kit-artifact-guide-fact-label';
            statLabel.textContent = String(item.label || '');
            stat.appendChild(statLabel);
            const statValue = document.createElement('span');
            statValue.className = 'kit-artifact-guide-fact-value';
            statValue.textContent = String(item.value || '');
            stat.appendChild(statValue);
            facts.appendChild(stat);
        });
        guide.appendChild(facts);
        shell.appendChild(guide);

        const kindOptions = _manifestArtifactKindOptions().map((value) => ({
            value,
            label: Kit.dict.label(`protocol.artifact.kind.${value}`, value),
        }));
        const onCommit = context.readOnly
            ? null
            : (_target, key, value) => {
                const activeArtifactKey = String(
                    selection.sectionKey === 'artifacts'
                        ? selection.nodeKey || artifactKey
                        : artifactKey,
                ).trim();
                _commitNodeField('artifact', activeArtifactKey, key, value);
            };

        const basics = Kit.detailsPanel({
            target: artifact,
            surfaceKey: 'protocol.artifact',
            onCommit,
            schema: context.applyReadOnly([
                { key: 'display_name', kind: 'text', label: 'Name', required: true, commitOnInput: true },
                { key: 'kind', kind: 'select', label: 'What it represents', options: kindOptions, help: 'Most datasets, code files, documents, and reports should stay as workspace files.' },
                ...(String(artifact?.kind || 'workspace_file').trim().toLowerCase() === 'control_plane_text'
                    ? []
                    : [{ key: 'path', kind: 'text', label: 'Workspace path', help: Kit.dict.label('protocol.artifact.path.help'), placeholder: Kit.dict.label('protocol.artifact.path.placeholder'), commitOnInput: true }]),
            ]),
            actions: context.readOnly
                ? []
                : [{ label: 'Delete artifact', tone: 'btn-danger', onClick: () => _confirmArtifactDelete(artifactKey) }],
        });
        shell.appendChild(_stageEditorSection('Artifact basics', basics));

        const details = Kit.detailsPanel({
            target: artifact,
            surfaceKey: 'protocol.artifact',
            onCommit,
            schema: context.applyReadOnly([
                { key: 'description', kind: 'textarea', rows: 4 },
                {
                    key: 'verify',
                    kind: 'checkbox',
                    label: 'Require verification',
                    help: 'Keep this enabled when a writing step should not complete until the artifact is observed or verified.',
                },
            ]),
        });
        shell.appendChild(_stageEditorSection('Details', details, {
            wide: true,
            collapsible: true,
            open: Boolean(String(artifact?.description || '').trim()),
            stateKey: `artifact:${artifactKey}:details`,
        }));

        const usage = _artifactUsage(context.doc, artifactKey);
        const usagePanel = document.createElement('div');
        usagePanel.className = 'kit-artifact-usage';
        if (!usage.reads.length && !usage.writes.length) {
            usagePanel.appendChild(UI.renderEmptyState('This artifact is not attached to any step yet. Define it here first, then attach it in a step’s inputs and outputs section.', true));
        } else {
            [
                { label: 'Needed by', items: usage.reads },
                { label: 'Produced by', items: usage.writes },
            ].forEach((group) => {
                if (!group.items.length) return;
                const groupEl = document.createElement('div');
                groupEl.className = 'kit-artifact-usage-group';
                const groupLabel = document.createElement('strong');
                groupLabel.className = 'kit-artifact-usage-label';
                groupLabel.textContent = String(group.label || '');
                groupEl.appendChild(groupLabel);
                const list = document.createElement('div');
                list.className = 'kit-artifact-usage-list';
                group.items.forEach((item) => {
                    const chip = document.createElement('span');
                    chip.className = 'badge';
                    chip.textContent = String(item || '');
                    list.appendChild(chip);
                });
                groupEl.appendChild(list);
                usagePanel.appendChild(groupEl);
            });
        }
        shell.appendChild(_stageEditorSection('Used by steps', usagePanel, {
            wide: true,
            collapsible: true,
            open: Boolean(usage.reads.length || usage.writes.length),
            stateKey: `artifact:${artifactKey}:usage`,
        }));
        return shell;
    }

    function _artifactCatalogEl(context, {
        sourceStageKey = '',
        showTitle = true,
        closeAction = null,
        surfaceKey = 'secondary',
    } = {}) {
        const panel = document.createElement('section');
        panel.className = 'kit-protocol-inline-card';
        if (showTitle) {
            panel.appendChild(_surfaceHeaderEl({
                title: 'Workflow files and outputs',
                note: sourceStageKey
                    ? 'Define or refine the shared files and outputs this step needs, then return to the same step to attach them.'
                    : 'Define shared datasets, code files, documents, reports, or run-carried text once here. Steps attach reads and writes to these definitions later.',
                actions: closeAction ? [{ label: sourceStageKey ? 'Back to step' : 'Back to workflow', onClick: closeAction }] : [],
            }));
        }

        const actions = document.createElement('div');
        actions.className = 'kit-protocol-segment-step-actions';
        if (!context.readOnly) {
            const add = document.createElement('button');
            add.type = 'button';
            add.className = 'btn btn-small';
            add.textContent = 'Add artifact';
            add.addEventListener('click', () => _addArtifact(sourceStageKey, surfaceKey));
            actions.appendChild(add);
        }
        if (actions.childElementCount) panel.appendChild(actions);

        const list = document.createElement('div');
        list.className = 'kit-protocol-stage-stack';
        const selectedArtifactKey = String(selection.sectionKey === 'artifacts' ? selection.nodeKey || '' : '');
        (context.doc.artifacts || []).forEach((artifact) => {
            const artifactKey = String(artifact.artifact_key || '');
            const entry = document.createElement('div');
            entry.className = 'kit-protocol-segment-entry';
            entry.dataset.key = `protocol-artifact-entry:${artifactKey}`;

            const row = document.createElement('button');
            row.type = 'button';
            row.className = `kit-protocol-segment-step${selectedArtifactKey === artifactKey ? ' is-selected' : ''}`;
            row.dataset.testid = `workflow-artifact-${artifactKey}`;
            row.dataset.key = `protocol-artifact-row:${artifactKey}`;
            row.addEventListener('click', () => {
                selection = {
                    sectionKey: 'artifacts',
                    nodeKey: artifactKey,
                    sourceStageKey: String(sourceStageKey || '').trim(),
                    surfaceKey: String(surfaceKey || 'secondary') === 'local' ? 'local' : 'secondary',
                };
                render();
            });

            const titleRow = document.createElement('div');
            titleRow.className = 'kit-protocol-segment-step-head';
            const label = document.createElement('strong');
            label.className = 'kit-protocol-segment-step-title';
            label.textContent = String(artifact.display_name || artifact.artifact_key || 'Untitled artifact');
            titleRow.appendChild(label);
            row.appendChild(titleRow);

            const summary = document.createElement('div');
            summary.className = 'kit-protocol-segment-step-meta';
            summary.textContent = [
                _artifactPurposeLabel(artifact),
                _artifactDefinitionPath(artifact),
                _artifactUsageSummary(context.doc, artifactKey),
            ].filter(Boolean).join(' · ');
            row.appendChild(summary);
            entry.appendChild(row);

            if (selectedArtifactKey === artifactKey) {
                const inline = document.createElement('div');
                inline.className = 'kit-protocol-inline-editor';
                inline.dataset.key = `protocol-artifact-inline:${artifactKey}`;
                inline.appendChild(_artifactEditorEl(artifact, context));
                entry.appendChild(inline);
            }

            list.appendChild(entry);
        });
        if (!list.childElementCount) {
            list.appendChild(UI.renderEmptyState('No shared files or outputs yet. Add one here, then attach it from a step’s inputs and outputs section.', true));
        }
        panel.appendChild(list);
        return panel;
    }

    function _stageEditorTarget(stage) {
        return {
            ...stage,
            selector_mode: _currentStageAssignmentMode(String(stage?.stage_key || ''), String(stage?.selector?.kind || '')),
            selector_kind: String(stage?.selector?.kind || ''),
            selector_value: String(stage?.selector?.value || ''),
            selector_preferred_agent_id: String(stage?.selector?.preferred_agent_id || ''),
        };
    }

    function _activeStageKey() {
        const sourceStageKey = _selectionSourceStageKey();
        if (sourceStageKey) {
            return sourceStageKey;
        }
        if (editorMode.kind === 'create-route') {
            return String(pendingRoute.source_stage_key || '');
        }
        if (editorMode.kind === 'insert-stage') {
            return String(editorMode.sourceStageKey || '');
        }
        if (selection.sectionKey === 'stages' && selection.nodeKey) {
            return String(selection.nodeKey || '');
        }
        if (selection.sectionKey === 'transitions' && selection.nodeKey) {
            return String(selection.nodeKey || '').split('::')[0] || '';
        }
        return '';
    }

    function _toggleStageSelection(stageKey) {
        const nextKey = String(stageKey || '');
        if (!nextKey) return;
        if (String(_activeStageKey() || '') === nextKey) {
            if (selection.sectionKey === 'artifacts' && _selectionSourceStageKey() === nextKey) {
                _queueStageViewportAnchor(nextKey, { panelKey: 'artifacts' });
                selection = { sectionKey: 'stages', nodeKey: nextKey };
                render();
                return;
            }
            if (selection.sectionKey === 'transitions' && String(selection.nodeKey || '').startsWith(`${nextKey}::`)) {
                _queueStageViewportAnchor(nextKey, { panelKey: 'routing' });
                selection = { sectionKey: 'stages', nodeKey: nextKey };
                render();
                return;
            }
            if (selection.sectionKey === 'stages' && String(selection.nodeKey || '') === nextKey) {
                selection = { sectionKey: 'overview', nodeKey: '' };
                render();
                return;
            }
        }
        _queueStageViewportAnchor(nextKey);
        selection = { sectionKey: 'stages', nodeKey: nextKey };
        render();
    }

    function _stageInsertMatchesDefaultAnchor(stage, projection) {
        if (editorMode.kind !== 'insert-stage') return false;
        const anchor = _insertAnchorForStage(stage, projection);
        return Boolean(anchor
            && String(anchor.sourceStageKey || '') === String(editorMode.sourceStageKey || '')
            && String(anchor.decision || '') === String(editorMode.decision || ''));
    }

    function _inlineStageInsertEl(context) {
        const shell = _stageEditorShell({
            target: pendingStage,
            stageKey: String(pendingStage.stage_key || ''),
            participantOptions: context.stageParticipantOptions,
            kindOptions: context.kindOptions,
            artifactOptions: context.artifactOptions,
            editorContext: context,
            onCommit: _commitPendingStageField,
            createAction: _confirmStageInsert,
            cancelAction: _cancelStageInsert,
            createHint: _workflowInsertHint(),
        });
        shell.dataset.key = [
            'protocol-inline-insert',
            String(editorMode.sessionKey || ''),
            String(editorMode.sourceStageKey || ''),
            String(editorMode.decision || ''),
            String(pendingStage.display_name || ''),
            String(pendingStage.stage_kind || ''),
            String(pendingStage.participant_key || ''),
            String(pendingStage.selector_mode || ''),
            String(pendingStage.selector_kind || ''),
            String(pendingStage.selector_value || ''),
            String(pendingStage.selector_preferred_agent_id || ''),
            String(pendingStage.role_display_name || ''),
            String(pendingStage.role_participant_key || ''),
        ].join(':');
        return shell;
    }

    function _inlineRouteEditorEl(stageKey, context) {
        const stage = (context.doc.stages || []).find((item) => String(item.stage_key || '') === String(stageKey || ''));
        if (!stage) return null;
        if (editorMode.kind === 'create-route' && String(pendingRoute.source_stage_key || '') === String(stageKey || '')) {
            return _routeEditorPanel({
                target: {
                    source_stage: String(stage.display_name || stage.stage_key || ''),
                    decision: String(pendingRoute.decision || ''),
                    target_key: String(pendingRoute.target_key || ''),
                },
                sourceStage: stage,
                projection: context.projection,
                onCommit: _commitPendingRouteField,
                createAction: _confirmRouteInsert,
                cancelAction: _cancelRouteInsert,
            });
        }
        if (selection.sectionKey !== 'transitions') return null;
        const target = _transitionEntries(context.doc).find((item) => String(item.id || '') === String(selection.nodeKey || ''));
        if (!target || String(target.from_stage_key || '') !== String(stageKey || '')) return null;
        return _routeEditorPanel({
            target: {
                source_stage: String(stage.display_name || stage.stage_key || target.from_stage_key || ''),
                decision: String(target.decision || ''),
                target_key: String(target.target_key || ''),
            },
            sourceStage: stage,
            projection: context.projection,
            readOnly: context.readOnly,
            onCommit: context.readOnly ? null : (_t, key, value) => _commitTransitionField(selection.nodeKey, key, value),
            insertAction: context.readOnly ? null : () => _startStageInsert({
                sourceStageKey: target.from_stage_key,
                decision: target.decision,
            }),
            deleteAction: context.readOnly ? null : () => UI.showConfirm(
                'Remove transition',
                'Remove this transition from the workflow?',
                async () => { _deleteTransition(selection.nodeKey); },
            ),
            cancelAction: () => {
                _setStageWorkspacePanelValue(String(stageKey || ''), 'routing');
                _queueStageViewportAnchor(String(stageKey || ''), { panelKey: 'routing' });
                selection = { sectionKey: 'stages', nodeKey: String(stageKey || '') };
                render();
            },
            cancelLabel: 'Back to step',
        });
    }

    function _stageEditorEl(stage, context, { routeEditor = null, embedded = false } = {}) {
        const shell = _stageEditorShell({
            target: _stageEditorTarget(stage),
            stageKey: String(stage.stage_key || ''),
            readOnly: context.readOnly,
            participantOptions: context.participantOptions,
            kindOptions: context.kindOptions,
            artifactOptions: context.artifactOptions,
            editorContext: context,
            onCommit: context.readOnly
                ? null
                : (_t, key, value) => _commitNodeField('stage', String(stage.stage_key || ''), key, value),
            connectAction: context.readOnly ? null : () => _startRouteInsert(String(stage.stage_key || '')),
            deleteAction: context.readOnly ? null : () => _confirmStageDelete(String(stage.stage_key || '')),
            closeAction: embedded ? null : () => {
                selection = { sectionKey: 'overview', nodeKey: '' };
                render();
            },
            routeEditor,
            embedded,
        });
        shell.dataset.key = `protocol-stage-editor:${String(stage.stage_key || '')}`;
        return shell;
    }

    function _protocolSettingsSectionEl(context) {
        const sourceStageKey = _selectionSourceStageKey();
        const card = document.createElement('section');
        card.className = 'kit-protocol-inline-card kit-authoring-secondary-surface';
        card.appendChild(_surfaceHeaderEl({
            title: selection.sectionKey === 'artifacts' ? 'Workflow files and outputs' : 'Protocol settings',
            note: selection.sectionKey === 'artifacts'
                ? 'Manage the shared files and outputs used across the workflow, then return to the same step or overview.'
                : 'Adjust protocol-wide description and policies here without leaving the workflow.',
            actions: [{ label: 'Back to workflow', onClick: () => _closeFocusedSurface() }],
        }));
        const toggle = UI.createSegmentedControl(
            [
                { value: 'protocol', label: 'Settings' },
                { value: 'artifacts', label: 'Workflow files' },
            ],
            (value) => {
                selection = {
                    sectionKey: String(value || 'protocol'),
                    nodeKey: '',
                    sourceStageKey,
                    surfaceKey: 'secondary',
                };
                render();
            },
            {
                label: 'Protocol management surface',
                value: selection.sectionKey === 'artifacts' ? 'artifacts' : 'protocol',
            },
        );
        card.appendChild(toggle.element);
        if (selection.sectionKey === 'artifacts') {
            card.appendChild(_artifactCatalogEl(context, {
                sourceStageKey,
                showTitle: false,
                surfaceKey: 'secondary',
            }));
        } else {
            card.appendChild(_protocolSettingsPanelEl(context));
        }
        return card;
    }

    function _segmentPanelEl(segment, workflow, context) {
        const density = workflow?.density || _workflowDensityProfile(context?.projection);
        const panel = document.createElement('section');
        panel.className = 'kit-protocol-segment-panel';
        panel.dataset.key = `protocol-segment-panel:${String(segment.id || '')}`;
        panel.dataset.testid = `workflow-segment-${String(segment.id || '')}`;
        panel.dataset.density = String(density?.band || 'comfortable');

        const head = document.createElement('div');
        head.className = 'kit-protocol-segment-head';
        const firstStageLabel = String(segment?.stages?.[0]?.display_name || segment?.stages?.[0]?.stage_key || '').trim().toLowerCase();
        const segmentLabel = String(segment?.label || 'Section');
        const showSegmentTitle = Boolean(segmentLabel.trim()) && segmentLabel.trim().toLowerCase() !== firstStageLabel;
        const title = document.createElement('h3');
        title.className = 'kit-protocol-segment-step-title';
        title.textContent = segmentLabel;
        if (showSegmentTitle) {
            head.appendChild(title);
        }
        if (density?.showSegmentSubtitle) {
            const subtitle = document.createElement('p');
            subtitle.className = 'kit-protocol-segment-step-meta';
            subtitle.textContent = `${Array.isArray(segment?.stages) ? segment.stages.length : 0} step${segment?.stages?.length === 1 ? '' : 's'} in this section.`;
            head.appendChild(subtitle);
        }
        if (head.childElementCount) {
            panel.appendChild(head);
        }

        const activeStageKey = _activeStageKey();
        const selectedTransition = selection.sectionKey === 'transitions'
            ? _selectionTransition(context.doc)
            : null;
        const list = document.createElement('div');
        list.className = 'kit-protocol-segment-steps';
        list.dataset.density = String(density?.band || 'comfortable');

        (Array.isArray(segment?.stages) ? segment.stages : []).forEach((stage) => {
            const stageKey = String(stage.stage_key || '');
            const entry = document.createElement('div');
            entry.className = 'kit-protocol-segment-entry';
            entry.dataset.key = `protocol-segment-entry:${stageKey}`;
            entry.dataset.stageRow = stageKey;
            entry.classList.toggle('is-active', activeStageKey === stageKey);

            const row = document.createElement('button');
            row.type = 'button';
            row.className = `kit-protocol-segment-step${activeStageKey === stageKey ? ' is-selected' : ''}`;
            row.dataset.testid = `workflow-stage-${stageKey}`;
            row.dataset.stageRow = stageKey;
            row.setAttribute('aria-expanded', activeStageKey === stageKey ? 'true' : 'false');
            row.addEventListener('click', () => _toggleStageSelection(stageKey));

            const titleRow = document.createElement('div');
            titleRow.className = 'kit-protocol-segment-step-head';
            const label = document.createElement('strong');
            label.className = 'kit-protocol-segment-step-title';
            const stageLabel = String(stage.display_name || stage.stage_key || 'Untitled step');
            label.textContent = stageLabel;
            titleRow.appendChild(label);
            const state = String(workflow?.nodeStates?.[stageKey] || '');
            if (state) {
                const badge = document.createElement('span');
                badge.className = 'kit-workflow-node-state';
                badge.textContent = state;
                titleRow.appendChild(badge);
            }
            row.appendChild(titleRow);

            const stageSummary = _stageRowSummary(stage, context.doc, density, {
                selected: activeStageKey === stageKey,
            });
            if (stageSummary) {
                const summary = document.createElement('div');
                summary.className = 'kit-protocol-segment-step-meta';
                summary.textContent = stageSummary;
                row.appendChild(summary);
            }
            if (activeStageKey === stageKey) {
                const focusHead = document.createElement('div');
                focusHead.className = 'kit-protocol-stage-focus-head';
                focusHead.dataset.stageWorkspaceAnchor = stageKey;
                focusHead.appendChild(row);
                const actionRow = document.createElement('div');
                actionRow.className = 'kit-protocol-segment-step-actions';
                const done = document.createElement('button');
                done.type = 'button';
                done.className = 'btn btn-small';
                done.textContent = 'Done';
                done.addEventListener('click', (event) => {
                    event.stopPropagation();
                    selection = { sectionKey: 'overview', nodeKey: '' };
                    render();
                });
                actionRow.appendChild(done);
                if (!context.readOnly) {
                    const remove = document.createElement('button');
                    remove.type = 'button';
                    remove.className = 'btn btn-small btn-danger';
                    remove.textContent = 'Delete step';
                    remove.addEventListener('click', (event) => {
                        event.stopPropagation();
                        _confirmStageDelete(stageKey);
                    });
                    actionRow.appendChild(remove);
                }
                focusHead.appendChild(actionRow);
                entry.appendChild(focusHead);
            } else {
                entry.appendChild(row);
            }

            if (activeStageKey === stageKey) {
                const inline = document.createElement('div');
                inline.className = 'kit-protocol-inline-editor';
                const routeEditor = _inlineRouteEditorEl(stageKey, context);
                const showPendingInsert = editorMode.kind === 'insert-stage'
                    && String(editorMode.sourceStageKey || '') === stageKey
                    && (
                        (selectedTransition
                            && String(selectedTransition.from_stage_key || '') === stageKey
                            && String(selectedTransition.decision || '') === String(editorMode.decision || ''))
                        || _stageInsertMatchesDefaultAnchor(stage, context.projection)
                    );
                if (!showPendingInsert) {
                    inline.appendChild(_stageEditorEl(stage, context, {
                        routeEditor,
                        embedded: true,
                    }));
                }
                if (showPendingInsert) {
                    inline.appendChild(_inlineStageInsertEl(context));
                }
                entry.appendChild(inline);

                if (!context.readOnly && !showPendingInsert) {
                    const insertSlot = document.createElement('div');
                    insertSlot.className = 'kit-protocol-insert-slot';
                    const add = document.createElement('button');
                    add.type = 'button';
                    add.className = 'kit-protocol-insert-button';
                    add.dataset.testid = `workflow-insert-after-${stageKey}`;
                    add.setAttribute('aria-label', `Add step below ${stageLabel}`);
                    add.addEventListener('click', () => {
                        const anchor = _insertAnchorForStage(stage, context.projection);
                        _startStageInsert(anchor || {});
                    });
                    const icon = document.createElement('span');
                    icon.className = 'kit-protocol-insert-icon';
                    icon.textContent = '+';
                    add.appendChild(icon);
                    const insertLabel = document.createElement('span');
                    insertLabel.className = 'kit-protocol-insert-label';
                    insertLabel.textContent = 'Add step';
                    add.appendChild(insertLabel);
                    insertSlot.appendChild(add);
                    entry.appendChild(insertSlot);
                }
            }

            list.appendChild(entry);
        });

        if (!list.childElementCount && editorMode.kind === 'insert-stage') {
            list.appendChild(_inlineStageInsertEl(context));
        }
        panel.appendChild(list);
        return panel;
    }

    function _progressiveWorkflowEl(workflow) {
        const context = _editorContext(workflow);
        const root = document.createElement('div');
        root.className = 'kit-authoring-primary-column';
        root.dataset.key = 'protocol-authoring-primary-column';
        const focusedSurface = _focusedSecondarySurfaceKey();
        root.dataset.focusedSurface = String(focusedSurface || '');
        root.appendChild(Kit.workflowHeaderBar({
            firstRun: workflow.firstRun,
            editorMode,
            viewState: workflow.viewState,
            toolbarActions: workflow.toolbarActions,
        }));

        if (focusedSurface === 'map') {
            root.appendChild(_workflowMapPanelEl(workflow, {
                closeAction: () => _closeFocusedSurface(),
            }));
            return root;
        }

        if (focusedSurface === 'protocol' || focusedSurface === 'artifacts') {
            root.appendChild(_protocolSettingsSectionEl(context));
            return root;
        }

        const stack = document.createElement('div');
        stack.className = 'kit-protocol-stage-stack';
        stack.dataset.selection = String(selection.sectionKey || 'overview');
        stack.dataset.density = String(workflow?.density?.band || 'comfortable');
        workflow.projection.segments.forEach((segment) => {
            stack.appendChild(_segmentPanelEl(segment, workflow, context));
        });
        if (!workflow.projection.segments.length && editorMode.kind === 'insert-stage') {
            stack.appendChild(_inlineStageInsertEl(context));
        }
        root.appendChild(stack);

        const validation = editorMode.kind === 'rehearse' ? null : _validationEl();
        if (validation) {
            root.appendChild(validation);
        }
        if (editorMode.kind === 'rehearse' || rehearsal.runId) {
            root.appendChild(Kit.rehearsalPanel({
                runId: rehearsal.runId,
                sessions: rehearsal.sessions,
                scenarios: rehearsal.scenarios,
                drafts: rehearsal.drafts,
                onDraftChange: (payload) => { _updateRehearsalDraft(payload); },
                onRespond: (payload) => { void _respondRehearsal(payload); },
            }));
        }
        return root;
    }

    function _stageEditorSection(title, panel, { wide = false, collapsible = false, open = true, stateKey = '', showTitle = true } = {}) {
        const section = document.createElement(collapsible ? 'details' : 'section');
        section.className = `kit-stage-editor-section${wide ? ' is-wide' : ''}${collapsible ? ' is-collapsible' : ''}`;
        if (collapsible) {
            section.dataset.sectionStateKey = String(stateKey || '');
            section.open = _sectionStateValue(stateKey, open);
            if (String(stateKey || '').trim()) {
                section.addEventListener('toggle', () => _setSectionStateValue(stateKey, section.open));
            }
            if (showTitle) {
                const summary = document.createElement('summary');
                summary.className = 'kit-stage-editor-summary';
                const heading = document.createElement('h4');
                heading.className = 'kit-stage-editor-title';
                heading.textContent = String(title || '');
                summary.appendChild(heading);
                section.appendChild(summary);
            }
        } else {
            if (showTitle) {
                const heading = document.createElement('h4');
                heading.className = 'kit-stage-editor-title';
                heading.textContent = String(title || '');
                section.appendChild(heading);
            }
        }
        section.appendChild(panel);
        return section;
    }

    function _stageWorkspaceSubsection(title, panel) {
        const shell = document.createElement('section');
        shell.className = 'kit-stage-workspace-subsection';
        const heading = document.createElement('h5');
        heading.className = 'kit-stage-workspace-subtitle';
        heading.textContent = String(title || '');
        shell.appendChild(heading);
        shell.appendChild(panel);
        return shell;
    }

    function _stageArtifactsEditor({
        target,
        stageKey = '',
        readOnly = false,
        onCommit = null,
        artifactOptions = [],
        context = null,
        deferCatalogUntilStageCreated = false,
    } = {}) {
        const shell = document.createElement('div');
        shell.className = 'kit-stage-artifacts';
        const normalizedStageKey = String(stageKey || target?.stage_key || '').trim();
        const localArtifactManagerVisible = selection.sectionKey === 'artifacts'
            && String(selection?.surfaceKey || 'secondary') === 'local'
            && String(_selectionSourceStageKey() || '') === normalizedStageKey;
        shell.dataset.key = localArtifactManagerVisible
            ? `stage-artifacts:${normalizedStageKey}:local:${String(selection.nodeKey || '').trim()}`
            : `stage-artifacts:${normalizedStageKey}:attachments`;

        if (localArtifactManagerVisible && context) {
            const actions = document.createElement('div');
            actions.className = 'kit-stage-routing-actions';
            const back = document.createElement('button');
            back.type = 'button';
            back.className = 'btn btn-small';
            back.textContent = 'Back to attachments';
            back.addEventListener('click', () => {
                _setStageWorkspacePanelValue(normalizedStageKey, 'artifacts');
                selection = { sectionKey: 'stages', nodeKey: normalizedStageKey };
                _queueStageViewportAnchor(normalizedStageKey, { panelKey: 'artifacts' });
                render();
            });
            actions.appendChild(back);
            shell.appendChild(actions);
            shell.appendChild(_artifactCatalogEl(context, {
                sourceStageKey: normalizedStageKey,
                surfaceKey: 'local',
                showTitle: false,
            }));
            return shell;
        }

        if (!artifactOptions.length) {
            const note = document.createElement('p');
            note.className = 'kit-stage-editor-hero-note';
            note.textContent = deferCatalogUntilStageCreated
                ? 'Create this step before defining new workflow files or outputs. This keeps the unsaved step draft visible and prevents file definitions from being attached to a step that does not exist yet.'
                : 'Define the shared files or outputs this step should read or write, then attach them here.';
            shell.appendChild(note);
            shell.appendChild(UI.renderEmptyState('No workflow files or outputs are defined yet.', true));
            if (!readOnly && !deferCatalogUntilStageCreated) {
                const actions = document.createElement('div');
                actions.className = 'kit-stage-routing-actions';
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'btn btn-small';
                button.textContent = 'Define files and outputs';
                button.addEventListener('click', () => _openArtifactCatalog('', { stageKey: normalizedStageKey, surfaceKey: 'local' }));
                actions.appendChild(button);
                shell.appendChild(actions);
            }
            return shell;
        }

        shell.appendChild(Kit.detailsPanel({
            target,
            surfaceKey: 'protocol.stage',
            onCommit,
            schema: [
                { key: 'inputs', kind: 'checklist', options: artifactOptions, label: 'Needs from earlier steps', help: 'Check the shared files or text this step reads before it can run.', disabled: readOnly },
                { key: 'outputs', kind: 'checklist', options: artifactOptions, label: 'Produces for later steps', help: 'Check the shared files or text this step should create or update for later steps.', disabled: readOnly },
            ],
        }));
        if (!readOnly) {
            const actions = document.createElement('div');
            actions.className = 'kit-stage-routing-actions';
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'btn btn-small';
            if (deferCatalogUntilStageCreated) {
                button.textContent = 'Create step before managing files';
                button.disabled = true;
                button.title = 'Save the new step first, then manage workflow files from the saved step.';
                actions.appendChild(button);
                const note = document.createElement('p');
                note.className = 'quiet-note';
                note.textContent = 'Existing workflow files can be attached now. New file definitions are managed after the step is created.';
                actions.appendChild(note);
            } else {
                button.textContent = 'Manage workflow files';
                button.addEventListener('click', () => {
                    _openArtifactCatalog('', { stageKey: normalizedStageKey, surfaceKey: 'local' });
                });
                actions.appendChild(button);
            }
            shell.appendChild(actions);
        }
        return shell;
    }

    function _stageRoutingPanel(stage, { readOnly = false, connectAction = null, density = null, routeEditor = null } = {}) {
        const panel = document.createElement('div');
        panel.className = 'kit-stage-routing';

        const head = document.createElement('div');
        head.className = 'kit-stage-routing-head';

        const intro = document.createElement('p');
        intro.className = 'kit-stage-routing-copy';
        intro.textContent = density?.compactCopy
            ? 'Only add branches when this step can split or finish in different ways.'
            : 'Use branches only when this step can go to different next steps or finish outcomes.';
        head.appendChild(intro);

        if (!readOnly && typeof connectAction === 'function') {
            const add = document.createElement('button');
            add.type = 'button';
            add.className = 'btn btn-small';
            add.textContent = 'Add branch or finish';
            add.addEventListener('click', connectAction);
            head.appendChild(add);
        }
        panel.appendChild(head);

        const routes = _transitionEntries(draft.document)
            .filter((item) => String(item.from_stage_key || '') === String(stage?.stage_key || ''))
            .map((item) => ({
                ...item,
                decisionLabel: _protocolDecisionLabel(item.decision),
                targetLabel: _transitionTargetLabel(item.target_key, draft.document),
            }));

        if (!routes.length) {
            const empty = document.createElement('div');
            empty.className = 'kit-stage-routing-empty';
            empty.textContent = readOnly
                ? 'No routes are defined for this step yet.'
                : 'No branches yet. Add a finish outcome or another next step from here when this step can split.';
            panel.appendChild(empty);
            if (routeEditor) {
                const editorShell = document.createElement('div');
                editorShell.className = 'kit-stage-routing-editor';
                editorShell.appendChild(routeEditor);
                panel.appendChild(editorShell);
            }
            return panel;
        }

        const list = document.createElement('div');
        list.className = 'kit-stage-routing-list';
        routes.forEach((route) => {
            const entry = document.createElement('div');
            entry.className = 'kit-stage-routing-entry';

            const row = document.createElement('button');
            row.type = 'button';
            row.className = `kit-stage-routing-item${selection.sectionKey === 'transitions' && selection.nodeKey === route.id ? ' is-selected' : ''}`;
            row.dataset.testid = `stage-route-${String(route.id || '')}`;
            row.addEventListener('click', () => {
                _setStageWorkspacePanelValue(String(stage?.stage_key || ''), 'routing');
                _queueStageViewportAnchor(String(stage?.stage_key || ''), { panelKey: 'routing' });
                selection = { sectionKey: 'transitions', nodeKey: route.id };
                render();
            });

            const badge = document.createElement('span');
            badge.className = 'kit-stage-routing-badge';
            badge.textContent = String(route.decisionLabel || route.decision || '');
            row.appendChild(badge);

            const body = document.createElement('div');
            body.className = 'kit-stage-routing-body';

            const title = document.createElement('strong');
            title.className = 'kit-stage-routing-target';
            title.textContent = String(route.targetLabel || route.target_key || '');
            body.appendChild(title);

            const meta = document.createElement('span');
            meta.className = 'kit-stage-routing-meta';
            meta.textContent = PROTOCOL_TERMINAL_TARGETS.some((item) => item.key === route.target_key)
                ? 'Finish outcome'
                : 'Open route details';
            body.appendChild(meta);

            row.appendChild(body);
            entry.appendChild(row);

            if (!readOnly) {
                const actions = document.createElement('div');
                actions.className = 'kit-stage-routing-actions';
                const insert = document.createElement('button');
                insert.type = 'button';
                insert.className = 'btn btn-small';
                insert.textContent = `Insert before ${String(route.targetLabel || route.target_key || 'this target')}`;
                insert.addEventListener('click', () => _startStageInsert({
                    sourceStageKey: String(stage?.stage_key || ''),
                    decision: String(route.decision || ''),
                }));
                actions.appendChild(insert);
                entry.appendChild(actions);
            }

            list.appendChild(entry);
        });
        panel.appendChild(list);
        if (routeEditor) {
            const editorShell = document.createElement('div');
            editorShell.className = 'kit-stage-routing-editor';
            editorShell.appendChild(routeEditor);
            panel.appendChild(editorShell);
        }
        return panel;
    }

    function _stageEditorShell({
        target,
        stageKey = '',
        readOnly = false,
        participantOptions = [],
        kindOptions = [],
        artifactOptions = [],
        editorContext = null,
        onCommit = null,
        connectAction = null,
        createAction = null,
        cancelAction = null,
        deleteAction = null,
        closeAction = null,
        createHint = '',
        routeEditor = null,
        embedded = false,
    } = {}) {
        const applyReadOnly = (schema) => (!readOnly
            ? schema
            : schema.map((field) => ({
                ...field,
                disabled: field.kind === 'checkbox' || field.kind === 'select' ? true : field.disabled,
                readOnly: field.kind !== 'checkbox' && field.kind !== 'select' ? true : field.readOnly,
            })));
        const operatorSurface = _currentAuthoringSurface() === 'operator';
        const normalizedStageKey = String(stageKey || target?.stage_key || '').trim();
        const stageSectionKeyBase = createAction
            ? `pending:${String(editorMode.sessionKey || 'new')}`
            : normalizedStageKey;
        const stageWorkspaceAnchorKey = normalizedStageKey || stageSectionKeyBase;
        const density = editorContext?.density || _workflowDensityProfile(editorContext?.projection);
        const includeRouting = !createAction;
        const includeAdvanced = operatorSurface;
        const defaultPanel = _stageWorkspaceDefaultPanel(normalizedStageKey || stageSectionKeyBase, {
            includeRouting,
            createAction: Boolean(createAction),
        });
        const forcedPanel = normalizedStageKey && selection.sectionKey === 'artifacts' && _selectionSourceStageKey() === normalizedStageKey
            ? 'artifacts'
            : normalizedStageKey && selection.sectionKey === 'transitions' && String(selection.nodeKey || '').startsWith(`${normalizedStageKey}::`)
                ? 'routing'
                : '';
        const activePanelKey = forcedPanel || _stageWorkspacePanelValue(stageSectionKeyBase, defaultPanel, {
            includeRouting,
            includeAdvanced,
        });
        const shell = document.createElement('div');
        shell.className = `kit-stage-editor${embedded ? ' is-embedded' : ''}`;
        shell.dataset.density = String(density?.band || 'comfortable');
        shell.dataset.activePanel = String(activePanelKey || 'basics');
        const stageLabel = String(target?.display_name || target?.stage_key || '').trim() || (createAction ? 'New step' : 'Step');
        const stageSummaryNote = createAction
            ? String(createHint || '')
            : _stageRowSummary(target, editorContext?.doc || draft.document, density, { selected: true });
        if (!embedded || createAction) {
            shell.appendChild(_surfaceHeaderEl({
                title: createAction ? 'New step' : stageLabel,
                note: stageSummaryNote,
                actions: [
                    ...(createAction ? [{ label: 'Create step', tone: 'btn-primary', onClick: createAction }] : []),
                    ...(closeAction ? [{ label: 'Done', onClick: closeAction }] : []),
                    ...(cancelAction ? [{ label: createAction ? 'Cancel' : 'Back', onClick: cancelAction }] : []),
                    ...(deleteAction ? [{ label: 'Delete step', tone: 'btn-danger', onClick: deleteAction }] : []),
                ],
            }));
        }
        if (createAction && createHint && !stageSummaryNote) {
            const note = document.createElement('p');
            note.className = 'kit-stage-editor-hero-note';
            note.textContent = String(createHint || '');
            shell.appendChild(note);
        }
        const summaryPanel = Kit.detailsPanel({
            target,
            surfaceKey: 'protocol.stage',
            onCommit,
            schema: applyReadOnly([
                { key: 'display_name', kind: 'text', required: true, commitOnInput: Boolean(createAction) },
                { key: 'participant_key', kind: 'select', options: participantOptions },
                { key: 'stage_kind', kind: 'select', options: kindOptions },
            ]),
        });
        const basicsBody = document.createElement('div');
        basicsBody.className = 'kit-stage-workspace-body';
        basicsBody.appendChild(summaryPanel);
        if (String(target?.participant_key || '') === '__new__') {
            const rolePanel = Kit.detailsPanel({
                target,
                surfaceKey: 'protocol.participant',
                onCommit,
                schema: applyReadOnly([
                    { key: 'role_display_name', kind: 'text', label: 'Role name', help: 'Fill this in when this step should create a new reusable role instead of reusing the selected owner role.', commitOnInput: true },
                    { key: 'role_participant_key', kind: 'text', label: 'Role key', help: 'Internal reference for this role. It is generated from the role name.', commitOnInput: true },
                    { key: 'role_instructions', kind: 'textarea', rows: 3, label: 'Shared instructions', help: 'Optional guidance shared by every step that uses this role.', commitOnInput: true },
                ]),
            });
            basicsBody.appendChild(_stageWorkspaceSubsection('New owner role', rolePanel));
        }
        const assignmentPanel = _selectorEditor({
            stageKey: createAction ? '' : String(target?.stage_key || ''),
            selectorMode: String(target?.selector_mode || ''),
            selectorKind: String(target?.selector_kind || ''),
            selectorValue: String(target?.selector_value || ''),
            selectorPreferredAgentId: String(target?.selector_preferred_agent_id || ''),
            readOnly,
            onChange: createAction ? _commitPendingStageField : onCommit,
            density,
            onSelectorChange: createAction
                ? (kind, value, preferredAgentId) => _commitPendingStageSelector(kind, value, preferredAgentId)
                : (typeof onCommit === 'function' && target?.stage_key
                    ? (kind, value, preferredAgentId) => _commitStageSelector(String(target.stage_key || ''), kind, value, preferredAgentId)
                    : null),
        });

        const instructionsPanel = Kit.detailsPanel({
            target,
            surfaceKey: 'protocol.stage',
            onCommit,
            schema: applyReadOnly([
                { key: 'instructions', kind: 'textarea', rows: 6 },
            ]),
        });

        const artifactsPanel = _stageArtifactsEditor({
            target,
            stageKey: normalizedStageKey,
            readOnly,
            onCommit,
            artifactOptions,
            context: editorContext,
            deferCatalogUntilStageCreated: Boolean(createAction),
        });

        const panelOptions = [
            { value: 'basics', label: 'Basics' },
            { value: 'assignment', label: 'Assignment' },
            ...(!createAction ? [{ value: 'routing', label: 'Routing' }] : []),
            { value: 'instructions', label: 'Instructions' },
            { value: 'artifacts', label: 'Files & outputs' },
            ...(operatorSurface ? [{ value: 'advanced', label: 'Advanced' }] : []),
        ];

        const panelControl = UI.createSegmentedControl(
            panelOptions,
            null,
            {
                label: 'Stage work area',
                value: activePanelKey,
            },
        );
        panelControl.element.classList.add('kit-stage-workspace-nav');
        panelControl.element.dataset.stageWorkspaceNav = 'true';
        panelControl.element.dataset.workspaceKey = stageSectionKeyBase;
        panelControl.element.dataset.includeRouting = includeRouting ? 'true' : 'false';
        panelControl.element.dataset.includeAdvanced = includeAdvanced ? 'true' : 'false';
        panelControl.element.dataset.anchorStageKey = normalizedStageKey || String(editorMode.sourceStageKey || '');
        if (embedded && !createAction) {
            const workspaceToolbar = document.createElement('div');
            workspaceToolbar.className = 'kit-stage-workspace-toolbar';
            workspaceToolbar.appendChild(panelControl.element);
            shell.appendChild(workspaceToolbar);
        } else {
            shell.appendChild(panelControl.element);
        }

        const workspace = document.createElement('div');
        workspace.className = 'kit-stage-editor-grid kit-stage-workspace-panel';
        workspace.dataset.panel = String(activePanelKey || 'basics');
        if (createAction) {
            workspace.dataset.pendingStageEditor = 'true';
        }
        if (stageWorkspaceAnchorKey) {
            workspace.dataset.stageWorkspaceAnchor = stageWorkspaceAnchorKey;
        }

        const appendPanelSection = (title, panel, { wide = true } = {}) => {
            workspace.appendChild(_stageEditorSection(title, panel, {
                wide,
                showTitle: createAction || !embedded,
            }));
        };

        if (activePanelKey === 'basics') {
            appendPanelSection('Step basics', basicsBody);
        } else if (activePanelKey === 'assignment') {
            appendPanelSection('Assignment', assignmentPanel);
        } else if (activePanelKey === 'routing' && !createAction) {
            appendPanelSection('Routing', _stageRoutingPanel(target, {
                readOnly,
                connectAction,
                density,
                routeEditor,
            }));
        } else if (activePanelKey === 'instructions') {
            appendPanelSection('Instructions', instructionsPanel);
        } else if (activePanelKey === 'artifacts') {
            appendPanelSection('Inputs and outputs', artifactsPanel);
        }

        if (operatorSurface) {
            const advancedPanel = Kit.detailsPanel({
                target,
                surfaceKey: 'protocol.stage',
                onCommit,
                schema: applyReadOnly([
                    { key: 'stage_key', kind: 'text' },
                    { key: 'max_rounds', kind: 'text' },
                    { key: 'timeout_seconds', kind: 'text' },
                ]),
            });
            if (activePanelKey === 'advanced') {
                appendPanelSection('Advanced', advancedPanel);
            }
        }
        shell.appendChild(workspace);
        return shell;
    }

    function _validationEl() {
        const normalized = [];
        if (saveState.state === 'conflict' && draftConflict?.serverDetail?.protocol) {
            normalized.push({
                severity: 'error',
                message: 'This draft changed in another tab or client. Reload the latest server copy before validating, publishing, archiving, or rehearsing.',
                action: { label: 'Reload', onClick: _reloadServerDraftConflict },
            });
            normalized.push({
                severity: 'warning',
                message: 'If your local edits should win, reload the latest server draft first and then explicitly overwrite it.',
                action: {
                    label: 'Overwrite',
                    onClick: () => UI.showConfirm(
                        'Overwrite server draft',
                        'This reloads the latest server draft revision and immediately reapplies your current local edits on top of it.',
                        async () => { await _overwriteServerDraftConflict(); },
                    ),
                },
            });
        }
        if ((draft.document.stages || []).length === 0) {
            return normalized.length ? Kit.validationSurface({ issues: normalized, layout: 'summary' }) : null;
        }
        const validation = currentProtocol?.validation;
        if (!validation && !normalized.length) return null;
        const issues = Array.isArray(validation?.issues) ? validation.issues : [];
        const filteredIssues = issues.filter((item) => {
            const code = String(item.code || '');
            if (!(draft.document.stages || []).length && ["metadata.slug_required", "participants.required", "stages.required"].includes(code)) {
                return false;
            }
            return true;
        });
        normalized.push(...(filteredIssues.length
            ? filteredIssues.map((item) => ({
                severity: String(item.severity || 'error'),
                message: String(item.message || ''),
                path: String(item.path || ''),
            }))
            : (Array.isArray(validation?.errors) ? validation.errors : []).map((text) => ({
                severity: 'error',
                message: String(text || ''),
            }))));
        if (!normalized.length) {
            return null;
        }
        return Kit.validationSurface({ issues: normalized, layout: 'summary' });
    }

    function _manifestStageKindOptions() {
        return Array.isArray(authoringOptions?.stage_kind_options) && authoringOptions.stage_kind_options.length
            ? authoringOptions.stage_kind_options
            : ['work', 'review', 'acceptance'];
    }

    function _manifestArtifactKindOptions() {
        return Array.isArray(authoringOptions?.artifact_kind_options) && authoringOptions.artifact_kind_options.length
            ? authoringOptions.artifact_kind_options
            : ['workspace_file', 'control_plane_text'];
    }

    function _templateChooserEl() {
        const templates = UI.defaultVisibleRecords(
            Array.isArray(protocolTemplates) ? protocolTemplates : [],
            { includeHidden: includeGeneratedCatalog },
        );
        const shell = document.createElement('section');
        shell.className = 'editor-panel protocol-panel';
        shell.dataset.testid = 'protocol-template-chooser';

        const head = document.createElement('div');
        head.className = 'kit-catalog-hero';
        const copy = document.createElement('div');
        copy.className = 'kit-catalog-hero-copy';
        const title = document.createElement('h3');
        title.className = 'kit-catalog-hero-title';
        title.textContent = 'Start a protocol';
        copy.appendChild(title);
        const body = document.createElement('p');
        body.className = 'kit-catalog-hero-body';
        body.textContent = 'Create a blank workflow, or copy one of your saved templates into a separate protocol you can edit without changing the template.';
        copy.appendChild(body);
        head.appendChild(copy);
        shell.appendChild(head);

        const actions = document.createElement('div');
        actions.className = 'editor-actions';
        const blank = document.createElement('button');
        blank.type = 'button';
        blank.className = 'btn btn-primary';
        blank.textContent = 'Start blank';
        blank.dataset.protocolTemplateChooserAction = 'blank';
        actions.appendChild(blank);
        const auto = document.createElement('button');
        auto.type = 'button';
        auto.className = 'btn';
        auto.textContent = 'Auto protocol';
        auto.addEventListener('click', () => _openAutoProtocolDialog({ mode: 'create', ignoreRememberedSession: true }));
        actions.appendChild(auto);
        const cancel = document.createElement('button');
        cancel.type = 'button';
        cancel.className = 'btn';
        cancel.textContent = 'Close';
        cancel.dataset.protocolTemplateChooserAction = 'close';
        actions.appendChild(cancel);
        shell.appendChild(actions);

        const list = document.createElement('div');
        list.className = 'kit-catalog-list';
        if (!templates.length) {
            list.appendChild(UI.renderEmptyState('No saved templates are available yet.', true));
            shell.appendChild(list);
            return shell;
        }
        templates.forEach((template) => {
            const card = document.createElement('section');
            card.className = 'kit-catalog-card protocol-template-card';
            const top = document.createElement('div');
            top.className = 'kit-catalog-card-top';
            const copyBlock = document.createElement('div');
            copyBlock.className = 'kit-catalog-card-copy';
            const cardTitle = document.createElement('div');
            cardTitle.className = 'kit-catalog-card-title';
            cardTitle.textContent = String(template.display_name || template.slug || 'Template');
            copyBlock.appendChild(cardTitle);
            const slug = document.createElement('div');
            slug.className = 'kit-catalog-card-slug';
            slug.textContent = String(template.slug || '');
            copyBlock.appendChild(slug);
            top.appendChild(copyBlock);
            const cardActions = document.createElement('div');
            cardActions.className = 'editor-actions';
            const use = document.createElement('button');
            use.type = 'button';
            use.className = 'btn btn-primary';
            use.textContent = 'Review and create';
            use.dataset.protocolTemplateSlug = String(template.slug || '');
            cardActions.appendChild(use);
            top.appendChild(cardActions);
            card.appendChild(top);

            const description = document.createElement('p');
            description.className = 'kit-catalog-card-body';
            description.textContent = String(template.description || 'Reusable protocol template.');
            card.appendChild(description);

            const meta = document.createElement('div');
            meta.className = 'kit-catalog-card-meta';
            [
                `${Number(template.participant_count || 0)} roles`,
                `${Number(template.stage_count || 0)} steps`,
                `${Number(template.artifact_count || 0)} files`,
            ].forEach((label) => {
                const item = document.createElement('span');
                item.className = 'kit-catalog-card-meta-item';
                item.textContent = label;
                meta.appendChild(item);
            });
            card.appendChild(meta);
            list.appendChild(card);
        });
        shell.appendChild(list);
        return shell;
    }

    function _autoProtocolSessionStatusLabel(session) {
        const status = String(session?.status || '').trim().toLowerCase();
        const taskStatus = String(session?.planner_state?.planner_status || '').trim().toLowerCase();
        if (status === 'planning') return taskStatus ? `Planning · ${taskStatus.replace(/_/g, ' ')}` : 'Planning';
        if (status === 'ready') return 'Ready to review';
        if (status === 'applied') return 'Draft applied';
        if (status === 'published') return 'Published';
        if (status === 'running') return 'Run started';
        if (status === 'blocked') return 'Blocked';
        if (status === 'failed') return 'Failed';
        return status ? _titleCaseWords(status.replace(/_/g, ' ')) : 'Unknown';
    }

    function _autoProtocolSessionStatusBadgeClass(session) {
        const status = String(session?.status || '').trim().toLowerCase();
        const taskStatus = String(session?.planner_state?.planner_status || '').trim().toLowerCase();
        if (status === 'planning') {
            if (taskStatus === 'queued') return 'badge-queued';
            if (taskStatus === 'cancelled' || taskStatus === 'canceled') return 'badge-cancelled';
            if (taskStatus === 'failed' || taskStatus === 'timed_out') return 'badge-failed';
            return 'badge-running';
        }
        if (status === 'ready' || status === 'applied' || status === 'published' || status === 'running') return 'badge-connected';
        if (status === 'blocked') return 'badge-degraded';
        if (status === 'failed') return 'badge-failed';
        if (status === 'cancelled' || status === 'canceled') return 'badge-cancelled';
        return 'badge-open';
    }

    function _autoProtocolSessionTitle(session) {
        const plan = session?.plan || {};
        const analysis = session?.analysis || {};
        return String(
            plan.protocol_name
            || analysis.focus
            || session?.requirement_text
            || 'Auto Protocol design',
        ).replace(/\s+/g, ' ').trim();
    }

    function _autoProtocolSessionAgentLabel(session) {
        return _autoProtocolSelectedAgentLabel(session, [
            ..._availableAuthoringAgents(),
            ..._authoringAssignableAgents(),
        ]);
    }

    function _autoProtocolSessionBody(session) {
        const plannerState = session?.planner_state || {};
        const progress = String(plannerState.progress_summary || '').trim();
        if (progress) return progress;
        const status = String(session?.status || '').trim().toLowerCase();
        if (status === 'planning') return 'Planner work is in progress and will keep updating this design session.';
        if (status === 'ready') return 'Generated draft is ready for review before applying, publishing, or running.';
        if (status === 'applied') return 'Generated draft has been applied to the protocol catalog.';
        if (status === 'published') return 'Generated protocol has been published.';
        if (status === 'running') return 'Generated protocol was published and a run has been started.';
        if (status === 'blocked') return 'Design session needs operator review before it can move forward.';
        if (status === 'failed') return String(session?.error_message || 'Planner failed before producing a usable protocol draft.');
        if (session?.planner_task_id) return `Planner job ${session.planner_task_id}`;
        return 'Auto Protocol design session.';
    }

    function _autoProtocolSessionCard(session, { onOpen = null, selected = false } = {}) {
        const item = document.createElement('li');
        item.className = 'kit-catalog-item';

        const card = document.createElement('button');
        card.type = 'button';
        card.className = 'kit-catalog-card protocol-auto-session-card';
        if (selected) card.classList.add('selected');
        card.dataset.autoProtocolSessionId = String(session?.session_id || '');
        card.addEventListener('click', () => {
            if (typeof onOpen === 'function') {
                onOpen(session);
                return;
            }
            _openAutoProtocolDialog({ mode: 'create', sessionId: session.session_id });
        });

        const top = document.createElement('div');
        top.className = 'kit-catalog-card-top';
        const copy = document.createElement('div');
        copy.className = 'kit-catalog-card-copy';
        const title = document.createElement('div');
        title.className = 'kit-catalog-card-title';
        const titleText = _autoProtocolSessionTitle(session);
        title.textContent = titleText.length > 100 ? `${titleText.slice(0, 97).trim()}...` : titleText;
        copy.appendChild(title);
        const slug = document.createElement('div');
        slug.className = 'kit-catalog-card-slug';
        const agentLabel = _autoProtocolSessionAgentLabel(session);
        slug.textContent = agentLabel || 'Auto-selecting planner';
        copy.appendChild(slug);
        top.appendChild(copy);

        const badge = document.createElement('span');
        badge.className = `badge ${_autoProtocolSessionStatusBadgeClass(session)}`;
        badge.textContent = _autoProtocolSessionStatusLabel(session);
        top.appendChild(badge);
        card.appendChild(top);

        const facts = document.createElement('div');
        facts.className = 'kit-catalog-card-meta';
        const plannerState = session?.planner_state || {};
        [
            session?.mode ? `Mode: ${String(session.mode).replace(/_/g, ' ')}` : '',
            session?.planner_policy ? `Policy: ${String(session.planner_policy).replace(/_/g, ' ')}` : '',
            plannerState.queued_at ? `Queued ${UI.relativeTime(plannerState.queued_at)}` : '',
            plannerState.last_progress_at ? `Progress ${UI.relativeTime(plannerState.last_progress_at)}` : '',
            session?.updated_at ? `Updated ${UI.relativeTime(session.updated_at)}` : '',
            session?.planner_task_id ? `Job ${String(session.planner_task_id).slice(0, 8)}` : '',
        ].filter(Boolean).forEach((label) => {
            const item = document.createElement('span');
            item.className = 'kit-catalog-card-meta-item';
            item.textContent = label;
            facts.appendChild(item);
        });
        card.appendChild(facts);

        const body = document.createElement('p');
        body.className = 'kit-catalog-card-body';
        body.textContent = _autoProtocolSessionBody(session);
        card.appendChild(body);

        item.appendChild(card);
        return item;
    }

    function _autoProtocolQueueEl({ full = false } = {}) {
        const items = Array.isArray(autoProtocolSessions) ? autoProtocolSessions : [];
        if (!full && !autoProtocolSessionsLoading && !items.length) return null;

        const shell = document.createElement('section');
        shell.className = 'editor-panel protocol-panel protocol-auto-queue';
        shell.dataset.key = 'protocol-auto-design-queue';

        const head = document.createElement('div');
        head.className = 'kit-catalog-hero';
        const copy = document.createElement('div');
        copy.className = 'kit-catalog-hero-copy';
        const title = document.createElement('h3');
        title.className = 'kit-catalog-hero-title';
        title.textContent = 'Auto Protocol designs';
        copy.appendChild(title);
        const body = document.createElement('p');
        body.className = 'kit-catalog-hero-body';
        body.textContent = 'Planner jobs keep running after a dialog closes. Open a design here to watch progress, review the draft, apply, publish, or run it.';
        copy.appendChild(body);
        head.appendChild(copy);

        const metrics = document.createElement('div');
        metrics.className = 'kit-catalog-hero-metrics';
        const planningCount = items.filter((item) => String(item?.status || '').toLowerCase() === 'planning').length;
        const readyCount = items.filter((item) => String(item?.status || '').toLowerCase() === 'ready').length;
        [
            { label: 'Designing', value: planningCount },
            { label: 'Ready', value: readyCount },
            { label: 'Recent', value: items.length },
        ].forEach((metric) => {
            const chip = document.createElement('div');
            chip.className = 'kit-catalog-hero-metric';
            const value = document.createElement('strong');
            value.className = 'kit-catalog-hero-metric-value';
            value.textContent = String(metric.value);
            chip.appendChild(value);
            const label = document.createElement('span');
            label.className = 'kit-catalog-hero-metric-label';
            label.textContent = metric.label;
            chip.appendChild(label);
            metrics.appendChild(chip);
        });
        head.appendChild(metrics);
        shell.appendChild(head);

        const actions = document.createElement('div');
        actions.className = 'kit-catalog-controls';
        const create = document.createElement('button');
        create.type = 'button';
        create.className = 'btn btn-primary';
        create.textContent = 'New Auto Protocol';
        create.addEventListener('click', () => _openAutoProtocolDialog({ mode: 'create', ignoreRememberedSession: true }));
        actions.appendChild(create);
        if (!full) {
            const viewAll = document.createElement('button');
            viewAll.type = 'button';
            viewAll.className = 'btn';
            viewAll.textContent = 'View all designs';
            viewAll.addEventListener('click', () => Router.navigate('/ui/design-sessions'));
            actions.appendChild(viewAll);
        }
        if (full) {
            const statusFilter = document.createElement('select');
            statusFilter.className = 'input';
            statusFilter.setAttribute('aria-label', 'Design status filter');
            [
                ['', 'All designs'],
                ['planning', 'Planning'],
                ['ready', 'Ready'],
                ['blocked', 'Blocked'],
                ['failed', 'Failed'],
                ['cancelled', 'Cancelled'],
                ['applied', 'Applied'],
                ['published', 'Published'],
                ['running', 'Run started'],
            ].forEach(([value, label]) => {
                const option = document.createElement('option');
                option.value = value;
                option.textContent = label;
                option.selected = value === autoProtocolStatusFilter;
                statusFilter.appendChild(option);
            });
            statusFilter.addEventListener('change', () => {
                autoProtocolStatusFilter = statusFilter.value;
                autoProtocolCursor = 0;
                _writeState({ push: true });
                void loadAutoProtocolSessions({ quiet: false });
            });
            actions.appendChild(statusFilter);
        }
        const refresh = document.createElement('button');
        refresh.type = 'button';
        refresh.className = 'btn';
        refresh.textContent = 'Refresh';
        refresh.addEventListener('click', () => void loadAutoProtocolSessions({ quiet: false }));
        actions.appendChild(refresh);
        shell.appendChild(actions);

        const list = document.createElement('ul');
        list.className = 'kit-catalog-list';
        if (autoProtocolSessionsLoading && !items.length) {
            const loadingItem = document.createElement('li');
            loadingItem.className = 'kit-catalog-item kit-catalog-item-empty';
            loadingItem.appendChild(UI.renderEmptyState('Loading Auto Protocol designs…', true));
            list.appendChild(loadingItem);
        } else {
            const visibleItems = full ? items : items.slice(0, 8);
            if (!visibleItems.length) {
                const empty = document.createElement('li');
                empty.className = 'kit-catalog-item kit-catalog-item-empty';
                empty.appendChild(UI.renderEmptyState('No Auto Protocol design sessions match this view.', false));
                list.appendChild(empty);
            } else {
                visibleItems.forEach((session) => list.appendChild(_autoProtocolSessionCard(session, {
                    selected: full && String(session?.session_id || '') === selectedAutoProtocolSessionId,
                    onOpen: full
                        ? (nextSession) => {
                            selectedAutoProtocolSessionId = String(nextSession?.session_id || '');
                            selectedAutoProtocolSession = nextSession;
                            selectedAutoProtocolEvents = [];
                            autoProtocolQueueActionError = null;
                            autoProtocolQueueRetryAction = '';
                            _rememberActiveAutoProtocolSession(selectedAutoProtocolSession);
                            _writeState({ push: true });
                            void loadSelectedAutoProtocolSession({ quiet: false });
                        }
                        : null,
                })));
            }
        }
        shell.appendChild(list);
        if (full) {
            const paging = document.createElement('div');
            paging.className = 'kit-catalog-controls';
            const previous = document.createElement('button');
            previous.type = 'button';
            previous.className = 'btn';
            previous.textContent = 'Previous';
            previous.disabled = autoProtocolCursor <= 0;
            previous.addEventListener('click', () => {
                autoProtocolCursor = Math.max(0, autoProtocolCursor - 24);
                _writeState({ push: true });
                void loadAutoProtocolSessions({ quiet: false });
            });
            paging.appendChild(previous);
            const next = document.createElement('button');
            next.type = 'button';
            next.className = 'btn';
            next.textContent = 'Next';
            next.disabled = autoProtocolSessionsNextCursor === null;
            next.addEventListener('click', () => {
                if (autoProtocolSessionsNextCursor === null) return;
                autoProtocolCursor = Number(autoProtocolSessionsNextCursor || 0);
                _writeState({ push: true });
                void loadAutoProtocolSessions({ quiet: false });
            });
            paging.appendChild(next);
            shell.appendChild(paging);
        }
        return shell;
    }

    function _autoProtocolDesignSessionDetailEl() {
        const section = document.createElement('section');
        section.className = 'editor-panel protocol-panel protocol-auto-session-detail';
        section.dataset.key = 'protocol-auto-session-detail';
        if (!selectedAutoProtocolSessionId) {
            section.appendChild(UI.renderEmptyState('Select an Auto Protocol design session to inspect progress and actions.', false));
            return section;
        }
        if (autoProtocolDetailLoading && !selectedAutoProtocolSession) {
            section.appendChild(UI.renderEmptyState('Loading design session…', true));
            return section;
        }
        const session = selectedAutoProtocolSession;
        if (!session) {
            section.appendChild(UI.renderEmptyState('Design session was not found or is not visible.', false));
            return section;
        }

        const head = document.createElement('div');
        head.className = 'kit-catalog-card-top';
        const copy = document.createElement('div');
        copy.className = 'kit-catalog-card-copy';
        const title = document.createElement('h3');
        title.className = 'kit-catalog-hero-title';
        title.textContent = _autoProtocolSessionTitle(session);
        copy.appendChild(title);
        const sub = document.createElement('p');
        sub.className = 'quiet-note';
        sub.textContent = [
            session.session_id ? `Session ${String(session.session_id).slice(0, 12)}` : '',
            session.updated_at ? `updated ${UI.relativeTime(session.updated_at)}` : '',
        ].filter(Boolean).join(' · ');
        copy.appendChild(sub);
        head.appendChild(copy);
        const badge = document.createElement('span');
        badge.className = `badge ${_autoProtocolSessionStatusBadgeClass(session)}`;
        badge.textContent = _autoProtocolSessionStatusLabel(session);
        head.appendChild(badge);
        section.appendChild(head);

        const actions = document.createElement('div');
        actions.className = 'kit-catalog-controls';
        const ready = _autoProtocolReady(session);
        const planning = _autoProtocolPlanning(session);
        const hasDraft = _autoProtocolHasDraft(session);
        const addAction = (label, action, primary = false) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = primary ? 'btn btn-primary' : 'btn';
            button.textContent = label;
            const actionKey = `${String(session?.session_id || '')}:${action}`;
            button.disabled = planning || !hasDraft || (action !== 'apply' && !ready) || autoProtocolQueueActionInFlight === actionKey;
            button.addEventListener('click', () => void _runAutoProtocolQueueAction(action));
            actions.appendChild(button);
        };
        addAction('Apply draft', 'apply', !ready);
        addAction('Publish', 'publish');
        addAction('Publish & Run', 'run', ready);
        const openDesigner = document.createElement('button');
        openDesigner.type = 'button';
        openDesigner.className = 'btn';
        openDesigner.textContent = session.target_protocol_id ? 'Open designer' : 'Open dialog';
        openDesigner.addEventListener('click', () => {
            const protocolId = String(session.target_protocol_id || session?.applied_protocol?.protocol?.protocol_id || '').trim();
            if (protocolId) {
                Router.navigate(`/ui/protocols?protocol_id=${encodeURIComponent(protocolId)}`);
                return;
            }
            _openAutoProtocolDialog({ mode: 'create', sessionId: session.session_id });
        });
        actions.appendChild(openDesigner);
        section.appendChild(actions);

        if (autoProtocolQueueActionError) {
            section.appendChild(_autoProtocolErrorEl(
                'Auto Protocol action failed',
                autoProtocolQueueActionError,
                autoProtocolQueueRetryAction
                    ? () => _runAutoProtocolQueueAction(autoProtocolQueueRetryAction)
                    : null,
            ));
        }

        if (planning) {
            section.appendChild(_autoProtocolProgressEl(session));
        } else {
            section.appendChild(_autoProtocolSummaryEl(session));
        }

        const timeline = document.createElement('details');
        timeline.className = 'kit-stage-editor-section is-collapsible protocol-auto-session-events';
        timeline.open = true;
        const summary = document.createElement('summary');
        summary.className = 'kit-stage-editor-summary';
        summary.textContent = `Session events (${selectedAutoProtocolEvents.length})`;
        timeline.appendChild(summary);
        const list = document.createElement('div');
        list.className = 'task-artifact-list';
        UI.reconcileChildren(list, selectedAutoProtocolEvents.length
            ? selectedAutoProtocolEvents.map((event) => UI.renderListRow({
                label: _titleCaseWords(String(event.event_kind || 'event').replace(/_/g, ' ')),
                sublabel: [
                    event.created_at ? UI.relativeTime(event.created_at) : '',
                    event.actor_ref || '',
                ].filter(Boolean).join(' · '),
                badgeText: event.event_kind || '',
            }))
            : [UI.renderEmptyState('No session events have been recorded yet.', false)]);
        timeline.appendChild(list);
        section.appendChild(timeline);
        return section;
    }

    function _autoProtocolDesignSessionsRouteEl() {
        const wrapper = document.createElement('div');
        wrapper.className = 'protocol-catalog-shell protocol-auto-design-sessions-route';
        const queue = _autoProtocolQueueEl({ full: true });
        if (queue) wrapper.appendChild(queue);
        wrapper.appendChild(_autoProtocolDesignSessionDetailEl());
        return wrapper;
    }

    function _catalogEl() {
        const records = UI.defaultVisibleRecords(protocols, { includeHidden: includeGeneratedCatalog });
        const wrapper = document.createElement('div');
        wrapper.className = 'protocol-catalog-shell';
        const queue = _autoProtocolQueueEl();
        if (queue) wrapper.appendChild(queue);
        if (templateChooserMode === 'template' && protocolTemplates.length) {
            wrapper.appendChild(_templateChooserEl());
        }
        const catalog = Kit.authoredCatalog({
            records,
            surfaceKey: 'protocol',
            onOpen: (record) => {
                currentProtocolId = String(record.protocol_id || '');
                templateChooserMode = '';
                currentProtocol = null;
                protocolDetailLoading = true;
                _writeState({ push: true });
                render();
                void loadProtocolDetail();
            },
            createAction: {
                label: 'New protocol',
                onClick: () => void _createBlankDraft(),
            },
            secondaryAction: protocolTemplates.length
                ? {
                    label: Kit.dict.label('protocol.catalog.template'),
                    onClick: _openTemplateChooser,
                }
                : null,
            compactGeneratedFamilies: true,
        });
        const controls = catalog.querySelector('.kit-catalog-controls');
        if (controls) {
            const autoBtn = document.createElement('button');
            autoBtn.type = 'button';
            autoBtn.className = 'btn';
            autoBtn.textContent = 'Auto protocol';
            autoBtn.addEventListener('click', () => _openAutoProtocolDialog({ mode: 'create', ignoreRememberedSession: true }));
            controls.appendChild(autoBtn);
            const toggle = document.createElement('a');
            UI.updateQueryToggleLink(toggle, includeGeneratedCatalog, {
                label: 'Generated drafts',
                activeState: 'shown',
                inactiveState: 'hidden',
                showLabel: 'Show generated drafts',
                hideLabel: 'Hide generated drafts',
            });
            controls.appendChild(toggle);
        }
        wrapper.appendChild(catalog);
        return wrapper;
    }

    function render() {
        if (renderInFlight) {
            renderQueued = true;
            return;
        }
        renderInFlight = true;
        try {
        _captureCollapsibleSectionState();
        if (designSessionsRoute) {
            header.hidden = false;
            _writeState();
            UI.reconcileChildren(contentEl, [_autoProtocolDesignSessionsRouteEl()]);
            _lifecycleHeaderRef = null;
            return;
        }
        if (!currentProtocolId) {
            header.hidden = false;
            _writeState();
            UI.reconcileChildren(contentEl, [_catalogEl()]);
            _bindTemplateChooserControls(contentEl);
            _lifecycleHeaderRef = null;
            return;
        }

        if (protocolDetailLoading) {
            header.hidden = true;
            _writeState();
            UI.reconcileChildren(contentEl, [UI.renderEmptyState('Loading protocol detail…', true)]);
            _lifecycleHeaderRef = null;
            return;
        }

        header.hidden = true;
        _writeState();
        const headerEl = _lifecycleHeaderEl();
        headerEl.dataset.key = 'protocol-lifecycle-header';
        const workflow = _workflowData();

        const workspace = document.createElement('div');
        workspace.className = 'kit-authoring-workspace';
        workspace.dataset.key = 'protocol-authoring-workspace';
        workspace.dataset.selection = String(selection.sectionKey || 'overview');
        workspace.dataset.editorMode = String(editorMode.kind || 'idle');
        workspace.dataset.mapVisible = _workflowMapVisible() ? 'true' : 'false';
        workspace.appendChild(_progressiveWorkflowEl(workflow));

        const previousCanvasRoot = contentEl.__workflowCanvasRoot || null;
        UI.reconcileChildren(contentEl, [headerEl, workspace]);
        if (editorMode.kind === 'insert-stage') {
            const activeInsertEditor = contentEl.querySelector('.kit-stage-editor[data-key^="protocol-inline-insert:"]');
            if (activeInsertEditor instanceof Element) {
                _bindPendingStageEditorControls(activeInsertEditor);
            }
        }
        _bindStageWorkspacePanelControls(contentEl);
        const activeCanvasRoot = contentEl.querySelector('.kit-workflow-canvas');
        if (activeCanvasRoot && typeof activeCanvasRoot.__workflowCanvasSync === 'function') {
            activeCanvasRoot.__workflowCanvasSync({
                scene: workflow.scene,
                selection: _surfaceSelection(),
                viewportState: { zoom: _canvasZoomValue() },
                mapVisible: true,
            });
        }
        if (previousCanvasRoot && previousCanvasRoot !== activeCanvasRoot && typeof previousCanvasRoot.__workflowCanvasCleanup === 'function') {
            previousCanvasRoot.__workflowCanvasCleanup();
        }
        contentEl.__workflowCanvasRoot = activeCanvasRoot || null;
        _lifecycleHeaderRef = contentEl.querySelector('.kit-lifecycle-header');
        _applyPendingStageViewportAnchor();
        } finally {
            renderInFlight = false;
            if (renderQueued) {
                renderQueued = false;
                queueMicrotask(() => render());
            }
        }
    }

    async function loadProtocols({ quiet = false } = {}) {
        const next = await API.listProtocols({ limit: 200 });
        protocols = next;
        if (currentProtocolId && !protocols.some((item) => item.protocol_id === currentProtocolId)) {
            currentProtocolId = '';
            currentProtocol = null;
        }
        _writeState();
        if (!quiet) render();
    }

    async function loadAutoProtocolSessions({ quiet = false } = {}) {
        autoProtocolSessionsLoading = true;
        if (!quiet) render();
        try {
            const payload = await API.listProtocolAutoSessions({
                limit: designSessionsRoute ? 24 : 12,
                status: designSessionsRoute ? autoProtocolStatusFilter : '',
                cursor: designSessionsRoute ? autoProtocolCursor : 0,
            });
            autoProtocolSessions = Array.isArray(payload?.items) ? payload.items : [];
            const rawNextCursor = payload?.next_cursor;
            const parsedNextCursor = Number(rawNextCursor);
            autoProtocolSessionsNextCursor = rawNextCursor === null || rawNextCursor === undefined || rawNextCursor === '' || !Number.isFinite(parsedNextCursor)
                ? null
                : parsedNextCursor;
            if (designSessionsRoute && selectedAutoProtocolSessionId && !selectedAutoProtocolSession) {
                const listed = autoProtocolSessions.find((item) => String(item?.session_id || '') === selectedAutoProtocolSessionId);
                if (listed) selectedAutoProtocolSession = listed;
            }
        } catch (err) {
            autoProtocolSessions = [];
            autoProtocolSessionsNextCursor = null;
            if (!quiet) UI.reportError('Failed to load Auto Protocol designs', err);
        } finally {
            autoProtocolSessionsLoading = false;
        }
        if (!quiet) render();
    }

    function _subscribeSelectedAutoProtocolSession() {
        if (selectedAutoProtocolSubscription) {
            selectedAutoProtocolSubscription();
            selectedAutoProtocolSubscription = null;
        }
        const sessionId = String(selectedAutoProtocolSessionId || '').trim();
        if (!designSessionsRoute || !sessionId) return;
        selectedAutoProtocolSubscription = _subscribeAutoProtocolSession(sessionId, async (updated) => {
            if (String(sessionId || '') !== String(selectedAutoProtocolSessionId || '')) return;
            if (String(updated?.session_id || '') !== String(selectedAutoProtocolSessionId || '')) return;
            selectedAutoProtocolSession = updated;
            await loadAutoProtocolSessions({ quiet: true });
            try {
                const events = await API.listProtocolAutoSessionEvents(sessionId);
                selectedAutoProtocolEvents = Array.isArray(events?.items) ? events.items : [];
            } catch (err) {
                console.warn('Failed to refresh Auto Protocol session events', err);
            }
            render();
        });
    }

    async function loadSelectedAutoProtocolSession({ quiet = false } = {}) {
        const sessionId = String(selectedAutoProtocolSessionId || '').trim();
        if (selectedAutoProtocolSubscription) {
            selectedAutoProtocolSubscription();
            selectedAutoProtocolSubscription = null;
        }
        if (!sessionId) {
            selectedAutoProtocolSession = null;
            selectedAutoProtocolEvents = [];
            return;
        }
        autoProtocolDetailLoading = true;
        if (String(selectedAutoProtocolSession?.session_id || '') !== sessionId) {
            selectedAutoProtocolSession = null;
            selectedAutoProtocolEvents = [];
        }
        if (!quiet) render();
        try {
            const [session, events] = await Promise.all([
                API.getProtocolAutoSession(sessionId),
                API.listProtocolAutoSessionEvents(sessionId),
            ]);
            selectedAutoProtocolSession = session;
            selectedAutoProtocolEvents = Array.isArray(events?.items) ? events.items : [];
            _rememberActiveAutoProtocolSession(session);
            _subscribeSelectedAutoProtocolSession();
        } catch (err) {
            selectedAutoProtocolSession = null;
            selectedAutoProtocolEvents = [];
            if (!quiet) UI.reportError('Failed to load Auto Protocol design session', err);
        } finally {
            autoProtocolDetailLoading = false;
        }
        if (!quiet) render();
    }

    async function _runAutoProtocolQueueAction(action) {
        const sessionId = String(selectedAutoProtocolSessionId || selectedAutoProtocolSession?.session_id || '').trim();
        if (!sessionId) return;
        const actionKey = `${sessionId}:${String(action || '').trim()}`;
        if (autoProtocolQueueActionInFlight) return;
        autoProtocolQueueActionInFlight = actionKey;
        autoProtocolQueueActionError = null;
        autoProtocolQueueRetryAction = '';
        render();
        try {
            const latest = await API.getProtocolAutoSession(sessionId);
            selectedAutoProtocolSession = latest;
            if (_autoProtocolPlanning(latest)) {
                autoProtocolQueueActionError = {
                    status: 409,
                    errorCode: 'PROTOCOL_AUTO_PLANNING',
                    message: 'Auto Protocol is still designing this session. Wait for planning to finish before applying, publishing, or running.',
                };
                autoProtocolQueueRetryAction = '';
                render();
                return;
            }
            if (action === 'apply') {
                selectedAutoProtocolSession = await API.applyProtocolAutoSession(sessionId);
            } else if (action === 'publish') {
                selectedAutoProtocolSession = await API.publishProtocolAutoSession(sessionId);
            } else if (action === 'run') {
                selectedAutoProtocolSession = await API.runProtocolAutoSession(sessionId, {
                    origin_channel: 'registry',
                    idempotency_key: _autoProtocolRunAttemptKey(sessionId),
                });
            }
            await loadAutoProtocolSessions({ quiet: true });
            await loadSelectedAutoProtocolSession({ quiet: true });
            if (action === 'apply' || action === 'publish') {
                const protocolId = _autoProtocolTargetProtocolId(selectedAutoProtocolSession);
                if (protocolId) {
                    Router.navigate(`/ui/protocols?protocol_id=${encodeURIComponent(protocolId)}`);
                    return;
                }
            }
            if (action === 'run') {
                const runId = _autoProtocolRunId(selectedAutoProtocolSession);
                if (runId) {
                    Router.navigate(`/ui/runs?run_id=${encodeURIComponent(runId)}`);
                    return;
                }
            }
            render();
        } catch (err) {
            autoProtocolQueueActionError = err;
            const status = Number(err?.status || 0);
            const code = String(err?.errorCode || '').trim().toUpperCase();
            autoProtocolQueueRetryAction = (!status || status === 408 || status === 429 || status >= 500 || (status === 409 && code === 'CONCURRENT_MODIFICATION'))
                ? action
                : '';
            render();
        } finally {
            autoProtocolQueueActionInFlight = '';
            render();
        }
    }

    async function loadAuthoringOptions() {
        const [options, templates] = await Promise.all([
            API.getProtocolAuthoringOptions(),
            API.listProtocolTemplates(),
        ]);
        authoringOptions = options;
        protocolTemplates = Array.isArray(templates) ? templates : [];
    }

    async function loadAssignmentCatalog({ quiet = true } = {}) {
        try {
            const [agentData, skillData] = await Promise.all([
                API.listAgents({ limit: 100 }),
                API.listRoutingSkills(),
            ]);
            availableAgents = Array.isArray(agentData?.agents) ? agentData.agents : (Array.isArray(agentData) ? agentData : []);
            connectedAgents = availableAgents.filter((agent) =>
                String(agent?.connectivity_state || '').trim().toLowerCase() === 'connected',
            );
            availableRoutingSkills = (Array.isArray(skillData?.routing_skills) ? skillData.routing_skills : (Array.isArray(skillData) ? skillData : []))
                .filter((item) => _isAuthoringRoutingSkill(item));
            const catalogAgents = _authoringAssignableAgents()
                .filter((agent) => _supportsSkillCatalog(agent))
                .map((agent) => String(agent?.agent_id || '').trim())
                .filter(Boolean);
            const catalogByName = new Map();
            const catalogResponses = await Promise.allSettled(catalogAgents.map((agentId) => API.listSkills(agentId)));
            catalogResponses.forEach((result) => {
                if (result.status !== 'fulfilled') return;
                const payload = result.value;
                const items = Array.isArray(payload?.skills) ? payload.skills : (Array.isArray(payload) ? payload : []);
                items.forEach((item) => {
                    const skillName = String(item?.name || '').trim();
                    if (!skillName) return;
                    const existing = catalogByName.get(skillName);
                    if (!existing) {
                        catalogByName.set(skillName, item);
                        return;
                    }
                    const existingPrecedence = _skillSourcePrecedence(existing?.source_kind);
                    const nextPrecedence = _skillSourcePrecedence(item?.source_kind);
                    catalogByName.set(skillName, {
                        ...existing,
                        ...item,
                        source_kind: nextPrecedence >= existingPrecedence
                            ? String(item?.source_kind || existing?.source_kind || '')
                            : String(existing?.source_kind || item?.source_kind || ''),
                        source_label: nextPrecedence >= existingPrecedence
                            ? String(item?.source_label || existing?.source_label || '')
                            : String(existing?.source_label || item?.source_label || ''),
                        display_name: String(item?.display_name || existing?.display_name || skillName),
                        description: String(item?.description || existing?.description || ''),
                        runtime_available: Boolean(existing?.runtime_available || item?.runtime_available),
                        has_unpublished_changes: Boolean(existing?.has_unpublished_changes || item?.has_unpublished_changes),
                    });
                });
            });
            availableCatalogSkills = Array.from(catalogByName.values());
            if (currentProtocol && !protocolDetailLoading) {
                render();
            } else if (!currentProtocolId && Array.isArray(autoProtocolSessions) && autoProtocolSessions.length) {
                render();
            }
        } catch (err) {
            availableAgents = [];
            connectedAgents = [];
            availableRoutingSkills = [];
            availableCatalogSkills = [];
            if (!quiet) {
                UI.reportError('Failed to load assignment options', err);
            }
        }
    }

    async function loadProtocolDetail() {
        if (!currentProtocolId) {
            currentProtocol = null;
            protocolDetailLoading = false;
            _writeState();
            render();
            return;
        }
        protocolDetailLoading = true;
        render();
        currentProtocol = await API.getProtocol(currentProtocolId);
        _applyServerDetail(currentProtocol);
        protocolDetailLoading = false;
        _writeState();
        render();
    }

    async function bootstrap() {
        UI.reconcileChildren(contentEl, [UI.renderEmptyState('Loading protocols…', true)]);
        try {
            await Promise.all([
                loadProtocols({ quiet: true }),
                loadAutoProtocolSessions({ quiet: true }),
                loadAuthoringOptions(),
            ]);
            if (designSessionsRoute && selectedAutoProtocolSessionId) {
                await loadSelectedAutoProtocolSession({ quiet: true });
            }
            if (currentProtocolId) {
                await loadProtocolDetail();
            } else {
                render();
            }
            void loadAssignmentCatalog({ quiet: true });
        } catch (err) {
            UI.reconcileChildren(contentEl, [UI.createErrorCard('Failed to load protocols: ' + err.message, bootstrap)]);
        }
    }

    cleanups.add(() => {
        if (selectedAutoProtocolSubscription) {
            selectedAutoProtocolSubscription();
            selectedAutoProtocolSubscription = null;
        }
        _clearAutosaveTimer();
        if (contentEl.__workflowCanvasRoot?.__workflowCanvasCleanup) {
            contentEl.__workflowCanvasRoot.__workflowCanvasCleanup();
        }
        currentProtocol = null;
        _lifecycleHeaderRef = null;
    });
    const onResize = () => render();
    window.addEventListener('resize', onResize);
    cleanups.add(() => window.removeEventListener('resize', onResize));

    UI.subscribeWithRefresh(cleanups, 'protocols', async () => {
        await Promise.all([
            loadProtocols({ quiet: true }),
            loadAutoProtocolSessions({ quiet: true }),
        ]);
        render();
    }, 350);
    container.__routeReady = bootstrap();
}

function renderProtocolRuns(container) {
    const cleanups = UI.beginCleanupScope();
    const contentInner = container.closest('.content-inner');
    if (contentInner) {
        contentInner.classList.add('workspace-route-wide');
        contentInner.classList.add('protocol-runs-route-shell');
        cleanups.add(() => contentInner.classList.remove('workspace-route-wide'));
        cleanups.add(() => contentInner.classList.remove('protocol-runs-route-shell'));
    }

    const limit = UI.DEFAULT_PAGE_LIMIT;
    const initialCursor = Math.max(0, Number.parseInt(UI.readQueryParam('cursor', '0'), 10) || 0);
    const initialCursorStack = [];
    for (let value = 0; value < initialCursor; value += limit) {
        initialCursorStack.push(value);
    }
    let runs = [];
    let runsListData = null;
    let protocolIssues = [];
    let currentRunId = UI.readQueryParam('run_id', '');
    let currentRun = null;
    let currentIssues = [];
    let lastRunEvent = null;
    let runDetailLoading = false;
    let runSearch = '';
    let runStatusFilter = UI.readQueryParam('status', '');
    let runViewFilter = _protocolRunViewFilterValue(UI.readQueryParam('view', 'recent'));
    let issueKindFilter = _protocolIssueFilterValue(UI.readQueryParam('issue_kind', ''));
    let includeGenerated = UI.readQueryParam('include_generated', '') === '1';
    let activeRunDetailSection = '';
    let activeRunStageExecutionId = '';
    let activeRunStageFollowsCurrent = true;
    let activeRunArtifactStageExecutionId = '';
    const runDisclosureState = new Map();
    let currentRunSubscription = null;
    let runDetailRequestToken = 0;
    let runPaginator = null;
    let runRefreshTimer = 0;
    let runsRouteDisposed = false;

    function _resetRunStageEvidenceSelection() {
        activeRunStageExecutionId = '';
        activeRunStageFollowsCurrent = true;
    }

    const runPaginationEl = document.createElement('div');
    runPaginationEl.className = 'pagination-shell';

    const header = document.createElement('header');
    header.className = 'page-header page-header-compact';
    header.innerHTML = '<h2>Runs</h2><p>Watch workflow progress, find runs that need attention, and open produced artifacts.</p>';
    container.appendChild(header);

    const shell = document.createElement('section');
    shell.className = 'admin-shell protocol-route-shell';
    container.appendChild(shell);

    const contentEl = document.createElement('div');
    contentEl.className = 'protocol-surface-shell';
    shell.appendChild(contentEl);

    function _writeState({ push = false } = {}) {
        UI.updateQueryParams({
            protocol_id: '',
            run_id: currentRunId || '',
            status: runStatusFilter || '',
            view: runViewFilter !== 'recent' ? runViewFilter : '',
            issue_kind: issueKindFilter || '',
            include_generated: includeGenerated ? '1' : '',
            entry_agent_id: '',
            cursor: runPaginator && Number(runPaginator.cursor) > 0 ? runPaginator.cursor : '',
        }, { replace: !push });
    }

    runPaginator = UI.createCursorPaginator(runPaginationEl, () => loadRuns(), {
        initialCursor,
        initialStack: initialCursorStack,
        onChange: () => {
            currentRunId = '';
            currentRun = null;
            currentIssues = [];
            lastRunEvent = null;
            activeRunDetailSection = '';
            _resetRunStageEvidenceSelection();
            activeRunArtifactStageExecutionId = '';
            runDetailLoading = false;
            runDetailRequestToken += 1;
            _bindRunSubscription();
            _syncRunRefreshTimer();
            _writeState();
        },
    });

    function _bindRunSubscription() {
        if (currentRunSubscription) {
            currentRunSubscription();
            currentRunSubscription = null;
        }
        if (!currentRunId || typeof WS === 'undefined' || !WS || typeof WS.subscribe !== 'function') {
            return;
        }
        currentRunSubscription = WS.subscribe(`protocol-run:${currentRunId}`, (msg) => {
            if (msg && msg.type === 'event' && msg.data && msg.data.event_kind) {
                lastRunEvent = msg.data;
            }
            void Promise.all([
                loadRunDetail({ soft: true }),
                loadRuns(),
                loadIssues({ rerender: true }),
            ]);
        });
    }

    function _currentRunIsActive() {
        const status = String(currentRun?.run?.status || '').trim().toLowerCase();
        return Boolean(currentRunId) && !['completed', 'failed', 'cancelled', 'archived', 'deleted'].includes(status);
    }

    function _syncRunRefreshTimer() {
        clearTimeout(runRefreshTimer);
        runRefreshTimer = 0;
        if (runsRouteDisposed || !_currentRunIsActive() || UI.isBackgrounded()) return;
        runRefreshTimer = setTimeout(() => {
            void Promise.all([
                loadRunDetail({ soft: true }),
                loadRuns(),
                loadIssues({ rerender: true }),
            ]).finally(_syncRunRefreshTimer);
        }, 2500);
    }

    function _setRunSelection(nextRunId, { push = true } = {}) {
        const normalizedRunId = String(nextRunId || '');
        if (normalizedRunId && normalizedRunId === String(currentRunId || '')) {
            if (!currentRun && !runDetailLoading) {
                runDetailLoading = true;
                renderRunsRoute();
                void loadRunDetail();
            }
            return;
        }
        currentRun = null;
        currentIssues = [];
        lastRunEvent = null;
        activeRunDetailSection = '';
        _resetRunStageEvidenceSelection();
        activeRunArtifactStageExecutionId = '';
        if (normalizedRunId && normalizedRunId !== String(currentRunId || '')) {
            currentRunId = normalizedRunId;
            runDetailLoading = true;
            _writeState({ push });
            renderRunsRoute();
            _syncRunRefreshTimer();
            void loadRunDetail();
            return;
        }
        runDetailRequestToken += 1;
        currentRunId = '';
        runDetailLoading = false;
        _writeState({ push });
        _bindRunSubscription();
        _syncRunRefreshTimer();
        renderRunsRoute();
    }

    function _runRecordId(item) {
        return String(item?.protocol_run_id || item?.id || item?.run_id || '').trim();
    }

    function _selectedRunListRecord() {
        const selectedId = String(currentRunId || '');
        if (!selectedId) return null;
        return (runs || []).find((item) => _runRecordId(item) === selectedId) || null;
    }

    function _runListRecordChangedSinceDetail(listRecord) {
        const detail = currentRun?.run || null;
        if (!listRecord || !detail) return false;
        const changedFields = [
            'status',
            'current_stage_execution_id',
            'current_stage_key',
            'updated_at',
            'completed_at',
        ];
        if (changedFields.some((field) => String(listRecord[field] || '') !== String(detail[field] || ''))) {
            return true;
        }
        const listVersion = Number(listRecord.version || 0);
        const detailVersion = Number(detail.version || 0);
        return Number.isFinite(listVersion)
            && Number.isFinite(detailVersion)
            && listVersion > 0
            && detailVersion > 0
            && listVersion !== detailVersion;
    }

    function _queueSelectedRunDetailRefreshFromList() {
        if (!currentRunId || runDetailLoading) return false;
        const selectedListRecord = _selectedRunListRecord();
        if (!_runListRecordChangedSinceDetail(selectedListRecord)) return false;
        runDetailLoading = true;
        void loadRunDetail({ soft: true });
        return true;
    }

    function _filteredIssues() {
        return UI.defaultVisibleRecords(protocolIssues || [], { includeHidden: includeGenerated }).filter((item) => {
            const haystack = [
                item.protocol_display_name || '',
                item.protocol_id || '',
                item.issue_detail || '',
                item.issue_code || '',
                item.issue_kind || '',
                item.stage_key || '',
                item.protocol_run_id || '',
            ].join(' ').toLowerCase();
            return !runSearch || haystack.includes(runSearch.toLowerCase());
        });
    }

    function _protocolIssueLabel(kind) {
        const value = String(kind || '').trim();
        if (value === 'stuck_lease') return 'Expired write lease';
        return value.replace(/_/g, ' ');
    }

    function _issueFactParts(issue = {}) {
        const parts = [];
        const runState = String(issue.run_status || '').trim();
        const stageState = String(issue.stage_status || '').trim();
        if (runState || stageState) {
            parts.push(`state ${[runState, stageState].filter(Boolean).join(' / ')}`);
        }
        if (issue.lease_expires_at) {
            parts.push(`lease expires ${UI.relativeTime(issue.lease_expires_at) || issue.lease_expires_at}`);
        }
        if (issue.timeout_at) {
            parts.push(`timeout ${UI.relativeTime(issue.timeout_at) || issue.timeout_at}`);
        }
        if (issue.task_updated_at) {
            parts.push(`task updated ${UI.relativeTime(issue.task_updated_at) || issue.task_updated_at}`);
        } else if (issue.updated_at) {
            parts.push(`updated ${UI.relativeTime(issue.updated_at) || issue.updated_at}`);
        }
        return parts;
    }

    function _issueAttentionLabel(issue) {
        const kind = _protocolIssueLabel(issue?.issue_kind || '');
        const code = String(issue?.issue_code || '').trim().replace(/_/g, ' ');
        return (kind || code || 'Issue').replace(/\b\w/g, (char) => char.toUpperCase());
    }

    function _issueRows() {
        return _filteredIssues().map((item) => {
            const selected = String(item.protocol_run_id || '') === String(currentRunId || '');
            const shell = document.createElement('article');
            shell.className = 'kit-runs-list-entry';
            if (selected) {
                shell.classList.add('is-selected');
            }
            shell.dataset.runId = String(item.protocol_run_id || '');
            const row = UI.renderListRow({
                label: `${_protocolIssueLabel(item.issue_kind)} · ${item.protocol_display_name || item.protocol_id || 'Protocol issue'}`,
                sublabel: [
                    item.stage_key ? `stage ${item.stage_key}` : '',
                    item.issue_detail || item.issue_code || '',
                    ..._issueFactParts(item),
                ].filter(Boolean).join(' · '),
                badgeText: item.issue_code || item.stage_key || '',
                className: selected ? 'is-selected' : '',
                onClick: () => _setRunSelection(item.protocol_run_id),
            });
            row.setAttribute('aria-expanded', String(selected));
            shell.appendChild(row);
            return shell;
        });
    }

    function _runDisclosureKey(name) {
        return `${String(currentRunId || 'run')}:${String(name || 'section')}`;
    }

    function _bindRunDisclosure(details, name, { open = false } = {}) {
        if (!(details instanceof HTMLDetailsElement)) return details;
        const key = _runDisclosureKey(name);
        details.dataset.disclosureKey = key;
        details.open = runDisclosureState.has(key) ? Boolean(runDisclosureState.get(key)) : Boolean(open);
        details.addEventListener('toggle', () => {
            runDisclosureState.set(key, Boolean(details.open));
        });
        return details;
    }

    function _latestBlockedTransition(detail = currentRun) {
        const transitions = Array.isArray(detail?.transitions) ? detail.transitions : [];
        const stageId = String(detail?.run?.current_stage_execution_id || '').trim();
        return transitions.find((item) => {
            const kind = String(item?.transition_kind || '').trim().toLowerCase();
            const fromStage = String(item?.from_stage_execution_id || '').trim();
            const toStage = String(item?.to_stage_execution_id || '').trim();
            const stageMatches = !stageId || !fromStage || fromStage === stageId || toStage === stageId;
            return stageMatches && kind === 'blocked';
        }) || null;
    }

    function _missingEvidenceList(detail = currentRun) {
        const metadata = _latestBlockedTransition(detail)?.metadata_json || {};
        const missing = Array.isArray(metadata?.missing_runtime_evidence) ? metadata.missing_runtime_evidence : [];
        return missing.map((item) => String(item || '').trim()).filter(Boolean);
    }

    function _renderRunActionBlockedResult(mutation, detail = currentRun) {
        const run = detail?.run || mutation?.run || currentRun?.run || {};
        const stage = mutation?.stage_execution || detail?.stage_executions?.[0] || null;
        const transition = _latestBlockedTransition(detail);
        const panel = document.createElement('div');
        panel.className = 'error-card protocol-run-action-result';
        panel.setAttribute('role', 'alert');

        const title = document.createElement('strong');
        title.textContent = 'Run is still blocked';
        panel.appendChild(title);

        const detailText = String(
            run.blocked_detail
            || stage?.failure_detail
            || transition?.reason
            || mutation?.message
            || 'The Registry kept this run blocked after applying the operator action.',
        ).trim();
        const copy = document.createElement('p');
        copy.textContent = detailText;
        panel.appendChild(copy);

        const code = String(run.blocked_code || stage?.failure_code || transition?.error_code || '').trim();
        const missing = _missingEvidenceList(detail);
        if (code || missing.length) {
            const facts = document.createElement('div');
            facts.className = 'validation-list';
            if (code) {
                const row = document.createElement('div');
                row.textContent = `Code: ${code}`;
                facts.appendChild(row);
            }
            missing.forEach((value) => {
                const row = document.createElement('div');
                row.textContent = `Missing: ${value}`;
                facts.appendChild(row);
            });
            panel.appendChild(facts);
        }

        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = 'This result remains open so you can read and copy it. Close the dialog when you are done.';
        panel.appendChild(note);
        return panel;
    }

    function _runStatusValue(run) {
        return String(run?.status || '').trim().toLowerCase() || 'queued';
    }

    function _runGroupInfo(run, issue = null) {
        const status = _runStatusValue(run);
        if (issue || status === 'blocked' || status === 'failed') {
            return { key: 'attention', label: 'Needs attention', rank: 0 };
        }
        if (['running', 'queued'].includes(status)) {
            return { key: 'active', label: 'Running now', rank: 1 };
        }
        if (status === 'completed') {
            return { key: 'completed', label: 'Recently completed', rank: 2 };
        }
        if (status === 'cancelled') {
            return { key: 'ended', label: 'Ended', rank: 3 };
        }
        if (status === 'archived') {
            return { key: 'archived', label: 'Archived', rank: 4 };
        }
        if (status === 'deleted') {
            return { key: 'deleted', label: 'Deleted', rank: 5 };
        }
        return { key: 'other', label: 'Other runs', rank: 6 };
    }

    function _runHasOutcome(run) {
        if (!run) return false;
        if (String(run.primary_artifact_key || run.primary_outcome_key || '').trim()) return true;
        if (Number(run.artifact_count || run.output_count || 0) > 0) return true;
        const stage = String(run.current_stage_key || '').toLowerCase();
        const status = _runStatusValue(run);
        return status === 'completed' && /(artifact|outcome|release|implement|package|deliver)/.test(stage);
    }

    function _runMatchesViewFilter(run, issue = null) {
        const status = _runStatusValue(run);
        switch (runViewFilter) {
            case 'attention':
                return Boolean(issue) || ['blocked', 'failed'].includes(status);
            case 'running':
                return ['running', 'queued'].includes(status);
            case 'completed':
                return status === 'completed';
            case 'outcomes':
                return _runHasOutcome(run);
            case 'archived':
                return status === 'archived';
            case 'deleted':
                return status === 'deleted';
            case 'telegram':
                return String(run?.origin_channel || '').trim().toLowerCase() === 'telegram';
            case 'registry':
                return String(run?.origin_channel || '').trim().toLowerCase() === 'registry';
            case 'recent':
            default:
                return true;
        }
    }

    function _compactRunText(value, maxLength = 76) {
        const text = String(value || '').replace(/\s+/g, ' ').trim();
        if (!text || text.length <= maxLength) return text;
        return `${text.slice(0, Math.max(0, maxLength - 1)).trim()}…`;
    }

    function _stripRunImprovementBoilerplate(value, maxLength = 1200) {
        const contextLabels = /^(run id|protocol id|protocol name|run status|run objective|current stage|primary artifact|primary artifact expected path|existing artifacts)\s*:/i;
        const revisionLabel = /^(user improvement request|requested improvement|revision request)\s*:\s*(.*)$/i;
        const noise = /^(improve the existing protocol that produced this run|use the prior run as context|bring the revised protocol up to the current octopus standard)/i;
        const parts = String(value || '')
            .replace(/\r/g, '\n')
            .split('\n')
            .map((line) => {
                const cleaned = line.replace(/^\s*[-*]\s*/, '').trim();
                const revisionMatch = cleaned.match(revisionLabel);
                return revisionMatch ? revisionMatch[2].trim() : cleaned;
            })
            .filter((line) => line && !contextLabels.test(line) && !noise.test(line));
        const seen = new Set();
        const compact = [];
        parts.forEach((part) => {
            const key = part.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
            if (!key || seen.has(key)) return;
            seen.add(key);
            compact.push(part);
        });
        const text = compact.join(' ').replace(/\s+/g, ' ').trim();
        if (text.length <= maxLength) return text;
        return text.slice(0, maxLength).replace(/\s+\S*$/, '').trim();
    }

    function _runLaunchContextEntries(run) {
        const labels = {
            context: 'Additional context',
            constraints: 'Constraints',
            source_context: 'Files or data context',
            relationship_context: 'Keys and relationships',
            privacy_constraints: 'Privacy or execution constraints',
            acceptance_criteria: 'Acceptance criteria',
        };
        const entries = [];
        const objective = String(run?.problem_statement || '').trim();
        if (objective) {
            entries.push({ label: 'Run objective', value: objective });
        }
        const context = run?.constraints_json && typeof run.constraints_json === 'object'
            ? run.constraints_json
            : {};
        Object.entries(context).forEach(([key, value]) => {
            if (value === null || value === undefined || value === '') return;
            if (Array.isArray(value) && !value.length) return;
            if (typeof value === 'object' && !Array.isArray(value) && !Object.keys(value).length) return;
            const text = typeof value === 'string'
                ? value.trim()
                : JSON.stringify(value, null, 2);
            if (!text) return;
            entries.push({
                label: labels[key] || String(key || '').replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase()),
                value: text,
            });
        });
        return entries;
    }

    function _runLaunchContextList(run) {
        const list = document.createElement('div');
        list.className = 'run-launch-context-list';
        const entries = _runLaunchContextEntries(run);
        if (!entries.length) {
            list.appendChild(UI.renderEmptyState('No launch context was submitted for this run.', true));
            return list;
        }
        entries.forEach((entry) => {
            const value = document.createElement('span');
            value.className = 'run-launch-context-value';
            value.textContent = entry.value;
            list.appendChild(UI.renderListRow({
                label: entry.label,
                sublabelNode: value,
            }));
        });
        return list;
    }

    function _primaryRunArtifactInfo(runDetail) {
        const detail = runDetail || {};
        const artifacts = Array.isArray(detail.artifacts) ? detail.artifacts : [];
        const metadata = detail.version?.definition_json?.metadata || {};
        const autoMeta = metadata.auto_protocol || {};
        const explicitPrimary = autoMeta.primary_artifact || {};
        const explicitKey = String(explicitPrimary.artifact_key || autoMeta.primary_artifact_key || '').trim();
        const byKey = new Map(artifacts.map((item) => [String(item?.artifact_key || '').trim(), item]));
        if (explicitKey) {
            return {
                ...(byKey.get(explicitKey) || {}),
                ...explicitPrimary,
                artifact_key: explicitKey,
                expected_path: explicitPrimary.expected_path || '',
            };
        }
        const evidenceLike = /(^|[_-])(review|audit|evidence|logs?)([_-]|$)/i;
        return [...artifacts]
            .filter((item) => String(item?.artifact_key || '').trim())
            .sort((left, right) => {
                const leftKey = String(left.artifact_key || '');
                const rightKey = String(right.artifact_key || '');
                const leftScore = (left.exists ? 20 : 0)
                    + (!evidenceLike.test(leftKey) ? 10 : 0)
                    + (UI.isLikelyDirectoryArtifactPath(_protocolArtifactDisplayPath(left)) ? 8 : 0);
                const rightScore = (right.exists ? 20 : 0)
                    + (!evidenceLike.test(rightKey) ? 10 : 0)
                    + (UI.isLikelyDirectoryArtifactPath(_protocolArtifactDisplayPath(right)) ? 8 : 0);
                return rightScore - leftScore;
            })[0] || null;
    }

    function _runImprovementRequirement(runDetail, changeRequest) {
        return _stripRunImprovementBoilerplate(changeRequest, 1400) || 'Improve this protocol from the selected run.';
    }

    function _runImprovementContext(runDetail) {
        const detail = runDetail || {};
        const run = detail.run || {};
        const version = detail.version || {};
        const definition = version.definition_json || {};
        const artifacts = (detail.artifacts || [])
            .filter((item) => item && (item.exists || item.artifact_key || item.workspace_path || item.location))
            .slice(0, 6)
            .map((item) => [
                String(item.artifact_key || 'artifact').trim(),
                String(item.workspace_path || item.location || '').trim(),
                String(item.verification_state || item.state || '').trim(),
            ].filter(Boolean).join(' | '));
        const primary = _primaryRunArtifactInfo(detail);
        const runObjective = _stripRunImprovementBoilerplate(run.problem_statement || '', 520);
        return [
            'Prior run context for this protocol improvement. Use this as evidence and orientation, not as text to copy into the new run objective.',
            `Run id: ${run.protocol_run_id || ''}`,
            `Protocol id: ${run.protocol_id || ''}`,
            `Protocol name: ${run.protocol_display_name || definition.display_name || definition.name || ''}`,
            `Run status: ${run.status || ''}`,
            runObjective ? `Prior run objective: ${runObjective}` : '',
            `Current stage: ${run.current_stage_key || ''}`,
            primary?.artifact_key ? `Primary artifact: ${primary.artifact_key}` : '',
            primary?.expected_path ? `Primary artifact expected path: ${primary.expected_path}` : '',
            artifacts.length ? `Existing artifacts:\n- ${artifacts.join('\n- ')}` : 'Existing artifacts: none recorded',
            '',
            'Quality bar for the improved protocol: primary artifact first, root octopus-runtime.json for runnable UI/API/backend artifacts, coherent user-facing APIs, routed browser UI, downloadable zip package, outcome-readiness matrix, customer-facing branding check, smoke/runtime evidence, adversarial review, and no unnecessary late review stages after the main artifact review.',
        ].filter((line) => line !== '').join('\n');
    }

    function _runAutoSessionReady(session) {
        const validation = session?.validation || {};
        const unresolved = Array.isArray(session?.unresolved_decisions) ? session.unresolved_decisions : [];
        return Boolean(session?.session_id && validation.ok && !unresolved.length);
    }

    function _runAutoSessionRunId(session) {
        return String(
            session?.run_result?.run?.protocol_run_id
            || session?.run_result?.protocol_run_id
            || session?.run?.protocol_run_id
            || '',
        ).trim();
    }

    function _runImproveSummaryEl(session) {
        const plan = session?.plan || {};
        const analysis = session?.analysis || {};
        const validation = session?.validation || {};
        const warnings = Array.isArray(session?.warnings) ? session.warnings : [];
        const unresolved = Array.isArray(session?.unresolved_decisions) ? session.unresolved_decisions : [];
        const stages = Array.isArray(plan.stages) ? plan.stages : [];
        const artifacts = Array.isArray(plan.artifacts) ? plan.artifacts : [];
        const primary = plan.primary_artifact || session?.draft_definition_json?.metadata?.auto_protocol?.primary_artifact || {};
        const panel = document.createElement('div');
        panel.className = 'protocol-auto-summary protocol-auto-review';
        const header = document.createElement('div');
        header.className = 'protocol-auto-review-header';
        const title = document.createElement('h4');
        title.textContent = String(plan.protocol_name || 'Improved protocol draft');
        header.appendChild(title);
        const summary = document.createElement('p');
        summary.textContent = String(analysis.goal || plan.description || 'Review the generated improvement before applying it.');
        header.appendChild(summary);
        const readiness = document.createElement('span');
        readiness.className = _runAutoSessionReady(session) ? 'protocol-auto-readiness is-ready' : 'protocol-auto-readiness';
        readiness.textContent = _runAutoSessionReady(session)
            ? 'Ready to apply, publish, or run'
            : 'Needs attention before publishing';
        header.appendChild(readiness);
        panel.appendChild(header);
        panel.appendChild(UI.renderMetadataGrid([
            { label: 'Stages', value: String(stages.length) },
            { label: 'Artifacts', value: String(artifacts.length) },
            { label: 'Validation', value: validation.ok ? 'Ready' : 'Needs attention' },
            { label: 'Primary outcome', value: primary.display_name || primary.artifact_key || 'Produced outcome' },
        ], { compact: true }));
        if (warnings.length || unresolved.length) {
            const list = document.createElement('div');
            list.className = 'task-artifact-list';
            [...unresolved, ...warnings].slice(0, 5).forEach((item) => {
                list.appendChild(UI.renderListRow({
                    label: item.message || item.code || 'Auto Protocol warning',
                    sublabel: item.action || item.detail || '',
                    badgeText: item.severity || item.code || '',
                }));
            });
            panel.appendChild(list);
        }
        return panel;
    }

    function _shortRunId(value) {
        return String(value || '').trim().slice(0, 8);
    }

    function _runDisplayTitle(run) {
        const named = String(run?.protocol_display_name || run?.protocol_name || '').trim();
        if (named) return named;
        const problem = _compactRunText(run?.problem_statement || '', 82);
        if (problem) return problem;
        const runId = _shortRunId(_runRecordId(run));
        return runId ? `Protocol run ${runId}` : 'Protocol run';
    }

    function _runStageListLabel(run) {
        const stage = String(run?.current_stage_key || '').trim();
        if (stage) return `Stage ${stage}`;
        const status = _runStatusValue(run);
        return status === 'completed' ? 'Finished' : 'No active stage';
    }

    function _buildRunsOverviewStrip(runSource, issuesByRunId) {
        const counts = {
            attention: 0,
            active: 0,
            completed: 0,
            ended: 0,
        };
        (runSource || []).forEach((run) => {
            const group = _runGroupInfo(run, issuesByRunId.get(String(_runRecordId(run) || '').trim()) || null);
            if (Object.prototype.hasOwnProperty.call(counts, group.key)) {
                counts[group.key] += 1;
            }
        });
        const strip = document.createElement('div');
        strip.className = 'runs-overview-strip';
        strip.setAttribute('role', 'list');
        strip.setAttribute('aria-label', 'Run status summary');
        [
            { key: 'attention', label: 'Needs attention' },
            { key: 'active', label: 'Running now' },
            { key: 'completed', label: 'Completed' },
            { key: 'ended', label: 'Ended' },
        ].forEach((item) => {
            const card = document.createElement('div');
            card.className = `runs-overview-card runs-overview-${item.key}`;
            card.setAttribute('role', 'listitem');
            const value = document.createElement('strong');
            value.textContent = String(counts[item.key] || 0);
            card.appendChild(value);
            const copy = document.createElement('span');
            copy.textContent = item.label;
            card.appendChild(copy);
            strip.appendChild(card);
        });
        return strip;
    }

    function _buildRunSummaryGrid() {
        const run = currentRun.run;
        const maxRounds = Number(run.max_review_rounds || 0);
        return Kit.runSummary({
            run: {
                id: run.protocol_run_id,
                status: run.status,
                version: run.version || 1,
                current_stage_key: run.current_stage_key,
                review_loop: `${Number(run.current_review_rounds || 0)} / ${maxRounds || 'n/a'}`,
                workspace_ref: run.workspace_ref || 'default',
                root_conversation_id: run.root_conversation_id,
                notes: run.termination_summary || run.blocked_detail || '',
                stageProgress: _runStageProgressData(currentRun),
            },
            liveEventText: (lastRunEvent && String(lastRunEvent.protocol_run_id || '') === String(run.protocol_run_id || ''))
                ? `Live update: ${_protocolEventText(lastRunEvent)}`
                : '',
        });
    }

    function _runStageProgressData(runDetail = currentRun) {
        const detail = runDetail || {};
        const run = detail.run || detail || {};
        return {
            stages: detail.version?.definition_json?.stages || [],
            stageExecutions: detail.stage_executions || [],
            currentStageKey: String(run.current_stage_key || ''),
            runStatus: String(run.status || ''),
            issues: currentIssues || [],
        };
    }

    function _currentRunAllowedDecisions() {
        const currentStageKey = String(currentRun?.run?.current_stage_key || '').trim();
        if (!currentStageKey) return new Set();
        const stage = (currentRun?.version?.definition_json?.stages || [])
            .find((item) => String(item?.stage_key || '') === currentStageKey) || null;
        return new Set(Object.keys(stage?.transitions || {})
            .map((decision) => String(decision || '').trim().toLowerCase())
            .filter(Boolean));
    }

    function _runActionSpecs() {
        const status = String(currentRun?.run.status || '');
        const active = !['completed', 'failed', 'cancelled', 'archived', 'deleted'].includes(status);
        const allowedDecisions = _currentRunAllowedDecisions();
        const currentStageExecutionId = String(currentRun?.run?.current_stage_execution_id || '').trim();
        const currentStageKey = String(currentRun?.run?.current_stage_key || '').trim();
        const stageRows = Array.isArray(currentRun?.stage_executions) ? currentRun.stage_executions : [];
        const currentStageExecution = stageRows.find((item) =>
            currentStageExecutionId && String(item?.protocol_stage_execution_id || '') === currentStageExecutionId,
        ) || [...stageRows].reverse().find((item) =>
            currentStageKey && String(item?.stage_key || '') === currentStageKey,
        ) || null;
        const currentStageStatus = String(currentStageExecution?.status || '').trim().toLowerCase();
        const currentFailureCode = String(currentStageExecution?.failure_code || currentRun?.run?.blocked_code || '').trim().toLowerCase();
        const interrupted = currentFailureCode === 'interrupted';
        const currentStageBusy = ['queued', 'submitted', 'leased', 'running'].includes(currentStageStatus);
        const interventionNote = currentStageBusy
            ? ' This is an operator intervention while the current stage may still be working.'
            : '';
        return [
            {
                action: 'retry',
                label: interrupted ? 'Retry interrupted stage' : 'Retry',
                note: interrupted
                    ? 'This stage was interrupted before the agent result was saved. Retry will continue from the same stage with the same protocol definition and workspace context.'
                    : 'Retry creates a new execution of the current stage using the same protocol definition and workspace context.',
                confirmLabel: interrupted ? 'Retry stage' : 'Retry run',
                successMessage: interrupted ? 'Interrupted stage retry submitted.' : 'Protocol run retry submitted.',
                requireReason: false,
                visible: ['blocked', 'failed', 'cancelled'].includes(status),
                enabled: ['blocked', 'failed', 'cancelled'].includes(status),
            },
            {
                action: 'accept',
                label: 'Accept',
                note: `Accept records an operator review decision for the current stage using the reason you provide as audit context.${interventionNote}`,
                confirmLabel: 'Accept run',
                successMessage: 'Protocol run accepted.',
                requireReason: false,
                visible: active && allowedDecisions.has('accept'),
                enabled: active && allowedDecisions.has('accept'),
                intervention: currentStageBusy,
            },
            {
                action: 'send-back',
                label: 'Send back',
                note: `Send back records an operator revise decision and requires a short reason that explains what needs to change.${interventionNote}`,
                confirmLabel: 'Send back',
                successMessage: 'Protocol run sent back.',
                requireReason: true,
                visible: active && allowedDecisions.has('revise'),
                enabled: active && allowedDecisions.has('revise'),
                intervention: currentStageBusy,
            },
            {
                action: 'cancel',
                label: 'Cancel',
                note: 'Cancel is destructive for the current run lifecycle and requires a short audit reason.',
                confirmLabel: 'Cancel run',
                successMessage: 'Protocol run cancelled.',
                requireReason: true,
                visible: active,
                enabled: active,
            },
            {
                action: 'interrupt',
                label: 'Interrupt',
                note: 'Interrupt asks the assigned bot to stop the current provider process and blocks this stage so you can retry, send back, or cancel after reading the preserved result state.',
                confirmLabel: 'Interrupt stage',
                successMessage: 'Stage interrupt requested.',
                requireReason: true,
                visible: active && currentStageBusy,
                enabled: active && currentStageBusy,
                intervention: true,
            },
        ];
    }

    function _runLifecycleSpecs() {
        const status = String(currentRun?.run?.status || '').trim().toLowerCase();
        const busy = ['queued', 'running'].includes(status);
        return [
            {
                action: 'restore',
                label: 'Restore run',
                visible: status === 'archived',
                enabled: status === 'archived',
                danger: false,
                note: 'Restore makes this archived run visible in normal run views again.',
            },
            {
                action: 'archive',
                label: 'Archive run',
                visible: !['archived', 'deleted'].includes(status),
                enabled: !busy,
                danger: false,
                note: 'Archive hides this run from normal views while preserving audit history, artifacts, snapshots, and runtime events.',
            },
            {
                action: 'delete',
                label: 'Delete run',
                visible: status !== 'deleted',
                enabled: !busy,
                danger: true,
                note: 'Delete is a soft delete. It hides the run from normal views and preserves audit records for retention policy.',
            },
        ];
    }

    function _openRunLifecycleDialog(spec) {
        if (!currentRun?.run?.protocol_run_id) return;
        const form = document.createElement('div');
        form.className = 'studio-dialog-form';
        const note = document.createElement('p');
        note.className = 'quiet-note';
        const runningRuntimes = (currentRun?.runtime_instances || [])
            .filter((item) => ['starting', 'running', 'stopping'].includes(String(item?.status || '').trim().toLowerCase()));
        note.textContent = [
            spec.note || '',
            spec.action === 'archive' && runningRuntimes.length
                ? `${runningRuntimes.length} active artifact runtime${runningRuntimes.length === 1 ? '' : 's'} will be stopped before archiving.`
                : '',
        ].filter(Boolean).join(' ');
        form.appendChild(note);
        const reason = document.createElement('textarea');
        reason.className = 'guidance-textarea';
        reason.rows = 4;
        reason.placeholder = 'Optional reason saved in the run timeline';
        form.appendChild(reason);
        let confirmInput = null;
        if (spec.action === 'delete') {
            confirmInput = document.createElement('input');
            confirmInput.className = 'search-input';
            confirmInput.placeholder = 'Type DELETE to confirm';
            form.appendChild(confirmInput);
        }
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn';
        cancelBtn.textContent = 'Cancel';
        const confirmBtn = document.createElement('button');
        confirmBtn.type = 'button';
        confirmBtn.className = spec.danger ? 'btn btn-danger' : 'btn btn-primary';
        confirmBtn.textContent = spec.label;
        const view = UI.showDialog(spec.label, form, {
            actions: [cancelBtn, confirmBtn],
            role: spec.danger ? 'alertdialog' : 'dialog',
            initialFocus: confirmInput || reason,
            maxWidth: '620px',
        });
        cancelBtn.addEventListener('click', () => view.close());
        confirmBtn.addEventListener('click', async () => {
            const runId = currentRun?.run?.protocol_run_id;
            if (!runId) return;
            const body = { reason: String(reason.value || '').trim() };
            if (spec.action === 'delete') {
                const confirmation = String(confirmInput?.value || '').trim().toUpperCase();
                if (confirmation !== 'DELETE') {
                    confirmInput?.focus();
                    return;
                }
                body.confirm = 'DELETE';
            }
            confirmBtn.disabled = true;
            try {
                if (spec.action === 'archive') {
                    for (const runtime of runningRuntimes) {
                        await API.stopProtocolRunArtifactRuntime(runId, runtime.artifact_key);
                    }
                    await API.archiveProtocolRun(runId, body);
                } else if (spec.action === 'restore') {
                    await API.restoreProtocolRun(runId, body);
                } else {
                    await API.deleteProtocolRun(runId, body);
                }
                UI.notify(`${spec.label} completed.`, 'success');
                view.close();
                await Promise.all([loadRunDetail({ soft: true }), loadRuns(), loadIssues({ rerender: false })]);
                renderRunsRoute();
            } catch (err) {
                UI.reportError(`${spec.label} failed`, err, { context: 'Run lifecycle action failed' });
            } finally {
                confirmBtn.disabled = false;
            }
        });
    }

    function _openRunActionDialog(spec) {
        if (!currentRun) {
            return;
        }
        const canonicalSpec = _runActionSpecs()
            .find((item) => String(item?.action || '') === String(spec?.action || '')) || {};
        spec = {
            ...canonicalSpec,
            ...spec,
            title: spec.title || canonicalSpec.label || canonicalSpec.action || 'Run action',
        };
        const form = document.createElement('div');
        form.className = 'studio-dialog-form';

        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = spec.note;
        form.appendChild(note);

        const reasonInput = document.createElement('textarea');
        reasonInput.className = 'guidance-textarea';
        reasonInput.rows = 6;
        reasonInput.placeholder = 'Short reason recorded in the protocol audit trail';
        form.appendChild(reasonInput);

        const resultPanel = document.createElement('div');
        resultPanel.hidden = true;
        form.appendChild(resultPanel);

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn';
        cancelBtn.textContent = 'Cancel';
        const confirmBtn = document.createElement('button');
        confirmBtn.type = 'button';
        confirmBtn.className = spec.action === 'cancel' ? 'btn btn-danger' : 'btn btn-primary';
        confirmBtn.textContent = spec.confirmLabel;
        const view = UI.showDialog(spec.title, form, {
            actions: [cancelBtn, confirmBtn],
            role: 'alertdialog',
            initialFocus: reasonInput,
            maxWidth: '680px',
            closeOnOverlay: false,
            closeOnEscape: false,
        });
        cancelBtn.addEventListener('click', () => view.close());
        confirmBtn.addEventListener('click', async () => {
            const reason = String(reasonInput.value || '').trim();
            if (spec.requireReason && !reason) {
                reasonInput.focus();
                return;
            }
            confirmBtn.disabled = true;
            let mutation = null;
            try {
                mutation = await API.actOnProtocolRun(
                    currentRun.run.protocol_run_id,
                    spec.action,
                    { reason },
                    {
                        expectedVersion: currentRun.run.version || 1,
                        idempotencyKey: (window.crypto && typeof window.crypto.randomUUID === 'function')
                            ? window.crypto.randomUUID().replace(/-/g, '')
                            : `${Date.now()}${Math.random().toString(16).slice(2)}`,
                    },
                );
            } catch (err) {
                if (Number(err?.status || 0) === 409 || String(err?.errorCode || '').includes('CONCURRENT')) {
                    await loadRunDetail();
                    UI.notify('The run changed before this action was applied. Review the refreshed state and try again.', 'warning', { timeout: 0 });
                } else {
                    const message = err && err.message ? err.message : String(err || 'Unknown error');
                    UI.notify(`Failed to ${spec.action.replace('-', ' ')} the protocol run: ${message}`, 'danger', { timeout: 0 });
                    console.error('Protocol run action failed', err);
                }
                confirmBtn.disabled = false;
                return;
            }
            try {
                await loadRuns();
                await loadIssues({ rerender: false });
                await loadRunDetail();
            } catch (err) {
                UI.notify('The action was applied, but the refreshed run detail could not be loaded. Reload the run before taking another action.', 'warning', { timeout: 0 });
                console.error('Protocol run refresh after action failed', err);
            }
            const resultRun = currentRun?.run || mutation?.run || {};
            if (String(resultRun.status || '').trim().toLowerCase() === 'blocked') {
                UI.reconcileChildren(resultPanel, [_renderRunActionBlockedResult(mutation, currentRun)]);
                resultPanel.hidden = false;
                reasonInput.disabled = true;
                confirmBtn.hidden = true;
                cancelBtn.textContent = 'Close';
                confirmBtn.disabled = false;
                return;
            }
            view.close();
            UI.notify(spec.successMessage, 'success');
            confirmBtn.disabled = false;
        });
    }

    function _openForkRunDialog(stageExecution, mode = 'rerun_selected') {
        if (!currentRun?.run?.protocol_run_id || !stageExecution?.protocol_stage_execution_id) {
            UI.notify('Select a stage before forking this run.', 'warning');
            return;
        }
        const normalizedMode = mode === 'continue_after' ? 'continue_after' : 'rerun_selected';
        const form = document.createElement('div');
        form.className = 'studio-dialog-form';
        const note = document.createElement('p');
        note.className = 'quiet-note';
        note.textContent = normalizedMode === 'continue_after'
            ? 'Create a new run, copy snapshots through this stage, seed the prior context, and continue at the next stage.'
            : 'Create a new run, copy snapshots before this stage, and rerun this selected stage in a separate workspace prefix.';
        form.appendChild(note);
        const reasonInput = document.createElement('textarea');
        reasonInput.className = 'guidance-textarea';
        reasonInput.rows = 4;
        reasonInput.placeholder = 'Optional reason for the fork audit trail';
        form.appendChild(reasonInput);
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn';
        cancelBtn.textContent = 'Cancel';
        const confirmBtn = document.createElement('button');
        confirmBtn.type = 'button';
        confirmBtn.className = 'btn btn-primary';
        confirmBtn.textContent = normalizedMode === 'continue_after' ? 'Continue in new run' : 'Rerun stage in new run';
        const view = UI.showDialog(normalizedMode === 'continue_after' ? 'Continue after stage' : 'Rerun selected stage', form, {
            actions: [cancelBtn, confirmBtn],
            maxWidth: '620px',
        });
        cancelBtn.addEventListener('click', () => view.close());
        confirmBtn.addEventListener('click', async () => {
            confirmBtn.disabled = true;
            try {
                const result = await API.forkProtocolRunFromStage(
                    currentRun.run.protocol_run_id,
                    {
                        stage_execution_id: stageExecution.protocol_stage_execution_id,
                        fork_mode: normalizedMode,
                        fork_reason: String(reasonInput.value || '').trim(),
                    },
                    {
                        idempotencyKey: (window.crypto && typeof window.crypto.randomUUID === 'function')
                            ? window.crypto.randomUUID().replace(/-/g, '')
                            : `${Date.now()}${Math.random().toString(16).slice(2)}`,
                    },
                );
                view.close();
                await loadRuns();
                if (result?.run?.protocol_run_id) {
                    _setRunSelection(result.run.protocol_run_id);
                }
                UI.notify('Forked protocol run created.', 'success');
                renderRunsRoute();
            } catch (err) {
                if (String(err?.errorCode || '') === 'PROTOCOL_FORK_SNAPSHOTS_MISSING') {
                    const missing = Array.isArray(err?.details?.missing_snapshots)
                        ? err.details.missing_snapshots.join(', ')
                        : '';
                    UI.notify(missing ? `Fork needs snapshots: ${missing}` : 'Fork needs durable artifact snapshots before it can continue.', 'warning', { timeout: 0 });
                } else {
                    UI.reportError('Fork run failed', err, { context: 'Protocol fork failed' });
                }
            } finally {
                confirmBtn.disabled = false;
            }
        });
    }

    function _openImproveRunDialog() {
        if (!currentRun?.run?.protocol_id) {
            UI.notify('Select a run with a protocol before improving it.', 'warning');
            return;
        }
        const sourceRun = currentRun;
        const form = document.createElement('div');
        form.className = 'protocol-package-dialog protocol-auto-dialog';
        const intro = document.createElement('p');
        intro.className = 'quiet-note';
        intro.textContent = 'Auto Protocol will use this run as context and generate a revised normal protocol. It will not patch the old artifact directly.';
        form.appendChild(intro);

        const requestLabel = document.createElement('label');
        requestLabel.className = 'protocol-auto-field-label';
        requestLabel.textContent = 'What should improve?';
        form.appendChild(requestLabel);

        const request = document.createElement('textarea');
        request.className = 'input';
        request.rows = 5;
        request.placeholder = 'Example: make the runtime start without build/install work, exercise multiple routed journeys, record visible results, and add outcome-readiness plus branding evidence.';
        requestLabel.appendChild(request);

        const resourcePicker = Kit.resourceAttachmentPicker({
            label: 'Attach improvement files',
            help: 'Add assets, mechanics, datasets, patches, screenshots, or zips for the improved protocol.',
            sourceRef: `protocol-run:${sourceRun.run.protocol_run_id}`,
            relation: 'improvement_context',
        });
        form.appendChild(resourcePicker.element);

        const qualityHint = document.createElement('p');
        qualityHint.className = 'quiet-note';
        qualityHint.textContent = 'Good improvements should produce a prepared runtime package, a routed UI/API users can actually exercise, a pass/fail outcome-readiness matrix, and customer-facing copy that uses the requested product/domain brand rather than Octopus.';
        form.appendChild(qualityHint);

        const plannerField = _createAutoProtocolPlannerField([], { loading: true });
        form.appendChild(plannerField.element);

        const lessonPreview = document.createElement('details');
        lessonPreview.className = 'protocol-auto-detail';
        lessonPreview.open = true;
        const lessonSummary = document.createElement('summary');
        lessonSummary.textContent = 'Candidate lessons from this run';
        lessonPreview.appendChild(lessonSummary);
        const lessonBody = document.createElement('div');
        lessonBody.className = 'protocol-auto-detail-body';
        const lessonItems = [];
        if (sourceRun.run?.blocked_code) {
            lessonItems.push(`Blocked: ${sourceRun.run.blocked_code} ${sourceRun.run.blocked_detail || ''}`.trim());
        }
        (sourceRun.stage_executions || []).forEach((stage) => {
            if (stage.failure_code) {
                lessonItems.push(`Stage ${stage.stage_key} failed/blocked with ${stage.failure_code}: ${stage.failure_detail || ''}`.trim());
            } else if (stage.decision_summary) {
                lessonItems.push(`Stage ${stage.stage_key}: ${stage.decision_summary}`);
            }
        });
        (sourceRun.runtime_events || []).forEach((event) => {
            const kind = String(event.event_kind || '');
            if (['journey_failed', 'client_error', 'health_checked', 'runtime_error'].includes(kind)) {
                lessonItems.push(`Runtime ${kind}: ${event.summary || ''}`.trim());
            }
        });
        (sourceRun.transitions || []).forEach((transition) => {
            if (transition.error_code || ['late_result', 'runtime_evidence_auto_accept', 'task_cancel_requested'].includes(String(transition.transition_kind || ''))) {
                lessonItems.push(`${transition.transition_kind}: ${transition.reason || transition.error_code || ''}`.trim());
            }
        });
        (sourceRun.artifacts || []).forEach((artifact) => {
            if (artifact.exists === false || ['missing', 'declared'].includes(String(artifact.verification_state || ''))) {
                lessonItems.push(`Artifact ${artifact.artifact_key} was not proved available.`);
            }
        });
        const lessonNodes = lessonItems.slice(0, 12).map((text) => {
            const item = document.createElement('p');
            item.className = 'quiet-note';
            item.textContent = text;
            return item;
        });
        UI.reconcileChildren(lessonBody, lessonNodes.length ? lessonNodes : [UI.renderEmptyState('No prior blockers or evidence lessons were found in the current run detail. The server will still harvest structured lessons when generation starts.', true)]);
        lessonPreview.appendChild(lessonBody);
        form.appendChild(lessonPreview);

        const status = document.createElement('p');
        status.className = 'quiet-note';
        status.textContent = 'The generated improvement becomes a normal protocol draft you can apply, publish, and run.';
        form.appendChild(status);

        const preview = document.createElement('div');
        preview.className = 'protocol-auto-preview';
        form.appendChild(preview);

        let session = null;
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn';
        cancelBtn.textContent = 'Cancel';
        const generateBtn = document.createElement('button');
        generateBtn.type = 'button';
        generateBtn.className = 'btn btn-primary';
        generateBtn.textContent = 'Generate improvement';
        const applyBtn = document.createElement('button');
        applyBtn.type = 'button';
        applyBtn.className = 'btn';
        applyBtn.textContent = 'Apply draft';
        applyBtn.hidden = true;
        const publishBtn = document.createElement('button');
        publishBtn.type = 'button';
        publishBtn.className = 'btn';
        publishBtn.textContent = 'Publish';
        publishBtn.hidden = true;
        const runBtn = document.createElement('button');
        runBtn.type = 'button';
        runBtn.className = 'btn btn-primary';
        runBtn.textContent = 'Publish & Run';
        runBtn.hidden = true;
        const queueBtn = document.createElement('button');
        queueBtn.type = 'button';
        queueBtn.className = 'btn';
        queueBtn.textContent = 'View in queue';
        queueBtn.hidden = true;
        const view = UI.showDialog('Improve this run', form, {
            actions: [cancelBtn, generateBtn, applyBtn, publishBtn, runBtn, queueBtn],
            maxWidth: '760px',
            initialFocus: request,
            closeOnOverlay: false,
            closeOnEscape: false,
        });
        view.dialog.classList.add('protocol-auto-modal');
        let sessionSubscription = null;
        let planningWaitSeq = 0;
        const originalClose = view.close;
        view.close = () => {
            if (sessionSubscription) {
                sessionSubscription();
                sessionSubscription = null;
            }
            originalClose();
        };
        void API.listAgents({ limit: 100 }).then((payload) => {
            const agents = Array.isArray(payload?.agents) ? payload.agents : (Array.isArray(payload) ? payload : []);
            _populateAutoProtocolPlannerSelect(plannerField.select, agents);
        }).catch((err) => {
            console.warn('Failed to load planner agents for run improvement dialog', err);
            _populateAutoProtocolPlannerSelect(plannerField.select, []);
        });

        const syncActions = () => {
            const hasSession = Boolean(session?.session_id);
            const planning = _autoProtocolPlanning(session);
            const hasDraft = _autoProtocolHasDraft(session);
            const actionable = hasSession && !planning && hasDraft;
            const ready = _runAutoSessionReady(session);
            cancelBtn.textContent = hasSession ? 'Close' : 'Cancel';
            _setAutoProtocolButtonState(generateBtn, { visible: !(hasSession && (planning || hasDraft)) });
            _setAutoProtocolButtonState(applyBtn, { visible: actionable });
            _setAutoProtocolButtonState(publishBtn, { visible: actionable, disabled: planning || !ready });
            _setAutoProtocolButtonState(runBtn, { visible: actionable, disabled: planning || !ready });
            _setAutoProtocolButtonState(queueBtn, { visible: hasSession });
            applyBtn.className = ready || planning ? 'btn' : 'btn btn-primary';
            runBtn.className = ready ? 'btn btn-primary' : 'btn';
            runBtn.style.order = hasSession && ready ? '0' : '3';
            applyBtn.style.order = hasSession ? (ready ? '1' : '0') : '';
            publishBtn.style.order = hasSession ? '2' : '';
            queueBtn.style.order = hasSession ? '3' : '';
            cancelBtn.style.order = hasSession ? '4' : '';
            const gateTitle = ready ? '' : 'Resolve validation and assignment warnings before publishing or running.';
            publishBtn.title = gateTitle;
            runBtn.title = gateTitle;
        };
        queueBtn.addEventListener('click', () => {
            if (!session?.session_id) return;
            view.close();
            Router.navigate(`/ui/design-sessions?session_id=${encodeURIComponent(session.session_id)}`);
        });
        const renderSessionState = (nextSession, { progressMessage = 'Designing improved protocol…', readyMessage = 'Review the generated improvement. Apply it to continue through the normal protocol lifecycle.' } = {}) => {
            session = nextSession;
            if (session?.session_id) {
                _rememberActiveAutoProtocolSession(session);
            }
            if (_autoProtocolPlanning(session)) {
                intro.hidden = true;
                requestLabel.hidden = true;
                _setAutoProtocolStatus(status, progressMessage);
                UI.reconcileChildren(preview, [_autoProtocolProgressEl(session)]);
            } else if (session?.session_id) {
                UI.reconcileChildren(preview, [_runImproveSummaryEl(session)]);
                _setAutoProtocolStatus(status, _autoProtocolFinishedMessage(session, readyMessage));
            }
            syncActions();
        };
        const subscribeToSession = () => {
            if (sessionSubscription) {
                sessionSubscription();
                sessionSubscription = null;
            }
            if (!session?.session_id || !_autoProtocolPlanning(session)) return;
            sessionSubscription = _subscribeAutoProtocolSession(session.session_id, async (updated) => {
                if (!view.dialog.isConnected) return;
                renderSessionState(updated);
            });
        };
        const refreshSessionState = async (options = {}) => {
            if (!session?.session_id) return null;
            const updated = await API.getProtocolAutoSession(session.session_id);
            renderSessionState(updated, options);
            subscribeToSession();
            return session;
        };
        const attachSession = async (sessionId, options = {}) => {
            const id = String(sessionId || '').trim();
            if (!id) return null;
            const updated = await API.getProtocolAutoSession(id);
            if (options.requirePlanning && !_autoProtocolPlanning(updated)) {
                _rememberActiveAutoProtocolSession(null);
                return null;
            }
            if (options.rememberedContext && !_autoProtocolSessionMatchesRememberedContext(updated, options.rememberedContext)) {
                _rememberActiveAutoProtocolSession(null);
                return null;
            }
            renderSessionState(updated, options);
            subscribeToSession();
            return session;
        };
        const waitForPlanning = async (options = {}) => {
            const seq = ++planningWaitSeq;
            subscribeToSession();
            let current = session;
            let polls = 0;
            while (_autoProtocolPlanning(current) && view.dialog.isConnected && seq === planningWaitSeq) {
                await _autoProtocolSleep(sessionSubscription ? 30000 : Math.min(10000, polls < 10 ? 3000 : 5000));
                if (!view.dialog.isConnected || seq !== planningWaitSeq) return session;
                current = await API.getProtocolAutoSession(current.session_id);
                renderSessionState(current, options);
                subscribeToSession();
                polls += 1;
            }
            return session;
        };
        const handlePlanningError = async (err, options = {}) => {
            if (!_autoProtocolPlanningError(err)) return false;
            try {
                await refreshSessionState(options);
            } catch (refreshErr) {
                console.warn('Failed to refresh Auto Protocol session after planning error', refreshErr);
            }
            UI.notify('Auto Protocol is still designing. The dialog reattached to the active planner job.', 'warning', { timeout: 0 });
            return true;
        };
        const ensureSessionReadyForAction = async (options = {}) => {
            if (!session?.session_id) return false;
            await refreshSessionState(options);
            if (_autoProtocolPlanning(session)) {
                UI.notify('Auto Protocol is still designing. Wait for planning to finish before applying, publishing, or running.', 'warning', { timeout: 0 });
                return false;
            }
            return true;
        };

        cancelBtn.addEventListener('click', () => view.close());
        const rememberedSessionId = activeAutoProtocolSessionId || _rememberedAutoProtocolSessionId();
        if (rememberedSessionId) {
            void attachSession(rememberedSessionId, {
                requirePlanning: true,
                rememberedContext: { sourceRunId: sourceRun.run.protocol_run_id },
            }).catch((err) => {
                console.warn('Could not reattach Auto Protocol session', err);
            });
        }
        const runGenerateImprovement = async () => {
            const changeRequest = request.value.trim();
            if (!changeRequest) {
                status.textContent = 'Describe what should improve.';
                request.focus();
                return;
            }
            _setAutoProtocolButtonBusy(generateBtn, true);
            intro.hidden = true;
            requestLabel.hidden = true;
            _setAutoProtocolStatus(status, 'Designing improved protocol…');
            UI.reconcileChildren(preview, [UI.renderEmptyState('Planning stages, artifacts, reviewers, and runtime expectations…', true)]);
            try {
                session = await API.createProtocolAutoSession({
                    mode: 'revise',
                    surface: 'registry',
                    target_protocol_id: sourceRun.run.protocol_id,
                    source_run_id: sourceRun.run.protocol_run_id,
                    requirement_text: _runImprovementRequirement(sourceRun, changeRequest),
                    constraints_text: _runImprovementContext(sourceRun),
                    resource_refs: resourcePicker.resourceRefs(),
                    workspace_ref: sourceRun.run.workspace_ref || '',
                    preferred_design_agent_id: plannerField.select.value,
                });
                renderSessionState(session, { progressMessage: 'Designing improved protocol…' });
                if (_autoProtocolPlanning(session)) {
                    await waitForPlanning({
                        progressMessage: 'Designing improved protocol…',
                        readyMessage: 'Review the generated improvement. Apply it to continue through the normal protocol lifecycle.',
                    });
                } else {
                    renderSessionState(session, { readyMessage: 'Review the generated improvement. Apply it to continue through the normal protocol lifecycle.' });
                }
                syncActions();
            } catch (err) {
                const attachedSessionId = _autoProtocolErrorSessionId(err);
                if (attachedSessionId) {
                    try {
                        await attachSession(attachedSessionId);
                    } catch (attachErr) {
                        console.warn('Could not attach partially-created Auto Protocol session', attachErr);
                    }
                }
                if (!session?.session_id) {
                    intro.hidden = false;
                    requestLabel.hidden = false;
                }
                const retry = (session?.session_id || attachedSessionId)
                    ? () => refreshSessionState()
                    : () => runGenerateImprovement();
                _setAutoProtocolDialogError(preview, status, 'Failed to generate the run improvement', err, retry);
            }
            _setAutoProtocolButtonBusy(generateBtn, false);
            syncActions();
        };
        generateBtn.addEventListener('click', () => void runGenerateImprovement());
        const runApplyImprovement = async () => {
            if (!session?.session_id) return;
            _setAutoProtocolButtonBusy(applyBtn, true);
            _setAutoProtocolStatus(status, 'Applying improved draft…');
            try {
                if (!await ensureSessionReadyForAction()) {
                    _setAutoProtocolButtonBusy(applyBtn, false);
                    syncActions();
                    return;
                }
                const applied = await API.applyProtocolAutoSession(session.session_id);
                session = applied;
                UI.reconcileChildren(preview, [_runImproveSummaryEl(session)]);
                const protocolId = _autoProtocolTargetProtocolId(applied);
                if (protocolId) {
                    view.close();
                    UI.notify('Improved protocol draft applied.', 'success');
                    Router.navigate(`/ui/protocols?protocol_id=${encodeURIComponent(protocolId)}`);
                    return;
                }
                _setAutoProtocolStatus(status, 'Draft applied, but the protocol id was not returned.');
                UI.notify('Draft applied, but the protocol id was not returned. Refresh protocols before continuing.', 'warning', { timeout: 0 });
            } catch (err) {
                if (await handlePlanningError(err)) {
                    _setAutoProtocolButtonBusy(applyBtn, false);
                    syncActions();
                    return;
                }
                _setAutoProtocolDialogError(preview, status, 'Failed to apply improved protocol draft', err, () => runApplyImprovement());
            }
            _setAutoProtocolButtonBusy(applyBtn, false);
            syncActions();
        };
        applyBtn.addEventListener('click', () => void runApplyImprovement());
        const runPublishImprovement = async () => {
            if (!session?.session_id) return;
            _setAutoProtocolButtonBusy(publishBtn, true);
            _setAutoProtocolStatus(status, 'Publishing improved protocol…');
            try {
                if (!await ensureSessionReadyForAction()) {
                    _setAutoProtocolButtonBusy(publishBtn, false);
                    syncActions();
                    return;
                }
                session = await API.publishProtocolAutoSession(session.session_id);
                UI.reconcileChildren(preview, [_runImproveSummaryEl(session)]);
                _setAutoProtocolStatus(status, 'Published. You can start a fresh run now.');
                UI.notify('Improved protocol published.', 'success');
                syncActions();
            } catch (err) {
                if (await handlePlanningError(err)) {
                    _setAutoProtocolButtonBusy(publishBtn, false);
                    syncActions();
                    return;
                }
                _setAutoProtocolDialogError(preview, status, 'Failed to publish improved protocol', err, () => runPublishImprovement());
            }
            _setAutoProtocolButtonBusy(publishBtn, false);
            syncActions();
        };
        publishBtn.addEventListener('click', () => void runPublishImprovement());
        const runStartImprovement = async () => {
            if (!session?.session_id) return;
            _setAutoProtocolButtonBusy(runBtn, true);
            _setAutoProtocolStatus(status, 'Publishing and starting improved run…');
            try {
                if (!await ensureSessionReadyForAction()) {
                    _setAutoProtocolButtonBusy(runBtn, false);
                    syncActions();
                    return;
                }
                session = await API.runProtocolAutoSession(session.session_id, {
                    origin_channel: 'registry',
                    idempotency_key: _autoProtocolRunAttemptKey(session.session_id),
                });
                UI.reconcileChildren(preview, [_runImproveSummaryEl(session)]);
                const runId = _runAutoSessionRunId(session);
                view.close();
                if (runId) {
                    UI.notify('Improved run started.', 'success');
                    Router.navigate(`/ui/runs?run_id=${encodeURIComponent(runId)}`);
                    return;
                }
                UI.notify('Improved run started, but no run id was returned.', 'success');
            } catch (err) {
                if (await handlePlanningError(err)) {
                    _setAutoProtocolButtonBusy(runBtn, false);
                    syncActions();
                    return;
                }
                _setAutoProtocolDialogError(preview, status, 'Failed to run improved protocol', err, () => runStartImprovement());
            }
            _setAutoProtocolButtonBusy(runBtn, false);
            syncActions();
        };
        runBtn.addEventListener('click', () => void runStartImprovement());
        syncActions();
    }

    function _buildRunActionBar({ sticky = false, specs = null } = {}) {
        const runActionBar = document.createElement('div');
        runActionBar.className = sticky ? 'editor-actions protocol-sticky-actions' : 'editor-actions';
        (specs || _runActionSpecs()).filter((spec) => spec.visible !== false).forEach((spec) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = spec.action === 'cancel' ? 'btn btn-danger' : 'btn btn-primary';
            btn.textContent = spec.label;
            btn.dataset.runAction = spec.action;
            btn.setAttribute('aria-label', `${spec.label} protocol run`);
            btn.disabled = !spec.enabled;
            btn.addEventListener('click', async (event) => {
                const action = String(event.currentTarget?.dataset?.runAction || spec.action || '').trim();
                const latestSpec = _runActionSpecs().find((item) => String(item.action || '') === action) || null;
                if (!latestSpec || latestSpec.visible === false || latestSpec.enabled === false) {
                    await loadRunDetail();
                    UI.notify('The run changed before this action was applied. Review the refreshed state and try again.', 'warning');
                    return;
                }
                _openRunActionDialog({
                    title: latestSpec.label,
                    action: latestSpec.action,
                    note: latestSpec.note,
                    confirmLabel: latestSpec.confirmLabel,
                    successMessage: latestSpec.successMessage,
                    requireReason: latestSpec.requireReason,
                });
            });
            runActionBar.appendChild(btn);
        });

        const exportRunButton = document.createElement('button');
        exportRunButton.type = 'button';
        exportRunButton.className = 'btn';
        exportRunButton.textContent = 'Export run';
        exportRunButton.addEventListener('click', async () => {
            if (!currentRun) {
                return;
            }
            try {
                const exported = await API.exportProtocolRun(currentRun.run.protocol_run_id);
                _downloadProtocolText(
                    `${UI.safeFilename(currentRun.definition?.slug || currentRun.run.protocol_run_id || 'protocol-run')}.protocol-run.json`,
                    JSON.stringify(exported, null, 2),
                    'application/json',
                );
            } catch (err) {
                UI.reportError('Failed to export the protocol run', err, {
                    context: 'Protocol run export failed',
                });
            }
        });
        runActionBar.appendChild(exportRunButton);

        const improveRunButton = document.createElement('button');
        improveRunButton.type = 'button';
        improveRunButton.className = 'btn btn-primary';
        improveRunButton.textContent = 'Improve this run';
        improveRunButton.disabled = !currentRun?.run?.protocol_id;
        improveRunButton.addEventListener('click', _openImproveRunDialog);
        runActionBar.appendChild(improveRunButton);

        return runActionBar;
    }

    function _buildRunNavigatorPanel() {
        const issueListActive = Boolean(issueKindFilter);
        const panel = document.createElement('section');
        panel.className = 'editor-panel protocol-panel run-feed-panel';

        const title = document.createElement('div');
        title.className = 'editor-section-title';
        title.textContent = issueListActive ? 'Protocol issues' : Kit.dict.label('runs.list.title', 'Runs');
        panel.appendChild(title);

        const controls = document.createElement('div');
        controls.className = 'route-controls run-view-controls';
        const viewFilterControl = UI.createSegmentedControl(
            _compactProtocolRunViewOptions(),
            (value) => {
                runViewFilter = _protocolRunViewFilterValue(value);
                if (runPaginator) runPaginator.reset(0);
                currentRunId = '';
                currentRun = null;
                currentIssues = [];
                lastRunEvent = null;
                activeRunDetailSection = '';
                _resetRunStageEvidenceSelection();
                activeRunArtifactStageExecutionId = '';
                runDetailLoading = false;
                runDetailRequestToken += 1;
                _bindRunSubscription();
                _writeState({ push: true });
                renderRunsRoute();
            },
            { label: 'Run view', value: runViewFilter },
        );
        controls.appendChild(viewFilterControl.element);
        panel.appendChild(controls);

        const secondaryFilters = document.createElement('details');
        secondaryFilters.className = 'run-secondary-filters';
        secondaryFilters.open = Boolean(issueKindFilter || includeGenerated);
        const secondarySummary = document.createElement('summary');
        const secondaryTitle = document.createElement('span');
        secondaryTitle.textContent = 'Issue and audit filters';
        secondarySummary.appendChild(secondaryTitle);
        const secondaryState = document.createElement('small');
        secondaryState.textContent = [
            issueKindFilter
                ? (PROTOCOL_ISSUE_FILTER_OPTIONS.find((item) => item.value === issueKindFilter)?.label || 'Issue view')
                : 'Runs',
            includeGenerated ? 'generated shown' : 'generated hidden',
        ].join(' · ');
        secondarySummary.appendChild(secondaryState);
        secondaryFilters.appendChild(secondarySummary);
        const secondaryBody = document.createElement('div');
        secondaryBody.className = 'run-secondary-filter-body';
        const issueFilterControl = UI.createSegmentedControl(
            PROTOCOL_ISSUE_FILTER_OPTIONS,
            (value) => {
                issueKindFilter = _protocolIssueFilterValue(value);
                if (runPaginator) runPaginator.reset(0);
                _writeState({ push: true });
                if (issueKindFilter) {
                    void loadIssues({ rerender: true });
                } else {
                    renderRunsRoute();
                }
            },
            { label: 'Run triage focus', value: issueKindFilter || '' },
        );
        secondaryBody.appendChild(issueFilterControl.element);

        const generatedToggle = document.createElement('a');
        UI.updateGeneratedAuditToggleLink(generatedToggle, includeGenerated, 'runs');
        secondaryBody.appendChild(generatedToggle);
        secondaryFilters.appendChild(secondaryBody);
        panel.appendChild(secondaryFilters);

        if (issueListActive) {
            if (runPaginator) runPaginator.clear();
            const searchInput = document.createElement('input');
            searchInput.className = 'search-input';
            searchInput.placeholder = 'Search issues';
            searchInput.value = runSearch;
            searchInput.addEventListener('input', () => {
                runSearch = searchInput.value;
                renderRunsRoute();
            });
            panel.appendChild(searchInput);

            const list = document.createElement('div');
            list.className = 'protocol-scroll';
            const rows = _issueRows();
            UI.reconcileChildren(
                list,
                rows.length
                    ? rows
                    : [UI.renderEmptyState(
                        'No blocked runs, lease issues, contract failures, or expired timeouts match this filter.',
                        true,
                    )],
            );
            panel.appendChild(list);
            if (currentRunId) {
                panel.appendChild(_buildRunDetailPanel());
            }
            return panel;
        }

        const issuesByRunId = new Map();
        (protocolIssues || []).forEach((issue) => {
            const runId = String(issue.protocol_run_id || '').trim();
            if (!runId || issuesByRunId.has(runId)) return;
            issuesByRunId.set(runId, issue);
        });

        const runSource = [...(runs || [])];
        if (currentRunId && !runSource.some((item) => _runRecordId(item) === String(currentRunId || ''))) {
            const selectedHiddenRun = (runs || []).find((item) => _runRecordId(item) === String(currentRunId || ''));
            if (selectedHiddenRun) {
                runSource.unshift(selectedHiddenRun);
            } else if (_runRecordId(currentRun?.run) === String(currentRunId || '')) {
                runSource.unshift(currentRun.run);
            }
        }
        panel.appendChild(_buildRunsOverviewStrip(runSource, issuesByRunId));
        const listRuns = runSource.filter((item) => {
            const runId = _runRecordId(item);
            const issue = issuesByRunId.get(String(runId || '').trim()) || null;
            if (!_runMatchesViewFilter(item, issue)) return false;
            if (runStatusFilter && String(item.status || '') !== runStatusFilter) return false;
            if (!runSearch) return true;
            const haystack = [
                item.problem_statement || '',
                item.protocol_run_id || '',
                item.current_stage_key || '',
                item.status || '',
                item.protocol_id || '',
            ].join(' ').toLowerCase();
            return haystack.includes(runSearch.toLowerCase());
        }).map((item) => {
            const runId = _runRecordId(item);
            const issue = issuesByRunId.get(String(runId || '').trim()) || null;
            const group = _runGroupInfo(item, issue);
            const stageLabel = _runStageListLabel(item);
            return {
                id: runId,
                status: item.status,
                attention: issue ? _issueAttentionLabel(issue) : '',
                attentionStatus: issue ? 'blocked' : '',
                title: _runDisplayTitle(item),
                subtitle: [
                    stageLabel,
                    item.protocol_id ? `Protocol ${_shortRunId(item.protocol_id)}` : '',
                ].filter(Boolean).join(' · '),
                badge: _shortRunId(runId),
                meta: [
                    stageLabel,
                    item.updated_at ? `Updated ${UI.relativeTime(item.updated_at)}` : '',
                    item.origin_channel ? `From ${item.origin_channel}` : '',
                ],
                groupKey: runViewFilter === 'attention' ? group.key : '',
                groupLabel: runViewFilter === 'attention' ? group.label : '',
                groupRank: runViewFilter === 'attention' ? group.rank : 0,
                groupMeta: group.key === 'attention'
                    ? 'Review blocked or failed work first'
                    : group.key === 'active'
                        ? 'Live and queued work'
                        : '',
                raw: item,
            };
        });

        panel.appendChild(Kit.runsList({
            runs: listRuns,
            search: runSearch,
            statusFilter: runStatusFilter,
            selectedId: currentRunId,
            onSearch: (value) => {
                runSearch = value;
                renderRunsRoute();
            },
            onStatusFilter: (value) => {
                runStatusFilter = value || '';
                if (runPaginator) runPaginator.reset(0);
                currentRunId = '';
                currentRun = null;
                currentIssues = [];
                lastRunEvent = null;
                activeRunDetailSection = '';
                _resetRunStageEvidenceSelection();
                activeRunArtifactStageExecutionId = '';
                runDetailLoading = false;
                runDetailRequestToken += 1;
                _bindRunSubscription();
                _writeState({ push: true });
                renderRunsRoute();
            },
            onSelect: (run) => _setRunSelection(run.id),
            renderExpanded: () => _buildRunDetailPanel(),
            filtersMode: 'disclosure',
            emptyHint: includeGenerated
                ? 'No generated or normal runs match this filter.'
                : 'No normal runs match this filter. Use Show generated/audit runs to inspect test, rehearsal, and generated executions.',
        }));
        if (currentRunId) {
            if (runPaginator) runPaginator.clear();
        } else {
            panel.appendChild(runPaginationEl);
            if (runPaginator) {
                runPaginator.render({
                    hasMore: !!runsListData?.has_more,
                    nextCursor: runsListData?.next_cursor || 0,
                    info: `${listRuns.length} shown`,
                });
            }
        }
        return panel;
    }

    function _buildRunDetailPanel() {
        const issueListActive = Boolean(issueKindFilter);
        const detailPanel = document.createElement('div');
        detailPanel.className = 'run-expansion-panel';

        if ((runDetailLoading || !currentRun) && currentRunId) {
            detailPanel.appendChild(UI.renderEmptyState('Loading run detail…', true));
            return detailPanel;
        }

        if (!currentRun) {
            detailPanel.appendChild(UI.renderEmptyState(
                issueListActive
                    ? 'Select an issue to inspect the affected run and operator actions.'
                    : 'Select a run to inspect state, timeline, artifacts, and operator actions.',
                true,
            ));
            return detailPanel;
        }

        const stageDefinitionByKey = new Map(
            (currentRun.version?.definition_json?.stages || []).map((item) => [String(item.stage_key || ''), item]),
        );
        const stageOrderByKey = new Map(
            (currentRun.version?.definition_json?.stages || []).map((item, index) => [String(item.stage_key || ''), index]),
        );
        const artifactDefinitionByKey = new Map(
            (currentRun.version?.definition_json?.artifacts || []).map((item) => [String(item.artifact_key || ''), item]),
        );
        const timestampMs = (value) => {
            const parsed = Date.parse(String(value || ''));
            return Number.isFinite(parsed) ? parsed : 0;
        };
        const taskById = new Map(
            (currentRun.tasks || []).map((item) => [String(item.routed_task_id || ''), item]),
        );
        const stageTimelineMs = (item) => {
            const task = taskById.get(String(item?.routed_task_id || '')) || null;
            return timestampMs(item?.started_at || item?.completed_at || item?.updated_at || task?.updated_at);
        };
        const stageRows = [...(currentRun.stage_executions || [])].sort((left, right) => {
            const leftTime = stageTimelineMs(left);
            const rightTime = stageTimelineMs(right);
            if (leftTime && rightTime && leftTime !== rightTime) return leftTime - rightTime;
            if (leftTime !== rightTime) return leftTime ? -1 : 1;
            const leftOrder = stageOrderByKey.has(String(left.stage_key || ''))
                ? stageOrderByKey.get(String(left.stage_key || ''))
                : Number.MAX_SAFE_INTEGER;
            const rightOrder = stageOrderByKey.has(String(right.stage_key || ''))
                ? stageOrderByKey.get(String(right.stage_key || ''))
                : Number.MAX_SAFE_INTEGER;
            if (leftOrder !== rightOrder) return leftOrder - rightOrder;
            const leftAttempt = Number(left.attempt || 0);
            const rightAttempt = Number(right.attempt || 0);
            if (leftAttempt !== rightAttempt) return leftAttempt - rightAttempt;
            return String(left.protocol_stage_execution_id || '').localeCompare(String(right.protocol_stage_execution_id || ''));
        });
        const stageValueFor = (item, index = 0) => String(item?.protocol_stage_execution_id || item?.stage_key || `stage-${index}`);
        const stageValueForStageKey = (stageKey) => {
            const normalizedStageKey = String(stageKey || '').trim();
            if (!normalizedStageKey) return '';
            let index = -1;
            stageRows.forEach((item, itemIndex) => {
                if (String(item.stage_key || '') === normalizedStageKey) {
                    index = itemIndex;
                }
            });
            return index >= 0 ? stageValueFor(stageRows[index], index) : normalizedStageKey;
        };
        const selectRunStageEvidence = (stageInfo = {}) => {
            activeRunDetailSection = 'stages';
            const nextStageValue = String(
                stageInfo.executionId
                || stageValueForStageKey(stageInfo.stageKey)
                || '',
            );
            activeRunStageExecutionId = nextStageValue;
            const currentStage = currentRunStageExecution();
            const currentStageIndex = currentStage ? Math.max(stageRows.indexOf(currentStage), 0) : -1;
            const currentStageValue = currentStage ? stageValueFor(currentStage, currentStageIndex) : '';
            activeRunStageFollowsCurrent = Boolean(nextStageValue && currentStageValue && nextStageValue === currentStageValue);
            UI.clearMemoizedRender(contentEl);
            renderRunsRoute();
        };
        const { transitionRows } = _filteredProtocolTimelineData(currentRun, '');
        const stageById = new Map(
            (currentRun.stage_executions || []).map((item) => [String(item.protocol_stage_execution_id || ''), item]),
        );
        const participantByKey = new Map(
            (currentRun.participants || []).map((item) => [String(item.participant_key || ''), item]),
        );
        const issuesByStageKey = new Map();
        (currentIssues || []).forEach((item) => {
            const key = String(item.stage_key || '').trim();
            if (!key) return;
            const bucket = issuesByStageKey.get(key) || [];
            bucket.push(item);
            issuesByStageKey.set(key, bucket);
        });
        const artifactsByProducer = new Map();
        (currentRun.artifacts || []).forEach((item) => {
            const key = String(item.produced_by_stage_execution_id || '').trim();
            if (!key) return;
            const bucket = artifactsByProducer.get(key) || [];
            bucket.push(item);
            artifactsByProducer.set(key, bucket);
        });
        const artifactGroups = new Map();
        (currentRun.artifacts || []).forEach((item) => {
            const key = String(item.artifact_key || '').trim() || String(item.workspace_path || item.location || '').trim();
            if (!key) return;
            const bucket = artifactGroups.get(key) || [];
            bucket.push(item);
            artifactGroups.set(key, bucket);
        });
        const artifactRows = [];
        const pendingArtifactRows = [];
        artifactGroups.forEach((items) => {
            const sorted = [...items].sort((left, right) => {
                const leftExists = Boolean(left?.exists);
                const rightExists = Boolean(right?.exists);
                if (leftExists !== rightExists) return leftExists ? -1 : 1;
                const leftVerified = String(left?.verification_state || '').trim().toLowerCase() === 'verified';
                const rightVerified = String(right?.verification_state || '').trim().toLowerCase() === 'verified';
                if (leftVerified !== rightVerified) return leftVerified ? -1 : 1;
                const leftSize = Number(left?.size_bytes || 0);
                const rightSize = Number(right?.size_bytes || 0);
                if (leftSize !== rightSize) return rightSize - leftSize;
                return String(left?.artifact_key || '').localeCompare(String(right?.artifact_key || ''));
            });
            const chosen = sorted[0] || null;
            if (!chosen) return;
            if (chosen.exists) {
                artifactRows.push(chosen);
            } else {
                pendingArtifactRows.push(chosen);
            }
        });

        const appendSectionTitle = (target, titleText, noteText = '') => {
            const wrap = document.createElement('div');
            wrap.className = 'run-evidence-section-head';
            const title = document.createElement('div');
            title.className = 'editor-section-title';
            title.textContent = titleText;
            wrap.appendChild(title);
            if (noteText) {
                const note = document.createElement('p');
                note.className = 'quiet-note';
                note.textContent = noteText;
                wrap.appendChild(note);
            }
            target.appendChild(wrap);
        };

        const createRunArtifactRow = (artifact, { relationship = 'Produced output', missing = false, compactActions = false } = {}) => {
            const definition = artifactDefinitionByKey.get(String(artifact.artifact_key || '')) || null;
            const pathLabel = _protocolArtifactDisplayPath(artifact) || _artifactDefinitionPath(definition || artifact);
            const identifier = definition && String(definition.display_name || '').trim()
                ? String(artifact.artifact_key || '').trim()
                : '';
            const autoMeta = currentRun.version?.definition_json?.metadata?.auto_protocol || {};
            const explicitPrimary = autoMeta.primary_artifact || {};
            const explicitPrimaryKey = String(explicitPrimary.artifact_key || autoMeta.primary_artifact_key || '').trim();
            const isPrimaryArtifact = explicitPrimaryKey && String(artifact.artifact_key || '').trim() === explicitPrimaryKey;
            const runtimeExpected = primaryRuntimeExpected(artifact, definition, isPrimaryArtifact ? explicitPrimary : {});
            return UI.createArtifactListRow({
                label: _protocolArtifactDisplayLabel(artifact, definition),
                sublabelParts: [
                    relationship,
                    pathLabel,
                    identifier,
                    _protocolArtifactLabel(artifact),
                ],
                badgeText: missing ? 'missing' : (artifact.verification_state || artifact.state || 'available'),
                badgeClass: missing ? 'badge-blocked' : 'badge-connected',
                actionRow: _protocolArtifactActionRow(
                    currentRun.run.protocol_run_id,
                    artifact,
                    definition,
                    {
                        missing: missing || !artifact.exists,
                        runtimeExpected,
                        prominentRuntime: compactActions,
                    },
                ),
            });
        };

        const createArtifactList = (rows, { emptyText = '', relationshipFor = null, missing = false } = {}) => {
            const list = document.createElement('div');
            list.className = 'task-artifact-list';
            const nodes = rows.map((artifact) => createRunArtifactRow(artifact, {
                relationship: typeof relationshipFor === 'function' ? relationshipFor(artifact) : relationshipFor || 'Produced output',
                missing,
            }));
            UI.reconcileChildren(list, nodes.length ? nodes : [UI.renderEmptyState(emptyText, true)]);
            return list;
        };

        const transitionsForStage = (stageExecutionId) => transitionRows.filter((item) =>
            String(item.to_stage_execution_id || '') === String(stageExecutionId || '')
            || String(item.from_stage_execution_id || '') === String(stageExecutionId || ''),
        );
        const stageLabelForExecutionId = (stageExecutionId) => {
            const stage = stageById.get(String(stageExecutionId || ''));
            const stageDef = stage ? stageDefinitionByKey.get(String(stage.stage_key || '')) || {} : {};
            return stage ? String(stageDef.display_name || stage.stage_key || 'Stage') : '';
        };
        const transitionDirectionForStage = (transition, stageExecutionId) => {
            const stageId = String(stageExecutionId || '');
            const fromId = String(transition?.from_stage_execution_id || '');
            const toId = String(transition?.to_stage_execution_id || '');
            if (fromId === stageId && toId === stageId) return 'within';
            if (fromId === stageId && toId) return 'outgoing';
            if (toId === stageId && fromId) return 'incoming';
            if (fromId === stageId) return 'from-stage';
            if (toId === stageId) return 'to-stage';
            return '';
        };
        const transitionLabelForStage = (transition, stageExecutionId) => {
            const kind = String(transition?.transition_kind || '').trim().toLowerCase();
            const decision = String(transition?.decision || '').trim();
            const direction = transitionDirectionForStage(transition, stageExecutionId);
            if (kind === 'dispatch') return 'Dispatched to agent';
            if (kind === 'advance' && direction === 'incoming') return 'Arrived from previous stage';
            if (kind === 'advance' && direction === 'outgoing') return 'Completed and advanced';
            if (kind === 'terminal') return 'Finished run';
            if (kind === 'blocked') return 'Blocked';
            if (kind === 'retry') return 'Retry requested';
            return [
                _titleCaseWords(kind || 'transition'),
                decision ? _protocolDecisionLabel(decision) || decision : '',
            ].filter(Boolean).join(' · ');
        };
        const transitionSummaryForStage = (transition, stageExecutionId) => {
            const direction = transitionDirectionForStage(transition, stageExecutionId);
            const fromLabel = stageLabelForExecutionId(transition?.from_stage_execution_id);
            const toLabel = stageLabelForExecutionId(transition?.to_stage_execution_id);
            const directionText = direction === 'incoming' && fromLabel
                ? `from ${fromLabel}`
                : direction === 'outgoing' && toLabel
                    ? `to ${toLabel}`
                    : '';
            return [
                transition?.reason || transition?.actor_ref || '',
                directionText,
                transition?.error_code || '',
            ].filter(Boolean).join(' · ');
        };

        const latestStageExecution = (items = []) => {
            const rows = Array.isArray(items) ? items.filter(Boolean) : [];
            return rows.reduce((best, item) => {
                if (!best) return item;
                const bestAttempt = Number(best.attempt || 0);
                const itemAttempt = Number(item.attempt || 0);
                if (itemAttempt !== bestAttempt) return itemAttempt > bestAttempt ? item : best;
                const bestTime = timestampMs(best.updated_at || best.completed_at || best.started_at);
                const itemTime = timestampMs(item.updated_at || item.completed_at || item.started_at);
                return itemTime >= bestTime ? item : best;
            }, null);
        };
        const stageAttemptsByKey = new Map();
        stageRows.forEach((item) => {
            const key = String(item.stage_key || '').trim();
            if (!key) return;
            const bucket = stageAttemptsByKey.get(key) || [];
            bucket.push(item);
            stageAttemptsByKey.set(key, bucket);
        });
        const latestStageExecutionByKey = new Map();
        stageAttemptsByKey.forEach((items, key) => {
            latestStageExecutionByKey.set(key, latestStageExecution(items));
        });
        const stageOrdinalFor = (stageKey) => {
            const key = String(stageKey || '').trim();
            if (key && stageOrderByKey.has(key)) return Number(stageOrderByKey.get(key) || 0) + 1;
            const fallbackIndex = Array.from(stageAttemptsByKey.keys()).findIndex((item) => item === key);
            return fallbackIndex >= 0 ? fallbackIndex + 1 : 0;
        };
        const runStageCount = () => {
            const definitionCount = Array.isArray(currentRun.version?.definition_json?.stages)
                ? currentRun.version.definition_json.stages.length
                : 0;
            return Math.max(definitionCount, stageAttemptsByKey.size);
        };
        const isPreviousStageAttempt = (item) => {
            const key = String(item?.stage_key || '').trim();
            const latest = key ? latestStageExecutionByKey.get(key) : null;
            if (!latest || !item) return false;
            return String(latest.protocol_stage_execution_id || '') !== String(item.protocol_stage_execution_id || '');
        };
        const taskForStage = (item) => taskById.get(String(item?.routed_task_id || '')) || null;
        const taskTargetLabel = (task, fallback = '') => String(
            task?.target_display_name
            || task?.target_agent_id
            || fallback
            || '',
        ).trim();
        const taskStateLabel = (task) => {
            const status = String(task?.status || '').trim();
            return status ? _titleCaseWords(status) : '';
        };
        const taskUpdateText = (task, limit = 220) => {
            const taskStatus = String(task?.status || '').trim().toLowerCase();
            const terminal = ['completed', 'failed', 'cancelled'].includes(taskStatus);
            const text = String(terminal
                ? (task?.result_summary || task?.summary || '')
                : (task?.summary || task?.result_summary || '')).trim();
            return text ? _compactRunText(text, limit) : '';
        };
        const taskUpdatedLabel = (task) => task?.updated_at ? `Updated ${UI.relativeTime(task.updated_at)}` : '';
        const stageAttemptLabel = (item) => `Attempt ${String(item?.attempt || 1)}`;
        const stageStatusLabel = (item) => {
            const status = String(item?.status || '').trim().toLowerCase();
            const failureCode = String(item?.failure_code || '').trim().toLowerCase();
            if (status === 'blocked' && failureCode.startsWith('runtime_')) return 'Needs runtime evidence';
            if (status === 'blocked') return 'Needs attention';
            return status ? _titleCaseWords(status) : 'Pending';
        };
        const runStatusInfo = (run = {}) => {
            const status = String(run.status || 'queued').trim().toLowerCase();
            const blockedCode = String(run.blocked_code || '').trim().toLowerCase();
            if (status === 'blocked' && blockedCode.startsWith('runtime_')) {
                return {
                    status,
                    active: false,
                    actionable: true,
                    label: 'Runtime verification required',
                    kicker: 'Verification required',
                    detail: run.blocked_detail || 'Start and exercise the primary artifact through the Registry before final acceptance.',
                };
            }
            if (status === 'blocked') {
                return {
                    status,
                    active: false,
                    actionable: true,
                    label: 'Needs attention',
                    kicker: 'Needs attention',
                    detail: run.blocked_detail || 'The current stage needs operator action before the run can continue.',
                };
            }
            if (['queued', 'running'].includes(status)) {
                return { status, active: true, actionable: true, label: status || 'running', kicker: 'Run in progress', detail: '' };
            }
            return {
                status,
                active: false,
                actionable: !['completed', 'failed', 'cancelled', 'archived', 'deleted'].includes(status),
                label: status || 'queued',
                kicker: ['completed', 'failed', 'cancelled', 'archived', 'deleted'].includes(status) ? 'Run finished' : 'Run status',
                detail: run.termination_summary || '',
            };
        };
        const primaryRuntimeExpected = (artifact, definition = {}, primary = {}) => {
            const artifactKey = String(artifact?.artifact_key || primary?.artifact_key || '').trim();
            const blockedCode = String(currentRun?.run?.blocked_code || '').trim().toLowerCase();
            const autoMeta = currentRun.version?.definition_json?.metadata?.auto_protocol || {};
            const explicitPrimaryKey = String(autoMeta.primary_artifact?.artifact_key || autoMeta.primary_artifact_key || '').trim();
            if (artifactKey && blockedCode.startsWith('runtime_') && (!explicitPrimaryKey || artifactKey === explicitPrimaryKey)) return true;
            const parts = [
                primary?.open_behavior,
                definition?.open_behavior,
                primary?.runtime_kind,
                definition?.runtime_kind,
                ...(Array.isArray(primary?.evidence_requirements) ? primary.evidence_requirements : []),
            ].map((item) => String(item || '').trim()).filter(Boolean);
            return parts.some((item) => /(runtime|runnable|app|service|api|ui|browser|playable)/i.test(item));
        };

        const currentRunStageExecution = () => {
            const run = currentRun.run || {};
            const primaryArtifactStageExecution = () => {
                const autoMeta = currentRun.version?.definition_json?.metadata?.auto_protocol || {};
                const primary = autoMeta.primary_artifact || {};
                const primaryStageKey = String(primary.produced_by_stage_key || '').trim();
                if (primaryStageKey) {
                    const matchingAttempts = stageRows.filter((item) => String(item.stage_key || '') === primaryStageKey);
                    if (matchingAttempts.length) return latestStageExecution(matchingAttempts);
                }
                const primaryArtifactKey = String(primary.artifact_key || autoMeta.primary_artifact_key || '').trim();
                const producedArtifact = primaryArtifactKey
                    ? artifactRows.find((item) => String(item.artifact_key || '') === primaryArtifactKey)
                    : null;
                const producerExecutionId = String(producedArtifact?.produced_by_stage_execution_id || '').trim();
                if (producerExecutionId && stageById.has(producerExecutionId)) {
                    return stageById.get(producerExecutionId);
                }
                return null;
            };
            const runStatus = String(run.status || '').trim().toLowerCase();
            const blockedCode = String(run.blocked_code || '').trim().toLowerCase();
            if ((runStatus === 'blocked' && blockedCode.startsWith('runtime_')) || runStatus === 'completed') {
                const primaryStage = primaryArtifactStageExecution();
                if (primaryStage) return primaryStage;
            }
            const executionId = String(run.current_stage_execution_id || '').trim();
            if (executionId && stageById.has(executionId)) {
                return stageById.get(executionId);
            }
            const currentStageKey = String(run.current_stage_key || '').trim();
            if (currentStageKey) {
                const matchingAttempts = stageRows.filter((item) => String(item.stage_key || '') === currentStageKey);
                if (matchingAttempts.length) return latestStageExecution(matchingAttempts);
            }
            return latestStageExecution(stageRows);
        };

        const durationLabel = (ms) => {
            const seconds = Math.max(0, Math.round(Number(ms || 0) / 1000));
            if (seconds < 60) return `${seconds}s`;
            const minutes = Math.round(seconds / 60);
            if (minutes < 60) return `${minutes}m`;
            const hours = Math.floor(minutes / 60);
            const remainder = minutes % 60;
            return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
        };

        const runDurationMs = (run) => {
            const start = timestampMs(run?.created_at || run?.started_at);
            const end = timestampMs(run?.completed_at || run?.updated_at);
            return start && end && end >= start ? end - start : 0;
        };

        const averageCompletedRunDurationMs = () => {
            const protocolId = String(currentRun?.run?.protocol_id || '').trim();
            const samples = (runs || [])
                .filter((run) =>
                    String(run.protocol_id || '').trim() === protocolId
                    && String(run.status || '').trim().toLowerCase() === 'completed')
                .map(runDurationMs)
                .filter((value) => value > 0)
                .slice(0, 3);
            if (!samples.length) return 0;
            return samples.reduce((sum, value) => sum + value, 0) / samples.length;
        };

        const buildRunFocusHero = () => {
            const run = currentRun.run || {};
            const statusInfo = runStatusInfo(run);
            const status = statusInfo.status;
            const active = statusInfo.active;
            const currentStage = currentRunStageExecution();
            const currentStageOrdinal = currentStage ? stageOrdinalFor(currentStage.stage_key) : 0;
            const totalStages = runStageCount();
            const currentStageDef = currentStage
                ? stageDefinitionByKey.get(String(currentStage.stage_key || '')) || {}
                : {};
            const protocolLabel = String(
                currentRun.definition?.display_name
                || currentRun.definition?.slug
                || run.protocol_id
                || 'Protocol run',
            ).trim();
            const startMs = timestampMs(run.created_at || run.started_at || currentStage?.started_at);
            const elapsed = startMs ? durationLabel(Date.now() - startMs) : 'n/a';
            const hero = document.createElement('article');
            hero.className = `run-focus-hero run-focus-status-${status || 'queued'}`;

            const main = document.createElement('div');
            main.className = 'run-focus-main';
            const kicker = document.createElement('div');
            kicker.className = 'run-focus-kicker';
            kicker.textContent = statusInfo.kicker;
            main.appendChild(kicker);
            const title = document.createElement('h3');
            title.className = 'run-focus-title';
            title.textContent = protocolLabel;
            main.appendChild(title);
            const stage = document.createElement('div');
            stage.className = 'run-focus-stage';
            stage.textContent = currentStage
                ? `${currentStageDef.display_name || currentStage.stage_key || 'Stage'} · ${stageStatusLabel(currentStage)}`
                : statusInfo.detail || 'Waiting for the first stage';
            main.appendChild(stage);
            if (run.problem_statement) {
                const problem = document.createElement('p');
                problem.className = 'run-focus-problem';
                problem.textContent = _compactRunText(run.problem_statement, 220);
                main.appendChild(problem);
            }
            const parentRunId = String(run.parent_protocol_run_id || '').trim();
            const childRuns = (runs || [])
                .filter((item) => String(item.parent_protocol_run_id || '').trim() === String(run.protocol_run_id || '').trim())
                .slice(0, 4);
            if (parentRunId || childRuns.length) {
                const lineage = document.createElement('div');
                lineage.className = 'run-focus-lineage';
                if (parentRunId) {
                    const parent = document.createElement('a');
                    parent.href = _protocolRunHref(parentRunId);
                    parent.textContent = `Forked from ${parentRunId.slice(0, 8)}`;
                    lineage.appendChild(parent);
                    if (run.fork_mode) {
                        const mode = document.createElement('span');
                        mode.textContent = String(run.fork_mode || '').replace(/_/g, ' ');
                        lineage.appendChild(mode);
                    }
                }
                childRuns.forEach((child) => {
                    const childLink = document.createElement('a');
                    childLink.href = _protocolRunHref(child.protocol_run_id);
                    childLink.textContent = `Child ${String(child.protocol_run_id || '').slice(0, 8)}`;
                    lineage.appendChild(childLink);
                });
                main.appendChild(lineage);
            }
            hero.appendChild(main);

            const state = document.createElement('div');
            state.className = 'run-focus-state';

            const progressRail = Kit.runStageProgressRail({
                ..._runStageProgressData(currentRun),
                selectedStageExecutionId: activeRunStageExecutionId,
                selectedStageKey: String(currentStage?.stage_key || run.current_stage_key || ''),
                onStageSelect: selectRunStageEvidence,
            });
            progressRail.classList.add('run-focus-progress');
            state.appendChild(progressRail);

            const latestEvent = lastRunEvent && String(lastRunEvent.protocol_run_id || '') === String(run.protocol_run_id || '')
                ? lastRunEvent
                : null;
            const currentTask = taskForStage(currentStage);
            const currentTaskUpdate = taskUpdateText(currentTask, 260);
            const currentTaskTarget = taskTargetLabel(currentTask, currentStage?.routed_task_id || '');
            const currentTaskState = taskStateLabel(currentTask) || currentStage?.status || run.status || '';
            const currentTaskFreshness = taskUpdatedLabel(currentTask);
            const currentParticipant = participantByKey.get(String(currentStage?.participant_key || '')) || {};
            const currentStageStartedMs = timestampMs(currentStage?.started_at || currentStage?.updated_at);
            const currentStageAge = currentStageStartedMs ? durationLabel(Date.now() - currentStageStartedMs) : '';
            const taskProgressText = currentTaskUpdate
                ? [
                    currentTaskUpdate,
                    currentTaskTarget ? `Agent ${currentTaskTarget}` : '',
                    currentTaskState,
                    currentTaskFreshness,
                ].filter(Boolean).join(' · ')
                : '';
            const quietProgressText = currentStage
                ? [
                    `Stage ${currentStageOrdinal || 1}${totalStages ? ` / ${totalStages}` : ''}`,
                    currentStageDef.display_name || currentStage.stage_key || 'Current stage',
                    currentStage.status || run.status || 'running',
                    currentTaskTarget ? `agent ${currentTaskTarget}` : '',
                    currentParticipant.display_name ? `participant ${currentParticipant.display_name}` : '',
                    currentStageAge ? `active ${currentStageAge}` : '',
                ].filter(Boolean).join(' · ')
                : 'Waiting for the first stage to dispatch.';
            const live = document.createElement('div');
            live.className = `run-focus-live${active ? ' is-live' : ''}${active && !latestEvent && !currentTaskUpdate ? ' is-quiet' : ''}`;
            const liveLabel = document.createElement('strong');
            liveLabel.textContent = currentTaskUpdate ? 'Agent update' : (active ? 'Live update' : status === 'blocked' ? 'What is needed' : 'Latest update');
            live.appendChild(liveLabel);
            const liveCopy = document.createElement('span');
            liveCopy.textContent = taskProgressText
                || (latestEvent
                ? _protocolEventText(latestEvent)
                : active
                    ? quietProgressText
                    : statusInfo.detail || run.termination_summary || 'Run is no longer active.');
            live.appendChild(liveCopy);
            state.appendChild(live);

            const metrics = document.createElement('div');
            metrics.className = 'run-focus-metrics';
            [
                { label: 'Status', value: statusInfo.label },
                { label: 'Stage', value: totalStages ? `${currentStageOrdinal || 1} / ${totalStages}` : 'n/a' },
                { label: 'Outputs', value: `${artifactRows.length}${pendingArtifactRows.length ? ` / ${artifactRows.length + pendingArtifactRows.length}` : ''}` },
                { label: 'Issues', value: String(currentIssues.length) },
                { label: 'Elapsed', value: elapsed },
            ].forEach((item) => {
                const metric = document.createElement('span');
                metric.className = 'run-focus-metric';
                const value = document.createElement('strong');
                value.textContent = item.value;
                metric.appendChild(value);
                const label = document.createElement('small');
                label.textContent = item.label;
                metric.appendChild(label);
                metrics.appendChild(metric);
            });
            state.appendChild(metrics);
            hero.appendChild(state);

            const lower = document.createElement('div');
            lower.className = 'run-focus-lower';
            const actions = document.createElement('div');
            actions.className = 'run-focus-actions';
            const actionSpecs = _runActionSpecs().filter((spec) => spec.visible !== false);
            const actionTitle = document.createElement('div');
            actionTitle.className = 'detail-label';
            actionTitle.textContent = actionSpecs.length ? 'Operator controls' : 'Run actions';
            actions.appendChild(actionTitle);
            if (actionSpecs.some((spec) => spec.intervention)) {
                const actionNote = document.createElement('p');
                actionNote.className = 'quiet-note run-focus-action-note';
                actionNote.textContent = 'These controls can intervene in the current stage; use them only when the displayed stage evidence is enough to make that decision.';
                actions.appendChild(actionNote);
            }
            actions.appendChild(_buildRunActionBar({ specs: actionSpecs }));
            const lifecycleSpecs = _runLifecycleSpecs().filter((spec) => spec.visible !== false);
            if (lifecycleSpecs.length) {
                const lifecycleTitle = document.createElement('div');
                lifecycleTitle.className = 'detail-label';
                lifecycleTitle.textContent = 'Lifecycle';
                actions.appendChild(lifecycleTitle);
                const row = document.createElement('div');
                row.className = 'editor-actions';
                lifecycleSpecs.forEach((item) => {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = item.danger ? 'btn btn-danger' : 'btn';
                    button.textContent = item.label;
                    button.disabled = !item.enabled;
                    button.addEventListener('click', () => _openRunLifecycleDialog(item));
                    row.appendChild(button);
                });
                actions.appendChild(row);
            }
            lower.appendChild(actions);
            if (actions.childElementCount) {
                hero.appendChild(lower);
            }

            return hero;
        };

        const buildRunLivenessCard = () => {
            const run = currentRun.run || {};
            const statusInfo = runStatusInfo(run);
            const status = statusInfo.status;
            const active = statusInfo.active;
            const currentStage = currentRunStageExecution();
            const currentStageOrdinal = currentStage ? stageOrdinalFor(currentStage.stage_key) : 0;
            const currentStageDef = currentStage
                ? stageDefinitionByKey.get(String(currentStage.stage_key || '')) || {}
                : {};
            const currentTask = taskForStage(currentStage);
            const currentTaskUpdate = taskUpdateText(currentTask, 240);
            const currentTaskTarget = taskTargetLabel(currentTask, currentStage?.routed_task_id || '');
            const startMs = timestampMs(run.created_at || currentStage?.started_at);
            const elapsed = startMs ? durationLabel(Date.now() - startMs) : '';
            const averageMs = averageCompletedRunDurationMs();
            const card = document.createElement('article');
            card.className = 'protocol-lineage-card';
            card.dataset.key = 'run-liveness';

            const label = active && currentStage
                ? `Running stage ${currentStageOrdinal || 1} of ${runStageCount() || 1}: ${currentStageDef.display_name || currentStage.stage_key || 'Stage'}`
                : statusInfo.label;
            card.appendChild(UI.renderListRow({
                label,
                sublabel: [
                    active ? 'Work is being dispatched through the protocol runtime' : statusInfo.detail || run.termination_summary || 'Execution is no longer active',
                    elapsed ? `elapsed ${elapsed}` : '',
                    averageMs ? `typical completed run ${durationLabel(averageMs)}` : 'estimate available after completed run history',
                ].filter(Boolean).join(' · '),
                    badgeText: active ? 'live' : (statusInfo.label || run.status || ''),
                badgeClass: active ? 'badge-running' : '',
            }));
            card.appendChild(UI.renderMetadataGrid([
                { label: 'Current stage', value: currentStage ? (currentStageDef.display_name || currentStage.stage_key || 'Stage') : '—' },
                { label: 'Stage state', value: currentStage ? stageStatusLabel(currentStage) : statusInfo.label || '—' },
                { label: 'Assigned to', value: currentTaskTarget || '—' },
                { label: 'Task state', value: taskStateLabel(currentTask) || '—' },
                { label: 'Available outputs', value: String(artifactRows.length) },
                { label: 'Missing declared outputs', value: String(pendingArtifactRows.length) },
            ], { compact: true }));
            if (currentTaskUpdate) {
                card.appendChild(UI.renderListRow({
                    label: 'Latest agent update',
                    sublabel: [
                        currentTaskUpdate,
                        currentTaskTarget ? `Assigned to ${currentTaskTarget}` : '',
                        taskUpdatedLabel(currentTask),
                    ].filter(Boolean).join(' · '),
                    badgeText: taskStateLabel(currentTask) || currentStage?.status || '',
                }));
            }
            if (stageRows.length > stageAttemptsByKey.size) {
                card.appendChild(UI.renderListRow({
                    label: 'Loop/attempt history',
                    sublabel: `${stageRows.length} stage executions across ${stageAttemptsByKey.size} declared stages. Review loops and send-backs are listed chronologically below.`,
                    badgeText: 'attempts',
                }));
            }
            if (lastRunEvent && String(lastRunEvent.protocol_run_id || '') === String(run.protocol_run_id || '')) {
                card.appendChild(UI.renderListRow({
                    label: `Latest event: ${_protocolEventKindLabel(lastRunEvent.event_kind)}`,
                    sublabel: _protocolEventText(lastRunEvent) || 'Live event received from the registry.',
                    badgeText: 'event',
                }));
            } else if (active) {
                card.appendChild(UI.renderListRow({
                    label: 'Watching current stage',
                    sublabel: currentStage
                        ? `${currentStageDef.display_name || currentStage.stage_key || 'Current stage'} is ${currentStage.status || run.status || 'running'}. Refreshes arrive as agents create tasks, decisions, and artifacts.`
                        : 'The registry refreshes this run as the first stage is dispatched.',
                    badgeText: 'watching',
                }));
            }
            return card;
        };

        const buildStageEvidenceCard = (item, index) => {
            const stageDef = stageDefinitionByKey.get(String(item.stage_key || '')) || {};
            const task = taskById.get(String(item.routed_task_id || '')) || null;
            const producedArtifacts = artifactsByProducer.get(String(item.protocol_stage_execution_id || '')) || [];
            const participant = participantByKey.get(String(item.participant_key || '')) || {};
            const stageTransitions = transitionsForStage(item.protocol_stage_execution_id);
            const stageIssues = issuesByStageKey.get(String(item.stage_key || '')) || [];
            const previousAttempt = isPreviousStageAttempt(item);
            const taskTarget = taskTargetLabel(task, item.routed_task_id || '');
            const taskState = taskStateLabel(task);
            const taskUpdate = taskUpdateText(task, 260);
            const taskFreshness = taskUpdatedLabel(task);

            const card = document.createElement('article');
            card.className = 'protocol-lineage-card';
            if (previousAttempt) {
                card.classList.add('is-previous-attempt');
            }
            card.dataset.stageKey = String(item.stage_key || '');

            const head = document.createElement('div');
            head.className = 'protocol-lineage-head';
            const titleWrap = document.createElement('div');
            titleWrap.className = 'protocol-lineage-copy';
            const label = document.createElement('strong');
            label.className = 'protocol-lineage-title';
            label.textContent = `${index + 1}. ${stageDef.display_name || item.stage_key || 'Stage'} · ${stageStatusLabel(item)}`;
            titleWrap.appendChild(label);
            const subtitle = document.createElement('div');
            subtitle.className = 'protocol-lineage-subtitle';
            subtitle.textContent = [
                participant.display_name || item.participant_key || '',
                taskTarget,
                taskState ? `Task ${taskState}` : '',
                item.decision_summary || item.failure_detail || '',
            ].filter(Boolean).join(' · ');
            titleWrap.appendChild(subtitle);
            head.appendChild(titleWrap);
            if (item.decision) {
                const badge = document.createElement('span');
                badge.className = 'badge badge-connected';
                badge.textContent = item.decision;
                head.appendChild(badge);
            }
            if (previousAttempt) {
                const badge = document.createElement('span');
                badge.className = 'badge';
                badge.textContent = 'previous attempt';
                head.appendChild(badge);
            }
            card.appendChild(head);

            if (stageIssues.length) {
                const issueList = document.createElement('div');
                issueList.className = 'run-evidence-issue-list';
                UI.reconcileChildren(issueList, stageIssues.map((issue) => UI.renderListRow({
                    label: `${_protocolIssueLabel(issue.issue_kind)} · ${issue.issue_code || 'issue'}`,
                    sublabel: issue.issue_detail || issue.updated_at || '',
                    badgeText: issue.stage_key || '',
                    badgeClass: 'badge-blocked',
                })));
                card.appendChild(issueList);
            }

            const note = document.createElement('div');
            note.className = 'protocol-lineage-note';
            note.textContent = [
                stageAttemptLabel(item),
                previousAttempt ? 'Superseded by a newer attempt' : '',
                taskFreshness,
                item.completed_at
                    ? `Completed ${UI.relativeTime(item.completed_at)}`
                    : item.started_at
                        ? `Started ${UI.relativeTime(item.started_at)}`
                        : '',
                producedArtifacts.length
                    ? `${producedArtifacts.length} output${producedArtifacts.length === 1 ? '' : 's'}`
                    : '',
            ].filter(Boolean).join(' · ');
            card.appendChild(note);

            if (taskUpdate) {
                card.appendChild(UI.renderListRow({
                    label: 'Latest agent update',
                    sublabel: [
                        taskUpdate,
                        taskTarget ? `Assigned to ${taskTarget}` : '',
                        taskFreshness,
                    ].filter(Boolean).join(' · '),
                    badgeText: taskState || item.status || '',
                }));
            }

            const facts = UI.renderMetadataGrid([
                { label: 'Task', value: item.routed_task_id || '—' },
                { label: 'Attempt', value: String(item.attempt || 1) },
                { label: 'Assigned to', value: taskTarget || '—' },
                { label: 'Task state', value: taskState || '—' },
                { label: 'Started', value: item.started_at ? UI.relativeTime(item.started_at) : '—' },
                { label: 'Completed', value: item.completed_at ? UI.relativeTime(item.completed_at) : '—' },
            ], { compact: true });
            card.appendChild(facts);

            if (producedArtifacts.length) {
                const outputsLabel = document.createElement('div');
                outputsLabel.className = 'detail-label';
                outputsLabel.textContent = 'Outputs';
                card.appendChild(outputsLabel);
                card.appendChild(createArtifactList(producedArtifacts, {
                    relationshipFor: (artifact) => {
                        if (!previousAttempt) return 'Produced by this stage';
                        return artifact?.exists === false
                            ? 'Missing output from previous attempt'
                            : 'Output from previous attempt';
                    },
                }));
            }

            if (stageTransitions.length) {
                const decisionsLabel = document.createElement('div');
                decisionsLabel.className = 'detail-label';
                decisionsLabel.textContent = 'Decisions';
                card.appendChild(decisionsLabel);
                const decisionList = document.createElement('div');
                const decisionRows = stageTransitions.slice(0, 3).map((transition) => UI.renderListRow({
                    label: transitionLabelForStage(transition, item.protocol_stage_execution_id),
                    sublabel: transitionSummaryForStage(transition, item.protocol_stage_execution_id),
                    badgeText: String(transition.metadata_json?.target_agent_id || ''),
                }));
                UI.reconcileChildren(decisionList, decisionRows);
                card.appendChild(decisionList);
            }

            const actions = document.createElement('div');
            actions.className = 'task-action-row';
            if (item.routed_task_id) {
                const openTask = document.createElement('a');
                openTask.href = _protocolRunTaskHref(currentRun.run.protocol_run_id, item.routed_task_id);
                openTask.className = 'btn btn-sm';
                openTask.textContent = 'Open task';
                actions.appendChild(openTask);
            }
            if (task?.parent_conversation_id) {
                const openConversation = document.createElement('a');
                openConversation.href = UI.conversationHref(task.parent_conversation_id, { operational: true });
                openConversation.className = 'btn btn-sm';
                openConversation.textContent = 'Open activity';
                actions.appendChild(openConversation);
            }
            const rerunFork = document.createElement('button');
            rerunFork.type = 'button';
            rerunFork.className = 'btn btn-sm';
            rerunFork.textContent = 'Rerun from here';
            rerunFork.addEventListener('click', () => _openForkRunDialog(item, 'rerun_selected'));
            actions.appendChild(rerunFork);
            const continueFork = document.createElement('button');
            continueFork.type = 'button';
            continueFork.className = 'btn btn-sm';
            continueFork.textContent = 'Continue after';
            continueFork.addEventListener('click', () => _openForkRunDialog(item, 'continue_after'));
            actions.appendChild(continueFork);
            if (actions.childElementCount) {
                card.appendChild(actions);
            }

            return card;
        };

        const buildOverviewSection = () => {
            const section = document.createElement('div');
            section.className = 'studio-stack';
            appendSectionTitle(section, 'Overview', 'The run story starts with state, active issue, current stage, and produced outputs.');
            section.appendChild(buildRunLivenessCard());
            if (currentIssues.length) {
                const issueSummary = document.createElement('div');
                issueSummary.className = 'run-evidence-issue-list';
                UI.reconcileChildren(issueSummary, currentIssues.slice(0, 3).map((issue) => UI.renderListRow({
                    label: `${_protocolIssueLabel(issue.issue_kind)} · ${issue.issue_code || issue.stage_key || 'issue'}`,
                    sublabel: issue.issue_detail || issue.updated_at || '',
                    badgeText: issue.stage_key || '',
                    badgeClass: 'badge-blocked',
                })));
                section.appendChild(issueSummary);
            }
            const currentStage = currentRunStageExecution();
            if (currentStage) {
                const currentStageIndex = Math.max(stageRows.indexOf(currentStage), 0);
                const currentStageDef = stageDefinitionByKey.get(String(currentStage.stage_key || '')) || {};
                const currentTask = taskForStage(currentStage);
                const currentTaskUpdate = taskUpdateText(currentTask, 180);
                section.appendChild(UI.renderListRow({
                    label: `Current step: ${currentStageDef.display_name || currentStage.stage_key || 'Stage'}`,
                    sublabel: [
                        String(currentStage.status || ''),
                        currentTaskUpdate ? `Latest agent update: ${currentTaskUpdate}` : '',
                        currentStage.decision_summary || currentStage.failure_detail || '',
                        'Open Stages for task, decision, and output evidence',
                    ].filter(Boolean).join(' · '),
                    badgeText: currentStage.decision || currentStage.status || '',
                    onClick: () => {
                        activeRunDetailSection = 'stages';
                        activeRunStageFollowsCurrent = true;
                        activeRunStageExecutionId = String(
                            currentStage.protocol_stage_execution_id
                            || currentStage.stage_key
                            || `stage-${currentStageIndex}`,
                        );
                        renderRunsRoute();
                    },
                }));
            }
            if (artifactRows.length || pendingArtifactRows.length) {
                section.appendChild(UI.renderListRow({
                    label: `${artifactRows.length} output${artifactRows.length === 1 ? '' : 's'} available`,
                    sublabel: pendingArtifactRows.length
                        ? `${pendingArtifactRows.length} declared output${pendingArtifactRows.length === 1 ? '' : 's'} not produced yet`
                        : 'Open Artifacts for preview, download, and path actions',
                    badgeText: pendingArtifactRows.length ? 'partial' : 'available',
                    badgeClass: pendingArtifactRows.length ? 'badge-blocked' : 'badge-connected',
                    onClick: () => {
                        activeRunDetailSection = 'artifacts';
                        activeRunArtifactStageExecutionId = '';
                        renderRunsRoute();
                    },
                }));
            }
            const autoMeta = currentRun.version?.definition_json?.metadata?.auto_protocol || {};
            const contract = autoMeta.acceptance_contract || {};
            if (Number(contract.schema_version || 0) >= 2 || autoMeta.contract_required) {
                const contractKey = String(contract.contract_artifact_key || 'auto_protocol_contract').trim();
                const producerManifestKey = String(contract.producer_manifest_artifact_key || 'producer_evidence_manifest').trim();
                const reviewerManifestKey = String(contract.reviewer_manifest_artifact_key || 'reviewer_evidence_manifest').trim();
                const findArtifact = (key) => artifactRows.find((item) => String(item.artifact_key || '').trim() === key) || null;
                const missingEvidence = _missingEvidenceList(currentRun);
                const contractBox = document.createElement('div');
                contractBox.className = 'run-evidence-issue-list';
                contractBox.appendChild(UI.renderListRow({
                    label: 'Auto Protocol product/system contract',
                    sublabel: [
                        String(autoMeta.product_class || contract.product_class || '').trim() ? `Product class: ${autoMeta.product_class || contract.product_class}` : '',
                        contract.contract_required || autoMeta.contract_required ? 'Full contract mode' : 'Contract metadata present',
                    ].filter(Boolean).join(' · '),
                    badgeText: 'v2',
                    badgeClass: 'badge-connected',
                }));
                [
                    [contractKey, 'Authoritative contract'],
                    [producerManifestKey, 'Producer evidence manifest'],
                    [reviewerManifestKey, 'Reviewer evidence manifest'],
                ].forEach(([key, label]) => {
                    const artifact = findArtifact(key);
                    contractBox.appendChild(UI.renderListRow({
                        label,
                        sublabel: artifact
                            ? [_protocolArtifactLabel(artifact), _protocolArtifactDisplayPath(artifact)].filter(Boolean).join(' · ')
                            : `Missing artifact ${key}`,
                        badgeText: artifact ? 'available' : 'missing',
                        badgeClass: artifact ? 'badge-connected' : 'badge-blocked',
                    }));
                });
                if (missingEvidence.length) {
                    contractBox.appendChild(UI.renderListRow({
                        label: `${missingEvidence.length} evidence item${missingEvidence.length === 1 ? '' : 's'} still required`,
                        sublabel: missingEvidence.slice(0, 4).join(' · '),
                        badgeText: 'blocked',
                        badgeClass: 'badge-blocked',
                    }));
                }
                section.appendChild(contractBox);
            }
            return section;
        };

        const artifactStageFor = (artifact) => {
            const executionId = String(artifact?.produced_by_stage_execution_id || '').trim();
            return executionId ? stageById.get(executionId) || null : null;
        };

        const inferPrimaryArtifact = () => {
            const metadata = currentRun.version?.definition_json?.metadata || {};
            const autoMeta = metadata.auto_protocol || {};
            const explicitPrimary = autoMeta.primary_artifact || {};
            const explicitKey = String(explicitPrimary.artifact_key || autoMeta.primary_artifact_key || '').trim();
            const allArtifacts = [...artifactRows, ...pendingArtifactRows]
                .filter((item) => String(item?.artifact_key || '').trim());
            if (explicitKey) {
                const explicitArtifact = allArtifacts.find((item) => String(item.artifact_key || '').trim() === explicitKey)
                    || { artifact_key: explicitKey, exists: false };
                return {
                    artifact: explicitArtifact,
                    definition: artifactDefinitionByKey.get(explicitKey) || {},
                    primary: explicitPrimary,
                    inferred: false,
                    key: explicitKey,
                };
            }
            if (!allArtifacts.length) return null;
            const evidenceLike = /(^|[_-])(review|audit|evidence|logs?)([_-]|$)/i;
            const scored = allArtifacts.map((artifact, index) => {
                const key = String(artifact.artifact_key || '').trim();
                const definition = artifactDefinitionByKey.get(key) || {};
                const pathLabel = _protocolArtifactDisplayPath(artifact) || _artifactDefinitionPath(definition || artifact);
                const stage = artifactStageFor(artifact);
                const stageKey = String(stage?.stage_key || '').trim();
                const verified = String(artifact.verification_state || artifact.state || '').trim().toLowerCase() === 'verified';
                let score = 0;
                if (artifact.exists !== false) score += 50;
                if (UI.isLikelyDirectoryArtifactPath(pathLabel)) score += 40;
                if (_protocolArtifactPreviewable(artifact)) score += 20;
                if (verified) score += 10;
                if (!evidenceLike.test(key)) score += 12;
                if (stageKey && !evidenceLike.test(stageKey)) score += 8;
                if (Number(artifact.size_bytes || 0) > 0) score += Math.min(10, Math.log10(Number(artifact.size_bytes || 1)));
                return { artifact, definition, key, score, index };
            }).sort((left, right) => {
                if (right.score !== left.score) return right.score - left.score;
                return left.index - right.index;
            });
            const selected = scored[0] || null;
            if (!selected) return null;
            return {
                artifact: selected.artifact,
                definition: selected.definition,
                primary: {
                    artifact_key: selected.key,
                    display_name: selected.definition.display_name || _protocolArtifactDisplayLabel(selected.artifact, selected.definition),
                    produced_by_stage_key: artifactStageFor(selected.artifact)?.stage_key || '',
                    expected_path: _artifactDefinitionPath(selected.definition || selected.artifact),
                },
                inferred: true,
                key: selected.key,
            };
        };

        const buildPrimaryArtifactPanel = ({ includeRunControls = false } = {}) => {
            const inferred = inferPrimaryArtifact();
            if (!inferred) return null;
            const { artifact, definition, primary, key } = inferred;
            const producerStage = artifactStageFor(artifact);
            const producerStageDef = producerStage
                ? stageDefinitionByKey.get(String(producerStage.stage_key || '')) || {}
                : {};
            const producerTask = taskForStage(producerStage);
            const producerUpdate = taskUpdateText(producerTask, 260)
                || producerStage?.decision_summary
                || producerStage?.failure_detail
                || '';
            const finalStageCandidates = stageRows.filter((item) => {
                const stageKey = String(item?.stage_key || '').trim();
                const stageDef = stageDefinitionByKey.get(stageKey) || {};
                const label = `${stageKey} ${String(stageDef.display_name || '')}`.toLowerCase();
                return /(accept|final|release|evidence)/i.test(label);
            });
            const finalStage = latestStageExecution(finalStageCandidates) || latestStageExecution(stageRows);
            const finalStageDef = finalStage
                ? stageDefinitionByKey.get(String(finalStage.stage_key || '')) || {}
                : {};
            const finalTask = taskForStage(finalStage);
            const finalUpdate = finalStage?.decision_summary
                || taskUpdateText(finalTask, 320)
                || finalStage?.failure_detail
                || '';
            const totalExecutions = stageRows.length;
            const totalStages = stageAttemptsByKey.size || runStageCount();
            const panel = document.createElement('article');
            panel.className = 'run-primary-artifact-panel';
            const head = document.createElement('div');
            head.className = 'run-primary-artifact-head';
            const title = document.createElement('div');
            title.className = 'editor-section-title';
            title.textContent = `Primary outcome: ${String(primary.display_name || definition.display_name || key)}`;
            head.appendChild(title);
            const badge = document.createElement('span');
            badge.className = artifact.exists ? 'badge-connected' : 'badge-blocked';
            badge.textContent = artifact.exists ? 'available' : 'not produced yet';
            head.appendChild(badge);
            panel.appendChild(head);
            const note = document.createElement('p');
            note.className = 'quiet-note';
            note.textContent = inferred.inferred
                ? 'Promoted from produced artifacts because this run did not declare a primary outcome.'
                : 'This is the protocol-declared main outcome for the run.';
            panel.appendChild(note);
            const runtimeExpected = primaryRuntimeExpected(artifact, definition, primary);
            const evidence = artifactRows.find((item) => String(item.artifact_key || '').trim() === 'release_evidence') || null;
            const evidenceRequirements = Array.isArray(primary.evidence_requirements)
                ? primary.evidence_requirements.map((item) => String(item || '').trim()).filter(Boolean)
                : [];
            const readiness = document.createElement('div');
            readiness.className = 'run-primary-story-list run-primary-readiness-list';
            readiness.appendChild(UI.renderListRow({
                label: inferred.inferred ? 'Primary outcome inferred' : 'Primary outcome declared',
                sublabel: inferred.inferred
                    ? 'Registry selected the strongest produced package because this run did not name a primary outcome; use review evidence before treating it as ready.'
                    : 'The protocol identified this artifact as the user-facing deliverable.',
                badgeText: inferred.inferred ? 'inferred' : 'declared',
                badgeClass: inferred.inferred ? 'badge-degraded' : 'badge-connected',
            }));
            readiness.appendChild(UI.renderListRow({
                label: evidence ? 'Release evidence available' : 'Release evidence missing',
                sublabel: evidence
                    ? 'Open the evidence artifact to see what the reviewer inspected, accepted, revised, or left risky.'
                    : 'No release evidence artifact is available for the UI to summarize.',
                badgeText: evidence ? 'evidence' : 'missing',
                badgeClass: evidence ? 'badge-connected' : 'badge-blocked',
            }));
            if (runtimeExpected) {
                readiness.appendChild(UI.renderListRow({
                    label: 'Runtime launch is not acceptance',
                    sublabel: 'Start app and Open app expose the Registry-managed runtime; final readiness still comes from the review evidence and run state.',
                    badgeText: 'runtime',
                }));
            }
            if (evidenceRequirements.length) {
                readiness.appendChild(UI.renderListRow({
                    label: `${evidenceRequirements.length} required evidence check${evidenceRequirements.length === 1 ? '' : 's'}`,
                    sublabel: evidenceRequirements.slice(0, 3).join(' · '),
                    badgeText: 'quality bar',
                }));
            }
            panel.appendChild(readiness);
            if (runtimeExpected && String(currentRun.run?.blocked_code || '').trim().toLowerCase().startsWith('runtime_')) {
                panel.appendChild(UI.renderListRow({
                    label: 'Runtime verification required',
                    sublabel: currentRun.run?.blocked_detail || 'Start and exercise the primary artifact through the Registry, then accept the final stage.',
                    badgeText: 'verify',
                    badgeClass: 'badge-blocked',
                }));
            }
            const actions = _protocolArtifactActionRow(
                currentRun.run.protocol_run_id,
                artifact,
                definition,
                {
                    missing: !artifact.exists,
                    runtimeExpected,
                    prominentRuntime: true,
                },
            );
            actions.classList.add('run-primary-actions');
            panel.appendChild(actions);

            const story = document.createElement('div');
            story.className = 'run-primary-story-list';
            if (producerStage) {
                story.appendChild(UI.renderListRow({
                    label: `Built by ${producerStageDef.display_name || producerStage.stage_key || 'producer stage'}`,
                    sublabel: [
                        producerUpdate,
                        stageAttemptLabel(producerStage),
                        producerStage.completed_at ? `completed ${UI.relativeTime(producerStage.completed_at)}` : '',
                    ].filter(Boolean).join(' · '),
                    badgeText: stageStatusLabel(producerStage),
                    badgeClass: String(producerStage.status || '').toLowerCase() === 'completed' ? 'badge-connected' : '',
                }));
            }
            if (finalStage && finalStage !== producerStage) {
                story.appendChild(UI.renderListRow({
                    label: `Verified by ${finalStageDef.display_name || finalStage.stage_key || 'final review'}`,
                    sublabel: [
                        finalUpdate,
                        stageAttemptLabel(finalStage),
                        finalStage.completed_at ? `completed ${UI.relativeTime(finalStage.completed_at)}` : '',
                    ].filter(Boolean).join(' · '),
                    badgeText: stageStatusLabel(finalStage),
                    badgeClass: String(finalStage.status || '').toLowerCase() === 'completed' ? 'badge-connected' : '',
                }));
            }
            if (totalExecutions || totalStages) {
                story.appendChild(UI.renderListRow({
                    label: 'Execution history',
                    sublabel: `${totalExecutions || totalStages} execution${(totalExecutions || totalStages) === 1 ? '' : 's'} across ${totalStages || totalExecutions} stage${(totalStages || totalExecutions) === 1 ? '' : 's'}. Full handoff and review history is below.`,
                    badgeText: stageRows.length > stageAttemptsByKey.size ? 'loops' : 'history',
                }));
            }
            if (story.childElementCount) {
                panel.appendChild(story);
            }
            const packageSummary = document.createElement('div');
            packageSummary.className = 'run-primary-package-summary';
            const packageLabel = document.createElement('strong');
            packageLabel.textContent = 'Package';
            packageSummary.appendChild(packageLabel);
            const packageCopy = document.createElement('span');
            const observedPath = _protocolArtifactDisplayPath(artifact);
            const expectedPath = primary.expected_path || _artifactDefinitionPath(definition);
            const packagePath = observedPath || expectedPath || '';
            const packageName = packagePath
                ? String(packagePath).split('/').filter(Boolean).slice(-1)[0] || packagePath
                : key;
            packageCopy.textContent = [
                key,
                artifact.verification_state || artifact.state || '',
                packageName ? `workspace folder ${packageName}` : '',
                evidence ? 'release evidence available' : '',
            ].filter(Boolean).join(' · ');
            packageSummary.appendChild(packageCopy);
            const moreDetails = document.createElement('details');
            moreDetails.className = 'run-primary-package-details';
            _bindRunDisclosure(moreDetails, 'evidence-paths');
            const moreDetailsSummary = document.createElement('summary');
            moreDetailsSummary.textContent = 'Evidence and paths';
            moreDetails.appendChild(moreDetailsSummary);
            if (evidence) {
                const evidenceRow = document.createElement('div');
                evidenceRow.className = 'run-primary-evidence-detail';
                const evidenceCopy = document.createElement('span');
                evidenceCopy.textContent = [
                    'Release evidence',
                    evidence.verification_state || evidence.state || '',
                    _compactRunText(_protocolArtifactDisplayPath(evidence) || '', 96),
                ].filter(Boolean).join(' · ');
                evidenceRow.appendChild(evidenceCopy);
                const evidenceActions = document.createElement('div');
                evidenceActions.className = 'run-primary-compact-actions';
                const evidenceOpen = document.createElement('a');
                evidenceOpen.href = API.protocolRunArtifactContentUrl(currentRun.run.protocol_run_id, evidence.artifact_key);
                evidenceOpen.className = 'btn btn-sm';
                evidenceOpen.textContent = 'Open evidence';
                evidenceActions.appendChild(evidenceOpen);
                const evidenceDownload = document.createElement('a');
                evidenceDownload.href = API.protocolRunArtifactContentUrl(currentRun.run.protocol_run_id, evidence.artifact_key, { download: true });
                evidenceDownload.className = 'btn btn-sm';
                evidenceDownload.textContent = 'Download evidence';
                evidenceActions.appendChild(evidenceDownload);
                evidenceRow.appendChild(evidenceActions);
                moreDetails.appendChild(evidenceRow);
            }
            moreDetails.appendChild(UI.renderMetadataGrid([
                { label: 'Artifact key', value: key },
                { label: 'Produced by', value: primary.produced_by_stage_key || 'produce_outcome' },
                { label: 'Expected path', value: expectedPath || '-' },
                { label: 'Observed path', value: observedPath || '-' },
                { label: 'Verification', value: artifact.verification_state || artifact.state || '-' },
            ], { compact: true }));
            packageSummary.appendChild(moreDetails);
            panel.appendChild(packageSummary);
            if (includeRunControls) {
                const controls = document.createElement('div');
                controls.className = 'run-primary-control-bar';
                const actionSpecs = _runActionSpecs().filter((spec) => spec.visible !== false);
                controls.appendChild(_buildRunActionBar({ specs: actionSpecs }));
                const lifecycleSpecs = _runLifecycleSpecs().filter((spec) => spec.visible !== false);
                if (lifecycleSpecs.length) {
                    const moreOptions = document.createElement('details');
                    moreOptions.className = 'run-primary-more-options';
                    _bindRunDisclosure(moreOptions, 'more-run-options');
                    const moreOptionsSummary = document.createElement('summary');
                    moreOptionsSummary.textContent = 'More run options';
                    moreOptions.appendChild(moreOptionsSummary);
                    const row = document.createElement('div');
                    row.className = 'editor-actions';
                    lifecycleSpecs.forEach((item) => {
                        const button = document.createElement('button');
                        button.type = 'button';
                        button.className = item.danger ? 'btn btn-danger' : 'btn';
                        button.textContent = item.label;
                        button.disabled = !item.enabled;
                        button.addEventListener('click', () => _openRunLifecycleDialog(item));
                        row.appendChild(button);
                    });
                    moreOptions.appendChild(row);
                    controls.appendChild(moreOptions);
                }
                if (controls.childElementCount) {
                    panel.appendChild(controls);
                }
            }
            return panel;
        };

        const normalizedRunStatus = String(currentRun.run?.status || '').trim().toLowerCase();
        const primaryOwnsRunStory = !['queued', 'running'].includes(normalizedRunStatus);
        const primaryArtifactPanel = buildPrimaryArtifactPanel({ includeRunControls: primaryOwnsRunStory });
        if (primaryArtifactPanel) {
            detailPanel.appendChild(primaryArtifactPanel);
        }
        if (!primaryArtifactPanel || !primaryOwnsRunStory) {
            detailPanel.appendChild(buildRunFocusHero());
        }

        const stagePanel = document.createElement('div');
        stagePanel.className = 'run-stage-timeline';
        appendSectionTitle(stagePanel, 'Stages', 'Click a stage to see the work, outputs, and decisions for that step.');
        if (stageRows.length > stageAttemptsByKey.size) {
            const attemptNote = document.createElement('p');
            attemptNote.className = 'quiet-note run-stage-attempt-note';
            attemptNote.textContent = `${stageRows.length} executions across ${stageAttemptsByKey.size} stages; repeated attempts are shown in handoff order.`;
            stagePanel.appendChild(attemptNote);
        }
        if (stageRows.length) {
            const stageValues = new Set(stageRows.map((item, index) => stageValueFor(item, index)));
            const preferredStage = currentRunStageExecution();
            const currentStageIndex = Math.max(stageRows.indexOf(preferredStage), 0);
            const currentStage = stageRows[currentStageIndex] || stageRows[0];
            const currentStageValue = currentStage ? stageValueFor(currentStage, currentStageIndex) : '';
            if (activeRunStageFollowsCurrent && currentStageValue) {
                activeRunStageExecutionId = currentStageValue;
            } else if (!stageValues.has(String(activeRunStageExecutionId || ''))) {
                activeRunStageExecutionId = currentStageValue || stageValueFor(stageRows[0], 0);
                activeRunStageFollowsCurrent = true;
            }
            const stageList = document.createElement('div');
            stageList.className = 'run-stage-timeline-list';
            stageRows.forEach((stageItem, index) => {
                const stageDef = stageDefinitionByKey.get(String(stageItem.stage_key || '')) || {};
                const value = stageValueFor(stageItem, index);
                const producedArtifacts = artifactsByProducer.get(String(stageItem.protocol_stage_execution_id || '')) || [];
                const selected = value === String(activeRunStageExecutionId || '');
                const normalizedStageStatus = String(stageItem.status || 'pending').trim().toLowerCase() || 'pending';
                const task = taskForStage(stageItem);
                const taskTarget = taskTargetLabel(task, stageItem.routed_task_id || '');
                const taskState = taskStateLabel(task);
                const taskUpdate = taskUpdateText(task, 150);
                const previousAttempt = isPreviousStageAttempt(stageItem);
                const activeTaskState = !['completed', 'failed', 'cancelled'].includes(String(task?.status || stageItem.status || '').trim().toLowerCase());
                const item = document.createElement('article');
                item.className = `run-stage-timeline-item is-${normalizedStageStatus}${selected ? ' is-expanded' : ''}`;
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'run-stage-timeline-button';
                button.setAttribute('aria-expanded', String(selected));
                button.addEventListener('click', () => {
                    activeRunDetailSection = 'stages';
                    activeRunStageExecutionId = value;
                    activeRunStageFollowsCurrent = value === currentStageValue;
                    UI.clearMemoizedRender(contentEl);
                    renderRunsRoute();
                });
                const marker = document.createElement('span');
                marker.className = 'run-stage-timeline-marker';
                marker.textContent = String(index + 1);
                button.appendChild(marker);
                const copy = document.createElement('span');
                copy.className = 'run-stage-timeline-copy';
                const label = document.createElement('strong');
                label.textContent = stageDef.display_name || stageItem.stage_key || 'Stage';
                copy.appendChild(label);
                const meta = document.createElement('small');
                meta.textContent = [
                    stageAttemptLabel(stageItem),
                    previousAttempt ? 'previous attempt' : '',
                    stageStatusLabel(stageItem),
                    taskState ? `task ${taskState}` : '',
                    taskTarget ? `Agent ${taskTarget}` : '',
                    activeTaskState ? taskUpdate : '',
                    producedArtifacts.length ? `${producedArtifacts.length} output${producedArtifacts.length === 1 ? '' : 's'}` : '',
                    stageItem.decision_summary || stageItem.failure_detail || '',
                ].filter(Boolean).join(' · ');
                copy.appendChild(meta);
                button.appendChild(copy);
                const badge = document.createElement('span');
                badge.className = `badge ${String(stageItem.status || '').toLowerCase() === 'completed' ? 'badge-connected' : ''}`;
                badge.textContent = stageItem.status || 'pending';
                button.appendChild(badge);
                item.appendChild(button);
                if (selected) {
                    item.appendChild(buildStageEvidenceCard(stageItem, index));
                }
                stageList.appendChild(item);
            });
            stagePanel.appendChild(stageList);
        } else {
            stagePanel.appendChild(UI.renderEmptyState('No stage executions recorded for this run yet.', true));
        }
        if (pendingArtifactRows.length) {
            appendSectionTitle(stagePanel, 'Declared but missing');
            stagePanel.appendChild(createArtifactList(pendingArtifactRows, {
                relationshipFor: () => 'Declared output not yet recorded',
                missing: true,
            }));
        }
        if (primaryArtifactPanel && primaryOwnsRunStory) {
            const stageHistory = document.createElement('details');
            stageHistory.className = 'run-stage-history-disclosure';
            _bindRunDisclosure(stageHistory, 'stage-history');
            const summary = document.createElement('summary');
            summary.textContent = `Stage history (${stageRows.length || stageAttemptsByKey.size})`;
            stageHistory.appendChild(summary);
            stageHistory.appendChild(stagePanel);
            detailPanel.appendChild(stageHistory);
        } else {
            detailPanel.appendChild(stagePanel);
        }

        const auditDetails = document.createElement('details');
        auditDetails.className = 'run-audit-disclosure';
        _bindRunDisclosure(auditDetails, 'audit');
        const auditSummary = document.createElement('summary');
        auditSummary.textContent = 'Audit and troubleshooting';
        auditDetails.appendChild(auditSummary);
        const sectionPanel = document.createElement('div');
        sectionPanel.className = 'studio-stack run-evidence-panel';
        appendSectionTitle(sectionPanel, 'Audit', 'Raw participants, decisions, and support issues remain available here without driving the default run story.');
        {
            const run = currentRun.run || {};
            appendSectionTitle(sectionPanel, 'Run inspector', 'Identifiers and runtime context are kept here for audit and troubleshooting.');
            sectionPanel.appendChild(UI.renderMetadataGrid([
                { label: 'Run id', value: run.protocol_run_id || '—' },
                { label: 'Protocol id', value: run.protocol_id || '—' },
                { label: 'Version', value: String(run.version || 1) },
                { label: 'Workspace', value: run.workspace_ref || 'default' },
                { label: 'Root conversation', value: run.root_conversation_id || '—' },
                { label: 'Origin', value: run.origin_channel || '—' },
                { label: 'Created', value: run.created_at ? UI.relativeTime(run.created_at) : '—' },
                { label: 'Updated', value: run.updated_at ? UI.relativeTime(run.updated_at) : '—' },
            ], { compact: true }));
            appendSectionTitle(sectionPanel, 'Launch context', 'Submitted launch text is included in stage prompts, but it does not rewrite the published stage or artifact contract.');
            sectionPanel.appendChild(_runLaunchContextList(run));
            const participantList = document.createElement('div');
            const participantRows = (currentRun.participants || []).map((item) => UI.renderListRow({
                label: `${item.display_name || item.participant_key} · ${item.resolution_outcome || item.state || 'queued'}`,
                sublabel: item.resolution_reason || item.resolved_agent_id || item.session_key || '',
                badgeText: item.resolution_outcome || '',
            }));
            appendSectionTitle(sectionPanel, 'Participants');
            UI.reconcileChildren(participantList, participantRows.length ? participantRows : [UI.renderEmptyState('No participants resolved yet.', true)]);
            sectionPanel.appendChild(participantList);

            const transitionList = document.createElement('div');
            transitionList.setAttribute('aria-live', 'polite');
            const transitionNodes = transitionRows.map((item) => UI.renderListRow({
                label: `${item.transition_kind} · ${item.decision || 'n/a'}`,
                sublabel: [item.reason || item.actor_ref || '', item.error_code || ''].filter(Boolean).join(' · '),
                badgeText: String(item.metadata_json?.target_agent_id || ''),
            }));
            appendSectionTitle(sectionPanel, 'Decision history');
            UI.reconcileChildren(transitionList, transitionNodes.length ? transitionNodes : [UI.renderEmptyState('No transitions recorded yet.', true)]);
            sectionPanel.appendChild(transitionList);

            const issueDetailList = document.createElement('div');
            const issueDetailRows = (currentIssues || []).map((item) => UI.renderListRow({
                label: `${_protocolIssueLabel(item.issue_kind)} · ${item.issue_code || item.stage_key || 'issue'}`,
                sublabel: item.issue_detail || item.updated_at || '',
                badgeText: item.stage_key || '',
            }));
            appendSectionTitle(sectionPanel, 'Support issues');
            UI.reconcileChildren(issueDetailList, issueDetailRows.length ? issueDetailRows : [UI.renderEmptyState('No protocol issues detected for this run.', true)]);
            sectionPanel.appendChild(issueDetailList);
            if ((currentIssues || []).length) {
                const issueFacts = document.createElement('div');
                issueFacts.className = 'run-evidence-issue-list';
                UI.reconcileChildren(issueFacts, (currentIssues || []).map((item) => {
                    const card = document.createElement('article');
                    card.className = 'protocol-lineage-card';
                    card.appendChild(UI.renderMetadataGrid([
                        { label: 'Issue', value: `${_protocolIssueLabel(item.issue_kind)} · ${item.issue_code || item.stage_key || 'issue'}` },
                        { label: 'Run state', value: item.run_status || '—' },
                        { label: 'Stage state', value: item.stage_status || '—' },
                        { label: 'Lease expiry', value: item.lease_expires_at || '—' },
                        { label: 'Timeout', value: item.timeout_at || '—' },
                        { label: 'Last issue update', value: item.updated_at ? `${item.updated_at} (${UI.relativeTime(item.updated_at)})` : '—' },
                    ], { compact: true }));
                    return card;
                }));
                sectionPanel.appendChild(issueFacts);
            }
        }
        auditDetails.appendChild(sectionPanel);
        detailPanel.appendChild(auditDetails);
        return detailPanel;
    }

    function renderRunsRoute() {
        UI.memoizedRender(contentEl, {
            runs,
            protocolIssues,
            currentRunId,
            currentRun,
            currentIssues,
            lastRunEvent,
            issueKindFilter,
            runViewFilter,
            runStatusFilter,
            runSearch,
            includeGenerated,
            activeRunDetailSection,
            activeRunStageExecutionId,
            activeRunStageFollowsCurrent,
            activeRunArtifactStageExecutionId,
        }, () => {
            const workbench = document.createElement('div');
            workbench.className = 'protocol-runs-workbench';
            workbench.dataset.hasSelection = currentRunId ? 'true' : 'false';
            workbench.dataset.issueMode = issueKindFilter ? 'true' : 'false';
            workbench.appendChild(_buildRunNavigatorPanel());
            return workbench;
        });
    }

    async function loadRuns() {
        const response = await API.listProtocolRuns({
            limit,
            cursor: runPaginator ? runPaginator.cursor : 0,
            status: runStatusFilter || (['completed', 'archived', 'deleted'].includes(runViewFilter) ? runViewFilter : ''),
            include_generated: includeGenerated ? '1' : '0',
        });
        runsListData = response || null;
        runs = response.runs || response || [];
        _queueSelectedRunDetailRefreshFromList();
        _writeState();
        renderRunsRoute();
    }

    async function loadIssues({ rerender = true } = {}) {
        const response = await API.listProtocolIssues({
            limit: 50,
            issue_kind: _protocolIssueApiValue(issueKindFilter),
        });
        protocolIssues = response.issues || response || [];
        if (rerender) {
            renderRunsRoute();
        }
    }

    async function loadRunDetail({ soft = false } = {}) {
        if (!currentRunId) {
            runDetailRequestToken += 1;
            currentRun = null;
            currentIssues = [];
            lastRunEvent = null;
            runDetailLoading = false;
            _writeState();
            _bindRunSubscription();
            _syncRunRefreshTimer();
            renderRunsRoute();
            return;
        }
        const requestedRunId = String(currentRunId || '');
        const requestToken = runDetailRequestToken + 1;
        runDetailRequestToken = requestToken;
        try {
            if (!soft || !currentRun) {
                runDetailLoading = true;
            }
            const [runDetail, issues] = await Promise.all([
                API.getProtocolRun(requestedRunId),
                API.listProtocolIssues({ protocol_run_id: requestedRunId, limit: 50 }),
            ]);
            if (requestToken !== runDetailRequestToken || requestedRunId !== String(currentRunId || '')) {
                return;
            }
            currentRun = runDetail;
            currentIssues = issues.issues || issues || [];
            runDetailLoading = false;
            _writeState();
            _bindRunSubscription();
            renderRunsRoute();
            _syncRunRefreshTimer();
        } catch (err) {
            if (requestToken !== runDetailRequestToken || requestedRunId !== String(currentRunId || '')) {
                return;
            }
            runDetailLoading = false;
            if (soft && currentRun) {
                UI.reportError('Failed to refresh the protocol run detail', err, {
                    context: 'Protocol run detail refresh failed',
                });
                _syncRunRefreshTimer();
                return;
            }
            throw err;
        }
    }

    async function bootstrap() {
        UI.reconcileChildren(contentEl, [UI.renderEmptyState('Loading protocol runs…', true)]);
        try {
            if (currentRunId) {
                runDetailLoading = true;
            }
            await Promise.all([loadRuns(), loadIssues({ rerender: false })]);
            if (currentRunId) {
                await loadRunDetail();
            } else {
                renderRunsRoute();
            }
        } catch (err) {
            UI.reconcileChildren(contentEl, [UI.createErrorCard('Failed to load protocol runs: ' + err.message, bootstrap)]);
        }
    }

    cleanups.add(() => {
        runsRouteDisposed = true;
        if (currentRunSubscription) {
            currentRunSubscription();
            currentRunSubscription = null;
        }
        clearTimeout(runRefreshTimer);
        runRefreshTimer = 0;
        currentRun = null;
        currentIssues = [];
        protocolIssues = [];
    });

    UI.subscribeWithRefresh(cleanups, 'summary', () => Promise.all([
        loadRuns(),
        loadIssues({ rerender: true }),
    ]), 400);
    UI.subscribeWithRefresh(cleanups, 'agents', () => Promise.all([
        loadRuns(),
        currentRunId ? loadRunDetail({ soft: true }) : Promise.resolve(),
    ]), 400);
    UI.subscribeWithRefresh(cleanups, 'tasks', () => Promise.all([
        loadRuns(),
        currentRunId ? loadRunDetail({ soft: true }) : Promise.resolve(),
    ]), 350);
    UI.subscribeWithRefresh(cleanups, 'protocols', () => Promise.all([
        loadRuns(),
        currentRunId ? loadRunDetail({ soft: true }) : Promise.resolve(),
    ]), 350);

    container.__routeReady = bootstrap();
}
