// How each team is named and drawn. Every team wears a "kit":
//   colour  = the model (Haiku teal, Sonnet blue, Opus red, bots grey)
//   pattern = the memory (plain = none, vertical stripes = self-written, hoops = verified)

export const TEAM_IDS = [
  "H-none", "H-self", "H-verified",
  "S-none", "S-self", "S-verified",
  "O-none", "O-self", "O-verified",
  "form-bot", "crowd-bot", "stats-bot",
] as const;

export type Pattern = "plain" | "stripes" | "hoops" | "sash" | "halves";

export type TeamInfo = {
  id: string;
  name: string;        // e.g. "Opus, verified memory"
  model: string;       // e.g. "Opus 5.5" or "Rule-based"
  modelId: string;     // exact model id, or "rule-based"
  memory: string;      // e.g. "Verified memory"
  colour: string;      // CSS colour variable
  pattern: Pattern;
  blurb: string;       // one sentence on how the team works
};

const MODELS: Record<string, { name: string; id: string; colour: string }> = {
  H: { name: "Haiku 5.5", id: "claude-haiku-5-5", colour: "var(--haiku)" },
  S: { name: "Sonnet 5.5", id: "claude-sonnet-5-5", colour: "var(--sonnet)" },
  O: { name: "Opus 5.5", id: "claude-opus-5-5", colour: "var(--opus)" },
};

const MEMORY: Record<string, { name: string; pattern: Pattern; blurb: string }> = {
  none: { name: "No memory", pattern: "plain", blurb: "Starts every week fresh, seeing only this week's data and its own squad." },
  self: {
    name: "Self-written memory",
    pattern: "stripes",
    blurb: "Keeps up to 8 notes of its own, sees last week's results, and rewrites its notes each week.",
  },
  verified: {
    name: "Verified memory",
    pattern: "hoops",
    blurb: "Keeps numbered lessons and must cite them; lessons whose picks keep falling short of the experiment's predicted points are removed.",
  },
};

export function teamInfo(id: string): TeamInfo {
  if (id === "form-bot")
    return {
      id, name: "Form bot", model: "Rule-based", modelId: "rule-based", memory: "No memory",
      colour: "var(--bot)", pattern: "plain",
      blurb: "Buys, starts and captains the players in the best recent form. No AI.",
    };
  if (id === "crowd-bot")
    return {
      id, name: "Crowd bot", model: "Rule-based", modelId: "rule-based", memory: "No memory",
      colour: "var(--bot)", pattern: "sash",
      blurb: "Copies what most real managers own: the template team. No AI.",
    };
  if (id === "stats-bot")
    return {
      id, name: "Stats bot", model: "Rule-based", modelId: "rule-based", memory: "No memory",
      colour: "var(--bot)", pattern: "halves",
      blurb: "Picks by the experiment's own predicted points, which weigh expected goals, minutes and fixture difficulty. No AI.",
    };
  const [letter, memory] = id.split("-");
  const model = MODELS[letter];
  const mem = MEMORY[memory];
  return {
    id, name: `${model.name.split(" ")[0]}, ${mem.name.toLowerCase()}`, model: model.name, modelId: model.id,
    memory: mem.name, colour: model.colour, pattern: mem.pattern, blurb: mem.blurb,
  };
}

export const isTeamId = (id: string) => (TEAM_IDS as readonly string[]).includes(id);

/** Dash style for charts: solid = no memory, dashed = self-written, dotted = verified. */
export function dashFor(id: string): string | undefined {
  if (id.endsWith("-self")) return "7 4";
  if (id.endsWith("-verified")) return "2 4";
  if (id === "crowd-bot") return "10 3 2 3";
  if (id === "stats-bot") return "1 3";
  return undefined;
}

export const CHIPS: Record<string, string> = {
  wildcard: "Wildcard",
  freehit: "Free hit",
  bboost: "Bench boost",
  "3xc": "Triple captain",
};
