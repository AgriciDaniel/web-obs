import React from 'react';
import type { SiteGraphManifest } from '../types/site';
import { buildDiscoveryChecklist } from '../data/discoveryChecklist';

const STATE_LABEL: Record<string, string> = { ok: 'Found', warn: 'Check', missing: 'Missing', unknown: 'Not found', pass: 'Pass', fail: 'Fail' };
const STATE_CLASS: Record<string, string> = { ok: 'wo-chip-hub', pass: 'wo-chip-hub', warn: 'wo-chip-warn', missing: 'wo-chip-warn', fail: 'wo-chip-fail', unknown: '' };

function copyText(text: string): void {
  try {
    void navigator.clipboard?.writeText(text);
  } catch {
    /* clipboard unavailable */
  }
}

export const DiscoveryPanel: React.FC<{ manifest: SiteGraphManifest }> = ({ manifest }) => {
  const { rows, score } = buildDiscoveryChecklist(manifest);
  return (
    <>
      <div className="wo-inspector-section">
        <div className="wo-section-title">Site health</div>
        <div className="wo-scorecard" role="list">
          {score.map((item) => (
            <div key={item.id} className="wo-score-item" role="listitem" title={item.detail}>
              <span className="wo-score-label">{item.label}</span>
              <span className={`wo-schema-chip ${STATE_CLASS[item.state]}`}>{item.state === 'unknown' ? 'Not assessed' : STATE_LABEL[item.state]}</span>
              <span className="wo-score-detail">{item.detail}</span>
            </div>
          ))}
        </div>
        <p className="wo-evidence-note">Each area is a status, not a combined score. Header checks cover the homepage only.</p>
      </div>
      <div className="wo-inspector-section">
        <div className="wo-section-title">Discovery files</div>
        <div className="wo-scorecard" role="list">
          {rows.map((row) => (
            <div key={row.id} className="wo-score-item" role="listitem">
              <span className="wo-score-label">{row.label}</span>
              <span className={`wo-schema-chip ${STATE_CLASS[row.state]}`}>{row.badge ?? STATE_LABEL[row.state]}</span>
              <span className="wo-score-detail">{row.detail}</span>
              {row.fix && (
                <details className="wo-fix">
                  <summary>Suggested fix</summary>
                  <pre>{row.fix}</pre>
                  <button type="button" className="wo-btn-secondary" onClick={() => copyText(row.fix as string)}>
                    Copy
                  </button>
                </details>
              )}
            </div>
          ))}
        </div>
      </div>
    </>
  );
};
