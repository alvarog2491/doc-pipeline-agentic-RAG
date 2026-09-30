import { describe, expect, it, vi } from "vitest";
import { restoreChatInputFocus } from "./ChatInput";

describe("restoreChatInputFocus", () => {
  it("restores pending focus when the input becomes available", () => {
    const focus = vi.fn();

    const stillPending = restoreChatInputFocus({ focus }, true, false);

    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    expect(stillPending).toBe(false);
  });

  it("keeps focus pending while the input is disabled", () => {
    const focus = vi.fn();

    const stillPending = restoreChatInputFocus({ focus }, true, true);

    expect(focus).not.toHaveBeenCalled();
    expect(stillPending).toBe(true);
  });

  it("does not move focus when no return was requested", () => {
    const focus = vi.fn();

    const stillPending = restoreChatInputFocus({ focus }, false, false);

    expect(focus).not.toHaveBeenCalled();
    expect(stillPending).toBe(false);
  });
});
