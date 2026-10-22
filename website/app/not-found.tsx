import Link from "next/link";

export default function NotFound() {
  return (
    <>
      <h1>No such page</h1>
      <p>That team or page doesn&apos;t exist. The experiment has 11 teams, all listed on the teams page.</p>
      <p><Link href="/teams">See all teams</Link></p>
    </>
  );
}
