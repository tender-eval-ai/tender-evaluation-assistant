-- 001_jobs: the check worker's tables (app/jobs). Procrastinate's own tables are created
-- by the library (app.jobs.queue.apply_schema), not here.

-- migrate:up
create table if not exists runs (
  run_id          text primary key,
  project         text not null,
  tenderer        text not null,
  kind            text not null,
  state           text not null check (state in ('queued', 'running', 'paused', 'done', 'failed', 'dead')),
  step            text,
  progress        jsonb not null default '{}'::jsonb,
  attempt         int not null default 1,
  job_id          bigint,
  worker_pid      int,
  ruleset_version int,
  error           text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists runs_project_tenderer on runs (project, tenderer);
create index if not exists runs_state on runs (state);

-- Per-run progress: the steps finished so far and the data they produced, plus the
-- checkpoints a step writes inside itself (after each batch of pages).
create table if not exists job_steps (
  run_id     text primary key references runs (run_id) on delete cascade,
  done       jsonb not null default '[]'::jsonb,
  data       jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

-- What the API reads: the extracted fields, the verdict pinned to a rule-set version,
-- and the reviewer's corrections kept beside the model's values.
create table if not exists results (
  run_id          text primary key references runs (run_id) on delete cascade,
  project         text not null,
  tenderer        text not null,
  ruleset_version int not null,
  fields          jsonb not null,
  verdict         jsonb not null,
  corrections     jsonb not null default '{}'::jsonb,
  updated_at      timestamptz not null default now()
);
create index if not exists results_project on results (project);

-- Rule-set versions per project. `spec` holds the rule set as JSON (app/rulesets/schema.py
-- from S3 on; a plain dict for the harness). A draft becomes confirmed in place; a
-- published change is a new confirmed version.
create table if not exists rulesets (
  project      text not null,
  version      int not null,
  status       text not null check (status in ('draft', 'confirmed')),
  spec         jsonb not null,
  created_at   timestamptz not null default now(),
  confirmed_at timestamptz,
  primary key (project, version)
);

-- migrate:down
drop table if exists results;
drop table if exists job_steps;
drop table if exists rulesets;
drop table if exists runs;
