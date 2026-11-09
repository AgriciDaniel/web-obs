// The runtime "styles" file: a flat { slot: value } list that a report can carry to change its look (v0.1.4).
//
// ONE pure module (no file access, no packages, safe in the browser) used in three places: the Studio and publish tools when a styles file is
// attached, the ingest when an upload arrives, and the viewer server again when a page is served. It never throws: every problem becomes a
// plain message in `errors` (or a reason code in `codes`). Nothing from the file is ever copied into the stylesheet: every CSS line is written
// here from validated values (hex colours, bundled font names, one of four case words).
//
// Reserved for visibility: there is NO slot for the page and 3D stage background or the 3D render, so a styles file cannot change them.
import { STAGE_BG, contrast, luminance, mix, readableOn, ensureContrast, rgb } from './color.mjs';

export const STYLES_VERSION = 1;
/** The size cap for the file as sent (characters of its compact JSON). A real file is under 1 KB. */
export const STYLES_MAX_CHARS = 4096;
export const COLOR_SLOTS = ['accent', 'secondary', 'link', 'text', 'muted', 'surface', 'cardText', 'cardMuted'];
export const FONT_SLOTS = ['headingFont', 'bodyFont'];
export const TEXT_SLOTS = { name: 80, footerText: 120 };
export const CASE_VALUES = ['uppercase', 'none', 'capitalize', 'lowercase'];
/** Every key a styles file may have. Anything else is refused at upload (a typo like "acent" is named in the message). */
export const STYLE_SLOTS = [...COLOR_SLOTS, ...FONT_SLOTS, 'headingCase', ...Object.keys(TEXT_SLOTS)];
/** Fonts bundled in the image, by name. A styles file can only NAME one of these; font bytes never travel with a report. */
export const BUNDLED_FONTS = {
  Oswald: [{ file: 'Oswald.woff2', weight: '400 700' }],
  Inter: [{ file: 'Inter-Regular.woff2', weight: '400' }, { file: 'Inter-SemiBold.woff2', weight: '600 700' }],
};
export const SYSTEM_STACK = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
/** The built-in light-on-dark values the checks use for a slot the file leaves out (the CSS never overrides a missing slot). */
const DEFAULT_INK = '#f4f6fb', DEFAULT_PANEL = '#101521';
/** The built-in muted text, second color and accent of the viewer (what shows on a card when a look does not set them). */
const DEFAULT_MUTED = '#aab2c5', DEFAULT_SECONDARY = '#5fd3c6', DEFAULT_ACCENT = '#7c5cff';
/** The dark text colour suggested for a light card (the same dark the accent button uses). */
const SUGGEST_DARK = '#10131a', SUGGEST_LIGHT = '#ffffff';
const r2 = (n) => Number(n.toFixed(2));
/** The fixed severity and warning pairs of the viewer stylesheet (made for the default dark card): [token name, tint, tint opacity, text color, label]. */
const CHIPS = [['sev-high', '#ff6363', 0.18, '#ff9d9d', 'the high severity chip'], ['sev-medium', '#ffb84d', 0.17, '#ffcc80', 'the medium severity chip'], ['sev-low', '#6eaaff', 0.17, '#a8cbff', 'the low severity chip'], ['warn', '#ffb84d', 0.2, '#ffd08a', 'the warning box']];

const HEX = /^#[0-9a-fA-F]{6}$/;
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const isPlain = (v) => v !== null && typeof v === 'object' && !Array.isArray(v) && Object.getPrototypeOf(v) === Object.prototype || (v !== null && typeof v === 'object' && !Array.isArray(v) && Object.getPrototypeOf(v) === null);
// Characters a text may not contain: control characters, line and paragraph separators, zero-width and bidi controls, the byte order mark,
// the interlinear marks, and a lone surrogate half. Written as number ranges so no odd character sits in this file.
const BAD_RANGES = [[0, 31], [127, 159], [0x61c, 0x61c], [0x200b, 0x200f], [0x2028, 0x202e], [0x2060, 0x2069], [0xfeff, 0xfeff], [0xfff9, 0xfffb], [0xd800, 0xdfff]];
const cleanText = (v) => { for (const ch of v) { const cp = ch.codePointAt(0); if (BAD_RANGES.some(([x, y]) => cp >= x && cp <= y)) return false; } return true; };
const textOk = (v, max) => typeof v === 'string' && v.trim().length > 0 && [...v].length <= max && cleanText(v);

/**
 * Checks a parsed styles object. Returns { ok, errors, codes, styles } where `styles` is a FRESH object holding only validated slots
 * (colours lower-cased, texts trimmed). `ok` is false when anything is wrong; the caller decides what that means (the ingest refuses the
 * upload, the viewer server uses the neutral look).
 */
export function validateStyles(raw) {
  const errors = [], codes = new Set();
  const bad = (code, msg) => { codes.add(code); errors.push(msg); };
  try {
    if (!isPlain(raw)) { bad('not-object', 'The styles must be an object of names and values.'); return { ok: false, errors, codes: [...codes], styles: null }; }
    let size = 0; try { size = JSON.stringify(raw).length; } catch { size = Infinity; }
    if (size > STYLES_MAX_CHARS) { bad('too-big', `The styles are larger than ${STYLES_MAX_CHARS} characters.`); return { ok: false, errors, codes: [...codes], styles: null }; }
    const out = {};
    for (const k of Object.keys(raw)) {
      if (!STYLE_SLOTS.includes(k)) { bad('unknown-key', `"${k.length > 40 ? k.slice(0, 40) + '...' : k}" is not a styles name. The names are: ${STYLE_SLOTS.join(', ')}.`); continue; }
      const v = raw[k];
      if (COLOR_SLOTS.includes(k)) { if (typeof v === 'string' && HEX.test(v)) out[k] = v.toLowerCase(); else bad('bad-value', `${k} must be a colour like #1a2b3c.`); }
      else if (FONT_SLOTS.includes(k)) { if (typeof v === 'string' && has(BUNDLED_FONTS, v)) out[k] = v; else bad('bad-value', `${k} must be one of: ${Object.keys(BUNDLED_FONTS).join(', ')}.`); }
      else if (k === 'headingCase') { if (typeof v === 'string' && CASE_VALUES.includes(v)) out[k] = v; else bad('bad-value', `headingCase must be one of: ${CASE_VALUES.join(', ')}.`); }
      else if (has(TEXT_SLOTS, k)) { if (textOk(v, TEXT_SLOTS[k])) out[k] = v.trim(); else bad('bad-value', `${k} must be plain text of 1 to ${TEXT_SLOTS[k]} characters.`); }
    }
    if (errors.length) return { ok: false, errors, codes: [...codes], styles: null };
    // Readability the page cannot repair: the nudging below fixes a text or link color that is a little too dim, but a card color that the card text cannot
    // read on cannot be fixed by nudging. Such a look is refused, naming the slot, the colors and the numbers.
    for (const p of readabilityProblems(out)) bad('unreadable', p.message);
    if (errors.length) return { ok: false, errors, codes: [...codes], styles: null };
    return { ok: true, errors, codes: [], styles: out };
  } catch { return { ok: false, errors: ['The styles could not be read.'], codes: ['unreadable'], styles: null }; }
}

/**
 * The best plain text color for a card: white or a near-black, whichever reads better on it. { color, ratio, ok, tone }; ok is true when it reaches 4.5:1.
 * Used in messages ("Use light text on this card, for example #ffffff (5.0:1)") and by the publish form's one-click suggestion. Never throws.
 */
export function suggestCardText(surface) {
  try {
    if (typeof surface !== 'string' || !HEX.test(surface)) return null;
    const light = contrast(SUGGEST_LIGHT, surface), dark = contrast(SUGGEST_DARK, surface);
    const useLight = light >= dark; const ratio = useLight ? light : dark;
    return { color: useLight ? SUGGEST_LIGHT : SUGGEST_DARK, ratio: Number(ratio.toFixed(1)), ok: ratio >= 4.5, tone: useLight ? 'light' : 'dark' };
  } catch { return null; }
}
const suggestionText = (surface) => {
  const s = suggestCardText(surface);
  if (!s) return '';
  return s.ok ? `Use ${s.tone} text on this card, for example ${s.color} (${s.ratio.toFixed(1)}:1).` : 'Neither light nor dark text reaches 4.5:1 on this card color: choose a lighter or a darker card color.';
};

/**
 * The readability failures that remain AFTER the page's own nudging, as [{ slot, what, ratio, min, message }], one per slot. Empty when the look reads.
 * Only text checks (4.5:1) count; the accent on the stage and the card edge stay advisory. Every message is built from the failing check itself: the slot to blame,
 * the two colors that were compared and the ratio of that pair. Takes validated styles (validateStyles calls it after checking every value); never throws.
 */
export function readabilityProblems(styles) {
  try {
    const s = styles || {};
    const out = deriveStyleOutput(s);
    const list = [], seen = new Set();
    const panel = s.surface || DEFAULT_PANEL;
    const cardTextFails = Boolean(s.cardText) && contrast(s.cardText, panel) < 4.5;
    const label = (what) => what.replace(/ on a card$/, '').replace(/^the /, '');
    for (const c of out.checks) {
      if (c.ok || c.min < 4.5) continue; // text only: the accent on the stage and the card edges stay advisory (a dim accent or a faint edge is a style choice, not unreadable text)
      const slot = c.slot || 'text';
      // When the card text itself cannot be read, the links, the second color, the chips and the warning boxes on the card follow from it (they are derived toward the card text): one clear message, not several.
      if (cardTextFails && slot !== 'cardText' && slot !== 'cardMuted') continue;
      const nums = `on the card ${c.bg} reaches only ${c.ratio}:1 and needs ${c.min}:1.`;
      const cmp = `${c.fg} on ${c.bg} reaches only ${c.ratio}:1 and needs ${c.min}:1.`;
      let message;
      if (slot === 'cardText') message = `cardText: ${c.fg} ${nums} ${suggestionText(c.bg)}`;
      else if (slot === 'cardMuted') message = `cardMuted: ${c.fg} ${nums} Choose a color closer to the card text.`;
      else if (slot === 'surface' && /^text/.test(c.what)) message = `surface: the page text (${c.fg}) ${nums} Set cardText for the text on cards. ${suggestionText(c.bg)}`;
      else if (slot === 'surface') message = `surface: ${label(c.what)} (${c.fg}) ${nums} Set cardText and cardMuted for the text on cards, or choose a different card color.`;
      else message = `${slot}: ${c.what} ${cmp} Choose a lighter color.`;
      if (seen.has(slot)) continue; seen.add(slot);
      list.push({ slot, what: c.what, ratio: c.ratio, min: c.min, message });
    }
    return list;
  } catch { return [{ slot: 'styles', what: 'readability', ratio: 0, min: 0, message: 'styles: readability could not be checked.' }]; }
}

/** The fixed text form that is hashed: the slot names sorted, written as a list of [name, value] pairs. Same bytes on every machine. */
export function canonicalStyles(raw) {
  try {
    const o = raw && typeof raw === 'object' ? raw : {};
    return JSON.stringify(Object.keys(o).sort().map((k) => [k, o[k]]));
  } catch { return ''; } // never throws: an unreadable object has no fixed form
}

const escHtml = (s) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
/** JSON for a script block of type application/json: < > & and the two line separators are written as \uXXXX. */
export const safeJson = (obj) => JSON.stringify(obj).replace(/[<>&]/g, (c) => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0')).split(String.fromCharCode(0x2028)).join('\\u2028').split(String.fromCharCode(0x2029)).join('\\u2029');

/**
 * From validated styles: the CSS variable lines (only for slots that were given, plus what must follow from them), the small object the
 * page reads, the page title, the bundled font files needed, notes (what was adjusted) and the contrast checks.
 */
export function deriveStyleOutput(styles) {
  const s = styles || {};
  const vars = {}, notes = [], checks = [];
  const bg = STAGE_BG;
  const panel = s.surface || DEFAULT_PANEL;
  // With NO cardText the look behaves exactly as before: one text color for the page and the cards, lightened until it reads on both.
  // With a cardText the text on the cards is its own color, checked against the card only; the text on the page (text, muted) is checked against the dark stage only.
  const hasCard = Boolean(s.cardText);
  const stageInk = s.text ? ensureContrast(s.text, bg, '#ffffff', 4.5) : DEFAULT_INK;
  const ink = hasCard ? stageInk : (s.text ? ensureContrast(stageInk, panel, '#ffffff', 4.5) : DEFAULT_INK);
  const cardInk = hasCard ? s.cardText : ink;
  const rgba = (hex, a) => `rgba(${rgb(hex).join(', ')}, ${a})`;
  if (s.text) {
    vars['--ink'] = ink;
    if (ink !== s.text) notes.push(hasCard
      ? `text ${s.text} reaches ${r2(contrast(s.text, bg))}:1 on the dark page (needs 4.5:1), so the page uses ${ink} instead`
      : `text ${s.text} is adjusted to ${ink} (${r2(contrast(ink, bg))}:1 on the dark page, ${r2(contrast(ink, panel))}:1 on the card) so it reads on the dark page and cards`);
  }
  if (s.muted) {
    const m = hasCard ? ensureContrast(s.muted, bg, ink, 4.5) : ensureContrast(ensureContrast(s.muted, bg, ink, 4.5), panel, ink, 4.5);
    vars['--muted'] = m; if (m !== s.muted) notes.push(`muted ${s.muted} is adjusted to ${m} (${r2(contrast(s.muted, bg))}:1 on the dark page before, needs 4.5:1)`);
  }
  if (hasCard) {
    vars['--rp-card-ink'] = cardInk;
    // The muted text on cards: its own color if given, otherwise a softer shade of the card text that still reads on the card.
    vars['--rp-card-muted'] = s.cardMuted || ensureContrast(mix(cardInk, panel, 0.35), panel, cardInk, 4.5);
  } else if (s.cardMuted) vars['--rp-card-muted'] = s.cardMuted;
  if (s.surface) { vars['--panel-solid'] = panel; vars['--panel'] = rgba(panel, 0.82); vars['--rp-card-solid'] = panel; vars['--rp-card-glass'] = rgba(panel, 0.9); }
  if (s.surface || s.text || hasCard) vars['--rp-card-edge'] = rgba(cardInk, 0.28);
  let accent = null;
  if (s.accent) { accent = s.accent; vars['--rp-accent'] = accent; vars['--rp-on-accent'] = readableOn(accent); }
  const linkIn = s.link || s.accent;
  if (linkIn) {
    // Links and the name sit on the cards. With a cardText they are checked against the card (toward the card text); otherwise against the stage and the card, as before.
    const l = hasCard ? ensureContrast(linkIn, panel, cardInk, 4.5) : ensureContrast(ensureContrast(linkIn, bg, '#ffffff', 4.5), panel, '#ffffff', 4.5);
    vars['--rp-link'] = l; if (l !== linkIn) notes.push(`${s.link ? 'link' : 'accent'} ${linkIn} is adjusted to ${l} for links and the name (${r2(contrast(linkIn, hasCard ? panel : bg))}:1 before, needs 4.5:1)`);
  }
  // The severity chips and the warning boxes use fixed pastel colors made for the default dark card. On a card where those do not read (a light card, a red card), the card gets its own
  // pairs (the same tints over this card, the text color pushed toward the card text until it reads), and a light card also gets dark-on-light borders and chip backgrounds.
  // defBg is what the stylesheet draws today (the tint over the card). If those pairs do not read, a light card uses the same tints with the text pushed toward the card text; a mid-tone or
  // dark card (a red card, say) gets a darker chip background, so the light text keeps its contrast.
  const lightCard = luminance(panel) > 0.4;
  let plainChip = mix(panel, '#ffffff', 0.08); // the plain chip's effective background
  const defBg = (k) => { const c = CHIPS.find((x) => x[0] === k); return mix(panel, c[1], c[2]); };
  const chipBg = (k) => (vars[`--rp-card-${k}-bg`] || defBg(k));
  if (s.surface) {
    if (!CHIPS.every(([k, , , fg]) => contrast(fg, defBg(k)) >= 4.5)) for (const [k, , , fg] of CHIPS) {
      let b = lightCard ? defBg(k) : mix(panel, '#000000', 0.22), f2 = ensureContrast(fg, b, cardInk, 4.5);
      if (contrast(f2, b) < 4.5) { b = panel; f2 = ensureContrast(fg, b, cardInk, 4.5); } // last resort: no tint, the chip is the card itself, so it reads whenever the card text does
      vars[`--rp-card-${k}-bg`] = b; vars[`--rp-card-${k}-fg`] = f2;
    }
    // The plain chip is the card text on a faint tint. On a light card the tint is a faint shade of the card text (weakened until the card text still reads on it); on a mid-tone card
    // (a red card) the default tint of white makes the light text read worse, so the tint becomes a slight shade instead.
    if (lightCard) {
      let a = 0.06; while (a > 0 && contrast(cardInk, mix(panel, cardInk, a)) < 4.5) a = Number((a - 0.02).toFixed(2));
      vars['--rp-card-line'] = rgba(cardInk, 0.16); vars['--rp-card-chip'] = rgba(cardInk, a); plainChip = mix(panel, cardInk, a);
    } else if (contrast(cardInk, mix(panel, '#ffffff', 0.08)) < 4.5) {
      const dark = contrast(cardInk, mix(panel, '#000000', 0.2)) >= 4.5; vars['--rp-card-chip'] = dark ? 'rgba(0, 0, 0, 0.2)' : 'rgba(0, 0, 0, 0)'; plainChip = dark ? mix(panel, '#000000', 0.2) : panel;
    }
  }
  if (s.secondary) { const c = ensureContrast(s.secondary, panel, hasCard ? cardInk : '#ffffff', 4.5); vars['--rp-secondary'] = c; if (c !== s.secondary) notes.push(`secondary ${s.secondary} is adjusted to ${c} (${r2(contrast(s.secondary, panel))}:1 on the card before, needs 4.5:1)`); }
  // A look that sets a card color but not the muted text, the second color or a link/accent color shows the BUILT-IN ones on that card (made for the dark card). On a card where they do not
  // read (a red or a light card, not a dark one) they are nudged toward the card text, like the ones a look sets itself, so no text on the card is left below 4.5:1.
  if (s.surface && luminance(panel) > 0.1) { // a dark card keeps the built-in colors exactly as before (they were made for it)
    if (!vars['--rp-card-muted'] && !vars['--muted'] && contrast(DEFAULT_MUTED, panel) < 4.5) { const c = ensureContrast(DEFAULT_MUTED, panel, cardInk, 4.5); vars['--rp-card-muted'] = c; notes.push(`the built-in muted text ${DEFAULT_MUTED} is adjusted to ${c} on this card (${r2(contrast(DEFAULT_MUTED, panel))}:1 before, needs 4.5:1)`); }
    if (!s.secondary && contrast(DEFAULT_SECONDARY, panel) < 4.5) { const c = ensureContrast(DEFAULT_SECONDARY, panel, hasCard ? cardInk : '#ffffff', 4.5); vars['--rp-secondary'] = c; notes.push(`the built-in second color ${DEFAULT_SECONDARY} is adjusted to ${c} on this card (${r2(contrast(DEFAULT_SECONDARY, panel))}:1 before, needs 4.5:1)`); }
    if (!linkIn && contrast(DEFAULT_ACCENT, panel) < 4.5) { const c = ensureContrast(DEFAULT_ACCENT, panel, hasCard ? cardInk : '#ffffff', 4.5); vars['--rp-link'] = c; notes.push(`the built-in link color ${DEFAULT_ACCENT} is adjusted to ${c} on this card (${r2(contrast(DEFAULT_ACCENT, panel))}:1 before, needs 4.5:1)`); }
  }
  // The cards are drawn at 82 to 90 percent of the card color over the dark stage, so the real card is a little DARKER than the color that was checked. That only helps light text,
  // but it lowers dark text on a light card (a light card read about 10 percent below its checked ratio). So when any text color on the card (the card text, the muted text, links,
  // the second color) is darker than the card, the cards are drawn opaque: the checked color is then the color on screen. Light text on a dark or mid-tone card keeps the glass look.
  if (s.surface) {
    const textCols = [cardInk, vars['--rp-card-muted'], vars['--rp-link'], vars['--rp-secondary']].filter(Boolean);
    if (textCols.some((c) => luminance(c) < luminance(panel))) { vars['--panel'] = panel; vars['--rp-card-glass'] = panel; }
  }
  // The muted label chips (Fetched, Raw, Lab) are the muted text on the faint tint of the plain chip. The tint lowers the muted text's ratio, so the chip gets its own text color: the
  // muted text pushed toward the card text until it reads on the chip. Only written when the muted text itself does not already read there.
  const labelBase = vars['--rp-card-muted'] || vars['--muted'] || (s.surface ? DEFAULT_MUTED : null);
  let labelFg = null, labelBg = null;
  if (labelBase && (s.surface || hasCard || s.cardMuted || s.muted)) {
    labelBg = s.surface ? plainChip : mix(panel, '#ffffff', 0.08);
    labelFg = ensureContrast(labelBase, labelBg, cardInk, 4.5);
    if (labelFg !== labelBase) vars['--rp-card-label-fg'] = labelFg;
  }
  const fonts = [];
  if (s.headingFont) { vars['--rp-font-heading'] = `"${s.headingFont}", ${SYSTEM_STACK}`; fonts.push(s.headingFont); }
  if (s.bodyFont) { vars['--rp-font-body'] = `"${s.bodyFont}", ${SYSTEM_STACK}`; if (!fonts.includes(s.bodyFont)) fonts.push(s.bodyFont); }
  if (s.headingCase) vars['--rp-heading-case'] = s.headingCase;
  // checks (the same pairs the build brand checks, for the values this file gives)
  // Each check names the style slot to blame (`slot`), so a message always names the slot, the two colors that were compared and the ratio of THAT pair.
  const pair = (what, fg, back, min, slot) => checks.push({ what, fg, bg: back, ratio: Number(contrast(fg, back).toFixed(2)), min, ok: contrast(fg, back) >= min, slot });
  const oldCard = !hasCard && Boolean(s.surface); // no cardText: the page colors must also read on the card, so a failure points at the card color
  pair('text on the stage background', ink, bg, 4.5, 'text'); pair('text on a card', cardInk, panel, 4.5, hasCard ? 'cardText' : (s.surface ? 'surface' : 'text'));
  if (vars['--muted']) { pair('muted text on the stage background', vars['--muted'], bg, 4.5, 'muted'); if (!hasCard) pair('muted text on a card', vars['--muted'], panel, 4.5, oldCard ? 'surface' : 'muted'); }
  if (vars['--rp-card-muted']) pair('muted text on a card', vars['--rp-card-muted'], panel, 4.5, s.cardMuted ? 'cardMuted' : 'cardText');
  if (vars['--rp-link']) { const ls = s.link ? 'link' : 'accent'; if (!hasCard) pair('links on the stage background', vars['--rp-link'], bg, 4.5, ls); pair('links on a card', vars['--rp-link'], panel, 4.5, oldCard ? 'surface' : ls); }
  if (accent) { pair('the accent on the stage background', accent, bg, 3, 'accent'); pair('text on an accent button', vars['--rp-on-accent'], accent, 4.5, 'accent'); }
  if (vars['--rp-secondary']) pair('the second color on a card', vars['--rp-secondary'], panel, 4.5, oldCard ? 'surface' : 'secondary');
  if (s.surface) pair('a plain chip on a card', cardInk, plainChip, 4.5, 'surface');
  if (labelFg) pair('a muted label chip on a card', labelFg, labelBg, 4.5, 'surface');
  for (const [k, , , defFg, label] of CHIPS) if (s.surface) pair(`${label} on a card`, vars[`--rp-card-${k}-fg`] || defFg, vars[`--rp-card-${k}-bg`] || chipBg(k), 4.5, 'surface');
  if (vars['--rp-card-edge']) { pair('the card edge against the card', mix(panel, cardInk, 0.28), panel, 1.5); pair('the card edge against the stage background', mix(bg, cardInk, 0.28), bg, 1.5); }
  const footer = s.footerText || (s.name ? `Prepared by ${s.name}` : undefined);
  const page = { v: STYLES_VERSION, ...(s.name ? { name: s.name } : {}), ...(footer ? { footer } : {}), ...(accent ? { accent } : {}), ...(s.headingCase ? { headingCase: s.headingCase } : {}), ...(s.headingFont ? { headingFont: s.headingFont } : {}), ...(s.bodyFont ? { bodyFont: s.bodyFont } : {}) };
  return { vars, notes, checks, fonts, page, titleText: s.name ? `${escHtml(s.name)} · Website health walkthrough` : null };
}

/** The bundled font files a list of font names needs: [{ family, file, weight }]. */
export function fontFilesFor(names) {
  const list = [];
  for (const n of names) if (has(BUNDLED_FONTS, n)) for (const f of BUNDLED_FONTS[n]) list.push({ family: n, file: f.file, weight: f.weight });
  return list;
}

const DATA_URL = /url\(data:font\/woff2;base64,[A-Za-z0-9+/=]+\)/g;
/** A last check on the finished CSS: only the characters this module writes, no @import, no outside url, no script words. */
export function cssIsSafe(css) {
  try {
    const rest = String(css).replace(DATA_URL, 'url(x)');
    if (!/^[A-Za-z0-9 #%.,:;"'\-_(){}@\n]*$/.test(rest)) return false;
    if (/url\((?!x\))/i.test(rest) || /@(?!font-face\{)/.test(rest) || /import|expression|javascript|behavior|binding/i.test(rest)) return false;
    return (rest.match(/\{/g) || []).length === (rest.match(/\}/g) || []).length;
  } catch { return false; }
}

/** The stylesheet text. `fontData` maps a bundled file name to its base64 text (the server reads and checks the files). Returns null if the guard fails. */
export function buildStyleCss(out, fontData = {}) {
  try {
    const faces = fontFilesFor(out.fonts).filter((f) => typeof fontData[f.file] === 'string' && /^[A-Za-z0-9+/=]+$/.test(fontData[f.file]))
      .map((f) => `@font-face{font-family:"${f.family}";font-style:normal;font-weight:${f.weight};font-display:block;src:url(data:font/woff2;base64,${fontData[f.file]}) format("woff2")}`);
    const lines = Object.entries(out.vars).map(([k, v]) => `${k}:${v}`).join(';');
    const css = `${faces.join('\n')}${faces.length ? '\n' : ''}.rp-root.rp-dark.rp-branded{${lines}}`;
    return cssIsSafe(css) ? css : null;
  } catch { return null; }
}
