-- Roles de db_agente (spec-agente-consultas.md §2.3, ADR-033).
-- Correr UNA vez como usuario administrador (postgres) contra la instancia ministerio-postgres,
-- ANTES de `alembic upgrade head`. Las contraseñas se generan aparte y van a Secret Manager;
-- nunca se commitean (reemplazar los :'pwd_*' con \set en psql).
--
--   psql "host=127.0.0.1 port=5432 user=postgres dbname=postgres" \
--        -v pwd_app='...' -v pwd_llm='...' -v pwd_ro='...' -f sql/roles_db_agente.sql

CREATE ROLE agente_app LOGIN PASSWORD :'pwd_app';
CREATE ROLE agente_llm LOGIN PASSWORD :'pwd_llm' NOINHERIT;
CREATE ROLE agente_ro  LOGIN PASSWORD :'pwd_ro'  NOINHERIT;

CREATE DATABASE db_agente OWNER agente_app;

\connect db_agente
-- El rol del modelo no puede crear nada ni leer el schema public (conversaciones, auditoría).
REVOKE ALL ON DATABASE db_agente FROM PUBLIC;
GRANT CONNECT ON DATABASE db_agente TO agente_app, agente_llm;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM agente_llm;
ALTER ROLE agente_llm SET search_path = ag;
ALTER ROLE agente_llm SET default_transaction_read_only = on;
ALTER ROLE agente_llm SET statement_timeout = '10s';
ALTER ROLE agente_llm SET work_mem = '16MB';
ALTER ROLE agente_llm CONNECTION LIMIT 5;
-- Los GRANT sobre ag.* los aplica la migración 0001 (el schema todavía no existe acá).
