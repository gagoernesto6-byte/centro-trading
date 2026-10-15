"""
Bitcoin por dentro (todo gratis y en vivo, 24/7):

- Opciones de Deribit (el mayor mercado de opciones de cripto): gamma de los dealers (GEX),
  gamma flip, call wall, put wall, max pain, volatilidad implícita y rango esperado.
- Futuro perpetuo de Deribit: tasa de financiamiento (funding) e interés abierto.
- Order flow (Coinbase): desequilibrio del libro de órdenes cerca del precio y "delta"
  de las últimas 1.000 operaciones (quién está agrediendo: compradores o vendedores).
- Índice de miedo y codicia de cripto (alternative.me).

Uso:  python clases/bitcoin.py
"""
import json
import math
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gamma import gamma_bs  # noqa: E402

DERIBIT = "https://www.deribit.com/api/v2/public/"
MESES = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def vencimiento(codigo):
    """'17OCT26' → datetime (las opciones de Deribit vencen a las 08:00 UTC)."""
    dia, mes, anio = int(codigo[:-5]), MESES[codigo[-5:-2]], 2000 + int(codigo[-2:])
    return datetime(anio, mes, dia, 8, tzinfo=timezone.utc)


def opciones():
    filas = get(DERIBIT + "get_book_summary_by_currency?currency=BTC&kind=option")["result"]
    ahora = datetime.now(timezone.utc)
    ops = []
    for f in filas:
        try:
            _, v, k, t = f["instrument_name"].split("-")
            T = (vencimiento(v) - ahora).total_seconds() / (365 * 86400)
        except Exception:
            continue
        if T <= 0 or not f.get("mark_iv"):
            continue
        ops.append({"venc": v, "fecha": vencimiento(v), "T": T, "K": float(k), "tipo": "call" if t == "C" else "put",
                    "oi": float(f.get("open_interest") or 0), "iv": float(f["mark_iv"]) / 100,
                    "vol": float(f.get("volume") or 0), "S": float(f["underlying_price"])})
    return ops


def gex(ops, S, dias_max=35):
    sel = [o for o in ops if o["T"] * 365 <= dias_max and o["oi"] > 0]
    K = np.array([o["K"] for o in sel]); T = np.array([o["T"] for o in sel]); iv = np.array([o["iv"] for o in sel])
    oi = np.array([o["oi"] for o in sel]); signo = np.array([1.0 if o["tipo"] == "call" else -1.0 for o in sel])

    def total(x):
        return float(np.sum(signo * gamma_bs(x, K, T, iv) * oi * x ** 2 * 0.01))

    g = signo * gamma_bs(S, K, T, iv) * oi * S ** 2 * 0.01
    por = {}
    for k, s, v in zip(K, signo, g):
        d = por.setdefault(float(k), {"call": 0.0, "put": 0.0})
        d["call" if s > 0 else "put"] += float(v)
    cerca = {k: v for k, v in por.items() if S * 0.85 < k < S * 1.15}
    call_wall = max(cerca, key=lambda k: cerca[k]["call"]) if cerca else None
    put_wall = min(cerca, key=lambda k: cerca[k]["put"]) if cerca else None
    grilla = np.linspace(S * 0.88, S * 1.12, 121)
    perfil = np.array([total(x) for x in grilla])
    flip = None
    cruces = np.where(np.diff(np.sign(perfil)) != 0)[0]
    if len(cruces):
        i = cruces[np.argmin(np.abs(grilla[cruces] - S))]
        x0, x1, y0, y1 = grilla[i], grilla[i + 1], perfil[i], perfil[i + 1]
        flip = float(x0 - y0 * (x1 - x0) / (y1 - y0))
    return {"total_millones": round(float(g.sum()) / 1e6, 1), "flip": flip, "call_wall": call_wall, "put_wall": put_wall,
            "por_strike": [{"precio": k, "call": round(v["call"] / 1e6, 3), "put": round(v["put"] / 1e6, 3)}
                           for k, v in sorted(cerca.items()) if S * 0.9 < k < S * 1.1],
            "perfil": {"precios": [round(x) for x in grilla[::3]], "gex_millones": [round(v / 1e6, 2) for v in perfil[::3]]}}


def resumen_opciones(ops, S):
    vencs = sorted({(o["fecha"], o["venc"]) for o in ops})
    estructura = []
    for fecha, v in vencs[:12]:
        sel = [o for o in ops if o["venc"] == v]
        k = min({o["K"] for o in sel}, key=lambda x: abs(x - S))
        ivs = [o["iv"] for o in sel if o["K"] == k]
        T = sel[0]["T"]
        iv = float(np.mean(ivs))
        estructura.append({"venc": v, "dias": round(T * 365, 2), "iv_atm": round(iv * 100, 1),
                           "rango": round(S * iv * math.sqrt(T)), "rango_pct": round(iv * math.sqrt(T) * 100, 2)})
    # max pain del vencimiento más cercano con interés abierto relevante
    mp = None
    for fecha, v in vencs:
        sel = [o for o in ops if o["venc"] == v]
        if sum(o["oi"] for o in sel) < 500:
            continue
        strikes = sorted({o["K"] for o in sel})
        dolor = [sum(o["oi"] * (max(K - o["K"], 0) if o["tipo"] == "call" else max(o["K"] - K, 0)) for o in sel) for K in strikes]
        mp = {"venc": v, "precio": strikes[int(np.argmin(dolor))]}
        break
    oi_c = sum(o["oi"] for o in ops if o["tipo"] == "call"); oi_p = sum(o["oi"] for o in ops if o["tipo"] == "put")
    iv24 = estructura[0]["iv_atm"] / 100 if estructura else None
    return {"estructura": estructura, "max_pain": mp, "put_call_oi": round(oi_p / oi_c, 2) if oi_c else None,
            "rango_24h": None if iv24 is None else round(S * iv24 * math.sqrt(1 / 365)),
            "iv_corta": estructura[0]["iv_atm"] if estructura else None}


def perpetuo():
    r = get(DERIBIT + "ticker?instrument_name=BTC-PERPETUAL")["result"]
    f8 = r.get("funding_8h") or 0
    return {"precio": r["last_price"], "funding_8h_pct": round(f8 * 100, 4), "funding_anual_pct": round(f8 * 3 * 365 * 100, 1),
            "oi_usd_millones": round((r.get("open_interest") or 0) / 1e6, 1)}


def order_flow():
    libro = get("https://api.exchange.coinbase.com/products/BTC-USD/book?level=2")
    bids = [(float(p), float(q)) for p, q, _ in libro["bids"]]
    asks = [(float(p), float(q)) for p, q, _ in libro["asks"]]
    medio = (bids[0][0] + asks[0][0]) / 2
    def suma(lado, banda):
        return sum(q for p, q in lado if abs(p / medio - 1) <= banda)
    b5, a5 = suma(bids, 0.005), suma(asks, 0.005)
    # muros: precios con más BTC esperando (agrupados cada $250) dentro de ±3 %
    def muros(lado):
        cubos = {}
        for p, q in lado:
            if abs(p / medio - 1) <= 0.03:
                c = round(p / 250) * 250
                cubos[c] = cubos.get(c, 0) + q
        return sorted(cubos.items(), key=lambda x: -x[1])[:3]
    trades = get("https://api.exchange.coinbase.com/products/BTC-USD/trades?limit=1000")
    # En Coinbase "side" es el lado del que esperaba (maker): side=sell → el agresor COMPRÓ
    compra = sum(float(t["size"]) for t in trades if t["side"] == "sell")
    venta = sum(float(t["size"]) for t in trades if t["side"] == "buy")
    t0, t1 = trades[-1]["time"], trades[0]["time"]
    bandas = []
    for banda in (0.001, 0.0025, 0.005, 0.01):
        b, a = suma(bids, banda), suma(asks, banda)
        bandas.append({"banda_pct": banda * 100, "compra_btc": round(b, 1), "venta_btc": round(a, 1),
                       "desequilibrio": round((b - a) / (b + a) * 100, 1) if (b + a) else None})
    return {"medio": round(medio, 1), "bandas": bandas,
            "desequilibrio_05": round((b5 - a5) / (b5 + a5) * 100, 1) if (b5 + a5) else None,
            "bids_05": round(b5, 2), "asks_05": round(a5, 2),
            "muros_compra": [{"precio": p, "btc": round(q, 1)} for p, q in muros(bids)],
            "muros_venta": [{"precio": p, "btc": round(q, 1)} for p, q in muros(asks)],
            "delta_btc": round(compra - venta, 2), "pct_compra": round(compra / (compra + venta) * 100, 1) if compra + venta else None,
            "ventana": f"{t0[11:16]}–{t1[11:16]} UTC"}


def miedo_codicia():
    d = get("https://api.alternative.me/fng/?limit=8")["data"]
    return {"valor": int(d[0]["value"]), "texto": d[0]["value_classification"], "semana": [int(x["value"]) for x in reversed(d)]}


def analizar():
    res = {"calculado": datetime.now(timezone.utc).isoformat(timespec="minutes")}
    try:
        ops = opciones()
        try:
            S = float(get(DERIBIT + "get_index_price?index_name=btc_usd")["result"]["index_price"])
        except Exception:
            S = float(min((o for o in ops), key=lambda o: o["T"])["S"])
        res.update({"precio": round(S, 1), "gex": gex(ops, S), **resumen_opciones(ops, S)})
    except Exception as e:
        res["error_opciones"] = str(e)[:120]
    for clave, fn in [("perpetuo", perpetuo), ("order_flow", order_flow), ("miedo_codicia", miedo_codicia)]:
        try:
            res[clave] = fn()
        except Exception as e:
            res[clave] = {"error": str(e)[:120]}
    return res


if __name__ == "__main__":
    r = analizar()
    g = r.get("gex", {})
    print(f"Bitcoin {r.get('precio')} · GEX {g.get('total_millones')} M$/1% · flip {g.get('flip') and round(g['flip'])} · call wall {g.get('call_wall')} · put wall {g.get('put_wall')}")
    print(f"Rango esperado 24 h: ±{r.get('rango_24h')} · IV corta {r.get('iv_corta')} % · max pain {r.get('max_pain')} · put/call OI {r.get('put_call_oi')}")
    print("Perpetuo:", r.get("perpetuo"))
    of = r.get("order_flow", {})
    print(f"Order flow: desequilibrio ±0,5 % = {of.get('desequilibrio_05')} % · delta {of.get('delta_btc')} BTC ({of.get('pct_compra')} % compras) · {of.get('ventana')}")
    print("Muros compra:", of.get("muros_compra"), "| venta:", of.get("muros_venta"))
    print("Miedo y codicia:", r.get("miedo_codicia"))
