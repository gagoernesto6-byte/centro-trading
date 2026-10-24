"""
Prueba: cuando el precio toca varias veces el mismo nivel, ¿en qué toque se rompe?

Idea (TikTok de Chalito: "tercer rebote en el mismo nivel… a la cuarta, la atravesó").
Todavía no tenemos años de paredes de gamma guardadas (las juntamos desde el 14-oct-2026),
así que probamos la misma pregunta con los niveles más usados: el máximo y el mínimo de ayer.

Reglas (iguales para todos los casos):
- Toque: el precio llega a menos de TOL del nivel sin cerrar del otro lado.
- El toque termina cuando el precio se aleja más de 2×TOL.
- Ruptura: una vela CIERRA más allá del nivel por más de RUP.
- TOL = 0,05 % del precio · RUP = 0,10 % del precio.

Uso:  uv run --with yfinance --with pandas --with numpy python clases/prueba_toques.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

BASE = Path(__file__).resolve().parent.parent
TOL, RUP = 0.0005, 0.0010


def velas(sim, periodo, intervalo):
    d = yf.download(sim, period=periodo, interval=intervalo, progress=False, timeout=30, auto_adjust=True)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = [c[0] for c in d.columns]
    d = d.dropna()
    d.index = d.index.tz_convert("America/New_York") if d.index.tz else d.index.tz_localize("UTC").tz_convert("America/New_York")
    return d


def recorrer(df, nivel, lado):
    """lado=+1: nivel arriba (máximo de ayer); lado=-1: nivel abajo (mínimo de ayer).
    Devuelve la lista de toques: True si ese toque terminó en ruptura."""
    tol, rup = nivel * TOL, nivel * RUP
    toques, en_toque = [], False
    for h, l, c in zip(df.High.values, df.Low.values, df.Close.values):
        extremo = h if lado > 0 else l
        dist = (nivel - extremo) * lado          # >0: todavía no llega
        cierre_mas_alla = (c - nivel) * lado > rup
        if cierre_mas_alla:
            if not en_toque:
                toques.append(True)              # rompió sin tocar antes (cuenta como toque que rompe)
            else:
                toques[-1] = True
            return toques
        if not en_toque and dist <= tol:
            en_toque = True
            toques.append(False)
        elif en_toque and dist > 2 * tol:
            en_toque = False
    return toques


def medir(sim, periodo, intervalo):
    d = velas(sim, periodo, intervalo)
    # sesión de Globex: de las 18:00 de un día a las 17:00 del siguiente → la etiqueta es el día siguiente
    sesion = (d.index + pd.Timedelta(hours=6)).date
    d["sesion"] = sesion
    resumen = d.groupby("sesion").agg(H=("High", "max"), L=("Low", "min"))
    dias = list(resumen.index)
    casos = []
    for i in range(1, len(dias)):
        ayer, hoy = resumen.loc[dias[i - 1]], d[d.sesion == dias[i]]
        if len(hoy) < 10:
            continue
        for nivel, lado in ((ayer.H, 1), (ayer.L, -1)):
            # solo cuenta si el día abre del lado de adentro
            if (hoy.Open.iloc[0] - nivel) * lado >= 0:
                continue
            t = recorrer(hoy, float(nivel), lado)
            if t:
                casos.append(t)
    maxn = 5
    filas = []
    for n in range(1, maxn + 1):
        llegaron = [t for t in casos if len(t) >= n]
        rompen = sum(1 for t in llegaron if t[n - 1])
        filas.append({"toque": n, "casos": len(llegaron), "rompe_pct": round(rompen / len(llegaron) * 100, 1) if llegaron else None})
    return {"mercado": sim.replace("=F", ""), "datos": f"{intervalo} · {periodo}", "niveles_tocados": len(casos), "por_toque": filas}


def main():
    res = []
    for sim in ("NQ=F", "ES=F"):
        for periodo, intervalo in (("60d", "5m"), ("730d", "1h")):
            try:
                res.append(medir(sim, periodo, intervalo))
            except Exception as e:
                print(sim, intervalo, "error:", e)
    (BASE / "datos" / "prueba_toques.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    for r in res:
        print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
