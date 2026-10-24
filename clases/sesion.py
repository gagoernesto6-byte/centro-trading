"""
La sesión de hoy en el NQ y el ES: zonas del día, VWAP, perfil de volumen y toques a las paredes de gamma.

1. Zonas del día: con la volatilidad implícita de ayer (VXN / VIX) se calcula 1 sigma diaria.
   La zona roja (posible máximo) y la verde (posible mínimo) usan los cuartiles 25–75 medidos
   en 2010–2018 (ver clases/prueba_zonas.py): fuera de muestra aciertan ~47 % de los días.
2. VWAP (precio promedio pesado por volumen) con bandas de 1 y 2 desviaciones.
3. Perfil de volumen: cuánto se negoció en cada precio. POC = el precio con más volumen;
   área de valor = donde se negoció el 70 % del volumen (VAH arriba, VAL abajo).
4. Paredes de gamma: cuántas veces las tocó el precio hoy y qué tan "firmes" son
   (aproximación propia de la "convexidad": si más allá de la pared la gamma se vuelve
   negativa, una ruptura tiende a acelerar).

Datos: velas de 1 minuto de Yahoo (gratis, con retraso). Sesión de Globex: desde las 18:00 de Nueva York.
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

BASE = Path(__file__).resolve().parent.parent
PARES = {"NQ=F": ("^VXN", "NQ", "QQQ", 5.0), "ES=F": ("^VIX", "ES", "SPY", 1.0)}
TOL = 0.0005


def _bajar(sim, periodo, intervalo):
    d = yf.download(sim, period=periodo, interval=intervalo, progress=False, timeout=20, auto_adjust=True)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = [c[0] for c in d.columns]
    d = d.dropna()
    if len(d) and d.index.tz is not None:
        d.index = d.index.tz_convert("America/New_York")
    return d


def calibracion():
    try:
        return {r["mercado"]: r for r in json.loads((BASE / "datos" / "prueba_zonas.json").read_text())}
    except Exception:
        return {}


def ultima_sesion(m1):
    """Velas de la última sesión de Globex (empieza a las 18:00 de Nueva York)."""
    fin = m1.index[-1]
    inicio = fin.normalize() + pd.Timedelta(hours=18)
    if fin < inicio:
        inicio -= pd.Timedelta(days=1)
    s = m1[m1.index >= inicio]
    if len(s) < 30:                       # domingo temprano: usar la sesión anterior completa
        s = m1[m1.index >= inicio - pd.Timedelta(days=1)]
    return s


def vwap(s):
    tp = (s.High + s.Low + s.Close) / 3
    v = s.Volume.clip(lower=0)
    if v.sum() <= 0:
        return None
    vw = float((tp * v).sum() / v.sum())
    sd = float(math.sqrt(((tp - vw) ** 2 * v).sum() / v.sum()))
    return {"vwap": round(vw, 2), "sd": round(sd, 2),
            "b1": [round(vw - sd, 2), round(vw + sd, 2)], "b2": [round(vw - 2 * sd, 2), round(vw + 2 * sd, 2)]}


def perfil_volumen(s, paso):
    vol = {}
    for h, l, v in zip(s.High.values, s.Low.values, s.Volume.values):
        if v <= 0:
            continue
        a, b = math.floor(l / paso) * paso, math.floor(h / paso) * paso
        n = int(round((b - a) / paso)) + 1
        for k in range(n):
            p = round(a + k * paso, 2)
            vol[p] = vol.get(p, 0.0) + v / n
    if not vol:
        return None
    precios = sorted(vol)
    poc = max(vol, key=vol.get)
    total, i = sum(vol.values()), precios.index(poc)
    lo, hi, acum = i, i, vol[poc]
    while acum < 0.7 * total and (lo > 0 or hi < len(precios) - 1):
        abajo = vol[precios[lo - 1]] if lo > 0 else -1
        arriba = vol[precios[hi + 1]] if hi < len(precios) - 1 else -1
        if arriba >= abajo:
            hi += 1; acum += arriba
        else:
            lo -= 1; acum += abajo
    # para el gráfico: como máximo ~80 barras (agrupar si hace falta)
    grupo = max(1, math.ceil(len(precios) / 80))
    barras = []
    for j in range(0, len(precios), grupo):
        ps = precios[j:j + grupo]
        barras.append({"precio": ps[0], "vol": round(sum(vol[p] for p in ps))})
    return {"poc": poc, "vah": precios[hi], "val": precios[lo], "paso": paso * grupo, "barras": barras}


def zonas(sim, iv_sim, ref):
    iv = _bajar(iv_sim, "10d", "1d")
    if not len(iv) or not ref:
        return None
    ivv = float(iv.Close.iloc[-2] if len(iv) > 1 and iv.index[-1].date() == pd.Timestamp.now(tz="America/New_York").date() else iv.Close.iloc[-1])
    sig = ref * ivv / 100 / math.sqrt(252)
    cal = calibracion().get(PARES[sim][1], {})
    zu, zd = cal.get("zona_max_sigmas", [0.25, 0.85]), cal.get("zona_min_sigmas", [0.2, 0.85])
    return {"iv": round(ivv, 2), "sigma": round(sig, 1), "ref": round(ref, 2),
            "roja": [round(ref + zu[0] * sig, 2), round(ref + zu[1] * sig, 2)],
            "verde": [round(ref - zd[1] * sig, 2), round(ref - zd[0] * sig, 2)],
            "mas1": round(ref + sig, 2), "menos1": round(ref - sig, 2),
            "acierto_max": cal.get("acierto_zona_max"), "acierto_min": cal.get("acierto_zona_min")}


def contar_toques(s, nivel, lado):
    """Toques del día a un nivel (lado=+1 techo, -1 piso) hasta que lo rompe (cierre 0,1 % más allá)."""
    if not nivel:
        return None
    tol, rup = nivel * TOL, nivel * 2 * TOL
    n, en_toque, roto = 0, False, False
    for h, l, c in zip(s.High.values, s.Low.values, s.Close.values):
        extremo = h if lado > 0 else l
        dist = (nivel - extremo) * lado
        if (c - nivel) * lado > rup:
            roto = True
            if not en_toque:
                n += 1
            break                          # después de romper ya no es el mismo nivel
        if not en_toque and dist <= tol:
            en_toque, n = True, n + 1
        elif en_toque and dist > 2 * tol:
            en_toque = False
    return {"toques": n, "roto": roto}


def firmeza(g, nivel, lado):
    """Concentración de gamma en la pared y qué gamma hay más allá (aprox. de la 'convexidad')."""
    try:
        ps = g["por_strike"]
        tipo = "call" if lado > 0 else "put"
        total = sum(abs(x[tipo]) for x in ps) or 1
        cerca = min(ps, key=lambda x: abs(x["futuro"] - nivel))
        conc = abs(cerca[tipo]) / total
        precios, perfil = g["perfil"]["precios_futuro"], g["perfil"]["gex_millones"]
        mas_alla = nivel * (1 + lado * 0.0075)
        gex_alla = float(np.interp(mas_alla, precios, perfil))
        if gex_alla < 0:
            txt, cls = "Si se rompe, puede acelerar (gamma negativa detrás)", "mal"
        elif conc >= 0.15:
            txt, cls = "Firme: mucha gamma concentrada y gamma positiva detrás", "ok"
        else:
            txt, cls = "Media: poca concentración de gamma", "med"
        return {"concentracion_pct": round(conc * 100, 1), "gex_detras_M": round(gex_alla, 1), "lectura": txt, "nivel_color": cls}
    except Exception:
        return None


def analizar(gamma_res=None):
    out = []
    gam = {g["futuro"].split(" ")[0]: g for g in (gamma_res or []) if g}
    for sim, (iv_sim, nombre, etf, paso) in PARES.items():
        try:
            m1 = _bajar(sim, "5d", "1m")
            s = ultima_sesion(m1)
            d1 = _bajar(sim, "10d", "1d")
            # referencia = cierre de la sesión anterior (el último diario completo antes de hoy)
            hoy = (s.index[0] + pd.Timedelta(hours=6)).date()
            prev = d1[[x.date() < hoy for x in d1.index]]
            ref = float(prev.Close.iloc[-1]) if len(prev) else float(s.Open.iloc[0])
            m5 = s.Close.resample("5min").last().dropna()
            r = {"simbolo": sim, "nombre": nombre, "precio": round(float(s.Close.iloc[-1]), 2),
                 "inicio": s.index[0].strftime("%d-%b %H:%M"), "fin": s.index[-1].strftime("%d-%b %H:%M"),
                 "max": round(float(s.High.max()), 2), "min": round(float(s.Low.min()), 2),
                 "serie": [round(float(x), 2) for x in m5.values][-300:],
                 "zonas": zonas(sim, iv_sim, ref), "vwap": vwap(s), "perfil": perfil_volumen(s, paso), "paredes": []}
            g = gam.get(nombre)
            if g:
                apertura = float(s.Open.iloc[0])
                for etiqueta, nivel in (("Call wall", g["call_wall"]["futuro"]), ("Put wall", g["put_wall"]["futuro"]),
                                        ("Gamma flip", g["gamma_flip"]["futuro"])):
                    if not nivel:
                        continue
                    lado = 1 if nivel > apertura else -1   # techo o piso según dónde abrió la sesión
                    t = contar_toques(s, nivel, lado) or {}
                    f = firmeza(g, nivel, lado) if etiqueta != "Gamma flip" else None
                    r["paredes"].append({"nombre": etiqueta, "nivel": nivel, "rol": "techo" if lado > 0 else "piso", **t, "firmeza": f})
            out.append(r)
        except Exception as e:
            out.append({"simbolo": sim, "nombre": nombre, "error": str(e)[:120]})
    guardar_toques(out)
    return out


def guardar_toques(res):
    """Guarda una fila por día con los toques a cada pared (para probar más adelante si el toque N rompe)."""
    filas = []
    for r in res:
        for p in r.get("paredes", []):
            filas.append({"sesion": r.get("fin", "")[:6], "mercado": r["nombre"], "pared": p["nombre"], "nivel": p["nivel"],
                          "toques": p.get("toques"), "roto": p.get("roto")})
    if not filas:
        return
    archivo = BASE / "datos" / "gex" / "toques.csv"
    archivo.parent.mkdir(parents=True, exist_ok=True)
    nuevo = pd.DataFrame(filas)
    if archivo.exists():
        viejo = pd.read_csv(archivo)
        nuevo = pd.concat([viejo, nuevo]).drop_duplicates(subset=["sesion", "mercado", "pared"], keep="last")
    nuevo.to_csv(archivo, index=False)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(BASE / "clases"))
    import gamma as GA
    try:
        g = GA.resultados()
    except Exception as e:
        print("gamma:", e); g = []
    for r in analizar(g):
        r2 = {k: v for k, v in r.items() if k not in ("serie",)}
        if r2.get("perfil"):
            r2["perfil"] = {k: v for k, v in r2["perfil"].items() if k != "barras"}
        print(json.dumps(r2, ensure_ascii=False))
