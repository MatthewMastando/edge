-- Stage 4 (records): preserve original CSV cells per imported fill for source-row provenance.

alter table public.imported_fills
  add column if not exists source_row_raw jsonb;

comment on column public.imported_fills.source_row_raw is
  'Original CSV column values for this row (keys are file headers).';
