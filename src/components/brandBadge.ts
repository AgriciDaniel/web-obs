/**
 * Draws the round brand badge that replaces the home sphere: the site's logo on a backing that keeps
 * it visible, inside a ring in the brand colour. Without a logo it shows the brand's initials.
 *
 * The logo arrives as bytes read from the vault and is decoded from a blob URL, which is same-origin,
 * so the canvas stays untainted and WebGL accepts it.
 */
import { type BrandMark, MAP_SURFACE, contrastRatio, inkOn, ringColorFor } from '../data/brandMark';
import type { ThemeMode } from '../types/site';

export const BADGE_PX = 256;
const RING_PX = 14;
const DARK_BACKING = '#161616';
const LIGHT_BACKING = '#f7f7f7';

export interface LogoTone {
  /** Fill behind the logo. */
  backing: string;
  /** True when the image paints its own background to the edges (a square app icon, for example). */
  ownBackground: boolean;
  /** Painted share of the image, 0 to 1, weighted by opacity. */
  coverage: number;
  /** Painted area as fractions of the image, so transparent padding can be trimmed. */
  crop?: { x: number; y: number; w: number; h: number };
}

const MIME: Record<string, string> = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif',
  svg: 'image/svg+xml', ico: 'image/x-icon', avif: 'image/avif',
};

const RASTER_PX = 512;

/**
 * Decodes the logo and rasterises it once at up to 512 px on its long side. Working from a raster
 * keeps sampling and cropping identical for PNG and SVG, whose source rectangles Chrome measures in
 * the SVG's own intrinsic units.
 */
export async function decodeLogo(bytes: ArrayBuffer, path: string): Promise<HTMLCanvasElement | null> {
  const ext = path.split('.').pop()?.toLowerCase() ?? '';
  const type = MIME[ext];
  if (!type || bytes.byteLength === 0) return null;
  const url = URL.createObjectURL(new Blob([bytes], { type }));
  try {
    const img = new Image();
    img.decoding = 'async';
    img.src = url;
    await img.decode();
    const iw = img.naturalWidth; const ih = img.naturalHeight;
    const scale = iw > 0 && ih > 0 ? RASTER_PX / Math.max(iw, ih) : 1;
    const raster = document.createElement('canvas');
    raster.width = iw > 0 && ih > 0 ? Math.max(1, Math.round(iw * scale)) : RASTER_PX;
    raster.height = iw > 0 && ih > 0 ? Math.max(1, Math.round(ih * scale)) : RASTER_PX;
    const ctx = raster.getContext('2d');
    if (!ctx) return null;
    ctx.drawImage(img, 0, 0, raster.width, raster.height);
    return raster;
  } catch {
    return null;
  } finally {
    URL.revokeObjectURL(url);
  }
}

const hex2 = (n: number) => Math.round(Math.max(0, Math.min(255, n))).toString(16).padStart(2, '0');

/** Share of the image that must be painted before it counts as a usable mark. */
export const MIN_LOGO_COVERAGE = 0.01;

/**
 * Most logos are drawn for a white page, and soft or semi-transparent marks only read on light, so a
 * light backing is the default. A dark one is used only when the ink itself is light (a white or pale
 * logo), where light would leave it under 2:1.
 */
export function backingForInk(ink: string): string {
  return contrastRatio(ink, LIGHT_BACKING) < 2 && contrastRatio(ink, DARK_BACKING) > contrastRatio(ink, LIGHT_BACKING) ? DARK_BACKING : LIGHT_BACKING;
}

/**
 * Samples the logo to choose its backing. An image with an opaque border keeps that border colour,
 * so the badge looks continuous. For a transparent logo every visible pixel counts by its opacity
 * (watercolour and anti-aliased marks are mostly partial alpha), and `backingForInk` picks the
 * backing, so a white logo never vanishes on a white surface.
 * `coverage` near zero means the file paints almost nothing, such as an icon drawn with
 * `currentColor` that has no colour outside its page.
 */
export function analyseLogo(img: HTMLCanvasElement): LogoTone {
  const size = 48;
  const canvas = document.createElement('canvas');
  canvas.width = size; canvas.height = size;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) return { backing: LIGHT_BACKING, ownBackground: false, coverage: 1 };
  ctx.drawImage(img, 0, 0, size, size);
  let data: Uint8ClampedArray;
  try {
    data = ctx.getImageData(0, 0, size, size).data;
  } catch {
    return { backing: LIGHT_BACKING, ownBackground: false, coverage: 1 };
  }
  let edge = 0; let edgeOpaque = 0; let er = 0; let eg = 0; let eb = 0;
  let alphaSum = 0; let ir = 0; let ig = 0; let ib = 0;
  let minX = size; let minY = size; let maxX = -1; let maxY = -1;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const i = (y * size + x) * 4;
      const a = data[i + 3] / 255;
      if (x < 2 || y < 2 || x >= size - 2 || y >= size - 2) {
        edge++;
        if (a > 0.9) { edgeOpaque++; er += data[i]; eg += data[i + 1]; eb += data[i + 2]; }
      }
      if (a > 0.04) {
        alphaSum += a; ir += data[i] * a; ig += data[i + 1] * a; ib += data[i + 2] * a;
        if (x < minX) minX = x; if (x > maxX) maxX = x; if (y < minY) minY = y; if (y > maxY) maxY = y;
      }
    }
  }
  const coverage = alphaSum / (size * size);
  if (edgeOpaque / edge >= 0.85) {
    return { backing: `#${hex2(er / edgeOpaque)}${hex2(eg / edgeOpaque)}${hex2(eb / edgeOpaque)}`, ownBackground: true, coverage };
  }
  if (alphaSum === 0) return { backing: LIGHT_BACKING, ownBackground: false, coverage: 0 };
  const ink = `#${hex2(ir / alphaSum)}${hex2(ig / alphaSum)}${hex2(ib / alphaSum)}`;
  // One sample pixel of slack on each side keeps anti-aliased edges.
  const x0 = Math.max(0, minX - 1); const y0 = Math.max(0, minY - 1);
  const x1 = Math.min(size, maxX + 2); const y1 = Math.min(size, maxY + 2);
  const crop = { x: x0 / size, y: y0 / size, w: (x1 - x0) / size, h: (y1 - y0) / size };
  return { backing: backingForInk(ink), ownBackground: false, coverage, crop };
}

export interface BadgeColors {
  ring: string;
  fill: string;
}

/** Ring and initials fill for a theme. `fallback` is the map's own home colour. */
export function badgeColors(mark: BrandMark, theme: ThemeMode, fallback: string): BadgeColors {
  const ring = mark.color ? ringColorFor(mark.color.hex, theme) : fallback;
  return { ring, fill: ring };
}

function drawImageContained(ctx: CanvasRenderingContext2D, img: HTMLCanvasElement, cx: number, cy: number, box: number, crop?: LogoTone['crop']) {
  const iw = img.width || 1; const ih = img.height || 1;
  const sx = crop ? crop.x * iw : 0; const sy = crop ? crop.y * ih : 0;
  const sw = crop ? crop.w * iw : iw; const sh = crop ? crop.h * ih : ih;
  const scale = box / Math.max(sw, sh);
  const dw = sw * scale; const dh = sh * scale;
  ctx.drawImage(img, sx, sy, sw, sh, cx - dw / 2, cy - dh / 2, dw, dh);
}

/**
 * Paints the badge. Returns false when the canvas could not be read back (tainted), in which case
 * the caller must not upload it to WebGL.
 */
export function drawBrandBadge(
  canvas: HTMLCanvasElement,
  mark: BrandMark,
  colors: BadgeColors,
  logo: { img: HTMLCanvasElement; tone: LogoTone } | null,
): boolean {
  canvas.width = BADGE_PX; canvas.height = BADGE_PX;
  const ctx = canvas.getContext('2d');
  if (!ctx) return false;
  const c = BADGE_PX / 2;
  const ringRadius = c - RING_PX / 2 - 1;
  const inner = ringRadius - RING_PX / 2;
  ctx.clearRect(0, 0, BADGE_PX, BADGE_PX);

  ctx.save();
  ctx.beginPath();
  ctx.arc(c, c, inner + 0.5, 0, Math.PI * 2);
  ctx.closePath();
  ctx.fillStyle = logo ? logo.tone.backing : colors.fill;
  ctx.fill();
  ctx.clip();
  if (logo) {
    // The largest square inside the circle is 0.707 of its diameter; a little less leaves air.
    drawImageContained(ctx, logo.img, c, c, inner * 2 * (logo.tone.ownBackground ? 0.8 : 0.68), logo.tone.ownBackground ? undefined : logo.tone.crop);
  } else {
    const text = mark.initials.slice(0, 2);
    ctx.fillStyle = inkOn(colors.fill);
    ctx.font = `700 ${Math.round(BADGE_PX * (text.length > 1 ? 0.34 : 0.42))}px system-ui, -apple-system, "Segoe UI", sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, c, c + BADGE_PX * 0.02);
  }
  ctx.restore();

  ctx.beginPath();
  ctx.arc(c, c, ringRadius, 0, Math.PI * 2);
  ctx.lineWidth = RING_PX;
  ctx.strokeStyle = colors.ring;
  ctx.stroke();

  try {
    ctx.getImageData(0, 0, 1, 1);
    return true;
  } catch {
    return false;
  }
}

/** True when the ring is distinguishable from the map surface; exposed for tests and diagnostics. */
export function ringPassesContrast(ring: string, theme: ThemeMode): boolean {
  return contrastRatio(ring, MAP_SURFACE[theme]) >= 3;
}
