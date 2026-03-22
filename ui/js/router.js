/**
 * Minimal SPA router using history.pushState.
 * Routes map URL patterns to component render functions.
 */
const Router = (() => {
    const routes = [];
    let contentEl = null;

    function register(pattern, render) {
        // Convert /ui/agents/:id to regex
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
        // Strip trailing slash (except root)
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
        contentEl.innerHTML = '<div class="empty-state">Page not found</div>';
    }

    function _render(renderFn, params) {
        if (!contentEl) contentEl = document.getElementById('content');
        contentEl.innerHTML = '';
        renderFn(contentEl, params);
    }

    function _updateActiveNav(path) {
        document.querySelectorAll('.nav-links a').forEach(a => {
            const route = a.getAttribute('data-route');
            if (route === '/' && (path === '/ui' || path === '/ui/')) {
                a.classList.add('active');
            } else if (route && route !== '/' && path.startsWith('/ui' + route)) {
                a.classList.add('active');
            } else {
                a.classList.remove('active');
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
