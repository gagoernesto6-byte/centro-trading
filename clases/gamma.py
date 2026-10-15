"""
Calculadora de gamma (GEX): dónde los dealers de opciones frenan o aceleran el precio.

Idea: los market makers venden opciones y se cubren comprando/vendiendo el índice.
- GEX positivo (dealers "largos en gamma"): venden en subidas y compran en bajadas → rango.
- GEX negativo (dealers "cortos en gamma"): persiguen el precio → movimientos más fuertes.
- Gamma flip: precio donde el GEX total cambia de signo.
- Call wall: strike con más gamma de calls (suele frenar subidas).
- Put wall: strike con más gamma de puts (suele frenar caídas).

Supuesto estándar (SqueezeMetrics): dealers largos en calls y cortos en puts.
Es una ESTIMACIÓN: nadie ve las posiciones reales de los dealers.

Datos: cadenas de opciones de SPY y QQQ (Yahoo, gratis, ~15 min de retraso; el
open interest se actualiza una vez al día). Se traducen a ES y NQ con la razón de precios.

Uso:  uv run python clases/gamma.py            (imprime el resumen)
      uv run python clases/gamma.py --json     (salida para el panel/alertas)
"""
import json
import math
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent.parent
DIAS_MAX = 35          # usar vencimientos de los próximos 35 días (ahí está casi toda la gamma)
TASA = 0.04            # tasa libre de riesgo aproximada
PARES = {"SPY": ("ES=F", "ES (S&P 500)"), "QQQ": ("NQ=F", "NQ (Nasdaq 100)")}


def gamma_bs(S, K, T, sigma, r=TASA):
    """Gamma de Black-Scholes (igual para calls y puts). Vectorizado."""
    S = np.asarray(S, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        g = np.exp(-0.5 * d1 ** 2) / (np.sqrt(2 * np.pi) * S * sigma * np.sqrt(T))
    return np.nan_to_num(g)


def ultimo_precio(simbolo):
    d = yf.download(simbolo, period="5d", interval="5m", progress=False, auto_adjust=True)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = [c[0] for c in d.columns]
    return float(d["Close"].dropna().iloc[-1])


def cadena(etf):
    t = yf.Ticker(etf)
    hoy = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
    filas = []
    for venc in t.options:
        fecha = pd.Timestamp(venc)
        dias = (fecha - hoy).days
        if dias < 0 or dias > DIAS_MAX:
            continue
        oc = t.option_chain(venc)
        # vence al cierre (16:00 NY); mínimo ~1 hora para no dividir entre cero
        T = max((dias + 16 / 24) / 365, 1 / (365 * 24))
        for df, tipo in [(oc.calls, "call"), (oc.puts, "put")]:
            d = df[["strike", "openInterest", "impliedVolatility"]].copy()
            d["tipo"], d["T"], d["venc"] = tipo, T, venc
            filas.append(d)
    ch = pd.concat(filas, ignore_index=True)
    ch = ch[(ch.openInterest > 0) & (ch.impliedVolatility.between(0.01, 3))]
    return ch


def gex_total(ch, S):
    g = gamma_bs(S, ch.strike.values, ch["T"].values, ch.impliedVolatility.values)
    signo = np.where(ch.tipo.values == "call", 1.0, -1.0)
    return float(np.sum(signo * g * ch.openInterest.values * 100 * S ** 2 * 0.01))


def analizar(etf):
    fut_sim, fut_nombre = PARES[etf]
    S = ultimo_precio(etf)
    F = ultimo_precio(fut_sim)
    razon = F / S
    ch = cadena(etf)

    g = gamma_bs(S, ch.strike.values, ch["T"].values, ch.impliedVolatility.values)
    ch["gex"] = np.where(ch.tipo == "call", 1, -1) * g * ch.openInterest * 100 * S ** 2 * 0.01
    por_strike = ch.groupby(["strike", "tipo"]).gex.sum().unstack(fill_value=0.0)
    for c in ["call", "put"]:
        if c not in por_strike:
            por_strike[c] = 0.0
    por_strike["neto"] = por_strike["call"] + por_strike["put"]
    cerca = por_strike[(por_strike.index > S * 0.9) & (por_strike.index < S * 1.1)]

    total = float(ch.gex.sum())
    call_wall = float(cerca["call"].idxmax())
    put_wall = float(cerca["put"].idxmin())

    # Gamma flip: GEX total recalculado a precios hipotéticos, buscando el cambio de signo
    grilla = np.linspace(S * 0.92, S * 1.08, 161)
    perfil = np.array([gex_total(ch, x) for x in grilla])
    flip = None
    cruces = np.where(np.diff(np.sign(perfil)) != 0)[0]
    if len(cruces):
        i = cruces[np.argmin(np.abs(grilla[cruces] - S))]
        x0, x1, y0, y1 = grilla[i], grilla[i + 1], perfil[i], perfil[i + 1]
        flip = float(x0 - y0 * (x1 - x0) / (y1 - y0))

    top = cerca["neto"].abs().sort_values(ascending=False).head(5).index.tolist()
    a_fut = lambda x: None if x is None else round(x * razon, 2)
    return {
        "etf": etf, "futuro": fut_nombre, "precio_etf": round(S, 2), "precio_futuro": round(F, 2),
        "gex_total_millones": round(total / 1e6, 1),
        "regimen": "positivo (rango, el precio tiende a frenarse)" if total > 0 else "negativo (movimientos más fuertes)",
        "gamma_flip": {"etf": None if flip is None else round(flip, 2), "futuro": a_fut(flip)},
        "call_wall": {"etf": call_wall, "futuro": a_fut(call_wall)},
        "put_wall": {"etf": put_wall, "futuro": a_fut(put_wall)},
        "strikes_clave": [{"etf": k, "futuro": a_fut(k), "gex_millones": round(float(cerca.loc[k, "neto"]) / 1e6, 1)} for k in top],
        "perfil": {"precios_futuro": [round(x * razon, 1) for x in grilla[::4]], "gex_millones": [round(v / 1e6, 1) for v in perfil[::4]]},
        "por_strike": [{"futuro": round(k * razon, 1), "call": round(float(r.call) / 1e6, 2), "put": round(float(r.put) / 1e6, 2)}
                       for k, r in cerca.iterrows()],
        "contratos_usados": int(len(ch)),
    }


def guardar(res):
    """Guarda una foto diaria para probar hipótesis más adelante (nuestra 'data farm')."""
    carpeta = BASE / "datos" / "gex"
    carpeta.mkdir(parents=True, exist_ok=True)
    fila = {"fecha_utc": datetime.now(timezone.utc).isoformat(timespec="minutes")}
    for r in res:
        p = r["etf"].lower()
        fila.update({f"{p}_precio": r["precio_etf"], f"{p}_gex_M": r["gex_total_millones"],
                     f"{p}_flip": r["gamma_flip"]["etf"], f"{p}_callwall": r["call_wall"]["etf"],
                     f"{p}_putwall": r["put_wall"]["etf"]})
    archivo = carpeta / "historial.csv"
    pd.DataFrame([fila]).to_csv(archivo, mode="a", header=not archivo.exists(), index=False)


def main():
    res = [analizar(etf) for etf in PARES]
    guardar(res)
    if "--json" in sys.argv:
        print(json.dumps(res, ensure_ascii=False))
        return
    for r in res:
        print(f"\n=== {r['futuro']} (calculado con opciones de {r['etf']}) ===")
        print(f"Precio: {r['precio_futuro']:,}   GEX total: {r['gex_total_millones']:+,} millones de $ por cada 1 % de movimiento")
        print(f"Régimen: {r['regimen']}")
        f = r["gamma_flip"]["futuro"]
        print(f"Gamma flip ≈ {f:,}" if f else "Gamma flip: no se encontró en ±8 %")
        print(f"Call wall (techo probable) ≈ {r['call_wall']['futuro']:,}   |   Put wall (suelo probable) ≈ {r['put_wall']['futuro']:,}")
        print("Strikes con más gamma: " + ", ".join(f"{s['futuro']:,} ({s['gex_millones']:+})" for s in r["strikes_clave"]))
    print("\nOjo: es una estimación con datos públicos (supone dealers largos en calls y cortos en puts).")


if __name__ == "__main__":
    main()
