# Gameweek 8: the stats bot's pick with the original expected points (not used)

On 2026-10-22 the stats bot picked its first squad using the original version of our expected
points (`experiment/xpoints.py`, `Settings()`). On 2026-10-23, before the gameweek 8 deadline and
before any points were scored, the project chose a season version of the predictor after testing
it on four past seasons (METHODS.md, 2026-10-23, "Expected points tested on four past seasons").
The stats bot then picked again with it.

The bot was re-run because its picks are made from these predictions, not because of any
particular pick. The AI teams and the other two bots were not re-run: they never see our
predictions. Every team's gameweek 8 expected points were recalculated with the season version.

These files are the original decision, team state and predictions (`xpoints/gw8.csv`), kept
unchanged for transparency. They play no part in the experiment's scores.
