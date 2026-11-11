// Style profiles for Publish: the look a client report carries (v0.1.4 of the report app).
//
// Three choices in the Publish dialog: Default (the built-in look, nothing is sent), Agency (agency.json) and Client (one file from clients/).
// The profiles are plain JSON files in a folder of the vault (default <vault>/.web-obs/styles/):
//   default.json         optional; a generic look. Absent: the built-in look.
//   agency.json          the agency profile
//   clients/<name>.json  one per client
// A file is either a brand profile (the home system's shape: name, colors, fonts, attribution, plus the optional colors.surface; the voice,
// avoid_words, preferences and similar keys are never sent) or an already flat styles file. Either way it is turned into the flat styles
// and checked with the SAME validator the ingest and the report server use (src/report/styles/styles.mjs), before anything leaves this computer.
// Reading is bounded and plain: no symbolic links, no folders outside the profiles folder, file names from the listing only.
import fs from 'node:fs';
import path from 'node:path';
import { profileTarget } from './profileSource';
import { usText } from '../data/profileForm';
import { contrast } from '../report/styles/color.mjs';
import { BUNDLED_FONTS, STYLE_SLOTS, deriveStyleOutput, validateStyles } from '../report/styles/styles.mjs';

export const PROFILE_MAX_BYTES = 64 * 1024;
export const DEFAULT_STYLES_SUBFOLDER = path.join('.web-obs', 'styles');
const CLIENT_FILE = /^[A-Za-z0-9][A-Za-z0-9._ -]{0,80}\.json$/;

export interface StyleChoiceInfo { id: string; label: string; kind: 'default' | 'agency' | 'client'; ok: boolean; problem?: string; /** Offered, but there is no profile file yet: choosing it opens the create form. */ missing?: boolean }
export interface StylePreview { id: string; label: string; styles: Record<string, string> | null; summary: string; notes: string[]; problem?: string }

const isObj = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);
const own = (o: Record<string, unknown>, k: string): unknown => (Object.prototype.hasOwnProperty.call(o, k) ? o[k] : undefined);
const str = (v: unknown): string | undefined => (typeof v === 'string' && v.length > 0 ? v : undefined);

/** Whether a key is within two edits of a styles name, ignoring case, dashes and underscores: a slip of the hand rather than a key of its own. */
function nearStylesName(key: string): boolean {
  const plain = (t: string) => t.toLowerCase().replace(/[-_ ]/g, '');
  const k = plain(key); if (k.length < 3 || k.length > 24) return false;
  const distance = (a: string, b: string): number => {
    let row = Array.from({ length: b.length + 1 }, (_, i) => i);
    for (let i = 1; i <= a.length; i++) { const next = [i]; for (let j = 1; j <= b.length; j++) next[j] = Math.min(row[j] + 1, next[j - 1] + 1, row[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)); row = next; }
    return row[b.length];
  };
  return STYLE_SLOTS.some((slot) => { const t = plain(slot); return distance(k, t) <= (t.length <= 4 ? 1 : 2); });
}

/**
 * Turns a profile (or an already flat styles object) into flat styles. Never throws. `errors` is empty when `styles` is set.
 * Mapping: accent = colors.accent_orange (else primary); link = primary; secondary = blue_light; text = text_on_dark; muted = muted; cardText = colors.text (only when it reads on the card); cardMuted = colors.muted_on_card;
 * surface = surface (else grey_2); headingFont and bodyFont = the font names (only the bundled ones); headingCase = fonts.heading.case;
 * name = name; footerText = attribution.footer_text. grey_0 and grey_1 are reserved and never used. Everything else is left behind.
 */
export function profileToStyles(raw: unknown): { styles: Record<string, string> | null; notes: string[]; errors: string[] } {
  const notes: string[] = [];
  try {
    if (!isObj(raw)) return { styles: null, notes, errors: ['The profile is not a JSON object.'] };
    let flat: Record<string, unknown>;
    if (!isObj(own(raw, 'colors'))) {
      // Already a flat styles file. Keys that are not styles names (a note someone keeps in the file, a key from a newer version) are left out and named,
      // as the extra keys of a profile with "colors" are. The editor keeps them in the file; the validator and the server stay strict about what is sent.
      flat = {};
      const extra: string[] = [];
      // A key that is nearly a styles name ("acent", "Surface") is a typo, not a note: it stays in, so the validator refuses the file and names the key.
      for (const k of Object.keys(raw)) { if (STYLE_SLOTS.includes(k) || nearStylesName(k)) flat[k] = raw[k]; else extra.push(k); }
      if (extra.length) notes.push(`${extra.slice(0, 5).map((k) => `"${k.slice(0, 40)}"`).join(', ')}${extra.length > 5 ? ` and ${extra.length - 5} more` : ''} ${extra.length === 1 ? 'is not a styles name and is' : 'are not styles names and are'} not sent.`);
    } else {
      const c = own(raw, 'colors') as Record<string, unknown>, f = isObj(own(raw, 'fonts')) ? (own(raw, 'fonts') as Record<string, unknown>) : {};
      const a = isObj(own(raw, 'attribution')) ? (own(raw, 'attribution') as Record<string, unknown>) : {};
      flat = {};
      const put = (k: string, v: unknown) => { if (v !== undefined) flat[k] = v; };
      put('accent', own(c, 'accent_orange') ?? own(c, 'primary'));
      put('link', own(c, 'primary')); put('secondary', own(c, 'blue_light')); put('text', own(c, 'text_on_dark')); put('muted', own(c, 'muted'));
      put('surface', own(c, 'surface') ?? own(c, 'grey_2'));
      // The home profile has two text colors: text_on_dark (the page text, above) and text (for light backgrounds). colors.text becomes the text on cards, but only when it
      // reads on this profile's card; on a dark card a dark text would be unreadable, so it is left out and the page text is used on cards as before.
      const cardText = str(own(c, 'text'));
      if (cardText) {
        const card = typeof flat.surface === 'string' && /^#[0-9a-fA-F]{6}$/.test(flat.surface) ? flat.surface : '#101521';
        if (/^#[0-9a-fA-F]{6}$/.test(cardText) && contrast(cardText, card) >= 4.5) put('cardText', cardText);
        else notes.push(`colors.text (${cardText.slice(0, 9)}) does not read on the card ${card}, so the page text is used on cards.`);
      }
      put('cardMuted', own(c, 'muted_on_card'));
      const heading = isObj(own(f, 'heading')) ? (own(f, 'heading') as Record<string, unknown>) : null, body = isObj(own(f, 'body')) ? (own(f, 'body') as Record<string, unknown>) : null;
      const font = (role: string, o: Record<string, unknown> | null, slot: string) => {
        const n = o ? str(own(o, 'name')) : undefined; if (!n) return;
        if (Object.prototype.hasOwnProperty.call(BUNDLED_FONTS, n)) flat[slot] = n;
        else notes.push(`The ${role} font "${n.slice(0, 40)}" is not bundled with the report server (Oswald and Inter are), so the system font is used.`);
      };
      font('heading', heading, 'headingFont'); font('body', body, 'bodyFont');
      if (heading) put('headingCase', own(heading, 'case'));
      put('name', own(raw, 'name')); put('footerText', own(a, 'footer_text'));
      if (str(own(c, 'grey_0')) || str(own(c, 'grey_1'))) notes.push('grey_0 and grey_1 are reserved for the page and 3D stage and are not sent.');
    }
    const v = validateStyles(flat);
    if (!v.ok || !v.styles) return { styles: null, notes, errors: v.errors.map((e) => `The profile needs a fix: ${usText(e)}`) };
    return { styles: v.styles, notes, errors: [] };
  } catch { return { styles: null, notes, errors: ['The profile could not be read.'] }; }
}

/** The folder the profiles live in: the setting (a full path, or relative to the vault), or <vault>/.web-obs/styles. */
export function resolveStylesFolder(vaultRoot: string, setting: string): string {
  const s = (setting ?? '').trim();
  if (!s) return path.join(vaultRoot, DEFAULT_STYLES_SUBFOLDER);
  return path.isAbsolute(s) ? s : path.join(vaultRoot, s);
}

/** Reads one profile file: a plain file (not a link), at most 64 KB, valid JSON. Throws a plain message otherwise. */
export function readProfileFile(file: string): unknown {
  const st = fs.lstatSync(file);
  if (!st.isFile()) throw new Error('The profile is not a plain file.');
  if (st.size > PROFILE_MAX_BYTES) throw new Error('The profile file is larger than 64 KB.');
  const text = fs.readFileSync(file, 'utf8').replace(/^\ufeff/, '');
  try { return JSON.parse(text); } catch { throw new Error('The profile file is not valid JSON.'); }
}

const clientDir = (folder: string) => path.join(folder, 'clients');
const fileFor = (folder: string, id: string): string | null => {
  if (id === 'agency') return path.join(folder, 'agency.json');
  if (id === 'default') return path.join(folder, 'default.json');
  if (id.startsWith('client:')) {
    const name = id.slice(7);
    if (!CLIENT_FILE.test(name) || name !== path.basename(name)) return null; // a name from the listing only: no folders, no dots-only, no odd characters
    return path.join(clientDir(folder), name);
  }
  return null;
};

/** What the Publish dialog offers. Default is always there; Agency and the clients appear when their file exists. A file that needs a fix is listed with its problem. */
export function listStyleChoices(folder: string, domain?: string): StyleChoiceInfo[] {
  const out: StyleChoiceInfo[] = [{ id: 'default', label: 'Default (built-in look)', kind: 'default', ok: true }];
  const add = (id: string, kind: 'agency' | 'client', fallbackLabel: string) => {
    const file = fileFor(folder, id); if (!file) return;
    let label = fallbackLabel;
    try {
      const raw = readProfileFile(file); const r = profileToStyles(raw);
      const nm = isObj(raw) ? str(own(raw, 'name')) : undefined; if (nm) label = `${kind === 'agency' ? 'Agency' : 'Client'}: ${nm.slice(0, 60)}`;
      out.push(r.styles ? { id, label, kind, ok: true } : { id, label, kind, ok: false, problem: r.errors[0] });
    } catch (e) { out.push({ id, label, kind, ok: false, problem: (e as Error).message }); }
  };
  if (fs.existsSync(path.join(folder, 'agency.json'))) add('agency', 'agency', 'Agency');
  else out.push({ id: 'agency', label: 'Agency (not set up yet)', kind: 'agency', ok: true, missing: true });
  let clients: string[] = [];
  try { clients = fs.readdirSync(clientDir(folder)).filter((n) => CLIENT_FILE.test(n)).sort().slice(0, 200); } catch { /* no clients folder */ }
  for (const n of clients) add('client:' + n, 'client', 'Client: ' + n.replace(/\.json$/, ''));
  // The client look for THIS site is always offered: from its file, or as a create-it entry.
  const mine = domain ? profileTarget(folder, 'client', domain) : null;
  if (mine && !out.some((c) => c.id.toLowerCase() === mine.id.toLowerCase())) out.push({ id: mine.id, label: `Client: ${mine.id.slice(7).replace(/.json$/, '')} (not set up yet)`, kind: 'client', ok: true, missing: true });
  // A default.json, when present, replaces the built-in look as the Default choice.
  const d = out[0]; if (fs.existsSync(path.join(folder, 'default.json'))) { try { const r = profileToStyles(readProfileFile(path.join(folder, 'default.json'))); d.label = r.styles ? 'Default (default.json)' : 'Default (default.json needs a fix)'; if (!r.styles) { d.ok = false; d.problem = r.errors[0]; } } catch (e) { d.ok = false; d.problem = (e as Error).message; d.label = 'Default (default.json needs a fix)'; } }
  return out;
}

/** Loads one choice for a preview or a publish. Default without a default.json means no styles (the built-in look). Never throws; `problem` says what is wrong. */
export function loadStyleChoice(folder: string, id: string): StylePreview {
  const none = (label: string, problem?: string): StylePreview => ({ id, label, styles: null, summary: problem ? '' : 'The built-in look. Nothing extra is sent.', notes: [], problem });
  try {
    const file = fileFor(folder, id);
    if (!file) return none('Unknown choice', 'That style choice is not one of the offered ones.');
    if (id === 'default' && !fs.existsSync(file)) return none('Default (built-in look)');
    let raw: unknown; try { raw = readProfileFile(file); } catch (e) { return none(id, (e as Error).message); }
    const r = profileToStyles(raw);
    if (!r.styles) return none(id, r.errors[0]);
    const out = deriveStyleOutput(r.styles);
    const label = (isObj(raw) && str(own(raw, 'name'))) || id;
    const bits = [r.styles.accent ? `accent ${r.styles.accent}` : '', r.styles.surface ? `cards ${r.styles.surface}` : '', [r.styles.headingFont, r.styles.bodyFont].filter(Boolean).join(' and ') ? `fonts ${[...new Set([r.styles.headingFont, r.styles.bodyFont].filter(Boolean))].join(' and ')}` : ''].filter(Boolean);
    const low = out.checks.filter((c) => !c.ok && !/card edge/.test(c.what)).map((c) => `${c.what} is ${c.ratio}:1 (wanted ${c.min}:1)`);
    return { id, label: String(label).slice(0, 80), styles: r.styles, summary: bits.join(', ') || 'No colors or fonts set.', notes: [...r.notes, ...out.notes, ...low.map((x) => 'Readability: ' + x)] };
  } catch { return none('Style', 'The style choice could not be read.'); }
}

export interface ProfileSummary { id: string; label: string; kind: 'agency' | 'client'; file: string; summary: string; problem?: string }
/**
 * The profiles in the styles folder for the settings list: Agency first, then each client file by name, each with a one-line summary (accent, cards, fonts) and the problem the
 * validator finds in it, if any. Backup copies (.bak) and files that are not client profiles are not listed. Never throws.
 */
export function listProfileSummaries(folder: string): ProfileSummary[] {
  const out: ProfileSummary[] = [];
  const add = (id: string, kind: 'agency' | 'client', file: string, fallback: string) => {
    try {
      const l = loadStyleChoice(folder, id);
      let label = fallback; try { const raw = readProfileFile(file); const nm = isObj(raw) ? str(own(raw, 'name')) : undefined; if (nm) label = nm.slice(0, 60); } catch { /* the label stays */ }
      out.push({ id, label, kind, file, summary: l.problem ? '' : l.summary, ...(l.problem ? { problem: l.problem } : {}) });
    } catch { out.push({ id, label: fallback, kind, file, summary: '', problem: 'The profile could not be read.' }); }
  };
  if (fs.existsSync(path.join(folder, 'agency.json'))) add('agency', 'agency', path.join(folder, 'agency.json'), 'Agency');
  let names: string[] = [];
  try { names = fs.readdirSync(clientDir(folder)).filter((x) => CLIENT_FILE.test(x)).sort().slice(0, 200); } catch { /* no clients folder */ }
  for (const nm of names) add('client:' + nm, 'client', path.join(clientDir(folder), nm), nm.replace(/\.json$/, ''));
  return out;
}
