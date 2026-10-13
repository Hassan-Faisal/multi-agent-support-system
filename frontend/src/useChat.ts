import { useCallback, useEffect, useReducer, useRef } from "react";
import { ApiError, api } from "./api/client";
import type { AgentName, TraceEvent, TranscriptMessage } from "./api/types";

export interface ThreadMessage extends TranscriptMessage {
  key: string;
  trace?: TraceEvent[]; // only for replies produced in this session
}

export interface Draft {
  agent: AgentName;
  text: string;
}

interface State {
  messages: ThreadMessage[];
  loading: boolean;
  pending: { trace: TraceEvent[]; drafts: Draft[] } | null;
  lastTrace: TraceEvent[];
  activeAgent: AgentName | null;
  error: string | null;
}

type Action =
  | { type: "loaded"; messages: TranscriptMessage[]; activeAgent: AgentName | null }
  | { type: "reset" }
  | { type: "sent"; text: string }
  | { type: "token"; agent: AgentName; text: string }
  | { type: "trace"; event: TraceEvent }
  | { type: "reply"; message: TranscriptMessage; activeAgent: AgentName | null }
  | { type: "failed"; error: string }
  | { type: "finished" };

let seq = 0;
const key = () => `local-${++seq}`;

const initial: State = { messages: [], loading: false, pending: null, lastTrace: [], activeAgent: null, error: null };

function reducer(s: State, a: Action): State {
  switch (a.type) {
    case "reset":
      return { ...initial, loading: true };
    case "loaded":
      return {
        ...initial,
        messages: a.messages.map((m) => ({ ...m, key: m.id ?? key() })),
        activeAgent: a.activeAgent,
      };
    case "sent":
      return {
        ...s,
        error: null,
        messages: [...s.messages, { key: key(), id: null, role: "customer", agent: null, content: a.text, sources: [] }],
        pending: { trace: [], drafts: [] },
      };
    case "token": {
      if (!s.pending) return s;
      const drafts = [...s.pending.drafts];
      const last = drafts.at(-1);
      if (last && last.agent === a.agent) drafts[drafts.length - 1] = { ...last, text: last.text + a.text };
      else drafts.push({ agent: a.agent, text: a.text });
      return { ...s, pending: { ...s.pending, drafts } };
    }
    case "trace":
      return s.pending ? { ...s, pending: { ...s.pending, trace: [...s.pending.trace, a.event] } } : s;
    case "reply": {
      const trace = s.pending?.trace ?? [];
      return {
        ...s,
        messages: [...s.messages, { ...a.message, key: a.message.id ?? key(), trace }],
        pending: s.pending && { ...s.pending, drafts: [] },
        lastTrace: trace,
        activeAgent: a.activeAgent,
      };
    }
    case "failed":
      return { ...s, error: a.error };
    case "finished":
      return { ...s, pending: null };
  }
}

/** Conversation state: loads history, streams turns, and tracks the live trace. */
export function useChat(conversationId: string | null, initialAgent: AgentName | null, onTurnDone?: () => void) {
  const [state, dispatch] = useReducer(reducer, initial);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    abort.current?.abort();
    if (!conversationId) return;
    let cancelled = false;
    dispatch({ type: "reset" });
    api
      .transcript(conversationId)
      .then((messages) => !cancelled && dispatch({ type: "loaded", messages, activeAgent: initialAgent }))
      .catch((e: Error) => !cancelled && dispatch({ type: "failed", error: e.message }));
    return () => {
      cancelled = true;
    };
    // initialAgent only seeds the switchboard when a conversation is opened
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  const send = useCallback(
    async (text: string) => {
      if (!conversationId) return;
      const ctrl = new AbortController();
      abort.current = ctrl;
      dispatch({ type: "sent", text });
      try {
        for await (const ev of api.sendMessage(conversationId, text, ctrl.signal)) {
          if (ev.type === "token") dispatch({ type: "token", agent: ev.data.agent, text: ev.data.text });
          else if (ev.type === "trace") dispatch({ type: "trace", event: ev.data });
          else if (ev.type === "message")
            dispatch({ type: "reply", message: ev.data.message, activeAgent: ev.data.active_agent });
          else if (ev.type === "error") dispatch({ type: "failed", error: ev.data.message });
        }
      } catch (e) {
        if (!(e instanceof DOMException && e.name === "AbortError")) {
          dispatch({
            type: "failed",
            error: e instanceof ApiError ? e.message : "Couldn't reach Nimbus Help. Check your connection.",
          });
        }
      } finally {
        dispatch({ type: "finished" });
        onTurnDone?.();
      }
    },
    [conversationId, onTurnDone],
  );

  useEffect(() => () => abort.current?.abort(), []);
  return { ...state, send };
}
