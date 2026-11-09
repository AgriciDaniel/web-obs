// Deterministic draft walkthrough: manifest in, walkthrough out. No AI and no network.
// The catalog below is the plain-English translation layer: it turns engine findings into client-facing stories.
// Every figure is a {{binding}} resolved from the capture; every judgement is labelled INFER with its basis.
import type { SiteGraphManifest } from '../types/site';
import {
  type Claim, type Ctx, type Issue, type Label, type Level, type Owner, type Ref, type Scene, type Size, type Stop, type Walkthrough,
  countOf, horizonFor, makeCtx, nodesAffected, resolvePath,
} from './core';

// Units for counting each finding, so prose reads "1 page" / "19 pages" and not "1 pages".
const UNIT: Record<string, string> = {
  'link-fix-broken': 'link,links', 'link-fix-redirect': 'link,links', 'link-fix-non-canonical': 'link,links',
  'dup-content-near': 'match,matches', 'dup-content-exact': 'group,groups', 'dup-title': 'group,groups', 'dup-h1': 'group,groups', 'dup-description': 'group,groups',
  'schema-missing-recommended': 'gap,gaps', 'schema-missing-required': 'gap,gaps', 'schema-content-mismatch': 'mismatch,mismatches', 'schema-headline-differs': 'mismatch,mismatches',
  'image-oversized': 'image,images', 'image-legacy-format': 'image,images', 'link-opportunity': 'opportunity,opportunities',
  'anchor-multiple-targets': 'anchor,anchors', 'crawl-traps': 'pattern,patterns', 'robots-syntax': 'note,notes',
};
const unit = (id: string) => UNIT[id.replace(/^seo:/, '')] ?? 'page,pages';

interface Story {
  id: string;
  title: string;
  scope: Issue['scope'];
  owner: Owner;
  effort: { size: Size; basis: string };
  /** Findings that belong to this story (plain ids or seo:-prefixed slugs). */
  ids: string[];
  /** The story is only told when at least one of these exists (defaults to `ids`). */
  anyOf?: string[];
  severity: (k: K) => { level: Level; basis: string };
  saw: (k: K) => Claim[];
  why: Array<{ text: string; basis: string }>;
  caveat?: string;
  fix: string[];
  verify: string;
  ask?: string[];
  example?: string;
}

/** Helpers a story uses to look at the capture. */
interface K {
  c: Ctx;
  /** Real finding id for a slug, accepting both "slug" and "seo:slug". */
  id: (slug: string) => string | null;
  has: (slug: string) => boolean;
  /** Binding for a finding's count with a unit noun. */
  n: (slug: string) => string;
  fc: (slug: string, text: (n: string) => string, label?: Label, extra?: Ref[]) => Claim[];
  path: (p: string) => unknown;
}

// Plural verb -> singular form, so "1 page has" and "19 pages have" both read correctly.
const VERB_SINGULAR: Record<string, string> = {
  have: 'has', point: 'points', load: 'loads', contain: 'contains', share: 'shares', cannot: 'cannot', ask: 'asks', name: 'names', are: 'is',
  could: 'could', use: 'uses', show: 'shows', delay: 'delays', skip: 'skips', returned: 'returned', do: 'does', link: 'links', were: 'was',
  return: 'returns', redirect: 'redirects', display: 'displays', lack: 'lacks', need: 'needs',
};
function agree(text: string, countBinding: string, id: string): string {
  const at = text.indexOf(countBinding + ' ');
  if (at < 0) return text;
  const rest = text.slice(at + countBinding.length + 1);
  const word = /^[a-z]+/.exec(rest)?.[0];
  if (!word || !(word in VERB_SINGULAR)) return text;
  return text.slice(0, at + countBinding.length + 1) + `{{f:${id}#count|v=${VERB_SINGULAR[word]},${word}}}` + rest.slice(word.length);
}

function makeK(c: Ctx): K {
  const id = (slug: string) => (c.F.has(slug) ? slug : c.F.has(`seo:${slug}`) ? `seo:${slug}` : null);
  return {
    c, id, has: (s) => id(s) !== null && countOf(c, id(s)!) > 0,
    n: (s) => { const real = id(s) ?? s; return `{{f:${real}#count|pl=${unit(real)}}}`; },
    fc: (s, text, label = 'FETCH', extra = []) => {
      const real = id(s);
      if (!real || countOf(c, real) === 0) return [];
      const binding = `{{f:${real}#count|pl=${unit(real)}}}`;
      return [{ text: agree(text(binding), binding, real), label, refs: [{ finding: real }, ...extra] }];
    },
    path: (p) => resolvePath(c.m, p),
  };
}

const sampleLab = 'siteIntel.browserAudit.pages[*].lab';

const STORIES: Story[] = [
  {
    id: 'slow-first-paint', title: 'Your pages are slow to show their main content', scope: 'sitewide', owner: 'developer',
    effort: { size: 'M', basis: 'Needs a waterfall analysis first; fixes are usually theme, image and script changes rather than a rebuild.' },
    ids: ['slow-lab-lcp', 'third-party-before-interaction', 'render-blocking-resources', 'no-compression'], anyOf: ['slow-lab-lcp'],
    severity: () => ({ level: 'high', basis: 'The sampled pages were slower than the audit\'s slow-load threshold, and speed affects every page a visitor opens.' }),
    saw: (k) => {
      const out: Claim[] = [];
      const lcp = k.path(`${sampleLab}.lcpMs`) as number[] | undefined;
      if (lcp?.length) out.push({
        text: `In our test load, the main content took between {{m:${sampleLab}.lcpMs|min|sec1}} and {{m:${sampleLab}.lcpMs|max|sec1}} seconds to appear across the {{m:siteIntel.browserAudit.pages|len|pl=page,pages}} we sampled.`,
        label: 'LAB', refs: [{ finding: k.id('slow-lab-lcp')! }, { path: `${sampleLab}.lcpMs` }],
      });
      const cls = k.path(`${sampleLab}.cls`) as number[] | undefined;
      if (cls?.length && Math.max(...cls) > 0.1) out.push({
        text: `The layout also jumped around while loading; the worst shift score was {{m:${sampleLab}.cls|max|round2}}.`,
        label: 'LAB', refs: [{ path: `${sampleLab}.cls` }],
      });
      out.push(...k.fc('third-party-before-interaction', (n) => `Third-party services were contacted before any interaction on ${n} we sampled, which adds to load time.`, 'LAB'));
      out.push(...k.fc('render-blocking-resources', (n) => `${n} load scripts or styles that hold up the first paint.`));
      return out;
    },
    why: [{ text: 'Visitors who wait for a page to settle are more likely to leave before reading the offer, and the delay affects every service page the same way.', basis: 'General web-performance practice. No analytics data was supplied, so the size of the effect on this business is not demonstrated.' }],
    caveat: 'Measured in one lab load on one computer through the capture proxy. Confirm with real-visitor (field) data before committing budget.',
    fix: ['Pull real-visitor speed data (Search Console, CrUX) so the starting point is not a single lab run.', 'Run a waterfall on the homepage to find the largest element and what delays it.', 'Defer or remove scripts that load before the visitor does anything.'],
    verify: 'Recapture. Lab load times on the sampled pages drop and field data agrees.', example: 'slow-lab-lcp',
    ask: ['Ask whether they have ever timed the site on a phone.'],
  },
  {
    id: 'security-gaps', title: 'Your site\'s security settings have gaps', scope: 'sitewide', owner: 'hosting',
    effort: { size: 'S', basis: 'Response-header rules can usually be set in one place at the CDN or host.' },
    ids: ['hsts-weak', 'csp-weak', 'header-hygiene', 'cookie-flags', 'tls-expiring', 'tls-not-verified', 'tls-old-version', 'tls-alternate-host', 'links-to-http', 'mixed-content', 'securitytxt-expiry'],
    anyOf: ['hsts-weak', 'csp-weak', 'header-hygiene', 'cookie-flags', 'tls-expiring', 'tls-not-verified', 'tls-old-version', 'tls-alternate-host', 'links-to-http', 'mixed-content'],
    severity: (k) => k.has('tls-not-verified') || k.has('tls-expiring') ? { level: 'high', basis: 'A certificate problem is visible to every visitor as a browser warning.' } : { level: 'medium', basis: 'Credibility issue that is visible with free scanning tools. No direct ranking claim is made.' },
    saw: (k) => {
      const out: Claim[] = [];
      const missing = k.path('siteIntel.techStack.securityHeaders.missing') as string[] | undefined;
      if (missing?.length) out.push({ text: `{{m:siteIntel.techStack.securityHeaders.missing|len|pl=standard browser protection was,standard browser protections were}} not sent by the homepage: {{m:siteIntel.techStack.securityHeaders.missing|join}}.`, label: 'FETCH', refs: [{ path: 'siteIntel.techStack.securityHeaders.missing' }] });
      const cdn = k.path('siteIntel.techStack.hostingAndCdn') as string[] | undefined;
      if (missing?.length && cdn?.length) out.push({ text: 'The site is served through {{m:siteIntel.techStack.hostingAndCdn|join}}.', label: 'FETCH', refs: [{ path: 'siteIntel.techStack.hostingAndCdn' }] });
      out.push(...k.fc('tls-expiring', () => 'The site\'s security certificate is close to expiring: {{m:siteIntel.transport.tls.daysRemaining|pl=day,days}} left.', 'FETCH', [{ path: 'siteIntel.transport.tls.daysRemaining' }]));
      out.push(...k.fc('links-to-http', (n) => `${n} link to plain http:// addresses from secure pages.`));
      out.push(...k.fc('mixed-content', (n) => `${n} load some resources over plain http://.`));
      out.push(...k.fc('hsts-weak', () => 'The HSTS policy is weak or incomplete.'));
      out.push(...k.fc('csp-weak', () => 'The Content Security Policy has gaps.'));
      out.push(...k.fc('cookie-flags', () => 'Some cookies are missing standard protection flags.'));
      return out;
    },
    why: [{ text: 'Prospects evaluating a business can see these gaps with free tools, and they weaken the site\'s own trust story.', basis: 'Common due-diligence practice; the effect on this business is not measured here.' }],
    caveat: 'Header observations cover the homepage response only, and may be set by a CDN rather than the website itself.',
    fix: ['Add the missing headers with a CDN or host response-header rule, starting with the least disruptive ones.', 'Introduce a Content Security Policy in report-only mode first so nothing breaks.', 'Update links that still point at plain http:// addresses.'],
    verify: 'Recapture. The missing list is shorter or empty and the site still renders normally.', example: 'links-to-http',
    ask: ['Relate this to how they present their own security posture to clients.'],
  },
  {
    id: 'dead-links', title: 'Visitors and search engines run into dead or detoured links', scope: 'sitewide-template', owner: 'developer',
    effort: { size: 'S', basis: 'Usually a handful of link edits, often in one shared template.' },
    ids: ['link-fix-broken', 'link-fix-redirect', 'link-fix-non-canonical', 'page-broken'],
    severity: (k) => k.has('link-fix-broken') ? { level: 'high', basis: 'Links that lead nowhere interrupt a visitor at the moment they chose to act.' } : { level: 'medium', basis: 'Detoured links waste visitors\' time and search engines\' crawl effort.' },
    saw: (k) => [
      ...k.fc('link-fix-broken', (n) => `${n} point to a page that returns 404 or 410.`),
      ...k.fc('link-fix-redirect', (n) => `${n} point to a URL that redirects instead of the final address.`),
      ...k.fc('link-fix-non-canonical', (n) => `${n} point to a URL that is not the preferred one.`),
      ...k.fc('page-broken', (n) => `${n} returned 404 or 410 when requested.`),
    ],
    why: [{ text: 'A dead link is a dead end for the visitor, and repeated redirects slow every click that passes through them.', basis: 'General usability and crawl-efficiency practice.' }],
    fix: ['Fix or remove each broken link on the page that contains it.', 'Update redirected links to point straight at the final address.'],
    verify: 'Recapture. The broken and redirected link counts fall to zero.', example: 'link-fix-broken',
    ask: ['Check the example links in a normal browser before presenting.'],
  },
  {
    id: 'duplicate-and-hidden-pages', title: 'Duplicate and hard-to-reach pages compete with your real content', scope: 'section', owner: 'content',
    effort: { size: 'M', basis: 'A policy decision (keep, consolidate or noindex) followed by a template or plugin setting.' },
    ids: ['dup-content-exact', 'dup-content-near', 'cannibalization', 'orphan-page', 'weak-single-inlink', 'weak-no-body-links', 'weak-deep', 'conflict-noindex-heavily-linked'],
    anyOf: ['dup-content-exact', 'dup-content-near', 'cannibalization', 'orphan-page'],
    severity: () => ({ level: 'medium', basis: 'Large share of the captured site, but archive and duplicate pages are rarely the pages that win business.' }),
    saw: (k) => [
      ...k.fc('orphan-page', (n) => `${n} cannot be reached by following links from the homepage.`, 'FETCH', [{ path: 'stats.orphanPages' }]),
      ...k.fc('dup-content-near', (n) => `The audit found ${n} where two pages have almost identical text.`),
      ...k.fc('dup-content-exact', (n) => `The audit reports ${n} of pages with identical text.`),
      ...k.fc('cannibalization', (n) => `${n} share the same topic phrase, so they compete with each other instead of with other sites.`),
      ...k.fc('weak-single-inlink', (n) => `${n} have only one internal link pointing to them.`),
    ],
    why: [{ text: 'Search engines see many thin, repeated pages and have to guess which one to show, which dilutes the pages you actually want found.', basis: 'Standard duplicate-content reasoning. Impact on this site\'s rankings is not demonstrated (no search data supplied).' }],
    fix: ['Decide which archive and duplicate page types deserve to exist (category, tag, date, print versions).', 'Noindex or consolidate the rest, and stop linking to them from navigation.'],
    verify: 'Recapture. Orphan and near-duplicate counts fall and the remaining pages have distinct text.', example: 'orphan-page',
    ask: ['Show the map with only the unreachable pages highlighted.'],
  },
  {
    id: 'search-snippets', title: 'Your search-result snippets are left to chance', scope: 'page-specific', owner: 'marketing',
    effort: { size: 'S', basis: 'Copywriting plus a plugin field; no engineering.' },
    ids: ['missing-title', 'title-too-short', 'title-too-long', 'missing-meta-description', 'meta-description-too-long', 'missing-h1', 'missing-canonical', 'dup-title', 'dup-h1'],
    anyOf: ['missing-title', 'title-too-short', 'title-too-long', 'missing-meta-description', 'missing-h1', 'missing-canonical', 'dup-title'],
    severity: (k) => k.has('missing-title') || k.has('missing-h1') ? { level: 'medium', basis: 'Some pages have no title or main heading at all.' } : { level: 'low', basis: 'Cheap to fix and visible to prospects, but rarely decisive on its own.' },
    saw: (k) => [
      ...k.fc('missing-title', (n) => `${n} have no title.`),
      ...k.fc('missing-meta-description', (n) => `${n} have no meta description, so search engines write their own snippet.`),
      ...k.fc('title-too-short', (n) => `${n} have very short titles.`),
      ...k.fc('title-too-long', (n) => `${n} have titles long enough to be cut off in results.`),
      ...k.fc('missing-h1', (n) => `${n} have no main heading.`),
      ...k.fc('dup-title', (n) => `The same title is reused across ${n}.`),
      ...k.fc('missing-canonical', (n) => `${n} do not declare a preferred URL.`),
    ],
    why: [{ text: 'The snippet is the first thing a searcher reads about you; a written one can speak to the services you want to be hired for.', basis: 'General search-result presentation practice.' }],
    fix: ['Write a distinct title and description for each service page first, then the rest.', 'Set a canonical URL on every indexable page.'],
    verify: 'Recapture. The counts drop to zero for the service pages.', example: 'missing-meta-description',
    ask: ['Quick win: mostly copywriting.'],
  },
  {
    id: 'accessibility', title: 'Parts of the site are hard to use with assistive technology', scope: 'sitewide-template', owner: 'developer',
    effort: { size: 'M', basis: 'Most fixes are template-level, but they touch navigation, forms and colour.' },
    ids: ['links-without-text', 'form-inputs-without-label', 'buttons-without-name', 'images-missing-alt', 'heading-level-skip', 'a11y-color-contrast', 'a11y-link-name', 'a11y-link-in-text-block', 'a11y-label', 'a11y-select-name'],
    severity: (k) => k.has('a11y-color-contrast') ? { level: 'medium', basis: 'Automated testing found serious contrast failures on sampled pages.' } : { level: 'low', basis: 'Automated checks found issues, but their reach is limited to what those rules can see.' },
    saw: (k) => [
      ...k.fc('a11y-color-contrast', (n) => `Automated testing found text with too little colour contrast on ${n} we sampled.`, 'LAB'),
      ...k.fc('a11y-link-name', (n) => `Automated testing found links with no readable name on ${n} we sampled.`, 'LAB'),
      ...k.fc('links-without-text', (n) => `${n} contain links with no text or label.`),
      ...k.fc('form-inputs-without-label', (n) => `${n} have form fields without a label.`),
      ...k.fc('images-missing-alt', (n) => `${n} have images without alt text.`),
      ...k.fc('heading-level-skip', (n) => `${n} skip heading levels.`),
    ],
    why: [{ text: 'People using screen readers or low vision settings can be unable to complete forms or find contact links, which is also a legal and reputational exposure.', basis: 'General accessibility practice. Automated rules cover only part of WCAG, so conformance is not assessed.' }],
    caveat: 'Automated rules cover only part of the accessibility guidelines. A manual review is still needed before claiming conformance.',
    fix: ['Give every link, button and form field a clear accessible name.', 'Raise text contrast where the automated test flagged it.', 'Add alt text to meaningful images.'],
    verify: 'Recapture and re-run the automated accessibility rules on the same pages.', example: 'links-without-text',
  },
  {
    id: 'structured-data', title: 'Your structured data is incomplete', scope: 'sitewide', owner: 'developer',
    effort: { size: 'S', basis: 'Usually an SEO-plugin setting or a small template edit.' },
    ids: ['schema-missing-required', 'schema-missing-recommended', 'schema-content-mismatch', 'schema-headline-differs', 'invalid-jsonld'],
    severity: (k) => k.has('schema-missing-required') || k.has('invalid-jsonld') ? { level: 'medium', basis: 'Required properties are missing, which can make markup ineligible for rich results.' } : { level: 'low', basis: 'Only optional properties are missing; the markup still works.' },
    saw: (k) => [
      ...k.fc('invalid-jsonld', (n) => `${n} contain structured data that cannot be read.`),
      ...k.fc('schema-missing-required', (n) => `The audit found ${n} in required structured-data properties.`),
      ...k.fc('schema-content-mismatch', (n) => `The audit found ${n} between markup and visible content.`),
      ...k.fc('schema-missing-recommended', (n) => `The audit found ${n} in optional, recommended structured-data properties.`),
    ],
    why: [{ text: 'Complete markup helps search engines understand who you are and what you offer, and can make results richer.', basis: 'Based on published search-engine documentation; eligibility for a given rich result is not guaranteed.' }],
    fix: ['Fix invalid or incomplete markup first, then add the recommended properties on the homepage and main service pages.'],
    verify: 'Recapture. The structured-data gaps shrink and test pages pass the Rich Results Test.', example: 'schema-missing-recommended',
  },
  {
    id: 'indexing-signals', title: 'Some pages send mixed signals to search engines', scope: 'page-specific', owner: 'developer',
    effort: { size: 'S', basis: 'Individual tag or setting changes per page.' },
    ids: ['noindex', 'noindex-header', 'canonical-points-elsewhere', 'unlisted-in-sitemap', 'sitemap-limits', 'robots-syntax', 'conflict-noindex-heavily-linked'],
    severity: (k) => k.has('conflict-noindex-heavily-linked') ? { level: 'medium', basis: 'A page is both heavily linked and asking not to be indexed.' } : { level: 'low', basis: 'Each case may be intentional, so each needs a quick review.' },
    saw: (k) => [
      ...k.fc('noindex', (n) => `${n} ask search engines not to index them.`),
      ...k.fc('conflict-noindex-heavily-linked', (n) => `${n} are noindex but linked from many places.`),
      ...k.fc('canonical-points-elsewhere', (n) => `${n} name a different URL as their preferred version.`),
      ...k.fc('unlisted-in-sitemap', (n) => `${n} are reachable by links but missing from the sitemap.`),
      ...k.fc('robots-syntax', (n) => `The robots.txt file has ${n} about syntax.`),
    ],
    why: [{ text: 'When signals disagree, search engines choose for you, and the pages you care about may not be the ones shown.', basis: 'Search-engine documentation describes this behaviour; the effect on this site is not demonstrated.' }],
    fix: ['Review each page and decide whether it should be indexed.', 'Make the tags, sitemap and internal links agree with that decision.'],
    verify: 'Recapture. The conflicting-signal counts fall to zero.', example: 'noindex',
  },
  {
    id: 'stale-or-thin-content', title: 'Some content looks out of date or thin', scope: 'section', owner: 'content',
    effort: { size: 'M', basis: 'Each page needs an editorial decision.' },
    ids: ['stale-content', 'trust-pages-missing', 'thin-content'],
    severity: () => ({ level: 'low', basis: 'Quality signals matter over time, but no single page is critical.' }),
    saw: (k) => [
      ...k.fc('stale-content', (n) => `${n} show a date more than a year old.`),
      ...k.fc('thin-content', (n) => `${n} have very little body text.`),
      ...k.fc('trust-pages-missing', () => 'Standard trust pages (about, contact, privacy or terms) were not all found.'),
    ],
    why: [{ text: 'Old or thin pages can read as neglected and give visitors less reason to trust or contact you.', basis: 'General content-quality practice.' }],
    fix: ['Review each flagged page: refresh, merge or retire it.', 'Add any missing trust pages.'],
    verify: 'Recapture. Flagged pages show a recent date or no longer appear.', example: 'stale-content',
  },
  {
    id: 'image-weight', title: 'Images are heavier or less stable than they need to be', scope: 'sitewide', owner: 'content',
    effort: { size: 'S', basis: 'Compression and width/height attributes, often automated by a plugin.' },
    ids: ['image-oversized', 'image-legacy-format', 'images-missing-dimensions', 'first-image-lazy-loaded'],
    severity: () => ({ level: 'low', basis: 'Helps speed and layout stability, but is rarely the largest cause on its own.' }),
    saw: (k) => [
      ...k.fc('image-oversized', (n) => `${n} are larger than the recommended size.`),
      ...k.fc('image-legacy-format', (n) => `${n} could use a modern format.`),
      ...k.fc('images-missing-dimensions', (n) => `${n} have images without width and height set, which lets the layout jump.`),
      ...k.fc('first-image-lazy-loaded', (n) => `${n} delay their first image on purpose, which can slow the main content.`),
    ],
    why: [{ text: 'Lighter, properly sized images load faster and keep the page from shifting under the reader.', basis: 'General web-performance practice.' }],
    fix: ['Compress and resize oversized images.', 'Serve modern formats where the CMS supports them.', 'Set width and height on every image.'],
    verify: 'Recapture. Oversized image counts fall.', example: 'image-oversized',
  },
  {
    id: 'email-trust', title: 'Email authentication has gaps', scope: 'sitewide', owner: 'hosting',
    effort: { size: 'S', basis: 'DNS record changes, usually a short change window.' },
    ids: ['spf-missing', 'spf-weak', 'dmarc-missing', 'dmarc-weak', 'dkim-not-found', 'caa-missing'],
    severity: (k) => k.has('dmarc-missing') || k.has('spf-missing') ? { level: 'high', basis: 'Without these records, anyone can send mail that appears to come from your domain.' } : { level: 'medium', basis: 'Present but weak records give limited protection.' },
    saw: (k) => [
      ...k.fc('spf-missing', () => 'No SPF record was found for the domain.', 'FETCH'),
      ...k.fc('spf-weak', () => 'The SPF record is weak.', 'FETCH'),
      ...k.fc('dmarc-missing', () => 'No DMARC record was found for the domain.', 'FETCH'),
      ...k.fc('dmarc-weak', () => 'The DMARC policy does not yet enforce anything.', 'FETCH'),
      ...k.fc('dkim-not-found', () => 'No DKIM key was found at the common selectors we checked.', 'FETCH'),
    ],
    why: [{ text: 'Missing email authentication makes it easier to impersonate your domain and can send your real mail to spam.', basis: 'Standard email-security practice.' }],
    caveat: 'Only common DKIM selectors are checked, so an absent key is not proof that none exists.',
    fix: ['Publish SPF and DMARC records, starting DMARC in monitoring mode.', 'Confirm DKIM with your mail provider.'],
    verify: 'Recapture with the email DNS check on; the records are found.',
  },
  {
    id: 'internal-linking', title: 'Internal links leave opportunities on the table', scope: 'section', owner: 'content',
    effort: { size: 'S', basis: 'Adding links inside existing copy.' },
    ids: ['link-opportunity', 'anchor-multiple-targets', 'generic-anchor-text', 'weak-nofollow-internal'],
    severity: () => ({ level: 'low', basis: 'A steady, low-cost improvement rather than a defect.' }),
    saw: (k) => [
      ...k.fc('link-opportunity', (n) => `The audit found ${n} where a page mentions another page but does not link to it.`),
      ...k.fc('anchor-multiple-targets', (n) => `The audit found ${n} used to link to different pages.`),
      ...k.fc('generic-anchor-text', (n) => `${n} use link text such as "click here".`),
    ],
    why: [{ text: 'Clear internal links guide visitors and search engines to the pages that matter.', basis: 'General internal-linking practice.' }],
    fix: ['Add the suggested links where the text already mentions the target.', 'Replace generic link text with descriptive text.'],
    verify: 'Recapture. The opportunity counts fall.', example: 'link-opportunity',
  },
];

// ---------------------------------------------------------------------------
// Draft
// ---------------------------------------------------------------------------
const SEV_WEIGHT: Record<Level, number> = { high: 3, medium: 2, low: 1 };

/** A "broken link" reported for a single URL under /cdn-cgi/ is Cloudflare's email-address obfuscation, not a real dead link. */
function detectFalsePositive(c: Ctx, story: Story): { note: string } | null {
  if (story.id !== 'dead-links') return null;
  const f = c.F.get('link-fix-broken');
  if (!f) return null;
  const urls = new Set((f.targets as Array<{ url?: string }>).map((t) => t.url ?? ''));
  const only = [...urls];
  if (only.length === 1 && /\/cdn-cgi\//.test(only[0])) {
    return { note: `Every broken-link report points at one URL under /cdn-cgi/. That path is a CDN feature (for example email-address protection) that browsers normally resolve. It is probably not broken for real visitors. Open it in a normal browser before presenting.` };
  }
  return null;
}

function mapStops(c: Ctx): Stop[] {
  const m = c.m;
  const stops: Stop[] = [{
    view: 'globe', focus: {},
    caption: { text: 'We mapped {{m:stats.pagesCrawled|pl=page,pages}} of your site and {{m:stats.externalDomains|pl=outside website,outside websites}} it links to.', label: 'FETCH', refs: [{ path: 'stats.pagesCrawled' }, { path: 'stats.externalDomains' }] },
    talk: ['Let them find their own homepage in the centre first.'],
  }];
  const orphan = countOf(c, 'seo:orphan-page');
  if (orphan > 0 && m.nodes.some((n) => n.health === 'orphan')) stops.push({
    view: 'globe', focus: { health: 'orphan', filter: 'orphans' },
    caption: { text: 'These {{m:stats.orphanPages|pl=page,pages}} sit apart from the rest: no link path from your homepage reaches them.', label: 'FETCH', refs: [{ finding: 'seo:orphan-page' }] },
    talk: ['Do not call them bad pages yet. Ask what they think these are.'],
  });
  if (m.nodes.some((n) => n.health === 'broken')) stops.push({
    view: 'globe', focus: { health: 'broken', filter: 'issues' },
    caption: { text: '{{m:stats.brokenOrRedirectPages|pl=page,pages}} returned an error or a redirect when we asked for it.', label: 'FETCH', refs: [{ path: 'stats.brokenOrRedirectPages' }] },
  });
  if (m.nodes.length > 8) stops.push({
    view: 'clusters', focus: {},
    caption: { text: 'The same {{m:stats.pagesCrawled|pl=page,pages}}, grouped by how closely they link to one another: tightly linked pages sit together and loosely linked ones drift apart.', label: 'FETCH', refs: [{ path: 'stats.pagesCrawled' }] },
    talk: ['Show that the structure is real: ask which group they would expect their best pages to be in.'],
  });
  const depths = m.nodes.map((n) => n.clickDepth).filter((d): d is number => typeof d === 'number');
  if (depths.length) stops.push({
    view: 'road', focus: {},
    caption: { text: 'The deepest page is {{m:nodes[*].clickDepth|max|pl=click,clicks}} from the homepage.', label: 'FETCH', refs: [{ path: 'nodes[*].clickDepth' }] },
    talk: ['Lead with something neutral before the findings.'],
  });
  return stops;
}

export interface DraftOptions { generatedBy?: string; presenter?: string; preparedFor?: string }

export function buildDraft(m: SiteGraphManifest, manifestSha: string, opts: DraftOptions = {}): Walkthrough {
  const c = makeCtx(m);
  const k = makeK(c);
  const issues: Issue[] = [];
  const ranks = new Map<string, number>();

  for (const s of STORIES) {
    const anyOf = s.anyOf ?? s.ids;
    if (!anyOf.some((slug) => k.has(slug))) continue;
    const saw = s.saw(k);
    if (!saw.length) continue;
    const findings = s.ids.map((slug) => k.id(slug)).filter((x): x is string => x !== null && countOf(c, x) > 0);
    const sev = s.severity(k);
    const fp = detectFalsePositive(c, s);
    const issue: Issue = {
      id: s.id, title: s.title, scope: s.scope,
      disposition: fp ? 'needs-verification' : 'confirmed', ...(fp ? { dispositionNote: fp.note } : {}),
      findings, severity: sev, effort: s.effort, owner: s.owner,
      whatWeSaw: saw,
      whyItMatters: fp ? [] : s.why.map((w) => ({ text: w.text, label: 'INFER', basis: w.basis })),
      ...(s.caveat ? { caveat: s.caveat } : {}),
      fix: fp ? [] : s.fix, verify: fp ? 'Open the flagged link in a normal browser. If it works, mark this issue as a false positive.' : s.verify,
      ...(s.example && k.id(s.example) ? { exampleFinding: k.id(s.example)! } : {}),
      ...(s.ask ? { talk: s.ask } : {}),
    };
    // Priority level first, then distinct pages affected (not item counts: 190 near-duplicate matches are pairs, not 190 pages).
    // A site-wide issue touches every page. Held-back issues sink below everything.
    const pagesAffected = s.scope === 'sitewide' ? (m.stats?.pagesCrawled ?? m.nodes.length) : nodesAffected(m, c, findings).length;
    ranks.set(issue.id, SEV_WEIGHT[sev.level] * 100000 + Math.min(99999, pagesAffected) - (fp ? 1e9 : 0));
    // Home snapshot as the visual evidence when the capture has one.
    const home = m.nodes.find((n) => n.kind === 'home');
    if (home?.snapshot && ['slow-first-paint', 'search-snippets'].includes(issue.id)) issue.evidenceShots = [{ nodeId: home.id, kind: 'snapshot' }];
    issues.push(issue);
  }
  issues.sort((a, b) => (ranks.get(b.id) ?? 0) - (ranks.get(a.id) ?? 0));

  const confirmed = issues.filter((i) => i.disposition === 'confirmed');
  const headline = confirmed.slice(0, 5);
  const scenes: Scene[] = [];
  scenes.push({ id: 'cover', type: 'cover', title: 'Website health walkthrough', subtitle: 'What a visitor and a search engine can see on your site', talk: ['Frame this as a review of what is publicly visible, nothing more.', 'Mention the capture date up front so it is not mistaken for live monitoring.'] });

  const tiles = [
    { label: 'Pages mapped', value: '{{m:stats.pagesCrawled}}', path: 'stats.pagesCrawled' },
    { label: 'Outside websites linked', value: '{{m:stats.externalDomains}}', path: 'stats.externalDomains' },
    { label: 'Pages nobody links to', value: '{{m:stats.orphanPages}}', path: 'stats.orphanPages', skipIfZero: true },
    { label: 'Typical response time', value: '{{m:stats.medianResponseTimeMs}} ms', path: 'stats.medianResponseTimeMs' },
    { label: 'Individual items flagged', value: '{{m:stats.auditFindingItems}}', path: 'stats.auditFindingItems', note: 'Many are one cause repeated across pages.' },
    { label: 'Certificate days left', value: '{{m:siteIntel.transport.tls.daysRemaining}}', path: 'siteIntel.transport.tls.daysRemaining' },
  ].filter((t) => { const v = resolvePath(m, t.path); return typeof v === 'number' && !(t.skipIfZero && v === 0); }).slice(0, 6)
    .map(({ label, value, note }) => ({ label, value, ...(note ? { note } : {}) }));
  if (tiles.length >= 3) scenes.push({ id: 'glance', type: 'glance', title: 'Your site at a glance', tiles, talk: ['Let the numbers land; do not explain each one yet.'] });

  scenes.push({ id: 'map', type: 'map-tour', title: 'Your website as a map', stops: mapStops(c), talk: ['Invite them to point at pages they recognise.'] });
  for (const i of headline) scenes.push({ id: `issue-${i.id}`, type: 'issue', issueId: i.id });
  for (const i of issues.filter((x) => x.disposition !== 'confirmed')) scenes.push({ id: `issue-${i.id}`, type: 'issue', issueId: i.id, audience: 'presenter', talk: ['Presenter only: verify this before it goes in front of the client.'] });

  const d = m.drift as Record<string, unknown> | null | undefined;
  if (d?.hasChanges) {
    const claims: Claim[] = [];
    const added = (d.addedPagesCount as number) ?? 0;
    const titles = Array.isArray(d.titleChanges) ? d.titleChanges.length : 0;
    const hdr = Array.isArray((d.headerChanges as Record<string, unknown> | undefined)?.added) ? ((d.headerChanges as { added: unknown[] }).added.length) : 0;
    if (added > 0) claims.push({ text: '{{m:drift.addedPagesCount|pl=page was,pages were}} added since the previous capture.', label: 'FETCH', refs: [{ path: 'drift.addedPagesCount' }] });
    if (titles > 0) claims.push({ text: '{{m:drift.titleChanges|len|pl=page title was,page titles were}} rewritten since the previous capture.', label: 'FETCH', refs: [{ path: 'drift.titleChanges' }] });
    if (hdr > 0) claims.push({ text: '{{m:drift.headerChanges.added|len|pl=security header is,security headers are}} now present that were missing before: {{m:drift.headerChanges.added|join}}.', label: 'FETCH', refs: [{ path: 'drift.headerChanges.added' }] });
    if (claims.length) scenes.push({ id: 'wins', type: 'since-last-capture', title: 'What changed since the last capture', claims, talk: ['Credit the work already done before moving on to what remains.'] });
  }

  scenes.push({ id: 'inventory', type: 'inventory', title: 'Everything else we found', groupBy: 'category', talk: ['Do not read these out. Offer to cover them in the next session.'] });
  scenes.push({ id: 'roadmap', type: 'roadmap', title: 'A sensible order of work', items: confirmed.map((i) => ({ issueId: i.id, horizon: horizonFor(i) })), talk: ['Agree who owns each item before leaving this slide.'] });

  const limits: Claim[] = [
    { text: 'Real-visitor speed (field data) was not measured; speed figures come from a lab load.', label: 'SCOPE', refs: [] },
  ];
  // Only when browser tests really sampled pages: an empty list (the browser step was skipped) has nothing to cite.
  const sampledPages = resolvePath(m, 'siteIntel.browserAudit.pages');
  if (Array.isArray(sampledPages) && sampledPages.length > 0) limits.push({ text: 'Browser tests covered {{m:siteIntel.browserAudit.pages|len|pl=sampled page,sampled pages}}, not the whole site.', label: 'SCOPE', refs: [{ path: 'siteIntel.browserAudit.pages' }] });
  if (resolvePath(m, 'siteIntel.transport.emailDns.state') === 'skipped') limits.push({ text: 'Email authentication (SPF, DMARC, DKIM) was not checked in this capture.', label: 'SCOPE', refs: [{ path: 'siteIntel.transport.emailDns.state', equals: 'skipped' }] });
  limits.push({ text: 'Security headers were read from the homepage response only.', label: 'SCOPE', refs: [] });
  limits.push({ text: 'Rankings, traffic and conversions are not part of this data. No search or analytics account was connected.', label: 'SCOPE', refs: [] });
  limits.push({ text: 'Automated accessibility rules cover only part of the guidelines; a manual review is still needed.', label: 'SCOPE', refs: [] });
  if (m.captureStatus === 'partial') limits.unshift({ text: 'This capture was partial, so some pages are missing from the figures.', label: 'SCOPE', refs: [{ path: 'captureStatus', equals: 'partial' }] });
  scenes.push({ id: 'limits', type: 'limits', title: 'What this review does not cover', claims: limits, talk: ['Position the gaps as the next conversation, not as weaknesses of this review.'] });
  scenes.push({ id: 'next', type: 'next-steps', title: 'Where we go from here', claims: [
    { text: 'Agree an owner for each first-month item.', label: 'SCOPE', refs: [] },
    { text: 'Set a date to recapture the site so progress is measured, not assumed. The report compares captures automatically.', label: 'SCOPE', refs: [] },
  ], talk: ['Ask for a decision, not feedback.'] });

  return {
    walkthroughVersion: '0.2',
    source: { siteId: m.siteId, capturedAt: m.capturedAt, manifestSha256: manifestSha },
    authoring: { generatedBy: opts.generatedBy ?? 'Web-Obs report draft generator (rule-based)', skills: [], reviewState: 'draft', reviewedBy: null },
    brand: { name: m.brandName || m.domain, accent: { hex: null, approvedBy: null }, ...(opts.presenter ? { presenter: opts.presenter } : {}), ...(opts.preparedFor ? { preparedFor: opts.preparedFor } : {}) },
    issues, scenes,
  };
}
