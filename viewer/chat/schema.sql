-- ShadowBroker public viewer chat: database rules for a Supabase project.
--
-- Paste this whole file into the Supabase SQL editor once (it is safe to
-- re-run). It creates two small tables and the rules that keep the chat
-- room safe when the only thing between the internet and the database is
-- the browser:
--
--   * anyone may READ visible messages and usernames;
--   * only a signed-in person may POST, only as themselves, only after
--     picking a username, and only at a human pace;
--   * nobody can set their own "banned" or "moderator" flag;
--   * moderators can hide messages and ban accounts.
--
-- The chat service is completely separate from the ShadowBroker engine. It
-- never sees map data, API keys or anything about the engine machine.

create extension if not exists citext;

-- ── Profiles: one chosen username per account ──────────────────────────────

create table if not exists public.profiles (
  id          uuid primary key references auth.users (id) on delete cascade,
  username    citext not null unique,
  created_at  timestamptz not null default now(),
  banned      boolean not null default false,
  is_mod      boolean not null default false,
  constraint username_shape check (username::text ~ '^[A-Za-z0-9_]{3,20}$')
);

-- Names that would let someone pose as the project or as staff.
create or replace function public.chat_check_username()
returns trigger
language plpgsql
as $$
begin
  if lower(new.username::text) ~ '(admin|moderator|^mod$|^mods$|shadowbroker|shadow_broker|official|support|system|staff)' then
    raise exception 'That username is reserved. Pick another.' using errcode = 'P0001';
  end if;
  return new;
end
$$;

drop trigger if exists chat_check_username on public.profiles;
create trigger chat_check_username
  before insert or update of username on public.profiles
  for each row execute function public.chat_check_username();

-- ── Messages ───────────────────────────────────────────────────────────────

create table if not exists public.messages (
  id          bigint generated always as identity primary key,
  user_id     uuid not null references auth.users (id) on delete cascade,
  username    text not null,
  body        text not null,
  created_at  timestamptz not null default now(),
  hidden      boolean not null default false,
  constraint body_length check (char_length(body) between 1 and 500)
);

create index if not exists messages_recent on public.messages (id desc) where not hidden;
create index if not exists messages_by_user on public.messages (user_id, created_at desc);

-- Every post goes through this. The browser only supplies the text; who
-- wrote it, when, and under what name are filled in here and cannot be
-- forged. It also enforces the pace limits.
create or replace function public.chat_before_insert()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  author  public.profiles;
  recent  integer;
begin
  if auth.uid() is null then
    raise exception 'Sign in to chat.' using errcode = 'P0001';
  end if;

  select * into author from public.profiles where id = auth.uid();
  if author.id is null then
    raise exception 'Pick a username first.' using errcode = 'P0001';
  end if;
  if author.banned then
    raise exception 'This account cannot post.' using errcode = 'P0001';
  end if;

  if exists (
    select 1 from public.messages
    where user_id = auth.uid() and created_at > now() - interval '3 seconds'
  ) then
    raise exception 'Slow down a little.' using errcode = 'P0001';
  end if;

  select count(*) into recent from public.messages
  where user_id = auth.uid() and created_at > now() - interval '1 minute';
  if recent >= 10 then
    raise exception 'Too many messages. Try again in a minute.' using errcode = 'P0001';
  end if;

  new.user_id    := auth.uid();
  new.username   := author.username::text;
  new.created_at := now();
  new.hidden     := false;
  -- Plain text only: collapse control characters and trim.
  new.body := btrim(regexp_replace(new.body, '[[:cntrl:]]+', ' ', 'g'));
  if char_length(new.body) = 0 then
    raise exception 'Message is empty.' using errcode = 'P0001';
  end if;
  return new;
end
$$;

drop trigger if exists chat_before_insert on public.messages;
create trigger chat_before_insert
  before insert on public.messages
  for each row execute function public.chat_before_insert();

-- ── Reports: "flag this message" ───────────────────────────────────────────

create table if not exists public.reports (
  id          bigint generated always as identity primary key,
  message_id  bigint not null references public.messages (id) on delete cascade,
  reporter    uuid not null default auth.uid() references auth.users (id) on delete cascade,
  created_at  timestamptz not null default now(),
  unique (message_id, reporter)
);

-- ── Who may do what ────────────────────────────────────────────────────────

alter table public.profiles enable row level security;
alter table public.messages enable row level security;
alter table public.reports  enable row level security;

-- Start from nothing, then grant exactly the columns each role needs.
revoke all on public.profiles, public.messages, public.reports from anon, authenticated;

grant select (id, username)                 on public.profiles to anon, authenticated;
grant insert (id, username)                 on public.profiles to authenticated;
grant select (id, username, body, created_at) on public.messages to anon, authenticated;
grant insert (body)                         on public.messages to authenticated;
grant update (hidden)                       on public.messages to authenticated;
grant update (banned)                       on public.profiles to authenticated;
grant insert (message_id)                   on public.reports  to authenticated;
grant select                                on public.reports  to authenticated;

create or replace function public.chat_is_mod()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (select 1 from public.profiles where id = auth.uid() and is_mod and not banned);
$$;

drop policy if exists profiles_read        on public.profiles;
drop policy if exists profiles_create_own  on public.profiles;
drop policy if exists profiles_mod_ban     on public.profiles;
drop policy if exists messages_read        on public.messages;
drop policy if exists messages_post        on public.messages;
drop policy if exists messages_mod_hide    on public.messages;
drop policy if exists reports_create       on public.reports;
drop policy if exists reports_mod_read     on public.reports;

create policy profiles_read       on public.profiles for select using (true);
-- One profile per account, created by its owner. Usernames are permanent:
-- there is no update grant on the username column.
create policy profiles_create_own on public.profiles for insert to authenticated
  with check (id = auth.uid());
create policy profiles_mod_ban    on public.profiles for update to authenticated
  using (public.chat_is_mod()) with check (public.chat_is_mod());

create policy messages_read       on public.messages for select using (not hidden or public.chat_is_mod());
create policy messages_post       on public.messages for insert to authenticated with check (true);
create policy messages_mod_hide   on public.messages for update to authenticated
  using (public.chat_is_mod()) with check (public.chat_is_mod());

create policy reports_create      on public.reports for insert to authenticated
  with check (reporter = auth.uid());
create policy reports_mod_read    on public.reports for select to authenticated
  using (public.chat_is_mod());

-- ── Housekeeping ───────────────────────────────────────────────────────────

-- Keep the room small: call this from a scheduled job (Database > Cron) or
-- run it by hand. It removes messages older than 30 days.
create or replace function public.chat_prune()
returns void
language sql
security definer
set search_path = public
as $$
  delete from public.messages where created_at < now() - interval '30 days';
$$;
revoke all on function public.chat_prune() from anon, authenticated;

-- To make yourself a moderator after you have signed in once and picked a
-- username, run (with your username):
--   update public.profiles set is_mod = true where username = 'your_name';
