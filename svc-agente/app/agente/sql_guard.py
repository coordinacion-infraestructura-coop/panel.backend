"""Validación del SQL que escribe el modelo (spec §6.2, tool `consulta_sql`).

Es UNA capa. La garantía real es el rol `agente_llm` (SELECT sólo sobre `ag.*`, transacción READ
ONLY, statement_timeout): aunque este validador tuviera un hueco, la base no deja escribir ni leer
otras tablas.
"""
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.semantica.models import NOMBRES_TABLAS_AG

# Funciones que no tienen sentido en una consulta analítica y abren puertas a la instancia.
_FUNCIONES_PROHIBIDAS_PREFIJOS = ("pg_", "lo_", "dblink", "current_setting", "set_config", "txid_")
_FUNCIONES_PROHIBIDAS = {
    "version", "inet_server_addr", "inet_client_addr", "query_to_xml", "table_to_xml",
    "database_to_xml", "cursor_to_xml", "copy", "sleep", "generate_series",
}
_NODOS_PROHIBIDOS = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
    exp.Command, exp.Into, exp.Grant, exp.Set, exp.Transaction, exp.Commit, exp.Rollback,
    exp.Lock, exp.TruncateTable, exp.Copy,
)


class SqlRechazado(ValueError):
    pass


@dataclass
class SqlValidado:
    sql: str
    limite_aplicado: int


def _nombre_funcion(f: exp.Expression) -> str:
    if isinstance(f, exp.Anonymous):
        return str(f.name).lower()
    return (f.sql_name() or "").lower()


def validar(sql: str, *, limite: int, dialecto_salida: str = "postgres") -> SqlValidado:
    if not sql or not sql.strip():
        raise SqlRechazado("La consulta está vacía.")
    try:
        sentencias = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except ParseError as e:
        raise SqlRechazado(f"No se pudo interpretar el SQL: {str(e).splitlines()[0]}") from e
    if len(sentencias) != 1:
        raise SqlRechazado("Se permite una sola sentencia SELECT.")
    arbol = sentencias[0]

    if not isinstance(arbol, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise SqlRechazado("Sólo se permiten consultas SELECT.")

    for nodo in arbol.walk():
        if isinstance(nodo, _NODOS_PROHIBIDOS):
            raise SqlRechazado(f"Operación no permitida: {type(nodo).__name__}.")
        if isinstance(nodo, exp.Func):
            nombre = _nombre_funcion(nodo)
            if nombre in _FUNCIONES_PROHIBIDAS or nombre.startswith(_FUNCIONES_PROHIBIDAS_PREFIJOS):
                raise SqlRechazado(f"Función no permitida: {nombre}.")

    ctes = {c.alias_or_name.lower() for c in arbol.find_all(exp.CTE)}
    for tabla in arbol.find_all(exp.Table):
        nombre = (tabla.name or "").lower()
        esquema = (tabla.db or "").lower()
        if tabla.catalog:
            raise SqlRechazado("No se permite referenciar otra base.")
        if not nombre:
            raise SqlRechazado("Origen de datos no permitido (sólo tablas ag_*).")
        if nombre in ctes and not esquema:
            continue
        if esquema not in ("", "ag") or nombre not in NOMBRES_TABLAS_AG:
            raise SqlRechazado(
                f"Tabla no permitida: {tabla.sql()}. Sólo se pueden consultar: "
                + ", ".join(sorted(NOMBRES_TABLAS_AG))
            )
        # Siempre calificada: el rol agente_llm tiene search_path=ag, pero no dependemos de eso.
        tabla.set("db", exp.to_identifier("ag"))

    # LIMIT forzado o recortado en la sentencia de nivel superior.
    limite_actual = arbol.args.get("limit")
    aplicado = limite
    if limite_actual is not None:
        try:
            pedido = int(limite_actual.expression.name)
            aplicado = min(pedido, limite)
        except (AttributeError, ValueError, TypeError):
            aplicado = limite
    arbol = arbol.limit(aplicado, copy=False) if hasattr(arbol, "limit") else arbol

    dialecto = "postgres" if dialecto_salida == "postgresql" else dialecto_salida
    return SqlValidado(sql=arbol.sql(dialect=dialecto), limite_aplicado=aplicado)
