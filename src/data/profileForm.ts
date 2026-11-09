// The "create a profile" form of the Publish dialog (pure: no files, no Obsidian). Used by the dialog and by the checks.
// A form becomes (a) a brand profile in the home system's shape, which is what gets saved, and (b) the flat styles, checked with the SAME
// validator as the ingest and the report server. The saved profile and the sent styles are therefore the same thing seen two ways.
import { BUNDLED_FONTS, deriveStyleOutput, validateStyles } from '../report/styles/styles.mjs';
import { contrast } from '../report/styles/color.mjs';

export interface StyleForm {
  name: string; accent: string; secondary: string; surface: string; text: string; muted: string; cardText: string; cardMuted: string;
  headingFont: string; bodyFont: string; headingCase: string; footerText: string;
}
export const HEADING_CASES = ['uppercase', 'none', 'capitalize', 'lowercase'] as const;
export const FONT_CHOICES = ['', ...Object.keys(BUNDLED_FONTS)];
export const EMPTY_FORM: StyleForm = { name: '', accent: '', secondary: '', surface: '', text: '', muted: '', cardText: '', cardMuted: '', headingFont: '', bodyFont: '', headingCase: 'none', footerText: '' };

const HEX = /^#[0-9a-fA-F]{6}$/;
/** The shared validator (an exact copy of the report app's file) words some messages in British spelling; the dialog shows US spelling. */
export const usText = (s: string): string => String(s).replace(/colours/g, 'colors').replace(/Colours/g, 'Colors').replace(/colour/g, 'color').replace(/Colour/g, 'Color');
const isObj = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);
const hexOf = (v: unknown): string | null => {
  const s = typeof v === 'string' ? v : isObj(v) ? [v.hex, v.value, v.color].find((x): x is string => typeof x === 'string') : undefined;
  const t = (s ?? '').trim(); return HEX.test(t) ? t.toLowerCase() : null;
};

/** What the audit already knows about the site, turned into a starting point. Only a starting point: the person edits and checks it. Never throws. */
export function draftFromManifest(m: { domain?: string; brandName?: string; brandKit?: { palette?: unknown[]; colorTokens?: unknown[]; themeColor?: string | null; typography?: { primaryFamilies?: string[] }; localLogoAsset?: string | null; logoUrls?: string[] } } | null | undefined, kind: 'agency' | 'client', agencyName?: string | null): { form: StyleForm; hints: string[] } {
  const form: StyleForm = { ...EMPTY_FORM }; const hints: string[] = [];
  try {
    // The Name of a CLIENT profile is the client's own name (it fills the browser tab title). The Name of an AGENCY profile is the person's own agency, so it is not taken from the captured site.
    if (kind === 'client') form.name = (m?.brandName ?? m?.domain ?? '').toString().slice(0, 80);
    // The attribution footer of a client profile starts as "Prepared by <agency name>", with the name taken from the agency profile. With no agency profile it stays empty (never the client's name).
    if (kind === 'client') {
      const ag = typeof agencyName === 'string' ? agencyName.trim().slice(0, 80) : '';
      if (ag) form.footerText = `Prepared by ${ag}`;
      else hints.push('There is no agency profile yet, so the attribution footer starts empty. Create the Agency profile first (Look: Agency) and new client profiles will start with “Prepared by <your agency>”.');
    }
    if (kind === 'client' && m) {
      const kit = m.brandKit ?? {};
      const found = [...(Array.isArray(kit.palette) ? kit.palette : []), ...(Array.isArray(kit.colorTokens) ? kit.colorTokens : [])].map(hexOf).filter((x): x is string => !!x);
      const theme = hexOf(kit.themeColor);
      const accent = theme ?? found[0]; if (accent) { form.accent = accent; hints.push('Accent taken from the site’s theme color or palette.'); }
      const second = found.find((c) => c !== accent); if (second) form.secondary = second;
      const fam = (kit.typography?.primaryFamilies ?? []).map((f) => String(f).split(',')[0].replace(/["']/g, '').trim());
      const bundled = Object.keys(BUNDLED_FONTS);
      const hit = fam.find((f) => bundled.some((b) => b.toLowerCase() === f.toLowerCase()));
      if (hit) { const b = bundled.find((x) => x.toLowerCase() === hit.toLowerCase())!; form.bodyFont = b; hints.push(`The site uses ${b}, which the report server has.`); }
      else if (fam[0]) hints.push(`The site uses ${fam[0].slice(0, 40)}, which the report server does not have (Oswald and Inter are bundled), so pick one below or leave the system font.`);
      if (kit.localLogoAsset || (kit.logoUrls && kit.logoUrls.length)) hints.push('A logo was found on the site. Logos are not part of a look yet, so it is not sent.');
    }
  } catch { /* a starting point only */ }
  return { form, hints };
}

/** Form to flat styles (empty fields left out) and the check. `errors` is empty when `styles` is set. */
export function formToStyles(form: StyleForm): { styles: Record<string, string> | null; errors: string[] } {
  try {
    const flat: Record<string, string> = {};
    const put = (k: string, v: unknown) => { if (typeof v === 'string' && v.trim()) flat[k] = v.trim(); };
    put('name', form.name); put('accent', form.accent); put('secondary', form.secondary); put('surface', form.surface); put('text', form.text); put('muted', form.muted); put('cardText', form.cardText); put('cardMuted', form.cardMuted);
    put('headingFont', form.headingFont); put('bodyFont', form.bodyFont); put('footerText', form.footerText);
    if (form.headingCase && form.headingCase !== 'none') put('headingCase', form.headingCase);
    if (!flat.name) return { styles: null, errors: ['Give the profile a name.'] };
    const v = validateStyles(flat);
    return v.ok && v.styles ? { styles: v.styles, errors: [] } : { styles: null, errors: v.errors.map((e) => usText(String(e).slice(0, 200))) };
  } catch { return { styles: null, errors: ['The form could not be read.'] }; }
}

/** The live preview line under the form: the summary, adjustments and low contrast. */
export function previewForm(form: StyleForm): { ok: boolean; errors: string[]; summary: string; notes: string[] } {
  const r = formToStyles(form);
  if (!r.styles) return { ok: false, errors: r.errors, summary: '', notes: [] };
  const out = deriveStyleOutput(r.styles);
  const low = out.checks.filter((c) => !c.ok && !/card edge/.test(c.what)).map((c) => `Readability: ${c.what} is ${c.ratio}:1 (wanted ${c.min}:1)`);
  const bits = [r.styles.accent ? `accent ${r.styles.accent}` : '', r.styles.surface ? `cards ${r.styles.surface}` : ''].filter(Boolean);
  return { ok: true, errors: [], summary: bits.join(', ') || 'No colors set.', notes: [...out.notes, ...low].map(usText) };
}

/** What each field is for, in plain words (the dialog shows these under the fields). */
export const FIELD_TEXT: Record<keyof StyleForm, { label: string; help: string }> = {
  name: { label: 'Name', help: 'Shown in the browser tab title, and in the footer line (Prepared by …) when the attribution footer is empty.' },
  footerText: { label: 'Attribution footer', help: 'The line shown below the 3D presentation layer, for example Prepared by Your Agency.' },
  accent: { label: 'Accent', help: 'Buttons, the active step and highlights.' },
  secondary: { label: 'Secondary', help: 'The expandable sections.' },
  surface: { label: 'Card surface (optional)', help: 'The background of cards and panels. Light or dark both work: set the text on cards below to match.' },
  text: { label: 'Text on the page', help: 'The main text color on the dark page, outside the cards. It is lightened if it is too dark to read there.' },
  muted: { label: 'Muted on the page', help: 'Small secondary text on the page, such as captions.' },
  cardText: { label: 'Text on cards', help: 'The text inside cards and panels. Use dark text on a light card and light text on a dark card. Empty: the page text is used on cards.' },
  cardMuted: { label: 'Muted on cards', help: 'Small secondary text inside cards. Empty: a softer shade of the card text.' },
  headingFont: { label: 'Heading font', help: 'Page headings. System font is the default.' },
  bodyFont: { label: 'Body font', help: 'Reading text. System font is the default.' },
  headingCase: { label: 'Heading case', help: 'How headings are written.' },
};
export const COLOR_FIELDS = ['accent', 'secondary', 'surface'] as const;
/** The text colors: the page text and the text on cards, each with its small text. */
export const TEXT_FIELDS = ['text', 'muted', 'cardText', 'cardMuted'] as const;
export const COLOR_FALLBACK: Record<(typeof COLOR_FIELDS)[number] | (typeof TEXT_FIELDS)[number], string> = { accent: '#7c5cff', secondary: '#2ecdf5', surface: '#101521', text: '#f4f6fb', muted: '#9aa4b8', cardText: '#f4f6fb', cardMuted: '#9aa4b8' };
/** The built-in card color the checks use when no card surface is chosen. */
export const DEFAULT_CARD = '#101521';
export const HEADING_CASE_LABELS: Record<string, string> = { none: 'As written', uppercase: 'ALL CAPS', capitalize: 'Each Word Capitalized', lowercase: 'all lowercase' };
export const PAGE_BACKGROUND_NOTE = 'The page background and the 3D globe never change, so your colors always sit on the same dark stage.';

const FIELD_KEYS = Object.keys(EMPTY_FORM) as Array<keyof StyleForm>;
/**
 * The preview messages sorted by the field they belong to, so a note can sit next to the field that needs it.
 * A message that names no field (for example a general readability line) goes in `general`. Never throws.
 */
export function fieldIssues(form: StyleForm): { errors: Partial<Record<keyof StyleForm, string[]>>; notes: Partial<Record<keyof StyleForm, string[]>>; general: string[]; ok: boolean; summary: string } {
  const out = { errors: {} as Partial<Record<keyof StyleForm, string[]>>, notes: {} as Partial<Record<keyof StyleForm, string[]>>, general: [] as string[], ok: false, summary: '' };
  try {
    const p = previewForm(form);
    out.ok = p.ok; out.summary = p.summary;
    const slotOf = (msg: string): keyof StyleForm | null => {
      const first = /^([A-Za-z]+)/.exec(msg)?.[1];
      if (!first) return null;
      if (first === 'link') return 'accent';
      return (FIELD_KEYS as string[]).includes(first) ? (first as keyof StyleForm) : null;
    };
    // Next to its field the message does not need the field name in front ("surface: text on a card..." becomes "Text on a card...").
    const plain = (m: string) => { const s = m.replace(/^[A-Za-z]+:\s*/, ''); return s.charAt(0).toUpperCase() + s.slice(1); };
    const put = (bucket: Partial<Record<keyof StyleForm, string[]>>, msg: string) => { const k = slotOf(msg); if (k) (bucket[k] ??= []).push(plain(msg)); else out.general.push(msg); };
    for (const e of p.errors) { if (/^Give the profile a name/.test(e)) (out.errors.name ??= []).push(e); else put(out.errors, e); }
    for (const n of p.notes) put(out.notes, n);
  } catch { /* an empty result */ }
  return out;
}

/** The profile file written to disk, in the home brand-profile shape. Only keys the look uses; nothing else is invented. */
export function formToProfile(form: StyleForm): Record<string, unknown> | null {
  const r = formToStyles(form); if (!r.styles) return null;
  const s = r.styles;
  const colors: Record<string, string> = {};
  if (s.accent) { colors.primary = s.accent; colors.accent_orange = s.accent; }
  if (s.secondary) colors.blue_light = s.secondary;
  if (s.text) colors.text_on_dark = s.text;
  if (s.muted) colors.muted = s.muted;
  if (s.cardText) colors.text = s.cardText;
  if (s.cardMuted) colors.muted_on_card = s.cardMuted;
  if (s.surface) colors.surface = s.surface;
  const profile: Record<string, unknown> = { name: s.name, colors };
  const fonts: Record<string, unknown> = {};
  if (s.headingFont || s.headingCase) fonts.heading = { ...(s.headingFont ? { name: s.headingFont } : {}), ...(s.headingCase ? { case: s.headingCase } : {}) };
  if (s.bodyFont) fonts.body = { name: s.bodyFont };
  if (Object.keys(fonts).length) profile.fonts = fonts;
  if (s.footerText) profile.attribution = { footer_text: s.footerText };
  return profile;
}

const KEYS = Object.keys(EMPTY_FORM) as Array<keyof StyleForm>;
const str = (v: unknown): string => (typeof v === 'string' ? v : '');

/**
 * A stored profile (the home shape, or an already flat styles file) into the form, for editing. Never throws: a value of the wrong type becomes an empty field.
 * colors.text is the text on cards only when it reads on the card (the same rule the publish mapping uses), so a home profile with a dark card and dark colors.text does not show an error the person never made.
 */
export function profileToForm(raw: unknown): StyleForm {
  const f = { ...EMPTY_FORM };
  try {
    if (!isObj(raw)) return f;
    if (!isObj(raw.colors)) { for (const k of KEYS) f[k] = str(raw[k]); f.headingCase = f.headingCase || 'none'; return f; }
    const c = raw.colors, fo = isObj(raw.fonts) ? raw.fonts : {}, a = isObj(raw.attribution) ? raw.attribution : {};
    const h = isObj(fo.heading) ? fo.heading : {}, b = isObj(fo.body) ? fo.body : {};
    f.name = str(raw.name); f.accent = str(c.accent_orange) || str(c.primary); f.secondary = str(c.blue_light); f.text = str(c.text_on_dark); f.muted = str(c.muted); f.surface = str(c.surface);
    const ct = str(c.text), card = HEX.test(f.surface) ? f.surface : DEFAULT_CARD;
    f.cardText = HEX.test(ct) && contrast(ct, card) >= 4.5 ? ct : ''; f.cardMuted = str(c.muted_on_card);
    f.headingFont = str(h.name); f.bodyFont = str(b.name); f.headingCase = str(h.case) || 'none'; f.footerText = str(a.footer_text);
  } catch { /* empty form */ }
  return f;
}

const clone = (v: unknown): Record<string, unknown> => { try { return isObj(v) ? (JSON.parse(JSON.stringify(v)) as Record<string, unknown>) : {}; } catch { return {}; } };
/** Sets or removes a nested key, making the folders on the way when they are missing (a folder that is not an object is replaced). */
function setPath(o: Record<string, unknown>, p: string[], v: string): void {
  let cur = o;
  for (let i = 0; i < p.length - 1; i++) { const n = cur[p[i]]; if (!isObj(n)) { if (!v) return; cur[p[i]] = {}; } cur = cur[p[i]] as Record<string, unknown>; }
  const last = p[p.length - 1]; if (v) cur[last] = v; else delete cur[last];
}

/**
 * The stored file with the person's changes applied: ONLY the fields that changed against `initial` are written, every other key (the voice, the logo, notes, keys this
 * plugin does not know) stays exactly as it was. A cleared field removes its key. The file keeps its own shape (home profile or flat styles file). Never throws.
 */
export function applyFormToRaw(raw: unknown, initial: StyleForm, form: StyleForm): Record<string, unknown> {
  const out = clone(raw);
  try {
    const flat = !isObj(out.colors);
    const colors = isObj(out.colors) ? out.colors : {};
    for (const k of KEYS) {
      if (form[k] === initial[k]) continue;
      const v = k === 'headingCase' && form[k] === 'none' ? '' : form[k];
      if (flat) { if (v) out[k] = v; else delete out[k]; continue; }
      switch (k) {
        case 'name': setPath(out, ['name'], v); break;
        case 'accent': setPath(out, ['colors', Object.prototype.hasOwnProperty.call(colors, 'accent_orange') || !Object.prototype.hasOwnProperty.call(colors, 'primary') ? 'accent_orange' : 'primary'], v); break;
        case 'secondary': setPath(out, ['colors', 'blue_light'], v); break;
        case 'text': setPath(out, ['colors', 'text_on_dark'], v); break;
        case 'muted': setPath(out, ['colors', 'muted'], v); break;
        case 'surface': setPath(out, ['colors', 'surface'], v); break;
        case 'cardText': setPath(out, ['colors', 'text'], v); break;
        case 'cardMuted': setPath(out, ['colors', 'muted_on_card'], v); break;
        case 'headingFont': setPath(out, ['fonts', 'heading', 'name'], v); break;
        case 'headingCase': setPath(out, ['fonts', 'heading', 'case'], v); break;
        case 'bodyFont': setPath(out, ['fonts', 'body', 'name'], v); break;
        case 'footerText': setPath(out, ['attribution', 'footer_text'], v); break;
      }
    }
  } catch { /* the copy is returned as it is */ }
  return out;
}

