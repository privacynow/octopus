/**
 * App bootstrap — registers routes, connects WebSocket, initializes.
 */

// ── Utility: escape HTML ──
function esc(str) {
    if (str === null || str === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

// ── Utility: render markdown content safely ──
function _renderContent(text) {
    if (!text) return '';
    // Only render markdown if both marked and DOMPurify are loaded
    if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
        return DOMPurify.sanitize(marked.parse(text));
    }
    // Safe fallback: plain escaped text with line breaks only.
    return esc(text).replace(/\n/g, '<br>');
}

// ── Utility: relative time ──
function _relativeTime(iso) {
    if (!iso) return '';
    try {
        const d = new Date(iso);
        const now = new Date();
        const sec = Math.floor((now - d) / 1000);
        if (sec < 0) return 'just now';
        if (sec < 60) return 'just now';
        if (sec < 3600) return Math.floor(sec / 60) + 'm ago';
        if (sec < 86400) return Math.floor(sec / 3600) + 'h ago';
        return Math.floor(sec / 86400) + 'd ago';
    } catch {
        return iso;
    }
}

// ── Utility: format time ──
function _formatTime(iso) {
    if (!iso) return '';
    try {
        const d = new Date(iso);
        return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
        return iso;
    }
}

// ── Utility: render skeleton loaders ──
function _renderSkeletons(container, count, type) {
    const cls = type === 'row' ? 'skeleton skeleton-row' : 'skeleton skeleton-card';
    for (let i = 0; i < count; i++) {
        const div = document.createElement('div');
        div.className = cls;
        container.appendChild(div);
    }
}

// ── Utility: render pagination controls ──
function _renderPagination(container, { hasPrev, hasNext, onPrev, onNext, info }) {
    const pag = document.createElement('div');
    pag.className = 'pagination';

    const prevBtn = document.createElement('button');
    prevBtn.className = 'btn btn-sm';
    prevBtn.textContent = 'Previous';
    prevBtn.disabled = !hasPrev;
    if (hasPrev) prevBtn.addEventListener('click', onPrev);

    const infoSpan = document.createElement('span');
    infoSpan.className = 'page-info';
    infoSpan.textContent = info || '';

    const nextBtn = document.createElement('button');
    nextBtn.className = 'btn btn-sm';
    nextBtn.textContent = 'Next';
    nextBtn.disabled = !hasNext;
    if (hasNext) nextBtn.addEventListener('click', onNext);

    pag.appendChild(prevBtn);
    pag.appendChild(infoSpan);
    pag.appendChild(nextBtn);
    container.appendChild(pag);
}

// ── Utility: create error card with retry ──
function _renderError(container, message, retryFn) {
    const card = document.createElement('div');
    card.className = 'error-card';
    const p = document.createElement('p');
    p.textContent = message;
    card.appendChild(p);
    if (retryFn) {
        const btn = document.createElement('button');
        btn.className = 'btn btn-primary';
        btn.textContent = 'Retry';
        btn.addEventListener('click', retryFn);
        card.appendChild(btn);
    }
    container.appendChild(card);
}

// ── Utility: confirmation dialog ──
function _showConfirm(title, message, onConfirm) {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    overlay.innerHTML = '';

    const dialog = document.createElement('div');
    dialog.className = 'confirm-dialog';

    const h3 = document.createElement('h3');
    h3.textContent = title;
    dialog.appendChild(h3);

    const p = document.createElement('p');
    p.textContent = message;
    dialog.appendChild(p);

    const actions = document.createElement('div');
    actions.className = 'confirm-actions';

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', () => overlay.remove());

    const confirmBtn = document.createElement('button');
    confirmBtn.className = 'btn btn-primary';
    confirmBtn.textContent = 'Confirm';
    confirmBtn.addEventListener('click', () => {
        overlay.remove();
        onConfirm();
    });

    actions.appendChild(cancelBtn);
    actions.appendChild(confirmBtn);
    dialog.appendChild(actions);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    // Close on overlay click or Escape
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.remove();
    });
    const escHandler = (e) => {
        if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', escHandler); }
    };
    document.addEventListener('keydown', escHandler);
}

// ── Hamburger / sidebar drawer ──
function _initSidebar() {
    const hamburger = document.getElementById('hamburger');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    if (!hamburger || !sidebar) return;

    function openDrawer() {
        sidebar.classList.add('open');
        overlay.classList.add('active');
        hamburger.classList.add('active');
    }

    function closeDrawer() {
        sidebar.classList.remove('open');
        overlay.classList.remove('active');
        hamburger.classList.remove('active');
    }

    hamburger.addEventListener('click', () => {
        if (sidebar.classList.contains('open')) {
            closeDrawer();
        } else {
            openDrawer();
        }
    });

    overlay.addEventListener('click', closeDrawer);

    // Close drawer on navigation
    sidebar.addEventListener('click', (e) => {
        if (e.target.closest('a[href]')) {
            closeDrawer();
        }
    });
}

// ── Relative time refresh ──
let _timestampRefreshInterval = null;

function _startTimestampRefresh() {
    if (_timestampRefreshInterval) return;
    _timestampRefreshInterval = setInterval(() => {
        document.querySelectorAll('[data-timestamp]').forEach(el => {
            const ts = el.getAttribute('data-timestamp');
            if (ts) {
                el.textContent = _relativeTime(ts);
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

// ── Keyboard shortcuts ──
function _initKeyboard() {
    document.addEventListener('keydown', (e) => {
        // / to focus search
        if (e.key === '/' && !_isInputFocused()) {
            const search = document.querySelector('.search-input');
            if (search) {
                e.preventDefault();
                search.focus();
            }
        }
        // Escape to close drawers/modals
        if (e.key === 'Escape') {
            const sidebar = document.getElementById('sidebar');
            if (sidebar && sidebar.classList.contains('open')) {
                sidebar.classList.remove('open');
                const overlay = document.getElementById('sidebar-overlay');
                if (overlay) overlay.classList.remove('active');
                const hamburger = document.getElementById('hamburger');
                if (hamburger) hamburger.classList.remove('active');
            }
        }
    });
}

function _isInputFocused() {
    const active = document.activeElement;
    if (!active) return false;
    const tag = active.tagName.toLowerCase();
    return tag === 'input' || tag === 'textarea' || tag === 'select' || active.isContentEditable;
}

// ── Register routes ──
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

// ── Initialize ──
document.addEventListener('DOMContentLoaded', async () => {
    _initSidebar();
    _initKeyboard();
    _startTimestampRefresh();
    await API.fetchCsrf();
    Router.init();
    WS.connect();
});
