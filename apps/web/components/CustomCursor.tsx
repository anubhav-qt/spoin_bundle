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

    const onDown = (event: PointerEvent) => {
      if (event.button !== 0) return;
      dot.dataset.state = "active";
    };

    const onUp = (event: PointerEvent) => {
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
