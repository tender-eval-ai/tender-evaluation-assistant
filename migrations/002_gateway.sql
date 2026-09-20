-- 002_gateway: the LLM gateway's shared state (app/gateway_pg.py).

-- migrate:up
-- Answers to identical model calls, keyed by chain, prompt version, prompt, images and
-- output shape (app.gateway._sha). Never paid twice, by any worker.
create table if not exists llm_cache (
  key            text primary key,
  kind           text not null,
  chain          jsonb not null,
  prompt_version text not null,
  project        text,
  value          text not null,
  created_at     timestamptz not null default now()
);
create index if not exists llm_cache_project on llm_cache (project);

-- One pace per provider: the next free slot; every caller takes the one after it.
create table if not exists llm_rate_limit (
  key       text primary key,
  next_slot timestamptz not null
);

-- Calls and dollars per project per day, against LLM_DAILY_BUDGET_*.
create table if not exists llm_budget (
  project text not null,
  day     date not null,
  calls   int not null default 0,
  usd     double precision not null default 0,
  primary key (project, day)
);

-- migrate:down
drop table if exists llm_budget;
drop table if exists llm_rate_limit;
drop table if exists llm_cache;
