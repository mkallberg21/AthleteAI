/**
 * The director's one-step-at-a-time setup: the parts that are not drawing.
 *
 * A program with a dozen teams should not create a dozen teams one form at a time. Two steps take many at once:
 *
 *   1. Teams: one name per line (or separated by commas or semicolons). `parseTeamNames` turns that text into the
 *      names to create, and says plainly which lines it left out and why.
 *   2. Coaches: one row per team that has no coach, with a name and an email. `coachCalls` groups the rows by email,
 *      because one person who coaches three teams is one person with one sign-in, not three.
 *
 * Nothing here talks to the server. The page sends each result through the routes the one-team form already uses
 * (POST /api/teams, POST /api/coach/staff), so a team made here is exactly a team made there.
 */

/** Most teams one paste will take. A larger club adds the rest in a second pass. */
export const MAX_TEAMS = 60;

const squash = (v) => String(v == null ? '' : v).replace(/[\r\n\t]+/g, ' ').replace(/\s+/g, ' ').trim();
const key = (v) => squash(v).toLowerCase();

/**
 * Names to create from pasted text.
 * @param {string} text what the director typed or pasted
 * @param {string[]} existing names the program already has (compared without case)
 * @returns {{names: string[], left: {text: string, why: string}[]}}
 */
export function parseTeamNames(text, existing = []) {
  const seen = new Set(existing.map(key));
  const names = [];
  const left = [];
  const pieces = String(text == null ? '' : text).split(/[\r\n,;]+/);
  for (const piece of pieces) {
    const name = squash(piece);
    if (!name) continue;
    if (name.length > 120) { left.push({ text: name.slice(0, 40) + '\u2026', why: 'too long for a team name' }); continue; }
    if (seen.has(key(name))) {
      left.push({ text: name, why: existing.map(key).includes(key(name)) ? 'already a team in this program' : 'listed twice' });
      continue;
    }
    if (names.length >= MAX_TEAMS) { left.push({ text: name, why: `over ${MAX_TEAMS} teams at a time; add it in a second pass` }); continue; }
    seen.add(key(name));
    names.push(name);
  }
  return { names, left };
}

const looksLikeEmail = (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v);

/**
 * The coach accounts to create from the coach rows.
 * @param {{team_id:number, team_name?:string, name:string, email:string}[]} rows one per team, as typed
 * @returns {{calls: {display_name:string, email:string, team_ids:number[]}[], problems: {team_id:number, why:string}[]}}
 *   `calls` is one entry per person; `problems` are rows that cannot be used yet, each with what to fix.
 */
export function coachCalls(rows) {
  const byEmail = new Map();
  const calls = [];
  const problems = [];
  for (const r of rows || []) {
    const name = squash(r.name);
    const email = squash(r.email).toLowerCase();
    if (!name && !email) continue;                          // an empty row is a team left for later, not a mistake
    if (!name) { problems.push({ team_id: r.team_id, why: 'Add the coach\u2019s name.' }); continue; }
    if (!email) { problems.push({ team_id: r.team_id, why: 'Add the coach\u2019s email, so their sign-in link can reach them.' }); continue; }
    if (!looksLikeEmail(email)) { problems.push({ team_id: r.team_id, why: 'That email does not look right.' }); continue; }
    if (byEmail.has(email)) {
      const call = byEmail.get(email);
      if (!call.team_ids.includes(r.team_id)) call.team_ids.push(r.team_id);
      continue;
    }
    const call = { display_name: name, email, team_ids: [r.team_id] };
    byEmail.set(email, call);
    calls.push(call);
  }
  return { calls, problems };
}

/** Teams that still need a coach, for the "n of m have a coach" line and for deciding whether the step is done. */
export function teamsWithoutCoach(teams) {
  return (teams || []).filter((t) => !squash(t.coaches));
}

/** The one sentence under the step bar for the roster step: how many teams have players. */
export function rosterProgress(teams) {
  const all = teams || [];
  const filled = all.filter((t) => Number(t.roster) > 0).length;
  if (!all.length) return 'Add a team first.';
  if (filled === all.length) return `All ${all.length} teams have players.`;
  return `${filled} of ${all.length} teams have players.`;
}
