// One team, week by week: the squad on a pitch, transfers, captain, chip, rule breaks, points and reasoning.
import Link from "next/link";
import { notFound } from "next/navigation";
import { Kit } from "@/components/Kit";
import {
  getDecisions, getPlayers, getResults,
  type Decision, type PlayerResult, type Result, type SnapshotPlayer,
} from "@/lib/data";
import { CHIPS, TEAM_IDS, isTeamId, teamInfo } from "@/lib/teams";

export const revalidate = 300; // seconds; Next.js needs a plain number here (same as REVALIDATE_SECONDS)

export function generateStaticParams() {
  return TEAM_IDS.map((id) => ({ id }));
}

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props) {
  const { id } = await params;
  return { title: isTeamId(id) ? `${id} | AI Fantasy League` : "Team not found" };
}

export default async function TeamPage({ params }: Props) {
  const { id } = await params;
  if (!isTeamId(id)) notFound();
  const info = teamInfo(id);
  const [decisions, results] = await Promise.all([getDecisions(id), getResults(id)]);
  const latest = results.at(-1);

  return (
    <>
      <div className="team-hero">
        <Kit team={id} size={88} />
        <div>
          <h1>{id}</h1>
          <p className="facts">
            {info.modelId === "rule-based" ? "Rule-based bot" : <>Model <code>{info.modelId}</code></>}, {info.memory.toLowerCase()}.
          </p>
        </div>
      </div>
      <p>{info.blurb}</p>

      <div className="stat-row">
        <div className="stat"><b>{latest?.season_points ?? 0}</b><span>season points</span></div>
        <div className="stat"><b>{latest ? `#${latest.season_rank}` : "–"}</b><span>rank of 11</span></div>
        <div className="stat"><b>{latest ? Math.round(latest.season_expected) : "–"}</b><span>expected points</span></div>
        <div className="stat"><b>{decisions.reduce((n, d) => n + d.transfers_made, 0)}</b><span>transfers</span></div>
        <div className="stat"><b>{decisions.reduce((n, d) => n + d.errors_by_attempt.filter((e) => e.length).length, 0)}</b><span>rule breaks</span></div>
      </div>

      {decisions.length === 0 && <p className="muted" style={{ marginTop: 32 }}>No decisions yet.</p>}
      {decisions.map((d) => (
        <Week key={d.gw} decision={d} result={results.find((r) => r.gw === d.gw)} />
      ))}

      <p style={{ marginTop: 40 }}><Link href="/teams">All teams</Link></p>
    </>
  );
}

async function Week({ decision: d, result }: { decision: Decision; result?: Result }) {
  const ids = [...(d.squad ?? []), ...d.transfers.flatMap((t) => [t.in, t.out])];
  const players = await getPlayers(d.gw, ids);
  const scored = new Map((result?.players ?? []).map((p) => [p.id, p]));
  const name = (pid: number) => players.get(pid)?.name ?? scored.get(pid)?.name ?? `Player ${pid}`;
  const breaks = d.errors_by_attempt.filter((e) => e.length);

  return (
    <section className="week" aria-labelledby={`gw${d.gw}`}>
      <div className="week-head">
        <h2 id={`gw${d.gw}`}>Gameweek {d.gw}</h2>
        <span className="week-score">
          {result ? <>{result.net_points} pts, #{result.rank} of 11</> : <span className="muted">Not scored yet</span>}
        </span>
      </div>
      <div className="tags">
        {d.first_week && <span className="tag">First squad, £100m</span>}
        {d.chip && <span className="tag">{CHIPS[d.chip] ?? d.chip}</span>}
        {d.expected_points !== null && <span className="tag">Expected {d.expected_points} pts</span>}
        {result?.luck !== null && result?.luck !== undefined && (
          <span className="tag">Luck {result.luck > 0 ? "+" : ""}{result.luck}</span>
        )}
        {d.hit_points > 0 && <span className="tag warn">−{d.hit_points} hit</span>}
        {breaks.length > 0 && (
          <span className="tag warn" title={breaks.map((e) => e.join(", ")).join(" / ")}>
            {breaks.length} rule {breaks.length === 1 ? "break" : "breaks"}: {[...new Set(breaks.flat())].join(", ")}
          </span>
        )}
        {d.outcome !== "accepted" && <span className="tag warn">Kept last week&apos;s team</span>}
      </div>

      {d.transfers.length > 0 && (
        <ul className="transfers">
          {d.transfers.map((t) => (
            <li key={`${t.out}-${t.in}`}>
              <span className="out">{name(t.out)}</span> out, <span className="in">{name(t.in)}</span> in
            </li>
          ))}
        </ul>
      )}

      {d.starting_xi && d.bench_order && (
        <Pitch xi={d.starting_xi} bench={d.bench_order} captain={d.captain} vice={d.vice_captain}
          players={players} scored={scored} />
      )}

      {d.reasoning && (
        <details className="reasoning">
          <summary>{d.team.endsWith("-bot") ? "Rule" : "Reasoning, in the agent's words"}</summary>
          <blockquote>{d.reasoning}</blockquote>
        </details>
      )}
    </section>
  );
}

const LINES = ["GKP", "DEF", "MID", "FWD"];

function Pitch({ xi, bench, captain, vice, players, scored }: {
  xi: number[]; bench: number[]; captain: number | null; vice: number | null;
  players: Map<number, SnapshotPlayer>; scored: Map<number, PlayerResult>;
}) {
  const card = (pid: number) => {
    const p = players.get(pid);
    const s = scored.get(pid);
    const armband = pid === captain ? " (C)" : pid === vice ? " (V)" : "";
    return (
      <div className="player" key={pid}>
        <b>{p?.name ?? s?.name ?? pid}<span className="armband">{armband}</span></b>
        <span>{p ? `${p.club} £${p.price}m` : ""}{s ? `, ${s.points} pts` : ""}</span>
      </div>
    );
  };
  return (
    <div className="pitch" aria-label="Starting eleven and bench">
      {LINES.map((pos) => (
        <div className="pitch-row" key={pos}>{xi.filter((pid) => players.get(pid)?.pos === pos).map(card)}</div>
      ))}
      <div className="bench">{bench.map(card)}</div>
    </div>
  );
}
