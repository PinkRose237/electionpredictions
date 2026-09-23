/**
 * common.js — shared helpers for the Midterm Model 2026 site.
 *
 * Sections
 *   1. Site constants, state list, tile-map layout
 *   2. Data base path (`?data=_fixture` switch) and JSON loading
 *   3. Formatting: percents, margins, money, dates, relative time (null → "—")
 *   4. Theme detection + diverging blue→gray→red probability scale (OKLab)
 *   5. DOM / SVG builders (text always goes through text nodes, never innerHTML)
 *   6. Scales, ticks and a responsive chart wrapper
 *   7. Tooltip singleton
 *   8. Political helpers: party colours, rating labels/pills, candidate lines
 *   9. Page chrome: top bar, "updated" line, footer, error panel
 */

// ---------------------------------------------------------------------------
// 1. Constants
// ---------------------------------------------------------------------------

/** Site name — rename here (and in the <title> tags) to rebrand. */
export const SITE_NAME = 'Midterm Model 2026';
export const ELECTION_DATE = '2026-11-03';
export const DASH = '—';

export const CHAMBERS = ['house', 'senate', 'governor'];
export const CHAMBER_LABEL = { house: 'House', senate: 'Senate', governor: 'Governors', president: 'President' };
export const CHAMBER_SINGULAR = { house: 'House', senate: 'Senate', governor: 'Governor', president: 'President' };

export const LABELS = ['Safe D', 'Likely D', 'Lean D', 'Tossup', 'Lean R', 'Likely R', 'Safe R'];
export const COMPETITIVE = new Set(['Likely D', 'Lean D', 'Tossup', 'Lean R', 'Likely R']);

export const STATE_NAMES = {
  AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California', CO: 'Colorado',
  CT: 'Connecticut', DE: 'Delaware', FL: 'Florida', GA: 'Georgia', HI: 'Hawaii', ID: 'Idaho',
  IL: 'Illinois', IN: 'Indiana', IA: 'Iowa', KS: 'Kansas', KY: 'Kentucky', LA: 'Louisiana',
  ME: 'Maine', MD: 'Maryland', MA: 'Massachusetts', MI: 'Michigan', MN: 'Minnesota',
  MS: 'Mississippi', MO: 'Missouri', MT: 'Montana', NE: 'Nebraska', NV: 'Nevada',
  NH: 'New Hampshire', NJ: 'New Jersey', NM: 'New Mexico', NY: 'New York', NC: 'North Carolina',
  ND: 'North Dakota', OH: 'Ohio', OK: 'Oklahoma', OR: 'Oregon', PA: 'Pennsylvania',
  RI: 'Rhode Island', SC: 'South Carolina', SD: 'South Dakota', TN: 'Tennessee', TX: 'Texas',
  UT: 'Utah', VT: 'Vermont', VA: 'Virginia', WA: 'Washington', WV: 'West Virginia',
  WI: 'Wisconsin', WY: 'Wyoming', DC: 'District of Columbia',
};

/** Tile-map layout: 8 rows × 11 columns, roughly geographic (NPR/538 style). '' = empty cell. */
export const STATE_GRID = [
  ['AK', '', '', '', '', '', '', '', '', '', 'ME'],
  ['', '', '', '', '', '', '', '', '', 'VT', 'NH'],
  ['WA', 'ID', 'MT', 'ND', 'MN', 'IL', 'WI', 'MI', 'NY', 'RI', 'MA'],
  ['OR', 'NV', 'WY', 'SD', 'IA', 'IN', 'OH', 'PA', 'NJ', 'CT', ''],
  ['CA', 'UT', 'CO', 'NE', 'MO', 'KY', 'WV', 'VA', 'MD', 'DE', ''],
  ['', 'AZ', 'NM', 'KS', 'AR', 'TN', 'NC', 'SC', '', '', ''],
  ['', '', '', 'OK', 'LA', 'MS', 'AL', 'GA', '', '', ''],
  ['HI', '', '', 'TX', '', '', '', '', 'FL', '', ''],
];

// ---------------------------------------------------------------------------
// 2. Data base path + loading
// ---------------------------------------------------------------------------

export const query = new URLSearchParams(window.location.search);

/**
 * Resolve the data directory. Default `./data`; `?data=_fixture` → `./_fixture`.
 * Only a simple relative folder name is accepted (no `..`, no absolute paths).
 */
export function resolveDataBase(raw) {
  if (!raw) return './data';
  const cleaned = String(raw).replace(/^[./]+/, '').replace(/\/+$/, '');
  if (!cleaned || cleaned.includes('..') || !/^[A-Za-z0-9_][A-Za-z0-9_\-/]*$/.test(cleaned)) return './data';
  return `./${cleaned}`;
}
export const DATA_BASE = resolveDataBase(query.get('data'));
/** The `data` query value to propagate to other pages, or null when using the default. */
export const DATA_PARAM = DATA_BASE === './data' ? null : DATA_BASE.slice(2);

/** Append `?data=` to an internal link when a non-default data directory is in use. */
export function withData(url) {
  if (!DATA_PARAM) return url;
  const [base, hash] = String(url).split('#');
  const joined = `${base}${base.includes('?') ? '&' : '?'}data=${encodeURIComponent(DATA_PARAM)}`;
  return hash != null ? `${joined}#${hash}` : joined;
}
export function raceHref(id) {
  return withData(`race.html?id=${encodeURIComponent(id)}`);
}

/** Fetch `${base}/${relPath}` and parse JSON, with readable errors. */
export async function loadJSON(relPath, base) {
  const url = `${base || DATA_BASE}/${relPath}`;
  let res;
  try {
    res = await fetch(url, { cache: 'no-cache' });
  } catch (e) {
    throw new Error(`Network error while loading ${url}`);
  }
  if (!res.ok) throw new Error(`Could not load ${url} (HTTP ${res.status})`);
  try {
    return await res.json();
  } catch (e) {
    throw new Error(`${url} is not valid JSON`);
  }
}

// ---------------------------------------------------------------------------
// 3. Formatting
// ---------------------------------------------------------------------------

export const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** Parse an ISO date or date-time. Date-only strings are treated as local dates. */
export function parseDate(iso) {
  if (!iso || typeof iso !== 'string') return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  const d = m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function relativeTime(iso) {
  const d = parseDate(iso);
  if (!d) return DASH;
  const diff = Date.now() - d.getTime();
  const abs = Math.abs(diff);
  const units = [['year', 365 * 864e5], ['month', 30 * 864e5], ['day', 864e5], ['hour', 36e5], ['minute', 6e4]];
  for (const [name, ms] of units) {
    if (abs >= ms) {
      const n = Math.round(abs / ms);
      const label = `${n} ${name}${n === 1 ? '' : 's'}`;
      return diff >= 0 ? `${label} ago` : `in ${label}`;
    }
  }
  return 'just now';
}

export function daysUntil(dateStr) {
  const d = parseDate(dateStr);
  if (!d) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((d.getTime() - today.getTime()) / 864e5);
}

export const fmt = {
  /** Probability 0–1 → "93%". Extremes shown as ">99%" / "<1%". */
  pct(p, digits = 0) {
    if (!isNum(p)) return DASH;
    const x = p * 100;
    if (digits === 0) {
      if (x > 99 && x < 100) return '>99%';
      if (x > 0 && x < 1) return '<1%';
      return `${Math.round(x)}%`;
    }
    return `${x.toFixed(digits)}%`;
  },
  /** Percentage points (already ×100) → "48.0%". */
  pts(x, digits = 1) {
    return isNum(x) ? `${x.toFixed(digits)}%` : DASH;
  },
  /** D-minus-R margin → "D+7.1" / "R+3.4" / "Even". */
  margin(m, digits = 1) {
    if (!isNum(m)) return DASH;
    const a = Math.abs(m);
    if (a < 0.05) return 'Even';
    return `${m > 0 ? 'D' : 'R'}+${a.toFixed(digits)}`;
  },
  /** Dollars → "$77.3M" / "$401K" / "$950". */
  money(x) {
    if (!isNum(x)) return DASH;
    const a = Math.abs(x);
    const sign = x < 0 ? '−' : '';
    if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(a >= 1e10 ? 0 : 1)}B`;
    if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(a >= 1e8 ? 0 : 1)}M`;
    if (a >= 1e3) return `${sign}$${Math.round(a / 1e3)}K`;
    return `${sign}$${Math.round(a)}`;
  },
  num(n, digits = 0) {
    return isNum(n)
      ? n.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: digits })
      : DASH;
  },
  dec(n, digits = 1) {
    return isNum(n) ? n.toFixed(digits) : DASH;
  },
  /** Signed number with a real minus sign: "+2.0" / "−1.5" / "0.0". */
  signed(n, digits = 1) {
    if (!isNum(n)) return DASH;
    const s = n > 0 ? '+' : n < 0 ? '−' : '';
    return `${s}${Math.abs(n).toFixed(digits)}`;
  },
  date(iso) {
    const d = parseDate(iso);
    return d ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : DASH;
  },
  dateShort(iso) {
    const d = parseDate(iso);
    return d ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : DASH;
  },
  dateTime(iso) {
    const d = parseDate(iso);
    return d
      ? d.toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
      : DASH;
  },
  /** "Sep 14–16" style date range for polls. */
  dateRange(a, b) {
    const da = parseDate(a), db = parseDate(b);
    if (!da && !db) return DASH;
    if (!da) return fmt.dateShort(b);
    if (!db || da.getTime() === db.getTime()) return fmt.dateShort(a);
    const sameMonth = da.getMonth() === db.getMonth() && da.getFullYear() === db.getFullYear();
    return sameMonth ? `${fmt.dateShort(a)}–${db.getDate()}` : `${fmt.dateShort(a)}–${fmt.dateShort(b)}`;
  },
  platform(p) {
    if (!p) return DASH;
    const map = { polymarket: 'Polymarket', predictit: 'PredictIt', kalshi: 'Kalshi' };
    return map[String(p).toLowerCase()] || String(p).charAt(0).toUpperCase() + String(p).slice(1);
  },
};

// ---------------------------------------------------------------------------
// 4. Theme + colour scale
// ---------------------------------------------------------------------------

const darkMQ = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
const THEME_KEY = 'theme';
/** 'auto' | 'light' | 'dark' — the user's explicit choice, if any (stored on <html data-theme>). */
export function themeMode() {
  const t = document.documentElement.dataset.theme;
  return t === 'light' || t === 'dark' ? t : 'auto';
}
export function isDark() {
  const mode = themeMode();
  if (mode !== 'auto') return mode === 'dark';
  return !!(darkMQ && darkMQ.matches);
}
const themeListeners = new Set();
/** Register a callback for light/dark changes (OS or toggle); returns an unsubscribe function. */
export function onThemeChange(fn) {
  themeListeners.add(fn);
  return () => themeListeners.delete(fn);
}
function notifyThemeChange() {
  colorCache.light.clear();
  colorCache.dark.clear();
  repaintAll();
  themeListeners.forEach((fn) => {
    try { fn(); } catch (e) { console.error(e); }
  });
}
if (darkMQ && darkMQ.addEventListener) {
  darkMQ.addEventListener('change', () => { if (themeMode() === 'auto') notifyThemeChange(); });
}
/** Apply and remember a theme choice; 'auto' follows the operating system. */
export function setTheme(mode) {
  if (mode === 'auto') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = mode;
  try {
    if (mode === 'auto') localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, mode);
  } catch (e) { /* storage unavailable: the choice still applies to this page */ }
  document.querySelectorAll('.theme-toggle').forEach(updateThemeToggle);
  notifyThemeChange();
}
const THEME_LABEL = { auto: 'Auto', light: 'Light', dark: 'Dark' };
const THEME_ICON = { auto: '◐', light: '☀', dark: '☾' };
function updateThemeToggle(btn) {
  const mode = themeMode();
  btn.replaceChildren(h('span', { class: 'theme-icon', 'aria-hidden': 'true' }, THEME_ICON[mode]), h('span', {}, THEME_LABEL[mode]));
  btn.setAttribute('aria-label', `Theme: ${THEME_LABEL[mode]}. Activate to change.`);
  btn.title = `Theme: ${THEME_LABEL[mode]} — click to cycle Auto → Light → Dark`;
}
/** Add the Auto/Light/Dark toggle to the top bar. */
export function mountThemeToggle(container) {
  if (!container || container.querySelector('.theme-toggle')) return;
  const btn = h('button', { class: 'theme-toggle', type: 'button' });
  updateThemeToggle(btn);
  btn.addEventListener('click', () => {
    const order = ['auto', 'light', 'dark'];
    setTheme(order[(order.indexOf(themeMode()) + 1) % order.length]);
  });
  container.append(btn);
}

// --- sRGB ⇄ OKLab (Björn Ottosson's matrices) for perceptually even ramps ---
function srgbToLinear(c) {
  c /= 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}
function linearToSrgb(c) {
  const v = c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
  return Math.round(clamp(v, 0, 1) * 255);
}
export function hexToRgb(hex) {
  const h = hex.replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function rgbToOklab([r, g, b]) {
  const lr = srgbToLinear(r), lg = srgbToLinear(g), lb = srgbToLinear(b);
  const l = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb);
  const m = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb);
  const s = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}
function oklabToHex([L, a, b]) {
  const l = Math.pow(L + 0.3963377774 * a + 0.2158037573 * b, 3);
  const m = Math.pow(L - 0.1055613458 * a - 0.0638541728 * b, 3);
  const s = Math.pow(L - 0.0894841775 * a - 1.291485548 * b, 3);
  const r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s;
  const g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s;
  const bb = -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s;
  return '#' + [r, g, bb].map((v) => linearToSrgb(v).toString(16).padStart(2, '0')).join('');
}
export function mixOklab(hexA, hexB, t) {
  const a = rgbToOklab(hexToRgb(hexA)), b = rgbToOklab(hexToRgb(hexB));
  return oklabToHex([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]);
}

/** Diverging stops for P(Democrat wins): 0 = Republican red … 0.5 = neutral gray … 1 = Democratic blue. */
const STOPS_LIGHT = [[0, '#b2182b'], [0.25, '#e07b68'], [0.5, '#dcdcda'], [0.75, '#7fb0d6'], [1, '#2166ac']];
const STOPS_DARK = [[0, '#d8504a'], [0.25, '#9a4f4c'], [0.5, '#4f5157'], [0.75, '#48709f'], [1, '#4a90d9']];
const colorCache = { light: new Map(), dark: new Map() };

function computeProbColor(p, stops) {
  // Compress toward the poles a little so Lean/Likely races still carry visible colour.
  let t = (p - 0.5) * 2;
  t = Math.sign(t) * Math.pow(Math.abs(t), 0.8);
  const q = t / 2 + 0.5;
  for (let i = 1; i < stops.length; i++) {
    if (q <= stops[i][0]) {
      const [q0, c0] = stops[i - 1];
      const [q1, c1] = stops[i];
      return mixOklab(c0, c1, (q - q0) / (q1 - q0));
    }
  }
  return stops[stops.length - 1][1];
}

/** Colour for a Democratic win probability (theme aware). null → "no data" gray. */
export function probColor(p) {
  const dark = isDark();
  if (!isNum(p)) return dark ? '#2a2b30' : '#e9e9e6';
  const key = Math.round(clamp(p, 0, 1) * 200) / 200;
  const cache = dark ? colorCache.dark : colorCache.light;
  let c = cache.get(key);
  if (!c) {
    c = computeProbColor(key, dark ? STOPS_DARK : STOPS_LIGHT);
    cache.set(key, c);
  }
  return c;
}

/** Sample the scale for CSS gradients / legends. */
export function probGradient(steps = 11) {
  const cols = [];
  for (let i = 0; i < steps; i++) cols.push(probColor(i / (steps - 1)));
  return `linear-gradient(90deg, ${cols.join(', ')})`;
}

function luminance(hex) {
  const [r, g, b] = hexToRgb(hex).map(srgbToLinear);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
/** WCAG contrast ratio between two hex colours. */
export function contrast(a, b) {
  const la = luminance(a), lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}
/** Ink colour (white or near-black) that reads best on a given fill. */
export function textOn(bgHex) {
  const dark = '#141414', light = '#ffffff';
  return contrast(bgHex, light) >= contrast(bgHex, dark) ? light : dark;
}

/**
 * Paint an HTML element with the probability colour and matching ink.
 * Elements are remembered so they can be repainted when the OS theme flips.
 */
const painted = new Set();
export function paintProb(el, p) {
  const bg = probColor(p);
  el.style.background = bg;
  el.style.color = textOn(bg);
  el.dataset.p = isNum(p) ? String(p) : '';
  painted.add(el);
  return el;
}
function repaintAll() {
  for (const el of painted) {
    if (!el.isConnected) { painted.delete(el); continue; }
    const p = el.dataset.p === '' ? null : Number(el.dataset.p);
    paintProb(el, p);
  }
}

// ---------------------------------------------------------------------------
// 5. DOM / SVG builders
// ---------------------------------------------------------------------------

const SVG_NS = 'http://www.w3.org/2000/svg';

function applyAttrs(el, attrs) {
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.setAttribute('class', v);
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else el.setAttribute(k, v === true ? '' : String(v));
  }
}
function appendChildren(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}
/** h('div', {class:'x', onClick: fn}, 'text', child, [more]) — text is never parsed as HTML. */
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  applyAttrs(el, attrs);
  appendChildren(el, children);
  return el;
}
/** SVG-namespace twin of h(). */
export function svgEl(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  applyAttrs(el, attrs);
  appendChildren(el, children);
  return el;
}
export function clear(el) {
  el.replaceChildren();
  return el;
}

// ---------------------------------------------------------------------------
// 6. Scales, ticks, responsive charts
// ---------------------------------------------------------------------------

export function scaleLinear([d0, d1], [r0, r1]) {
  const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
  const f = (v) => r0 + (v - d0) * k;
  f.invert = (r) => (k === 0 ? d0 : d0 + (r - r0) / k);
  f.domain = [d0, d1];
  f.range = [r0, r1];
  return f;
}

/** "Nice" tick values covering [min, max]. */
export function niceTicks(min, max, count = 5) {
  const span = max - min;
  if (!(span > 0)) return [min];
  const step0 = span / Math.max(1, count);
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const err = step0 / mag;
  const step = mag * (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1);
  const out = [];
  for (let v = Math.ceil(min / step - 1e-9) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

/** Date ticks: up to `count` evenly spaced local-midnight dates between two timestamps. */
export function dateTicks(t0, t1, count = 5) {
  const days = Math.max(1, Math.round((t1 - t0) / 864e5));
  const stepDays = days <= count ? 1 : Math.ceil(days / count);
  const out = [];
  const d = new Date(t0);
  d.setHours(0, 0, 0, 0);
  if (d.getTime() < t0) d.setDate(d.getDate() + 1);
  while (d.getTime() <= t1 + 1) {
    out.push(d.getTime());
    d.setDate(d.getDate() + stepDays);
  }
  return out;
}

/**
 * Draw a chart into `container` at its current width and redraw on resize
 * or theme change. `draw(width)` returns a node.
 */
export function responsiveChart(container, draw, { minWidth = 160 } = {}) {
  let lastW = -1;
  let lastTheme = isDark();
  const render = (force) => {
    const w = Math.max(minWidth, Math.floor(container.clientWidth || 0));
    if (!force && w === lastW && lastTheme === isDark()) return;
    lastW = w;
    lastTheme = isDark();
    container.replaceChildren(draw(w));
  };
  render(true);
  if ('ResizeObserver' in window) {
    const ro = new ResizeObserver(() => render(false));
    ro.observe(container);
  } else {
    window.addEventListener('resize', () => render(false));
  }
  onThemeChange(() => render(true));
  return () => render(true);
}

// ---------------------------------------------------------------------------
// 7. Tooltip
// ---------------------------------------------------------------------------

let tipEl = null;
function ensureTip() {
  if (!tipEl) {
    tipEl = h('div', { class: 'tooltip', role: 'tooltip', hidden: true });
    document.body.append(tipEl);
  }
  return tipEl;
}
function positionTip(x, y) {
  const pad = 14;
  const r = tipEl.getBoundingClientRect();
  let left = x + pad, top = y + pad;
  if (left + r.width > window.innerWidth - 8) left = x - r.width - pad;
  if (top + r.height > window.innerHeight - 8) top = y - r.height - pad;
  tipEl.style.left = `${Math.max(4, left)}px`;
  tipEl.style.top = `${Math.max(4, top)}px`;
}
export const tooltip = {
  show(content, x, y) {
    ensureTip();
    tipEl.replaceChildren(...[content].flat(Infinity).filter(Boolean).map((c) => (c instanceof Node ? c : document.createTextNode(String(c)))));
    tipEl.hidden = false;
    positionTip(x, y);
  },
  move(x, y) {
    if (tipEl && !tipEl.hidden) positionTip(x, y);
  },
  hide() {
    if (tipEl) tipEl.hidden = true;
  },
};
/** Build a standard tooltip body: title + [label, value, keyColour?] rows. */
export function tipContent(title, rows = []) {
  const out = [];
  if (title) out.push(h('div', { class: 'tip-title' }, title));
  for (const [label, value, key] of rows) {
    out.push(
      h('div', { class: 'tip-row' },
        h('span', { class: 'k' }, key ? h('span', { class: 'tip-key', style: { background: key } }) : null, label),
        h('span', { class: 'v' }, value)),
    );
  }
  return out;
}
function pointOf(e, el) {
  if (e && e.type !== 'focus' && isNum(e.clientX)) return { x: e.clientX, y: e.clientY };
  const r = el.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}
/** Attach hover + keyboard-focus tooltips to an element. `contentFn()` returns nodes/strings. */
export function attachTooltip(el, contentFn) {
  const show = (e) => {
    const c = contentFn();
    if (!c) return;
    const { x, y } = pointOf(e, el);
    tooltip.show(c, x, y);
  };
  el.addEventListener('pointerenter', show);
  el.addEventListener('pointermove', (e) => tooltip.move(e.clientX, e.clientY));
  el.addEventListener('pointerleave', () => tooltip.hide());
  el.addEventListener('focus', show);
  el.addEventListener('blur', () => tooltip.hide());
}
/** Event-delegated tooltips for many small elements (e.g. 435 seat squares). */
export function delegateTooltip(container, selector, contentFn) {
  let current = null;
  const show = (e) => {
    const t = e.target.closest && e.target.closest(selector);
    if (!t || !container.contains(t)) return;
    if (t !== current || e.type === 'focusin') {
      current = t;
      const c = contentFn(t);
      if (!c) return;
      const { x, y } = pointOf(e, t);
      tooltip.show(c, x, y);
    } else if (isNum(e.clientX)) {
      tooltip.move(e.clientX, e.clientY);
    }
  };
  const hide = (e) => {
    const t = e.target.closest && e.target.closest(selector);
    if (t && t === current) { current = null; tooltip.hide(); }
  };
  container.addEventListener('pointerover', show);
  container.addEventListener('pointermove', show);
  container.addEventListener('pointerout', hide);
  container.addEventListener('focusin', show);
  container.addEventListener('focusout', hide);
}

// ---------------------------------------------------------------------------
// 8. Political helpers
// ---------------------------------------------------------------------------

export function partyVar(party) {
  return party === 'D' ? 'var(--dem)' : party === 'R' ? 'var(--rep)' : 'var(--ind)';
}
export function partyClass(party) {
  return party === 'D' ? 'dem' : party === 'R' ? 'rep' : 'ind';
}
export function partyName(party) {
  const map = { D: 'Democratic', R: 'Republican', I: 'Independent', L: 'Libertarian', G: 'Green', O: 'Other', NP: 'Nonpartisan', W: 'Write-in' };
  return map[party] || (party ? `Party ${party}` : 'Unknown party');
}

/** Normalise rater wording ("Solid R", "Toss-up", "Tilt D") to a canonical label. */
export function normalizeRating(str) {
  if (!str) return null;
  let s = String(str).trim().replace(/\s*\(.*?\)\s*/g, ' ').replace(/\s+/g, ' ').trim();
  s = s.replace(/^Solid/i, 'Safe').replace(/toss[- ]?up/i, 'Tossup');
  s = s.replace(/\b(Dem|Democrat|Democratic)\b/i, 'D').replace(/\b(Rep|Republican|GOP)\b/i, 'R');
  const m = /^(Safe|Likely|Lean|Tilt)\s*([DR])$/i.exec(s);
  if (m) return `${m[1][0].toUpperCase()}${m[1].slice(1).toLowerCase()} ${m[2].toUpperCase()}`;
  if (/^Tossup$/i.test(s)) return 'Tossup';
  return s;
}
const LABEL_P = {
  'Safe D': 0.985, 'Likely D': 0.88, 'Lean D': 0.7, 'Tilt D': 0.59, Tossup: 0.5,
  'Tilt R': 0.41, 'Lean R': 0.3, 'Likely R': 0.12, 'Safe R': 0.015,
};
/** Representative probability for a rating label (for colouring pills). */
export function ratingP(label) {
  const n = normalizeRating(label);
  return n in LABEL_P ? LABEL_P[n] : null;
}
/** A coloured rating pill. */
export function ratingPill(label, { title } = {}) {
  if (!label) return h('span', { class: 'muted' }, DASH);
  const el = h('span', { class: 'pill', title }, String(label));
  return paintProb(el, ratingP(label));
}
/** Small coloured probability chip (used in tables). */
export function probChip(p) {
  const el = h('span', { class: 'prob-chip num' }, fmt.pct(p));
  return paintProb(el, p);
}

export function lastName(name) {
  if (!name) return '';
  const cleaned = String(name).replace(/\s*\(.*?\)\s*/g, ' ').trim();
  const parts = cleaned.split(/\s+/).filter((t) => !/^(jr\.?|sr\.?|ii|iii|iv)$/i.test(t));
  return parts[parts.length - 1] || cleaned;
}

/** Inline candidate name with party and incumbent marker. */
export function candNode(c, { short = false } = {}) {
  if (!c || !c.name) return h('span', { class: 'muted' }, 'No candidate');
  return h('span', { class: 'cand' },
    h('span', { class: `party-dot ${partyClass(c.party)}`, 'aria-hidden': 'true' }),
    short ? lastName(c.name) : c.name,
    ` (${c.party || '?'})`,
    c.incumbent ? h('abbr', { class: 'inc', title: 'Incumbent' }, '†') : null,
  );
}
/** "Ossoff (D)† vs Collins (R)" for tables and cards. */
export function matchupNode(race, opts = {}) {
  const parts = [];
  if (race.dem) parts.push(candNode(race.dem, opts));
  if (race.rep) parts.push(candNode(race.rep, opts));
  if (!parts.length) return h('span', { class: 'muted' }, DASH);
  const out = h('span', { class: 'matchup' });
  parts.forEach((p, i) => {
    if (i) out.append(h('span', { class: 'vs' }, ' vs '));
    out.append(p);
  });
  if (race.uncontested) out.append(h('span', { class: 'muted small' }, ' (uncontested)'));
  return out;
}
/** Seat holder description: "Jon Ossoff (D)", "Open (R)", "Vacant". */
export function holderNode(race) {
  const party = race.holder_party || race.incumbent_party;
  if (!race.incumbent) return h('span', { class: 'muted' }, party ? `Vacant (${party})` : 'Vacant');
  const el = h('span', {}, h('span', { class: `party-dot ${partyClass(party)}`, 'aria-hidden': 'true' }), race.incumbent, party ? ` (${party})` : '');
  if (race.open_seat || race.incumbent_running === false) el.append(h('span', { class: 'muted' }, ' · open'));
  return el;
}

// ---------------------------------------------------------------------------
// 9. Page chrome
// ---------------------------------------------------------------------------

/** Fill the brand name, propagate the data parameter to nav links, mark the current page. */
export function initChrome({ current } = {}) {
  document.querySelectorAll('[data-site-name]').forEach((el) => { el.textContent = SITE_NAME; });
  if (document.title.includes('Midterm Model 2026')) document.title = document.title.replace('Midterm Model 2026', SITE_NAME);
  document.querySelectorAll('a[data-nav]').forEach((a) => {
    a.setAttribute('href', withData(a.getAttribute('href')));
    if (current && a.dataset.nav === current) a.setAttribute('aria-current', 'page');
  });
  mountThemeToggle(document.querySelector('.topbar-inner'));
}

/** "Updated 3 hours ago · 42 days to Nov 3, 2026" in the top bar. */
export function renderUpdated(summary) {
  const el = document.querySelector('[data-updated]');
  if (!el || !summary) return;
  const electionDate = summary.election_date || ELECTION_DATE;
  const days = isNum(summary.days_to_election) ? summary.days_to_election : daysUntil(electionDate);
  const dayText = !isNum(days) ? `Election ${fmt.date(electionDate)}`
    : days === 0 ? `Election Day is today`
    : days < 0 ? `${-days} days since ${fmt.date(electionDate)}`
    : `${days} day${days === 1 ? '' : 's'} to ${fmt.date(electionDate)}`;
  el.replaceChildren(
    h('span', { title: fmt.dateTime(summary.generated_at) }, `Updated ${relativeTime(summary.generated_at)}`),
    h('span', { class: 'sep', 'aria-hidden': 'true' }, '·'),
    h('span', {}, dayText),
  );
}

export function renderFooterMeta(summary) {
  const el = document.querySelector('[data-generated]');
  if (el && summary) el.textContent = `Generated ${fmt.dateTime(summary.generated_at)}`;
}

/** Replace a container's content with a readable error panel. */
export function showError(container, err, hint) {
  if (!container) return;
  container.hidden = false;
  container.replaceChildren(
    h('div', { class: 'error', role: 'alert' },
      h('strong', {}, 'Could not load the forecast data. '),
      h('span', {}, err && err.message ? err.message : String(err)),
      hint ? h('div', { class: 'muted small', style: { marginTop: '6px' } }, hint) : null),
  );
}
