// What the memory teams remember: self-written notes week by week, and verified lessons with their records.
import Link from "next/link";
import { Kit } from "@/components/Kit";
import { getLessons, getMemoryNotes, type LessonRecord, type MemoryNotes } from "@/lib/data";
import { teamInfo } from "@/lib/teams";

export const revalidate = 300; // seconds; Next.js needs a plain number here (same as REVALIDATE_SECONDS)
export const metadata = { title: "Memory | AI Fantasy League" };

const SELF = ["H-self", "S-self", "O-self"];
const VERIFIED = ["H-verified", "S-verified", "O-verified"];
const STATUS: Record<LessonRecord["status"], string> = {
  active: "Active",
  dropped_by_agent: "Dropped by the agent",
  removed: "Removed by the check",
};

export default async function Memory() {
  const [notes, lessons] = await Promise.all([getMemoryNotes(), getLessons()]);

  return (
    <>
      <h1>What the teams remember</h1>
      <p className="lede">
        Memory teams carry something from week to week. Self-written teams keep up to 8 notes and rewrite them
        freely. Verified teams keep numbered lessons and must cite them for every transfer and captain pick; our
        code then checks how those picks did against the experiment&apos;s own predicted points.
      </p>

      <h2>Self-written notes</h2>
      <p>The notes as each team left them after its latest decision. New notes since the week before are highlighted.</p>
      {SELF.map((team) => <SelfNotes key={team} team={team} weeks={notes.filter((n) => n.team === team)} />)}

      <h2>Verified lessons</h2>
      <p>
        Each lesson&apos;s record compares the points of the picks that cited it with the experiment&apos;s predicted points
        for them at decision time. A lesson cited at least 5 times whose picks average more than 1 point below
        prediction is removed, and the team is told why. See the{" "}
        <a href="https://github.com/lavast1c/fpl-experiment/blob/main/METHODS.md">methods</a> for the exact rule.
      </p>
      {VERIFIED.map((team) => <Lessons key={team} team={team} lessons={lessons.filter((l) => l.team === team)} />)}
    </>
  );
}

function TeamHeader({ team }: { team: string }) {
  return (
    <header>
      <Kit team={team} size={40} />
      <h2><Link href={`/teams/${team}`}>{team}</Link></h2>
      <span className="muted">{teamInfo(team).model}</span>
    </header>
  );
}

function SelfNotes({ team, weeks }: { team: string; weeks: MemoryNotes[] }) {
  const latest = weeks.at(-1);
  const before = weeks.at(-2)?.notes ?? [];
  return (
    <section className="memory-team">
      <TeamHeader team={team} />
      {!latest?.notes?.length ? (
        <p className="muted">No notes yet.</p>
      ) : (
        <>
          <p className="small muted">After gameweek {latest.gw}: {latest.notes.length} notes</p>
          <ul className="notes">
            {latest.notes.map((note) => (
              <li key={note} className={weeks.length > 1 && !before.includes(note) ? "added" : undefined}>{note}</li>
            ))}
          </ul>
          {weeks.length > 1 && (
            <details className="reasoning">
              <summary>Earlier weeks</summary>
              {weeks.slice(0, -1).reverse().map((w) => (
                <div key={w.gw}>
                  <h3 style={{ marginTop: 14 }}>After gameweek {w.gw}</h3>
                  <ul className="notes">{(w.notes ?? []).map((n) => <li key={n}>{n}</li>)}</ul>
                </div>
              ))}
            </details>
          )}
        </>
      )}
    </section>
  );
}

function Lessons({ team, lessons }: { team: string; lessons: LessonRecord[] }) {
  const sorted = [...lessons].sort((a, b) => Number(a.id.slice(1)) - Number(b.id.slice(1)));
  return (
    <section className="memory-team">
      <TeamHeader team={team} />
      {sorted.length === 0 ? (
        <p className="muted">No lessons yet.</p>
      ) : (
        <div>
          {sorted.map((l) => (
            <div key={l.id} className={`lesson ${l.status === "active" ? "" : "gone"}`}>
              <span className="lid">{l.id}</span>
              <span>
                <span className="text">{l.text}</span>
                <br />
                <span className={`status ${l.status}`}>{STATUS[l.status]}</span>
                <span className="small muted">
                  {" "}since gameweek {l.created_gw}{l.ended_gw ? `, ended gameweek ${l.ended_gw}` : ""}
                </span>
              </span>
              <span className="record">
                {l.uses === 0 ? <span className="muted">Not checked yet</span> : (
                  <>
                    {l.uses} {l.uses === 1 ? "use" : "uses"}
                    <br />
                    <span className={(l.average ?? 0) >= 0 ? "pos-good" : "pos-bad"}>
                      {(l.average ?? 0) > 0 ? "+" : ""}{l.average} vs predicted
                    </span>
                  </>
                )}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
