// Builds the Publish dialog harness into a folder with an HTML page that loads the plugin's own stylesheet. Usage: node scripts/ui-harness/build.mjs <outdir>
// The page defines the Obsidian variables the dialog reads, with the values of Obsidian's default dark and light themes (body.theme-dark / body.theme-light).
import fs from 'node:fs';
import path from 'node:path';
import { build } from 'esbuild';
const out = path.resolve(process.argv[2] || 'ui-harness-out'); fs.mkdirSync(out, { recursive: true });
await build({ entryPoints: ['scripts/ui-harness/publish-dialog-harness.tsx'], bundle: true, outfile: path.join(out, 'harness.js'), format: 'iife', platform: 'browser', jsx: 'automatic', logLevel: 'silent', define: { 'process.env.NODE_ENV': '"production"' } });
const css = ['dist-plugin/styles.css', 'dist-plugin/main.css'].filter((f) => fs.existsSync(f)).map((f) => fs.readFileSync(f, 'utf8')).join('\n');
fs.writeFileSync(path.join(out, 'harness.css'), css);
const dark = '--background-primary:#1e1e1e;--background-primary-alt:#262626;--background-secondary:#262626;--background-secondary-alt:#363636;--background-modifier-border:#363636;--background-modifier-border-hover:#3f3f3f;--background-modifier-hover:rgba(255,255,255,0.075);--background-modifier-form-field:#262626;--text-normal:#dadada;--text-muted:#b3b3b3;--text-faint:#7f7f7f;--text-error:#fb464c;--text-success:#08b94e;--text-on-accent:#ffffff;--interactive-accent:#7b6cd9;--interactive-accent-hover:#8b7de0;--interactive-normal:#363636;--interactive-hover:#3f3f3f;--color-orange:#e9973f;--font-ui-small:13px';
const light = '--background-primary:#ffffff;--background-primary-alt:#fafafa;--background-secondary:#f6f6f6;--background-secondary-alt:#e3e3e3;--background-modifier-border:#e0e0e0;--background-modifier-border-hover:#d4d4d4;--background-modifier-hover:rgba(0,0,0,0.075);--background-modifier-form-field:#ffffff;--text-normal:#222222;--text-muted:#5c5c5c;--text-faint:#ababab;--text-error:#e93147;--text-success:#08b94e;--text-on-accent:#ffffff;--interactive-accent:#705dcf;--interactive-accent-hover:#7a6ad5;--interactive-normal:#f2f3f5;--interactive-hover:#e9e9e9;--color-orange:#d97706;--font-ui-small:13px';
const style = `html,body,#root{margin:0;height:100%;font-family:system-ui,sans-serif;font-size:14px}#root{container-type:inline-size;container-name:web-obs;position:relative}
body.theme-dark{background:#1e1e1e;color:#dadada;${dark}}
body.theme-light{background:#ffffff;color:#222222;${light}}`;
fs.writeFileSync(path.join(out, 'index.html'), `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="harness.css"><style>${style}</style></head><body><div id="root"></div><script src="harness.js"></script></body></html>`);
console.log('harness built in ' + out);
