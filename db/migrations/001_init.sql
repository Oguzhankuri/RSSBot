-- RSSBot v2 şeması. Supabase → SQL Editor → bu dosyanın tamamını yapıştır → Run.
-- Uygulama yalnızca service_role anahtarıyla bağlanır; RLS açık ve anonim erişim YOK.

create table if not exists ideas (
  id text primary key,
  text text not null,
  source text not null default 'panel',          -- panel | telegram
  priority int not null default 3,               -- 1 (düşük) – 5 (acil)
  status text not null default 'yeni',           -- yeni | kullanildi | arsiv
  tags jsonb not null default '[]',
  category text,
  suggested_format text,                         -- yatay | dikey
  used_in jsonb not null default '[]',           -- content id listesi
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create table if not exists seen_items (
  id text primary key,                           -- haber linki / kimliği
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create table if not exists runs (
  id text primary key,
  date text not null unique,                     -- YYYY-MM-DD
  status text not null default 'aktif',          -- aktif | bitti
  plan jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create table if not exists run_steps (
  id text primary key,                           -- <run_id>:<key>
  run_id text not null references runs(id) on delete cascade,
  key text not null,
  position int not null,
  actor text not null,                           -- pc | colab | user
  status text not null default 'bekliyor',       -- bekliyor | sirada | calisiyor | tamam | hata | atlandi
  message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create table if not exists contents (
  id text primary key,
  run_id text references runs(id) on delete set null,
  date text not null,
  format text not null,                          -- yatay | dikey
  title text not null,
  source_title text,
  source_url text,
  script text,
  summary text,
  hook text,
  tags jsonb not null default '[]',
  idea_id text references ideas(id) on delete set null,
  folder text,                                   -- output kökünden göreli yol
  features jsonb not null default '{}',
  yt_video_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create table if not exists ratings (
  id text primary key,
  content_id text not null references contents(id) on delete cascade,
  score int not null check (score between 1 and 5),
  note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create table if not exists metrics (
  id text primary key,
  content_id text not null references contents(id) on delete cascade,
  yt_video_id text not null,
  views bigint,
  avg_view_duration double precision,
  avg_view_pct double precision,
  likes bigint,
  comments bigint,
  subs_gained bigint,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create table if not exists insights (
  id text primary key,
  rule text not null,
  format text,                                   -- null = tüm formatlar
  confidence double precision not null default 0.5,
  evidence int not null default 0,
  active boolean not null default true,
  approved boolean not null default false,       -- kullanıcı onayladıysa reflect silmez
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create table if not exists kv (
  id text primary key,
  value jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create index if not exists contents_date_idx on contents(date);
create index if not exists contents_run_idx on contents(run_id);
create index if not exists run_steps_run_idx on run_steps(run_id);
create index if not exists metrics_content_idx on metrics(content_id);

alter table ideas enable row level security;
alter table seen_items enable row level security;
alter table runs enable row level security;
alter table run_steps enable row level security;
alter table contents enable row level security;
alter table ratings enable row level security;
alter table metrics enable row level security;
alter table insights enable row level security;
alter table kv enable row level security;
-- Bilerek hiçbir policy tanımlanmadı: anon/authenticated rolleri hiçbir satırı göremez.
-- service_role RLS'i atlar.
