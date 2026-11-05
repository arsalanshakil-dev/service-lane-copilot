create table if not exists public.vehicle_records (
    serial text primary key,
    record jsonb not null,
    updated_at timestamptz not null default now(),
    constraint vehicle_records_serial_normalized
        check (serial = upper(btrim(serial))),
    constraint vehicle_records_record_is_object
        check (jsonb_typeof(record) = 'object'),
    constraint vehicle_records_record_serial_matches
        check (record ->> 'serial' = serial)
);

alter table public.vehicle_records enable row level security;

revoke all on table public.vehicle_records from public;
revoke all on table public.vehicle_records from anon, authenticated;
grant all privileges on table public.vehicle_records to service_role;

comment on table public.vehicle_records is
    'Synthetic demo vehicle record aggregates. Access only through the local FastAPI backend.';
