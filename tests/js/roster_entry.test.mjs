/**
 * Typing a roster in by hand: what a row is, what is wrong with one, how a paste becomes rows, and the CSV
 * that goes to the same importer an uploaded file uses.
 *
 * Every test here is a way a coach's own typing goes wrong: a name with an apostrophe or a comma, a phone
 * number in the year box, a paste from a spreadsheet with its header row in any order, a name in one cell.
 */
import assert from 'node:assert';
import { test } from 'node:test';
import {
  COLUMNS, MAX_ROWS, blankRow, isBlank, rowProblem, filledRows, firstProblem, withoutParent,
  buildCsv, parsePaste, mergePasted,
} from '../../offdays/web/static/roster_entry.js';

const row = (o = {}) => ({ ...blankRow(), ...o });
const NOW = 2026;

test('a blank row is empty, not wrong', () => {
  assert.equal(isBlank(blankRow()), true);
  assert.equal(rowProblem(blankRow(), NOW), '');
  assert.equal(isBlank(row({ first: '   ' })), true, 'spaces are nothing');
});

test('a row with anything in it needs both names', () => {
  assert.match(rowProblem(row({ first: 'Sam' }), NOW), /first and a last name/);
  assert.match(rowProblem(row({ last: 'Lee' }), NOW), /first and a last name/);
  assert.match(rowProblem(row({ email: 'a@b.co' }), NOW), /first and a last name/);
  assert.equal(rowProblem(row({ first: 'Sam', last: 'Lee' }), NOW), '');
});

test('birth year: four digits, and not in the future', () => {
  const ok = { first: 'Sam', last: 'Lee' };
  assert.equal(rowProblem(row({ ...ok, year: '2013' }), NOW), '');
  assert.equal(rowProblem(row({ ...ok, year: '' }), NOW), '', 'no year is allowed: the preview warns');
  for (const bad of ['13', '20133', 'abc', '1899', '2o13']) assert.match(rowProblem(row({ ...ok, year: bad }), NOW), /four digits/, bad);
  assert.match(rowProblem(row({ ...ok, year: '2027' }), NOW), /not happened yet/);
  assert.equal(rowProblem(row({ ...ok, year: '2026' }), NOW), '');
});

test('parent email and phone are checked loosely, not strictly', () => {
  const ok = { first: 'Sam', last: 'Lee' };
  for (const good of ['pat@example.com', 'pat.o+club@mail.example.org', 'a@b.co']) assert.equal(rowProblem(row({ ...ok, email: good }), NOW), '', good);
  for (const bad of ['pat', 'pat@', '@example.com', 'pat@example', 'pat @example.com']) assert.match(rowProblem(row({ ...ok, email: bad }), NOW), /parent email/, bad);
  assert.equal(rowProblem(row({ ...ok, phone: '(615) 555-0101' }), NOW), '');
  assert.equal(rowProblem(row({ ...ok, phone: '615.555.0101' }), NOW), '');
  assert.match(rowProblem(row({ ...ok, phone: '555' }), NOW), /too short/);
});

test('the first problem names the row, so the page can point at it', () => {
  const rows = [row({ first: 'A', last: 'B' }), blankRow(), row({ first: 'C' }), row({ first: 'D', last: 'E', year: '9' })];
  const p = firstProblem(rows, NOW);
  assert.equal(p.index, 2);
  assert.equal(firstProblem([row({ first: 'A', last: 'B' }), blankRow()], NOW), null);
});

test('blank rows are not sent, and order is kept', () => {
  const rows = [row({ first: 'A', last: 'A' }), blankRow(), row({ first: 'B', last: 'B' }), blankRow()];
  assert.deepEqual(filledRows(rows).map((r) => r.first), ['A', 'B']);
});

test('it counts the players nobody can invite', () => {
  const rows = [row({ first: 'A', last: 'A', email: 'a@b.co' }), row({ first: 'B', last: 'B' }), blankRow(), row({ first: 'C', last: 'C', email: '  ' })];
  assert.equal(withoutParent(rows), 2);
});

// ---------------------------------------------------------------------------------------- the CSV

function csvCells(line) {
  // a strict reader: every cell quoted, "" is a quote. Enough to prove the output round-trips.
  const cells = [];
  let i = 0;
  while (i < line.length) {
    assert.equal(line[i], '"', `cell must start with a quote at ${i} in ${line}`);
    i += 1;
    let cur = '';
    for (;;) {
      if (line[i] === '"' && line[i + 1] === '"') { cur += '"'; i += 2; }
      else if (line[i] === '"') { i += 1; break; }
      else { cur += line[i]; i += 1; }
    }
    cells.push(cur);
    if (line[i] === ',') i += 1;
  }
  return cells;
}

test('the CSV has the importer\'s header row and one line per filled row', () => {
  const csv = buildCsv([row({ first: 'Sam', last: 'Lee', year: '2013' }), blankRow()]);
  const lines = csv.split('\n');
  assert.equal(lines.length, 2);
  assert.deepEqual(csvCells(lines[0]), COLUMNS.map((c) => c.header));
  assert.deepEqual(csvCells(lines[1]).slice(0, 3), ['Sam', 'Lee', '2013']);
});

test('names with apostrophes, commas, quotes and accents survive the round trip', () => {
  const names = [["Sam", "O'Brien"], ['Lee', 'Smith, Jr.'], ['Ana', 'García-Núñez'], ['Jo', 'Say "Hi"'], ['Zoë', 'Müller'], ['李', '雷']];
  const csv = buildCsv(names.map(([first, last]) => row({ first, last })));
  const back = csv.split('\n').slice(1).map(csvCells);
  assert.deepEqual(back.map((c) => [c[0], c[1]]), names);
});

test('a newline or tab typed into a cell cannot break a line', () => {
  const csv = buildCsv([row({ first: 'Sam\nX', last: 'Lee\tY' })]);
  assert.equal(csv.split('\n').length, 2);
  assert.deepEqual(csvCells(csv.split('\n')[1]).slice(0, 2), ['Sam X', 'Lee Y']);
});

test('an empty roster is just the header, never a crash', () => {
  assert.equal(buildCsv([blankRow(), blankRow()]).split('\n').length, 1);
});

// ---------------------------------------------------------------------------------------- pasting

test('a spreadsheet paste (tabs) in the page\'s own order', () => {
  const rows = parsePaste("Sam\tO'Brien\t2013\tpat@example.com\t615-555-0101\t7\tAttack\nAna\tLopez\t2014\t\t\t\t");
  assert.equal(rows.length, 2);
  assert.deepEqual(rows[0], { first: 'Sam', last: "O'Brien", year: '2013', email: 'pat@example.com', phone: '615-555-0101', jersey: '7', position: 'Attack' });
  assert.equal(rows[1].first, 'Ana');
  assert.equal(rows[1].email, '');
});

test('a header row says which cell is which, in any order', () => {
  const rows = parsePaste('Parent Email\tLast Name\tFirst Name\tBirth Year\nlee@example.com\tLee\tSam\t2013');
  assert.deepEqual(rows, [row({ first: 'Sam', last: 'Lee', year: '2013', email: 'lee@example.com' })]);
});

test('real export headers are understood', () => {
  const rows = parsePaste('Participant Name\tParent Cell\tParent E-mail\tJersey Number\tPos\nSam Lee\t615-555-0101\tp@e.co\t12\tMidfield');
  assert.equal(rows.length, 1);
  assert.deepEqual([rows[0].first, rows[0].last, rows[0].phone, rows[0].email, rows[0].jersey, rows[0].position],
    ['Sam', 'Lee', '615-555-0101', 'p@e.co', '12', 'Midfield']);
});

test('a lone full name is split on its last space', () => {
  const rows = parsePaste('Name\nSam O\'Brien\nMary Ann Smith\nCher');
  assert.deepEqual(rows.map((r) => [r.first, r.last]), [['Sam', "O'Brien"], ['Mary Ann', 'Smith'], ['Cher', '']]);
});

test('a pasted CSV with quoted commas keeps them together', () => {
  const rows = parsePaste('First Name,Last Name,Parent Email\nLee,"Smith, Jr.",lee@example.com');
  assert.equal(rows[0].last, 'Smith, Jr.');
  assert.equal(rows[0].email, 'lee@example.com');
});

test('blank lines, spaces and windows line endings are harmless', () => {
  const rows = parsePaste('\r\nSam\tLee\r\n\r\n   \r\nAna\tLopez\r\n');
  assert.deepEqual(rows.map((r) => r.first), ['Sam', 'Ana']);
});

test('a header row alone gives nothing, and nothing gives nothing', () => {
  assert.deepEqual(parsePaste('First Name\tLast Name\tParent Email'), []);
  assert.deepEqual(parsePaste(''), []);
  assert.deepEqual(parsePaste(null), []);
});

test('a single column of first names is not mistaken for a header', () => {
  const rows = parsePaste('Sam\nAna');
  assert.deepEqual(rows.map((r) => r.first), ['Sam', 'Ana']);
});

test('a paste is capped, so a huge clipboard cannot freeze the page', () => {
  const text = Array.from({ length: MAX_ROWS + 50 }, (_, i) => `P${i}\tX`).join('\n');
  assert.equal(parsePaste(text).length, MAX_ROWS);
});

test('pasted cells that match nothing are dropped, not misfiled', () => {
  const rows = parsePaste('Sam\tLee\t2013\ta@b.co\t6155550101\t7\tAttack\tEXTRA\tMORE');
  assert.equal(rows.length, 1);
  assert.deepEqual(Object.keys(rows[0]).sort(), COLUMNS.map((c) => c.key).sort());
});

// ---------------------------------------------------------------------------------------- merging

test('a paste fills the empty rows first, then adds more', () => {
  const rows = [row({ first: 'Keep', last: 'Me' }), blankRow(), blankRow()];
  const merged = mergePasted(rows, [row({ first: 'A', last: 'A' }), row({ first: 'B', last: 'B' }), row({ first: 'C', last: 'C' })], 0);
  assert.deepEqual(merged.map((r) => r.first), ['Keep', 'A', 'B', 'C']);
});

test('a paste never overwrites a player already typed in', () => {
  const rows = [row({ first: 'One', last: '1' }), row({ first: 'Two', last: '2' })];
  const merged = mergePasted(rows, [row({ first: 'New', last: 'N' })], 0);
  assert.deepEqual(merged.map((r) => r.first), ['One', 'Two', 'New']);
});

test('merging does not change the rows it was given', () => {
  const rows = [blankRow()];
  mergePasted(rows, [row({ first: 'A', last: 'A' })], 0);
  assert.equal(isBlank(rows[0]), true);
});

test('merging stops at the cap', () => {
  const full = Array.from({ length: MAX_ROWS }, (_, i) => row({ first: `P${i}`, last: 'X' }));
  assert.equal(mergePasted(full, [row({ first: 'Over', last: 'Flow' })], 0).length, MAX_ROWS);
});
