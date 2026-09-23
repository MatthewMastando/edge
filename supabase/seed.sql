-- Local seed. Instruments and contracts are loaded from the fixture manifest by the persistence
-- layer (Stage 1B); only non-secret defaults live here.

insert into public.settings (key, value, description) values
  ('display_timezone', '"America/New_York"', 'Default UI timezone; storage is always UTC'),
  ('llm_model', 'null', 'Server-side model name; null until verified with a live provider'),
  ('research_defaults', '{"max_external_calls": 12, "evidence_pack_tokens": 25000, "timeout_seconds": 180, "repair_attempts": 1}',
   'Initial harness limits from the build spec')
on conflict (key) do nothing;

insert into public.budgets (category, period_start, limit_usd) values
  ('ai_search', date_trunc('month', now())::date, 100),
  ('market_data', date_trunc('month', now())::date, 0)
on conflict (category, period_start) do nothing;
