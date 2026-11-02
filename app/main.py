"""Nóminas — app web (Starlette + Jinja2 + SQLite).

Starlette es la base sobre la que está hecho FastAPI; como aquí todo son
páginas HTML renderizadas en servidor, no hace falta la capa de API de FastAPI.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import (FileResponse, PlainTextResponse, RedirectResponse,
                                 Response)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from jinja2 import Undefined

from app import auth, db
from app.calculos import CATEGORIAS, comprobaciones, cuadra, desglose
from app.parser_a3 import ParseError, parse_pdf

log = logging.getLogger("nominas")
BASE = Path(__file__).parent
DATA = Path(db.DATA_DIR)
TMP = DATA / "tmp"
ARCHIVO = DATA / "archivo"
MAX_SUBIDA = 15 * 1024 * 1024

MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
MESES_CORTOS = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago",
                "Sep", "Oct", "Nov", "Dic"]
TIPOS = ["Mensual", "Extra", "Atrasos", "Finiquito", "Otra"]

templates = Jinja2Templates(directory=str(BASE / "templates"))


# --------------------------------------------------------------------------- #
#  Formato
# --------------------------------------------------------------------------- #
def _vacio(x) -> bool:
    return x is None or x == "" or isinstance(x, Undefined)


def eur(x, simbolo=True) -> str:
    if _vacio(x):
        return "—"
    s = f"{Decimal(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €" if simbolo else s


def num(x) -> str:
    """Para valores de inputs: 1180.17 -> '1180,17'."""
    if _vacio(x):
        return ""
    return f"{Decimal(x):.2f}".replace(".", ",")


def pct(x) -> str:
    return "—" if _vacio(x) else f"{Decimal(x):.2f} %".replace(".", ",")


templates.env.filters.update(eur=eur, num=num, pct=pct)
templates.env.globals.update(MESES=MESES, MESES_CORTOS=MESES_CORTOS, TIPOS=TIPOS,
                             CATEGORIAS=CATEGORIAS)


def render(request: Request, nombre: str, status_code=200, **ctx):
    ctx.setdefault("usuario", request.session.get("usuario"))
    return templates.TemplateResponse(request, nombre, ctx, status_code=status_code)


def parse_importe(txt: str | None) -> Decimal | None:
    """Acepta '1.180,17', '1180,17', '1180.17' y '1180'."""
    if txt is None:
        return None
    s = txt.strip().replace("€", "").replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"-?\d{1,3}\.\d{3}", s):
        s = s.replace(".", "")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise ValueError(f"«{txt}» no es un importe válido")


# --------------------------------------------------------------------------- #
#  Autenticación
# --------------------------------------------------------------------------- #
PUBLICAS = ("/login", "/health", "/static/")


class RequiereLogin(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        p = request.url.path
        if not p.startswith(PUBLICAS) and not request.session.get("usuario"):
            return RedirectResponse("/login", status_code=303)
        return await call_next(request)


async def login(request: Request):
    error = None
    if request.method == "POST":
        form = await request.form()
        if auth.comprobar_credenciales(form.get("usuario", ""), form.get("password", "")):
            request.session.clear()
            request.session["usuario"] = form["usuario"]
            return RedirectResponse("/", status_code=303)
        await asyncio.sleep(1.5)  # frena fuerza bruta
        error = "Usuario o contraseña incorrectos."
        log.warning("Login fallido desde %s", request.client.host if request.client else "?")
    if not auth.configurado():
        error = "Falta configurar APP_USER y APP_PASSWORD_HASH en el stack (ver README)."
    return render(request, "login.html", error=error)


async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


async def health(request: Request):
    db.anios()  # comprueba que la base de datos responde
    return PlainTextResponse("ok")


# --------------------------------------------------------------------------- #
#  Panel
# --------------------------------------------------------------------------- #
def _sumar(filas, campo):
    return sum((f[campo] or Decimal(0) for f in filas), Decimal(0))


def _totales(filas):
    t = {c: _sumar(filas, c) for c in
         ["total_devengado", "salarial", "no_salarial", "ss", "irpf", "otra_ded",
          "liquido", "base_irpf", "coste_empresa"]}
    t["tipo_irpf"] = (t["irpf"] / t["base_irpf"] * 100) if t["base_irpf"] else None
    t["n"] = len(filas)
    return t


async def panel(request: Request):
    anios = db.anios()
    try:
        anio = int(request.query_params.get("anio") or (anios[0] if anios else time.localtime().tm_year))
    except ValueError:
        anio = time.localtime().tm_year
    filas_todas = db.resumen(anio)
    empresas = sorted({f["empresa"] for f in filas_todas})
    empresa = request.query_params.get("empresa") or ""
    filas = [f for f in filas_todas if not empresa or f["empresa"] == empresa]

    meses = list(range(1, 13))
    def por_mes(campo, src=filas):
        return [float(sum((f[campo] for f in src if f["mes"] == m), Decimal(0))) for m in meses]

    grafica = {
        "meses": MESES_CORTOS[1:],
        "barras": {
            "Líquido": por_mes("liquido"),
            "IRPF": por_mes("irpf"),
            "Seg. Social": por_mes("ss"),
            "Otras deducciones": por_mes("otra_ded"),
        },
        "irpf_pct": {
            e: [next((float(f["irpf_pct"]) for f in filas_todas
                      if f["empresa"] == e and f["mes"] == m and f["tipo"] == "Mensual"
                      and f["irpf_pct"] is not None), None) for m in meses]
            for e in empresas
        },
    }
    if not any(grafica["barras"]["Otras deducciones"]):
        del grafica["barras"]["Otras deducciones"]

    por_empresa = [{"empresa": e, **_totales([f for f in filas_todas if f["empresa"] == e])}
                   for e in empresas]
    return render(request, "panel.html", anio=anio, anios=anios or [anio], empresas=empresas,
                  empresa=empresa, filas=filas, total=_totales(filas), por_empresa=por_empresa,
                  grafica_json=json.dumps(grafica).replace("<", "\\u003c"), msg=request.query_params.get("msg"))


# --------------------------------------------------------------------------- #
#  Editor (subida, alta manual, edición)
# --------------------------------------------------------------------------- #
def _vacia() -> dict:
    hoy = time.localtime()
    return {"empresa": "", "anio": hoy.tm_year, "mes": hoy.tm_mon, "tipo": "Mensual",
            "dias": 30, "lineas": [], "origen": "manual", "avisos": []}


def _editor(request, n, errores=None, nomina_id=None, tmp_token="", duplicado=None,
            status_code=200):
    return render(request, "editor.html", status_code=status_code, n=n, errores=errores or [],
                  nomina_id=nomina_id, tmp_token=tmp_token, duplicado=duplicado,
                  empresas=[e["nombre"] for e in db.empresas()],
                  checks=comprobaciones(n) if n.get("lineas") else [])


async def nueva(request: Request):
    return _editor(request, _vacia())


async def subir(request: Request):
    if request.method == "GET":
        return render(request, "subir.html")
    form = await request.form()
    f = form.get("archivo")
    if not f or not getattr(f, "filename", ""):
        return render(request, "subir.html", error="Elige un archivo PDF.", status_code=400)
    datos = await f.read()
    if len(datos) > MAX_SUBIDA:
        return render(request, "subir.html", error="El archivo supera 15 MB.", status_code=400)
    if not datos.startswith(b"%PDF"):
        return render(request, "subir.html", status_code=400,
                      error="Solo se admiten PDF por ahora. Para la nómina en papel usa "
                            "«Entrada manual» (el OCR de fotos llegará en la fase 2).")
    TMP.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(12)
    ruta = TMP / f"{token}.pdf"
    ruta.write_bytes(datos)
    try:
        n = parse_pdf(str(ruta))
    except ParseError as e:
        ruta.unlink(missing_ok=True)
        return render(request, "subir.html", error=str(e), status_code=422)
    n["origen"] = "pdf"
    dup = db.buscar_duplicado(n["empresa"], n["anio"], n["mes"], n["tipo"]) if n["anio"] else None
    return _editor(request, n, tmp_token=token, duplicado=dup)


def _form_a_nomina(form) -> tuple[dict, list[str]]:
    errores = []
    n = {"empresa": (form.get("empresa") or "").strip(),
         "tipo": form.get("tipo") or "Mensual",
         "notas": (form.get("notas") or "").strip(),
         "origen": form.get("origen") or "manual",
         "lineas": [], "avisos": []}
    if not n["empresa"]:
        errores.append("Falta la empresa.")
    for campo, lo, hi in [("anio", 2000, 2100), ("mes", 1, 12), ("dias", 0, 31)]:
        try:
            v = int(form.get(campo) or 0) if form.get(campo) else None
            if v is not None and not lo <= v <= hi:
                raise ValueError
            n[campo] = v
        except ValueError:
            errores.append(f"Valor no válido en {campo}.")
            n[campo] = None
    if not n.get("anio") or not n.get("mes"):
        errores.append("Faltan año y mes.")
    for c in db.CAMPOS_IMPORTE:
        try:
            n[c] = parse_importe(form.get(c))
        except ValueError as e:
            errores.append(f"{c.replace('_', ' ')}: {e}")
            n[c] = None
    cats, cods = form.getlist("l_cat"), form.getlist("l_cod")
    conceptos, importes = form.getlist("l_concepto"), form.getlist("l_importe")
    for cat, cod, con, imp in zip(cats, cods, conceptos, importes):
        if not con.strip() and not imp.strip():
            continue  # fila vacía
        try:
            v = parse_importe(imp)
        except ValueError as e:
            errores.append(f"Línea «{con}»: {e}")
            v = None
        if cat not in CATEGORIAS:
            errores.append(f"Categoría desconocida en «{con}».")
        n["lineas"].append({"categoria": cat, "codigo": cod.strip(),
                            "concepto": con.strip() or "(sin concepto)", "importe": v})
    if not n["lineas"]:
        errores.append("Añade al menos una línea (devengo o deducción).")
    if any(l["importe"] is None for l in n["lineas"]):
        errores.append("Hay líneas sin importe.")
    return n, errores


async def guardar(request: Request):
    form = await request.form()
    n, errores = _form_a_nomina(form)
    nomina_id = int(form["nomina_id"]) if (form.get("nomina_id") or "").isdigit() else None
    token = form.get("tmp_token") or ""
    if token and not re.fullmatch(r"[0-9a-f]{24}", token):
        token = ""

    if not errores:
        n["cuadra"] = cuadra(n)
        if not n["cuadra"] and not form.get("forzar"):
            errores.append("Las cuentas no cuadran (ver comprobaciones). Corrige los importes "
                           "o marca «Guardar aunque no cuadre».")
    dup = None
    if not errores:
        dup = db.buscar_duplicado(n["empresa"], n["anio"], n["mes"], n["tipo"])
        if dup and dup != nomina_id:
            if form.get("sobrescribir"):
                nomina_id = dup
            else:
                errores.append(f"Ya hay una nómina de {n['empresa']} para "
                               f"{MESES[n['mes']]} {n['anio']} ({n['tipo']}). "
                               "Marca «Sobrescribir» para reemplazarla.")
    if errores:
        return _editor(request, n, errores, nomina_id, token, dup, status_code=422)

    # Archivo original
    anterior = db.obtener(nomina_id)["archivo"] if nomina_id else None
    n["archivo"] = anterior
    if token and (TMP / f"{token}.pdf").exists():
        destino_dir = ARCHIVO / str(n["anio"])
        destino_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", n["empresa"].lower()).strip("-")[:40]
        nombre = f"{n['anio']}-{n['mes']:02d}_{slug}_{n['tipo'].lower()}_{token[:6]}.pdf"
        shutil.move(TMP / f"{token}.pdf", destino_dir / nombre)
        n["archivo"] = f"{n['anio']}/{nombre}"
        if anterior and anterior != n["archivo"]:
            (ARCHIVO / anterior).unlink(missing_ok=True)
    try:
        nid = db.guardar(n, nomina_id)
    except sqlite3.IntegrityError:
        return _editor(request, n, ["Ya existe otra nómina con esa empresa, mes, año y tipo."],
                       nomina_id, token, status_code=422)
    return RedirectResponse(f"/nomina/{nid}?msg=guardada", status_code=303)


async def detalle(request: Request):
    n = db.obtener(request.path_params["id"])
    if not n:
        return PlainTextResponse("No existe", status_code=404)
    return render(request, "detalle.html", n=n, d=desglose(n["lineas"]),
                  checks=comprobaciones(n), msg=request.query_params.get("msg"))


async def editar(request: Request):
    n = db.obtener(request.path_params["id"])
    if not n:
        return PlainTextResponse("No existe", status_code=404)
    return _editor(request, n, nomina_id=n["id"])


async def borrar(request: Request):
    archivo = db.borrar(request.path_params["id"])
    if archivo:
        (ARCHIVO / archivo).unlink(missing_ok=True)
    return RedirectResponse("/?msg=borrada", status_code=303)


async def original(request: Request):
    n = db.obtener(request.path_params["id"])
    if not n or not n["archivo"]:
        return PlainTextResponse("Sin archivo", status_code=404)
    ruta = (ARCHIVO / n["archivo"]).resolve()
    if ARCHIVO.resolve() not in ruta.parents or not ruta.exists():
        return PlainTextResponse("Sin archivo", status_code=404)
    return FileResponse(ruta, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{ruta.name}"'})


async def exportar_csv(request: Request):
    try:
        anio = int(request.query_params.get("anio", ""))
    except ValueError:
        return PlainTextResponse("Indica ?anio=", status_code=400)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Año", "Mes", "Empresa", "Tipo", "Devengos salariales", "Otros cobros (no salariales)",
                "Total devengado", "Seg. Social", "IRPF", "% IRPF", "Otras deducciones",
                "Líquido", "Base IRPF", "Coste empresa", "Cuadra"])
    for f in db.resumen(anio):
        w.writerow([f["anio"], f["mes"], f["empresa"], f["tipo"], num(f["salarial"]),
                    num(f["no_salarial"]), num(f["total_devengado"]), num(f["ss"]), num(f["irpf"]),
                    num(f["irpf_pct"]), num(f["otra_ded"]), num(f["liquido"]), num(f["base_irpf"]),
                    num(f["coste_empresa"]), "sí" if f["cuadra"] else "no"])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="nominas_{anio}.csv"'})


# --------------------------------------------------------------------------- #
#  Arranque
# --------------------------------------------------------------------------- #
def _limpiar_tmp():
    if TMP.exists():
        limite = time.time() - 86400
        for p in TMP.glob("*.pdf"):
            if p.stat().st_mtime < limite:
                p.unlink(missing_ok=True)


def _secret_key() -> str:
    """SECRET_KEY del entorno o, si no hay, una persistida en /data."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    f = DATA / ".secret_key"
    DATA.mkdir(parents=True, exist_ok=True)
    if not f.exists():
        f.write_text(secrets.token_urlsafe(48))
        f.chmod(0o600)
    return f.read_text().strip()


db.init()
_limpiar_tmp()
if not auth.configurado():
    log.warning("APP_USER / APP_PASSWORD_HASH sin configurar: nadie podrá iniciar sesión.")

app = Starlette(
    routes=[
        Route("/", panel),
        Route("/login", login, methods=["GET", "POST"]),
        Route("/logout", logout, methods=["POST"]),
        Route("/health", health),
        Route("/subir", subir, methods=["GET", "POST"]),
        Route("/nueva", nueva),
        Route("/guardar", guardar, methods=["POST"]),
        Route("/nomina/{id:int}", detalle),
        Route("/nomina/{id:int}/editar", editar),
        Route("/nomina/{id:int}/borrar", borrar, methods=["POST"]),
        Route("/nomina/{id:int}/pdf", original),
        Route("/export.csv", exportar_csv),
        Mount("/static", StaticFiles(directory=str(BASE / "static")), name="static"),
    ],
    middleware=[
        Middleware(SessionMiddleware, secret_key=_secret_key(), session_cookie="nominas_sesion",
                   max_age=30 * 24 * 3600, same_site="lax", https_only=False),
        Middleware(RequiereLogin),
    ],
)
