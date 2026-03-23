/**
 * App bootstrap — registers routes, connects WebSocket, initializes.
 */

// Utility: escape HTML
function esc(str) {
    if (str === null || str === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

// Utility: render markdown content safely
function _renderContent(text) {
    if (!text) return '';
    if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
        return DOMPurify.sanitize(marked.parse(text));
    }
    // Safe fallback: plain escaped text with line breaks only.
    // No regex markdown — that path is XSS-vulnerable without DOMPurify.
    return esc(text).replace(/\n/g, '<br>');
}

// Utility: relative time
function _relativeTime(iso) {
    if (!iso) return '';
    try {
        const d = new Date(iso);
        const now = new Date();
        const sec = Math.floor((now - d) / 1000);
        if (sec < 60) return 'just now';
        if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
        if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
        return `${Math.floor(sec / 86400)}d ago`;
    } catch {
        return iso;
    }
}

// Utility: format timestamp
function _formatTime(iso) {
    if (!iso) return '';
    try {
        const d = new Date(iso);
        return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
        return iso;
    }
}

// Register routes
Router.register('/ui', renderAgentList);
Router.register('/ui/', renderAgentList);
Router.register('/ui/agents/:id', renderAgentDetail);
Router.register('/ui/agents/:id/conversations', renderAgentConversations);
Router.register('/ui/conversations', renderConversationList);
Router.register('/ui/conversations/:id', renderConversationDetail);
Router.register('/ui/tasks', renderTaskList);
Router.register('/ui/capabilities', renderCapabilityList);
Router.register('/ui/skills', renderSkillCatalog);
Router.register('/ui/usage', renderUsageView);
Router.register('/ui/login', renderLoginForm);

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    Router.init();
    WS.connect();
});
