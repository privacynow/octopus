/**
 * WebSocket client — real-time event push from registry.
 * v1: operator session cookie auth only (no token in URL).
 */
const WS = (() => {
    let socket = null;
    let reconnectTimer = null;
    const listeners = new Map(); // topic -> Set<callback>

    function connect() {
        if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
            return;
        }
        const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        socket = new WebSocket(`${proto}//${window.location.host}/v1/ws`);

        socket.onopen = () => {
            // Resubscribe to all active topics
            const topics = Array.from(listeners.keys());
            if (topics.length > 0) {
                socket.send(JSON.stringify({ subscribe: topics }));
            }
        };

        socket.onmessage = (evt) => {
            try {
                const msg = JSON.parse(evt.data);
                _dispatch(msg);
            } catch (e) {
                console.warn('WS: failed to parse message', e);
            }
        };

        socket.onclose = () => {
            _scheduleReconnect();
        };

        socket.onerror = () => {
            socket.close();
        };
    }

    function _scheduleReconnect() {
        if (reconnectTimer) return;
        reconnectTimer = setTimeout(() => {
            reconnectTimer = null;
            connect();
        }, 3000);
    }

    function _dispatch(msg) {
        // msg: {type: "event", data: {conversation_id, agent_id, ...}}
        // or:  {type: "heartbeat", data: {agent_id, ...}}
        const data = msg.data || {};
        const topics = [];
        if (data.conversation_id) topics.push(`conversation:${data.conversation_id}`);
        if (data.agent_id) topics.push(`agent:${data.agent_id}`);

        for (const topic of topics) {
            const cbs = listeners.get(topic);
            if (cbs) {
                for (const cb of cbs) {
                    try { cb(msg); } catch (e) { console.error('WS listener error', e); }
                }
            }
        }
        // Also dispatch to wildcard listeners
        const wildcardCbs = listeners.get('*');
        if (wildcardCbs) {
            for (const cb of wildcardCbs) {
                try { cb(msg); } catch (e) { console.error('WS listener error', e); }
            }
        }
    }

    function subscribe(topic, callback) {
        if (!listeners.has(topic)) listeners.set(topic, new Set());
        listeners.get(topic).add(callback);
        // Send subscription to server if connected
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
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
        if (socket) {
            socket.close();
            socket = null;
        }
    }

    return { connect, disconnect, subscribe, unsubscribe };
})();
