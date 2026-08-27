"""
DCubic — carregador de malhas STL via pyvista.
Usado para arquivos exportados pelo Bruker microCT CTAnalyser.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def load_mesh(data: bytes, name: str) -> dict:
    """Carrega um STL a partir de bytes e retorna métricas da malha.

    Args:
        data: conteúdo binário do arquivo STL.
        name: nome original do arquivo (ex.: "Esmalte.stl").

    Returns:
        dict com:
            mesh          – pyvista.PolyData triangulada
            name          – stem do arquivo original
            volume_native – volume nas unidades de coordenada do próprio STL
            area_native   – área de superfície nas mesmas unidades
            n_points, n_faces, bounds

    Nota: volume_native e area_native estão nas unidades de coordenada do
    próprio STL (tipicamente voxels do Bruker CTAnalyser). A conversão para
    mm³/mm² físicos exige o tamanho do voxel (pixel size, em µm) do log de
    reconstrução do scan — aplicada em etapa posterior, nunca assumida.
    """
    import pyvista as pv

    stem = Path(name).stem

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

    # pyvista.PolyData.volume requer malha fechada; triangula se necessário
    tri = mesh.triangulate()

    try:
        vol = abs(float(tri.volume))  # abs: normais invertidas geram volume negativo
    except Exception:
        vol = 0.0

    return {
        "mesh":           tri,
        "name":           stem,
        "volume_native":  vol,
        "area_native":    float(tri.area),
        "n_points":       int(tri.n_points),
        "n_faces":        int(tri.n_cells),
        "bounds":         tuple(float(b) for b in tri.bounds),
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
