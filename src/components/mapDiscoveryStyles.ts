export const mapDiscoveryStyles = `
.wo-canvas-stage { container-name: wo-map; container-type: size; }
.wo-shell .wo-discovery-layer { position: absolute; left: 16px; right: 16px; bottom: 16px; z-index: 6; display: flex; justify-content: flex-start; pointer-events: none; max-height: calc(100% - 32px); }
.wo-shell .wo-discovery-layer button { font: inherit; cursor: pointer; }
.wo-shell .wo-discovery-layer button > svg { flex-shrink: 0; }
.wo-shell .wo-discovery-layer button:disabled { opacity: .4; cursor: default; }
.wo-shell .wo-discovery-layer button:focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 3px; }
.wo-shell .wo-discovery-launcher { display: flex; gap: 4px; padding: 5px; border: 1px solid var(--border-strong); background: var(--bg-panel-solid); border-radius: 14px; box-shadow: 0 8px 28px #0002; pointer-events: auto; }
.wo-shell .wo-discovery-start, .wo-shell .wo-discovery-shuffle { display: flex; align-items: center; justify-content: center; gap: 9px; min-height: 38px; border: 0; border-radius: 10px; background: transparent; color: var(--ink-primary); padding: 0 12px; font-size: 12px !important; }
.wo-shell .wo-discovery-start { background: var(--accent-soft); }
.wo-shell .wo-discovery-start > svg { color: var(--accent-bright); transition: transform .2s ease; }
.wo-shell .wo-discovery-start:hover > svg { transform: rotate(-18deg); }
.wo-shell .wo-discovery-start small { margin-left: 4px; color: var(--ink-secondary); font-size: 10px; font-variant-numeric: tabular-nums; }
.wo-shell .wo-discovery-shuffle { color: var(--ink-secondary); padding: 0 10px; }
.wo-shell .wo-discovery-shuffle:hover { background: var(--bg-subtle); color: var(--ink-primary); }
.wo-shell .wo-discovery-card { width: min(352px, 100%); overflow-y: auto; padding: 14px; border: 1px solid var(--border-strong); border-radius: 16px; background: var(--bg-panel-solid); color: var(--ink-primary); box-shadow: 0 12px 36px #0003; pointer-events: auto; }
.wo-shell .wo-discovery-head { display: flex; align-items: center; gap: 8px; color: var(--accent-bright); }
.wo-shell .wo-discovery-head > span { font-size: 9px; letter-spacing: .11em; font-weight: 700; }
.wo-shell .wo-discovery-head > small { color: var(--ink-secondary); margin-left: auto; font-size: 10px; font-variant-numeric: tabular-nums; }
.wo-shell .wo-discovery-dismiss { border: 0; background: transparent; color: var(--ink-secondary); padding: 3px; display: inline-flex; border-radius: 5px; margin-right: -3px; }
.wo-shell .wo-discovery-dismiss:hover { color: var(--ink-primary); background: var(--bg-subtle); }
.wo-shell .wo-discovery-kicker { display: block; margin: 11px 0 4px; font-size: 10px; color: var(--hub); }
.wo-shell .wo-discovery-title { font-size: 16px; font-weight: 650; letter-spacing: -.025em; line-height: 1.3; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wo-shell .wo-discovery-path { font-size: 10px; color: var(--ink-secondary); margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wo-shell .wo-discovery-description { color: var(--ink-secondary); font-size: 11px; line-height: 1.5; margin: 8px 0 10px; }
.wo-shell .wo-discovery-links { border-top: 1px solid var(--border-hairline); padding-top: 9px; margin: 0 0 10px; }
.wo-shell .wo-discovery-links > span { font-size: 9px; letter-spacing: .08em; color: var(--ink-secondary); text-transform: uppercase; }
.wo-shell .wo-discovery-peers { display: flex; gap: 5px; margin-top: 7px; flex-wrap: wrap; }
.wo-shell .wo-discovery-peer { display: flex; align-items: center; gap: 5px; min-width: 0; max-width: 100%; padding: 5px 7px; border: 1px solid var(--border-hairline); border-radius: 7px; background: transparent; color: var(--ink-secondary); font-size: 10px !important; }
.wo-shell .wo-discovery-peer > span { max-width: 190px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wo-shell .wo-discovery-peer > svg { color: var(--hub); flex-shrink: 0; }
.wo-shell .wo-discovery-peer:hover { border-color: var(--hub); color: var(--ink-primary); background: var(--bg-subtle); }
.wo-shell .wo-discovery-actions { display: flex; align-items: center; gap: 7px; }
.wo-shell .wo-discovery-step { padding: 0; min-width: 30px; min-height: 30px; display: flex; justify-content: center; align-items: center; border: 1px solid var(--border-hairline); border-radius: 8px; background: transparent; color: var(--ink-secondary); }
.wo-shell .wo-discovery-step:hover { background: var(--bg-subtle); color: var(--ink-primary); }
.wo-shell .wo-discovery-pagination { display: flex; gap: 4px; align-items: center; justify-content: center; flex: 1; }
.wo-shell .wo-discovery-pagination > span { width: 5px; height: 5px; border-radius: 50%; background: var(--border-strong); transition: width .18s, background .18s; }
.wo-shell .wo-discovery-pagination > span.is-current { width: 17px; border-radius: 5px; background: var(--accent-bright); }
.wo-shell .wo-discovery-random { display: flex; gap: 6px; align-items: center; justify-content: center; min-height: 30px; padding: 0 9px; border: 1px solid var(--border-hairline); border-radius: 8px; background: var(--accent-soft); color: var(--accent-bright); font-size: 10px !important; }
.wo-shell .wo-discovery-random:hover { border-color: var(--accent-bright); }
.wo-shell .wo-discovery-inspect { display: flex; align-items: center; gap: 4px; min-height: 30px; padding: 0 7px; border: 1px solid var(--border-hairline); border-radius: 8px; background: transparent; color: var(--ink-secondary); font-size: 10px !important; }
.wo-shell .wo-discovery-inspect:hover { border-color: var(--accent-bright); color: var(--ink-primary); }
@container wo-map (max-height: 560px) {
  .wo-shell .wo-discovery-card { padding: 12px; }
  .wo-shell .wo-discovery-description, .wo-shell .wo-discovery-path { display: none; }
  .wo-shell .wo-discovery-peers { flex-wrap: nowrap; }
  .wo-shell .wo-discovery-peer { flex: 1; }
  .wo-shell .wo-discovery-title { font-size: 14px; margin-bottom: 10px; }
  .wo-shell .wo-discovery-kicker { margin-top: 9px; }
}
@container wo-map (max-height: 360px) { .wo-discovery-links { display: none; } }
@container wo-map (max-width: 380px) {
  .wo-shell .wo-discovery-layer { left: 8px; right: 8px; bottom: 92px; max-height: calc(100% - 100px); }
  .wo-shell .wo-discovery-start { padding: 0 8px; gap: 6px; }
  .wo-shell .wo-discovery-start small { display: none; }
  .wo-shell .wo-discovery-shuffle { padding: 0 8px; }
  .wo-shell .wo-discovery-pagination, .wo-shell .wo-discovery-random span { display: none; }
}
@container web-obs (max-width: 600px) {
  .wo-explorer-open .wo-discovery-layer, .wo-inspector-open .wo-discovery-layer { visibility: hidden; }
}
@media (prefers-reduced-motion: reduce) {
  .wo-shell .wo-discovery-layer *, .wo-shell .wo-discovery-layer *::before { transition: none !important; animation: none !important; }
}
`;
