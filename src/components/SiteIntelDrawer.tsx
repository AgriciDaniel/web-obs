import React from 'react';
import { ExternalLink, FileText, Globe, Mail, Phone, X } from 'lucide-react';
import type { SiteGraphManifest } from '../types/site';
import { aiCrawlerRows } from '../data/aiCrawlers';
import { pendingLinkChecks } from '../data/linkCoverage';
import { captureDate } from '../data/sitePresentation';
import { DiscoveryFilesList, SiteHealthList } from './DiscoveryPanel';
import { TransportSections, transportNotes } from './IntelAuditCards';
import { Disclosure, EmptyState, KeyValueList, SegmentedBar, Section, StatRow, StatTile, StatusPill, Tabs, formatCount, type KeyValue } from './ui';
import '../styles/drawers.css';

interface SiteIntelDrawerProps {
  manifest: SiteGraphManifest;
  isPreview: boolean;
  onClose: () => void;
  onContinueLinks?: () => void;
  onOpenNote: (obsidianPath: string) => void;
  onOpenExternalUrl: (url: string) => void;
}

const listOr = (values: string[], empty: string) => values.length ? values.join(', ') : empty;
const shortUrl = (url: string) => url.replace(/^https?:\/\/(www\.)?/i, '').replace(/\/$/, '');

function HealthTab({ manifest, isPreview, onContinueLinks, onOpenNote }: SiteIntelDrawerProps) {
  const intel = manifest.siteIntel;
  const responseMs = intel?.avgResponseTimeMs ?? manifest.stats.avgResponseTimeMs;
  const links = manifest.linkHealth;
  const pending = links ? pendingLinkChecks(links) : 0;
  const resources = manifest.resources;
  const byStatus = (status: string) => links?.results.filter((row) => row.status === status).length ?? 0;
  const broken = links?.brokenLinks.length ?? 0;
  return <>
    <StatRow label="Key numbers">
      <StatTile label="Pages" value={formatCount(manifest.stats.pagesCrawled)} />
      <StatTile label="Avg request" value={responseMs !== undefined && responseMs > 0 ? `${formatCount(responseMs)} ms` : 'No data'} />
      <StatTile label="Broken links" value={links ? formatCount(broken) : 'No data'} status={broken > 0 ? 'critical' : undefined} />
      <StatTile label="Local assets" value={formatCount(manifest.stats.localImagesDownloaded)} hint={intel?.totalAssetsMb ? `${intel.totalAssetsMb} MB` : undefined} />
    </StatRow>

    <Section title="Site health" aside="Status per area">
      <SiteHealthList manifest={manifest} />
    </Section>

    {links && <Section title="Link checks" aside={`${formatCount(links.totalCount)} targets`}>
      <p className="wo-dr-line">{links.checkedCount} of {links.totalCount} observed targets attempted. {links.brokenLinks.length} returned 404/410; {links.serverErrors.length} returned server errors.</p>
      <SegmentedBar thin label="Link check results" parts={[
        { id: 'ok', label: 'OK', value: byStatus('ok'), status: 'good' },
        { id: 'broken', label: 'Broken', value: byStatus('broken'), status: 'critical' },
        { id: 'server', label: 'Server error', value: byStatus('server-error'), status: 'warning' },
        { id: 'unknown', label: 'Inconclusive', value: byStatus('unknown'), status: 'neutral' },
        { id: 'unchecked', label: 'Unchecked', value: byStatus('unchecked'), color: 'var(--border-hairline)' },
      ]} />
      <div className="wo-dr-actions">
        <button type="button" className="wo-btn-secondary wo-btn-xs" onClick={() => onOpenNote(`sites/${manifest.siteId}/_link-health.md`)}>Open link report</button>
        {!isPreview && pending > 0 && onContinueLinks && <button type="button" className="wo-btn-secondary wo-btn-xs" onClick={onContinueLinks}>Check remaining {pending} targets</button>}
      </div>
    </Section>}

    {resources && <Section title="Media and resources" aside={`${formatCount(resources.length)} observed`}>
      <p className="wo-dr-line">{resources.filter((r) => r.localPath).length} saved locally. {resources.filter((r) => r.type === 'audio').length} audio · {resources.filter((r) => r.type === 'video').length} video · {resources.filter((r) => r.type === 'transcript').length} caption or transcript files.</p>
      <div className="wo-dr-actions">
        <button type="button" className="wo-btn-secondary wo-btn-xs" onClick={() => onOpenNote(`sites/${manifest.siteId}/_resources.md`)}>Open media inventory</button>
      </div>
    </Section>}
  </>;
}

function FilesTab({ manifest }: { manifest: SiteGraphManifest }) {
  const ai = manifest.siteIntel?.aiReadiness;
  const hygiene = ai?.sitemapHygiene;
  const hygieneParts = hygiene ? [
    hygiene.broken.length && `${hygiene.broken.length} broken`,
    hygiene.unavailable.length && `${hygiene.unavailable.length} unavailable`,
    hygiene.redirect.length && `${hygiene.redirect.length} redirected`,
    hygiene.noindex.length && `${hygiene.noindex.length} noindex`,
    hygiene.undeclaredSitemaps.length && `${hygiene.undeclaredSitemaps.length} not in robots.txt`,
    hygiene.redirectChains?.length && `${hygiene.redirectChains.length} redirect chains`,
    hygiene.lastmodMismatch?.length && `${hygiene.lastmodMismatch.length} lastmod mismatches`,
    hygiene.hreflangNonReciprocal?.length && `${hygiene.hreflangNonReciprocal.length} hreflang not reciprocal`,
  ].filter(Boolean) as string[] : [];
  const crawlerRows: KeyValue[] = ai ? [
    ...aiCrawlerRows(ai),
    ...(hygiene ? [{ label: 'Sitemap URLs', value: hygieneParts.length ? hygieneParts.join(', ') : 'No issues found', status: hygieneParts.length ? 'warning' as const : 'good' as const }] : []),
  ] : [];
  return <>
    <Section title="Discovery files" aside="Problems first">
      <DiscoveryFilesList manifest={manifest} />
    </Section>
    {ai && <Section title="Crawlers and sitemaps"><KeyValueList rows={crawlerRows} /></Section>}
  </>;
}

function TechTab({ manifest }: { manifest: SiteGraphManifest }) {
  const tech = manifest.siteIntel?.techStack;
  if (!tech && !manifest.siteIntel?.transport) return <EmptyState>No technology data in this capture.</EmptyState>;
  const ids = tech ? [...(tech.measurementIds.ga4 ?? []), ...(tech.measurementIds.gtm ?? []), ...(tech.measurementIds.googleAds ?? [])] : [];
  const verification = tech ? [tech.searchConsoleVerifiedMeta && 'Google Search Console', tech.bingVerifiedMeta && 'Bing Webmaster'].filter(Boolean) as string[] : [];
  const sec = tech?.securityHeaders;
  const inconsistent = sec?.consistency?.inconsistent ?? [];
  return <>
    {tech && <Section title="Stack and edge">
      <KeyValueList rows={[
        { label: 'CMS or framework', value: listOr(tech.cmsOrFramework, 'Static or custom') },
        { label: 'Hosting and CDN', value: listOr(tech.hostingAndCdn, 'Not identified') },
      ]} />
    </Section>}
    {tech && <Section title="Analytics and pixels">
      <KeyValueList rows={[
        { label: 'Trackers', value: listOr(tech.analyticsAndPixels.map((item) => item.name), 'None detected') },
        ...(ids.length ? [{ label: 'Measurement IDs', value: <span className="wo-dr-mono">{ids.join(', ')}</span> }] : []),
        { label: 'Verification tags', value: listOr(verification, 'None') },
      ]} />
    </Section>}
    {sec && <Section title="Security headers" aside="Homepage">
      <KeyValueList rows={[
        { label: 'Present', value: `${sec.present.length} of 6`, status: sec.missing.length > 3 ? 'critical' : sec.missing.length > 0 ? 'warning' : 'good' },
        ...(sec.missing.length ? [{ label: 'Missing', value: sec.missing.join(', ') }] : []),
        ...(inconsistent.length ? [{ label: `Inconsistent on ${sec.consistency!.sampledPages} pages`, value: inconsistent.join(', ') }] : []),
      ]} />
    </Section>}
    <TransportSections manifest={manifest} />
  </>;
}

function BrandTab({ manifest, onOpenExternalUrl }: { manifest: SiteGraphManifest; onOpenExternalUrl: (url: string) => void }) {
  const contacts = manifest.siteIntel?.contacts;
  const funnel = manifest.siteIntel?.funnel;
  const fonts = manifest.brandKit?.typography?.primaryFamilies ?? [];
  const palette = (manifest.brandKit?.palette ?? []) as Array<{ hex?: string; occurrences?: number }>;
  const swatches = palette.filter((c) => typeof c.hex === 'string' && /^#[0-9a-f]{3,8}$/i.test(c.hex)).slice(0, 8);
  const hasContacts = Boolean(contacts && (contacts.emails.length > 0 || contacts.phones.length > 0));
  const socials = contacts?.socialProfiles ?? [];
  const socialButton = (url: string) => <button key={url} type="button" className="wo-dr-link" onClick={() => onOpenExternalUrl(url)} title={url}>
    <Globe size={13} aria-hidden="true" /><span>{shortUrl(url)}</span>
  </button>;
  if (!hasContacts && !socials.length && !funnel && !fonts.length && !swatches.length) return <EmptyState>No brand or contact data in this capture.</EmptyState>;
  return <>
    {hasContacts && <Section title="Published contacts">
      <ul className="wo-dr-contacts">
        {contacts!.emails.map((email) => <li key={email}><Mail size={13} aria-hidden="true" /><span>{email}</span></li>)}
        {contacts!.phones.map((phone) => <li key={phone}><Phone size={13} aria-hidden="true" /><span>{phone}</span></li>)}
      </ul>
    </Section>}
    {socials.length > 0 && <Section title="Social profiles" aside={formatCount(socials.length)}>
      <div className="wo-dr-links">{socials.slice(0, 6).map(socialButton)}</div>
      {socials.length > 6 && <Disclosure summary="More profiles" count={socials.length - 6}>
        <div className="wo-dr-links">{socials.slice(6).map(socialButton)}</div>
      </Disclosure>}
    </Section>}
    {funnel && <Section title="Conversion and funnel">
      <div className="wo-dr-stat3"><StatRow label="Funnel elements">
        <StatTile label="Forms" value={formatCount(funnel.formsCount)} />
        <StatTile label="Videos" value={formatCount(funnel.videosCount)} />
        <StatTile label="Downloads" value={formatCount(funnel.downloadsCount)} />
      </StatRow></div>
      {funnel.platforms.length > 0 && <KeyValueList rows={funnel.platforms.map((p) => ({ label: p.platform, value: p.category }))} />}
    </Section>}
    {(fonts.length > 0 || swatches.length > 0) && <Section title="Fonts and colours">
      {fonts.length > 0 && <KeyValueList rows={[{ label: 'Font declarations', value: fonts.join(', ') }]} />}
      {swatches.length > 0 && <ul className="wo-dr-swatches" aria-label="Most used declared colours">
        {swatches.map((c) => <li key={c.hex} title={`${c.hex}${c.occurrences ? `, ${c.occurrences} declarations` : ''}`}>
          <i style={{ background: c.hex }} aria-hidden="true" /><span className="wo-dr-mono">{c.hex}</span>
        </li>)}
      </ul>}
    </Section>}
  </>;
}

export const SiteIntelDrawer: React.FC<SiteIntelDrawerProps> = (props) => {
  const { manifest, isPreview, onClose, onOpenNote, onOpenExternalUrl } = props;
  const intel = manifest.siteIntel;
  const tech = intel?.techStack;
  const ai = intel?.aiReadiness;
  const warnings = manifest.captureWarnings ?? [];
  const links = manifest.linkHealth;

  const notes: string[] = [
    'Public website signals. Tracking delivery and consent were not tested.',
    'Site health shows a status per area, not a combined score. Header checks cover the homepage only.',
  ];
  if (tech) notes.push(tech.coverage
    ? `Observed in ${tech.coverage.sampledPages} of ${tech.coverage.capturedHtmlPages} captured HTML pages. ${tech.coverage.selection}. Security headers: ${tech.coverage.securityHeadersScope}.`
    : 'Legacy capture: technology sample coverage was not recorded.');
  if (links) notes.push(`${links.uncheckedCount} link targets unchecked, ${links.unknownCount} inconclusive.${links.updatedAt ? ` Link checks updated ${captureDate(links.updatedAt)}. Page capture time is unchanged.` : ''}`);
  if (manifest.resources) notes.push('Media and resources are counted separately from HTML pages.');
  notes.push(...transportNotes(manifest));
  if (ai?.userTriggeredBots?.length) notes.push(`User-triggered fetchers (${ai.userTriggeredBots.join(', ')}) may ignore robots.txt, so a block is a request, not a guarantee.`);
  if (manifest.brandKit?.typography?.primaryFamilies?.length || manifest.brandKit?.palette?.length) notes.push('Font and colour evidence is in the website evidence package. Colour roles are inferred, not observed brand use.');
  if (manifest.captureProvenance) notes.push(`Capture engine ${manifest.captureProvenance.engineSha256.slice(0, 12)} · Python ${manifest.captureProvenance.runtime.pythonVersion}. Settings and source hashes are saved in the capture manifest.`);

  return (
    <aside className="wo-inspector wo-intel-drawer wo-dr" aria-label="Site Intelligence">
      <header className="wo-dr-head">
        <div className="wo-dr-head-text">
          <span className="wo-dr-kicker">Site Intelligence</span>
          <h2 className="wo-dr-title">{manifest.brandName || intel?.brandName || manifest.domain}</h2>
          <span className="wo-dr-sub"><span className="wo-dr-mono">{shortUrl(manifest.origin)}</span> · saved {captureDate(manifest.capturedAt)}</span>
        </div>
        <button type="button" className="wo-icon-btn wo-icon-btn-sm" onClick={onClose} title="Close Site Intelligence (Esc)" aria-label="Close Site Intelligence">
          <X size={15} />
        </button>
      </header>

      <div className="wo-dr-actions" role="group" aria-label="Site actions">
        {!isPreview && <button type="button" className="wo-btn-primary wo-btn-xs" onClick={() => onOpenNote(`sites/${manifest.siteId}/_dashboard.md`)}>
          <FileText size={13} aria-hidden="true" /><span>Dashboard note</span>
        </button>}
        <button type="button" className="wo-btn-secondary wo-btn-xs" onClick={() => onOpenExternalUrl(manifest.origin)} title={manifest.origin}>
          <ExternalLink size={13} aria-hidden="true" /><span>Visit site</span>
        </button>
      </div>

      {warnings.length > 0 && <div className="wo-dr-warning" role="status">
        <StatusPill status="warning" label={`${warnings.length} collection ${warnings.length === 1 ? 'warning' : 'warnings'}`} />
        <Disclosure summary="Show warnings"><ul className="wo-dr-list">{warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></Disclosure>
      </div>}

      <Tabs label="Site Intelligence sections" tabs={[
        { id: 'health', label: 'Health', content: <HealthTab {...props} /> },
        { id: 'files', label: 'Files', content: <FilesTab manifest={manifest} /> },
        { id: 'tech', label: 'Tech', content: <TechTab manifest={manifest} /> },
        { id: 'brand', label: 'Brand', content: <BrandTab manifest={manifest} onOpenExternalUrl={onOpenExternalUrl} /> },
      ]} />

      <div className="wo-dr-about">
        <Disclosure summary="About these numbers">
          <ul className="wo-dr-list">{notes.map((note) => <li key={note}>{note}</li>)}</ul>
        </Disclosure>
      </div>
    </aside>
  );
};
