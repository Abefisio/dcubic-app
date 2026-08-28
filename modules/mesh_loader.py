"""
DCubic — carregador de malhas STL via pyvista.
Usado para arquivos exportados pelo Bruker microCT CTAnalyser.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def load_mesh(
    data: bytes,
    name: str,
    *,
    decimate_target: int | None = 200_000,
    cache_key: str | None = None,
) -> dict:
    """Carrega um STL a partir de bytes e retorna métricas da malha.

    Se cache_key for fornecido (caminho-base sem extensão), salva/lê um cache
    de disco: <cache_key>.dcubic_cache.ply (malha decimada) e
    <cache_key>.dcubic_cache.json (métricas). O cache é considerado válido
    enquanto for mais novo que o STL original (mtime via data — não disponível
    aqui, então validade é verificada pelo chamador passando cache_key apenas
    quando o arquivo mudou, ex.: chave (path,mtime) no cache do Streamlit).
    """
    import pyvista as pv

    stem = Path(name).stem
    _ply = f"{cache_key}.dcubic_cache.ply" if cache_key else None
    _jsn = f"{cache_key}.dcubic_cache.json" if cache_key else None

    # a) tentar ler cache de disco
    if _ply and _jsn and os.path.isfile(_ply) and os.path.isfile(_jsn):
        try:
            mesh_display = pv.read(_ply)
            with open(_jsn, "r", encoding="utf-8") as _jf:
                _m = json.load(_jf)
            return {
                "mesh":            mesh_display,
                "name":            stem,
                "volume_native":   _m["volume_native"],
                "area_native":     _m["area_native"],
                "n_points":        _m["n_points"],
                "n_faces":         _m["n_faces"],
                "n_faces_display": _m["n_faces_display"],
                "bounds":          tuple(_m["bounds"]),
            }
        except Exception:
            pass  # cache corrompido → processa normalmente

    # b) ler e triangular STL
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

    # c) medir na malha ORIGINAL
    try:
        vol = abs(float(tri.volume))
    except Exception:
        vol = 0.0

    n_faces_original = int(tri.n_cells)
    area_original = float(tri.area)
    bounds_original = tuple(float(b) for b in tri.bounds)
    n_points_original = int(tri.n_points)

    # d) gerar malha de exibição (decimada)
    if decimate_target is not None and tri.n_cells > decimate_target:
        ratio = 1.0 - (decimate_target / tri.n_cells)
        mesh_display = tri.decimate_pro(ratio, preserve_topology=True)
    else:
        mesh_display = tri

    # e) gravar cache em disco
    if _ply and _jsn:
        try:
            mesh_display.save(_ply)
            with open(_jsn, "w", encoding="utf-8") as _jf:
                json.dump({
                    "volume_native":   vol,
                    "area_native":     area_original,
                    "n_points":        n_points_original,
                    "n_faces":         n_faces_original,
                    "n_faces_display": int(mesh_display.n_cells),
                    "bounds":          list(bounds_original),
                }, _jf)
        except Exception:
            pass  # falha ao gravar cache não interrompe o fluxo

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


def load_meshes(files: list, *, cache_keys: list | None = None) -> list:
    """Carrega vários STL a partir de uma lista de (name, bytes).

    cache_keys: lista paralela de cache_key (str ou None) para cada arquivo.
    Arquivos inválidos são registrados com chave 'error' e não interrompem os demais.
    """
    results = []
    for i, (name, data) in enumerate(files):
        ck = cache_keys[i] if cache_keys and i < len(cache_keys) else None
        try:
            results.append(load_mesh(data, name, cache_key=ck))
        except Exception as exc:
            results.append({"name": Path(name).stem, "error": str(exc)})
    return results
