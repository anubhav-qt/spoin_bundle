/**
 * The reduced-motion preference from Settings.
 *
 * Stored and read exactly like the palette and font choices (localStorage +
 * an attribute on <body>, set pre-hydration by `app/layout.tsx`), so there is
 * one persistence pattern for appearance preferences rather than two.
 *
 * It takes BOTH halves to actually stop motion in this app:
 *
 *   - CSS transitions/animations   -> `body[data-reduced-motion="1"]` in
 *                                     globals.css
 *   - Framer Motion                -> `<MotionConfig reducedMotion>` in
 *                                     AppShell, because Framer animates
 *                                     through inline style updates per frame,
 *                                     which no stylesheet rule can override
 *
 * The OS-level `prefers-reduced-motion: reduce` is honoured independently and
 * always. This switch can only turn motion OFF, never back on against the OS
 * setting — see `effectiveReducedMotion`.
 */

const STORAGE_KEY = "spoin-reduced-motion";
const ATTRIBUTE = "data-reduced-motion";

type Listener = () => void;
const listeners = new Set<Listener>();

export function getReducedMotion(): boolean {
  if (typeof document === "undefined") return false;
  return document.body.getAttribute(ATTRIBUTE) === "1";
}

export function setReducedMotion(on: boolean): void {
  if (on) {
    document.body.setAttribute(ATTRIBUTE, "1");
  } else {
    document.body.removeAttribute(ATTRIBUTE);
  }
  try {
    localStorage.setItem(STORAGE_KEY, on ? "1" : "0");
  } catch {
    // Private mode / storage disabled: the attribute above still applies for
    // this session, it just won't survive a reload. Not worth surfacing.
  }
  for (const listener of listeners) listener();
}

export function subscribeReducedMotion(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** True when motion should be reduced for any reason — the user's switch OR
 *  the OS setting. This is what components act on; the switch itself shows
 *  only the stored value, so the control never claims to be "on" because of
 *  something it doesn't own. */
export function effectiveReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return (
    getReducedMotion() || window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** Server snapshot for useSyncExternalStore — no DOM, no preference. */
export function getServerSnapshot(): boolean {
  return false;
}
