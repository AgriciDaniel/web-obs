// Walkthrough core: types, manifest bindings, validation. Pure (no DOM, no node APIs) so the hosted app,
// the exported client file and the node test-suite all run the exact same rules.
import type { EngineFinding, EngineFindingTarget, SiteGraphManifest } from '../types/site';
import { isHttpUrl } from './contractValues';

export type Label = 'RAW' | 'FETCH' | 'LAB' | 'INFER' | 'SCOPE';
export type Disposition = 'confirmed' | 'needs-verification' | 'likely-false-positive' | 'context-only';
export type Level = 'high' | 'medium' | 'low';
export type Size = 'S' | 'M' | 'L';
export type Owner = 'developer' | 'content' | 'marketing' | 'hosting';
export type Horizon = 'week-1' | 'month-1' | 'quarter';
export type SceneType = 'cover' | 'glance' | 'map-tour' | 'issue' | 'since-last-capture' | 'inventory' | 'roadmap' | 'limits' | 'next-steps';

/** Colours the client viewer will take from the report. Hex only (#rrggbb); anything else is rejected by the checker. */
export interface ThemeTokens { bg?: string; ink?: string; muted?: string }
export interface ClientTheme { accent?: string; /** Colour for the expandable explanations. */ secondary?: string; dark?: ThemeTokens; light?: ThemeTokens }
export const THEME_HEX = /^#[0-9a-f]{6}$/i;

export interface Ref { finding?: string; url?: string; path?: string; equals?: unknown; exists?: boolean }
export interface Claim { text: string; label: Label; refs?: Ref[]; basis?: string }
export interface Rated<T> { level?: T; size?: T; basis: string }
export interface Issue {
  id: string;
  title: string;
  scope: 'sitewide' | 'sitewide-template' | 'section' | 'page-specific';
  disposition: Disposition;
  dispositionNote?: string;
  findings: string[];
  severity: { level: Level; basis: string };
  effort: { size: Size; basis: string };
  owner: Owner;
  whatWeSaw: Claim[];
  whyItMatters: Claim[];
  caveat?: string;
  fix: string[];
  verify: string;
  /** Finding whose first targets are shown as examples. */
  exampleFinding?: string;
  evidenceShots?: Array<{ nodeId: string; kind: 'snapshot' }>;
  talk?: string[];
  hidden?: boolean;
}
export interface Stop { view: 'globe' | 'road' | 'clusters'; focus: { health?: string; filter?: string; section?: string; nodeIds?: string[] }; caption: Claim; talk?: string[] }
export interface Tile { label: string; value: string; note?: string }
export interface Scene {
  id: string;
  type: SceneType;
  title?: string;
  subtitle?: string;
  talk?: string[];
  hidden?: boolean;
  audience?: 'client' | 'presenter';
  when?: { path: string; gt?: number; equals?: unknown };
  issueId?: string;
  stops?: Stop[];
  tiles?: Tile[];
  claims?: Claim[];
  items?: Array<{ issueId: string; horizon: Horizon }>;
  groupBy?: 'category';
}
export interface Walkthrough {
  walkthroughVersion: '0.2';
  source: { siteId: string; capturedAt: string; manifestSha256: string };
  authoring: { generatedBy: string; skills?: string[]; reviewState: 'draft' | 'reviewed' | 'approved'; reviewedBy: string | null };
  brand: { name: string; accent: { hex: string | null; approvedBy: string | null }; /** Optional colour overrides for the client viewer, to match an agency's branding. Unset = the built-in scheme. */ theme?: ClientTheme; presenter?: string; preparedFor?: string; /** Where the client's feedback email is addressed. Set by the agency; never assumed. */ feedbackEmail?: string };
  issues: Issue[];
  scenes: Scene[];
  /** The agency's choice of which issues lead the guided tour (up to 5). Absent = the top 5 by rank. */
  tour?: { picks: string[] };
}

export const LABELS: Label[] = ['RAW', 'FETCH', 'LAB', 'INFER', 'SCOPE'];
export const LABEL_TEXT: Record<Label, string> = {
  RAW: 'Supplied', FETCH: 'Observed', LAB: 'Lab test', INFER: 'Our view', SCOPE: 'Scope',
};
export const HORIZONS: Array<{ id: Horizon; label: string }> = [
  { id: 'week-1', label: 'First week' }, { id: 'month-1', label: 'First month' }, { id: 'quarter', label: 'This quarter' },
];
export const OWNER_LABEL: Record<Owner, string> = { developer: 'Developer', content: 'Content team', marketing: 'Marketing', hosting: 'Hosting / IT' };
export const NODE_HEALTH = ['home', 'hub', 'healthy', 'orphan', 'unlisted', 'redirect', 'broken', 'unavailable', 'external'];
export const FOCUS_FILTERS = ['all', 'hubs', 'pages', 'orphans', 'issues', 'external'];

// ---------------------------------------------------------------------------
// Manifest access
// ---------------------------------------------------------------------------
type AnyObj = Record<string, unknown>;

export interface Ctx {
  m: SiteGraphManifest;
  F: Map<string, EngineFinding>;
}
export function makeCtx(m: SiteGraphManifest): Ctx {
  const F = new Map<string, EngineFinding>();
  for (const f of (m.audit?.findings ?? [])) F.set(f.id, f);
  return { m, F };
}
/**
 * The capture as a report reads it: every audit target is a full http(s) address. Captures made up to 0.3.2 can name a path on the site instead
 * (the crawl traps finding wrote "/calendar"), which a client report cannot carry. Such a path is read as that path on the captured site, and a
 * target that is neither an address nor a path is left out. Returns the same object when nothing needs changing; the capture is never modified.
 */
export function withAbsoluteTargets(m: SiteGraphManifest): SiteGraphManifest {
  const findings = m.audit?.findings;
  if (!m.audit || !findings) return m;
  const http = (u: unknown): boolean => isHttpUrl(u);
  const fix = (u: unknown): string | null => {
    if (typeof u !== 'string') return null;
    if (http(u)) return u;
    if (!u.startsWith('/') || u.startsWith('//')) return null;
    try { const full = new URL(u, http(m.origin) ? m.origin : `https://${m.domain}`).toString(); return http(full) ? full : null; } catch { return null; }
  };
  const loose = (t: EngineFindingTarget) => !http(t.url) || (t.sourceUrl !== undefined && !http(t.sourceUrl));
  if (!findings.some((f) => f.targets?.some(loose))) return m;
  const fixed = findings.map((f) => (f.targets?.some(loose) ? {
    ...f,
    targets: f.targets.flatMap((t) => {
      if (!loose(t)) return [t];
      const url = fix(t.url), source = fix(t.sourceUrl);
      if (!url) return [];
      const { sourceUrl: _old, ...rest } = t;
      void _old;
      return [{ ...rest, url, ...(source ? { sourceUrl: source } : {}) }];
    }),
  } : f));
  return { ...m, audit: { ...m.audit, findings: fixed } };
}
export const findingCount = (f: EngineFinding): number => (typeof f.targetCount === 'number' ? f.targetCount : f.targets?.length ?? 0);
export const countOf = (c: Ctx, id: string): number => { const f = c.F.get(id); return f ? findingCount(f) : 0; };

/** Resolve `a.b[*].c[0]` against the manifest. A path with `[*]` returns an array. */
export function resolvePath(obj: unknown, path: string): unknown {
  let cur: unknown[] = [obj];
  let multi = false;
  for (const part of path.match(/[^.[\]]+|\[\*\]|\[\d+\]/g) ?? []) {
    const next: unknown[] = [];
    for (const v of cur) {
      if (v == null) continue;
      if (part === '[*]') { multi = true; if (Array.isArray(v)) next.push(...(v as unknown[])); }
      else if (/^\[\d+\]$/.test(part)) next.push((v as unknown[])[Number(part.slice(1, -1))]);
      else next.push((v as AnyObj)[part]);
    }
    cur = next;
  }
  cur = cur.filter((v) => v !== undefined && v !== null);
  return multi ? cur : cur[0];
}

const fmtNum = (n: number) => (Math.abs(n) >= 1000 ? n.toLocaleString('en-US') : String(n));
function valueText(value: unknown): string {
  if (Array.isArray(value)) return (value as unknown[]).map(valueText).join(',');
  return value !== null && typeof value === 'object' ? '[object Object]' : String(value);
}
function applyOps(value: unknown, ops: string[]): string {
  let v: unknown = value;
  for (const op of ops) {
    if (op === 'len') v = Array.isArray(v) ? v.length : v == null ? 0 : valueText(v).length;
    else if (op === 'max') v = Math.max(...(v as unknown[]).filter((x): x is number => typeof x === 'number'));
    else if (op === 'min') v = Math.min(...(v as unknown[]).filter((x): x is number => typeof x === 'number'));
    else if (op === 'sum') v = (v as unknown[]).reduce<number>((a, x) => a + (typeof x === 'number' ? x : 0), 0);
    else if (op === 'join') v = (Array.isArray(v) ? v : [v]).join(', ');
    else if (op === 'sec1') v = (Number(v) / 1000).toFixed(1);
    else if (op === 'round2') v = String(Math.round(Number(v) * 100) / 100);
    else if (op === 'int') v = String(Math.round(Number(v)));
    else if (op.startsWith('pl=')) { const [one, many] = op.slice(3).split(','); const n = Number(v); v = `${fmtNum(n)} ${n === 1 ? one : many}`; }
    else if (op.startsWith('v=')) { const [one, many] = op.slice(2).split(','); v = Number(v) === 1 ? one : many; }
    else throw new Error(`unknown op "${op}"`);
  }
  return typeof v === 'number' ? fmtNum(v) : valueText(v);
}

export const BIND = /\{\{(m|f):([^}]+)\}\}/g;
const ALLOWED_NUMS = /\b(404|410|301|302|200|500|403)\b/g;
const PROMISE = /(?<!\bnot )(?<!\bno )\b(guarantee[sd]?|will (increase|improve|boost|rank|double|grow|skyrocket)|#\s?1\b|first page of google|\d+\s?x\b|top of google)\b/i;

export interface BindError { binding: string; message: string }
/** Replace every {{...}} binding with its manifest value. Failed bindings render as an em dash and are reported. */
export function renderText(s: string, c: Ctx, errors?: BindError[]): string {
  return (s ?? '').replace(BIND, (_all, kind: string, body: string) => {
    const fail = (message: string) => { errors?.push({ binding: `{{${kind}:${body}}}`, message }); return '\u2014'; };
    try {
      const [head, ...ops] = body.split('|');
      if (kind === 'f') {
        const [id, field] = head.split('#');
        const f = c.F.get(id);
        if (!f) return fail(`no finding "${id}"`);
        if (field !== 'count') return fail('only #count is supported');
        return applyOps(findingCount(f), ops);
      }
      const raw = resolvePath(c.m, head);
      if (raw === undefined || (Array.isArray(raw) && raw.length === 0 && !ops.includes('len'))) return fail(`no value at ${head}`);
      return applyOps(raw, ops);
    } catch (e) { return fail((e as Error).message); }
  });
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------
export interface Problem { where: string; message: string; level: 'error' | 'warn' }
export interface ValidateOptions { manifestSha?: string; mode?: 'draft' | 'client' }
export interface ValidateResult { errors: Problem[]; warnings: Problem[]; ok: boolean }

const DISP = new Set<string>(['confirmed', 'needs-verification', 'likely-false-positive', 'context-only']);
const LEVELS = new Set<string>(['high', 'medium', 'low']);
const SIZES = new Set<string>(['S', 'M', 'L']);
const OWNERS = new Set<string>(['developer', 'content', 'marketing', 'hosting']);
const SCENE_TYPES = new Set<string>(['cover', 'glance', 'map-tour', 'issue', 'since-last-capture', 'inventory', 'roadmap', 'limits', 'next-steps']);

export function validate(w: Walkthrough, m: SiteGraphManifest, opts: ValidateOptions = {}): ValidateResult {
  const errors: Problem[] = [], warnings: Problem[] = [];
  const E = (where: string, message: string) => errors.push({ where, message, level: 'error' });
  const W = (where: string, message: string) => warnings.push({ where, message, level: 'warn' });
  const c = makeCtx(m);
  const nodeIds = new Set(m.nodes.map((n) => n.id));
  const sections = new Set((m.sections ?? []).map((s) => s.id));

  if (opts.manifestSha && w.source?.manifestSha256 !== opts.manifestSha) E('source', 'manifestSha256 does not match this capture (the walkthrough is stale or belongs to another capture)');
  if (w.source?.capturedAt !== m.capturedAt) E('source', 'capturedAt differs from the capture');
  if (opts.mode === 'client') {
    if (w.authoring?.reviewState !== 'approved') E('authoring', `client export needs review state "approved" (it is "${w.authoring?.reviewState}")`);
    if (!w.brand?.accent?.approvedBy) W('brand', 'accent colour has not been approved by a person; the default is used');
  }

  const text = (where: string, s: unknown, client = true) => {
    if (typeof s !== 'string') return;
    const be: BindError[] = [];
    renderText(s, c, be);
    be.forEach((b) => E(where, `${b.binding} - ${b.message}`));
    if (client) {
      const bare = s.replace(BIND, '').replace(ALLOWED_NUMS, '').match(/\b\d[\d,.]*%?(?![\w])/g);
      if (bare) E(where, `bare number(s) ${JSON.stringify(bare)} in prose - every figure must be a binding`);
      const p = s.match(PROMISE);
      if (p) E(where, `forward-looking promise language: "${p[0]}"`);
    }
  };

  const claim = (where: string, cl: Claim) => {
    if (!LABELS.includes(cl.label)) E(where, `label "${cl.label}" is not one of ${LABELS.join(', ')}`);
    text(where, cl.text);
    if (cl.label === 'INFER' && !cl.basis) E(where, 'INFER claims need a "basis"');
    else if (cl.basis) text(`${where} basis`, cl.basis);
    if (cl.label !== 'INFER' && cl.label !== 'SCOPE' && !cl.refs?.length) E(where, `${cl.label} claim has no refs`);
    for (const r of cl.refs ?? []) {
      if (r.finding) {
        const f = c.F.get(r.finding);
        if (!f) { E(where, `ref finding "${r.finding}" does not exist`); continue; }
        if (r.url) {
          const hit = f.targets.some((x) => x.url === r.url || x.sourceUrl === r.url);
          if (!hit && f.targets.length >= findingCount(f)) E(where, `ref url ${r.url} is not a target of ${r.finding}`);
          else if (!hit) W(where, `ref url ${r.url} is not in the stored sample of ${r.finding}`);
        }
      } else if (r.path) {
        const v = resolvePath(m, r.path);
        const empty = v === undefined || (Array.isArray(v) && v.length === 0);
        if (empty) { if (r.exists !== false) E(where, `ref path ${r.path} has no value`); }
        else if ('equals' in r && v !== r.equals) E(where, `ref path ${r.path} is ${JSON.stringify(v)}, the claim says ${JSON.stringify(r.equals)}`);
      } else E(where, 'ref needs "finding" or "path"');
    }
  };

  const issues = new Map<string, Issue>();
  for (const i of w.issues ?? []) {
    const wh = `issue "${i.id}"`;
    if (issues.has(i.id)) E(wh, 'duplicate issue id');
    issues.set(i.id, i);
    if (!DISP.has(i.disposition)) E(wh, `bad disposition "${i.disposition}"`);
    if (i.disposition !== 'confirmed' && !i.dispositionNote) E(wh, 'a non-confirmed issue needs a dispositionNote');
    if (!LEVELS.has(i.severity?.level) || !i.severity?.basis) E(wh, 'severity needs level and basis');
    else text(`${wh} severity basis`, i.severity.basis);
    if (!SIZES.has(i.effort?.size) || !i.effort?.basis) E(wh, 'effort needs size and basis');
    else text(`${wh} effort basis`, i.effort.basis);
    if (!OWNERS.has(i.owner)) E(wh, `bad owner "${i.owner}"`);
    for (const id of i.findings ?? []) if (!c.F.has(id)) E(wh, `finding "${id}" does not exist in this capture`);
    if (!i.whatWeSaw?.length) E(wh, 'whatWeSaw is empty');
    i.whatWeSaw?.forEach((cl) => claim(`${wh} whatWeSaw`, cl));
    i.whyItMatters?.forEach((cl) => { if (cl.label !== 'INFER') E(`${wh} whyItMatters`, 'implications must be labelled INFER'); claim(`${wh} whyItMatters`, cl); });
    if (i.disposition === 'confirmed' && !i.whyItMatters?.length) W(wh, 'no whyItMatters');
    text(`${wh} title`, i.title);
    i.fix?.forEach((s) => text(`${wh} fix`, s));
    text(`${wh} verify`, i.verify);
    if (i.caveat) text(`${wh} caveat`, i.caveat);
    i.talk?.forEach((t) => text(`${wh} talk`, t, false));
    for (const s of i.evidenceShots ?? []) {
      const n = m.nodes.find((x) => x.id === s.nodeId);
      if (!n) E(wh, `evidence node "${s.nodeId}" not found`); else if (!n.snapshot) W(wh, `node "${s.nodeId}" has no snapshot`);
    }
  }

  const used = new Set<string>();
  for (const s of w.scenes ?? []) {
    const wh = `scene "${s.id}"`;
    if (!SCENE_TYPES.has(s.type)) { E(wh, `unknown scene type "${s.type}"`); continue; }
    if (s.title) text(`${wh} title`, s.title);
    if (s.subtitle) text(`${wh} subtitle`, s.subtitle);
    s.talk?.forEach((t) => text(`${wh} talk`, t, false));
    if (s.type === 'issue') {
      const i = s.issueId ? issues.get(s.issueId) : undefined;
      if (!i) { E(wh, `issue "${s.issueId}" is not defined`); continue; }
      used.add(i.id);
      if (!s.hidden && i.disposition !== 'confirmed' && (s.audience ?? 'client') === 'client') E(wh, `a client scene shows the "${i.disposition}" issue "${i.id}"`);
    } else if (s.type === 'map-tour') {
      for (const [k, st] of (s.stops ?? []).entries()) {
        const sw = `${wh} stop ${k + 1}`;
        if (!['globe', 'road', 'clusters'].includes(st.view)) E(sw, `bad view "${st.view}"`);
        const f = st.focus ?? {};
        if (f.health && !NODE_HEALTH.includes(f.health)) E(sw, `bad focus health "${f.health}"`);
        if (f.health && !m.nodes.some((n) => n.health === f.health)) E(sw, `focus health "${f.health}" matches no pages in this capture`);
        if (f.filter && !FOCUS_FILTERS.includes(f.filter)) E(sw, `bad focus filter "${f.filter}"`);
        if (f.section && !sections.has(f.section)) E(sw, `unknown section "${f.section}"`);
        f.nodeIds?.forEach((id) => { if (!nodeIds.has(id)) E(sw, `unknown node ${id}`); });
        claim(sw, st.caption);
      }
    } else if (s.type === 'roadmap') {
      for (const it of s.items ?? []) {
        if (!issues.has(it.issueId)) E(wh, `roadmap issue "${it.issueId}" is not defined`);
        if (!HORIZONS.some((h) => h.id === it.horizon)) E(wh, `bad horizon "${it.horizon}"`);
      }
    } else if (s.type === 'glance') {
      for (const t of s.tiles ?? []) { text(`${wh} tile "${t.label}"`, t.value); if (t.note) text(`${wh} tile note`, t.note); }
    } else if (s.claims) s.claims.forEach((cl) => claim(wh, cl));
  }
  // An active inventory scene lists every issue that has no scene of its own.
  if ((w.scenes ?? []).some((s) => s.type === 'inventory' && !s.hidden)) for (const id of issues.keys()) used.add(id);
  for (const id of issues.keys()) if (!used.has(id) && !issues.get(id)!.hidden) W(`issue "${id}"`, 'is defined but not shown in any scene');
  return { errors, warnings, ok: errors.length === 0 };
}

/** Whether a scene's condition holds for this capture. */
export function sceneActive(s: Scene, m: SiteGraphManifest): boolean {
  if (s.hidden) return false;
  if (!s.when) return true;
  const v = resolvePath(m, s.when.path);
  if (s.when.gt !== undefined) return typeof v === 'number' && v > s.when.gt;
  if (s.when.equals !== undefined) return v === s.when.equals;
  return Boolean(v);
}

export function horizonFor(i: Pick<Issue, 'severity' | 'effort'>): Horizon {
  const { level } = i.severity, { size } = i.effort;
  if (size === 'S') return level === 'low' ? 'month-1' : 'week-1';
  if (size === 'M') return level === 'high' ? 'month-1' : 'quarter';
  return 'quarter';
}

/**
 * The walkthrough as a client may see it: no presenter notes, no presenter-only scenes, no unverified findings.
 * Presenter material is removed from the data itself, not just hidden in the interface.
 */
export function stripForClient(w: Walkthrough): Walkthrough {
  const out = structuredClone(w);
  out.scenes = out.scenes.filter((s) => (s.audience ?? 'client') === 'client');
  for (const s of out.scenes) { delete s.talk; s.stops?.forEach((st) => { delete st.talk; }); }
  out.issues = out.issues.filter((i) => i.disposition === 'confirmed');
  for (const i of out.issues) { delete i.talk; delete i.dispositionNote; }
  const keep = new Set(out.issues.map((i) => i.id));
  out.scenes = out.scenes.filter((s) => s.type !== 'issue' || (s.issueId && keep.has(s.issueId)));
  for (const s of out.scenes) if (s.items) s.items = s.items.filter((it) => keep.has(it.issueId));
  return out;
}

/** Figures written directly into prose (anything that is not a binding or an HTTP status code). */
export function bareNumbers(s: string): string[] {
  return s.replace(BIND, '').replace(ALLOWED_NUMS, '').match(/\b\d[\d,.]*%?(?![\w])/g) ?? [];
}
/** Forward-looking promise language ("will improve", "guarantee", "#1"), or null. */
export function promiseLanguage(s: string): string | null {
  return s.match(PROMISE)?.[0] ?? null;
}
/**
 * The capture's own text that reads like a promise: a brand called "Guarantee Roofing", a page at /money-back-guarantee, a page title.
 * It is the site's wording, not a promise the report makes, so the check on the finished report sets these exact strings aside (longest first).
 */
export function capturedPromiseText(m: SiteGraphManifest): string[] {
  const found = new Set<string>();
  const walk = (v: unknown): void => {
    if (typeof v === 'string') { if (PROMISE.test(v)) found.add(v); }
    else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === 'object') Object.values(v).forEach(walk);
  };
  walk(m);
  return [...found].sort((a, b) => b.length - a.length);
}
/** Promise language in a string of the finished report, ignoring the captured strings from `capturedPromiseText`. */
export function promiseLanguageBeyond(s: string, captured: string[]): string | null {
  if (!promiseLanguage(s)) return null;
  let rest = s;
  for (const c of captured) rest = rest.split(c).join(' ');
  return promiseLanguage(rest);
}

// ---------------------------------------------------------------------------
// Ranking and affected pages (shared by the draft generator, the package and the explorer)
// ---------------------------------------------------------------------------
export const RANKING_BASIS = 'Ranked by priority level first, then by how many distinct pages are affected. A site-wide issue counts as every page.';

export const urlKey = (u: string) => { let x = u.split('#')[0]; while (x.endsWith('/')) x = x.slice(0, -1); return x; };

/** Distinct internal pages named by the targets of the given engine findings, nearest to the homepage first. */
export function nodesAffected(m: SiteGraphManifest, c: Ctx, findingIds: string[]): string[] {
  const byUrl = new Map(m.nodes.filter((n) => n.kind !== 'external-domain' && n.url).map((n) => [urlKey(n.url), n]));
  const hit = new Map<string, number>();
  for (const fid of findingIds) for (const t of ((c.F.get(fid)?.targets ?? []) as Array<{ url?: string }>)) {
    const n = t.url ? byUrl.get(urlKey(t.url)) : undefined;
    if (n) hit.set(n.id, typeof n.clickDepth === 'number' ? n.clickDepth : 99);
  }
  return [...hit.entries()].sort((a, b) => a[1] - b[1]).map(([id]) => id);
}
