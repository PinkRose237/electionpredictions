/** methodology.js — page chrome for the static methodology page. */
import { loadJSON, initChrome, renderUpdated, renderFooterMeta } from './common.js';

initChrome({ current: 'methodology' });
loadJSON('summary.json').then((s) => { renderUpdated(s); renderFooterMeta(s); }).catch(() => {});
