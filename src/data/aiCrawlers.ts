/**
 * AI crawler access from robots.txt. When robots.txt could not be read, every bot is "unknown":
 * that is no data, never a count such as "0 of 16" or "blocked: none".
 */
export function botsUnknown(policy: Record<string, string> | undefined | null): boolean {
  const states = Object.values(policy ?? {});
  return states.length > 0 && states.every((status) => String(status).startsWith('unknown'));
}

export interface AiCrawlerSummary {
  aiBotsPolicy: Record<string, string>;
  allowedAiBotsCount?: number;
  blockedAiBots?: string[];
}

/** The rows the site drawer shows: allowed count and blocked list, or one "No data" row. */
export function aiCrawlerRows(ai: AiCrawlerSummary): { label: string; value: string }[] {
  if (botsUnknown(ai.aiBotsPolicy)) return [{ label: 'AI bots allowed at /', value: 'No data (robots.txt could not be read)' }];
  const blocked = ai.blockedAiBots ?? [];
  return [
    { label: 'AI bots allowed at /', value: `${ai.allowedAiBotsCount ?? 0} of ${Object.keys(ai.aiBotsPolicy).length}` },
    { label: 'Blocked in robots.txt', value: blocked.length ? blocked.join(', ') : 'None' },
  ];
}
