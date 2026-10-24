"""
La araña: lector de informes anuales (10-K) de la SEC.

Baja el último 10-K de una empresa, encuentra las cifras etiquetadas (XBRL en línea), calcula
observaciones y prepara el recorrido que hace la araña en el visor (docs/arana/index.html).

Uso:   uv run --with beautifulsoup4 python arana/construir.py AMD NVDA AAPL
Salida: docs/arana/data/<TICKER>.json (cifras, secciones, observaciones) y <TICKER>.html (el informe limpio)

La SEC exige un correo de contacto en cada descarga: se lee del archivo privado .sec_contacto
(no se sube a GitHub).
"""
import json
import math
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "docs" / "arana" / "data"
CACHE = RAIZ / "arana" / "cache"
UA = (RAIZ / ".sec_contacto").read_text().strip()

# clave → (conceptos XBRL en orden de preferencia, etiqueta en español, "dur" = del año / "inst" = al cierre)
CLAVES = {
    "valor_mercado": (["dei:EntityPublicFloat"], "Valor de mercado (acciones del público)", "cualquiera"),
    "acciones": (["dei:EntityCommonStockSharesOutstanding"], "Acciones en circulación", "cualquiera"),
    "ingresos": (["us-gaap:Revenues", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                  "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax", "us-gaap:SalesRevenueNet"], "Ingresos (ventas)", "dur"),
    "costo_ventas": (["us-gaap:CostOfRevenue", "us-gaap:CostOfGoodsAndServicesSold"], "Costo de lo vendido", "dur"),
    "utilidad_bruta": (["us-gaap:GrossProfit"], "Utilidad bruta", "dur"),
    "id": (["us-gaap:ResearchAndDevelopmentExpense", "us-gaap:ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"], "Investigación y desarrollo (I+D)", "dur"),
    "sga": (["us-gaap:SellingGeneralAndAdministrativeExpense"], "Gastos de ventas y administración", "dur"),
    "utilidad_operativa": (["us-gaap:OperatingIncomeLoss"], "Utilidad operativa", "dur"),
    "impuestos": (["us-gaap:IncomeTaxExpenseBenefit"], "Impuesto sobre la renta", "dur"),
    "utilidad_neta": (["us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss"], "Utilidad neta", "dur"),
    "bpa": (["us-gaap:EarningsPerShareDiluted"], "Utilidad por acción (diluida)", "dur"),
    "sbc": (["us-gaap:ShareBasedCompensation", "us-gaap:AllocatedShareBasedCompensationExpense"], "Pago en acciones a empleados", "dur"),
    "flujo_operativo": (["us-gaap:NetCashProvidedByUsedInOperatingActivities"], "Efectivo generado por la operación", "dur"),
    "capex": (["us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", "us-gaap:PaymentsToAcquireProductiveAssets"], "Inversión en fábricas y equipos (capex)", "dur"),
    "recompras": (["us-gaap:PaymentsForRepurchaseOfCommonStock"], "Recompra de acciones", "dur"),
    "dividendos": (["us-gaap:PaymentsOfDividends", "us-gaap:PaymentsOfDividendsCommonStock"], "Dividendos pagados", "dur"),
    "caja": (["us-gaap:CashAndCashEquivalentsAtCarryingValue"], "Efectivo", "inst"),
    "inversiones_cp": (["us-gaap:ShortTermInvestments", "us-gaap:MarketableSecuritiesCurrent",
                        "us-gaap:AvailableForSaleSecuritiesDebtSecuritiesCurrent"], "Inversiones de corto plazo", "inst"),
    "cxc": (["us-gaap:AccountsReceivableNetCurrent"], "Cuentas por cobrar", "inst"),
    "inventario": (["us-gaap:InventoryNet"], "Inventario", "inst"),
    "goodwill": (["us-gaap:Goodwill"], "Plusvalía (goodwill)", "inst"),
    "activos": (["us-gaap:Assets"], "Activos totales", "inst"),
    "deuda_cp": (["us-gaap:LongTermDebtCurrent", "us-gaap:DebtCurrent"], "Deuda que vence en el año", "inst"),
    "deuda_lp": (["us-gaap:LongTermDebtNoncurrent", "us-gaap:LongTermDebt"], "Deuda de largo plazo", "inst"),
    "pasivos": (["us-gaap:Liabilities"], "Pasivos totales", "inst"),
    "patrimonio": (["us-gaap:StockholdersEquity"], "Patrimonio de los accionistas", "inst"),
}
CON_ANTERIOR = ("ingresos", "utilidad_neta", "utilidad_operativa", "flujo_operativo", "bpa")
N_OTRAS = 55


def get(url, nombre=None):
    """Descarga con el correo de contacto que exige la SEC (y guarda copia para no repetir)."""
    if nombre and (CACHE / nombre).exists():
        return (CACHE / nombre).read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    datos = urllib.request.urlopen(req, timeout=90).read()
    time.sleep(0.25)                      # la SEC pide no pasar de 10 pedidos por segundo
    if nombre:
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / nombre).write_bytes(datos)
    return datos


def es_num(x, dec=0):
    s = f"{x:,.{dec}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def dinero(v):
    if v is None:
        return "—"
    a, signo = abs(v), "-" if v < 0 else ""
    if a >= 1e9:
        return f"{signo}${es_num(a / 1e6)} M"
    if a >= 1e6:
        return f"{signo}${es_num(a / 1e6, 1)} M"
    return f"{signo}${es_num(a, 2)}"


def humano(concepto):
    base = concepto.split(":")[-1]
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base)


def ultimo_10k(ticker):
    tabla = json.loads(get("https://www.sec.gov/files/company_tickers.json", "company_tickers.json"))
    fila = next(v for v in tabla.values() if v["ticker"] == ticker.upper())
    cik = int(fila["cik_str"])
    sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))
    r = sub["filings"]["recent"]
    i = next(k for k, f in enumerate(r["form"]) if f == "10-K")
    acc = r["accessionNumber"][i]
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{r['primaryDocument'][i]}"
    return {"cik": cik, "empresa": sub["name"], "url": url, "periodo": r["reportDate"][i], "presentado": r["filingDate"][i],
            "archivo": f"{ticker.upper()}-{acc}.htm"}


def contextos(soup):
    ctx = {}
    for c in soup.find_all("xbrli:context"):
        p = c.find("xbrli:period")
        d = {"dims": c.find("xbrli:segment") is not None}
        for k in ("startdate", "enddate", "instant"):
            t = p.find("xbrli:" + k) if p else None
            d[k] = date.fromisoformat(t.text.strip()[:10]) if t else None
        ctx[c.get("id")] = d
    return ctx


def valor(tag):
    texto = tag.get_text(strip=True)
    if tag.get("format", "").endswith(("fixed-zero", "fixedzero")) or texto in ("—", "-", "–"):
        v = 0.0
    else:
        try:
            v = float(texto.replace(",", ""))
        except ValueError:
            return None
    v *= 10 ** int(tag.get("scale", "0") or 0)
    return -v if tag.get("sign") == "-" else v


def construir(ticker):
    info = ultimo_10k(ticker)
    print(f"{ticker}: {info['empresa']} · 10-K del {info['periodo']} · {info['url']}")
    html = get(info["url"], info["archivo"]).decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    ctx = contextos(soup)
    fin = date.fromisoformat(info["periodo"])

    def cerca(d, objetivo, dias=12):
        return d is not None and abs((d - objetivo).days) <= dias

    def tipo_ctx(cid):
        c = ctx.get(cid)
        if not c or c["dims"]:
            return None
        if c["enddate"] and c["startdate"] and (c["enddate"] - c["startdate"]).days > 300:
            if cerca(c["enddate"], fin):
                return "dur"
            if cerca(c["enddate"], date(fin.year - 1, fin.month, min(fin.day, 28))):
                return "dur_ant"
        if c["instant"]:
            if cerca(c["instant"], fin):
                return "inst"
            if cerca(c["instant"], date(fin.year - 1, fin.month, min(fin.day, 28))):
                return "inst_ant"
        return "otro"

    # 1) Quitar lo que no se ve (encabezado XBRL oculto), scripts e imágenes
    for t in soup.find_all("ix:header"):
        t.decompose()
    for t in soup.find_all(["script", "img"]):
        t.decompose()
    for t in soup.find_all(style=re.compile(r"display:\s*none")):
        t.decompose()

    # 2) Páginas: contar los saltos de página en orden
    pagina, marcas = 1, {}
    hechos, n = [], 0
    for el in soup.find_all(True):
        st = (el.get("style") or "").replace(" ", "")
        if "page-break-before:always" in st:
            pagina += 1
        if el.name == "ix:nonfraction":
            n += 1
            fid = f"f{n}"
            hechos.append({"id": fid, "concepto": el.get("name"), "ctx": tipo_ctx(el.get("contextref")),
                           "unidad": (el.get("unitref") or "").lower(), "valor": valor(el), "pagina": pagina, "orden": n})
            marcas[id(el)] = fid
        if "page-break-after:always" in st:
            pagina += 1

    # 3) Elegir las cifras clave (primera aparición del año, sin desgloses) y valores del año anterior
    figuras, usados, valores, anteriores = [], set(), {}, {}
    for clave, (conceptos, etiqueta, cual) in CLAVES.items():
        for concepto in conceptos:
            candidatos = [h for h in hechos if h["concepto"] == concepto and h["valor"] is not None and
                          (h["ctx"] in (("dur",) if cual == "dur" else ("inst",) if cual == "inst" else ("dur", "inst", "otro")))]
            if candidatos:
                h = candidatos[0]
                figuras.append({**h, "clave": clave, "etiqueta": etiqueta, "tipo": "clave"})
                usados.add(h["id"]); valores[clave] = h["valor"]
                if clave in CON_ANTERIOR:
                    ant = [x for x in hechos if x["concepto"] == concepto and x["ctx"] == "dur_ant" and x["valor"] is not None]
                    if ant:
                        anteriores[clave] = ant[0]["valor"]
                break

    # 4) Otras cifras del año (para "Más del reporte"): una por concepto, repartidas por todo el informe
    vistos, otras = {f["concepto"] for f in figuras}, []
    for h in hechos:
        if h["concepto"] in vistos or h["ctx"] not in ("dur", "inst") or h["valor"] is None:
            continue
        if h["unidad"] in ("usd",) and abs(h["valor"]) < 1e6:
            continue
        if h["valor"] == 0:
            continue
        vistos.add(h["concepto"])
        otras.append(h)
    etiquetas_es = {}
    try:
        etiquetas_es = json.loads((RAIZ / "arana" / "etiquetas_es.json").read_text(encoding="utf-8"))
    except Exception:
        pass

    def repartir(lista, cuantas):
        if len(lista) <= cuantas:
            return lista
        paso = len(lista) / cuantas
        return [lista[int(i * paso)] for i in range(cuantas)]

    # primero las que ya tienen nombre en español; si faltan, se completa con las demás
    trad = [h for h in otras if h["concepto"].split(":")[-1] in etiquetas_es]
    resto = [h for h in otras if h["concepto"].split(":")[-1] not in etiquetas_es]
    otras = repartir(trad, N_OTRAS)
    if len(otras) < N_OTRAS:
        otras += repartir(resto, N_OTRAS - len(otras))
    for h in otras:
        nombre = h["concepto"].split(":")[-1]
        figuras.append({**h, "clave": None, "etiqueta": etiquetas_es.get(nombre, humano(h["concepto"])), "tipo": "otra",
                        "traducida": nombre in etiquetas_es})

    for f in figuras:
        u = f["unidad"]
        if "shares" in u and "usd" not in u:
            f["texto"] = f"{es_num(f['valor'] / 1e6, 1)} M"
        elif "usdpershare" in u.replace("_", "").replace("/", "per") or u in ("usdpershare", "usd/shares"):
            f["texto"] = f"${es_num(f['valor'], 2)}"
        elif u == "pure":
            f["texto"] = f"{es_num(f['valor'] * 100, 1)} %"
        else:
            f["texto"] = dinero(f["valor"])
    figuras.sort(key=lambda f: f["orden"])

    # 5) Secciones: títulos en negrita fuera de tablas (NOTE 1…, Item 7…, Revenue Recognition…)
    secciones, k = [], 0
    for sp in soup.find_all("span", style=re.compile(r"font-weight:\s*(700|bold)")):
        texto = re.sub(r"\s+", " ", sp.get_text(" ", strip=True))
        if not (4 <= len(texto) <= 90) or sp.find_parent("table") or texto.endswith((".", ",")) and not re.match(r"^(Item|ITEM)\s+\d", texto):
            continue
        if re.fullmatch(r"[\d\W]+", texto):
            continue
        k += 1
        sp["data-s"] = f"s{k}"
        secciones.append({"id": f"s{k}", "titulo": texto, "nota": bool(re.match(r"^(NOTE|Note)\s+\d+", texto)),
                          "item": bool(re.match(r"^(ITEM|Item)\s+\d", texto))})
    # páginas de las secciones
    pagina, pags = 1, {}
    for el in soup.find_all(True):
        st = (el.get("style") or "").replace(" ", "")
        if "page-break-before:always" in st:
            pagina += 1
        if el.get("data-s"):
            pags[el["data-s"]] = pagina
        if "page-break-after:always" in st:
            pagina += 1
    for s in secciones:
        s["pagina"] = pags.get(s["id"])
    # nos quedamos con todas las NOTAS e ITEMS y con algunos subtítulos dentro de las notas
    principales = [s for s in secciones if s["nota"] or s["item"]]
    primera_nota = next((s["pagina"] for s in secciones if s["nota"]), 10 ** 6)
    subs = [s for s in secciones if not (s["nota"] or s["item"]) and (s["pagina"] or 0) >= primera_nota]
    if len(subs) > 30:
        paso = len(subs) / 30
        subs = [subs[int(i * paso)] for i in range(30)]
    elegidas = {s["id"] for s in principales + subs}
    for sp in soup.find_all("span", attrs={"data-s": True}):
        if sp["data-s"] not in elegidas:
            del sp["data-s"]
    secciones = [s for s in secciones if s["id"] in elegidas]

    # 6) Convertir las etiquetas XBRL en HTML normal (las cifras quedan como <span data-f="…">)
    elegidas_f = {f["id"] for f in figuras}
    for el in soup.find_all("ix:nonfraction"):
        fid = marcas.get(id(el))
        el.name = "span"
        for a in list(el.attrs):
            del el[a]
        if fid in elegidas_f:
            el["data-f"] = fid
    for el in soup.find_all(re.compile(r"^ix:")):
        el.unwrap()
    cuerpo = soup.body or soup
    for a in cuerpo.find_all("a"):
        a.attrs.pop("href", None)
    contenido = "".join(str(x) for x in cuerpo.contents)

    # 7) Observaciones (en español, con los números)
    v, obs = valores, []

    def agregar(titulo, texto, valor_txt, usa):
        if all(x in v for x in usa):
            obs.append({"titulo": titulo, "texto": texto, "valor": valor_txt, "usa": usa})

    if "flujo_operativo" in v and "capex" in v:
        fcf = v["flujo_operativo"] - abs(v["capex"])
        agregar("Flujo de caja libre", "El efectivo que le queda después de invertir en fábricas y equipos.", dinero(fcf), ["flujo_operativo", "capex"])
        devuelto = abs(v.get("recompras", 0)) + abs(v.get("dividendos", 0))
        usa = [x for x in ("recompras", "dividendos") if x in v]
        if usa and fcf > 0:
            agregar("Devolvió a los accionistas", f"Repartió el {es_num(devuelto / fcf * 100)} % de su flujo de caja libre en recompras y dividendos.",
                    dinero(devuelto), ["flujo_operativo", "capex"] + usa)
        if "sbc" in v and fcf > 0:
            agregar("Costo escondido: pago en acciones", f"Lo que paga a empleados en acciones equivale al {es_num(v['sbc'] / fcf * 100)} % del flujo de caja libre (diluye a los accionistas).",
                    dinero(v["sbc"]), ["sbc", "flujo_operativo", "capex"])
        if "valor_mercado" in v and fcf > 0:
            agregar("¿Cara o barata?", f"Al valor de mercado del informe, comprarla toda costaba unos {es_num(v['valor_mercado'] / fcf)} años de flujo de caja libre.",
                    f"{es_num(v['valor_mercado'] / fcf, 1)} veces", ["valor_mercado", "flujo_operativo", "capex"])
    if "ingresos" in v and "ingresos" in anteriores and anteriores["ingresos"]:
        g = (v["ingresos"] / anteriores["ingresos"] - 1) * 100
        agregar("Crecimiento de ventas", f"Los ingresos {'crecieron' if g >= 0 else 'cayeron'} {es_num(abs(g), 1)} % frente al año anterior ({dinero(anteriores['ingresos'])}).",
                f"{'+' if g >= 0 else '−'}{es_num(abs(g), 1)} %", ["ingresos"])
    if "utilidad_neta" in v and "utilidad_neta" in anteriores and anteriores["utilidad_neta"] > 0:
        g = (v["utilidad_neta"] / anteriores["utilidad_neta"] - 1) * 100
        agregar("Ganancias vs. año anterior", f"La utilidad neta {'subió' if g >= 0 else 'bajó'} {es_num(abs(g), 1)} % (antes: {dinero(anteriores['utilidad_neta'])}).",
                f"{'+' if g >= 0 else '−'}{es_num(abs(g), 1)} %", ["utilidad_neta"])
    if "ingresos" in v and v["ingresos"]:
        if "utilidad_bruta" in v:
            m = v["utilidad_bruta"] / v["ingresos"] * 100
            agregar("Margen bruto", f"De cada $100 que vende, le quedan ${es_num(m)} después de pagar lo que cuesta fabricarlo.", f"{es_num(m, 1)} %", ["utilidad_bruta", "ingresos"])
        if "utilidad_operativa" in v:
            m = v["utilidad_operativa"] / v["ingresos"] * 100
            agregar("Margen operativo", f"Después de pagar todos sus gastos (sueldos, I+D, ventas) le quedan ${es_num(m)} de cada $100.", f"{es_num(m, 1)} %", ["utilidad_operativa", "ingresos"])
        if "id" in v:
            m = v["id"] / v["ingresos"] * 100
            agregar("Apuesta al futuro (I+D)", f"Gasta el {es_num(m, 1)} % de sus ventas en investigación y desarrollo.", f"{es_num(m, 1)} %", ["id", "ingresos"])
    if "caja" in v and ("deuda_lp" in v or "deuda_cp" in v):
        liquido = v["caja"] + v.get("inversiones_cp", 0)
        deuda = v.get("deuda_lp", 0) + v.get("deuda_cp", 0)
        neto = liquido - deuda
        usa = ["caja"] + [x for x in ("inversiones_cp", "deuda_lp", "deuda_cp") if x in v]
        agregar("Caja neta" if neto >= 0 else "Deuda neta",
                f"Tiene {dinero(abs(neto))} {'más en efectivo e inversiones que en deudas' if neto >= 0 else 'más de deuda que de efectivo e inversiones'}.",
                dinero(neto), usa)
    if "impuestos" in v and "utilidad_neta" in v and v["utilidad_neta"] + v["impuestos"] > 0:
        t = v["impuestos"] / (v["utilidad_neta"] + v["impuestos"]) * 100
        if v["impuestos"] >= 0:
            agregar("Impuestos", f"Pagó una tasa efectiva de impuestos de {es_num(t, 1)} % sobre sus ganancias.", f"{es_num(t, 1)} %", ["impuestos", "utilidad_neta"])
        else:
            agregar("Impuestos", f"Tuvo un beneficio fiscal: en vez de pagar, el fisco le reconoció {dinero(abs(v['impuestos']))} (tasa efectiva {es_num(t, 1)} %).",
                    dinero(v["impuestos"]), ["impuestos", "utilidad_neta"])
    if "goodwill" in v and "activos" in v and v["activos"]:
        p = v["goodwill"] / v["activos"] * 100
        agregar("Compras de otras empresas", f"El {es_num(p)} % de sus activos es plusvalía (goodwill): lo que pagó de más al comprar otras empresas.", f"{es_num(p, 1)} %", ["goodwill", "activos"])

    claves_presentes = [f for f in figuras if f["tipo"] == "clave"]
    datos = {
        "ticker": ticker.upper(), "empresa": info["empresa"].upper(), "formulario": "10-K",
        "periodo": info["periodo"], "presentado": info["presentado"], "anio_fiscal": fin.year - 1 if (fin.month == 1 and fin.day <= 7) else fin.year,
        "url": info["url"], "paginas": pagina,
        "figuras": [{k: f[k] for k in ("id", "clave", "etiqueta", "texto", "valor", "pagina", "tipo")} for f in figuras],
        "secciones": [{k: s[k] for k in ("id", "titulo", "pagina", "nota", "item")} for s in secciones],
        "observaciones": obs,
        "total_claves": len(claves_presentes), "total_cifras": len(figuras),
        "sin_traducir": sorted({f["concepto"].split(":")[-1] for f in figuras if f["tipo"] == "otra" and not f.get("traducida")}),
    }
    SALIDA.mkdir(parents=True, exist_ok=True)
    (SALIDA / f"{ticker.upper()}.json").write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    (SALIDA / f"{ticker.upper()}.html").write_text(contenido, encoding="utf-8")
    print(f"  {len(claves_presentes)} cifras clave · {len(figuras)} cifras en total · {len(secciones)} secciones · "
          f"{len(obs)} observaciones · {pagina} páginas · {len(contenido) / 1e6:.1f} MB")
    return datos


def indice():
    """Lista de empresas disponibles para el selector del visor."""
    lista = []
    for f in sorted(SALIDA.glob("*.json")):
        if f.name == "indice.json":
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        lista.append({"ticker": d["ticker"], "empresa": d["empresa"], "anio_fiscal": d["anio_fiscal"]})
    (SALIDA / "indice.json").write_text(json.dumps(lista, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    for t in sys.argv[1:] or ["AMD"]:
        try:
            construir(t)
        except Exception as e:
            print(t, "error:", e)
    indice()
