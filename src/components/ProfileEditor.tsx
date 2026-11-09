import { useId, useState } from 'react';
import { previewForm, type StyleForm } from '../data/profileForm';
import { Callout } from './AuditActionsBar';
import { StyleProfileForm } from './StyleProfileForm';

interface Props {
  kind: 'agency' | 'client';
  /** The profile's name, for the title. */
  label: string;
  initial: StyleForm;
  /** Saves the changes; the answer says whether it worked and, if not, why in plain words. */
  onSave: (form: StyleForm) => Promise<{ ok: boolean; message?: string; backup?: string }>;
  onClose: () => void;
}

/**
 * The same form as in the Publish dialog, for editing a saved profile from the plugin settings: the saved values, the same checks, the same readable-text help and
 * contrast notes. Save changes writes the file in place (the previous version stays as a .bak copy); Cancel asks first when there are unsaved changes.
 */
export function ProfileEditor({ kind, label, initial, onSave, onClose }: Props) {
  const [form, setForm] = useState<StyleForm>(initial);
  const [baseline, setBaseline] = useState<StyleForm>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [askDiscard, setAskDiscard] = useState(false);
  const uid = useId();
  const dirty = JSON.stringify(form) !== JSON.stringify(baseline);
  const ok = previewForm(form).ok;
  const reason = !dirty ? 'Change a field to enable Save changes.' : !ok ? 'Fix the highlighted fields to save.' : null;
  const set = (k: keyof StyleForm, v: string) => { setSaved(null); setForm((f) => ({ ...f, [k]: v })); };
  const save = () => {
    setBusy(true); setError(null);
    onSave(form).then((r) => { if (r.ok) { setBaseline(form); setSaved(r.backup ? 'Changes saved. The previous version is kept next to the file as a .bak copy.' : 'Changes saved.'); } else setError(r.message ?? 'The changes could not be saved.'); })
      .catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  return (
    <div className="wo-audit-confirm wo-audit-embedded" role="dialog" aria-labelledby={`${uid}-t`}>
      <div className="wo-audit-confirm-head"><h2 id={`${uid}-t`} className="wo-audit-confirm-title">Edit {kind} profile <span className="wo-audit-confirm-sub">{label}</span></h2></div>
      <div className="wo-audit-confirm-scroll">
        <StyleProfileForm kind={kind} domain={label} form={form} hints={[]} onChange={set} mode="edit" />
        {askDiscard && <Callout kind="caution">You have unsaved changes. Discard them? <button type="button" className="wo-audit-button is-danger" onClick={onClose}>Discard changes</button> <button type="button" className="wo-audit-button" onClick={() => setAskDiscard(false)}>Keep editing</button></Callout>}
        {saved && <p className="wo-audit-confirm-ok" role="status">{saved}</p>}
        {error && <Callout kind="error">{error}</Callout>}
      </div>
      <div className="wo-audit-confirm-foot">
        {reason && <p className="wo-audit-reason" id={`${uid}-r`}>{reason}</p>}
        <div className="wo-audit-confirm-row">
          <button type="button" className="wo-audit-button is-primary" disabled={busy || !dirty || !ok} aria-describedby={reason ? `${uid}-r` : undefined} onClick={save}>{busy ? 'Saving…' : 'Save changes'}</button>
          <button type="button" className="wo-audit-link" onClick={() => (dirty ? setAskDiscard(true) : onClose())}>{saved && !dirty ? 'Close' : 'Cancel'}</button>
        </div>
      </div>
    </div>
  );
}
