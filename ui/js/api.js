/**
 * API client — fetch wrappers for /v1/ resource endpoints.
 * All data via the same endpoints any external consumer would use.
 * Auth via session cookie (set by /ui/login).
 * CSRF token passed on mutating requests.
 */
const API = (() => {
    let csrfToken = '';

    function setCsrfToken(token) {
        csrfToken = token;
    }

    async function request(method, path, { body, params } = {}) {
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
        };
        if (body !== undefined) opts.body = JSON.stringify(body);
        if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method) && csrfToken) {
            opts.headers['X-CSRF-Token'] = csrfToken;
        }
        const resp = await fetch(url, opts);
        if (resp.status === 401 || resp.status === 302) {
            window.location.href = '/ui/login';
            throw new Error('Authentication required');
        }
        if (!resp.ok) {
            const text = await resp.text();
            throw new Error(`${resp.status}: ${text}`);
        }
        if (resp.status === 204) return null;
        const ct = resp.headers.get('content-type') || '';
        if (ct.includes('application/json')) return resp.json();
        return resp.text();
    }

    async function unwrap(key, promise) {
        const data = await promise;
        if (data && typeof data === 'object' && key in data) return data[key];
        return data;
    }

    return {
        setCsrfToken,
        // Agents
        listAgents: () => unwrap('agents', request('GET', '/v1/agents')),
        getAgentStatus: (id) => request('GET', `/v1/agents/${id}/status`),
        getAgentConversations: (id, opts = {}) =>
            unwrap('conversations', request('GET', `/v1/agents/${id}/conversations`, { params: opts })),
        // Conversations
        listConversations: (opts = {}) =>
            unwrap('conversations', request('GET', '/v1/conversations', { params: opts })),
        getConversation: (id) => request('GET', `/v1/conversations/${id}`),
        createConversation: (body) => request('POST', '/v1/conversations', { body }),
        getEvents: (id, opts = {}) =>
            request('GET', `/v1/conversations/${id}/events`, { params: opts }),
        getMessages: (id, opts = {}) =>
            request('GET', `/v1/conversations/${id}/messages`, { params: opts }),
        sendMessage: (id, text) =>
            request('POST', `/v1/conversations/${id}/messages`, { body: { text } }),
        conversationAction: (id, action, payload = {}) =>
            request('POST', `/v1/conversations/${id}/actions`, { body: { action, ...payload } }),
        exportConversation: (id) => request('GET', `/v1/conversations/${id}/export`),
        // Tasks
        listTasks: (opts = {}) => unwrap('tasks', request('GET', '/v1/tasks', { params: opts })),
        // Capabilities
        listCapabilities: () => request('GET', '/v1/capabilities'),
        enableCapability: (name) => request('POST', `/v1/capabilities/${name}/enable`),
        disableCapability: (name) => request('POST', `/v1/capabilities/${name}/disable`),
        // Usage
        getUsage: (opts = {}) => request('GET', '/v1/usage', { params: opts }),
    };
})();
