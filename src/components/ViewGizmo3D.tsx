import { forwardRef, useImperativeHandle, useRef } from 'react';
import * as THREE from 'three';
import type { CameraAxisSnap } from '../types/site';

export interface ViewGizmoHandle {
  updateCameraQuaternion: (quat: THREE.Quaternion) => void;
}

interface ViewGizmo3DProps {
  onSnapAxis: (axis: CameraAxisSnap) => void;
}

interface AxisEndpointSpec {
  id: CameraAxisSnap;
  axis: 'x' | 'y' | 'z';
  sign: 1 | -1;
  label: string;
  tip: string;
  vec: THREE.Vector3;
}

const ENDPOINTS: AxisEndpointSpec[] = [
  {
    id: '+X',
    axis: 'x',
    sign: 1,
    label: 'E',
    tip: 'East Meridian (+X) · click again to flip',
    vec: new THREE.Vector3(1, 0, 0),
  },
  {
    id: '-X',
    axis: 'x',
    sign: -1,
    label: '',
    tip: 'West Meridian (-X)',
    vec: new THREE.Vector3(-1, 0, 0),
  },
  {
    id: '+Y',
    axis: 'y',
    sign: 1,
    label: 'N',
    tip: 'North Pole / Top Sitemap View (+Y) · click again to flip',
    vec: new THREE.Vector3(0, 1, 0),
  },
  {
    id: '-Y',
    axis: 'y',
    sign: -1,
    label: '',
    tip: 'South Pole / Orphan Drift View (-Y)',
    vec: new THREE.Vector3(0, -1, 0),
  },
  {
    id: '+Z',
    axis: 'z',
    sign: 1,
    label: 'Z',
    tip: 'Front Globe View (+Z) · click again to flip',
    vec: new THREE.Vector3(0, 0, 1),
  },
  {
    id: '-Z',
    axis: 'z',
    sign: -1,
    label: '',
    tip: 'Rear Globe View (-Z)',
    vec: new THREE.Vector3(0, 0, -1),
  },
];

export const ViewGizmo3D = forwardRef<ViewGizmoHandle, ViewGizmo3DProps>(
  ({ onSnapAxis }, ref) => {
    const btnRefs = useRef<Record<string, HTMLButtonElement | null>>({});
    const lineRefs = useRef<Record<'x' | 'y' | 'z', SVGLineElement | null>>({
      x: null,
      y: null,
      z: null,
    });
    const invQuatRef = useRef(new THREE.Quaternion());
    const tmpVecRef = useRef(new THREE.Vector3());
    const lastAlignedRef = useRef<CameraAxisSnap | null>('+Z');

    useImperativeHandle(ref, () => ({
      updateCameraQuaternion(cameraQuat: THREE.Quaternion) {
        const inv = invQuatRef.current.copy(cameraQuat).invert();
        const tv = tmpVecRef.current;
        const radius = 23;
        let frontMost: { id: CameraAxisSnap; z: number } = { id: '+Z', z: -2 };

        for (const ep of ENDPOINTS) {
          tv.copy(ep.vec).applyQuaternion(inv);
          const cx = 32 + tv.x * radius;
          const cy = 32 - tv.y * radius;
          const depth01 = (tv.z + 1) * 0.5;

          if (tv.z > frontMost.z) {
            frontMost = { id: ep.id, z: tv.z };
          }

          if (ep.sign === 1) {
            const lineEl = lineRefs.current[ep.axis];
            if (lineEl) {
              lineEl.setAttribute('x2', cx.toFixed(1));
              lineEl.setAttribute('y2', cy.toFixed(1));
              lineEl.style.opacity = (0.32 + depth01 * 0.58).toFixed(2);
            }
          }

          const btn = btnRefs.current[ep.id];
          if (btn) {
            const scale = 0.78 + depth01 * 0.26;
            btn.style.transform = `translate(${cx.toFixed(1)}px, ${cy.toFixed(1)}px) translate(-50%, -50%) scale(${scale.toFixed(2)})`;
            btn.style.zIndex = String(Math.round(10 + tv.z * 8));
            btn.style.opacity = (0.38 + depth01 * 0.62).toFixed(2);
          }
        }

        lastAlignedRef.current = frontMost.z > 0.96 ? frontMost.id : null;
      },
    }));

    const flipAxis = (axis: CameraAxisSnap): CameraAxisSnap => {
      const sign = axis.startsWith('+') ? '-' : '+';
      return `${sign}${axis.slice(1)}` as CameraAxisSnap;
    };

    return (
      <div className="wo-view-gizmo" role="group" aria-label="3D orientation gizmo">
        <svg viewBox="0 0 64 64" className="wo-view-gizmo-svg" aria-hidden="true">
          <circle cx="32" cy="32" r="28" className="wo-view-gizmo-ring" />
          <line
            ref={(el) => {
              lineRefs.current.x = el;
            }}
            x1="32"
            y1="32"
            x2="55"
            y2="32"
            className="wo-gizmo-line wo-gizmo-x"
          />
          <line
            ref={(el) => {
              lineRefs.current.y = el;
            }}
            x1="32"
            y1="32"
            x2="32"
            y2="9"
            className="wo-gizmo-line wo-gizmo-y"
          />
          <line
            ref={(el) => {
              lineRefs.current.z = el;
            }}
            x1="32"
            y1="32"
            x2="32"
            y2="32"
            className="wo-gizmo-line wo-gizmo-z"
          />
        </svg>

        {ENDPOINTS.map((ep) => (
          <button
            key={ep.id}
            ref={(el) => {
              btnRefs.current[ep.id] = el;
            }}
            type="button"
            title={ep.tip}
            aria-label={ep.tip}
            className={`wo-gizmo-cap wo-gizmo-cap-${ep.axis} ${ep.sign < 0 ? 'is-neg' : 'is-pos'}`}
            onClick={() => {
              const next =
                lastAlignedRef.current === ep.id ? flipAxis(ep.id) : ep.id;
              onSnapAxis(next);
            }}
          >
            {ep.label}
          </button>
        ))}
      </div>
    );
  }
);

ViewGizmo3D.displayName = 'ViewGizmo3D';
