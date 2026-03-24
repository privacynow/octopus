# PLAN: UI Redesign — Mobile-First, Polished, Light + Dark

## Context

The registry SPA works functionally (conversations, delegation, usage, skills, guidance) but has critical UX bugs and a flat, unpolished visual design. Reference: liftandshift.io — warm monochromatic palette, frosted glass cards, smooth transitions, mobile-first accordion patterns.

This plan fixes the broken chat experience, adds visual polish, introduces a light theme, and cleans up the component architecture — all in vanilla HTML/CSS/JS (no framework).

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

The conversation detail becomes a flex column filling the viewport below the sidebar header:

```css
/* Conversation detail occupies remaining height */
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

Now that timeline has `overflow-y: auto`, the existing `scrollTop` logic works:
```javascript
// After appending new message:
const isNearBottom = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 100;
if (isNearBottom) {
    timeline.scrollTop = timeline.scrollHeight;
}
```

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

### 2.4 "Load older" as scroll sentinel

Replace the "Load older" button with a scroll sentinel at the top of the timeline. When the user scrolls to the top, older messages load automatically.

**Exit gate**: Chat timeline scrolls independently. Compose box stays visible at bottom. New messages auto-scroll. Works on mobile.

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

Router applies `route-entering` class, then on next frame applies `route-visible`.

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
- Total agents, connected count, degraded count
- Total conversations, active conversations
- Computed from the existing `listAgents` response

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

Relative widths computed from the max value across conversations.

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

**Exit gate**: All expandable elements have `aria-expanded`. Modals have `role="dialog"` and focus trapping. Toggle switches have `role="switch"`.

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
| `ui/js/app.js` | Theme toggle logic, route transition classes, shared render helpers |
| `ui/js/components/conversation-detail.js` | Conversation view flex layout, fixed compose box, working scroll |
| `ui/js/components/agent-list.js` | Use renderCard helper, add dashboard summary |
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
- No redesign of the data model or API layer
