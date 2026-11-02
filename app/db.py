"""SQLite. Los importes se guardan en CÉNTIMOS (enteros) para no arrastrar
errores de coma flotante."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from decimal import Decimal

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "nominas.db")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS empresas (
    id     INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS nominas (
    id              INTEGER PRIMARY KEY,
    empresa_id      INTEGER NOT NULL REFERENCES empresas(id),
    anio            INTEGER NOT NULL,
    mes             INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
    tipo            TEXT    NOT NULL DEFAULT 'Mensual',
    dias            INTEGER,
    total_devengado INTEGER,
    total_deducir   INTEGER,
    liquido         INTEGER,
    base_cc         INTEGER,
    base_irpf       INTEGER,
    irpf_pct        INTEGER,          -- en centésimas de punto: 15,65 % -> 1565
    coste_empresa   INTEGER,
    cuadra          INTEGER NOT NULL DEFAULT 1,
    origen          TEXT    NOT NULL DEFAULT 'manual',  -- 'pdf' | 'manual'
    archivo         TEXT,
    notas           TEXT,
    creado          TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (empresa_id, anio, mes, tipo)
);
CREATE TABLE IF NOT EXISTS lineas (
    id        INTEGER PRIMARY KEY,
    nomina_id INTEGER NOT NULL REFERENCES nominas(id) ON DELETE CASCADE,
    orden     INTEGER NOT NULL,
    categoria TEXT    NOT NULL,
    codigo    TEXT,
    concepto  TEXT    NOT NULL,
    importe   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_nominas_anio ON nominas(anio, mes);
"""


def a_cent(x) -> int | None:
    if x is None or x == "":
        return None
    return int((Decimal(str(x)) * 100).quantize(Decimal("1")))


def de_cent(x) -> Decimal | None:
    return None if x is None else (Decimal(x) / 100).quantize(Decimal("0.01"))


@contextmanager
def conexion():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init():
    with conexion() as con:
        con.executescript(ESQUEMA)
        con.execute("PRAGMA journal_mode = WAL")


def empresas() -> list[sqlite3.Row]:
    with conexion() as con:
        return con.execute("SELECT * FROM empresas ORDER BY nombre").fetchall()


def empresa_id(con, nombre: str) -> int:
    nombre = nombre.strip()
    row = con.execute("SELECT id FROM empresas WHERE nombre = ?", (nombre,)).fetchone()
    if row:
        return row["id"]
    return con.execute("INSERT INTO empresas(nombre) VALUES (?)", (nombre,)).lastrowid


CAMPOS_IMPORTE = ["total_devengado", "total_deducir", "liquido", "base_cc",
                  "base_irpf", "irpf_pct", "coste_empresa"]


def buscar_duplicado(empresa: str, anio: int, mes: int, tipo: str) -> int | None:
    with conexion() as con:
        row = con.execute(
            """SELECT n.id FROM nominas n JOIN empresas e ON e.id = n.empresa_id
               WHERE e.nombre = ? AND n.anio = ? AND n.mes = ? AND n.tipo = ?""",
            (empresa.strip(), anio, mes, tipo)).fetchone()
        return row["id"] if row else None


def guardar(n: dict, nomina_id: int | None = None) -> int:
    """Inserta o (si nomina_id) reemplaza una nómina con sus líneas."""
    with conexion() as con:
        eid = empresa_id(con, n["empresa"])
        valores = {
            "empresa_id": eid, "anio": n["anio"], "mes": n["mes"], "tipo": n["tipo"],
            "dias": n.get("dias"), "cuadra": int(n["cuadra"]), "origen": n["origen"],
            "archivo": n.get("archivo"), "notas": n.get("notas") or None,
            **{c: a_cent(n.get(c)) for c in CAMPOS_IMPORTE},
        }
        cols = list(valores)
        if nomina_id:
            con.execute(f"UPDATE nominas SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
                        [valores[c] for c in cols] + [nomina_id])
            con.execute("DELETE FROM lineas WHERE nomina_id = ?", (nomina_id,))
        else:
            nomina_id = con.execute(
                f"INSERT INTO nominas({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [valores[c] for c in cols]).lastrowid
        con.executemany(
            "INSERT INTO lineas(nomina_id, orden, categoria, codigo, concepto, importe) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(nomina_id, i, l["categoria"], l.get("codigo") or "", l["concepto"], a_cent(l["importe"]))
             for i, l in enumerate(n["lineas"])])
        # Empresas huérfanas (p. ej. tras renombrar)
        con.execute("DELETE FROM empresas WHERE id NOT IN (SELECT empresa_id FROM nominas)")
        return nomina_id


def obtener(nomina_id: int) -> dict | None:
    with conexion() as con:
        row = con.execute(
            "SELECT n.*, e.nombre AS empresa FROM nominas n JOIN empresas e ON e.id = n.empresa_id "
            "WHERE n.id = ?", (nomina_id,)).fetchone()
        if not row:
            return None
        n = dict(row)
        for c in CAMPOS_IMPORTE:
            n[c] = de_cent(n[c])
        n["lineas"] = [
            {**dict(l), "importe": de_cent(l["importe"])}
            for l in con.execute("SELECT * FROM lineas WHERE nomina_id = ? ORDER BY orden", (nomina_id,))
        ]
        return n


def borrar(nomina_id: int) -> str | None:
    with conexion() as con:
        row = con.execute("SELECT archivo FROM nominas WHERE id = ?", (nomina_id,)).fetchone()
        con.execute("DELETE FROM nominas WHERE id = ?", (nomina_id,))
        con.execute("DELETE FROM empresas WHERE id NOT IN (SELECT empresa_id FROM nominas)")
        return row["archivo"] if row else None


def anios() -> list[int]:
    with conexion() as con:
        return [r[0] for r in con.execute("SELECT DISTINCT anio FROM nominas ORDER BY anio DESC")]


def resumen(anio: int) -> list[dict]:
    """Una fila por nómina del año con el desglose por categorías (en euros)."""
    with conexion() as con:
        filas = con.execute(
            """SELECT n.id, n.anio, n.mes, n.tipo, n.cuadra, n.origen, n.irpf_pct,
                      n.total_devengado, n.liquido, n.base_irpf, n.coste_empresa,
                      e.nombre AS empresa,
                      COALESCE(SUM(CASE WHEN l.categoria='salarial'    THEN l.importe END),0) AS salarial,
                      COALESCE(SUM(CASE WHEN l.categoria='no_salarial' THEN l.importe END),0) AS no_salarial,
                      COALESCE(SUM(CASE WHEN l.categoria='ss'          THEN l.importe END),0) AS ss,
                      COALESCE(SUM(CASE WHEN l.categoria='irpf'        THEN l.importe END),0) AS irpf,
                      COALESCE(SUM(CASE WHEN l.categoria='otra_ded'    THEN l.importe END),0) AS otra_ded
               FROM nominas n
               JOIN empresas e ON e.id = n.empresa_id
               LEFT JOIN lineas l ON l.nomina_id = n.id
               WHERE n.anio = ?
               GROUP BY n.id
               ORDER BY n.mes, e.nombre, n.tipo""", (anio,)).fetchall()
    out = []
    for f in filas:
        d = dict(f)
        for c in ["total_devengado", "liquido", "base_irpf", "coste_empresa", "irpf_pct",
                  "salarial", "no_salarial", "ss", "irpf", "otra_ded"]:
            d[c] = de_cent(d[c])
        out.append(d)
    return out
