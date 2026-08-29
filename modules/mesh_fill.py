"""
mesh_fill.py — gera malha sólida preenchendo o interior de uma casca STL oca.

Pipeline:
  1. grade de voxels nos bounds da casca
  2. select_enclosed_points (pyvista) — marca voxels dentro da casca
  3. scipy.ndimage.binary_fill_holes — fecha ilhas abertas / furos
  4. skimage.measure.marching_cubes — isosuperfície do volume binário
  5. retorna pv.PolyData
"""

import numpy as np
import pyvista as pv
from scipy.ndimage import binary_fill_holes
from skimage.measure import marching_cubes


def preencher_interior(mesh_pv: pv.PolyData, resolucao: int = 128) -> pv.PolyData:
    """
    Recebe uma malha pyvista (casca oca de STL) e retorna uma nova malha
    pyvista SÓLIDA preenchendo o volume interno fechado.

    Parâmetros
    ----------
    mesh_pv   : pv.PolyData — casca de entrada (pode ter pequenos furos)
    resolucao : int — dimensão da grade voxel em cada eixo (padrão 128)

    Retorna
    -------
    pv.PolyData com a malha do preenchimento interno, ou None se o interior
    estiver vazio (casca completamente convexa ou sem volume fechado detectável).
    """
    bounds = mesh_pv.bounds          # (xmin,xmax, ymin,ymax, zmin,zmax)
    xmin, xmax, ymin, ymax, zmin, zmax = bounds

    # Grade uniforme de pontos dentro dos bounds
    xs = np.linspace(xmin, xmax, resolucao)
    ys = np.linspace(ymin, ymax, resolucao)
    zs = np.linspace(zmin, zmax, resolucao)
    dx = xs[1] - xs[0]
    dy = ys[1] - ys[0]
    dz = zs[1] - zs[0]

    gx, gy, gz = np.meshgrid(xs, ys, zs, indexing='ij')
    pts_grid = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])

    cloud = pv.PolyData(pts_grid)
    # select_enclosed_points: tolerance baixa para malhas com pequenos furos
    sel = cloud.select_enclosed_points(mesh_pv, tolerance=1e-6, check_surface=False)
    inside = sel["SelectedPoints"].reshape(resolucao, resolucao, resolucao).astype(bool)

    # Fecha ilhas / furos internos (ajuda em malhas não-watertight)
    inside_filled = binary_fill_holes(inside)

    if not inside_filled.any():
        print("[mesh_fill] AVISO: nenhum voxel interno detectado. "
              "Verifique se a casca é watertight e fechada.")
        return None

    interior_ratio = inside_filled.sum() / inside_filled.size
    if interior_ratio < 0.001:
        print(f"[mesh_fill] AVISO: interior muito pequeno ({interior_ratio:.4%}). "
              "A casca pode precisar de reparo (furos grandes).")

    # Marching cubes na grade binária preenchida
    verts, faces, normals, _ = marching_cubes(
        inside_filled.astype(np.float32),
        level=0.5,
        spacing=(dx, dy, dz),
    )

    # Reposiciona vértices para o espaço real (marching_cubes usa índices de grade)
    verts[:, 0] += xmin
    verts[:, 1] += ymin
    verts[:, 2] += zmin

    # Monta pv.PolyData: cada face tem 3 vértices — formato pyvista [3, i, j, k, ...]
    n_faces = len(faces)
    cells = np.hstack([np.full((n_faces, 1), 3, dtype=np.int64), faces]).ravel()
    celltypes = np.full(n_faces, pv.CellType.TRIANGLE, dtype=np.uint8)
    fill_mesh = pv.UnstructuredGrid(cells, celltypes, verts).extract_surface()

    return fill_mesh


# ── Teste standalone ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    import sys

    _STL_DIR = os.path.expanduser("~/Desktop/DCUBIC-SITE/MICROTOMO/leve")
    _candidatos = ["molar_sup__raiz_voi_.stl", "Dentina.stl", "Esmalte.stl"]

    _stl_path = None
    for _c in _candidatos:
        _p = os.path.join(_STL_DIR, _c)
        if os.path.isfile(_p):
            _stl_path = _p
            break

    if _stl_path is None:
        print("ERRO: nenhum STL encontrado em", _STL_DIR)
        sys.exit(1)

    print(f"STL de entrada : {os.path.basename(_stl_path)}")
    casca = pv.read(_stl_path)
    print(f"Pontos da casca: {casca.n_points}")
    print(f"Faces  da casca: {casca.n_cells}")
    print("Rodando preencher_interior (resolucao=64 para teste rápido)...")

    fill = preencher_interior(casca, resolucao=64)

    if fill is None:
        print("RESULTADO: preenchimento VAZIO — casca sem interior detectável.")
    else:
        vol = fill.volume
        print(f"Pontos do preenchimento: {fill.n_points}")
        print(f"Faces  do preenchimento: {fill.n_cells}")
        print(f"Volume do preenchimento: {vol:.4f} unidades nativas³")
        print(f"Volume > 0: {'SIM' if vol > 0 else 'NÃO'}")
