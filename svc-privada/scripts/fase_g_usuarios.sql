-- Fase G — Alta de usuarios de Secretaría Privada en portal_usuarios
-- ============================================================================
-- Corre contra db_vivienda (NO db_privada): portal_usuarios vive en svc-vivienda
-- (ADR-003 / ADR-015). Ejecutar con el cloud-sql-proxy apuntando a
-- ministerio-postgres y psql -d db_vivienda.
--
-- Origen: services/svc-privada/anexos/C_usuarios_roles.csv (18 filas).
-- Excluidos a propósito:
--   * infraestructura.coop@gmail.com, pedrobonafe.data@gmail.com,
--     test.operador@ministerio-test.com  -> cuentas gateway/test marcadas Admin
--     en el sistema viejo; no son personal de Privada. Si se necesitan, alta manual.
--   * prueba@gmail.com  -> activo=false en el origen.
--
-- Idempotente:
--   * portal_usuarios: ON CONFLICT (email) DO NOTHING -> si el usuario ya existe
--     (p. ej. bonafepedro@gmail.com como Admin del portal) NO se le pisa rol/nombre.
--   * portal_usuario_secretarias: ON CONFLICT DO NOTHING -> agrega 'privada' sin
--     duplicar ni tocar otras secretarías que ya tenga.
-- ============================================================================

BEGIN;

-- 1) Alta de los usuarios que aún no existen (rol 1:1 con el sistema viejo)
INSERT INTO portal_usuarios (email, nombre, rol, activo, created_by, updated_by)
VALUES
  ('bonafepedro@gmail.com',            'Pedro Bonafe',        'Admin',      true, 'migracion-svc-privada', 'migracion-svc-privada'),
  ('priv.infracoop@gmail.com',         'Secretaría Infraestructura Molinari', 'Consulta',  true, 'migracion-svc-privada', 'migracion-svc-privada'),
  ('labotech.analytics@gmail.com',     'Labo Tech',           'Operador',   true, 'migracion-svc-privada', 'migracion-svc-privada'),
  ('mattiasmz22@gmail.com',            'Matías Chávez',       'Operador',   true, 'migracion-svc-privada', 'migracion-svc-privada'),
  ('aguirrevictoriamariela@gmail.com', 'Victoria Aguirre',    'Supervisor', true, 'migracion-svc-privada', 'migracion-svc-privada'),
  ('amuchasteguivocalacj@gmail.com',   'Juan Amuchastegui',   'Supervisor', true, 'migracion-svc-privada', 'migracion-svc-privada'),
  ('anonimo.conocido65@gmail.com',     'Fernando Zaya',       'Supervisor', true, 'migracion-svc-privada', 'migracion-svc-privada'),
  ('ariasmelisa.ofi@gmail.com',        'Melisa Arias',        'Supervisor', true, 'migracion-svc-privada', 'migracion-svc-privada'),
  ('fabricdiaz@gmail.com',             'Fabricio Díaz',       'Supervisor', true, 'migracion-svc-privada', 'migracion-svc-privada'),
  ('gustavomasotti75@gmail.com',       'Gustavo Massotti',    'Supervisor', true, 'migracion-svc-privada', 'migracion-svc-privada'),
  ('lorena752aguilar@gmail.com',       'Lorena Aguilar',      'Supervisor', true, 'migracion-svc-privada', 'migracion-svc-privada'),
  ('marcelaluquee@gmail.com',          'Marcela Luque',       'Supervisor', true, 'migracion-svc-privada', 'migracion-svc-privada'),
  ('vanetoranzo@gmail.com',            'Vaneza Toranzo',      'Supervisor', true, 'migracion-svc-privada', 'migracion-svc-privada')
ON CONFLICT (email) DO NOTHING;

-- 2) Asignar la secretaría 'privada' a todos (incluye a quien ya existiera)
INSERT INTO portal_usuario_secretarias (email, secretaria)
SELECT email, 'privada'
FROM (VALUES
  ('bonafepedro@gmail.com'),
  ('priv.infracoop@gmail.com'),
  ('labotech.analytics@gmail.com'),
  ('mattiasmz22@gmail.com'),
  ('aguirrevictoriamariela@gmail.com'),
  ('amuchasteguivocalacj@gmail.com'),
  ('anonimo.conocido65@gmail.com'),
  ('ariasmelisa.ofi@gmail.com'),
  ('fabricdiaz@gmail.com'),
  ('gustavomasotti75@gmail.com'),
  ('lorena752aguilar@gmail.com'),
  ('marcelaluquee@gmail.com'),
  ('vanetoranzo@gmail.com')
) AS s(email)
ON CONFLICT (email, secretaria) DO NOTHING;

-- 3) Verificación
SELECT u.email, u.nombre, u.rol, u.activo,
       array_agg(ps.secretaria ORDER BY ps.secretaria) AS secretarias
FROM portal_usuarios u
JOIN portal_usuario_secretarias ps ON ps.email = u.email
WHERE ps.email IN (
  SELECT email FROM portal_usuario_secretarias WHERE secretaria = 'privada'
)
GROUP BY u.email, u.nombre, u.rol, u.activo
ORDER BY u.rol, u.email;

COMMIT;
