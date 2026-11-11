import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MAX_TEAMS, parseTeamNames, coachCalls, teamsWithoutCoach, rosterProgress,
} from '../../offdays/web/static/setup_flow.js';

test('team names split on lines, commas and semicolons, and are tidied', () => {
  const r = parseTeamNames('2031 Red\n  2031   Blue \r\n2032 Red, 2032 Blue;U10');
  assert.deepEqual(r.names, ['2031 Red', '2031 Blue', '2032 Red', '2032 Blue', 'U10']);
  assert.deepEqual(r.left, []);
});

test('blank lines are ignored, not reported', () => {
  const r = parseTeamNames('\n\n  \n2031 Red\n\n');
  assert.deepEqual(r.names, ['2031 Red']);
  assert.deepEqual(r.left, []);
});

test('a name the program already has is left out, whatever its case, and says why', () => {
  const r = parseTeamNames('2031 red\n2032 Red', ['2031 Red']);
  assert.deepEqual(r.names, ['2032 Red']);
  assert.equal(r.left.length, 1);
  assert.match(r.left[0].why, /already a team/);
});

test('a name listed twice is made once, and the repeat says so', () => {
  const r = parseTeamNames('2031 Red\n2031 RED');
  assert.deepEqual(r.names, ['2031 Red']);
  assert.match(r.left[0].why, /twice/);
});

test('more than the cap is left for a second pass, in order', () => {
  const text = Array.from({ length: MAX_TEAMS + 3 }, (_, i) => `Team ${i}`).join('\n');
  const r = parseTeamNames(text);
  assert.equal(r.names.length, MAX_TEAMS);
  assert.equal(r.names[0], 'Team 0');
  assert.equal(r.left.length, 3);
  assert.match(r.left[0].why, /second pass/);
});

test('an absurdly long name is refused, not created', () => {
  const r = parseTeamNames('x'.repeat(121));
  assert.deepEqual(r.names, []);
  assert.match(r.left[0].why, /too long/);
});

test('nothing in, nothing out', () => {
  assert.deepEqual(parseTeamNames(''), { names: [], left: [] });
  assert.deepEqual(parseTeamNames(null), { names: [], left: [] });
});

test('one coach on three teams is one person with three teams', () => {
  const { calls, problems } = coachCalls([
    { team_id: 1, name: 'Sam Hill', email: 'Sam@Example.com' },
    { team_id: 2, name: 'Sam Hill', email: 'sam@example.com ' },
    { team_id: 3, name: 'Pat Roe', email: 'pat@example.com' },
    { team_id: 4, name: 'S. Hill', email: 'sam@example.com' },
  ]);
  assert.deepEqual(problems, []);
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[0], { display_name: 'Sam Hill', email: 'sam@example.com', team_ids: [1, 2, 4] });
  assert.deepEqual(calls[1].team_ids, [3]);
});

test('two different emails with the same name stay two people', () => {
  const { calls } = coachCalls([
    { team_id: 1, name: 'Alex Kim', email: 'a@example.com' },
    { team_id: 2, name: 'Alex Kim', email: 'b@example.com' },
  ]);
  assert.equal(calls.length, 2);
});

test('an empty row is a team left for later, not a mistake', () => {
  const { calls, problems } = coachCalls([{ team_id: 1, name: '', email: '' }, { team_id: 2, name: ' ', email: ' ' }]);
  assert.deepEqual(calls, []);
  assert.deepEqual(problems, []);
});

test('a half-filled row says what to add, and is not sent', () => {
  const { calls, problems } = coachCalls([
    { team_id: 1, name: 'Sam', email: '' },
    { team_id: 2, name: '', email: 'x@example.com' },
    { team_id: 3, name: 'Pat', email: 'not-an-email' },
  ]);
  assert.deepEqual(calls, []);
  assert.deepEqual(problems.map((p) => p.team_id), [1, 2, 3]);
  assert.match(problems[0].why, /Add the coach.s email/);
  assert.match(problems[1].why, /Add the coach.s name/);
  assert.match(problems[2].why, /look right/);
});

test('one bad row does not stop the good ones', () => {
  const { calls, problems } = coachCalls([
    { team_id: 1, name: 'Sam', email: '' },
    { team_id: 2, name: 'Pat', email: 'pat@example.com' },
  ]);
  assert.equal(calls.length, 1);
  assert.equal(problems.length, 1);
});

test('teams without a coach are the ones with an empty coach list', () => {
  const t = [{ id: 1, coaches: 'Sam Hill' }, { id: 2, coaches: '' }, { id: 3, coaches: null }, { id: 4 }, { id: 5, coaches: '  ' }];
  assert.deepEqual(teamsWithoutCoach(t).map((x) => x.id), [2, 3, 4, 5]);
});

test('roster progress reads as a sentence', () => {
  assert.equal(rosterProgress([]), 'Add a team first.');
  assert.equal(rosterProgress([{ roster: 0 }, { roster: 12 }, { roster: 3 }]), '2 of 3 teams have players.');
  assert.equal(rosterProgress([{ roster: 5 }, { roster: 1 }]), 'All 2 teams have players.');
});
