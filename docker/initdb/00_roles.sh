#!/bin/sh
# Supabase ile aynı rol modeli: anon (hiçbir yetki yok), service_role (RLS'i atlar), authenticator (PostgREST girişi).
set -eu
psql -v ON_ERROR_STOP=1 --username postgres --dbname postgres <<SQL
create role anon nologin;
create role service_role nologin bypassrls;
create role authenticator login noinherit password '${AUTHENTICATOR_PASSWORD}';
grant anon to authenticator;
grant service_role to authenticator;
SQL
