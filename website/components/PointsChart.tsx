// Season points race: cumulative points after each gameweek, one line per team, drawn as plain SVG
// on the server. Colour = model, dash = memory (as in the kits), FPL's average manager in black.
import { dashFor, teamInfo } from "@/lib/teams";

export type Series = { id: string; label: string; points: { gw: number; total: number }[]; reference?: boolean };

const W = 760, H = 380;
const PAD = { top: 16, right: 112, bottom: 36, left: 44 };

export function PointsChart({ series }: { series: Series[] }) {
  const gws = [...new Set(series.flatMap((s) => s.points.map((p) => p.gw)))].sort((a, b) => a - b);
  if (gws.length === 0) return null;
  const maxTotal = Math.max(10, ...series.flatMap((s) => s.points.map((p) => p.total)));
  const step = niceStep(maxTotal);
  const top = Math.ceil(maxTotal / step) * step;

  const x = (gw: number) =>
    gws.length === 1 ? PAD.left + (W - PAD.left - PAD.right) / 2
      : PAD.left + ((gw - gws[0]) / (gws[gws.length - 1] - gws[0])) * (W - PAD.left - PAD.right);
  const y = (total: number) => PAD.top + (1 - total / top) * (H - PAD.top - PAD.bottom);

  // End-of-line labels, nudged apart so they don't overlap.
  const ends = series
    .filter((s) => s.points.length)
    .map((s) => ({ s, y: y(s.points[s.points.length - 1].total) }))
    .sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i++) ends[i].y = Math.max(ends[i].y, ends[i - 1].y + 13);

  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Season points after each gameweek, per team">
        {Array.from({ length: top / step + 1 }, (_, i) => i * step).map((v) => (
          <g key={v}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} className="grid" />
            <text x={PAD.left - 8} y={y(v) + 4} textAnchor="end" className="tick">{v}</text>
          </g>
        ))}
        {gws.map((gw) => (
          <text key={gw} x={x(gw)} y={H - PAD.bottom + 20} textAnchor="middle" className="tick">GW{gw}</text>
        ))}
        {series.map((s) => {
          const colour = s.reference ? "var(--ink)" : teamInfo(s.id).colour;
          const path = s.points.map((p, i) => `${i ? "L" : "M"}${x(p.gw).toFixed(1)},${y(p.total).toFixed(1)}`).join(" ");
          return (
            <g key={s.id}>
              <path d={path} fill="none" stroke={colour} strokeWidth={s.reference ? 2.5 : 2}
                strokeDasharray={s.reference ? "4 3" : dashFor(s.id)} strokeLinecap="round" />
              {s.points.length === 1 && <circle cx={x(s.points[0].gw)} cy={y(s.points[0].total)} r="4" fill={colour} />}
            </g>
          );
        })}
        {ends.map(({ s, y: labelY }) => (
          <text key={s.id} x={W - PAD.right + 8} y={labelY + 4} className="end-label"
            fill={s.reference ? "var(--ink)" : teamInfo(s.id).colour}>{s.label}</text>
        ))}
      </svg>
      <figcaption>
        Total points after each gameweek. Line colour is the model; solid lines have no memory, dashed lines
        self-written memory, dotted lines verified memory. The black dashed line is FPL&apos;s average manager.
      </figcaption>
    </figure>
  );
}

function niceStep(max: number): number {
  const rough = max / 5;
  const power = 10 ** Math.floor(Math.log10(rough));
  return [1, 2, 5, 10].map((m) => m * power).find((s) => s >= rough) ?? power * 10;
}
