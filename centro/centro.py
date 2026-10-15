"""
Centro de Trading de Ernesto: junta todo lo aprendido en una sola herramienta.

Cada vez que corre (cada hora en la nube):
1. Precios, cambios y niveles (clases/mercado.py).
2. Gamma de los dealers para ES y NQ (clases/gamma.py) y lo guarda a diario.
3. Alertas: movimientos fuertes, cruces de niveles, gamma y datos económicos (clases/alertas.py);
   si existe NTFY_TOPIC, las manda al celular.
4. Titulares (CNBC, Investing.com) y el último reporte con IA (carpeta reportes/).
5. Arma el panel: docs/index.html (página web) y centro/panel.html (versión para Claude).

Uso:  uv run python centro/centro.py   (desde la carpeta escuela-trading)
"""
import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "clases"))
import alertas as AL  # noqa: E402
import mercado as ME  # noqa: E402

CARACAS = timezone(timedelta(hours=-4))
FUENTES = [("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
           ("Investing.com", "https://www.investing.com/rss/news_25.rss")]
ESCALERAS = [("NQ=F", "Nasdaq 100 (NQ)", "QQQ", 500, 2), ("ES=F", "S&P 500 (ES)", "SPY", 50, 2),
             ("BTC-USD", "Bitcoin", None, 2000, 0)]


def titulares():
    out = []
    for nombre, url in FUENTES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            texto = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
        except Exception:
            continue
        for bloque in re.findall(r"<item>(.*?)</item>", texto, re.S)[:8]:
            t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", bloque, re.S)
            l = re.search(r"<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>", bloque, re.S)
            f = re.search(r"<pubDate>(.*?)</pubDate>", bloque, re.S)
            if not t:
                continue
            try:
                fecha = parsedate_to_datetime(f.group(1)) if f else None
                if fecha and fecha.tzinfo is None:
                    fecha = fecha.replace(tzinfo=timezone.utc)
            except Exception:
                try:
                    fecha = datetime.strptime(f.group(1).strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                except Exception:
                    fecha = None
            out.append({"titulo": html.unescape(t.group(1).strip()), "link": (l.group(1).strip() if l else ""),
                        "fuente": nombre, "ts": fecha.timestamp() if fecha else 0,
                        "hora": AL.fecha_es(fecha, dia=False) if fecha else ""})
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out[:12]


def ultimo_reporte():
    carpeta = RAIZ / "reportes"
    archivos = sorted(carpeta.glob("*.md")) if carpeta.exists() else []
    if not archivos:
        return None
    texto = archivos[-1].read_text(encoding="utf-8")
    texto = re.sub(r"^---.*?---\s*", "", texto, flags=re.S)  # quitar encabezado YAML
    bloques = []
    for linea in texto.splitlines():
        l = linea.strip()
        if not l or l.startswith(">") or l.startswith("|---") or l.startswith("[[") or l.lower().startswith("## relacionado"):
            continue
        l = re.sub(r"\*\*(.*?)\*\*", r"\1", l)
        l = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", l)
        l = re.sub(r"\[\[([^\]|]+)(\|[^\]]+)?\]\]", r"\1", l)
        if l.startswith("#"):
            bloques.append({"tipo": "h", "texto": l.lstrip("#").strip()})
        elif l.startswith(("- ", "* ", "• ")):
            bloques.append({"tipo": "li", "texto": l[2:].strip()})
        elif l.startswith("|"):
            celdas = [c.strip() for c in l.strip("|").split("|")]
            bloques.append({"tipo": "li", "texto": " · ".join(c for c in celdas if c)})
        else:
            bloques.append({"tipo": "p", "texto": l})
    return {"fecha": archivos[-1].stem, "bloques": bloques[:60]}


def semaforo(mercado, gamma_res, calendario):
    luces = []
    ahora = datetime.now(timezone.utc)
    futuros = [e for e in calendario if datetime.fromisoformat(e["ts"]) >= ahora]
    if futuros:
        e = futuros[0]
        mins = (datetime.fromisoformat(e["ts"]) - ahora).total_seconds() / 60
        cuando = f"en {mins:.0f} min" if mins < 120 else f"en {mins / 60:.0f} h"
        nivel = "mal" if mins <= 60 else "med" if mins <= 360 else "ok"
        luces.append({"titulo": "Próximo dato fuerte", "valor": f"{e['titulo']} {cuando}", "nivel": nivel,
                      "detalle": "Espera a que pase: el precio puede saltar en segundos." if nivel != "ok" else f"{e['hora']} (Caracas)"})
    else:
        luces.append({"titulo": "Próximo dato fuerte", "valor": "Nada esta semana", "nivel": "ok", "detalle": "Sin eventos de alto impacto pendientes."})
    vix = next((a["precio"] for a in mercado["activos"] if a["simbolo"] == "^VIX"), None)
    if vix is not None:
        nivel, txt = ("ok", "Calma") if vix < 15 else ("ok", "Normal") if vix < 20 else ("med", "Tensión") if vix < 30 else ("mal", "Pánico")
        luces.append({"titulo": "Miedo del mercado (VIX)", "valor": f"{vix:.1f} · {txt}", "nivel": nivel,
                      "detalle": "Con VIX alto, los movimientos son más grandes: baja el tamaño."})
    g = next((r for r in gamma_res if r["etf"] == "QQQ"), None)
    if g:
        pos = g["gex_total_millones"] > 0
        luces.append({"titulo": "Gamma del Nasdaq", "valor": "Positiva · rango probable" if pos else "Negativa · movimientos fuertes",
                      "nivel": "ok" if pos else "med",
                      "detalle": "Las rupturas tienden a fallar; los extremos frenan." if pos else "Stops más amplios o tamaño más chico."})
    nq = next((a for a in mercado["activos"] if a["simbolo"] == "NQ=F"), None)
    if nq and nq["c24"] is not None:
        m = abs(nq["c24"])
        nivel = "ok" if m < 1 else "med" if m < 2 else "mal"
        luces.append({"titulo": "Nasdaq en 24 h", "valor": f"{nq['c24']:+.2f}%", "nivel": nivel,
                      "detalle": "Día normal." if nivel == "ok" else "Día movido: más ruido y barridas."})
    luces.append({"titulo": "Tu regla", "valor": "Riesgo ≤ 1 % · demo", "nivel": "ok",
                  "detalle": "Stop definido antes de entrar. Si dudas, no operes."})
    return luces


def escaleras(mercado, gamma_res):
    precios = {a["simbolo"]: a["precio"] for a in mercado["activos"]}
    out = []
    for sim, nombre, etf, paso, dec in ESCALERAS:
        precio = precios.get(sim)
        if precio is None:
            continue
        niveles = []
        n = mercado["niveles"].get(sim, {})
        for clave, etiqueta in [("PDH", "Máx. de ayer"), ("PDL", "Mín. de ayer"), ("PDC", "Cierre de ayer"),
                                ("HOY_max", "Máx. de hoy"), ("HOY_min", "Mín. de hoy")]:
            if clave in n:
                niveles.append({"precio": n[clave], "etiqueta": etiqueta, "tipo": "liq"})
        g = next((r for r in gamma_res if r["etf"] == etf), None) if etf else None
        if g:
            for clave, etiqueta in [("gamma_flip", "Gamma flip"), ("call_wall", "Call wall"), ("put_wall", "Put wall")]:
                v = g[clave]["futuro"]
                if v:
                    niveles.append({"precio": v, "etiqueta": etiqueta, "tipo": "gam" if clave != "put_wall" else "gamneg"})
        base = int(precio // paso) * paso
        for r in [base - paso, base, base + paso, base + 2 * paso]:
            niveles.append({"precio": float(r), "etiqueta": "Número redondo", "tipo": ""})
        # quitar niveles casi duplicados (se queda el más informativo)
        niveles.sort(key=lambda x: (x["tipo"] == "", x["precio"]))
        limpio = []
        for x in niveles:
            cerca = next((y for y in limpio if abs(x["precio"] - y["precio"]) <= precio * 0.0004), None)
            if cerca is None:
                limpio.append(dict(x))
            elif x["tipo"]:  # dos niveles casi iguales: se juntan las etiquetas (zona más fuerte)
                cerca["etiqueta"] += " + " + x["etiqueta"]
        out.append({"simbolo": sim, "nombre": nombre, "precio": precio, "dec": dec, "niveles": limpio})
    return out


def armar():
    estado = AL.cargar_estado()
    nuevas = []
    AL.revisar_precios(nuevas, estado)
    gamma_res = AL.revisar_gamma(nuevas, estado) or []
    calendario = AL.revisar_calendario(nuevas, estado) or []
    enviadas = sum(AL.enviar(a) for a in nuevas)
    estado["historial"] = (nuevas + estado.get("historial", []))[:50]
    AL.guardar_estado(estado)

    mercado = ME.foto()
    try:
        lab = json.loads((RAIZ / "datos" / "laboratorio.json").read_text(encoding="utf-8"))
    except Exception:
        lab = []
    datos = {
        "hora": AL.fecha_es(datetime.now(timezone.utc)) + f" {datetime.now(CARACAS).year}",
        "semaforo": semaforo(mercado, gamma_res, calendario),
        "alertas": estado["historial"][:10],
        "calendario": [c for c in calendario if datetime.fromisoformat(c["ts"]) >= datetime.now(timezone.utc) - timedelta(hours=1)],
        "mercado": mercado,
        "escaleras": escaleras(mercado, gamma_res),
        "gamma": [{k: v for k, v in g.items() if k != "por_strike"} for g in gamma_res],
        "titulares": titulares(),
        "reporte": ultimo_reporte(),
        "laboratorio": lab,
    }
    plantilla = (RAIZ / "centro" / "plantilla.html").read_text(encoding="utf-8")
    js = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")
    pagina = plantilla.replace("__DATOS__", js)
    (RAIZ / "centro" / "panel.html").write_text(pagina, encoding="utf-8")
    docs = RAIZ / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "index.html").write_text("<!doctype html>\n<html lang=\"es\">\n<head>\n" + pagina.replace("<style>", "</head>\n<body>\n<style>", 1)
                                     .replace("<title>", "<title>", 1) + "\n</body>\n</html>\n", encoding="utf-8")
    (docs / "datos.json").write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    print(f"Panel listo · {len(nuevas)} alertas nuevas ({enviadas} enviadas al celular) · {datos['hora']}")
    for a in nuevas:
        print(f"  [{a['hora']}] {a['titulo']}")


if __name__ == "__main__":
    armar()
