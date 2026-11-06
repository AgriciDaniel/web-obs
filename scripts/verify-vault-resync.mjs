// After a capture swaps sites/<site> in one rename, Obsidian keeps a stale index for that folder.
// This fake adapter copies the relevant Obsidian behaviour: a folder event for a known folder path
// only updates its location (no rescan), and per-folder watchers stay on the folder that moved away.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { build } from 'esbuild';

const output = await build({ entryPoints: ['src/plugin/vaultResync.ts'], bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent' });
const { resyncVaultFolder } = await import('data:text/javascript;base64,' + Buffer.from(output.outputFiles[0].contents).toString('base64'));

const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'web-obs-resync-'));
const write = (rel, text = 'x') => { fs.mkdirSync(path.dirname(path.join(vault, rel)), { recursive: true }); fs.writeFileSync(path.join(vault, rel), text); };
const inode = (rel) => fs.statSync(path.join(vault, rel)).ino;

function fakeAdapter() {
  const adapter = {
    files: {},
    watchers: {},
    queued: 0,
    async list(rel) {
      const entries = fs.readdirSync(path.join(vault, rel), { withFileTypes: true });
      return { files: entries.filter(e => e.isFile()).map(e => `${rel}/${e.name}`), folders: entries.filter(e => e.isDirectory()).map(e => `${rel}/${e.name}`) };
    },
    queue(task) { adapter.queued += 1; return task(); },
    async reconcileInternalFile(rel) {
      const full = path.join(vault, rel);
      if (!fs.existsSync(full)) {
        for (const key of Object.keys(adapter.files)) if (key === rel || key.startsWith(rel + '/')) delete adapter.files[key];
        return;
      }
      const stat = fs.statSync(full);
      if (stat.isDirectory()) {
        if (adapter.files[rel]) return; // Obsidian: known folder path, keep the old listing
        adapter.files[rel] = { type: 'folder' };
        adapter.startWatchPath(rel);
        return;
      }
      adapter.files[rel] = { type: 'file', mtime: Math.round(stat.mtimeMs), size: stat.size };
    },
    startWatchPath(rel) { adapter.watchers[rel] = { ino: inode(rel) }; },
    stopWatchPath(rel) { delete adapter.watchers[rel]; },
  };
  return adapter;
}

async function indexAll(adapter, rel) {
  await adapter.reconcileInternalFile(rel);
  const listing = await adapter.list(rel);
  for (const file of listing.files) await adapter.reconcileInternalFile(file);
  for (const folder of listing.folders) await indexAll(adapter, folder);
}

// The previous capture, indexed and watched.
write('sites/example.com/pages/index.md', 'old');
write('sites/example.com/pages/gone.md', 'removed by the new capture');
write('sites/example.com/assets/logo.png');
const adapter = fakeAdapter();
await indexAll(adapter, 'sites');

// The new capture is staged elsewhere and swapped in, as capture_store.py does.
write('.web-obs/staging/pages/index.md', 'new and longer');
write('.web-obs/staging/assets/logo.png');
write('.web-obs/staging/assets/screenshots/full-home-abc123.jpg', 'jpeg');
fs.mkdirSync(path.join(vault, '.web-obs/history'), { recursive: true });
fs.renameSync(path.join(vault, 'sites/example.com'), path.join(vault, '.web-obs/history/old'));
fs.renameSync(path.join(vault, '.web-obs/staging'), path.join(vault, 'sites/example.com'));
await adapter.reconcileInternalFile('sites/example.com'); // what Obsidian's watcher does with the event

assert.equal(adapter.files['sites/example.com/assets/screenshots/full-home-abc123.jpg'], undefined, 'the bug: a new file stays unknown');
assert.ok(adapter.files['sites/example.com/pages/gone.md'], 'the bug: a removed file stays listed');
assert.notEqual(adapter.watchers['sites/example.com/pages'].ino, inode('sites/example.com/pages'), 'the bug: the watcher follows the moved folder');

const result = await resyncVaultFolder(adapter, 'sites/example.com');
assert.equal(result.state, 'synced');
assert.ok(adapter.files['sites/example.com/assets/screenshots/full-home-abc123.jpg'], 'new snapshot is indexed');
assert.ok(adapter.files['sites/example.com/assets/screenshots'], 'new folder is indexed');
assert.equal(adapter.files['sites/example.com/pages/gone.md'], undefined, 'removed note leaves the index');
assert.equal(adapter.files['sites/example.com/pages/index.md'].size, 'new and longer'.length, 'changed note is refreshed');
for (const folder of ['sites/example.com', 'sites/example.com/pages', 'sites/example.com/assets']) {
  assert.equal(adapter.watchers[folder].ino, inode(folder), `${folder} is watched where it is now`);
}
assert.ok(adapter.watchers['sites/example.com/assets/screenshots'], 'a new folder gets a watcher');
assert.ok(adapter.queued > 0, 'reconciles go through the adapter queue');
assert.equal(adapter.files['sites'] !== undefined, true, 'paths outside the site folder are left alone');

const unsupported = await resyncVaultFolder({ list: adapter.list }, 'sites/example.com');
assert.equal(unsupported.state, 'unsupported', 'missing internals are reported, not guessed');
const missing = await resyncVaultFolder(fakeAdapter(), 'sites/not-there');
assert.equal(missing.state, 'missing');

fs.rmSync(vault, { recursive: true, force: true });
console.log('[PASS] Obsidian index and watchers follow a swapped site folder after capture.');
