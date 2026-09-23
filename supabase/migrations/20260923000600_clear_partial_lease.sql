-- A job in `partial` is paused work, not a live lease. Stage 0 cleared `lease_until` on the
-- way back to `queued` and on terminal states, but a transition to `partial` left the lease
-- in place, so the worker query (`lease_until is null or lease_until < now()`) skipped it.
-- Clear the lease on `partial` as well, and reject a paused row that still holds one.

create or replace function public.jobs_enforce_transition()
returns trigger
language plpgsql
as $$
begin
  if old.state = new.state then
    return new;
  end if;
  if old.state in ('completed', 'failed', 'cancelled', 'budget_exceeded') then
    raise exception 'job % is terminal (%), cannot move to %', old.id, old.state, new.state
      using errcode = 'check_violation';
  end if;
  if old.state = 'queued' and new.state not in ('running', 'cancelled') then
    raise exception 'invalid job transition % -> %', old.state, new.state
      using errcode = 'check_violation';
  end if;
  if old.state = 'partial' and new.state not in
      ('running', 'completed', 'failed', 'cancelled', 'budget_exceeded') then
    raise exception 'invalid job transition % -> %', old.state, new.state
      using errcode = 'check_violation';
  end if;
  if new.state = 'running' and old.state <> 'running' then
    new.started_at := coalesce(new.started_at, now());
    new.attempts := old.attempts + 1;
  end if;
  if new.state in ('completed', 'failed', 'cancelled', 'budget_exceeded') then
    new.finished_at := coalesce(new.finished_at, now());
    new.lease_until := null;
    new.leased_by := null;
  end if;
  -- queued (lease expiry) and partial (paused, ready to resume) must both be leasable.
  if new.state in ('queued', 'partial') then
    new.lease_until := null;
    new.leased_by := null;
  end if;
  return new;
end;
$$;

alter table public.jobs
  drop constraint if exists jobs_paused_lease_clear;

alter table public.jobs
  add constraint jobs_paused_lease_clear
  check (
    state not in ('queued', 'partial')
    or (lease_until is null and leased_by is null)
  );
