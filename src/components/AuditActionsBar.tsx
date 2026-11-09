import { useState, type ReactNode } from 'react';
import { Archive, Copy, ExternalLink, FileJson, X } from 'lucide-react';
import type { ArchivePlan, AuditActions, PublishAuditResult, SiteGraphManifest } from '../types/site';

const mb = (bytes: number) => `${(bytes / 1048576).toFixed(1)} MB`;

interface Props {
  manifest: SiteGraphManifest;
  actions?: AuditActions;
  onOpenUrl: (url: string) => void;
  /** Called after a capture has been moved to the trash folder, so the view can refresh its site list. */
  onArchived: () => void;
}

/**
 * Publish audit: writes the client report JSON (allowlisted fields only) to the reports folder in the settings, under a random file name.
 * Archive audit: lists exactly what would move, asks for the site name again, then moves it to the vault's trash folder. Nothing is deleted.
 */
export function useAuditActions({ manifest, actions, onOpenUrl, onArchived }: Props): { buttons: ReactNode; dialogs: ReactNode } {
  const [mode, setMode] = useState<'publish' | 'archive' | null>(null);
  const [approver, setApprover] = useState(actions?.approver ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [published, setPublished] = useState<PublishAuditResult | null>(null);
  const [plan, setPlan] = useState<ArchivePlan | null>(null);
  const [typed, setTyped] = useState('');
  const [done, setDone] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const open = (next: 'publish' | 'archive') => {
    setMode(next); setError(null); setPublished(null); setPlan(null); setTyped(''); setDone(null); setCopied(false);
    if (next === 'archive' && actions) {
      setBusy(true);
      actions.previewArchive(manifest.siteId).then(setPlan).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
    }
  };
  const close = () => { setMode(null); setError(null); };
  const publish = () => {
    if (!actions) return;
    setBusy(true); setError(null);
    actions.publish(manifest.siteId, approver).then(setPublished).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  const archive = () => {
    if (!actions) return;
    setBusy(true); setError(null);
    actions.archive(manifest.siteId, typed).then((r) => { setDone(`Moved ${r.files} files of ${r.domain} to ${r.trash}/. Nothing was deleted; REMOVED.txt there says how to restore it.`); setPlan(null); onArchived(); }).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };

  if (!actions) return { buttons: null, dialogs: null };

  const buttons = <>
    <button type="button" className="wo-audit-button" disabled={busy} onClick={() => open('publish')} aria-expanded={mode === 'publish'} aria-label="Publish audit" title="Publish audit: create the client report file"><FileJson size={14} aria-hidden="true" /> Publish</button>
    <button type="button" className="wo-audit-button" disabled={busy} onClick={() => open('archive')} aria-expanded={mode === 'archive'} aria-label="Archive audit" title="Archive audit: move this capture to the trash folder"><Archive size={14} aria-hidden="true" /> Archive</button>
  </>;

  const dialogs = mode === null ? null : <div className="wo-audit-actionbar">
    {mode === 'publish' && <div className="wo-audit-confirm" role="dialog" aria-label="Publish audit">
      <button type="button" className="wo-audit-close" disabled={busy} onClick={close} aria-label="Close"><X size={16} aria-hidden="true" /></button>
      {!published ? <>
        <b>Publish the client report for {manifest.domain}?</b>
        <p>This creates a client report from the capture's findings. It includes page titles, public URLs, the site map and audit findings. Vault paths, page text, resource lists and agency notes are excluded. Review the findings before approving this report.</p>
        {!actions.publishReady && <p className="wo-audit-confirm-warn">Set a publish target or the client reports folder in the Web-Obs settings first.</p>}
        {actions.publishTargetLabel ? <p className="wo-audit-confirm-small">Destination: <code>{actions.publishTargetLabel}</code>. A web or SSH destination sends the report outside your vault.</p> : <p className="wo-audit-confirm-small">The report is saved to your configured reports folder. If no destination is configured, you will choose one before continuing.</p>}
        <label className="wo-audit-confirm-field">Approved by <input value={approver} onChange={(e) => setApprover(e.target.value)} placeholder="Your name" autoComplete="off" /></label>
        <div className="wo-audit-confirm-row"><button type="button" className="wo-audit-button is-primary" disabled={busy || !actions.publishReady || !approver.trim()} onClick={publish}>{busy ? 'Creating…' : 'Approve and create report'}</button><button type="button" className="wo-audit-link" disabled={busy} onClick={close}>Cancel</button></div>
      </> : <>
        <b>{published.pushedTo ? 'Client report published' : 'Client report created'}</b>
        {published.pushedTo
          ? <p>The report ({published.sizeKb} KB, {published.findings} findings) was sent to <code>{published.pushedTo}</code>. The link stops working on {new Date(published.expires ?? '').toLocaleString()}. It is shown only now: copy it before you close this.</p>
          : <p><code>{published.file}</code> ({published.sizeKb} KB, {published.findings} findings) was saved in <code>{published.folder}</code>. The name is random on purpose: it says nothing about the client.</p>}
        {published.top.length > 0 && <p className="wo-audit-confirm-small">The tour leads with: {published.top.join('; ')}.</p>}
        {published.link ? <>
          <p className="wo-audit-confirm-link"><a href={published.link} onClick={(e) => { e.preventDefault(); onOpenUrl(published.link!); }}>{published.link}</a></p>
          <div className="wo-audit-confirm-row">
            <button type="button" className="wo-audit-button" onClick={() => { void (navigator.clipboard?.writeText(published.link!) ?? Promise.reject(new Error('Clipboard unavailable'))).then(() => setCopied(true)).catch(() => setError('Could not copy the link. Select and copy it manually.')); }}><Copy size={14} aria-hidden="true" /> {copied ? 'Copied' : 'Copy link'}</button>
            <button type="button" className="wo-audit-button" onClick={() => onOpenUrl(published.link!)}><ExternalLink size={14} aria-hidden="true" /> Open</button>
          </div>
        </> : <p className="wo-audit-confirm-small">Set a report link base in the Web-Obs settings to get a link here.</p>}
      </>}
      {error && <p className="wo-audit-confirm-warn" role="alert">{error}</p>}
    </div>}

    {mode === 'archive' && <div className="wo-audit-confirm" role="alertdialog" aria-label="Archive audit">
      <button type="button" className="wo-audit-close" disabled={busy} onClick={close} aria-label="Close"><X size={16} aria-hidden="true" /></button>
      {done ? <p role="status">{done}</p> : <>
        <b>Archive {manifest.domain}?</b>
        {busy && !plan && <p>Checking what would move…</p>}
        {plan && <>
          <p>These folders will be <b>moved</b> to <code>.web-obs/trash/{plan.domain}-&lt;time&gt;/</code> inside your vault. Nothing is deleted.</p>
          <ul>{plan.items.map((i) => <li key={i.rel}><code>{i.rel}/</code> ({i.label}): {i.files} files, {mb(i.bytes)}</li>)}</ul>
          <p className="wo-audit-confirm-small">Other sites, and any report you published from this capture, are not touched. In total {plan.files} files, {mb(plan.bytes)}.</p>
          <label className="wo-audit-confirm-field">Type <b>{plan.domain}</b> to confirm <input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} aria-label="Type the site name to confirm" /></label>
          <div className="wo-audit-confirm-row"><button type="button" className="wo-audit-button is-danger" disabled={busy || typed !== plan.domain} onClick={archive}>{busy ? 'Moving…' : 'Move to the trash folder'}</button><button type="button" className="wo-audit-link" disabled={busy} onClick={close}>Cancel</button></div>
        </>}
      </>}
      {error && <p className="wo-audit-confirm-warn" role="alert">{error}</p>}
    </div>}
  </div>;
  return { buttons, dialogs };
}
