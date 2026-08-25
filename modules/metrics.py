"""
DCubic Image System Platform — métricas quantitativas (Princípio 1).

Todos os cálculos operam sobre masks de voxels brutos ou malhas geradas
a partir deles. Nunca sobre imagens renderizadas nem sobre overlays visuais.
"""

from __future__ import annotations
import io
import os
import tempfile
os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")
import numpy as np
import pyvista as pv


def compute_volumes(
    masks: dict[str, np.ndarray],
    spacing: tuple[float, float, float],
) -> dict[str, float]:
    """
    Volume em mm³ por tecido.
    Cálculo: contagem de voxels True × volume unitário do voxel (Princípio 1).
    """
    voxel_vol = spacing[0] * spacing[1] * spacing[2]
    return {name: float(mask.sum()) * voxel_vol for name, mask in masks.items()}


def compute_surface_areas(
    meshes: dict[str, pv.PolyData | None],
) -> dict[str, float]:
    """
    Área de superfície em mm² por tecido.
    Cálculo: soma das áreas dos triângulos da malha gerada por marching cubes.
    A malha foi gerada a partir do mask de voxels brutos, logo indiretamente
    derivada dos dados brutos — em conformidade com o Princípio 1.
    """
    areas: dict[str, float] = {}
    for name, mesh in meshes.items():
        if mesh is None:
            areas[name] = 0.0
            continue
        sized = mesh.compute_cell_sizes(length=False, area=True, volume=False)
        areas[name] = float(sized.cell_data["Area"].sum())
    return areas


def compute_distance(
    point_a: tuple[int, int, int],
    point_b: tuple[int, int, int],
    spacing: tuple[float, float, float],
) -> float:
    """
    Distância euclidiana em mm entre dois pontos em coordenadas de voxel (Z, Y, X).
    Converte voxels para mm usando spacing antes de calcular.
    """
    za, ya, xa = point_a
    zb, yb, xb = point_b
    sz, sy, sx = spacing
    return float(np.sqrt(
        ((za - zb) * sz) ** 2 +
        ((ya - yb) * sy) ** 2 +
        ((xa - xb) * sx) ** 2
    ))


def mesh_to_stl_bytes(mesh: pv.PolyData) -> bytes:
    """Serializa malha PyVista para STL binário (bytes) — para download."""
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        tmp = f.name
    try:
        mesh.save(tmp)
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp)


def mesh_to_obj_bytes(mesh: pv.PolyData) -> bytes:
    """Serializa malha PyVista para OBJ (bytes) — para download."""
    with tempfile.NamedTemporaryFile(suffix=".obj", delete=False) as f:
        tmp = f.name
    try:
        mesh.save(tmp)
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp)
