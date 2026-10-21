-- Phase 1: raw fetch log, gameweeks and weekly snapshots.
-- Files in data/ are the source of truth; these tables are a copy written by experiment/supabase_sync.py.
-- RLS is on with no policies: only the secret key (server side) can read or write for now.
-- Phase 6 adds read-only public policies for the website.

create table public.fetches (
    file        text primary key,          -- path inside data/raw, e.g. gw8/fixtures_20261021T175537Z.json.gz
    fetched_at  timestamptz not null,
    gw          integer not null,
    endpoint    text not null,
    sha256      text not null,
    bytes       integer not null,
    forced      boolean not null default false
);

create table public.gameweeks (
    id             integer primary key,
    name           text not null,
    deadline_time  timestamptz not null,
    is_current     boolean not null,
    is_next        boolean not null,
    finished       boolean not null,
    data_checked   boolean not null
);

create table public.snapshots (
    gw                   integer primary key,
    built_at             timestamptz not null,
    filter               text not null,
    players_in_game      integer not null,
    players_in_snapshot  integer not null,
    chars                integer not null,
    est_tokens           integer not null,
    sources              jsonb not null
);

create table public.snapshot_players (
    gw             integer not null references public.snapshots (gw) on delete cascade,
    id             integer not null,           -- FPL player id (changes every season)
    name           text not null,
    club           text not null,
    pos            text not null,
    price          numeric(4, 1) not null,     -- £m
    form           numeric not null,
    ppg            numeric not null,
    total_pts      integer not null,
    minutes        integer not null,
    xg             numeric not null,
    xa             numeric not null,
    ep_next        numeric not null,
    own_pct        numeric not null,
    status         text not null,
    chance_next    integer,                    -- null = no flag
    news           text not null,
    next_fixtures  text not null,
    primary key (gw, id)
);

alter table public.fetches enable row level security;
alter table public.gameweeks enable row level security;
alter table public.snapshots enable row level security;
alter table public.snapshot_players enable row level security;
