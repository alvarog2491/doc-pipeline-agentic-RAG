interface ScrollViewport {
  readonly scrollHeight: number;
  readonly clientHeight: number;
  scrollTop: number;
}

interface AnimationScheduler {
  request(callback: FrameRequestCallback): number;
  cancel(frameId: number): void;
}

const browserScheduler: AnimationScheduler = {
  request: (callback) => requestAnimationFrame(callback),
  cancel: (frameId) => cancelAnimationFrame(frameId),
};

const EASING_FACTOR = 0.24;
const ARRIVAL_THRESHOLD_PX = 0.5;
const BOTTOM_THRESHOLD_PX = 24;

export class ConversationScrollFollower {
  private frameId: number | null = null;
  private autoFollow = true;
  private lastScrollTop: number | null = null;

  constructor(
    private readonly getViewport: () => ScrollViewport | null,
    private readonly scheduler: AnimationScheduler = browserScheduler,
    private readonly prefersReducedMotion: () => boolean = () => false,
  ) {}

  follow(): void {
    const viewport = this.getViewport();
    if (!viewport || !this.autoFollow) return;

    this.lastScrollTop = viewport.scrollTop;

    if (this.prefersReducedMotion()) {
      this.cancel();
      viewport.scrollTop = this.targetScrollTop(viewport);
      this.lastScrollTop = viewport.scrollTop;
      return;
    }

    if (this.frameId === null) {
      this.frameId = this.scheduler.request(this.advance);
    }
  }

  handleScroll(): void {
    const viewport = this.getViewport();
    if (!viewport) return;

    const scrolledUp =
      this.lastScrollTop !== null &&
      viewport.scrollTop < this.lastScrollTop - ARRIVAL_THRESHOLD_PX;
    this.lastScrollTop = viewport.scrollTop;

    if (scrolledUp) {
      this.autoFollow = false;
      this.cancel();
      return;
    }

    if (this.distanceFromBottom(viewport) <= BOTTOM_THRESHOLD_PX) {
      this.autoFollow = true;
    }
  }

  cancel(): void {
    if (this.frameId === null) return;
    this.scheduler.cancel(this.frameId);
    this.frameId = null;
  }

  private readonly advance: FrameRequestCallback = () => {
    const viewport = this.getViewport();
    if (!viewport) {
      this.frameId = null;
      return;
    }

    const target = this.targetScrollTop(viewport);
    const distance = target - viewport.scrollTop;
    if (Math.abs(distance) <= ARRIVAL_THRESHOLD_PX) {
      viewport.scrollTop = target;
      this.lastScrollTop = viewport.scrollTop;
      this.frameId = null;
      return;
    }

    viewport.scrollTop += distance * EASING_FACTOR;
    this.lastScrollTop = viewport.scrollTop;
    this.frameId = this.scheduler.request(this.advance);
  };

  private distanceFromBottom(viewport: ScrollViewport): number {
    return this.targetScrollTop(viewport) - viewport.scrollTop;
  }

  private targetScrollTop(viewport: ScrollViewport): number {
    return Math.max(0, viewport.scrollHeight - viewport.clientHeight);
  }
}
