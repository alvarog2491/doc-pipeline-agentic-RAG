const INITIAL_BUFFER_MS = 24;
const REVEAL_INTERVAL_MS = 16;

interface SmoothTextBufferOptions {
  onText: (text: string) => void;
  onDrained?: () => void;
}

export class SmoothTextBuffer {
  private queuedText = "";
  private pendingMarkdown = "";
  private timer: ReturnType<typeof setTimeout> | undefined;
  private completionRequested = false;
  private firstChunkRendered = false;

  constructor(private readonly options: SmoothTextBufferOptions) {}

  enqueue(text: string): void {
    if (!text) return;

    if (!this.firstChunkRendered) {
      this.firstChunkRendered = true;
      this.emitSafeText(text);
      return;
    }

    this.queuedText += text;
    if (!this.timer) {
      this.schedule(INITIAL_BUFFER_MS);
    }
  }

  complete(): void {
    this.completionRequested = true;
    if (!this.queuedText && !this.timer) {
      this.flushPendingMarkdown();
      this.notifyDrained();
    }
  }

  cancel(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined;
    this.queuedText = "";
    this.pendingMarkdown = "";
    this.completionRequested = false;
    this.firstChunkRendered = false;
  }

  private schedule(delayMs: number): void {
    this.timer = setTimeout(() => this.revealNext(), delayMs);
  }

  private revealNext(): void {
    this.timer = undefined;
    const chunkSize = this.nextChunkSize();
    const chunk = this.queuedText.slice(0, chunkSize);
    this.queuedText = this.queuedText.slice(chunkSize);
    this.emitSafeText(chunk);

    if (this.queuedText) {
      this.schedule(REVEAL_INTERVAL_MS);
    } else if (this.completionRequested) {
      this.flushPendingMarkdown();
      this.notifyDrained();
    }
  }

  private emitSafeText(text: string): void {
    const candidate = this.pendingMarkdown + text;
    const pendingIndex = findIncompleteMarkdownLink(candidate);

    if (pendingIndex === -1) {
      this.pendingMarkdown = "";
      this.options.onText(candidate);
      return;
    }

    this.pendingMarkdown = candidate.slice(pendingIndex);
    const safeText = candidate.slice(0, pendingIndex);
    if (safeText) this.options.onText(safeText);
  }

  private flushPendingMarkdown(): void {
    if (!this.pendingMarkdown) return;

    this.options.onText(this.pendingMarkdown);
    this.pendingMarkdown = "";
  }

  private nextChunkSize(): number {
    if (this.queuedText.length >= 160) return 6;
    if (this.queuedText.length >= 80) return 4;
    if (this.queuedText.length >= 32) return 2;
    return 1;
  }

  private notifyDrained(): void {
    this.completionRequested = false;
    this.firstChunkRendered = false;
    this.options.onDrained?.();
  }
}

function findIncompleteMarkdownLink(text: string): number {
  for (let openingBracket = 0; openingBracket < text.length; openingBracket++) {
    if (text[openingBracket] !== "[" || text[openingBracket - 1] === "\\") {
      continue;
    }

    const closingBracket = text.indexOf("]", openingBracket + 1);
    if (closingBracket === -1 || closingBracket === text.length - 1) {
      return openingBracket;
    }

    if (text[closingBracket + 1] !== "(") {
      openingBracket = closingBracket;
      continue;
    }

    let depth = 1;
    for (let index = closingBracket + 2; index < text.length; index++) {
      if (text[index - 1] === "\\") continue;
      if (text[index] === "(") depth++;
      if (text[index] === ")") depth--;
      if (depth === 0) {
        openingBracket = index;
        break;
      }
    }

    if (depth > 0) return openingBracket;
  }

  return -1;
}
