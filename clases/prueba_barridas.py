"""
Prueba 1: ¿las barridas de liquidez (SMC) predicen el rebote?

Hipótesis SMC: cuando el precio "barre" unos mínimos iguales (EQL) y cierra de
vuelta arriba, sube en los siguientes minutos más de lo normal (y al revés con
los máximos iguales).

Método honesto:
- Datos: futuro del Nasdaq (NQ=F), velas de 5 min, ~60 días (lo máximo gratis).
- Un mínimo "pivote" solo se da por confirmado K velas después (sin mirar el futuro).
- Mínimos iguales = 2 pivotes a menos de TOL puntos, sin que el nivel se rompiera en medio.
- Barrida = una vela que perfora el nivel y CIERRA de vuelta del otro lado.
- Ruptura = una vela que perfora el nivel y cierra más allá (lo que el SMC "rechazaría").
- Se compara contra el comportamiento normal de TODAS las velas (grupo control).

Uso:  uv run python clases/prueba_barridas.py   (desde la carpeta escuela-trading)
"""
import math
import warnings

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

import sys

# Uso opcional: prueba_barridas.py SIMBOLO INTERVALO PERIODO   (p. ej. ES=F 1h 730d)
SIMBOLO = sys.argv[1] if len(sys.argv) > 1 else "NQ=F"
INTERVALO = sys.argv[2] if len(sys.argv) > 2 else "5m"
PERIODO = sys.argv[3] if len(sys.argv) > 3 else "60d"
MIN_VELA = {"5m": 5, "15m": 15, "1h": 60}[INTERVALO]
K = 3                 # velas a cada lado para confirmar un pivote
TOL_PCT = 0.0002      # 0,02 % del precio (~6 puntos en NQ) para considerar "iguales"
VENTANA = 120         # buscar el pivote gemelo en las últimas 120 velas
VIDA = 288 if MIN_VELA == 5 else 120   # cuántas velas vale el nivel si nadie lo toca
HORIZONTES = [6, 12] if MIN_VELA == 5 else [1, 2]   # 5m: 30 y 60 min · 1h: 1 y 2 horas
COSTO_PCT = 0.000035  # comisión + deslizamiento ida y vuelta ≈ 1 punto en NQ (estimación)


def cargar():
    df = yf.download(SIMBOLO, period=PERIODO, interval=INTERVALO, progress=False, timeout=20, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df[["Open", "High", "Low", "Close"]].dropna()
    return df


def pivotes(serie: np.ndarray, tipo: str):
    """Devuelve lista de (indice_pivote, indice_confirmacion, precio)."""
    out = []
    n = len(serie)
    for i in range(K, n - K):
        izq, der = serie[i - K:i], serie[i + 1:i + K + 1]
        if tipo == "min" and serie[i] < izq.min() and serie[i] <= der.min():
            out.append((i, i + K, serie[i]))
        if tipo == "max" and serie[i] > izq.max() and serie[i] >= der.max():
            out.append((i, i + K, serie[i]))
    return out


def niveles_iguales(df, tipo):
    s = (df["Low"] if tipo == "min" else df["High"]).to_numpy()
    piv = pivotes(s, tipo)
    niveles = []
    for a in range(len(piv)):
        ia, ca, pa = piv[a]
        for b in range(a - 1, -1, -1):
            ib, cb, pb = piv[b]
            if ia - ib > VENTANA:
                break
            if abs(pa - pb) <= TOL_PCT * pa:
                nivel = min(pa, pb) if tipo == "min" else max(pa, pb)
                medio = s[ib + 1:ia]
                roto = (medio < nivel - 0.25).any() if tipo == "min" else (medio > nivel + 0.25).any()
                if not roto:
                    niveles.append((ca, nivel))  # activo desde la confirmación del 2.º pivote
                break
    return niveles


def eventos(df, tipo):
    low, high, close = df["Low"].to_numpy(), df["High"].to_numpy(), df["Close"].to_numpy()
    idx = df.index
    res = []
    usados = set()
    for desde, nivel in niveles_iguales(df, tipo):
        if (round(nivel, 2), tipo) in usados:
            continue
        for t in range(desde + 1, min(desde + VIDA, len(df) - max(HORIZONTES) - 1)):
            toca = low[t] < nivel - 0.25 if tipo == "min" else high[t] > nivel + 0.25
            if not toca:
                continue
            # descartar si la ventana cruza el cierre diario (hueco de más de 30 min)
            fin = t + max(HORIZONTES)
            if (idx[fin] - idx[t]) > pd.Timedelta(minutes=MIN_VELA * max(HORIZONTES) + 30):
                break
            recupera = close[t] > nivel if tipo == "min" else close[t] < nivel
            fila = {"t": idx[t], "tipo": tipo, "clase": "barrida" if recupera else "ruptura"}
            for h in HORIZONTES:
                mov = close[t + h] - close[t]
                fila[f"mov_{h}"] = mov if tipo == "min" else -mov  # positivo = a favor de la idea SMC
            res.append(fila)
            usados.add((round(nivel, 2), tipo))
            break
    return res


def control(df):
    """Movimiento normal: todas las velas, a 30 y 60 min (sin cruzar el cierre diario)."""
    close = df["Close"].to_numpy()
    idx = df.index
    filas = []
    for t in range(len(df) - max(HORIZONTES) - 1):
        if (idx[t + max(HORIZONTES)] - idx[t]) > pd.Timedelta(minutes=MIN_VELA * max(HORIZONTES) + 30):
            continue
        filas.append({f"mov_{h}": close[t + h] - close[t] for h in HORIZONTES})
    return pd.DataFrame(filas)


COSTO = None


def resumen(nombre, serie, base_media, base_std):
    n = len(serie)
    if n == 0:
        return f"  {nombre:46} n=0"
    media = serie.mean()
    acierto = (serie > 0).mean() * 100
    z = (media - base_media) / (base_std / math.sqrt(n)) if base_std > 0 else 0
    return (f"  {nombre:46} n={n:3d} | media {media:+7.1f} pts | a favor {acierto:4.0f}% "
            f"| neto tras costo {media - COSTO:+7.1f} | z vs normal {z:+.2f}")


def main():
    global COSTO
    df = cargar()
    COSTO = COSTO_PCT * df["Close"].iloc[-1]
    print(f"Datos: {SIMBOLO} {INTERVALO}, {df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d}, {len(df)} velas\n")
    ev = pd.DataFrame(eventos(df, "min") + eventos(df, "max"))
    ctrl = control(df)
    for h in HORIZONTES:
        print(f"=== A {h * MIN_VELA} minutos (puntos a favor de la idea SMC; 'normal' = cualquier vela) ===")
        bm, bs = ctrl[f"mov_{h}"].mean(), ctrl[f"mov_{h}"].std()
        print(f"  {'Normal (todas las velas, subida = +)':46} n={len(ctrl):4d} | media {bm:+7.1f} pts | sube {(ctrl[f'mov_{h}'] > 0).mean() * 100:4.0f}%")
        for tipo, txt in [("min", "mínimos iguales → largo"), ("max", "máximos iguales → corto")]:
            for clase in ["barrida", "ruptura"]:
                s = ev[(ev.tipo == tipo) & (ev.clase == clase)][f"mov_{h}"] if len(ev) else pd.Series(dtype=float)
                base = bm if tipo == "min" else -bm
                print(resumen(f"{clase.capitalize()} de {txt}", s, base, bs))
        todas = ev[ev.clase == "barrida"][f"mov_{h}"] if len(ev) else pd.Series(dtype=float)
        print(resumen("TODAS las barridas (largo y corto juntos)", todas, 0, bs))
        print()
    print("Cómo leerlo: 'a favor' >50 % y 'z' mayor que +2 serían señal de ventaja real. Entre -2 y +2 = no se distingue del azar.")
    print("Ojo: 60 días es una muestra chica; un resultado aquí es una pista, no una prueba definitiva.")


if __name__ == "__main__":
    main()
