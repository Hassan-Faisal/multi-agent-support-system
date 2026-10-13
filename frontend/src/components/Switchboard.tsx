import { LINES, lineColor, type Line } from "../agents";

const X = (i: number) => (i + 0.5) * (100 / LINES.length);
const LAMP_Y = 34;

interface Props {
  path: Line[];
  live: boolean;
}

/**
 * The routing strip above the thread. Each specialist is a line on the board; the
 * last turn's route is drawn as patch cords between them, and the line currently
 * handling the conversation is lit.
 */
export function Switchboard({ path, live }: Props) {
  const index = (l: Line) => LINES.findIndex((x) => x.id === l);
  const current = path.at(-1);
  const cords = path.slice(1).map((to, i) => {
    const a = index(path[i]!);
    const b = index(to);
    const lift = 10 + Math.abs(b - a) * 6;
    const mid = (X(a) + X(b)) / 2;
    return { key: `${i}-${to}`, d: `M ${X(a)} ${LAMP_Y} Q ${mid} ${LAMP_Y - lift} ${X(b)} ${LAMP_Y}`, to };
  });

  const summary = path.length
    ? `Route for the latest reply: ${path.map((l) => LINES.find((x) => x.id === l)?.name).join(", then ")}.`
    : "No reply yet.";

  return (
    <section className="switchboard" aria-label="Who is handling your conversation">
      <svg className="switchboard-cords" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">
        {cords.map((c, i) => (
          <path
            key={c.key}
            d={c.d}
            stroke={lineColor(c.to)}
            className={live && i === cords.length - 1 ? "cord cord-live" : "cord"}
            pathLength={1}
          />
        ))}
      </svg>
      <ol className="switchboard-lines">
        {LINES.map((line) => {
          const onPath = path.includes(line.id);
          const isCurrent = line.id === current;
          return (
            <li
              key={line.id}
              className="line"
              data-state={isCurrent ? "current" : onPath ? "visited" : "idle"}
              style={{ "--c": lineColor(line.id) } as React.CSSProperties}
              aria-current={isCurrent ? "true" : undefined}
            >
              <span className={isCurrent && live ? "lamp lamp-live" : "lamp"} />
              <span className="line-name">{line.name}</span>
              <span className="line-handles">{line.handles}</span>
            </li>
          );
        })}
      </ol>
      <p className="visually-hidden" aria-live="polite">
        {summary}
      </p>
    </section>
  );
}
