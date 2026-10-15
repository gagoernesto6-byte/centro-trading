"""
Monitor de mercado: foto rápida de los activos principales.

Muestra el último precio y cuánto se movió en ~4 horas, 24 horas y 7 días,
más la volatilidad reciente. Sirve de base para el reporte de noticias.

Uso:  uv run python clases/mercado.py   (desde la carpeta escuela-trading)
"""
import warnings

import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

ACTIVOS = {
    "NQ=F": "Futuro Nasdaq 100 (NQ)",
    "ES=F": "Futuro S&P 500 (ES)",
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "^GSPC": "S&P 500 (bolsa EE. UU.)",
    "^IXIC": "Nasdaq (tecnológicas)",
    "^VIX": "VIX (índice del miedo)",
    "DX-Y.NYB": "Índice del dólar (DXY)",
    "EURUSD=X": "Euro / dólar",
    "GC=F": "Oro",
    "CL=F": "Petróleo WTI",
    "^TNX": "Tasa del bono a 10 años EE. UU. (%)",
}


def cambio(serie: pd.Series, horas: float) -> float | None:
    if serie.empty:
        return None
    fin = serie.index[-1]
    antes = serie[serie.index <= fin - pd.Timedelta(hours=horas)]
    if antes.empty:
        return None
    return (serie.iloc[-1] / antes.iloc[-1] - 1) * 100


def foto():
    """Devuelve los datos (para el panel y las alertas): precios, cambios y niveles."""
    activos = []
    for simbolo, nombre in ACTIVOS.items():
        fila = {"simbolo": simbolo, "nombre": nombre, "precio": None, "c1": None, "c4": None, "c24": None, "c7": None,
                "serie": []}
        try:
            df = yf.download(simbolo, period="10d", interval="1h", progress=False, timeout=20, auto_adjust=True)
            close = df["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            close = close.dropna()
            if len(close):
                fila.update({"precio": float(close.iloc[-1]), "c1": cambio(close, 1), "c4": cambio(close, 4),
                             "c24": cambio(close, 24), "c7": cambio(close, 24 * 7),
                             "serie": [round(float(x), 4) for x in close.tail(72)]})
        except Exception:
            pass
        activos.append(fila)
    niveles = {}
    for simbolo in ["NQ=F", "ES=F", "BTC-USD", "GC=F", "EURUSD=X"]:
        try:
            d = yf.download(simbolo, period="7d", interval="1d", progress=False, timeout=20, auto_adjust=True)
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = [c[0] for c in d.columns]
            d = d.dropna()
            if len(d) < 2:
                continue
            ayer, hoy = d.iloc[-2], d.iloc[-1]
            niveles[simbolo] = {"PDH": float(ayer["High"]), "PDL": float(ayer["Low"]), "PDC": float(ayer["Close"]),
                                "HOY_max": float(hoy["High"]), "HOY_min": float(hoy["Low"])}
        except Exception:
            pass
    return {"activos": activos, "niveles": niveles}


def main():
    datos = foto()

    def f(x, dec=2, signo=True):
        if x is None or pd.isna(x):
            return "—"
        return f"{x:+.{dec}f}%" if signo else f"{x:,.{dec}f}"

    print(f"{'Activo':40} {'Precio':>14} {'~1 h':>8} {'~4 h':>8} {'24 h':>8} {'7 días':>8}")
    for a in datos["activos"]:
        print(f"{a['nombre']:40} {f(a['precio'], 2, False):>14} {f(a['c1']):>8} {f(a['c4']):>8} {f(a['c24']):>8} {f(a['c7']):>8}")
    # Niveles del día anterior (máximo, mínimo y cierre): ahí se acumulan órdenes y stops ("liquidez")
    print("\nNiveles del día anterior (PDH = máximo, PDL = mínimo, PDC = cierre):")
    for simbolo, n in datos["niveles"].items():
        dec = 4 if simbolo == "EURUSD=X" else 2
        print(f"  {ACTIVOS[simbolo]:30} PDH {n['PDH']:,.{dec}f} | PDL {n['PDL']:,.{dec}f} | PDC {n['PDC']:,.{dec}f}"
              f"  → hoy: máx {n['HOY_max']:,.{dec}f} / mín {n['HOY_min']:,.{dec}f}")
    print("\nNota: la bolsa y los futuros cierran fines de semana y de noche; cripto opera 24/7.")


if __name__ == "__main__":
    main()
