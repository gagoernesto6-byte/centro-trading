"""
Alertas de mercado para Ernesto (corre cada hora).

Revisa:
1. Movimientos fuertes en la última hora (NQ, ES, bitcoin, oro, petróleo, VIX).
2. Cruces de niveles clave: máximo/mínimo de ayer (PDH/PDL) y números redondos.
3. Gamma: cambio de régimen y cruces del gamma flip, call wall y put wall.
4. Calendario: datos de alto impacto de EE. UU. en los próximos ~75 minutos.

Si existe la variable de entorno NTFY_TOPIC, manda las alertas al celular por ntfy
(app gratis). Si no, solo las imprime. Guarda el estado para no repetir avisos.

Uso:  uv run python clases/alertas.py            (revisa y avisa)
      uv run python clases/alertas.py --json     (además imprime las alertas en JSON)
"""
import json
import os
import sys
import urllib.request
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent.parent
ESTADO = BASE / "datos" / "estado_alertas.json"
CALENDARIO = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CARACAS = timezone(timedelta(hours=-4))
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def fecha_es(dt, dia=True):
    """Fecha corta en español en hora de Caracas, p. ej. 'jue 15-oct 08:30'."""
    dt = dt.astimezone(CARACAS)
    base = f"{dt.day:02d}-{MESES[dt.month - 1]} {dt:%H:%M}"
    return f"{DIAS[dt.weekday()]} {base}" if dia else base

#            símbolo   nombre          umbral 1 h (%)   paso de número redondo
ACTIVOS = {"NQ=F": ("Nasdaq (NQ)", 0.75, 500),
           "ES=F": ("S&P 500 (ES)", 0.6, 50),
           "BTC-USD": ("Bitcoin", 1.5, 2000),
           "GC=F": ("Oro", 1.0, 100),
           "CL=F": ("Petróleo WTI", 2.0, 5),
           "^VIX": ("VIX (miedo)", 10.0, None)}


def cargar_estado():
    try:
        return json.loads(ESTADO.read_text())
    except Exception:
        return {"precios": {}, "enviadas": {}, "gamma": {}}


def guardar_estado(e):
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(e, ensure_ascii=False, indent=1))


def datos(simbolo):
    h = yf.download(simbolo, period="5d", interval="15m", progress=False, timeout=20, auto_adjust=True)
    d = yf.download(simbolo, period="10d", interval="1d", progress=False, timeout=20, auto_adjust=True)
    for x in (h, d):
        if isinstance(x.columns, pd.MultiIndex):
            x.columns = [c[0] for c in x.columns]
    return h.dropna(), d.dropna()


def ya_enviada(estado, clave, horas=6):
    t = estado["enviadas"].get(clave)
    return t is not None and datetime.now(timezone.utc) - datetime.fromisoformat(t) < timedelta(hours=horas)


def nueva(alertas, estado, clave, titulo, texto, prioridad=3, horas=6):
    if ya_enviada(estado, clave, horas):
        return
    estado["enviadas"][clave] = datetime.now(timezone.utc).isoformat()
    alertas.append({"clave": clave, "titulo": titulo, "texto": texto, "prioridad": prioridad,
                    "hora": fecha_es(datetime.now(timezone.utc), dia=False)})


def revisar_precios(alertas, estado):
    for sim, (nombre, umbral, paso) in ACTIVOS.items():
        try:
            h, d = datos(sim)
        except Exception:
            continue
        if len(h) < 6 or len(d) < 2:
            continue
        precio = float(h["Close"].iloc[-1])
        hace_1h = h[h.index <= h.index[-1] - pd.Timedelta(hours=1)]
        if len(hace_1h):
            cambio = (precio / float(hace_1h["Close"].iloc[-1]) - 1) * 100
            if abs(cambio) >= umbral:
                flecha = "📈 sube" if cambio > 0 else "📉 cae"
                nueva(alertas, estado, f"mov-{sim}-{'up' if cambio > 0 else 'down'}",
                      f"{nombre} {flecha} {cambio:+.2f} % en 1 h",
                      f"Precio {precio:,.2f}. Movimiento fuerte: revisa noticias antes de operar.", prioridad=4, horas=2)
        # niveles del día anterior y números redondos (solo si tenemos el precio de la revisión pasada)
        previo = estado["precios"].get(sim)
        ayer = d.iloc[-2]
        if previo is not None and sim != "^VIX":
            for etiqueta, nivel in [("máximo de ayer (PDH)", float(ayer["High"])), ("mínimo de ayer (PDL)", float(ayer["Low"]))]:
                if (previo - nivel) * (precio - nivel) < 0:
                    sentido = "arriba ⬆️" if precio > nivel else "abajo ⬇️"
                    nueva(alertas, estado, f"nivel-{sim}-{etiqueta[:6]}-{nivel:.0f}",
                          f"{nombre} cruzó hacia {sentido} el {etiqueta}",
                          f"Nivel {nivel:,.2f} · precio {precio:,.2f}. Zona de liquidez: ojo con barridas y rupturas falsas.", horas=12)
            if paso:
                a, b = sorted([previo, precio])
                cruzados = [n * paso for n in range(int(a // paso) + 1, int(b // paso) + 1)]
                redondo = min(cruzados, key=lambda n: abs(n - precio)) if cruzados else None
                if redondo is not None:
                    nueva(alertas, estado, f"redondo-{sim}-{redondo}", f"{nombre} cruzó el número redondo {redondo:,}",
                          f"Precio {precio:,.2f}. En números redondos se juntan órdenes y stops.", horas=12)
        estado["precios"][sim] = precio


def revisar_gamma(alertas, estado):
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import gamma
        res = gamma.resultados()
    except Exception:
        return []
    for r in res:
        etf, positivo = r["etf"], r["gex_total_millones"] > 0
        previo = estado["gamma"].get(etf)
        if previo is not None and previo["positivo"] != positivo:
            nueva(alertas, estado, f"gamma-regimen-{etf}-{positivo}",
                  f"Gamma de {r['futuro']} cambió a {'POSITIVO' if positivo else 'NEGATIVO'}",
                  ("Ahora los dealers frenan el precio: más probable un día de rango." if positivo
                   else "Ahora los dealers aceleran el precio: más probables movimientos fuertes.") +
                  f" GEX {r['gex_total_millones']:+,} M.", prioridad=4, horas=12)
        precio = r["precio_futuro"]
        if previo is not None:
            for nombre, nivel in [("gamma flip", r["gamma_flip"]["futuro"]), ("call wall", r["call_wall"]["futuro"]),
                                  ("put wall", r["put_wall"]["futuro"])]:
                if nivel and (previo["precio"] - nivel) * (precio - nivel) < 0:
                    nueva(alertas, estado, f"gamma-{etf}-{nombre}-{nivel:.0f}",
                          f"{r['futuro']} cruzó el {nombre} (~{nivel:,.0f})",
                          f"Precio {precio:,.0f}. Nivel de opciones donde puede cambiar el comportamiento del precio.", horas=12)
        estado["gamma"][etf] = {"positivo": positivo, "precio": precio}
    return res


def revisar_calendario(alertas, estado):
    try:
        req = urllib.request.Request(CALENDARIO, headers={"User-Agent": "Mozilla/5.0"})
        eventos = json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception:
        return []
    ahora = datetime.now(timezone.utc)
    proximos = []
    for e in eventos:
        if e.get("country") != "USD" or e.get("impact") != "High":
            continue
        t = datetime.fromisoformat(e["date"])
        proximos.append({"hora": fecha_es(t), "titulo": e["title"],
                         "pronostico": e.get("forecast", ""), "anterior": e.get("previous", ""), "ts": t.isoformat()})
        minutos = (t - ahora).total_seconds() / 60
        if 0 <= minutos <= 75:
            nueva(alertas, estado, f"evento-{e['title']}-{e['date']}",
                  f"⏰ En {minutos:.0f} min: {e['title']}",
                  f"Pronóstico {e.get('forecast') or '—'} · anterior {e.get('previous') or '—'}. "
                  "El precio puede saltar en segundos: muchos profesionales esperan a que pase el dato.", prioridad=4, horas=3)
    return [p for p in proximos if datetime.fromisoformat(p["ts"]) >= ahora - timedelta(hours=2)]


def enviar(alerta):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return False
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=alerta["texto"].encode("utf-8"), method="POST",
                                 headers={"Title": alerta["titulo"].encode("utf-8").decode("latin-1", "ignore"),
                                          "Priority": str(alerta["prioridad"]), "Tags": "chart_with_upwards_trend"})
    try:
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception:
        return False


def main():
    estado = cargar_estado()
    alertas = []
    revisar_precios(alertas, estado)
    gamma_res = revisar_gamma(alertas, estado)
    proximos = revisar_calendario(alertas, estado)
    enviadas = sum(enviar(a) for a in alertas)
    historial = estado.get("historial", [])
    estado["historial"] = (alertas + historial)[:50]
    guardar_estado(estado)
    if "--json" in sys.argv:
        print(json.dumps({"alertas": alertas, "calendario": proximos, "gamma": gamma_res}, ensure_ascii=False))
        return
    print(f"{len(alertas)} alertas nuevas ({enviadas} enviadas al celular).")
    for a in alertas:
        print(f"  [{a['hora']}] {a['titulo']} — {a['texto']}")
    print("\nPróximos datos de alto impacto (hora de Caracas):")
    for p in proximos[:8]:
        print(f"  {p['hora']}  {p['titulo']}  (pronóstico {p['pronostico'] or '—'}, anterior {p['anterior'] or '—'})")


if __name__ == "__main__":
    main()
