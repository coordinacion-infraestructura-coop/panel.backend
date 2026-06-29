# svc-privada-adapter

Este directorio no contiene código backend. El svc-privada es el sistema existente
en producción en `essential-haiku-482815-u4`.

La integración se realiza exclusivamente vía API Gateway: las rutas `/api/v1/privada/*`
son proxy al Cloud Run existente.

Ver: `docs/context/areas/Privada Ministro/arquitectura_actual.md`
