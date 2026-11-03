import type { CrawlProgressState, PipelineLane } from '../types/site';

const number = (value: unknown) => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : 0;
function lane(value: unknown): PipelineLane {
  const row = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  return { discovered: number(row.discovered), completed: number(row.completed), active: number(row.active), queued: number(row.queued), failed: number(row.failed), skipped: number(row.skipped), bytes: number(row.bytes) };
}

/** Both hosts consume the same bounded pipeline progress protocol. */
export function applyPipelineProgress(state: CrawlProgressState, event: Record<string, unknown>): boolean {
  if (event.event !== 'pipeline_progress') return false;
  state.pipeline = {
    pages: lane(event.pages), media: lane(event.media), links: lane(event.links),
    elapsedSec: number(event.elapsedSec), stage: typeof event.stage === 'string' ? event.stage : 'crawl',
  };
  if (event.phase === 'crawl' || event.phase === 'compile') state.phase = event.phase;
  state.currentPage = state.pipeline.pages.completed;
  state.currentUrl = typeof event.currentUrl === 'string' ? event.currentUrl : '';
  if (typeof event.message === 'string') state.message = event.message;
  return true;
}
