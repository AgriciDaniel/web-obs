import type { SiteEdge, SiteGraphManifest, SiteNode } from '../types/site';

export const GLOBE_HUB_RADIUS = 3.05;
export const GLOBE_SURFACE_RADIUS = 5.35;
export const GLOBE_ORPHAN_RADIUS = 5.35;
export const GLOBE_EXTERNAL_RADIUS = 7.85;

export interface SectionSector {
  id: string;
  label: string;
  startAngle: number;
  endAngle: number;
  midAngle: number;
  pageCount: number;
}

export interface ComputedSiteLayouts {
  sectors: SectionSector[];
  globe: Map<string, [number, number, number]>;
  road: Map<string, [number, number, number]>;
  clusters: Map<string, [number, number, number]>;
}

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

function sphericalToWorld(
  radius: number,
  azimuth: number,
  latitudeRad: number
): [number, number, number] {
  const cosLat = Math.cos(latitudeRad);
  const x = radius * cosLat * Math.sin(azimuth);
  const y = radius * Math.sin(latitudeRad);
  const z = radius * cosLat * Math.cos(azimuth);
  return [x, y, z];
}

/**
 * Computes deterministic, non-overlapping 3D coordinates for:
 * 1. `globe`: Concentric Cartographic Site Globe
 *    - Core [0,0,0]: Homepage (`/`)
 *    - Inner Hub Shell (R=3.05): Section root / pillar pages on their meridian
 *    - Main Domain Surface (R=5.35): Child pages packed cleanly inside their section's longitude slice
 *    - South Polar Drift Ring: Orphan pages (in sitemap, 0 incoming links) so isolated pages stand out
 *    - Outer Satellite Orbit (R=7.85): External domains positioned near the azimuth of linking pages
 * 2. `road`: Layered Click-Depth Sitemap Funnel (D0 -> D1 -> D2 -> D3+ -> Orphans -> External)
 * 3. `clusters`: 3D Force-Directed Link Authority Clusters
 */
export function computeSiteLayouts(manifest: SiteGraphManifest): ComputedSiteLayouts {
  const globe = new Map<string, [number, number, number]>();
  const road = new Map<string, [number, number, number]>();
  const clusters = new Map<string, [number, number, number]>();

  const nodes = manifest.nodes;
  const edges = manifest.edges;

  const homeNode =
    nodes.find((n) => n.kind === 'home') ??
    nodes.find((n) => n.path === '/') ??
    nodes[0];

  const internalNonHome = nodes.filter(
    (n) => n.kind !== 'external-domain' && n.id !== homeNode?.id
  );
  const externalNodes = nodes.filter((n) => n.kind === 'external-domain');

  // Group internal non-home nodes by section
  const bySection = new Map<string, SiteNode[]>();
  for (const n of internalNonHome) {
    const sec = n.section || 'root';
    let list = bySection.get(sec);
    if (!list) {
      list = [];
      bySection.set(sec, list);
    }
    list.push(n);
  }

  const sortedSections = Array.from(bySection.entries()).sort(
    (a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0])
  );

  const totalWeight = Math.max(
    1,
    sortedSections.reduce((acc, [, arr]) => acc + Math.max(1.5, Math.sqrt(arr.length) + arr.length * 0.45), 0)
  );

  const sectors: SectionSector[] = [];
  const sectorById = new Map<string, SectionSector>();
  let cursorAngle = 0;

  for (const [secId, arr] of sortedSections) {
    const weight = Math.max(1.5, Math.sqrt(arr.length) + arr.length * 0.45);
    const span = (weight / totalWeight) * Math.PI * 2;
    const startAngle = cursorAngle;
    const endAngle = cursorAngle + span;
    const midAngle = (startAngle + endAngle) * 0.5;
    cursorAngle = endAngle;

    const sector: SectionSector = {
      id: secId,
      label: secId === 'root' ? '/' : `/${secId}`,
      startAngle,
      endAngle,
      midAngle,
      pageCount: arr.length,
    };
    sectors.push(sector);
    sectorById.set(secId, sector);
  }

  // 1. GLOBE LAYOUT
  if (homeNode) {
    globe.set(homeNode.id, [0, 0, 0]);
  }

  const orphans: SiteNode[] = [];

  for (const [secId, arr] of sortedSections) {
    const sec = sectorById.get(secId)!;
    const usableSpan = Math.max(0.18, (sec.endAngle - sec.startAngle) * 0.8);

    const hubs = arr.filter((n) => n.kind === 'hub' && n.health !== 'orphan');
    const regularPages = arr.filter((n) => n.kind !== 'hub' && n.health !== 'orphan');
    const secOrphans = arr.filter((n) => n.health === 'orphan');
    orphans.push(...secOrphans);

    // Place section hubs on Inner Hub Shell (R = 3.05)
    hubs.sort((a, b) => b.inlinksTotal - a.inlinksTotal || a.path.localeCompare(b.path));
    hubs.forEach((hub, idx) => {
      const frac = hubs.length === 1 ? 0 : (idx / (hubs.length - 1) - 0.5);
      const az = sec.midAngle + frac * Math.min(usableSpan * 0.65, 0.7);
      const lat = hubs.length === 1 ? 0.22 : 0.28 - (idx % 2) * 0.34;
      globe.set(hub.id, sphericalToWorld(GLOBE_HUB_RADIUS, az, lat));
    });

    // Place section child pages on Main Domain Globe Surface (R = 5.35)
    regularPages.sort(
      (a, b) =>
        (a.clickDepth ?? 9) - (b.clickDepth ?? 9) ||
        b.inlinksBody - a.inlinksBody ||
        a.path.localeCompare(b.path)
    );

    const count = regularPages.length;
    regularPages.forEach((page, idx) => {
      // Spread across latitude (+48 deg down to -42 deg) by depth + index, and across sector azimuth using golden ratio offset
      const t = count === 1 ? 0.5 : idx / (count - 1);
      const latDeg = count === 1 ? 8 : 46 - t * 86;
      const latRad = (latDeg * Math.PI) / 180;
      const goldenFrac = count <= 2 ? (idx - (count - 1) * 0.5) * 0.45 : (((idx * 0.61803398875) % 1) - 0.5);
      const az = sec.midAngle + goldenFrac * usableSpan;
      globe.set(page.id, sphericalToWorld(GLOBE_SURFACE_RADIUS, az, latRad));
    });
  }

  // Place Orphan pages on a distinct South Polar Drift Ring (lat = -63 deg) so isolated pages are unmistakable
  orphans.sort((a, b) => a.path.localeCompare(b.path));
  orphans.forEach((orph, idx) => {
    const sec = sectorById.get(orph.section || 'root');
    const baseAz = sec ? sec.midAngle : (idx / Math.max(1, orphans.length)) * Math.PI * 2;
    const spread = orphans.length > 1 ? ((idx / Math.max(1, orphans.length)) * Math.PI * 2) : baseAz;
    const az = orphans.length <= 3 && sec ? baseAz + (idx - (orphans.length - 1) * 0.5) * 0.32 : spread;
    const latRad = (-63 * Math.PI) / 180;
    globe.set(orph.id, sphericalToWorld(GLOBE_ORPHAN_RADIUS, az, latRad));
  });

  // Place External Domains on the Outer Satellite Orbit (R = 7.85), aligned with the linking internal pages
  const incomingSourcesByExt = new Map<string, string[]>();
  for (const e of edges) {
    if (e.kind === 'external') {
      let arr = incomingSourcesByExt.get(e.target);
      if (!arr) {
        arr = [];
        incomingSourcesByExt.set(e.target, arr);
      }
      arr.push(e.source);
    }
  }

  externalNodes.forEach((ext, idx) => {
    const sources = incomingSourcesByExt.get(ext.id) ?? [];
    let sumSin = 0;
    let sumCos = 0;
    let sumY = 0;
    let validSources = 0;

    for (const sid of sources) {
      const p = globe.get(sid);
      if (p) {
        const horiz = Math.hypot(p[0], p[2]);
        if (horiz > 0.05) {
          sumSin += p[0] / horiz;
          sumCos += p[2] / horiz;
          sumY += p[1] / GLOBE_SURFACE_RADIUS;
          validSources++;
        }
      }
    }

    let az: number;
    let latRad: number;
    if (validSources > 0) {
      az = Math.atan2(sumSin / validSources, sumCos / validSources);
      // Offset slightly by index hash so multiple externals from same page never stack
      az += (((idx % 5) - 2) * 0.16);
      const meanY = Math.max(-0.55, Math.min(0.55, sumY / validSources));
      latRad = Math.asin(meanY) * 0.72 + (((idx % 3) - 1) * 0.14);
    } else {
      az = idx * GOLDEN_ANGLE;
      latRad = (((idx % 5) - 2) * 0.18);
    }

    globe.set(ext.id, sphericalToWorld(GLOBE_EXTERNAL_RADIUS, az, latRad));
  });

  // 2. SITEMAP ROAD LAYOUT (Left-to-right 3D Click-Depth Terraces)
  // Columns: 0 = Home, 1 = Depth 1 / Hubs, 2 = Depth 2, 3 = Depth 3+, 4 = Orphans, 5 = External
  const roadCols = new Map<number, SiteNode[]>();
  for (const n of nodes) {
    let col = 2;
    if (n.kind === 'home' || n.id === homeNode?.id) {
      col = 0;
    } else if (n.kind === 'external-domain') {
      col = 5;
    } else if (n.health === 'orphan' || n.clickDepth === null) {
      col = 4;
    } else if (n.clickDepth <= 1 || n.kind === 'hub') {
      col = 1;
    } else if (n.clickDepth === 2) {
      col = 2;
    } else {
      col = 3;
    }
    let arr = roadCols.get(col);
    if (!arr) {
      arr = [];
      roadCols.set(col, arr);
    }
    arr.push(n);
  }

  const colX: Record<number, number> = {
    0: -8.2,
    1: -4.9,
    2: -1.3,
    3: 2.3,
    4: 5.5,
    5: 8.8,
  };

  roadCols.forEach((colNodes, col) => {
    colNodes.sort((a, b) => a.section.localeCompare(b.section) || a.path.localeCompare(b.path));
    const count = colNodes.length;
    const xBase = colX[col] ?? 0;
    const maxPerVertical = 9;
    const subCols = Math.ceil(count / maxPerVertical);

    colNodes.forEach((n, idx) => {
      const subCol = Math.floor(idx / maxPerVertical);
      const rowInSub = idx % maxPerVertical;
      const rowsThisSub = Math.min(maxPerVertical, count - subCol * maxPerVertical);
      const yStep = Math.min(1.05, 7.6 / Math.max(1, rowsThisSub));
      const y = ((rowsThisSub - 1) * 0.5 - rowInSub) * yStep;
      const z = (subCol - (subCols - 1) * 0.5) * 2.15 + ((rowInSub % 2) - 0.5) * 0.35;
      road.set(n.id, [xBase + subCol * 0.55, y, z]);
    });
  });

  // 3. 3D LINK CLUSTERS (Deterministic 3D Force Relaxation seeded from Globe)
  const pos = new Map<string, [number, number, number]>();
  for (const n of nodes) {
    const g = globe.get(n.id) ?? [0, 0, 0];
    pos.set(n.id, [g[0] * 0.85, g[1] * 0.85, g[2] * 0.85]);
  }

  const activeEdges: SiteEdge[] = edges.filter((e) => e.kind !== 'internal-chrome');
  const idList = nodes.map((n) => n.id);
  const vel = new Map<string, [number, number, number]>();
  for (const id of idList) vel.set(id, [0, 0, 0]);

  const iterations = Math.min(90, Math.max(40, Math.round(1400 / Math.max(12, nodes.length))));
  for (let iter = 0; iter < iterations; iter++) {
    const alpha = 1 - iter / iterations;
    // Repulsion
    for (let i = 0; i < idList.length; i++) {
      const pA = pos.get(idList[i])!;
      const vA = vel.get(idList[i])!;
      for (let j = i + 1; j < idList.length; j++) {
        const pB = pos.get(idList[j])!;
        const vB = vel.get(idList[j])!;
        const dx = pA[0] - pB[0];
        const dy = pA[1] - pB[1];
        const dz = pA[2] - pB[2];
        const dSq = Math.max(0.25, dx * dx + dy * dy + dz * dz);
        const f = (0.52 * alpha) / dSq;
        const dist = Math.sqrt(dSq);
        const fx = (dx / dist) * f;
        const fy = (dy / dist) * f;
        const fz = (dz / dist) * f;
        vA[0] += fx;
        vA[1] += fy;
        vA[2] += fz;
        vB[0] -= fx;
        vB[1] -= fy;
        vB[2] -= fz;
      }
    }

    // Spring attraction
    for (const e of activeEdges) {
      const pS = pos.get(e.source);
      const pT = pos.get(e.target);
      if (!pS || !pT) continue;
      const vS = vel.get(e.source)!;
      const vT = vel.get(e.target)!;
      const ideal = e.kind === 'external' ? 5.6 : e.kind === 'sitemap-hierarchy' ? 3.2 : 3.8;
      const dx = pT[0] - pS[0];
      const dy = pT[1] - pS[1];
      const dz = pT[2] - pS[2];
      const dist = Math.max(0.1, Math.hypot(dx, dy, dz));
      const pull = (dist - ideal) * 0.045 * alpha;
      const fx = (dx / dist) * pull;
      const fy = (dy / dist) * pull;
      const fz = (dz / dist) * pull;
      vS[0] += fx;
      vS[1] += fy;
      vS[2] += fz;
      vT[0] -= fx;
      vT[1] -= fy;
      vT[2] -= fz;
    }

    // Centering + integrate
    for (const n of nodes) {
      if (homeNode && n.id === homeNode.id) {
        pos.set(n.id, [0, 0, 0]);
        continue;
      }
      const p = pos.get(n.id)!;
      const v = vel.get(n.id)!;
      p[0] = (p[0] + v[0]) * 0.995;
      p[1] = (p[1] + v[1]) * 0.995;
      p[2] = (p[2] + v[2]) * 0.995;
      v[0] *= 0.6;
      v[1] *= 0.6;
      v[2] *= 0.6;
    }
  }

  for (const n of nodes) {
    clusters.set(n.id, pos.get(n.id) ?? [0, 0, 0]);
  }

  return { sectors, globe, road, clusters };
}
