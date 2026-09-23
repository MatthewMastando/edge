-- Foundation: helper functions shared by every table.
-- Conventions (see README "Database conventions"):
--   * all timestamps are timestamptz stored in UTC; user-facing instants carry a *_tz column
--     holding the original IANA timezone name;
--   * money, prices and sizes are numeric, never float;
--   * enumerations are text with CHECK constraints so they can evolve with plain migrations;
--   * ids are uuid (gen_random_uuid()) unless a natural key is clearly better.

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

comment on function public.set_updated_at() is 'Trigger helper: stamps updated_at on row update.';
