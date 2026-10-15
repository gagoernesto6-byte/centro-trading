# Rutina en la nube: reporte de mercado con IA (cada hora)

Instrucciones para la rutina de Claude Code que corre en la nube (claude.ai/code/routines).
Escribe todo **en español**, claro y corto: Ernesto lo lee en el celular en 2 minutos.

## Pasos
1. `pip install -r requirements.txt -q`
2. `python clases/mercado.py` → precios, cambios a 1 h, 4 h, 24 h y 7 días, y niveles PDH/PDL/PDC.
3. `python clases/gamma.py`, `python clases/opciones.py` y `python clases/bitcoin.py` → gamma, walls, rango esperado (straddle), skew, put/call, max pain; bitcoin con Deribit + order flow de Coinbase + miedo y codicia. Usa el rango esperado y las probabilidades de tocar niveles (`docs/datos.json` → `escaleras`) en los escenarios.
4. Busca en internet (WebSearch) las noticias de **las últimas horas**:
   - bolsa de EE. UU. y futuros del Nasdaq;
   - la Fed, las tasas y los bonos;
   - petróleo y geopolítica (Ormuz, Rusia);
   - bitcoin;
   - el calendario de hoy y mañana;
   - probabilidades del mercado (CME FedWatch, Polymarket o Kalshi).

   Solo usa noticias con fecha y fuente.
5. Escribe el reporte en `reportes/AAAA-MM-DD-HHh.md` (hora de Caracas, UTC-4) con este formato:
   - `# 📊 Reporte de mercado · <día> <hora>` y una línea de resumen.
   - `## 🌡️ Termómetro`: tabla corta con los 6–8 activos clave y el VIX.
   - `## 📰 Lo que pasó`: 3–6 viñetas con qué pasó → por qué mueve el precio → fuente.
   - `## 📅 Lo que viene`: eventos de las próximas 24–48 h, con la hora de Caracas.
   - `## 🎲 Escenarios (próximas 24 h)` para NQ y bitcoin: base, alcista y bajista con un %. Di que es una estimación. Si hay probabilidades de mercado, cítalas aparte.
   - `## 🧲 Gamma`: el régimen y los niveles (flip y walls) en puntos de ES y NQ, y qué implican (rango o movimientos fuertes).
   - `## 🎯 Niveles a vigilar`: PDH, PDL, máximo y mínimo de hoy, niveles de gamma y números redondos.
   - `## ⚠️ Recordatorio`: demo, riesgo ≤ 1 %, y que en los datos fuertes el precio salta.
6. `python centro/centro.py` → actualiza el panel (`docs/`) y manda las alertas automáticas.
7. Si en esta hora pasó algo **importante** y es entre las 7:00 y las 23:00 de Caracas, manda un resumen de una línea al celular:

   `curl -s -H "Title: <titulo corto>" -d "<resumen de 1-2 líneas>" https://ntfy.sh/$NTFY_TOPIC`

   Es importante si NQ o ES se movieron más de 1,5 % en 4 h, si bitcoin se movió más de 3 %, si el VIX subió más de 15 %, o si hubo una noticia mayor (la Fed, una guerra, un CPI o un dato de empleo con sorpresa).
8. `git add reportes docs datos && git commit -m "Reporte IA <fecha hora>" && git pull --rebase && git push origin main`.

   Haz el push **directo a main**, no a otra rama.

## Reglas
- Nadie sabe con certeza qué hará el precio. Los escenarios son probabilidades, no promesas.
- No das órdenes personalizadas ("compra X ahora"). Das contexto, escenarios y niveles.
- Fines de semana: la bolsa y los futuros están cerrados, así que el reporte se enfoca en cripto y en la apertura del domingo en la noche.
- Es educativo, no es asesoría financiera.
