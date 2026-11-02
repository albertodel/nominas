"""Parser de nóminas generadas por A3 (A3Nom / A3innuva).

Trabaja sobre la salida de `pdftotext -layout`, que conserva las columnas del
PDF. Se apoya en la POSICIÓN de los encabezados (DEVENGOS / DEDUCCIONES, y la
fila REM. TOTAL ... T. A DEDUCIR) para saber a qué columna pertenece cada
importe, así funciona aunque haya columnas vacías.

No extrae datos personales (nombre, DNI, NSS, IBAN): solo importes y periodo.
"""
from __future__ import annotations

import re
import subprocess
from decimal import Decimal, InvalidOperation

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

IMPORTE_RE = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}")


class ParseError(Exception):
    pass


def a_decimal(txt: str) -> Decimal:
    """'1.180,17' -> Decimal('1180.17')"""
    try:
        return Decimal(txt.strip().replace(".", "").replace(",", "."))
    except InvalidOperation as e:
        raise ParseError(f"Importe ilegible: {txt!r}") from e


def pdf_a_texto(ruta_pdf: str) -> str:
    res = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", ruta_pdf, "-"],
        capture_output=True, text=True, timeout=60,
    )
    if res.returncode != 0:
        raise ParseError(f"No se pudo leer el PDF: {res.stderr.strip()[:200]}")
    return res.stdout


# --------------------------------------------------------------------------- #
#  Clasificación de líneas
# --------------------------------------------------------------------------- #
def categoria_deduccion(concepto: str) -> str:
    c = concepto.lower()
    if "irpf" in c or "retenci" in c or "tributaci" in c:
        return "irpf"
    if c.startswith("cotizaci") or "seg. social" in c or "s.s." in c:
        return "ss"
    return "otra_ded"


def categoria_devengo(marca: str | None) -> str:
    if marca == "**":
        return "informativo"
    if marca == "-":
        return "no_salarial"
    return "salarial"  # '*' o sin marca


LINEA_RE = re.compile(
    r"""^\s*
    (?:(?P<cuantia>-?[\d.]+,\d+)\s+(?P<precio>-?[\d.]+,\d+)\s+)?   # cuantía y precio (opcionales)
    (?:(?P<codigo>\d{1,4})\s+)?                                    # código de concepto
    (?P<marca>\*\*|\*|-)?                                         # *, - o **
    (?P<concepto>\S.*?)                                            # texto del concepto
    \s{2,}(?P<resto>.*)$""",
    re.VERBOSE,
)


def _fin_columna(cabecera: str, palabra: str) -> int:
    i = cabecera.find(palabra)
    if i < 0:
        raise ParseError(f"No encuentro la columna {palabra}")
    return i + len(palabra)


def _parse_lineas(lineas: list[str]) -> list[dict]:
    try:
        i_cab = next(i for i, l in enumerate(lineas) if "DEVENGOS" in l and "DEDUCCIONES" in l)
    except StopIteration:
        raise ParseError("No encuentro la tabla de conceptos (cabecera DEVENGOS / DEDUCCIONES). "
                         "¿Es una nómina de A3?")
    cab = lineas[i_cab]
    fin_dev = _fin_columna(cab, "DEVENGOS")
    fin_ded = _fin_columna(cab, "DEDUCCIONES")
    limite = (fin_dev + fin_ded) / 2  # a la izquierda = devengo, a la derecha = deducción

    salida = []
    for l in lineas[i_cab + 1:]:
        if "REM. TOTAL" in l or "T. DEVENGADO" in l:
            break
        if not l.strip():
            continue
        m = LINEA_RE.match(l)
        if not m:
            continue
        concepto = m.group("concepto").strip()
        # Importes al final de la línea (puede haber uno o, raro, dos columnas)
        for imp in IMPORTE_RE.finditer(l, m.start("resto")):
            fin = imp.end()
            es_ded = fin > limite
            if es_ded:
                cat = categoria_deduccion(concepto)
            else:
                cat = categoria_devengo(m.group("marca"))
            salida.append({
                "categoria": cat,
                "codigo": m.group("codigo") or "",
                "concepto": concepto,
                "importe": a_decimal(imp.group()),
            })
    if not salida:
        raise ParseError("La tabla de conceptos está vacía o no la entiendo.")
    return salida


TOTALES_CAMPOS = [
    ("REM. TOTAL", "rem_total"),
    ("P.P. EXTRAS", "pp_extras"),
    ("BASE C.C.", "base_cc"),
    ("BASE A.T. Y DES", "base_at"),
    ("BASE I.R.P.F.", "base_irpf"),
    ("T. DEVENGADO", "total_devengado"),
    ("T. A DEDUCIR", "total_deducir"),
]


def _parse_totales(lineas: list[str]) -> dict:
    """Asigna cada número de la fila de valores al encabezado más cercano en columna."""
    try:
        i_cab = next(i for i, l in enumerate(lineas) if "T. DEVENGADO" in l)
    except StopIteration:
        raise ParseError("No encuentro la fila de totales (T. DEVENGADO).")
    cab = lineas[i_cab]
    centros = []
    for etiqueta, clave in TOTALES_CAMPOS:
        p = cab.find(etiqueta)
        if p >= 0:
            centros.append((p + len(etiqueta) / 2, clave))
    valores = next((l for l in lineas[i_cab + 1:] if l.strip()), "")
    tot = {}
    for imp in IMPORTE_RE.finditer(valores):
        c = (imp.start() + imp.end()) / 2
        clave = min(centros, key=lambda x: abs(x[0] - c))[1]
        tot[clave] = a_decimal(imp.group())
    return tot


def parse_texto(texto: str) -> dict:
    lineas = texto.splitlines()
    avisos: list[str] = []

    # --- Empresa: primera columna de la línea bajo "EMPRESA ... DOMICILIO"
    empresa = ""
    for i, l in enumerate(lineas):
        if "EMPRESA" in l and "DOMICILIO" in l:
            sig = next((x for x in lineas[i + 1:] if x.strip()), "")
            empresa = re.split(r"\s{2,}", sig.strip())[0]
            break
    if not empresa:
        avisos.append("No he encontrado el nombre de la empresa.")

    # --- Periodo: "Mensual - 1 Octubre 2026 a 31 Octubre 2026"
    tipo, mes, anio, dias = "Mensual", None, None, None
    m = re.search(
        r"([A-Za-zÁÉÍÓÚáéíóúñÑ. ]+?)\s*-\s*(\d{1,2})\s+([A-Za-zñÑ]+)\s+(\d{4})\s+a\s+"
        r"(\d{1,2})\s+([A-Za-zñÑ]+)\s+(\d{4})\s+(\d{1,3})?",
        texto,
    )
    if m:
        tipo = m.group(1).strip().split()[-1].capitalize() if m.group(1).strip() else "Mensual"
        mes = MESES.get(m.group(6).lower())
        anio = int(m.group(7))
        if m.group(8):
            dias = int(m.group(8))
    if not (mes and anio):
        avisos.append("No he podido leer el periodo; revísalo.")

    conceptos = _parse_lineas(lineas)
    totales = _parse_totales(lineas)

    # --- Líquido: primer importe tras "Líquido a Percibir"
    liquido = None
    ml = re.search(r"L[íi]quido\s+a\s+Percibir", texto, re.I)
    if ml:
        mi = IMPORTE_RE.search(texto, ml.end())
        if mi:
            liquido = a_decimal(mi.group())
    if liquido is None:
        avisos.append("No he encontrado el líquido a percibir.")

    mc = re.search(r"Coste\s+Empresa:?\s*(" + IMPORTE_RE.pattern + ")", texto, re.I)
    coste = a_decimal(mc.group(1)) if mc else None

    mp = re.search(r"IRPF\s*\((\d+(?:,\d+)?)\s*%\)", texto)
    irpf_pct = a_decimal(mp.group(1) + ("" if "," in mp.group(1) else ",00")) if mp else None

    return {
        "empresa": empresa,
        "tipo": tipo,
        "mes": mes,
        "anio": anio,
        "dias": dias,
        "lineas": conceptos,
        "total_devengado": totales.get("total_devengado"),
        "total_deducir": totales.get("total_deducir"),
        "base_cc": totales.get("base_cc"),
        "base_irpf": totales.get("base_irpf"),
        "irpf_pct": irpf_pct,
        "liquido": liquido,
        "coste_empresa": coste,
        "avisos": avisos,
    }


def parse_pdf(ruta_pdf: str) -> dict:
    texto = pdf_a_texto(ruta_pdf)
    if len(texto.strip()) < 50:
        raise ParseError("Este PDF no tiene texto seleccionable (parece un escaneo). "
                         "Usa la entrada manual; el OCR llegará en la fase 2.")
    return parse_texto(texto)
