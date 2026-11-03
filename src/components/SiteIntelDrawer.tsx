import React from 'react';
import {
  Activity,
  Bot,
  ExternalLink,
  FileText,
  Globe,
  Lock,
  Mail,
  Phone,
  Server,
  Target,
  X,
} from 'lucide-react';
import type { SiteGraphManifest } from '../types/site';
import { pendingLinkChecks } from '../data/linkCoverage';
import { DiscoveryPanel } from './DiscoveryPanel';
import { captureDate } from '../data/sitePresentation';

interface SiteIntelDrawerProps {
  manifest: SiteGraphManifest;
  isPreview: boolean;
  onClose: () => void;
  onContinueLinks?: () => void;
  onOpenNote: (obsidianPath: string) => void;
  onOpenExternalUrl: (url: string) => void;
}

export const SiteIntelDrawer: React.FC<SiteIntelDrawerProps> = ({
  manifest,
  isPreview,
  onClose,
  onContinueLinks,
  onOpenNote,
  onOpenExternalUrl,
}) => {
  const intel = manifest.siteIntel;
  const tech = intel?.techStack;
  const ai = intel?.aiReadiness;
  const funnel = intel?.funnel;
  const contacts = intel?.contacts;
  const responseMs = intel?.avgResponseTimeMs ?? manifest.stats.avgResponseTimeMs;

  const measurementBadges: string[] = [
    ...(tech?.measurementIds.ga4 ?? []),
    ...(tech?.measurementIds.gtm ?? []),
    ...(tech?.measurementIds.googleAds ?? []),
  ];

  return (
    <aside className="wo-inspector wo-intel-drawer" aria-label="Site Intelligence">
      <div className="wo-inspector-head">
        <div className="wo-inspector-badges">
          <span className="wo-badge wo-badge-home">Site Intelligence</span>

        </div>
        <button
          type="button"
          className="wo-icon-btn wo-icon-btn-sm"
          onClick={onClose}
          title="Close Site Intelligence (Esc)"
          aria-label="Close Site Intelligence"
        >
          <X size={15} />
        </button>
      </div>

      <h2 className="wo-inspector-title">
        {manifest.brandName || intel?.brandName || manifest.domain}
      </h2>
      <div className="wo-inspector-path">{manifest.origin}</div>
      <p className="wo-evidence-note">Saved {captureDate(manifest.capturedAt)}. Public website signals; tracking delivery and consent were not tested.</p>

      {manifest.captureProvenance && <p className="wo-evidence-note">Capture engine {manifest.captureProvenance.engineSha256.slice(0, 12)} · Python {manifest.captureProvenance.runtime.pythonVersion}. Settings and source hashes are saved in the capture manifest.</p>}
      {(manifest.captureWarnings?.length ?? 0) > 0 && <div className="wo-evidence-note" role="status">
        <strong>Collection and note warnings</strong>
        <ul>{manifest.captureWarnings?.map((warning, index) => <li key={index}>{warning}</li>)}</ul>
      </div>}

      <DiscoveryPanel manifest={manifest} />

      {manifest.linkHealth && <div className="wo-inspector-section">
        <div className="wo-section-title">Direct link and resource checks</div>
        <p className="wo-evidence-note">{manifest.linkHealth.checkedCount} of {manifest.linkHealth.totalCount} observed targets attempted. {manifest.linkHealth.uncheckedCount} unchecked, {manifest.linkHealth.unknownCount} inconclusive.</p>
        <p className="wo-evidence-note">{manifest.linkHealth.brokenLinks.length} returned 404/410; {manifest.linkHealth.serverErrors.length} returned server errors.</p>
        {manifest.linkHealth.updatedAt && <p className="wo-evidence-note">Link checks updated {captureDate(manifest.linkHealth.updatedAt)}. Page capture time is unchanged.</p>}
        <div className="wo-inspector-actions wo-link-check-actions">
        <button type="button" className="wo-btn-secondary" onClick={() => onOpenNote(`sites/${manifest.siteId}/_link-health.md`)}>Open link report</button>
        {!isPreview && pendingLinkChecks(manifest.linkHealth) > 0 && onContinueLinks && <button type="button" className="wo-btn-secondary" onClick={onContinueLinks}>Check remaining {pendingLinkChecks(manifest.linkHealth)} targets</button>}
        </div>
      </div>}
      {manifest.resources && <div className="wo-inspector-section">
        <div className="wo-section-title">Media and resources</div>
        <p className="wo-evidence-note">{manifest.resources.length} observed resources, separate from HTML pages. {manifest.resources.filter(resource => resource.localPath).length} saved locally.</p>
        <p className="wo-evidence-note">{manifest.resources.filter(resource => resource.type === 'audio').length} audio · {manifest.resources.filter(resource => resource.type === 'video').length} video · {manifest.resources.filter(resource => resource.type === 'transcript').length} caption or transcript files.</p>
        <button type="button" className="wo-btn-secondary" onClick={() => onOpenNote(`sites/${manifest.siteId}/_resources.md`)}>Open media inventory</button>
      </div>}
      {manifest.brandKit?.typography?.primaryFamilies && manifest.brandKit.typography.primaryFamilies.length > 0 && <p className="wo-evidence-note">Observed font declarations: {manifest.brandKit.typography.primaryFamilies.join(', ')}. Source evidence is in the website evidence package.</p>}

      <div className="wo-inspector-actions">
        {!isPreview && (
          <button
            type="button"
            className="wo-btn-primary"
            onClick={() => onOpenNote(`sites/${manifest.siteId}/_dashboard.md`)}
          >
            <FileText size={14} />
            <span>Dashboard Note</span>
          </button>
        )}
        <button
          type="button"
          className="wo-btn-secondary"
          onClick={() => onOpenExternalUrl(manifest.origin)}
        >
          <ExternalLink size={14} />
          <span>Visit Site</span>
        </button>
      </div>

      <div className="wo-metrics-grid">
        <div className="wo-metric-card">
          <span className="wo-metric-label">Pages Crawled</span>
          <span className="wo-metric-val">{manifest.stats.pagesCrawled}</span>
        </div>
        <div className="wo-metric-card">
          <span className="wo-metric-label" title="Average duration of each final page request. Redirect hops are not counted.">Avg page request time</span>
          <span className="wo-metric-val">
            {responseMs !== undefined && responseMs > 0 ? `${responseMs} ms` : 'No data'}
          </span>
        </div>
        <div className="wo-metric-card">
          <span className="wo-metric-label">Local Assets</span>
          <span className="wo-metric-val">
            {manifest.stats.localImagesDownloaded}
            {intel?.totalAssetsMb ? ` (${intel.totalAssetsMb} MB)` : ''}
          </span>
        </div>
        <div className="wo-metric-card">
          <span className="wo-metric-label">SEO Flagged Pages</span>
          <span className="wo-metric-val">
            {manifest.stats.pagesWithSeoIssues ?? 'No data'}
          </span>
        </div>
      </div>

      {/* Analytics, Pixels & Verification */}
      {tech && (
        <div className="wo-inspector-section">
          <div className="wo-section-title">
            <Activity size={11} className="wo-inline-sec-icon" /> Analytics & Pixels
          </div>
          <p className="wo-evidence-note">{tech.coverage ? `Observed in ${tech.coverage.sampledPages} of ${tech.coverage.capturedHtmlPages} captured HTML pages. ${tech.coverage.selection}. Security headers: ${tech.coverage.securityHeadersScope}.` : 'Legacy capture: technology sample coverage was not recorded.'}</p>
          {tech.analyticsAndPixels.length > 0 ? (
            <div className="wo-schema-row">
              {tech.analyticsAndPixels.map((item) => (
                <span key={item.name} className="wo-schema-chip wo-chip-accent">
                  {item.name}
                </span>
              ))}
            </div>
          ) : (
            <span className="wo-meta-key">No client-side analytics trackers detected in the sampled pages</span>
          )}

          {measurementBadges.length > 0 && (
            <div className="wo-schema-row">
              {measurementBadges.map((id) => (
                <span key={id} className="wo-schema-chip">
                  {id}
                </span>
              ))}
            </div>
          )}

          {(tech.searchConsoleVerifiedMeta || tech.bingVerifiedMeta) && (
            <div className="wo-meta-key">
              Verification tags observed:{' '}
              {[
                tech.searchConsoleVerifiedMeta ? 'Google Search Console' : '',
                tech.bingVerifiedMeta ? 'Bing Webmaster' : '',
              ]
                .filter(Boolean)
                .join(', ')}
            </div>
          )}
        </div>
      )}

      {/* Stack, CDN & Security Headers */}
      {tech && (
        <div className="wo-inspector-section">
          <div className="wo-section-title">
            <Server size={11} className="wo-inline-sec-icon" /> Tech Stack & Edge
          </div>
          <div className="wo-schema-row">
            {tech.cmsOrFramework.map((fw) => (
              <span key={fw} className="wo-schema-chip">
                {fw}
              </span>
            ))}
            {tech.hostingAndCdn.map((cdn) => (
              <span key={cdn} className="wo-schema-chip wo-chip-hub">
                {cdn}
              </span>
            ))}
            {tech.cmsOrFramework.length === 0 && tech.hostingAndCdn.length === 0 && (
              <span className="wo-meta-key">Static / Custom stack</span>
            )}
          </div>

          <div className="wo-meta-block">
            <span className="wo-meta-key">
              <Lock size={10} className="wo-inline-sec-icon" /> Security Headers (
              {tech.securityHeaders.present.length}/6)
            </span>
            {tech.securityHeaders.present.length > 0 && (
              <div className="wo-schema-row">
                {tech.securityHeaders.present.map((h) => (
                  <span key={h} className="wo-schema-chip wo-chip-hub">
                    {h}
                  </span>
                ))}
              </div>
            )}
            {tech.securityHeaders.missing.length > 0 && (
              <span className="wo-meta-key">
                Missing: {tech.securityHeaders.missing.join(', ')}
              </span>
            )}
            {tech.securityHeaders.consistency && tech.securityHeaders.consistency.inconsistent.length > 0 && (
              <span className="wo-meta-key">
                Inconsistent across {tech.securityHeaders.consistency.sampledPages} sampled pages: {tech.securityHeaders.consistency.inconsistent.join(', ')}
              </span>
            )}
            {tech.securityHeaders.consistency?.notes.map((note) => (
              <span key={note} className="wo-meta-key">{note}</span>
            ))}
          </div>
        </div>
      )}

      {/* AI Search / GEO Readiness */}
      {ai && (
        <div className="wo-inspector-section">
          <div className="wo-section-title">
            <Bot size={11} className="wo-inline-sec-icon" /> AI Discovery Signals
          </div>
          <div className="wo-schema-row">
            <span
              className={`wo-schema-chip ${
                ai.endpoints.llmsTxt ? 'wo-chip-hub' : ''
              }`}
            >
              llms.txt: {ai.endpoints.llmsTxt ? 'Observed' : 'Not observed'}
            </span>
            <span
              className={`wo-schema-chip ${
                ai.endpoints.llmsFullTxt ? 'wo-chip-hub' : ''
              }`}
            >
              llms-full.txt: {ai.endpoints.llmsFullTxt ? 'Observed' : 'Not observed'}
            </span>
            {(['llmsTxt', 'securityTxt'] as const).map((key) => {
              const v = ai.validation?.[key];
              if (!v) return null;
              return (
                <span key={key} className={`wo-schema-chip ${v.valid ? 'wo-chip-hub' : ''}`}>
                  {key === 'llmsTxt' ? 'llms.txt' : 'security.txt'}: {v.valid ? 'Valid' : `Check: ${v.issues.join(', ')}`}
                </span>
              );
            })}
            {ai.endpoints.apiCatalog !== undefined && (
              <span className={`wo-schema-chip ${ai.endpoints.apiCatalog ? 'wo-chip-hub' : ''}`}>
                api-catalog: {ai.endpoints.apiCatalog ? 'Observed' : 'Not observed'}
              </span>
            )}
            <span className="wo-schema-chip">
              Bots allowed at /: {ai.allowedAiBotsCount}/
              {Object.keys(ai.aiBotsPolicy).length}
            </span>
          </div>
          {ai.sitemapHygiene && (
            <span className="wo-meta-key">
              Sitemap hygiene:{' '}
              {(() => {
                const h = ai.sitemapHygiene;
                const parts = [
                  h.broken.length && `${h.broken.length} broken`,
                  h.unavailable.length && `${h.unavailable.length} unavailable`,
                  h.redirect.length && `${h.redirect.length} redirected`,
                  h.noindex.length && `${h.noindex.length} noindex`,
                  h.undeclaredSitemaps.length && `${h.undeclaredSitemaps.length} not declared in robots.txt`,
                  h.redirectChains?.length && `${h.redirectChains.length} redirect chains`,
                  h.lastmodMismatch?.length && `${h.lastmodMismatch.length} lastmod mismatches`,
                  h.hreflangNonReciprocal?.length && `${h.hreflangNonReciprocal.length} hreflang not reciprocal`,
                ].filter(Boolean);
                return parts.length ? parts.join(', ') : 'no issues found';
              })()}
            </span>
          )}
          {ai.userTriggeredBots && ai.userTriggeredBots.length > 0 && (
            <span className="wo-meta-key">
              User-triggered fetchers ({ai.userTriggeredBots.join(', ')}) may ignore robots.txt, so a block is a request, not a guarantee.
            </span>
          )}
          {ai.blockedAiBots.length > 0 && (
            <span className="wo-meta-key">
              Blocked in robots.txt: {ai.blockedAiBots.join(', ')}
            </span>
          )}
        </div>
      )}

      {/* Conversion & Funnel Signals */}
      {funnel && (
        <div className="wo-inspector-section">
          <div className="wo-section-title">
            <Target size={11} className="wo-inline-sec-icon" /> Conversion & Funnel
          </div>
          <div className="wo-schema-row">
            <span className="wo-schema-chip">Forms: {funnel.formsCount}</span>
            <span className="wo-schema-chip">Videos: {funnel.videosCount}</span>
            <span className="wo-schema-chip">Downloads: {funnel.downloadsCount}</span>
          </div>
          {funnel.platforms.length > 0 && (
            <div className="wo-schema-row">
              {funnel.platforms.map((p) => (
                <span key={p.platform} className="wo-schema-chip wo-chip-accent">
                  {p.platform} ({p.category})
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Contacts observed on captured website pages */}
      {(contacts &&
          (contacts.emails.length > 0 ||
            contacts.phones.length > 0 ||
            contacts.socialProfiles.length > 0)) && (
        <div className="wo-inspector-section">
          <div className="wo-section-title">Published Contacts</div>
          {contacts?.emails.map((em) => (
            <div key={em} className="wo-contact-line">
              <Mail size={12} />
              <span>{em}</span>
            </div>
          ))}
          {contacts?.phones.map((ph) => (
            <div key={ph} className="wo-contact-line">
              <Phone size={12} />
              <span>{ph}</span>
            </div>
          ))}
          {contacts && contacts.socialProfiles.length > 0 && (
            <div className="wo-ext-sample-list">
              {contacts.socialProfiles.slice(0, 8).map((sp) => (
                <button
                  key={sp}
                  type="button"
                  className="wo-link-row"
                  onClick={() => onOpenExternalUrl(sp)}
                >
                  <Globe size={12} className="wo-link-icon-ext" />
                  <span className="wo-link-row-main">
                    {sp.replace(/^https?:\/\/(www\.)?/i, '')}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </aside>
  );
};
