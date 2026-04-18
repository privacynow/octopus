/*
 * Authoring kit — shared UI primitives for authoring surfaces.
 *
 * Contract and invariants live in telegram-agent-bot/protocol_kit_plan.md §7.
 * Consumers must prefer kit primitives over bespoke ones; the acceptance
 * gate (plan §9) flags new bespoke variants of any concern covered here.
 *
 * All primitives build on window.UI helpers. This file depends on helpers/ui.js
 * being loaded first (see index.html script order).
 */
window.Kit = (() => {
    // -----------------------------------------------------------------------
    // Dictionary — plain-language labels, help text, empty/first-run copy.
    //
    // Every user-facing string in authoring UIs must resolve through this
    // dictionary. Missing entries are visible as `[key]` so that the lint /
    // acceptance-gate step can flag them.
    // -----------------------------------------------------------------------
    const DICT = {
        // Protocol — record fields
        'protocol.display_name.label': 'Name',
        'protocol.display_name.help': 'Human-readable name for this protocol. You can change it later.',
        'protocol.display_name.placeholder': 'e.g. Pull request review',

        'protocol.slug.label': 'URL slug',
        'protocol.slug.help': 'Short identifier used in URLs. Auto-suggested from the name once you enter one.',
        'protocol.slug.placeholder': 'pull-request-review',

        'protocol.description.label': 'Description',
        'protocol.description.help': 'Optional. What this protocol is for and when to use it.',
        'protocol.description.placeholder': 'Describe the workflow and when to run it…',

        // Protocol — lifecycle
        'protocol.lifecycle.draft': 'Draft',
        'protocol.lifecycle.published': 'Published',
        'protocol.lifecycle.archived': 'Archived',
        'protocol.lifecycle.filter.all': 'All',

        // Protocol — actions
        'protocol.action.validate': 'Validate',
        'protocol.action.publish': 'Publish',
        'protocol.action.archive': 'Archive',
        'protocol.action.discard': 'Delete draft',
        'protocol.action.rehearse': 'Rehearse',

        // Protocol — rehearsal panel
        'protocol.rehearsal.panel.title': 'Rehearsal',
        'protocol.rehearsal.panel.subtitle_idle': 'Start rehearsal from the Rehearse button.',
        'protocol.rehearsal.panel.subtitle_active': 'Dry run — external transports gated.',
        'protocol.rehearsal.panel.firstrun': 'Rehearsal not started yet. Use the Rehearse action on the lifecycle header to begin a dry run.',
        'protocol.rehearsal.panel.empty': 'No pending stages — rehearsal is idle. The engine will dispatch the next stage here when ready.',
        'protocol.rehearsal.response.placeholder': 'Type the response this participant would send…',
        'protocol.rehearsal.response.submit': 'Submit response',
        'protocol.rehearsal.scenarios.label': 'Canned scenarios',
        'protocol.rehearsal.scenarios.unnamed': 'Untitled',

        // Protocol — stages (plain language — no stage_kind / strict_completion)
        'protocol.stage.kind.work': 'Work',
        'protocol.stage.kind.review': 'Review',
        'protocol.stage.kind.acceptance': 'Acceptance',
        'protocol.stage.decision.complete': 'Completed',
        'protocol.stage.decision.accept': 'Accept',
        'protocol.stage.decision.revise': 'Send back',
        'protocol.stage.decision.fail': 'Reject',

        // Details — participants
        'protocol.participants.section': 'Participants',
        'protocol.participants.firstrun': 'Add the first participant — a person or agent who will work on this.',
        'protocol.participants.add': '+ Add participant',
        'protocol.participant.display_name.label': 'Name',
        'protocol.participant.display_name.help': 'Who (or what agent) takes part in this stage?',
        'protocol.participant.display_name.placeholder': 'e.g. Reviewer',
        'protocol.participant.participant_key.label': 'Key',
        'protocol.participant.participant_key.help': 'Short identifier used when other stages reference this participant.',
        'protocol.participant.participant_key.placeholder': 'reviewer',
        'protocol.participant.instructions.label': 'Instructions',
        'protocol.participant.instructions.help': 'What this participant is expected to do across the workflow.',
        'protocol.participant.instructions.placeholder': 'Instructions shared with this participant…',
        'protocol.participant.required_skills.label': 'Required skills',
        'protocol.participant.required_skills.help': 'Comma-separated skill slugs — leave blank if anyone can do it.',
        'protocol.participant.required_skills.placeholder': 'code-review, sql',

        // Details — stages
        'protocol.stages.section': 'Stages',
        'protocol.stages.firstrun': 'Add the first stage — what happens, and who owns it.',
        'protocol.stages.add': '+ Add stage',
        'protocol.stage.display_name.label': 'Name',
        'protocol.stage.display_name.placeholder': 'e.g. Planning',
        'protocol.stage.display_name.help': 'Name of this step in the workflow.',
        'protocol.stage.stage_key.label': 'Key',
        'protocol.stage.stage_key.placeholder': 'planning',
        'protocol.stage.stage_key.help': 'Short identifier used in transitions.',
        'protocol.stage.participant_key.label': 'Assigned participant',
        'protocol.stage.participant_key.help': 'Which participant runs this stage.',
        'protocol.stage.stage_kind.label': 'Stage type',
        'protocol.stage.stage_kind.help': 'Work produces output; review evaluates output; acceptance signs off.',
        'protocol.stage.instructions.label': 'Instructions',
        'protocol.stage.instructions.placeholder': 'What should happen in this stage?',
        'protocol.stage.instructions.help': 'Step-level guidance for the assigned participant.',
        'protocol.stage.max_rounds.label': 'Max rounds',
        'protocol.stage.max_rounds.help': 'How many revise cycles this stage allows (0 = unlimited).',
        'protocol.stage.max_rounds.placeholder': '0',
        'protocol.stage.timeout_seconds.label': 'Timeout (seconds)',
        'protocol.stage.timeout_seconds.help': 'Abandon the stage after this long (0 = no timeout).',
        'protocol.stage.timeout_seconds.placeholder': '0',

        // Details — artifacts
        'protocol.artifacts.section': 'Artifacts',
        'protocol.artifacts.firstrun': 'Artifacts are files or plans the workflow reads and writes. Optional.',
        'protocol.artifacts.add': '+ Add artifact',
        'protocol.artifact.display_name.label': 'Name',
        'protocol.artifact.display_name.placeholder': 'e.g. Review notes',
        'protocol.artifact.display_name.help': 'Human-readable name.',
        'protocol.artifact.artifact_key.label': 'Key',
        'protocol.artifact.artifact_key.placeholder': 'review-notes',
        'protocol.artifact.artifact_key.help': 'Identifier used when stages reference this artifact.',
        'protocol.artifact.kind.label': 'Kind',
        'protocol.artifact.kind.help': 'What the artifact lives in.',
        'protocol.artifact.description.label': 'Description',
        'protocol.artifact.description.placeholder': 'What the artifact contains…',

        // Details — overview
        'protocol.details.overview.empty': 'Select a participant, stage, or artifact in the canvas — or edit the name and slug above.',

        // Empty / first-run / onboarding
        'protocol.canvas.empty.title': 'Design your workflow',
        'protocol.canvas.empty.body': 'Start by adding the first participant — a person or agent who will work on this.',
        'protocol.catalog.empty.title': 'No protocols yet',
        'protocol.catalog.empty.body': 'Create one from a template in the Gallery, or start from a blank draft.',
        'protocol.firstrun.participant': 'Add the first participant.',
        'protocol.firstrun.stage': 'Add the first stage to what this participant does.',
        'protocol.firstrun.transition': 'Connect stages to say what happens when each finishes.',

        // Draft state chip
        'draftchip.idle': 'Saved',
        'draftchip.editing': 'Editing…',
        'draftchip.saving': 'Saving…',
        'draftchip.saved': 'Saved',
        'draftchip.conflict': 'Conflict — reload to resolve',
        'draftchip.error': 'Save failed',

        // Validation
        'validation.empty': 'No issues.',
        'validation.heading.errors': 'To fix before publishing',
        'validation.heading.warnings': 'Warnings',

        // Runs — generalized runs surface
        'runs.empty': 'No runs match this filter.',
        'runs.list.title': 'Runs',
        'runs.search.placeholder': 'Search runs by id, stage, or problem…',
        'runs.status.filter.all': 'All',
        'runs.status.running': 'Running',
        'runs.status.queued': 'Queued',
        'runs.status.blocked': 'Blocked',
        'runs.status.completed': 'Completed',
        'runs.status.failed': 'Failed',
        'runs.status.cancelled': 'Cancelled',
        'runs.detail.firstrun': 'Select a run to inspect state, timeline, artifacts, and operator actions.',
        'runs.summary.run_id': 'Run id',
        'runs.summary.status': 'Status',
        'runs.summary.version': 'Version',
        'runs.summary.stage': 'Current stage',
        'runs.summary.loop': 'Review loop',
        'runs.summary.workspace': 'Workspace',
        'runs.summary.conversation': 'Root conversation',

        // Agents — admin + observability
        'agents.list.title': 'Agents',
        'agents.empty': 'No agents match this view.',
        'agents.search.placeholder': 'Search by name, slug, role, or provider…',
        'agents.presence.filter.all': 'All',
        'agents.presence.connected': 'Connected',
        'agents.presence.degraded': 'Degraded',
        'agents.presence.disconnected': 'Disconnected',
        'agents.presence.standalone': 'Standalone',
        'agents.presence.stopped': 'Stopped',
        'agents.presence.faulted': 'Execution faulted',
        'agents.detail.firstrun': 'Select an agent to inspect presence, skills, workload, and admin actions.',
        'agents.summary.agent_id': 'Agent ID',
        'agents.summary.slug': 'Slug',
        'agents.summary.role': 'Role',
        'agents.summary.provider': 'Provider',
        'agents.summary.trust_tier': 'Trust tier',
        'agents.summary.authority': 'Authority',
        'agents.summary.registry_scope': 'Scope',
        'agents.summary.version': 'Version',
        'agents.summary.transport': 'Transport',
        'agents.summary.execution': 'Execution',
        'agents.summary.capacity': 'Capacity',
        'agents.summary.last_heartbeat': 'Last heartbeat',
        'agents.summary.skills': 'Advertised skills',
        'agents.trust_tier.community': 'Community',
        'agents.trust_tier.trusted': 'Trusted',
        'agents.trust_tier.verified': 'Verified',
        'agents.trust_tier.restricted': 'Restricted',
        'agents.admin.title': 'Admin actions',
        'agents.admin.gated_help': 'These actions require registry admin permissions. They are hidden when the viewer lacks them.',
        'agents.admin.trust_tier.label': 'Trust tier',
        'agents.admin.trust_tier.apply': 'Update tier',
        'agents.admin.trust_tier.saved': 'Trust tier updated.',
        'agents.admin.capacity.label': 'Capacity (current / max)',
        'agents.admin.capacity.current': 'Current',
        'agents.admin.capacity.max': 'Max',
        'agents.admin.capacity.apply': 'Apply capacity',
        'agents.admin.capacity.save': 'Save capacity',
        'agents.admin.capacity.saved': 'Capacity updated.',
        'agents.admin.rotate_token': 'Rotate token',
        'agents.admin.rotate_token.confirm': 'Rotate this agent\u2019s bearer token? The old token will stop working immediately.',
        'agents.admin.rotate_token.result_label': 'New agent token (copy now; not shown again)',
        'agents.admin.rotate_token.shown': 'Copy this new bearer token now \u2014 the registry will not display it again.',
        'agents.admin.rotate_token.saved': 'Token rotated.',
        'agents.admin.disconnect': 'Disconnect',
        'agents.admin.soft_delete': 'Disconnect and soft-delete',
        'agents.admin.soft_delete.confirm': 'Disconnect this agent and mark it soft-deleted? It will stop receiving routed tasks.',
        'agents.selector.title': 'Selector resolution preview',
        'agents.selector.help': 'Paste or type a selector (@agent-slug, @skill:foo, @role:reviewer) to see which agents would resolve.',
        'agents.selector.placeholder': '@skill:pull-request-review',
        'agents.selector.run': 'Resolve',
        'agents.selector.empty': 'No candidates yet — enter a selector and press Resolve.',
        'agents.selector.no_matches': 'No connected agents match this selector.',
        'agents.selector.result_title': 'Candidates',
        'agents.selector.candidate_badge_current': 'current agent',
        'agents.selector.candidate_subtitle_template': '{role} · {slug}',

        // Skills / guidance — enough for stub adoption; expanded on migration
        'skill.lifecycle.draft': 'Draft',
        'skill.lifecycle.published': 'Published',
        'skill.lifecycle.archived': 'Archived',
        'guidance.lifecycle.draft': 'Draft',
        'guidance.lifecycle.published': 'Published',
        'guidance.lifecycle.archived': 'Archived',
    };

    function dictValue(key, fallback) {
        if (key in DICT) return DICT[key];
        if (typeof fallback === 'string') return fallback;
        // Visible marker so missing keys surface in UI review and in tests.
        return `[${key}]`;
    }

    const dict = {
        label: (key, fallback) => dictValue(key, fallback),
        help: (key, fallback) => dictValue(key, fallback),
        emptyState: (surfaceKey, fallback) => dictValue(surfaceKey, fallback),
        firstRun: (surfaceKey, step, fallback) => dictValue(`${surfaceKey}.firstrun.${step}`, fallback),
        has: (key) => key in DICT,
        keys: () => Object.keys(DICT),
        // Allow test helpers to extend the dictionary if a surface registers
        // its own domain keys before first render. Surfaces should define
        // their strings here in the main module rather than relying on this.
        register: (entries) => {
            Object.entries(entries || {}).forEach(([key, value]) => {
                DICT[String(key)] = String(value);
            });
        },
    };

    // -----------------------------------------------------------------------
    // Draft-state chip
    //
    // Contract: { state, lastSavedAt, error }.
    // State: idle | editing | saving | saved | conflict | error.
    // "saved" is reserved for server-confirmed persistence.
    // -----------------------------------------------------------------------
    const VALID_CHIP_STATES = ['idle', 'editing', 'saving', 'saved', 'conflict', 'error'];

    function draftStateChip({ state = 'idle', lastSavedAt = '', error = '' } = {}) {
        const el = document.createElement('span');
        el.className = 'kit-draft-chip';
        el.setAttribute('role', 'status');
        applyChipState(el, { state, lastSavedAt, error });
        return el;
    }

    function applyChipState(el, { state = 'idle', lastSavedAt = '', error = '' } = {}) {
        if (!el) return;
        const resolved = VALID_CHIP_STATES.includes(state) ? state : 'idle';
        el.dataset.state = resolved;
        el.className = `kit-draft-chip kit-draft-chip-${resolved}`;
        const base = dict.label(`draftchip.${resolved}`);
        let text = base;
        if (resolved === 'saved' || resolved === 'idle') {
            if (lastSavedAt) {
                text = `${base} · ${UI.relativeTime(lastSavedAt)}`;
            }
        } else if (resolved === 'error' && error) {
            text = `${base}: ${error}`;
        }
        el.textContent = text;
        el.title = error || lastSavedAt || '';
    }

    // -----------------------------------------------------------------------
    // Lifecycle header
    //
    // Contract: { record, saveState, actions, permissions, onTitleCommit,
    //            onSlugCommit, surfaceKey }
    //
    // One header for every authoring surface — title + slug + draft chip +
    // validate / publish / archive / discard. Destructive actions share the
    // same `btn-danger` styling and confirmation pattern.
    // -----------------------------------------------------------------------
    function lifecycleHeader({
        surfaceKey = 'protocol',
        record = {},
        saveState = { state: 'idle', lastSavedAt: '', error: '' },
        actions = {},
        permissions = {},
        onTitleCommit = null,
        onSlugCommit = null,
    } = {}) {
        const header = document.createElement('header');
        header.className = 'kit-lifecycle-header';

        const topRow = document.createElement('div');
        topRow.className = 'kit-lifecycle-header-top';

        const titleWrap = document.createElement('div');
        titleWrap.className = 'kit-lifecycle-title';
        const titleInput = document.createElement('input');
        titleInput.type = 'text';
        titleInput.className = 'kit-lifecycle-title-input';
        titleInput.placeholder = dict.label(`${surfaceKey}.display_name.placeholder`);
        titleInput.setAttribute('aria-label', dict.label(`${surfaceKey}.display_name.label`));
        titleInput.value = String(record.display_name || '');
        if (onTitleCommit) {
            titleInput.addEventListener('change', () => onTitleCommit(titleInput.value));
            titleInput.addEventListener('blur', () => onTitleCommit(titleInput.value));
        }
        titleWrap.appendChild(titleInput);

        const slugInput = document.createElement('input');
        slugInput.type = 'text';
        slugInput.className = 'kit-lifecycle-slug-input';
        slugInput.placeholder = dict.label(`${surfaceKey}.slug.placeholder`);
        slugInput.setAttribute('aria-label', dict.label(`${surfaceKey}.slug.label`));
        slugInput.value = String(record.slug || '');
        if (onSlugCommit) {
            slugInput.addEventListener('change', () => onSlugCommit(slugInput.value));
            slugInput.addEventListener('blur', () => onSlugCommit(slugInput.value));
        }
        titleWrap.appendChild(slugInput);

        topRow.appendChild(titleWrap);

        const chip = draftStateChip(saveState);
        topRow.appendChild(chip);
        header.appendChild(topRow);

        const actionRow = document.createElement('div');
        actionRow.className = 'kit-lifecycle-actions';

        const lifecycleState = String(record.lifecycle_state || 'draft');
        const chipBadge = document.createElement('span');
        chipBadge.className = `badge kit-lifecycle-chip kit-lifecycle-chip-${lifecycleState}`;
        chipBadge.textContent = dict.label(`${surfaceKey}.lifecycle.${lifecycleState}`);
        actionRow.appendChild(chipBadge);

        const buttonSpec = [
            { key: 'validate', tone: '', permissionKey: 'canValidate' },
            { key: 'publish', tone: 'btn-primary', permissionKey: 'canPublish' },
            { key: 'rehearse', tone: '', permissionKey: 'canRehearse' },
            { key: 'archive', tone: 'btn-secondary', permissionKey: 'canArchive' },
            { key: 'discard', tone: 'btn-danger', permissionKey: 'canDiscard' },
        ];
        buttonSpec.forEach(({ key, tone, permissionKey }) => {
            const handler = actions[key];
            if (!handler) return;
            if (permissions[permissionKey] === false) return;
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = ['btn', tone].filter(Boolean).join(' ');
            btn.dataset.kitAction = key;
            btn.textContent = dict.label(`${surfaceKey}.action.${key}`);
            btn.addEventListener('click', () => handler(record));
            actionRow.appendChild(btn);
        });

        header.appendChild(actionRow);

        header.updateSaveState = (state) => applyChipState(chip, state);
        header.syncRecord = (next) => {
            if (!next) return;
            if (document.activeElement !== titleInput && titleInput.value !== String(next.display_name || '')) {
                titleInput.value = String(next.display_name || '');
            }
            if (document.activeElement !== slugInput && slugInput.value !== String(next.slug || '')) {
                slugInput.value = String(next.slug || '');
            }
            const nextState = String(next.lifecycle_state || 'draft');
            chipBadge.className = `badge kit-lifecycle-chip kit-lifecycle-chip-${nextState}`;
            chipBadge.textContent = dict.label(`${surfaceKey}.lifecycle.${nextState}`);
        };

        return header;
    }

    // -----------------------------------------------------------------------
    // Validation surface
    //
    // Contract: { issues: [{ severity, message, path, action? }], layout }
    // Renders error + warning severities through the dictionary. No raw
    // Pydantic text reaches the surface.
    // -----------------------------------------------------------------------
    function validationSurface({ issues = [], layout = 'summary' } = {}) {
        const container = document.createElement('div');
        container.className = `kit-validation kit-validation-${layout}`;

        const errors = issues.filter((i) => (i.severity || 'error') === 'error');
        const warnings = issues.filter((i) => i.severity === 'warning');

        if (!errors.length && !warnings.length) {
            const ok = document.createElement('div');
            ok.className = 'kit-validation-ok';
            ok.textContent = dict.label('validation.empty');
            container.appendChild(ok);
            return container;
        }

        function renderSection(label, severity, items) {
            if (!items.length) return;
            const section = document.createElement('div');
            section.className = `kit-validation-section kit-validation-${severity}`;
            const heading = document.createElement('div');
            heading.className = 'kit-validation-heading';
            heading.textContent = label;
            section.appendChild(heading);

            const list = document.createElement('ul');
            list.className = 'kit-validation-list';
            items.forEach((item) => {
                const li = document.createElement('li');
                li.className = 'kit-validation-item';
                const msg = document.createElement('span');
                msg.className = 'kit-validation-message';
                msg.textContent = String(item.message || '');
                li.appendChild(msg);
                if (item.action && typeof item.action.onClick === 'function') {
                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'btn btn-small';
                    btn.textContent = String(item.action.label || 'Fix');
                    btn.addEventListener('click', item.action.onClick);
                    li.appendChild(btn);
                }
                list.appendChild(li);
            });
            section.appendChild(list);
            container.appendChild(section);
        }

        renderSection(dict.label('validation.heading.errors'), 'error', errors);
        renderSection(dict.label('validation.heading.warnings'), 'warning', warnings);

        return container;
    }

    // -----------------------------------------------------------------------
    // Details panel
    //
    // Contract: { target, schema, dictionary, onCommit, surfaceKey }
    //
    // schema: [{ key, kind: 'text' | 'textarea' | 'select' | 'checkbox',
    //            options?, required?, maxLength?, rows? }]
    //
    // Invariant (plan §7.4): blank records render inputs with NO prefilled
    // text — only placeholder-styled hints sourced from the dictionary.
    // -----------------------------------------------------------------------
    function detailsPanel({
        target = null,
        schema = [],
        surfaceKey = 'protocol',
        onCommit = null,
        emptyHint = '',
    } = {}) {
        const panel = document.createElement('aside');
        panel.className = 'kit-details-panel';

        if (!target) {
            const empty = document.createElement('div');
            empty.className = 'kit-details-empty';
            empty.textContent = emptyHint || dict.emptyState(`${surfaceKey}.details.empty`, 'Select something to edit its details here.');
            panel.appendChild(empty);
            return panel;
        }

        schema.forEach((field) => {
            if (!field || !field.key) return;
            const labelKey = field.labelKey || `${surfaceKey}.${field.key}.label`;
            const helpKey = field.helpKey || `${surfaceKey}.${field.key}.help`;
            const placeholderKey = field.placeholderKey || `${surfaceKey}.${field.key}.placeholder`;

            const row = document.createElement('div');
            row.className = 'kit-details-row';

            const label = document.createElement('label');
            label.className = 'kit-details-label';
            label.textContent = dict.label(labelKey, field.label || field.key);
            row.appendChild(label);

            let control;
            const kind = field.kind || 'text';
            const currentValue = target[field.key];
            const hasValue = currentValue !== undefined && currentValue !== null && String(currentValue) !== '';

            if (kind === 'textarea') {
                control = document.createElement('textarea');
                control.rows = Number(field.rows || 4);
            } else if (kind === 'select') {
                control = document.createElement('select');
                (field.options || []).forEach((opt) => {
                    const option = document.createElement('option');
                    option.value = String(opt.value);
                    option.textContent = String(opt.label || opt.value);
                    control.appendChild(option);
                });
            } else if (kind === 'checkbox') {
                control = document.createElement('input');
                control.type = 'checkbox';
            } else {
                control = document.createElement('input');
                control.type = 'text';
            }
            control.className = 'kit-details-control';
            control.id = `kit-details-${field.key}`;
            label.htmlFor = control.id;

            // Placeholder / value assignment honors the blank-first-paint invariant.
            if (kind === 'checkbox') {
                control.checked = Boolean(currentValue);
            } else {
                const placeholderText = dict.label(placeholderKey, field.placeholder || '');
                if (hasValue) {
                    control.value = String(currentValue);
                    if (placeholderText) control.placeholder = placeholderText;
                } else {
                    control.value = '';
                    if (placeholderText) control.placeholder = placeholderText;
                }
            }
            if (field.required) control.required = true;
            if (field.maxLength) control.maxLength = Number(field.maxLength);

            if (typeof onCommit === 'function') {
                const commit = () => {
                    const value = kind === 'checkbox' ? control.checked : control.value;
                    onCommit(target, field.key, value);
                };
                control.addEventListener('change', commit);
                if (kind === 'text' || kind === 'textarea') {
                    control.addEventListener('blur', commit);
                }
            }

            row.appendChild(control);

            const helpText = dict.help(helpKey, field.help || '');
            if (helpText) {
                const help = document.createElement('div');
                help.className = 'kit-details-help';
                help.textContent = helpText;
                row.appendChild(help);
            }

            panel.appendChild(row);
        });

        return panel;
    }

    // -----------------------------------------------------------------------
    // Authored catalog
    //
    // Contract: { records, onOpen, lifecycleFilter, search, surfaceKey,
    //            statusChipRenderer, emptyStateRenderer, createAction }
    //
    // Every row carries an explicit lifecycle chip; default filter is "all".
    // Authored records and template/Gallery entries never mix here.
    // Narrow widths render a single-column card stack via CSS.
    // -----------------------------------------------------------------------
    function authoredCatalog({
        records = [],
        onOpen = null,
        surfaceKey = 'protocol',
        lifecycleFilter = 'all',
        search = '',
        createAction = null,
    } = {}) {
        const container = document.createElement('section');
        container.className = 'kit-authored-catalog';

        const state = { lifecycleFilter, search };
        const controls = document.createElement('div');
        controls.className = 'kit-catalog-controls';

        const filter = document.createElement('div');
        filter.className = 'kit-catalog-filter';
        const filterOptions = [
            { value: 'all', key: `${surfaceKey}.lifecycle.filter.all` },
            { value: 'draft', key: `${surfaceKey}.lifecycle.draft` },
            { value: 'published', key: `${surfaceKey}.lifecycle.published` },
            { value: 'archived', key: `${surfaceKey}.lifecycle.archived` },
        ];
        filterOptions.forEach((opt) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = `btn btn-small kit-catalog-filter-chip${opt.value === state.lifecycleFilter ? ' is-active' : ''}`;
            btn.dataset.value = opt.value;
            btn.textContent = dict.label(opt.key);
            btn.addEventListener('click', () => {
                state.lifecycleFilter = opt.value;
                filter.querySelectorAll('button').forEach((el) => {
                    el.classList.toggle('is-active', el.dataset.value === state.lifecycleFilter);
                });
                renderList();
            });
            filter.appendChild(btn);
        });
        controls.appendChild(filter);

        const searchBox = document.createElement('input');
        searchBox.type = 'search';
        searchBox.className = 'kit-catalog-search';
        searchBox.placeholder = 'Search…';
        searchBox.value = state.search;
        searchBox.addEventListener('input', () => {
            state.search = searchBox.value;
            renderList();
        });
        controls.appendChild(searchBox);

        if (createAction && typeof createAction.onClick === 'function') {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-primary';
            btn.textContent = String(createAction.label || 'Create');
            btn.addEventListener('click', createAction.onClick);
            controls.appendChild(btn);
        }

        container.appendChild(controls);

        const listEl = document.createElement('ul');
        listEl.className = 'kit-catalog-list';
        container.appendChild(listEl);

        function _matches(record) {
            const lifecycle = String(record.lifecycle_state || 'draft');
            if (state.lifecycleFilter !== 'all' && state.lifecycleFilter !== lifecycle) {
                return false;
            }
            const query = state.search.trim().toLowerCase();
            if (!query) return true;
            const hay = [record.display_name, record.slug, record.description]
                .map((v) => String(v || '').toLowerCase())
                .join(' ');
            return hay.includes(query);
        }

        function renderList() {
            const filtered = records.filter(_matches);
            listEl.innerHTML = '';
            if (!filtered.length) {
                const empty = UI.renderEmptyState(
                    dict.emptyState(`${surfaceKey}.catalog.empty.body`, 'Nothing here yet.'),
                );
                listEl.appendChild(empty);
                return;
            }
            filtered.forEach((record) => {
                const li = document.createElement('li');
                li.className = 'kit-catalog-item';
                const lifecycle = String(record.lifecycle_state || 'draft');
                const chip = document.createElement('span');
                chip.className = `badge kit-lifecycle-chip kit-lifecycle-chip-${lifecycle}`;
                chip.textContent = dict.label(`${surfaceKey}.lifecycle.${lifecycle}`);

                const row = UI.renderListRow({
                    label: String(record.display_name || record.slug || record.id || 'Untitled'),
                    sublabel: String(record.description || record.slug || ''),
                    badgeText: '',
                    onClick: onOpen ? () => onOpen(record) : undefined,
                    trailing: chip,
                });
                li.appendChild(row);
                listEl.appendChild(li);
            });
        }

        renderList();
        return container;
    }

    // -----------------------------------------------------------------------
    // Canvas
    //
    // Contract: { sections: [{ key, title, nodes, onAdd?, addLabel?, empty?,
    //                         firstRunHint? }], selection, onSelect }
    //
    // A single scroll surface with labeled groups of selectable node cards.
    // Fluid — everything edits through the details panel; no in-place forms.
    // When a section is empty and carries a firstRunHint, the hint is shown
    // as a placeholder card that also triggers onAdd.
    // -----------------------------------------------------------------------
    function canvas({
        sections = [],
        selection = null,
        onSelect = null,
    } = {}) {
        const root = document.createElement('div');
        root.className = 'kit-canvas';

        sections.forEach((section) => {
            if (!section || !section.key) return;
            const group = document.createElement('section');
            group.className = 'kit-canvas-section';
            group.dataset.section = section.key;

            const head = document.createElement('header');
            head.className = 'kit-canvas-section-head';
            const title = document.createElement('h3');
            title.className = 'kit-canvas-section-title';
            title.textContent = String(section.title || '');
            head.appendChild(title);
            if (typeof section.onAdd === 'function') {
                const add = document.createElement('button');
                add.type = 'button';
                add.className = 'btn btn-small';
                add.textContent = String(section.addLabel || '+ Add');
                add.addEventListener('click', section.onAdd);
                head.appendChild(add);
            }
            group.appendChild(head);

            const nodes = Array.isArray(section.nodes) ? section.nodes : [];
            const list = document.createElement('ul');
            list.className = 'kit-canvas-nodes';

            if (!nodes.length) {
                const placeholder = document.createElement('li');
                placeholder.className = 'kit-canvas-placeholder';
                const hint = section.firstRunHint || section.empty || '';
                placeholder.textContent = String(hint || 'Nothing here yet.');
                if (typeof section.onAdd === 'function' && section.firstRunHint) {
                    placeholder.classList.add('is-actionable');
                    placeholder.addEventListener('click', section.onAdd);
                }
                list.appendChild(placeholder);
            } else {
                nodes.forEach((node) => {
                    if (!node || node.key === undefined || node.key === null) return;
                    const nodeKey = String(node.key);
                    const li = document.createElement('li');
                    const isSelected =
                        selection
                        && String(selection.sectionKey || selection.kind || '') === section.key
                        && String(selection.nodeKey || selection.key || '') === nodeKey;
                    li.className = `kit-canvas-node${isSelected ? ' is-selected' : ''}`;
                    li.dataset.nodeKey = nodeKey;

                    const label = document.createElement('div');
                    label.className = 'kit-canvas-node-label';
                    label.textContent = String(node.label || nodeKey);
                    li.appendChild(label);

                    if (node.sublabel) {
                        const sub = document.createElement('div');
                        sub.className = 'kit-canvas-node-sublabel';
                        sub.textContent = String(node.sublabel);
                        li.appendChild(sub);
                    }

                    if (typeof onSelect === 'function') {
                        li.addEventListener('click', () => onSelect({ sectionKey: section.key, nodeKey }));
                    }

                    list.appendChild(li);
                });
            }

            group.appendChild(list);
            root.appendChild(group);
        });

        return root;
    }

    // -----------------------------------------------------------------------
    // Rehearsal panel — per-stage conversation threads for rehearsal runs.
    //
    // Contract (plan §7.10): { runId, sessions, scenarios, onRespond, onDismiss }.
    // No external egress. Responses submit via onRespond; scenarios prefill the
    // response text when picked.
    // -----------------------------------------------------------------------
    function rehearsalPanel({
        runId = '',
        sessions = [],
        scenarios = [],
        onRespond = null,
        emptyHint = '',
    } = {}) {
        const root = document.createElement('div');
        root.className = 'kit-rehearsal-panel';

        const head = document.createElement('div');
        head.className = 'kit-rehearsal-header';
        const title = document.createElement('span');
        title.className = 'kit-rehearsal-title';
        title.textContent = dictValue('protocol.rehearsal.panel.title', 'Rehearsal');
        head.appendChild(title);
        const subtitle = document.createElement('span');
        subtitle.className = 'kit-rehearsal-subtitle';
        subtitle.textContent = runId
            ? dictValue('protocol.rehearsal.panel.subtitle_active', 'Dry run — external transports gated.')
            : dictValue('protocol.rehearsal.panel.subtitle_idle', 'Start rehearsal from the Rehearse button.');
        head.appendChild(subtitle);
        root.appendChild(head);

        if (!runId) {
            root.appendChild(UI.renderEmptyState(
                emptyHint || dictValue('protocol.rehearsal.panel.firstrun', 'Rehearsal not started yet. Use the Rehearse action on the lifecycle header to begin a dry run.'),
            ));
            return root;
        }

        const pendingList = Array.isArray(sessions) ? sessions.filter(Boolean) : [];
        if (pendingList.length === 0) {
            root.appendChild(UI.renderEmptyState(
                dictValue('protocol.rehearsal.panel.empty', 'No pending stages — rehearsal is idle. The engine will dispatch the next stage here when ready.'),
            ));
            return root;
        }

        const scenariosByStage = new Map();
        (Array.isArray(scenarios) ? scenarios : []).forEach((scenario) => {
            const key = String(scenario?.stage_key || '').trim() || '__any__';
            if (!scenariosByStage.has(key)) scenariosByStage.set(key, []);
            scenariosByStage.get(key).push(scenario);
        });

        pendingList.forEach((session) => {
            const card = document.createElement('div');
            card.className = 'kit-rehearsal-session';
            card.dataset.routedTaskId = String(session.routed_task_id || '');
            card.dataset.stageKey = String(session.stage_key || '');

            const sessionTitle = document.createElement('div');
            sessionTitle.className = 'kit-rehearsal-session-title';
            const strong = document.createElement('strong');
            strong.textContent = String(session.stage_key || 'stage');
            sessionTitle.appendChild(strong);
            if (session.participant_key) {
                const participant = document.createElement('span');
                participant.className = 'kit-rehearsal-session-participant';
                participant.textContent = ` · ${String(session.participant_key)}`;
                sessionTitle.appendChild(participant);
            }
            card.appendChild(sessionTitle);

            if (session.instructions) {
                const instructions = document.createElement('pre');
                instructions.className = 'kit-rehearsal-session-instructions';
                instructions.textContent = String(session.instructions);
                card.appendChild(instructions);
            }

            const form = document.createElement('form');
            form.className = 'kit-rehearsal-session-form';

            const textarea = document.createElement('textarea');
            textarea.className = 'kit-rehearsal-session-response';
            textarea.rows = 4;
            textarea.placeholder = dictValue('protocol.rehearsal.response.placeholder', 'Type the response this participant would send…');
            form.appendChild(textarea);

            const stageScenarios = [
                ...(scenariosByStage.get(String(session.stage_key || '')) || []),
                ...(scenariosByStage.get('__any__') || []),
            ];
            if (stageScenarios.length > 0) {
                const scenarioRow = document.createElement('div');
                scenarioRow.className = 'kit-rehearsal-scenarios';
                const scenarioLabel = document.createElement('label');
                scenarioLabel.textContent = dictValue('protocol.rehearsal.scenarios.label', 'Canned scenarios');
                scenarioRow.appendChild(scenarioLabel);
                stageScenarios.forEach((scenario) => {
                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'kit-rehearsal-scenario-btn';
                    btn.textContent = scenario.display_name || dictValue('protocol.rehearsal.scenarios.unnamed', 'Untitled');
                    btn.addEventListener('click', () => {
                        textarea.value = String(scenario.response_text || '');
                        textarea.focus();
                    });
                    scenarioRow.appendChild(btn);
                });
                form.appendChild(scenarioRow);
            }

            const submit = document.createElement('button');
            submit.type = 'submit';
            submit.className = 'btn btn-primary';
            submit.textContent = dictValue('protocol.rehearsal.response.submit', 'Submit response');
            form.appendChild(submit);

            form.addEventListener('submit', (e) => {
                e.preventDefault();
                if (typeof onRespond === 'function') {
                    onRespond({
                        routedTaskId: session.routed_task_id,
                        responseText: textarea.value,
                        stageKey: session.stage_key,
                        participantKey: session.participant_key,
                    });
                }
            });

            card.appendChild(form);
            root.appendChild(card);
        });

        return root;
    }

    // -----------------------------------------------------------------------
    // Runs widgets (plan §7.9)
    //
    // A *run* in kit terms is a record with:
    //   { id, status, title, subtitle, badge, participants, updatedAt }
    // The list primitive doesn't know "protocol_run" specifically — callers
    // adapt their domain records into this shape so the same widget can
    // serve delegation chains, coordination sessions, and anything else
    // that maps onto the run state machine later.
    // -----------------------------------------------------------------------
    const RUN_STATUS_STATES = ['queued', 'running', 'blocked', 'completed', 'failed', 'cancelled'];

    function _runStatusChip(status) {
        const value = String(status || '').trim();
        const normalized = RUN_STATUS_STATES.includes(value) ? value : 'queued';
        const chip = document.createElement('span');
        chip.className = `kit-run-status-chip kit-run-status-${normalized}`;
        chip.dataset.status = normalized;
        chip.textContent = dictValue(`runs.status.${normalized}`, value || 'queued');
        return chip;
    }

    function runsList({
        runs = [],
        search = '',
        statusFilter = '',
        selectedId = '',
        onSearch = null,
        onStatusFilter = null,
        onSelect = null,
        emptyHint = '',
    } = {}) {
        const root = document.createElement('div');
        root.className = 'kit-runs-list';

        const filters = document.createElement('div');
        filters.className = 'kit-runs-filters';
        const searchInput = document.createElement('input');
        searchInput.className = 'kit-runs-search';
        searchInput.type = 'search';
        searchInput.placeholder = dictValue('runs.search.placeholder', 'Search runs…');
        searchInput.value = String(search || '');
        if (typeof onSearch === 'function') {
            searchInput.addEventListener('input', (e) => onSearch(String(e.target.value || '')));
        }
        filters.appendChild(searchInput);

        const filterRow = document.createElement('div');
        filterRow.className = 'kit-runs-filter-chips';
        const statusOptions = ['', ...RUN_STATUS_STATES];
        statusOptions.forEach((value) => {
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'kit-runs-filter-chip';
            if (String(statusFilter || '') === value) chip.classList.add('is-active');
            chip.textContent = value
                ? dictValue(`runs.status.${value}`, value)
                : dictValue('runs.status.filter.all', 'All');
            if (typeof onStatusFilter === 'function') {
                chip.addEventListener('click', () => onStatusFilter(value));
            }
            filterRow.appendChild(chip);
        });
        filters.appendChild(filterRow);
        root.appendChild(filters);

        const list = document.createElement('div');
        list.className = 'kit-runs-list-body';
        const entries = Array.isArray(runs) ? runs.filter(Boolean) : [];
        if (entries.length === 0) {
            list.appendChild(UI.renderEmptyState(
                emptyHint || dictValue('runs.empty', 'No runs match this filter.'),
            ));
        } else {
            entries.forEach((run) => {
                const row = document.createElement('div');
                row.className = 'kit-runs-list-row';
                if (String(run.id || '') === String(selectedId || '')) {
                    row.classList.add('is-selected');
                }
                row.dataset.runId = String(run.id || '');

                const head = document.createElement('div');
                head.className = 'kit-runs-list-row-head';
                head.appendChild(_runStatusChip(run.status));
                const title = document.createElement('span');
                title.className = 'kit-runs-list-row-title';
                title.textContent = String(run.title || run.id || '');
                head.appendChild(title);
                if (run.badge) {
                    const badge = document.createElement('span');
                    badge.className = 'kit-runs-list-row-badge';
                    badge.textContent = String(run.badge);
                    head.appendChild(badge);
                }
                row.appendChild(head);

                if (run.subtitle) {
                    const sub = document.createElement('div');
                    sub.className = 'kit-runs-list-row-subtitle';
                    sub.textContent = String(run.subtitle);
                    row.appendChild(sub);
                }

                if (typeof onSelect === 'function') {
                    row.addEventListener('click', () => onSelect(run));
                }
                list.appendChild(row);
            });
        }
        root.appendChild(list);
        return root;
    }

    function runSummary({ run = null, liveEventText = '' } = {}) {
        const root = document.createElement('div');
        root.className = 'kit-run-summary';

        if (!run) {
            root.appendChild(UI.renderEmptyState(
                dictValue('runs.detail.firstrun', 'Select a run to inspect state, timeline, artifacts, and operator actions.'),
            ));
            return root;
        }

        const metadata = [
            { label: dictValue('runs.summary.run_id', 'Run id'), value: String(run.id || '') },
            { label: dictValue('runs.summary.status', 'Status'), value: String(run.status || 'queued') },
            { label: dictValue('runs.summary.version', 'Version'), value: String(run.version || 1) },
            { label: dictValue('runs.summary.stage', 'Current stage'), value: String(run.current_stage_key || 'n/a') },
            { label: dictValue('runs.summary.loop', 'Review loop'), value: String(run.review_loop || '0 / n/a') },
            { label: dictValue('runs.summary.workspace', 'Workspace'), value: String(run.workspace_ref || 'default') },
            { label: dictValue('runs.summary.conversation', 'Root conversation'), value: String(run.root_conversation_id || 'n/a') },
        ];
        root.appendChild(UI.renderMetadataGrid(metadata));

        if (run.notes) {
            const notes = document.createElement('div');
            notes.className = 'kit-run-summary-notes quiet-note';
            notes.textContent = String(run.notes);
            root.appendChild(notes);
        }
        if (liveEventText) {
            const live = document.createElement('div');
            live.className = 'kit-run-summary-live quiet-note';
            live.textContent = String(liveEventText);
            root.appendChild(live);
        }

        return root;
    }

    // -----------------------------------------------------------------------
    // Agents widgets (list, summary, selector preview)
    //
    // Agents are represented in kit terms as:
    //   { id, slug, displayName, role, provider, presence, trustTier,
    //     currentCapacity, maxCapacity, routingSkills, executionState,
    //     lastHeartbeat, softDeletedAt }
    //
    // Callers adapt registry AgentRecord into this shape. Presence is a
    // normalized enum mirroring agents.presence.* dictionary keys.
    // -----------------------------------------------------------------------
    const PRESENCE_STATES = ['connected', 'degraded', 'disconnected', 'standalone', 'stopped'];

    function _presenceChip(presence, { faulted = false } = {}) {
        const normalized = PRESENCE_STATES.includes(String(presence || '')) ? String(presence) : 'stopped';
        const effective = faulted ? 'faulted' : normalized;
        const chip = document.createElement('span');
        chip.className = `kit-agent-presence-chip kit-agent-presence-${effective}`;
        chip.dataset.presence = effective;
        chip.textContent = dictValue(`agents.presence.${effective}`, effective);
        return chip;
    }

    function _trustTierChip(trustTier) {
        const value = String(trustTier || 'community').toLowerCase();
        const chip = document.createElement('span');
        chip.className = `kit-agent-trust-chip kit-agent-trust-${value}`;
        chip.textContent = dictValue(`agents.trust_tier.${value}`, value);
        return chip;
    }

    function agentsList({
        agents = [],
        search = '',
        presenceFilter = '',
        selectedId = '',
        onSearch = null,
        onPresenceFilter = null,
        onSelect = null,
        emptyHint = '',
    } = {}) {
        const root = document.createElement('div');
        root.className = 'kit-agents-list';

        const filters = document.createElement('div');
        filters.className = 'kit-agents-filters';
        const searchInput = document.createElement('input');
        searchInput.className = 'kit-agents-search';
        searchInput.type = 'search';
        searchInput.placeholder = dictValue('agents.search.placeholder', 'Search agents…');
        searchInput.value = String(search || '');
        if (typeof onSearch === 'function') {
            searchInput.addEventListener('input', (e) => onSearch(String(e.target.value || '')));
        }
        filters.appendChild(searchInput);

        const chips = document.createElement('div');
        chips.className = 'kit-agents-filter-chips';
        const options = ['', ...PRESENCE_STATES];
        options.forEach((value) => {
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'kit-agents-filter-chip';
            if (String(presenceFilter || '') === value) chip.classList.add('is-active');
            chip.textContent = value
                ? dictValue(`agents.presence.${value}`, value)
                : dictValue('agents.presence.filter.all', 'All');
            if (typeof onPresenceFilter === 'function') {
                chip.addEventListener('click', () => onPresenceFilter(value));
            }
            chips.appendChild(chip);
        });
        filters.appendChild(chips);
        root.appendChild(filters);

        const list = document.createElement('div');
        list.className = 'kit-agents-list-body';
        const entries = Array.isArray(agents) ? agents.filter(Boolean) : [];
        if (entries.length === 0) {
            list.appendChild(UI.renderEmptyState(
                emptyHint || dictValue('agents.empty', 'No agents match this view.'),
            ));
        } else {
            entries.forEach((agent) => {
                const row = document.createElement('div');
                row.className = 'kit-agents-list-row';
                if (String(agent.id || '') === String(selectedId || '')) {
                    row.classList.add('is-selected');
                }
                row.dataset.agentId = String(agent.id || '');

                const head = document.createElement('div');
                head.className = 'kit-agents-list-row-head';
                head.appendChild(_presenceChip(agent.presence, { faulted: agent.executionFaulted }));
                const title = document.createElement('span');
                title.className = 'kit-agents-list-row-title';
                title.textContent = String(agent.displayName || agent.slug || agent.id || '');
                head.appendChild(title);
                head.appendChild(_trustTierChip(agent.trustTier));
                row.appendChild(head);

                const sub = document.createElement('div');
                sub.className = 'kit-agents-list-row-subtitle';
                const parts = [
                    agent.role || '',
                    agent.provider || '',
                    agent.slug ? `@${agent.slug}` : '',
                    Number.isFinite(agent.currentCapacity) || Number.isFinite(agent.maxCapacity)
                        ? `capacity ${Number(agent.currentCapacity || 0)}/${Number(agent.maxCapacity || 1)}`
                        : '',
                    agent.lastHeartbeat ? UI.relativeTime(agent.lastHeartbeat) : '',
                ].filter(Boolean);
                sub.textContent = parts.join(' · ');
                row.appendChild(sub);

                if (typeof onSelect === 'function') {
                    row.addEventListener('click', () => onSelect(agent));
                }
                list.appendChild(row);
            });
        }
        root.appendChild(list);
        return root;
    }

    function agentSummary({ agent = null, emptyHint = '' } = {}) {
        const root = document.createElement('div');
        root.className = 'kit-agent-summary';
        if (!agent) {
            root.appendChild(UI.renderEmptyState(
                emptyHint || dictValue('agents.detail.firstrun', 'Select an agent to inspect presence, skills, workload, and admin actions.'),
            ));
            return root;
        }
        const capacity = `${Number(agent.current_capacity || 0)} / ${Number(agent.max_capacity || 1)}`;
        const metadata = [
            { label: dictValue('agents.summary.agent_id', 'Agent ID'), value: String(agent.agent_id || '') },
            { label: dictValue('agents.summary.slug', 'Slug'), value: String(agent.slug || '') },
            { label: dictValue('agents.summary.role', 'Role'), value: String(agent.role || '—') },
            { label: dictValue('agents.summary.provider', 'Provider'), value: String(agent.provider || '—') },
            { label: dictValue('agents.summary.trust_tier', 'Trust tier'), value: dictValue(`agents.trust_tier.${String(agent.trust_tier || 'community').toLowerCase()}`, String(agent.trust_tier || 'community')) },
            { label: dictValue('agents.summary.registry_scope', 'Scope'), value: String(agent.registry_scope || 'full') },
            { label: dictValue('agents.summary.version', 'Version'), value: String(agent.version || '—') },
            { label: dictValue('agents.summary.transport', 'Transport'), value: String(agent.connectivity_state || 'unknown') },
            { label: dictValue('agents.summary.execution', 'Execution'), value: String(agent.execution_state || 'healthy') },
            { label: dictValue('agents.summary.capacity', 'Capacity'), value: capacity },
            { label: dictValue('agents.summary.last_heartbeat', 'Last heartbeat'), value: agent.last_heartbeat_at ? UI.relativeTime(agent.last_heartbeat_at) : 'never' },
        ];
        root.appendChild(UI.renderMetadataGrid(metadata));

        const skills = Array.isArray(agent.routing_skills) ? agent.routing_skills.filter(Boolean) : [];
        if (skills.length) {
            const skillsLabel = document.createElement('div');
            skillsLabel.className = 'detail-label';
            skillsLabel.textContent = dictValue('agents.summary.skills', 'Advertised skills');
            root.appendChild(skillsLabel);
            const chips = document.createElement('div');
            chips.className = 'chip-row';
            skills.slice(0, 16).forEach((skill) => {
                const chip = document.createElement('span');
                chip.className = 'quickstart-chip static';
                chip.textContent = String(skill || '');
                chips.appendChild(chip);
            });
            if (skills.length > 16) {
                const more = document.createElement('span');
                more.className = 'quiet-note';
                more.textContent = `+${skills.length - 16} more`;
                chips.appendChild(more);
            }
            root.appendChild(chips);
        }
        return root;
    }

    function selectorResolutionPreview({
        selector = '',
        candidates = [],
        onResolve = null,
        busy = false,
        message = '',
        currentAgentId = '',
    } = {}) {
        const root = document.createElement('section');
        root.className = 'kit-selector-preview';

        const header = document.createElement('div');
        header.className = 'kit-selector-preview-header';
        const title = document.createElement('strong');
        title.textContent = dictValue('agents.selector.title', 'Selector resolution preview');
        header.appendChild(title);
        const help = document.createElement('p');
        help.className = 'quiet-note';
        help.textContent = dictValue('agents.selector.help', '');
        header.appendChild(help);
        root.appendChild(header);

        const form = document.createElement('div');
        form.className = 'kit-selector-preview-form';
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'kit-selector-preview-input';
        input.placeholder = dictValue('agents.selector.placeholder', '@skill:name');
        input.value = String(selector || '');
        form.appendChild(input);

        const resolveBtn = document.createElement('button');
        resolveBtn.type = 'button';
        resolveBtn.className = 'btn btn-sm btn-primary';
        resolveBtn.textContent = dictValue('agents.selector.run', 'Resolve');
        resolveBtn.disabled = Boolean(busy);
        if (typeof onResolve === 'function') {
            const submit = () => {
                const value = String(input.value || '').trim();
                if (value) onResolve(value);
            };
            resolveBtn.addEventListener('click', submit);
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    submit();
                }
            });
        }
        form.appendChild(resolveBtn);
        root.appendChild(form);

        if (message) {
            const note = document.createElement('div');
            note.className = 'kit-selector-preview-message quiet-note';
            note.textContent = String(message);
            root.appendChild(note);
        }

        const list = document.createElement('div');
        list.className = 'kit-selector-preview-results';
        const rows = Array.isArray(candidates) ? candidates.filter(Boolean) : [];
        if (rows.length === 0) {
            list.appendChild(UI.renderEmptyState(
                selector
                    ? dictValue('agents.selector.no_matches', 'No connected agents match this selector.')
                    : dictValue('agents.selector.empty', 'No candidates yet — enter a selector and press Resolve.'),
            ));
        } else {
            const resultsLabel = document.createElement('div');
            resultsLabel.className = 'detail-label';
            resultsLabel.textContent = dictValue('agents.selector.result_title', 'Candidates');
            list.appendChild(resultsLabel);
            rows.forEach((candidate) => {
                const row = document.createElement('div');
                row.className = 'kit-selector-preview-row';
                row.appendChild(_presenceChip(candidate.connectivity_state || 'connected'));
                const label = document.createElement('span');
                label.className = 'kit-selector-preview-row-title';
                label.textContent = String(candidate.display_name || candidate.slug || candidate.agent_id || '');
                row.appendChild(label);
                row.appendChild(_trustTierChip(candidate.trust_tier));
                const sub = document.createElement('span');
                sub.className = 'kit-selector-preview-row-subtitle';
                sub.textContent = [
                    candidate.role || '',
                    candidate.slug ? `@${candidate.slug}` : '',
                    Number.isFinite(candidate.current_capacity) || Number.isFinite(candidate.max_capacity)
                        ? `capacity ${Number(candidate.current_capacity || 0)}/${Number(candidate.max_capacity || 1)}`
                        : '',
                ].filter(Boolean).join(' · ');
                row.appendChild(sub);
                if (currentAgentId && String(candidate.agent_id || '') === String(currentAgentId)) {
                    const badge = document.createElement('span');
                    badge.className = 'kit-selector-preview-row-badge';
                    badge.textContent = dictValue('agents.selector.candidate_badge_current', 'current agent');
                    row.appendChild(badge);
                }
                list.appendChild(row);
            });
        }
        root.appendChild(list);
        return root;
    }

    return {
        dict,
        draftStateChip,
        lifecycleHeader,
        validationSurface,
        detailsPanel,
        authoredCatalog,
        canvas,
        rehearsalPanel,
        runsList,
        runSummary,
        agentsList,
        agentSummary,
        selectorResolutionPreview,
    };
})();
