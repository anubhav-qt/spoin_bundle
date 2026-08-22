"use client";

/**
 * Single toast for the Notes/Liked/Saved removal-undo window (`lib/undo.ts`).
 * Mounted once in AppShell, outside every view's `hidden`-toggled subtree —
 * see that module's doc comment for why a per-view toast wouldn't survive a
 * view switch mid-countdown.
 */

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

import { dismissUndo, subscribeUndo, type UndoEntry } from "@/lib/undo";

export function UndoToast() {
  const [entry, setEntry] = useState<UndoEntry | null>(null);

  useEffect(() => subscribeUndo(setEntry), []);

  const handleUndo = () => {
    // Withdraw the offer immediately so a slow onUndo can't be triggered
    // twice by an impatient double-click, then run it.
    const onUndo = entry?.onUndo;
    dismissUndo();
    void onUndo?.();
  };

  return (
    <AnimatePresence>
      {entry ? (
        <motion.div
          className="undo-toast"
          role="status"
          aria-live="polite"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 16 }}
          transition={{ duration: 0.18 }}
        >
          <span className="undo-toast-label">{entry.label}</span>
          <button type="button" className="undo-toast-action" onClick={handleUndo}>
            Undo
          </button>
          <button
            type="button"
            className="undo-toast-dismiss"
            aria-label="Dismiss"
            onClick={() => dismissUndo()}
          >
            ×
          </button>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
