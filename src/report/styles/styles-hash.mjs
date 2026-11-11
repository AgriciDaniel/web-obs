// The pairing name of a styles file: the first 12 hex characters of the SHA-256 of its fixed text form (see canonicalStyles in styles.mjs).
// Node only (uses node:crypto); the Studio and the browser never need it. The ingest recomputes it and refuses a mismatch.
import crypto from 'node:crypto';
import { canonicalStyles } from './styles.mjs';

export const STYLES_KEY = /^styles_([0-9a-f]{12})$/;
export const DATA_KEY = /^data_([0-9a-f]{12})$/;
export const stylesHash = (raw) => crypto.createHash('sha256').update(canonicalStyles(raw), 'utf8').digest('hex').slice(0, 12);
/** Builds the one-request envelope the publish route accepts: { styles_<hash>: styles, data_<hash>: report }. */
export function makeEnvelope(report, styles) {
  const h = stylesHash(styles);
  return { ['styles_' + h]: styles, ['data_' + h]: report };
}
