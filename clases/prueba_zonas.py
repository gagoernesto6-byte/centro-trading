"""
Prueba: ¿las "zonas del día" sacadas de la volatilidad implícita aciertan el máximo y el mínimo?

Idea (la del TikTok que "predice el máximo y el mínimo con 91 %"): antes de abrir, con la
volatilidad implícita (VXN para el Nasdaq, VIX para el S&P) se calcula cuánto suele moverse
el precio en un día (1 sigma). Arriba queda una zona donde podría estar el máximo y abajo una
donde podría estar el mínimo.

Cómo medimos (sin hacer trampa):
- Referencia = cierre de ayer. Sigma diaria = referencia × IV / 100 / raíz(252).
- u = (máximo − referencia) / sigma   ·   d = (referencia − mínimo) / sigma
- Las zonas se calibran con los años 2010–2018 (cuartiles 25–75 de u y d) y se prueban
  en 2019–hoy, que el método nunca vio (fuera de muestra).

Uso:  uv run --with yfinance --with pandas --with numpy python clases/prueba_zonas.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

BASE = Path(__file__).resolve().parent.parent
PARES = {"NQ=F": ("^VXN", "NQ"), "ES=F": ("^VIX", "ES")}
CORTE = "2019-01-01"


def bajar(sim):
    d = yf.download(sim, start="2009-06-01", interval="1d", progress=False, timeout=30, auto_adjust=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = [c[0] for c in d.columns]
    return d.dropna()


def medir(sim):
    vol_sim, nombre = PARES[sim]
    f, v = bajar(sim), bajar(vol_sim)
    df = pd.DataFrame({"H": f.High, "L": f.Low, "C": f.Close}).join(v.Close.rename("IV"), how="inner")
    df["ref"] = df.C.shift(1)
    df["sig"] = df.ref * df.IV.shift(1) / 100 / np.sqrt(252)
    df = df.dropna()
    df = df[(df.H > df.L) & (df.sig > 0)]
    df["u"] = (df.H - df.ref) / df.sig
    df["d"] = (df.ref - df.L) / df.sig
    df["c"] = (df.C - df.ref) / df.sig
    ent, prueba = df[df.index < CORTE], df[df.index >= CORTE]
    # zonas calibradas solo con el pasado
    zu = (float(ent.u.quantile(0.25)), float(ent.u.quantile(0.75)))
    zd = (float(ent.d.quantile(0.25)), float(ent.d.quantile(0.75)))
    en_zona_max = ((prueba.u >= zu[0]) & (prueba.u <= zu[1])).mean() * 100
    en_zona_min = ((prueba.d >= zd[0]) & (prueba.d <= zd[1])).mean() * 100
    ambos = (((prueba.u >= zu[0]) & (prueba.u <= zu[1])) & ((prueba.d >= zd[0]) & (prueba.d <= zd[1]))).mean() * 100
    # ¿Qué tan ancha tiene que ser la banda para "acertar" 91 %?
    cubre = {k: float(((prueba.u <= k) & (prueba.d <= k)).mean() * 100) for k in (1.0, 1.5, 2.0)}
    k91 = float(np.quantile(np.maximum(prueba.u, prueba.d), 0.91))
    r = {
        "mercado": nombre, "dias_prueba": int(len(prueba)), "desde": str(prueba.index[0].date()),
        "cierre_dentro_1sigma": round(float((prueba.c.abs() <= 1).mean() * 100), 1),
        "toca_mas_1sigma": round(float((prueba.u >= 1).mean() * 100), 1),
        "toca_menos_1sigma": round(float((prueba.d >= 1).mean() * 100), 1),
        "zona_max_sigmas": [round(x, 2) for x in zu], "zona_min_sigmas": [round(x, 2) for x in zd],
        "acierto_zona_max": round(float(en_zona_max), 1), "acierto_zona_min": round(float(en_zona_min), 1),
        "acierto_ambas": round(float(ambos), 1),
        "rango_dentro_de": {f"±{k}σ": round(x, 1) for k, x in cubre.items()},
        "sigmas_para_91": round(k91, 2),
        "u_mediana": round(float(prueba.u.median()), 2), "d_mediana": round(float(prueba.d.median()), 2),
    }
    return r


def main():
    res = [medir(s) for s in PARES]
    out = BASE / "datos" / "prueba_zonas.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    for r in res:
        print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
