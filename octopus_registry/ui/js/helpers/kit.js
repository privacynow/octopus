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
        'protocol.display_name.placeholder': 'Give this workflow a name',

        'protocol.slug.label': 'URL slug',
        'protocol.slug.help': 'Short identifier used in URLs. Auto-suggested from the name once you enter one.',
        'protocol.slug.placeholder': 'URL slug is generated from the name; editable later',

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
        'protocol.participants.firstrun': 'Add the first participant in the workflow.',
        'protocol.participants.add': '+ Add participant',
        'protocol.participant.display_name.label': 'Name',
        'protocol.participant.display_name.help': 'Name the reusable participant that owns one or more steps.',
        'protocol.participant.display_name.placeholder': 'e.g. Approver',
        'protocol.participant.participant_key.label': 'Key',
        'protocol.participant.participant_key.help': 'Internal reference for this participant. It is usually generated from the name.',
        'protocol.participant.participant_key.placeholder': 'approver',
        'protocol.participant.instructions.label': 'Instructions',
        'protocol.participant.instructions.help': 'Guidance shared across every step this participant owns.',
        'protocol.participant.instructions.placeholder': 'Instructions shared with this participant…',
        'protocol.participant.selector_kind.label': 'Assignment rule',
        'protocol.participant.selector_kind.help': 'How this protocol should find someone for this participant at runtime.',
        'protocol.participant.selector_kind.placeholder': 'Choose how to assign this participant…',
        'protocol.participant.selector_strategy.label': 'Strategy',
        'protocol.participant.selector_value.label': 'Rule value',
        'protocol.participant.selector_value.help': 'For example: a skill slug, a runtime role tag, or an agent slug.',
        'protocol.participant.selector_value.placeholder': 'e.g. legal-review, approver, m1',
        'protocol.participant.selector_preview.label': 'Who matches right now',
        'protocol.participant.selector_preview.help': 'Preview uses the shared registry selector resolution path. It is informational while you author the protocol.',
        'protocol.participant.selector_none': 'No rule yet',
        'protocol.participant.selector_current': 'Currently matches',
        'protocol.participant.selector_hint': 'Build a rule first, then preview who currently matches it.',
        'protocol.participant.selector_advanced.label': 'Advanced assignment',
        'protocol.participant.selector_advanced.strategy': 'Advanced strategy',
        'protocol.participant.selector_override.label': 'Custom value',

        // Details — stages
        'protocol.stages.section': 'Steps',
        'protocol.stages.firstrun': 'Add the first step in the workflow.',
        'protocol.stages.add': '+ Add step',
        'protocol.stage.display_name.label': 'Name',
        'protocol.stage.display_name.placeholder': 'e.g. Planning',
        'protocol.stage.display_name.help': 'Name of this step in the workflow.',
        'protocol.stage.stage_key.label': 'Key',
        'protocol.stage.stage_key.placeholder': 'planning',
        'protocol.stage.stage_key.help': 'Internal reference for this step. It is usually generated from the name.',
        'protocol.stage.participant_key.label': 'Owning participant',
        'protocol.stage.participant_key.help': 'Which participant owns this step.',
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
        'protocol.stage.inputs.label': 'Reads artifacts',
        'protocol.stage.inputs.help': 'Artifacts this stage needs before it starts.',
        'protocol.stage.outputs.label': 'Writes artifacts',
        'protocol.stage.outputs.help': 'Artifacts this stage produces or updates.',
        'protocol.stage.connect': 'Connect step',
        'protocol.stage.connect_help': 'Choose what should happen after this step, then click the next step or outcome.',

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
        'protocol.artifact.path.label': 'Workspace path',
        'protocol.artifact.path.help': 'Relative path inside the workspace for file-based artifacts.',
        'protocol.artifact.path.placeholder': 'docs/review-notes.md',
        'protocol.artifact.verify.label': 'Verify outputs',
        'protocol.artifact.verify.help': 'Keep verification on unless this artifact is intentionally advisory only.',

        // Details — transitions / policies
        'protocol.transition.details.label': 'Transition',
        'protocol.transition.decision.label': 'When this happens',
        'protocol.transition.decision.help': 'Label the outcome that sends the workflow to the next step.',
        'protocol.transition.decision.placeholder': 'completed',
        'protocol.transition.target.label': 'Next step',
        'protocol.transition.target.help': 'Choose the next stage or one of the terminal outcomes.',
        'protocol.transition.delete': 'Remove transition',
        'protocol.transition.target.complete': 'Finish successfully',
        'protocol.transition.target.failed': 'Finish as failed',
        'protocol.transition.target.cancelled': 'Finish as cancelled',
        'protocol.transition.connecting': 'Click the next stage or outcome to finish this transition.',
        'protocol.transition.cancel_connect': 'Cancel transition',
        'protocol.policy.single_active_writer.label': 'One active writer at a time',
        'protocol.policy.single_active_writer.help': 'Prevent multiple write-capable stages from running in parallel.',
        'protocol.policy.max_review_rounds.label': 'Max review loops',
        'protocol.policy.max_review_rounds.help': 'How many review loops the protocol allows before it must finish or fail.',

        // Details — overview
        'protocol.details.overview.empty': 'Select a participant, step, or artifact in the workspace — or edit the name and slug above.',
        'protocol.details.transition.empty': 'Select a transition to edit what happens next.',

        // Empty / first-run / onboarding
        'protocol.canvas.empty.title': 'Start the workflow',
        'protocol.canvas.empty.body': 'Add the first participant in the workflow, then define the first step it owns.',
        'protocol.catalog.empty.title': 'No protocols yet',
        'protocol.catalog.empty.body': 'Create one from a template in the Gallery, or start from a blank draft.',
        'protocol.catalog.title': 'Workflow definitions',
        'protocol.catalog.subtitle': 'Draft, publish, and rehearse reusable protocols without leaving the registry.',
        'protocol.catalog.search': 'Search protocols',
        'protocol.catalog.gallery': 'Browse template gallery',
        'protocol.firstrun.participant': 'Add the first participant.',
        'protocol.firstrun.stage': 'Add the first step for that participant.',
        'protocol.firstrun.transition': 'Connect the step to the next step or an outcome.',
        'protocol.workflow.outcomes': 'Outcomes',
        'protocol.workflow.artifacts': 'Artifacts',
        'protocol.workflow.drag_hint': 'Select a step to edit it, or drag it to reorganize the workflow.',
        'protocol.workflow.lane_hint': 'Participants in this workflow',
        'protocol.workflow.outcomes_hint': 'How the workflow can finish',

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
        'agents.selector.quick_picks': 'Quick picks',

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
        compact = false,
        primaryActions = ['validate', 'publish', 'rehearse'],
        secondaryActions = ['archive', 'discard'],
    } = {}) {
        const header = document.createElement('header');
        header.className = `kit-lifecycle-header${compact ? ' is-compact' : ''}`;
        const lifecycleState = String(record.lifecycle_state || 'draft');
        const availableActions = [
            permissions.canValidate !== false ? 'validate' : '',
            permissions.canPublish !== false ? 'publish' : '',
            permissions.canRehearse !== false ? 'rehearse' : '',
            permissions.canArchive !== false ? 'archive' : '',
            permissions.canDiscard !== false ? 'discard' : '',
        ].filter(Boolean);
        header.dataset.key = ['lifecycle-header', surfaceKey, lifecycleState, availableActions.join(',')].join('|');

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
        const chipBadge = document.createElement('span');
        chipBadge.dataset.key = 'lifecycle-state';
        chipBadge.className = `badge kit-lifecycle-chip kit-lifecycle-chip-${lifecycleState}`;
        chipBadge.textContent = dict.label(`${surfaceKey}.lifecycle.${lifecycleState}`);
        const chip = draftStateChip(saveState);

        const buttonSpec = [
            { key: 'validate', tone: '', permissionKey: 'canValidate' },
            { key: 'publish', tone: 'btn-primary', permissionKey: 'canPublish' },
            { key: 'rehearse', tone: '', permissionKey: 'canRehearse' },
            { key: 'archive', tone: 'btn-secondary', permissionKey: 'canArchive' },
            { key: 'discard', tone: 'btn-danger', permissionKey: 'canDiscard' },
        ];
        const buttons = [];
        buttonSpec.forEach(({ key, tone, permissionKey }) => {
            const handler = actions[key];
            if (!handler) return;
            if (permissions[permissionKey] === false) return;
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.dataset.key = `lifecycle-action-${key}`;
            btn.className = ['btn', tone].filter(Boolean).join(' ');
            btn.dataset.kitAction = key;
            btn.textContent = dict.label(`${surfaceKey}.action.${key}`);
            btn.addEventListener('click', () => handler(record));
            buttons.push({ key, btn });
        });

        if (compact) {
            const meta = document.createElement('div');
            meta.className = 'kit-lifecycle-meta';
            const slugText = document.createElement('span');
            slugText.className = 'kit-lifecycle-slug-chip';
            slugText.textContent = String(record.slug || '').trim() ? `protocol/${String(record.slug || '').trim()}` : 'Protocol settings';
            meta.appendChild(chipBadge);
            meta.appendChild(slugText);
            titleWrap.appendChild(meta);

            topRow.appendChild(titleWrap);

            const primary = document.createElement('div');
            primary.className = 'kit-lifecycle-primary';
            primary.appendChild(chip);
            buttons
                .filter(({ key }) => primaryActions.includes(key))
                .forEach(({ btn }) => primary.appendChild(btn));

            const overflow = document.createElement('details');
            overflow.className = 'kit-lifecycle-overflow';
            const overflowSummary = document.createElement('summary');
            overflowSummary.className = 'btn btn-small';
            overflowSummary.textContent = 'Protocol';
            overflowSummary.setAttribute('role', 'button');
            overflowSummary.setAttribute('aria-label', 'Protocol');
            overflow.appendChild(overflowSummary);
            const overflowBody = document.createElement('div');
            overflowBody.className = 'kit-lifecycle-overflow-body';
            if (onSlugCommit) {
                const slugRow = document.createElement('div');
                slugRow.className = 'kit-lifecycle-overflow-row';
                const slugLabel = document.createElement('label');
                slugLabel.className = 'kit-details-label';
                slugLabel.textContent = dict.label(`${surfaceKey}.slug.label`);
                slugRow.appendChild(slugLabel);
                slugRow.appendChild(slugInput);
                overflowBody.appendChild(slugRow);
            }
            const secondary = buttons.filter(({ key }) => secondaryActions.includes(key));
            if (secondary.length) {
                const secondaryRow = document.createElement('div');
                secondaryRow.className = 'kit-lifecycle-actions';
                secondary.forEach(({ btn }) => secondaryRow.appendChild(btn));
                overflowBody.appendChild(secondaryRow);
            }
            overflow.appendChild(overflowBody);
            primary.appendChild(overflow);
            topRow.appendChild(primary);
            header.appendChild(topRow);
        } else {
            titleWrap.appendChild(slugInput);
            topRow.appendChild(titleWrap);
            topRow.appendChild(chip);
            header.appendChild(topRow);

            const actionRow = document.createElement('div');
            actionRow.className = 'kit-lifecycle-actions';
            actionRow.appendChild(chipBadge);
            buttons.forEach(({ btn }) => actionRow.appendChild(btn));
            header.appendChild(actionRow);
        }

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
            if (compact) {
                const slugChip = header.querySelector('.kit-lifecycle-slug-chip');
                if (slugChip) {
                    slugChip.textContent = String(next.slug || '').trim() ? `protocol/${String(next.slug || '').trim()}` : 'Protocol settings';
                }
            }
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
        actions = [],
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
            } else if (kind === 'checklist') {
                control = document.createElement('div');
                control.className = 'kit-details-checklist';
                const selectedValues = Array.isArray(currentValue)
                    ? currentValue.map((item) => String(item || ''))
                    : [];
                (field.options || []).forEach((opt) => {
                    const itemLabel = document.createElement('label');
                    itemLabel.className = 'kit-details-checklist-item';
                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.value = String(opt.value);
                    checkbox.checked = selectedValues.includes(String(opt.value));
                    if (field.disabled || field.readOnly) checkbox.disabled = true;
                    if (typeof onCommit === 'function') {
                        checkbox.addEventListener('change', () => {
                            const values = Array.from(control.querySelectorAll('input[type="checkbox"]:checked'))
                                .map((el) => String(el.value || ''));
                            onCommit(target, field.key, values);
                        });
                    }
                    const text = document.createElement('span');
                    text.textContent = String(opt.label || opt.value);
                    itemLabel.appendChild(checkbox);
                    itemLabel.appendChild(text);
                    control.appendChild(itemLabel);
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
            if (kind === 'checklist') {
                control.id = '';
                label.htmlFor = '';
            } else if (kind === 'checkbox') {
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
            if (field.disabled) control.disabled = true;
            if (field.readOnly && kind !== 'checkbox' && kind !== 'select') control.readOnly = true;

            if (typeof onCommit === 'function' && kind !== 'checklist') {
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

        const actionItems = Array.isArray(actions) ? actions.filter(Boolean) : [];
        if (actionItems.length) {
            const actionsRow = document.createElement('div');
            actionsRow.className = 'kit-details-actions';
            actionItems.forEach((action) => {
                if (!action || typeof action.onClick !== 'function') return;
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = ['btn', action.tone || ''].filter(Boolean).join(' ');
                btn.textContent = String(action.label || 'Action');
                btn.disabled = Boolean(action.disabled);
                btn.addEventListener('click', () => action.onClick(target));
                actionsRow.appendChild(btn);
            });
            panel.appendChild(actionsRow);
        }

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
        secondaryAction = null,
    } = {}) {
        const container = document.createElement('section');
        container.className = 'kit-authored-catalog';

        const state = { lifecycleFilter, search };
        const hero = document.createElement('div');
        hero.className = 'kit-catalog-hero';

        const heroCopy = document.createElement('div');
        heroCopy.className = 'kit-catalog-hero-copy';
        const heroTitle = document.createElement('h3');
        heroTitle.className = 'kit-catalog-hero-title';
        heroTitle.textContent = dict.label(`${surfaceKey}.catalog.title`, 'Definitions');
        heroCopy.appendChild(heroTitle);
        const heroBody = document.createElement('p');
        heroBody.className = 'kit-catalog-hero-body';
        heroBody.textContent = dict.label(`${surfaceKey}.catalog.subtitle`, 'Manage reusable records here.');
        heroCopy.appendChild(heroBody);
        hero.appendChild(heroCopy);

        const heroMetrics = document.createElement('div');
        heroMetrics.className = 'kit-catalog-hero-metrics';
        const draftCount = records.filter((item) => String(item.lifecycle_state || 'draft') === 'draft').length;
        const publishedCount = records.filter((item) => String(item.lifecycle_state || '') === 'published').length;
        [
            { label: dict.label(`${surfaceKey}.lifecycle.draft`), value: draftCount },
            { label: dict.label(`${surfaceKey}.lifecycle.published`), value: publishedCount },
            { label: dict.label(`${surfaceKey}.lifecycle.filter.all`), value: records.length },
        ].forEach((metric) => {
            const chip = document.createElement('div');
            chip.className = 'kit-catalog-hero-metric';
            const value = document.createElement('strong');
            value.className = 'kit-catalog-hero-metric-value';
            value.textContent = String(metric.value);
            chip.appendChild(value);
            const label = document.createElement('span');
            label.className = 'kit-catalog-hero-metric-label';
            label.textContent = String(metric.label || '');
            chip.appendChild(label);
            heroMetrics.appendChild(chip);
        });
        hero.appendChild(heroMetrics);
        container.appendChild(hero);

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
        searchBox.placeholder = dict.label(`${surfaceKey}.catalog.search`, 'Search…');
        searchBox.value = state.search;
        searchBox.addEventListener('input', () => {
            state.search = searchBox.value;
            renderList();
        });
        controls.appendChild(searchBox);

        if (records.length && secondaryAction && typeof secondaryAction.onClick === 'function') {
            const secondaryBtn = document.createElement('button');
            secondaryBtn.type = 'button';
            secondaryBtn.className = 'btn';
            secondaryBtn.textContent = String(secondaryAction.label || 'Browse');
            secondaryBtn.addEventListener('click', secondaryAction.onClick);
            controls.appendChild(secondaryBtn);
        }

        if (records.length && createAction && typeof createAction.onClick === 'function') {
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
                const emptyCard = document.createElement('li');
                emptyCard.className = 'kit-catalog-item kit-catalog-item-empty';
                const emptyShell = document.createElement('div');
                emptyShell.className = 'kit-catalog-empty';
                const emptyTitle = document.createElement('h4');
                emptyTitle.className = 'kit-catalog-empty-title';
                emptyTitle.textContent = dict.label(`${surfaceKey}.catalog.empty.title`, 'Nothing here yet');
                emptyShell.appendChild(emptyTitle);
                const emptyBody = document.createElement('p');
                emptyBody.className = 'kit-catalog-empty-body';
                emptyBody.textContent = dict.emptyState(`${surfaceKey}.catalog.empty.body`, 'Nothing here yet.');
                emptyShell.appendChild(emptyBody);
                const emptyActions = document.createElement('div');
                emptyActions.className = 'kit-catalog-empty-actions';
                if (createAction && typeof createAction.onClick === 'function') {
                    const createBtn = document.createElement('button');
                    createBtn.type = 'button';
                    createBtn.className = 'btn btn-primary';
                    createBtn.textContent = String(createAction.label || 'Create');
                    createBtn.addEventListener('click', createAction.onClick);
                    emptyActions.appendChild(createBtn);
                }
                if (secondaryAction && typeof secondaryAction.onClick === 'function') {
                    const browseBtn = document.createElement('button');
                    browseBtn.type = 'button';
                    browseBtn.className = 'btn';
                    browseBtn.textContent = String(secondaryAction.label || 'Browse');
                    browseBtn.addEventListener('click', secondaryAction.onClick);
                    emptyActions.appendChild(browseBtn);
                }
                emptyShell.appendChild(emptyActions);
                emptyCard.appendChild(emptyShell);
                listEl.appendChild(emptyCard);
                return;
            }
            filtered.forEach((record) => {
                const li = document.createElement('li');
                li.className = 'kit-catalog-item';
                const lifecycle = String(record.lifecycle_state || 'draft');
                const chip = document.createElement('span');
                chip.className = `badge kit-lifecycle-chip kit-lifecycle-chip-${lifecycle}`;
                chip.textContent = dict.label(`${surfaceKey}.lifecycle.${lifecycle}`);

                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'kit-catalog-card';
                if (typeof onOpen === 'function') {
                    button.addEventListener('click', () => onOpen(record));
                }

                const top = document.createElement('div');
                top.className = 'kit-catalog-card-top';
                const titleBlock = document.createElement('div');
                titleBlock.className = 'kit-catalog-card-copy';
                const title = document.createElement('div');
                title.className = 'kit-catalog-card-title';
                title.textContent = String(record.display_name || record.slug || record.id || 'Untitled');
                titleBlock.appendChild(title);
                const slug = document.createElement('div');
                slug.className = 'kit-catalog-card-slug';
                slug.textContent = String(record.slug || '');
                titleBlock.appendChild(slug);
                top.appendChild(titleBlock);
                top.appendChild(chip);
                button.appendChild(top);

                const description = document.createElement('p');
                description.className = 'kit-catalog-card-body';
                description.textContent = String(record.description || 'Open this protocol to edit stages, transitions, and rehearsal flow.');
                button.appendChild(description);

                const meta = document.createElement('div');
                meta.className = 'kit-catalog-card-meta';
                const updated = document.createElement('span');
                updated.className = 'kit-catalog-card-meta-item';
                updated.textContent = record.updated_at ? `Updated ${UI.relativeTime(record.updated_at)}` : 'Updated just now';
                meta.appendChild(updated);
                if (record.current_version_id) {
                    const published = document.createElement('span');
                    published.className = 'kit-catalog-card-meta-item';
                    published.textContent = 'Versioned';
                    meta.appendChild(published);
                }
                button.appendChild(meta);

                li.appendChild(button);
                listEl.appendChild(li);
            });
        }

        renderList();
        return container;
    }

    // -----------------------------------------------------------------------
    // Section list canvas
    //
    // Grouped list primitive retained for non-graph surfaces. Protocol
    // authoring no longer consumes it; see workflowCanvas below.
    // -----------------------------------------------------------------------
    function sectionListCanvas({
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
                add.addEventListener('click', (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    section.onAdd();
                });
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
                    placeholder.addEventListener('click', (event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        section.onAdd();
                    });
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
                    li.className = `kit-canvas-node-wrap${isSelected ? ' is-selected' : ''}`;
                    // Stable key for morphdom reconciliation (helpers/ui.js getNodeKey uses dataset.key).
                    li.dataset.key = `canvas-${section.key}-${nodeKey}`;

                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'kit-canvas-node';
                    btn.dataset.nodeKey = nodeKey;

                    const label = document.createElement('div');
                    label.className = 'kit-canvas-node-label';
                    label.textContent = String(node.label || nodeKey);
                    btn.appendChild(label);

                    if (node.sublabel) {
                        const sub = document.createElement('div');
                        sub.className = 'kit-canvas-node-sublabel';
                        sub.textContent = String(node.sublabel);
                        btn.appendChild(sub);
                    }

                    if (typeof onSelect === 'function') {
                        btn.addEventListener('click', (event) => {
                            event.preventDefault();
                            event.stopPropagation();
                            onSelect({ sectionKey: section.key, nodeKey });
                        });
                    }

                    li.appendChild(btn);
                    list.appendChild(li);
                });
            }

            group.appendChild(list);
            root.appendChild(group);
        });

        return root;
    }

    function workflowCanvas({
        lanes = [],
        nodes = [],
        edges = [],
        selection = null,
        onSelect = null,
        onBeginConnect = null,
        onCancelConnect = null,
        onMutate = null,
        firstRun = null,
        mode = 'graph',
        editorMode = null,
        accessorySections = [],
        toolbarActions = [],
        nodeStates = {},
        laneLabels = {},
        outcomes = null,
        viewState = null,
        viewportState = {},
        onViewportChange = null,
    } = {}) {
        const root = document.createElement('section');
        root.className = `kit-workflow-canvas kit-workflow-canvas-${mode} kit-workflow-view-${String(viewState?.kind || 'detail')}`;
        root.dataset.key = [
            'workflow-canvas',
            mode,
            String(viewState?.kind || ''),
            String(viewState?.title || ''),
            lanes.map((lane) => String(lane.key || '')).join(','),
            nodes.map((node) => String(node.id || '')).join(','),
            edges.map((edge) => String(edge.id || '')).join(','),
            String(firstRun?.body || ''),
            String(editorMode?.kind || ''),
            String(editorMode?.sourceStageKey || ''),
            String(editorMode?.decision || ''),
        ].join('|');
        root.tabIndex = 0;
        const currentView = String(viewState?.kind || 'detail');
        const isOverview = currentView === 'overview';
        const isTopology = currentView === 'topology';
        const topologyScope = String(viewState?.scope || 'full');

        if (firstRun && firstRun.active) {
            const card = document.createElement('div');
            card.className = 'kit-workflow-first-run';

            const title = document.createElement('h3');
            title.className = 'kit-workflow-first-run-title';
            title.textContent = String(firstRun.title || dictValue('protocol.canvas.empty.title', 'Design your workflow'));
            card.appendChild(title);

            const body = document.createElement('p');
            body.className = 'kit-workflow-first-run-body';
            body.textContent = String(firstRun.body || dictValue('protocol.canvas.empty.body', 'Start by adding the first participant.'));
            card.appendChild(body);

            const actions = document.createElement('div');
            actions.className = 'kit-workflow-first-run-actions';
            (Array.isArray(firstRun.actions) ? firstRun.actions : []).forEach((action) => {
                if (!action || typeof action.onClick !== 'function') return;
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = ['btn', action.tone || 'btn-primary'].filter(Boolean).join(' ');
                btn.textContent = String(action.label || 'Continue');
                btn.addEventListener('click', action.onClick);
                actions.appendChild(btn);
            });
            card.appendChild(actions);
            root.appendChild(card);
        }

        const actions = Array.isArray(toolbarActions) ? toolbarActions.filter(Boolean) : [];
        const currentMode = String(editorMode?.kind || 'idle');
        const toolbarHint = currentMode === 'connect'
            ? dictValue('protocol.transition.connecting', 'Connecting this step. Click the next step or finish outcome.')
            : currentMode === 'rehearse'
                ? 'Viewing live rehearsal state on the published workflow.'
                : '';
        if (viewState?.title || viewState?.subtitle) {
            const viewBar = document.createElement('div');
            viewBar.className = 'kit-workflow-viewbar';
            const title = document.createElement('strong');
            title.className = 'kit-workflow-viewbar-title';
            title.textContent = String(viewState?.title || (isOverview ? 'Workflow overview' : 'Workflow'));
            viewBar.appendChild(title);
            if (viewState?.subtitle) {
                const subtitle = document.createElement('span');
                subtitle.className = 'kit-workflow-viewbar-subtitle';
                subtitle.textContent = String(viewState.subtitle || '');
                viewBar.appendChild(subtitle);
            }
            root.appendChild(viewBar);
        }
        if (!firstRun?.active || currentMode === 'connect' || currentMode === 'rehearse') {
            const toolbar = document.createElement('div');
            toolbar.className = 'kit-workflow-toolbar';
            if (toolbarHint) {
                const hint = document.createElement('div');
                hint.className = 'kit-workflow-toolbar-hint';
                hint.textContent = toolbarHint;
                toolbar.appendChild(hint);
            }
            if (currentMode === 'connect' && typeof onCancelConnect === 'function') {
                const cancelBtn = document.createElement('button');
                cancelBtn.type = 'button';
                cancelBtn.className = 'btn btn-small';
                cancelBtn.textContent = dictValue('protocol.transition.cancel_connect', 'Cancel transition');
                cancelBtn.addEventListener('click', onCancelConnect);
                toolbar.appendChild(cancelBtn);
            }
            if (actions.length) {
                const actionBar = document.createElement('div');
                actionBar.className = 'kit-workflow-toolbar-actions';
                actions.forEach((action) => {
                    if (!action || typeof action.onClick !== 'function') return;
                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = ['btn', action.tone || 'btn-small'].filter(Boolean).join(' ');
                    btn.textContent = String(action.label || '');
                    btn.disabled = Boolean(action.disabled);
                    btn.addEventListener('click', action.onClick);
                    actionBar.appendChild(btn);
                });
                toolbar.appendChild(actionBar);
            }
            root.appendChild(toolbar);
        }

        function _orderedNodes() {
            return [...nodes].sort((a, b) => {
                const aOrder = Number(a.order);
                const bOrder = Number(b.order);
                if (Number.isFinite(aOrder) || Number.isFinite(bOrder)) {
                    if (!Number.isFinite(aOrder)) return 1;
                    if (!Number.isFinite(bOrder)) return -1;
                    if (aOrder !== bOrder) return aOrder - bOrder;
                }
                const aCol = Number(a.column || 0);
                const bCol = Number(b.column || 0);
                if (aCol !== bCol) return aCol - bCol;
                const aRow = Number(a.row || 0);
                const bRow = Number(b.row || 0);
                if (aRow !== bRow) return aRow - bRow;
                return String(a.id || '').localeCompare(String(b.id || ''));
            });
        }

        function _moveSelection(delta) {
            if (typeof onSelect !== 'function') return;
            const ordered = _orderedNodes();
            if (!ordered.length) return;
            const currentId = String(selection?.id || '');
            const idx = Math.max(0, ordered.findIndex((item) => String(item.id || '') === currentId));
            const next = ordered[Math.max(0, Math.min(ordered.length - 1, idx + delta))];
            if (next) onSelect({ kind: next.kind, id: next.id });
        }

        root.addEventListener('keydown', (event) => {
            if ((event.metaKey || event.ctrlKey) && String(event.key || '').toLowerCase() === 'z' && typeof onMutate === 'function') {
                event.preventDefault();
                onMutate({ type: event.shiftKey ? 'redo' : 'undo' });
                return;
            }
            if (event.key === 'Escape' && currentMode === 'connect' && typeof onCancelConnect === 'function') {
                event.preventDefault();
                onCancelConnect();
                return;
            }
            if (event.target && !root.contains(event.target)) return;
            if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
                event.preventDefault();
                _moveSelection(1);
            } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
                event.preventDefault();
                _moveSelection(-1);
            }
        });

        if (!nodes.length && !lanes.length) {
            // True blank-first-run state: no fake graph, no decorative lanes.
        } else if (isOverview) {
            const ordered = _orderedNodes();
            const overview = document.createElement('div');
            overview.className = 'kit-workflow-overview';
            ordered.forEach((node, index) => {
                const row = document.createElement('div');
                row.className = 'kit-workflow-overview-row';

                const rail = document.createElement('div');
                rail.className = 'kit-workflow-overview-rail';

                const order = document.createElement('span');
                order.className = 'kit-workflow-overview-order';
                order.textContent = String(index + 1).padStart(2, '0');
                rail.appendChild(order);

                if (index < ordered.length - 1) {
                    const connector = document.createElement('span');
                    connector.className = 'kit-workflow-overview-connector';
                    rail.appendChild(connector);
                }
                row.appendChild(rail);

                const card = document.createElement('button');
                card.type = 'button';
                card.className = `kit-workflow-overview-card${selection?.kind === 'segment' && selection?.id === node.id ? ' is-selected' : ''}`;
                card.dataset.testid = `workflow-node-${String(node.id || '')}`;
                card.dataset.nodeId = String(node.id || '');
                if (typeof onSelect === 'function') {
                    card.addEventListener('click', () => onSelect({ kind: node.kind, id: node.id }));
                }

                const top = document.createElement('div');
                top.className = 'kit-workflow-overview-card-top';

                const badges = (Array.isArray(node.badges) ? node.badges : []).slice(0, 2);
                if (badges.length) {
                    const badgeRow = document.createElement('div');
                    badgeRow.className = 'kit-workflow-overview-badges';
                    badges.forEach((badge) => {
                        const chip = document.createElement('span');
                        chip.className = `kit-workflow-node-badge${badge?.tone ? ` is-${badge.tone}` : ''}`;
                        chip.textContent = String(badge?.label || '');
                        badgeRow.appendChild(chip);
                    });
                    top.appendChild(badgeRow);
                }
                card.appendChild(top);

                const label = document.createElement('div');
                label.className = 'kit-workflow-overview-label';
                label.textContent = String(node.label || node.id || '');
                card.appendChild(label);

                if (node.sublabel) {
                    const sub = document.createElement('div');
                    sub.className = 'kit-workflow-overview-sublabel';
                    sub.textContent = String(node.sublabel || '');
                    card.appendChild(sub);
                }

                if (node.preview) {
                    const preview = document.createElement('div');
                    preview.className = 'kit-workflow-overview-preview';
                    preview.textContent = String(node.preview || '');
                    card.appendChild(preview);
                }

                const stageNames = Array.isArray(node.stageNames) ? node.stageNames.filter(Boolean) : [];
                if (stageNames.length) {
                    const sequence = document.createElement('div');
                    sequence.className = 'kit-workflow-overview-stages';
                    stageNames.slice(0, 5).forEach((name) => {
                        const pill = document.createElement('span');
                        pill.className = 'kit-workflow-overview-stage';
                        pill.textContent = String(name || '');
                        sequence.appendChild(pill);
                    });
                    if (stageNames.length > 5) {
                        const extra = document.createElement('span');
                        extra.className = 'kit-workflow-overview-stage is-muted';
                        extra.textContent = `+ ${stageNames.length - 5} more`;
                        sequence.appendChild(extra);
                    }
                    card.appendChild(sequence);
                }

                const routes = Array.isArray(node.routes) ? node.routes.filter(Boolean) : [];
                if (routes.length) {
                    const routeList = document.createElement('div');
                    routeList.className = 'kit-workflow-overview-routes';
                    routes.forEach((route) => {
                        const routeRow = document.createElement('div');
                        routeRow.className = 'kit-workflow-overview-route';

                        const decision = document.createElement('span');
                        decision.className = 'kit-workflow-node-badge is-context';
                        decision.textContent = String(route.label || 'Next');
                        routeRow.appendChild(decision);

                        const routeBody = document.createElement('span');
                        routeBody.className = 'kit-workflow-overview-route-body';
                        routeBody.textContent = `${String(route.targetLabel || '')} · ${String(route.metaLabel || '')}`;
                        routeRow.appendChild(routeBody);

                        routeList.appendChild(routeRow);
                    });
                    card.appendChild(routeList);
                }

                if (node.footnote) {
                    const foot = document.createElement('div');
                    foot.className = 'kit-workflow-overview-footnote';
                    foot.textContent = String(node.footnote || '');
                    card.appendChild(foot);
                }

                row.appendChild(card);
                overview.appendChild(row);
            });
            root.appendChild(overview);
        } else {
            const shell = document.createElement('div');
            shell.className = 'kit-workflow-shell';
            const denseMode = (isTopology && topologyScope === 'full') || nodes.length >= 8;

            const controls = document.createElement('div');
            controls.className = 'kit-workflow-controls';
            const viewport = document.createElement('div');
            viewport.className = 'kit-workflow-viewport';

            const rowHeight = isTopology ? (topologyScope === 'full' ? 88 : 96) : denseMode ? 82 : 92;
            const rowGap = isTopology ? (topologyScope === 'full' ? 18 : 14) : denseMode ? 10 : 14;
            const columnWidth = isTopology ? (topologyScope === 'full' ? 214 : 224) : denseMode ? 194 : 214;
            const columnGap = isTopology ? (topologyScope === 'full' ? 28 : 24) : denseMode ? 18 : 24;
            const leftPad = lanes.length ? (isTopology ? 84 : denseMode ? 94 : 108) : (isTopology ? 34 : 18);
            const rightPad = isTopology ? 34 : denseMode ? 18 : 24;
            const bottomPad = 24;
            const laneIndex = new Map(lanes.map((lane, index) => [String(lane.key || ''), index]));
            const nodeRow = (node) => {
                if (Number.isFinite(Number(node.row))) return Number(node.row);
                const laneRow = laneIndex.get(String(node.laneKey || ''));
                return Number.isFinite(Number(laneRow)) ? Number(laneRow) : 0;
            };
            const nodeBox = (node) => {
                if (node.isTerminal) {
                    return { width: isTopology ? (topologyScope === 'full' ? 154 : 168) : denseMode ? 140 : 148, height: isTopology ? (topologyScope === 'full' ? 60 : 66) : denseMode ? 58 : 64 };
                }
                if (node.isContext) {
                    return { width: isTopology ? (topologyScope === 'full' ? 170 : 182) : denseMode ? 158 : 166, height: isTopology ? (topologyScope === 'full' ? 64 : 72) : denseMode ? 64 : 70 };
                }
                if (node.kind === 'segment') {
                    return { width: isTopology ? (topologyScope === 'full' ? 178 : 190) : denseMode ? 168 : 178, height: isTopology ? (topologyScope === 'full' ? 68 : 76) : denseMode ? 68 : 74 };
                }
                return { width: isTopology ? (topologyScope === 'full' ? 198 : 220) : denseMode ? 184 : 198, height: isTopology ? (topologyScope === 'full' ? 88 : 102) : denseMode ? 84 : 92 };
            };
            const nodeById = new Map(nodes.map((node) => [String(node.id || ''), node]));
            const backEdges = edges.filter((edge) => {
                const fromNode = nodeById.get(String(edge.from || ''));
                const toNode = nodeById.get(String(edge.to || ''));
                return toNode && fromNode && Number(toNode.column || 0) <= Number(fromNode.column || 0);
            });
            const routeHeadroom = backEdges.length
                ? (isTopology && topologyScope !== 'full' ? 8 + (backEdges.length * 8) : 14 + (backEdges.length * 18))
                : (isTopology && topologyScope !== 'full' ? 8 : 14);
            const topPad = (isTopology && topologyScope !== 'full' ? 14 : 18) + routeHeadroom;
            const maxColumn = Math.max(0, ...nodes.map((node) => Number(node.column || 0)));
            const maxRow = Math.max(0, ...nodes.map((node) => nodeRow(node)));
            const graphWidth = leftPad + rightPad + ((maxColumn + 1) * columnWidth) + (Math.max(0, maxColumn) * columnGap);
            const graphHeight = topPad + bottomPad + ((maxRow + 1) * rowHeight) + (Math.max(0, maxRow) * rowGap);

            const layout = new Map();
            nodes.forEach((node) => {
                const row = Math.max(0, nodeRow(node));
                const size = nodeBox(node);
                const x = leftPad + (Number(node.column || 0) * (columnWidth + columnGap)) + Math.max(0, Math.floor((columnWidth - size.width) / 2));
                const y = topPad + (row * (rowHeight + rowGap)) + Math.max(0, Math.floor((rowHeight - size.height) / 2));
                layout.set(String(node.id || ''), {
                    x,
                    y,
                    width: size.width,
                    height: size.height,
                    row,
                    column: Number(node.column || 0),
                });
            });

            const graphFrame = document.createElement('div');
            graphFrame.className = 'kit-workflow-frame';

            const graph = document.createElement('div');
            graph.className = 'kit-workflow-graph';
            graph.style.width = `${graphWidth}px`;
            graph.style.height = `${graphHeight}px`;
            graph.style.setProperty('--workflow-columns', String(Math.max(1, maxColumn + 1)));
            graph.style.setProperty('--workflow-rows', String(Math.max(1, maxRow + 1)));
            graph.style.setProperty('--workflow-lane-gutter', `${leftPad}px`);

            const guidesLayer = document.createElement('div');
            guidesLayer.className = 'kit-workflow-guide-layer';
            lanes.forEach((lane) => {
                const guide = document.createElement('div');
                guide.className = 'kit-workflow-lane-guide';
                const laneMeta = laneLabels[String(lane.key || '')] || {};
                const row = Math.max(0, Number(laneMeta.row || laneIndex.get(String(lane.key || '')) || 0));
                guide.style.top = `${topPad + (row * (rowHeight + rowGap))}px`;
                guide.style.height = `${rowHeight}px`;
                const label = document.createElement('button');
                label.type = 'button';
                label.className = `kit-workflow-lane-guide-label${selection?.kind === 'participant' && selection?.id === lane.key ? ' is-selected' : ''}`;
                label.dataset.testid = `workflow-lane-${String(lane.key || '')}`;
                label.textContent = String(laneMeta.label || lane.label || lane.key || '');
                if (typeof onSelect === 'function') {
                    label.addEventListener('click', () => onSelect({ kind: 'participant', id: lane.key }));
                }
                guide.appendChild(label);
                if (laneMeta.sublabel && !denseMode && !isTopology) {
                    const sub = document.createElement('div');
                    sub.className = 'kit-workflow-lane-guide-sublabel';
                    sub.textContent = String(laneMeta.sublabel || '');
                    guide.appendChild(sub);
                }
                const rule = document.createElement('div');
                rule.className = 'kit-workflow-lane-guide-rule';
                guide.appendChild(rule);
                guidesLayer.appendChild(guide);
            });
            if (outcomes && Number(outcomes.count || 0) > 0) {
                const guide = document.createElement('div');
                guide.className = 'kit-workflow-lane-guide is-outcomes';
                guide.style.top = `${topPad + (Number(outcomes.startRow || 0) * (rowHeight + rowGap))}px`;
                guide.style.height = `${(Number(outcomes.count || 0) * rowHeight) + (Math.max(0, Number(outcomes.count || 0) - 1) * rowGap)}px`;
                const label = document.createElement('div');
                label.className = 'kit-workflow-lane-guide-label is-static';
                label.textContent = String(outcomes.label || 'Outcomes');
                guide.appendChild(label);
                const rule = document.createElement('div');
                rule.className = 'kit-workflow-lane-guide-rule';
                guide.appendChild(rule);
                guidesLayer.appendChild(guide);
            }
            graph.appendChild(guidesLayer);

            const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.setAttribute('class', 'kit-workflow-edges');
            svg.setAttribute('aria-hidden', 'true');
            svg.setAttribute('viewBox', `0 0 ${graphWidth} ${graphHeight}`);
            const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
            const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
            marker.setAttribute('id', 'kit-workflow-arrow');
            marker.setAttribute('markerWidth', '8');
            marker.setAttribute('markerHeight', '8');
            marker.setAttribute('refX', '7');
            marker.setAttribute('refY', '4');
            marker.setAttribute('orient', 'auto');
            const markerPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            markerPath.setAttribute('d', 'M 0 0 L 8 4 L 0 8 z');
            markerPath.setAttribute('fill', 'currentColor');
            marker.appendChild(markerPath);
            defs.appendChild(marker);
            svg.appendChild(defs);
            graph.appendChild(svg);

            const labelsLayer = document.createElement('div');
            labelsLayer.className = 'kit-workflow-edge-labels';
            graph.appendChild(labelsLayer);

            const nodesLayer = document.createElement('div');
            nodesLayer.className = 'kit-workflow-nodes-layer';
            graph.appendChild(nodesLayer);

            let draggedNodeId = '';
            nodes.forEach((node) => {
                const nodeLayout = layout.get(String(node.id || ''));
                if (!nodeLayout) return;
                const isConnectSource = String(editorMode?.sourceStageKey || '') === String(node.id || '');
                const isConnectTarget = currentMode === 'connect'
                    && String(editorMode?.sourceStageKey || '') !== String(node.id || '')
                    && (node.kind === 'stage' || node.kind === 'terminal');

                const wrap = document.createElement('div');
                wrap.className = [
                    'kit-workflow-node-wrap',
                    selection?.kind === node.kind && selection?.id === node.id ? 'is-selected' : '',
                    node.isTerminal ? 'is-terminal' : '',
                    node.isContext ? 'is-context' : '',
                    isConnectSource ? 'is-connect-source' : '',
                    isConnectTarget ? 'is-connect-target' : '',
                ].filter(Boolean).join(' ');
                wrap.dataset.nodeId = String(node.id || '');
                wrap.style.left = `${nodeLayout.x}px`;
                wrap.style.top = `${nodeLayout.y}px`;
                wrap.style.width = `${nodeLayout.width}px`;
                wrap.style.height = `${nodeLayout.height}px`;

                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = `kit-workflow-node kit-workflow-node-${node.kind || 'stage'}`;
                btn.dataset.nodeId = String(node.id || '');
                btn.dataset.testid = `workflow-node-${String(node.id || '')}`;
                btn.title = String(node.label || node.id || '');
                btn.draggable = Boolean(node.kind === 'stage' && typeof onMutate === 'function');
                if (node.kind === 'stage' && typeof onMutate === 'function') {
                    btn.addEventListener('dragstart', () => {
                        draggedNodeId = String(node.id || '');
                        wrap.classList.add('is-dragging');
                    });
                    btn.addEventListener('dragend', () => {
                        draggedNodeId = '';
                        wrap.classList.remove('is-dragging');
                    });
                    btn.addEventListener('dragover', (event) => event.preventDefault());
                    btn.addEventListener('drop', (event) => {
                        event.preventDefault();
                        if (draggedNodeId && draggedNodeId !== String(node.id || '')) {
                            onMutate({ type: 'reorder', nodeId: draggedNodeId, targetId: String(node.id || '') });
                        }
                    });
                }
                if (typeof onSelect === 'function') {
                    btn.addEventListener('click', () => onSelect({ kind: node.kind, id: node.id }));
                }

                const metaRow = document.createElement('div');
                metaRow.className = 'kit-workflow-node-meta';
                const visibleBadges = (Array.isArray(node.badges) ? node.badges : []).slice(0, denseMode ? 1 : 2);
                if (visibleBadges.length) {
                    const badgeRow = document.createElement('div');
                    badgeRow.className = 'kit-workflow-node-badges';
                    visibleBadges.forEach((badge) => {
                        if (!badge) return;
                        const chip = document.createElement('span');
                        chip.className = `kit-workflow-node-badge${badge.tone ? ` is-${badge.tone}` : ''}`;
                        chip.textContent = String(badge.label || '');
                        badgeRow.appendChild(chip);
                    });
                    metaRow.appendChild(badgeRow);
                }

                const state = nodeStates && Object.prototype.hasOwnProperty.call(nodeStates, String(node.id || ''))
                    ? String(nodeStates[String(node.id || '')] || '')
                    : '';
                if (state) {
                    const badge = document.createElement('span');
                    badge.className = `kit-workflow-node-state kit-workflow-node-state-${state}`;
                    badge.textContent = state;
                    metaRow.appendChild(badge);
                }
                if (metaRow.childElementCount) {
                    btn.appendChild(metaRow);
                }

                const label = document.createElement('div');
                label.className = 'kit-workflow-node-label';
                label.textContent = String(node.label || node.id || '');
                btn.appendChild(label);

                if (node.sublabel) {
                    const sub = document.createElement('div');
                    sub.className = 'kit-workflow-node-sublabel';
                    sub.textContent = String(node.sublabel);
                    btn.appendChild(sub);
                }

                wrap.appendChild(btn);
                nodesLayer.appendChild(wrap);
            });

            const backEdgeOrder = new Map();
            edges.forEach((edge) => {
                const fromLayout = layout.get(String(edge.from || ''));
                const toLayout = layout.get(String(edge.to || ''));
                if (fromLayout && toLayout && toLayout.column <= fromLayout.column) {
                    backEdgeOrder.set(String(edge.id || ''), backEdgeOrder.size);
                }
            });
            const nodeBoxes = Array.from(layout.values()).map((item) => ({
                left: item.x - 10,
                right: item.x + item.width + 10,
                top: item.y - 10,
                bottom: item.y + item.height + 10,
            }));
            const labelBoxes = [];
            function estimateLabelBox(text, x, y) {
                    const width = Math.min(isTopology ? 128 : 176, Math.max(48, (String(text || '').length * 7) + 28));
                const height = 24;
                return {
                    width,
                    height,
                    left: Number(x || 0) - (width / 2),
                    right: Number(x || 0) + (width / 2),
                    top: Number(y || 0) - (height / 2),
                    bottom: Number(y || 0) + (height / 2),
                };
            }
            function overlapsBox(left, right, top, bottom, target) {
                return left < target.right
                    && right > target.left
                    && top < target.bottom
                    && bottom > target.top;
            }
            function placeLabel(text, candidates) {
                for (const candidate of candidates) {
                    const box = estimateLabelBox(text, candidate.x, candidate.y);
                    const nodeCollision = nodeBoxes.some((target) => overlapsBox(box.left, box.right, box.top, box.bottom, target));
                    const labelCollision = labelBoxes.some((target) => overlapsBox(box.left, box.right, box.top, box.bottom, target));
                    if (!nodeCollision && !labelCollision) {
                        labelBoxes.push(box);
                        return candidate;
                    }
                }
                return null;
            }

            edges.forEach((edge) => {
                const fromLayout = layout.get(String(edge.from || ''));
                const toLayout = layout.get(String(edge.to || ''));
                if (!fromLayout || !toLayout) return;

                const fromX = fromLayout.x + fromLayout.width;
                const fromY = fromLayout.y + (fromLayout.height / 2);
                const toX = toLayout.x;
                const toY = toLayout.y + (toLayout.height / 2);
                const selected = selection?.kind === 'transition' && selection?.id === edge.id;
                const isBackEdge = toLayout.column <= fromLayout.column;

                let pathData = '';
                let labelCandidates = [];

                if (isBackEdge) {
                    const bandIndex = Number(backEdgeOrder.get(String(edge.id || '')) || 0);
                    const trackY = 16 + (bandIndex * 22);
                    const exitX = fromX + 18;
                    const entryX = Math.max(leftPad - 10, toX - 18);
                    pathData = [
                        `M ${fromX} ${fromY}`,
                        `L ${exitX} ${fromY}`,
                        `L ${exitX} ${trackY}`,
                        `L ${entryX} ${trackY}`,
                        `L ${entryX} ${toY}`,
                        `L ${toX} ${toY}`,
                    ].join(' ');
                    const centerX = entryX + ((exitX - entryX) / 2);
                    labelCandidates = [
                        { x: centerX, y: trackY - 12 },
                        { x: centerX, y: trackY + 14 },
                        { x: entryX + 28, y: trackY - 12 },
                    ];
                } else {
                const bendX = fromX + Math.max(22, Math.floor((toX - fromX) / 2));
                pathData = [
                    `M ${fromX} ${fromY}`,
                    `L ${bendX} ${fromY}`,
                    `L ${bendX} ${toY}`,
                    `L ${toX} ${toY}`,
                    ].join(' ');
                    if (Math.abs(fromY - toY) < 8) {
                        const midX = fromX + ((toX - fromX) / 2);
                        labelCandidates = [
                            { x: midX, y: fromY - 18 },
                            { x: midX, y: fromY + 20 },
                            { x: bendX - 26, y: fromY - 18 },
                        ];
                    } else {
                        const midY = fromY + ((toY - fromY) / 2);
                        labelCandidates = [
                            { x: bendX + 24, y: midY },
                            { x: bendX - 24, y: midY },
                            { x: bendX, y: midY - 18 },
                            { x: bendX, y: midY + 18 },
                        ];
                    }
                }

                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('class', `kit-workflow-edge-path${edge?.tone ? ` is-${edge.tone}` : ''}${selected ? ' is-selected' : ''}`);
                path.setAttribute('d', pathData);
                path.setAttribute('marker-end', 'url(#kit-workflow-arrow)');
                if (typeof onSelect === 'function') {
                    path.style.pointerEvents = 'visibleStroke';
                    path.style.cursor = 'pointer';
                    path.addEventListener('click', () => onSelect({ kind: 'transition', id: edge.id }));
                }
                svg.appendChild(path);

                if (edge.showLabel === false || !String(edge.label || '').trim()) {
                    return;
                }
                let reserved = placeLabel(String(edge.label || ''), labelCandidates);
                if (!reserved) {
                    if (isTopology || !labelCandidates.length) {
                        return;
                    }
                    reserved = labelCandidates[0];
                }
                const label = document.createElement('button');
                label.type = 'button';
                label.className = `kit-workflow-edge-label${selected ? ' is-selected' : ''}`;
                label.dataset.testid = `workflow-edge-${String(edge.id || '')}`;
                label.textContent = String(edge.label || '');
                label.style.left = `${reserved.x}px`;
                label.style.top = `${reserved.y}px`;
                if (typeof onSelect === 'function') {
                    label.addEventListener('click', () => onSelect({ kind: 'transition', id: edge.id }));
                }
                labelsLayer.appendChild(label);
            });

            const defaultZoom = Object.prototype.hasOwnProperty.call(viewportState || {}, 'zoom')
                ? viewportState.zoom
                : (isTopology ? 'fit' : 1);
            const minZoom = isTopology ? (topologyScope === 'full' ? 0.4 : 0.55) : 0.55;
            const maxZoom = isTopology ? (topologyScope === 'full' ? 1.2 : 1.3) : 1.5;
            function resolvedZoomValue() {
                return Math.max(minZoom, Math.min(maxZoom, Number(graph.dataset.zoomResolved || 1) || 1));
            }
            function computeFitZoom() {
                const viewportWidth = Math.max(320, Number(viewport.clientWidth || 0) - 12);
                const viewportHeight = Math.max(260, Number(viewport.clientHeight || 0) - 12);
                const fitCap = isTopology && topologyScope !== 'full' ? maxZoom : 1;
                return Math.max(
                    minZoom,
                    Math.min(fitCap, viewportWidth / Math.max(graphWidth, 1), viewportHeight / Math.max(graphHeight, 1)),
                );
            }
            function applyZoom(nextZoom, notify = true) {
                const zoomValue = nextZoom === 'fit'
                    ? computeFitZoom()
                    : Math.max(minZoom, Math.min(maxZoom, Number(nextZoom || 1) || 1));
                graph.dataset.zoomResolved = String(zoomValue);
                graph.style.transform = `scale(${zoomValue})`;
                graphFrame.style.width = `${graphWidth * zoomValue}px`;
                graphFrame.style.height = `${graphHeight * zoomValue}px`;
                controls.dataset.zoom = nextZoom === 'fit' ? 'fit' : String(zoomValue);
                if (notify && typeof onViewportChange === 'function') {
                    onViewportChange(nextZoom === 'fit' ? 'fit' : zoomValue);
                }
            }

            const fitBtn = document.createElement('button');
            fitBtn.type = 'button';
            fitBtn.className = 'btn btn-small';
            fitBtn.textContent = 'Fit';
            fitBtn.addEventListener('click', () => applyZoom('fit'));
            controls.appendChild(fitBtn);

            const zoomOut = document.createElement('button');
            zoomOut.type = 'button';
            zoomOut.className = 'btn btn-small';
            zoomOut.textContent = '−';
            zoomOut.addEventListener('click', () => applyZoom(resolvedZoomValue() - 0.12));
            controls.appendChild(zoomOut);

            const zoomReset = document.createElement('button');
            zoomReset.type = 'button';
            zoomReset.className = 'btn btn-small';
            zoomReset.textContent = '100%';
            zoomReset.addEventListener('click', () => applyZoom(1));
            controls.appendChild(zoomReset);

            const zoomIn = document.createElement('button');
            zoomIn.type = 'button';
            zoomIn.className = 'btn btn-small';
            zoomIn.textContent = '+';
            zoomIn.addEventListener('click', () => applyZoom(resolvedZoomValue() + 0.12));
            controls.appendChild(zoomIn);

            graphFrame.appendChild(graph);
            viewport.appendChild(graphFrame);
            shell.appendChild(controls);
            shell.appendChild(viewport);
            root.appendChild(shell);
            requestAnimationFrame(() => applyZoom(defaultZoom, false));
        }

        const extras = Array.isArray(accessorySections) ? accessorySections.filter(Boolean) : [];
        if (extras.length) {
            const accessories = document.createElement('div');
            accessories.className = 'kit-workflow-accessories';
            extras.forEach((section) => {
                const block = document.createElement('section');
                block.className = 'kit-workflow-accessory';
                const head = document.createElement('div');
                head.className = 'kit-workflow-accessory-head';
                const title = document.createElement('h3');
                title.className = 'kit-workflow-accessory-title';
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
                block.appendChild(head);

                const items = Array.isArray(section.items) ? section.items : [];
                if (!items.length) {
                    block.appendChild(UI.renderEmptyState(String(section.empty || 'Nothing here yet.')));
                } else {
                    const list = document.createElement('div');
                    list.className = 'kit-workflow-accessory-list';
                    items.forEach((item) => {
                        const btn = document.createElement('button');
                        btn.type = 'button';
                        btn.className = `kit-workflow-accessory-item${selection?.kind === item.kind && selection?.id === item.id ? ' is-selected' : ''}`;
                        btn.dataset.testid = `workflow-accessory-${String(item.kind || 'item')}-${String(item.id || '')}`;
                        btn.textContent = String(item.label || item.id || '');
                        if (typeof section.onSelect === 'function') {
                            btn.addEventListener('click', () => section.onSelect(item));
                        }
                        list.appendChild(btn);
                    });
                    block.appendChild(list);
                }
                accessories.appendChild(block);
            });
            root.appendChild(accessories);
        }

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
        suggestions = [],
        onSuggestionSelect = null,
        title = '',
        help = '',
        showForm = true,
        showSuggestions = true,
        emptyHint = '',
        resultTitle = '',
    } = {}) {
        const root = document.createElement('section');
        root.className = 'kit-selector-preview';

        const header = document.createElement('div');
        header.className = 'kit-selector-preview-header';
        const titleNode = document.createElement('strong');
        titleNode.textContent = String(title || dictValue('agents.selector.title', 'Selector resolution preview'));
        header.appendChild(titleNode);
        const helpText = String(help || dictValue('agents.selector.help', ''));
        if (helpText) {
            const helpNode = document.createElement('p');
            helpNode.className = 'quiet-note';
            helpNode.textContent = helpText;
            header.appendChild(helpNode);
        }
        root.appendChild(header);

        let input = null;
        if (showForm) {
            const form = document.createElement('div');
            form.className = 'kit-selector-preview-form';
            input = document.createElement('input');
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
        }

        const quickPicks = showSuggestions && Array.isArray(suggestions) ? suggestions.filter(Boolean) : [];
        if (quickPicks.length && input) {
            const picker = document.createElement('div');
            picker.className = 'kit-selector-preview-suggestions';
            const pickerLabel = document.createElement('div');
            pickerLabel.className = 'detail-label';
            pickerLabel.textContent = dictValue('agents.selector.quick_picks', 'Quick picks');
            picker.appendChild(pickerLabel);

            const chips = document.createElement('div');
            chips.className = 'chip-row';
            quickPicks.forEach((suggestion) => {
                const chip = document.createElement('button');
                chip.type = 'button';
                chip.className = 'quickstart-chip';
                chip.textContent = String(suggestion.label || suggestion.value || '');
                chip.addEventListener('click', () => {
                    const value = String(suggestion.value || '').trim();
                    if (!value) return;
                    input.value = value;
                    if (typeof onSuggestionSelect === 'function') {
                        onSuggestionSelect(suggestion);
                        return;
                    }
                    if (typeof onResolve === 'function') {
                        onResolve(value);
                    }
                });
                chips.appendChild(chip);
            });
            picker.appendChild(chips);
            root.appendChild(picker);
        }

        const list = document.createElement('div');
        list.className = 'kit-selector-preview-results';
        const rows = Array.isArray(candidates) ? candidates.filter(Boolean) : [];
        if (message && rows.length) {
            const note = document.createElement('div');
            note.className = 'kit-selector-preview-message quiet-note';
            note.textContent = String(message);
            root.appendChild(note);
        }
        if (rows.length === 0) {
            list.appendChild(UI.renderEmptyState(
                selector
                    ? String(message || emptyHint || dictValue('agents.selector.no_matches', 'No connected agents match this selector.'))
                    : String(emptyHint || dictValue('agents.selector.empty', 'No candidates yet — enter a selector and press Resolve.')),
            ));
        } else {
            const resultsLabel = document.createElement('div');
            resultsLabel.className = 'detail-label';
            resultsLabel.textContent = String(resultTitle || dictValue('agents.selector.result_title', 'Candidates'));
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
        sectionListCanvas,
        workflowCanvas,
        rehearsalPanel,
        runsList,
        runSummary,
        agentsList,
        agentSummary,
        selectorResolutionPreview,
    };
})();
