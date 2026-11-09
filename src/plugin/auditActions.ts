// File side of the audit view's Publish audit and Archive audit buttons (desktop only, uses Node's fs).
// Publish audit writes one client-report JSON into a folder you choose. Archive audit MOVES a capture to the vault's trash folder:
// nothing is ever deleted. No network, no credentials.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import type { ArchivePlan, ArchiveResult } from '../types/site';
import { isSafeSiteId } from '../data/validateManifest';

/** A random 128-bit file name: nothing in it says whose report it is. */
export const newReportFileName = () => `${crypto.randomBytes(16).toString('hex')}.json`;
export const reportLink = (base: string, file: string) => `${base.trim()}${file}`;

/** Writes the JSON under a new random name in `folder` (created if needed). Never overwrites: the name is new each time. */
export function writeReportFile(folder: string, json: string): { file: string; full: string } {
  if (!path.isAbsolute(folder)) throw new Error('The client reports folder must be a full path.');
  fs.mkdirSync(folder, { recursive: true });
  const file = newReportFileName();
  const full = path.join(folder, file);
  fs.writeFileSync(full, json, { flag: 'wx' });
  return { file, full };
}

// ---- archive: move, never delete --------------------------------------------------------------------------------
export const isDomain = isSafeSiteId;

/** Do not follow directory links while moving captures, including links in parent folders. */
function safeDirectory(vault: string, relative: string[]): string | null {
  let current = vault;
  for (const part of relative) {
    current = path.join(current, part);
    let info: fs.Stats;
    try { info = fs.lstatSync(current); } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
      throw error;
    }
    if (info.isSymbolicLink() || !info.isDirectory()) throw new Error('An archive folder is a link or is not a directory.');
  }
  return current;
}
const stat = (dir: string) => {
  let files = 0, bytes = 0;
  const walk = (d: string) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, e.name); if (e.isDirectory()) walk(p); else { files++; bytes += fs.lstatSync(p).size; } } };
  walk(dir);
  return { files, bytes };
};
const targets = (vault: string, domain: string) => {
  const items = [
    { label: 'capture', rel: ['sites', domain], trash: 'sites' },
    { label: 'history', rel: ['.web-obs', 'history', domain], trash: 'history' },
    { label: 'preserved proposals', rel: ['.web-obs', 'proposals', domain], trash: 'proposals' },
  ];
  const staging = safeDirectory(vault, ['.web-obs', 'staging']);
  if (staging) for (const run of fs.readdirSync(staging, { withFileTypes: true })) {
    // Transactions are stored by run ID, with the site nested below sites/.
    if (!run.isDirectory() || run.isSymbolicLink()) continue;
    items.push({ label: 'unfinished capture', rel: ['.web-obs', 'staging', run.name, 'sites', domain], trash: `staging/${run.name}/sites/${domain}` });
  }
  return items;
};

/** Exactly what would move. Read only. */
export function planArchive(vault: string, domain: string): ArchivePlan {
  if (!isDomain(domain)) throw new Error('That is not a plain site name.');
  safeDirectory(vault, ['.web-obs']);
  if (fs.existsSync(path.join(vault, '.web-obs', 'promotion.json'))) throw new Error('A capture needs recovery. Finish or recover it before archiving.');
  const items = targets(vault, domain).filter((t) => safeDirectory(vault, t.rel)).map((t) => ({ label: t.label, rel: t.rel.join('/'), ...stat(path.join(vault, ...t.rel)) }));
  if (!items.length) throw new Error(`Nothing was found for ${domain}.`);
  return { domain, items, files: items.reduce((a, i) => a + i.files, 0), bytes: items.reduce((a, i) => a + i.bytes, 0) };
}

/** Moves the folders to <vault>/.web-obs/trash/<domain>-<time>/ with a restore note. Needs the name typed again. A failure puts back what moved. */
export function archiveToTrash(vault: string, domain: string, confirm: string): ArchiveResult {
  const plan = planArchive(vault, domain);
  if (confirm !== domain) throw new Error('Type the site name again to confirm.');
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/[.]\d+Z$/, 'Z');
  safeDirectory(vault, ['.web-obs', 'trash']);
  const trashRoot = path.join(vault, '.web-obs', 'trash');
  fs.mkdirSync(trashRoot, { recursive: true });
  const trash = fs.mkdtempSync(path.join(trashRoot, `${domain}-${stamp}-`));
  const selected = targets(vault, domain).filter((t) => plan.items.some((i) => i.rel === t.rel.join('/')));
  // Write the restore instructions before the first move, so a note-write failure cannot strand a capture.
  fs.writeFileSync(path.join(trash, 'REMOVED.txt'), `Capture ${domain} was moved here on ${new Date().toISOString()}.\nTo restore it, move the folders back: ${selected.map((t) => `${t.trash}/ -> ${t.rel.join('/')}/`).join('; ')}\nNothing in this folder is deleted until you delete it yourself.\n`, { flag: 'wx' });
  const moved: Array<{ from: string; to: string }> = [];
  try {
    for (const t of selected) {
      const from = safeDirectory(vault, t.rel);
      if (!from) throw new Error('A capture folder changed. Preview the archive again.');
      const to = path.join(trash, t.trash);
      fs.mkdirSync(path.dirname(to), { recursive: true });
      fs.renameSync(from, to); moved.push({ from, to });
    }
  } catch (e) {
    let restored = true;
    for (const m of moved.reverse()) {
      try { fs.renameSync(m.to, m.from); } catch { restored = false; }
    }
    throw new Error(restored ? `Could not move everything (${(e as NodeJS.ErrnoException).code ?? 'error'}). All moved folders were restored.` : `Some folders could not be restored. Use ${path.relative(vault, trash)}/REMOVED.txt to recover them.`);
  }
  return { domain, trash: path.relative(vault, trash).split(path.sep).join('/'), files: plan.files };
}
