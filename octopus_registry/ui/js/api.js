/**
 * API client — fetch wrappers for /v1/ resource endpoints.
 * Auth via session cookie (set by /ui/login).
 * CSRF token fetched on load and sent on mutating requests.
 */
const API = (() => {
    let csrfToken = '';
    const REQUEST_TIMEOUT = 30000;

    function setCsrfToken(token) {
        csrfToken = token;
    }

    function _notify(message, error, context = '') {
        if (window.UI && typeof window.UI.reportError === 'function') {
            window.UI.reportError(message, error, { context });
            return;
        }
        console.warn(message, error);
    }

    /** Fetch CSRF token from the auth endpoint. */
    async function fetchCsrf({ silent = false } = {}) {
        try {
            const resp = await fetch('/v1/auth/csrf', { credentials: 'same-origin' });
            if (!resp.ok) {
                throw new Error(`HTTP ${resp.status}`);
            }
            const data = await resp.json();
            csrfToken = data.token || data.csrf_token || '';
            if (!csrfToken) {
                throw new Error('Token missing from response');
            }
            return csrfToken;
        } catch (e) {
            csrfToken = '';
            if (!silent) {
                _notify('Could not verify your session', e, 'Failed to fetch CSRF token');
            }
            return '';
        }
    }

    async function request(method, path, { body, params, raw, headers, timeoutMs } = {}) {
        const url = new URL(path, window.location.origin);
        if (params) {
            for (const [k, v] of Object.entries(params)) {
                if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v);
            }
        }
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json', ...(headers || {}) },
            credentials: 'same-origin',
            signal: AbortSignal.timeout(Number.isFinite(timeoutMs) ? timeoutMs : REQUEST_TIMEOUT),
        };
        if (body !== undefined) opts.body = JSON.stringify(body);
        if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
            if (!csrfToken) {
                await fetchCsrf();
            }
            if (!csrfToken) {
                throw new Error('Could not verify your session security. Refresh and try again.');
            }
            opts.headers['X-CSRF-Token'] = csrfToken;
        }
        const resp = await fetch(url, opts);
        if (resp.status === 401 || resp.status === 302) {
            _showSessionExpired();
            throw new Error('Authentication required');
        }
        if (!resp.ok) {
            const text = await resp.text();
            let message = text;
            let parsed = null;
            try {
                parsed = JSON.parse(text);
                if (parsed && typeof parsed === 'object') {
                    const detail = parsed.detail && typeof parsed.detail === 'object' ? parsed.detail : parsed;
                    message = detail.message || detail.error_code || text;
                }
            } catch (err) {
                void err;
            }
            const detail = parsed && typeof parsed === 'object'
                ? (parsed.detail && typeof parsed.detail === 'object' ? parsed.detail : parsed)
                : null;
            const error = new Error(`${resp.status}: ${message}`);
            error.status = resp.status;
            error.errorCode = detail && typeof detail.error_code === 'string' ? detail.error_code : '';
            error.details = detail && typeof detail.details === 'object' ? detail.details : null;
            error.payload = parsed;
            throw error;
        }
        if (resp.status === 204) return null;
        if (raw) return resp.text();
        const ct = resp.headers.get('content-type') || '';
        if (ct.includes('application/json')) return resp.json();
        return resp.text();
    }

    function _showSessionExpired() {
        if (document.getElementById('session-expired-overlay')) return;
        const overlay = document.createElement('div');
        overlay.id = 'session-expired-overlay';
        overlay.className = 'session-expired';
        overlay.innerHTML = '<div class="session-card">' +
            '<h3 id="session-expired-title">Session Expired</h3>' +
            '<p>Your session has timed out. Please log in again.</p>' +
            '<div class="session-card-actions">' +
            '<a href="/ui/login" class="btn btn-primary">Log in</a>' +
            '<button type="button" class="btn" id="session-expired-close">Dismiss</button>' +
            '</div>' +
            '</div>';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-labelledby', 'session-expired-title');
        document.body.appendChild(overlay);
        const close = document.getElementById('session-expired-close');
        if (close) close.addEventListener('click', () => overlay.remove());
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) overlay.remove();
        });
    }

    function _actionId() {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') {
            return window.crypto.randomUUID().replace(/-/g, '');
        }
        return `${Date.now()}${Math.random().toString(16).slice(2)}`;
    }

    function _agentPath(agentId) {
        const value = String(agentId || '').trim();
        if (!value) {
            throw new Error('Agent selection required');
        }
        return `/v1/agents/${encodeURIComponent(value)}`;
    }

    function _protocolArtifactContentPath(runId, artifactKey) {
        return `/v1/protocol-runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactKey)}/content`;
    }

    function _taskArtifactContentPath(taskId, artifactKey) {
        return `/v1/tasks/${encodeURIComponent(taskId)}/artifacts/${encodeURIComponent(artifactKey)}/content`;
    }

    function routedTaskIdFromConversation(conversation) {
        if (!conversation || typeof conversation !== 'object') return '';
        if (String(conversation.conversation_type || 'conversation') !== 'task_thread') return '';
        const externalRef = String(conversation.external_conversation_ref || '').trim();
        return externalRef.startsWith('routed-task:')
            ? externalRef.slice('routed-task:'.length).trim()
            : '';
    }

    function _normalizeProtocolRuns(payload) {
        if (Array.isArray(payload)) return payload;
        if (Array.isArray(payload?.runs)) return payload.runs;
        return [];
    }

    async function listConversationProtocolRuns(conversationId, conversation = {}, opts = {}) {
        const normalizedId = String(conversationId || '').trim();
        const limit = Number(opts.limit || 25) || 25;
        const runData = await request('GET', '/v1/protocol-runs', {
            params: { root_conversation_id: normalizedId, limit },
        });
        const runs = [..._normalizeProtocolRuns(runData)];
        const taskId = routedTaskIdFromConversation(conversation);
        if (!taskId) return runs;
        try {
            const task = await request('GET', `/v1/tasks/${encodeURIComponent(taskId)}`);
            const runId = String(task?.protocol_run_id || '').trim();
            if (!runId || runs.some((run) => String(run.protocol_run_id || '') === runId)) {
                return runs;
            }
            const detail = await request('GET', `/v1/protocol-runs/${encodeURIComponent(runId)}`);
            const linkedRun = detail?.run || detail;
            return linkedRun ? [linkedRun, ...runs].slice(0, limit) : runs;
        } catch (err) {
            _notify('Could not resolve linked protocol run', err, 'Conversation protocol run lookup failed');
            return runs;
        }
    }

    return {
        setCsrfToken,
        fetchCsrf,
        routedTaskIdFromConversation,

        // Agents
        getSummary: () =>
            request('GET', '/v1/summary'),
        cleanupWorkspaceData: (body = {}) =>
            request('POST', '/v1/admin/workspace-data/cleanup', { body }),
        listApprovals: (opts = {}) =>
            request('GET', '/v1/approvals', { params: opts }),
        listAgents: (opts = {}) =>
            request('GET', '/v1/agents', { params: opts }),
        getAgentStatus: (id) =>
            request('GET', `/v1/agents/${encodeURIComponent(id)}/status`),
        resetAgentExecutionFault: (id, body = {}) =>
            request('POST', `/v1/agents/${encodeURIComponent(id)}/execution/reset`, { body }),
        updateAgentTrustTier: (id, trustTier) =>
            request('PATCH', `/v1/agents/${encodeURIComponent(id)}/trust-tier`, {
                body: { trust_tier: String(trustTier || '') },
            }),
        updateAgentCapacity: (id, body = {}) =>
            request('PATCH', `/v1/agents/${encodeURIComponent(id)}/capacity`, { body }),
        rotateAgentToken: (id) =>
            request('POST', `/v1/agents/${encodeURIComponent(id)}/rotate-token`, { body: {} }),
        softDeleteAgent: (id) =>
            request('DELETE', `/v1/agents/${encodeURIComponent(id)}`),
        previewSelectorResolution: (body = {}) =>
            request('POST', '/v1/selector/preview', { body }),
        getAgentConversations: (id, opts = {}) =>
            request('GET', `/v1/agents/${encodeURIComponent(id)}/conversations`, { params: opts }),
        openConversationForAgent: async (agentId, opts = {}) => {
            const preferExisting = opts.preferExisting !== false;
            if (preferExisting) {
                const existing = await request('GET', `/v1/agents/${encodeURIComponent(agentId)}/conversations`, {
                    params: { limit: 25 },
                });
                const conversations = existing.conversations || existing || [];
                const registryOpen = conversations.find((item) =>
                    ['open', 'running'].includes(String(item.status || ''))
                    && String(item.conversation_type || 'conversation') === 'conversation'
                    && String(item.origin_channel || '') === 'registry'
                );
                if (registryOpen) {
                    return registryOpen;
                }
                const anyOpen = conversations.find((item) =>
                    ['open', 'running'].includes(String(item.status || ''))
                    && String(item.conversation_type || 'conversation') === 'conversation'
                );
                if (anyOpen) {
                    return anyOpen;
                }
            }
            return request('POST', '/v1/conversations', {
                body: {
                    target_agent_id: agentId,
                    origin_channel: 'registry',
                    external_conversation_ref: 'ui-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8),
                    title: opts.title || 'New conversation',
                },
            });
        },

        // Conversations
        listConversations: (opts = {}) =>
            request('GET', '/v1/conversations', { params: opts }),
        createConversation: (targetAgentId, title) =>
            request('POST', '/v1/conversations', {
                body: {
                    target_agent_id: targetAgentId,
                    origin_channel: 'registry',
                    external_conversation_ref: 'ui-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8),
                    title: title || 'New conversation',
                },
            }),
        getConversation: (id) =>
            request('GET', `/v1/conversations/${encodeURIComponent(id)}`),
        getEvents: (id, opts = {}) =>
            request('GET', `/v1/conversations/${encodeURIComponent(id)}/events`, { params: opts }),
        sendMessage: (id, text) =>
            request('POST', `/v1/conversations/${encodeURIComponent(id)}/messages`, { body: { text } }),
        conversationAction: (id, action, payload = {}) =>
            request('POST', `/v1/conversations/${encodeURIComponent(id)}/actions`, {
                body: { action_id: _actionId(), action, payload },
            }),
        exportConversation: (id) =>
            request('GET', `/v1/conversations/${encodeURIComponent(id)}/export`, { raw: true }),
        listConversationProtocolRuns,

        // Tasks
        listTasks: (opts = {}) =>
            request('GET', '/v1/tasks', { params: opts }),
        getTask: (id) =>
            request('GET', `/v1/tasks/${encodeURIComponent(id)}`),
        taskArtifactContentUrl: (taskId, artifactKey, opts = {}) => {
            const url = new URL(_taskArtifactContentPath(taskId, artifactKey), window.location.origin);
            if (opts.download) {
                url.searchParams.set('download', '1');
            }
            if (opts.browse) {
                url.searchParams.set('browse', '1');
            }
            if (opts.path) {
                url.searchParams.set('path', String(opts.path || ''));
            }
            return url.toString();
        },

        // Protocols
        listProtocols: (opts = {}) =>
            request('GET', '/v1/protocols', { params: opts }),
        getProtocolAuthoringOptions: () =>
            request('GET', '/v1/protocol-authoring/options'),
        listProtocolTemplates: () =>
            request('GET', '/v1/protocol-templates'),
        getProtocolTemplate: (slug) =>
            request('GET', `/v1/protocol-templates/${encodeURIComponent(slug)}`),
        getProtocol: (id) =>
            request('GET', `/v1/protocols/${encodeURIComponent(id)}`),
        getProtocolVersion: (protocolId, versionId) =>
            request('GET', `/v1/protocols/${encodeURIComponent(protocolId)}/versions/${encodeURIComponent(versionId)}`),
        parseProtocolDocument: (body = {}) =>
            request('POST', '/v1/protocols/parse', { body }),
        createProtocolDraft: (body = {}) =>
            request('POST', '/v1/protocol-drafts', { body }),
        createProtocol: (body = {}, opts = {}) =>
            request('POST', '/v1/protocols', {
                body,
                headers: opts.authoringSurface ? { 'X-Protocol-Authoring-Surface': String(opts.authoringSurface) } : undefined,
            }),
        deleteProtocol: (id) =>
            request('DELETE', `/v1/protocols/${encodeURIComponent(id)}`),
        saveProtocolDraft: (id, body = {}, opts = {}) =>
            request('PUT', `/v1/protocols/${encodeURIComponent(id)}/draft`, {
                body,
                headers: {
                    ...(Number.isFinite(opts.ifMatch) ? { 'If-Match': String(opts.ifMatch) } : {}),
                    ...(opts.authoringSurface ? { 'X-Protocol-Authoring-Surface': String(opts.authoringSurface) } : {}),
                },
            }),
        validateProtocol: (id) =>
            request('POST', `/v1/protocols/${encodeURIComponent(id)}/validate`, { body: {} }),
        publishProtocol: (id) =>
            request('POST', `/v1/protocols/${encodeURIComponent(id)}/publish`, { body: {} }),
        createProtocolTemplate: (body = {}) =>
            request('POST', '/v1/protocol-templates', { body }),
        archiveProtocol: (id) =>
            request('POST', `/v1/protocols/${encodeURIComponent(id)}/archive`, { body: {} }),
        exportProtocolDraft: (id, format = 'json') =>
            request('GET', `/v1/protocols/${encodeURIComponent(id)}/draft/export`, { params: { format } }),
        diffProtocolDraft: (id, format = 'json') =>
            request('GET', `/v1/protocols/${encodeURIComponent(id)}/diff`, { params: { format } }),
        listProtocolRuns: (opts = {}) =>
            request('GET', '/v1/protocol-runs', { params: opts }),
        listProtocolIssues: (opts = {}) =>
            request('GET', '/v1/protocol-runs/issues', { params: opts }),
        createProtocolRun: (body = {}, opts = {}) =>
            request('POST', '/v1/protocol-runs', {
                body,
                headers: opts.idempotencyKey ? { 'Idempotency-Key': opts.idempotencyKey } : undefined,
            }),
        getProtocolRun: (id) =>
            request('GET', `/v1/protocol-runs/${encodeURIComponent(id)}`),
        getProtocolRunParticipants: (id) =>
            request('GET', `/v1/protocol-runs/${encodeURIComponent(id)}/participants`),
        getProtocolRunArtifacts: (id) =>
            request('GET', `/v1/protocol-runs/${encodeURIComponent(id)}/artifacts`),
        protocolRunArtifactContentUrl: (id, artifactKey, opts = {}) => {
            const url = new URL(_protocolArtifactContentPath(id, artifactKey), window.location.origin);
            if (opts.download) {
                url.searchParams.set('download', '1');
            }
            if (opts.browse) {
                url.searchParams.set('browse', '1');
            }
            if (opts.path) {
                url.searchParams.set('path', String(opts.path || ''));
            }
            return url.toString();
        },
        getProtocolRunTimeline: (id) =>
            request('GET', `/v1/protocol-runs/${encodeURIComponent(id)}/timeline`),
        exportProtocolRun: (id) =>
            request('GET', `/v1/protocol-runs/${encodeURIComponent(id)}/export`),
        actOnProtocolRun: (id, action, body = {}, opts = {}) =>
            request('POST', `/v1/protocol-runs/${encodeURIComponent(id)}/actions/${encodeURIComponent(action)}`, {
                body,
                headers: {
                    ...(opts.idempotencyKey ? { 'Idempotency-Key': opts.idempotencyKey } : {}),
                    ...(Number.isFinite(opts.expectedVersion) ? { 'If-Match': String(opts.expectedVersion) } : {}),
                },
            }),
        listRehearsalSessions: (runId) =>
            request('GET', `/v1/protocol-runs/${encodeURIComponent(runId)}/rehearsal/sessions`),
        respondRehearsalSession: (runId, body = {}) =>
            request('POST', `/v1/protocol-runs/${encodeURIComponent(runId)}/rehearsal/respond`, { body }),
        listProtocolScenarios: (opts = {}) =>
            request('GET', '/v1/protocol-scenarios', { params: opts }),
        createProtocolScenario: (body = {}) =>
            request('POST', '/v1/protocol-scenarios', { body }),
        deleteProtocolScenario: (scenarioId) =>
            request('DELETE', `/v1/protocol-scenarios/${encodeURIComponent(scenarioId)}`),

        // Routing skills
        listRoutingSkills: () =>
            request('GET', '/v1/routing/skills'),
        enableRoutingSkill: (name) =>
            request('POST', `/v1/routing/skills/${encodeURIComponent(name)}/enable`),
        disableRoutingSkill: (name) =>
            request('POST', `/v1/routing/skills/${encodeURIComponent(name)}/disable`),

        // Skills
        listSkills: (agentId, opts = {}) =>
            request('GET', `${_agentPath(agentId)}/catalog/skills`, { params: opts }),
        searchCatalogSkills: (agentId, query) =>
            request('GET', `${_agentPath(agentId)}/catalog/skills/search`, { params: { q: query } }),
        getSkillDetail: (agentId, name) =>
            request('GET', `${_agentPath(agentId)}/catalog/skills/${encodeURIComponent(name)}`),
        getSkillLifecycle: (agentId, name) =>
            request('GET', `${_agentPath(agentId)}/catalog/skills/${encodeURIComponent(name)}/lifecycle`),
        saveSkillDraft: (agentId, name, body = {}) =>
            request('PUT', `${_agentPath(agentId)}/catalog/skills/${encodeURIComponent(name)}/draft`, { body }),
        exportSkillPackage: (agentId, name, opts = {}) =>
            request('GET', `${_agentPath(agentId)}/catalog/skills/${encodeURIComponent(name)}/export`, {
                params: { revision: opts.revision || 'draft' },
            }),
        importSkillPackage: (agentId, body = {}) =>
            request('POST', `${_agentPath(agentId)}/catalog/skills/import`, { body }),
        submitSkillDraft: (agentId, name, body = {}) =>
            request('POST', `${_agentPath(agentId)}/catalog/skills/${encodeURIComponent(name)}/submit`, { body }),
        approveSkillDraft: (agentId, name, body = {}) =>
            request('POST', `${_agentPath(agentId)}/catalog/skills/${encodeURIComponent(name)}/approve`, { body }),
        rejectSkillDraft: (agentId, name, body = {}) =>
            request('POST', `${_agentPath(agentId)}/catalog/skills/${encodeURIComponent(name)}/reject`, { body }),
        publishSkillDraft: (agentId, name, body = {}) =>
            request('POST', `${_agentPath(agentId)}/catalog/skills/${encodeURIComponent(name)}/publish`, {
                body,
                timeoutMs: 90000,
            }),
        archiveSkillDraft: (agentId, name, body = {}) =>
            request('POST', `${_agentPath(agentId)}/catalog/skills/${encodeURIComponent(name)}/archive`, { body }),
        installSkill: (agentId, name) =>
            request('POST', `${_agentPath(agentId)}/catalog/skills/${encodeURIComponent(name)}/install`),
        uninstallSkill: (agentId, name) =>
            request('POST', `${_agentPath(agentId)}/catalog/skills/${encodeURIComponent(name)}/uninstall`),
        updateSkill: (agentId, name) =>
            request('POST', `${_agentPath(agentId)}/catalog/skills/${encodeURIComponent(name)}/update`),
        diffSkill: (agentId, name) =>
            request('GET', `${_agentPath(agentId)}/catalog/skills/${encodeURIComponent(name)}/diff`),
        getConversationSkills: (agentId, conversationId) =>
            request('GET', `${_agentPath(agentId)}/conversations/${encodeURIComponent(conversationId)}/skills`),
        activateConversationSkill: (agentId, conversationId, skillName, body = {}) =>
            request('POST', `${_agentPath(agentId)}/conversations/${encodeURIComponent(conversationId)}/skills/${encodeURIComponent(skillName)}/activate`, { body }),
        deactivateConversationSkill: (agentId, conversationId, skillName, body = {}) =>
            request('POST', `${_agentPath(agentId)}/conversations/${encodeURIComponent(conversationId)}/skills/${encodeURIComponent(skillName)}/deactivate`, { body }),
        clearConversationSkills: (agentId, conversationId, body = {}) =>
            request('POST', `${_agentPath(agentId)}/conversations/${encodeURIComponent(conversationId)}/skills/clear`, { body }),
        submitConversationSkillCredential: (agentId, conversationId, skillName, body = {}) =>
            request('POST', `${_agentPath(agentId)}/conversations/${encodeURIComponent(conversationId)}/skills/${encodeURIComponent(skillName)}/credential`, { body }),
        getConversationSettings: (agentId, conversationId) =>
            request('GET', `${_agentPath(agentId)}/conversations/${encodeURIComponent(conversationId)}/settings`),
        updateConversationSetting: (agentId, conversationId, body = {}) =>
            request('POST', `${_agentPath(agentId)}/conversations/${encodeURIComponent(conversationId)}/settings`, { body }),
        resetConversation: (agentId, conversationId, body = {}) =>
            request('POST', `${_agentPath(agentId)}/conversations/${encodeURIComponent(conversationId)}/reset`, { body }),

        // Provider Guidance
        getGuidance: (agentId, provider, opts = {}) =>
            request('GET', `${_agentPath(agentId)}/guidance/${encodeURIComponent(provider)}`, { params: opts }),
        updateGuidanceDraft: (agentId, provider, body) =>
            request('PUT', `${_agentPath(agentId)}/guidance/${encodeURIComponent(provider)}/draft`, { body }),
        previewGuidance: (agentId, provider, body = {}) =>
            request('POST', `${_agentPath(agentId)}/guidance/${encodeURIComponent(provider)}/preview`, { body }),
        submitGuidance: (agentId, provider, body = {}) =>
            request('POST', `${_agentPath(agentId)}/guidance/${encodeURIComponent(provider)}/submit`, { body }),
        approveGuidance: (agentId, provider, body = {}) =>
            request('POST', `${_agentPath(agentId)}/guidance/${encodeURIComponent(provider)}/approve`, { body }),
        rejectGuidance: (agentId, provider, body = {}) =>
            request('POST', `${_agentPath(agentId)}/guidance/${encodeURIComponent(provider)}/reject`, { body }),
        publishGuidance: (agentId, provider, body = {}) =>
            request('POST', `${_agentPath(agentId)}/guidance/${encodeURIComponent(provider)}/publish`, { body }),
        archiveGuidance: (agentId, provider, body = {}) =>
            request('POST', `${_agentPath(agentId)}/guidance/${encodeURIComponent(provider)}/archive`, { body }),

        // Usage
        getUsage: (opts = {}) =>
            request('GET', '/v1/usage', { params: opts }),
    };
})();
