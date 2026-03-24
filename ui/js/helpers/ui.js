window.UI = (() => {
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

    function renderStatCard({ value, label, detail = '' }) {
        const card = document.createElement('div');
        card.className = 'stat-card';

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

    function renderSkeletons(container, count, type) {
        const cls = type === 'row' ? 'skeleton skeleton-row' : 'skeleton skeleton-card';
        for (let i = 0; i < count; i++) {
            const div = document.createElement('div');
            div.className = cls;
            container.appendChild(div);
        }
    }

    function renderPagination(container, { hasPrev, hasNext, onPrev, onNext, info }) {
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

    function renderError(container, message, retryFn) {
        const card = document.createElement('div');
        card.className = 'error-card';
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
        container.appendChild(card);
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
        esc,
        renderContent,
        relativeTime,
        formatTime,
        formatApprovalTime,
        makePressable,
        renderListRow,
        renderSettingsRow,
        renderEmptyState,
        renderStatCard,
        renderSkeletons,
        renderPagination,
        renderError,
        showConfirm,
    };
})();
