// Test harness (not shipped): renders the real Publish dialog (useAuditActions) inside a panel shaped like the audit panel, with mock actions.
// window.__calls records what the dialog asked the plugin to do, so a browser test can check the order (save before publish, never publish an unsaved look).
import { createRoot } from 'react-dom/client';
import { useAuditActions } from '../../src/components/AuditActionsBar';
import type { AuditActions, SiteGraphManifest, StyleChoiceInfo } from '../../src/types/site';
import { EMPTY_FORM } from '../../src/data/profileForm';

declare global { interface Window { __calls: Array<{ fn: string; args: unknown[] }>; __cfg: Record<string, unknown>; __saved: boolean } }
window.__calls = []; window.__cfg = {}; window.__saved = false;
const log = (fn: string, ...args: unknown[]) => { window.__calls.push({ fn, args }); };
const cfg = () => window.__cfg as { agencyExists?: boolean; preference?: string; editResult?: { ok: boolean; id?: string; backup?: string; code?: string; message?: string }; editFail?: string; saveResult?: { ok: boolean; id?: string; code?: string; message?: string }; failPublish?: boolean; publishReady?: boolean; noTarget?: boolean };
const params = new URLSearchParams(location.search);
const THEME = params.get('theme') === 'light' ? 'light' : 'dark';
document.body.classList.add(THEME === 'light' ? 'theme-light' : 'theme-dark');

const manifest = { siteId: 's1', domain: 'example-client.com' } as unknown as SiteGraphManifest;
const CLIENT_ID = 'client:example-client.com.json';
const choices = (): StyleChoiceInfo[] => [
  { id: 'default', label: 'Default (built-in look)', kind: 'default', ok: true },
  cfg().agencyExists ? { id: 'agency', label: 'Agency: Example Agency', kind: 'agency', ok: true } : { id: 'agency', label: 'Agency (not set up yet)', kind: 'agency', ok: true, missing: true },
  window.__saved ? { id: CLIENT_ID, label: 'Client: Example Client', kind: 'client', ok: true } : { id: CLIENT_ID, label: 'Client: example-client.com (not set up yet)', kind: 'client', ok: true, missing: true },
];
const actions: AuditActions = {
  approver: 'Tester', lastStyleId: 'default',
  get stylePreference() { return (cfg().preference ?? 'auto') as 'auto'; },
  styleEdit: async (id) => { log('styleEdit', id); if (cfg().editFail) return { ok: false, message: cfg().editFail as string }; return { ok: true, baseHash: 'h1', form: { ...EMPTY_FORM, name: 'Example Agency', accent: '#e8743b', secondary: '#4fb0c6', surface: '#f7f7f7', text: '#e6e6e6', cardText: '#222222', footerText: 'Prepared by Example Agency' } }; },
  saveStyleEdit: async (id, initial, form, baseHash) => { log('saveStyleEdit', id, JSON.stringify(Object.keys(form).filter((k) => (form as never as Record<string, string>)[k] !== (initial as never as Record<string, string>)[k])), baseHash); return cfg().editResult ?? { ok: true, id, backup: id + '.bak' }; },
  get publishReady() { return cfg().publishReady ?? true; },
  get publishTargetLabel() { return cfg().noTarget ? null : 'audit.example.com'; },
  styleChoices: async (d) => { log('styleChoices', d); return choices(); },
  previewStyle: async (id) => { log('previewStyle', id); return { id, label: id, summary: id === 'default' ? 'The built-in look. Nothing extra is sent.' : 'accent #e8743b', notes: [] }; },
  styleDraft: async (siteId, id) => { log('styleDraft', siteId, id); return { form: { ...EMPTY_FORM, name: 'Example Client', accent: '#2a7fff', secondary: '#4fb0c6' }, hints: ['Accent taken from the site’s theme color or palette.'] }; },
  saveStyleProfile: async (siteId, id, form, overwrite) => {
    log('saveStyleProfile', siteId, id, form.name, !!overwrite);
    const r = cfg().saveResult ?? { ok: true, id: CLIENT_ID };
    if (r.ok) window.__saved = true;
    return r;
  },
  publish: async (siteId, by, styleId) => {
    log('publish', siteId, by, styleId);
    if (cfg().failPublish) throw new Error('The server said no.');
    return { sizeKb: 12, findings: 5, top: [], pushedTo: 'audit.example.com', link: 'https://audit.example.com/r/abc', expires: new Date().toISOString(), lookLabel: styleId === 'default' ? undefined : 'Example Client' } as never;
  },
  previewArchive: async () => ({ domain: 'example-client.com', items: [{ label: 'Notes', rel: 'sites/example-client.com', files: 412, bytes: 3_400_000 }, { label: 'Captures', rel: '.web-obs/captures/example-client.com', files: 1280, bytes: 52_000_000 }], files: 1692, bytes: 55_400_000 }),
  archive: async () => ({ domain: 'example-client.com', trash: '.web-obs/trash/example-client.com-20261109', files: 1692 }),
};
function Panel() {
  const ui = useAuditActions({ manifest, actions, onOpenUrl: () => {}, onArchived: () => {} });
  return <section className="wo-audit-panel" aria-label="Site audit">
    <header className="wo-audit-header"><div className="wo-audit-heading"><h1>Site audit <span>example-client.com</span></h1></div><div className="wo-audit-actions">{ui.buttons}</div></header>
    {ui.dialogs}
    <div className="wo-audit-body"><div className="wo-audit-content">{Array.from({ length: 30 }, (_, i) => <p key={i}>Audit content row {i + 1}</p>)}</div></div>
  </section>;
}
createRoot(document.getElementById('root')!).render(<div className={`wo-shell wo-theme-${THEME}`} style={{ position: 'absolute', inset: 0 }}><Panel /></div>);
