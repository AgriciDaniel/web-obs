// The dialog shown by Publish audit when no publish target and no reports folder are set.
// The user either saves the file in a local folder (and handles ingestion themselves) or enters the front end address to push to.
// "Remember" stores the address or folder path in the settings. Never a secret.
import { App, Modal, Setting } from 'obsidian';
import { parseDestination, type Destination } from './publishTarget';

export interface DestinationChoice { destination: Destination; remember: boolean }

export function askDestination(app: App): Promise<DestinationChoice | null> {
  return new Promise((resolve) => {
    class DestinationModal extends Modal {
      private done = false;
      private finish(v: DestinationChoice | null) { if (!this.done) { this.done = true; resolve(v); } this.close(); }
      onOpen() {
        this.titleEl.setText('Where should this report go?');
        const { contentEl } = this;
        contentEl.createEl('p', { text: 'Fill in one of the two. A folder saves the file there under a random name and you handle ingestion yourself. An address pushes the report to your report front end, which makes the link.' });
        const state = { folder: '', address: '', remember: false };
        const error = contentEl.createEl('p', { cls: 'mod-warning' });
        new Setting(contentEl).setName('Save in a folder').setDesc('A full folder path.').addText((t) => t.setPlaceholder('C:\\path\\to\\reports').onChange((v) => { state.folder = v; }));
        new Setting(contentEl).setName('Push to a front end').setDesc('The base address only. HTTPS is required; the upload route is added for you.').addText((t) => t.setPlaceholder('audit.example.com').onChange((v) => { state.address = v; }));
        new Setting(contentEl).setName('Remember this choice').setDesc('Saves the address or folder path in the Web-Obs settings. No secret is saved there.').addToggle((tg) => tg.onChange((v) => { state.remember = v; }));
        new Setting(contentEl)
          .addButton((b) => b.setButtonText('Continue').setCta().onClick(() => {
            try { this.finish({ destination: parseDestination(state), remember: state.remember }); } catch (e) { error.setText((e as Error).message); }
          }))
          .addButton((b) => b.setButtonText('Cancel').onClick(() => this.finish(null)));
      }
      onClose() { if (!this.done) { this.done = true; resolve(null); } this.contentEl.empty(); }
    }
    new DestinationModal(app).open();
  });
}
