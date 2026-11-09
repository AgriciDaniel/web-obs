import esbuild from 'esbuild';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { builtinModules } from 'node:module';
import zlib from 'node:zlib';
import { engineFileHashes } from './scripts/engine-files.mjs';

// Pack the engine into main.js: Obsidian's installer delivers only main.js, manifest.json and styles.css.
function packEngine() {
  const files = {};
  for (const relative of Object.keys(engineFileHashes('engine'))) {
    files[relative] = fs.readFileSync(path.join('engine', relative)).toString('base64');
  }
  return zlib.gzipSync(Buffer.from(JSON.stringify({ schemaVersion: 1, files })), { level: 9 }).toString('base64');
}

const prod = process.argv[2] !== 'watch';
const outDir = process.env.OBSIDIAN_PLUGIN_OUTDIR
  ? path.resolve(process.env.OBSIDIAN_PLUGIN_OUTDIR)
  : path.resolve('./dist-plugin');

fs.mkdirSync(outDir, { recursive: true });

function copyDirFiltered(srcDir, destDir) {
  if (!fs.existsSync(srcDir)) return;
  fs.mkdirSync(destDir, { recursive: true });
  for (const entry of fs.readdirSync(srcDir, { withFileTypes: true })) {
    if (
      entry.name === '__pycache__' ||
      entry.name === '.venv' ||
      entry.name === '.pytest_cache' ||
      entry.name.endsWith('.pyc')
    ) {
      continue;
    }
    const srcPath = path.join(srcDir, entry.name);
    const destPath = path.join(destDir, entry.name);
    if (entry.isDirectory()) {
      copyDirFiltered(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

const syncPluginAssets = {
  name: 'sync-plugin-assets',
  setup(build) {
    build.onEnd((result) => {
      if (result.errors.length > 0) return;
      fs.copyFileSync('manifest.json', path.join(outDir, 'manifest.json'));
      fs.writeFileSync(path.join(outDir, 'styles.css'), ['theme', 'ui', 'map', 'drawers', 'audit']
        .map((name) => `src/styles/${name}.css`).filter((file) => fs.existsSync(file))
        .map((file) => fs.readFileSync(file, 'utf8')).join('\n'));
      // Start clean so a renamed or deleted engine file cannot linger in the output.
      fs.rmSync(path.join(outDir, 'engine'), { recursive: true, force: true });
      copyDirFiltered('engine', path.join(outDir, 'engine'));
      fs.writeFileSync(path.join(outDir, 'engine-manifest.json'), JSON.stringify({ schemaVersion: 1, files: engineFileHashes('engine') }, null, 2) + '\n');
      if (!prod) {
        fs.writeFileSync(path.join(outDir, '.hotreload'), '');
      }
      console.log(`[web-obs] Built Obsidian plugin -> ${outDir}`);
    });
  },
};

// Web-Obs never renders <script> tags, preinits scripts or uses dangerouslySetInnerHTML. React DOM still ships
// those paths, and they read as script injection and raw HTML sinks to reviewers and scanners, so they are replaced
// with a hard error at build time. Each pattern must match, so a React upgrade that moves them fails the build.
const REACT_DOM_CLIENT = /[\\/]node_modules[\\/]react-dom[\\/]cjs[\\/]react-dom-client\.production\.js$/;
const reactDomHardening = {
  name: 'react-dom-hardening',
  setup(build) {
    build.onLoad({ filter: REACT_DOM_CLIENT }, async (args) => {
      let source = await fs.promises.readFile(args.path, 'utf8');
      const unsupported = (what) => `(function () { throw Error("Web-Obs does not render ${what}."); })()`;
      const replacements = [
        [/nextResource = ownerDocument\.createElement\("div"\);\s*nextResource\.innerHTML = "<script>\\x3c\/script>";\s*nextResource = nextResource\.removeChild\(\s*nextResource\.firstChild\s*\);/g, 1,
          `nextResource = ${unsupported('script elements')};`],
        [/\(domElement\.innerHTML = key\)/g, 2, unsupported('raw HTML')],
        [/\w+\.createElement\("script"\)/g, 3, unsupported('script elements')],
      ];
      for (const [pattern, expected, replacement] of replacements) {
        const found = source.match(pattern)?.length ?? 0;
        if (found !== expected) {
          throw new Error(`React DOM hardening expected ${expected} match(es) of ${pattern}, found ${found} in ${args.path}`);
        }
        source = source.replace(pattern, replacement);
      }
      return { contents: source, loader: 'js' };
    });
  },
};

const banner = `/*
GENERATED OBSIDIAN PLUGIN BUNDLE: Web-Obs 3D Site Globe (web-obs)
Source workspace: web-obs
*/`;

const ctx = await esbuild.context({
  banner: { js: banner },
  entryPoints: ['src/plugin/main.ts'],
  bundle: true,
  external: [
    'obsidian',
    'electron',
    '@codemirror/autocomplete',
    '@codemirror/collab',
    '@codemirror/commands',
    '@codemirror/language',
    '@codemirror/lint',
    '@codemirror/search',
    '@codemirror/state',
    '@codemirror/view',
    '@lezer/common',
    '@lezer/highlight',
    '@lezer/lr',
    ...builtinModules,
    ...builtinModules.map((m) => `node:${m}`),
  ],
  format: 'cjs',
  target: 'es2022',
  jsx: 'automatic',
  define: {
    'process.env.NODE_ENV': prod ? '"production"' : '"development"',
    __WEB_OBS_ENGINE_BUNDLE__: JSON.stringify(packEngine()),
  },
  logLevel: 'info',
  sourcemap: prod ? false : 'inline',
  treeShaking: true,
  minify: prod,
  outfile: path.join(outDir, 'main.js'),
  plugins: [reactDomHardening, syncPluginAssets],
});

if (prod) {
  await ctx.rebuild();
  await ctx.dispose();
  process.exit(0);
} else {
  await ctx.watch();
}
