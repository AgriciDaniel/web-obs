import assert from 'node:assert/strict';
import { build } from 'esbuild';

// The layout and node-look modules use browser window APIs; Node gives them the same timers and globals.
globalThis.window ??= globalThis;

async function load(entry) {
  const output = await build({ entryPoints: [entry], bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent' });
  return import('data:text/javascript;base64,' + Buffer.from(output.outputFiles[0].contents).toString('base64'));
}
const look = await load('src/components/nodeLook.ts');

function check(name, fn) {
  fn();
  console.log(`[PASS] ${name}`);
}

check('the original look is the default', () => {
  assert.equal(look.DEFAULT_NODE_LOOK, 'classic');
  assert.deepEqual(look.DEFAULT_NODE_VISUALS, look.CLASSIC_NODE_VISUALS);
  assert.deepEqual(look.resolveNodeVisuals('classic'), look.CLASSIC_NODE_VISUALS);
});

check('the original look has solid orbs and the ring halo, at one fixed sphere detail', () => {
  const v = look.CLASSIC_NODE_VISUALS;
  assert.deepEqual([v.defaultOpacity, v.highlightOpacity, v.dimOpacity], [1, 1, 1], 'orbs are never see-through');
  assert.equal(v.haloStyle, 'ring');
  assert.equal(v.adaptiveSphereDetail, false);
  assert.deepEqual([v.sphereWidthSegments, v.sphereHeightSegments], [22, 22]);
  assert.equal(v.transitionMs, 0, 'a selection takes effect at once, as before');
  assert.deepEqual([v.glowDefault, v.glowSelected, v.glowDim], [0.32, 0.85, 0.08]);
  assert.deepEqual([v.haloAlphaDefault, v.haloAlphaSelected, v.haloAlphaDim], [0.28, 0.85, 0.05]);
});

check('the translucent look changes opacity, dimming and the halo', () => {
  const v = look.resolveNodeVisuals('translucent');
  assert.ok(v.defaultOpacity < 1, 'translucent at rest');
  assert.ok(v.dimOpacity < v.defaultOpacity, 'unlinked orbs recede when something is selected');
  assert.equal(v.highlightOpacity, 1);
  assert.equal(v.haloStyle, 'hairline');
  assert.ok(v.transitionMs > 0, 'changes ease in');
});

check('the developer override applies on top of the chosen look', () => {
  globalThis.__WO_VISUAL__ = { defaultOpacity: 0.5 };
  try {
    assert.equal(look.resolveNodeVisuals('classic').defaultOpacity, 0.5);
    assert.equal(look.resolveNodeVisuals('classic').haloStyle, 'ring');
    assert.equal(look.resolveNodeVisuals('translucent').haloStyle, 'hairline');
  } finally {
    delete globalThis.__WO_VISUAL__;
  }
});

console.log('[PASS] Node look presets verified.');
