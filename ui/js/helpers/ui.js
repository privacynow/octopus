window.UI = (() => {
    const DEFAULT_PAGE_LIMIT = 25;
    const EVENT_PAGE_LIMIT = 50;
    let toastRegion = null;
    let activeCleanupBag = null;

    function esc(str) {
        if (str === null || str === undefined) return '';
        const div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }

    function renderContent(text) {
        if (!text) return '';
        if (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined') {
            return DOMPurify.sanitize(marked.parse(text));
        }
        return esc(text).replace(/\n/g, '<br>');
    }

    function relativeTime(iso) {
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

    function formatTime(iso) {
        if (!iso) return '';
        try {
            const d = new Date(iso);
            return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        } catch {
            return iso;
        }
    }

    function formatApprovalTime(iso) {
        try {
            return new Date(iso).toLocaleString();
        } catch {
            return iso;
        }
    }

    function safeFilename(value, fallback = 'export') {
        const raw = String(value || fallback).trim();
        const cleaned = raw
            .replace(/[\\/:*?"<>|]+/g, '-')
            .replace(/\s+/g, '-')
            .replace(/-+/g, '-')
            .replace(/^-|-$/g, '');
        return cleaned || fallback;
    }

    function readQueryParam(name, fallback = '') {
        try {
            const url = new URL(window.location.href);
            return url.searchParams.get(name) || fallback;
        } catch {
            return fallback;
        }
    }

    function updateQueryParams(updates, { replace = true } = {}) {
        try {
            const url = new URL(window.location.href);
            Object.entries(updates || {}).forEach(([key, value]) => {
                if (value === undefined || value === null || value === '') {
                    url.searchParams.delete(key);
                } else {
                    url.searchParams.set(key, String(value));
                }
            });
            const next = `${url.pathname}${url.search}${url.hash}`;
            if (replace) {
                history.replaceState(null, '', next);
            } else {
                history.pushState(null, '', next);
            }
        } catch (e) {
            console.warn('Failed to update query params', e);
        }
    }

    function _getToastRegion() {
        if (toastRegion && document.body.contains(toastRegion)) return toastRegion;
        toastRegion = document.getElementById('toast-region');
        if (toastRegion) return toastRegion;
        toastRegion = document.createElement('div');
        toastRegion.id = 'toast-region';
        toastRegion.className = 'toast-region';
        toastRegion.setAttribute('aria-live', 'polite');
        toastRegion.setAttribute('aria-atomic', 'false');
        document.body.appendChild(toastRegion);
        return toastRegion;
    }

    function notify(message, tone = 'info', { timeout = 5000 } = {}) {
        if (!message) return;
        const region = _getToastRegion();
        const toast = document.createElement('div');
        toast.className = ['toast', `toast-${tone}`].join(' ');
        toast.setAttribute('role', tone === 'danger' ? 'alert' : 'status');

        const text = document.createElement('span');
        text.className = 'toast-message';
        text.textContent = message;
        toast.appendChild(text);

        const close = document.createElement('button');
        close.type = 'button';
        close.className = 'toast-close';
        close.setAttribute('aria-label', 'Dismiss notification');
        close.textContent = '×';
        close.addEventListener('click', () => toast.remove());
        toast.appendChild(close);

        region.appendChild(toast);
        if (timeout > 0) {
            window.setTimeout(() => {
                if (toast.isConnected) toast.remove();
            }, timeout);
        }
    }

    function reportError(message, error, { context = '' } = {}) {
        const errText = error && error.message ? error.message : String(error || '');
        const userMessage = errText && errText !== message ? `${message}: ${errText}` : message;
        notify(userMessage, 'danger');
        if (context) {
            console.error(context, error);
        } else {
            console.error(userMessage, error);
        }
    }

    function createCleanupBag() {
        const fns = [];
        let flushed = false;
        return {
            add(fn) {
                if (typeof fn === 'function' && !flushed) fns.push(fn);
                return fn;
            },
            flush() {
                if (flushed) return;
                flushed = true;
                while (fns.length) {
                    const fn = fns.pop();
                    try {
                        if (typeof fn === 'function') fn();
                    } catch (e) {
                        console.error('Cleanup error', e);
                    }
                }
            },
        };
    }

    function setActiveCleanupBag(bag) {
        activeCleanupBag = bag || null;
    }

    function beginCleanupScope() {
        const bag = createCleanupBag();
        if (activeCleanupBag) {
            activeCleanupBag.add(() => bag.flush());
        }
        return bag;
    }

    function makePressable(el, onActivate) {
        if (!el) return;
        el.tabIndex = 0;
        el.setAttribute('role', 'button');
        el.addEventListener('click', onActivate);
        el.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onActivate(e);
            }
        });
    }

    function renderListRow({ href, label, sublabel, sublabelNode, badgeText, badgeClass, onClick, trailing, className }) {
        const isLink = !!href;
        const isAction = !href && typeof onClick === 'function';
        const row = document.createElement(isLink ? 'a' : isAction ? 'button' : 'div');
        row.className = ['list-row', className || ''].join(' ').trim();
        if (isLink) {
            row.href = href;
        } else if (isAction) {
            row.type = 'button';
        }

        const main = document.createElement('div');
        main.className = 'list-row-main';

        const title = document.createElement('span');
        title.className = 'list-row-label';
        title.textContent = label;
        main.appendChild(title);

        if (sublabelNode) {
            const sub = document.createElement('span');
            sub.className = 'list-row-sublabel';
            sub.appendChild(sublabelNode);
            main.appendChild(sub);
        } else if (sublabel) {
            const sub = document.createElement('span');
            sub.className = 'list-row-sublabel';
            sub.textContent = sublabel;
            main.appendChild(sub);
        }

        row.appendChild(main);

        if (badgeText) {
            const badge = document.createElement('span');
            badge.className = ['badge', badgeClass || ''].join(' ').trim();
            badge.textContent = badgeText;
            row.appendChild(badge);
        }

        if (trailing instanceof Node) {
            row.appendChild(trailing);
        }

        if (isAction) {
            row.addEventListener('click', onClick);
        }

        return row;
    }

    function renderSettingsRow({ label, sublabel, control, className }) {
        const row = document.createElement('div');
        row.className = ['settings-row', className || ''].join(' ').trim();

        const main = document.createElement('div');
        main.className = 'settings-row-main';

        const title = document.createElement('div');
        title.className = 'settings-row-label';
        title.textContent = label;
        main.appendChild(title);

        if (sublabel) {
            const sub = document.createElement('div');
            sub.className = 'settings-row-sublabel';
            sub.textContent = sublabel;
            main.appendChild(sub);
        }

        row.appendChild(main);
        if (control instanceof Node) row.appendChild(control);
        return row;
    }

    function renderEmptyState(message, compact = false) {
        const el = document.createElement('div');
        el.className = compact ? 'empty-state empty-state-compact' : 'empty-state';
        el.textContent = message;
        return el;
    }

    function isOpaqueIdentifier(value) {
        const text = String(value || '').trim();
        if (!text) return false;
        if (/^[0-9a-f]{24,}$/i.test(text)) return true;
        if (/^[0-9a-f]{8,}-[0-9a-f-]{12,}$/i.test(text)) return true;
        if (text.length >= 24 && !/[A-Z]/.test(text) && /^[a-z0-9._:-]+$/i.test(text)) return true;
        return false;
    }

    function visibleLabel(...candidates) {
        for (const candidate of candidates) {
            const text = String(candidate || '').trim();
            if (!text || isOpaqueIdentifier(text)) continue;
            return text;
        }
        return '';
    }

    function renderStatCard({ value, label, detail = '', href = '' }) {
        const card = document.createElement(href ? 'a' : 'div');
        card.className = 'stat-card';
        if (href) {
            card.href = href;
        }

        const valueEl = document.createElement('div');
        valueEl.className = 'stat-card-value';
        valueEl.textContent = value;
        card.appendChild(valueEl);

        const labelEl = document.createElement('div');
        labelEl.className = 'stat-card-label';
        labelEl.textContent = label;
        card.appendChild(labelEl);

        if (detail) {
            const detailEl = document.createElement('div');
            detailEl.className = 'stat-card-detail';
            detailEl.textContent = detail;
            card.appendChild(detailEl);
        }

        return card;
    }

    function createSkeletonNodes(count, type) {
        const cls = type === 'row' ? 'skeleton skeleton-row' : 'skeleton skeleton-card';
        return Array.from({ length: count }, (_, index) => {
            const div = document.createElement('div');
            div.className = cls;
            div.dataset.key = `skeleton-${type}-${index}`;
            return div;
        });
    }

    function renderSkeletons(container, count, type) {
        createSkeletonNodes(count, type).forEach((node) => container.appendChild(node));
    }

    function createErrorCard(message, retryFn) {
        const card = document.createElement('div');
        card.className = 'error-card';
        card.dataset.key = `error-${safeFilename(message || 'error')}`;
        const p = document.createElement('p');
        p.textContent = message;
        card.appendChild(p);
        if (retryFn) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-primary';
            btn.textContent = 'Retry';
            btn.addEventListener('click', retryFn);
            card.appendChild(btn);
        }
        return card;
    }

    function renderPagination(container, { hasPrev, hasNext, onPrev, onNext, info }) {
        if (!hasPrev && !hasNext && !String(info || '').trim()) {
            return;
        }
        const nav = document.createElement('nav');
        nav.className = 'pagination';
        nav.setAttribute('aria-label', 'Pagination');

        const prevBtn = document.createElement('button');
        prevBtn.type = 'button';
        prevBtn.className = 'btn btn-sm';
        prevBtn.textContent = 'Previous';
        prevBtn.disabled = !hasPrev;
        if (hasPrev) prevBtn.addEventListener('click', onPrev);

        const infoSpan = document.createElement('span');
        infoSpan.className = 'page-info';
        infoSpan.textContent = info || '';

        const nextBtn = document.createElement('button');
        nextBtn.type = 'button';
        nextBtn.className = 'btn btn-sm';
        nextBtn.textContent = 'Next';
        nextBtn.disabled = !hasNext;
        if (hasNext) nextBtn.addEventListener('click', onNext);

        nav.appendChild(prevBtn);
        nav.appendChild(infoSpan);
        nav.appendChild(nextBtn);
        container.appendChild(nav);
    }

    function reconcileChildren(container, nextNodes) {
        const target = container.cloneNode(false);
        Array.from(nextNodes || []).forEach((node) => {
            target.appendChild(node);
        });
        if (typeof morphdom !== 'function') {
            container.replaceChildren(...Array.from(target.childNodes));
            return;
        }
        morphdom(container, target, {
            childrenOnly: true,
            getNodeKey(node) {
                if (!(node instanceof Element)) return undefined;
                return (node.dataset && node.dataset.key) || node.id || undefined;
            },
        });
    }

    function bindSegmentedControlKeyboard(group, onActivate) {
        if (!(group instanceof Element)) return;
        group.addEventListener('keydown', (e) => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
            const tabs = Array.from(group.querySelectorAll('[role="tab"]'));
            if (!tabs.length) return;
            const currentIndex = tabs.indexOf(document.activeElement);
            if (currentIndex < 0) return;
            e.preventDefault();

            let nextIndex = currentIndex;
            if (e.key === 'Home') {
                nextIndex = 0;
            } else if (e.key === 'End') {
                nextIndex = tabs.length - 1;
            } else {
                const delta = e.key === 'ArrowRight' ? 1 : -1;
                nextIndex = (currentIndex + delta + tabs.length) % tabs.length;
            }

            const target = tabs[nextIndex];
            if (!target) return;
            target.focus();
            if (typeof onActivate === 'function') {
                onActivate(target);
            } else {
                target.click();
            }
            requestAnimationFrame(() => {
                if (target.isConnected && typeof target.focus === 'function') {
                    target.focus();
                }
            });
        });
    }

    function renderError(container, message, retryFn) {
        container.appendChild(createErrorCard(message, retryFn));
    }

    function showConfirm(title, message, onConfirm) {
        const previousFocus = document.activeElement;
        const overlay = document.createElement('div');
        overlay.className = 'confirm-overlay';

        const dialog = document.createElement('div');
        dialog.className = 'confirm-dialog';
        dialog.setAttribute('role', 'alertdialog');
        dialog.setAttribute('aria-modal', 'true');

        const titleId = `confirm-title-${Date.now()}`;
        dialog.setAttribute('aria-labelledby', titleId);

        const h3 = document.createElement('h3');
        h3.id = titleId;
        h3.textContent = title;
        dialog.appendChild(h3);

        const p = document.createElement('p');
        p.textContent = message;
        dialog.appendChild(p);

        const actions = document.createElement('div');
        actions.className = 'confirm-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn';
        cancelBtn.textContent = 'Cancel';

        const confirmBtn = document.createElement('button');
        confirmBtn.type = 'button';
        confirmBtn.className = 'btn btn-primary';
        confirmBtn.textContent = 'Confirm';

        function close() {
            overlay.remove();
            document.removeEventListener('keydown', keyHandler);
            if (previousFocus && typeof previousFocus.focus === 'function') previousFocus.focus();
        }

        cancelBtn.addEventListener('click', close);
        confirmBtn.addEventListener('click', async () => {
            close();
            await onConfirm();
        });

        actions.appendChild(cancelBtn);
        actions.appendChild(confirmBtn);
        dialog.appendChild(actions);
        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        const focusables = [cancelBtn, confirmBtn];
        confirmBtn.focus();

        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) close();
        });

        function keyHandler(e) {
            if (e.key === 'Escape') {
                close();
                return;
            }
            if (e.key !== 'Tab') return;
            const currentIndex = focusables.indexOf(document.activeElement);
            if (e.shiftKey) {
                if (currentIndex <= 0) {
                    e.preventDefault();
                    focusables[focusables.length - 1].focus();
                }
                return;
            }
            if (currentIndex === focusables.length - 1) {
                e.preventDefault();
                focusables[0].focus();
            }
        }

        document.addEventListener('keydown', keyHandler);
    }

    return {
        DEFAULT_PAGE_LIMIT,
        EVENT_PAGE_LIMIT,
        esc,
        renderContent,
        relativeTime,
        formatTime,
        formatApprovalTime,
        safeFilename,
        readQueryParam,
        updateQueryParams,
        notify,
        reportError,
        createCleanupBag,
        setActiveCleanupBag,
        beginCleanupScope,
        makePressable,
        renderListRow,
        renderSettingsRow,
        renderEmptyState,
        renderStatCard,
        isOpaqueIdentifier,
        visibleLabel,
        createSkeletonNodes,
        renderSkeletons,
        renderPagination,
        reconcileChildren,
        bindSegmentedControlKeyboard,
        createErrorCard,
        renderError,
        showConfirm,
    };
})();
