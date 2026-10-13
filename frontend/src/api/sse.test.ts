import { describe, expect, it } from "vitest";
import { SSEParser, readSSE } from "./sse";

describe("SSEParser", () => {
  it("parses complete events with ids", () => {
    const p = new SSEParser();
    expect(p.push('id: 1\nevent: token\ndata: {"text":"Hi"}\n\n')).toEqual([
      { event: "token", data: '{"text":"Hi"}', id: "1" },
    ]);
  });

  it("buffers events split across chunks, including mid-line", () => {
    const p = new SSEParser();
    expect(p.push("event: tra")).toEqual([]);
    expect(p.push('ce\ndata: {"a"')).toEqual([]);
    expect(p.push(":1}\n\nevent: done\ndata: {}\n\n")).toEqual([
      { event: "trace", data: '{"a":1}', id: undefined },
      { event: "done", data: "{}", id: undefined },
    ]);
  });

  it("handles CRLF, comments and multi-line data", () => {
    const p = new SSEParser();
    expect(p.push(": ping\r\n\r\nevent: x\r\ndata: a\r\ndata: b\r\n\r\n")).toEqual([
      { event: "x", data: "a\nb", id: undefined },
    ]);
  });

  it("decodes multi-byte characters split between chunks", () => {
    const bytes = new TextEncoder().encode("data: café ☕\n\n");
    const p = new SSEParser();
    const split = bytes.indexOf(0xe2); // first byte of the 3-byte ☕
    expect(p.push(bytes.slice(0, split + 1))).toEqual([]);
    expect(p.push(bytes.slice(split + 1))).toEqual([{ event: "message", data: "café ☕", id: undefined }]);
  });
});

describe("readSSE", () => {
  it("yields events from a byte stream", async () => {
    const enc = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(enc.encode("event: a\ndata: 1\n\nevent: b\n"));
        c.enqueue(enc.encode("data: 2\n\n"));
        c.close();
      },
    });
    const events = [];
    for await (const e of readSSE(stream)) events.push(e.event + e.data);
    expect(events).toEqual(["a1", "b2"]);
  });
});
