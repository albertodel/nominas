"""Prueba del parser A3 contra una nómina de ejemplo (estructura real de A3,
datos e importes sintéticos).

    docker run --rm ghcr.io/USUARIO/nominas:latest python -m tests.test_parser
"""
from decimal import Decimal as D
from pathlib import Path

from app.calculos import cuadra, desglose
from app.parser_a3 import parse_texto

r = parse_texto((Path(__file__).parent / "muestra_a3.txt").read_text(encoding="utf-8"))

assert r["empresa"] == "EMPRESA EJEMPLO, S.A.", r["empresa"]
assert (r["anio"], r["mes"], r["tipo"], r["dias"]) == (2026, 10, "Mensual", 30)
assert r["total_devengado"] == D("1660.00")
assert r["total_deducir"] == D("290.46")
assert r["liquido"] == D("1369.54")
assert r["base_irpf"] == D("1570.00") and r["irpf_pct"] == D("12.00")
assert r["coste_empresa"] == D("2196.05")
assert len(r["lineas"]) == 12
d = desglose(r["lineas"])
assert d["salarial"] == D("1570.00") and d["no_salarial"] == D("90.00")
assert d["ss"] == D("102.06") and d["irpf"] == D("188.40")
assert cuadra(r), r
print("OK — parser A3 correcto (12 líneas, todo cuadra)")
