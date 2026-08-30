"""SQLite storage layer.

Deliberately stdlib-only (`sqlite3`) -- no ORM. The schema is small and the
queries are mostly aggregations, so an ORM would add a dependency and a layer
of indirection without buying much. Swapping to Postgres later means changing
this module and nothing else.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import CONFIG

SCHEMA_VERSION = 13

SCHEMA = """
PRAGMA foreign_keys = ON;

-- A program: a club, school athletic department, or organization.
CREATE TABLE IF NOT EXISTS organizations (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    sport       TEXT NOT NULL DEFAULT 'lacrosse',
    -- Age at which position-specific training guidance switches on. Below it,
    -- every athlete gets the general-athlete drill mix regardless of the
    -- position on their jersey.
    --
    -- Defaults to 15 because early single-sport, single-role specialisation is
    -- the pattern youth sports medicine warns about most consistently, and a
    -- twelve-year-old labelled a goalie who then trains only goalie work is
    -- how that starts. It is a program setting rather than a constant because
    -- the right answer differs between a rec league and a high-school program,
    -- and that call belongs to the director, not to us. Set above the oldest
    -- band (99) to keep every athlete on the general mix permanently.
    position_emphasis_min_age INTEGER NOT NULL DEFAULT 15,
    -- Where the program is in its year. Scales the self-directed weekly
    -- budget, because the age bands know how old a child is and not whether
    -- it is February. In-season the figure goes *down*: these budgets have
    -- only ever counted work on top of team practice, and in-season there is
    -- already a lot of that. Chosen, never inferred -- sports do not share a
    -- season, and a wrong guess quietly changes what every child is told.
    season_phase TEXT NOT NULL DEFAULT 'preseason',
    -- A senior figure in the program whose recognition carries extra weight --
    -- a director of player development, a former professional. Optional, and
    -- absent means every message comes from the athlete's own coach.
    voice_name  TEXT NOT NULL DEFAULT '',
    voice_title TEXT NOT NULL DEFAULT '',
    -- Whether this org is a club or school ('program') or one family running
    -- the app for their own children ('family').
    kind        TEXT NOT NULL DEFAULT 'program',
    -- Family accounts only. Off by default: ranking a nine-year-old against
    -- their thirteen-year-old sibling says nothing except which is older.
    -- A parent can turn it on, because parents know their own children.
    sibling_compare INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
    id          INTEGER PRIMARY KEY,
    org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    season      TEXT NOT NULL DEFAULT '',
    -- Athletes self-serve onboarding with this code; no email needed, which
    -- matters when the athletes are 12 and do not have school email.
    join_code   TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_teams_org ON teams(org_id);

CREATE TABLE IF NOT EXISTS users (
    id               INTEGER PRIMARY KEY,
    org_id           INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL CHECK (role IN ('athlete','coach','director','guardian')),
    display_name     TEXT NOT NULL,
    email            TEXT,
    birth_year       INTEGER,
    -- Timestamp of recorded guardian consent. NULL for a minor means their
    -- name is withheld from shared leaderboards.
    guardian_consent_at TEXT,
    -- Athlete's stated dominant hand, so the scorer knows which side is the
    -- off-hand rather than assuming right.
    dominant_hand    TEXT CHECK (dominant_hand IN ('left','right')),
    -- Preferred language. Per person rather than per program: a
    -- Spanish-speaking household inside an English-speaking club is the
    -- common case, and a consent screen somebody cannot read is not consent.
    locale           TEXT NOT NULL DEFAULT 'en',
    token_hash       TEXT NOT NULL UNIQUE,
    created_at       TEXT NOT NULL,
    active           INTEGER NOT NULL DEFAULT 1,
    -- Identifier from whatever system the roster came out of (TeamSnap,
    -- SportsEngine, a school SIS). Present only when the import file carried
    -- one; it is what makes re-importing an edited file update rather than
    -- duplicate.
    external_id      TEXT,
    -- Short code an athlete types once to claim their account. A bulk import
    -- creates hundreds of logins at once and a token shown once on screen is
    -- unusable at that scale -- the coach prints a sheet of these instead.
    claim_code_hash  TEXT UNIQUE,
    claim_expires_at TEXT,
    -- True when birth year was estimated from a grade column rather than
    -- given. Estimates are treated as minors, never as adults.
    birth_year_estimated INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_users_external ON users(org_id, external_id);
CREATE INDEX IF NOT EXISTS idx_users_org_role ON users(org_id, role);
CREATE INDEX IF NOT EXISTS idx_users_token ON users(token_hash);

CREATE TABLE IF NOT EXISTS team_members (
    team_id     INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    jersey      TEXT,
    position    TEXT,
    joined_at   TEXT NOT NULL,
    PRIMARY KEY (team_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_team_members_user ON team_members(user_id);

-- The other sports an athlete plays. Drives how cautious the specialisation
-- gate is and how much solo training the weekly budget expects: a kid playing
-- three sports is already moving plenty, and none of that shows up here.
--
-- Seasons rather than hours, because a twelve-year-old can answer "which
-- seasons do you play basketball" and cannot answer "how many hours a year".
CREATE TABLE IF NOT EXISTS athlete_sports (
    athlete_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sport       TEXT NOT NULL,
    -- Comma-joined subset of fall/winter/spring/summer, normalised on write.
    seasons     TEXT NOT NULL DEFAULT '',
    is_primary  INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (athlete_id, sport)
);
CREATE INDEX IF NOT EXISTS idx_athlete_sports ON athlete_sports(athlete_id);

-- A daily "how do you feel". Deliberately one row and one word: a check-in a
-- kid completes in two taps gets completed, and a six-question wellness
-- questionnaire gets clicked through at random.
--
-- Counts toward a streak exactly as a recovery day does. An athlete who loses
-- something by reporting soreness stops reporting soreness, and the data then
-- becomes a record saying everyone is healthy.
CREATE TABLE IF NOT EXISTS wellness_checkins (
    athlete_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day         TEXT NOT NULL,
    soreness    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (athlete_id, day)
);

-- Something specific that hurts. `note` is the athlete's own words and is
-- readable by them and their guardian only -- never by a coach, and the form
-- says so before they type.
CREATE TABLE IF NOT EXISTS discomfort_reports (
    id          INTEGER PRIMARY KEY,
    athlete_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    area        TEXT NOT NULL,
    side        TEXT NOT NULL DEFAULT '',
    severity    TEXT NOT NULL,
    flags       TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    -- Severity before the most recent change, so direction of travel
    -- survives. Repeat reports on one area update the row rather than stacking
    -- new ones, so without this there is no earlier row to compare against and
    -- "getting worse" -- the signal that matters most -- can never fire.
    previous_severity TEXT,
    started_on  TEXT NOT NULL,
    reported_on TEXT NOT NULL,
    resolved_on TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_discomfort_open
    ON discomfort_reports(athlete_id, resolved_on);

-- The ramp back after something serious. This app never clears anyone: a
-- return after an injury is a human decision, and these rows record that a
-- named adult made it on a named date. `clinician_name` is what a guardian
-- typed, attesting that a healthcare professional said yes -- unverifiable by
-- us, and stored as an attestation rather than a fact about the clinician.
CREATE TABLE IF NOT EXISTS return_plans (
    id              INTEGER PRIMARY KEY,
    athlete_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    report_id       INTEGER,
    area            TEXT NOT NULL,
    stage           TEXT NOT NULL,
    clearance       TEXT NOT NULL,
    cleared_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    cleared_by_name TEXT NOT NULL DEFAULT '',
    clinician_name  TEXT NOT NULL DEFAULT '',
    cleared_on      TEXT,
    setbacks        INTEGER NOT NULL DEFAULT 0,
    started_on      TEXT NOT NULL,
    stage_started_on TEXT NOT NULL,
    completed_on    TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_return_plans_open
    ON return_plans(athlete_id, completed_on);

-- Append-only history of everything that happened to a plan. A return after an
-- injury is the one place in this product where "who decided what, and when"
-- may genuinely need answering later.
CREATE TABLE IF NOT EXISTS return_plan_events (
    id          INTEGER PRIMARY KEY,
    plan_id     INTEGER NOT NULL REFERENCES return_plans(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    actor_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor_name  TEXT NOT NULL DEFAULT '',
    day         TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_return_plan_events ON return_plan_events(plan_id);

-- A curated film clip. Stores a provider and an id, never the video: the
-- athlete's browser plays it from the provider's own embed, nothing is
-- downloaded or re-hosted.
CREATE TABLE IF NOT EXISTS clips (
    id          INTEGER PRIMARY KEY,
    org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    provider    TEXT NOT NULL DEFAULT 'youtube',
    video_id    TEXT NOT NULL,
    title       TEXT NOT NULL,
    -- What to watch for. The difference between film study and watching telly.
    focus       TEXT NOT NULL DEFAULT '',
    start_s     INTEGER NOT NULL DEFAULT 0,
    end_s       INTEGER,
    positions   TEXT NOT NULL DEFAULT '',
    min_age     INTEGER NOT NULL DEFAULT 0,
    max_age     INTEGER NOT NULL DEFAULT 200,
    question    TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clips_org ON clips(org_id, active);

-- One athlete watching one clip. Heartbeats update this row in place rather
-- than writing their own -- a beat every few seconds would be the largest
-- table in the database within a season, and the aggregate is what anyone
-- ever reads.
CREATE TABLE IF NOT EXISTS clip_watches (
    id           INTEGER PRIMARY KEY,
    athlete_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    clip_id      INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    day          TEXT NOT NULL,
    position_s   REAL NOT NULL DEFAULT 0,
    watched_s    REAL NOT NULL DEFAULT 0,
    audible_s    REAL NOT NULL DEFAULT 0,
    focused_s    REAL NOT NULL DEFAULT 0,
    wall_s       REAL NOT NULL DEFAULT 0,
    seeks        INTEGER NOT NULL DEFAULT 0,
    max_rate     REAL NOT NULL DEFAULT 1,
    -- Whole seconds of the clip actually seen, so rewatching the first ten
    -- seconds forty times does not read as having watched it.
    seen_json    TEXT NOT NULL DEFAULT '[]',
    verdict      TEXT NOT NULL DEFAULT 'partial',
    -- How many deliberate passes through the clip this row represents. A
    -- second look is the point of the film module rather than a failure of
    -- it, so it is counted rather than prevented -- and counted here, on the
    -- watch, so that no separate table has to be kept in step with it.
    looks        INTEGER NOT NULL DEFAULT 1,
    answered     INTEGER,
    answer_ok    INTEGER,
    xp_awarded   INTEGER NOT NULL DEFAULT 0,
    started_at   TEXT NOT NULL,
    last_beat_at TEXT NOT NULL,
    UNIQUE (athlete_id, clip_id, day)
);
CREATE INDEX IF NOT EXISTS idx_clip_watches_day ON clip_watches(athlete_id, day);

-- A coach's own words for a milestone. Absent means the shipped default is
-- used, so a program that never opens this screen still sends something.
-- A clip an athlete chose to send their coach for feedback.
--
-- This is the one place in the product where video leaves a phone, and it only
-- does so when a guardian has turned on the `coach_video` consent AND the
-- athlete has picked one specific clip. Nothing here is automatic: there is no
-- path that uploads a recording because a session happened.
--
-- Stored with an expiry, purged by the same cron that sends notifications, and
-- deleted outright the moment consent is withdrawn.
CREATE TABLE IF NOT EXISTS shared_clips (
    id          INTEGER PRIMARY KEY,
    athlete_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id  INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    drill_key   TEXT NOT NULL DEFAULT '',
    mime        TEXT NOT NULL DEFAULT 'video/webm',
    bytes       BLOB NOT NULL,
    size_bytes  INTEGER NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    shared_at   TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shared_clips_athlete ON shared_clips(athlete_id);

-- Who watched a shared clip and when. A child's video being viewed is exactly
-- the kind of thing a parent may want to ask about later.
CREATE TABLE IF NOT EXISTS shared_clip_views (
    id         INTEGER PRIMARY KEY,
    clip_id    INTEGER NOT NULL REFERENCES shared_clips(id) ON DELETE CASCADE,
    viewer_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    viewer_name TEXT NOT NULL DEFAULT '',
    viewed_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shared_clip_views ON shared_clip_views(clip_id);

-- A team wired up to wherever its roster actually lives.
--
-- `token` reaches back into a system holding children's contact details, so it
-- is write-only everywhere above this line: it goes in, is used by the sync,
-- and is never returned to a dashboard, an API response, or a log.
CREATE TABLE IF NOT EXISTS roster_links (
    id          INTEGER PRIMARY KEY,
    org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    team_id     INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    provider    TEXT NOT NULL,
    token       TEXT NOT NULL DEFAULT '',
    remote_ref  TEXT NOT NULL,
    -- Off until a coach has seen one dry run and agreed with it. A sync that
    -- starts writing the moment it is connected is a sync nobody trusts.
    auto_sync   INTEGER NOT NULL DEFAULT 0,
    last_run_at TEXT,
    last_result TEXT NOT NULL DEFAULT '',
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (team_id, provider)
);
CREATE INDEX IF NOT EXISTS idx_roster_links_org ON roster_links(org_id);

CREATE TABLE IF NOT EXISTS recognition_templates (
    org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    milestone   TEXT NOT NULL,
    body        TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    -- Whose name goes on it. 'coach' is the athlete's own coach; 'voice' is
    -- the program's senior figure, set below. Reserving the rarer milestones
    -- for the second is the point: a note from a former pro means something
    -- because it does not arrive every week.
    from_voice  TEXT NOT NULL DEFAULT 'coach',
    updated_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (org_id, milestone)
);

-- One recording. Contains no video and no frames -- only derived counts.
CREATE TABLE IF NOT EXISTS sessions (
    id               INTEGER PRIMARY KEY,
    athlete_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drill_key        TEXT NOT NULL,
    -- Issued at session start and required at submit, so a replayed or
    -- fabricated payload cannot be posted twice.
    nonce            TEXT NOT NULL UNIQUE,
    started_at       TEXT NOT NULL,
    submitted_at     TEXT,
    duration_ms      INTEGER NOT NULL DEFAULT 0,
    reps_total       INTEGER NOT NULL DEFAULT 0,
    reps_left        INTEGER NOT NULL DEFAULT 0,
    reps_right       INTEGER NOT NULL DEFAULT 0,
    hold_ms          INTEGER NOT NULL DEFAULT 0,
    mean_confidence  REAL NOT NULL DEFAULT 0.0,
    cadence_cv       REAL NOT NULL DEFAULT 0.0,
    integrity_score  REAL NOT NULL DEFAULT 0.0,
    integrity_notes  TEXT NOT NULL DEFAULT '',
    xp_awarded       INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'open'
                     CHECK (status IN ('open','counted','review','rejected')),
    client_version   TEXT NOT NULL DEFAULT '',
    device_label     TEXT NOT NULL DEFAULT '',
    -- When the athlete actually finished, as reported by their device. An
    -- offline session recorded Sunday and synced Monday must earn Sunday's
    -- credit, or every dead zone silently breaks a streak.
    completed_at     TEXT,
    -- Cached submit response, replayed verbatim if the client resends. An
    -- offline client that never saw its ack will retry, and it must get the
    -- original result rather than an error or a second score.
    result_json      TEXT,
    -- True when the nonce was handed out ahead of time for offline use.
    reserved         INTEGER NOT NULL DEFAULT 0,
    -- Form quality, 0-100. NULL when the session was too short to judge or the
    -- client reported no per-rep shape data.
    quality_score    INTEGER,
    quality_json     TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_athlete ON sessions(athlete_id, submitted_at);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);

-- Per-rep timings, retained briefly for integrity review then pruned.
CREATE TABLE IF NOT EXISTS rep_events (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    t_ms        INTEGER NOT NULL,
    hand        TEXT CHECK (hand IN ('left','right','none')),
    confidence  REAL NOT NULL DEFAULT 0.0,
    -- Shape of the rep: the signal's extreme, the range of motion covered,
    -- and how long the cycle took. This is what form scoring reads.
    peak        REAL,
    rom         REAL,
    cycle_ms    INTEGER,
    -- Cued drills only: which of the nine cells the hands reached. Null on
    -- every self-paced drill, and 'unknown' when the camera could not tell --
    -- which is deliberately not the same value as a wrong cell.
    zone        TEXT,
    -- Stance-width drills only: 1 when the feet crossed during this rep.
    crossed     INTEGER,
    -- Shooting drills only: elbow offset from the wrist at release, in torso
    -- lengths. Null when the release could not be read.
    flare       REAL
);
CREATE INDEX IF NOT EXISTS idx_rep_events_session ON rep_events(session_id);

-- Training an athlete did that no camera saw.
--
-- The load model was blind to the single thing that hurts endurance athletes.
-- Every other sport's training load arrives through a counted session; a
-- runner's arrives through their feet on a road and a swimmer's through four
-- thousand yards of water, both miles from any phone. So a fifty-mile week and
-- a five-mile week produced the SAME acute:chronic ratio, and the app would
-- cheerfully suggest more.
--
-- Self-reported and therefore unverifiable, which is normally the end of the
-- conversation in this codebase. It is admissible because of what it is wired
-- to: **a logged session earns nothing at all.** No XP, no streak, no
-- leaderboard, no badge. It feeds the load model and nothing else, and the
-- load model only ever produces cautions. Over-reporting buys a warning nobody
-- needed; under-reporting buys silence nobody wants. There is no direction in
-- which lying pays, which is what makes an unverifiable number safe to accept
-- here and nowhere else.
--
-- `activity` is what was done, because the same minute costs different things.
-- An hour of running is bone loading; an hour of swimming is shoulder volume
-- and no bone loading at all. One rate for both would have been a number that
-- was wrong for whichever sport was not thought of first.
--
-- One row per athlete per day per activity, replaced on re-entry rather than
-- accumulated: somebody correcting yesterday is the common case, and two rows
-- for one session would count it twice.
CREATE TABLE IF NOT EXISTS training_log (
    id          INTEGER PRIMARY KEY,
    athlete_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day         TEXT NOT NULL,          -- YYYY-MM-DD, athlete-local
    activity    TEXT NOT NULL,          -- 'run' | 'swim'
    minutes     INTEGER NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    UNIQUE(athlete_id, day, activity)
);
CREATE INDEX IF NOT EXISTS idx_training_log_athlete
    ON training_log(athlete_id, day);

-- Append-only XP record. Every leaderboard and streak is derived from this,
-- so a scoring bug can be audited and recomputed rather than guessed at.
CREATE TABLE IF NOT EXISTS xp_ledger (
    id          INTEGER PRIMARY KEY,
    athlete_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id  INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    amount      INTEGER NOT NULL,
    reason      TEXT NOT NULL,
    day         TEXT NOT NULL,          -- YYYY-MM-DD, athlete-local
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_xp_athlete_day ON xp_ledger(athlete_id, day);

CREATE TABLE IF NOT EXISTS badges (
    id          INTEGER PRIMARY KEY,
    athlete_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    badge_key   TEXT NOT NULL,
    awarded_at  TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    UNIQUE (athlete_id, badge_key)
);

-- A coach's prescription. This is what turns free-form logging into a
-- program: the athlete sees what was asked of them, and the coach sees who
-- did it.
-- Which parts of the camera analysis do not fit how an athlete trains.
--
-- Deliberately not a disability record and deliberately not a diagnosis. Every
-- column here describes what *our tool* cannot do for this athlete, which is
-- the honest framing and also the only one that keeps this table out of the
-- territory of health data about a minor.
CREATE TABLE IF NOT EXISTS adaptive_profiles (
    athlete_id     INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    -- Comma-separated accommodation keys. See adaptive.ACCOMMODATIONS.
    accommodations TEXT NOT NULL DEFAULT '',
    -- Logistics only: "uses a chair for lower-body work" is training
    -- information. Anything more belongs with the family and their clinician.
    note           TEXT NOT NULL DEFAULT '',
    set_by         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    set_by_name    TEXT NOT NULL DEFAULT '',
    updated_at     TEXT NOT NULL
);

-- A holiday, a tournament weekend, a school trip.
--
-- These days are *removed from the timeline* rather than credited as training.
-- An athlete comes back to the streak they earned, not a bigger one: a
-- fortnight away must not turn a 7-day streak into 21, or the number stops
-- meaning anything and the streak stops being worth protecting.
--
-- Set by a parent or a coach, never by the athlete. A child who can declare
-- their own absence has a button that undoes a missed day, which is the same
-- thing as not having streaks at all.
CREATE TABLE IF NOT EXISTS planned_absences (
    id          INTEGER PRIMARY KEY,
    athlete_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    starts_on   TEXT NOT NULL,
    ends_on     TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    set_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    set_by_name TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_absences_athlete
    ON planned_absences(athlete_id, starts_on);

-- A number a squad chases together.
--
-- The shape matters more than the fields. `target_athletes` is a count of
-- people, and `per_athlete_days`/`per_athlete_sessions` is a small personal
-- bar each of them has to clear. Contribution is therefore binary and capped:
-- the committed athlete doing six sessions adds exactly what the quiet one
-- doing three does, so the only way the number moves is somebody new turning
-- up. A goal denominated in reps would do the opposite -- it would let one
-- athlete carry the squad, and make a quiet one visibly the shortfall.
CREATE TABLE IF NOT EXISTS team_goals (
    id                   INTEGER PRIMARY KEY,
    org_id               INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    team_id              INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    created_by           INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title                TEXT NOT NULL,
    target_athletes      INTEGER NOT NULL,
    per_athlete_days     INTEGER NOT NULL DEFAULT 0,
    per_athlete_sessions INTEGER NOT NULL DEFAULT 0,
    starts_on            TEXT NOT NULL,
    ends_on              TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    active               INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_team_goals_team ON team_goals(team_id, active);

CREATE TABLE IF NOT EXISTS assignments (
    id              INTEGER PRIMARY KEY,
    org_id          INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    team_id         INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    created_by      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drill_key       TEXT NOT NULL,
    title           TEXT NOT NULL,
    notes           TEXT NOT NULL DEFAULT '',
    -- Any target may be 0, meaning "not part of this assignment".
    target_reps     INTEGER NOT NULL DEFAULT 0,
    target_sessions INTEGER NOT NULL DEFAULT 0,
    -- Minimum share of reps on the athlete's weaker hand, 0..1.
    min_offhand     REAL NOT NULL DEFAULT 0.0,
    starts_on       TEXT NOT NULL,
    due_on          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_assignments_team ON assignments(team_id, active);

-- Optional narrowing: rows here restrict an assignment to specific athletes.
-- No rows means it applies to the whole team, which is the common case.
CREATE TABLE IF NOT EXISTS assignment_athletes (
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    athlete_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (assignment_id, athlete_id)
);

-- Generated nudges. Stored regardless of whether a push channel is
-- configured, so the in-app feed works with no third-party service at all.
CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    link        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    read_at     TEXT,
    pushed_at   TEXT,
    -- Collapses repeat nudges: one "streak at risk" per athlete per day, not
    -- one per cron tick.
    dedupe_key  TEXT NOT NULL,
    -- Which athlete this is about. Set on a guardian's copy so a parent with
    -- two children can tell which one a message concerns, and on the
    -- athlete's own row so the two can be matched up.
    about_athlete_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    -- True on the guardian's copy. Every message an athlete receives is
    -- mirrored to their guardians, and the copy says so rather than reading
    -- as a message addressed to the parent.
    is_copy     INTEGER NOT NULL DEFAULT 0,
    -- Which wording of a recognition message went out, so the next athlete
    -- to cross the same milestone can be given a different one. Null on
    -- every other kind of notification.
    variant     INTEGER,
    -- Who it is from, when it is from a person. Recognition messages carry a
    -- coach's name because being noticed by a person is the point.
    from_name   TEXT NOT NULL DEFAULT '',
    UNIQUE (user_id, dedupe_key)
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, created_at);

-- Web Push endpoints, one row per device an athlete has opted in on.
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint    TEXT NOT NULL UNIQUE,
    p256dh      TEXT NOT NULL,
    auth        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    failed_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_push_user ON push_subscriptions(user_id);

-- A day the athlete deliberately rested while carrying enough load to warrant
-- it. These count toward a streak.
--
-- Without this the streak mechanic punishes resting, which turns the whole
-- gamification layer into a risk factor: the athlete most in need of a day off
-- is exactly the one with the longest streak to protect.
CREATE TABLE IF NOT EXISTS recovery_days (
    id          INTEGER PRIMARY KEY,
    athlete_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day         TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    UNIQUE (athlete_id, day)
);
CREATE INDEX IF NOT EXISTS idx_recovery_athlete ON recovery_days(athlete_id, day);

-- Who is responsible for a minor. Many-to-many on purpose: a child can have
-- two parents, and a parent can have three kids in the program.
CREATE TABLE IF NOT EXISTS guardians (
    guardian_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    athlete_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    relationship  TEXT NOT NULL DEFAULT 'parent',
    linked_at     TEXT NOT NULL,
    PRIMARY KEY (guardian_id, athlete_id)
);
CREATE INDEX IF NOT EXISTS idx_guardians_athlete ON guardians(athlete_id);

-- Single-use, expiring invitations. A code that reaches the wrong person grants
-- access to a child's data, so these are short-lived, revocable, and stored
-- hashed like any other credential.
CREATE TABLE IF NOT EXISTS guardian_invites (
    id          INTEGER PRIMARY KEY,
    athlete_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_by  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash   TEXT NOT NULL UNIQUE,
    email       TEXT,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    redeemed_at TEXT,
    redeemed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    revoked_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_invites_athlete ON guardian_invites(athlete_id);

-- Granular, revocable consent. Replaces a single boolean a coach ticked, which
-- was never a consent record -- it recorded that an adult clicked something,
-- not who agreed to what, or when, or whether they later changed their mind.
CREATE TABLE IF NOT EXISTS consents (
    id           INTEGER PRIMARY KEY,
    athlete_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    guardian_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    scope        TEXT NOT NULL,
    granted      INTEGER NOT NULL DEFAULT 1,
    granted_at   TEXT NOT NULL,
    -- What they actually agreed to, so a later policy change cannot be applied
    -- retroactively to a consent given under different terms.
    policy_version TEXT NOT NULL DEFAULT '1',
    method       TEXT NOT NULL DEFAULT 'guardian_portal'
);
CREATE INDEX IF NOT EXISTS idx_consents_athlete ON consents(athlete_id, scope);

-- Deletion leaves the data gone but the fact recorded, so a program can show
-- an auditor that a request was honoured without retaining what was deleted.
CREATE TABLE IF NOT EXISTS erasure_log (
    id            INTEGER PRIMARY KEY,
    athlete_ref   TEXT NOT NULL,
    requested_by  TEXT NOT NULL,
    scope         TEXT NOT NULL,
    rows_removed  INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

-- A person's role in a program. Authoritative; `users.org_id` is kept as the
-- home org a token defaults to.
--
-- Many-to-many because it genuinely is: a school coach who also runs a club
-- side is one person with two jobs, and making them keep two logins is how a
-- roster ends up half-maintained.
CREATE TABLE IF NOT EXISTS memberships (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id     INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK (role IN ('athlete','coach','director','guardian')),
    created_at TEXT NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, org_id)
);
CREATE INDEX IF NOT EXISTS idx_memberships_org ON memberships(org_id, role);

-- Which teams a coach is responsible for.
--
-- Without this every coach in a program can read every athlete in it. At a
-- club with four hundred children that is not a product gap, it is a
-- safeguarding one: access should follow responsibility.
CREATE TABLE IF NOT EXISTS team_staff (
    team_id    INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role       TEXT NOT NULL DEFAULT 'coach',
    created_at TEXT NOT NULL,
    PRIMARY KEY (team_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_team_staff_user ON team_staff(user_id);

-- One row per program. Absent means the free plan.
-- A club's sponsorship fund: credit earned on what they have paid, and drawn
-- down when they cover a family who cannot afford the season.
--
-- A ledger rather than a balance column so the club can see where it came from
-- and where it went. Accrued rather than netted off the invoice on purpose: a
-- discount disappears into a smaller number nobody looks at, and a fund with a
-- balance is something a director can point at and spend on a named family.
CREATE TABLE IF NOT EXISTS sponsorship_credits (
    id           INTEGER PRIMARY KEY,
    org_id       INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    -- Positive is earned, negative is spent.
    amount_cents INTEGER NOT NULL,
    reason       TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sponsorship_org ON sponsorship_credits(org_id);

-- What one child's family has bought, under a club-free plan.
--
-- Per athlete rather than per guardian: a household with two children in
-- different clubs is one family and two entitlements, and a guardian-level row
-- would have to invent an answer for which club it applied to.
--
-- `source` distinguishes paid, sponsored (the club covered it), hardship
-- (granted free, no questions) and trial. That distinction is for the family
-- and for reconciliation; it is never surfaced anywhere a coach can see, and a
-- test enforces that. A dashboard that quietly showed which children came from
-- paying households would break the promise that this product does not score
-- what a family can afford.
CREATE TABLE IF NOT EXISTS household_subscriptions (
    athlete_id   INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    source       TEXT NOT NULL DEFAULT 'paid'
                 CHECK (source IN ('paid','sponsored','hardship','trial')),
    status       TEXT NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active','lapsed','canceled')),
    period_start TEXT NOT NULL,
    period_end   TEXT NOT NULL,
    external_ref TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_household_status
    ON household_subscriptions(status, period_end);

CREATE TABLE IF NOT EXISTS subscriptions (
    org_id             INTEGER PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    plan_code          TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'trialing'
                       CHECK (status IN ('trialing','active','past_due','canceled')),
    seats_purchased    INTEGER NOT NULL DEFAULT 0,
    trial_ends_at      TEXT,
    period_start       TEXT NOT NULL,
    period_end         TEXT NOT NULL,
    -- Identifier from whatever processor is attached. Empty while billing is
    -- being kept manually.
    external_ref       TEXT NOT NULL DEFAULT '',
    updated_at         TEXT NOT NULL
);

-- Append-only billing history: plan changes, seat changes, invoices raised.
-- Append-only because a billing dispute is settled by what happened and when,
-- not by the current state of a row.
CREATE TABLE IF NOT EXISTS billing_events (
    id          INTEGER PRIMARY KEY,
    org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    amount_cents INTEGER NOT NULL DEFAULT 0,
    seats       INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_billing_org ON billing_events(org_id, created_at);

-- Outbound mail, queued before it is sent.
--
-- Queued rather than sent inline because a weekly job that emails a hundred
-- coaches inside one SMTP connection loses the whole week when the ninetieth
-- times out. Composition and delivery are separate steps, and delivery retries.
CREATE TABLE IF NOT EXISTS email_outbox (
    id              INTEGER PRIMARY KEY,
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    to_email        TEXT NOT NULL,
    subject         TEXT NOT NULL,
    html_body       TEXT NOT NULL,
    text_body       TEXT NOT NULL,
    kind            TEXT NOT NULL,
    -- Makes queueing idempotent. A cron that fires twice on a Monday must not
    -- send the same digest twice.
    dedupe_key      TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','sent','failed','suppressed')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT NOT NULL DEFAULT '',
    queued_at       TEXT NOT NULL,
    next_attempt_at TEXT NOT NULL,
    sent_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON email_outbox(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_outbox_user ON email_outbox(user_id, kind);

-- Addresses that must not be written to again: hard bounces, and anyone who
-- unsubscribed. Repeatedly mailing a dead address is how a sending domain
-- loses its reputation, and mailing someone who opted out is worse than that.
CREATE TABLE IF NOT EXISTS email_suppressions (
    email      TEXT PRIMARY KEY,
    reason     TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Per-person, per-kind opt-out. Absent means opted in.
CREATE TABLE IF NOT EXISTS email_preferences (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, kind)
);

-- Every delivery event a mail provider has told us about.
--
-- Kept raw as well as normalized: when a coach says they never got the digest,
-- the provider's own words are what settles it, and a normalization bug should
-- not destroy the evidence of what actually arrived.
CREATE TABLE IF NOT EXISTS webhook_events (
    id          INTEGER PRIMARY KEY,
    provider    TEXT NOT NULL,
    -- The provider's own id for this event. Providers retry webhooks, and a
    -- retried soft bounce counted twice pushes a live address off the list.
    event_id    TEXT NOT NULL UNIQUE,
    event_type  TEXT NOT NULL,
    email       TEXT NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    message_id  TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL DEFAULT '',
    received_at TEXT NOT NULL,
    action      TEXT NOT NULL DEFAULT '',
    raw         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_webhook_email ON webhook_events(email, event_type, received_at);

-- Pre-fetched OCSP responses for certificates we expect to verify.
--
-- The point of stapling: someone fetches the responder's answer ahead of time
-- and attaches it, so verification reads a fresh local answer instead of
-- making a network call while a request waits. That moves the freshness
-- problem off the request path, which is what makes refusing an unproven
-- certificate practical rather than an availability risk.
CREATE TABLE IF NOT EXISTS ocsp_staples (
    id            INTEGER PRIMARY KEY,
    -- Certificate serial and issuer, which together identify what the
    -- response is about.
    serial        TEXT NOT NULL,
    issuer_key_id TEXT NOT NULL,
    subject       TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL,
    response      BLOB NOT NULL,
    this_update   TEXT NOT NULL DEFAULT '',
    -- After this the staple is stale and must not be believed.
    next_update   TEXT NOT NULL DEFAULT '',
    fetched_at    TEXT NOT NULL,
    source        TEXT NOT NULL DEFAULT 'prefetch',
    UNIQUE (serial, issuer_key_id)
);
CREATE INDEX IF NOT EXISTS idx_staples_next ON ocsp_staples(next_update);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def hash_token(token: str) -> str:
    """Tokens are stored hashed so a database leak is not a credential leak."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def new_join_code() -> str:
    """Short, unambiguous team code an athlete can type from a whiteboard.

    Excludes characters that get misread when a 12-year-old copies them off a
    locker room wall: O/0, I/1, S/5.
    """
    alphabet = "ABCDEFGHJKLMNPQRTUVWXYZ234679"
    return "".join(secrets.choice(alphabet) for _ in range(6))


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or CONFIG.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets the coach dashboard read while athletes are submitting.
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# Columns added to existing tables after their initial release. `CREATE TABLE
# IF NOT EXISTS` silently skips these on a database that already exists, so
# they have to be applied explicitly or an upgraded deployment reads a schema it
# does not have.
ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("completed_at", "TEXT"),
        ("result_json", "TEXT"),
        ("reserved", "INTEGER NOT NULL DEFAULT 0"),
        ("quality_score", "INTEGER"),
        ("quality_json", "TEXT"),
        # Marked for ever on a session the camera could not count. Kept out of
        # any statistic that needs a measured number, counted for turning up.
        ("self_reported", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "rep_events": [
        ("peak", "REAL"),
        ("rom", "REAL"),
        ("cycle_ms", "INTEGER"),
    ],
    "users": [
        ("external_id", "TEXT"),
        ("claim_code_hash", "TEXT"),
        ("claim_expires_at", "TEXT"),
        ("birth_year_estimated", "INTEGER NOT NULL DEFAULT 0"),
        # Per person, not per program: a Spanish-speaking household inside an
        # English-speaking club is the common case, not the edge one.
        ("locale", "TEXT NOT NULL DEFAULT 'en'"),
    ],
    "organizations": [
        ("position_emphasis_min_age", "INTEGER NOT NULL DEFAULT 15"),
        ("voice_name", "TEXT NOT NULL DEFAULT ''"),
        ("voice_title", "TEXT NOT NULL DEFAULT ''"),
        ("kind", "TEXT NOT NULL DEFAULT 'program'"),
        ("sibling_compare", "INTEGER NOT NULL DEFAULT 0"),
        ("season_phase", "TEXT NOT NULL DEFAULT 'preseason'"),
    ],
    "notifications": [
        # Which wording went out, so the next athlete can be given a
        # different one. Null on everything that is not recognition.
        ("variant", "INTEGER"),
    ],
    "recognition_templates": [
        ("from_voice", "TEXT NOT NULL DEFAULT 'coach'"),
    ],
    "notifications": [
        ("about_athlete_id", "INTEGER"),
        ("is_copy", "INTEGER NOT NULL DEFAULT 0"),
        ("from_name", "TEXT NOT NULL DEFAULT ''"),
    ],
    "discomfort_reports": [
        ("previous_severity", "TEXT"),
    ],
    "rep_events": [
        ("zone", "TEXT"),
        ("crossed", "INTEGER"),
        ("flare", "REAL"),
    ],
    "clip_watches": [
        ("looks", "INTEGER NOT NULL DEFAULT 1"),
    ],
}


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    for table, columns in ADDED_COLUMNS.items():
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            continue
        present = _existing_columns(conn, table)
        for name, decl in columns:
            if name not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _widen_user_roles(conn: sqlite3.Connection) -> None:
    """Allow the 'guardian' role on a database created before it existed.

    SQLite cannot alter a CHECK constraint, so this is the documented
    rebuild-and-rename dance. Guarded by an actual probe rather than a version
    number, so it is safe to run against any vintage of the schema.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    if row is None or "guardian" in (row[0] or ""):
        return

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        columns = ", ".join(sorted(_existing_columns(conn, "users")))
        conn.executescript(
            SCHEMA[SCHEMA.index("CREATE TABLE IF NOT EXISTS users ("):]
            .split(");", 1)[0]
            .replace("CREATE TABLE IF NOT EXISTS users (", "CREATE TABLE users_migrated (")
            + ");"
        )
        conn.execute(f"INSERT INTO users_migrated ({columns}) SELECT {columns} FROM users")
        conn.execute("DROP TABLE users")
        conn.execute("ALTER TABLE users_migrated RENAME TO users")
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _backfill_memberships(conn: sqlite3.Connection) -> None:
    """Give every existing user a membership row for their home org.

    Memberships became the authority for role and program access; a database
    predating them has that information only in `users.org_id`, and skipping
    this would leave every existing user with no access to anything.
    """
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memberships'"
    ).fetchone():
        return
    conn.execute(
        "INSERT OR IGNORE INTO memberships(user_id, org_id, role, created_at, active) "
        "SELECT id, org_id, role, created_at, active FROM users"
    )


def migrate(conn: sqlite3.Connection) -> int:
    """Bring an existing database up to the current schema.

    Idempotent and probe-driven rather than version-driven, because the version
    counter was being bumped for several releases before this runner existed
    and cannot be trusted to describe what is actually on disk.
    """
    before = conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    _widen_user_roles(conn)
    _add_missing_columns(conn)
    _backfill_memberships(conn)
    conn.commit()

    # Existing programs get a plan matching what they already run, rather than
    # being dropped onto the free tier and finding half their teams blocked.
    try:
        from .billing import backfill_subscriptions

        backfill_subscriptions(conn)
    except Exception:  # noqa: BLE001 -- billing must never block opening the DB
        pass
    conn.commit()
    return int(before[0]) if before else 0


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    migrate(conn)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on any exception."""
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
