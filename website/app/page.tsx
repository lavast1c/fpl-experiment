// Home: the season table as a stadium scoreboard, the points race, and how to read the kits.
import Link from "next/link";
import { Kit } from "@/components/Kit";
import { PointsChart, type Series } from "@/components/PointsChart";
import { getDecisions, getGameweeks, getResults, getStandings, nextGameweek } from "@/lib/data";
import { TEAM_IDS, teamInfo } from "@/lib/teams";

export const revalidate = 300; // seconds; Next.js needs a plain number here (same as REVALIDATE_SECONDS)

const signed = (n: number | null | undefined) =>
  n === null || n === undefined ? "–" : `${n > 0 ? "+" : ""}${Math.round(n * 10) / 10}`;

export default async function Home() {
  const [standings, results, decisions, gameweeks] = await Promise.all([
    getStandings(), getResults(), getDecisions(), getGameweeks(),
  ]);

  const scoredGws = [...new Set(results.map((r) => r.gw))].sort((a, b) => a - b);
  const lastScored = scoredGws.at(-1);
  const lastDecided = Math.max(0, ...decisions.map((d) => d.gw));
  const upcoming = nextGameweek(gameweeks);

  // One row per team: season totals if any gameweek is scored, otherwise just the team.
  const rows = TEAM_IDS.map((id) => {
    const s = standings.find((x) => x.team === id);
    const last = results.find((r) => r.team === id && r.gw === lastScored);
    return { id, points: s?.points ?? null, expected: s?.expected_points ?? null, luck: s?.luck ?? null, lastGw: last?.net_points ?? null };
  }).sort((a, b) => (b.points ?? 0) - (a.points ?? 0));
  const average = standings.find((s) => s.team === "fpl-average");
  const lastAverage = results.find((r) => r.gw === lastScored)?.fpl_average ?? null;
  const rank = (points: number | null) => (points === null ? "–" : 1 + rows.filter((r) => (r.points ?? 0) > points).length);

  const series: Series[] = TEAM_IDS.map((id) => ({
    id, label: id,
    points: results.filter((r) => r.team === id).map((r) => ({ gw: r.gw, total: r.season_points })),
  }));
  if (results.length && results.every((r) => r.fpl_average !== null)) {
    let total = 0;
    series.push({
      id: "fpl-average", label: "FPL average", reference: true,
      points: scoredGws.map((gw) => ({ gw, total: (total += results.find((r) => r.gw === gw)?.fpl_average ?? 0) })),
    });
  }

  return (
    <>
      <h1>Do AI agents learn from experience, or from luck?</h1>
      <p className="lede">
        Nine Claude agents, three model sizes with three kinds of memory, manage simulated Fantasy Premier
        League teams for the rest of the 2026/27 season. Three simple bots and FPL&apos;s average manager are the
        yardsticks. Every team started from £100m in gameweek 8, and each model&apos;s three teams share one starting squad.
      </p>

      <section className="board" aria-labelledby="table-title">
        <div className="board-status">
          <span id="table-title">
            <strong>Season table</strong>
            {lastScored ? ` after gameweek ${lastScored}` : ""}
          </span>
          <span>{statusLine(lastScored, lastDecided, upcoming)}</span>
        </div>
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th className="pos">Pos</th>
                <th className="left">Team</th>
                <th>{lastScored ? `GW${lastScored}` : "Last GW"}</th>
                <th className="hide-sm">Expected</th>
                <th className="hide-sm">Luck</th>
                <th>Points</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const info = teamInfo(r.id);
                return (
                  <tr key={r.id}>
                    <td className="pos">{rank(r.points)}</td>
                    <td className="left">
                      <Link href={`/teams/${r.id}`} className="team-cell">
                        <Kit team={r.id} size={34} />
                        <span>
                          <span className="team-name">{r.id}</span>
                          <br />
                          <span className="team-sub">{info.model}, {info.memory.toLowerCase()}</span>
                        </span>
                      </Link>
                    </td>
                    <td className="num">{r.lastGw ?? "–"}</td>
                    <td className="num hide-sm">{r.expected === null ? "–" : Math.round(r.expected)}</td>
                    <td className={`num hide-sm ${(r.luck ?? 0) > 0 ? "up" : (r.luck ?? 0) < 0 ? "down" : ""}`}>{signed(r.luck)}</td>
                    <td className={`lamp ${r.points === null ? "waiting" : ""}`}>{r.points ?? "0"}</td>
                  </tr>
                );
              })}
              <tr className="reference">
                <td className="pos"></td>
                <td className="left">
                  <span className="team-cell">
                    <span className="ref-mark" aria-hidden="true" />
                    <span>
                      <span className="team-name">FPL average</span>
                      <br />
                      <span className="team-sub">All real managers, for reference</span>
                    </span>
                  </span>
                </td>
                <td className="num">{lastAverage ?? "–"}</td>
                <td className="hide-sm"></td>
                <td className="hide-sm"></td>
                <td className="num">{average?.points ?? "–"}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <p className="small muted">
        <b>Expected</b> adds up the experiment&apos;s own predicted points for each team&apos;s choices at the time it made them.{" "}
        <b>Luck</b> is actual minus expected: a team can be top through luck, or bottom despite good decisions.
      </p>

      <h2>The points race</h2>
      {scoredGws.length ? (
        <div className="panel"><PointsChart series={series} /></div>
      ) : (
        <p className="muted">The race starts once gameweek {lastDecided || 8} is finished and FPL confirms the points.</p>
      )}

      <h2>Reading the kits</h2>
      <p>Each team&apos;s shirt shows who is playing: the colour is the model, the pattern is the memory.</p>
      <div className="legend">
        <div><Kit team="H-none" /> Teal: Claude Haiku 5.5</div>
        <div><Kit team="S-none" /> Blue: Claude Sonnet 5.5</div>
        <div><Kit team="O-none" /> Red: Claude Opus 5.5</div>
        <div><Kit team="form-bot" /> Grey: rule-based bot, no AI</div>
        <div><Kit team="O-none" /> Plain: no memory</div>
        <div><Kit team="O-self" /> Stripes: self-written notes</div>
        <div><Kit team="O-verified" /> Hoops: verified lessons</div>
        <div><Kit team="crowd-bot" /> Sash: the crowd bot</div>
        <div><Kit team="stats-bot" /> Halves: the stats bot</div>
      </div>
    </>
  );
}

function statusLine(lastScored: number | undefined, lastDecided: number, upcoming?: { id: number; deadline_time: string }) {
  if (lastDecided && lastDecided !== lastScored) return `Gameweek ${lastDecided} teams are picked; points come in once it finishes.`;
  if (upcoming) {
    const when = new Date(upcoming.deadline_time).toLocaleString("en-GB", {
      weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC",
    });
    return `Next deadline: gameweek ${upcoming.id}, ${when} UTC`;
  }
  return "";
}
