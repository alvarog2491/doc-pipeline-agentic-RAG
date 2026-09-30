import { describe, expect, it, vi } from "vitest";
import { ConversationScrollFollower } from "./conversationScroll";

describe("ConversationScrollFollower", () => {
  it("eases toward the bottom over successive animation frames", () => {
    const viewport = { scrollHeight: 200, clientHeight: 100, scrollTop: 0 };
    const frames: FrameRequestCallback[] = [];
    const follower = new ConversationScrollFollower(() => viewport, {
      request: (callback) => frames.push(callback),
      cancel: vi.fn(),
    });

    follower.follow();
    frames.shift()?.(0);

    expect(viewport.scrollTop).toBeGreaterThan(0);
    expect(viewport.scrollTop).toBeLessThan(100);

    while (frames.length > 0) frames.shift()?.(0);
    expect(viewport.scrollTop).toBe(100);
  });

  it("keeps one animation running while the streaming target changes", () => {
    const viewport = { scrollHeight: 200, clientHeight: 100, scrollTop: 0 };
    const request = vi.fn<(callback: FrameRequestCallback) => number>();
    request.mockReturnValue(1);
    const follower = new ConversationScrollFollower(() => viewport, {
      request,
      cancel: vi.fn(),
    });

    follower.follow();
    follower.follow();

    expect(request).toHaveBeenCalledOnce();
  });

  it("jumps directly when reduced motion is preferred", () => {
    const viewport = { scrollHeight: 200, clientHeight: 100, scrollTop: 0 };
    const request = vi.fn<(callback: FrameRequestCallback) => number>();
    const follower = new ConversationScrollFollower(
      () => viewport,
      { request, cancel: vi.fn() },
      () => true,
    );

    follower.follow();

    expect(viewport.scrollTop).toBe(100);
    expect(request).not.toHaveBeenCalled();
  });

  it("stops following when the user scrolls upward", () => {
    const viewport = { scrollHeight: 300, clientHeight: 100, scrollTop: 200 };
    const request = vi.fn<(callback: FrameRequestCallback) => number>(() => 1);
    const cancel = vi.fn();
    const follower = new ConversationScrollFollower(
      () => viewport,
      { request, cancel },
    );

    follower.follow();
    viewport.scrollTop = 80;
    follower.handleScroll();
    follower.follow();

    expect(cancel).toHaveBeenCalledWith(1);
    expect(request).toHaveBeenCalledOnce();
  });

  it("resumes following after the user returns to the bottom", () => {
    const viewport = { scrollHeight: 300, clientHeight: 100, scrollTop: 200 };
    const request = vi.fn<(callback: FrameRequestCallback) => number>(() => 1);
    const follower = new ConversationScrollFollower(
      () => viewport,
      { request, cancel: vi.fn() },
    );

    follower.follow();
    viewport.scrollTop = 80;
    follower.handleScroll();
    viewport.scrollTop = 200;
    follower.handleScroll();
    follower.follow();

    expect(request).toHaveBeenCalledTimes(2);
  });
});
