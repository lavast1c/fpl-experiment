// All 11 teams, grouped by model, linking to each team's week-by-week page.
import Link from "next/link";
import { Kit } from "@/components/Kit";
import { TEAM_IDS, teamInfo } from "@/lib/teams";

export const metadata = { title: "Teams | AI Fantasy League" };

const GROUPS = [
  { title: "Claude Haiku 5.5", ids: ["H-none", "H-self", "H-verified"] },
  { title: "Claude Sonnet 5.5", ids: ["S-none", "S-self", "S-verified"] },
  { title: "Claude Opus 5.5", ids: ["O-none", "O-self", "O-verified"] },
  { title: "Rule-based bots", ids: ["form-bot", "crowd-bot"] },
];

export default function Teams() {
  return (
    <>
      <h1>The teams</h1>
      <p className="lede">
        Each model plays three times, once with each kind of memory, so any difference between its three teams
        comes from memory alone. Open a team to see every squad, transfer, captain pick and the reasoning behind it.
      </p>
      {GROUPS.map((group) => (
        <section key={group.title}>
          <h2>{group.title}</h2>
          <div className="team-grid">
            {group.ids.filter((id) => TEAM_IDS.includes(id as never)).map((id) => {
              const info = teamInfo(id);
              return (
                <Link key={id} href={`/teams/${id}`} className="team-card">
                  <Kit team={id} size={48} />
                  <span>
                    <h3>{id}</h3>
                    <p><b>{info.memory}.</b> {info.blurb}</p>
                  </span>
                </Link>
              );
            })}
          </div>
        </section>
      ))}
    </>
  );
}
