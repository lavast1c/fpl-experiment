// Reads the experiment's results from Supabase (a read-only copy of the files in the repo's data/ folder).
// Uses the public "publishable" key: row level security allows reading the result tables only.
// Pages are rebuilt at most every 5 minutes, so the database is queried rarely.

export const REVALIDATE_SECONDS = 300;

export type TeamRow = { id: string; kind: "ai" | "bot"; model: string; memory: "none" | "self" | "verified" };

export type Gameweek = {
  id: number;
  name: string;
  deadline_time: string;
  is_current: boolean;
  is_next: boolean;
  finished: boolean;
  average_entry_score: number | null;
};

export type Decision = {
  team: string;
  gw: number;
  decided_at: string;
  outcome: string;
  first_week: boolean;
  copied_from?: string | null;
  attempts: number;
  errors_by_attempt: string[][];
  stale_picks: unknown[];
  transfers: { out: number; in: number }[];
  squad: number[] | null;
  starting_xi: number[] | null;
  bench_order: number[] | null;
  captain: number | null;
  vice_captain: number | null;
  chip: string | null;
  reasoning: string | null;
  transfers_made: number;
  hit_points: number;
  expected_points: number | null;
  input_tokens: number;
  output_tokens: number;
};

export type PlayerResult = { id: number; name: string; points: number; role: string };

export type Result = {
  team: string;
  gw: number;
  points: number;
  hit_points: number;
  net_points: number;
  rank: number;
  fpl_average: number | null;
  vs_average: number | null;
  expected_points: number | null;
  luck: number | null;
  season_points: number;
  season_expected: number;
  season_rank: number;
  outcome: string;
  rule_breaks: number;
  transfers_made: number;
  captain_changed: boolean | null;
  chip: string | null;
  auto_subs: number;
  bench_points: number;
  players: PlayerResult[];
  transfer_points: { out_name: string; out_points: number; in_name: string; in_points: number }[];
};

export type Standing = {
  team: string;
  kind: "ai" | "bot" | "reference";
  gameweeks: number;
  points: number;
  expected_points: number | null;
  luck: number | null;
  hit_points: number | null;
  rule_breaks: number | null;
  transfers: number | null;
  captain_changes: number | null;
};

export type Lesson = {
  id: string;
  text: string;
  created_gw: number;
  status: "active" | "dropped_by_agent" | "removed";
  ended_gw?: number | null;
  uses?: unknown[];
};

export type MemoryNotes = { team: string; gw: number; kind: "self" | "verified"; notes: string[] | null; lessons: Lesson[] | null };

export type LessonRecord = {
  team: string;
  id: string;
  text: string;
  created_gw: number;
  status: "active" | "dropped_by_agent" | "removed";
  ended_gw: number | null;
  uses: number;
  average: number | null;
};

export type SnapshotPlayer = { id: number; name: string; club: string; pos: string; price: number };

/** The automatic runs' status (one row, written by experiment/automation.py on the project's computer). */
export type AutomationStatus = {
  checked_at: string;
  next_check_by: string | null;
  every_hours: number | null;
  upcoming: { step: string; from: string; note: string }[];
  waiting: string[];
  problems: string[];
  last_result: string | null;
  last_result_at: string | null;
  last_result_ok: boolean | null;
};

/** One query to Supabase's REST API, e.g. table("results", "select=*&order=gw"). */
async function table<T>(name: string, query: string): Promise<T[]> {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key) throw new Error("SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY must be set (see .env.example).");
  const response = await fetch(`${url}/rest/v1/${name}?${query}`, {
    headers: { apikey: key, Authorization: `Bearer ${key}` },
    next: { revalidate: REVALIDATE_SECONDS },
  });
  if (!response.ok) throw new Error(`Supabase ${name}: ${response.status} ${await response.text()}`);
  return response.json();
}

export const getTeams = () => table<TeamRow>("teams", "select=*");
export const getGameweeks = () => table<Gameweek>("gameweeks", "select=*&order=id");
export const getStandings = () => table<Standing>("standings", "select=*");
export const getResults = (team?: string) =>
  table<Result>("results", `select=*&order=gw${team ? `&team=eq.${encodeURIComponent(team)}` : ""}`);
export const getDecisions = (team?: string) =>
  table<Decision>("decisions", `select=*&order=gw.desc${team ? `&team=eq.${encodeURIComponent(team)}` : ""}`);
export const getMemoryNotes = () => table<MemoryNotes>("memory_notes", "select=*&order=gw");
export const getLessons = () => table<LessonRecord>("lessons", "select=team,id,text,created_gw,status,ended_gw,uses,average");

/** The status row, or null if there is none yet (the panel is then left out rather than breaking the page). */
export async function getAutomationStatus(): Promise<AutomationStatus | null> {
  try {
    return (await table<AutomationStatus>("automation_status", "select=*&id=eq.1"))[0] ?? null;
  } catch {
    return null;
  }
}

/** Player names, clubs and positions from the snapshot each team decided with. */
export async function getPlayers(gw: number, ids: number[]): Promise<Map<number, SnapshotPlayer>> {
  if (ids.length === 0) return new Map();
  const rows = await table<SnapshotPlayer>(
    "snapshot_players",
    `select=id,name,club,pos,price&gw=eq.${gw}&id=in.(${[...new Set(ids)].join(",")})`,
  );
  return new Map(rows.map((p) => [p.id, p]));
}

/** The gameweek the next decisions are for, and the latest one with decisions. */
export function nextGameweek(gameweeks: Gameweek[]): Gameweek | undefined {
  return gameweeks.find((g) => g.is_next);
}
