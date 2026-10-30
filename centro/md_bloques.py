"""Convierte un reporte en Markdown (carpetas reportes/ y noticias/) en bloques simples para el panel."""
import re
from pathlib import Path


def ultimo_md(carpeta: Path, max_bloques: int = 60):
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
    return {"fecha": archivos[-1].stem, "bloques": bloques[:max_bloques]}
