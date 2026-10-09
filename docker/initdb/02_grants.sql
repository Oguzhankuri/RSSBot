-- Yalnızca service_role tablolara erişir; anon hiçbir şey göremez (RLS + yetki yok).
grant usage on schema public to anon, service_role;
grant select, insert, update, delete on all tables in schema public to service_role;
alter default privileges in schema public grant select, insert, update, delete on tables to service_role;
