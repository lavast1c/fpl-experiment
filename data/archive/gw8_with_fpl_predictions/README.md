# Gameweek 8: picks made while agents could see FPL's ep_next (not used)

On 2026-10-22 the three no-memory teams (H-none, S-none, O-none) picked their first squads with
prompt v1, whose player table included FPL's own expected points (`ep_next`). Their memory teams
copied those squads (shared start). Later that day, before the gameweek 8 deadline and before any
points were scored, the project removed `ep_next` from the agents' table (prompt v2) and the nine
AI teams picked again. See METHODS.md, 2026-10-22, "FPL's expected points removed from the agents'
table".

The change was made for every AI team, because of the input, not because of any particular pick.
These files are the original decisions, team states, memory and raw agent logs, kept unchanged
for transparency. They play no part in the experiment's scores. The three bots were not re-run:
they never used `ep_next`, and the player data had not changed.
