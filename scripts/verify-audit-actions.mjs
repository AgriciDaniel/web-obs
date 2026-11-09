// Checks for the audit view's Publish audit and Archive audit: the client report export, the random file name, and the archive
// (move to trash, never delete). Uses a synthetic manifest and temporary folders only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { build } from 'esbuild';

async function load(entry) {
  const output = await build({ entryPoints: [entry], bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent' });
  return import('data:text/javascript;base64,' + Buffer.from(output.outputFiles[0].contents).toString('base64'));
}
const { exportClientReport } = await load('src/report/exportAudit.ts');
const { writeReportFile, newReportFileName, planArchive, archiveToTrash } = await load('src/plugin/auditActions.ts');
const { PREVIEW_SITE_MANIFEST } = await load('src/data/demoSite.ts');

// ---- export ---------------------------------------------------------------------------------------------------------------
const manifest = structuredClone(PREVIEW_SITE_MANIFEST);
manifest.nodes.forEach((n) => { n.obsidianPath = `sites/${manifest.domain}/Pages/${n.id}.md`; n.metaDescription = 'PRIVATE-META-TEXT'; });
manifest.brandKit = { ...manifest.brandKit, localLogoAsset: 'sites/example.test/assets/PRIVATE-VAULT-LOGO.png' };
const result = await exportClientReport(manifest, { approvedBy: 'Test Approver' });
const report = JSON.parse(result.json);
assert.equal(report.format, 'webobs.client-report');
assert.equal(report.meta.review.state, 'approved');
assert.equal(report.meta.review.reviewedBy, 'Test Approver');
assert.ok(report.meta.integrity?.contentSha256?.length === 64, 'the file is sealed with a hash');
assert.ok(!result.json.includes('obsidianPath') && !result.json.includes('PRIVATE-META-TEXT') && !result.json.includes('/Pages/'), 'no vault paths or page text in the client file');
assert.ok(!result.json.includes('PRIVATE-VAULT-LOGO') && !('localLogoAsset' in report.map.site.brandKit), 'local brand asset paths never leave the vault');
assert.ok(!('resources' in report.map.site) && !('linkHealth' in report.map.site) && !('siteIntel' in report.map.site), 'the map carries only allowlisted fields');
await assert.rejects(() => exportClientReport(manifest, { approvedBy: '   ' }), /approve/, 'a person must approve');
await assert.rejects(() => exportClientReport(manifest, { approvedBy: 'A', feedbackTo: 'not an email' }), /email/, 'a bad feedback address is refused');

// ---- file name and writing --------------------------------------------------------------------------------------------------
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'wo-audit-actions-'));
const names = new Set(Array.from({ length: 200 }, newReportFileName));
assert.equal(names.size, 200, 'file names do not repeat');
assert.ok([...names].every((n) => /^[0-9a-f]{32}\.json$/.test(n)), 'file names are 128 random bits in hex');
const folder = path.join(tmp, 'reports');
const a = writeReportFile(folder, result.json), b = writeReportFile(folder, result.json);
assert.notEqual(a.file, b.file, 'a second publish never overwrites the first');
assert.equal(fs.readFileSync(a.full, 'utf8'), result.json);
assert.ok(!a.file.toLowerCase().includes(manifest.domain.split('.')[0].toLowerCase()), 'the file name says nothing about the site');
assert.throws(() => writeReportFile('relative/folder', '{}'), /full path/);

// ---- archive: move, never delete --------------------------------------------------------------------------------------------
const vault = path.join(tmp, 'vault');
const put = (rel, text = 'x') => { const f = path.join(vault, rel); fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, text); };
put('sites/a.test/_site-graph.json', '{}'); put('sites/a.test/Pages/home.md', 'home'); put('sites/b.test/_site-graph.json', '{"keep":1}');
put('.web-obs/history/a.test/cap1/_site-graph.json', 'old'); put('.web-obs/history/b.test/cap1/x.json', 'b-old');
const count = () => { let n = 0; const walk = (d) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) e.isDirectory() ? walk(path.join(d, e.name)) : n++; }; walk(vault); return n; };
const before = count();
const plan = planArchive(vault, 'a.test');
assert.deepEqual(plan.items.map((i) => i.rel), ['sites/a.test', '.web-obs/history/a.test']);
assert.equal(plan.files, 3);
assert.equal(count(), before, 'the preview changes nothing');
assert.throws(() => archiveToTrash(vault, 'a.test', 'b.test'), /again/, 'the wrong confirmation is refused');
assert.throws(() => planArchive(vault, '../x'), /plain site name/);
assert.throws(() => planArchive(vault, 'zzz.test'), /Nothing was found/);
assert.equal(count(), before);
const moved = archiveToTrash(vault, 'a.test', 'a.test');
assert.equal(moved.files, 3);
assert.ok(!fs.existsSync(path.join(vault, 'sites/a.test')) && !fs.existsSync(path.join(vault, '.web-obs/history/a.test')), 'the capture and its history are gone from their places');
const trash = path.join(vault, moved.trash);
assert.ok(fs.existsSync(path.join(trash, 'sites/Pages/home.md')) && fs.existsSync(path.join(trash, 'history/cap1/_site-graph.json')) && fs.existsSync(path.join(trash, 'REMOVED.txt')), 'everything is in the trash folder, with a restore note');
assert.equal(count(), before + 1, 'nothing was deleted (only the restore note was added)');
assert.equal(fs.readFileSync(path.join(vault, 'sites/b.test/_site-graph.json'), 'utf8'), '{"keep":1}', 'other sites are untouched');
assert.ok(fs.existsSync(path.join(vault, '.web-obs/history/b.test/cap1/x.json')));

// Real transaction paths and preserved proposals belong to the same site, even with a port in its ID.
put('sites/local.test_8080/_site-graph.json', '{}');
put('.web-obs/proposals/local.test_8080/run/home.md', 'proposal');
put('.web-obs/staging/run-a/sites/local.test_8080/Pages/home.md', 'unfinished');
put('.web-obs/staging/run-a/sites/b.test/Pages/home.md', 'keep');
const staged = planArchive(vault, 'local.test_8080');
assert.equal(staged.files, 3);
const first = archiveToTrash(vault, 'local.test_8080', 'local.test_8080');
assert.ok(fs.existsSync(path.join(vault, first.trash, 'staging/run-a/sites/local.test_8080/Pages/home.md')));
assert.ok(fs.existsSync(path.join(vault, '.web-obs/staging/run-a/sites/b.test/Pages/home.md')));
put('sites/local.test_8080/_site-graph.json', '{"second":true}');
const second = archiveToTrash(vault, 'local.test_8080', 'local.test_8080');
assert.notEqual(first.trash, second.trash, 'each archive owns a unique destination');
assert.ok(fs.existsSync(path.join(vault, first.trash, 'sites/_site-graph.json')));

// A failed second move rolls the first one back, with restore instructions already written.
put('sites/rollback.test/_site-graph.json', 'active');
put('.web-obs/history/rollback.test/run/_site-graph.json', 'previous');
const originalRename = fs.renameSync;
let renameCalls = 0;
try {
  fs.renameSync = (...args) => { if (++renameCalls === 2) throw Object.assign(new Error('injected'), { code: 'EACCES' }); return originalRename(...args); };
  assert.throws(() => archiveToTrash(vault, 'rollback.test', 'rollback.test'), /All moved folders were restored/);
} finally { fs.renameSync = originalRename; }
assert.equal(fs.readFileSync(path.join(vault, 'sites/rollback.test/_site-graph.json'), 'utf8'), 'active');
assert.equal(fs.readFileSync(path.join(vault, '.web-obs/history/rollback.test/run/_site-graph.json'), 'utf8'), 'previous');

put('.web-obs/promotion.json', '{}');
assert.throws(() => planArchive(vault, 'b.test'), /needs recovery/);
fs.unlinkSync(path.join(vault, '.web-obs/promotion.json'));
fs.symlinkSync(path.join(vault, 'sites/b.test'), path.join(vault, 'sites/linked.test'), 'junction');
assert.throws(() => planArchive(vault, 'linked.test'), /link/);

// ---- after archive nothing stale stays loaded ----------------------------------------------------------------------------------
// The picker lists every sites/<name>/ folder that holds a _site-graph.json (the same rule as the view's site list).
const listed = () => fs.readdirSync(path.join(vault, 'sites'), { withFileTypes: true }).filter((e) => e.isDirectory() && fs.existsSync(path.join(vault, 'sites', e.name, '_site-graph.json'))).map((e) => e.name);
assert.ok(!listed().includes('a.test') && listed().includes('b.test'), 'the archived site is gone from the site list and the other site is still there');
// The view must drop the archived site from memory and from the screen: the app clears the loaded site, closes the panels and refreshes the list.
const app = fs.readFileSync('src/App.tsx', 'utf8');
const handler = app.slice(app.indexOf('const handleArchived'), app.indexOf('const handleArchived') + 400);
assert.ok(/setManifest\(null\)/.test(handler) && /setAuditOpen\(false\)/.test(handler) && /setIntelOpen\(false\)/.test(handler) && /setSelectedId\(null\)/.test(handler) && /refreshSitesList\(\)/.test(handler), 'after archive the app unloads the site, closes the panels and refreshes the list');
assert.ok(app.includes('onArchived={handleArchived}'), 'the audit panel calls that reset');
const view = fs.readFileSync('src/plugin/SiteGlobeView.ts', 'utf8');
assert.ok(/latestManifestCache\?\.siteId === siteId\) this\.latestManifestCache = null/.test(view), 'the host forgets the archived site');

fs.rmSync(tmp, { recursive: true, force: true });
console.log('Audit actions OK: client report export (approved, sealed, no vault paths or page text), random file names that never overwrite, and archive that moves to the trash folder and never deletes.');
