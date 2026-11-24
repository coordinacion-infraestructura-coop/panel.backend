"""Sync de las inscripciones del "Congreso de Formación Digital 2026" a Planificación
(docs/files/spec-privada-sync-capacitacion.md).

Lee el Sheet de respuestas del formulario de Google, lo espeja en
`priv_capacitacion_inscripcion` y escribe, por localidad, los conteos y nombres en las columnas
automáticas del programa de Planificación, junto con un estado automático ("Con inscriptos" o
"Solo intendente / jefe comunal"). Nunca pisa un estado puesto por una persona (§4.2).

Las escrituras de Planificación pasan por `planificacion.service.actualizar_localidad`, así que
quedan en `priv_plan_historial` y en `priv_audit_log` igual que una edición desde la pantalla.
Los logs llevan conteos, nunca nombres.
"""
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.auth import AuthUser
from app.capacitacion.models import CapacitacionInscripcion
from app.common import now_utc
from app.config import settings
from app.geo_matching import candidatos_localidad, normalize_departamento, normalize_name
from app.integrations import google_sheets
from app.planificacion import service as planif
from app.planificacion.models import PlanColumna, PlanEstado, PlanLocalidad, PlanPrograma
from app.territorial.models import GeoLocalidad

logger = logging.getLogger(__name__)

ACTOR = AuthUser(uid="sync-capacitacion", email="sync-capacitacion@system", role="system", secretarias=[])

CAPACITACION = "congreso-formacion-digital-2026"
PROGRAMA_NOMBRE = "Congreso de Formación Digital 2026"
PROGRAMA_DESCRIPCION = (
    "Inscriptos al congreso para líderes territoriales y equipos de comunicación (sábado 28/11/2026). "
    "Las columnas y estados \"(automático)\" los actualiza solo el formulario de inscripción cada 15 minutos."
)

ESTADO_CON = {"nombre": "Con inscriptos", "color_bg": "#C8E6C9", "color_texto": "#1B5E20"}
ESTADO_SOLO_LIDER = {"nombre": "Solo intendente / jefe comunal", "color_bg": "#FFF9C4", "color_texto": "#8D6E00"}

COLUMNAS_AUTO: list[dict[str, str]] = [
    {"clave": "insc_total", "nombre": "Inscriptos en total (automático)", "tipo": "numero"},
    {"clave": "insc_lider", "nombre": "Intendente / jefe comunal inscripto (automático)", "tipo": "si_no"},
    {"clave": "insc_equipo", "nombre": "Equipo de comunicación (automático)", "tipo": "numero"},
    {"clave": "insc_otros", "nombre": "Legisladores / ministros (automático)", "tipo": "numero"},
    {"clave": "insc_nombres", "nombre": "Inscriptos – nombres (automático)", "tipo": "texto_largo"},
    {"clave": "insc_ultima", "nombre": "Última inscripción (automático)", "tipo": "fecha"},
]
CLAVES_AUTO = [c["clave"] for c in COLUMNAS_AUTO]

CARGOS_LIDER = {"intendente", "jefe comunal"}
CARGO_EQUIPO = "equipo de comunicacion"

# Opciones del desplegable que no cruzan por nombre con el padrón oficial (§5). Revisadas a mano el
# 2026-11-24 con los mismos criterios que la recarga del semáforo de ese día. Clave: nombre
# normalizado de la opción (`normalize_name`).
VINCULACION_MANUAL: dict[str, str] = {
    "alcira gigena": "161",                       # ALCIRA - EST. GIGENA
    "bouwer": "303",                              # BOWER
    "brinkmann": "269",                           # BRINCKMANN
    "canada del sauce": "510",                    # VILLA CAÑADA DEL SAUCE
    "capitan general bernardo o higgins": "103",  # CAP. GRAL. B.OHIGGINS (COLONIA PROGRESO)
    "colonia barge": "105",                       # CASTRO URDIALES - COLONIA 25 DE MAYO (confirmado por el usuario)
    "corral de bustos ifflinger": "107",          # CORRAL DE BUSTOS
    "estacion general paz": "26",                 # GENERAL PAZ
    "general levalle": "128",                     # GENERAL LE VALLE
    "huanchilla": "92",                           # HUANCHILLAS
    "james craik": "327",                         # JAMES CRAICK
    "las bajadas": "7",                           # LAS BAJADAS (no SOCONCHO (LAS BAJADAS), 387)
    "las penas sud": "175",                       # LAS PEÑAS SUR
    "lucio v mansilla": "350",                    # LUCIO V. MANSILLA
    "nicolas bruzzone": "55",                     # NICOLAS BRUZONE
    "pacheco de melo": "96",                      # ESTACION PACHECO DE MELO
    "parque calmayo": "2",                        # CALMAYO
    "paso del durazno": "443",                    # la Lista la pone en Juárez Celman; el padrón, en Río Cuarto
    "riobamba": "133",                            # RIO BAMBA
    "san javier y yacanto": "261",                # SAN JAVIER
    "saturnino maria laspiur": "296",             # SATURNINO M. LASPIUR
    "villa candelaria norte": "220",              # VILLA CANDELARIA
    "villa de maria": "221",                      # VILLA DE MARIA DE RIO SECO
    "villa rio icho cruz": "158",                 # ICHO CRUZ
}

_TZ_FORMULARIO = timezone(timedelta(hours=-3))  # la planilla está en hora de Argentina
_EPOCA_SHEETS = datetime(1899, 12, 30)


# --- lectura de la planilla ----------------------------------------------------------------

def _norm_header(s: Any) -> str:
    return re.sub(r"\s+", " ", normalize_name(str(s or ""))).strip()


def _dep(s: str | None) -> str:
    return re.sub(r"[.\s]+", " ", normalize_departamento(s)).strip()


def _texto(v: Any) -> str | None:
    if v is None:
        return None
    t = re.sub(r"\s+", " ", str(v)).strip()
    return t or None


def _fecha_serial(v: Any) -> datetime | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return (_EPOCA_SHEETS + timedelta(days=float(v))).replace(microsecond=0, tzinfo=_TZ_FORMULARIO)


def _naive_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _indices(header: list, requeridas: dict[str, str]) -> dict[str, int]:
    norm = [_norm_header(h) for h in header]
    out = {}
    for clave, titulo in requeridas.items():
        if titulo not in norm:
            raise google_sheets.SheetReadError(f"La planilla no tiene la columna '{titulo}'")
        out[clave] = norm.index(titulo)
    return out


@dataclass
class Respuesta:
    fila: int
    marca: datetime
    email_hash: str
    apellido: str | None
    nombre: str | None
    cargo: str | None
    localidad: str | None
    departamento: str | None = None
    id_geo: str | None = None
    match_tipo: str = "sin_match"


def parsear(respuestas: list[list], lista: list[list]) -> tuple[list[Respuesta], dict[str, str], int]:
    """Devuelve (respuestas válidas, {opción normalizada: departamento}, filas descartadas)."""
    if not respuestas:
        return [], {}, 0
    ir = _indices(respuestas[0], {
        "marca": "marca temporal", "email": "direccion de correo electronico", "apellido": "apellido",
        "nombre": "nombre", "localidad": "localidad", "cargo": "cargo",
    })
    deptos: dict[str, str] = {}
    if lista:
        il = _indices(lista[0], {"departamento": "departamento", "localidad": "localidad"})
        for row in lista[1:]:
            loc = _texto(row[il["localidad"]] if len(row) > il["localidad"] else None)
            dep = _texto(row[il["departamento"]] if len(row) > il["departamento"] else None)
            if loc:
                deptos[normalize_name(loc)] = dep or ""

    def celda(row: list, k: str) -> Any:
        i = ir[k]
        return row[i] if len(row) > i else None

    out, descartadas = [], 0
    for n, row in enumerate(respuestas[1:], start=2):
        marca = _fecha_serial(celda(row, "marca"))
        email = (_texto(celda(row, "email")) or "").lower()
        if marca is None or not email:
            if any(c not in (None, "") for c in row):
                descartadas += 1
            continue
        loc = _texto(celda(row, "localidad"))
        out.append(Respuesta(
            fila=n, marca=marca, email_hash=hashlib.sha256(email.encode()).hexdigest(),
            apellido=_texto(celda(row, "apellido")), nombre=_texto(celda(row, "nombre")),
            cargo=_texto(celda(row, "cargo")), localidad=loc,
            departamento=deptos.get(normalize_name(loc)) if loc else None,
        ))
    return out, deptos, descartadas


# --- vínculo con el padrón -----------------------------------------------------------------

async def resolver(db: AsyncSession, respuestas: list[Respuesta]) -> None:
    padron = (await db.execute(select(GeoLocalidad).where(GeoLocalidad.activo.is_(True)))).scalars().all()
    activos = {g.id_geo for g in padron}
    idx: dict[tuple[str, str], set[str]] = {}
    for g in padron:
        for k in candidatos_localidad(g.localidad):
            idx.setdefault((_dep(g.departamento), k), set()).add(g.id_geo)
    cache: dict[str, tuple[str | None, str]] = {}
    for r in respuestas:
        if not r.localidad:
            continue
        clave = normalize_name(r.localidad)
        if clave not in cache:
            manual = VINCULACION_MANUAL.get(clave)
            if manual and manual in activos:
                cache[clave] = (manual, "manual")
            elif r.departamento is None:
                cache[clave] = (None, "sin_match")  # opción fuera de la Lista, p. ej. "OTRA LOCALIDAD"
            else:
                hits: set[str] = set()
                for k in candidatos_localidad(r.localidad):
                    hits |= idx.get((_dep(r.departamento), k), set())
                cache[clave] = (next(iter(hits)), "exacto") if len(hits) == 1 else (None, "ambiguo" if hits else "sin_match")
        r.id_geo, r.match_tipo = cache[clave]


# --- agregado por localidad ----------------------------------------------------------------

@dataclass
class Agregado:
    lider: int = 0
    equipo: int = 0
    otros: int = 0
    nombres: list[str] = field(default_factory=list)
    ultima: datetime | None = None

    @property
    def total(self) -> int:
        return self.lider + self.equipo + self.otros


def deduplicar(respuestas: list[Respuesta]) -> list[Respuesta]:
    """Una persona por correo: su última respuesta (§3)."""
    ultima: dict[str, Respuesta] = {}
    for r in respuestas:
        if r.email_hash not in ultima or r.marca >= ultima[r.email_hash].marca:
            ultima[r.email_hash] = r
    return list(ultima.values())


def agregar(personas: list[Respuesta]) -> dict[str, Agregado]:
    out: dict[str, Agregado] = {}
    for r in sorted(personas, key=lambda x: ((x.apellido or "").lower(), (x.nombre or "").lower())):
        if not r.id_geo:
            continue
        a = out.setdefault(r.id_geo, Agregado())
        cargo = normalize_name(r.cargo)
        if cargo in CARGOS_LIDER:
            a.lider += 1
        elif cargo == CARGO_EQUIPO:
            a.equipo += 1
        else:
            a.otros += 1
        nombre = ", ".join(p for p in ((r.apellido or "").upper(), r.nombre or "") if p)
        a.nombres.append(f"{nombre} ({r.cargo})" if r.cargo else nombre)
        a.ultima = max(a.ultima, r.marca) if a.ultima else r.marca
    return out


def valores_deseados(a: Agregado | None) -> dict[str, Any]:
    if a is None or a.total == 0:
        return {k: None for k in CLAVES_AUTO}
    return {
        "insc_total": a.total,
        "insc_lider": a.lider > 0,
        "insc_equipo": a.equipo,
        "insc_otros": a.otros,
        "insc_nombres": "; ".join(a.nombres),
        "insc_ultima": a.ultima.date().isoformat() if a.ultima else None,
    }


def estado_deseado(a: Agregado | None) -> str | None:
    """"Solo intendente / jefe comunal" si se inscribió únicamente el líder; "Con inscriptos" si hay
    cualquier otra inscripción (legisladores y ministros cuentan, decisión del usuario 2026-11-24)."""
    if a is None or a.total == 0:
        return None
    if a.lider > 0 and a.equipo == 0 and a.otros == 0:
        return ESTADO_SOLO_LIDER["nombre"]
    return ESTADO_CON["nombre"]


# --- programa de Planificación ---------------------------------------------------------------

async def _asegurar_programa(db: AsyncSession, *, crear: bool) -> tuple[PlanPrograma | None, dict[str, int]]:
    """Programa, columnas automáticas y estados automáticos; los crea si faltan (idempotente).
    Devuelve (programa, {nombre de estado automático: id})."""
    progs = (await db.execute(select(PlanPrograma).where(PlanPrograma.deleted_at.is_(None)))).scalars().all()
    prog = next((p for p in progs if planif._norm_txt(p.nombre) == planif._norm_txt(PROGRAMA_NOMBRE)), None)
    if prog is None:
        if not crear:
            return None, {}
        out = await planif.crear_programa(db, ACTOR, {
            "nombre": PROGRAMA_NOMBRE, "area": "privada", "fuente": None,
            "descripcion": PROGRAMA_DESCRIPCION, "orden": 0, "activo": True,
        })
        prog = await db.get(PlanPrograma, out["id"])
        # Las columnas por defecto (anuncio, montos, observación) no aplican: se ocultan sin borrarlas.
        for col in (await db.execute(select(PlanColumna).where(PlanColumna.programa_id == prog.id))).scalars():
            col.visible = False
    cols = {c.clave: c for c in (await db.execute(select(PlanColumna).where(PlanColumna.programa_id == prog.id))).scalars()}
    max_orden = max((c.orden for c in cols.values()), default=0)
    for i, c in enumerate(COLUMNAS_AUTO):
        if c["clave"] in cols:
            if cols[c["clave"]].deleted_at is not None:
                cols[c["clave"]].deleted_at = None  # el sync es dueño de sus columnas
            continue
        if not crear:
            continue
        obj = PlanColumna(programa_id=prog.id, orden=max_orden + i + 1, visible=True, **c)
        planif._sello(obj, ACTOR, nuevo=True)
        db.add(obj)
        await db.flush()
        await audit.log_audit(db, actor=ACTOR, action="CREATE", resource_type="privada_plan_columna",
                              resource_id=str(obj.id), payload={"programa_id": prog.id, **c})
    estados = {
        planif._norm_txt(e.nombre): e
        for e in (await db.execute(
            select(PlanEstado).where(PlanEstado.programa_id == prog.id, PlanEstado.deleted_at.is_(None))
        )).scalars()
    }
    ids: dict[str, int] = {}
    for i, est in enumerate((ESTADO_CON, ESTADO_SOLO_LIDER)):
        e = estados.get(planif._norm_txt(est["nombre"]))
        if e is None and crear:
            e = PlanEstado(programa_id=prog.id, orden=10 + i, **est)
            planif._sello(e, ACTOR, nuevo=True)
            db.add(e)
            await db.flush()
            await audit.log_audit(db, actor=ACTOR, action="CREATE", resource_type="privada_plan_estado",
                                  resource_id=str(e.id), payload={"programa_id": prog.id, **est})
        if e is not None:
            ids[est["nombre"]] = e.id
    await db.flush()
    return prog, ids


# --- espejo -------------------------------------------------------------------------------

async def _espejar(db: AsyncSession, respuestas: list[Respuesta]) -> int:
    ahora = now_utc()
    existentes = {
        (_naive_utc(f.marca_temporal), f.email_hash): f
        for f in (await db.execute(
            select(CapacitacionInscripcion).where(CapacitacionInscripcion.capacitacion == CAPACITACION)
        )).scalars()
    }
    vistos, fallidas = set(), 0
    for r in respuestas:
        clave = (_naive_utc(r.marca), r.email_hash)
        if clave in vistos:
            continue
        vistos.add(clave)
        datos = dict(
            fila_origen=r.fila, apellido=(r.apellido or "")[:120] or None, nombre=(r.nombre or "")[:120] or None,
            cargo=(r.cargo or "")[:60] or None, localidad_texto=(r.localidad or "")[:200] or None,
            departamento_texto=(r.departamento or "")[:120] or None, id_geo=r.id_geo, match_tipo=r.match_tipo,
            synced_at=ahora, deleted_at=None,
        )
        try:
            async with db.begin_nested():
                f = existentes.get(clave)
                if f is None:
                    db.add(CapacitacionInscripcion(
                        capacitacion=CAPACITACION, marca_temporal=r.marca, email_hash=r.email_hash, **datos
                    ))
                else:
                    for k, v in datos.items():
                        setattr(f, k, v)
                await db.flush()
        except Exception:  # noqa: BLE001 — una fila mala no corta el resto (patrón checklist_sync)
            fallidas += 1
            logger.exception("capacitacion: no se pudo guardar la fila %s", r.fila)
    for clave, f in existentes.items():
        if clave not in vistos and f.deleted_at is None:
            f.deleted_at = ahora  # la respuesta ya no está en la planilla
    await db.flush()
    return fallidas


# --- sync ---------------------------------------------------------------------------------

async def sincronizar(db: AsyncSession, *, dry_run: bool = False) -> dict:
    if not settings.capacitacion_sheet_id:
        return {"deshabilitado": True}
    datos = await google_sheets.leer_rangos(
        settings.capacitacion_sheet_id, [settings.capacitacion_rango_respuestas, settings.capacitacion_rango_lista]
    )
    respuestas, _deptos, descartadas = parsear(
        datos[settings.capacitacion_rango_respuestas], datos[settings.capacitacion_rango_lista]
    )
    await resolver(db, respuestas)
    personas = deduplicar(respuestas)
    agregados = agregar(personas)

    sin_resolver: dict[str, int] = {}
    for r in personas:
        if not r.id_geo:
            sin_resolver[r.localidad or "(vacía)"] = sin_resolver.get(r.localidad or "(vacía)", 0) + 1

    fallidas = 0 if dry_run else await _espejar(db, respuestas)
    prog, estados_auto = await _asegurar_programa(db, crear=not dry_run)
    ids_auto = set(estados_auto.values())

    filas = {}
    if prog is not None:
        filas = {
            pl.id_geo: pl
            for pl in (await db.execute(
                select(PlanLocalidad).where(PlanLocalidad.programa_id == prog.id, PlanLocalidad.deleted_at.is_(None))
            )).scalars()
        }
    cambiadas = 0
    for id_geo in sorted(set(agregados) | set(filas)):
        a = agregados.get(id_geo)
        pl = filas.get(id_geo)
        actuales = (pl.valores or {}) if pl else {}
        valores = {k: v for k, v in valores_deseados(a).items() if actuales.get(k) != v}
        data: dict[str, Any] = {}
        if valores:
            data["valores"] = valores
        estado_actual = pl.estado_id if pl else None
        if estado_actual is None or estado_actual in ids_auto:  # nunca pisa un estado manual
            nombre = estado_deseado(a)
            objetivo = estados_auto.get(nombre) if nombre else None
            if objetivo != estado_actual and (nombre is None or objetivo is not None):
                data["estado_id"] = objetivo
        if not data:
            continue
        cambiadas += 1
        if dry_run:
            continue
        data["updated_at"] = pl.updated_at if pl else None
        await planif.actualizar_localidad(db, ACTOR, prog.id, id_geo, data)

    resumen = {
        "deshabilitado": False,
        "dry_run": dry_run,
        "programa_id": prog.id if prog else None,
        "respuestas_leidas": len(respuestas),
        "filas_descartadas": descartadas,
        "filas_con_error": fallidas,
        "personas": len(personas),
        "personas_sin_localidad_oficial": sum(sin_resolver.values()),
        "sin_resolver": [{"localidad": k, "personas": v} for k, v in sorted(sin_resolver.items())],
        "localidades_con_inscriptos": sum(1 for a in agregados.values() if a.total),
        "localidades_solo_lider": sum(1 for a in agregados.values() if estado_deseado(a) == ESTADO_SOLO_LIDER["nombre"]),
        "filas_planificacion_cambiadas": cambiadas,
        "sincronizado_en": now_utc().isoformat(),
    }
    logger.info(
        "capacitacion: %d respuestas, %d personas, %d localidades, %d sin resolver, %d filas cambiadas (dry_run=%s)",
        len(respuestas), len(personas), resumen["localidades_con_inscriptos"],
        resumen["personas_sin_localidad_oficial"], cambiadas, dry_run,
    )
    return resumen
