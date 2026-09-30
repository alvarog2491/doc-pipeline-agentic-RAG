/** One decoded Server-Sent Event. */
export interface SseMessage {
  event: string;
  data: string;
  id: string | null;
}

/**
 * Incremental Server-Sent Events parser.
 *
 * Network chunks can split an event anywhere, so callers feed decoded text as it arrives and
 * receive every event completed by that chunk. Comment lines (keep-alives) are ignored.
 */
export class SseParser {
  private buffer = "";
  private event = "message";
  private data: string[] = [];
  private id: string | null = null;

  /** Feeds a decoded text chunk and returns the events it completed. */
  push(chunk: string): SseMessage[] {
    this.buffer += chunk;
    const messages: SseMessage[] = [];
    let newline: number;
    while ((newline = this.nextLineBreak()) !== -1) {
      const raw = this.buffer.slice(0, newline);
      const skip = this.buffer.startsWith("\r\n", newline) ? 2 : 1;
      this.buffer = this.buffer.slice(newline + skip);
      const message = this.consume(raw);
      if (message) messages.push(message);
    }
    return messages;
  }

  private nextLineBreak(): number {
    const lf = this.buffer.indexOf("\n");
    const cr = this.buffer.indexOf("\r");
    if (cr !== -1 && (lf === -1 || cr < lf)) {
      // A trailing "\r" might be the first half of "\r\n": wait for the next chunk.
      return cr === this.buffer.length - 1 ? -1 : cr;
    }
    return lf;
  }

  private consume(line: string): SseMessage | null {
    if (line === "") {
      if (this.data.length === 0) {
        this.event = "message";
        return null;
      }
      const message = { event: this.event, data: this.data.join("\n"), id: this.id };
      this.event = "message";
      this.data = [];
      return message;
    }
    if (line.startsWith(":")) return null;

    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") this.event = value;
    else if (field === "data") this.data.push(value);
    else if (field === "id") this.id = value;
    return null;
  }
}
