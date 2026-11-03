/** Decode the crawler protocol across arbitrary UTF-8 and newline boundaries. */
export class JsonlDecoder {
  private readonly decoder = new TextDecoder();
  private buffer = '';

  constructor(private readonly onRecord: (record: Record<string, unknown>) => void) {}

  push(chunk: Uint8Array | string): void {
    this.buffer += typeof chunk === 'string' ? chunk : this.decoder.decode(chunk, { stream: true });
    this.drain(false);
  }

  finish(): void {
    this.buffer += this.decoder.decode();
    this.drain(true);
  }

  private drain(final: boolean): void {
    let boundary = this.buffer.indexOf('\n');
    while (boundary >= 0) {
      this.parse(this.buffer.slice(0, boundary));
      this.buffer = this.buffer.slice(boundary + 1);
      boundary = this.buffer.indexOf('\n');
    }
    if (this.buffer.length > 1024 * 1024) throw new Error('Crawler event exceeded the 1 MB line limit.');
    if (final && this.buffer.trim()) this.parse(this.buffer);
    if (final) this.buffer = '';
  }

  private parse(raw: string): void {
    const line = raw.trim();
    if (!line) return;
    if (line.length > 1024 * 1024) throw new Error('Crawler event exceeded the 1 MB line limit.');
    let value: unknown;
    try { value = JSON.parse(line); } catch { throw new Error('Crawler returned an invalid JSON event.'); }
    if (!value || typeof value !== 'object' || Array.isArray(value) || typeof (value as Record<string, unknown>).event !== 'string') {
      throw new Error('Crawler event has an invalid shape.');
    }
    this.onRecord(value as Record<string, unknown>);
  }
}
