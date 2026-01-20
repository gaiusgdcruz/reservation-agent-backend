-- Enable UUID extension
create extension if not exists "uuid-ossp";

-- Users table (identified by phone number)
create table if not exists users (
  id uuid primary key default uuid_generate_v4(),
  contact_number text unique not null,
  name text,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- Appointments table
create table if not exists appointments (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references users(id) not null,
  start_time timestamp with time zone not null,
  end_time timestamp with time zone not null,
  status text default 'booked' check (status in ('booked', 'cancelled', 'completed')),
  details text,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- Index for faster retrieval by contact number
create index if not exists idx_users_contact on users(contact_number);
create index if not exists idx_appointments_user on appointments(user_id);
create index if not exists idx_appointments_start on appointments(start_time);

-- Summaries table for conversation history
create table if not exists summaries (
  id text primary key,
  user_id uuid references users(id),
  content text,
  bookings_snapshot jsonb,
  timestamp text,
  created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

create index if not exists idx_summaries_user on summaries(user_id);
create index if not exists idx_summaries_created on summaries(created_at);
