-- Supabase schema for CyliaTales

create table if not exists profiles (
  id uuid primary key references auth.users(id),
  display_name text,
  is_parent boolean default true,
  created_at timestamptz default now()
);

create table if not exists projects (
  id uuid primary key default gen_random_uuid(),
  owner uuid references profiles(id),
  title text,
  plan text,
  pages int,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists orders (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references profiles(id),
  product_handle text,
  lemon_order_id text,
  status text,
  metadata jsonb,
  created_at timestamptz default now()
);

create table if not exists allowances (
  user_id uuid references profiles(id) primary key,
  starter_equivalent_books int default 0,
  video_seconds_remaining int default 0,
  tts_seconds_remaining int default 0,
  founder boolean default false,
  founder_expires_at timestamptz
);

create table if not exists renders (
  id uuid primary key default gen_random_uuid(),
  project_id uuid references projects(id),
  type text,
  status text,
  output_url text,
  duration_seconds int,
  created_at timestamptz default now()
);

create table if not exists admin_counter (
  key text primary key,
  value int default 0
);
