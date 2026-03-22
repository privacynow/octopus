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

// Utility: render markdown-ish content (basic: code blocks, bold, links)
function _renderContent(text) {
    if (!text) return '';
    if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
        return DOMPurify.sanitize(marked.parse(text));
    }
    // Fallback: basic rendering when vendor libs are not loaded
    let html = esc(text);
    // Code blocks
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    // Line breaks
    html = html.replace(/\n/g, '<br>');
    return html;
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
