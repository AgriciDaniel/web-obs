/**
 * The site's own mark for the centre of the map: a logo file from the capture and an accent colour.
 *
 * Everything here is read from evidence the capture already saved (brandKit and resources), so a
 * capture made before this feature gets a mark too. Nothing is fetched. The capture never inspects
 * a logo visually, so the choice is a best guess, and the map keeps the domain label beside it.
 */
import type { SiteGraphManifest, ThemeMode } from '../types/site';

export type BrandLogoSource = 'brand-logo' | 'touch-icon' | 'favicon';
export type BrandColorSource = 'theme-color' | 'stylesheet';

export interface BrandMark {
  /** Brand name when the capture found one, otherwise the domain. */
  label: string;
  initials: string;
  /** The best candidate; `logoCandidates` holds it first, then the fallbacks in order. */
  logo: { path: string; source: BrandLogoSource } | null;
  logoCandidates: Array<{ path: string; source: BrandLogoSource }>;
  color: { hex: string; declared: string; source: BrandColorSource } | null;
}

/** Map surfaces from theme.css (--bg-inner); the ring is checked against these. */
export const MAP_SURFACE: Record<ThemeMode, string> = { dark: '#141414', light: '#fafafa' };
/** WCAG 2.2 non-text contrast for a graphic object. */
export const MIN_RING_CONTRAST = 3;
/** Below this OKLCH chroma a colour reads as grey or near black, which says little about a brand. */
export const MIN_BRAND_CHROMA = 0.07;

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'webp', 'gif', 'svg', 'ico', 'avif']);

interface BrandKitLike {
  themeColor?: unknown;
  localLogoAsset?: unknown;
  localFaviconAsset?: unknown;
  faviconUrls?: unknown;
  palette?: unknown;
}

// ---------------------------------------------------------------------------------------------
// Colour maths (sRGB <-> OKLab), enough to judge chroma and contrast without a library.

type Rgb = [number, number, number];

function parseCssColor(value: string): { rgb: Rgb; alpha: number } | null {
  const text = value.trim().toLowerCase();
  const hex = /^#([0-9a-f]{3,8})$/.exec(text);
  if (hex) {
    let digits = hex[1];
    if (digits.length === 3 || digits.length === 4) digits = digits.split('').map((d) => d + d).join('');
    if (digits.length !== 6 && digits.length !== 8) return null;
    const n = (i: number) => parseInt(digits.slice(i, i + 2), 16);
    return { rgb: [n(0), n(2), n(4)], alpha: digits.length === 8 ? n(6) / 255 : 1 };
  }
  const fn = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+%?))?\s*\)$/.exec(text);
  if (fn) {
    const alphaText = fn[4];
    const alpha = alphaText === undefined ? 1 : alphaText.endsWith('%') ? parseFloat(alphaText) / 100 : parseFloat(alphaText);
    const channels = [fn[1], fn[2], fn[3]].map((c) => Math.max(0, Math.min(255, Math.round(parseFloat(c))))) as Rgb;
    return Number.isFinite(alpha) ? { rgb: channels, alpha } : null;
  }
  return null;
}

const toLinear = (c: number) => { const v = c / 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
const fromLinear = (v: number) => 255 * (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055);

function rgbToOklch([r, g, b]: Rgb): [number, number, number] {
  const [lr, lg, lb] = [toLinear(r), toLinear(g), toLinear(b)];
  const l = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb);
  const m = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb);
  const s = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb);
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  return [L, Math.hypot(A, B), Math.atan2(B, A)];
}

/** OKLCH to sRGB; null when the colour falls outside the sRGB gamut. */
function oklchToRgb(L: number, C: number, h: number): Rgb | null {
  const A = C * Math.cos(h); const B = C * Math.sin(h);
  const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3;
  const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3;
  const s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3;
  const linear = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ];
  if (linear.some((v) => v < -1e-4 || v > 1 + 1e-4)) return null;
  return linear.map((v) => Math.round(fromLinear(Math.max(0, Math.min(1, v))))) as Rgb;
}

const toHex = (rgb: Rgb) => '#' + rgb.map((c) => c.toString(16).padStart(2, '0')).join('');

export function relativeLuminance(hex: string): number {
  const parsed = parseCssColor(hex);
  if (!parsed) return 0;
  const [r, g, b] = parsed.rgb.map(toLinear);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

export function oklchChroma(color: string): number {
  const parsed = parseCssColor(color);
  return parsed ? rgbToOklch(parsed.rgb)[1] : 0;
}

/**
 * The brand colour stepped in lightness, keeping its hue, until it has at least 3:1 contrast with
 * the map surface. Chroma is reduced only as far as the sRGB gamut requires.
 */
export function ringColorFor(hex: string, theme: ThemeMode): string {
  const parsed = parseCssColor(hex);
  if (!parsed) return hex;
  const surface = MAP_SURFACE[theme];
  const original = toHex(parsed.rgb);
  if (contrastRatio(original, surface) >= MIN_RING_CONTRAST) return original;
  const [L0, C0, h] = rgbToOklch(parsed.rgb);
  const step = theme === 'dark' ? 0.01 : -0.01;
  for (let L = L0 + step; L > 0.02 && L < 0.98; L += step) {
    for (let C = C0; C >= 0; C -= 0.005) {
      const rgb = oklchToRgb(L, C, h);
      if (!rgb) continue;
      const candidate = toHex(rgb);
      if (contrastRatio(candidate, surface) >= MIN_RING_CONTRAST) return candidate;
      break;
    }
  }
  return theme === 'dark' ? '#ffffff' : '#000000';
}

/** Near-black or white text, whichever reads better on the given fill. */
export function inkOn(fill: string): string {
  return contrastRatio(fill, '#111111') >= contrastRatio(fill, '#ffffff') ? '#111111' : '#ffffff';
}

// ---------------------------------------------------------------------------------------------
// Selection

function safeSitePath(value: unknown, siteId: string): string | null {
  if (typeof value !== 'string') return null;
  const path = value.trim();
  if (!path.startsWith(`sites/${siteId}/`) || path.includes('\\') || path.split('/').some((part) => part === '..' || part === '.' || part === '')) return null;
  const ext = path.split('.').pop()?.toLowerCase() ?? '';
  return IMAGE_EXTENSIONS.has(ext) ? path : null;
}

/** Largest pixel size a favicon URL or file name declares, such as 512x512 or icon-192. */
function declaredIconSize(text: string): number {
  const lower = text.toLowerCase();
  const square = /(\d{2,4})x(\d{2,4})/.exec(lower);
  if (square) return Math.max(parseInt(square[1], 10), parseInt(square[2], 10));
  const single = /[-_.](\d{2,4})(?=[-_.])/.exec(lower);
  if (single) return parseInt(single[1], 10);
  if (lower.includes('apple-touch-icon')) return 180; // its default size
  return 0;
}

function iconScore(url: string, path: string): number {
  const ext = path.split('.').pop()?.toLowerCase() ?? '';
  if (ext === 'svg') return 4000; // scales cleanly at any size
  const size = declaredIconSize(url) || declaredIconSize(path);
  return size + (ext === 'ico' ? -100 : 0) + (url.toLowerCase().includes('apple-touch-icon') ? 1 : 0);
}

function logoCandidates(manifest: SiteGraphManifest, kit: BrandKitLike): BrandMark['logoCandidates'] {
  const logo = safeSitePath(kit.localLogoAsset, manifest.siteId);
  const declared = new Set(Array.isArray(kit.faviconUrls) ? kit.faviconUrls.filter((u): u is string => typeof u === 'string') : []);
  const icons: Array<{ path: string; score: number; touch: boolean }> = [];
  for (const resource of manifest.resources ?? []) {
    const path = safeSitePath(resource.localPath, manifest.siteId);
    if (!path || resource.type !== 'image') continue;
    const url = resource.url || '';
    const lower = url.toLowerCase();
    if (!declared.has(url) && !lower.includes('apple-touch-icon') && !/\/favicon[^/]*$/.test(lower)) continue;
    icons.push({ path, score: iconScore(url, path), touch: lower.includes('apple-touch-icon') });
  }
  const fallback = safeSitePath(kit.localFaviconAsset, manifest.siteId);
  if (fallback && !icons.some((icon) => icon.path === fallback)) icons.push({ path: fallback, score: iconScore(fallback, fallback), touch: false });
  icons.sort((a, b) => b.score - a.score || a.path.localeCompare(b.path));
  const ordered: BrandMark['logoCandidates'] = logo ? [{ path: logo, source: 'brand-logo' }] : [];
  for (const icon of icons) {
    if (!ordered.some((c) => c.path === icon.path)) ordered.push({ path: icon.path, source: icon.touch ? 'touch-icon' : 'favicon' });
  }
  return ordered.slice(0, 4);
}

function usableBrandColor(declared: unknown): { hex: string; declared: string } | null {
  if (typeof declared !== 'string') return null;
  const parsed = parseCssColor(declared);
  // A translucent tint (for example #e0785026, the brand colour at 15%) still names the brand colour;
  // only a fully transparent value says nothing.
  if (!parsed || parsed.alpha <= 0.01) return null;
  const hex = toHex(parsed.rgb);
  return oklchChroma(hex) >= MIN_BRAND_CHROMA ? { hex, declared: declared.trim() } : null;
}

function pickColor(kit: BrandKitLike): BrandMark['color'] {
  const theme = usableBrandColor(kit.themeColor);
  if (theme) return { ...theme, source: 'theme-color' };
  for (const entry of Array.isArray(kit.palette) ? kit.palette : []) {
    if (!entry || typeof entry !== 'object') continue;
    const row = entry as { declared?: unknown; hex?: unknown; candidateRole?: unknown };
    if (row.candidateRole !== undefined && row.candidateRole !== 'chromatic') continue;
    const color = usableBrandColor(row.declared ?? row.hex);
    if (color) return { ...color, source: 'stylesheet' };
  }
  return null;
}

export function brandInitials(label: string): string {
  const words = label.replace(/^https?:\/\//i, '').replace(/^www\./i, '').split(/[\s._-]+/).filter((w) => /[\p{L}\p{N}]/u.test(w));
  if (words.length === 0) return '?';
  const letters = words.length > 1 && !/\.[a-z]{2,}$/i.test(label) ? words[0][0] + words[1][0] : words[0].slice(0, 2);
  return letters.toLocaleUpperCase();
}

export function pickBrandMark(manifest: SiteGraphManifest | null): BrandMark | null {
  if (!manifest) return null;
  const kit = (manifest.brandKit ?? {}) as BrandKitLike;
  const label = (typeof manifest.brandName === 'string' && manifest.brandName.trim()) || manifest.domain || manifest.siteId;
  const candidates = logoCandidates(manifest, kit);
  return { label, initials: brandInitials(label), logo: candidates[0] ?? null, logoCandidates: candidates, color: pickColor(kit) };
}
