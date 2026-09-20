-- 003_api: the audit log and the rule-set columns the API needs.

-- migrate:up
alter table rulesets add column if not exists created_by text;
alter table rulesets add column if not exists updated_by text;
alter table rulesets add column if not exists confirmed_by text;
alter table rulesets add column if not exists parent_version int;

-- Append-only: every mutating route writes one row (docs/api_contract.md, Conventions).
create table if not exists events (
  id      bigserial primary key,
  kind    text not null,
  project text not null,
  subject text,
  before  jsonb,
  after   jsonb,
  actor   text not null,
  reason  text,
  at      timestamptz not null default now()
);
create index if not exists events_project_id on events (project, id);

-- migrate:down
drop table if exists events;
alter table rulesets drop column if exists parent_version;
alter table rulesets drop column if exists confirmed_by;
alter table rulesets drop column if exists updated_by;
alter table rulesets drop column if exists created_by;
