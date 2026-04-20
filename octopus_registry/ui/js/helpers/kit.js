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

        // Details — roles
        'protocol.participants.section': 'Roles',
        'protocol.participants.firstrun': 'Add a reusable role for this workflow.',
        'protocol.participants.add': '+ Add role',
        'protocol.participant.display_name.label': 'Name',
        'protocol.participant.display_name.help': 'Name the reusable role that can own one or more steps.',
        'protocol.participant.display_name.placeholder': 'e.g. Approver',
        'protocol.participant.participant_key.label': 'Key',
        'protocol.participant.participant_key.help': 'Internal reference for this role. It is usually generated from the name.',
        'protocol.participant.participant_key.placeholder': 'approver',
        'protocol.participant.instructions.label': 'Instructions',
        'protocol.participant.instructions.help': 'Guidance shared across every step this role owns.',
        'protocol.participant.instructions.placeholder': 'Instructions shared with this role…',
        'protocol.participant.selector_kind.label': 'Assignment',
        'protocol.participant.selector_kind.help': 'How this step should resolve someone at runtime.',
        'protocol.participant.selector_kind.placeholder': 'Choose how this step should resolve…',
        'protocol.participant.selector_strategy.label': 'Strategy',
        'protocol.participant.selector_value.label': 'Rule value',
        'protocol.participant.selector_value.help': 'For example: a skill slug, a runtime role tag, or an agent slug.',
        'protocol.participant.selector_value.placeholder': 'e.g. legal-review, approver, m1',
        'protocol.participant.selector_preview.label': 'Who matches right now',
        'protocol.participant.selector_preview.help': 'Preview uses the shared registry selector resolution path. Choose a matching agent to pin this step when needed.',
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
        'protocol.stage.participant_key.label': 'Owner role',
        'protocol.stage.participant_key.help': 'Which reusable role owns this step.',
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
        'protocol.details.overview.empty': 'Select a role, step, or artifact in the workspace — or edit the name and slug above.',
        'protocol.details.transition.empty': 'Select a transition to edit what happens next.',

        // Empty / first-run / onboarding
        'protocol.canvas.empty.title': 'Start the workflow',
        'protocol.canvas.empty.body': 'Add the first step in the workflow and create its owner role inline if needed.',
        'protocol.catalog.empty.title': 'No protocols yet',
        'protocol.catalog.empty.body': 'Create one from a template in the Gallery, or start from a blank draft.',
        'protocol.catalog.title': 'Workflow definitions',
        'protocol.catalog.subtitle': 'Draft, publish, and rehearse reusable protocols without leaving the registry.',
        'protocol.catalog.search': 'Search protocols',
        'protocol.catalog.gallery': 'Browse template gallery',
        'protocol.firstrun.participant': 'Add the first role.',
        'protocol.firstrun.stage': 'Add the first step for that role.',
        'protocol.firstrun.transition': 'Connect the step to the next step or an outcome.',
        'protocol.workflow.outcomes': 'Outcomes',
        'protocol.workflow.artifacts': 'Artifacts',
        'protocol.workflow.drag_hint': 'Select a step to edit it, or drag it to reorganize the workflow.',
        'protocol.workflow.lane_hint': 'Roles in this workflow',
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
        utilityActions = [],
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
            const utilityItems = Array.isArray(utilityActions) ? utilityActions.filter(Boolean) : [];
            if (utilityItems.length) {
                const utilityRow = document.createElement('div');
                utilityRow.className = 'kit-lifecycle-actions';
                utilityItems.forEach((item) => {
                    if (!item || typeof item.onClick !== 'function') return;
                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = ['btn', item.tone || 'btn-secondary'].filter(Boolean).join(' ');
                    btn.textContent = String(item.label || 'Open');
                    btn.addEventListener('click', () => {
                        overflow.open = false;
                        item.onClick(record);
                    });
                    utilityRow.appendChild(btn);
                });
                overflowBody.appendChild(utilityRow);
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
                if (field.commitOnInput && (kind === 'text' || kind === 'textarea')) {
                    control.addEventListener('input', commit);
                }
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
        scene = null,
        lanes = [],
        nodes = [],
        edges = [],
        selection = null,
        onSelect = null,
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
        root.className = `kit-workflow-canvas kit-workflow-canvas-${mode}`;
        root.dataset.key = `workflow-canvas:${mode}`;
        root.tabIndex = 0;

        if (firstRun && firstRun.active) {
            const card = document.createElement('div');
            card.className = 'kit-workflow-first-run';

            const title = document.createElement('h3');
            title.className = 'kit-workflow-first-run-title';
            title.textContent = String(firstRun.title || dictValue('protocol.canvas.empty.title', 'Design your workflow'));
            card.appendChild(title);

            const body = document.createElement('p');
            body.className = 'kit-workflow-first-run-body';
            body.textContent = String(firstRun.body || dictValue('protocol.canvas.empty.body', 'Add the first step in the workflow and create its owner role inline if needed.'));
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
        const toolbarHint = String(viewState?.hint || '');
        if (viewState?.title || viewState?.subtitle) {
            const viewBar = document.createElement('div');
            viewBar.className = 'kit-workflow-viewbar';
            const title = document.createElement('strong');
            title.className = 'kit-workflow-viewbar-title';
            title.textContent = String(viewState?.title || 'Workflow');
            viewBar.appendChild(title);
            if (viewState?.subtitle) {
                const subtitle = document.createElement('span');
                subtitle.className = 'kit-workflow-viewbar-subtitle';
                subtitle.textContent = String(viewState.subtitle || '');
                viewBar.appendChild(subtitle);
            }
            root.appendChild(viewBar);
        }
        if (!firstRun?.active || String(editorMode?.kind || '') === 'rehearse') {
            const toolbar = document.createElement('div');
            toolbar.className = 'kit-workflow-toolbar';
            if (toolbarHint) {
                const hint = document.createElement('div');
                hint.className = 'kit-workflow-toolbar-hint';
                hint.textContent = toolbarHint;
                toolbar.appendChild(hint);
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

        let graphScene = scene || {
            graph: {
                nodes: Array.isArray(nodes) ? nodes : [],
                edges: Array.isArray(edges) ? edges : [],
            },
            outline: [],
            keyboardOrder: [],
        };
        let currentSelection = selection || { kind: 'overview', id: '' };

        function _moveSelection(delta) {
            if (typeof onSelect !== 'function') return;
            const ordered = Array.isArray(graphScene.keyboardOrder) && graphScene.keyboardOrder.length
                ? graphScene.keyboardOrder
                : (Array.isArray(graphScene.graph?.nodes) ? graphScene.graph.nodes.map((item) => ({
                    kind: item.kind,
                    id: item.id,
                })) : []);
            if (!ordered.length) return;
            const currentId = String(currentSelection?.id || '');
            const idx = Math.max(0, ordered.findIndex((item) => String(item.id || '') === currentId));
            const next = ordered[Math.max(0, Math.min(ordered.length - 1, idx + delta))];
            if (next) onSelect({ kind: next.kind, id: next.id });
        }

        let cy = null;
        let disposed = false;
        let syncingFit = false;
        let mountedSceneKey = '';
        let currentZoom = viewportState?.zoom === 'fit'
            ? 'fit'
            : Math.max(0.35, Math.min(2.25, Number(viewportState?.zoom || 1) || 1));

        root.addEventListener('keydown', (event) => {
            if ((event.metaKey || event.ctrlKey) && String(event.key || '').toLowerCase() === 'z' && typeof onMutate === 'function') {
                event.preventDefault();
                onMutate({ type: event.shiftKey ? 'redo' : 'undo' });
                return;
            }
            if (event.target && !root.contains(event.target)) return;
            if ((event.ctrlKey || event.metaKey || event.shiftKey) && cy) {
                const delta = event.shiftKey ? 140 : 64;
                if (event.key === 'ArrowRight') {
                    event.preventDefault();
                    currentZoom = Number(cy.zoom() || 1);
                    cy.panBy({ x: -delta, y: 0 });
                    return;
                }
                if (event.key === 'ArrowLeft') {
                    event.preventDefault();
                    currentZoom = Number(cy.zoom() || 1);
                    cy.panBy({ x: delta, y: 0 });
                    return;
                }
                if (event.key === 'ArrowDown') {
                    event.preventDefault();
                    currentZoom = Number(cy.zoom() || 1);
                    cy.panBy({ x: 0, y: -delta });
                    return;
                }
                if (event.key === 'ArrowUp') {
                    event.preventDefault();
                    currentZoom = Number(cy.zoom() || 1);
                    cy.panBy({ x: 0, y: delta });
                    return;
                }
            }
            if (event.key === '+' || event.key === '=') {
                event.preventDefault();
                if (cy) cy.zoom({ level: Math.min(2.25, cy.zoom() + 0.14), renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
                return;
            }
            if (event.key === '-') {
                event.preventDefault();
                if (cy) cy.zoom({ level: Math.max(0.35, cy.zoom() - 0.14), renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
                return;
            }
            if (String(event.key || '').toLowerCase() === '0') {
                event.preventDefault();
                currentZoom = 'fit';
                if (cy) _fitCamera(cy, true);
                return;
            }
            if (event.key === 'Escape' && typeof onSelect === 'function') {
                event.preventDefault();
                onSelect({ kind: 'overview', id: '' });
                return;
            }
            if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
                event.preventDefault();
                _moveSelection(1);
            } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
                event.preventDefault();
                _moveSelection(-1);
            }
        });

        function _fitCamera(instance, force = false) {
            if (!instance) return;
            const targetIds = Array.isArray(graphScene.focusIds) ? graphScene.focusIds.filter(Boolean) : [];
            const fitElements = targetIds.length
                ? instance.elements().filter((item) => targetIds.includes(String(item.id() || '')))
                : instance.elements();
            if (!fitElements.length) return;
            const animate = !window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
            if (currentZoom === 'fit' || force) {
                syncingFit = true;
                instance.animate({
                    fit: {
                        eles: fitElements,
                        padding: Number(graphScene.fitPadding || 72),
                    },
                    duration: animate ? 220 : 0,
                    complete: () => {
                        syncingFit = false;
                        if (typeof onViewportChange === 'function') {
                            onViewportChange('fit');
                        }
                    },
                });
            }
        }

        const shell = document.createElement('div');
        shell.className = 'kit-workflow-shell kit-workflow-shell-scene';

        const outline = document.createElement('aside');
        outline.className = 'kit-workflow-outline';
        const outlineTitle = document.createElement('div');
        outlineTitle.className = 'kit-workflow-outline-title';
        outlineTitle.textContent = String(graphScene.outlineTitle || 'Workflow outline');
        outline.appendChild(outlineTitle);
        const outlineList = document.createElement('div');
        outlineList.className = 'kit-workflow-outline-list';
        (Array.isArray(graphScene.outline) ? graphScene.outline : []).forEach((section) => {
            const group = document.createElement('div');
            group.className = 'kit-workflow-outline-group';
            group.dataset.key = `workflow-outline-group:${String(section.id || '')}`;
            const head = document.createElement('button');
            head.type = 'button';
            head.className = `kit-workflow-outline-item${selection?.kind === section.kind && selection?.id === section.id ? ' is-selected' : ''}`;
            head.dataset.key = `workflow-outline-item:${String(section.id || '')}`;
            head.dataset.testid = `workflow-outline-${String(section.id || '')}`;
            head.textContent = String(section.label || '');
            if (typeof onSelect === 'function') {
                head.addEventListener('click', () => onSelect({ kind: section.kind, id: section.id }));
            }
            group.appendChild(head);
            if (section.meta) {
                const meta = document.createElement('div');
                meta.className = 'kit-workflow-outline-meta';
                meta.dataset.key = `workflow-outline-item-meta:${String(section.id || '')}`;
                meta.textContent = String(section.meta || '');
                group.appendChild(meta);
            }
            const items = Array.isArray(section.items) ? section.items : [];
            if (items.length && section.expanded) {
                const list = document.createElement('div');
                list.className = 'kit-workflow-outline-children';
                list.dataset.key = `workflow-outline-children:${String(section.id || '')}`;
                items.forEach((item) => {
                    const child = document.createElement('button');
                    child.type = 'button';
                    child.className = `kit-workflow-outline-child${selection?.kind === item.kind && selection?.id === item.id ? ' is-selected' : ''}`;
                    child.dataset.key = `workflow-outline-child:${String(item.id || '')}`;
                    child.dataset.testid = `workflow-outline-${String(item.id || '')}`;
                    child.textContent = String(item.label || '');
                    if (typeof onSelect === 'function') {
                        child.addEventListener('click', () => onSelect({ kind: item.kind, id: item.id }));
                    }
                    list.appendChild(child);
                    if (item.meta) {
                        const meta = document.createElement('div');
                        meta.className = 'kit-workflow-outline-child-meta';
                        meta.dataset.key = `workflow-outline-child-meta:${String(item.id || '')}`;
                        meta.textContent = String(item.meta || '');
                        list.appendChild(meta);
                    }
                });
                group.appendChild(list);
            }
            outlineList.appendChild(group);
        });
        if (!outlineList.childElementCount) {
            outlineList.appendChild(UI.renderEmptyState(String(graphScene.emptyHint || 'Add the first step to start shaping the workflow.')));
        }
        outline.appendChild(outlineList);

        const canvasColumn = document.createElement('div');
        canvasColumn.className = 'kit-workflow-canvas-column';
        const controls = document.createElement('div');
        controls.className = 'kit-workflow-controls';

        const fitBtn = document.createElement('button');
        fitBtn.type = 'button';
        fitBtn.className = 'btn btn-small';
        fitBtn.textContent = 'Fit';
        fitBtn.addEventListener('click', () => {
            currentZoom = 'fit';
            if (cy) _fitCamera(cy, true);
        });
        controls.appendChild(fitBtn);

        const zoomOut = document.createElement('button');
        zoomOut.type = 'button';
        zoomOut.className = 'btn btn-small';
        zoomOut.textContent = '−';
        zoomOut.addEventListener('click', () => {
            if (!cy) return;
            currentZoom = Math.max(0.35, cy.zoom() - 0.14);
            cy.zoom({ level: currentZoom, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
        });
        controls.appendChild(zoomOut);

        const zoomReset = document.createElement('button');
        zoomReset.type = 'button';
        zoomReset.className = 'btn btn-small';
        zoomReset.textContent = '100%';
        zoomReset.addEventListener('click', () => {
            if (!cy) return;
            currentZoom = 1;
            cy.zoom({ level: 1, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
        });
        controls.appendChild(zoomReset);

        const zoomIn = document.createElement('button');
        zoomIn.type = 'button';
        zoomIn.className = 'btn btn-small';
        zoomIn.textContent = '+';
        zoomIn.addEventListener('click', () => {
            if (!cy) return;
            currentZoom = Math.min(2.25, cy.zoom() + 0.14);
            cy.zoom({ level: currentZoom, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
        });
        controls.appendChild(zoomIn);

        const viewport = document.createElement('div');
        viewport.className = 'kit-workflow-viewport kit-workflow-viewport-cy';
        const graphHost = document.createElement('div');
        graphHost.className = 'kit-workflow-cy-host';
        graphHost.dataset.signature = `workflow-graph:${String(graphScene.key || '')}`;
        viewport.appendChild(graphHost);

        canvasColumn.appendChild(controls);
        canvasColumn.appendChild(viewport);
        shell.appendChild(outline);
        shell.appendChild(canvasColumn);
        root.appendChild(shell);

        function _nodeLabel(node) {
            return [node.label, node.meta, node.secondary].map((item) => String(item || '').trim()).filter(Boolean).join('\n');
        }

        function _selectionMatches(kind, id) {
            return String(currentSelection?.kind || '') === String(kind || '')
                && String(currentSelection?.id || '') === String(id || '');
        }

        function _cyElements() {
            return [
                ...(Array.isArray(graphScene.graph?.nodes) ? graphScene.graph.nodes : []).map((node) => ({
                    data: {
                        id: String(node.id || ''),
                        label: _nodeLabel(node),
                        kind: String(node.kind || 'section'),
                        state: String(node.state || ''),
                    },
                    classes: [
                        `kind-${String(node.kind || 'section')}`,
                        node.selected || _selectionMatches(String(node.kind || 'section'), String(node.id || '')) ? 'is-selected' : '',
                        node.context ? 'is-context' : '',
                        node.emphasis === 'muted' ? 'is-muted' : '',
                    ].filter(Boolean).join(' '),
                })),
                ...(Array.isArray(graphScene.graph?.edges) ? graphScene.graph.edges : []).map((edge) => ({
                    data: {
                        id: String(edge.id || ''),
                        source: String(edge.from || ''),
                        target: String(edge.to || ''),
                        label: String(edge.label || ''),
                    },
                    classes: [
                        _selectionMatches('transition', String(edge.id || '')) ? 'is-selected' : '',
                        edge.primary ? 'is-primary' : '',
                        edge.muted ? 'is-muted' : '',
                    ].filter(Boolean).join(' '),
                })),
            ];
        }

        function _destroyCy() {
            if (cy) {
                try {
                    cy.destroy();
                } catch (_err) {
                    // best effort
                }
                cy = null;
            }
        }

        function _syncCySelection() {
            if (!cy) return;
            cy.batch(() => {
                cy.nodes().forEach((node) => {
                    const selected = _selectionMatches(String(node.data('kind') || 'section'), String(node.id() || ''));
                    node.toggleClass('is-selected', selected);
                });
                cy.edges().forEach((edge) => {
                    edge.toggleClass('is-selected', _selectionMatches('transition', String(edge.id() || '')));
                });
            });
        }

        async function _layoutAndMount() {
            if (disposed || !root.isConnected) return;
            const graphHostEl = root.querySelector('.kit-workflow-cy-host');
            if (!(graphHostEl instanceof Element)) return;
            const nextSceneKey = String(graphScene.key || '');
            if (cy && mountedSceneKey === nextSceneKey) {
                _syncCySelection();
                return;
            }
            mountedSceneKey = nextSceneKey;
            _destroyCy();
            if (typeof window.cytoscape !== 'function' || typeof window.ELK !== 'function') {
                graphHostEl.replaceChildren(UI.createErrorCard('Workflow canvas dependencies are missing.'));
                return;
            }
            const elements = _cyElements();
            if (!elements.length) {
                graphHostEl.replaceChildren(UI.renderEmptyState(String(graphScene.emptyHint || 'Add the first step to start shaping the workflow.')));
                return;
            }

            cy = window.cytoscape({
                container: graphHostEl,
                elements,
                style: [
                    {
                        selector: 'node',
                        style: {
                            'shape': 'round-rectangle',
                            'background-color': '#f8fafc',
                            'border-width': 1.5,
                            'border-color': '#d6dbe4',
                            'label': 'data(label)',
                            'font-family': 'ui-sans-serif, system-ui, sans-serif',
                            'font-size': 11,
                            'font-weight': 700,
                            'text-wrap': 'wrap',
                            'text-max-width': 172,
                            'text-valign': 'center',
                            'text-halign': 'center',
                            'padding': 14,
                            'line-height': 1.25,
                            'color': '#122033',
                            'width': 'label',
                            'height': 'label',
                            'min-width': 132,
                            'min-height': 54,
                            'overlay-opacity': 0,
                        },
                    },
                    {
                        selector: 'node.kind-segment',
                        style: {
                            'background-color': '#fffaf5',
                            'border-color': '#d9b28d',
                            'min-width': 144,
                            'min-height': 48,
                            'font-size': 12,
                            'text-max-width': 132,
                            'padding': 10,
                        },
                    },
                    {
                        selector: 'node.kind-stage',
                        style: {
                            'background-color': '#ffffff',
                            'border-color': '#cdd8e8',
                            'min-width': 156,
                            'min-height': 62,
                            'text-max-width': 148,
                        },
                    },
                    {
                        selector: 'node.kind-outcome',
                        style: {
                            'shape': 'round-rectangle',
                            'background-color': '#eef8f1',
                            'border-color': '#96c5a4',
                            'min-width': 128,
                            'min-height': 46,
                            'font-size': 10,
                            'text-max-width': 120,
                        },
                    },
                    {
                        selector: 'node.is-context',
                        style: {
                            'background-color': '#f3f7fb',
                            'border-color': '#c5d4e4',
                            'min-width': 132,
                            'min-height': 44,
                            'font-size': 10,
                            'text-max-width': 120,
                        },
                    },
                    {
                        selector: 'node.is-muted',
                        style: {
                            'opacity': 0.74,
                        },
                    },
                    {
                        selector: 'node.is-selected',
                        style: {
                            'border-width': 2.5,
                            'border-color': '#8f4f2a',
                            'background-color': '#fff7f0',
                        },
                    },
                    {
                        selector: 'edge',
                        style: {
                            'width': 2.2,
                            'curve-style': 'bezier',
                            'line-color': '#8ea0b8',
                            'target-arrow-color': '#8ea0b8',
                            'target-arrow-shape': 'triangle',
                            'arrow-scale': 0.9,
                            'label': 'data(label)',
                            'font-size': 10,
                            'font-weight': 700,
                            'text-background-color': '#ffffff',
                            'text-background-opacity': 0.9,
                            'text-background-padding': 3,
                            'text-rotation': 'autorotate',
                            'text-margin-y': -10,
                            'color': '#334155',
                            'overlay-opacity': 0,
                        },
                    },
                    {
                        selector: 'edge.is-muted',
                        style: {
                            'line-color': '#c4cedb',
                            'target-arrow-color': '#c4cedb',
                            'opacity': 0.76,
                        },
                    },
                    {
                        selector: 'edge.is-primary',
                        style: {
                            'line-color': '#8f4f2a',
                            'target-arrow-color': '#8f4f2a',
                        },
                    },
                    {
                        selector: 'edge.is-selected',
                        style: {
                            'line-color': '#8f4f2a',
                            'target-arrow-color': '#8f4f2a',
                            'width': 3,
                        },
                    },
                ],
                wheelSensitivity: 0.18,
                userPanningEnabled: true,
                userZoomingEnabled: true,
                boxSelectionEnabled: false,
                autoungrabify: true,
                selectionType: 'single',
            });

            const elk = new window.ELK();
            const elkGraph = {
                id: 'root',
                layoutOptions: {
                    'elk.algorithm': 'layered',
                    'elk.direction': String(graphScene.direction || 'RIGHT'),
                    'elk.spacing.nodeNode': String(graphScene.nodeSpacing || 34),
                    'elk.layered.spacing.nodeNodeBetweenLayers': String(graphScene.layerSpacing || 78),
                    'elk.edgeRouting': 'POLYLINE',
                },
                children: (Array.isArray(graphScene.graph?.nodes) ? graphScene.graph.nodes : []).map((node) => ({
                    id: String(node.id || ''),
                    width: Number(node.width || (node.kind === 'segment' ? 260 : node.kind === 'stage' ? 220 : node.kind === 'outcome' ? 160 : 180)),
                    height: Number(node.height || (node.kind === 'segment' ? 126 : node.kind === 'stage' ? 98 : node.kind === 'outcome' ? 60 : 72)),
                })),
                edges: (Array.isArray(graphScene.graph?.edges) ? graphScene.graph.edges : []).map((edge) => ({
                    id: String(edge.id || ''),
                    sources: [String(edge.from || '')],
                    targets: [String(edge.to || '')],
                })),
            };

            const laidOut = await elk.layout(elkGraph);
            if (disposed || !cy) return;
            const positions = new Map((laidOut.children || []).map((node) => [
                String(node.id || ''),
                {
                    x: Number(node.x || 0) + (Number(node.width || 0) / 2),
                    y: Number(node.y || 0) + (Number(node.height || 0) / 2),
                },
            ]));
            cy.nodes().positions((node) => positions.get(String(node.id() || '')) || { x: 0, y: 0 });
            _syncCySelection();

            cy.on('tap', 'node', (event) => {
                if (typeof onSelect === 'function') {
                    onSelect({
                        kind: String(event.target.data('kind') || 'segment'),
                        id: String(event.target.id() || ''),
                    });
                }
            });
            cy.on('tap', 'edge', (event) => {
                if (typeof onSelect === 'function') {
                    onSelect({ kind: 'transition', id: String(event.target.id() || '') });
                }
            });
            cy.on('zoom pan', (event) => {
                if (syncingFit) return;
                if (currentZoom === 'fit' && event?.originalEvent) {
                    currentZoom = Number(cy.zoom() || 1);
                }
                if (typeof onViewportChange === 'function') {
                    onViewportChange(currentZoom === 'fit' ? 'fit' : Number(cy.zoom() || 1));
                }
            });

            if (currentZoom !== 'fit') {
                cy.zoom(Number(currentZoom || 1));
                cy.center();
            } else {
                _fitCamera(cy, true);
            }
        }

        root.__workflowCanvasSync = ({
            scene: nextScene = graphScene,
            selection: nextSelection = currentSelection,
            viewportState: nextViewportState = {},
        } = {}) => {
            graphScene = nextScene || graphScene;
            currentSelection = nextSelection || currentSelection;
            currentZoom = nextViewportState?.zoom === 'fit'
                ? 'fit'
                : Math.max(0.35, Math.min(2.25, Number(nextViewportState?.zoom || currentZoom || 1) || 1));
            if (!root.isConnected || disposed) return;
            requestAnimationFrame(() => {
                if (disposed) return;
                void _layoutAndMount();
            });
        };

        root.__workflowCanvasCleanup = () => {
            disposed = true;
            _destroyCy();
        };

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
                const row = document.createElement(typeof onSuggestionSelect === 'function' ? 'button' : 'div');
                row.className = 'kit-selector-preview-row';
                if (row.tagName === 'BUTTON') {
                    row.type = 'button';
                    row.addEventListener('click', () => onSuggestionSelect(candidate));
                }
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
