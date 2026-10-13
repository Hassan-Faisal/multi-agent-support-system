import { useEffect, useRef, useState } from "react";
import type { Conversation } from "../api/types";
import { fmtAgo } from "../format";

interface Props {
  conversation: Conversation;
  current: boolean;
  disabled: boolean;
  onOpen: () => void;
  onDelete: () => Promise<void>;
}

/** One row in the conversation list, with a "⋯" menu holding Delete (confirmed inline). */
export function ConversationItem({ conversation: c, current, disabled, onOpen, onDelete }: Props) {
  const [menu, setMenu] = useState<"closed" | "open" | "confirm">("closed");
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const root = useRef<HTMLLIElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (menu === "closed") return;
    const onPointer = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setMenu("closed");
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMenu("closed");
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [menu]);

  const confirmDelete = async () => {
    setDeleting(true);
    setError(null);
    try {
      await onDelete();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't delete this chat.");
      setDeleting(false);
    }
  };

  return (
    <li className="convo-row" ref={root} data-menu={menu}>
      <button className="convo" aria-current={current ? "page" : undefined} disabled={disabled} onClick={onOpen}>
        <span className="convo-title">{c.title}</span>
        <span className="convo-meta">{fmtAgo(c.updated_at)}</span>
      </button>
      <button
        ref={trigger}
        className="convo-more"
        aria-label={`Options for "${c.title}"`}
        aria-haspopup="menu"
        aria-expanded={menu !== "closed"}
        disabled={disabled}
        onClick={() => setMenu(menu === "closed" ? "open" : "closed")}
      >
        <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
          <circle cx="3" cy="8" r="1.5" />
          <circle cx="8" cy="8" r="1.5" />
          <circle cx="13" cy="8" r="1.5" />
        </svg>
      </button>

      {menu === "open" && (
        <div className="convo-menu" role="menu">
          <button role="menuitem" className="convo-menu-item danger" autoFocus onClick={() => setMenu("confirm")}>
            Delete chat
          </button>
        </div>
      )}
      {menu === "confirm" && (
        <div className="convo-menu" role="alertdialog" aria-label="Delete this chat?">
          <p className="convo-confirm">Delete this chat? This can't be undone.</p>
          {error && (
            <p className="convo-confirm notice-error" role="alert">
              {error}
            </p>
          )}
          <div className="convo-confirm-actions">
            <button className="btn btn-quiet" onClick={() => setMenu("closed")} disabled={deleting}>
              Cancel
            </button>
            <button className="btn btn-danger" autoFocus onClick={() => void confirmDelete()} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete"}
            </button>
          </div>
        </div>
      )}
    </li>
  );
}
