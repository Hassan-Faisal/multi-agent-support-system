import Markdown from "react-markdown";
import { describe, lineColor, speakerName } from "../agents";
import type { Speaker, TraceEvent } from "../api/types";
import type { ThreadMessage } from "../useChat";

/**
 * The model cites help-center articles inline as [article-slug]. Sources are listed under
 * the reply instead, so the markers are removed: known slugs, plus anything shaped like a
 * slug (lowercase, hyphenated) in case the model cites an article it didn't retrieve.
 * Markdown links like [text](url) are left alone.
 */
export function stripCitations(text: string, slugs: string[]): string {
  const known = slugs.map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const pattern = [...known, "[a-z0-9]+(?:-[a-z0-9]+)+"].join("|");
  return text.replace(new RegExp(`\\s?\\[(?:${pattern})\\](?!\\()`, "g"), "");
}

function Body({ text }: { text: string }) {
  return (
    <div className="prose">
      <Markdown
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}

function HowHandled({ trace }: { trace: TraceEvent[] }) {
  const steps = trace.map(describe).filter((s): s is string => Boolean(s));
  if (!steps.length) return null;
  return (
    <details className="how">
      <summary>How this was handled</summary>
      <ol>
        {steps.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ol>
    </details>
  );
}

export function MessageView({ message }: { message: ThreadMessage }) {
  if (message.role === "customer") {
    return (
      <div className="msg msg-customer">
        <p>{message.content}</p>
      </div>
    );
  }
  return (
    <article className="msg msg-agent" style={{ "--c": lineColor(message.agent) } as React.CSSProperties}>
      <h3 className="speaker">{speakerName(message.agent)}</h3>
      <Body text={stripCitations(message.content, message.sources.map((s) => s.source))} />
      {message.sources.length > 0 && (
        <p className="sources">
          From the help center:{" "}
          {message.sources.map((s, i) => (
            <span key={s.source}>
              {i > 0 && ", "}
              <a href={s.url} target="_blank" rel="noreferrer noopener">
                {s.title}
              </a>
            </span>
          ))}
        </p>
      )}
      {message.trace && <HowHandled trace={message.trace} />}
    </article>
  );
}

export function DraftView({ agent, text }: { agent: Speaker; text: string }) {
  return (
    <article className="msg msg-agent msg-draft" style={{ "--c": lineColor(agent) } as React.CSSProperties}>
      <h3 className="speaker">{speakerName(agent)}</h3>
      <Body text={text} />
    </article>
  );
}
