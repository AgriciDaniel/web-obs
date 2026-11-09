import { useId } from 'react';
import { Wand2, X } from 'lucide-react';
import { suggestCardText } from '../report/styles/styles.mjs';
import { COLOR_FALLBACK, COLOR_FIELDS, DEFAULT_CARD, FIELD_TEXT, TEXT_FIELDS, FONT_CHOICES, HEADING_CASES, HEADING_CASE_LABELS, PAGE_BACKGROUND_NOTE, fieldIssues, type StyleForm } from '../data/profileForm';

const HEX = /^#[0-9a-fA-F]{6}$/;

interface Props {
  kind: 'agency' | 'client';
  domain: string;
  form: StyleForm;
  hints: string[];
  onChange: (k: keyof StyleForm, v: string) => void;
  /** create (a new profile) or edit (a saved one): only the lead sentence differs. */
  mode?: 'create' | 'edit';
}

/** One color: a native color picker kept in step with a hex text box, its purpose in a line, and any note that belongs to it. */
function ColorField({ field, form, onChange, issues }: { field: (typeof COLOR_FIELDS)[number] | (typeof TEXT_FIELDS)[number]; form: StyleForm; onChange: Props['onChange']; issues: ReturnType<typeof fieldIssues> }) {
  const id = useId();
  const { label, help } = FIELD_TEXT[field];
  const value = form[field];
  const valid = HEX.test(value);
  const errs = issues.errors[field] ?? [], notes = issues.notes[field] ?? [];
  return (
    <div className="wo-audit-field wo-audit-colorfield">
      <label htmlFor={id}>{label}</label>
      <div className="wo-audit-colorrow">
        <input type="color" className="wo-audit-colorpick" aria-label={`${label} color picker`} title="Pick a color" value={valid ? value.toLowerCase() : COLOR_FALLBACK[field]} onChange={(e) => onChange(field, e.target.value)} />
        <input id={id} type="text" className="wo-audit-colorhex" value={value} placeholder="built-in" maxLength={7} spellCheck={false} autoComplete="off" aria-invalid={Boolean(value) && !valid} onChange={(e) => onChange(field, e.target.value.trim())} />
        {value && <button type="button" className="wo-audit-iconbtn" onClick={() => onChange(field, '')} aria-label={`Clear ${label}`} title="Use the built-in value"><X size={13} aria-hidden="true" /></button>}
      </div>
      <p className="wo-audit-help">{help}</p>
      {errs.map((m) => <p key={m} className="wo-audit-fieldnote is-error" role="alert">{m}</p>)}
      {notes.map((m) => <p key={m} className="wo-audit-fieldnote">{m}</p>)}
      {field === 'cardText' && <ReadableTextButton form={form} onChange={onChange} failing={errs.length > 0} />}
    </div>
  );
}

/** One click fills the text on cards with the better of white and near-black for the chosen card color, and says how well it reads. */
function ReadableTextButton({ form, onChange, failing }: { form: StyleForm; onChange: Props['onChange']; failing: boolean }) {
  const card = HEX.test(form.surface) ? form.surface : DEFAULT_CARD;
  const sug = suggestCardText(card);
  if (!sug || !sug.ok || (form.cardText && !failing && form.cardText.toLowerCase() === sug.color)) return null;
  return <button type="button" className="wo-audit-button wo-audit-suggest" onClick={() => onChange('cardText', sug.color)} title={`The best of white and near-black on ${card}`}><Wand2 size={13} aria-hidden="true" /> Use readable text ({sug.color}, {sug.ratio.toFixed(1)}:1)</button>;
}

function TextField({ field, form, onChange, issues, max }: { field: 'name' | 'footerText'; form: StyleForm; onChange: Props['onChange']; issues: ReturnType<typeof fieldIssues>; max: number }) {
  const id = useId();
  const { label, help } = FIELD_TEXT[field];
  return (
    <div className="wo-audit-field">
      <label htmlFor={id}>{label}</label>
      <input id={id} type="text" value={form[field]} maxLength={max} autoComplete="off" onChange={(e) => onChange(field, e.target.value)} />
      <p className="wo-audit-help">{help}</p>
      {(issues.errors[field] ?? []).map((m) => <p key={m} className="wo-audit-fieldnote is-error" role="alert">{m}</p>)}
    </div>
  );
}

function SelectField({ field, form, onChange, options }: { field: 'headingFont' | 'bodyFont' | 'headingCase'; form: StyleForm; onChange: Props['onChange']; options: Array<[string, string]> }) {
  const id = useId();
  const { label, help } = FIELD_TEXT[field];
  return (
    <div className="wo-audit-field">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={form[field]} onChange={(e) => onChange(field, e.target.value)}>{options.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select>
      <p className="wo-audit-help">{help}</p>
    </div>
  );
}

/**
 * The create-a-profile form, in three compact groups: Identity (two fields in a row), Colors (the five colors in a grid of small cells) and Fonts
 * (three selects in a row). The cells wrap to fewer columns in a narrow dialog.
 */
export function StyleProfileForm({ kind, domain, form, hints, onChange, mode = 'create' }: Props) {
  const issues = fieldIssues(form);
  const identityId = useId();
  return (
    <div className="wo-audit-profile" role="group" aria-label="Create a style profile">
      <p className="wo-audit-profile-lead">{mode === 'edit'
        ? <><b>Editing the saved {kind} profile{kind === 'agency' ? '' : ` for ${domain}`}.</b> The file is changed only when you press Save changes, and the previous version is kept next to it as a .bak copy. Nothing leaves this computer until you publish.</>
        : <><b>No {kind} profile for {kind === 'agency' ? 'your agency' : domain} yet.</b> Fill in what the report should use. Save profile creates the file in your styles folder. Nothing is written until you press Save, and nothing leaves this computer until you publish.</>}</p>
      {hints.map((h) => <p key={h} className="wo-audit-confirm-small">{h}</p>)}
      <div className="wo-audit-form-grid">
        <div className="wo-audit-group wo-audit-fs-identity" role="group" aria-labelledby={identityId}>
          <h4 className="wo-audit-group-title" id={identityId}>Identity</h4>
          <div className="wo-audit-cells wo-audit-cells-2">
            <TextField field="name" form={form} onChange={onChange} issues={issues} max={80} />
            <TextField field="footerText" form={form} onChange={onChange} issues={issues} max={120} />
          </div>
        </div>
        <div className="wo-audit-group wo-audit-fs-colors" role="group" aria-label="Colors">
          <h4 className="wo-audit-group-title">Colors</h4>
          <div className="wo-audit-cells wo-audit-cells-colors">
            {COLOR_FIELDS.map((f) => <ColorField key={f} field={f} form={form} onChange={onChange} issues={issues} />)}
          </div>
          <p className="wo-audit-confirm-small">{PAGE_BACKGROUND_NOTE}</p>
        </div>
        <div className="wo-audit-group wo-audit-fs-text" role="group" aria-label="Text colors">
          <h4 className="wo-audit-group-title">Text colors</h4>
          <div className="wo-audit-cells wo-audit-cells-text">
            {TEXT_FIELDS.map((f) => <ColorField key={f} field={f} form={form} onChange={onChange} issues={issues} />)}
          </div>
        </div>
        <div className="wo-audit-group wo-audit-fs-fonts" role="group" aria-label="Fonts">
          <h4 className="wo-audit-group-title">Fonts</h4>
          <div className="wo-audit-cells wo-audit-cells-3">
            <SelectField field="headingFont" form={form} onChange={onChange} options={FONT_CHOICES.map((f) => [f, f || 'System font'])} />
            <SelectField field="bodyFont" form={form} onChange={onChange} options={FONT_CHOICES.map((f) => [f, f || 'System font'])} />
            <SelectField field="headingCase" form={form} onChange={onChange} options={HEADING_CASES.map((c) => [c, HEADING_CASE_LABELS[c] ?? c])} />
          </div>
        </div>
      </div>
      {issues.general.map((m) => <p key={m} className="wo-audit-confirm-warn" role="alert">{m}</p>)}
      {issues.ok && <p className="wo-audit-confirm-small">{issues.summary}.{Object.values(issues.notes).flat().length === 0 && issues.general.length === 0 ? ' Every color reads well on the dark page.' : ''}</p>}
    </div>
  );
}
