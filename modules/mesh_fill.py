"""
mesh_fill.py — gera malha sólida preenchendo o interior de uma casca STL oca.

Caminho primário (VTK via pyvista.select_enclosed_points):
  grade de voxels → inside mask → binary_fill_holes → marching_cubes → PolyData

Caminho fallback (puro numpy/scipy, sem VTK display):
  rasteriza vértices+centróides → dilation fecha casca → label/flood exterior
  → interior = complemento → binary_fill_holes → marching_cubes → PolyData

A função preencher_interior NUNCA derruba o app: retorna None em qualquer erro.
"""

import os
import logging

os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")  # headless no Cloud

import numpy as np
try:
    import pyvista as pv
    _PV_OK = True
except Exception as _pv_import_err:
    logging.warning("[mesh_fill] pyvista/vtk indisponível: %s — somente fallback scipy", _pv_import_err)
    pv = None  # type: ignore[assignment]
    _PV_OK = False

from scipy.ndimage import (
    binary_fill_holes, binary_dilation, label, generate_binary_structure
)
from skimage.measure import marching_cubes


# ── Caminho primário: VTK ────────────────────────────────────────────────────

def _inside_vtk(mesh_pv, resolucao: int, bounds) -> np.ndarray:
    if not _PV_OK:
        raise RuntimeError("pyvista não disponível neste ambiente")
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    xs = np.linspace(xmin, xmax, resolucao)
    ys = np.linspace(ymin, ymax, resolucao)
    zs = np.linspace(zmin, zmax, resolucao)
    gx, gy, gz = np.meshgrid(xs, ys, zs, indexing='ij')
    pts_grid = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])
    cloud = pv.PolyData(pts_grid)
    sel = cloud.select_enclosed_points(mesh_pv, tolerance=1e-6, check_surface=False)
    return sel["SelectedPoints"].reshape(resolucao, resolucao, resolucao).astype(bool)


# ── Caminho fallback: rasterização + flood-fill (sem VTK display) ────────────

def _inside_fallback(mesh_pv, resolucao: int, bounds) -> np.ndarray:
    """
    Rasteriza a superfície da malha na grade voxel, fecha com dilation,
    e detecta o interior via flood-fill do exterior (canto = fora).
    Não depende de nenhuma função de renderização do VTK.
    """
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    n = resolucao

    def w2v(p, lo, hi):
        return ((p - lo) / (hi - lo + 1e-9) * (n - 1)).astype(int).clip(0, n - 1)

    pts = mesh_pv.points
    surface = np.zeros((n, n, n), dtype=bool)

    # Marca vértices
    surface[w2v(pts[:, 0], xmin, xmax),
            w2v(pts[:, 1], ymin, ymax),
            w2v(pts[:, 2], zmin, zmax)] = True

    # Marca centróides de faces (melhora densidade da superfície)
    try:
        faces = mesh_pv.faces.reshape(-1, 4)[:, 1:]
        ctr = pts[faces].mean(axis=1)
        surface[w2v(ctr[:, 0], xmin, xmax),
                w2v(ctr[:, 1], ymin, ymax),
                w2v(ctr[:, 2], zmin, zmax)] = True
    except Exception:
        pass

    # Fecha lacunas da casca rasterizada
    struct = generate_binary_structure(3, 1)
    surface_closed = binary_dilation(surface, structure=struct, iterations=2)

    # Flood-fill do exterior: canto (0,0,0) está sempre fora da malha
    labeled, _ = label(~surface_closed, structure=struct)
    exterior_label = labeled[0, 0, 0]
    inside = ~(labeled == exterior_label) & ~surface_closed
    return inside


# ── Função pública ────────────────────────────────────────────────────────────

def preencher_interior(mesh_pv, resolucao: int = 128):
    """
    Recebe uma malha pyvista (casca oca de STL) e retorna uma nova malha
    pyvista SÓLIDA preenchendo o volume interno fechado.

    Parâmetros
    ----------
    mesh_pv   : pv.PolyData — casca de entrada
    resolucao : int — dimensão da grade voxel em cada eixo (padrão 128)

    Retorna
    -------
    pv.PolyData com a malha do preenchimento interno, ou None se o interior
    estiver vazio ou em caso de qualquer erro.
    """
    try:
        bounds = mesh_pv.bounds
        xmin, xmax, ymin, ymax, zmin, zmax = bounds
        xs = np.linspace(xmin, xmax, resolucao)
        ys = np.linspace(ymin, ymax, resolucao)
        zs = np.linspace(zmin, zmax, resolucao)
        dx, dy, dz = xs[1] - xs[0], ys[1] - ys[0], zs[1] - zs[0]

        # Tenta VTK; fallback scipy se qualquer exceção ocorrer
        try:
            inside = _inside_vtk(mesh_pv, resolucao, bounds)
            logging.info("[mesh_fill] caminho VTK OK")
        except Exception as vtk_err:
            logging.warning("[mesh_fill] VTK falhou (%s); usando fallback scipy puro", vtk_err)
            inside = _inside_fallback(mesh_pv, resolucao, bounds)

        inside_filled = binary_fill_holes(inside)
        if not inside_filled.any():
            logging.warning("[mesh_fill] nenhum voxel interno detectado")
            return None

        verts, faces_mc, _, _ = marching_cubes(
            inside_filled.astype(np.float32), level=0.5, spacing=(dx, dy, dz)
        )
        verts[:, 0] += xmin
        verts[:, 1] += ymin
        verts[:, 2] += zmin

        n_f = len(faces_mc)
        cells = np.hstack([np.full((n_f, 1), 3, dtype=np.int64), faces_mc]).ravel()
        celltypes = np.full(n_f, pv.CellType.TRIANGLE, dtype=np.uint8)
        return pv.UnstructuredGrid(cells, celltypes, verts).extract_surface()

    except Exception as e:
        logging.error("[mesh_fill] erro inesperado: %s", e)
        return None


# ── Teste standalone ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    _STL_DIR = os.path.expanduser("~/Desktop/DCUBIC-SITE/MICROTOMO/leve")
    _candidatos = ["molar_sup__raiz_voi_.stl", "Dentina.stl", "Esmalte.stl"]
    _stl_path = next(
        (os.path.join(_STL_DIR, c) for c in _candidatos
         if os.path.isfile(os.path.join(_STL_DIR, c))), None
    )
    if _stl_path is None:
        print("ERRO: nenhum STL encontrado em", _STL_DIR)
        sys.exit(1)

    print(f"STL de entrada : {os.path.basename(_stl_path)}")
    casca = pv.read(_stl_path)
    print(f"Pontos da casca: {casca.n_points}")
    print(f"Faces  da casca: {casca.n_cells}")
    print("Rodando preencher_interior (resolucao=64)...")

    fill = preencher_interior(casca, resolucao=64)
    if fill is None:
        print("RESULTADO: preenchimento VAZIO ou erro.")
    else:
        vol = fill.volume
        print(f"Pontos do preenchimento: {fill.n_points}")
        print(f"Faces  do preenchimento: {fill.n_cells}")
        print(f"Volume > 0: {'SIM' if vol > 0 else 'NÃO'}")
