"use client";
// Runs in the browser, so "how long ago" and "is the computer off?" use the visitor's clock, not the
// time the page was last rebuilt. Before that, the strip shows plain times.
import { useEffect, useState } from "react";
import type { AutomationStatus } from "@/lib/data";

const utc = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", {
    weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC",
  }) + " UTC";

function ago(iso: string, now: number) {
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} h ago` : `${Math.round(hours / 24)} days ago`;
}

export function AutomationStrip({ status }: { status: AutomationStatus }) {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => setNow(Date.now()), []);

  // The computer runs a check every few hours; an hour past the due time means it is probably off.
  const off = now !== null && status.next_check_by !== null && now > new Date(status.next_check_by).getTime() + 3600_000;
  const state = status.problems.length ? "bad" : off ? "off" : status.waiting.length ? "wait" : "ok";

  return (
    <section className="auto-bar" aria-label="Automatic runs">
      <div className="wrap auto-row">
        <span className="auto-title">
          <span className={`auto-dot ${state}`} aria-hidden="true" />
          Automatic runs
        </span>
        <span>
          Last check {now === null ? utc(status.checked_at) : ago(status.checked_at, now)}
          {off ? ": the computer running the experiment seems to be off, and catches up when it is back on" : ""}
        </span>
        {status.upcoming.map((u) => (
          <span key={u.step}>
            <b>Next:</b> {u.step},{" "}
            {now !== null && new Date(u.from).getTime() <= now ? "due now" : `from ${utc(u.from)}`} ({u.note})
          </span>
        ))}
        {status.problems.map((p) => (
          <span key={p} className="problem">{p}</span>
        ))}
        {status.last_result && status.last_result_at && (
          <span className={status.last_result_ok === false ? "problem" : ""}>
            <b>Last result:</b> {status.last_result} ({utc(status.last_result_at)})
          </span>
        )}
      </div>
    </section>
  );
}
