/**
 * Typing a roster in by hand.
 *
 * The page shows one block per player. This module is everything that is not drawing: what a row is,
 * what is wrong with one, how pasted spreadsheet cells become rows, and how the rows become the CSV the
 * server's own roster importer already reads. There is deliberately no second way in: the CSV goes to the
 * same preview and the same import as an uploaded file, so duplicates, the no-parent warning, invites, the
 * parent's contact, the funnel and billing-from-the-day-they-joined all behave exactly as they do for a file.
 */

/** The columns, in the order a spreadsheet would have them. `header` is what the importer recognises. */
export const COLUMNS = [
  { key: 'first', header: 'First Name' },
  { key: 'last', header: 'Last Name' },
  { key: 'year', header: 'Birth Year' },
  { key: 'email', header: 'Parent Email' },
  { key: 'phone', header: 'Parent Phone' },
  { key: 'jersey', header: 'Jersey #' },
  { key: 'position', header: 'Position' },
];

/** Most rows one paste or one import will take. A bigger roster is a file. */
export const MAX_ROWS = 300;

export function blankRow() {
  const row = {};
  for (const c of COLUMNS) row[c.key] = '';
  return row;
}

const clean = (v) => String(v == null ? '' : v).replace(/[\r\n\t]+/g, ' ').trim();

export function isBlank(row) {
  return COLUMNS.every((c) => !clean(row[c.key]));
}

/**
 * What is wrong with this row, in a sentence a coach can act on, or '' if nothing. A row with nothing in it is
 * not wrong, it is empty, and is ignored. `now` is the current year, a parameter so tests do not age.
 */
export function rowProblem(row, now = new Date().getFullYear()) {
  if (isBlank(row)) return '';
  const first = clean(row.first), last = clean(row.last);
  if (!first || !last) return 'Add a first and a last name.';
  const year = clean(row.year);
  if (year) {
    if (!/^(19|20)\d{2}$/.test(year)) return 'Birth year is four digits, like 2013.';
    if (Number(year) > now) return 'That birth year has not happened yet.';
  }
  const email = clean(row.email);
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return 'That parent email does not look right.';
  const phone = clean(row.phone);
  if (phone && phone.replace(/\D/g, '').length < 7) return 'That parent phone number is too short.';
  return '';
}

/** The rows that will actually be sent: not empty. Order kept. */
export function filledRows(rows) {
  return rows.filter((r) => !isBlank(r));
}

/** First row that has a problem, as { index, message }, or null. Index is into `rows`. */
export function firstProblem(rows, now) {
  for (let i = 0; i < rows.length; i += 1) {
    const message = rowProblem(rows[i], now);
    if (message) return { index: i, message };
  }
  return null;
}

/** How many of the filled rows have no parent email. A player gets in through a link their parent sends, so these cannot start. */
export function withoutParent(rows) {
  return filledRows(rows).filter((r) => !clean(r.email)).length;
}

const quote = (v) => `"${clean(v).replace(/"/g, '""')}"`;

/** The CSV the importer reads: the header row, then one line per filled row, every cell quoted. */
export function buildCsv(rows) {
  const lines = [COLUMNS.map((c) => quote(c.header)).join(',')];
  for (const r of filledRows(rows)) lines.push(COLUMNS.map((c) => quote(r[c.key])).join(','));
  return lines.join('\n');
}

// ---------------------------------------------------------------------------------------------- pasting

const HEADER_WORDS = [
  ['first', /^(first|given|forename)(\s*name)?$/i],
  ['last', /^(last|family|sur)\s*name$|^(last|surname)$/i],
  ['name', /^(player|athlete|participant)?\s*name$|^full\s*name$/i],
  ['year', /(birth\s*year|^year$|^born$|^dob$|birth\s*date|^grad)/i],
  ['email', /(e-?mail)/i],
  ['phone', /(phone|mobile|cell)/i],
  ['jersey', /(jersey|number|^no\.?$|^#$)/i],
  ['position', /^pos(ition)?$/i],
];

function headerKey(cell) {
  const text = clean(cell);
  for (const [key, pattern] of HEADER_WORDS) if (pattern.test(text)) return key;
  return null;
}

function splitLine(line) {
  if (line.includes('\t')) return line.split('\t');
  // A pasted CSV line. Quoted commas stay together.
  const cells = [];
  let cur = '', inQuote = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (inQuote) {
      if (ch === '"' && line[i + 1] === '"') { cur += '"'; i += 1; }
      else if (ch === '"') inQuote = false;
      else cur += ch;
    } else if (ch === '"') inQuote = true;
    else if (ch === ',') { cells.push(cur); cur = ''; }
    else cur += ch;
  }
  cells.push(cur);
  return cells;
}

/**
 * Turn pasted text (from a spreadsheet, an email, a notes app) into rows.
 *
 * - Tabs mean a spreadsheet; otherwise commas are read as CSV.
 * - A first line that names columns ("First Name", "Parent Email"...) says which cell is which, in any order.
 *   Without one, cells are taken in the page's own order.
 * - A single "Full Name" cell is split on its last space ("Sam O'Brien" -> Sam / O'Brien). Names are never
 *   guessed at beyond that, and the preview shows the coach what was understood.
 * - Blank lines are skipped. At most MAX_ROWS rows.
 */
export function parsePaste(text) {
  const lines = String(text || '').split(/\r?\n/).filter((l) => l.trim());
  if (!lines.length) return [];
  let order = COLUMNS.map((c) => c.key);
  let body = lines;
  const firstCells = splitLine(lines[0]);
  const keys = firstCells.map(headerKey);
  // A header row is one where at least half the cells are recognised as column names (so a lone "Name" counts).
  if (keys.filter(Boolean).length >= Math.max(1, Math.ceil(firstCells.length / 2))) {
    order = keys;
    body = lines.slice(1);
  }
  const rows = [];
  for (const line of body.slice(0, MAX_ROWS)) {
    const cells = splitLine(line);
    const row = blankRow();
    cells.forEach((cell, i) => {
      const key = order[i];
      const value = clean(cell);
      if (!key || !value) return;
      if (key === 'name') {
        const at = value.lastIndexOf(' ');
        if (at > 0) { row.first = value.slice(0, at).trim(); row.last = value.slice(at + 1).trim(); }
        else row.first = value;
      } else row[key] = value;
    });
    if (!isBlank(row)) rows.push(row);
  }
  return rows;
}

/** Merge pasted rows into the page's rows starting at `at`: fills empty rows first, then adds more, never past MAX_ROWS. */
export function mergePasted(rows, pasted, at = 0) {
  const out = rows.map((r) => ({ ...r }));
  let i = Math.max(0, at);
  for (const p of pasted) {
    while (i < out.length && !isBlank(out[i])) i += 1;
    if (i >= out.length) { if (out.length >= MAX_ROWS) break; out.push(blankRow()); }
    out[i] = { ...p };
    i += 1;
  }
  return out;
}
