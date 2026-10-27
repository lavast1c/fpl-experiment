-- Automatic runs (METHODS.md, 2026-10-27).

-- 1. The website's status panel: one row, written by automation.py after every automatic run.
create table public.automation_status (
    id              integer primary key check (id = 1),   -- always exactly one row
    checked_at      timestamptz not null,   -- when the computer last ran the routine
    next_check_by   timestamptz,            -- the next run is due by then, if the computer is on
    every_hours     integer,                -- how often the scheduler runs it
    upcoming        jsonb not null,         -- [{step, from, note}]: the next scoring and picks
    waiting         jsonb not null,         -- normal waits, e.g. FPL is still checking the points
    problems        jsonb not null,         -- what went wrong in the last run (empty if nothing)
    last_result     text,                   -- the last finished job or problem
    last_result_at  timestamptz,
    last_result_ok  boolean
);
alter table public.automation_status enable row level security;
create policy "public read" on public.automation_status for select to anon, authenticated using (true);

-- 2. Missed deadlines (outcome "missed") are counted apart from a team's own failed weeks.
alter table public.standings add column missed_weeks integer;
