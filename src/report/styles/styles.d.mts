// Types for the plain-JavaScript styles module (an exact copy of the report app's apps/viewer/brand/styles.mjs; see src/report/styles/README.md).
export const STYLES_MAX_CHARS: number;
export const BUNDLED_FONTS: Record<string, Array<{ file: string; weight: string }>>;
export function suggestCardText(surface: string): { color: string; ratio: number; ok: boolean; tone: 'light' | 'dark' } | null;
export function readabilityProblems(styles: Record<string, string> | null | undefined): Array<{ slot: string; what: string; ratio: number; min: number; message: string }>;
export function validateStyles(raw: unknown): { ok: boolean; errors: string[]; codes: string[]; styles: Record<string, string> | null };
export function deriveStyleOutput(styles: Record<string, string> | null | undefined): {
  vars: Record<string, string>; notes: string[]; fonts: string[]; titleText: string | null;
  checks: Array<{ what: string; fg: string; bg: string; ratio: number; min: number; ok: boolean }>;
  page: Record<string, string | number>;
};
