"""Check the expected-points predictor against gameweeks that have already been played.

For each test gameweek, the predictor only sees the gameweeks before it, then we compare its
prediction with each player's official points. FPL's own past `ep_next` values were never saved
(we only started downloading at gameweek 8), so we compare with two simple stand-ins instead:
    form:    average points over the team's last 4 gameweeks (FPL's `form` is the last 30 days)
    ppg:     points per game played this season, times how often he played
FPL's `ep_next` itself is compared live from gameweek 8 onwards (both are saved every week).

Scores, over every player who had played before the test gameweek:
    correlation   how well the ranking of players matches the ranking of their points (Spearman)
    RMSE          typical size of the error, in points (MAE would reward predicting too low,
                  because most players score 1-2 and a few score a lot)
    bias          average predicted minus actual points
    top-50 pick   average actual points of the 50 players each method rated highest
"""

from collections import defaultdict

from . import config
from .files import read_json_gz, write_json
from .xpoints import load_history, live_file, predict


def spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        r = [0.0] * len(values)
        i = 0
        while i < len(order):                      # equal values share their average rank
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    return cov / ((sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5)


def actual_points(gw: int) -> dict[int, int]:
    return {e["id"]: e["stats"]["total_points"] for e in read_json_gz(live_file(gw))["elements"]}


def run(test_gws=range(4, 8), bootstrap_file: str = "gw8/bootstrap-static_20261022T143206Z.json.gz",
        fixtures_file: str = "gw8/fixtures_20261022T143207Z.json.gz") -> dict:
    bootstrap = read_json_gz(config.RAW_DIR / bootstrap_file)
    fixtures = read_json_gz(config.RAW_DIR / fixtures_file)
    points_by_gw = {gw: actual_points(gw) for gw in range(1, max(test_gws) + 1)}
    scores = defaultdict(lambda: defaultdict(list))
    for gw in test_gws:
        history = load_history(gw, bootstrap, fixtures)
        xp = predict(gw, bootstrap, fixtures)
        candidates = [pid for pid, h in history.players.items() if h.minutes > 0]
        played = {pid: [points_by_gw[g].get(pid, 0) for g in range(1, gw)] for pid in candidates}
        appearances = {pid: sum(1 for m in history.players[pid].matches if m[1] > 0) for pid in candidates}
        methods = {
            "our xP": {pid: xp[pid]["xp_if_fit"] for pid in candidates},
            "form": {pid: sum(played[pid][-4:]) / len(played[pid][-4:]) for pid in candidates},
            "ppg": {pid: (sum(played[pid]) / appearances[pid] if appearances[pid] else 0)
                         * appearances[pid] / max(1, len(history.players[pid].matches)) for pid in candidates},
        }
        actual = [points_by_gw[gw].get(pid, 0) for pid in candidates]
        for name, pred in methods.items():
            values = [pred[pid] for pid in candidates]
            top = sorted(candidates, key=lambda pid: -pred[pid])[:50]
            scores[name]["correlation"].append(spearman(values, actual))
            scores[name]["RMSE"].append((sum((v - a) ** 2 for v, a in zip(values, actual)) / len(actual)) ** 0.5)
            scores[name]["bias"].append(sum(v - a for v, a in zip(values, actual)) / len(actual))
            scores[name]["top-50 pick"].append(sum(points_by_gw[gw].get(pid, 0) for pid in top) / len(top))
    summary = {name: {metric: round(sum(v) / len(v), 3) for metric, v in m.items()} for name, m in scores.items()}
    per_gw = {name: {metric: [round(x, 3) for x in v] for metric, v in m.items()} for name, m in scores.items()}
    result = {"test_gameweeks": list(test_gws), "average": summary, "per_gameweek": per_gw,
              "inputs": {"bootstrap": bootstrap_file, "fixtures": fixtures_file}}
    write_json(config.DATA_DIR / "checks" / "xpoints_backtest.json", result)
    print(f"Predictor check, gameweeks {min(test_gws)}-{max(test_gws)} (average over gameweeks):")
    print(f"  {'method':<8} {'correlation':>12} {'RMSE':>7} {'bias':>7} {'top-50 pick':>12}")
    for name, m in summary.items():
        print(f"  {name:<8} {m['correlation']:>12.3f} {m['RMSE']:>7.2f} {m['bias']:>7.2f} {m['top-50 pick']:>12.2f}")
    return result
