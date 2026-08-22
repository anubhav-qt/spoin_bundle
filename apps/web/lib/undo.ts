"use client";

/**
 * Single-slot undo toast (docs/tasks — Notes/Liked/Saved removal undo).
 *
 * Mirrors `refresh.ts`'s pub/sub shape: a module-level store, one component
 * (`UndoToast`) subscribed to it. Needed because every collection view
 * (Notes/Liked/Saved) stays mounted-but-hidden once visited (AppShell), so a
 * toast owned by whichever view triggered the removal would be invisible the
 * moment the user switches views mid-countdown. One toast, mounted once in
 * AppShell, outside every view's subtree.
 *
 * **One entry at a time, newest wins.** Removing a second card while the
 * first's toast is still up replaces it outright — the first becomes
 * un-undoable. A queue would turn a 5-second convenience into a triage list;
 * this matches how most "undo remove" toasts (Gmail's archive/delete) behave.
 *
 * **The X dismisses, it does not undo.** The removal already happened
 * (delete-now, not defer-then-commit — see the view callers); closing early
 * just gives up the chance to reverse it.
 */

const UNDO_WINDOW_MS = 5000;

export interface UndoEntry {
  /** Shown in the toast, e.g. "Removed from Liked". */
  label: string;
  onUndo: () => void | Promise<void>;
}

type Listener = (entry: UndoEntry | null) => void;

let current: UndoEntry | null = null;
let timer: ReturnType<typeof setTimeout> | null = null;
const listeners = new Set<Listener>();

function notify(): void {
  for (const fn of listeners) fn(current);
}

function clearTimer(): void {
  if (timer !== null) {
    clearTimeout(timer);
    timer = null;
  }
}

/** Replaces any in-flight undo offer with this one and (re)starts the
 *  5-second window. */
export function offerUndo(entry: UndoEntry): void {
  clearTimer();
  current = entry;
  notify();
  timer = setTimeout(() => {
    current = null;
    timer = null;
    notify();
  }, UNDO_WINDOW_MS);
}

/** Explicit dismissal (the toast's X) or a successful undo -- either way,
 *  withdraws the offer without re-triggering it. */
export function dismissUndo(): void {
  clearTimer();
  current = null;
  notify();
}

export function subscribeUndo(fn: Listener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}
