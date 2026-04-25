window.UI = (() => {
    const DEFAULT_PAGE_LIMIT = 25;
    const EVENT_PAGE_LIMIT = 50;
    let toastRegion = null;
    let activeCleanupBag = null;
    let artifactPreviewDelegationBound = false;
    const memoizedSignatures = new WeakMap();
    const dataCache = new Map();

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

    function compactMarkdownReferences(text) {
        const compacted = String(text || '').replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, label, href) => {
            const cleanLabel = String(label || '').trim();
            const cleanHref = String(href || '').trim();
            return cleanLabel || basenameDisplayPath(cleanHref) || cleanHref || match;
        });
        return compacted.replace(/\[([^\]]+)\]\([^,\s)]*/g, (match, label) =>
            String(label || '').trim() || match);
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

    function renderListRow({ href, label, sublabel, sublabelNode, badgeText, badgeClass, onClick, trailing, className, signature }) {
        const isLink = !!href;
        const isAction = !href && typeof onClick === 'function';
        const hasTrailing = trailing instanceof Node;
        const usePressableContainer = isAction && hasTrailing;
        const row = document.createElement(isLink ? 'a' : isAction && !usePressableContainer ? 'button' : 'div');
        row.className = [
            'list-row',
            isLink || isAction ? 'is-actionable' : 'is-passive',
            className || '',
        ].join(' ').trim();
        if (signature) {
            row.dataset.signature = signature;
        }
        if (isLink) {
            row.href = href;
        } else if (isAction && !usePressableContainer) {
            row.type = 'button';
        }
        if (usePressableContainer) {
            row.setAttribute('aria-label', [label, sublabel, badgeText].filter(Boolean).join(' · '));
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

        if (hasTrailing) {
            if (trailing.classList && trailing.classList.contains('artifact-action-row')) {
                row.classList.add('list-row-with-artifact-actions');
            }
            row.appendChild(trailing);
        }

        if (isAction) {
            const activate = (event) => {
                const target = event && event.target instanceof Element ? event.target : null;
                if (target && target !== row) {
                    const nestedInteractive = target.closest('a, button, input, textarea, select, summary, [role="button"], [data-artifact-preview-url]');
                    if (nestedInteractive && nestedInteractive !== row) return;
                }
                onClick(event);
            };
            if (usePressableContainer) {
                makePressable(row, activate);
            } else {
                row.addEventListener('click', activate);
            }
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

    function renderMetadataGrid(items, { compact = false } = {}) {
        const grid = document.createElement('div');
        grid.className = compact ? 'task-item-facts' : 'metadata-grid';
        for (const item of items || []) {
            if (!item) continue;
            const fact = document.createElement('div');
            fact.className = 'metadata-item';

            const label = document.createElement('span');
            label.textContent = String(item.label || '');
            fact.appendChild(label);

            const value = item.value;
            if (value instanceof Node) {
                fact.appendChild(value);
            } else {
                const strong = document.createElement('strong');
                strong.textContent = String(value || '');
                fact.appendChild(strong);
            }
            grid.appendChild(fact);
        }
        return grid;
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

    function _dialogFocusables(dialog) {
        return Array.from(
            dialog.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'),
        ).filter((el) => !el.disabled && el.tabIndex !== -1);
    }

    function showDialog(
        title,
        body,
        {
            actions = [],
            maxWidth = '560px',
            role = 'dialog',
            closeOnOverlay = true,
            initialFocus = null,
        } = {},
    ) {
        const previousFocus = document.activeElement;
        const overlay = document.createElement('div');
        overlay.className = 'confirm-overlay';

        const dialog = document.createElement('div');
        dialog.className = 'confirm-dialog';
        dialog.setAttribute('role', role);
        dialog.setAttribute('aria-modal', 'true');
        dialog.style.maxWidth = maxWidth;
        const titleId = `dialog-title-${Date.now()}`;
        dialog.setAttribute('aria-labelledby', titleId);

        const heading = document.createElement('h3');
        heading.id = titleId;
        heading.textContent = title;
        dialog.appendChild(heading);

        if (body instanceof Node || String(body || '').trim()) {
            const bodyWrap = document.createElement('div');
            bodyWrap.className = 'confirm-dialog-body';
            if (body instanceof Node) {
                bodyWrap.appendChild(body);
            } else {
                const text = document.createElement('p');
                text.textContent = String(body || '');
                bodyWrap.appendChild(text);
            }
            dialog.appendChild(bodyWrap);
        }

        if (actions.length) {
            const actionsEl = document.createElement('div');
            actionsEl.className = 'confirm-actions';
            actions.forEach((action) => {
                if (action instanceof Node) {
                    actionsEl.appendChild(action);
                }
            });
            dialog.appendChild(actionsEl);
        }

        function close() {
            overlay.remove();
            document.removeEventListener('keydown', keyHandler);
            if (previousFocus && typeof previousFocus.focus === 'function') previousFocus.focus();
        }

        overlay.appendChild(dialog);
        overlay.addEventListener('click', (event) => {
            if (closeOnOverlay && event.target === overlay) close();
        });
        document.body.appendChild(overlay);

        function keyHandler(e) {
            if (e.key === 'Escape') {
                close();
                return;
            }
            if (e.key !== 'Tab') return;
            const focusables = _dialogFocusables(dialog);
            if (!focusables.length) return;
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

        requestAnimationFrame(() => {
            if (initialFocus instanceof HTMLElement) {
                initialFocus.focus();
                return;
            }
            const focusables = _dialogFocusables(dialog);
            const target = focusables[0];
            if (target && typeof target.focus === 'function') {
                target.focus();
            }
        });

        return { overlay, dialog, close };
    }

    function showTextDialog(title, text, { maxWidth = '760px' } = {}) {
        const pre = document.createElement('pre');
        pre.className = 'event-pre';
        pre.style.whiteSpace = 'pre-wrap';
        pre.textContent = text;

        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'btn';
        closeBtn.textContent = 'Close';

        const view = showDialog(title, pre, {
            actions: [closeBtn],
            maxWidth,
        });
        closeBtn.addEventListener('click', () => view.close());
    }

    function _artifactPreviewErrorMessage(response, text) {
        let message = text || `HTTP ${response.status}`;
        try {
            const parsed = JSON.parse(text);
            const detail = parsed && typeof parsed === 'object' && parsed.detail && typeof parsed.detail === 'object'
                ? parsed.detail
                : parsed;
            if (detail && typeof detail === 'object') {
                message = detail.message || detail.error_code || message;
            }
        } catch (err) {
            void err;
        }
        return `${response.status}: ${message}`;
    }

    function _ensureArtifactPreviewDelegation() {
        if (artifactPreviewDelegationBound) return;
        artifactPreviewDelegationBound = true;
        document.addEventListener('click', async (event) => {
            const target = event.target instanceof Element
                ? event.target.closest('[data-artifact-preview-url]')
                : null;
            if (!(target instanceof HTMLElement)) return;
            const url = String(target.dataset.artifactPreviewUrl || '').trim();
            if (!url) return;
            event.preventDefault();
            event.stopPropagation();
            try {
                const response = await fetch(url, { credentials: 'same-origin' });
                const text = await response.text();
                if (!response.ok) {
                    throw new Error(_artifactPreviewErrorMessage(response, text));
                }
                showTextDialog(
                    target.dataset.artifactPreviewTitle || 'Artifact preview',
                    text,
                    { maxWidth: '920px' },
                );
            } catch (err) {
                reportError('Failed to preview the artifact', err, {
                    context: 'Artifact preview failed',
                });
            }
        });
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

    function dataSignature(value) {
        try {
            return JSON.stringify(value);
        } catch {
            return String(value);
        }
    }

    function joinDisplayPath(root, relativeOrAbsolute) {
        const value = String(relativeOrAbsolute || '').trim();
        if (!value) return '';
        if (value.startsWith('/')) return value;
        const prefix = String(root || '').trim().replace(/\/+$/, '');
        return prefix ? `${prefix}/${value}` : value;
    }

    function basenameDisplayPath(path) {
        const value = String(path || '').trim().replace(/\/+$/, '');
        if (!value) return '';
        const segments = value.split('/');
        return String(segments[segments.length - 1] || '').trim();
    }

    function isPreviewableFilePath(path) {
        return /\.(md|markdown|txt|log|json|jsonl|ya?ml|csv|tsv|py|js|mjs|cjs|ts|tsx|jsx|sh|sql|rb|go|java|rs|php)$/i.test(String(path || '').trim());
    }

    function generatedTimestamp(value) {
        const match = String(value || '').trim().match(/(?:^|[\s_-])(\d{10,})(?:\b|$)/);
        return match ? match[1] : '';
    }

    function isGeneratedTimestampName(value) {
        return Boolean(generatedTimestamp(value));
    }

    function isHumanAssignableCapabilityName(value) {
        const normalized = String(value || '').trim().toLowerCase();
        return Boolean(normalized)
            && normalized !== '*'
            && normalized !== 'rehearsal'
            && !isGeneratedOrRehearsalText(normalized);
    }

    function _recordFieldText(record, fields) {
        return fields
            .map((field) => String(record?.[field] || '').trim())
            .filter(Boolean)
            .join(' ');
    }

    function isGeneratedOrRehearsalText(value) {
        const normalized = String(value || '').trim().toLowerCase();
        if (!normalized) return false;
        const generatedWorkflowKeys = [
            'compose-assistant-protocol',
            'compose assistant protocol',
            'publish-report',
            'publish report',
            'live-authoring',
            'live authoring',
        ];
        const generatedWorkflowKey = generatedWorkflowKeys.some((item) =>
            normalized === item
            || normalized.startsWith(`${item} `)
            || normalized.includes(` ${item} `)
            || normalized.endsWith(` ${item}`));
        const looksLikeGeneratedVariant = (
            /^draft-[0-9a-f]{8}$/i.test(normalized)
            || (
                /[-_]\d{1,4}$/.test(normalized)
                && /\b(?:draft|protocol|analysis|approval|engineering|authoring|assistant|document|software)\b/.test(normalized.replace(/[-_]+/g, ' '))
            )
        );
        return normalized === 'rehearsal'
            || normalized === 'registry.rehearsal'
            || normalized.startsWith('rehearsal ')
            || normalized.includes(' rehearsal')
            || normalized.includes(' meta protocol composer ')
            || normalized.startsWith('meta protocol composer ')
            || generatedWorkflowKey
            || looksLikeGeneratedVariant
            || isGeneratedTimestampName(normalized);
    }

    function isDefaultHiddenRecord(record) {
        if (record == null) return false;
        if (typeof record !== 'object') {
            return isGeneratedOrRehearsalText(record);
        }
        if (record.is_rehearsal === true || record.rehearsal === true || record.is_generated === true) {
            return true;
        }
        const tags = Array.isArray(record.tags)
            ? record.tags.map((item) => String(item || '').trim().toLowerCase()).filter(Boolean)
            : [];
        if (tags.some((tag) => ['rehearsal', 'generated', 'test', 'system'].includes(tag))) {
            return true;
        }
        const source = [
            record.source_kind,
            record.entry_authority_ref,
            record.origin_channel,
            record.run_mode,
            record.bot_key,
            record.role,
        ].map((item) => String(item || '').trim().toLowerCase()).filter(Boolean);
        if (source.some((item) => (
            item === 'rehearsal'
            || item === 'registry.rehearsal'
            || item === 'generated'
            || item.includes('e2e')
            || item.includes('spec')
            || item.includes('test')
            || item.includes('audit')
            || item.endsWith('-ui')
        ))) {
            return true;
        }
        return isGeneratedOrRehearsalText(_recordFieldText(record, [
            'display_name',
            'name',
            'title',
            'slug',
            'protocol_id',
            'protocol_key',
            'protocol_display_name',
            'protocol_name',
            'conversation_title',
            'target_display_name',
            'target_agent_id',
            'origin_display_name',
            'origin_agent_id',
            'skill_name',
        ]));
    }

    function defaultVisibleRecords(records, { includeHidden = false } = {}) {
        const list = Array.isArray(records) ? records : [];
        return includeHidden ? list : list.filter((record) => !isDefaultHiddenRecord(record));
    }

    function compactGeneratedName(value, { stripUiOnly = false } = {}) {
        const original = String(value || '').trim();
        if (!original) return '';
        let label = original
            .replace(/(?:[\s_-]+)\d{10,}(?:\b|$)/g, '')
            .replace(/[-_\s]+\d{1,4}$/g, '')
            .replace(/^draft-[0-9a-f]{8}$/i, 'Generated draft')
            .replace(/[-_]+/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
        if (stripUiOnly) {
            label = label.replace(/^ui only\s+/i, '').trim();
        }
        return label || original;
    }

    function conversationHref(conversationId, {
        view = '',
        conversationType = '',
        operational = false,
    } = {}) {
        const normalizedId = String(conversationId || '').trim();
        if (!normalizedId) return '/ui/conversations';
        const url = new URL(`/ui/conversations/${encodeURIComponent(normalizedId)}`, window.location.origin);
        const normalizedView = String(view || '').trim();
        if (normalizedView === 'tasks' || normalizedView === 'activity') {
            url.searchParams.set('view', normalizedView);
        } else if (operational || String(conversationType || '').trim() === 'task_thread') {
            url.searchParams.set('view', 'tasks');
        }
        return `${url.pathname}${url.search}${url.hash}`;
    }

    function taskArtifactEvidence(task) {
        if (!task || typeof task !== 'object') return null;
        const request = task.request && typeof task.request === 'object' ? task.request : {};
        const result = task.result && typeof task.result === 'object' ? task.result : {};
        const internalContext = request.internal_context && typeof request.internal_context === 'object'
            ? request.internal_context
            : {};
        const contract = internalContext.protocol_stage_contract && typeof internalContext.protocol_stage_contract === 'object'
            ? internalContext.protocol_stage_contract
            : {};
        const expectedOutputs = Array.isArray(contract.output_artifacts) ? contract.output_artifacts : [];
        const recordedArtifacts = Array.isArray(result.artifacts) ? result.artifacts : [];
        if (!expectedOutputs.length && !recordedArtifacts.length) return null;
        return { expectedOutputs, recordedArtifacts };
    }

    function taskExpectedOutput(expectedOutputs = [], artifactKey = '') {
        const normalized = String(artifactKey || '').trim();
        if (!normalized) return null;
        return (expectedOutputs || []).find((item) => String(item?.artifact_key || '').trim() === normalized) || null;
    }

    function taskArtifactDisplayPath(task, artifact, expectedOutput = null) {
        return joinDisplayPath(task?.working_dir || '', expectedOutput?.path || artifact?.path || '');
    }

    function taskArtifactLabel(artifact, expectedOutput = null) {
        const declaredPath = String(expectedOutput?.path || artifact?.path || '').trim();
        return basenameDisplayPath(declaredPath) || String(artifact?.artifact_key || expectedOutput?.artifact_key || 'Artifact').trim();
    }

    function taskArtifactPreviewable(artifact, expectedOutput = null) {
        return isPreviewableFilePath(expectedOutput?.path || artifact?.path || '');
    }

    function createArtifactActionRow({
        previewable = false,
        onPreview = null,
        previewHref = '',
        previewTitle = 'Artifact preview',
        openHref = '',
        downloadHref = '',
        copyPathText = '',
        available = true,
        stopPropagation = true,
        copySuccessMessage = 'Artifact path copied.',
        copyErrorMessage = 'Failed to copy the artifact path.',
    } = {}) {
        const actionRow = document.createElement('div');
        actionRow.className = 'list-row-actions artifact-action-row';

        const stop = (event) => {
            if (!stopPropagation || !event) return;
            event.stopPropagation();
        };

        const previewUrl = String(previewHref || openHref || '').trim();
        if (available && previewable && (previewUrl || typeof onPreview === 'function')) {
            const previewBtn = previewUrl ? document.createElement('a') : document.createElement('button');
            if (previewUrl) {
                _ensureArtifactPreviewDelegation();
                previewBtn.href = previewUrl;
                previewBtn.setAttribute('role', 'button');
                previewBtn.dataset.artifactPreviewUrl = previewUrl;
                previewBtn.dataset.artifactPreviewTitle = String(previewTitle || 'Artifact preview');
            } else {
                previewBtn.type = 'button';
                previewBtn.dataset.artifactPreviewAction = 'true';
                previewBtn.addEventListener('click', (event) => {
                    stop(event);
                    void onPreview();
                });
            }
            previewBtn.className = 'btn btn-sm';
            previewBtn.textContent = 'Preview';
            actionRow.appendChild(previewBtn);
        }

        if (available && String(openHref || '').trim()) {
            const openLink = document.createElement('a');
            openLink.href = String(openHref || '').trim();
            openLink.className = 'btn btn-sm';
            openLink.target = '_blank';
            openLink.rel = 'noreferrer noopener';
            openLink.textContent = 'Open';
            openLink.addEventListener('click', stop);
            actionRow.appendChild(openLink);
        }

        if (available && String(downloadHref || '').trim()) {
            const downloadLink = document.createElement('a');
            downloadLink.href = String(downloadHref || '').trim();
            downloadLink.className = 'btn btn-sm';
            downloadLink.textContent = 'Download';
            downloadLink.addEventListener('click', stop);
            actionRow.appendChild(downloadLink);
        }

        if (available && String(copyPathText || '').trim()) {
            const copyBtn = document.createElement('button');
            copyBtn.type = 'button';
            copyBtn.className = 'btn btn-sm';
            copyBtn.textContent = 'Copy path';
            copyBtn.addEventListener('click', async (event) => {
                stop(event);
                try {
                    await copyText(String(copyPathText || ''), {
                        successMessage: copySuccessMessage,
                        errorMessage: copyErrorMessage,
                    });
                } catch (err) {
                    void err;
                }
            });
            actionRow.appendChild(copyBtn);
        }

        return actionRow;
    }

    function createArtifactListRow({
        label,
        sublabel = '',
        sublabelParts = [],
        badgeText = '',
        badgeClass = '',
        actionRow = null,
        className = '',
        signature = '',
    } = {}) {
        const trailing = actionRow instanceof Node ? actionRow : null;
        const previewTarget = trailing
            ? trailing.querySelector('[data-artifact-preview-url], [data-artifact-preview-action]')
            : null;
        const parts = Array.isArray(sublabelParts)
            ? sublabelParts
            : String(sublabelParts || '').trim()
                ? [sublabelParts]
                : [];
        return renderListRow({
            label,
            sublabel: sublabel || parts.filter(Boolean).join(' · '),
            badgeText,
            badgeClass,
            trailing,
            className: ['artifact-list-row', className || ''].join(' ').trim(),
            signature,
            onClick: previewTarget
                ? () => previewTarget.click()
                : null,
        });
    }


    function _cloneCachedValue(value) {
        if (typeof structuredClone === 'function') {
            try {
                return structuredClone(value);
            } catch {
                // Fall through to JSON cloning for plain data payloads.
            }
        }
        try {
            return JSON.parse(JSON.stringify(value));
        } catch {
            return value;
        }
    }

    function peekCachedData(key, { allowExpired = true } = {}) {
        const normalizedKey = String(key || '').trim();
        if (!normalizedKey) return null;
        const entry = dataCache.get(normalizedKey);
        if (!entry || entry.error) {
            return null;
        }
        const fresh = entry.expiresAt > Date.now();
        if (!allowExpired && !fresh) {
            return null;
        }
        return _cloneCachedValue(entry.value);
    }

    async function loadCachedData(key, loader, { ttlMs = 30000, errorTtlMs = 5000, forceRefresh = false } = {}) {
        const normalizedKey = String(key || '').trim();
        if (!normalizedKey) {
            return loader();
        }
        const now = Date.now();
        const entry = dataCache.get(normalizedKey);
        if (!forceRefresh && entry && !entry.error && entry.expiresAt > now) {
            return _cloneCachedValue(entry.value);
        }
        if (!forceRefresh && entry && entry.error && entry.expiresAt > now) {
            throw entry.error;
        }
        if (entry && entry.inflight) {
            const result = await entry.inflight;
            return _cloneCachedValue(result);
        }
        const inflight = Promise.resolve().then(loader);
        const pending = {
            expiresAt: 0,
            value: null,
            error: null,
            inflight,
        };
        dataCache.set(normalizedKey, pending);
        try {
            const value = await inflight;
            if (dataCache.get(normalizedKey) === pending) {
                dataCache.set(normalizedKey, {
                    expiresAt: Date.now() + Math.max(0, ttlMs),
                    value: _cloneCachedValue(value),
                    error: null,
                    inflight: null,
                });
            }
            return _cloneCachedValue(value);
        } catch (error) {
            if (dataCache.get(normalizedKey) === pending) {
                dataCache.set(normalizedKey, {
                    expiresAt: Date.now() + Math.max(0, errorTtlMs),
                    value: null,
                    error,
                    inflight: null,
                });
            }
            throw error;
        }
    }

    function invalidateCachedData(prefixes) {
        const values = Array.isArray(prefixes) ? prefixes : [prefixes];
        values
            .map((value) => String(value || '').trim())
            .filter(Boolean)
            .forEach((prefix) => {
                Array.from(dataCache.keys()).forEach((key) => {
                    if (key === prefix || key.startsWith(prefix)) {
                        dataCache.delete(key);
                    }
                });
            });
    }

    function subscribeWithRefresh(cleanups, topic, loader, delay = 350) {
        let timer = null;
        const unsub = WS.subscribe(topic, () => {
            if (isBackgrounded()) return;
            clearTimeout(timer);
            timer = setTimeout(() => {
                void loader();
            }, delay);
        });
        const dispose = () => {
            clearTimeout(timer);
            if (typeof unsub === 'function') {
                unsub();
            }
        };
        if (cleanups && typeof cleanups.add === 'function') {
            cleanups.add(dispose);
        }
        return dispose;
    }

    function createSegmentedControl(options, onChange, { label = '', value = '' } = {}) {
        const group = document.createElement('div');
        group.className = 'segmented-control';
        group.setAttribute('role', 'tablist');
        if (label) {
            group.setAttribute('aria-label', label);
        }
        const buttons = new Map();

        function setActive(nextValue) {
            const normalizedValue = String(nextValue ?? '');
            group.querySelectorAll('.segmented-control-btn').forEach((btn) => {
                const active = String(btn.dataset.value || '') === normalizedValue;
                btn.classList.toggle('active', active);
                btn.setAttribute('aria-selected', String(active));
                btn.tabIndex = active ? 0 : -1;
            });
        }

        function applyValue(nextValue, target = null) {
            const normalizedValue = String(nextValue ?? '');
            setActive(normalizedValue);
            if (typeof onChange === 'function') {
                const match = (options || []).find((option) => String(option.value ?? '') === normalizedValue) || null;
                onChange(normalizedValue, match, target);
            }
        }

        (options || []).forEach((option, index) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'segmented-control-btn';
            btn.dataset.key = String(option.key ?? option.value ?? option.label ?? index);
            btn.dataset.value = String(option.value ?? '');
            btn.textContent = String(option.label ?? option.value ?? '');
            btn.setAttribute('role', 'tab');
            if (option.id) btn.id = option.id;
            if (option.controls) btn.setAttribute('aria-controls', option.controls);
            if (option.title) btn.title = option.title;
            btn.addEventListener('click', () => {
                applyValue(btn.dataset.value || '', btn);
            });
            group.appendChild(btn);
            buttons.set(String(option.value ?? ''), btn);
        });

        bindSegmentedControlKeyboard(group, (target) => {
            applyValue(target.dataset.value || '', target);
        });
        setActive(value);

        return { element: group, setActive, buttons };
    }

    function createCursorPaginator(container, loadFn, { initialCursor = 0, initialStack = [], onChange = null } = {}) {
        let cursor = initialCursor;
        let cursorStack = Array.isArray(initialStack) ? initialStack.slice() : [];

        function emitChange() {
            if (typeof onChange === 'function') {
                onChange({ cursor, hasPrev: cursorStack.length > 0, stackLength: cursorStack.length });
            }
        }

        function reset(nextCursor = initialCursor) {
            cursor = nextCursor;
            cursorStack = [];
            emitChange();
        }

        function clear() {
            reconcileChildren(container, []);
        }

        function render({ hasMore = false, nextCursor = 0, info = '' } = {}) {
            const wrapper = document.createElement('div');
            renderPagination(wrapper, {
                hasPrev: cursorStack.length > 0,
                hasNext: !!hasMore,
                info,
                onPrev: () => {
                    const previousCursor = cursorStack.pop();
                    cursor = previousCursor === undefined ? initialCursor : previousCursor;
                    emitChange();
                    loadFn();
                },
                onNext: () => {
                    cursorStack.push(cursor);
                    cursor = nextCursor;
                    emitChange();
                    loadFn();
                },
            });
            reconcileChildren(container, Array.from(wrapper.childNodes));
        }

        return {
            get cursor() {
                return cursor;
            },
            get hasPrev() {
                return cursorStack.length > 0;
            },
            get stackLength() {
                return cursorStack.length;
            },
            reset,
            clear,
            render,
        };
    }

    function _buildSignatureValue(data, { signatureFn, signatureFields, timestampFields = [] } = {}) {
        if (typeof signatureFn === 'function') {
            return signatureFn(data);
        }
        if (!Array.isArray(signatureFields) || !signatureFields.length || !data || typeof data !== 'object') {
            return data;
        }
        const normalized = {};
        signatureFields.forEach((field) => {
            if (!field) return;
            const raw = data[field];
            normalized[field] = timestampFields.includes(field) ? relativeTime(raw) : raw;
        });
        return normalized;
    }

    function memoizedRender(container, data, renderFn, options = {}) {
        const signature = dataSignature(_buildSignatureValue(data, options));
        if (memoizedSignatures.get(container) === signature) {
            return { changed: false, signature };
        }
        const rendered = renderFn(data);
        const nodes = Array.isArray(rendered)
            ? rendered
            : rendered
                ? [rendered]
                : [];
        reconcileChildren(container, nodes);
        memoizedSignatures.set(container, signature);
        return { changed: true, signature };
    }

    function clearMemoizedRender(container) {
        if (!container || (typeof container !== 'object' && typeof container !== 'function')) {
            return;
        }
        memoizedSignatures.delete(container);
    }

    function createTaskActionButtons(taskId, conversationId, status, onComplete, {
        cancelLabel = 'Cancel',
        retryLabel = 'Retry',
    } = {}) {
        const actions = document.createElement('div');
        actions.className = 'task-action-row';
        const statusText = document.createElement('span');
        statusText.className = 'task-action-status';
        actions.appendChild(statusText);

        async function perform(button, action, pendingText, successText, failureText) {
            button.disabled = true;
            statusText.textContent = pendingText;
            try {
                await API.conversationAction(conversationId, action, { routed_task_id: taskId });
                statusText.textContent = successText;
                if (typeof onComplete === 'function') {
                    onComplete({ action, ok: true, statusText, actions });
                }
            } catch (err) {
                button.disabled = false;
                statusText.textContent = failureText;
                reportError(
                    action === 'cancel_task' ? 'Failed to cancel the task' : 'Failed to retry the task',
                    err,
                    { context: action === 'cancel_task' ? 'Task cancel failed' : 'Task retry failed' },
                );
                if (typeof onComplete === 'function') {
                    onComplete({ action, ok: false, statusText, actions, error: err });
                }
            }
        }

        if (taskId && conversationId && ['queued', 'submitted', 'leased', 'running'].includes(status || '')) {
            const cancelBtn = document.createElement('button');
            cancelBtn.type = 'button';
            cancelBtn.className = 'btn btn-sm btn-danger';
            cancelBtn.textContent = cancelLabel;
            cancelBtn.addEventListener('click', (event) => {
                if (event) {
                    event.preventDefault();
                    event.stopPropagation();
                }
                void perform(cancelBtn, 'cancel_task', 'Cancelling…', 'Cancel requested.', 'Cancel failed.');
            });
            actions.appendChild(cancelBtn);
        }

        if (taskId && conversationId && ['failed', 'cancelled', 'timed_out'].includes(status || '')) {
            const retryBtn = document.createElement('button');
            retryBtn.type = 'button';
            retryBtn.className = 'btn btn-sm';
            retryBtn.textContent = retryLabel;
            retryBtn.addEventListener('click', (event) => {
                if (event) {
                    event.preventDefault();
                    event.stopPropagation();
                }
                void perform(retryBtn, 'retry_task', 'Retrying…', 'Retry queued.', 'Retry failed.');
            });
            actions.appendChild(retryBtn);
        }

        return { element: actions, statusText };
    }

    function createAgentManagementDropdown(
        agents,
        selectedId,
        onChange,
        { label = 'Managed bot', allowEmpty = false, emptyLabel = 'Choose a bot' } = {},
    ) {
        const select = document.createElement('select');
        select.className = 'search-input';
        select.setAttribute('aria-label', label);
        select.addEventListener('change', () => {
            if (typeof onChange === 'function') {
                onChange(select.value);
            }
        });

        function update(nextAgents, nextSelectedId) {
            const options = [];
            if (allowEmpty) {
                const placeholder = document.createElement('option');
                placeholder.value = '';
                placeholder.textContent = emptyLabel;
                options.push(placeholder);
            }
            options.push(...(nextAgents || []).map((agent) => {
                const option = document.createElement('option');
                option.value = agent.agent_id || '';
                option.textContent = visibleLabel(agent.display_name, agent.agent_id) || agent.slug || agent.agent_id || 'Bot';
                return option;
            }));
            reconcileChildren(select, options);
            select.disabled = allowEmpty ? options.length <= 1 : options.length <= 1;
            const targetValue = String(nextSelectedId || '');
            if (targetValue && options.some((option) => option.value === targetValue)) {
                select.value = targetValue;
            } else if (allowEmpty) {
                select.value = '';
            } else if (options.length) {
                select.value = options[0].value;
            } else {
                select.value = '';
            }
        }

        update(agents, selectedId);
        return { element: select, update };
    }

    function filterManagedAgents(agents, capability = '') {
        return (agents || []).filter((agent) => {
            const connectivity = String(agent.connectivity_state || '').trim();
            const capabilities = Array.isArray(agent.management_capabilities)
                ? agent.management_capabilities
                : [];
            return ['connected', 'degraded'].includes(connectivity)
                && (!capability || capabilities.includes(capability));
        });
    }

    async function copyText(text, {
        successMessage = 'Copied to clipboard.',
        errorMessage = 'Copy failed.',
    } = {}) {
        const value = String(text || '');
        if (!value) {
            throw new Error('Nothing to copy.');
        }
        if (!navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') {
            throw new Error('Clipboard access unavailable.');
        }
        try {
            await navigator.clipboard.writeText(value);
            if (successMessage) notify(successMessage, 'success');
            return true;
        } catch (err) {
            if (errorMessage) reportError(errorMessage, err, { context: 'Clipboard write failed' });
            throw err;
        }
    }

    function filterProtocolRunAgents(agents) {
        return filterManagedAgents(agents);
    }

    function buildConversationTypeBadge(value) {
        const conversationType = typeof value === 'string'
            ? value
            : String((value && value.conversation_type) || 'conversation');
        if (conversationType !== 'task_thread') {
            return null;
        }
        const badge = document.createElement('span');
        badge.className = 'badge badge-task-thread';
        badge.textContent = 'Delegation thread';
        return badge;
    }

    function isBackgrounded() {
        return typeof document !== 'undefined' && Boolean(document.hidden);
    }

    function _morphOptions() {
        return {
            childrenOnly: true,
            getNodeKey(node) {
                if (!(node instanceof Element)) return undefined;
                return (node.dataset && node.dataset.key) || node.id || undefined;
            },
            onBeforeElUpdated(fromEl, toEl) {
                if (
                    fromEl instanceof Element
                    && toEl instanceof Element
                    && fromEl.dataset
                    && toEl.dataset
                    && fromEl.dataset.signature
                    && fromEl.dataset.signature === toEl.dataset.signature
                ) {
                    return false;
                }
                return true;
            },
        };
    }

    function reconcileElement(container, nextNode) {
        if (!(container instanceof Element) || !(nextNode instanceof Element)) return;
        if (typeof morphdom !== 'function') {
            container.replaceWith(nextNode);
            return;
        }
        morphdom(container, nextNode, _morphOptions());
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
        morphdom(container, target, _morphOptions());
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
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'btn';
        cancelBtn.textContent = 'Cancel';

        const confirmBtn = document.createElement('button');
        confirmBtn.type = 'button';
        confirmBtn.className = 'btn btn-primary';
        confirmBtn.textContent = 'Confirm';

        const view = showDialog(title, message, {
            actions: [cancelBtn, confirmBtn],
            role: 'alertdialog',
            initialFocus: confirmBtn,
        });
        cancelBtn.addEventListener('click', close);
        confirmBtn.addEventListener('click', async () => {
            view.close();
            await onConfirm();
        });
        function close() {
            view.close();
        }
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
        joinDisplayPath,
        basenameDisplayPath,
        isPreviewableFilePath,
        generatedTimestamp,
        isGeneratedTimestampName,
        isHumanAssignableCapabilityName,
        isGeneratedOrRehearsalText,
        isDefaultHiddenRecord,
        defaultVisibleRecords,
        compactGeneratedName,
        conversationHref,
        taskArtifactEvidence,
        taskExpectedOutput,
        taskArtifactDisplayPath,
        taskArtifactLabel,
        taskArtifactPreviewable,
        createArtifactActionRow,
        createArtifactListRow,
        compactMarkdownReferences,
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
        renderMetadataGrid,
        isOpaqueIdentifier,
        visibleLabel,
        renderPagination,
        dataSignature,
        peekCachedData,
        loadCachedData,
        invalidateCachedData,
        subscribeWithRefresh,
        createSegmentedControl,
        createCursorPaginator,
        memoizedRender,
        clearMemoizedRender,
        createTaskActionButtons,
        createAgentManagementDropdown,
        filterManagedAgents,
        filterProtocolRunAgents,
        buildConversationTypeBadge,
        isBackgrounded,
        reconcileChildren,
        reconcileElement,
        bindSegmentedControlKeyboard,
        createErrorCard,
        renderError,
        showDialog,
        showConfirm,
        showTextDialog,
        copyText,
    };
})();
