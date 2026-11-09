// Publish with push: send the client report to a publish target instead of saving it in a local folder. Desktop only.
//
// A target is one of
//   https://host/path        the report server's HTTPS ingest route: the server stores the report, makes the link and sends it back
//   alias:/dir  or  user@host:/dir   over ssh, using your own ssh config (an alias can carry a ProxyCommand for a Cloudflare tunnel)
//   /full/or/C:\local\folder  a local folder (the same layout the server reads)
// Empty means "no push": Publish audit saves the file in the client reports folder, as before.
//
// Secrets: the https route needs an ingest secret and two Cloudflare Access values. They come from Obsidian's own secret storage, or a
// prompt kept in memory for the session, or (only if the user switches it on) the environment. The secret never goes into data.json
// or the vault, and is never put in the page, a log or an error message. For ssh, no key is read or
// stored here: ssh uses the user's own agent and config, with BatchMode (never prompts) and the host key checked.
//
// To remove this feature: delete this file, the two settings it adds, and the `publishToTarget` branch in SiteGlobeView.buildAuditActions.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import https from 'node:https';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';

export type PublishTarget =
  | { kind: 'none' }
  | { kind: 'https'; url: string; host: string }
  | { kind: 'ssh'; host: string; dir: string }
  | { kind: 'folder'; dir: string };

export interface PublishedLink { link: string | null; linkId: string; expires: string; via: string }

export interface HttpReply { status: number; body: string }
/** The three values the https route needs. Where they come from is the caller's business (Obsidian secret storage, a prompt, or an explicit environment override). */
export const SECRET_NAMES = { ingest: 'web-obs-publish-ingest-secret', cfId: 'web-obs-publish-cf-access-id', cfSecret: 'web-obs-publish-cf-access-secret' } as const;
export type SecretName = (typeof SECRET_NAMES)[keyof typeof SECRET_NAMES];

export interface PublishDeps {
  /** Looks up a secret by name; null or empty when there is none. Used for the https route. */
  secret?: (name: SecretName) => Promise<string | null> | string | null;
  /** Only for an explicit environment override (a plugin setting turns it on). Not read unless the caller passes it. */
  env?: Record<string, string | undefined>;
  /** Sends the POST. Default: Node's http/https, no redirects, a time limit and a size cap. */
  post?: (url: string, headers: Record<string, string>, body: string) => Promise<HttpReply>;
  /** Runs ssh or scp. Default: spawnSync. Returns the exit status and the last stderr line only. */
  run?: (cmd: string, args: string[]) => { status: number | null; stderr: string };
  now?: () => number;
}

const INGEST_ROUTE = '/ingest/v1/reports';
const BARE_HOST = /^(localhost|127\.0\.0\.1|[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+)(:\d{1,5})?\/?$/;
const DRIVE_PATH = /^[A-Za-z]:[\\/]/;
const SSH =/^([A-Za-z0-9][A-Za-z0-9._@-]*):(\/[A-Za-z0-9._/~-]*)$/;
const refused = (status: number) => `The server refused the upload (HTTP ${status}). Check the Publish secret and the Cloudflare Access ID and secret in Web-Obs settings (Client reports), and that the address is right. 3xx = Cloudflare Access login page (token missing or not accepted); 401/403/404 = credentials were rejected, access was blocked, or the route is wrong.`;

export function parsePublishTarget(text: string): PublishTarget {
  const t = (text ?? '').trim();
  if (!t) return { kind: 'none' };
  // Front end address only: "audit.example.com" or "https://audit.example.com". The ingest route is added here, so nobody types it.
  if (/^https?:\/\//i.test(t) || BARE_HOST.test(t)) {
    let u: URL;
    try { u = new URL(/^https?:\/\//i.test(t) ? t : 'https://' + t); } catch { throw new Error('The publish target is not a valid web address.'); }
    const loopback = u.hostname === '127.0.0.1' || u.hostname === 'localhost';
    if (u.protocol !== 'https:' && !(u.protocol === 'http:' && loopback)) throw new Error('The publish target must use https (plain http works only for this computer).');
    if (u.username || u.password || u.hash || u.search) throw new Error('The publish target must not hold a login, a query or a fragment.');
    const base = u.pathname.replace(/\/+$/, '');
    // Only the bare front end address, or that address plus the ingest route itself, is accepted; any other path is refused.
    if (base !== '' && base !== INGEST_ROUTE) throw new Error('Give the front end address only, for example audit.example.com.');
    return { kind: 'https', url: u.origin + INGEST_ROUTE, host: u.host };
  }
  // A full local path is checked first: "C:/reports" would otherwise read as ssh host C, folder /reports. A one-letter ssh host is refused for the same reason.
  if (path.isAbsolute(t) || DRIVE_PATH.test(t)) return { kind: 'folder', dir: t };
  const m = SSH.exec(t);
  if (m && m[1].length > 1) return { kind: 'ssh', host: m[1], dir: m[2].replace(/\/+$/, '') };
  throw new Error('The publish target must be an https address, host:/folder for ssh, or a full local folder path.');
}

/**
 * The "where should this go" dialog: one filled-in field decides. A folder means "save the file here and I will handle ingestion";
 * an address means "push to the front end". The address gets the same checks as the setting. Returns what to remember (never a secret).
 */
export type Destination = { kind: 'folder'; dir: string } | { kind: 'push'; target: Extract<PublishTarget, { kind: 'https' }>; remember: string };
export function parseDestination(input: { folder?: string; address?: string }): Destination {
  const folder = (input.folder ?? '').trim(), address = (input.address ?? '').trim();
  if (folder && address) throw new Error('Fill in one of the two: a folder to save in, or the front end address to push to.');
  if (!folder && !address) throw new Error('Choose a folder to save in, or enter the front end address to push to.');
  if (folder) {
    if (!path.isAbsolute(folder)) throw new Error('The folder must be a full path.');
    return { kind: 'folder', dir: folder };
  }
  const t = parsePublishTarget(address);
  if (t.kind !== 'https') throw new Error('Enter the front end address, for example audit.example.com.');
  return { kind: 'push', target: t, remember: address };
}

/** What may be shown on screen about a target: the host, never a path or a login. */
export const describeTarget = (t: PublishTarget): string => (t.kind === 'https' ? t.host : t.kind === 'ssh' ? t.host : t.kind === 'folder' ? 'a local folder' : 'nowhere');

function defaultPost(url: string, headers: Record<string, string>, body: string): Promise<HttpReply> {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const lib = u.protocol === 'https:' ? https : http;
    const req = lib.request(u, { method: 'POST', headers: { ...headers, 'Content-Length': String(Buffer.byteLength(body)) }, timeout: 30000 }, (res) => {
      const chunks: Buffer[] = []; let size = 0;
      res.on('data', (c: Buffer) => { size += c.length; if (size > 1_000_000) { req.destroy(); reject(new Error('too large')); } else chunks.push(c); });
      res.on('end', () => resolve({ status: res.statusCode ?? 0, body: Buffer.concat(chunks).toString('utf8') })); // a redirect is just a status here: never followed
    });
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    req.on('error', reject);
    req.end(body);
  });
}

function defaultRun(cmd: string, args: string[]): { status: number | null; stderr: string } {
  const r = spawnSync(cmd, args, { encoding: 'utf8', timeout: 60000 });
  return { status: r.error ? null : r.status, stderr: (r.stderr || '').trim().split('\n').slice(-1)[0] ?? '' };
}

/** A report that is not on the contract never leaves the machine. The export step already guarantees this; this is the last check. */
function assertClientReport(json: string): void {
  let r: { format?: string; meta?: { review?: { state?: string } } };
  try { r = JSON.parse(json) as typeof r; } catch { throw new Error('That is not a report.'); }
  if (r.format !== 'webobs.client-report') throw new Error('That is not a client report.');
  if (r.meta?.review?.state !== 'approved') throw new Error('The report is not approved yet.');
}

const sha256hex = (s: string) => crypto.createHash('sha256').update(s).digest('hex');

export async function publishToTarget(target: PublishTarget, json: string, o: { hours: number; linkBase?: string; deps?: PublishDeps }): Promise<PublishedLink> {
  if (target.kind === 'none') throw new Error('No publish target is set.');
  if (!Number.isInteger(o.hours) || !(o.hours >= 1 && o.hours <= 720)) throw new Error('Hours must be between 1 and 720.');
  assertClientReport(json);
  const deps = o.deps ?? {};
  const now = (deps.now ?? Date.now)();

  if (target.kind === 'https') {
    const envName: Record<SecretName, string> = { [SECRET_NAMES.ingest]: 'WEBOBS_INGEST_SECRET', [SECRET_NAMES.cfId]: 'CF_ACCESS_CLIENT_ID', [SECRET_NAMES.cfSecret]: 'CF_ACCESS_CLIENT_SECRET' };
    const get = async (n: SecretName): Promise<string> => (deps.secret ? await deps.secret(n) : null) || deps.env?.[envName[n]] || '';
    const secret = await get(SECRET_NAMES.ingest);
    if (!secret) throw new Error('No ingest secret is available, so the upload cannot be authorised. Add it in the Web-Obs settings (Publish secret).');
    const headers: Record<string, string> = { 'Content-Type': 'application/json', Authorization: 'Bearer ' + secret };
    const cfId = await get(SECRET_NAMES.cfId), cfSecret = await get(SECRET_NAMES.cfSecret);
    if (cfId && cfSecret) { headers['CF-Access-Client-Id'] = cfId; headers['CF-Access-Client-Secret'] = cfSecret; }
    const url = new URL(target.url); url.searchParams.set('hours', String(o.hours));
    let reply: HttpReply;
    try { reply = await (deps.post ?? defaultPost)(url.toString(), headers, json); } catch { throw new Error('The server could not be reached.'); }
    if ([401, 403, 404].includes(reply.status) || (reply.status >= 300 && reply.status < 400)) throw new Error(refused(reply.status));
    if (reply.status === 429) throw new Error('The server says there have been too many uploads. Try again later.');
    type IngestResponse = { ok?: boolean; link?: string | null; linkId?: string; expiresAt?: string };
    let body: IngestResponse | null = null;
    try {
      const value: unknown = JSON.parse(reply.body);
      if (value && typeof value === 'object') body = {
        ok: 'ok' in value && value.ok === true,
        link: 'link' in value && typeof value.link === 'string' ? value.link : null,
        linkId: 'linkId' in value && typeof value.linkId === 'string' ? value.linkId : undefined,
        expiresAt: 'expiresAt' in value && typeof value.expiresAt === 'string' ? value.expiresAt : undefined,
      };
    } catch { body = null; }
    if (reply.status !== 201 || body?.ok !== true) throw new Error(`The server did not accept the report (${reply.status}).`);
    if (!body.link) throw new Error('The server stored the report but sent no link: its public address is not set.');
    try {
      const link = new URL(body.link);
      const local = link.hostname === 'localhost' || link.hostname === '127.0.0.1';
      if ((link.protocol !== 'https:' && !(link.protocol === 'http:' && local)) || link.username || link.password || typeof body.linkId !== 'string' || !body.linkId || typeof body.expiresAt !== 'string' || !Number.isFinite(Date.parse(body.expiresAt))) throw new Error();
    } catch { throw new Error('The server returned an invalid report link or expiry.'); }
    return { link: body.link, linkId: String(body.linkId), expires: String(body.expiresAt), via: describeTarget(target) };
  }

  // folder and ssh: make the link here, then copy the report first and the link entry last (a link never points at a missing report)
  const fileId = crypto.randomBytes(16).toString('hex');
  const linkId = crypto.randomBytes(5).toString('hex');
  const token = crypto.randomBytes(32).toString('base64url');
  const expires = new Date(now + o.hours * 3600000).toISOString();
  const entry = { id: linkId, tokenHash: sha256hex(token), path: `${fileId}.json`, createdAt: new Date(now).toISOString(), expiresAt: expires, revoked: false };
  const link = o.linkBase?.trim() ? `${o.linkBase.trim().replace(/\/+$/, '')}/r/${token}` : null;
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'wo-publish-'));
  try {
    const reportFile = path.join(work, `${fileId}.json`), entryFile = path.join(work, `${linkId}.json`);
    fs.writeFileSync(reportFile, json); fs.writeFileSync(entryFile, JSON.stringify(entry) + '\n');
    if (target.kind === 'folder') {
      fs.mkdirSync(path.join(target.dir, 'reports'), { recursive: true }); fs.mkdirSync(path.join(target.dir, 'registry'), { recursive: true });
      fs.copyFileSync(reportFile, path.join(target.dir, 'reports', `${fileId}.json`));
      fs.copyFileSync(entryFile, path.join(target.dir, 'registry', `${linkId}.json`));
    } else {
      const run = deps.run ?? defaultRun;
      const opts = ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes'];
      const step = (what: string, cmd: string, args: string[]) => { const r = run(cmd, args); if (r.status !== 0) throw new Error(`${what} failed. Check your SSH configuration and server access.`); };
      step('Creating folders on the server over ssh', 'ssh', [...opts, target.host, 'mkdir', '-p', `${target.dir}/reports`, `${target.dir}/registry`]);
      step('Copying the report over scp', 'scp', [...opts, '-q', reportFile, `${target.host}:${target.dir}/reports/`]);
      step('Copying the link entry over scp', 'scp', [...opts, '-q', entryFile, `${target.host}:${target.dir}/registry/`]);
    }
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
  return { link, linkId, expires, via: describeTarget(target) };
}
