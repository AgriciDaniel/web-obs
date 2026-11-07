import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { StringDecoder } from 'node:string_decoder';
import type { PluginOption } from 'vite';
import { JsonlDecoder } from '../data/jsonl';
import { isSafeSiteId, parseSiteManifest } from '../data/validateManifest';
import { askEngineToStop, CANCEL_ON_STDIN, forceEngineStop } from '../plugin/engineStop';

const SITE_IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.ico', '.avif']);
export const MAX_SITE_IMAGE_BYTES = 4 * 1024 * 1024;

/**
 * Resolves `sites/<siteId>/...` to a real image file inside that site's folder, or null. Rejects
 * traversal, other file types, oversized files and symlinks that lead outside the capture.
 */
export function resolveSiteImage(sitesRoot: string, requested: string | null): string | null {
  if (typeof requested !== 'string' || requested.length > 300 || /[\x00-\x1f\x7f\\]/.test(requested)) return null;
  const parts = requested.split('/');
  if (parts.length < 3 || parts[0] !== 'sites' || !isSafeSiteId(parts[1]) || parts.some((part) => !part || part === '.' || part === '..')) return null;
  if (!SITE_IMAGE_EXTENSIONS.has(path.extname(requested).toLowerCase())) return null;
  try {
    const siteRoot = fs.realpathSync(path.join(sitesRoot, parts[1]));
    const file = fs.realpathSync(path.join(sitesRoot, ...parts.slice(1)));
    if (!file.startsWith(siteRoot + path.sep)) return null;
    const stat = fs.statSync(file);
    return stat.isFile() && stat.size <= MAX_SITE_IMAGE_BYTES ? file : null;
  } catch {
    return null;
  }
}

/** Local development transport for the same crawler used by the Obsidian view. */
export function webObsDevApiPlugin(): PluginOption {
  const vaultRoot = process.cwd();
  const sitesRoot = path.join(vaultRoot, 'sites');
  const children = new Set<ChildProcessWithoutNullStreams>();
  return {
    name: 'web-obs-dev-api',
    configureServer(server) {
      server.httpServer?.once('close', () => { for (const child of children) askEngineToStop(child); });
      server.middlewares.use((req, res, next) => {
        if (!req.url?.startsWith('/__web_obs/')) return next();
        const url = new URL(req.url, 'http://localhost');
        const json = (status: number, value: unknown) => {
          res.statusCode = status;
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify(value));
        };
        if (req.method === 'GET' && url.pathname === '/__web_obs/sites') {
          const sites = [];
          const invalidCaptures: string[] = [];
          if (fs.existsSync(sitesRoot)) for (const entry of fs.readdirSync(sitesRoot, { withFileTypes: true })) {
            if (!entry.isDirectory() || !isSafeSiteId(entry.name)) continue;
            const file = path.join(sitesRoot, entry.name, '_site-graph.json');
            if (!fs.existsSync(file)) continue;
            try {
              const capture = parseSiteManifest(JSON.parse(fs.readFileSync(file, 'utf8')));
              sites.push({ siteId: entry.name, domain: capture.domain, capturedAt: capture.capturedAt, pagesCrawled: capture.stats.pagesCrawled, externalDomains: capture.stats.externalDomains });
            } catch { invalidCaptures.push(entry.name); }
          }
          sites.sort((a, b) => b.capturedAt.localeCompare(a.capturedAt));
          return json(200, { sites, invalidCaptures });
        }
        if (req.method === 'GET' && url.pathname === '/__web_obs/site') {
          const id = url.searchParams.get('id');
          if (!isSafeSiteId(id)) return json(400, { error: 'Invalid site ID.' });
          const file = path.join(sitesRoot, id, '_site-graph.json');
          if (!fs.existsSync(file)) return json(404, { error: 'Site capture not found.' });
          try { return json(200, parseSiteManifest(JSON.parse(fs.readFileSync(file, 'utf8')))); }
          catch (error) { return json(422, { error: error instanceof Error ? error.message : 'Invalid capture.' }); }
        }
        if (req.method === 'GET' && url.pathname === '/__web_obs/asset') {
          // Read-only: a saved image inside one site's capture folder, for the map's brand badge.
          if (req.headers['sec-fetch-site'] === 'cross-site') return json(403, { error: 'Assets require a same-origin request.' });
          const asset = resolveSiteImage(sitesRoot, url.searchParams.get('path'));
          if (!asset) return json(404, { error: 'Asset not found.' });
          res.statusCode = 200;
          res.setHeader('Content-Type', 'application/octet-stream');
          res.setHeader('X-Content-Type-Options', 'nosniff');
          res.setHeader('Cache-Control', 'no-store');
          return res.end(fs.readFileSync(asset));
        }
        if (req.method !== 'POST' || !['/__web_obs/crawl', '/__web_obs/continue-links'].includes(url.pathname)) return json(404, { error: 'Unknown capture endpoint.' });
        if (req.headers['sec-fetch-site'] === 'cross-site') return json(403, { error: 'Capture requires a same-origin request.' });
        try {
          if (req.headers.origin && new URL(req.headers.origin).host !== req.headers.host) return json(403, { error: 'Capture requires a same-origin request.' });
        } catch { return json(403, { error: 'Invalid request origin.' }); }
        let body = '';
        let bodyBytes = 0;
        const bodyDecoder = new StringDecoder('utf8');
        let oversized = false;
        req.on('data', (chunk: Buffer) => {
          if (oversized) return;
          bodyBytes += chunk.length;
          body += bodyDecoder.write(chunk);
          if (bodyBytes > 16 * 1024) { oversized = true; json(413, { error: 'Capture request is too large.' }); }
        });
        req.on('end', () => {
          if (oversized || res.destroyed || req.aborted) return;
          body += bodyDecoder.end();
          const continuing = url.pathname === '/__web_obs/continue-links';
          let options: { url: string; maxPages: number; renderMode: 'auto' | 'always' | 'never'; downloadImages: boolean; imageMode: 'preferred' | 'all'; continueLinksSiteId?: string; browserAudit: boolean; spellCheck: boolean; dnsChecks: boolean; pageSnapshots: boolean; snapshotLimit: number; snapshotHtml: boolean; tlsCheck: boolean; taskList: boolean; deadlineSec: number | null };
          try {
            const data = JSON.parse(body || '{}');
            if (!data || typeof data !== 'object' || Array.isArray(data) || typeof data.url !== 'string' || !data.url.trim() || data.url.length > 2048) throw new Error('Enter a website URL.');
            const maxPages = data.maxPages ?? 250;
            if (!Number.isInteger(maxPages) || maxPages < 1 || maxPages > 1000) throw new Error('Page limit must be between 1 and 1000.');
            const renderMode = data.renderMode ?? 'auto';
            if (!['auto', 'always', 'never'].includes(renderMode)) throw new Error('Invalid rendering mode.');
            const imageMode = data.imageMode ?? 'preferred';
            if (!['preferred', 'all'].includes(imageMode)) throw new Error('Invalid image variant mode.');
            if (continuing && !isSafeSiteId(data.continueLinksSiteId)) throw new Error('Invalid saved site ID.');
            const deadlineSec = data.deadlineSec ?? null;
            if (deadlineSec !== null && (typeof deadlineSec !== 'number' || !Number.isFinite(deadlineSec) || deadlineSec < 0 || deadlineSec > 86400)) throw new Error('Capture time limit must be between 0 and 86400 seconds.');
            options = { url: data.url.trim(), maxPages, renderMode, imageMode, downloadImages: data.downloadImages !== false, continueLinksSiteId: continuing ? data.continueLinksSiteId : undefined,
              browserAudit: data.browserAudit !== false, spellCheck: data.spellCheck === true, dnsChecks: data.dnsChecks !== false,
              pageSnapshots: data.pageSnapshots !== false, snapshotLimit: Number.isInteger(data.snapshotLimit) ? Math.max(1, Math.min(500, data.snapshotLimit)) : 25, snapshotHtml: data.snapshotHtml === true,
              tlsCheck: data.tlsCheck !== false, taskList: data.taskList !== false, deadlineSec: deadlineSec ? Math.max(1, Math.round(deadlineSec)) : null };
          } catch (error) { return json(400, { error: error instanceof Error ? error.message : 'Invalid capture request.' }); }

          res.setHeader('Content-Type', 'application/x-ndjson; charset=utf-8');
          res.setHeader('Cache-Control', 'no-store');
          res.flushHeaders();
          const script = path.join(vaultRoot, 'engine', 'crawl_site.py');
          const venv = path.join(vaultRoot, 'engine', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python3');
          const args = continuing
            ? [script, options.continueLinksSiteId!, '--vault', vaultRoot, '--continue-links']
            : [script, options.url, '--vault', vaultRoot, '--max-pages', String(options.maxPages), '--render', options.renderMode, '--image-mode', options.imageMode];
          if (!options.downloadImages) args.push('--no-images');
          args.push(CANCEL_ON_STDIN);
          if (!options.continueLinksSiteId) {
            if (!options.browserAudit) args.push('--no-browser-audit');
            if (options.spellCheck) args.push('--spell-check');
            if (!options.dnsChecks) args.push('--no-dns-checks');
            if (!options.pageSnapshots) args.push('--no-snapshots');
            else args.push('--snapshot-limit', String(options.snapshotLimit));
            if (options.snapshotHtml) args.push('--snapshot-html');
            if (!options.tlsCheck) args.push('--no-tls-check');
            if (!options.taskList) args.push('--no-tasks');
            if (options.deadlineSec) args.push('--deadline', String(options.deadlineSec));
          }
          const child = spawn(fs.existsSync(venv) ? venv : (process.env.WEB_OBS_PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3')), args, { cwd: vaultRoot });
          children.add(child);
          let terminal = false;
          let completed: Record<string, unknown> | undefined;
          let stderr = '';
          let forceTimer: ReturnType<typeof setTimeout> | undefined;
          const stop = () => {
            if (child.exitCode !== null || child.signalCode !== null) return;
            askEngineToStop(child);
            forceTimer ??= setTimeout(() => { if (child.exitCode === null && child.signalCode === null) forceEngineStop(child); }, 3000);
            forceTimer.unref();
          };
          const finish = (event: Record<string, unknown>) => {
            if (terminal) return;
            terminal = true;
            if (!res.destroyed) res.end(JSON.stringify(event) + '\n');
          };
          const decoder = new JsonlDecoder((event) => {
            if (terminal) return;
            if (completed) throw new Error('Crawler emitted data after completion.');
            if (event.event === 'error') { finish(event); stop(); }
            else if (event.event === 'complete') completed = event;
            else if (!res.destroyed) res.write(JSON.stringify(event) + '\n');
          });
          const onAborted = () => stop();
          const onClosed = () => { if (!res.writableEnded) stop(); };
          req.once('aborted', onAborted);
          res.once('close', onClosed);
          const deadline = setTimeout(() => { finish({ event: 'error', message: 'Capture exceeded its 15 minute time budget.' }); stop(); }, 15 * 60 * 1000);
          deadline.unref();
          child.stdout.on('data', (chunk: Buffer) => {
            try { decoder.push(chunk); }
            catch (error) { finish({ event: 'error', message: error instanceof Error ? error.message : 'Invalid crawler stream.' }); stop(); }
          });
          child.stderr.on('data', (chunk: Buffer) => { stderr = (stderr + chunk.toString('utf8')).slice(-4000); });
          child.once('error', (error) => { finish({ event: 'error', message: `Could not start the crawler: ${error.message}` }); });
          child.once('close', (code, signal) => {
            children.delete(child);
            clearTimeout(deadline);
            if (forceTimer) clearTimeout(forceTimer);
            req.removeListener('aborted', onAborted);
            res.removeListener('close', onClosed);
            try {
              decoder.finish();
              if (code !== 0) finish({ event: 'error', message: stderr.trim().slice(0, 400) || `Crawler stopped (${signal || `exit ${code}`}).` });
              else if (!completed) finish({ event: 'error', message: 'Crawler exited without a completed capture.' });
              else finish(completed);
            } catch (error) { finish({ event: 'error', message: error instanceof Error ? error.message : 'Invalid crawler stream.' }); }
          });
        });
      });
    },
  };
}
