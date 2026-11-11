// The dialog for the plugin settings that edits a saved style profile (the same form as in the Publish dialog).
import { Modal, type App } from 'obsidian';
import { createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ProfileEditor } from '../components/ProfileEditor';
import { readProfileForEdit, updateProfile } from './profileSource';

interface Opts { folder: string; id: string; onDone: () => void }

export class ProfileEditorModal extends Modal {
  private root: Root | null = null;
  private opts: Opts;
  constructor(app: App, opts: Opts) { super(app); this.opts = opts; }
  onOpen() {
    this.modalEl.addClass('wo-profile-modal');
    const r = readProfileForEdit(this.opts.folder, this.opts.id);
    if (!r.ok) { this.titleEl.setText('This profile cannot be edited here'); this.contentEl.createEl('p', { text: r.message }); return; }
    const { folder, id } = this.opts; const initial = r.form;
    let baseHash = r.baseHash, base = initial;
    this.root = createRoot(this.contentEl);
    this.root.render(createElement(ProfileEditor, {
      kind: id === 'agency' ? 'agency' : 'client', label: id === 'agency' ? 'agency.json' : id.slice(7), initial,
      onSave: async (form) => {
        const res = updateProfile(folder, id, base, form, baseHash);
        if (!res.ok) return { ok: false, message: res.message };
        // The file is now the new version: a second Save changes works from it.
        const again = readProfileForEdit(folder, id); if (again.ok) { base = form; baseHash = again.baseHash; }
        this.opts.onDone(); return { ok: true, backup: res.backup };
      },
      onClose: () => this.close(),
    }));
  }
  onClose() { try { this.root?.unmount(); } catch { /* already gone */ } this.root = null; this.contentEl.empty(); }
}
