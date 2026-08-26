# Mayank's UI Changes Archive (2026-08-26)

This document records all UI changes introduced by Mayank across PRs/branches (`daily-goal-ring`, `mobile-shell-nav`, `mobile-compatibility`, `daily-goal-popover-portal-fix`) before being reverted from `apps/web`.

---

## 1. Summary of Features Introduced

### A. Daily Goal Progress Ring (ADR-0062)
- **Purpose**: Render a circular SVG progress ring tracking `cards_read` vs `daily_card_goal` for the reader's local day.
- **Components Added/Modified**:
  - `apps/web/components/DailyGoalRing.tsx`: SVG ring with `strokeDashoffset` progress, hover/click pinned state, and portaled popover mounted to `document.body`.
  - `apps/web/lib/api.ts`: Added `getTodayProgress()` calling `GET /profile/me/today?tz_offset_minutes=...`.
  - `apps/web/components/RightRail.tsx`: Added DailyGoalRing into right rail utility row.
  - `apps/web/components/AppShell.tsx`: Lifted `dailyGoal` state and `refreshDailyGoal` callback triggered on card seen events.

### B. Mobile Shell Navigation (ADR-0063)
- **Purpose**: Floating pill bottom navigation for phones (≤680px) and slide-over/bottom sheet for right rail filters.
- **Components Added/Modified**:
  - `apps/web/components/MobileTopBar.tsx`: Fixed top bar on mobile (≤680px) merging wordmark, daily goal ring, focus toggle, and refresh button.
  - `apps/web/components/MobileProfileNav.tsx`: Profile sub-navigation grouping Notes, Liked, Saved, and Log out into a bordered card inside `ProfileView.tsx`.
  - `apps/web/components/Sidebar.tsx`: Added "Topics" trigger item (`.nav-item-topics-trigger`) to open the right rail sheet on smaller viewports.
  - `apps/web/components/RightRail.tsx`: Wrapped in backdrop (`.rail-sheet-backdrop`) and added close button (`.rail-sheet-close`) for sheet mode.
  - `apps/web/components/icons.tsx`: Added `SlidersIcon` and `CloseIcon`.
  - `apps/web/app/layout.tsx`: Added `viewportFit: "cover"` to viewport config for mobile notch support.

### C. CSS & Breakpoint Overhauls (`apps/web/app/globals.css`)
- Added sticky mobile topic filter strip (`.mobile-topic-strip`).
- Added responsive media queries for 1400px, 1150px, 900px, and 680px.
- Bottom floating pill nav (`.nav-items`, 4 items: Home, Topics, Profile, Settings).
- Portaled popover positioning styles (`.share-popover.daily-goal-popover`).

---

## 2. File-by-File Breakdown of Reverted Files

### 1. `apps/web/components/DailyGoalRing.tsx`
- Circular SVG progress ring component with hover/click pinned popover
- Portaled to `document.body` via `ReactDOM.createPortal`
- Tracked `cardsRead` vs `goal`

### 2. `apps/web/components/MobileTopBar.tsx`
- Fixed top bar rendered only at ≤680px
- Hosts wordmark on left, DailyGoalRing + FocusToggle + RefreshIcon on right

### 3. `apps/web/components/MobileProfileNav.tsx`
- Nested navigation inside ProfileView on mobile
- Houses Notes, Liked, Saved, Log out

### 4. `apps/web/components/AppShell.tsx`
- Reverted `dailyGoal` state and `refreshDailyGoal` polling.
- Reverted `MobileTopBar` render outside `.app-grid`.
- Reverted `.mobile-topic-strip` render.
- Reverted `onOpenRail` and `railOpen` state plumbing.

### 5. `apps/web/components/RightRail.tsx`
- Reverted sheet backdrop, sheet close button, and `open`/`onClose` props.
- Reverted `DailyGoalRing` and `FocusToggle` row restructuring.

### 6. `apps/web/components/Sidebar.tsx`
- Reverted `.nav-item-topics-trigger` and `onOpenRail` prop.
- Reverted mobile-hidden class tags (`.nav-item-mobile-hidden`, etc.).

### 7. `apps/web/components/ProfileView.tsx`
- Reverted `<MobileProfileNav>` inclusion.

### 8. `apps/web/components/icons.tsx`
- Reverted `CloseIcon` and `SlidersIcon`.

### 9. `apps/web/lib/api.ts`
- Reverted `DailyGoalOut` type interface and `getTodayProgress()` method.

### 10. `apps/web/app/globals.css`
- Reverted mobile shell floating pill, mobile topbar, topic strip, sheet backdrop/animations, and daily goal ring CSS classes.

---

## 3. Related ADR & Task References
- `docs/adr/0062-daily-goal-ring-and-local-day-semantics.md`
- `docs/adr/0063-mobile-shell.md`
- `docs/tasks/0027-mobile-shell.md`
