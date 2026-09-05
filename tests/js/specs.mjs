// The drill specs, as the browser receives them.
//
// These used to come only from a DRILL_SPECS environment variable. That worked
// until the catalog passed 128KB of JSON, which is Linux's per-variable ceiling
// (MAX_ARG_STRLEN) -- at 98 drills the documented test command started failing
// with "Argument list too long", and would have kept failing for every drill
// added after. The variable still works when it fits; a file works at any size.
import { readFileSync } from 'node:fs';

function load() {
  const file = process.env.DRILL_SPECS_FILE;
  if (file) return readFileSync(file, 'utf8');
  const inline = process.env.DRILL_SPECS;
  if (inline) return inline;
  throw new Error(
    'No drill specs. Set DRILL_SPECS_FILE to a JSON file (see README), '
    + 'or DRILL_SPECS inline for a catalog small enough to fit in an env var.');
}

export const SPECS = JSON.parse(load());
