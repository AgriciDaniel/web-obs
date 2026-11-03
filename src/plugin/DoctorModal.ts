import { Modal, Notice, type App } from 'obsidian';
import { doctorReportText, summarizeDoctor, type DoctorRow } from './doctorReport';

const STATE_LABEL = { pass: 'Pass', warn: 'Note', fail: 'Fix' } as const;

export class DoctorModal extends Modal {
  private rows: DoctorRow[] | null = null;

  constructor(app: App, private readonly run: () => Promise<DoctorRow[]>) {
    super(app);
  }

  override onOpen(): void {
    this.modalEl.addClass('wo-doctor-modal');
    this.render();
    void this.run().then(
      (rows) => { this.rows = rows; this.render(); },
      (error) => {
        this.rows = [{ id: 'doctor', label: 'Diagnostics', state: 'fail', detail: error instanceof Error ? error.message : 'Diagnostics failed to run.' }];
        this.render();
      }
    );
  }

  private render(): void {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.createEl('h3', { text: 'Web-Obs diagnostics' });
    if (!this.rows) {
      contentEl.createEl('p', { text: 'Checking Python, engine files, browser, vault access and network...', cls: 'wo-doctor-pending' });
      return;
    }
    const rows = this.rows;
    const summary = summarizeDoctor(rows);
    contentEl.createDiv({ cls: `wo-doctor-summary wo-doctor-${summary.state}`, text: summary.headline });
    const list = contentEl.createDiv({ cls: 'wo-doctor-list' });
    for (const row of rows) {
      const item = list.createDiv({ cls: `wo-doctor-row wo-doctor-${row.state}` });
      item.createSpan({ cls: 'wo-doctor-badge', text: STATE_LABEL[row.state] });
      const body = item.createDiv({ cls: 'wo-doctor-body' });
      body.createDiv({ cls: 'wo-doctor-label', text: row.label });
      body.createDiv({ cls: 'wo-doctor-detail', text: row.detail });
      if (row.fix) body.createDiv({ cls: 'wo-doctor-fix', text: row.fix });
    }
    const actions = contentEl.createDiv({ cls: 'wo-doctor-actions' });
    actions.createEl('button', { text: 'Copy report' }).addEventListener('click', () => {
      navigator.clipboard.writeText(doctorReportText(rows)).then(
        () => new Notice('Diagnostics report copied.'),
        () => new Notice('Could not copy. Select the text manually.')
      );
    });
    actions.createEl('button', { text: 'Run again' }).addEventListener('click', () => {
      this.rows = null;
      this.render();
      void this.run().then((next) => { this.rows = next; this.render(); });
    });
  }

  override onClose(): void {
    this.contentEl.empty();
  }
}
