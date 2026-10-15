"""
Análisis de opciones de SPY (→ ES) y QQQ (→ NQ): lo que el mercado de opciones "espera".

- Rango esperado (expected move): cuánto espera el mercado que se mueva el precio hasta
  cada vencimiento, sacado del precio del straddle (call + put en el dinero).
- Estructura temporal: volatilidad implícita en el dinero (ATM) para cada vencimiento.
- Sonrisa y skew: volatilidad por strike; si las puts están más caras = miedo a caídas.
- Put/Call: cuántas puts vs calls se operan (volumen) y hay abiertas (open interest).
- Max pain: precio al que vencerían sin valor la mayor cantidad de opciones.
- Open interest por strike (calls vs puts) cerca del precio.
- Distribución de precios: campana log-normal con la volatilidad implícita.
- Probabilidades: chance de tocar / terminar arriba de un nivel.

Datos de Yahoo (gratis, ~15 min de retraso). Confiables con el mercado abierto (9:45–16:00 NY);
fuera de horario se usa el último cálculo bueno (datos/opciones/ultimo.json).

Uso:  python clases/opciones.py
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gamma as G  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
CACHE = BASE / "datos" / "opciones" / "ultimo.json"
DIAS_MAX = 60


def N(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def cadena_completa(etf):
    t = yf.Ticker(etf)
    hoy = pd.Timestamp.now(tz="America/New_York")
    filas = []
    for venc in t.options:
        cierre = pd.Timestamp(venc + " 16:00", tz="America/New_York")
        horas = (cierre - hoy).total_seconds() / 3600
        if horas < -0.5 or horas / 24 > DIAS_MAX:
            continue
        oc = t.option_chain(venc)
        for df, tipo in [(oc.calls, "call"), (oc.puts, "put")]:
            d = df[["strike", "openInterest", "volume", "impliedVolatility", "bid", "ask", "lastPrice"]].copy()
            d["tipo"], d["venc"], d["T"] = tipo, venc, max(horas, 0.5) / (24 * 365)
            filas.append(d)
    ch = pd.concat(filas, ignore_index=True).fillna(0)
    ch["mid"] = np.where((ch.bid > 0) & (ch.ask > 0), (ch.bid + ch.ask) / 2, ch.lastPrice)
    return ch


def atm(ch_v, S):
    """IV y straddle en el dinero para un vencimiento."""
    strikes = ch_v.strike.unique()
    k = strikes[np.argmin(np.abs(strikes - S))]
    c = ch_v[(ch_v.strike == k) & (ch_v.tipo == "call")]
    p = ch_v[(ch_v.strike == k) & (ch_v.tipo == "put")]
    ivs = [x for x in [c.impliedVolatility.mean(), p.impliedVolatility.mean()] if x and x > 0.03]
    straddle = float(c.mid.mean() + p.mid.mean()) if len(c) and len(p) else None
    return k, (float(np.mean(ivs)) if ivs else None), straddle


def max_pain(ch_v):
    strikes = np.sort(ch_v.strike.unique())
    calls, puts = ch_v[ch_v.tipo == "call"], ch_v[ch_v.tipo == "put"]
    dolor = [float((calls.openInterest * np.maximum(K - calls.strike, 0)).sum() +
                   (puts.openInterest * np.maximum(puts.strike - K, 0)).sum()) for K in strikes]
    return float(strikes[int(np.argmin(dolor))])


def analizar(etf):
    fut_sim, fut_nombre = G.PARES[etf]
    S, F = G.ultimo_precio(etf), G.ultimo_precio(fut_sim)
    razon = F / S
    ch = cadena_completa(etf)
    vencs = sorted(ch.venc.unique())

    # Estructura temporal y rango esperado por vencimiento
    estructura = []
    for v in vencs:
        cv = ch[ch.venc == v]
        k, iv, straddle = atm(cv, S)
        T = float(cv["T"].iloc[0])
        dias = round(T * 365, 2)
        em = straddle if straddle and straddle > 0 else (S * iv * math.sqrt(T) if iv else None)
        estructura.append({"venc": v, "dias": dias, "iv_atm": None if iv is None else round(iv * 100, 2),
                           "rango_pct": None if not em else round(em / S * 100, 2),
                           "rango_futuro": None if not em else round(em * razon, 1)})
    estructura = [e for e in estructura if e["iv_atm"]]
    proximo = estructura[0] if estructura else None
    hoy_ny = pd.Timestamp.now(tz="America/New_York")
    viernes = (hoy_ny + pd.offsets.Week(weekday=4)).strftime("%Y-%m-%d") if hoy_ny.weekday() != 4 else hoy_ny.strftime("%Y-%m-%d")
    semanal = next((e for e in estructura if e["venc"] >= viernes), None)

    # Sonrisa (vencimiento de ~30 días) y skew
    obj = min(estructura, key=lambda e: abs(e["dias"] - 30)) if estructura else None
    sonrisa, skew = [], None
    if obj:
        cv = ch[(ch.venc == obj["venc"]) & (ch.impliedVolatility > 0.03)]
        otm = pd.concat([cv[(cv.tipo == "put") & (cv.strike <= S)], cv[(cv.tipo == "call") & (cv.strike > S)]])
        otm = otm[(otm.strike > S * 0.85) & (otm.strike < S * 1.15)].sort_values("strike")
        sonrisa = [{"futuro": round(k * razon, 0), "iv": round(iv * 100, 2), "mon": round(k / S * 100, 1)}
                   for k, iv in zip(otm.strike, otm.impliedVolatility)]
        def iv_en(m):
            fila = otm.iloc[(otm.strike - S * m).abs().argsort()[:1]]
            return float(fila.impliedVolatility.iloc[0]) if len(fila) else None
        a, b = iv_en(0.95), iv_en(1.05)
        if a and b:
            skew = round((a - b) * 100, 2)

    # Put/Call y max pain del vencimiento más cercano
    vol_c, vol_p = ch[ch.tipo == "call"].volume.sum(), ch[ch.tipo == "put"].volume.sum()
    oi_c, oi_p = ch[ch.tipo == "call"].openInterest.sum(), ch[ch.tipo == "put"].openInterest.sum()
    mp = max_pain(ch[ch.venc == vencs[0]]) if vencs else None

    # Open interest por strike (vencimientos de las próximas 5 semanas) cerca del precio
    cerca = ch[(ch["T"] * 365 <= 35) & (ch.strike > S * 0.94) & (ch.strike < S * 1.06)]
    oi = cerca.groupby(["strike", "tipo"]).openInterest.sum().unstack(fill_value=0)
    oi_strike = [{"futuro": round(k * razon, 0), "call": int(r.get("call", 0)), "put": int(r.get("put", 0))} for k, r in oi.iterrows()]

    # Distribución log-normal para el próximo vencimiento y el semanal
    def campana(e):
        if not e:
            return None
        sig = e["iv_atm"] / 100 * math.sqrt(max(e["dias"], 0.02) / 365)
        xs = np.linspace(F * math.exp(-3.2 * sig), F * math.exp(3.2 * sig), 81)
        pdf = np.exp(-(np.log(xs / F)) ** 2 / (2 * sig ** 2)) / (xs * sig * math.sqrt(2 * math.pi))
        return {"venc": e["venc"], "sigma": sig, "x": [round(float(x), 1) for x in xs],
                "pdf": [float(p / pdf.max()) for p in pdf],
                "uno": [round(F * math.exp(-sig), 1), round(F * math.exp(sig), 1)],
                "dos": [round(F * math.exp(-2 * sig), 1), round(F * math.exp(2 * sig), 1)]}

    return {
        "etf": etf, "futuro": fut_nombre, "precio_etf": round(S, 2), "precio_futuro": round(F, 2), "razon": razon,
        "proximo": proximo, "semanal": semanal, "estructura": estructura[:14],
        "sonrisa": sonrisa, "skew_30d": skew, "venc_sonrisa": obj["venc"] if obj else None,
        "put_call_volumen": round(vol_p / vol_c, 2) if vol_c else None,
        "put_call_oi": round(oi_p / oi_c, 2) if oi_c else None,
        "max_pain": {"venc": vencs[0] if vencs else None, "etf": mp, "futuro": None if mp is None else round(mp * razon, 0)},
        "oi_strike": oi_strike,
        "distribucion": {"proximo": campana(proximo), "semanal": campana(semanal)},
        "calculado": datetime.now(timezone.utc).isoformat(timespec="minutes"),
    }


def probabilidades(F, sigma, niveles):
    """sigma = volatilidad hasta el vencimiento (no anualizada). Devuelve P(tocar) y P(terminar más allá)."""
    out = []
    for n in niveles:
        K = n["precio"]
        if K <= 0 or sigma <= 0:
            continue
        z = abs(math.log(K / F)) / sigma
        terminar = 1 - N(z)                 # terminar más allá del nivel
        tocar = min(1.0, 2 * terminar)      # principio de reflexión (aprox.)
        out.append({**n, "p_tocar": round(tocar * 100, 1), "p_terminar": round(terminar * 100, 1)})
    return out


def resultados():
    if G.en_horario() or not CACHE.exists():
        res = [analizar(etf) for etf in G.PARES]
        if G.en_horario():
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(res, ensure_ascii=False))
        else:
            for r in res:
                r["nota"] = "Fuera del horario de mercado: estimación poco confiable hasta las 9:45."
        return res
    res = json.loads(CACHE.read_text())
    for r in res:
        r["nota"] = f"Del último horario de mercado ({r.get('calculado', '?')} UTC)."
    return res


if __name__ == "__main__":
    for r in resultados():
        p, s = r["proximo"], r["semanal"]
        print(f"\n=== {r['futuro']} ({r['etf']}) · {r.get('nota', 'en vivo')}")
        if p:
            print(f"Rango esperado al {p['venc']}: ±{p['rango_futuro']} pts (±{p['rango_pct']} %) · IV {p['iv_atm']} %")
        if s:
            print(f"Rango esperado semanal ({s['venc']}): ±{s['rango_futuro']} pts (±{s['rango_pct']} %)")
        print(f"Skew 30d (IV 95 % − IV 105 %): {r['skew_30d']} pts · Put/Call vol {r['put_call_volumen']} · OI {r['put_call_oi']}")
        print(f"Max pain ({r['max_pain']['venc']}): {r['max_pain']['futuro']}")
        print("Estructura: " + ", ".join(f"{e['dias']:.0f}d {e['iv_atm']}%" for e in r["estructura"][:8]))
