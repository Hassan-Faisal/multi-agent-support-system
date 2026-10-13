/**
 * Minimal Server-Sent Events parser for fetch() streams.
 *
 * EventSource can't send POST bodies or Authorization headers, so the chat stream is
 * read from a fetch ReadableStream instead. The parser is incremental: chunks may
 * split anywhere, including inside a UTF-8 character or between "\r" and "\n".
 */
export interface SSEMessage {
  event: string;
  data: string;
  id?: string;
}

export class SSEParser {
  private buffer = "";
  private decoder = new TextDecoder();

  push(chunk: Uint8Array | string): SSEMessage[] {
    this.buffer += typeof chunk === "string" ? chunk : this.decoder.decode(chunk, { stream: true });
    this.buffer = this.buffer.replace(/\r\n?/g, "\n");
    const out: SSEMessage[] = [];
    let boundary: number;
    while ((boundary = this.buffer.indexOf("\n\n")) !== -1) {
      const block = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      const msg = parseBlock(block);
      if (msg) out.push(msg);
    }
    return out;
  }
}

function parseBlock(block: string): SSEMessage | null {
  let event = "message";
  let id: string | undefined;
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue; // comment / heartbeat
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
    else if (field === "id") id = value;
  }
  return data.length ? { event, data: data.join("\n"), id } : null;
}

export async function* readSSE(body: ReadableStream<Uint8Array>): AsyncGenerator<SSEMessage> {
  const parser = new SSEParser();
  const reader = body.getReader();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      yield* parser.push(value);
    }
  } finally {
    reader.releaseLock();
  }
}
