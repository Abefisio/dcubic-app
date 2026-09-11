"""
DCubic Image System Platform — render 3D via marching cubes + Plotly Mesh3d.

PyVista é usado APENAS para geração de malha e exportação (STL/OBJ no Bloco 5).
A visualização 3D interativa usa Plotly Mesh3d (WebGL client-side) — sem
dependência de VTK em runtime, funciona em qualquer ambiente.

Princípio 1 (inviolável): as malhas são geradas a partir dos masks de voxels
brutos. O render não altera os dados nem os masks. Métricas de volume/área
(Bloco 5) usam os masks direto, nunca as malhas renderizadas.
"""

from __future__ import annotations
import os
os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")
import numpy as np
import plotly.graph_objects as go
from skimage.measure import marching_cubes


def build_mesh(
    mask: np.ndarray,
    spacing: tuple[float, float, float],
    step_size: int = 1,
) -> pv.PolyData | None:
    """
    Gera malha 3D (marching cubes) a partir de um mask booleano.
    Coordenadas em mm (spacing aplicado).

    Args:
        mask:      bool (Z, Y, X) — máscara de voxels do tecido
        spacing:   (z_mm, y_mm, x_mm) — espaçamento real
        step_size: passo de subsampling (1=full, 2=metade, etc.)

    Returns:
        pv.PolyData triangulado em mm, ou None se mask vazio
    """
    if not mask.any():
        return None

    import pyvista as pv
    verts, faces, normals, _ = marching_cubes(
        mask, level=0.5, spacing=spacing, step_size=step_size
    )
    # ponytail: verts[:,0]=Z, verts[:,1]=Y, verts[:,2]=X (ordem de spacing)

    pv_faces = np.hstack([np.full((len(faces), 1), 3, dtype=np.int_), faces])
    mesh = pv.PolyData(verts, pv_faces)
    mesh["normals"] = normals
    return mesh


def build_all_meshes(
    masks: dict[str, np.ndarray],
    spacing: tuple[float, float, float],
    exclude: set[str] | None = None,
) -> dict[str, pv.PolyData | None]:
    """Gera malhas para todos os tecidos exceto os em `exclude`."""
    _exclude = exclude or set()
    return {
        name: build_mesh(mask, spacing)
        for name, mask in masks.items()
        if name not in _exclude
    }


def create_plotly_3d(
    meshes: dict[str, pv.PolyData | None],
    tissue_colors: dict[str, tuple[int, int, int]],
    opacities: dict[str, float] | None = None,
    clip_z_mm: float | None = None,
    clip_plane: dict | None = None,
    bbox_meshes: dict[str, pv.PolyData | None] | None = None,
) -> go.Figure:
    """
    Cria figura Plotly 3D com todas as malhas de tecidos (WebGL — sem VTK em runtime).

    Mapeamento de eixos (marching_cubes com spacing=(z,y,x)):
      mesh.points[:,0] = Z  →  Plotly z
      mesh.points[:,1] = Y  →  Plotly y
      mesh.points[:,2] = X  →  Plotly x

    bbox_meshes: conjunto COMPLETO de malhas (incluindo as não visíveis) usado
    exclusivamente para calcular o bounding box estável da cena. Se None, usa meshes.
    """
    _op = opacities or {}
    fig = go.Figure()

    # Resolve clip: clip_plane tem precedência; clip_z_mm é alias legado para eixo Z
    _clip_axis: int | None = None
    _clip_val: float | None = None
    if clip_z_mm is not None:
        _clip_axis, _clip_val = 0, clip_z_mm
    if clip_plane is not None:
        _clip_axis, _clip_val = clip_plane["axis"], clip_plane["value"]

    # Bounding box global — calculado uma única vez a partir de TODAS as malhas
    _bbox_src = bbox_meshes if bbox_meshes is not None else meshes
    _all_pts = [m.points for m in _bbox_src.values() if m is not None and len(m.points)]
    if _all_pts:
        _pts_cat = np.concatenate(_all_pts, axis=0)
        # col2→plotly_x, col1→plotly_y, col0→plotly_z
        _xr = [float(_pts_cat[:, 2].min()), float(_pts_cat[:, 2].max())]
        _yr = [float(_pts_cat[:, 1].min()), float(_pts_cat[:, 1].max())]
        _zr = [float(_pts_cat[:, 0].min()), float(_pts_cat[:, 0].max())]
        _xe, _ye, _ze = _xr[1]-_xr[0], _yr[1]-_yr[0], _zr[1]-_zr[0]
        _me = max(_xe, _ye, _ze, 1e-6)
        _aspect = dict(x=_xe/_me, y=_ye/_me, z=_ze/_me)
    else:
        _xr = _yr = _zr = [0, 1]
        _aspect = dict(x=1, y=1, z=1)

    for name, mesh in meshes.items():
        if mesh is None:
            continue

        pts = mesh.points                              # (N, 3): col0=Z, col1=Y, col2=X
        fcs = mesh.faces.reshape(-1, 4)[:, 1:]        # (M, 3): índices de face

        if _clip_axis is not None:
            keep = pts[:, _clip_axis][fcs].max(axis=1) <= _clip_val
            fcs = fcs[keep]
            if len(fcs) == 0:
                continue

        r, g, b = tissue_colors.get(name, (200, 200, 200))
        op = _op.get(name, 1.0)

        if op <= 0.01:   # skip em vez de opacity=0 — evita artefato WebGL
            continue

        fig.add_trace(go.Mesh3d(
            x=pts[:, 2],         # X anatômico
            y=pts[:, 1],         # Y anatômico
            z=pts[:, 0],         # Z anatômico
            i=fcs[:, 0],
            j=fcs[:, 1],
            k=fcs[:, 2],
            color=f"#{r:02x}{g:02x}{b:02x}",
            opacity=op,
            name=name,
            showlegend=True,
            lighting=dict(
                ambient=0.4, diffuse=0.8, specular=0.3,
                roughness=0.5, fresnel=0.2,
            ),
            lightposition=dict(x=100, y=100, z=200),
        ))

    fig.update_layout(
        uirevision="constant",  # preserva câmera/zoom/rotação entre reruns do Streamlit
        scene=dict(
            xaxis=dict(title="X (mm)", backgroundcolor="rgb(10,10,10)", gridcolor="rgb(40,40,40)", range=_xr),
            yaxis=dict(title="Y (mm)", backgroundcolor="rgb(10,10,10)", gridcolor="rgb(40,40,40)", range=_yr),
            zaxis=dict(title="Z (mm)", backgroundcolor="rgb(10,10,10)", gridcolor="rgb(40,40,40)", range=_zr),
            bgcolor="rgb(15,15,15)",
            aspectmode="manual",
            aspectratio=_aspect,
        ),
        paper_bgcolor="rgb(15,15,15)",
        font=dict(color="white"),
        legend=dict(bgcolor="rgba(30,30,30,0.8)", bordercolor="gray", borderwidth=1),
        height=520,
        margin=dict(l=0, r=0, t=10, b=0),
    )
    return fig
