/*!
MIT License

Copyright (c) 2026 web-obs-client-report contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
*/
// Builds the client report JSON for a capture: the same steps as the report Studio's "Export client JSON" and the export command.
// Pure and browser-safe (no file access), so it can run inside the Obsidian plugin. The output holds only the fields on the export
// allowlist (see contract.ts): no vault paths, page text, resource lists or agency notes.
import type { SiteGraphManifest } from '../types/site';
import { makeCtx, stripForClient, validate, withAbsoluteTargets } from './core';
import { buildDraft } from './draft';
import { buildClientReport, isEmail, sealReport, validateClientReport } from './package';

export interface ExportAuditOptions {
  /** A person must approve what goes to a client. */
  approvedBy: string;
  /** Where the client's feedback is sent (shown in the file; the report server may hold it instead). */
  feedbackTo?: string;
  createdAt?: string;
}
export interface ExportAuditResult { json: string; sizeKb: number; clientName: string; findings: number; top: string[] }

async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

export async function exportClientReport(capture: SiteGraphManifest, opts: ExportAuditOptions): Promise<ExportAuditResult> {
  const approvedBy = opts.approvedBy.trim();
  if (!approvedBy) throw new Error('Enter your name: a person has to approve what goes to a client.');
  const feedbackTo = opts.feedbackTo?.trim() || undefined;
  if (feedbackTo && !isEmail(feedbackTo)) throw new Error('The feedback address in the settings is not a valid email address.');

  // The hash names the capture as it is stored. The report is built from the same capture with every audit target as a full address.
  const sha = await sha256Hex(JSON.stringify(capture));
  const m = withAbsoluteTargets(capture);
  const w = buildDraft(m, sha, {});
  w.authoring.reviewState = 'approved';
  w.authoring.reviewedBy = approvedBy;
  if (feedbackTo) w.brand.feedbackEmail = feedbackTo;

  const res = validate(w, m, { manifestSha: sha, mode: 'client' });
  if (!res.ok) throw new Error(`The report is not ready to send: ${res.errors[0]?.message ?? 'it failed its checks'}`);
  const built = buildClientReport(w, m, { createdAt: opts.createdAt ?? new Date().toISOString(), feedbackDefaults: { to: feedbackTo } });
  const report = await sealReport(built, sha256Hex);
  const problems = validateClientReport(report, makeCtx(m));
  if (problems.length) throw new Error(`The client report failed its own checks: ${problems[0].where}: ${problems[0].message}`);
  void stripForClient;

  const json = JSON.stringify(report, null, 2);
  return {
    json, sizeKb: Math.round(json.length / 1024), clientName: report.client.name, findings: report.findings.length,
    top: report.modes.guided.top.findingIds.map((id) => report.findings.find((f) => f.id === id)?.title ?? id),
  };
}
