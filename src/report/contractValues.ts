// ---------------------------------------------------------------------------------------------------------------
// VALUES, not just names. Every value in a client report is checked for type, length and (for addresses and images)
// shape, and unknown keys are refused at every level. The schema and value behavior match the report server;
// this TypeScript copy adds explicit types for the plugin boundary.
// Only values that are present are checked; required-ness is the business of the other checks.
// ---------------------------------------------------------------------------------------------------------------
/** The whole serialised report may not exceed this many characters (the ingest route's default upload cap). */
export const REPORT_MAX_CHARS = 2 * 1024 * 1024;

interface ValueProblem { where: string; message: string }
type Fields = Record<string, Schema>;
type Schema = { nullable?: boolean } & (
  | { t: 's'; max: number; line?: boolean; re?: string; en?: string[]; url?: boolean }
  | { t: 'n' | 'b' }
  | { t: 'a'; of: Schema; max: number }
  | { t: 'or'; of: Schema[] }
  | { t: 'rec'; max: number; key: string; val: Schema }
  | { t: 'o'; f: Fields; by?: string; kinds?: Record<string, Fields> }
);

const HEX = '^#[0-9a-fA-F]{6}$', HEX64 = '^[0-9a-f]{64}$';
const IMAGE_URI = '^data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/]+={0,2}$';
const EMAIL = '^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(\\.[A-Za-z0-9-]{1,63})*\\.[A-Za-z]{2,24}$';
const line = (max: number): Schema => ({ t: 's', max, line: true });
const text = (max: number): Schema => ({ t: 's', max });
const re = (max: number, pattern: string): Schema => ({ t: 's', max, line: true, re: pattern });
const en = (...v: string[]): Schema => ({ t: 's', max: 40, line: true, en: v });
const url = (): Schema => ({ t: 's', max: 2048, line: true, url: true });
const num: Schema = { t: 'n' }, bool: Schema = { t: 'b' };
const nul = (s: Schema): Schema => ({ ...s, nullable: true });
const arr = (of: Schema, max: number): Schema => ({ t: 'a', of, max });
const obj = (f: Fields): Schema => ({ t: 'o', f });
const ID = line(200), HEXC = re(7, HEX);
const SOURCE = obj({ finding: ID, path: line(500), url: url() });
const CLAIM = obj({ text: text(2000), label: en('RAW', 'FETCH', 'LAB', 'INFER', 'SCOPE'), labelText: line(100), basis: text(2000), sources: arr(SOURCE, 50), nodeIds: arr(ID, 5000) });
const PROSE = { title: line(300), body: arr(text(2000), 30) };
const STEP: Schema = { t: 'o', by: 'kind', f: { id: line(100) }, kinds: {
  welcome: PROSE,
  orientation: { ...PROSE, tiles: arr(obj({ label: line(200), value: line(200), note: text(2000), meaning: text(2000) }), 50) },
  map: { ...PROSE, stops: arr(obj({ caption: CLAIM, focus: obj({ view: en('globe', 'road', 'clusters'), health: line(60), filter: line(60), section: ID, nodeIds: arr(ID, 5000) }) }), 50) },
  finding: {
    findingId: ID, title: line(300), tier: en('top', 'more'), rank: num, view: en('globe', 'road', 'clusters'),
    beats: obj({ found: arr(CLAIM, 100), meaning: obj({ inPlain: text(2000), picture: text(2000) }), ifIgnored: obj({ text: text(2000), basis: text(2000) }), yourPart: text(2000), howFixed: arr(text(2000), 50), askYourTeam: arr(text(2000), 50) }),
    terms: arr(line(100), 50), checkpoint: obj({ id: line(100), question: text(500), options: arr(line(300), 10) }),
  },
  plan: { ...PROSE, horizons: arr(obj({ id: en('week-1', 'month-1', 'quarter'), label: line(100), findingIds: arr(ID, 200) }), 10) },
  limits: { ...PROSE, claims: arr(CLAIM, 100) },
  decisions: { ...PROSE, questions: arr(obj({ findingId: ID, question: text(2000) }), 500) },
  send: PROSE,
} };
const FINDING = obj({
  id: ID, title: line(300), scope: en('sitewide', 'sitewide-template', 'section', 'page-specific'), categories: arr(obj({ id: line(100), label: line(100) }), 30),
  severity: obj({ level: en('high', 'medium', 'low'), basis: text(2000) }), effort: obj({ size: en('S', 'M', 'L'), basis: text(2000) }),
  owner: obj({ id: en('developer', 'content', 'marketing', 'hosting'), label: line(100) }), horizon: en('week-1', 'month-1', 'quarter'),
  observed: arr(CLAIM, 100), implications: arr(CLAIM, 100), caveat: text(2000), fix: arr(text(2000), 50), verify: text(2000),
  examples: arr(obj({ url: url(), title: line(500) }), 20), evidence: obj({ image: line(100), caption: text(500) }), glossary: arr(line(100), 50),
  spotlight: obj({ kind: en('pages', 'sitewide'), nodeIds: arr(ID, 5000), pageCount: num, filter: en('all', 'issues', 'orphans') }),
});
const NODE = obj({
  id: ID, kind: line(60), health: line(60), flags: arr(line(60), 50), title: line(1000), url: url(), path: line(2048), section: ID,
  statusCode: nul(num), inSitemap: nul(bool), urlDepth: nul(num), clickDepth: nul(num), wordCount: nul(num), inlinksBody: nul(num), inlinksTotal: nul(num),
  outlinksBody: nul(num), outlinksTotal: nul(num), externalDomainsOut: nul(num), renderUsed: nul(bool),
});
const SITE = obj({
  schemaVersion: { t: 'or', of: [line(20), num] }, siteId: line(253), domain: line(253), brandName: line(200), origin: url(), capturedAt: line(64), captureStatus: line(60),
  stats: obj(Object.fromEntries(['pagesCrawled', 'orphanPages', 'unlistedPages', 'brokenOrRedirectPages', 'externalDomains', 'externalEdges', 'internalEdges', 'sitemapUrlsTotal', 'sitemapsFound'].map((k) => [k, nul(num)]))),
  brandKit: obj({ localLogoAsset: line(300) }),
  sections: arr(obj({ id: ID, label: line(200), pageCount: num }), 1000), nodes: arr(NODE, 20000),
  edges: arr(obj({ id: ID, source: ID, target: ID, kind: line(60) }), 100000),
  audit: obj({ findings: arr(obj({ id: ID, category: line(100), tone: line(60), title: line(300), targets: arr(obj({ url: url() }), 5000) }), 5000) }),
});
const TOKENS = obj({ bg: HEXC, ink: HEXC, muted: HEXC });
export const REPORT_SPEC = obj({
  format: line(40), version: line(10),
  meta: obj({
    reportId: re(100, '^[A-Za-z0-9._-]+$'), createdAt: line(64), generator: line(200),
    source: obj({ siteId: line(253), capturedAt: line(64), manifestSha256: re(64, HEX64) }),
    review: obj({ state: en('draft', 'reviewed', 'approved'), reviewedBy: nul(line(200)) }), integrity: obj({ algorithm: en('sha256'), contentSha256: re(64, HEX64) }),
  }),
  client: obj({ name: line(200), domain: re(253, '^[A-Za-z0-9._:-]+$'), accent: nul(HEXC), preparedFor: line(200), presenter: line(200), logo: line(100), theme: obj({ accent: HEXC, secondary: HEXC, dark: TOKENS, light: TOKENS }) }),
  feedback: obj({ to: re(254, EMAIL), subject: line(300) }),
  styles: obj({ accent: HEXC, secondary: HEXC, link: HEXC, text: HEXC, muted: HEXC, surface: HEXC, cardText: HEXC, cardMuted: HEXC, headingFont: en('Oswald', 'Inter'), bodyFont: en('Oswald', 'Inter'), headingCase: en('uppercase', 'none', 'capitalize', 'lowercase'), name: line(160), footerText: line(240) }), // the styles validator is the authority (80 and 120 characters, counted as characters); these allow the same text counted in UTF-16 units
  labels: obj({ RAW: line(100), FETCH: line(100), LAB: line(100), INFER: line(100), SCOPE: line(100) }),
  summary: obj({ pagesMapped: num, findingsCount: num, bySeverity: obj({ high: num, medium: num, low: num }) }),
  findings: arr(FINDING, 200), glossary: arr(obj({ id: line(100), term: line(200), plain: text(2000) }), 200),
  map: obj({ site: SITE }),
  assets: { t: 'rec', max: 60, key: '^[A-Za-z0-9:_.-]{1,100}$', val: { t: 's', max: 1500000, line: true, re: IMAGE_URI } },
  modes: obj({ guided: obj({
    estimatedMinutes: num, steps: arr(STEP, 500), tour: arr(line(100), 500), more: arr(line(100), 500),
    top: obj({ findingIds: arr(ID, 20), picked: en('auto', 'agency'), basis: text(2000) }),
    responses: obj({ schema: en('webobs.client-responses/1'), note: text(2000) }),
  }) }),
});

// eslint-disable-next-line no-control-regex -- Reject actual control characters in untrusted report text.
const BAD_TEXT = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u2028\u2029\u202a-\u202e\u2066-\u2069]/;
// eslint-disable-next-line no-control-regex -- Single-line report fields must reject every control character.
const BAD_LINE = /[\u0000-\u001f\u007f-\u009f\u2028\u2029\u202a-\u202e\u2066-\u2069]/;
const isRec = (x: unknown): x is Record<string, unknown> => x !== null && typeof x === 'object' && !Array.isArray(x);
const rxCache = new Map<string, RegExp>();
const rx = (p: string): RegExp => { let r = rxCache.get(p); if (!r) rxCache.set(p, (r = new RegExp(p))); return r; };
const has = (o: object, k: string): boolean => Object.prototype.hasOwnProperty.call(o, k);

/** Only http: and https: addresses, with no spaces, control characters, backslashes or embedded passwords. */
export function isHttpUrl(s: unknown): s is string {
  // eslint-disable-next-line no-control-regex -- URLs must reject whitespace and control characters.
  if (typeof s !== 'string' || s.length > 2048 || /[\s\u0000-\u001f\u007f-\u009f\\]/.test(s) || !/^https?:\/\/[^/?#]/i.test(s)) return false;
  try { const u = new URL(s); return (u.protocol === 'http:' || u.protocol === 'https:') && u.hostname !== '' && !u.username && !u.password; } catch { return false; }
}

function walk(spec: Schema, v: unknown, where: string, out: ValueProblem[]): void {
  if (out.length >= 40) return;
  const bad = (msg: string): void => { out.push({ where, message: msg }); };
  if (v === null && spec.nullable) return;
  if (spec.t === 'or') {
    const tries = spec.of.map((s) => { const o: ValueProblem[] = []; walk(s, v, where, o); return o; });
    if (!tries.some((o) => !o.length)) bad('has the wrong type');
    return;
  }
  if (spec.t === 's') {
    if (typeof v !== 'string') return bad('must be text');
    if (v.length > spec.max) return bad(`is too long (more than ${spec.max} characters)`);
    if ((spec.line ? BAD_LINE : BAD_TEXT).test(v)) return bad('contains control characters');
    if (spec.url && !isHttpUrl(v)) return bad('must be an http or https address');
    if (spec.en && !spec.en.includes(v)) return bad('is not an allowed value');
    if (spec.re && !rx(spec.re).test(v)) return bad('is not in the allowed format');
  } else if (spec.t === 'n') {
    if (typeof v !== 'number' || !Number.isFinite(v) || Math.abs(v) > 1e12) bad('must be a number');
  } else if (spec.t === 'b') {
    if (typeof v !== 'boolean') bad('must be true or false');
  } else if (spec.t === 'a') {
    if (!Array.isArray(v)) return bad('must be a list');
    if (v.length > spec.max) return bad(`has too many items (more than ${spec.max})`);
    v.forEach((x, i) => walk(spec.of, x, `${where}[${i}]`, out));
  } else if (spec.t === 'rec') {
    if (!isRec(v)) return bad('must be an object');
    const keys = Object.keys(v);
    if (keys.length > spec.max) return bad(`has too many entries (more than ${spec.max})`);
    for (const k of keys) { if (k === '__proto__' || !rx(spec.key).test(k)) bad(`entry "${k.slice(0, 30)}" has a name that is not allowed`); else walk(spec.val, v[k], `${where}.${k}`, out); }
  } else if (spec.t === 'o') {
    if (!isRec(v)) return bad('must be an object');
    let fields = spec.f;
    if (spec.by && spec.kinds) {
      const k = v[spec.by], extra = typeof k === 'string' && has(spec.kinds, k) ? spec.kinds[k] : null;
      if (!extra) return bad(`has an unknown ${spec.by}`);
      fields = { ...spec.f, [spec.by]: en(...Object.keys(spec.kinds)), ...extra };
    }
    for (const k of Object.keys(v)) {
      if (!has(fields, k)) bad(`field "${k.slice(0, 30)}" is not part of the contract`);
      else if (v[k] !== undefined) walk(fields[k], v[k], where ? `${where}.${k}` : k, out);
    }
  }
}

/** Problems with the VALUES and nested structure of a client report (types, lengths, addresses, images, unknown nested keys, total size). */
export function reportValueProblems(report: unknown): ValueProblem[] {
  const out: ValueProblem[] = [];
  walk(REPORT_SPEC, report, '', out);
  let size = 0;
  try { size = JSON.stringify(report).length; } catch { size = Infinity; }
  if (size > REPORT_MAX_CHARS) out.push({ where: '$', message: 'the report is larger than the allowed size' });
  return out.map((p) => ({ where: p.where || '$', message: p.message }));
}
