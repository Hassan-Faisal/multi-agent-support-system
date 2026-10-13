import { describe, expect, it } from "vitest";
import { describe as describeStep, pathOf } from "./agents";
import type { TraceEvent } from "./api/types";
import { stripCitations } from "./components/Message";

describe("pathOf", () => {
  it("starts at the front desk and follows handoffs", () => {
    const events: TraceEvent[] = [
      { type: "route", agent: "orders", reason: "tracking" },
      { type: "tool", agent: "orders", tool: "list_orders", args: {}, outcome: "ok", ms: 3 },
      { type: "handoff", source: "orders", target: "billing", reason: "charged twice" },
    ];
    expect(pathOf(events, null)).toEqual(["desk", "orders", "billing"]);
  });

  it("uses the sticky agent when triage was skipped", () => {
    expect(pathOf([], "technical")).toEqual(["technical"]);
  });

  it("shows the front desk when it redirects an off-topic message", () => {
    expect(pathOf([{ type: "guardrail", kind: "off_topic" }], "escalation")).toEqual(["desk"]);
  });

  it("adds the human team when a guardrail escalates", () => {
    const events: TraceEvent[] = [
      { type: "route", agent: "billing", reason: "x" },
      { type: "guardrail", kind: "tool_step_limit" },
    ];
    expect(pathOf(events, null)).toEqual(["desk", "billing", "escalation"]);
  });
});

describe("describe", () => {
  it("explains policy rejections in plain words", () => {
    expect(
      describeStep({
        type: "tool",
        agent: "billing",
        tool: "request_refund",
        args: { invoice_id: "INV-1" },
        outcome: "rejected",
        ms: 1,
      }),
    ).toBe("Requested a refund on INV-1. Not allowed by policy.");
  });
});

describe("stripCitations", () => {
  it("removes known source markers but keeps markdown links and other brackets", () => {
    const text = "Refunds take 5-7 days [refund-policy]. See [the guide](https://x) and [note].";
    expect(stripCitations(text, ["refund-policy"])).toBe("Refunds take 5-7 days. See [the guide](https://x) and [note].");
  });

  it("also removes slug-shaped citations to articles that weren't retrieved", () => {
    expect(stripCitations("Restart sync [sync-issues].", [])).toBe("Restart sync.");
  });
});
