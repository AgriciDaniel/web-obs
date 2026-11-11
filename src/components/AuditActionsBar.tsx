import { useEffect, useId, useRef, useState, type ReactNode, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { Archive, Copy, ExternalLink, FileJson, Info, TriangleAlert, X } from 'lucide-react';
import { resolveDefaultLook } from '../data/defaultLook';
import { previewForm, type StyleForm } from '../data/profileForm';
import { StyleProfileForm } from './StyleProfileForm';
import type { ArchivePlan, AuditActions, PublishAuditResult, SiteGraphManifest, StyleChoiceInfo, StylePreview } from '../types/site';

const mb = (bytes: number) => `${(bytes / 1048576).toFixed(1)} MB`;
/** The file a choice id points to, for the "saved" message. */
const profileFileOf = (id: string) => (id === 'agency' ? 'agency.json' : id.startsWith('client:') ? `clients/${id.slice(7)}` : id);

interface Props {
  manifest: SiteGraphManifest;
  actions?: AuditActions;
  onOpenUrl: (url: string) => void;
  /** Called after a capture has been moved to the trash folder, so the view can refresh its site list. */
  onArchived: () => void;
}

/** A calm message box: information, a caution, or an error. Errors are announced to screen readers. */
export function Callout({ kind, children }: { kind: 'info' | 'caution' | 'error'; children: ReactNode }) {
  return (
    <div className={`wo-audit-callout is-${kind}`} role={kind === 'error' ? 'alert' : undefined}>
      {kind === 'info' ? <Info size={15} aria-hidden="true" /> : <TriangleAlert size={15} aria-hidden="true" />}
      <div>{children}</div>
    </div>
  );
}

/**
 * Publish audit: writes the client report JSON (allowlisted fields only) to the reports folder in the settings, under a random file name.
 * Archive audit: lists exactly what would move, asks for the site name again, then moves it to the vault's trash folder. Nothing is deleted.
 *
 * The dialog has a scrolling body and a button row that is always visible, so a tall form never hides its buttons. Its colors come from
 * Obsidian's own variables (see audit.css), so it follows the active theme, light or dark.
 */
type LookActions = Required<Pick<AuditActions, 'styleChoices' | 'previewStyle' | 'styleDraft' | 'saveStyleProfile' | 'styleEdit' | 'saveStyleEdit'>>;
/** The Look needs all six style members; a host without them shows no Look choice and publishes as before. */
const lookOf = (a: AuditActions | undefined): (AuditActions & LookActions) | undefined => (a?.styleChoices && a.previewStyle && a.styleDraft && a.saveStyleProfile && a.styleEdit && a.saveStyleEdit ? (a as AuditActions & LookActions) : undefined);

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
  // The look sent with the report: Default (nothing extra), the agency profile, or one client profile.
  const [styleChoices, setStyleChoices] = useState<StyleChoiceInfo[]>([]);
  const [styleId, setStyleId] = useState('default');
  const [stylePreview, setStylePreview] = useState<StylePreview | null>(null);
  // The create-a-profile panel: shown when Agency or Client is chosen and there is no profile file yet. Nothing is written until Save.
  // `initial` is the form as it was when it opened (to tell unsaved changes); `editId` and `baseHash` are set when a SAVED profile is being edited.
  const [draft, setDraft] = useState<{ form: StyleForm; hints: string[]; initial: StyleForm; editId?: string; baseHash?: string } | null>(null);
  /** Why the look that was preselected was chosen, one line (from the Default look setting). */
  const [why, setWhy] = useState('');
  const [whyId, setWhyId] = useState('');
  /** Asked when something would throw away unsaved changes; `then` is the look to go to. */
  const [discard, setDiscard] = useState<{ then: string } | null>(null);
  /** Set when the file already exists: the person is asked before it is replaced; `thenPublish` says what to do after. */
  const [replaceAsk, setReplaceAsk] = useState<{ thenPublish: boolean } | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const uid = useId();
  const titleId = `${uid}-title`, introId = `${uid}-intro`, reasonId = `${uid}-reason`, approverId = `${uid}-approver`, lookId = `${uid}-look`, typedId = `${uid}-typed`;
  const dialogRef = useRef<HTMLDivElement>(null);
  // Keyboard users land in the dialog when it opens, and Escape closes it.
  useEffect(() => { if (mode) dialogRef.current?.focus({ preventScroll: true }); }, [mode]);
  // An error is announced and also brought into view, so it is never hidden below the fold of the scrolling body.
  useEffect(() => { if (error) dialogRef.current?.querySelector('.wo-audit-callout.is-error')?.scrollIntoView({ block: 'nearest' }); }, [error]);

  const setField = (k: keyof StyleForm, v: string) => setDraft((d) => (d ? { ...d, form: { ...d.form, [k]: v } } : d));
  const lk = lookOf(actions);
  // The look most recently asked for. A preview or draft that arrives after another look was picked is dropped, so it never shows for the wrong look.
  const wantedStyle = useRef('default');
  const pickStyle = (id: string, list: StyleChoiceInfo[] = styleChoices) => {
    wantedStyle.current = id;
    setStyleId(id); setStylePreview(null); setDraft(null); setReplaceAsk(null);
    const stillWanted = () => wantedStyle.current === id;
    if (list.find((c) => c.id === id)?.missing) {
      lk?.styleDraft(manifest.siteId, id).then((d) => { if (stillWanted()) setDraft({ ...d, initial: d.form }); }).catch(() => { if (stillWanted()) setStylePreview({ id, label: id, summary: '', notes: [], problem: 'The starting values could not be prepared.' }); });
      return;
    }
    lk?.previewStyle(id).then((p) => { if (stillWanted()) setStylePreview(p); }).catch(() => { if (stillWanted()) setStylePreview({ id, label: id, summary: '', notes: [], problem: 'That look could not be read.' }); });
  };

  const open = (next: 'publish' | 'archive') => {
    setMode(next); setError(null); setPublished(null); setPlan(null); setTyped(''); setDone(null); setCopied(false); setSaved(null); setReplaceAsk(null); setDiscard(null);
    // Start from Default every time, so a look picked the last time (perhaps for another site) is never used before this site's list has loaded.
    wantedStyle.current = 'default'; setStyleId('default'); setStyleChoices([]); setStylePreview(null); setDraft(null);
    if (next === 'publish' && actions && lk) {
      lk.styleChoices(manifest.domain).then((list) => { setStyleChoices(list); const r = resolveDefaultLook({ domain: manifest.domain, choices: list, preference: actions.stylePreference, lastId: actions.lastStyleId }); setWhy(r.reason); setWhyId(r.id); pickStyle(r.id, list); }).catch(() => { setStyleChoices([]); setStyleId('default'); setStylePreview(null); });
    }
    if (next === 'archive' && actions) {
      setBusy(true);
      actions.previewArchive(manifest.siteId).then(setPlan).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
    }
  };
  const close = () => { setMode(null); setError(null); };
  /** Publishes with a look that is already saved (or the built-in one). It never publishes a look that was not saved. */
  const publishWith = (id: string) => {
    if (!actions) return;
    setBusy(true); setError(null);
    actions.publish(manifest.siteId, approver, id).then(setPublished).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  const publish = () => publishWith(styleId);
  /**
   * Saves the form as a profile file. With `thenPublish`, publishes with that saved profile right after; if the save did not happen, nothing is published.
   * An existing file is replaced only after the person confirms.
   */
  const saveProfile = (thenPublish: boolean, overwrite = false) => {
    if (!lk || !draft) return;
    setBusy(true); setError(null); setSaved(null);
    lk.saveStyleProfile(manifest.siteId, styleId, draft.form, overwrite).then(async (r) => {
      if (r.ok && r.id) {
        const list = await lk.styleChoices(manifest.domain); setStyleChoices(list); pickStyle(r.id, list);
        if (thenPublish) publishWith(r.id); else setSaved(`Profile saved as ${profileFileOf(r.id)} and selected below. Press Approve and create report to publish with it.`);
      } else if (r.code === 'exists') setReplaceAsk({ thenPublish });
      else setError(r.message ?? 'The profile could not be saved.');
    }).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  const useDefault = () => { setDraft(null); setReplaceAsk(null); pickStyle('default'); };
  const sendDefault = () => { useDefault(); publishWith('default'); };
  // ---- editing a saved profile and the unsaved-changes guard ----
  const dirty = Boolean(draft) && JSON.stringify(draft!.form) !== JSON.stringify(draft!.initial);
  const current = styleChoices.find((c) => c.id === styleId);
  const canEdit = Boolean(current && current.kind !== 'default' && !current.missing);
  /** Picking another look while a form has unsaved changes asks first. */
  const requestPick = (id: string) => { if (draft && dirty && id !== styleId) { setDiscard({ then: id }); return; } setDiscard(null); pickStyle(id); };
  /** Cancel returns to the look the form came from (or Default for a new profile); with unsaved changes it asks first. */
  const cancelDraft = () => { const back = draft?.editId ?? 'default'; if (dirty) { setDiscard({ then: back }); return; } setDraft(null); setReplaceAsk(null); pickStyle(back); };
  const confirmDiscard = () => { const to = discard?.then ?? 'default'; setDiscard(null); setDraft(null); setReplaceAsk(null); pickStyle(to); };
  const startEdit = () => {
    if (!lk) return;
    setError(null); setSaved(null);
    lk.styleEdit(styleId).then((r) => { if (r.ok) setDraft({ form: r.form, hints: [], initial: r.form, editId: styleId, baseHash: r.baseHash }); else setError(r.message); }).catch((e: Error) => setError(e.message));
  };
  /** Saves the changes of a saved profile in place (the old version stays as a .bak copy). With thenPublish the report is published with it; nothing is published if the save did not happen. */
  const saveEdit = (thenPublish: boolean) => {
    if (!lk || !draft?.editId) return;
    if (!dirty) { if (thenPublish) publishWith(draft.editId); return; }
    setBusy(true); setError(null); setSaved(null);
    lk.saveStyleEdit(draft.editId, draft.initial, draft.form, draft.baseHash ?? '').then(async (r) => {
      if (r.ok) {
        const id = draft.editId!; const list = await lk.styleChoices(manifest.domain); setStyleChoices(list); pickStyle(id, list);
        if (thenPublish) publishWith(id); else setSaved(`Changes saved to ${profileFileOf(id)}. The previous version is kept next to it as a .bak copy.`);
      } else setError(r.message ?? 'The changes could not be saved.');
    }).catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
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

  const canPublish = !busy && actions.publishReady && Boolean(approver.trim());
  const lookBlocked = Boolean(stylePreview?.problem);
  const formOk = draft ? previewForm(draft.form).ok : true;
  // Why a button is off, in plain words, shown next to the buttons (and read by screen readers through aria-describedby).
  const reason = busy ? null
    : !actions.publishReady ? 'Set a publish target or a client reports folder in the Web-Obs settings to publish.'
    : !approver.trim() ? 'Fill in Approved by to publish.'
    : draft && !formOk ? 'Fix the highlighted fields to save this profile.'
    : lookBlocked ? 'This look needs a fix before it can be sent.'
    : null;
  const formHint = formOk ? undefined : 'Fix the highlighted fields first';
  const onKey = (e: ReactKeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };

  const dialogs = mode === null ? null : <div className="wo-audit-actionbar">
    {mode === 'publish' && <div ref={dialogRef} tabIndex={-1} className="wo-audit-confirm" role="dialog" aria-label="Publish audit" aria-describedby={introId} onKeyDown={onKey}>
      <div className="wo-audit-confirm-head">
        <h2 id={titleId} className="wo-audit-confirm-title"><span>{published ? (published.pushedTo ? 'Client report published' : 'Client report created') : 'Publish the client report'}</span> <span className="wo-audit-confirm-sub">for <b>{manifest.domain}</b></span></h2>
      </div>
      <div className="wo-audit-confirm-scroll">
        {!published ? <>
          {!actions.publishReady
            ? <Callout kind="caution">Set a publish target or the client reports folder in the Web-Obs settings first.</Callout>
            : <div id={introId} className="wo-audit-destination">{actions.publishTargetLabel
              ? <>Sent to <code>{actions.publishTargetLabel}</code>, not saved on this computer.</>
              : <>Saved as one file in your client reports folder.</>}
              {' '}<details className="wo-audit-info"><summary>What is sent</summary><span>A person approves what goes to a client. The report carries only the fields on the export allowlist: no vault paths, page text, resource lists or agency notes.</span></details></div>}

          <div className="wo-audit-twocol">
            <div className="wo-audit-row"><label htmlFor={approverId}>Approved by</label><input id={approverId} type="text" value={approver} onChange={(e) => setApprover(e.target.value)} placeholder="Your name" autoComplete="off" /></div>
            {styleChoices.length > 0 && <div className="wo-audit-row"><label htmlFor={lookId}>Look</label><select id={lookId} value={styleId} onChange={(e) => requestPick(e.target.value)} aria-label="Look for this report">{styleChoices.map((c) => <option key={c.id} value={c.id}>{c.label}{c.ok ? '' : ' (needs a fix)'}</option>)}</select></div>}
          </div>
          {styleChoices.length > 0 && <>
            {why && styleId === whyId && !draft && <p className="wo-audit-confirm-small">{why}</p>}
            {canEdit && !draft && <div className="wo-audit-lookactions"><button type="button" className="wo-audit-button" onClick={startEdit}>Edit profile</button></div>}
            {draft && <StyleProfileForm kind={styleId === 'agency' ? 'agency' : 'client'} domain={manifest.domain} form={draft.form} hints={draft.hints} onChange={setField} mode={draft.editId ? 'edit' : 'create'} />}
            {discard && <Callout kind="caution">You have unsaved changes. Discard them? <button type="button" className="wo-audit-button is-danger" onClick={confirmDiscard}>Discard changes</button> <button type="button" className="wo-audit-button" onClick={() => setDiscard(null)}>Keep editing</button></Callout>}
            {replaceAsk && <Callout kind="caution">A profile file with this name already exists. Replace it with these values? <button type="button" className="wo-audit-button is-danger" disabled={busy} onClick={() => saveProfile(replaceAsk.thenPublish, true)}>{replaceAsk.thenPublish ? 'Replace the file and publish' : 'Replace the file'}</button></Callout>}
            {saved && <p className="wo-audit-confirm-ok" role="status">{saved}</p>}
            {stylePreview?.problem && <Callout kind="error">{stylePreview.problem}</Callout>}
            <p className="wo-audit-hint">{stylePreview && !stylePreview.problem && <><span>{stylePreview.summary}</span>{stylePreview.notes.length > 0 && <span className="wo-audit-hint-notes"> {stylePreview.notes.join(' ')}</span>}{' '}</>}<span className="wo-audit-hint-caution"><TriangleAlert size={13} aria-hidden="true" /> Everything in a look is visible to anyone who has the report link.</span></p>
          </>}
        </> : <>
          <p id={introId} className="wo-audit-facts-line">{published.sizeKb} KB · {published.findings} findings{published.lookLabel ? <> · Look: {published.lookLabel}</> : null} · {published.pushedTo ? <>sent to <code>{published.pushedTo}</code></> : <>saved in <code>{published.folder}</code> as <code>{published.file}</code></>}</p>
          {published.top.length > 0 && <p className="wo-audit-confirm-small">The tour leads with: {published.top.join('; ')}.</p>}
          {published.link ? <>
            <div className="wo-audit-linkrow">
              <a className="wo-audit-linkbox" href={published.link} onClick={(e) => { e.preventDefault(); onOpenUrl(published.link!); }}>{published.link}</a>
              <button type="button" className="wo-audit-button is-primary" onClick={() => { void (navigator.clipboard?.writeText(published.link!) ?? Promise.reject(new Error('Clipboard unavailable'))).then(() => setCopied(true)).catch(() => setError('Could not copy the link. Select and copy it manually.')); }}><Copy size={13} aria-hidden="true" /> {copied ? 'Copied' : 'Copy link'}</button>
              <button type="button" className="wo-audit-button" onClick={() => onOpenUrl(published.link!)}><ExternalLink size={13} aria-hidden="true" /> Open</button>
            </div>
            <p className="wo-audit-confirm-small">Copy the link now: it is shown only once. Send it to your client; anyone who has it can open the report.{published.expires ? <> It stops working on {new Date(published.expires).toLocaleString()}.</> : null} <span role="status">{copied ? 'The link is on your clipboard.' : ''}</span></p>
          </> : <Callout kind="info">Set a report link base in the Web-Obs settings to get a link here.</Callout>}
        </>}
        {error && <Callout kind="error">{error}</Callout>}
      </div>
      {!published ? <div className="wo-audit-confirm-foot">
        {reason && <p id={reasonId} className="wo-audit-reason">{reason}</p>}
        {draft?.editId ? <div className="wo-audit-confirm-row">
          <button type="button" className="wo-audit-button is-primary" disabled={!canPublish || !formOk} aria-describedby={reason ? reasonId : undefined} title={formHint ?? 'Saves the changes to the profile file, then publishes the report with it'} onClick={() => saveEdit(true)}>{busy ? 'Working…' : 'Save changes and publish'}</button>
          <button type="button" className="wo-audit-button" disabled={busy || !formOk || !dirty} title={!dirty ? 'Change a field to enable this' : formHint ?? 'Saves the changes to the profile file; nothing is published'} onClick={() => saveEdit(false)}>Save changes</button>
          <button type="button" className="wo-audit-link" onClick={cancelDraft}>Cancel</button>
        </div> : draft ? <div className="wo-audit-confirm-row">
          <button type="button" className="wo-audit-button is-primary" disabled={!canPublish || !formOk} aria-describedby={reason ? reasonId : undefined} title={formHint ?? 'Writes the profile file, then publishes the report with it'} onClick={() => saveProfile(true)}>{busy ? 'Working…' : 'Save profile and publish'}</button>
          <button type="button" className="wo-audit-button" disabled={busy || !formOk} title={formHint ?? 'Writes the profile file only; nothing is published'} onClick={() => saveProfile(false)}>Save profile</button>
          <button type="button" className="wo-audit-button" disabled={!canPublish} title="Publishes now with the Default look (the built-in look, or default.json when the profiles folder has one); the form is not saved" onClick={sendDefault}>Send with Default look</button>
          <button type="button" className="wo-audit-link" onClick={cancelDraft}>Cancel</button>
        </div> : <div className="wo-audit-confirm-row">
          <button type="button" className="wo-audit-button is-primary" disabled={!canPublish || lookBlocked} aria-describedby={reason ? reasonId : undefined} onClick={publish}>{busy ? 'Creating…' : 'Approve and create report'}</button>
          <button type="button" className="wo-audit-link" disabled={busy} onClick={close}>Cancel</button>
        </div>}
      </div> : <div className="wo-audit-confirm-foot"><div className="wo-audit-confirm-row"><button type="button" className="wo-audit-button" onClick={close}>Done</button></div></div>}
      <button type="button" className="wo-audit-close" disabled={busy} onClick={close} aria-label="Close"><X size={15} aria-hidden="true" /></button>
    </div>}

    {mode === 'archive' && <div ref={dialogRef} tabIndex={-1} className="wo-audit-confirm" role="alertdialog" aria-label="Archive audit" aria-describedby={introId} onKeyDown={onKey}>
      <div className="wo-audit-confirm-head">
        <h2 id={titleId} className="wo-audit-confirm-title"><span>{done ? 'Capture archived' : 'Archive this capture'}</span> <span className="wo-audit-confirm-sub">for <b>{manifest.domain}</b></span></h2>
      </div>
      <div className="wo-audit-confirm-scroll">
        {done ? <Callout kind="info"><span role="status">{done}</span></Callout> : <>
          {busy && !plan && <p className="wo-audit-confirm-small" role="status">Checking what would move…</p>}
          {plan && <>
            <p id={introId} className="wo-audit-destination">These folders will be <b>moved</b> to <code>.web-obs/trash/{plan.domain}-&lt;time&gt;/</code> inside your vault. Nothing is deleted.</p>
            <ul className="wo-audit-folders">{plan.items.map((i) => <li key={i.rel}><span><code>{i.rel}/</code> <small>{i.label}</small></span><span>{i.files} files, {mb(i.bytes)}</span></li>)}</ul>
            <p className="wo-audit-confirm-small">Other sites, and any report you published from this capture, are not touched. In total {plan.files} files, {mb(plan.bytes)}.</p>
            <div className="wo-audit-row"><label htmlFor={typedId}>Type <b>{plan.domain}</b> to confirm</label><input id={typedId} type="text" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} aria-label="Type the site name to confirm" placeholder={plan.domain} /></div>
          </>}
        </>}
        {error && <Callout kind="error">{error}</Callout>}
      </div>
      {plan && !done ? <div className="wo-audit-confirm-foot">
        {typed !== plan.domain && !busy && <p id={reasonId} className="wo-audit-reason">Type the site name exactly to enable the button.</p>}
        <div className="wo-audit-confirm-row"><button type="button" className="wo-audit-button is-danger" disabled={busy || typed !== plan.domain} aria-describedby={typed !== plan.domain ? reasonId : undefined} onClick={archive}>{busy ? 'Moving…' : 'Move to the trash folder'}</button><button type="button" className="wo-audit-link" disabled={busy} onClick={close}>Cancel</button></div>
      </div> : done ? <div className="wo-audit-confirm-foot"><div className="wo-audit-confirm-row"><button type="button" className="wo-audit-button" onClick={close}>Done</button></div></div> : null}
      <button type="button" className="wo-audit-close" disabled={busy} onClick={close} aria-label="Close"><X size={15} aria-hidden="true" /></button>
    </div>}
  </div>;
  return { buttons, dialogs };
}
