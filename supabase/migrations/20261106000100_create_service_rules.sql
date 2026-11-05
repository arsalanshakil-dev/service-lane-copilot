-- Editable demo maintenance rules (issue #47).
-- Synthetic demo rules only; not manufacturer schedules. Access only through the local FastAPI backend.

create table if not exists public.service_rules (
    id text primary key,
    service_name text not null,
    coming_up_miles integer not null,
    due_miles integer not null,
    safety boolean not null default false,
    enabled boolean not null default true,
    change_log jsonb not null default '[]'::jsonb,
    updated_at timestamptz not null default now(),
    constraint service_rules_id_slug check (id ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    constraint service_rules_name_length check (char_length(btrim(service_name)) between 1 and 80),
    constraint service_rules_miles check (coming_up_miles >= 0 and coming_up_miles < due_miles and due_miles <= 200000),
    constraint service_rules_change_log_is_array check (jsonb_typeof(change_log) = 'array')
);

create unique index if not exists service_rules_name_unique on public.service_rules (lower(btrim(service_name)));

alter table public.service_rules enable row level security;

revoke all on table public.service_rules from public;
revoke all on table public.service_rules from anon, authenticated;
grant all privileges on table public.service_rules to service_role;

comment on table public.service_rules is
    'Editable synthetic demo maintenance rules (miles since last service). Access only through the local FastAPI backend.';

insert into public.service_rules (id, service_name, coming_up_miles, due_miles, safety, enabled, change_log) values
    ('engine-oil-and-filter', 'Engine oil and filter', 4000, 5000, false, true, '[{"action":"rule_seeded","actor":"migration","summary":"Starting demo rule."}]'),
    ('tire-rotation', 'Tire rotation', 6000, 7500, false, true, '[{"action":"rule_seeded","actor":"migration","summary":"Starting demo rule."}]'),
    ('vehicle-inspection', 'Vehicle inspection', 10000, 12000, false, true, '[{"action":"rule_seeded","actor":"migration","summary":"Starting demo rule."}]'),
    ('brake-inspection', 'Brake inspection', 12000, 15000, true, true, '[{"action":"rule_seeded","actor":"migration","summary":"Starting demo rule."}]'),
    ('cabin-air-filter', 'Cabin air filter', 12000, 15000, false, true, '[{"action":"rule_seeded","actor":"migration","summary":"Starting demo rule."}]'),
    ('wiper-blades', 'Wiper blades', 10000, 12000, false, true, '[{"action":"rule_seeded","actor":"migration","summary":"Starting demo rule."}]'),
    ('battery-test', 'Battery test', 16000, 20000, false, true, '[{"action":"rule_seeded","actor":"migration","summary":"Starting demo rule."}]'),
    ('engine-air-filter', 'Engine air filter', 25000, 30000, false, true, '[{"action":"rule_seeded","actor":"migration","summary":"Starting demo rule."}]')
on conflict (id) do nothing;
