# PLAN: UI Redesign — Mobile-First, Polished, Light + Dark

## Context

The registry SPA works functionally (conversations, delegation, usage, skills, guidance) but has critical UX bugs and a flat, unpolished visual design. Reference: liftandshift.io — warm monochromatic palette, frosted glass cards, smooth transitions, mobile-first accordion patterns.

This plan fixes the broken chat experience, adds visual polish, introduces a light theme, and cleans up the component architecture — all in vanilla HTML/CSS/JS (no framework).

The plan is **UI target state constrained by the current registry backend contract**. It should not invent new client-side data shapes or assume legacy field names. Where the desired UX needs backend support that does not exist yet, that dependency is called out explicitly instead of being smuggled in as a UI detail.

## Problems

### Critical UX bugs
- **P1: Chat doesn't scroll.** `.chat-timeline` has no `overflow-y: auto` or fixed height. `scrollTop` logic is dead code. Messages flow past the viewport.
- **P2: Compose box isn't pinned.** It scrolls away with content instead of staying fixed at the bottom.
- **P3: Broken CSS variables.** Guidance editor uses `--border-color`, `--color-success`, `--text-primary` — none of which exist. Actual tokens: `--border`, `--success`, `--text`.

### Design quality
- **P4: No visual depth.** Flat cards, no glass effect, no hover lift, no transitions. Everything looks the same.
- **P5: No light theme.** Dark-only. No `prefers-color-scheme` support.
- **P6: Magic number spacing.** 37+ different pixel values. No scale.
- **P7: Low information density.** Capabilities, skills, and guidance pages are mostly empty space.
- **P8: No route transitions.** Content snaps in. No fade, no slide.

### Code quality
- **P9: Duplicate rendering.** Card+row+info+badge pattern copy-pasted 5+ times.
- **P10: Inline styles.** Guidance editor, new conversation dialog, skill catalog all use `element.style.*` instead of CSS classes.
- **P11: Zero accessibility.** No ARIA attributes, no focus trapping in modals, no keyboard navigation beyond `/` and `Escape`.

## Decisions

1. **Mobile-first CSS rewrite.** Base styles target mobile (single column, full-width cards, touch targets). Desktop layout added via `min-width` media queries. Not the current approach which is desktop-first with mobile overrides.

2. **Design token system.** 4px spacing grid (`--sp-1` through `--sp-10`), 5-step type scale, 3 elevation levels (flat, raised, floating). All current magic numbers replaced.

3. **Light + dark themes via `prefers-color-scheme` + manual toggle.** CSS custom properties swap between two palettes. Default follows system preference. Toggle in sidebar footer persists to `localStorage`.

4. **Frosted glass on cards and sidebar.** `backdrop-filter: blur(12px)` with semi-transparent backgrounds. Graceful fallback (opaque background) for browsers without support.

5. **Conversation detail as a full-height flex layout.** Metadata pinned at top, timeline scrolls in the middle (`flex: 1; overflow-y: auto`), compose box pinned at bottom. This is the single most important UX fix.

6. **Shared render helpers.** `renderCard()`, `renderFilterBar()`, `renderStatCard()` — extracted from the 5 duplicated patterns. Not a component framework, just functions that return DOM elements.

7. **Smooth transitions.** Route changes fade in (opacity 0→1, 0.15s). Card hover lifts (translateY -2px, 0.2s). Modal backdrop fades (0.2s). Event cards expand with height transition.

8. **Contract-first UI work.** The redesign consumes the current resource API and SDK event contract as-is:
   - Agent list/detail come from `/v1/agents`, `/v1/agents/{id}/status`, `/v1/agents/{id}/conversations`
   - Conversations come from `/v1/conversations`, `/v1/conversations/{id}`, `/v1/conversations/{id}/events`
   - Operator writes go through `/v1/conversations/{id}/messages` and `/v1/conversations/{id}/actions`
   - Event rendering is driven by the stored event envelope and `registry_sdk/events.py`

## Phase 0: Backend contract freeze

Before the visual rewrite, freeze the backend contract the new SPA is allowed to depend on.

### 0.1 Agent resources

`GET /v1/agents` returns a paginated `agents` array plus `next_cursor` and `has_more`.

Each agent item currently includes:
- `agent_id`
- `display_name`
- `slug`
- `role`
- `registry_scope`
- `capabilities`
- `tags`
- `description`
- `provider`
- `mode`
- `connectivity_state`
- `current_capacity`
- `max_capacity`
- `channel_capabilities`
- `version`
- `last_heartbeat_at`
- `updated_at`
- `runtime_health_summary`
- `runtime_health_generated_at`

`GET /v1/agents/{id}/status` returns the same base agent fields plus:
- `workers`
- `active_conversations`
- `recent_errors`

The redesign must not assume removed config concepts such as `allowed_user_ids`, `admin_user_ids`, or other operator-only config internals are present in these payloads.

### 0.2 Conversation resources

`GET /v1/conversations` returns paginated conversation cards:
- `conversation_id`
- `target_agent_id`
- `target_display_name`
- `title`
- `origin_channel`
- `status`
- `created_at`
- `updated_at`

`GET /v1/conversations/{id}` returns the full conversation detail payload. The SPA should treat `conversation_id` as the canonical conversation identifier and should not rely on legacy `chat_id`-style concepts.

`POST /v1/conversations` requires:
- `target_agent_id`
- `origin_channel`
- `external_conversation_ref`
- optional `title`

For operator-created UI conversations, the SPA should continue to create registry-native threads with `origin_channel="registry"` and a non-empty minted `external_conversation_ref`.

### 0.3 Event envelope

`GET /v1/conversations/{id}/events` and live WebSocket event payloads share the same stored event envelope:

```json
{
  "seq": 12,
  "event_id": "evt-123",
  "conversation_id": "conv-123",
  "agent_id": "agent-123",
  "kind": "message.user",
  "actor": "Alice",
  "content": "Hello",
  "metadata": {},
  "created_at": "2026-03-23T00:00:00+00:00"
}
```

The redesign should render from top-level `actor`, `content`, `metadata`, and `created_at`. It should not expect old names such as `request_user_id`.

### 0.4 Event kinds the UI should handle cleanly

The plan should assume these current SDK-backed event kinds exist:
- `message.user`
- `message.bot`
- `provider.request`
- `provider.response`
- `tool.execution`
- `file.change`
- `approval.requested` — **note: defined in SDK schema but no publisher currently emits this kind.** The existing SPA has dead Approve/Reject buttons for this kind in `conversation-detail.js`. The redesign should remove them until a publisher exists.
- `approval.decided`
- `delegation.proposed`
- `delegation.submitted`
- `delegation.completed`
- `task.status`
- `error`

The plan should not assume every kind has a custom card on day one. Unknown or newly added kinds must fall back to a generic expandable event card that shows `content` plus pretty-printed `metadata`.

**Stale SPA code to clean up during redesign:**
- Remove Approve/Reject buttons for `approval.requested` events (no publisher exists)
- Replace raw JSON metadata dumps with kind-specific renderers per the Phase 2.5 matrix

### 0.5 Event metadata contract

Known metadata shapes the redesigned UI may specialize:

- `provider.response`
  - `prompt_tokens`
  - `completion_tokens`
  - `cost_usd`
  - `provider`
  - `tool_calls`

- `delegation.proposed` / `delegation.submitted` / `delegation.completed`
  - `tasks[]` (required, non-empty)
  - each task item has required fields: `title`, `target`, `status`
  - validated by `DelegationTaskSummary` in `registry_sdk/events.py`

- `approval.decided`
  - `action`
  - `decided_by`
  - `decision`

- `task.status`
  - `status`
  - optional `progress`
  - optional `title`

- `error`
  - `error_type`
  - `message`

`message.user` and `message.bot` may have empty metadata and should render from top-level `actor` and `content`.

### 0.6 Operator mutation contract

The SPA is not an event publisher. Operator actions stay on the existing mutation endpoints:
- `POST /v1/conversations/{id}/messages` with `{text}`
- `POST /v1/conversations/{id}/actions` with `{action, payload?}`

The redesigned conversation view should treat event cards as history and status, not as the primary mutation surface.

### 0.7 History pagination constraint

The current event API is forward-cursor only:
- `GET /v1/conversations/{id}/events?cursor=<seq>&limit=<n>`
- returns events with `seq > cursor` in ascending order

That contract is good for live append and simple pagination, but it does **not** support a true chat-style "open at latest, scroll upward for older history" experience by itself.

Target-state chat UX therefore has one explicit dependency:
- either add reverse pagination support (`before_seq`, descending window, or equivalent) to `/events`
- or keep the history UX scoped to the current forward-only contract and do not promise top-sentinel older-history loading

## Phase 1: Design tokens + theme system

### 1.1 Spacing scale

Replace all magic numbers with a 4px base grid:

```css
:root {
    --sp-1: 4px;    /* tight: badge padding, inline gaps */
    --sp-2: 8px;    /* compact: button gaps, card internal */
    --sp-3: 12px;   /* standard: card padding, list gaps */
    --sp-4: 16px;   /* comfortable: section gaps, card margins */
    --sp-5: 20px;   /* sidebar padding, page padding mobile */
    --sp-6: 24px;   /* page padding desktop, section separators */
    --sp-7: 32px;   /* large: summary card gaps, page headers */
    --sp-8: 48px;   /* empty state padding */
}
```

### 1.2 Type scale

```css
:root {
    --text-xs: 10px;   /* timestamps, event kind labels */
    --text-sm: 12px;   /* subtitles, table headers, badges */
    --text-base: 13px; /* body text, buttons, table cells */
    --text-md: 14px;   /* card titles, nav links */
    --text-lg: 18px;   /* sidebar title */
    --text-xl: 20px;   /* page headings */
    --text-2xl: 24px;  /* stat values */
}
```

### 1.3 Elevation

```css
:root {
    --elevation-0: none;
    --elevation-1: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.08);
    --elevation-2: 0 4px 12px rgba(0,0,0,0.15), 0 2px 4px rgba(0,0,0,0.1);
}
```

### 1.4 Dark theme (default, refined)

```css
:root, [data-theme="dark"] {
    --bg: #0d1117;
    --bg-secondary: rgba(22, 27, 34, 0.8);    /* semi-transparent for glass */
    --bg-secondary-solid: #161b22;              /* opaque fallback */
    --bg-tertiary: #21262d;
    --border: #30363d;
    --text: #e6edf3;
    --text-secondary: #8b949e;
    --text-muted: #6e7681;
    --accent: #58a6ff;
    --accent-hover: #79c0ff;
    --success: #3fb950;
    --warning: #d29922;
    --danger: #f85149;
    --glass-bg: rgba(22, 27, 34, 0.75);
    --glass-blur: blur(12px);
    --glass-border: rgba(48, 54, 61, 0.6);
}
```

### 1.5 Light theme

```css
[data-theme="light"] {
    --bg: #f6f8fa;
    --bg-secondary: rgba(255, 255, 255, 0.8);
    --bg-secondary-solid: #ffffff;
    --bg-tertiary: #f0f2f5;
    --border: #d0d7de;
    --text: #1f2328;
    --text-secondary: #656d76;
    --text-muted: #8b949e;
    --accent: #0969da;
    --accent-hover: #0550ae;
    --success: #1a7f37;
    --warning: #9a6700;
    --danger: #cf222e;
    --glass-bg: rgba(255, 255, 255, 0.7);
    --glass-blur: blur(12px);
    --glass-border: rgba(208, 215, 222, 0.6);
}
```

### 1.6 System preference + toggle

```css
@media (prefers-color-scheme: light) {
    :root:not([data-theme="dark"]) {
        /* light theme vars */
    }
}
```

JS toggle in sidebar footer: reads/writes `localStorage.getItem('theme')`, sets `document.documentElement.dataset.theme`.

### 1.7 Glass utility class

```css
.glass {
    background: var(--glass-bg);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border-color: var(--glass-border);
}

/* Fallback for browsers without backdrop-filter */
@supports not (backdrop-filter: blur(1px)) {
    .glass {
        background: var(--bg-secondary-solid);
    }
}
```

**Exit gate**: All hardcoded pixel values replaced with `--sp-*` tokens. Light theme renders correctly. Theme toggle works.

## Phase 2: Chat experience (P1, P2 — critical fix)

### 2.1 Full-height conversation layout

The conversation detail must be restructured as its own flex container — the CSS only works if the HTML wraps the conversation view in a dedicated element that owns the viewport height, separate from the page-level layout.

**Required DOM structure:**
```html
<div class="page-layout">          <!-- page header + sidebar + main -->
  <main id="content">
    <div class="conversation-view">  <!-- NEW: owns height, not inherited -->
      <div class="conversation-meta">...</div>
      <div class="chat-timeline">...</div>   <!-- scrollable middle -->
      <div class="compose-box">...</div>     <!-- pinned bottom -->
    </div>
  </main>
</div>
```

The `.conversation-view` wrapper is the real prerequisite — without it, the timeline cannot be the independent scroller while metadata and compose stay pinned.

```css
/* Conversation view is its own flex container with explicit height */
.conversation-view {
    display: flex;
    flex-direction: column;
    height: calc(100vh - 60px); /* below page header */
    min-height: 0; /* crucial for flex overflow */
}

.conversation-meta {
    flex-shrink: 0;
    /* metadata card + action bar */
}

.chat-timeline {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
    padding: var(--sp-3);
    /* Scroll to bottom on new messages */
    scroll-behavior: smooth;
}

.compose-box {
    flex-shrink: 0;
    border-top: 1px solid var(--border);
    padding: var(--sp-3);
    background: var(--bg);
}
```

### 2.2 Auto-scroll behavior

The near-bottom check must be captured **before** appending the new event to the DOM, not after. Checking after append will always see the user as "not near bottom" if the new content pushed the scroll position up.

```javascript
// BEFORE appending new message — capture scroll position first:
const wasNearBottom = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 100;

// Append the new message element
timeline.appendChild(newEventEl);

// AFTER append — scroll only if user was already near bottom:
if (wasNearBottom) {
    timeline.scrollTop = timeline.scrollHeight;
}
```

This prevents the chat from jumping when the user has scrolled up to read history.

### 2.3 Mobile chat

```css
@media (max-width: 640px) {
    .conversation-view {
        height: calc(100vh - 48px); /* smaller header */
    }
    .chat-bubble {
        max-width: 90%;
    }
    .compose-box {
        padding: var(--sp-2);
    }
    .compose-box textarea {
        min-height: 44px; /* touch target */
    }
}
```

### 2.4 History pagination

The visual redesign should not promise a top-of-timeline sentinel until the backend can actually supply older history windows. The current `/v1/conversations/{id}/events` contract is forward-cursor only, so true "open at latest and scroll upward for history" needs explicit backend support.

Target-state rule:
- If reverse pagination lands, use an IntersectionObserver sentinel at the top of the timeline.
- If reverse pagination does not land, keep an explicit history affordance and scope the redesign to layout, compose pinning, and correct live append behavior.

When reverse pagination exists, two behaviors are still required to prevent UX bugs:

1. **Scroll-anchor preservation**: Before prepending older events, record the current first visible element and its offset. After prepend, restore scroll position so the viewport doesn't jump. Use `scrollTop += (newScrollHeight - oldScrollHeight)`.

2. **Single-flight guard**: While a fetch is in-flight, disable the observer (or set a `loading` flag) to prevent repeated/infinite fetches when the sentinel stays visible during the network round trip.

```javascript
const sentinel = document.createElement('div');
sentinel.className = 'scroll-sentinel';
timeline.prepend(sentinel);

let loading = false;
const observer = new IntersectionObserver(async ([entry]) => {
    if (!entry.isIntersecting || loading) return;
    loading = true;
    const firstChild = timeline.children[1]; // first real event
    const oldTop = firstChild?.offsetTop ?? 0;
    await loadOlderEvents();
    const newTop = firstChild?.offsetTop ?? 0;
    timeline.scrollTop += (newTop - oldTop);
    loading = false;
}, { root: timeline, threshold: 0.1 });

observer.observe(sentinel);
```

### 2.5 Event rendering matrix

The redesigned conversation detail should be explicitly keyed to the current event contract:

- `message.user`, `message.bot`
  - render as chat bubbles
  - use top-level `actor`, `content`, `created_at`

- `provider.response`
  - specialized compact card
  - show provider name, prompt tokens, completion tokens, cost
  - render `tool_calls` only when non-empty

- `delegation.proposed`, `delegation.submitted`, `delegation.completed`
  - specialized delegation cards
  - render `metadata.tasks[]`
  - each task row shows `title`, `target`, `status`

- `task.status`
  - compact status card
  - show `metadata.status`
  - show progress/title only when present

- `approval.requested`
  - **no publisher currently emits this kind** — render as generic card if it appears
  - do NOT render inline Approve/Reject buttons (the existing SPA buttons are dead code)

- `approval.decided`
  - compact action card
  - show action, decision, and decided_by

- `error`
  - error card
  - show `metadata.error_type` and `metadata.message`

- all other kinds
  - generic expandable event card
  - show rendered content plus pretty-printed metadata

Do not hide unsupported kinds. The fallback card is part of the design, not a temporary dev-only behavior.

### 2.6 Conversation actions stay on resource endpoints

The redesign should keep operator actions on the current resource API:
- send operator chat input through `POST /v1/conversations/{id}/messages`
- send approve/reject/cancel through `POST /v1/conversations/{id}/actions`

Do not make the event timeline responsible for writing raw events. The action bar remains the mutation surface; the timeline is the read model.

**Exit gate**: Chat timeline scrolls independently. Compose box stays visible at bottom. New messages auto-scroll only when user was near bottom. Event rendering is keyed to the current SDK/backend contract. History UX does not promise unsupported reverse pagination behavior. Works on mobile.

## Phase 3: Visual polish (P4, P8)

### 3.1 Card glass effect

```css
.card {
    background: var(--glass-bg);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border: 1px solid var(--glass-border);
    border-radius: var(--sp-2);
    padding: var(--sp-4);
    margin-bottom: var(--sp-3);
    transition: transform var(--transition-fast), box-shadow var(--transition-fast);
}

.card.clickable:hover {
    transform: translateY(-2px);
    box-shadow: var(--elevation-2);
}
```

### 3.2 Sidebar glass

```css
#sidebar {
    background: var(--glass-bg);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border-right: 1px solid var(--glass-border);
}
```

### 3.3 Route transitions

```css
#content {
    transition: opacity var(--transition-fast);
}

#content.route-entering {
    opacity: 0;
    transform: translateY(8px);
}

#content.route-visible {
    opacity: 1;
    transform: translateY(0);
    transition: opacity var(--transition-med), transform var(--transition-med);
}
```

The **router** (`ui/js/router.js`) applies `route-entering` class on navigation start, then on next frame applies `route-visible`. This must be in the router, not `app.js`, because route render/cleanup/error handling already live in the router and transitions must be synchronized with the navigation lifecycle.

### 3.4 Event card expand animation

```css
.event-card-body {
    max-height: 0;
    overflow: hidden;
    transition: max-height var(--transition-med);
}

.event-card-body.expanded {
    max-height: 500px; /* generous upper bound */
}
```

### 3.5 Modal fade

```css
.confirm-overlay {
    opacity: 0;
    transition: opacity var(--transition-fast);
}

.confirm-overlay.visible {
    opacity: 1;
}
```

Show modal by adding element, then on next frame adding `.visible`.

**Exit gate**: Cards have glass effect and hover lift. Routes fade in. Event cards expand smoothly. Modals fade in/out.

## Phase 4: Mobile-first layout rewrite (P6)

### 4.1 Base styles are mobile

```css
/* Base (mobile): single column, full width */
#content {
    margin-left: 0;
    padding: var(--sp-5) var(--sp-3);
    padding-top: 56px; /* hamburger space */
}

#sidebar {
    transform: translateX(-100%);
}

.hamburger {
    display: flex;
}

/* Tablet: collapsed sidebar */
@media (min-width: 641px) {
    #content {
        margin-left: var(--sidebar-collapsed);
        padding: var(--sp-6) var(--sp-5);
        padding-top: var(--sp-6);
    }
    #sidebar {
        transform: translateX(0);
        width: var(--sidebar-collapsed);
    }
    .hamburger {
        display: none;
    }
}

/* Desktop: full sidebar */
@media (min-width: 1025px) {
    #content {
        margin-left: var(--sidebar-width);
        padding: var(--sp-6) var(--sp-7);
    }
    #sidebar {
        width: var(--sidebar-width);
    }
}
```

### 4.2 Touch-friendly targets

```css
/* Mobile: all interactive elements min 44px */
@media (max-width: 640px) {
    .btn { min-height: 44px; padding: var(--sp-3) var(--sp-4); }
    .nav-links li a { min-height: 44px; }
    select, input { min-height: 44px; font-size: 16px; } /* 16px prevents iOS zoom */
}
```

### 4.3 Responsive table → card list

On mobile, tables transform into stacked cards (already partially done). Ensure all tables with `.responsive` class use the `data-label` pattern consistently.

**Exit gate**: Default layout is mobile. Sidebar is off-canvas on mobile, collapsed on tablet, full on desktop. All targets are 44px minimum on touch.

## Phase 5: Shared render helpers (P9, P10)

### 5.1 renderCard()

```javascript
function renderCard({ title, subtitle, badge, onClick, actions } = {}) {
    const card = document.createElement('div');
    card.className = 'card' + (onClick ? ' clickable' : '');
    // ... standard card-row + info + badge structure
    if (onClick) card.addEventListener('click', onClick);
    return card;
}
```

### 5.2 renderFilterBar()

```javascript
function renderFilterBar({ searchPlaceholder, statusOptions, onSearch, onStatusChange } = {}) {
    // Returns a filter-bar div with search input + optional status select
}
```

### 5.3 renderStatCard()

```javascript
function renderStatCard(stats) {
    // stats = [{value: "1,234", label: "Prompt Tokens"}, ...]
    // Returns a summary-card with stat items
}
```

### 5.4 Remove inline styles

Replace all `element.style.*` assignments in guidance-editor, conversation-list dialog, and skill-catalog with CSS classes:
- `.guidance-textarea` class (already exists, just use it)
- `.dialog-select`, `.dialog-label` classes
- `.detail-section` class for task details

### 5.5 Fix CSS variable references

Replace throughout JS components:
- `--border-color` → `--border`
- `--color-success` → `--success`
- `--color-danger` → `--danger`
- `--text-primary` → `--text`
- `--bg-secondary` in inline styles → use CSS class

**Exit gate**: No `element.style.*` assignments in component JS. Card rendering uses shared helpers. All CSS variable references are valid.

## Phase 6: Information density + page-specific improvements

### 6.1 Agents page: dashboard summary

Before the agent list, show a summary bar:
- Agents on this page
- Connected on this page
- Degraded on this page
- Stopped/offline on this page

This plan should stay aligned with the current backend and avoid inventing a summary API. The summary bar is therefore **page-scoped**, not global.

Rules:
- Compute only from the current `/v1/agents` page payload.
- Label it clearly as page-scoped if needed.
- Do not show "total conversations" or other global cross-page aggregates on the landing page unless a separate backend plan adds a real aggregate endpoint.
- Agent-specific operational metrics such as `active_conversations` and `recent_errors` belong on the agent detail page, where `/v1/agents/{id}/status` already provides them.

### 6.2 Capabilities + Skills: compact layout

Replace one-card-per-item with a compact grid:

```css
.compact-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: var(--sp-3);
}
```

Each card shows name, badge, and action button in one row. Less vertical waste.

### 6.3 Usage: chart placeholder

Add a simple bar chart for daily usage using CSS (no charting library):

```css
.usage-bar {
    height: 4px;
    background: var(--accent);
    border-radius: 2px;
    transition: width var(--transition-med);
}
```

Use the current `/v1/usage` contract:
- `daily_total`
- `by_conversation[]`

Relative widths are computed from the max value across `by_conversation`.

### 6.4 Guidance: live preview pane

Split the guidance editor into two columns on desktop: textarea on left, rendered preview on right. On mobile, preview is in a modal (already exists).

**Exit gate**: Agents page shows summary stats. Skills/capabilities are denser. Usage has visual bars.

## Phase 7: Accessibility foundations (P11)

### 7.1 ARIA on key interactive patterns

```javascript
// Event card expand/collapse
header.setAttribute('role', 'button');
header.setAttribute('aria-expanded', 'false');
// On toggle:
header.setAttribute('aria-expanded', body.classList.contains('expanded'));

// Modal dialogs
dialog.setAttribute('role', 'dialog');
dialog.setAttribute('aria-modal', 'true');
dialog.setAttribute('aria-labelledby', titleId);

// Toggle switch
checkbox.setAttribute('role', 'switch');
checkbox.setAttribute('aria-checked', checkbox.checked);
```

### 7.2 Focus trapping in modals

When a modal opens, trap Tab/Shift+Tab within the dialog. Restore focus on close.

### 7.3 Skip to content link

Hidden link at the top of the page that becomes visible on focus:
```html
<a href="#content" class="skip-link">Skip to content</a>
```

### 7.4 Color contrast check

Ensure all text/background combinations meet WCAG AA (4.5:1 for normal text, 3:1 for large text). The dark theme's `--text-muted` (#6e7681) on `--bg` (#0d1117) is borderline — may need to lighten to #848d97.

### 7.5 Keyboard navigation for custom interactive elements

All custom clickable elements (cards, headers, drawer toggles) need:
- `tabindex="0"` for focusability
- Enter/Space activation via `keydown` handler
- Explicit focus return when closing drawers/modals (back to the trigger element)

### 7.6 Reduced motion

```css
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        transition-duration: 0.01ms !important;
    }
}
```

**Exit gate**: All expandable elements have `aria-expanded`. Modals have `role="dialog"` and focus trapping. Toggle switches have `role="switch"`. Custom clickable elements are keyboard-focusable with Enter/Space activation. `prefers-reduced-motion` disables animations.

## Implementation sequence

| Order | Phase | Size | Depends on |
|-------|-------|------|------------|
| 1 | Phase 1 (tokens + themes) | Medium | Nothing |
| 2 | Phase 2 (chat fix) | Small | Phase 1 (uses tokens) |
| 3 | Phase 4 (mobile-first layout) | Medium | Phase 1 |
| 4 | Phase 3 (visual polish) | Small | Phase 1 |
| 5 | Phase 5 (shared helpers) | Medium | Nothing |
| 6 | Phase 6 (density) | Small | Phases 1, 5 |
| 7 | Phase 7 (accessibility) | Small | Phases 5, 6 |

Phase 1 is the foundation — everything else uses the tokens. Phase 2 is the highest-priority UX fix. Phase 5 is independent (JS only).

## Files changed

| File | Changes |
|------|---------|
| `ui/css/main.css` | Full rewrite: tokens, themes, glass, mobile-first, transitions, chat layout |
| `ui/index.html` | Add theme toggle in sidebar footer, skip-link, meta theme-color |
| `ui/js/app.js` | Theme bootstrap and shared render helpers |
| `ui/js/router.js` | Route transition lifecycle classes |
| `ui/js/components/conversation-detail.js` | Conversation view flex layout, fixed compose box, correct live scroll behavior, contract-driven event cards |
| `ui/js/components/agent-list.js` | Use renderCard helper, add page-scoped dashboard summary |
| `ui/js/components/agent-detail.js` | Surface existing agent status metrics (`active_conversations`, `recent_errors`) more clearly |
| `ui/js/components/conversation-list.js` | Use renderCard helper, fix new-conversation dialog inline styles |
| `ui/js/components/task-list.js` | Use renderCard helper |
| `ui/js/components/capability-list.js` | Compact grid layout |
| `ui/js/components/skill-catalog.js` | Compact grid layout, remove inline styles |
| `ui/js/components/usage-view.js` | Add visual bars |
| `ui/js/components/guidance-editor.js` | Remove inline styles, split-pane on desktop |
| `ui/js/components/login-form.js` | Theme-aware styling |

## Non-goals

- No JS framework (React, Vue, etc.) — vanilla stays
- No build step (webpack, vite) — direct script tags stay
- No charting library — CSS bars only
- No full WCAG AAA compliance (AA foundations only)
- No intentional redesign of registry data models, database tables, SDK event schemas, or resource routes as part of this UI plan
- No UI-only invented payload fields; the redesign consumes the current backend contract and calls out any true backend dependency explicitly
