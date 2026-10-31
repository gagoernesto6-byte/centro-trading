"""
Rearma el panel SIN bajar datos nuevos: toma docs/datos.json (lo último que armó la nube),
le pone el reporte de precios y las noticias más recientes (carpetas reportes/ y noticias/)
y escribe la página para el Artifact de Claude. No toca archivos del repositorio.

Uso:  python3 centro/rearmar.py [salida]   (por defecto ~/estudios/escuela-trading/centro/panel.html)
"""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import md_bloques as MD  # noqa: E402

salida = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "estudios/escuela-trading/centro/panel.html"
datos = json.loads((RAIZ / "docs" / "datos.json").read_text(encoding="utf-8"))
datos["reporte"] = MD.ultimo_md(RAIZ / "reportes")
datos["noticias"] = MD.ultimo_md(RAIZ / "noticias", max_bloques=90)
try:
    datos["verificados"] = json.loads((RAIZ / "datos" / "verificados.json").read_text(encoding="utf-8"))
except Exception:
    pass
plantilla = (RAIZ / "centro" / "plantilla.html").read_text(encoding="utf-8")
js = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")
salida.write_text(plantilla.replace("__DATOS__", js), encoding="utf-8")
print(f"Panel rearmado → {salida} · reporte {datos['reporte'] and datos['reporte']['fecha']} · noticias {datos['noticias'] and datos['noticias']['fecha']}")
