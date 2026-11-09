// Client Report Package (webobs.client-report 1.1) and the agency-only Explore Pack (webobs.explore-pack 1.0).
//
// CLIENT REPORT: the JSON file a client-facing web app consumes.
//  1. Self-contained and resolved. Every {{binding}} is already rendered, so the consumer needs no engine,
//     no manifest and no network. Each claim keeps its `sources` so figures stay traceable.
//  2. Client data only. No presenter notes, no unverified findings, no vault paths, no raw crawl data.
//  3. One guided tour: the top five findings by priority, explained in plain language over the 3D globe,
//     ending with a feedback step the client can email back to the agency.
//
// EXPLORE PACK: the agency's own file for a meeting. Everything from the scrape (every engine finding, every page),
// the held-back findings and the private notes. It is never sent to a client; the client-report validator refuses it.
//
// Pure module (no DOM, no node APIs) so the studio, the CLI export and the tests share it.
import type { GlobeViewMode, SiteGraphManifest } from '../types/site';
import { AUDIT_CATEGORIES } from '../data/siteAudit';
import { attentionNodeIds } from '../data/mapAttention';
import {
  type Claim, type ClientTheme, THEME_HEX, type Ctx, type Horizon, type Issue, type Label, type Level, type Owner, type Ref, type Size, type Stop, type Walkthrough,
  HORIZONS, LABEL_TEXT, OWNER_LABEL, RANKING_BASIS, bareNumbers, makeCtx, nodesAffected, promiseLanguage, renderText, resolvePath, sceneActive, stripForClient, urlKey,
} from './core';
import { GLOSSARY, PLAIN, type GlossaryTerm } from './plain';
import { projectSite, unlistedSiteFields, reportValueProblems, REPORT_FIELDS } from './contract';

export const REPORT_FORMAT = 'webobs.client-report';
export const REPORT_VERSION = '1.1';
export const EXPLORE_FORMAT = 'webobs.explore-pack';
export const EXPLORE_VERSION = '1.0';

// ---------------------------------------------------------------------------
// Types (this is the contract; docs/CLIENT-REPORT-FORMAT.md explains it in prose)
// ---------------------------------------------------------------------------
export interface Source { finding?: string; path?: string; url?: string }
export interface RClaim {
  text: string; label: Label; labelText: string; basis?: string; sources: Source[];
  /** The pages this statement is about, so the viewer can bring them forward on the map. Absent when it is not about particular pages. */
  nodeIds?: string[];
}

export type Spotlight = { kind: 'pages'; nodeIds: string[]; pageCount: number; filter: 'all' | 'issues' | 'orphans' } | { kind: 'sitewide' };

export interface RFinding {
  id: string;
  title: string;
  scope: Issue['scope'];
  /** The engine's own groupings this topic draws from (Links, Content, Accessibility...). */
  categories: Array<{ id: string; label: string }>;
  severity: { level: Level; basis: string };
  effort: { size: Size; basis: string };
  owner: { id: Owner; label: string };
  horizon: Horizon;
  observed: RClaim[];
  implications: RClaim[];
  caveat?: string;
  fix: string[];
  verify: string;
  examples: Array<{ url: string; title?: string }>;
  evidence?: { image: string; caption: string };
  glossary: string[];
  /** Where the globe should look. Sitewide issues have no pages to point at, so the tour uses a panel instead. */
  spotlight: Spotlight;
}

export interface MapFocus { view: 'globe' | 'road' | 'clusters'; health?: string; filter?: string; section?: string; nodeIds?: string[] }

/** GUIDED: the recipient reads on their own; every step explains what it means and what is theirs to do. */
export interface Checkpoint { id: string; question: string; options: string[] }
export type GuidedStep =
  | { id: string; kind: 'welcome'; title: string; body: string[] }
  | { id: string; kind: 'orientation'; title: string; body: string[]; tiles: Array<{ label: string; value: string; note?: string; meaning: string }> }
  | { id: string; kind: 'map'; title: string; body: string[]; stops: Array<{ caption: RClaim; focus: MapFocus }> }
  | {
      id: string; kind: 'finding'; findingId: string; title: string; tier: 'top' | 'more'; rank?: number;
      /** Which view of the 3D map shows this finding best. Absent means the Globe. */
      view?: GlobeViewMode;
      beats: {
        found: RClaim[];
        meaning: { inPlain: string; picture?: string };
        ifIgnored?: { text: string; basis: string };
        yourPart: string;
        howFixed: string[];
        askYourTeam: string[];
      };
      terms: string[];
      checkpoint: Checkpoint;
    }
  | { id: string; kind: 'plan'; title: string; body: string[]; horizons: Array<{ id: Horizon; label: string; findingIds: string[] }> }
  | { id: string; kind: 'limits'; title: string; body: string[]; claims: RClaim[] }
  | { id: string; kind: 'decisions'; title: string; body: string[]; questions: Array<{ findingId: string; question: string }> }
  | { id: string; kind: 'send'; title: string; body: string[] };

export interface ClientReport {
  format: typeof REPORT_FORMAT;
  version: typeof REPORT_VERSION;
  meta: {
    reportId: string;
    createdAt: string;
    generator: string;
    source: { siteId: string; capturedAt: string; manifestSha256: string };
    review: { state: 'draft' | 'reviewed' | 'approved'; reviewedBy: string | null };
    integrity?: { algorithm: 'sha256'; contentSha256: string };
  };
  client: { name: string; domain: string; preparedFor?: string; presenter?: string; accent: string | null; logo?: string; theme?: ClientTheme };
  /** Where the client's feedback email goes. Set by the agency in the studio; absent = copy/download only. */
  feedback?: { to: string; subject: string };
  labels: Record<Label, string>;
  summary: { pagesMapped?: number; findingsCount: number; bySeverity: Record<Level, number> };
  findings: RFinding[];
  glossary: GlossaryTerm[];
  /** The site as the 3D globe draws it: the client's own pages only, already trimmed for sharing. */
  map?: { site: Record<string, unknown> };
  assets: Record<string, string>;
  modes: {
    guided: {
      estimatedMinutes: number;
      steps: GuidedStep[];
      /** Step ids the tour walks, in order. */
      tour: string[];
      /** Finding steps outside the top five, reachable from the end-of-tour list. */
      more: string[];
      top: { findingIds: string[]; picked: 'auto' | 'agency'; basis: string };
      responses: { schema: 'webobs.client-responses/1'; note: string };
    };
  };
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------
const CATEGORY_LABEL = new Map<string, string>(AUDIT_CATEGORIES.map((c) => [c.id, c.label]));

function sourceOf(r: Ref): Source { return { ...(r.finding ? { finding: r.finding } : {}), ...(r.path ? { path: r.path } : {}), ...(r.url ? { url: r.url } : {}) }; }

/** Pages a single statement is about: its audit findings' pages, else the homepage for site-level checks, else the sampled pages. */
export function claimNodes(cl: Claim, c: Ctx): string[] {
  const fids = (cl.refs ?? []).map((r) => r.finding).filter((x): x is string => Boolean(x));
  const ids = fids.length ? nodesAffected(c.m, c, fids) : [];
  if (ids.length) return ids;
  const paths = (cl.refs ?? []).map((r) => r.path ?? '');
  if (paths.some((p) => p.startsWith('siteIntel.techStack') || p.startsWith('siteIntel.transport'))) {
    const home = c.m.nodes.find((n) => n.kind === 'home');
    return home ? [home.id] : [];
  }
  if (paths.some((p) => p.startsWith('siteIntel.browserAudit'))) {
    const byUrl = new Map(c.m.nodes.filter((n) => n.kind !== 'external-domain' && n.url).map((n) => [urlKey(n.url), n.id]));
    const pages = (resolvePath(c.m, 'siteIntel.browserAudit.pages') ?? []) as Array<{ url?: string }>;
    return pages.map((p) => (p.url ? byUrl.get(urlKey(p.url)) : undefined)).filter((x): x is string => Boolean(x));
  }
  return [];
}

/**
 * The rule for choosing a view: findings about how pages relate to each other (duplicates, hidden pages, internal links) are shown in
 * Clusters, where related pages sit together; findings about how far pages are from the homepage are shown on the Road; everything
 * else is shown on the Globe. Each step also flies to its first affected page.
 */
const FINDING_VIEW: Record<string, GlobeViewMode> = {
  'duplicate-and-hidden-pages': 'clusters', 'internal-linking': 'clusters', 'indexing-signals': 'road',
};

export function renderClaim(cl: Claim, c: Ctx): RClaim {
  const nodeIds = claimNodes(cl, c);
  return {
    ...(nodeIds.length ? { nodeIds } : {}),
    text: renderText(cl.text, c), label: cl.label, labelText: LABEL_TEXT[cl.label],
    ...(cl.basis ? { basis: renderText(cl.basis, c) } : {}),
    sources: (cl.refs ?? []).map(sourceOf),
  };
}

/**
 * Which globe filter honestly matches a finding's pages. The unmodified globe can only dim by its own filters,
 * so one is chosen only when at least 80% of the pages fit it; otherwise everything stays lit.
 */
export function spotlightFilter(m: SiteGraphManifest, ids: string[], attention: Set<string> = attentionNodeIds(m)): 'all' | 'issues' | 'orphans' {
  if (!ids.length) return 'all';
  const health = new Map(m.nodes.map((n) => [n.id, n.health]));
  const share = (pred: (id: string) => boolean) => ids.filter(pred).length / ids.length;
  if (share((id) => health.get(id) === 'orphan' || health.get(id) === 'unlisted') >= 0.8) return 'orphans';
  if (share((id) => attention.has(id)) >= 0.8) return 'issues';
  return 'all';
}

export function spotlightFor(m: SiteGraphManifest, c: Ctx, i: Pick<Issue, 'scope' | 'findings'>, attention: Set<string>): Spotlight {
  if (i.scope === 'sitewide') return { kind: 'sitewide' };
  const ids = nodesAffected(m, c, i.findings);
  if (!ids.length) return { kind: 'sitewide' };
  return { kind: 'pages', nodeIds: ids.slice(0, 60), pageCount: ids.length, filter: spotlightFilter(m, ids, attention) };
}

const categoriesOf = (c: Ctx, ids: string[]) => {
  const out: Array<{ id: string; label: string }> = [];
  for (const id of ids) {
    const cat = c.F.get(id)?.category;
    if (cat && !out.some((x) => x.id === cat)) out.push({ id: cat, label: CATEGORY_LABEL.get(cat) ?? cat });
  }
  return out;
};

const stableId = (sha: string, at: string) => `wr-${sha.slice(0, 10)}-${at.replace(/\D/g, '').slice(0, 8)}`;
// Strict on purpose: the address is put straight into a mailto: link, so "?bcc=" or "," must not fit.
const EMAIL = /^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,24}$/;
export const isEmail = (s: string) => EMAIL.test(s);

// ---------------------------------------------------------------------------
// Build the client report
// ---------------------------------------------------------------------------
export interface BuildOptions {
  createdAt: string;
  generator?: string;
  includeMap?: boolean;
  /** Data URIs keyed "logo" or "snap:<nodeId>". */
  images?: Record<string, string>;
  /** Fallbacks for the feedback email (from .env). A per-report address in the walkthrough wins. */
  feedbackDefaults?: { to?: string; subject?: string };
}

export const DEFAULT_FEEDBACK_SUBJECT = 'Feedback on the {client} website review';

export function buildClientReport(wIn: Walkthrough, m: SiteGraphManifest, opts: BuildOptions): ClientReport {
  const w = stripForClient(wIn);
  const c = makeCtx(m);
  const R = (s: string) => renderText(s, c);
  const claim = (cl: Claim) => renderClaim(cl, c);
  const attention = attentionNodeIds(m);

  const roadmap = w.scenes.find((s) => s.type === 'roadmap' && sceneActive(s, m));
  const horizonOf = new Map<string, Horizon>((roadmap?.items ?? []).map((it) => [it.issueId, it.horizon]));
  const used = new Set<string>();

  const findings: RFinding[] = w.issues.filter((i) => !i.hidden).map((i) => {
    const glossary = (PLAIN[i.id]?.terms ?? []);
    glossary.forEach((t) => used.add(t));
    const ex = i.exampleFinding ? c.F.get(i.exampleFinding) : undefined;
    const examples = ((ex?.targets ?? []) as Array<{ url?: string; title?: string }>).filter((t) => t.url).slice(0, 5).map((t) => ({ url: t.url!, ...(t.title ? { title: t.title } : {}) }));
    const shot = i.evidenceShots?.[0];
    const node = shot ? m.nodes.find((n) => n.id === shot.nodeId) : undefined;
    return {
      id: i.id, title: R(i.title), scope: i.scope, categories: categoriesOf(c, i.findings),
      severity: { level: i.severity.level, basis: R(i.severity.basis) },
      effort: { size: i.effort.size, basis: R(i.effort.basis) },
      owner: { id: i.owner, label: OWNER_LABEL[i.owner] },
      horizon: horizonOf.get(i.id) ?? 'quarter',
      observed: i.whatWeSaw.map(claim), implications: i.whyItMatters.map(claim),
      ...(i.caveat ? { caveat: R(i.caveat) } : {}),
      fix: i.fix.map(R), verify: R(i.verify), examples,
      ...(shot && node ? { evidence: { image: `snap:${shot.nodeId}`, caption: `How ${node.title || node.path || 'the page'} looked when captured.` } } : {}),
      glossary, spotlight: spotlightFor(m, c, i, attention),
    };
  });
  const byId = new Map(findings.map((f) => [f.id, f]));

  // ---- guided tour --------------------------------------------------------
  const guided: GuidedStep[] = [];
  const name = w.brand.name;
  guided.push({
    id: 'welcome', kind: 'welcome', title: `Welcome, this is the review of ${name}'s website`,
    body: [
      'This walk-through explains what we found on your public website, what it means in everyday terms, and what is yours to decide.',
      'It is a snapshot taken on one date. It is not live monitoring, and it does not include rankings, traffic or sales.',
      'Each finding is marked so you can tell the difference between what we observed and what we think. "Observed" is something we saw. "Our view" is an opinion, and it comes with the reason behind it.',
      'We start with the five things we would fix first. At the end you can send us your thoughts.',
    ],
  });
  const glanceScene = w.scenes.find((s) => s.type === 'glance' && sceneActive(s, m));
  if (glanceScene) {
    const tiles = (glanceScene.tiles ?? []).map((t) => ({ label: t.label, value: R(t.value), ...(t.note ? { note: t.note } : {}), meaning: tileMeaning(t.label) }));
    guided.push({ id: 'orientation', kind: 'orientation', title: 'Your site in a few numbers', body: ['These numbers set the scene. None of them is a score or a verdict on its own.'], tiles });
  }
  const mapScene = w.scenes.find((s) => s.type === 'map-tour' && sceneActive(s, m));
  if (mapScene) guided.push({
    id: 'map', kind: 'map', title: 'Your website as a map',
    body: ['Each dot is a page and the lines are the links between them. Drag to look around; the highlights show what each caption is about.'],
    stops: (mapScene.stops ?? []).map((s: Stop) => ({ caption: claim(s.caption), focus: { view: s.view, ...s.focus } })),
  });

  const picks = (w.tour?.picks ?? []).filter((id) => byId.has(id)).slice(0, 5);
  // findings are already ordered by rank: priority level, then distinct pages affected
  const topIds = picks.length ? picks : findings.slice(0, 5).map((f) => f.id);
  const dec: Array<{ findingId: string; question: string }> = [];
  for (const fid of [...new Set([...topIds, ...findings.map((f) => f.id)])]) {
    const f = byId.get(fid)!;
    const p = PLAIN[f.id];
    guided.push({
      id: `g-${f.id}`, kind: 'finding', findingId: f.id, title: f.title, ...(FINDING_VIEW[f.id] ? { view: FINDING_VIEW[f.id] } : {}), tier: topIds.includes(f.id) ? 'top' : 'more', ...(topIds.includes(f.id) ? { rank: topIds.indexOf(f.id) + 1 } : {}),
      beats: {
        found: f.observed,
        meaning: { inPlain: p?.inPlain ?? f.implications[0]?.text ?? f.title, ...(p?.picture ? { picture: p.picture } : {}) },
        ...(p ? { ifIgnored: p.ifIgnored } : f.implications[0] ? { ifIgnored: { text: f.implications[0].text, basis: f.implications[0].basis ?? '' } } : {}),
        yourPart: p?.yourPart ?? 'Ask your agency to walk you through the options for this item.',
        howFixed: f.fix, askYourTeam: p?.askYourTeam ?? [],
      },
      terms: f.glossary,
      checkpoint: { id: `cp-${f.id}`, question: 'How does this land?', options: ['This is what I expected', 'This surprises me', 'I would like to discuss this'] },
    });
    for (const q of p?.askYourTeam ?? []) dec.push({ findingId: f.id, question: q });
  }
  if (roadmap) {
    const horizons = HORIZONS.map((h) => ({ id: h.id, label: h.label, findingIds: findings.filter((f) => f.horizon === h.id).map((f) => f.id) })).filter((h) => h.findingIds.length);
    guided.push({ id: 'plan', kind: 'plan', title: 'A sensible order of work', body: ['Quick, low-effort items come first. Each one has an owner, so nothing waits for someone who does not know it is theirs.'], horizons });
  }
  const limitsScene = w.scenes.find((s) => s.type === 'limits' && sceneActive(s, m));
  if (limitsScene) guided.push({ id: 'limits', kind: 'limits', title: 'What this review does not tell you', body: ['A fair reading includes the gaps. These are things this review did not measure.'], claims: (limitsScene.claims ?? []).map(claim) });
  guided.push({ id: 'decisions', kind: 'decisions', title: 'Questions to take to your team', body: ['You do not need to answer these now. They are the questions that will move the work forward.'], questions: dec });
  guided.push({ id: 'send', kind: 'send', title: 'Tell us what you think', body: ['Your answers and any notes below are only on this device until you choose to send them.', 'Check the summary, add anything you like, then send it to us by email.'] });

  const stepOf = (id: string) => guided.find((g) => g.id === id);
  const tour = [
    ...['welcome', 'orientation', 'map'].filter((id) => stepOf(id)),
    ...topIds.map((id) => 'g-' + id),
    ...['plan', 'limits', 'decisions', 'send'].filter((id) => stepOf(id)),
  ];
  const more = guided.filter((g) => g.kind === 'finding' && g.tier === 'more').map((g) => g.id);

  // ---- glossary / assets / map -------------------------------------------
  for (const g of guided) if (g.kind === 'finding') g.terms.forEach((t) => used.add(t));
  const glossary = GLOSSARY.filter((g) => used.has(g.id));
  const assets: Record<string, string> = {};
  for (const [k, v] of Object.entries(opts.images ?? {})) if (k === 'logo' || findings.some((f) => f.evidence?.image === k)) assets[k] = v;
  const bySeverity: Record<Level, number> = { high: 0, medium: 0, low: 0 };
  findings.forEach((f) => { bySeverity[f.severity.level]++; });
  const to = w.brand.feedbackEmail?.trim() || opts.feedbackDefaults?.to?.trim();
  const subject = (opts.feedbackDefaults?.subject?.trim() || DEFAULT_FEEDBACK_SUBJECT).split('{client}').join(name).replace(/[\r\n]+/g, ' ');

  return {
    format: REPORT_FORMAT, version: REPORT_VERSION,
    meta: {
      reportId: stableId(w.source.manifestSha256, w.source.capturedAt),
      createdAt: opts.createdAt, generator: opts.generator ?? 'Web-Obs Report Studio',
      source: w.source, review: { state: w.authoring.reviewState, reviewedBy: w.authoring.reviewedBy },
    },
    client: {
      name, domain: m.domain, accent: w.brand.theme?.accent ?? w.brand.accent.hex,
      ...(w.brand.theme ? { theme: w.brand.theme } : {}),
      ...(w.brand.preparedFor ? { preparedFor: w.brand.preparedFor } : {}), ...(w.brand.presenter ? { presenter: w.brand.presenter } : {}),
      ...(assets.logo ? { logo: 'logo' } : {}),
    },
    ...(to ? { feedback: { to, subject } } : {}),
    labels: { ...LABEL_TEXT },
    summary: { ...(typeof m.stats?.pagesCrawled === 'number' ? { pagesMapped: m.stats.pagesCrawled } : {}), findingsCount: findings.length, bySeverity },
    findings, glossary, ...(opts.includeMap === false ? {} : { map: { site: buildSite(m) } }), assets,
    modes: {
      guided: {
        estimatedMinutes: Math.max(5, tour.length), steps: guided, tour, more,
        top: { findingIds: topIds, picked: picks.length ? 'agency' : 'auto', basis: RANKING_BASIS },
        responses: { schema: 'webobs.client-responses/1', note: 'The viewer records the recipient\'s checkpoint answers and comments as { reportId, answers, comments } and lets them email it to the agency. This file never contains them.' },
      },
    },
  };
}

function tileMeaning(label: string): string {
  const l = label.toLowerCase();
  if (l.includes('pages mapped')) return 'How many pages of your site we could find and read.';
  if (l.includes('outside')) return 'Other websites your pages link to. Each is a place a visitor can leave to.';
  if (l.includes('nobody links')) return 'Pages that exist but have no link path from the rest of your site.';
  if (l.includes('response')) return 'How quickly your server typically answers a request, before the page starts to draw.';
  if (l.includes('flagged')) return 'Individual items our checks raised. Many are one cause repeated across pages, so this is not a count of separate problems.';
  if (l.includes('certificate')) return 'Days until your site\'s security certificate expires. If it lapses, visitors see a warning.';
  return 'A figure from the capture.';
}

/** The capture trimmed to what the globe draws. Refuses if trimming would change any text or highlight. */
function buildSite(m: SiteGraphManifest): Record<string, unknown> {
  // The report text is already written, so the map carries only the allowlisted fields (see contract.ts).
  const site = projectSite(m);
  if ([...attentionNodeIds(m)].sort().join() !== [...attentionNodeIds(site as unknown as SiteGraphManifest)].sort().join()) throw new Error('Trimming the capture for the client file changed the globe highlights');
  return site;
}

/** Add a content hash so a consumer can detect a file edited after export. `sha` is the caller's SHA-256 (hex). */
export async function sealReport(r: ClientReport, sha: (s: string) => Promise<string>): Promise<ClientReport> {
  const body = { ...r, meta: { ...r.meta, integrity: undefined } };
  return { ...r, meta: { ...r.meta, integrity: { algorithm: 'sha256', contentSha256: await sha(JSON.stringify(body)) } } };
}

// ---------------------------------------------------------------------------
// Feedback email (runs in the client's browser; opens their own mail app, sends nothing by itself)
// ---------------------------------------------------------------------------
export interface FeedbackInput { answers: Record<string, string>; comments: Record<string, string>; general?: string; name?: string; }
export interface Feedback { subject: string; body: string; mailto: string | null; truncated: boolean }
/** Many mail clients and browsers cut off a mailto: link well before 2,000 characters. */
export const MAILTO_LIMIT = 1900;

export function composeFeedback(r: ClientReport, f: FeedbackInput): Feedback {
  const subject = r.feedback?.subject ?? `Feedback on the ${r.client.name} website review`;
  const lines: string[] = [`Feedback on the ${r.client.name} website review (captured ${r.meta.source.capturedAt.slice(0, 10)}).`, ''];
  if (f.name?.trim()) lines.push(`From: ${f.name.trim()}`, '');
  const order = [...r.modes.guided.top.findingIds, ...r.modes.guided.more.map((id) => id.replace(/^g-/, ''))];
  let any = false;
  for (const id of order) {
    const fi = r.findings.find((x) => x.id === id);
    const a = f.answers[`cp-${id}`], cm = f.comments[id]?.trim();
    if (!fi || (!a && !cm)) continue;
    any = true;
    lines.push(`- ${fi.title}: ${a ?? 'no answer'}`);
    if (cm) lines.push(`  Note: ${cm}`);
  }
  if (!any) lines.push('(No answers recorded.)');
  if (f.general?.trim()) lines.push('', 'Anything else:', f.general.trim());
  lines.push('', `Report ${r.meta.reportId}`);
  const body = lines.join('\n');
  const to = r.feedback?.to;
  if (!to || !isEmail(to)) return { subject, body, mailto: null, truncated: false };
  const url = (b: string) => `mailto:${to}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(b)}`;
  if (url(body).length <= MAILTO_LIMIT) return { subject, body, mailto: url(body), truncated: false };
  const note = '\n[Shortened to fit an email link.]';
  let lo = 0, hi = body.length;
  while (lo < hi) { const mid = Math.ceil((lo + hi) / 2); if (url(body.slice(0, mid) + note).length <= MAILTO_LIMIT) lo = mid; else hi = mid - 1; }
  return { subject, body, mailto: url(body.slice(0, lo) + note), truncated: true };
}

// ---------------------------------------------------------------------------
// Validation of the client report: gates on the finished JSON itself, independent of how it was built.
// ---------------------------------------------------------------------------
export interface PackageProblem { where: string; message: string }

const FORBIDDEN_KEYS = new Set(['talk', 'notes', 'dispositionNote', 'presenterNotes', 'obsidianPath', 'rawPath', 'targetUrl', 'anchor', 'manifest', 'capture', 'stories']);
const LOCAL_PATH = /(^|[^A-Za-z0-9])[A-Za-z]:[/]{1,2}(Users|git)|[/]Users[/]|[.]obsidian/;

export function validateClientReport(r: ClientReport, ctx?: Ctx): PackageProblem[] {
  const P: PackageProblem[] = [];
  const E = (where: string, message: string) => P.push({ where, message });
  for (const [k, v] of Object.entries(r.client?.theme ?? {})) {
    const vals = typeof v === 'string' ? [[k, v]] : Object.entries((v ?? {}) as Record<string, string>).map(([t, x]) => [`${k}.${t}`, x]);
    for (const [name, val] of vals) if (!THEME_HEX.test(String(val))) E('client.theme.' + name, 'colours must be #rrggbb');
  }
  if ((r as { format?: string }).format === EXPLORE_FORMAT) { E('format', 'this is the agency-only explore pack, not a client report'); return P; }
  if (r.format !== REPORT_FORMAT) E('format', 'expected "webobs.client-report"');
  if (r.version !== REPORT_VERSION) E('version', `unsupported version "${String(r.version)}"`);
  if (r.meta?.review?.state !== 'approved') E('meta.review', `report is "${r.meta?.review?.state}", not approved`);
  if ('presentation' in (r.modes ?? {})) E('modes', 'presentation mode was removed in 1.1');
  // Allowlist: only the fields the contract names may be present (see contract.ts and docs/CLIENT-REPORT-FORMAT.md).
  for (const k of Object.keys(r)) if (!REPORT_FIELDS.some((field) => field === k)) E('$', `field "${k}" is not part of the client report contract`);
  for (const k of Object.keys(r.meta ?? {})) if (!['reportId', 'createdAt', 'generator', 'source', 'review', 'integrity'].includes(k)) E('meta', `field "${k}" is not part of the contract`);
  for (const k of Object.keys(r.meta?.source ?? {})) if (!['siteId', 'capturedAt', 'manifestSha256'].includes(k)) E('meta.source', `field "${k}" is not part of the contract`);
  for (const k of Object.keys(r.client ?? {})) if (!['name', 'domain', 'accent', 'preparedFor', 'presenter', 'logo', 'theme'].includes(k)) E('client', `field "${k}" is not part of the contract`);
  if (r.map?.site) for (const where of unlistedSiteFields(r.map.site)) E(where, 'not part of the contract (the map carries only allowlisted fields)');
  // Values and nested structure: types, lengths, http(s)-only addresses, image-only assets, unknown nested keys, total size.
  // The deeper checks below assume the right shapes, so a file with wrong ones stops here.
  const valueProblems = reportValueProblems(r);
  for (const p of valueProblems) E(p.where, p.message);
  if (valueProblems.length) return P;

  const walk = (v: unknown, path: string, fn: (s: string, p: string) => void) => {
    if (typeof v === 'string') fn(v, path);
    else if (Array.isArray(v)) v.forEach((x, i) => walk(x, `${path}[${i}]`, fn));
    else if (v && typeof v === 'object') for (const [k, x] of Object.entries(v)) {
      if (FORBIDDEN_KEYS.has(k)) E(path || '$', `forbidden key "${k}" (private or raw data must not ship in the client file)`);
      walk(x, path ? `${path}.${k}` : k, fn);
    }
  };
  const { assets: _a, map: _m, ...noAssets } = r;
  void _a; void _m;
  walk(noAssets, '', (s, p) => {
    if (/\{\{.*\}\}/.test(s)) E(p, 'unresolved {{binding}}');
    if (s === '\u2014') E(p, 'a binding failed and rendered as a dash');
    if (/[A-Za-z]:\\|\/Users\/|\.obsidian|_site-graph/.test(s)) E(p, 'looks like a local path');
    const pl = promiseLanguage(s);
    if (pl) E(p, `promise language "${pl}"`);
  });

  if (r.feedback) {
    if (!isEmail(r.feedback.to)) E('feedback.to', 'not a valid email address');
    if (/[\r\n]/.test(r.feedback.subject)) E('feedback.subject', 'subject must be a single line');
  }

  const siteNodes = new Set<string>();
  if (r.map) {
    const site = r.map.site as { nodes?: Array<Record<string, unknown>> };
    if (!Array.isArray(site?.nodes)) E('map', 'map.site has no nodes');
    for (const n of site?.nodes ?? []) {
      siteNodes.add(String(n.id));
      for (const k of ['obsidianPath', 'rawPath', 'pageChecks', 'simhash', 'keywords']) if (k in n) E('map', 'node carries private field "' + k + '"');
    }
    if ('captureProvenance' in (r.map.site as object)) E('map', 'captureProvenance must not ship');
    if (LOCAL_PATH.test(JSON.stringify(r.map.site))) E('map', 'map.site looks like it contains a local path');
  }

  const ids = new Set<string>();
  for (const f of r.findings ?? []) {
    ids.add(f.id);
    const wh = `findings.${f.id}`;
    if (!f.observed.length) E(wh, 'no observed claims');
    for (const cl of [...f.observed, ...f.implications]) {
      if (cl.label === 'INFER' && !cl.basis) E(wh, 'INFER claim without basis');
      if (cl.label !== 'INFER' && cl.label !== 'SCOPE' && !cl.sources.length) E(wh, `${cl.label} claim without sources`);
    }
    for (const cl of f.implications) if (cl.label !== 'INFER') E(wh, 'implication not labelled INFER');
    if (f.spotlight.kind === 'pages') {
      if (!f.spotlight.nodeIds.length) E(wh, 'spotlight has no pages');
      if (!['all', 'issues', 'orphans'].includes(f.spotlight.filter)) E(wh, 'bad spotlight filter');
      if (r.map) for (const id of f.spotlight.nodeIds) if (!siteNodes.has(id)) E(wh, 'spotlight page "' + id + '" is not in the map');
    }
    if (ctx) for (const cl of f.observed) for (const s of cl.sources) {
      if (s.finding && !ctx.F.has(s.finding)) E(wh, `source finding "${s.finding}" is not in the capture`);
    }
  }
  const glossary = new Set((r.glossary ?? []).map((g) => g.id));
  const refs = (list: string[], where: string) => list.forEach((id) => { if (!ids.has(id)) E(where, `unknown finding "${id}"`); });

  const g = r.modes?.guided;
  const gd = new Set<string>();
  if (g) {
    const stepIds = new Set<string>(), cps = new Set<string>();
    for (const s of g.steps) {
      if (stepIds.has(s.id)) E(`guided.${s.id}`, 'duplicate step id');
      stepIds.add(s.id);
      if (s.kind === 'finding') {
        refs([s.findingId], `guided.${s.id}`); gd.add(s.findingId);
        if (!s.beats.yourPart) E(`guided.${s.id}`, 'no "your part"');
        if (!s.beats.meaning.inPlain) E(`guided.${s.id}`, 'no plain-language meaning');
        if (s.beats.ifIgnored && !s.beats.ifIgnored.basis) E(`guided.${s.id}`, 'ifIgnored without basis');
        s.terms.forEach((t) => { if (!glossary.has(t)) E(`guided.${s.id}`, `glossary term "${t}" missing`); });
        if (cps.has(s.checkpoint.id)) E(`guided.${s.id}`, 'duplicate checkpoint id');
        cps.add(s.checkpoint.id);
        const prose = [s.beats.meaning.inPlain, s.beats.meaning.picture ?? '', s.beats.ifIgnored?.text ?? '', s.beats.yourPart, ...s.beats.askYourTeam];
        for (const t of prose) { const b = bareNumbers(t); if (b.length) E(`guided.${s.id}`, `hand-typed figure ${JSON.stringify(b)} in explanatory prose`); }
      }
      if (s.kind === 'plan') s.horizons.forEach((h) => refs(h.findingIds, `guided.${s.id}`));
      if (s.kind === 'decisions') s.questions.forEach((q) => refs([q.findingId], `guided.${s.id}`));
    }
    for (const id of [...g.tour, ...g.more]) if (!stepIds.has(id)) E('guided.tour', 'unknown step "' + id + '"');
    const tourFindings = g.tour.map((id) => g.steps.find((x) => x.id === id)).filter((x) => x?.kind === 'finding');
    if (tourFindings.length > 5) E('guided.tour', 'more than five findings in the tour');
    if (g.top.findingIds.length > 5) E('guided.top', 'more than five top findings');
    for (const id of g.top.findingIds) if (!ids.has(id)) E('guided.top', 'unknown finding "' + id + '"');
    if (!g.top.basis) E('guided.top', 'no ranking basis stated');
    if (g.tour[g.tour.length - 1] !== 'send') E('guided.tour', 'the tour must end with the feedback step');
    for (const x of g.steps) if (x.kind === 'finding') {
      const inTour = g.tour.includes(x.id), inMore = g.more.includes(x.id);
      if (inTour === inMore) E('guided.' + x.id, 'a finding step must be in exactly one of tour / more');
      if ((x.tier === 'top') !== inTour) E('guided.' + x.id, 'tier does not match tour membership');
    }
  } else E('modes', 'no guided mode');
  for (const f of r.findings ?? []) if (!gd.has(f.id)) E(`findings.${f.id}`, 'not covered by the guided tour');
  for (const k of Object.keys(r.assets ?? {})) {
    if (!r.assets[k].startsWith('data:image/')) E(`assets.${k}`, 'asset must be an inline image data URI');
  }
  return P;
}

// ---------------------------------------------------------------------------
// Explore pack: the agency's own file. Never sent to a client.
// ---------------------------------------------------------------------------
export interface ExploreStory {
  id: string;
  title: string;
  /** "confirmed" stories are in the client report; anything else is held back. */
  disposition: string;
  dispositionNote?: string;
  scope: Issue['scope'];
  categories: Array<{ id: string; label: string }>;
  severity: { level: Level; basis: string };
  effort: { size: Size; basis: string };
  owner: { id: Owner; label: string };
  findings: string[];
  pagesAffected: number;
  observed: RClaim[];
  implications: RClaim[];
  caveat?: string;
  fix: string[];
  spotlight: Spotlight;
}

export interface ExplorePack {
  format: typeof EXPLORE_FORMAT;
  version: typeof EXPLORE_VERSION;
  audience: 'agency-only';
  meta: { reportId: string; createdAt: string; generator: string; source: { siteId: string; capturedAt: string; manifestSha256: string } };
  client: { name: string; domain: string; accent: string | null };
  ranking: { basis: string; topFindingIds: string[] };
  stories: ExploreStory[];
  /** Your private talk track, keyed by story id (and by scene id for the map tour). */
  notes: Record<string, string[]>;
  /** The whole scrape, minus vault paths and machine details. */
  capture: Record<string, unknown>;
  assets: Record<string, string>;
}

export function buildExplorePack(w: Walkthrough, m: SiteGraphManifest, report: ClientReport, opts: { createdAt: string; images?: Record<string, string> }): ExplorePack {
  const c = makeCtx(m);
  const attention = attentionNodeIds(m);
  const R = (s: string) => renderText(s, c);
  const stories: ExploreStory[] = w.issues.map((i) => ({
    id: i.id, title: R(i.title), disposition: i.disposition, ...(i.dispositionNote ? { dispositionNote: R(i.dispositionNote) } : {}),
    scope: i.scope, categories: categoriesOf(c, i.findings),
    severity: { level: i.severity.level, basis: R(i.severity.basis) }, effort: { size: i.effort.size, basis: R(i.effort.basis) },
    owner: { id: i.owner, label: OWNER_LABEL[i.owner] }, findings: i.findings,
    pagesAffected: i.scope === 'sitewide' ? (m.stats?.pagesCrawled ?? m.nodes.length) : nodesAffected(m, c, i.findings).length,
    observed: i.whatWeSaw.map((cl) => renderClaim(cl, c)), implications: i.whyItMatters.map((cl) => renderClaim(cl, c)),
    ...(i.caveat ? { caveat: R(i.caveat) } : {}), fix: i.fix.map(R), spotlight: spotlightFor(m, c, i, attention),
  }));
  const notes: Record<string, string[]> = {};
  for (const i of w.issues) if (i.talk?.length) notes[i.id] = i.talk.map(R);
  for (const s of w.scenes) {
    if (s.type === 'issue') { if (s.issueId && s.talk?.length) notes[s.issueId] = [...(notes[s.issueId] ?? []), ...s.talk.map(R)]; }
    else if (s.talk?.length) notes[s.id] = s.talk.map(R);
    for (const [k, st] of (s.stops ?? []).entries()) if (st.talk?.length) notes[`${s.id}#${k + 1}`] = st.talk.map(R);
  }
  const cap = structuredClone(m) as unknown as Record<string, unknown> & { nodes: Array<Record<string, unknown>> };
  delete cap.captureProvenance;
  cap.nodes = cap.nodes.map((n) => { const { obsidianPath: _o, rawPath: _r, ...rest } = n; void _o; void _r; return rest; });
  return {
    format: EXPLORE_FORMAT, version: EXPLORE_VERSION, audience: 'agency-only',
    meta: { reportId: report.meta.reportId, createdAt: opts.createdAt, generator: 'Web-Obs Report Studio', source: report.meta.source },
    client: { name: report.client.name, domain: m.domain, accent: report.client.accent },
    ranking: { basis: RANKING_BASIS, topFindingIds: report.modes.guided.top.findingIds },
    stories, notes, capture: cap, assets: { ...(opts.images ?? {}) },
  };
}

export function validateExplorePack(p: ExplorePack): PackageProblem[] {
  const P: PackageProblem[] = [];
  const E = (where: string, message: string) => P.push({ where, message });
  if (p.format !== EXPLORE_FORMAT) E('format', 'expected "webobs.explore-pack"');
  if (p.audience !== 'agency-only') E('audience', 'must be marked agency-only');
  const nodes = (p.capture as { nodes?: Array<Record<string, unknown>> })?.nodes;
  if (!Array.isArray(nodes)) { E('capture', 'no nodes'); return P; }
  for (const n of nodes) for (const k of ['obsidianPath', 'rawPath']) if (k in n) E('capture', `node carries "${k}"`);
  if ('captureProvenance' in p.capture) E('capture', 'captureProvenance must not be included');
  if (LOCAL_PATH.test(JSON.stringify(p.capture))) E('capture', 'capture looks like it contains a local path');
  const ids = new Set(p.stories.map((s) => s.id));
  for (const id of p.ranking.topFindingIds) if (!ids.has(id)) E('ranking', `top finding "${id}" has no story`);
  return P;
}
