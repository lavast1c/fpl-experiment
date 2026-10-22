-- Shared start (METHODS.md, 2026-10-22): a memory team's first squad is copied from its model's
-- no-memory team. This column says which team it was copied from (null for every other decision).
alter table public.decisions add column copied_from text;
