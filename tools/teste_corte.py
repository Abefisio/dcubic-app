"""Teste mínimo da função Cortes (modules/slices.gerar_corte) com trimesh atual.
Falha com ModuleNotFoundError: rtree se a dependência sumir do requirements.txt.
Uso: python tools/teste_corte.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import trimesh
from modules import slices

m = trimesh.creation.annulus(r_min=1.0, r_max=3.0, height=5.0)   # "dente" com canal
malhas = {"dentina": slices.para_trimesh(m.vertices[:, [2, 1, 0]], m.faces[:, ::-1])}
png, info = slices.gerar_corte(malhas, {"dentina": (255, 255, 255)}, "Axial (Z)", 0.0,
                               slices.bbox_combinado(malhas), 40.0)
assert png and png[:8] == b"\x89PNG\r\n\x1a\n", "PNG inválido"
print("OK: PNG de", len(png), "bytes; trimesh", trimesh.__version__)
