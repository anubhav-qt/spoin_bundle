"use client";

/**
 * A themed circular cursor, replacing the native pointer on fine-pointer
 * (mouse) devices only — `matchMedia("(pointer: fine)")` gates it off on
 * touch, where there's no hover to represent and forcing `cursor: none`
 * would just make taps harder to reason about.
 *
 * Two nested elements, not one, and deliberately so: the outer `.custom-
 * cursor-pos` is repositioned every pointermove via a direct style mutation
 * (not React state — this fires far too often for a re-render per event),
 * while the inner `.custom-cursor` carries the hover/active *visual* state
 * through a CSS `transform: scale()` driven by `data-state`. Putting both on
 * the same element would mean the JS-driven `translate3d` and CSS-driven
 * `scale` fight over the same `transform` property — same reason Card.tsx's
 * `.card-focus` is a separate element from the Framer-Motion-driven `.node`.
 *
 * Colors are theme tokens, not hardcoded — --accent for the outline, --accent-2
 * for the idle fill (a genuinely different color per palette, ADR-0012), the
 * hover state fills solid with the OUTLINE's own color, and the active
 * (left-click) state uses a shade of that same outline color via `color-mix`
 * rather than a third token, so it holds for every palette without needing
 * per-theme tuning.
 */

import { useEffect, useRef } from "react";

const INTERACTIVE_SELECTOR =
  'button, a, input, select, textarea, [role="button"], [tabindex]:not([tabindex="-1"]), .card:not([data-hero="true"])';

export function CustomCursor() {
  const posRef = useRef<HTMLDivElement>(null);
  const dotRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!window.matchMedia("(pointer: fine)").matches) return;

    const pos = posRef.current;
    const dot = dotRef.current;
    if (pos === null || dot === null) return;

    document.body.classList.add("custom-cursor-active");

    let raf = 0;
    let x = 0;
    let y = 0;

    const paint = () => {
      pos.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    };

    const hoverStateFor = (target: EventTarget | null): "hover" | "default" => {
      const el = target instanceof Element ? target : null;
      return el !== null && el.closest(INTERACTIVE_SELECTOR) !== null ? "hover" : "default";
    };

    const onMove = (event: PointerEvent) => {
      x = event.clientX;
      y = event.clientY;
      if (pos.dataset.visible !== "true") pos.dataset.visible = "true";
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(paint);
      // A left-click's "active" fill is restored to hover/default explicitly
      // on pointerup, not overwritten mid-press by ordinary hover tracking.
      if (dot.dataset.state !== "active") dot.dataset.state = hoverStateFor(event.target);
    };

    // A native scrollbar isn't part of the DOM, so `cursor: none` never
    // reaches it -- the browser always draws its own cursor there, drag or
    // no drag, and there's no fixing that. Dragging the thumb is the part
    // that actually breaks: the browser captures the pointer at the OS/
    // chrome level for the rest of the drag, so `document` stops receiving
    // `pointermove` entirely until release -- our JS-driven dot freezes at
    // the mousedown position while the real cursor keeps moving. The only
    // element a scrollbar click can hit-test to is `<html>` (nothing else
    // occupies that pixel column/row), so combined with the click landing
    // within the OS-reported scrollbar's own thickness of the viewport edge,
    // that's the best signal a plain PointerEvent gives us.
    const isScrollbarTarget = (event: PointerEvent): boolean => {
      if (event.target !== document.documentElement) return false;
      const vScrollbar = window.innerWidth - document.documentElement.clientWidth;
      const hScrollbar = window.innerHeight - document.documentElement.clientHeight;
      return (
        (vScrollbar > 0 && event.clientX >= window.innerWidth - vScrollbar) ||
        (hScrollbar > 0 && event.clientY >= window.innerHeight - hScrollbar)
      );
    };

    const onDown = (event: PointerEvent) => {
      if (event.button !== 0) return;
      if (isScrollbarTarget(event)) {
        // Bow out for the duration of the drag: hide the dot and hand the
        // whole page back to the native cursor, same as the scrollbar
        // itself already forces regardless. The next real `pointermove`
        // after release re-shows it at the (by-then-correct) position.
        pos.dataset.visible = "false";
        document.body.classList.remove("custom-cursor-active");
        return;
      }
      dot.dataset.state = "active";
    };

    const onUp = (event: PointerEvent) => {
      document.body.classList.add("custom-cursor-active");
      dot.dataset.state = hoverStateFor(event.target);
    };

    const onLeaveWindow = () => {
      pos.dataset.visible = "false";
    };

    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("pointerup", onUp);
    document.addEventListener("mouseleave", onLeaveWindow);

    return () => {
      document.body.classList.remove("custom-cursor-active");
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("pointerup", onUp);
      document.removeEventListener("mouseleave", onLeaveWindow);
      cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div ref={posRef} className="custom-cursor-pos" data-visible="false" aria-hidden="true">
      <div ref={dotRef} className="custom-cursor" data-state="default" />
    </div>
  );
}
