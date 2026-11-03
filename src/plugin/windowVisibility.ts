/**
 * Pauses the Three.js WebGL loop when the Obsidian tab or window is hidden/occluded.
 */
export class WindowVisibilityBinding {
  private generation = 0;
  private observer: IntersectionObserver | null = null;
  private doc: Document | null = null;
  private onVisibilityChange: (() => void) | null = null;
  private disposed = false;

  constructor(
    private target: Element,
    private onPausedChange: (paused: boolean) => void
  ) {}

  bind(win: Window, doc: Document): void {
    if (this.disposed) return;
    this.generation += 1;
    this.releaseCurrent();
    const currentGen = this.generation;
    let visible = true;

    const isCurrent = () => !this.disposed && this.generation === currentGen;
    const sync = () => {
      if (!isCurrent()) return;
      this.onPausedChange(doc.hidden || !visible);
    };

    const handleVis = () => sync();
    this.doc = doc;
    this.onVisibilityChange = handleVis;
    doc.addEventListener('visibilitychange', handleVis);

    const ObserverCtor = (
      win as Window & { IntersectionObserver?: typeof IntersectionObserver }
    ).IntersectionObserver;

    if (ObserverCtor) {
      const obs = new ObserverCtor((entries) => {
        if (!isCurrent() || this.observer !== obs) return;
        visible = entries[0]?.isIntersecting ?? true;
        sync();
      });
      this.observer = obs;
      obs.observe(this.target);
    }

    sync();
  }

  private releaseCurrent(): void {
    this.observer?.disconnect();
    this.observer = null;
    if (this.doc && this.onVisibilityChange) {
      this.doc.removeEventListener('visibilitychange', this.onVisibilityChange);
    }
    this.doc = null;
    this.onVisibilityChange = null;
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.generation += 1;
    this.releaseCurrent();
  }
}
