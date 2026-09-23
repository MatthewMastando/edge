-- Sources, conversations and artifacts.
-- Relationships (plan item 9): a conversation has many runs; a run produces at most one artifact
-- revision; an artifact has many immutable revisions plus one autosaved draft.

create table public.sources (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in
    ('web_search', 'web_page', 'fred', 'sec_filing', 'eia', 'usda',
     'central_bank_calendar', 'release_calendar')),
  url text,
  title text,
  publisher text,
  published_at timestamptz,
  retrieved_at timestamptz not null,
  provider text not null,
  provenance text not null check (provenance in ('fixture', 'recorded', 'live')),
  content_hash text,
  status text not null default 'ok' check (status in ('ok', 'stale', 'failed', 'rate_limited')),
  error text,
  created_at timestamptz not null default now()
);

create index sources_url_idx on public.sources (url);
create index sources_retrieved_idx on public.sources (retrieved_at desc);

create table public.source_excerpts (
  id uuid primary key default gen_random_uuid(),
  source_id uuid not null references public.sources (id) on delete cascade,
  text text not null check (char_length(text) <= 4000),
  start_offset integer,
  end_offset integer,
  published_at timestamptz,
  retrieved_at timestamptz not null,
  provenance text not null check (provenance in ('fixture', 'recorded', 'live')),
  created_at timestamptz not null default now()
);

create index source_excerpts_source_idx on public.source_excerpts (source_id);

create table public.conversations (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid,
  title text,
  context jsonb not null default '{}'::jsonb,   -- attached instrument / watchlist / artifact
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  archived_at timestamptz
);

create trigger conversations_set_updated_at
  before update on public.conversations
  for each row execute function public.set_updated_at();

create table public.messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations (id) on delete cascade,
  role text not null check (role in ('system', 'developer', 'user', 'assistant', 'tool')),
  content text not null,
  run_id uuid,                          -- FK added once runs exists
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index messages_conversation_idx on public.messages (conversation_id, created_at);

create table public.artifacts (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid,
  conversation_id uuid references public.conversations (id) on delete set null,
  kind text not null check (kind in ('thesis', 'brief', 'report', 'chart', 'event_brief')),
  title text not null,
  tags text[] not null default '{}',
  instrument_id uuid references public.instruments (id) on delete set null,
  contract_code text,
  current_revision_id uuid,             -- FK added below
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  archived_at timestamptz
);

create index artifacts_owner_idx on public.artifacts (owner_id, updated_at desc);
create index artifacts_tags_idx on public.artifacts using gin (tags);
create index artifacts_instrument_idx on public.artifacts (instrument_id);

create trigger artifacts_set_updated_at
  before update on public.artifacts
  for each row execute function public.set_updated_at();

create table public.artifact_revisions (
  id uuid primary key default gen_random_uuid(),
  artifact_id uuid not null references public.artifacts (id) on delete cascade,
  revision_number integer not null check (revision_number >= 1),
  parent_revision_id uuid references public.artifact_revisions (id) on delete set null,
  run_id uuid,                          -- FK added once runs exists
  structured jsonb not null,            -- Thesis contract (structured block + findings)
  presentation_markdown text not null,
  change_kind text not null check (change_kind in
    ('generated', 'narrative_edit', 'structured_edit', 'proposed_edit_accepted')),
  created_by text not null check (created_by in ('user', 'agent')),
  is_demonstration boolean not null default false,
  provenance text not null check (provenance in ('fixture', 'recorded', 'live')),
  created_at timestamptz not null default now(),
  unique (artifact_id, revision_number)
);

comment on table public.artifact_revisions is
  'Immutable saved revisions. Narrative edits preserve the original; structured edits create a recalculated version.';

alter table public.artifacts
  add constraint artifacts_current_revision_fk
  foreign key (current_revision_id) references public.artifact_revisions (id) on delete set null;

create table public.artifact_drafts (
  artifact_id uuid primary key references public.artifacts (id) on delete cascade,
  base_revision_id uuid references public.artifact_revisions (id) on delete set null,
  structured jsonb,
  presentation_markdown text,
  updated_at timestamptz not null default now()
);

comment on table public.artifact_drafts is 'One autosaved draft per artifact.';

create table public.artifact_proposed_edits (
  id uuid primary key default gen_random_uuid(),
  artifact_id uuid not null references public.artifacts (id) on delete cascade,
  base_revision_id uuid not null references public.artifact_revisions (id) on delete cascade,
  run_id uuid,
  proposal jsonb not null,              -- structured/presentation diff proposed by the agent
  status text not null default 'pending' check (status in ('pending', 'accepted', 'rejected')),
  resolved_at timestamptz,
  created_at timestamptz not null default now()
);

create index artifact_proposed_edits_idx on public.artifact_proposed_edits (artifact_id, status);
