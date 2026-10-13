import { useCallback, useEffect, useRef, useState } from "react";
import { pathOf } from "../agents";
import { api } from "../api/client";
import type { AccountOverview, Conversation } from "../api/types";
import { useAuth } from "../auth";
import { AccountPanel } from "../components/AccountPanel";
import { Composer } from "../components/Composer";
import { ConversationItem } from "../components/ConversationItem";
import { DraftView, MessageView } from "../components/Message";
import { Switchboard } from "../components/Switchboard";
import { useChat } from "../useChat";

const SUGGESTIONS: Record<string, string[]> = {
  C001: ["I was charged twice this month", "Where are my headphones?", "The app crashes when I open it"],
  C002: ["I want to return my desk lamp", "Why is my invoice overdue?", "The API gives me a 403"],
  C003: ["My standing desk is late again", "Refund my last invoice", "I lost the phone I use for 2FA"],
};
const GENERIC = ["Where is my order?", "I have a question about a charge", "I can't sign in"];

export function ChatPage() {
  const { user, logout } = useAuth();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [account, setAccount] = useState<AccountOverview | null>(null);
  const [drawer, setDrawer] = useState<"none" | "list" | "account">("none");
  const threadEnd = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    const [list, acct] = await Promise.all([api.conversations(), api.account()]);
    setConversations(list);
    setAccount(acct);
    return list;
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.conversations(), api.account()])
      .then(async ([list, acct]) => {
        // Open the latest conversation, or start the customer's first one.
        const convs = list.length ? list : [await api.createConversation()];
        if (cancelled) return;
        setAccount(acct);
        setConversations(convs);
        setActiveId(convs[0]!.id);
      })
      .catch(() => {
        /* 401s sign the user out via the API client; nothing else to show yet */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const active = conversations.find((c) => c.id === activeId) ?? null;
  const chat = useChat(activeId, active?.active_agent ?? null, refresh);
  const busy = chat.pending !== null;

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [chat.messages.length, chat.pending?.drafts]);

  const newConversation = async () => {
    const c = await api.createConversation();
    setConversations((cs) => [c, ...cs]);
    setActiveId(c.id);
    setDrawer("none");
  };

  const deleteConversation = async (id: string) => {
    await api.deleteConversation(id);
    const rest = conversations.filter((c) => c.id !== id);
    if (id !== activeId) {
      setConversations(rest);
      return;
    }
    // Deleted the open chat: move to the next one, or start a fresh one if none are left.
    const next = rest[0] ?? (await api.createConversation());
    setConversations(rest.length ? rest : [next]);
    setActiveId(next.id);
  };

  const path = chat.pending ? pathOf(chat.pending.trace, chat.activeAgent) : pathOf(chat.lastTrace, chat.activeAgent);
  const suggestions = SUGGESTIONS[user?.customer_id ?? ""] ?? GENERIC;

  return (
    <div className="app" data-drawer={drawer}>
      <header className="topbar">
        <p className="wordmark">Nimbus Help</p>
        <nav className="topbar-actions">
          <button className="btn btn-quiet only-narrow" onClick={() => setDrawer(drawer === "list" ? "none" : "list")}>
            Conversations
          </button>
          <button
            className="btn btn-quiet only-narrow"
            onClick={() => setDrawer(drawer === "account" ? "none" : "account")}
          >
            Account
          </button>
          <span className="who">{user?.display_name}</span>
          <button className="btn btn-quiet" onClick={logout}>
            Sign out
          </button>
        </nav>
      </header>

      <nav className="convos" aria-label="Conversations">
        <button className="btn btn-outline" onClick={newConversation} disabled={busy}>
          New conversation
        </button>
        <ul>
          {conversations.map((c) => (
            <ConversationItem
              key={c.id}
              conversation={c}
              current={c.id === activeId}
              disabled={busy}
              onOpen={() => {
                setActiveId(c.id);
                setDrawer("none");
              }}
              onDelete={() => deleteConversation(c.id)}
            />
          ))}
        </ul>
      </nav>

      <main className="thread-col">
        <Switchboard path={path} live={busy} />
        <div className="thread" aria-live="polite" aria-busy={busy}>
          {activeId && !chat.loading && chat.messages.length === 0 && !busy && (
            <div className="empty">
              <h1>What can we help with?</h1>
              <p>Tell us in your own words. You can ask about orders, charges, your account or the app.</p>
              <ul className="suggestions">
                {suggestions.map((s) => (
                  <li key={s}>
                    <button className="btn btn-outline" onClick={() => void chat.send(s)}>
                      {s}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {chat.messages.map((m) => (
            <MessageView key={m.key} message={m} />
          ))}
          {chat.pending?.drafts.map((d, i) => <DraftView key={i} agent={d.agent} text={d.text} />)}
          {busy && !chat.pending?.drafts.length && (
            <p className="working">{chat.pending?.trace.length ? "Working on it" : "Reading your message"}</p>
          )}
          {chat.error && (
            <p className="notice notice-error" role="alert">
              {chat.error}
            </p>
          )}
          <div ref={threadEnd} />
        </div>
        <Composer disabled={busy || !activeId} onSend={(t) => void chat.send(t)} />
      </main>

      <AccountPanel account={account} />
      {drawer !== "none" && <button className="scrim" aria-label="Close panel" onClick={() => setDrawer("none")} />}
    </div>
  );
}
