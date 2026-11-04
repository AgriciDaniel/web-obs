import React, { useState } from 'react';
import type { SiteGraphManifest } from '../types/site';
import { buildDiscoveryChecklist, type DiscoveryRow, type ScoreItem } from '../data/discoveryChecklist';
import { Disclosure, StatusPill, type Status } from './ui';

const SCORE: Record<ScoreItem['state'], { status: Status; label: string }> = {
  pass: { status: 'good', label: 'Pass' },
  warn: { status: 'warning', label: 'Check' },
  fail: { status: 'critical', label: 'Fail' },
  unknown: { status: 'neutral', label: 'Not assessed' },
};
const FILE: Record<DiscoveryRow['state'], { status: Status; label: string }> = {
  ok: { status: 'good', label: 'Found' },
  warn: { status: 'warning', label: 'Check' },
  missing: { status: 'warning', label: 'Missing' },
  unknown: { status: 'neutral', label: 'Not found' },
};

function copyText(text: string): boolean {
  try {
    void navigator.clipboard?.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** One status per area with a one-line reason. Not a combined score. */
export const SiteHealthList: React.FC<{ manifest: SiteGraphManifest }> = ({ manifest }) => {
  const { score } = buildDiscoveryChecklist(manifest);
  return <ul className="wo-dr-status-list" aria-label="Site health by area">
    {score.map((item) => <li key={item.id} className="wo-dr-status-row">
      <span className="wo-dr-status-name">{item.label}</span>
      <StatusPill status={SCORE[item.state].status} label={SCORE[item.state].label} />
      <span className="wo-dr-status-reason" title={item.detail}>{item.detail}</span>
    </li>)}
  </ul>;
};

function StarterFile({ fix }: { fix: string }) {
  const [copied, setCopied] = useState(false);
  return <Disclosure summary="Starter file">
    <pre className="wo-dr-pre">{fix}</pre>
    <button type="button" className="wo-btn-secondary wo-btn-xs" onClick={() => setCopied(copyText(fix))}>{copied ? 'Copied' : 'Copy'}</button>
  </Disclosure>;
}

/** Discovery files: name and status, with the reason shown only when something needs a look. */
export const DiscoveryFilesList: React.FC<{ manifest: SiteGraphManifest }> = ({ manifest }) => {
  const { rows } = buildDiscoveryChecklist(manifest);
  const order = (row: DiscoveryRow) => (row.state === 'warn' || row.state === 'missing' ? 0 : row.state === 'ok' ? 1 : 2);
  const sorted = [...rows].sort((a, b) => order(a) - order(b));
  return <ul className="wo-dr-status-list" aria-label="Discovery files">
    {sorted.map((row) => {
      const state = FILE[row.state];
      const needsLook = row.state === 'warn' || row.state === 'missing';
      return <li key={row.id} className="wo-dr-status-row" title={needsLook ? undefined : row.detail}>
        <span className="wo-dr-status-name">{row.label}</span>
        <StatusPill status={state.status} label={row.badge ?? state.label} />
        {needsLook && <span className="wo-dr-status-reason">{row.detail}</span>}
        {row.fix && <div className="wo-dr-status-extra"><StarterFile fix={row.fix} /></div>}
      </li>;
    })}
  </ul>;
};
