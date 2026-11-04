/**
 * Bring Obsidian's file index back in line with a site folder the engine just replaced.
 *
 * A capture publishes by swapping the whole `sites/<site>` folder in one rename. Obsidian's
 * watcher then sees an event for a folder path it already knows, so it keeps its old file list
 * (new files such as snapshots stay invisible until a reload) and, where Obsidian watches each
 * folder separately (Linux), keeps watching the folder that moved into the capture history.
 *
 * The fix walks the folder on disk and asks Obsidian to reconcile every path, which is what its
 * own watcher does for a single change: new files are indexed, changed files refresh and removed
 * files leave the index. Folder watchers are then attached to the folders now on disk.
 *
 * These are internal adapter methods with no public equivalent. Every call is feature-checked;
 * when one is missing the caller is told, so it can suggest reloading Obsidian instead.
 */

export interface ResyncAdapter {
  list(path: string): Promise<{ files: string[]; folders: string[] }>;
  files?: Record<string, unknown>;
  reconcileInternalFile?: (path: string) => Promise<unknown>;
  queue?: (task: () => Promise<unknown>) => Promise<unknown>;
  watchers?: Record<string, unknown>;
  startWatchPath?: (path: string) => Promise<unknown> | unknown;
  stopWatchPath?: (path: string) => void;
}

export interface ResyncResult {
  state: 'synced' | 'unsupported' | 'missing';
  checked: number;
  removed: number;
  rewatched: number;
}

const clean = (value: string) => value.replace(/\\/g, '/').replace(/\/+/g, '/').replace(/^\/|\/$/g, '');
const inside = (candidate: string, root: string) => candidate === root || candidate.startsWith(root + '/');

export async function resyncVaultFolder(adapter: ResyncAdapter, folder: string): Promise<ResyncResult> {
  const root = clean(folder);
  const result: ResyncResult = { state: 'unsupported', checked: 0, removed: 0, rewatched: 0 };
  if (!root || typeof adapter.list !== 'function' || typeof adapter.reconcileInternalFile !== 'function' || !adapter.files) return result;
  const reconcile = (target: string) => typeof adapter.queue === 'function'
    ? adapter.queue(() => adapter.reconcileInternalFile!(target))
    : adapter.reconcileInternalFile!(target);

  const onDisk = new Set<string>();
  const folders: string[] = [];
  try {
    const pending = [root];
    while (pending.length) {
      const current = pending.shift()!;
      const listing = await adapter.list(current);
      folders.push(current);
      onDisk.add(current);
      for (const child of listing.folders) pending.push(clean(child));
      for (const file of listing.files) onDisk.add(clean(file));
    }
  } catch {
    return { ...result, state: 'missing' };
  }

  // Re-attach per-folder watchers first, so changes made while reconciling are not missed.
  if (adapter.watchers && typeof adapter.stopWatchPath === 'function' && typeof adapter.startWatchPath === 'function') {
    for (const path of folders) {
      if (!Object.prototype.hasOwnProperty.call(adapter.watchers, path)) continue;
      adapter.stopWatchPath(path);
      await adapter.startWatchPath(path);
      result.rewatched += 1;
    }
  }

  // Parents before children; Obsidian reconciles a missing parent itself, but this keeps it cheap.
  for (const path of [...onDisk].sort((a, b) => a.split('/').length - b.split('/').length || a.localeCompare(b))) {
    await reconcile(path);
    result.checked += 1;
  }
  for (const path of Object.keys(adapter.files)) {
    if (inside(path, root) && !onDisk.has(path)) {
      await reconcile(path);
      result.removed += 1;
    }
  }
  return { ...result, state: 'synced' };
}
