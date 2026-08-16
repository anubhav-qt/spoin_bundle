"use client";

/**
 * Enters/exits focus mode: hides both rails, leaving just the feed. Rendered
 * in two different places by the same component so behavior stays in one
 * spot — inline in the theme row when entering (filling the leftover width
 * next to the swatches), fixed top-right when exiting (the rails that would
 * normally host it are unmounted in focus mode).
 */

import { FocusIcon } from "./icons";

interface Props {
  focused: boolean;
  onToggle: () => void;
}

export function FocusToggle({ focused, onToggle }: Props) {
  return (
    <button
      type="button"
      className="focus-toggle"
      data-focused={focused}
      data-tooltip={focused ? "Exit focus" : "Focus"}
      aria-label={focused ? "Exit focus mode" : "Enter focus mode"}
      onClick={onToggle}
    >
      <FocusIcon />
      {focused ? null : <span>Focus</span>}
    </button>
  );
}
