import React from 'react';
import { Image as ImageIcon } from 'lucide-react';
import type { BrowserAuditPage, PageChecks, SiteGraphManifest, SiteNode } from '../types/site';
import { Disclosure, EmptyState, KeyValueList, RankedBars, Section, StatRow, StatTile, StatusPill, type KeyValue } from './ui';

const NO_DATA = 'No data';
const pct = (value: number | null | undefined, digits = 1) => typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(digits)}%` : NO_DATA;
const num = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : NO_DATA;
const yesNo = (value: boolean | null | undefined) => value === undefined || value === null ? NO_DATA : value ? 'Yes' : 'No';
const kb = (bytes: number | null | undefined) => typeof bytes === 'number' ? `${(bytes / 1024).toFixed(0)} KB` : NO_DATA;
const list = (values: string[] | undefined, empty = 'None') => values === undefined ? NO_DATA : values.length ? values.join(', ') : empty;
const short = (values: string[], max = 3) => values.slice(0, max).join(', ') + (values.length > max ? ` +${values.length - max}` : '');

function TagTable({ tags }: { tags: Record<string, string> | undefined }) {
  if (!tags) return <p className="wo-ui-note">{NO_DATA}</p>;
  const entries = Object.entries(tags);
  if (!entries.length) return <p className="wo-ui-note">None observed</p>;
  return <dl className="wo-dr-tags">{entries.map(([key, value]) => <React.Fragment key={key}><dt>{key}</dt><dd>{value}</dd></React.Fragment>)}</dl>;
}

/** Find the browser sample entry for a page, tolerating a trailing slash difference. */
export function browserSampleFor(manifest: SiteGraphManifest, node: SiteNode): BrowserAuditPage | undefined {
  const key = (url: string) => url.replace(/\/+$/, '').toLowerCase();
  return manifest.siteIntel?.browserAudit?.pages?.find(page => key(page.url) === key(node.url));
}

export function issueLabel(manifest: SiteGraphManifest, issue: string): string {
  const match = issue.match(/^(.*?)\s*\((\d+)\)$/);
  const slug = match ? match[1] : issue;
  const title = manifest.issueCatalog?.[slug]?.title ?? slug.replace(/-/g, ' ');
  return match ? `${title} (${match[2]})` : title;
}

/** Only rows that point at something to fix. Everything else lives in the groups below. */
function noteworthy(checks: PageChecks): KeyValue[] {
  const rows: KeyValue[] = [];
  const blocking = [...(checks.scripts?.renderBlocking ?? []), ...(checks.stylesheets?.renderBlocking ?? [])];
  if (blocking.length) rows.push({ label: 'Render-blocking files', value: String(blocking.length), title: blocking.join('\n') });
  if (checks.mixedContent?.length) rows.push({ label: 'Mixed content', value: String(checks.mixedContent.length), title: checks.mixedContent.join('\n') });
  if (checks.insecureLinks?.length) rows.push({ label: 'Links to http://', value: String(checks.insecureLinks.length), title: checks.insecureLinks.join('\n') });
  if (checks.duplicateMetaTags?.length) rows.push({ label: 'Duplicate tags', value: short(checks.duplicateMetaTags) });
  if (checks.deprecatedTags?.length) rows.push({ label: 'Deprecated tags', value: short(checks.deprecatedTags) });
  if (checks.metaRefresh) rows.push({ label: 'Meta refresh', value: checks.metaRefresh });
  if (checks.frames) rows.push({ label: 'Frames', value: 'Used' });
  if (checks.flash) rows.push({ label: 'Flash', value: 'Used' });
  if (checks.placeholderText) rows.push({ label: 'Placeholder text', value: 'Found' });
  if (checks.doctype === false) rows.push({ label: 'Doctype', value: 'Missing' });
  if (checks.charsetMismatch) rows.push({ label: 'Charset', value: 'Header and meta differ' });
  if ((checks.htmlValidation?.errors ?? 0) > 0) rows.push({ label: 'HTML parse errors', value: num(checks.htmlValidation!.errors), title: checks.htmlValidation!.topCodes.map(row => `${row.code} ${row.count}`).join('\n') });
  if (checks.spelling?.possibleMisspellings.length) rows.push({ label: 'Possible misspellings', value: short(checks.spelling.possibleMisspellings), title: checks.spelling.possibleMisspellings.join(', ') });
  const a11y = checks.accessibility;
  if (a11y?.unlabeledInputs) rows.push({ label: 'Form fields without label', value: num(a11y.unlabeledInputs) });
  if (a11y?.unnamedButtons) rows.push({ label: 'Buttons without a name', value: num(a11y.unnamedButtons) });
  if (a11y?.emptyLinks) rows.push({ label: 'Links without text', value: num(a11y.emptyLinks) });
  if (checks.firstImageLazy) rows.push({ label: 'First image lazy loaded', value: 'Yes' });
  if (typeof checks.textRatio === 'number' && checks.textRatio < 0.1) rows.push({ label: 'Text to HTML', value: pct(checks.textRatio) });
  return rows;
}

function metadataRows(node: SiteNode): KeyValue[] {
  const rows: KeyValue[] = [];
  if (node.h1.length) rows.push({ label: 'H1', value: node.h1[0], title: node.h1.length > 1 ? `${node.h1.length} H1 headings` : undefined });
  if (node.metaDescription) rows.push({ label: `Description, ${node.metaDescription.length} characters`, value: node.metaDescription });
  if (node.canonical) rows.push({ label: 'Declared canonical', value: <span className="wo-dr-mono">{node.canonical}</span> });
  if (node.metaRobots) rows.push({ label: 'Robots directive', value: node.metaRobots });
  if (node.author) rows.push({ label: 'Author', value: node.author });
  if (node.publishedDate) rows.push({ label: 'Published', value: node.publishedDate.slice(0, 10) });
  if (node.lang) rows.push({ label: 'Language', value: node.lang });
  if (node.schemaTypes.length) rows.push({ label: 'Schema types', value: node.schemaTypes.join(', ') });
  const structure = [
    node.tablesCount && `${node.tablesCount} tables`, node.codeBlocksCount && `${node.codeBlocksCount} code blocks`,
    node.videosCount && `${node.videosCount} videos`, node.formsCount && `${node.formsCount} forms`,
  ].filter(Boolean) as string[];
  if (structure.length) rows.push({ label: 'Structure', value: structure.join(', ') });
  rows.push({ label: 'In sitemap', value: node.inSitemap ? 'Yes' : 'No' });
  rows.push({ label: 'Local media', value: `${node.localImagesCount} of ${node.imagesCount}` });
  return rows;
}

function ChecksGroups({ checks, node }: { checks: PageChecks; node: SiteNode }) {
  const rd = checks.readability;
  const cache = checks.cache;
  const cit = checks.citability;
  const a11y = checks.accessibility;
  const keywords = [...(node.keywords?.bigrams ?? []), ...(node.keywords?.unigrams ?? [])].slice(0, 8);
  const og = Object.keys(checks.openGraph ?? {}).length;
  const tw = Object.keys(checks.twitter ?? {}).length;
  return <>
    <Disclosure summary="Content">
      <KeyValueList rows={[
        { label: 'Words', value: num(node.wordCount) },
        { label: 'Text to HTML', value: pct(checks.textRatio), title: 'Visible text characters divided by HTML bytes' },
        { label: 'Reading ease / grade', value: rd ? `${rd.fleschReadingEase} / ${rd.fleschKincaidGrade}` : NO_DATA, title: 'Flesch reading ease and Flesch-Kincaid grade' },
        { label: 'Readability index', value: rd ? String(rd.automatedReadabilityIndex) : NO_DATA, title: 'Automated readability index' },
        { label: 'Title words in body', value: pct(checks.titleRelevance, 0) },
        { label: 'Description words in body', value: pct(checks.descriptionRelevance, 0) },
      ]} />
      {keywords.length > 0 && <RankedBars label="Top phrases on this page" limit={8} bars={keywords.map(row => ({ id: row.term, label: row.term, value: row.count }))} />}
    </Disclosure>
    <Disclosure summary="Document">
      <KeyValueList rows={[
        { label: 'DOM elements', value: checks.dom ? num(checks.dom.nodes) : NO_DATA },
        { label: 'DOM depth / widest', value: checks.dom ? `${num(checks.dom.maxDepth)} / ${num(checks.dom.maxChildren)}` : NO_DATA, title: checks.dom?.widestElement },
        { label: 'Scripts (external)', value: checks.scripts ? `${num(checks.scripts.total)} (${num(checks.scripts.external)})` : NO_DATA },
        { label: 'Stylesheets', value: checks.stylesheets ? num(checks.stylesheets.total) : NO_DATA },
        { label: 'Render-blocking', value: checks.scripts && checks.stylesheets ? `${checks.scripts.renderBlocking.length} scripts, ${checks.stylesheets.renderBlocking.length} styles` : NO_DATA },
        { label: 'Doctype / charset', value: `${yesNo(checks.doctype)} / ${checks.metaCharset || checks.headerCharset || NO_DATA}` },
        { label: 'Compression', value: cache ? cache.contentEncoding || 'None' : NO_DATA },
        { label: 'Cache-Control', value: cache ? cache.cacheControl || 'Not set' : NO_DATA },
        { label: 'ETag / Last-Modified', value: cache ? `${yesNo(cache.etag)} / ${cache.lastModified ? 'Set' : 'Not set'}` : NO_DATA, title: cache?.lastModified ?? undefined },
        { label: 'Microdata / RDFa', value: `${list(checks.microdataTypes)} / ${list(checks.rdfaTypes)}` },
        ...(checks.htmlValidation ? [{ label: 'HTML parse errors', value: num(checks.htmlValidation.errors), title: checks.htmlValidation.validator }] : []),
      ]} />
    </Disclosure>
    <Disclosure summary="Social tags" count={og + tw}>
      <span className="wo-dr-subhead">Open Graph</span>
      <TagTable tags={checks.openGraph} />
      <span className="wo-dr-subhead">Twitter</span>
      <TagTable tags={checks.twitter} />
    </Disclosure>
    <Disclosure summary="Accessibility (static HTML)">
      <KeyValueList rows={[
        { label: 'Form fields without label', value: num(a11y?.unlabeledInputs) },
        { label: 'Buttons without a name', value: num(a11y?.unnamedButtons) },
        { label: 'Links without text', value: num(a11y?.emptyLinks) },
        { label: 'First image lazy loaded', value: yesNo(checks.firstImageLazy) },
      ]} />
    </Disclosure>
    <Disclosure summary="Citability signals">
      <KeyValueList rows={[
        { label: 'Question headings', value: cit ? `${num(cit.questionHeadings)} of ${num(cit.headingsChecked)}` : NO_DATA },
        { label: 'Lists / tables / FAQ', value: cit ? `${num(cit.lists)} / ${num(cit.tables)} / ${num(cit.faqBlocks)}` : NO_DATA },
        { label: 'Avg paragraph words', value: cit ? String(cit.avgParagraphWords) : NO_DATA, title: cit ? `${cit.longParagraphs} paragraphs over 150 words` : undefined },
        { label: 'Answer-first opening', value: yesNo(cit?.answerFirst) },
      ]} />
    </Disclosure>
  </>;
}

/** Scope notes behind the inspector's single "About these numbers" disclosure. */
export function pageCheckNotes(manifest: SiteGraphManifest, node: SiteNode): string[] {
  const checks = node.pageChecks;
  const sample = browserSampleFor(manifest, node);
  const notes: string[] = [];
  if (checks?.readability?.note) notes.push(checks.readability.note);
  if (checks?.accessibility?.note) notes.push(checks.accessibility.note);
  if (checks?.citability?.note) notes.push(checks.citability.note);
  if (checks?.spelling?.note) notes.push(checks.spelling.note);
  if (sample && !sample.error) {
    notes.push(sample.lab?.note || 'Browser lab numbers come from one load on this machine. They are not field data or Core Web Vitals.');
    notes.push('Automated accessibility rules cover only part of WCAG.');
    if (sample.thirdParty?.note) notes.push(sample.thirdParty.note);
  }
  return notes;
}

/** Checks tab: problems first, then metadata and every group collapsed. */
export const PageChecksSection: React.FC<{ manifest: SiteGraphManifest; node: SiteNode }> = ({ manifest, node }) => {
  const checks = node.pageChecks;
  const problems = checks ? noteworthy(checks) : [];
  return <>
    {checks ? <Section title="Worth a look" aside={problems.length ? `${problems.length} ${problems.length === 1 ? 'item' : 'items'}` : undefined}>
      {problems.length ? <KeyValueList rows={problems} /> : <p className="wo-ui-note">Nothing stood out in the page checks.</p>}
    </Section> : manifest.audit !== undefined && <EmptyState>No page checks. The page HTML was not available.</EmptyState>}
    <Section title="Page details">
      <Disclosure summary="Metadata"><dl className="wo-dr-meta-list">{metadataRows(node).map((row) => <div key={row.label} title={row.title}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl></Disclosure>
      {checks && <ChecksGroups checks={checks} node={node} />}
    </Section>
  </>;
};

const IMPACT_ORDER: Record<string, number> = { critical: 0, serious: 1, moderate: 2, minor: 3 };

/** Browser tab, only for pages in the browser sample. */
export const BrowserSamplePanel: React.FC<{ manifest: SiteGraphManifest; sample: BrowserAuditPage; onOpenNote: (path: string) => void; resolveAssetUrl?: (path: string) => string | null }> = ({ manifest, sample, onOpenNote, resolveAssetUrl }) => {
  if (sample.error) return <EmptyState>Browser sample failed for this page: {sample.error}</EmptyState>;
  const { lab, jsGap: gap, a11y, thirdParty: third } = sample;
  const shotPath = sample.screenshot ? `sites/${manifest.siteId}/${sample.screenshot}` : null;
  const shotUrl = shotPath ? resolveAssetUrl?.(shotPath) : null;
  const violations = [...(a11y?.violations ?? [])].sort((a, b) => (IMPACT_ORDER[a.impact ?? ''] ?? 4) - (IMPACT_ORDER[b.impact ?? ''] ?? 4));
  const jsOnly = gap ? gap.renderedSchemaTypes.filter(type => !gap.rawSchemaTypes.includes(type)) : [];
  return <>
    {shotPath && <figure className="wo-dr-shot">
      {shotUrl && <img className="wo-check-screenshot-img" src={shotUrl} alt={`Screenshot of ${sample.url} from the browser sample`} loading="lazy" />}
      <button type="button" className="wo-btn-secondary wo-btn-xs" onClick={() => onOpenNote(shotPath)}><ImageIcon size={13} aria-hidden="true" /> <span>Open screenshot</span></button>
    </figure>}
    <Section title="Lab load" aside="One load, not field data">
      <StatRow label="Lab numbers">
        <StatTile label="Largest paint" value={typeof lab?.lcpMs === 'number' ? `${num(lab.lcpMs)} ms` : NO_DATA} />
        <StatTile label="Layout shift" value={typeof lab?.cls === 'number' ? String(lab.cls) : NO_DATA} />
        <StatTile label="Requests" value={lab ? num(lab.requests) : NO_DATA} hint={lab ? kb(lab.transferBytes) : undefined} />
        <StatTile label="Load event" value={typeof lab?.loadMs === 'number' ? `${num(lab.loadMs)} ms` : NO_DATA} />
      </StatRow>
    </Section>
    {gap && <Section title="JavaScript gap">
      <KeyValueList rows={[
        { label: 'Words added by JavaScript', value: `${num(gap.wordsAddedByJsPct)}%`, title: `${num(gap.rawWords)} raw, ${num(gap.renderedWords)} rendered` },
        { label: 'Links raw / rendered', value: `${num(gap.rawLinks)} / ${num(gap.renderedLinks)}` },
        ...(jsOnly.length ? [{ label: 'Schema only after JavaScript', value: jsOnly.join(', ') }] : []),
        ...(gap.rawH1.length === 0 && gap.renderedH1.length > 0 ? [{ label: 'H1 only after JavaScript', value: gap.renderedH1[0] }] : []),
      ]} />
    </Section>}
    <Section title="Accessibility rules" aside={a11y?.state === 'ok' ? `${num(a11y.passes)} passed` : undefined}>
      {!a11y ? <p className="wo-ui-note">{NO_DATA}</p> : a11y.state !== 'ok' ? <p className="wo-ui-note">Not run: {a11y.detail || a11y.state}</p>
        : violations.length === 0 ? <StatusPill status="good" label={`No ${a11y.engine ?? 'axe-core'} rule failed`} />
        : <ul className="wo-dr-rules">{violations.map(rule => <li key={rule.id}>
          <span className="wo-dr-rule-help">{rule.help}</span>
          <span className="wo-dr-rule-meta">{rule.impact === 'critical' || rule.impact === 'serious' ? <StatusPill status="critical" label={rule.impact} /> : <span>{rule.impact ?? 'impact not given'}</span>} {rule.nodes} {rule.nodes === 1 ? 'element' : 'elements'}</span>
        </li>)}</ul>}
    </Section>
    <Section title="Third parties on first load" aside={third ? `${third.hosts.length} hosts` : undefined}>
      {!third ? <p className="wo-ui-note">{NO_DATA}</p> : third.hosts.length === 0 ? <p className="wo-ui-note">No third-party hosts requested.</p>
        : <RankedBars label="Requests per third-party host" bars={third.hosts.map(host => ({ id: host.host, label: host.host, value: host.requests, hint: host.category }))} />}
      {third && third.cookies.length > 0 && <Disclosure summary="Cookies" count={third.cookies.length}>
        <ul className="wo-dr-list">{third.cookies.map(cookie => <li key={`${cookie.domain}:${cookie.name}`}><code>{cookie.name}</code> {cookie.domain}, {cookie.firstParty ? 'first party' : 'third party'}{cookie.secure ? ', Secure' : ''}{cookie.sameSite ? `, SameSite ${cookie.sameSite}` : ''}</li>)}</ul>
      </Disclosure>}
    </Section>
  </>;
};
