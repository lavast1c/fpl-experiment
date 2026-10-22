// A small football shirt in the team's colours (see lib/teams.ts for what colour and pattern mean).
import { teamInfo } from "@/lib/teams";

const SHIRT = "M22 6 L11 10 L2 22 L10 30 L16 26 L16 60 L48 60 L48 26 L54 30 L62 22 L53 10 L42 6 Q32 14 22 6 Z";

export function Kit({ team, size = 32 }: { team: string; size?: number }) {
  const info = teamInfo(team);
  const clip = `shirt-${team}-${size}`;
  return (
    <svg className="kit" width={size} height={size} viewBox="0 0 64 64" role="img" aria-label={`${info.name} kit`}>
      <defs>
        <clipPath id={clip}>
          <path d={SHIRT} />
        </clipPath>
      </defs>
      <g clipPath={`url(#${clip})`}>
        <rect width="64" height="64" fill={info.colour} />
        {info.pattern === "stripes" &&
          [20, 32, 44].map((x) => <rect key={x} x={x - 3} y="0" width="6" height="64" fill="var(--kit-trim)" />)}
        {info.pattern === "hoops" &&
          [18, 32, 46].map((y) => <rect key={y} x="0" y={y - 3.5} width="64" height="7" fill="var(--kit-trim)" />)}
        {info.pattern === "sash" && <path d="M4 10 L18 4 L62 54 L50 64 Z" fill="var(--kit-trim)" />}
        {info.pattern === "halves" && <rect x="32" y="0" width="32" height="64" fill="var(--kit-trim)" />}
      </g>
      <path d={SHIRT} fill="none" stroke="var(--kit-edge)" strokeWidth="2.5" strokeLinejoin="round" />
    </svg>
  );
}
