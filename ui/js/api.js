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

    /** Fetch CSRF token from the auth endpoint. */
    async function fetchCsrf() {
        try {
            const resp = await fetch('/v1/auth/csrf', { credentials: 'same-origin' });
            if (resp.ok) {
                const data = await resp.json();
                csrfToken = data.token || data.csrf_token || '';
            }
        } catch (e) {
            console.warn('Failed to fetch CSRF token', e);
        }
    }

    async function request(method, path, { body, params, raw } = {}) {
        const url = new URL(path, window.location.origin);
        if (params) {
            for (const [k, v] of Object.entries(params)) {
                if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v);
            }
        }
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            signal: AbortSignal.timeout(REQUEST_TIMEOUT),
        };
        if (body !== undefined) opts.body = JSON.stringify(body);
        if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method) && csrfToken) {
            opts.headers['X-CSRF-Token'] = csrfToken;
        }
        const resp = await fetch(url, opts);
        if (resp.status === 401 || resp.status === 302) {
            _showSessionExpired();
            throw new Error('Authentication required');
        }
        if (!resp.ok) {
            const text = await resp.text();
            throw new Error(`${resp.status}: ${text}`);
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
            '<h3>Session Expired</h3>' +
            '<p>Your session has timed out. Please log in again.</p>' +
            '<a href="/ui/login" class="btn btn-primary">Log in</a>' +
            '</div>';
        document.body.appendChild(overlay);
    }

    return {
        setCsrfToken,
        fetchCsrf,

        // Agents
        getSummary: () =>
            request('GET', '/v1/summary'),
        listApprovals: (opts = {}) =>
            request('GET', '/v1/approvals', { params: opts }),
        listAgents: (opts = {}) =>
            request('GET', '/v1/agents', { params: opts }),
        getAgentStatus: (id) =>
            request('GET', `/v1/agents/${encodeURIComponent(id)}/status`),
        getAgentConversations: (id, opts = {}) =>
            request('GET', `/v1/agents/${encodeURIComponent(id)}/conversations`, { params: opts }),

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
            request('POST', `/v1/conversations/${encodeURIComponent(id)}/actions`, { body: { action, payload } }),
        exportConversation: (id) =>
            request('GET', `/v1/conversations/${encodeURIComponent(id)}/export`, { raw: true }),

        // Tasks
        listTasks: (opts = {}) =>
            request('GET', '/v1/tasks', { params: opts }),

        // Capabilities
        listCapabilities: () =>
            request('GET', '/v1/capabilities'),
        enableCapability: (name) =>
            request('POST', `/v1/capabilities/${encodeURIComponent(name)}/enable`),
        disableCapability: (name) =>
            request('POST', `/v1/capabilities/${encodeURIComponent(name)}/disable`),

        // Skills
        listSkills: () =>
            request('GET', '/v1/catalog/skills'),
        getSkillDetail: (name) =>
            request('GET', `/v1/catalog/skills/${encodeURIComponent(name)}`),
        installSkill: (name) =>
            request('POST', `/v1/catalog/skills/${encodeURIComponent(name)}/install`),
        uninstallSkill: (name) =>
            request('POST', `/v1/catalog/skills/${encodeURIComponent(name)}/uninstall`),

        // Provider Guidance
        getGuidance: (provider) =>
            request('GET', `/v1/provider-guidance/${encodeURIComponent(provider)}`),
        updateGuidanceDraft: (provider, body) =>
            request('PUT', `/v1/provider-guidance/${encodeURIComponent(provider)}/draft`, { body }),
        previewGuidance: (provider, body = {}) =>
            request('POST', `/v1/provider-guidance/${encodeURIComponent(provider)}/preview`, { body }),
        submitGuidance: (provider, body = {}) =>
            request('POST', `/v1/provider-guidance/${encodeURIComponent(provider)}/submit`, { body }),
        approveGuidance: (provider, body = {}) =>
            request('POST', `/v1/provider-guidance/${encodeURIComponent(provider)}/approve`, { body }),
        publishGuidance: (provider, body = {}) =>
            request('POST', `/v1/provider-guidance/${encodeURIComponent(provider)}/publish`, { body }),

        // Usage
        getUsage: (opts = {}) =>
            request('GET', '/v1/usage', { params: opts }),
    };
})();
