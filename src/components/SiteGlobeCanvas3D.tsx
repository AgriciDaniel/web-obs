import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import {
  CSS2DObject,
  CSS2DRenderer,
} from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import {
  computeSiteLayouts,
  GLOBE_EXTERNAL_RADIUS,
  GLOBE_HUB_RADIUS,
  GLOBE_SURFACE_RADIUS,
} from '../data/globeLayout';
import type {
  CameraAxisSnap,
  GlobeViewMode,
  NodeFilter,
  NodeHealth,
  SiteEdge,
  SiteGraphManifest,
  SiteNode,
  ThemeMode,
} from '../types/site';
import type { ViewGizmoHandle } from './ViewGizmo3D';
import { hasNodeIssue } from '../data/sitePresentation';
import { MapDiscoveryControls } from './MapDiscoveryControls';

interface SiteGlobeCanvas3DProps {
  manifest: SiteGraphManifest | null;
  viewMode: GlobeViewMode;
  theme: ThemeMode;
  selectedId: string | null;
  hoveredId: string | null;
  filter: NodeFilter;
  searchQuery: string;
  showExternal: boolean;
  showChromeLinks: boolean;
  showAllLinks: boolean;
  showPulses: boolean;
  autoRotate: boolean;
  paused?: boolean;
  inspectorOpen: boolean;
  resetSignal: number;
  flyRequest: { nodeId: string; seq: number } | null;
  axisSnapRequest: { axis: CameraAxisSnap; seq: number } | null;
  gizmoRef?: React.RefObject<ViewGizmoHandle | null>;
  onSelectNode: (id: string | null) => void;
  onHoverNode: (id: string | null) => void;
  onOpenNoteNode?: (node: SiteNode) => void;
  onBeginDiscovery?: () => void;
  onWebGLContextLost?: () => void;
}

const HEALTH_COLORS_LIGHT: Record<NodeHealth, number> = {
  home: 0x7c3aed,
  hub: 0x347d59,
  healthy: 0x666666,
  orphan: 0x93621c,
  unlisted: 0x9a742b,
  redirect: 0xa45d26,
  broken: 0xb92c3c,
  unavailable: 0x93621c,
  external: 0x7358a6,
};

const HEALTH_COLORS_DARK: Record<NodeHealth, number> = {
  home: 0xa882ff,
  hub: 0x8fd6af,
  healthy: 0xb3b3b3,
  orphan: 0xe9b86c,
  unlisted: 0xe2c38a,
  redirect: 0xe3a27c,
  broken: 0xed8796,
  unavailable: 0xe9b86c,
  external: 0xc2a9de,
};

interface ScreenBox {
  l: number;
  r: number;
  t: number;
  b: number;
}

interface RuntimeNodeEntry {
  node: SiteNode;
  group: THREE.Group;
  coreMesh: THREE.Mesh;
  haloMesh: THREE.Mesh;
  coreMat: THREE.MeshStandardMaterial;
  haloMat: THREE.MeshBasicMaterial;
  cssObj: CSS2DObject;
  labelEl: HTMLDivElement;
  currentPos: THREE.Vector3;
  targetPos: THREE.Vector3;
  pillW: number;
  pillH: number;
  /** True once the label was laid out in the DOM and its real size read. */
  pillMeasured: boolean;
}

interface RuntimeEdgeEntry {
  edge: SiteEdge;
  line: THREE.Line;
  geom: THREE.BufferGeometry;
  mat: THREE.LineBasicMaterial;
  pulseSlot: number;
  pulsePhase: number;
  ambientEligible: boolean;
  p0: THREE.Vector3;
  p1: THREE.Vector3;
  p2: THREE.Vector3;
  lastSrc: THREE.Vector3;
  lastDst: THREE.Vector3;
  lastSrcHex: number;
  lastDstHex: number;
  pulseHighlighted: boolean;
}

const ROAD_COLUMNS = [
  { x: -8.2, title: 'D0 · Site Root' },
  { x: -4.9, title: 'D1 · Hubs' },
  { x: -1.3, title: 'D2 · Pages' },
  { x: 2.3, title: 'D3+ · Deep' },
  { x: 5.5, title: 'Orphans' },
  { x: 8.8, title: 'External' },
];

function boxesOverlap(a: ScreenBox, b: ScreenBox, pad = 5): boolean {
  return !(
    a.r + pad < b.l ||
    a.l - pad > b.r ||
    a.b + pad < b.t ||
    a.t - pad > b.b
  );
}

function pushCircleXZ(pts: THREE.Vector3[], radius: number, y: number, segs = 96): void {
  for (let i = 0; i < segs; i++) {
    const a0 = (i / segs) * Math.PI * 2;
    const a1 = ((i + 1) / segs) * Math.PI * 2;
    pts.push(
      new THREE.Vector3(Math.sin(a0) * radius, y, Math.cos(a0) * radius),
      new THREE.Vector3(Math.sin(a1) * radius, y, Math.cos(a1) * radius)
    );
  }
}

function pushMeridianHalfArc(
  pts: THREE.Vector3[],
  radius: number,
  azimuth: number,
  segs = 64
): void {
  const sinAz = Math.sin(azimuth);
  const cosAz = Math.cos(azimuth);
  for (let i = 0; i < segs; i++) {
    const lat0 = -Math.PI * 0.5 + (i / segs) * Math.PI;
    const lat1 = -Math.PI * 0.5 + ((i + 1) / segs) * Math.PI;
    const c0 = Math.cos(lat0);
    const c1 = Math.cos(lat1);
    pts.push(
      new THREE.Vector3(radius * c0 * sinAz, radius * Math.sin(lat0), radius * c0 * cosAz),
      new THREE.Vector3(radius * c1 * sinAz, radius * Math.sin(lat1), radius * c1 * cosAz)
    );
  }
}

function matchesFilter(node: SiteNode, filter: NodeFilter, showExternal: boolean): boolean {
  if (!showExternal && node.kind === 'external-domain') return false;
  switch (filter) {
    case 'hubs':
      return node.kind === 'home' || node.kind === 'hub';
    case 'pages':
      return node.kind !== 'external-domain';
    case 'orphans':
      return node.health === 'orphan' || node.health === 'unlisted' || node.kind === 'home';
    case 'issues':
      return hasNodeIssue(node);
    case 'external':
      return node.kind === 'external-domain' || node.externalDomainsOut > 0;
    default:
      return true;
  }
}

function shortPillLabel(node: SiteNode, domain?: string): string {
  if (node.kind === 'home') {
    const cleanDomain = (
      domain ||
      node.url.replace(/^https?:\/\//i, '').replace(/\/.*$/, '') ||
      'site'
    ).trim();
    return cleanDomain;
  }
  if (node.kind === 'external-domain') return node.title;
  const cleanTitle = node.title.split('|')[0].split(' - ')[0].trim();
  if (cleanTitle.length > 0 && cleanTitle.length <= 28) return cleanTitle;
  const p = node.path || '/';
  if (p.length <= 28) return p;
  const parts = p.split('/').filter(Boolean);
  const last = parts[parts.length - 1] ?? p;
  return `/${last.slice(0, 24)}`;
}

export const SiteGlobeCanvas3D: React.FC<SiteGlobeCanvas3DProps> = ({
  manifest,
  viewMode,
  theme,
  selectedId,
  hoveredId,
  filter,
  searchQuery,
  showExternal,
  showChromeLinks,
  showAllLinks,
  showPulses,
  autoRotate,
  paused = false,
  inspectorOpen,
  resetSignal,
  flyRequest,
  axisSnapRequest,
  gizmoRef,
  onSelectNode,
  onHoverNode,
  onOpenNoteNode,
  onBeginDiscovery,
  onWebGLContextLost,
}) => {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [renderUnavailable, setRenderUnavailable] = useState(false);
  const [discoveryFocusId, setDiscoveryFocusId] = useState<string | null>(null);
  const effectiveSelectedId = selectedId ?? discoveryFocusId;
  const pausedRef = useRef<boolean>(paused);
  pausedRef.current = paused;

  const layouts = useMemo(
    () => (manifest ? computeSiteLayouts(manifest) : null),
    [manifest]
  );
  const discoveryNodes = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return (manifest?.nodes ?? []).filter(node => matchesFilter(node, filter, showExternal) &&
      (!query || [node.title, node.path, node.url].join(' ').toLowerCase().includes(query)));
  }, [manifest, filter, searchQuery, showExternal]);

  // Bumped on every React render so any prop change marks the scene dirty for the on-demand frame loop.
  const renderVersionRef = useRef(0);
  const stateRef = useRef({
    manifest,
    layouts,
    viewMode,
    theme,
    selectedId: effectiveSelectedId,
    hoveredId,
    filter,
    searchQuery,
    showExternal,
    showChromeLinks,
    showAllLinks,
    showPulses,
    autoRotate,
    inspectorOpen,
  });
  renderVersionRef.current += 1;
  stateRef.current = {
    manifest,
    layouts,
    viewMode,
    theme,
    selectedId: effectiveSelectedId,
    hoveredId,
    filter,
    searchQuery,
    showExternal,
    showChromeLinks,
    showAllLinks,
    showPulses,
    autoRotate,
    inspectorOpen,
  };

  const callbacksRef = useRef({
    onSelectNode,
    onHoverNode,
    onOpenNoteNode,
    onWebGLContextLost,
    onBeginDiscovery,
  });
  callbacksRef.current = {
    onSelectNode,
    onHoverNode,
    onOpenNoteNode,
    onWebGLContextLost,
    onBeginDiscovery,
  };

  const gizmoHolderRef = useRef(gizmoRef);
  gizmoHolderRef.current = gizmoRef;

  const syncGraphRef = useRef<((m: SiteGraphManifest | null) => void) | null>(null);
  const cameraFlyRef = useRef<{
    active: boolean;
    camTarget: THREE.Vector3;
    lookTarget: THREE.Vector3;
    instant?: boolean;
  }>({
    active: false,
    camTarget: new THREE.Vector3(0, 4.2, 16.5),
    lookTarget: new THREE.Vector3(0, 0, 0),
  });
  const wakeLoopRef = useRef<(() => void) | null>(null);
  const discoverCameraRef = useRef<((nodeId: string) => void) | null>(null);
  const discoverNode = useCallback((nodeId: string) => {
    if (callbacksRef.current.onBeginDiscovery) callbacksRef.current.onBeginDiscovery();
    else callbacksRef.current.onSelectNode(null);
    setDiscoveryFocusId(nodeId);
    callbacksRef.current.onHoverNode(null);
    discoverCameraRef.current?.(nodeId);
  }, []);
  const inspectDiscoveryNode = useCallback((nodeId: string) => {
    callbacksRef.current.onSelectNode(nodeId);
  }, []);
  useEffect(() => { setDiscoveryFocusId(null); }, [manifest, filter, searchQuery, showExternal]);

  useEffect(() => {
    const container = mountRef.current;
    if (!container) return;
    const selectFromMap = (nodeId: string | null) => {
      setDiscoveryFocusId(null);
      callbacksRef.current.onSelectNode(nodeId);
    };

    const width = Math.max(320, container.clientWidth);
    const height = Math.max(260, container.clientHeight);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, width / height, 0.1, 180);
    camera.position.set(-4.6, 5.2, 16.2);

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        powerPreference: 'high-performance',
      });
    } catch {
      setRenderUnavailable(true);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height);
    container.appendChild(renderer.domElement);

    const labelRenderer = new CSS2DRenderer();
    labelRenderer.setSize(width, height);
    labelRenderer.domElement.className = 'wo-css2d-layer';
    container.appendChild(labelRenderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.075;
    controls.minDistance = 2.8;
    controls.maxDistance = 42;
    controls.target.set(0, 0, 0);

    controls.addEventListener('start', () => {
      cameraFlyRef.current.active = false;
    });

    // Subtle studio lighting for 3D node spheres
    const ambient = new THREE.AmbientLight(0xffffff, 1.35);
    const keyLight = new THREE.DirectionalLight(0xffffff, 1.45);
    keyLight.position.set(8, 14, 12);
    const rimLight = new THREE.DirectionalLight(0xa882ff, 0.65);
    rimLight.position.set(-10, -6, -8);
    scene.add(ambient, keyLight, rimLight);

    const disposables: Array<{ dispose: () => void }> = [];
    const track = <T extends { dispose: () => void }>(obj: T): T => {
      disposables.push(obj);
      return obj;
    };

    // =========================================================================
    // 1. CARTOGRAPHIC SITE GLOBE WIREFRAME & DYNAMIC SECTION MERIDIANS
    // =========================================================================
    const globeFrameGroup = new THREE.Group();
    scene.add(globeFrameGroup);

    const primaryWireMat = track(
      new THREE.LineBasicMaterial({
        color: 0xa882ff,
        transparent: true,
        opacity: 0.24,
        depthWrite: false,
      })
    );
    const secondaryWireMat = track(
      new THREE.LineBasicMaterial({
        color: 0x858585,
        transparent: true,
        opacity: 0.14,
        depthWrite: false,
      })
    );
    const orphanRingMat = track(
      new THREE.LineBasicMaterial({
        color: 0x93621c,
        transparent: true,
        opacity: 0.28,
        depthWrite: false,
      })
    );
    const externalOrbitMat = track(
      new THREE.LineBasicMaterial({
        color: 0x7c3aed,
        transparent: true,
        opacity: 0.18,
        depthWrite: false,
      })
    );

    // Static precision graticule
    {
      const primPts: THREE.Vector3[] = [];
      const secPts: THREE.Vector3[] = [];
      const orphPts: THREE.Vector3[] = [];
      const extPts: THREE.Vector3[] = [];

      // Core ring & Inner Hub shell equator
      pushCircleXZ(primPts, 1.05, 0, 64);
      pushCircleXZ(secPts, GLOBE_HUB_RADIUS, 0, 80);

      // Main Domain Globe equator + tropic/polar parallels (R = 5.35)
      pushCircleXZ(primPts, GLOBE_SURFACE_RADIUS, 0, 112);
      for (const deg of [26, -26, 50]) {
        const rad = (deg * Math.PI) / 180;
        pushCircleXZ(
          secPts,
          Math.cos(rad) * GLOBE_SURFACE_RADIUS,
          Math.sin(rad) * GLOBE_SURFACE_RADIUS,
          96
        );
      }

      // South Polar Orphan Drift Belt (-63 deg)
      {
        const rad = (-63 * Math.PI) / 180;
        pushCircleXZ(
          orphPts,
          Math.cos(rad) * GLOBE_SURFACE_RADIUS,
          Math.sin(rad) * GLOBE_SURFACE_RADIUS,
          80
        );
      }

      // Polar central axis spindle
      primPts.push(
        new THREE.Vector3(0, -GLOBE_SURFACE_RADIUS * 1.04, 0),
        new THREE.Vector3(0, GLOBE_SURFACE_RADIUS * 1.04, 0)
      );

      // Base 4 cardinal meridians (faint reference when 0 sections exist)
      for (let m = 0; m < 8; m++) {
        pushMeridianHalfArc(secPts, GLOBE_SURFACE_RADIUS, (m / 8) * Math.PI * 2, 56);
      }

      // Outer External Satellite Ring (R = 7.85)
      pushCircleXZ(extPts, GLOBE_EXTERNAL_RADIUS, 0, 120);
      pushCircleXZ(
        extPts,
        Math.cos(0.28) * GLOBE_EXTERNAL_RADIUS,
        Math.sin(0.28) * GLOBE_EXTERNAL_RADIUS,
        96
      );
      pushCircleXZ(
        extPts,
        Math.cos(-0.28) * GLOBE_EXTERNAL_RADIUS,
        Math.sin(-0.28) * GLOBE_EXTERNAL_RADIUS,
        96
      );

      globeFrameGroup.add(
        new THREE.LineSegments(track(new THREE.BufferGeometry().setFromPoints(primPts)), primaryWireMat),
        new THREE.LineSegments(track(new THREE.BufferGeometry().setFromPoints(secPts)), secondaryWireMat),
        new THREE.LineSegments(track(new THREE.BufferGeometry().setFromPoints(orphPts)), orphanRingMat),
        new THREE.LineSegments(track(new THREE.BufferGeometry().setFromPoints(extPts)), externalOrbitMat)
      );
    }

    // Dynamic section meridians & CSS2D equator plaques
    const dynamicSectorsGroup = new THREE.Group();
    globeFrameGroup.add(dynamicSectorsGroup);
    let dynamicSectorGeoms: THREE.BufferGeometry[] = [];
    let dynamicSectorPlaques: CSS2DObject[] = [];

    const clearDynamicSectors = () => {
      for (const p of dynamicSectorPlaques) {
        dynamicSectorsGroup.remove(p);
        p.element.remove();
      }
      dynamicSectorPlaques = [];
      for (const g of dynamicSectorGeoms) g.dispose();
      dynamicSectorGeoms = [];
      dynamicSectorsGroup.clear();
    };

    // =========================================================================
    // 2. SITEMAP ROAD STAGE COLUMNS
    // =========================================================================
    const roadFrameGroup = new THREE.Group();
    roadFrameGroup.visible = false;
    scene.add(roadFrameGroup);
    let roadRootTagEl: HTMLDivElement | null = null;
    {
      const rPts: THREE.Vector3[] = [];
      ROAD_COLUMNS.forEach((col, colIdx) => {
        rPts.push(
          new THREE.Vector3(col.x, -4.6, 0),
          new THREE.Vector3(col.x, 4.6, 0)
        );
        const tagEl = document.createElement('div');
        tagEl.className = 'wo-sector-tag';
        tagEl.textContent = col.title;
        if (colIdx === 0) roadRootTagEl = tagEl;
        const tagObj = new CSS2DObject(tagEl);
        tagObj.position.set(col.x, -5.05, 0);
        roadFrameGroup.add(tagObj);
      });
      roadFrameGroup.add(
        new THREE.LineSegments(
          track(new THREE.BufferGeometry().setFromPoints(rPts)),
          secondaryWireMat
        )
      );
    }

    // =========================================================================
    // 3. DYNAMIC NODES, EDGES, & SUBTLE MICRO-LIGHT FLOW
    // =========================================================================
    const sceneSpinGroup = new THREE.Group();
    sceneSpinGroup.add(globeFrameGroup);
    scene.add(sceneSpinGroup);

    const nodesRoot = new THREE.Group();
    const edgesRoot = new THREE.Group();
    sceneSpinGroup.add(edgesRoot, nodesRoot);
    discoverCameraRef.current = (nodeId) => {
      const state = stateRef.current;
      const map = state.viewMode === 'road' ? state.layouts?.road : state.viewMode === 'clusters' ? state.layouts?.clusters : state.layouts?.globe;
      const coordinates = map?.get(nodeId);
      if (!coordinates) return;
      sceneSpinGroup.updateWorldMatrix(true, false);
      const point = new THREE.Vector3(...coordinates);
      if (state.viewMode === 'globe') sceneSpinGroup.localToWorld(point);
      const direction = point.length() > .2 ? point.clone().normalize() : new THREE.Vector3(0, .3, 1).normalize();
      const kind = state.manifest?.nodes.find(node => node.id === nodeId)?.kind;
      const distance = kind === 'home' ? 8 : kind === 'hub' ? 7 : 6.2;
      cameraFlyRef.current = {
        active: true,
        lookTarget: point.clone(),
        camTarget: point.clone().addScaledVector(direction, distance).add(new THREE.Vector3(0, 1.1, 0)),
        instant: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false,
      };
    };

    const unitSphereGeom = track(new THREE.SphereGeometry(1, 22, 22));
    const unitHaloGeom = track(new THREE.RingGeometry(1.32, 1.65, 28));
    const pulseGeom = track(new THREE.SphereGeometry(0.017, 8, 8));
    const pulseMat = track(
      new THREE.MeshBasicMaterial({
        color: 0xa882ff,
        transparent: true,
        opacity: 0.62,
        depthWrite: false,
      })
    );

    const runtimeNodes = new Map<string, RuntimeNodeEntry>();
    const runtimeEdges = new Map<string, RuntimeEdgeEntry>();
    const pickableMeshes: THREE.Mesh[] = [];

    let pulseCapacity = 128;
    let pulseInstanced = new THREE.InstancedMesh(pulseGeom, pulseMat, pulseCapacity);
    pulseInstanced.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    pulseInstanced.frustumCulled = false;
    edgesRoot.add(pulseInstanced);

    const clearRuntimeGraph = () => {
      runtimeNodes.forEach((entry) => {
        entry.group.remove(entry.cssObj);
        entry.labelEl.remove();
        entry.coreMat.dispose();
        entry.haloMat.dispose();
        nodesRoot.remove(entry.group);
      });
      runtimeNodes.clear();
      pickableMeshes.length = 0;

      runtimeEdges.forEach((re) => {
        re.geom.dispose();
        re.mat.dispose();
        edgesRoot.remove(re.line);
      });
      runtimeEdges.clear();
      pulseInstanced.count = 0;
    };

    // Frame-loop invalidation state. The heavy scene and label work runs only when something changed.
    let forceHeavy = true;
    let lastKey = '';
    let lastManifestRef: unknown = null;
    let lastLayoutsRef: unknown = null;
    let lastVersion = -1;
    let nodesSettled = false;
    let measureAttempts = 0;
    let syncedGizmo: unknown = null;
    let labelHoverId: string | null = null;
    let pulseEdges: RuntimeEdgeEntry[] = [];
    const lastCamPos = new THREE.Vector3(Number.NaN, 0, 0);
    const lastCamQuat = new THREE.Quaternion(Number.NaN, 0, 0, 1);

    const rebuildGraph = (nextManifest: SiteGraphManifest | null) => {
      forceHeavy = true;
      clearRuntimeGraph();
      clearDynamicSectors();
      if (!nextManifest) {
        if (roadRootTagEl) roadRootTagEl.textContent = 'D0 · Site Root';
        return;
      }

      if (roadRootTagEl) {
        roadRootTagEl.textContent = nextManifest.domain
          ? `D0 · ${nextManifest.domain}`
          : 'D0 · Site Root';
      }

      const curLayouts = stateRef.current.layouts ?? computeSiteLayouts(nextManifest);

      // Build section boundary meridians & sector plaques
      const mPts: THREE.Vector3[] = [];
      for (const sec of curLayouts.sectors) {
        pushMeridianHalfArc(mPts, GLOBE_SURFACE_RADIUS, sec.startAngle, 56);
        if (curLayouts.sectors.length >= 1) {
          const el = document.createElement('div');
          el.className = 'wo-sector-tag';
          el.textContent = `${sec.label} · ${sec.pageCount}`;
          const obj = new CSS2DObject(el);
          const rTag = GLOBE_SURFACE_RADIUS + 0.42;
          obj.position.set(
            Math.sin(sec.midAngle) * rTag,
            0.22,
            Math.cos(sec.midAngle) * rTag
          );
          dynamicSectorsGroup.add(obj);
          dynamicSectorPlaques.push(obj);
        }
      }
      if (mPts.length > 0) {
        const g = new THREE.BufferGeometry().setFromPoints(mPts);
        dynamicSectorGeoms.push(g);
        dynamicSectorsGroup.add(new THREE.LineSegments(g, primaryWireMat));
      }

      const palette =
        stateRef.current.theme === 'dark' ? HEALTH_COLORS_DARK : HEALTH_COLORS_LIGHT;

      for (const node of nextManifest.nodes) {
        const initPos = curLayouts.globe.get(node.id) ?? [0, 0, 0];
        const group = new THREE.Group();
        group.position.set(initPos[0], initPos[1], initPos[2]);

        const baseRadius =
          node.kind === 'home'
            ? 0.34
            : node.kind === 'hub'
              ? 0.21
              : node.kind === 'external-domain'
                ? 0.115
                : 0.135;

        const hex = palette[node.health] ?? palette.healthy;
        const coreMat = new THREE.MeshStandardMaterial({
          color: hex,
          emissive: hex,
          emissiveIntensity: node.kind === 'home' ? 0.55 : 0.28,
          roughness: 0.28,
          metalness: 0.18,
        });
        const coreMesh = new THREE.Mesh(unitSphereGeom, coreMat);
        coreMesh.scale.setScalar(baseRadius);
        coreMesh.userData = { nodeId: node.id };
        group.add(coreMesh);
        pickableMeshes.push(coreMesh);

        const haloMat = new THREE.MeshBasicMaterial({
          color: hex,
          transparent: true,
          opacity: node.kind === 'home' || node.health === 'orphan' || node.health === 'broken' ? 0.55 : 0.22,
          side: THREE.DoubleSide,
          depthWrite: false,
        });
        const haloMesh = new THREE.Mesh(unitHaloGeom, haloMat);
        haloMesh.scale.setScalar(baseRadius);
        group.add(haloMesh);

        const pillText = shortPillLabel(node, nextManifest.domain);
        const labelEl = document.createElement('div');
        labelEl.className = `wo-node-pill wo-health-${node.health} wo-kind-${node.kind}`;
        labelEl.dataset.nodeId = node.id;
        labelEl.setAttribute('role', 'button');
        labelEl.tabIndex = 0;
        const dotEl = document.createElement('span');
        dotEl.className = 'wo-pill-dot';
        const txtEl = document.createElement('span');
        txtEl.className = 'wo-pill-label';
        txtEl.textContent = pillText;
        labelEl.append(dotEl, txtEl);

        if (node.health === 'orphan' || node.health === 'broken' || node.health === 'unlisted') {
          const badgeEl = document.createElement('span');
          badgeEl.className = 'wo-pill-badge';
          badgeEl.textContent =
            node.health === 'broken'
              ? String(node.statusCode || 404)
              : node.health === 'orphan'
                ? 'orphan'
                : 'unlisted';
          labelEl.appendChild(badgeEl);
        }
        labelEl.setAttribute('aria-label', `${labelEl.textContent}. Inspect ${node.title}`);

        labelEl.addEventListener('pointerenter', () => {
          callbacksRef.current.onHoverNode(node.id);
        });
        labelEl.addEventListener('pointerleave', () => {
          callbacksRef.current.onHoverNode(null);
        });
        labelEl.addEventListener('click', (ev) => {
          ev.stopPropagation();
          selectFromMap(node.id);
        });
        labelEl.addEventListener('focus', () => callbacksRef.current.onHoverNode(node.id));
        labelEl.addEventListener('blur', () => callbacksRef.current.onHoverNode(null));
        labelEl.addEventListener('keydown', (event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            event.stopPropagation();
            selectFromMap(node.id);
          }
        });
        labelEl.addEventListener('dblclick', (ev) => {
          ev.stopPropagation();
          selectFromMap(node.id);
          callbacksRef.current.onOpenNoteNode?.(node);
        });

        const cssObj = new CSS2DObject(labelEl);
        cssObj.position.set(0, baseRadius + 0.16, 0);
        group.add(cssObj);
        nodesRoot.add(group);

        runtimeNodes.set(node.id, {
          node,
          group,
          coreMesh,
          haloMesh,
          coreMat,
          haloMat,
          cssObj,
          labelEl,
          currentPos: new THREE.Vector3(...initPos),
          targetPos: new THREE.Vector3(...initPos),
          pillMeasured: false,
          pillW: Math.max(68, pillText.length * 7.2 + 28),
          pillH: 24,
        });
      }

      if (nextManifest.edges.length > pulseCapacity) {
        edgesRoot.remove(pulseInstanced);
        pulseInstanced.dispose();
        pulseCapacity = nextManifest.edges.length + 32;
        pulseInstanced = new THREE.InstancedMesh(pulseGeom, pulseMat, pulseCapacity);
        pulseInstanced.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        pulseInstanced.frustumCulled = false;
        edgesRoot.add(pulseInstanced);
      }

      // Select at most 24 calm structural routes for idle ambient light flow
      // so dense sites never produce a noisy swarm of dots.
      const nodeKindMap = new Map(nextManifest.nodes.map((n) => [n.id, n.kind]));
      const primaryCandidates: number[] = [];
      const secondaryCandidates: number[] = [];
      nextManifest.edges.forEach((edge, idx) => {
        if (edge.kind === 'internal-chrome') return;
        const sk = nodeKindMap.get(edge.source);
        const tk = nodeKindMap.get(edge.target);
        if (
          edge.kind === 'sitemap-hierarchy' ||
          (sk === 'home' && tk === 'hub')
        ) {
          primaryCandidates.push(idx);
        } else if (edge.kind === 'internal-body' && (sk === 'home' || sk === 'hub')) {
          secondaryCandidates.push(idx);
        }
      });

      const MAX_AMBIENT_PULSES = 24;
      const ambientSet = new Set<number>();
      if (primaryCandidates.length <= MAX_AMBIENT_PULSES) {
        for (const i of primaryCandidates) ambientSet.add(i);
        const rem = MAX_AMBIENT_PULSES - ambientSet.size;
        if (rem > 0 && secondaryCandidates.length > 0) {
          const step = Math.max(1, Math.floor(secondaryCandidates.length / rem));
          for (
            let k = 0;
            k < secondaryCandidates.length && ambientSet.size < MAX_AMBIENT_PULSES;
            k += step
          ) {
            ambientSet.add(secondaryCandidates[k]);
          }
        }
      } else {
        const step = primaryCandidates.length / MAX_AMBIENT_PULSES;
        for (let k = 0; k < MAX_AMBIENT_PULSES; k++) {
          ambientSet.add(primaryCandidates[Math.floor(k * step)]);
        }
      }

      nextManifest.edges.forEach((edge, idx) => {
        const geom = new THREE.BufferGeometry();
        geom.setAttribute('position', new THREE.BufferAttribute(new Float32Array(21 * 3), 3));
        geom.setAttribute('color', new THREE.BufferAttribute(new Float32Array(21 * 3), 3));
        const mat = new THREE.LineBasicMaterial({
          color: 0xffffff,
          vertexColors: true,
          transparent: true,
          opacity: edge.kind === 'sitemap-hierarchy' ? 0.36 : 0.24,
          depthWrite: false,
        });
        const line = new THREE.Line(geom, mat);
        edgesRoot.add(line);

        runtimeEdges.set(edge.id, {
          edge,
          line,
          geom,
          mat,
          pulseSlot: idx,
          pulsePhase: ((idx * 0.61803398875) % 1),
          ambientEligible: ambientSet.has(idx),
          p0: new THREE.Vector3(),
          p1: new THREE.Vector3(),
          p2: new THREE.Vector3(),
          lastSrc: new THREE.Vector3(NaN, NaN, NaN),
          lastDst: new THREE.Vector3(NaN, NaN, NaN),
          lastSrcHex: -1,
          lastDstHex: -1,
          pulseHighlighted: false,
        });
      });

      pulseInstanced.count = nextManifest.edges.length;
    };

    syncGraphRef.current = rebuildGraph;
    rebuildGraph(manifest);

    // =========================================================================
    // 4. POINTER RAYCASTING
    // =========================================================================
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let downPos = { x: 0, y: 0 };

    const pickNodeAt = (clientX: number, clientY: number): string | null => {
      const rect = renderer.domElement.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return null;
      pointer.x = ((clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const visible = pickableMeshes.filter((m) => m.parent?.visible);
      const hits = raycaster.intersectObjects(visible, false);
      return hits.length > 0 ? (hits[0].object.userData?.nodeId as string) ?? null : null;
    };

    const onLabelOver = (ev: MouseEvent) => {
      const pill = (ev.target as Element | null)?.closest?.('.wo-node-pill') as HTMLElement | null;
      const id = pill?.dataset.nodeId ?? null;
      if (id !== labelHoverId) { labelHoverId = id; forceHeavy = true; }
    };
    const onLabelOut = (ev: MouseEvent) => {
      const next = (ev.relatedTarget as Element | null)?.closest?.('.wo-node-pill');
      if (!next && labelHoverId !== null) { labelHoverId = null; forceHeavy = true; }
    };
    labelRenderer.domElement.addEventListener('mouseover', onLabelOver);
    labelRenderer.domElement.addEventListener('mouseout', onLabelOut);

    const onPointerMove = (ev: PointerEvent) => {
      if (labelHoverId !== null) { labelHoverId = null; forceHeavy = true; }
      const hit = pickNodeAt(ev.clientX, ev.clientY);
      renderer.domElement.style.cursor = hit ? 'pointer' : 'grab';
      if (hit !== stateRef.current.hoveredId) {
        callbacksRef.current.onHoverNode(hit);
      }
    };
    const onPointerLeave = (event: PointerEvent) => {
      if (event.relatedTarget instanceof Node && labelRenderer.domElement.contains(event.relatedTarget)) return;
      callbacksRef.current.onHoverNode(null);
    };

    const onPointerDown = (ev: PointerEvent) => {
      downPos = { x: ev.clientX, y: ev.clientY };
    };

    const onPointerUp = (ev: PointerEvent) => {
      if (Math.hypot(ev.clientX - downPos.x, ev.clientY - downPos.y) > 5) return;
      const hit = pickNodeAt(ev.clientX, ev.clientY);
      selectFromMap(hit);
    };

    const onDblClick = (ev: MouseEvent) => {
      const hit = pickNodeAt(ev.clientX, ev.clientY);
      if (hit) {
        const entry = runtimeNodes.get(hit);
        if (entry) callbacksRef.current.onOpenNoteNode?.(entry.node);
      }
    };

    renderer.domElement.addEventListener('pointermove', onPointerMove);
    renderer.domElement.addEventListener('pointerleave', onPointerLeave);
    renderer.domElement.addEventListener('pointerdown', onPointerDown);
    renderer.domElement.addEventListener('pointerup', onPointerUp);
    renderer.domElement.addEventListener('dblclick', onDblClick);

    const handleContextLost = (e: Event) => {
      e.preventDefault();
      callbacksRef.current.onWebGLContextLost?.();
    };
    renderer.domElement.addEventListener('webglcontextlost', handleContextLost);

    // =========================================================================
    // 5. RESIZE OBSERVER
    // =========================================================================
    let stageW = width;
    let stageH = height;
    const resizeObs = new ResizeObserver((entries) => {
      const cr = entries[0]?.contentRect;
      if (!cr || cr.width < 20 || cr.height < 20) return;
      stageW = cr.width;
      stageH = cr.height;
      camera.aspect = stageW / stageH;
      camera.updateProjectionMatrix();
      renderer.setSize(stageW, stageH);
      labelRenderer.setSize(stageW, stageH);
      forceHeavy = true;
    });
    resizeObs.observe(container);

    // =========================================================================
    // 6. RENDER LOOP (60fps, screen-space label solver, pulse animation)
    // =========================================================================
    let rafId = 0;
    let disposed = false;
    const clock = new THREE.Clock();
    const tmpColorA = new THREE.Color();
    const tmpColorB = new THREE.Color();
    const tmpVec = new THREE.Vector3();
    const tmpMid = new THREE.Vector3();
    const tmpWorldPos = new THREE.Vector3();
    const tmpMat4 = new THREE.Matrix4();
    const hiddenMat4 = new THREE.Matrix4().makeScale(0, 0, 0);

    // Moves one pulse instance along its cached curve. Shared by the dirty frame and the pulse-only frame.
    const writePulse = (re: RuntimeEdgeEntry, elapsed: number, isHighlighted: boolean) => {
      // Slow, meditative transit with a rest gap and smooth endpoint taper
      const period = isHighlighted ? 1.35 : 1.85;
      const speed = isHighlighted ? 0.115 : 0.072;
      const cycle = (elapsed * speed + re.pulsePhase * period) % period;
      if (cycle <= 1.0) {
        const tPulse = cycle;
        const inv = 1 - tPulse;
        const px = inv * inv * re.p0.x + 2 * inv * tPulse * re.p1.x + tPulse * tPulse * re.p2.x;
        const py = inv * inv * re.p0.y + 2 * inv * tPulse * re.p1.y + tPulse * tPulse * re.p2.y;
        const pz = inv * inv * re.p0.z + 2 * inv * tPulse * re.p1.z + tPulse * tPulse * re.p2.z;
        const envelope = Math.sin(tPulse * Math.PI);
        const sc = (isHighlighted ? 1.15 : 0.88) * envelope;
        if (sc > 0.05) {
          tmpMat4.makeTranslation(px, py, pz);
          tmpMat4.scale(tmpVec.set(sc, sc, sc));
          pulseInstanced.setMatrixAt(re.pulseSlot, tmpMat4);
        } else {
          pulseInstanced.setMatrixAt(re.pulseSlot, hiddenMat4);
        }
      } else {
        pulseInstanced.setMatrixAt(re.pulseSlot, hiddenMat4);
      }
    };

    const animate = () => {
      if (disposed) return;
      rafId = window.requestAnimationFrame(animate);
      if (pausedRef.current) return;

      const dt = Math.min(0.05, clock.getDelta());
      const elapsed = clock.elapsedTime;
      const st = stateRef.current;
      const isDark = st.theme === 'dark';
      const palette = isDark ? HEALTH_COLORS_DARK : HEALTH_COLORS_LIGHT;

      const spinningNow = (!st.manifest || st.autoRotate) && st.viewMode === 'globe' && !st.selectedId && !st.hoveredId;
      if (spinningNow) {
        sceneSpinGroup.rotation.y += dt * (st.manifest ? 0.08 : 0.14);
      } else if (st.viewMode !== 'globe') {
        sceneSpinGroup.rotation.y = THREE.MathUtils.lerp(sceneSpinGroup.rotation.y, 0, 0.14);
        if (Math.abs(sceneSpinGroup.rotation.y) < 1e-4) sceneSpinGroup.rotation.y = 0;
      }
      const settlingSpin = st.viewMode !== 'globe' && sceneSpinGroup.rotation.y !== 0;

      // Smooth camera fly-to
      const flying = cameraFlyRef.current.active;
      if (cameraFlyRef.current.active) {
        if (cameraFlyRef.current.instant) {
          camera.position.copy(cameraFlyRef.current.camTarget);
          controls.target.copy(cameraFlyRef.current.lookTarget);
        } else {
          camera.position.lerp(cameraFlyRef.current.camTarget, 0.11);
          controls.target.lerp(cameraFlyRef.current.lookTarget, 0.13);
        }
        if (
          camera.position.distanceTo(cameraFlyRef.current.camTarget) < 0.04 &&
          controls.target.distanceTo(cameraFlyRef.current.lookTarget) < 0.04
        ) {
          cameraFlyRef.current.active = false;
        }
      }

      controls.update();

      // On-demand rendering: skip the heavy node, label and edge work unless something changed.
      const camMoved = !camera.position.equals(lastCamPos) || !camera.quaternion.equals(lastCamQuat);
      const key = [
        st.viewMode, st.theme, st.selectedId ?? '', st.hoveredId ?? '', labelHoverId ?? '', st.filter, st.searchQuery,
        st.showExternal, st.showChromeLinks, st.showAllLinks, st.showPulses, st.autoRotate,
      ].join('|');
      const keyChanged = key !== lastKey || st.manifest !== lastManifestRef || st.layouts !== lastLayoutsRef ||
        renderVersionRef.current !== lastVersion;
      const heavy = forceHeavy || keyChanged || camMoved || spinningNow || settlingSpin || flying || !nodesSettled || Boolean(gizmoHolderRef.current?.current && gizmoHolderRef.current.current !== syncedGizmo);
      if (!heavy) {
        if (st.showPulses && pulseEdges.length > 0) {
          for (const re of pulseEdges) writePulse(re, elapsed, re.pulseHighlighted);
          pulseInstanced.instanceMatrix.needsUpdate = true;
          renderer.render(scene, camera);
        }
        return;
      }
      const measureLabels = keyChanged || forceHeavy;
      forceHeavy = false;
      lastKey = key;
      lastManifestRef = st.manifest;
      lastLayoutsRef = st.layouts;
      lastVersion = renderVersionRef.current;
      lastCamPos.copy(camera.position);
      lastCamQuat.copy(camera.quaternion);
      pulseEdges = [];
      const gizmo = gizmoHolderRef.current?.current;
      if (gizmo && (camMoved || gizmo !== syncedGizmo)) {
        gizmo.updateCameraQuaternion(camera.quaternion);
        syncedGizmo = gizmo;
      }

      // Update wireframe theme tint
      primaryWireMat.color.setHex(isDark ? 0xa882ff : 0x7c3aed);
      primaryWireMat.opacity = st.manifest ? (isDark ? 0.11 : 0.12) : 0.3;
      secondaryWireMat.color.setHex(isDark ? 0x666666 : 0xb3b3b3);
      secondaryWireMat.opacity = isDark ? 0.065 : 0.09;
      externalOrbitMat.color.setHex(isDark ? 0xc2a9de : 0x7358a6);
      externalOrbitMat.opacity = st.showExternal ? (isDark ? 0.2 : 0.18) : 0.04;
      pulseMat.color.setHex(isDark ? 0xcbb3ff : 0x7c3aed);

      globeFrameGroup.visible = st.viewMode === 'globe';
      roadFrameGroup.visible = st.viewMode === 'road' && Boolean(st.manifest);

      if (!st.manifest || !st.layouts) {
        renderer.render(scene, camera);
        labelRenderer.render(scene, camera);
        return;
      }

      const hoverId = labelHoverId ?? st.hoveredId;
      const focusId = hoverId ?? st.selectedId;
      labelRenderer.domElement.classList.toggle('is-hovering-node', hoverId !== null);
      const connectedIds = new Set<string>();
      if (focusId) {
        connectedIds.add(focusId);
        runtimeEdges.forEach((re) => {
          if (re.edge.kind === 'internal-chrome' && !st.showChromeLinks) return;
          if (re.edge.kind === 'external' && !st.showExternal) return;
          if (re.edge.source === focusId) connectedIds.add(re.edge.target);
          if (re.edge.target === focusId) connectedIds.add(re.edge.source);
        });
      }

      const query = st.searchQuery.trim().toLowerCase();
      const targetMap =
        st.viewMode === 'road'
          ? st.layouts.road
          : st.viewMode === 'clusters'
            ? st.layouts.clusters
            : st.layouts.globe;

      // Update nodes
      const visibleEntries: Array<{ entry: RuntimeNodeEntry; priority: number }> = [];

      let anyNodeMoving = false;
      runtimeNodes.forEach((entry, id) => {
        const tgt = targetMap.get(id) ?? [0, 0, 0];
        entry.targetPos.set(tgt[0], tgt[1], tgt[2]);
        entry.currentPos.lerp(entry.targetPos, 0.14);
        if (entry.currentPos.distanceToSquared(entry.targetPos) > 1e-6) anyNodeMoving = true;
        else entry.currentPos.copy(entry.targetPos);
        entry.group.position.copy(entry.currentPos);
        entry.haloMesh.quaternion.copy(camera.quaternion);

        const allowedByFilter = matchesFilter(entry.node, st.filter, st.showExternal);
        const matchesQuery =
          !query ||
          entry.node.title.toLowerCase().includes(query) ||
          entry.node.path.toLowerCase().includes(query) ||
          entry.node.url.toLowerCase().includes(query);

        entry.group.visible = allowedByFilter;
        if (!allowedByFilter) {
          entry.labelEl.classList.add('is-hidden');
          return;
        }

        const hex = palette[entry.node.health] ?? palette.healthy;
        entry.coreMat.color.setHex(hex);
        entry.coreMat.emissive.setHex(hex);
        entry.haloMat.color.setHex(hex);

        const isDirect = id === focusId;
        entry.labelEl.setAttribute('aria-pressed', String(id === st.selectedId));
        const isNeighbor = focusId ? connectedIds.has(id) : true;
        const dimmed = entry.node.kind !== 'home' && ((Boolean(focusId) && !isNeighbor) || (Boolean(query) && !matchesQuery));

        entry.coreMat.opacity = dimmed ? 0.22 : 1;
        entry.coreMat.transparent = dimmed;
        entry.coreMat.emissiveIntensity = isDirect ? 0.85 : dimmed ? 0.08 : 0.32;
        entry.haloMat.opacity = isDirect ? 0.85 : dimmed ? 0.05 : 0.28;

        entry.labelEl.classList.toggle('is-active', isDirect);
        entry.labelEl.classList.toggle('is-hover-target', id === hoverId);
        entry.labelEl.classList.toggle('is-hover-context', isNeighbor);
        entry.labelEl.classList.toggle('is-dimmed', dimmed);
        entry.labelEl.style.translate = '';
        if (hoverId && !isNeighbor) {
          entry.labelEl.classList.add('is-hidden');
          return;
        }

        let priority = 10;
        if (isDirect) priority = 100;
        else if (query && matchesQuery) priority = 90;
        else if (entry.node.kind === 'home') priority = 86;
        else if (focusId && isNeighbor) priority = 80;
        else if (entry.node.kind === 'hub') priority = 60;
        else if (entry.node.health === 'orphan' || entry.node.health === 'broken') priority = 50;
        else if (entry.node.kind === 'external-domain') priority = 25;
        else priority = 35 + Math.min(12, entry.node.inlinksBody);

        visibleEntries.push({ entry, priority });
      });

      nodesSettled = !anyNodeMoving;

      // Screen-space collision-free pill placement
      visibleEntries.sort((a, b) => b.priority - a.priority);
      const placedBoxes: ScreenBox[] = [];
      placedBoxes.push({ l: 0, r: stageW, t: 0, b: 12 });

      {
        // Read every size in one pass so layout is flushed once, not interleaved with class and style writes.
        // Labels that were never laid out (just created or not yet attached) are measured on every dirty frame
        // until they report a real size; a changed size schedules one more pass so placement converges.
        let sizeChanged = false;
        for (const { entry } of visibleEntries) {
          if (!measureLabels && entry.pillMeasured) continue;
          const measuredW = entry.labelEl.offsetWidth;
          const measuredH = entry.labelEl.offsetHeight;
          if (measuredW && measuredH) {
            if (Math.abs(measuredW - entry.pillW) > 0.5 || Math.abs(measuredH - entry.pillH) > 0.5) sizeChanged = true;
            entry.pillW = measuredW;
            entry.pillH = measuredH;
            entry.pillMeasured = true;
          }
        }
        const unmeasured = visibleEntries.some(({ entry }) => !entry.pillMeasured);
        measureAttempts = unmeasured ? measureAttempts + 1 : 0;
        // Bounded so a label that can never be measured cannot keep the loop awake forever.
        if (sizeChanged || (unmeasured && measureAttempts < 30)) forceHeavy = true;
      }

      for (const { entry } of visibleEntries) {
        entry.cssObj.getWorldPosition(tmpWorldPos);
        tmpVec.copy(tmpWorldPos).project(camera);
        if (tmpVec.z > 1 || tmpVec.z < -1) {
          entry.labelEl.classList.add('is-hidden');
          continue;
        }
        const sx = (tmpVec.x * 0.5 + 0.5) * stageW;
        const sy = (-tmpVec.y * 0.5 + 0.5) * stageH;
        const w = entry.pillW;
        const h = entry.pillH;

        const box: ScreenBox = {
          l: sx - w * 0.5,
          r: sx + w * 0.5,
          t: sy - h * 0.5,
          b: sy + h * 0.5,
        };

        if (entry.node.id === focusId || (!focusId && entry.node.kind === 'home')) {
          placedBoxes.push(box);
          entry.labelEl.classList.remove('is-hidden');
          continue;
        }

        // Move linked labels into nearby free slots, keeping the hovered label fixed.
        const offsets: Array<[number, number]> = [[0, 0]];
        if (hoverId && connectedIds.has(entry.node.id)) {
          for (const dy of [-28, 28, -56, 56, -84, 84, -112, 112, -140, 140]) offsets.push([0, dy]);
          for (const dx of [-(w + 12), w + 12]) {
            for (const dy of [0, -28, 28, -56, 56, -84, 84]) offsets.push([dx, dy]);
          }
        }
        const freeSlot = offsets.find(([dx, dy]) => {
          const candidate = { l: box.l + dx, r: box.r + dx, t: box.t + dy, b: box.b + dy };
          return candidate.l >= 8 && candidate.r <= stageW - 8 && candidate.t >= 12 &&
            candidate.b <= stageH - 8 && !placedBoxes.some((placed) => boxesOverlap(candidate, placed, 4));
        });
        if (!freeSlot) {
          entry.labelEl.classList.add('is-hidden');
        } else {
          const [dx, dy] = freeSlot;
          entry.labelEl.style.translate = `${dx}px ${dy}px`;
          placedBoxes.push({ l: box.l + dx, r: box.r + dx, t: box.t + dy, b: box.b + dy });
          entry.labelEl.classList.remove('is-hidden');
        }
      }

      // Update curved 3D edges & calm, sparse directional micro-pulses
      const densityScale = Math.max(
        0.38,
        Math.min(1, Math.sqrt(85 / Math.max(85, runtimeEdges.size)))
      );

      runtimeEdges.forEach((re) => {
        const srcEntry = runtimeNodes.get(re.edge.source);
        const dstEntry = runtimeNodes.get(re.edge.target);
        const isDirectConnection = Boolean(focusId) && (re.edge.source === focusId || re.edge.target === focusId);
        const isStructural = re.edge.kind === 'sitemap-hierarchy' ||
          re.edge.kind === 'external' || re.edge.kind === 'internal-chrome' ||
          srcEntry?.node.kind === 'home' ||
          (srcEntry?.node.kind === 'hub' && srcEntry.node.section === dstEntry?.node.section);
        const edgeAllowed =
          Boolean(srcEntry?.group.visible) &&
          Boolean(dstEntry?.group.visible) &&
          (re.edge.kind !== 'internal-chrome' || st.showChromeLinks) &&
          (re.edge.kind !== 'external' || st.showExternal) &&
          (st.showAllLinks || isDirectConnection || isStructural);

        re.line.visible = edgeAllowed;
        if (!edgeAllowed || !srcEntry || !dstEntry) {
          pulseInstanced.setMatrixAt(re.pulseSlot, hiddenMat4);
          return;
        }

        const pS = srcEntry.currentPos;
        const pT = dstEntry.currentPos;
        const srcHex = palette[srcEntry.node.health] ?? palette.healthy;
        const dstHex = palette[dstEntry.node.health] ?? palette.healthy;

        if (
          pS.distanceToSquared(re.lastSrc) > 0.0001 ||
          pT.distanceToSquared(re.lastDst) > 0.0001 ||
          srcHex !== re.lastSrcHex ||
          dstHex !== re.lastDstHex
        ) {
          re.lastSrc.copy(pS);
          re.lastDst.copy(pT);
          re.lastSrcHex = srcHex;
          re.lastDstHex = dstHex;

          re.p0.copy(pS);
          re.p2.copy(pT);
          tmpMid.addVectors(pS, pT).multiplyScalar(0.5);
          const chordLen = pS.distanceTo(pT);

          if (st.viewMode === 'globe') {
            const midLen = tmpMid.length();
            if (re.edge.kind === 'external') {
              if (midLen > 0.01) {
                tmpMid.normalize().multiplyScalar(GLOBE_SURFACE_RADIUS + chordLen * 0.25);
              }
            } else if (midLen > 0.2) {
              const targetArcR = Math.min(
                GLOBE_SURFACE_RADIUS + 0.65,
                Math.max(pS.length(), pT.length()) * 0.92 + chordLen * 0.14
              );
              tmpMid.normalize().multiplyScalar(targetArcR);
            } else {
              tmpMid.y += chordLen * 0.22;
            }
          } else {
            tmpMid.y += Math.min(1.6, chordLen * 0.16);
          }
          re.p1.copy(tmpMid);

          const posAttr = re.geom.getAttribute('position') as THREE.BufferAttribute;
          const colAttr = re.geom.getAttribute('color') as THREE.BufferAttribute;
          tmpColorA.setHex(srcHex);
          tmpColorB.setHex(dstHex);

          for (let s = 0; s <= 20; s++) {
            const t = s / 20;
            const inv = 1 - t;
            const x = inv * inv * re.p0.x + 2 * inv * t * re.p1.x + t * t * re.p2.x;
            const y = inv * inv * re.p0.y + 2 * inv * t * re.p1.y + t * t * re.p2.y;
            const z = inv * inv * re.p0.z + 2 * inv * t * re.p1.z + t * t * re.p2.z;
            posAttr.setXYZ(s, x, y, z);
            colAttr.setXYZ(
              s,
              THREE.MathUtils.lerp(tmpColorA.r, tmpColorB.r, t),
              THREE.MathUtils.lerp(tmpColorA.g, tmpColorB.g, t),
              THREE.MathUtils.lerp(tmpColorA.b, tmpColorB.b, t)
            );
          }
          posAttr.needsUpdate = true;
          colAttr.needsUpdate = true;
          re.geom.computeBoundingSphere();
        }

        const isHighlighted =
          Boolean(focusId) && (re.edge.source === focusId || re.edge.target === focusId);
        const isDimmed = Boolean(focusId) && !isHighlighted;
        re.mat.opacity = isHighlighted
          ? 0.72
          : isDimmed
            ? 0.035
            : (re.edge.kind === 'sitemap-hierarchy'
                ? 0.26
                : re.edge.kind === 'external'
                  ? 0.12
                  : 0.16) * densityScale;

        const shouldAnimatePulse =
          st.showPulses && (focusId ? isHighlighted : re.ambientEligible);

        if (shouldAnimatePulse) {
          re.pulseHighlighted = isHighlighted;
          pulseEdges.push(re);
          writePulse(re, elapsed, isHighlighted);
        } else {
          pulseInstanced.setMatrixAt(re.pulseSlot, hiddenMat4);
        }
      });

      pulseInstanced.instanceMatrix.needsUpdate = true;

      renderer.render(scene, camera);
      labelRenderer.render(scene, camera);
    };

    wakeLoopRef.current = () => {
      forceHeavy = true;
      clock.getDelta();
    };
    animate();

    return () => {
      disposed = true;
      window.cancelAnimationFrame(rafId);
      resizeObs.disconnect();
      labelRenderer.domElement.removeEventListener('mouseover', onLabelOver);
      labelRenderer.domElement.removeEventListener('mouseout', onLabelOut);
      renderer.domElement.removeEventListener('pointermove', onPointerMove);
      renderer.domElement.removeEventListener('pointerleave', onPointerLeave);
      renderer.domElement.removeEventListener('pointerdown', onPointerDown);
      renderer.domElement.removeEventListener('pointerup', onPointerUp);
      renderer.domElement.removeEventListener('dblclick', onDblClick);
      renderer.domElement.removeEventListener('webglcontextlost', handleContextLost);
      clearRuntimeGraph();
      clearDynamicSectors();
      pulseInstanced.dispose();
      for (const d of disposables) d.dispose();
      controls.dispose();
      discoverCameraRef.current = null;
      renderer.dispose();
      renderer.domElement.remove();
      labelRenderer.domElement.remove();
    };
  }, []);

  // Rebuild Three.js graph whenever manifest changes
  useEffect(() => {
    syncGraphRef.current?.(manifest);
    cameraFlyRef.current = {
      active: true,
      camTarget:
        viewMode === 'road'
          ? new THREE.Vector3(0, 1.2, 20.5)
          : new THREE.Vector3(-4.4, 5.0, 16.0),
      lookTarget: new THREE.Vector3(0, 0, 0),
    };
  }, [manifest]);

  // Reframe camera on viewMode or resetSignal
  useEffect(() => {
    if (viewMode === 'road') {
      cameraFlyRef.current = {
        active: true,
        camTarget: new THREE.Vector3(0, 1.0, 20.5),
        lookTarget: new THREE.Vector3(0, 0, 0),
      };
    } else {
      cameraFlyRef.current = {
        active: true,
        camTarget: new THREE.Vector3(-4.4, 5.0, 16.0),
        lookTarget: new THREE.Vector3(0, 0, 0),
      };
    }
  }, [viewMode, resetSignal]);

  // Fly to a requested node
  useEffect(() => {
    if (!flyRequest || !layouts) return;
    const map =
      viewMode === 'road'
        ? layouts.road
        : viewMode === 'clusters'
          ? layouts.clusters
          : layouts.globe;
    const target = map.get(flyRequest.nodeId);
    if (!target) return;
    const p = new THREE.Vector3(...target);
    const dir = p.length() > 0.2 ? p.clone().normalize() : new THREE.Vector3(0, 0.3, 1).normalize();
    cameraFlyRef.current = {
      active: true,
      lookTarget: p.clone(),
      camTarget: p.clone().addScaledVector(dir, 5.2).add(new THREE.Vector3(0, 1.1, 0)),
    };
  }, [flyRequest, layouts, viewMode]);

  // Snap camera to cardinal gizmo axis
  useEffect(() => {
    if (!axisSnapRequest) return;
    const dist = 16.5;
    const map: Record<CameraAxisSnap, [number, number, number]> = {
      '+X': [dist, 0.5, 0],
      '-X': [-dist, 0.5, 0],
      '+Y': [0, dist, 0.01],
      '-Y': [0, -dist, 0.01],
      '+Z': [0, 0.5, dist],
      '-Z': [0, 0.5, -dist],
    };
    cameraFlyRef.current = {
      active: true,
      camTarget: new THREE.Vector3(...map[axisSnapRequest.axis]),
      lookTarget: new THREE.Vector3(0, 0, 0),
    };
  }, [axisSnapRequest]);

  return <div ref={mountRef} className="wo-canvas-stage">
    {manifest && !renderUnavailable && <MapDiscoveryControls
      key={manifest.siteId + ':' + manifest.capturedAt}
      manifest={manifest}
      nodes={discoveryNodes}
      selectedId={effectiveSelectedId}
      showChromeLinks={showChromeLinks}
      onNavigate={discoverNode}
      onInspect={inspectDiscoveryNode}
    />}
    {renderUnavailable && <div className="wo-webgl-fallback" role="status">
      <strong>3D view unavailable</strong>
      <p>Capture pages, browse the Page explorer and open reports while graphics are unavailable.</p>
    </div>}
  </div>;
};
