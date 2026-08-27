"""
DCubic — carregador de malhas STL via pyvista.
Usado para arquivos exportados pelo Bruker microCT CTAnalyser.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def load_mesh(data: bytes, name: str, *, decimate_target: int | None = 200_000) -> dict:
    """Carrega um STL a partir de bytes e retorna métricas da malha.

    Args:
        data:             conteúdo binário do arquivo STL.
        name:             nome original do arquivo (ex.: "Esmalte.stl").
        decimate_target:  número-alvo de faces para a malha de exibição 3D.
                          None = não decimar (retorna a malha completa).

    Returns:
        dict com:
            mesh             – pyvista.PolyData de EXIBIÇÃO (decimada se aplicável)
            name             – stem do arquivo original
            volume_native    – volume medido na malha ORIGINAL, antes de decimar
            area_native      – área medida na malha ORIGINAL, antes de decimar
            n_points         – pontos da malha original
            n_faces          – faces da malha ORIGINAL (base para as métricas)
            n_faces_display  – faces da malha de exibição após decimação
            bounds           – (xmin,xmax,ymin,ymax,zmin,zmax) da original

    Nota: volume_native e area_native estão nas unidades de coordenada do
    próprio STL (tipicamente voxels do Bruker CTAnalyser). A conversão para
    mm³/mm² físicos exige o tamanho do voxel (pixel size, em µm) do log de
    reconstrução do scan — aplicada em etapa posterior, nunca assumida.
    A decimação afeta apenas a chave "mesh" (exibição) e nunca as métricas.
    """
    import pyvista as pv

    stem = Path(name).stem

    # a) ler e triangular
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".stl", prefix="dcubic_mesh_")
    try:
        os.write(tmp_fd, data)
        os.close(tmp_fd)
        try:
            mesh = pv.read(tmp_path)
        except Exception as exc:
            raise ValueError(f"Não foi possível ler '{name}' como malha STL: {exc}") from exc
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if mesh.n_points == 0:
        raise ValueError(f"Malha '{name}' está vazia (0 pontos).")

    tri = mesh.triangulate()

    # b) medir na malha ORIGINAL
    try:
        vol = abs(float(tri.volume))  # abs: normais invertidas geram volume negativo
    except Exception:
        vol = 0.0

    n_faces_original = int(tri.n_cells)
    area_original = float(tri.area)
    bounds_original = tuple(float(b) for b in tri.bounds)
    n_points_original = int(tri.n_points)

    # c) gerar malha de exibição (decimada)
    if decimate_target is not None and tri.n_cells > decimate_target:
        ratio = 1.0 - (decimate_target / tri.n_cells)
        mesh_display = tri.decimate(ratio)
    else:
        mesh_display = tri

    # d) retornar
    return {
        "mesh":            mesh_display,
        "name":            stem,
        "volume_native":   vol,
        "area_native":     area_original,
        "n_points":        n_points_original,
        "n_faces":         n_faces_original,
        "n_faces_display": int(mesh_display.n_cells),
        "bounds":          bounds_original,
    }


def load_meshes(files: list) -> list:
    """Carrega vários STL a partir de uma lista de (name, bytes).

    Arquivos inválidos são registrados com chave 'error' e não interrompem os demais.
    """
    results = []
    for name, data in files:
        try:
            results.append(load_mesh(data, name))
        except Exception as exc:
            results.append({"name": Path(name).stem, "error": str(exc)})
    return results
