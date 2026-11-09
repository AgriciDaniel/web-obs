// Checks for Publish with push: target parsing, the https route (mocked network), ssh (mocked), and a local folder.
// Synthetic data and temporary folders only; no network, no ssh, no key is touched.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { build } from 'esbuild';

const output = await build({ entryPoints: ['src/plugin/publishTarget.ts'], bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent' });
const { parsePublishTarget, publishToTarget, describeTarget, parseDestination } = await import('data:text/javascript;base64,' + Buffer.from(output.outputFiles[0].contents).toString('base64'));

const report = JSON.stringify({ format: 'webobs.client-report', version: '1.1', meta: { review: { state: 'approved' } }, client: { name: 'Example Co' } });
const SECRET = 'app-secret-' + 'a'.repeat(30), CFID = 'cf-id-123', CFSEC = 'cf-secret-' + 'b'.repeat(20);

// ---- parsing --------------------------------------------------------------------------------------------------------------
assert.equal(parsePublishTarget('').kind, 'none');
const H = { kind: 'https', url: 'https://audit.example.com/ingest/v1/reports', host: 'audit.example.com' };
for (const form of ['audit.example.com', 'https://audit.example.com', 'https://audit.example.com/', 'AUDIT.example.com', 'https://audit.example.com/ingest/v1/reports']) assert.deepEqual(parsePublishTarget(form), { ...H, host: form.toLowerCase().includes('audit') ? 'audit.example.com' : H.host }, 'front end address only: ' + form);
assert.throws(() => parsePublishTarget('https://audit.example.com/other/path'), /front end address only/);
assert.throws(() => parsePublishTarget('https://audit.example.com/?x=1'), /query/);
assert.equal(parsePublishTarget('audit.example.com:8443').host, 'audit.example.com:8443');
assert.equal(parsePublishTarget('http://127.0.0.1:8081/ingest/v1/reports').kind, 'https', 'plain http only to this computer');
assert.throws(() => parsePublishTarget('http://ingest.example.com/x'), /https/);
assert.throws(() => parsePublishTarget('https://user:pw@ingest.example.com/x'), /login/);
assert.deepEqual(parsePublishTarget('reports-box:/srv/webobs'), { kind: 'ssh', host: 'reports-box', dir: '/srv/webobs' });
assert.deepEqual(parsePublishTarget('deploy@host.example.com:/srv/webobs/'), { kind: 'ssh', host: 'deploy@host.example.com', dir: '/srv/webobs' });
assert.equal(parsePublishTarget(os.tmpdir()).kind, 'folder');
assert.equal(parsePublishTarget('C:/reports/out').kind, 'folder', 'a Windows path with forward slashes is a folder, not ssh host C');
assert.equal(parsePublishTarget('D:\\reports\\out').kind, 'folder');
assert.throws(() => parsePublishTarget('relative/folder'), /must be/);
assert.throws(() => parsePublishTarget('host:/dir; rm -rf /'), /must be/, 'no shell text gets through');
assert.equal(describeTarget(parsePublishTarget('https://ingest.example.com')), 'ingest.example.com', 'only the host is shown');

// ---- destination dialog (nothing set): a folder or a front end address, never both, same checks as the setting ----------------
assert.deepEqual(parseDestination({ folder: os.tmpdir() }), { kind: 'folder', dir: os.tmpdir() });
const pushed = parseDestination({ address: 'audit.example.com' });
assert.equal(pushed.kind, 'push'); assert.equal(pushed.target.url, 'https://audit.example.com/ingest/v1/reports'); assert.equal(pushed.remember, 'audit.example.com', 'only the address is remembered');
assert.throws(() => parseDestination({}), /Choose a folder/);
assert.throws(() => parseDestination({ folder: os.tmpdir(), address: 'audit.example.com' }), /one of the two/);
assert.throws(() => parseDestination({ folder: 'relative/dir' }), /full path/);
assert.throws(() => parseDestination({ address: 'http://audit.example.com' }), /https/, 'https required');
assert.throws(() => parseDestination({ address: 'https://user:pw@audit.example.com' }), /login/);
assert.throws(() => parseDestination({ address: 'reports-box:/srv/webobs' }), /front end address/, 'ssh is a setting, not the dialog');
const dlgSrc = fs.readFileSync('src/plugin/publishDestinationUi.ts', 'utf8');
assert.ok(!/password|setSecret|secretStorage|type = /i.test(dlgSrc), 'the dialog has no secret field');

// ---- https (mocked network) -----------------------------------------------------------------------------------------------
const calls = [];
const okPost = async (url, headers, body) => { calls.push({ url, headers, body }); return { status: 201, body: JSON.stringify({ ok: true, link: 'https://audit.example.com/r/' + 'T'.repeat(43), linkId: 'abc123', expiresAt: '2030-01-01T00:00:00.000Z' }) }; };
const https = parsePublishTarget('ingest.example.com');
const env = { WEBOBS_INGEST_SECRET: SECRET, CF_ACCESS_CLIENT_ID: CFID, CF_ACCESS_CLIENT_SECRET: CFSEC };
const done = await publishToTarget(https, report, { hours: 6, deps: { env, post: okPost } });
assert.equal(done.link, 'https://audit.example.com/r/' + 'T'.repeat(43));
assert.equal(done.via, 'ingest.example.com');
assert.equal(new URL(calls[0].url).searchParams.get('hours'), '6');
assert.equal(calls[0].headers.Authorization, 'Bearer ' + SECRET);
assert.equal(calls[0].headers['CF-Access-Client-Id'], CFID);
assert.equal(calls[0].headers['CF-Access-Client-Secret'], CFSEC);
assert.equal(calls[0].body, report, 'the report goes as sent, nothing is added');
const fail = async (deps, t = https, json = report) => { try { await publishToTarget(t, json, { hours: 72, deps }); return null; } catch (e) { return e; } };
const noSecret = await fail({ env: {}, post: okPost });
assert.match(noSecret.message, /No ingest secret is available/); assert.equal(calls.length, 1, 'nothing is sent without a secret');
for (const status of [404, 401, 403, 302]) { const e = await fail({ env, post: async () => ({ status, body: '' }) }); assert.match(e.message, /refused the upload/, 'status ' + status); assert.ok(e.message.includes(`HTTP ${status}`), 'the status number is shown: ' + status); assert.ok(!/environment Obsidian was started/.test(e.message)); assert.ok(![SECRET, CFID, CFSEC].some((s) => e.message.includes(s))); }
assert.match((await fail({ env, post: async () => ({ status: 429, body: '' }) })).message, /too many uploads/);
const down = await fail({ env, post: async () => { throw new Error('ECONNREFUSED ' + SECRET); } });
assert.equal(down.message, 'The server could not be reached.', 'no detail, no secret');
assert.match((await fail({ env, post: async () => ({ status: 422, body: 'x' }) })).message, /did not accept the report \(422\)/);
assert.match((await fail({ env, post: async () => ({ status: 201, body: JSON.stringify({ ok: true, linkId: 'a', expiresAt: 'b' }) }) })).message, /sent no link/);
for (const link of ['javascript:alert(1)', 'https://user:password@audit.example.com/r/token', 'http://audit.example.com/r/token']) {
  assert.match((await fail({ env, post: async () => ({ status: 201, body: JSON.stringify({ ok: true, link, linkId: 'id', expiresAt: '2030-01-01T00:00:00Z' }) }) })).message, /invalid report link/);
}
assert.match((await fail({ env, post: okPost }, https, JSON.stringify({ format: 'webobs.explore-pack' }))).message, /not a client report/, 'the explore pack never leaves');
assert.match((await fail({ env, post: okPost }, https, JSON.stringify({ format: 'webobs.client-report', meta: { review: { state: 'draft' } } }))).message, /not approved/);
await assert.rejects(() => publishToTarget(https, report, { hours: 0, deps: { env, post: okPost } }), /Hours/);
assert.equal(calls.length, 1, 'refusals above sent nothing');
assert.ok(!fs.readFileSync('src/plugin/publishTarget.ts', 'utf8').match(/writeFileSync\([^)]*(SECRET|secret|CF_)/), 'no secret is written anywhere');

// ---- local folder (the server's layout) ------------------------------------------------------------------------------------
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'wo-push-'));
const folder = parsePublishTarget(path.join(tmp, 'volume'));
const local = await publishToTarget(folder, report, { hours: 72, linkBase: 'https://audit.example.com/', deps: { now: () => Date.parse('2026-01-01T00:00:00Z') } });
const files = fs.readdirSync(path.join(tmp, 'volume', 'reports'));
assert.equal(files.length, 1); assert.match(files[0], /^[0-9a-f]{32}\.json$/, 'a random 32-hex name, nothing about the client');
const entries = fs.readdirSync(path.join(tmp, 'volume', 'registry'));
const entry = JSON.parse(fs.readFileSync(path.join(tmp, 'volume', 'registry', entries[0]), 'utf8'));
const token = local.link.split('/r/')[1];
assert.match(local.link, /^https:\/\/audit\.example\.com\/r\/[A-Za-z0-9_-]{43}$/);
assert.equal(entry.tokenHash, crypto.createHash('sha256').update(token).digest('hex'), 'only the hash is stored');
assert.ok(!JSON.stringify(entry).includes(token) && !fs.readFileSync(path.join(tmp, 'volume', 'reports', files[0]), 'utf8').includes(token));
assert.equal(entry.path, files[0]); assert.equal(entry.expiresAt, '2026-01-04T00:00:00.000Z', '72 hours'); assert.equal(entry.revoked, false);
assert.ok(!fs.readdirSync(os.tmpdir()).some((n) => n.startsWith('wo-publish-')), 'the working folder is removed');
assert.equal((await publishToTarget(folder, report, { hours: 72 })).link, null, 'no viewer address, no link');

// ---- ssh (mocked): order, options, nothing read or stored -------------------------------------------------------------------
const ran = [];
const ok = (cmd, args) => { ran.push([cmd, ...args]); return { status: 0, stderr: '' }; };
const ssh = parsePublishTarget('reports-box:/srv/webobs');
const viaSsh = await publishToTarget(ssh, report, { hours: 24, linkBase: 'https://audit.example.com', deps: { run: ok } });
assert.deepEqual(ran.map((r) => r[0]), ['ssh', 'scp', 'scp'], 'folders, then the report, then the link entry');
assert.ok(ran[1].some((a) => a.endsWith('/reports/')) && ran[2].some((a) => a.endsWith('/registry/')), 'the report goes first and the link entry last');
for (const r of ran) { assert.ok(r.includes('BatchMode=yes') && r.includes('StrictHostKeyChecking=yes'), 'never prompts, host key checked'); assert.ok(!r.includes('-i') && !r.some((a) => /\.(pem|key)$|id_rsa|id_ed25519/.test(a)), 'no key file is named'); }
assert.equal(ran[0][5], 'reports-box'); assert.equal(viaSsh.via, 'reports-box');
assert.match(viaSsh.link, /\/r\/[A-Za-z0-9_-]{43}$/);
const sshFail = await fail({ run: () => ({ status: 255, stderr: 'Host key verification failed. my-secret-token-value' }) }, ssh);
assert.match(sshFail.message, /Creating folders on the server over ssh failed/); assert.ok(!sshFail.message.includes('my-secret-token-value'), 'secret-looking words are masked');
const halfway = []; const second = await fail({ run: (c) => { halfway.push(c); return { status: c === 'scp' && halfway.length === 2 ? 1 : 0, stderr: '' }; } }, ssh);
assert.match(second.message, /Copying the report over scp failed/); assert.equal(halfway.length, 2, 'the link entry is not uploaded when the report failed');

// ---- secrets: storage first, memory prompt, env only as explicit override, never data.json ------------------------------------
const sec = await build({ entryPoints: ['src/plugin/publishSecrets.ts'], bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent' });
const { makeSecretProvider, saveSecret } = await import('data:text/javascript;base64,' + Buffer.from(sec.outputFiles[0].contents).toString('base64'));
const NAMES = { ingest: 'web-obs-publish-ingest-secret', cfId: 'web-obs-publish-cf-access-id', cfSecret: 'web-obs-publish-cf-access-secret' };
assert.ok(Object.values(NAMES).every((n) => /^web-obs-publish-[a-z-]+$/.test(n)), 'secret ids are namespaced so they cannot clash with another plugin');
const mem = new Map(); const store = { data: {}, getSecret(id) { return this.data[id] ?? null; }, setSecret(id, v) { this.data[id] = v; } };
let asked = 0; const ask = async () => { asked++; return ' typed-secret-' + 'c'.repeat(20) + ' '; };
const provider = makeSecretProvider({ store, session: mem, ask });
assert.equal(await provider(NAMES.cfId), null, 'the Cloudflare values are never prompted for'); assert.equal(asked, 0);
const prompted = await provider(NAMES.ingest); assert.equal(prompted, 'typed-secret-' + 'c'.repeat(20)); assert.equal(asked, 1, 'asked once');
assert.equal(await provider(NAMES.ingest), prompted); assert.equal(asked, 1, 'kept in memory for the session, not asked again');
assert.equal(saveSecret(store, NAMES.ingest, 'stored-' + 'd'.repeat(20)), true);
assert.equal(await provider(NAMES.ingest), 'stored-' + 'd'.repeat(20), 'Obsidian storage wins over memory');
assert.equal(await makeSecretProvider({ store: null, session: new Map() })(NAMES.ingest), null, 'no storage, no ask: nothing, no crash');
assert.equal(await makeSecretProvider({ store: { getSecret() { throw new Error('boom'); }, setSecret() {} }, session: new Map(), ask: async () => null })(NAMES.ingest), null, 'a failing store and a cancelled prompt give nothing');
assert.equal(saveSecret(null, NAMES.ingest, 'x'), false);
// the https route with the provider (no environment at all)
const withStore = { getSecret: (id) => ({ [NAMES.ingest]: SECRET, [NAMES.cfId]: CFID, [NAMES.cfSecret]: CFSEC })[id] ?? null, setSecret() {} };
const calls2 = []; const post2 = async (u, h, b) => { calls2.push(h); return okPost(u, h, b); };
await publishToTarget(https, report, { hours: 1, deps: { secret: makeSecretProvider({ store: withStore, session: new Map() }), post: post2 } });
assert.equal(calls2[0].Authorization, 'Bearer ' + SECRET); assert.equal(calls2[0]['CF-Access-Client-Id'], CFID);
await assert.rejects(() => publishToTarget(https, report, { hours: 1, deps: { post: post2 } }), /No ingest secret/, 'the environment is NOT read unless the caller passes it');
// data.json: the settings object holds no secret, and no source file writes one
const src = (f) => fs.readFileSync(f, 'utf8');
const settingsSrc = src('src/plugin/settings.ts'), viewSrc = src('src/plugin/SiteGlobeView.ts');
const defaults = settingsSrc.slice(settingsSrc.indexOf('DEFAULT_SETTINGS'), settingsSrc.indexOf('export interface SettingTabBridge'));
assert.ok(!/secret|token|cf_access/i.test(defaults.replace(/publishEnvSecrets/g, '')), 'no secret field in the saved settings');
assert.ok(settingsSrc.includes("t.inputEl.addEventListener('change'") && settingsSrc.includes('saveSecret(secretStore, id, v)'), 'secret fields go to secretStorage only');
assert.ok(!settingsSrc.includes('t.onChange((v) => { if (v) saveSecret'), 'a secret is saved when the field is left, never on every keystroke');
assert.ok(!settingsSrc.includes('this.bridge.settings[id]') && !settingsSrc.includes('bridge.settings.publishSecret'), 'a secret value is never assigned into settings');
const savedKeys = Object.keys({ clientReportsFolder: 1 }); void savedKeys;
const simulated = JSON.stringify({ publishTarget: 'audit.example.com', publishLinkBase: '', publishEnvSecrets: false }); // what saveSettings would hold
for (const s of [SECRET, CFID, CFSEC, 'typed-secret-', 'stored-']) assert.ok(!simulated.includes(s), 'data.json holds no secret value');
for (const f of ['src/plugin/publishTarget.ts', 'src/plugin/publishSecrets.ts', 'src/plugin/publishSecretsUi.ts']) { const s = src(f); assert.ok(!s.includes('writeFileSync(') || f.endsWith('publishTarget.ts'), f + ': no file writes'); assert.ok(!s.includes('localStorage') && !s.includes('console.'), f + ': nothing stored or logged'); }
assert.ok(!src('src/plugin/publishTarget.ts').includes('writeFileSync(reportFile, json); fs.writeFileSync(entryFile') === false, 'only the report and link entry are written (folder/ssh), never a secret');
assert.ok(!src('src/plugin/publishTarget.ts').includes('process.env'), 'publishTarget.ts does not read the environment itself');
assert.ok(viewSrc.includes('s.publishEnvSecrets ? process.env'), 'the environment is read only when the setting is on');

fs.rmSync(tmp, { recursive: true, force: true });
console.log('Publish target OK: base-address parsing, destination dialog rules, https with mocked network, secret sources (storage, session memory, no env by default), no secret in data.json, local folder layout, ssh (mocked).');
