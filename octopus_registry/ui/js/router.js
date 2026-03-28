/**
 * Minimal SPA router using history.pushState.
 * Supports cleanup callbacks — each view's render function can return
 * a cleanup function that is called before the next route renders.
 */
const Router = (() => {
    const routes = [];
    let contentEl = null;
    let currentCleanup = null;

    function register(pattern, render) {
        const paramNames = [];
        const regexStr = pattern
            .replace(/:[a-zA-Z]+/g, (match) => {
                paramNames.push(match.slice(1));
                return '([^/]+)';
            });
        routes.push({
            regex: new RegExp(`^${regexStr}$`),
            paramNames,
            render,
        });
    }

    function navigate(path, { replace = false } = {}) {
        if (replace) {
            history.replaceState(null, '', path);
        } else {
            history.pushState(null, '', path);
        }
        resolve();
    }

    function resolve() {
        const path = window.location.pathname;
        const normalized = path.length > 1 ? path.replace(/\/$/, '') : path;

        for (const route of routes) {
            const match = normalized.match(route.regex);
            if (match) {
                const params = {};
                route.paramNames.forEach((name, i) => {
                    params[name] = decodeURIComponent(match[i + 1]);
                });
                _render(route.render, params);
                _updateActiveNav(normalized);
                return;
            }
        }
        // 404
        _cleanup();
        if (!contentEl) contentEl = document.getElementById('content');
        contentEl.textContent = '';
        const msg = document.createElement('div');
        msg.className = 'empty-state';
        msg.textContent = 'Page not found';
        contentEl.appendChild(msg);
    }

    function _cleanup() {
        if (typeof currentCleanup === 'function') {
            try { currentCleanup(); } catch (e) { console.error('Route cleanup error', e); }
        }
        currentCleanup = null;
    }

    function _render(renderFn, params) {
        _cleanup();
        if (!contentEl) contentEl = document.getElementById('content');
        contentEl.classList.add('loading-route');
        contentEl.textContent = '';
        const inner = document.createElement('div');
        inner.className = 'content-inner route-enter';
        contentEl.appendChild(inner);
        const renderCleanup = window.UI && typeof UI.createCleanupBag === 'function'
            ? UI.createCleanupBag()
            : null;
        try {
            if (renderCleanup && typeof UI.setActiveCleanupBag === 'function') {
                UI.setActiveCleanupBag(renderCleanup);
            }
            const result = renderFn(inner, params);
            if (renderCleanup) {
                if (typeof result === 'function') renderCleanup.add(result);
                currentCleanup = () => renderCleanup.flush();
            } else if (typeof result === 'function') {
                currentCleanup = result;
            }
        } catch (e) {
            if (renderCleanup) renderCleanup.flush();
            console.error('Route render error', e);
            if (window.UI && typeof UI.notify === 'function') {
                UI.notify('This page failed to render. You can retry or navigate elsewhere.', 'danger');
            }
            const errCard = document.createElement('div');
            errCard.className = 'error-card';
            const errMsg = document.createElement('p');
            errMsg.textContent = 'Something went wrong: ' + (e.message || 'Unknown error');
            errCard.appendChild(errMsg);
            const retryBtn = document.createElement('button');
            retryBtn.className = 'btn btn-primary';
            retryBtn.textContent = 'Retry';
            retryBtn.addEventListener('click', () => resolve());
            errCard.appendChild(retryBtn);
            inner.textContent = '';
            inner.appendChild(errCard);
        } finally {
            if (window.UI && typeof UI.setActiveCleanupBag === 'function') {
                UI.setActiveCleanupBag(null);
            }
        }
        requestAnimationFrame(() => {
            contentEl.classList.remove('loading-route');
            inner.classList.add('route-enter-active');
            const main = document.getElementById('content');
            if (main) main.focus();
        });
    }

    function _updateActiveNav(path) {
        document.querySelectorAll('.nav-links a').forEach(a => {
            const route = a.getAttribute('data-route');
            let isActive = false;
            if (route === '/' && (path === '/ui' || path === '/ui/')) {
                isActive = true;
            } else if (route && route !== '/' && path.startsWith('/ui' + route)) {
                isActive = true;
            }
            a.classList.toggle('active', isActive);
            if (isActive) {
                a.setAttribute('aria-current', 'page');
            } else {
                a.removeAttribute('aria-current');
            }
        });
    }

    function init() {
        contentEl = document.getElementById('content');

        // Intercept link clicks for SPA navigation
        document.addEventListener('click', (e) => {
            const a = e.target.closest('a[href]');
            if (!a) return;
            const href = a.getAttribute('href');
            if (!href || !href.startsWith('/ui') || href === '/ui/logout') return;
            e.preventDefault();
            navigate(href);
        });

        // Handle browser back/forward
        window.addEventListener('popstate', () => resolve());

        resolve();
    }

    return { register, navigate, resolve, init };
})();
