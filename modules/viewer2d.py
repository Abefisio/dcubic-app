"""
DCubic Image System Platform — visualização 2D triplanar.

Os dados exibidos são sempre os voxels brutos do volume (Princípio 1).
O crosshair mostra a interseção dos três planos de corte.
"""

from __future__ import annotations
import numpy as np
import plotly.graph_objects as go
from modules.segmentation import overlay_slice


def _make_slice_fig(
    data: np.ndarray,
    title: str,
    crosshair_row: int,
    crosshair_col: int,
    vmin: float,
    vmax: float,
) -> go.Figure:
    """Heatmap em tons de cinza com crosshair ciano para um plano de corte."""
    fig = go.Figure(
        go.Heatmap(
            z=data,
            colorscale="gray",
            zmin=vmin,
            zmax=vmax,
            showscale=False,
            hovertemplate="linha %{y} · col %{x}<br>valor: %{z:.4f}<extra></extra>",
        )
    )

    rows, cols = data.shape

    fig.add_shape(
        type="line",
        x0=0, x1=cols - 1,
        y0=crosshair_row, y1=crosshair_row,
        line=dict(color="cyan", width=1, dash="dash"),
    )
    fig.add_shape(
        type="line",
        x0=crosshair_col, x1=crosshair_col,
        y0=0, y1=rows - 1,
        line=dict(color="cyan", width=1, dash="dash"),
    )

    fig.update_layout(
        title=dict(text=title, font=dict(size=12)),
        margin=dict(l=10, r=10, t=32, b=10),
        height=300,
        yaxis=dict(scaleanchor="x", autorange="reversed"),
    )
    return fig


def render_triplanar(
    volume: np.ndarray,
    z_idx: int,
    y_idx: int,
    x_idx: int,
) -> tuple[go.Figure, go.Figure, go.Figure]:
    """
    Gera os três cortes ortogonais de um volume 3D (Z, Y, X).

    Orientações:
      - Axial   (Z fixo) → plano Y×X  · crosshair em (y_idx, x_idx)
      - Sagital (X fixo) → plano Z×Y  · crosshair em (z_idx, y_idx)
      - Coronal (Y fixo) → plano Z×X  · crosshair em (z_idx, x_idx)

    Os voxels exibidos são sempre os dados brutos (Princípio 1).
    O vmin/vmax global garante escala consistente entre os três planos.

    Returns:
        (fig_axial, fig_sagital, fig_coronal)
    """
    vmin = float(volume.min())
    vmax = float(volume.max())

    axial   = volume[z_idx, :, :]   # (Y, X)
    sagital = volume[:, :, x_idx]   # (Z, Y)
    coronal = volume[:, y_idx, :]   # (Z, X)

    fig_ax  = _make_slice_fig(axial,   f"Axial   Z={z_idx}",  crosshair_row=y_idx, crosshair_col=x_idx, vmin=vmin, vmax=vmax)
    fig_sag = _make_slice_fig(sagital, f"Sagital X={x_idx}", crosshair_row=z_idx, crosshair_col=y_idx, vmin=vmin, vmax=vmax)
    fig_cor = _make_slice_fig(coronal, f"Coronal Y={y_idx}", crosshair_row=z_idx, crosshair_col=x_idx, vmin=vmin, vmax=vmax)

    return fig_ax, fig_sag, fig_cor


def make_overlay_fig(
    gray_slice: np.ndarray,
    mask_slices: dict[str, np.ndarray],
    tissue_colors: dict[str, tuple[int, int, int]],
    title: str,
    crosshair_row: int,
    crosshair_col: int,
) -> go.Figure:
    """
    Figura Plotly com corte 2D em tons de cinza + overlay colorido de tecidos + crosshair.

    Os dados brutos não são alterados — o RGBA é gerado apenas para exibição (Princípio 1).
    """
    rgba = overlay_slice(gray_slice, mask_slices, tissue_colors)
    H, W = gray_slice.shape

    fig = go.Figure(go.Image(z=rgba))

    fig.add_shape(type="line", x0=0, x1=W - 1, y0=crosshair_row, y1=crosshair_row,
                  line=dict(color="cyan", width=1, dash="dash"))
    fig.add_shape(type="line", x0=crosshair_col, x1=crosshair_col, y0=0, y1=H - 1,
                  line=dict(color="cyan", width=1, dash="dash"))

    fig.update_layout(
        title=dict(text=title, font=dict(size=12)),
        margin=dict(l=10, r=10, t=32, b=10),
        height=300,
    )
    fig.update_xaxes(showgrid=False, showticklabels=False)
    fig.update_yaxes(showgrid=False, showticklabels=False, scaleanchor="x")
    return fig
