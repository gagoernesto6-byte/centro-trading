"""
Ballenas: los que más ganan con dinero real y las inversiones de la familia Trump.

Fuentes públicas y verificables (sin claves):
- Hyperliquid: ranking de traders de futuros cripto y sus posiciones abiertas.
- Polymarket: ranking de apostadores de las últimas 24 h y sus apuestas más grandes.
- CoinGecko y Yahoo Finance: $TRUMP, WLFI, Trump Media (DJT) y American Bitcoin (ABTC).

Uso:  python3 clases/ballenas.py   (imprime un resumen)
"""
import json
import urllib.request
from datetime import datetime, timezone

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def _get(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(url, cuerpo, timeout=20):
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode(), headers={"User-Agent": UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _posiciones_hl(wallet):
    try:
        st = _post("https://api.hyperliquid.xyz/info", {"type": "clearinghouseState", "user": wallet})
    except Exception:
        return []
    pos = []
    for p in st.get("assetPositions", []):
        q = p.get("position", {})
        szi = float(q.get("szi") or 0)
        if not szi:
            continue
        pos.append({"moneda": q.get("coin"), "lado": "largo" if szi > 0 else "corto", "valor": round(float(q.get("positionValue") or 0)),
                    "entrada": float(q.get("entryPx") or 0), "pnl": round(float(q.get("unrealizedPnl") or 0)),
                    "apalancamiento": (q.get("leverage") or {}).get("value")})
    return sorted(pos, key=lambda x: -x["valor"])


def hyperliquid(n=10, minimo=1_000_000, muestra=20):
    filas = _get("https://stats-data.hyperliquid.xyz/Mainnet/leaderboard", timeout=90)["leaderboardRows"]

    def ventana(fila, nombre):
        for k, v in fila.get("windowPerformances", []):
            if k == nombre:
                return float(v.get("pnl") or 0), float(v.get("roi") or 0)
        return 0.0, 0.0

    # fuera cuentas del sistema (bóvedas y puentes con miles de millones y ganancias raras) y filas sin historia
    filas = [f for f in filas if minimo <= float(f.get("accountValue") or 0) <= 2e9
             and ventana(f, "week")[0] != 0 and ventana(f, "allTime")[0] > 0]
    top_dia = sorted(filas, key=lambda f: ventana(f, "day")[0], reverse=True)[:n]
    top_semana = sorted(filas, key=lambda f: ventana(f, "week")[0], reverse=True)[:muestra]
    cache, top = {}, []
    for f in top_dia:
        w = f["ethAddress"]
        cache[w] = _posiciones_hl(w)
        pd, rd = ventana(f, "day")
        ps, _ = ventana(f, "week")
        top.append({"wallet": w, "nombre": f.get("displayName") or "", "cuenta": round(float(f["accountValue"])),
                    "pnl_dia": round(pd), "roi_dia": round(rd * 100, 2), "pnl_semana": round(ps), "posiciones": cache[w][:4]})
    # termómetro: de los mejores de la semana, cuántos están en largo o en corto en cada moneda
    monedas = {}
    for f in top_semana:
        w = f["ethAddress"]
        if w not in cache:
            cache[w] = _posiciones_hl(w)
        for p in cache[w]:
            m = monedas.setdefault(p["moneda"], {"moneda": p["moneda"], "largos": 0, "cortos": 0, "valor_largo": 0, "valor_corto": 0})
            if p["lado"] == "largo":
                m["largos"] += 1
                m["valor_largo"] += p["valor"]
            else:
                m["cortos"] += 1
                m["valor_corto"] += p["valor"]
    termometro = sorted(monedas.values(), key=lambda m: -(m["valor_largo"] + m["valor_corto"]))[:5]
    return {"top": top, "muestra": len(top_semana), "termometro": termometro}


def polymarket(n=8):
    filas = _get(f"https://data-api.polymarket.com/v1/leaderboard?timePeriod=DAY&orderBy=PNL&limit={n}")
    out = []
    for f in filas:
        w = f.get("proxyWallet")
        try:
            pos = _get(f"https://data-api.polymarket.com/positions?user={w}&limit=3&sortBy=CURRENT&sortDirection=DESC")
        except Exception:
            pos = []
        out.append({"nombre": f.get("userName") or (w or "")[:10], "wallet": w, "pnl": round(float(f.get("pnl") or 0)),
                    "volumen": round(float(f.get("vol") or 0)),
                    "apuestas": [{"titulo": (p.get("title") or "")[:110], "lado": p.get("outcome"), "valor": round(p.get("currentValue") or 0),
                                  "pnl": round(p.get("cashPnl") or 0)} for p in pos[:3]]})
    return out


def _accion(simbolo, desde):
    import yfinance as yf  # el mismo proveedor que usa el resto del panel
    h = yf.Ticker(simbolo).history(start=desde, auto_adjust=False)
    cierres = [float(x) for x in h["Close"].dropna()]
    precio = cierres[-1]

    def cambio(dias):
        return round((precio / cierres[-1 - dias] - 1) * 100, 2) if len(cierres) > dias else None
    maximo = float(h["High"].max())  # el máximo desde que cotiza con ese nombre
    return {"precio": round(precio, 2), "c24": cambio(1), "c7": cambio(5), "c30": cambio(21), "maximo": round(maximo, 2),
            "desde_maximo": round((precio / maximo - 1) * 100, 1)}


def familia_trump():
    out = []
    try:
        monedas = _get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=official-trump,world-liberty-financial"
                       "&price_change_percentage=24h,7d,30d")
        nombres = {"official-trump": ("$TRUMP", "Memecoin oficial de Donald Trump (enero de 2025)"),
                   "world-liberty-financial": ("WLFI", "Token de World Liberty Financial, el proyecto cripto de la familia Trump")}
        for c in monedas:
            activo, que = nombres.get(c["id"], (c["symbol"].upper(), ""))
            out.append({"activo": activo, "que": que, "precio": c.get("current_price"),
                        "c24": c.get("price_change_percentage_24h_in_currency"), "c7": c.get("price_change_percentage_7d_in_currency"),
                        "c30": c.get("price_change_percentage_30d_in_currency"), "maximo": c.get("ath"),
                        "desde_maximo": c.get("ath_change_percentage")})
    except Exception as e:
        print("coingecko:", e)
    for simbolo, activo, que, desde in [("DJT", "Trump Media (DJT)", "Dueña de Truth Social; Trump es su mayor accionista", "2024-03-26"),
                                        ("ABTC", "American Bitcoin (ABTC)", "Minera de bitcoin de Eric Trump y Donald Trump Jr.", "2025-09-03")]:
        try:
            out.append({"activo": activo, "que": que, **_accion(simbolo, desde)})
        except Exception as e:
            print(simbolo, e)
    return out


def todo():
    datos = {"calculado": datetime.now(timezone.utc).isoformat(timespec="minutes")}
    for nombre, f in [("hyperliquid", hyperliquid), ("polymarket", polymarket), ("trump", familia_trump)]:
        try:
            datos[nombre] = f()
        except Exception as e:
            print(f"ballenas/{nombre}:", e)
            datos[nombre] = None
    return datos


if __name__ == "__main__":
    d = todo()
    hl = d.get("hyperliquid") or {}
    print("Hyperliquid termómetro:", hl.get("termometro"))
    for t in (hl.get("top") or [])[:5]:
        print(f"  {t['wallet'][:10]} hoy {t['pnl_dia']:+,} · semana {t['pnl_semana']:+,} ·", [f"{p['moneda']} {p['lado']} ${p['valor']:,}" for p in t["posiciones"][:2]])
    for p in (d.get("polymarket") or [])[:5]:
        print(f"  Polymarket {p['nombre']}: {p['pnl']:+,} ·", [f"{a['lado']} · {a['titulo'][:40]}" for a in p["apuestas"][:2]])
    for t in d.get("trump") or []:
        print(f"  {t['activo']}: {t['precio']} · 30d {t['c30']} · desde máximo {t['desde_maximo']}")
