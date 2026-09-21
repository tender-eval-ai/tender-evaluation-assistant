-- 004_review: a reviewer's confirmation of a checked tenderer's result (S4).

-- migrate:up
alter table results add column if not exists review_confirmed_by text;
alter table results add column if not exists review_confirmed_at timestamptz;

-- migrate:down
alter table results drop column if exists review_confirmed_at;
alter table results drop column if exists review_confirmed_by;
