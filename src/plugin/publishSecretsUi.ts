// The prompt used when no ingest secret is stored: asks once, and the answer is kept in memory for this session only.
import { App, Modal, Setting } from 'obsidian';

export function askIngestSecret(app: App): Promise<string | null> {
  return new Promise((resolve) => {
    class AskModal extends Modal {
      private done = false;
      private finish(v: string | null) { if (!this.done) { this.done = true; resolve(v); } this.close(); }
      onOpen() {
        this.titleEl.setText('Publish secret');
        (this as unknown as { modalEl?: { addClass?: (c: string) => void } }).modalEl?.addClass?.('wo-publish-modal');
        this.contentEl.createEl('p', { cls: 'wo-modal-intro', text: 'Enter the ingest secret. It is kept in memory until Obsidian closes, and is never saved in data.json or the vault. To keep it between sessions, add it in the Web-Obs settings instead.' });
        let value = '';
        new Setting(this.contentEl).setName('Ingest secret').addText((t) => { t.inputEl.type = 'password'; t.inputEl.autocomplete = 'off'; t.onChange((v) => { value = v; }); t.inputEl.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.finish(value); }); });
        new Setting(this.contentEl)
          .addButton((b) => b.setButtonText('Use for this session').setCta().onClick(() => this.finish(value)))
          .addButton((b) => b.setButtonText('Cancel').onClick(() => this.finish(null)));
      }
      onClose() { if (!this.done) { this.done = true; resolve(null); } this.contentEl.empty(); }
    }
    new AskModal(app).open();
  });
}
