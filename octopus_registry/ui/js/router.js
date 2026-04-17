/**
 * Minimal SPA router using history.pushState.
 * Supports cleanup callbacks — each view's render function can return
 * a cleanup function that is called after the next route finishes mounting.
 */
const Router = (() => {
    const routes = [];
    let contentEl = null;
    let currentCleanup = null;
    let renderSequence = 0;

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
                void _render(route.render, params, normalized);
                return;
            }
        }
        // 404
        if (!contentEl) contentEl = document.getElementById('content');
        const renderId = ++renderSequence;
        const inner = document.createElement('div');
        inner.className = 'content-inner';
        const msg = document.createElement('div');
        msg.className = 'empty-state';
        msg.textContent = 'Page not found';
        inner.appendChild(msg);
        _swapMountedRoute(inner, renderId, null, normalized);
    }

    function _cleanup(cleanup = currentCleanup) {
        if (typeof cleanup === 'function') {
            try { cleanup(); } catch (e) { console.error('Route cleanup error', e); }
        }
        if (cleanup === currentCleanup) {
            currentCleanup = null;
        }
    }

    function _cleanupShell(node) {
        if (!(node instanceof HTMLElement)) return;
        const cleanup = node.__routeCleanup;
        node.__routeCleanup = null;
        _cleanup(cleanup);
    }

    function _prepareShell(inner, nextCleanup) {
        inner.classList.add('route-shell');
        inner.__routeCleanup = nextCleanup;
    }

    function _routeReadyPromise(inner) {
        const ready = inner.__routeReady;
        return ready && typeof ready.then === 'function' ? ready : Promise.resolve();
    }

    function _swapMountedRoute(inner, renderId, nextCleanup, activePath) {
        _prepareShell(inner, nextCleanup);
        if (!contentEl || renderId !== renderSequence) {
            _cleanup(nextCleanup);
            return;
        }
        const previousShell = contentEl.firstElementChild instanceof HTMLElement
            ? contentEl.firstElementChild
            : null;
        contentEl.replaceChildren(inner);
        currentCleanup = nextCleanup;
        _updateActiveNav(activePath);
        if (!previousShell) return;
        requestAnimationFrame(() => {
            if (renderId !== renderSequence) return;
            _cleanupShell(previousShell);
        });
    }

    function _renderRouteError(inner, error) {
        console.error('Route render error', error);
        if (window.UI && typeof UI.notify === 'function') {
            UI.notify('This page failed to render. You can retry or navigate elsewhere.', 'danger');
        }
        const errCard = document.createElement('div');
        errCard.className = 'error-card';
        const errMsg = document.createElement('p');
        errMsg.textContent = 'Something went wrong: ' + (error.message || 'Unknown error');
        errCard.appendChild(errMsg);
        const retryBtn = document.createElement('button');
        retryBtn.className = 'btn btn-primary';
        retryBtn.textContent = 'Retry';
        retryBtn.addEventListener('click', () => resolve());
        errCard.appendChild(retryBtn);
        inner.textContent = '';
        inner.appendChild(errCard);
    }

    async function _render(renderFn, params, activePath) {
        if (!contentEl) contentEl = document.getElementById('content');
        const renderId = ++renderSequence;
        const inner = document.createElement('div');
        inner.className = 'content-inner';
        const renderCleanup = window.UI && typeof UI.createCleanupBag === 'function'
            ? UI.createCleanupBag()
            : null;
        let nextCleanup = renderCleanup
            ? () => renderCleanup.flush()
            : null;
        try {
            if (renderCleanup && typeof UI.setActiveCleanupBag === 'function') {
                UI.setActiveCleanupBag(renderCleanup);
            }
            const cleanup = renderFn(inner, params);
            if (renderCleanup && typeof cleanup === 'function') {
                renderCleanup.add(cleanup);
            } else if (!renderCleanup && typeof cleanup === 'function') {
                nextCleanup = cleanup;
            }
        } catch (e) {
            _renderRouteError(inner, e);
        } finally {
            if (window.UI && typeof UI.setActiveCleanupBag === 'function') {
                UI.setActiveCleanupBag(null);
            }
        }
        await _routeReadyPromise(inner);
        if (renderId !== renderSequence) {
            _cleanup(nextCleanup);
            return;
        }
        _swapMountedRoute(inner, renderId, nextCleanup, activePath);
    }

    function _updateActiveNav(path) {
        document.querySelectorAll('.nav-links a').forEach(a => {
            const route = a.getAttribute('data-route');
            let isActive = false;
            if (route === '/' && (path === '/ui' || path === '/ui/')) {
                isActive = true;
            } else if (route === '/protocols' && path.startsWith('/ui/protocol-runs')) {
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
