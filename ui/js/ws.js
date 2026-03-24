/**
 * WebSocket client — real-time event push from registry.
 * Exponential backoff, connection status tracking, client-side ping.
 */
const WS = (() => {
    let socket = null;
    let reconnectTimer = null;
    let pingTimer = null;
    let attempt = 0;
    let status = 'offline'; // 'connected' | 'reconnecting' | 'offline'
    let onStatusChange = null;
    const listeners = new Map(); // topic -> Set<callback>
    const BACKOFF_CAP = 30000;
    const PING_INTERVAL = 30000;

    function _setStatus(s) {
        if (status === s) return;
        status = s;
        _updateStatusUI();
        if (typeof onStatusChange === 'function') {
            try { onStatusChange(s); } catch (e) { /* ignore */ }
        }
    }

    function _updateStatusUI() {
        const dot = document.querySelector('#ws-status .ws-dot');
        const label = document.querySelector('#ws-status .ws-label');
        if (dot) {
            dot.className = 'ws-dot ' + status;
        }
        if (label) {
            const labels = { connected: 'Connected', reconnecting: 'Reconnecting', offline: 'Offline' };
            label.textContent = labels[status] || status;
        }
    }

    function connect() {
        if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
            return;
        }
        const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        socket = new WebSocket(`${proto}//${window.location.host}/v1/ws`);

        socket.onopen = () => {
            attempt = 0;
            _setStatus('connected');
            _startPing();
            // Resubscribe to all active topics
            const topics = Array.from(listeners.keys());
            if (topics.length > 0) {
                socket.send(JSON.stringify({ subscribe: topics }));
            }
        };

        socket.onmessage = (evt) => {
            try {
                const msg = JSON.parse(evt.data);
                if (msg.pong) return; // ignore pong replies
                _dispatch(msg);
            } catch (e) {
                console.warn('WS: failed to parse message', evt.data, e);
            }
        };

        socket.onclose = () => {
            _stopPing();
            _setStatus('reconnecting');
            _scheduleReconnect();
        };

        socket.onerror = () => {
            socket.close();
        };
    }

    function _startPing() {
        _stopPing();
        pingTimer = setInterval(() => {
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ ping: true }));
            }
        }, PING_INTERVAL);
    }

    function _stopPing() {
        if (pingTimer) {
            clearInterval(pingTimer);
            pingTimer = null;
        }
    }

    function _scheduleReconnect() {
        if (reconnectTimer) return;
        // Exponential backoff: 1s, 2s, 4s, 8s, 16s, 30s cap
        const delay = Math.min(1000 * Math.pow(2, attempt), BACKOFF_CAP);
        attempt++;
        reconnectTimer = setTimeout(() => {
            reconnectTimer = null;
            connect();
        }, delay);
    }

    function _dispatch(msg) {
        const data = msg.data || {};
        const topics = [];
        if (data.conversation_id) topics.push(`conversation:${data.conversation_id}`);
        if (data.agent_id) topics.push(`agent:${data.agent_id}`);

        for (const topic of topics) {
            const cbs = listeners.get(topic);
            if (cbs) {
                for (const cb of cbs) {
                    try { cb(msg); } catch (e) { console.error('WS listener error', { topic, type: msg.type, data }, e); }
                }
            }
        }
        // Wildcard listeners
        const wildcardCbs = listeners.get('*');
        if (wildcardCbs) {
            for (const cb of wildcardCbs) {
                try { cb(msg); } catch (e) { console.error('WS listener error', { topic: '*', type: msg.type, data }, e); }
            }
        }
    }

    function subscribe(topic, callback) {
        if (!listeners.has(topic)) listeners.set(topic, new Set());
        listeners.get(topic).add(callback);
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ subscribe: [topic] }));
        }
        return () => unsubscribe(topic, callback);
    }

    function unsubscribe(topic, callback) {
        const cbs = listeners.get(topic);
        if (cbs) {
            cbs.delete(callback);
            if (cbs.size === 0) {
                listeners.delete(topic);
                if (socket && socket.readyState === WebSocket.OPEN) {
                    socket.send(JSON.stringify({ unsubscribe: [topic] }));
                }
            }
        }
    }

    function disconnect() {
        _stopPing();
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
        if (socket) {
            socket.close();
            socket = null;
        }
        _setStatus('offline');
    }

    function getStatus() { return status; }

    function setOnStatusChange(cb) { onStatusChange = cb; }

    return { connect, disconnect, subscribe, unsubscribe, getStatus, setOnStatusChange };
})();
