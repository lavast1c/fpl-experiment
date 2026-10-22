// The experiment in plain English.
import Link from "next/link";

export const metadata = { title: "About | AI Fantasy League" };

export default function About() {
  return (
    <article>
      <h1>About the experiment</h1>
      <p className="lede">
        If you give an AI agent a memory of its past decisions, does it actually get better over a season? Or,
        in a game as random as Fantasy Premier League, does it learn superstitions from lucky and unlucky weeks?
      </p>

      <h2>The teams</h2>
      <p>
        Three Claude models (Haiku 5.5, Sonnet 5.5 and Opus 5.5) each manage three teams, one with each kind of
        memory. That makes nine AI teams. Two rule-based bots and FPL&apos;s average manager act as yardsticks.
      </p>
      <ul className="notes">
        <li><b>No memory.</b> The agent sees only this week&apos;s player data and its own squad, money, free transfers and chips.</li>
        <li><b>Self-written memory.</b> The agent also sees last week&apos;s results and up to 8 notes it wrote itself, and rewrites them each week.</li>
        <li><b>Verified memory.</b> The notes are numbered lessons, and every transfer and captain pick must cite the lessons behind it. Our code checks those picks against FPL&apos;s own predicted points and removes lessons that keep falling short.</li>
        <li><b>Form bot.</b> Buys, starts and captains the players in the best recent form.</li>
        <li><b>Crowd bot.</b> Copies what most real managers own.</li>
      </ul>
      <p>
        Both bots mark doubtful players down (a 75% chance of playing keeps half a player&apos;s value), start fit
        players first, and never take points hits or play chips.
      </p>

      <h2>How a gameweek works</h2>
      <ol className="notes">
        <li>Before each deadline, the project downloads FPL&apos;s public player data and builds one table of every player: price, form, expected goals and assists, FPL&apos;s predicted points, ownership, injury news and the next three fixtures.</li>
        <li>Every agent gets exactly the same table and the same instructions, with no web access and no tools, and answers with its transfers, team, captain and any chip.</li>
        <li>A rule checker enforces every FPL rule. An illegal answer goes back to the agent with the errors, up to two more times; after that the team keeps last week&apos;s side.</li>
        <li>After the gameweek, our own scorer works out the points, including automatic substitutions and chips. It was checked against official FPL scores and matched exactly.</li>
      </ol>

      <h2>Separating skill from luck</h2>
      <p>
        Points alone mostly measure luck. So for every decision we also record its <b>expected points</b>: the
        sum of FPL&apos;s predicted points for the starting eleven at the moment the team chose them, with the
        captain counted twice. <b>Luck</b> is actual points minus expected points. A team with high expected points
        made good decisions, whatever the result.
      </p>

      <h2>What this project does not do</h2>
      <p>
        No FPL accounts, no logins, nothing entered in the real game, no real person&apos;s team, and no paid API
        usage: the agents run on a Claude subscription.
      </p>

      <h2>Everything is open</h2>
      <p>
        Every prompt, every raw answer, every decision and every note is published in the{" "}
        <a href="https://github.com/lavast1c/fpl-experiment">GitHub repository</a>, together with the code and a
        dated log of every methodological decision in{" "}
        <a href="https://github.com/lavast1c/fpl-experiment/blob/main/METHODS.md">METHODS.md</a>.
      </p>
      <p><Link href="/">Back to the table</Link></p>
    </article>
  );
}
