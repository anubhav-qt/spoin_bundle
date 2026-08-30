"use client";

/**
 * A labelled trigger button ("Theme — Notebook", chevron) that opens its
 * children in a small popover. Used by `ThemePicker` and `FontPicker` in
 * their `variant="dropdown"` form for the right rail's utility row, where the
 * always-expanded swatch/`Aa` rows don't fit four-up.
 *
 * The popover is a `document.body` portal positioned from the trigger's
 * `getBoundingClientRect()`, recomputed on scroll/resize — same escape hatch
 * `TopicDiscoveryModal` and `DailyGoalRing` use, because `.rail-right` is
 * `overflow: hidden` and would clip an absolutely-positioned child.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface Props {
  /** Small uppercase label above the value. */
  label: string;
  /** The current selection, shown in the trigger. */
  value: string;
  /** Which edge of the trigger the popover hugs — "right" for controls near
   *  the rail's right edge so the popover opens inward. */
  align?: "left" | "right";
  /** Fires whenever the popover opens or closes. Pickers use `open === false`
   *  to reset any transient sub-state (a half-filled "name this theme" modal,
   *  a pending font import) that would otherwise reappear on the next open —
   *  the children unmount on close but the picker component stays mounted. */
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
}

export function PickerDropdown({ label, value, align = "left", onOpenChange, children }: Props) {
  const [open, setOpen] = useState(false);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Fire `onOpenChange` on the open↔closed transition, from an effect rather
  // than inside the state updater — the callback runs `setState` in a *parent*
  // (a picker resetting its transient sub-state), which React forbids during
  // another component's render phase.
  const prevOpen = useRef(open);
  useEffect(() => {
    if (prevOpen.current !== open) {
      prevOpen.current = open;
      onOpenChange?.(open);
    }
  }, [open, onOpenChange]);

  const measure = useCallback(() => {
    if (triggerRef.current) setRect(triggerRef.current.getBoundingClientRect());
  }, []);

  useLayoutEffect(() => {
    if (open) measure();
  }, [open, measure]);

  useEffect(() => {
    if (!open) return;
    const reposition = () => measure();
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !menuRef.current?.contains(target)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("resize", reposition);
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, measure]);

  return (
    <div className="picker-dropdown">
      <span className="picker-dropdown-label mono">{label}</span>
      <button
        ref={triggerRef}
        type="button"
        className="picker-dropdown-trigger"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="picker-dropdown-value">{value}</span>
        <svg className="picker-dropdown-chevron" viewBox="0 0 24 24" aria-hidden="true">
          <path d="m7 10 5 5 5-5" />
        </svg>
      </button>

      {open && rect
        ? createPortal(
            <div
              ref={menuRef}
              className="picker-dropdown-menu"
              style={{
                position: "fixed",
                top: rect.bottom + 8,
                ...(align === "right"
                  ? { right: Math.max(8, window.innerWidth - rect.right) }
                  : { left: Math.max(8, rect.left) }),
              }}
            >
              {children}
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
