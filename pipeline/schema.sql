-- Pro Cycling Analytics — Data Model
-- Covers: races, race editions (years), stages/routes, teams, riders, and
-- stage-by-stage results (with bonus/penalty seconds, GC standing, points).
-- Designed to extend beyond the Tour de France to any stage race or one-day race.

PRAGMA foreign_keys = ON;

-- A race franchise, independent of year (e.g. "Tour de France", "Giro d'Italia")
CREATE TABLE IF NOT EXISTS races (
    race_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    country     TEXT,             -- host country of the race, if relevant
    race_type   TEXT              -- 'stage_race' | 'one_day'
);

-- One year's running of a race (e.g. "2024 Tour de France", the 111th edition)
CREATE TABLE IF NOT EXISTS race_editions (
    edition_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id             INTEGER NOT NULL REFERENCES races(race_id),
    year                INTEGER NOT NULL,
    edition_name        TEXT,      -- e.g. "111th Tour de France"
    uci_classification  TEXT,      -- e.g. "2.UWT"
    UNIQUE(race_id, year)
);

-- A national federation / nationality code (ISO-ish 2-letter, as used by flags)
CREATE TABLE IF NOT EXISTS countries (
    code  TEXT PRIMARY KEY,   -- e.g. 'fr', 'be', 'si'
    name  TEXT                -- e.g. 'France'  (filled in opportunistically)
);

-- A rider, identified by their stable source slug (e.g. 'rider/tadej-pogacar')
CREATE TABLE IF NOT EXISTS riders (
    rider_id            TEXT PRIMARY KEY,
    full_name           TEXT NOT NULL,
    nationality_code    TEXT REFERENCES countries(code),
    birth_year_approx   INTEGER,   -- derived from age-at-race snapshots; approximate
    first_name          TEXT,      -- scraped from PCS rider page (scrape_rider_details.py)
    last_name           TEXT,      -- scraped from PCS rider page
    birthday            TEXT       -- ISO date 'YYYY-MM-DD'; may be NULL if not on PCS
);

-- A team roster for one season (team identity is re-created each year in pro cycling,
-- as sponsors/names change), identified by source slug e.g. 'team/uae-team-emirates-2024'
CREATE TABLE IF NOT EXISTS teams (
    team_id      TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    season_year  INTEGER
);

-- One stage (or the single "stage" of a one-day race) within an edition
CREATE TABLE IF NOT EXISTS stages (
    stage_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    edition_id            INTEGER NOT NULL REFERENCES race_editions(edition_id),
    stage_number          INTEGER NOT NULL,
    stage_label           TEXT,        -- e.g. "Stage 7 (ITT)"
    stage_date            TEXT,        -- ISO date 'YYYY-MM-DD'
    start_time            TEXT,        -- local start time 'HH:MM'
    start_location         TEXT,
    finish_location        TEXT,
    distance_km           REAL,
    stage_type            TEXT,        -- 'road' | 'itt' (individual time trial) | 'ttt' etc.
    profile_score         INTEGER,     -- PCS climbing-difficulty score
    vertical_meters       INTEGER,
    avg_speed_winner_kmh  REAL,
    avg_temperature_c     REAL,
    won_how               TEXT,        -- e.g. "14.3 km solo", "Sprint of large group"
    race_ranking          INTEGER,
    startlist_quality_score INTEGER,
    timelimit_text        TEXT,
    UNIQUE(edition_id, stage_number)
);

-- One rider's result on one stage. This is the core fact table.
CREATE TABLE IF NOT EXISTS stage_results (
    result_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_id            INTEGER NOT NULL REFERENCES stages(stage_id),
    rider_id            TEXT NOT NULL REFERENCES riders(rider_id),
    team_id             TEXT REFERENCES teams(team_id),
    bib_number          INTEGER,
    stage_rank          INTEGER,        -- NULL if DNF/DNS/OTL
    status              TEXT NOT NULL DEFAULT 'FINISHED',  -- FINISHED | DNF | DNS | OTL
    finish_time_seconds INTEGER,        -- absolute elapsed time for the stage, seconds
    gap_seconds         INTEGER,        -- gap to stage winner, seconds
    bonus_seconds       INTEGER NOT NULL DEFAULT 0,   -- "B" — time bonus for top finishers
    penalty_seconds     INTEGER NOT NULL DEFAULT 0,   -- "P" — time penalty for infractions
    uci_points          INTEGER,
    pcs_points          INTEGER,
    gc_rank             INTEGER,        -- overall classification rank after this stage
    gc_gap_seconds       INTEGER,        -- overall gap to GC leader after this stage
    age_at_race          INTEGER,
    UNIQUE(stage_id, rider_id)
);

-- Free-text race-jury incidents tied to a stage (relegations, fines, disqualifications)
-- that don't cleanly fit the per-rider numeric columns above.
CREATE TABLE IF NOT EXISTS stage_incidents (
    incident_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_id      INTEGER NOT NULL REFERENCES stages(stage_id),
    description   TEXT NOT NULL
);

-- Final standings for the race's secondary jerseys: points (green), mountains/KOM
-- (polka dot), and best young rider (white). General classification itself lives
-- in stage_results.gc_rank / gc_gap_seconds for the final stage, so it isn't repeated here.
CREATE TABLE IF NOT EXISTS classification_standings (
    standing_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    edition_id         INTEGER NOT NULL REFERENCES race_editions(edition_id),
    classification     TEXT NOT NULL,   -- 'points' | 'kom' | 'youth'
    rank               INTEGER NOT NULL,
    rider_id           TEXT NOT NULL REFERENCES riders(rider_id),
    team_id            TEXT REFERENCES teams(team_id),
    points             INTEGER,         -- total classification points (points/kom)
    time_seconds       INTEGER,         -- total time or gap-to-leader in seconds (youth)
    UNIQUE(edition_id, classification, rider_id)
);

CREATE INDEX IF NOT EXISTS idx_standings_edition ON classification_standings(edition_id, classification);

CREATE INDEX IF NOT EXISTS idx_results_stage ON stage_results(stage_id);
CREATE INDEX IF NOT EXISTS idx_results_rider ON stage_results(rider_id);
CREATE INDEX IF NOT EXISTS idx_results_team  ON stage_results(team_id);
CREATE INDEX IF NOT EXISTS idx_stages_edition ON stages(edition_id);
