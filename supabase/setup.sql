-- Long Live Lino: the shared sky.
-- Paste this whole file into Supabase → SQL Editor → New query → Run. Safe to run again.

create table if not exists public.lights (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  nx          real not null check (nx between -1.5 and 1.5),       -- where on screen it was lit (-1..1)
  ny          real not null check (ny between -1.5 and 1.5),
  z           real not null check (z between -2000 and -100),      -- depth in the sky
  message     text check (char_length(message) <= 280),
  name        text check (char_length(name) <= 40),                -- null = anonymous
  hidden      boolean not null default false                       -- set true to take a light down
);

alter table public.lights enable row level security;

-- anyone can read the lights that aren't hidden, and leave a new one; nobody but you can edit or delete
drop policy if exists "read visible lights" on public.lights;
create policy "read visible lights" on public.lights
  for select to anon, authenticated using (hidden = false);

drop policy if exists "leave a light" on public.lights;
create policy "leave a light" on public.lights
  for insert to anon, authenticated with check (hidden = false);

revoke update, delete on public.lights from anon, authenticated;

-- keep a flood from filling the sky: at most 40 new lights a minute, across everyone
create or replace function public.lights_flood_guard() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if (select count(*) from public.lights where created_at > now() - interval '1 minute') >= 40 then
    raise exception 'The sky is busy, try again in a minute';
  end if;
  return new;
end $$;

drop trigger if exists lights_flood_guard on public.lights;
create trigger lights_flood_guard before insert on public.lights
  for each row execute function public.lights_flood_guard();

-- new lights appear live on every open screen
do $$ begin
  alter publication supabase_realtime add table public.lights;
exception when duplicate_object then null;
end $$;
