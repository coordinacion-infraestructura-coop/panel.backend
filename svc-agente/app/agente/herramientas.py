"""Tools del agente (spec §6.2): definiciones para la API y ejecución."""
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agente import indicadores as ind
from app.agente.sql_guard import SqlRechazado, validar
from app.config import settings

PROGRAMAS = ["cc", "ch", "ml", "gas_obra", "gas_accion", "atp"]


def _nullable(tipo: str | dict, descripcion: str) -> dict:
    base = {"type": tipo} if isinstance(tipo, str) else dict(tipo)
    if "enum" in base:
        return {"anyOf": [base, {"type": "null"}], "description": descripcion}
    return {"type": [base["type"], "null"], "description": descripcion}


def _tool(nombre: str, descripcion: str, props: dict) -> dict:
    return {
        "name": nombre, "description": descripcion, "strict": True,
        "input_schema": {"type": "object", "properties": props, "required": list(props),
                         "additionalProperties": False},
    }


_TERR = {
    "departamento": _nullable("string", "Nombre oficial del departamento (de resolver_territorio). null si es una localidad o toda la provincia."),
    "id_geo": _nullable("string", "id_geo de la localidad (de resolver_territorio). null si es un departamento o toda la provincia."),
}
_PROG = _nullable({"type": "string", "enum": PROGRAMAS}, "Programa; null = todos.")

TOOLS: list[dict] = [
    _tool("resolver_territorio",
          "Convierte el nombre de una localidad o departamento escrito por el usuario en su forma oficial "
          "(id_geo / departamento). Llamarla antes de cualquier tool que reciba territorio.",
          {"texto": {"type": "string", "description": "Lo que escribió el usuario, ej. 'Villa Maria', 'depto San Justo', 'toda la provincia'."}}),
    _tool("estado_programa_territorio",
          "Estado de uno o todos los programas en una localidad, un departamento o la provincia: cantidad por "
          "estado normalizado y de origen, monto total, % finalizado, últimos movimientos y fecha del dato.",
          {"programa": _PROG, **_TERR}),
    _tool("ficha_territorio",
          "Ficha completa de una localidad o un departamento: contexto (población, intendente, partido), "
          "programas con su estado, gestiones de Privada, transferencias del último año y ATP.",
          dict(_TERR)),
    _tool("montos",
          "Comprometido vs. ejecutado por programa en un territorio, con ratio y dólares aparte; incluye "
          "transferencias a municipios. Período opcional (fechas ISO).",
          {"programa": _nullable({"type": "string", "enum": PROGRAMAS + ["transferencias"]}, "Programa; null = todos."),
           **_TERR,
           "desde": _nullable("string", "Fecha ISO AAAA-MM-DD o null."),
           "hasta": _nullable("string", "Fecha ISO AAAA-MM-DD o null.")}),
    _tool("pendientes",
          "Demoras y pendientes: gestiones de Privada abiertas (antigüedad, ranking por área y ministerio), "
          "convenios u obras sin movimiento, o hitos de obra sin acreditar.",
          {"tipo": {"type": "string", "enum": ["gestiones", "programas", "hitos"]},
           "umbral_dias": _nullable("integer", "Umbral de demora en días; null = el del glosario."),
           **_TERR, "programa": _PROG}),
    _tool("consulta_sql",
          "Ejecuta UNA consulta SELECT de PostgreSQL sobre las tablas ag_* descriptas en el sistema. Sólo "
          "para preguntas que no cubren las otras tools. Máximo "
          f"{settings.sql_limite_filas} filas.",
          {"sql": {"type": "string"}, "motivo": {"type": "string", "description": "Qué pregunta responde la consulta, en una frase."}}),
    _tool("responder",
          "Respuesta final al usuario. Llamarla una vez, al final.",
          {"texto": {"type": "string", "description": "Respuesta en markdown."},
           "interpretacion": {"type": "string", "description": "Cómo se interpretó la pregunta (territorio, programas, período)."},
           "sugerencias": {"type": "array", "items": {"type": "string"}, "description": "2 o 3 preguntas de seguimiento."},
           "bloques": {"type": "array", "items": {"type": "string"}, "description": "ids de bloques a mostrar (ej. ['b1','b3'])."}}),
]


def _json_default(v: Any) -> Any:
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return str(v)


def a_json(v: Any, ascii: bool = False) -> str:
    """`ascii=True` para el SSE: escapa U+2028/U+2029 (vienen en textos pegados desde Word/Sheets),
    que el navegador toma como fin de línea y cortaban el evento `respuesta` a la mitad."""
    return json.dumps(v, ensure_ascii=ascii, default=_json_default)


@dataclass
class Turno:
    """Estado de una pregunta: bloques generados, SQL ejecutado y traza de tools (para auditoría)."""
    bloques: dict[str, dict] = field(default_factory=dict)
    sql: list[str] = field(default_factory=list)
    traza: list[dict] = field(default_factory=list)
    filas_devueltas: int = 0

    def registrar_bloques(self, bloques: list[dict]) -> list[dict]:
        refs = []
        for b in bloques:
            bid = f"b{len(self.bloques) + 1}"
            self.bloques[bid] = {**b, "id": bid}
            refs.append({"id": bid, "tipo": b["tipo"], "titulo": b.get("titulo") or b.get("texto")})
        return refs


async def ejecutar_sql(db_llm: AsyncSession, sql: str, turno: Turno) -> dict:
    dialecto = db_llm.bind.dialect.name
    try:
        v = validar(sql, limite=settings.sql_limite_filas, dialecto_salida=dialecto)
    except SqlRechazado as e:
        return {"error": f"Consulta rechazada: {e}"}
    turno.sql.append(v.sql)
    try:
        if dialecto == "postgresql":
            await db_llm.execute(text("SET TRANSACTION READ ONLY"))
            await db_llm.execute(text(f"SET LOCAL statement_timeout = {int(settings.sql_timeout_ms)}"))
        res = await db_llm.execute(text(v.sql))
        columnas = list(res.keys())
        filas = [list(r) for r in res.fetchall()]
    except Exception as e:  # error de SQL: se devuelve al modelo para que corrija
        msg = str(getattr(e, "orig", e)).splitlines()[0][:300]
        return {"error": f"Error al ejecutar la consulta: {msg}"}
    finally:
        await db_llm.rollback()
    turno.filas_devueltas += len(filas)
    filas_json = json.loads(a_json(filas))
    refs = turno.registrar_bloques([{
        "tipo": "tabla", "titulo": None, "columnas": columnas, "filas": filas_json,
        "total_filas": len(filas),
    }]) if filas else []
    return {
        "columnas": columnas, "filas": filas_json[:50], "total_filas": len(filas),
        "recortado_al_limite": len(filas) >= v.limite_aplicado,
        "nota": "Se muestran hasta 50 filas acá; el bloque tiene todas." if len(filas) > 50 else None,
        "bloques": refs,
    }


async def ejecutar(nombre: str, args: dict, db: AsyncSession, db_llm: AsyncSession, turno: Turno) -> dict:
    """Ejecuta una tool y devuelve el dict que se le pasa al modelo como tool_result."""
    if nombre == "resolver_territorio":
        return await ind.resolver_territorio(db, args["texto"])
    if nombre == "consulta_sql":
        return await ejecutar_sql(db_llm, args["sql"], turno)
    terr = {"departamento": args.get("departamento"), "id_geo": args.get("id_geo")}
    if nombre == "estado_programa_territorio":
        res = await ind.estado_programa_territorio(db, args.get("programa"), **terr)
    elif nombre == "ficha_territorio":
        res = await ind.ficha_territorio(db, **terr)
    elif nombre == "montos":
        res = await ind.montos(db, args.get("programa"), **terr, desde=args.get("desde"), hasta=args.get("hasta"))
    elif nombre == "pendientes":
        res = await ind.pendientes(db, args["tipo"], args.get("umbral_dias"), **terr, programa=args.get("programa"))
    else:
        return {"error": f"Tool desconocida: {nombre}"}
    if "bloques" in res:
        res = {**res, "bloques": turno.registrar_bloques(res["bloques"])}
    return res
