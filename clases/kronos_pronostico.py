"""
Pronóstico con Kronos (modelo de IA de código abierto entrenado con velas de 45 bolsas).

Toma las últimas velas de 1 hora de bitcoin y del futuro del Nasdaq, le pide a Kronos
varias trayectorias posibles para las próximas 24 horas y guarda el rango en datos/kronos.json:
la mediana (p50) y la banda del 10 % al 90 % de esas trayectorias.

Es una herramienta educativa: el modelo da escenarios, no certezas. No es una señal para operar.

Uso:  python clases/kronos_pronostico.py
Necesita el código de Kronos (https://github.com/shiyu-coder/Kronos) en KRONOS_DIR
(por defecto ~/estudios/kronos) y torch, einops, huggingface_hub, safetensors, yfinance y pandas.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

RAIZ = Path(__file__).resolve().parent.parent
KRONOS_DIR = Path(os.environ.get("KRONOS_DIR", Path.home() / "estudios" / "kronos"))
sys.path.insert(0, str(KRONOS_DIR))

import torch  # noqa: E402
from model import Kronos, KronosPredictor, KronosTokenizer  # noqa: E402

ACTIVOS = {"BTC": ("BTC-USD", "Bitcoin"), "NQ": ("NQ=F", "Futuro Nasdaq 100")}
CONTEXTO = 400      # velas de 1 hora que mira el modelo (unos 17 días)
HORIZONTE = 24      # velas que proyecta (24 horas)
MUESTRAS = 20       # trayectorias para armar el rango
HISTORIA = 72       # velas pasadas que se muestran en el panel
CARACAS = timezone(timedelta(hours=-4))


def velas_coinbase(producto="BTC-USD"):
    """Velas de 1 hora de Coinbase (completas y con volumen real); la API da máximo 300 por llamada."""
    import urllib.request
    fin = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    filas = []
    for _ in range(2):
        ini = fin - timedelta(hours=300)
        url = (f"https://api.exchange.coinbase.com/products/{producto}/candles?granularity=3600"
               f"&start={ini.isoformat()}&end={fin.isoformat()}")
        req = urllib.request.Request(url, headers={"User-Agent": "centro-trading"})
        filas += json.loads(urllib.request.urlopen(req, timeout=30).read())
        fin = ini
    df = pd.DataFrame(filas, columns=["t", "low", "high", "open", "close", "volume"]).drop_duplicates("t").sort_values("t")
    df.index = pd.to_datetime(df["t"], unit="s")
    return df[["open", "high", "low", "close", "volume"]].astype(float).tail(CONTEXTO)


def velas(ticker):
    if ticker == "BTC-USD":
        try:
            return velas_coinbase()
        except Exception as e:
            print("Coinbase no respondió, uso Yahoo:", e)
    df = yf.download(ticker, period="60d", interval="1h", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna()
    df.index = pd.to_datetime(df.index, utc=True).tz_convert(None)
    return df.tail(CONTEXTO)


def pronosticar(predictor, df):
    x_ts = pd.Series(df.index)
    paso = pd.Timedelta(hours=1)
    y_ts = pd.Series([df.index[-1] + paso * (i + 1) for i in range(HORIZONTE)])
    cierres = []
    for semilla in range(MUESTRAS):
        torch.manual_seed(semilla)
        p = predictor.predict(df=df.reset_index(drop=True), x_timestamp=x_ts, y_timestamp=y_ts,
                              pred_len=HORIZONTE, T=1.0, top_p=0.9, sample_count=1, verbose=False)
        cierres.append(p["close"].to_numpy())
    c = np.vstack(cierres)
    p10, p50, p90 = (np.percentile(c, q, axis=0) for q in (10, 50, 90))
    return y_ts, p10, p50, p90


def iso(ts):
    return pd.Timestamp(ts).tz_localize("UTC").isoformat()


def main():
    torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))
    tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    modelo = Kronos.from_pretrained("NeoQuasar/Kronos-small")
    predictor = KronosPredictor(modelo, tokenizer, device="cpu", max_context=512)

    salida = {
        "hora": datetime.now(CARACAS).strftime("%Y-%m-%d %H:%M") + " (Caracas)",
        "modelo": "Kronos-small",
        "velas": "1 hora",
        "horizonte_h": HORIZONTE,
        "muestras": MUESTRAS,
        "activos": {},
    }
    for clave, (ticker, nombre) in ACTIVOS.items():
        try:
            df = velas(ticker)
            y_ts, p10, p50, p90 = pronosticar(predictor, df)
            ultimo = float(df["close"].iloc[-1])
            salida["activos"][clave] = {
                "nombre": nombre,
                "ultimo": round(ultimo, 2),
                "historia": [[iso(t), round(float(v), 2)] for t, v in df["close"].tail(HISTORIA).items()],
                "pronostico": [[iso(t), round(float(a), 2), round(float(b), 2), round(float(c), 2)]
                               for t, a, b, c in zip(y_ts, p10, p50, p90)],
                "mediana_final": round(float(p50[-1]), 2),
                "cambio_pct": round((float(p50[-1]) / ultimo - 1) * 100, 2),
                "rango_final": [round(float(p10[-1]), 2), round(float(p90[-1]), 2)],
            }
            print(f"{nombre}: {ultimo:,.2f} → mediana {p50[-1]:,.2f} en {HORIZONTE} h (10–90 %: {p10[-1]:,.2f} – {p90[-1]:,.2f})")
        except Exception as e:  # un activo que falle no tumba al otro
            print(f"{nombre}: no se pudo pronosticar ({e})")
    (RAIZ / "datos").mkdir(exist_ok=True)
    (RAIZ / "datos" / "kronos.json").write_text(json.dumps(salida, ensure_ascii=False), encoding="utf-8")
    print("Guardado en datos/kronos.json")


if __name__ == "__main__":
    main()
