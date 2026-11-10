/** The two looks a user can pick. `classic` is the original solid orb; `translucent` is the newer one. */
export type NodeLook = 'classic' | 'translucent';

/**
 * How nodes look. Everything here can be changed without touching the renderer. A look is a preset of these
 * fields; `window.__WO_VISUAL__ = { defaultOpacity: 0.8 }` set before the map is built overrides single fields on
 * top of the chosen look. That is how sphere detail, opacity and halo weight are tuned against frame rate.
 */
export interface NodeVisualTuning {
  /** Sphere tessellation. Fixed by default so a node looks the same at every site size. */
  sphereWidthSegments: number;
  sphereHeightSegments: number;
  /** When true, big sites use coarser spheres (14x10 above 400 nodes, 10x8 above 1200) to save GPU time. */
  adaptiveSphereDetail: boolean;
  /** Opacity of an orb at rest. */
  defaultOpacity: number;
  /** Opacity of the selected or hovered orb, the orbs linked to it, and search matches. */
  highlightOpacity: number;
  /** Opacity of every other orb while something is selected, hovered or searched. */
  dimOpacity: number;
  /** Time for an opacity change to settle, in milliseconds. 0 changes it at once. */
  transitionMs: number;
  /** Emissive glow strength (the share of the orb's own colour added on top of its lighting). */
  glowDefault: number;
  glowSelected: number;
  glowDim: number;
  /** Halo ring opacity for the same three states. */
  haloAlphaDefault: number;
  haloAlphaSelected: number;
  haloAlphaDim: number;
  /** `ring` is the original band that grows with the orb; `hairline` is a ring a fixed number of screen pixels wide. */
  haloStyle: 'ring' | 'hairline';
  /** Hairline halo width in screen pixels. Only used when haloStyle is `hairline`. */
  haloWidthPx: number;
}

/** The original look: solid orbs, a ring halo that grows with the orb, 22x22 spheres, changes apply at once. */
export const CLASSIC_NODE_VISUALS: NodeVisualTuning = {
  sphereWidthSegments: 22,
  sphereHeightSegments: 22,
  adaptiveSphereDetail: false,
  defaultOpacity: 1,
  highlightOpacity: 1,
  dimOpacity: 1,
  transitionMs: 0,
  glowDefault: 0.32,
  glowSelected: 0.85,
  glowDim: 0.08,
  haloAlphaDefault: 0.28,
  haloAlphaSelected: 0.85,
  haloAlphaDim: 0.05,
  haloStyle: 'ring',
  haloWidthPx: 1,
};

/** The newer look: translucent orbs, selection dims the rest, hairline halos, changes ease over a quarter second. */
export const TRANSLUCENT_NODE_VISUALS: NodeVisualTuning = {
  ...CLASSIC_NODE_VISUALS,
  defaultOpacity: 0.69,
  dimOpacity: 0.2,
  transitionMs: 240,
  haloStyle: 'hairline',
  haloWidthPx: 1,
};

export const NODE_LOOK_PRESETS: Record<NodeLook, NodeVisualTuning> = {
  classic: CLASSIC_NODE_VISUALS,
  translucent: TRANSLUCENT_NODE_VISUALS,
};

export const DEFAULT_NODE_LOOK: NodeLook = 'classic';
export const DEFAULT_NODE_VISUALS: NodeVisualTuning = NODE_LOOK_PRESETS[DEFAULT_NODE_LOOK];

/** The look's preset with any `window.__WO_VISUAL__` fields applied on top (a developer override). */
export function resolveNodeVisuals(look: NodeLook): NodeVisualTuning {
  const host = typeof window === 'undefined' ? undefined : (window as { __WO_VISUAL__?: Partial<NodeVisualTuning> });
  const override = host?.__WO_VISUAL__;
  return { ...NODE_LOOK_PRESETS[look], ...(override ?? {}) };
}
