// Plain-language layer for GUIDED mode. Keyed by issue id (see STORIES in draft.ts).
// Rules (the package validator enforces the mechanical ones):
//  - No figures in prose: numbers come from the issue's own bound claims, never from here.
//  - No promises. `ifIgnored` is an opinion, so it carries a `basis`.
//  - Write for a business owner who has never opened a developer tool.

export interface PlainNote {
  /** One or two sentences, no jargon: what is going on. */
  inPlain: string;
  /** A familiar comparison that makes the idea stick. */
  picture?: string;
  /** What is likely to happen if nothing changes. An opinion, so it needs a basis. */
  ifIgnored: { text: string; basis: string };
  /** What the reader actually has to do or decide (not what the agency does). */
  yourPart: string;
  /** Questions the reader can take to their team or to the agency. */
  askYourTeam: string[];
  /** Glossary term ids used by this note. */
  terms: string[];
}

export interface GlossaryTerm { id: string; term: string; plain: string }

export const GLOSSARY: GlossaryTerm[] = [
  { id: 'capture', term: 'Capture', plain: 'A snapshot of your public website taken on one day. It shows what visitors and search engines could see then, not what is happening live.' },
  { id: 'lcp', term: 'Main-content load time', plain: 'How long a visitor waits before the biggest thing on the page (usually a headline or a photo) shows up. Developers call it LCP.' },
  { id: 'lab-test', term: 'Lab test', plain: 'A single timed page load on one computer. Useful for spotting problems, but real visitors on real phones can see better or worse.' },
  { id: 'field-data', term: 'Real-visitor data', plain: 'Speed measured from the devices of people who actually visited. It is the fairer measure, and it was not part of this review.' },
  { id: 'third-party', term: 'Third-party service', plain: 'A tool on your pages that comes from another company, such as chat widgets, ad trackers or font libraries. Each one is an extra thing the page must wait for.' },
  { id: 'headers', term: 'Security headers', plain: 'Short instructions your site hands to every browser about how to stay safe, for example "only talk to me over a secure connection".' },
  { id: 'cdn', term: 'CDN', plain: 'A network of servers that sits in front of your site and delivers it faster. It is also a convenient single place to switch on security rules.' },
  { id: 'certificate', term: 'Security certificate', plain: 'The digital ID that lets a browser show the padlock. If it expires, visitors see a full-page warning.' },
  { id: 'broken-link', term: 'Broken link', plain: 'A link that leads to a page that no longer exists. Visitors see an error and search engines see a dead end.' },
  { id: 'redirect', term: 'Redirect', plain: 'A forwarding instruction: "this page moved, go over there." A few are normal; long chains slow people down.' },
  { id: 'orphan', term: 'Orphan page', plain: 'A page that exists but that nothing else on your site links to, so visitors and search engines have no path to it.' },
  { id: 'duplicate', term: 'Duplicate content', plain: 'Two or more pages that say nearly the same thing. Search engines have to guess which one to show.' },
  { id: 'title-meta', term: 'Page title and description', plain: 'The headline and two-line summary shown for your page in search results. If you do not write them, Google writes them for you.' },
  { id: 'schema', term: 'Structured data', plain: 'Hidden labels in a page that tell search engines exactly what it is: a business, an address, a service, an FAQ.' },
  { id: 'canonical', term: 'Canonical address', plain: 'The one official web address for a page, used when the same page can be reached several ways.' },
  { id: 'alt-text', term: 'Alt text', plain: 'A short written description of an image. Screen readers read it aloud and search engines use it to understand the picture.' },
  { id: 'assistive-tech', term: 'Assistive technology', plain: 'Tools such as screen readers that people with low vision or motor difficulty use to browse the web.' },
  { id: 'spf-dmarc', term: 'SPF, DKIM, DMARC', plain: 'Three records that prove an email really came from your domain. Without them, mail can land in spam or be forged in your name.' },
  { id: 'internal-link', term: 'Internal link', plain: 'A link from one page of your site to another. These tell visitors and search engines which pages matter and how they connect.' },
  { id: 'indexing', term: 'Indexing', plain: 'Search engines keeping a copy of your page so it can appear in results. A page that is not indexed cannot be found by searching.' },
];

export const PLAIN: Record<string, PlainNote> = {
  'slow-first-paint': {
    inPlain: 'When someone opens your pages, the main content takes longer to appear than it should. People tend to give up on a page that stays blank.',
    picture: 'It is like a shop with a front door that sticks: the goods are fine, but some people turn around before they get in.',
    ifIgnored: { text: 'Visitors on slower connections are more likely to leave before they read your offer.', basis: 'General web-performance practice. No analytics were supplied, so the effect on your business is not measured here.' },
    yourPart: 'Agree that speed is worth a short investigation, and ask your developer or host for real-visitor speed data so we start from facts and not one test.',
    askYourTeam: ['Has anyone timed the site on a phone on mobile data?', 'Which add-on scripts could we live without?'],
    terms: ['lcp', 'lab-test', 'field-data', 'third-party'],
  },
  'security-gaps': {
    inPlain: 'Your site is missing some standard safety instructions that browsers look for. Nothing here says you have been attacked; it means the doors are not locked as tightly as they could be.',
    picture: 'Think of a building with a good front lock but no instructions posted for visitors about fire exits.',
    ifIgnored: { text: 'The gaps stay visible to anyone who runs a free security scan, which can weaken trust with careful clients and IT teams.', basis: 'These checks are visible with free public tools. No direct effect on rankings is claimed.' },
    yourPart: 'Ask whoever manages your hosting or CDN to turn on the missing protections. It is usually one settings change.',
    askYourTeam: ['Who controls our hosting and CDN settings?', 'When does our security certificate renew, and who is told?'],
    terms: ['headers', 'cdn', 'certificate'],
  },
  'dead-links': {
    inPlain: 'Some links on your site lead to pages that do not work or that forward visitors on a detour.',
    picture: 'It is a sign on your street pointing to a shop that has closed.',
    ifIgnored: { text: 'Visitors who hit an error are likely to leave, and search engines may spend their time on dead ends.', basis: 'General crawling and usability practice; the size of the effect on this site is not measured.' },
    yourPart: 'Decide, for each broken link, whether to remove it, repoint it or restore the page. Your agency can list them.',
    askYourTeam: ['Was a page removed or renamed recently?'],
    terms: ['broken-link', 'redirect'],
  },
  'duplicate-and-hidden-pages': {
    inPlain: 'Some pages repeat each other and some real pages cannot be reached from the rest of the site.',
    picture: 'It is like two near-identical brochures on the counter, and a third one filed in a cupboard nobody opens.',
    ifIgnored: { text: 'Search engines may pick the wrong page to show, and the hidden pages are unlikely to be found.', basis: 'General search-engine behaviour; this review did not measure rankings or traffic.' },
    yourPart: 'Tell us which version of each repeated page is the one you want people to see, and whether the unreachable pages should still exist.',
    askYourTeam: ['Are these pages still in use?', 'Which page is the real one?'],
    terms: ['orphan', 'duplicate', 'canonical'],
  },
  'search-snippets': {
    inPlain: 'Many pages have no written title or description for search results, so Google picks words from the page for you.',
    picture: 'It is a shop window with no sign, where a passer-by reads whatever happens to be in the glass.',
    ifIgnored: { text: 'Your results may read awkwardly or unclearly next to competitors who wrote theirs.', basis: 'Search engines show their own text when none is supplied. How that affects clicks here is not measured.' },
    yourPart: 'Supply or approve the wording for your most important pages: what you want a stranger to read about you.',
    askYourTeam: ['What do we want our top services to say in one line?'],
    terms: ['title-meta'],
  },
  accessibility: {
    inPlain: 'Some parts of the site are hard to use for people who rely on screen readers or keyboards.',
    picture: 'It is a building with a lovely entrance and no ramp.',
    ifIgnored: { text: 'Some visitors cannot complete tasks on your site, and accessibility expectations are increasingly part of procurement checks.', basis: 'Accessibility guidelines and public-sector procurement practice. Automated checks cover only part of the guidelines.' },
    yourPart: 'Decide how much of this to include in the next round of work, and consider a manual accessibility review.',
    askYourTeam: ['Do any of our clients require accessibility compliance?'],
    terms: ['assistive-tech', 'alt-text'],
  },
  'structured-data': {
    inPlain: 'Your pages carry only some of the hidden labels that tell search engines what the page is about.',
    picture: 'It is a filing cabinet where some folders have labels and some do not.',
    ifIgnored: { text: 'Search engines have less to go on when deciding how to present you.', basis: 'Search engines document these labels as optional aids. No guaranteed display result is claimed.' },
    yourPart: 'Confirm your business details (name, address, services) are correct, because they will be written into these labels.',
    askYourTeam: ['Are our business name, address and phone number identical everywhere?'],
    terms: ['schema'],
  },
  'indexing-signals': {
    inPlain: 'Some pages tell search engines two different things about themselves, such as "list me" and "do not list me".',
    picture: 'It is a door with both an OPEN and a CLOSED sign hanging on it.',
    ifIgnored: { text: 'Search engines may skip pages you want found, or show ones you meant to hide.', basis: 'Conflicting directives are resolved by each search engine in its own way.' },
    yourPart: 'Say which pages should appear in search and which should not.',
    askYourTeam: ['Are there pages we deliberately want hidden from search?'],
    terms: ['indexing', 'canonical'],
  },
  'stale-or-thin-content': {
    inPlain: 'Some pages look out of date or say very little.',
    picture: 'It is a notice board with last year\'s dates on it.',
    ifIgnored: { text: 'Visitors may doubt whether the business is current, and thin pages give search engines little to work with.', basis: 'Visitor-trust and content-quality practice; not measured on this site.' },
    yourPart: 'Choose which pages deserve a refresh, which to merge, and which to retire.',
    askYourTeam: ['Who owns keeping each section current?'],
    terms: [],
  },
  'image-weight': {
    inPlain: 'Some images are larger than they need to be or load in a way that makes the page jump while it appears.',
    picture: 'It is like posting a billboard-sized photo through a letterbox.',
    ifIgnored: { text: 'Pages stay slower on phones and mobile data.', basis: 'Image size is a common contributor to slow loads; the share for this site is not measured.' },
    yourPart: 'Agree that new images are resized before upload, and approve a one-off clean-up of the existing ones.',
    askYourTeam: ['Who uploads images, and do they resize them first?'],
    terms: ['lcp'],
  },
  'email-trust': {
    inPlain: 'The records that prove an email came from your domain are missing or incomplete.',
    picture: 'It is a letterhead that anyone could print.',
    ifIgnored: { text: 'Your genuine emails may land in spam, and others could send mail that looks like it came from you.', basis: 'Mail providers use these records when judging a sender; outcomes vary by provider.' },
    yourPart: 'Ask whoever manages your email which services send mail for you, so the records can be set correctly.',
    askYourTeam: ['Which tools send email on our behalf (newsletter, invoicing, CRM)?'],
    terms: ['spf-dmarc'],
  },
  'internal-linking': {
    inPlain: 'Pages that should point to each other do not, so people and search engines miss useful routes through your site.',
    picture: 'It is a town with good shops but no signposts between them.',
    ifIgnored: { text: 'Valuable pages stay harder to find from the rest of the site.', basis: 'Internal links are how crawlers and visitors discover pages; the effect here is not measured.' },
    yourPart: 'Name the pages you most want visitors to reach, so links can be pointed at them.',
    askYourTeam: ['Which three pages matter most to the business?'],
    terms: ['internal-link', 'orphan'],
  },
};
