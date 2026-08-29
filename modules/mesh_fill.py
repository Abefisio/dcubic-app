"""
mesh_fill.py — gera malha sólida preenchendo o interior de uma casca STL oca.

Único caminho: rasterização + flood-fill (scipy puro, sem VTK para a grade).
  grade de voxels (booleana) → dilation fecha casca → label/flood exterior
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
    logging.warning("[mesh_fill] pyvista indisponível: %s", _pv_import_err)
    pv = None  # type: ignore[assignment]
    _PV_OK = False

from scipy.ndimage import (
    binary_fill_holes, binary_dilation, label, generate_binary_structure
)
from skimage.measure import marching_cubes


# ── Único caminho: rasterização + flood-fill (scipy puro) ────────────────────

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

def preencher_interior(mesh_pv, resolucao: int = 48):
    """
    Recebe uma malha pyvista (casca oca de STL) e retorna uma nova malha
    pyvista SÓLIDA preenchendo o volume interno fechado.

    Parâmetros
    ----------
    mesh_pv   : pv.PolyData — casca de entrada
    resolucao : int — dimensão da grade voxel em cada eixo (padrão 48)

    Retorna
    -------
    pv.PolyData com a malha do preenchimento interno, ou None se o interior
    estiver vazio ou em caso de qualquer erro.

    Levanta
    -------
    ValueError se resolucao³ × 8 bytes > 200 MB (proteção contra OOM no Cloud).
    """
    # Guard de memória: grade booleana cabe em 1 byte/voxel, mas marching_cubes
    # converte para float32 internamente — usa 8 bytes como margem conservadora.
    mem_bytes = resolucao ** 3 * 8
    if mem_bytes > 200_000_000:
        raise ValueError(
            f"resolucao={resolucao} exigiria ~{mem_bytes // 1_000_000} MB "
            f"(limite: 200 MB). Reduza a resolução."
        )

    try:
        bounds = mesh_pv.bounds
        xmin, xmax, ymin, ymax, zmin, zmax = bounds
        xs = np.linspace(xmin, xmax, resolucao)
        ys = np.linspace(ymin, ymax, resolucao)
        zs = np.linspace(zmin, zmax, resolucao)
        dx, dy, dz = xs[1] - xs[0], ys[1] - ys[0], zs[1] - zs[0]

        inside = _inside_fallback(mesh_pv, resolucao, bounds)
        logging.info("[mesh_fill] fallback scipy OK")

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

    except ValueError:
        raise  # propaga o guard de memória
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
    print("Rodando preencher_interior (resolucao=48)...")

    fill = preencher_interior(casca, resolucao=48)
    if fill is None:
        print("RESULTADO: preenchimento VAZIO ou erro.")
    else:
        vol = fill.volume
        print(f"Pontos do preenchimento: {fill.n_points}")
        print(f"Faces  do preenchimento: {fill.n_cells}")
        print(f"Volume > 0: {'SIM' if vol > 0 else 'NÃO'}")
