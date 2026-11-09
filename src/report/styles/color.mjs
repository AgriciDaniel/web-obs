// Pure colour helpers shared by the build-time brand loader and the runtime styles validator (no file access, no packages, safe in the browser too).
/** The page and stage background in every build, with or without a brand. */
export const STAGE_BG = '#07090f';

// ---- colour maths (WCAG 2.x) ----
export const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
export const hexOf = ([r, g, b]) => '#' + [r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('');
export const luminance = (hex) => { const [r, g, b] = rgb(hex).map((v) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
export const contrast = (a, b) => { const x = luminance(a), y = luminance(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
export const mix = (a, b, t) => { const p = rgb(a), q = rgb(b); return hexOf(p.map((v, i) => v + (q[i] - v) * t)); };
/** The text colour (dark or light) that reads best on `bg`. */
export const readableOn = (bg, dark = '#10131a', light = '#ffffff') => (contrast(bg, dark) >= contrast(bg, light) ? dark : light);
/** Nudges `fg` toward `toward` until it reads at least `min` on `bg` (up to the target itself). */
export function ensureContrast(fg, bg, toward, min = 4.5) {
  let c = fg;
  for (let t = 0; t <= 1.0001 && contrast(c, bg) < min; t += 0.05) c = mix(fg, toward, t);
  return c;
}
