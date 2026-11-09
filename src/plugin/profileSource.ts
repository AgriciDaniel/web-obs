// THE one place that finds or creates a style profile. Today the source is a folder of JSON files (agency.json, clients/<domain>.json).
// Later the source will become the tagged client contract in the home vault: swap `findProfile` and `createProfile` here and nothing else
// (the dialog, the form, the validator and the publish path only see these functions). The same goes for editing a profile (readProfileForEdit, updateProfile) and for the decision which look the Publish dialog starts on (resolveDefaultLook, re-exported from ../data/defaultLook).
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { applyFormToRaw, formToProfile, formToStyles, profileToForm, type StyleForm } from '../data/profileForm';

export { resolveDefaultLook, DEFAULT_LOOK_PREFERENCES, isDefaultLookPreference, type DefaultLookPreference } from '../data/defaultLook';

const DOMAIN = /^[a-z0-9](?:[a-z0-9-]{0,62}\.)+[a-z0-9-]{1,63}$|^[a-z0-9][a-z0-9-]{0,62}$/;

/** The domain as a safe file stem: lower case, letters, digits, dots and dashes only, no "..", no slashes. Null when it is not safe. */
export function safeDomain(domain: string): string | null {
  const d = String(domain ?? '').trim().toLowerCase();
  if (!d || d.length > 80 || d.includes('..') || !DOMAIN.test(d)) return null;
  return d;
}

/** The choice id and file for a kind: agency -> agency.json, client -> clients/<domain>.json. Null when the domain is not safe. */
export function profileTarget(folder: string, kind: 'agency' | 'client', domain: string): { id: string; file: string } | null {
  if (kind === 'agency') return { id: 'agency', file: path.join(folder, 'agency.json') };
  const d = safeDomain(domain); if (!d) return null;
  return { id: `client:${d}.json`, file: path.join(folder, 'clients', `${d}.json`) };
}

/** Finds the profile for a kind and domain. Returns the file when it exists as a plain file (a link or a folder counts as not found). */
export function findProfile(folder: string, kind: 'agency' | 'client', domain: string): { id: string; file: string } | null {
  const t = profileTarget(folder, kind, domain); if (!t) return null;
  try { return fs.lstatSync(t.file).isFile() ? t : null; } catch { return null; }
}

/** The agency's name from agency.json in the profiles folder (plain file, at most 64 KB), or null when there is no usable agency profile. Never throws. */
export function agencyNameFromFolder(folder: string): string | null {
  try {
    const file = path.join(folder, 'agency.json');
    const st = fs.lstatSync(file);
    if (!st.isFile() || st.size > 64 * 1024) return null;
    const raw: unknown = JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\ufeff/, ''));
    const n = raw && typeof raw === 'object' && !Array.isArray(raw) && Object.prototype.hasOwnProperty.call(raw, 'name') ? (raw as Record<string, unknown>).name : null;
    return typeof n === 'string' && n.trim() ? n.trim().slice(0, 80) : null;
  } catch { return null; }
}

export type CreateResult = { ok: true; id: string; file: string } | { ok: false; code: 'invalid' | 'exists' | 'unsafe' | 'failed'; message: string };

/**
 * Writes a new profile after the form passes the shared validator. Never overwrites an existing file unless `overwrite` is true (the dialog asks first).
 * The folder and the clients folder must be plain folders (not links) or are created. Writes to a temporary name, then moves it into place.
 */
export function createProfile(folder: string, kind: 'agency' | 'client', domain: string, form: StyleForm, overwrite = false): CreateResult {
  try {
    const t = profileTarget(folder, kind, domain);
    if (!t) return { ok: false, code: 'unsafe', message: 'The site name cannot be used as a file name, so no profile was written.' };
    const checked = formToStyles(form);
    const profile = formToProfile(form);
    if (!checked.styles || !profile) return { ok: false, code: 'invalid', message: checked.errors[0] ?? 'The profile needs a fix before it can be saved.' };
    const dir = path.dirname(t.file);
    for (const d of [folder, dir]) {
      try { if (fs.lstatSync(d).isSymbolicLink()) return { ok: false, code: 'unsafe', message: 'The profiles folder is a link, so nothing was written.' }; } catch { /* created below */ }
    }
    fs.mkdirSync(dir, { recursive: true });
    if (fs.lstatSync(dir).isSymbolicLink() || !fs.lstatSync(dir).isDirectory()) return { ok: false, code: 'unsafe', message: 'The profiles folder is not a plain folder, so nothing was written.' };
    if (path.relative(folder, t.file).startsWith('..')) return { ok: false, code: 'unsafe', message: 'The profile would be outside the profiles folder.' };
    let exists = false; try { fs.lstatSync(t.file); exists = true; } catch { /* free */ }
    if (exists && !overwrite) return { ok: false, code: 'exists', message: 'A profile file with this name already exists.' };
    if (exists && !fs.lstatSync(t.file).isFile()) return { ok: false, code: 'unsafe', message: 'The existing profile is not a plain file, so it was left alone.' };
    const tmp = `${t.file}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(profile, null, 2) + '\n', { flag: 'wx' });
    try { fs.renameSync(tmp, t.file); } catch (e) { try { fs.unlinkSync(tmp); } catch { /* gone */ } throw e; }
    return { ok: true, id: t.id, file: t.file };
  } catch { return { ok: false, code: 'failed', message: 'The profile could not be written.' }; }
}

// ---- editing a profile ----
const MAX_BYTES = 64 * 1024;
const CLIENT_NAME = /^[A-Za-z0-9][A-Za-z0-9._ -]{0,80}\.json$/;
const sha = (s: string) => crypto.createHash('sha256').update(s).digest('hex');

/** The file a choice id points to: agency.json, or clients/<name>.json for any plain client file name. Null for anything else (Default, odd names, folders). */
export function fileOfChoice(folder: string, id: string): string | null {
  if (id === 'agency') return path.join(folder, 'agency.json');
  if (typeof id === 'string' && id.startsWith('client:')) { const n = id.slice(7); if (CLIENT_NAME.test(n) && n === path.basename(n)) return path.join(folder, 'clients', n); }
  return null;
}
function readPlain(file: string): { ok: true; text: string; raw: unknown } | { ok: false; message: string } {
  try {
    const st = fs.lstatSync(file);
    if (!st.isFile()) return { ok: false, message: 'The profile is not a plain file.' };
    if (st.size > MAX_BYTES) return { ok: false, message: 'The profile file is larger than 64 KB.' };
    const text = fs.readFileSync(file, 'utf8');
    try { return { ok: true, text, raw: JSON.parse(text.replace(/^\ufeff/, '')) }; } catch { return { ok: false, message: 'The profile file is not valid JSON, so it cannot be edited here. Fix it in a text editor or create a new profile.' }; }
  } catch { return { ok: false, message: 'The profile file could not be read.' }; }
}

export interface EditableProfile { ok: true; id: string; file: string; form: StyleForm; baseHash: string; shape: 'home' | 'flat' }
/** Opens a stored profile for editing: the saved values in the form, and a hash of the file as it was read (used to notice a change made meanwhile). Never throws. */
export function readProfileForEdit(folder: string, id: string): EditableProfile | { ok: false; message: string } {
  try {
    const file = fileOfChoice(folder, id); if (!file) return { ok: false, message: 'That look is not a profile file, so it cannot be edited.' };
    const r = readPlain(file); if (!r.ok) return r;
    if (r.raw === null || typeof r.raw !== 'object' || Array.isArray(r.raw)) return { ok: false, message: 'The profile file does not hold a profile (a JSON object).' };
    const shape = (r.raw as Record<string, unknown>).colors !== null && typeof (r.raw as Record<string, unknown>).colors === 'object' && !Array.isArray((r.raw as Record<string, unknown>).colors) ? 'home' : 'flat';
    return { ok: true, id, file, form: profileToForm(r.raw), baseHash: sha(r.text), shape };
  } catch { return { ok: false, message: 'The profile could not be opened.' }; }
}

export type UpdateResult = { ok: true; id: string; file: string; backup: string } | { ok: false; code: 'invalid' | 'changed' | 'unsafe' | 'failed'; message: string };
/**
 * Saves changes to a stored profile in place. Only the fields the person changed are written; every other key in the file stays as it was. The old file is kept as ONE backup
 * copy next to it (<name>.json.bak, replacing an older backup), the new file is written to a temporary name and moved into place, and no other file is touched. If the file
 * changed since it was opened (`baseHash`) nothing is written.
 */
export function updateProfile(folder: string, id: string, initial: StyleForm, form: StyleForm, baseHash?: string): UpdateResult {
  try {
    const file = fileOfChoice(folder, id); if (!file) return { ok: false, code: 'unsafe', message: 'That look is not a profile file, so it cannot be changed.' };
    const checked = formToStyles(form); if (!checked.styles) return { ok: false, code: 'invalid', message: checked.errors[0] ?? 'The profile needs a fix before it can be saved.' };
    const cur = readPlain(file); if (!cur.ok) return { ok: false, code: 'unsafe', message: cur.message };
    if (baseHash && sha(cur.text) !== baseHash) return { ok: false, code: 'changed', message: 'The profile file changed since you opened it. Close this and open it again so nothing is lost.' };
    if (path.relative(folder, file).startsWith('..')) return { ok: false, code: 'unsafe', message: 'The profile would be outside the profiles folder.' };
    const next = applyFormToRaw(cur.raw, initial, form);
    const bak = file + '.bak', tmp = `${file}.${process.pid}.tmp`;
    fs.copyFileSync(file, bak);
    fs.writeFileSync(tmp, JSON.stringify(next, null, 2) + '\n', { flag: 'wx' });
    try { fs.renameSync(tmp, file); } catch (e) { try { fs.unlinkSync(tmp); } catch { /* gone */ } throw e; }
    return { ok: true, id, file, backup: bak };
  } catch { return { ok: false, code: 'failed', message: 'The changes could not be saved.' }; }
}

