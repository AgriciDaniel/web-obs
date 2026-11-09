// The look documentation says what a reader needs, and its links and images resolve. Synthetic and local only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

let n = 0;
const ok = (name, fn) => { fn(); n++; console.log('  ok   ' + name); };
const read = (f) => fs.readFileSync(f, 'utf8');
const reports = read('docs/CLIENT-REPORTS.md'), styles = read('docs/PUBLISH-STYLES.md');

ok('Client reports states the limits of the styles file, the request shape and the three version requirements', () => {
  for (const w of ['#rrggbb', 'Oswald', 'Inter', '4096', '80 characters', '120 characters', 'styles_<hash>', 'data_<hash>', 'report app 0.1.4 or later', '0.1.6 or later', '0.1.7', 'SSH and local folder routes', 'What is and is not sent']) assert.ok(reports.includes(w), w);
  for (const slot of ['accent', 'secondary', 'link', 'text', 'muted', 'surface', 'cardText', 'cardMuted', 'headingFont', 'bodyFont', 'headingCase', 'name', 'footerText']) assert.ok(reports.includes('`' + slot + '`'), slot);
});
ok('Publish with a look has the version table and points to Client reports instead of repeating it', () => {
  assert.ok(styles.includes('What needs which report app version') && styles.includes('(CLIENT-REPORTS.md#a-report-with-a-look)'));
  assert.ok(reports.includes('## A report with a look') && reports.includes('(PUBLISH-STYLES.md)'));
});
ok('every relative link and image in the two pages points at a file that exists', () => {
  for (const [file, text] of [['docs/CLIENT-REPORTS.md', reports], ['docs/PUBLISH-STYLES.md', styles]]) {
    for (const m of text.matchAll(/\]\(([^)#\s]+)(#[^)]*)?\)/g)) {
      const target = m[1]; if (/^(https?:|mailto:)/.test(target)) continue;
      assert.ok(fs.existsSync(path.join(path.dirname(file), target)), file + ' links to ' + target);
    }
  }
});
ok('every image the pages show exists in docs/screenshots and is small enough to keep the repository light', () => {
  let count = 0;
  for (const text of [reports, styles]) for (const m of text.matchAll(/!\[[^\]]*\]\(screenshots\/([^)]+)\)/g)) {
    const file = path.join('docs', 'screenshots', m[1]); assert.ok(fs.existsSync(file), file); assert.ok(fs.statSync(file).size < 250 * 1024, file + ' is under 250 KB'); count++;
    assert.match(m[1], /^client-reports-[a-z0-9-]+\.png$/, 'a plain name with no client or agency in it: ' + m[1]);
  }
  assert.ok(count >= 13, 'both pages show their pictures: ' + count);
});
console.log(`Look docs OK: ${n} checks passed.`);
