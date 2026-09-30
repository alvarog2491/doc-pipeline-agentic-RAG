import { afterEach, describe, expect, it, vi } from "vitest";
import { SmoothTextBuffer } from "./smoothTextBuffer";

afterEach(() => {
  vi.useRealTimers();
});

describe("SmoothTextBuffer", () => {
  it("renders the first chunk immediately and smooths subsequent text in order", () => {
    vi.useFakeTimers();
    let rendered = "";
    const buffer = new SmoothTextBuffer({
      onText: (text) => {
        rendered += text;
      },
    });

    buffer.enqueue("H");
    expect(rendered).toBe("H");

    buffer.enqueue("ello");
    expect(rendered).toBe("H");
    vi.advanceTimersByTime(24);
    expect(rendered).toBe("He");
    vi.advanceTimersByTime(16);
    expect(rendered).toBe("Hel");

    vi.runAllTimers();
    expect(rendered).toBe("Hello");
  });

  it("keeps completion pending until every buffered character is visible", () => {
    vi.useFakeTimers();
    let rendered = "";
    const onDrained = vi.fn();
    const buffer = new SmoothTextBuffer({
      onText: (text) => {
        rendered += text;
      },
      onDrained,
    });

    const fullResponse = "A response that arrived in one large network chunk.";
    buffer.enqueue(fullResponse.slice(0, 1));
    buffer.enqueue(fullResponse.slice(1));
    buffer.complete();

    expect(rendered).toBe("A");
    expect(onDrained).not.toHaveBeenCalled();
    vi.advanceTimersByTime(24);
    expect(rendered.length).toBeGreaterThan(0);
    expect(rendered.length).toBeLessThan(fullResponse.length);
    expect(onDrained).not.toHaveBeenCalled();

    vi.runAllTimers();
    expect(rendered).toBe(fullResponse);
    expect(onDrained).toHaveBeenCalledOnce();
  });

  it("cancels queued text without retracting the first visible chunk", () => {
    vi.useFakeTimers();
    const onText = vi.fn();
    const onDrained = vi.fn();
    const buffer = new SmoothTextBuffer({ onText, onDrained });

    buffer.enqueue("Visible");
    buffer.enqueue(" pending text");
    buffer.complete();
    buffer.cancel();
    vi.runAllTimers();

    expect(onText).toHaveBeenCalledOnce();
    expect(onText).toHaveBeenCalledWith("Visible");
    expect(onDrained).not.toHaveBeenCalled();
  });

  it("renders the first chunk of each completed response immediately", () => {
    vi.useFakeTimers();
    let rendered = "";
    const buffer = new SmoothTextBuffer({
      onText: (text) => {
        rendered += text;
      },
    });

    buffer.enqueue("First");
    buffer.complete();
    buffer.enqueue("Second");

    expect(rendered).toBe("FirstSecond");
  });

  it("does not reveal a markdown link until its closing parenthesis arrives", () => {
    vi.useFakeTimers();
    let rendered = "";
    const buffer = new SmoothTextBuffer({
      onText: (text) => {
        rendered += text;
      },
    });

    buffer.enqueue("Read the manual [Page 4](https://example.com/manual.pdf#page=");
    expect(rendered).toBe("Read the manual ");

    buffer.enqueue("5)");
    vi.runAllTimers();

    expect(rendered).toBe(
      "Read the manual [Page 4](https://example.com/manual.pdf#page=5)",
    );
  });

  it("releases an unfinished markdown candidate when the response completes", () => {
    vi.useFakeTimers();
    let rendered = "";
    const buffer = new SmoothTextBuffer({
      onText: (text) => {
        rendered += text;
      },
    });

    buffer.enqueue("Use array[index]");
    expect(rendered).toBe("Use array");

    buffer.complete();

    expect(rendered).toBe("Use array[index]");
  });
});
