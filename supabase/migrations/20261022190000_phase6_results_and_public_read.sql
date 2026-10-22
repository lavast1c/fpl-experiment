-- Phase 6: results, decisions and memory for the future website, plus public read-only access.
-- Files in data/ are the source of truth; these tables are a copy written by experiment/supabase_sync.py
-- (real runs only, never mock data). Raw prompts and agent replies stay in the GitHub repo only.
-- Anyone with the publishable (anon) key can READ these tables; only the secret key can write.

-- FPL's average manager score for each finished gameweek (the "global average" baseline).
alter table public.gameweeks add column average_entry_score integer;

create table public.teams (
    id           text primary key,          -- e.g. S-verified, form-bot
    kind         text not null,             -- ai / bot
    model        text not null,             -- exact model id, or rule-based
    memory       text not null              -- none / self / verified
);

create table public.decisions (
    team             text not null references public.teams (id),
    gw               integer not null,
    decided_at       timestamptz not null,
    outcome          text not null,         -- accepted / no_change / no_change_failed / no_squad
    first_week       boolean not null,
    attempts         integer not null,
    errors_by_attempt jsonb not null,       -- rule-break codes per attempt
    stale_picks      jsonb not null,
    transfers        jsonb not null,        -- [{"out": id, "in": id}]
    squad            jsonb,                 -- player ids after the decision
    starting_xi      jsonb,
    bench_order      jsonb,
    captain          integer,
    vice_captain     integer,
    chip             text,
    reasoning        text,
    transfers_made   integer not null,
    hit_points       integer not null,
    expected_points  numeric,
    input_tokens     integer not null,
    output_tokens    integer not null,
    model_mismatch   boolean not null,
    primary key (team, gw)
);

create table public.results (
    team             text not null references public.teams (id),
    gw               integer not null,
    points           integer not null,
    hit_points       integer not null,
    net_points       integer not null,
    rank             integer not null,      -- among the 11 teams this gameweek
    fpl_average      integer,
    vs_average       integer,
    expected_points  numeric,
    luck             numeric,
    season_points    integer not null,
    season_expected  numeric not null,
    season_rank      integer not null,
    outcome          text not null,
    attempts         integer not null,
    rule_breaks      integer not null,
    error_codes      text,
    stale_picks      integer not null,
    transfers_made   integer not null,
    captain_changed  boolean,
    chip             text,
    auto_subs        integer not null,
    bench_points     integer not null,
    players          jsonb not null,        -- each player's points and role
    transfer_points  jsonb not null,        -- each transfer with both players' points
    memory_detail    jsonb,                 -- notes with added/removed, or lessons with track records
    primary key (team, gw)
);

create table public.standings (
    team             text primary key,      -- a team id, or fpl-average
    kind             text not null,         -- ai / bot / reference
    model            text,
    memory           text,
    gameweeks        integer not null,
    points           integer not null,
    expected_points  numeric,
    luck             numeric,
    hit_points       integer,
    rule_breaks      integer,
    failed_weeks     integer,
    stale_picks      integer,
    transfers        integer,
    captain_changes  integer,
    chips            text,
    input_tokens     integer,
    output_tokens    integer
);

create table public.memory_notes (
    team     text not null references public.teams (id),
    gw       integer not null,              -- memory after this gameweek's decision
    kind     text not null,                 -- self / verified
    notes    jsonb,                         -- self-written notes
    lessons  jsonb,                         -- verified lessons (all, with status)
    primary key (team, gw)
);

create table public.lessons (
    team        text not null references public.teams (id),
    id          text not null,              -- L1, L2, ...
    text        text not null,
    created_gw  integer not null,
    status      text not null,              -- active / dropped_by_agent / removed
    ended_gw    integer,
    uses        integer not null,
    average     numeric,                    -- average value vs expected points
    uses_detail jsonb not null,             -- every checked decision
    primary key (team, id)
);

alter table public.teams enable row level security;
alter table public.decisions enable row level security;
alter table public.results enable row level security;
alter table public.standings enable row level security;
alter table public.memory_notes enable row level security;
alter table public.lessons enable row level security;

-- Public read-only access (the fetch log stays private).
create policy "public read" on public.gameweeks for select to anon, authenticated using (true);
create policy "public read" on public.snapshots for select to anon, authenticated using (true);
create policy "public read" on public.snapshot_players for select to anon, authenticated using (true);
create policy "public read" on public.teams for select to anon, authenticated using (true);
create policy "public read" on public.decisions for select to anon, authenticated using (true);
create policy "public read" on public.results for select to anon, authenticated using (true);
create policy "public read" on public.standings for select to anon, authenticated using (true);
create policy "public read" on public.memory_notes for select to anon, authenticated using (true);
create policy "public read" on public.lessons for select to anon, authenticated using (true);
