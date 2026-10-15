# Centro de Trading

Herramienta educativa de trading: semáforo antes de operar, alertas al celular, precios,
escalera de niveles (liquidez), gamma de los dealers (GEX estimado), calendario económico,
titulares y un laboratorio de pruebas con datos.

- `centro/centro.py` arma todo y genera el panel (`docs/index.html`).
- `clases/` tiene las piezas: `mercado.py`, `gamma.py`, `alertas.py`, `prueba_barridas.py`.
- `.github/workflows/centro.yml` lo corre cada hora en GitHub (gratis).
- Alertas: app **ntfy** suscrita al tema guardado en el secreto `NTFY_TOPIC`.

Educativo, no es asesoría financiera. Practicar en demo.
