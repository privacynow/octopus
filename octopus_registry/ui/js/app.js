/**
 * App bootstrap — registers routes, connects WebSocket, initializes.
 */

let _timestampRefreshInterval = null;

function _initSidebar() {
    const hamburger = document.getElementById('hamburger');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    const closeButton = document.getElementById('sidebar-close');
    if (!hamburger || !sidebar) return;

    function openDrawer() {
        sidebar.classList.add('open');
        if (overlay) overlay.classList.add('active');
        hamburger.classList.add('active');
        hamburger.setAttribute('aria-expanded', 'true');
        hamburger.setAttribute('aria-label', 'Navigation open');
        document.body.classList.add('mobile-nav-open');
    }

    function closeDrawer() {
        sidebar.classList.remove('open');
        if (overlay) overlay.classList.remove('active');
        hamburger.classList.remove('active');
        hamburger.setAttribute('aria-expanded', 'false');
        hamburger.setAttribute('aria-label', 'Open navigation');
        document.body.classList.remove('mobile-nav-open');
    }

    hamburger.addEventListener('click', () => {
        if (sidebar.classList.contains('open')) {
            closeDrawer();
        } else {
            openDrawer();
        }
    });

    if (overlay) overlay.addEventListener('click', closeDrawer);
    if (closeButton) closeButton.addEventListener('click', closeDrawer);
    document.addEventListener('octopus:close-mobile-nav', closeDrawer);

    sidebar.addEventListener('click', (e) => {
        if (e.target.closest('a[href]')) {
            closeDrawer();
        }
    });

    function syncDrawerForViewport() {
        if (window.innerWidth <= 900 || sidebar.classList.contains('open')) {
            closeDrawer();
        }
    }

    syncDrawerForViewport();
    window.addEventListener('resize', syncDrawerForViewport);
}

function _startTimestampRefresh() {
    if (_timestampRefreshInterval) return;
    _timestampRefreshInterval = setInterval(() => {
        document.querySelectorAll('[data-timestamp]').forEach((el) => {
            const ts = el.getAttribute('data-timestamp');
            if (ts) {
                el.textContent = UI.relativeTime(ts);
            }
        });
    }, 30000);
}

function _stopTimestampRefresh() {
    if (_timestampRefreshInterval) {
        clearInterval(_timestampRefreshInterval);
        _timestampRefreshInterval = null;
    }
}

function _initKeyboard() {
    document.addEventListener('keydown', (e) => {
        if (e.key === '/' && !_isInputFocused()) {
            const search = document.querySelector('.search-input');
            if (search) {
                e.preventDefault();
                search.focus();
            }
        }
        if (e.key === 'Escape') {
            document.dispatchEvent(new CustomEvent('octopus:close-mobile-nav'));
        }
    });
}

function _isInputFocused() {
    const active = document.activeElement;
    if (!active) return false;
    const tag = active.tagName.toLowerCase();
    return tag === 'input' || tag === 'textarea' || tag === 'select' || active.isContentEditable;
}

function _setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try {
        localStorage.setItem('octopus-theme', theme);
    } catch (e) {
        console.warn('Failed to persist theme', e);
    }
    const label = document.getElementById('theme-toggle-label');
    if (label) {
        label.textContent = theme === 'dark' ? 'Dark' : 'Light';
    }
}

function _initTheme() {
    const toggle = document.getElementById('theme-toggle');
    const stored = (() => {
        try {
            return localStorage.getItem('octopus-theme');
        } catch {
            return '';
        }
    })();
    _setTheme(stored || 'dark');
    if (!toggle) return;
    toggle.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme') || 'light';
        _setTheme(current === 'dark' ? 'light' : 'dark');
    });
}

Router.register('/ui', renderDashboard);
Router.register('/ui/', renderDashboard);
Router.register('/ui/approvals', renderApprovalList);
Router.register('/ui/agents', renderAgentList);
Router.register('/ui/agents/:id', renderAgentDetail);
Router.register('/ui/agents/:id/conversations', renderAgentConversations);
Router.register('/ui/conversations', renderConversationList);
Router.register('/ui/conversations/:id', renderConversationDetail);
Router.register('/ui/tasks', renderTaskList);
Router.register('/ui/protocols', renderProtocolWorkspace);
Router.register('/ui/design-sessions', renderProtocolWorkspace);
Router.register('/ui/runs', renderProtocolRuns);
Router.register('/ui/routing', renderRoutingPolicyList);
Router.register('/ui/skills', renderSkillCatalog);
Router.register('/ui/usage', renderUsageView);
Router.register('/ui/guidance', renderGuidanceEditor);
Router.register('/ui/login', renderLoginForm);

document.addEventListener('DOMContentLoaded', async () => {
    _initTheme();
    _initSidebar();
    _initKeyboard();
    _startTimestampRefresh();
    await API.fetchCsrf();
    Router.init();
    WS.connect();
});

window.addEventListener('beforeunload', () => {
    _stopTimestampRefresh();
});
