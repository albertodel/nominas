"""Cálculos derivados y comprobaciones aritméticas de una nómina.

La misma lógica está replicada en static/editor.js para la validación en vivo.
"""
from __future__ import annotations

from decimal import Decimal

CENT = Decimal("0.01")
TOLERANCIA = Decimal("0.01")

CATEGORIAS = {
    "salarial":    ("Devengo salarial", "devengo"),
    "no_salarial": ("Devengo no salarial (dietas, km…)", "devengo"),
    "informativo": ("Informativo (no suma)", "info"),
    "ss":          ("Cotización Seg. Social", "deduccion"),
    "irpf":        ("Retención IRPF", "deduccion"),
    "otra_ded":    ("Otra deducción", "deduccion"),
}


def D(x) -> Decimal:
    return Decimal(str(x or 0)).quantize(CENT)


def desglose(lineas: list[dict]) -> dict:
    s = {k: Decimal("0") for k in CATEGORIAS}
    for l in lineas:
        s[l["categoria"]] = s.get(l["categoria"], Decimal("0")) + D(l["importe"])
    dev = s["salarial"] + s["no_salarial"]
    ded = s["ss"] + s["irpf"] + s["otra_ded"]
    return {
        "salarial": s["salarial"],
        "no_salarial": s["no_salarial"],
        "ss": s["ss"],
        "irpf": s["irpf"],
        "otra_ded": s["otra_ded"],
        "devengado_calc": dev,
        "deducir_calc": ded,
        "liquido_calc": dev - ded,
    }


def comprobaciones(n: dict) -> list[dict]:
    """Devuelve una lista de {texto, ok, esperado, calculado}."""
    d = desglose(n["lineas"])
    res = []

    def chk(texto, impreso, calculado, estricta=True):
        if impreso is None:
            return
        ok = abs(D(impreso) - D(calculado)) <= TOLERANCIA
        res.append({"texto": texto, "ok": ok, "estricta": estricta,
                    "impreso": D(impreso), "calculado": D(calculado)})

    chk("Suma de devengos = Total devengado", n.get("total_devengado"), d["devengado_calc"])
    chk("Suma de deducciones = Total a deducir", n.get("total_deducir"), d["deducir_calc"])
    if n.get("total_devengado") is not None and n.get("total_deducir") is not None:
        chk("Devengado − Deducciones = Líquido", n.get("liquido"),
            D(n["total_devengado"]) - D(n["total_deducir"]))
    else:
        chk("Devengado − Deducciones = Líquido", n.get("liquido"), d["liquido_calc"])
    if n.get("base_irpf") and n.get("irpf_pct") is not None:
        teorico = (D(n["base_irpf"]) * D(n["irpf_pct"]) / 100).quantize(CENT)
        # Aviso, no bloqueo: A3 a veces redondea distinto
        res.append({"texto": "Base IRPF × % = Retención IRPF",
                    "ok": abs(teorico - d["irpf"]) <= Decimal("0.05"),
                    "estricta": False, "impreso": d["irpf"], "calculado": teorico})
    return res


def cuadra(n: dict) -> bool:
    return all(c["ok"] for c in comprobaciones(n) if c["estricta"])
