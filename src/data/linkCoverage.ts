import type { ExternalLinkHealth } from '../types/site';

/** Older HEAD-only missing responses need GET confirmation before being conclusive. */
export function pendingLinkChecks(health: ExternalLinkHealth | undefined): number {
  return health ? health.uncheckedCount + health.results.filter(row => row.status === 'broken' && row.method === 'HEAD').length : 0;
}
