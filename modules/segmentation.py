"""
DCubic Image System Platform — segmentação por threshold multi-tecido.

Princípio 1 (inviolável): segment_volume opera exclusivamente sobre os
voxels brutos do volume. Os masks retornados são a base para métricas
(Bloco 5) e geração de malha 3D (Bloco 4). Nunca calcular métricas
sobre imagens renderizadas ou sobre a sobreposição visual.
"""

from __future__ import annotations
import numpy as np


# ---------------------------------------------------------------------------
# Constantes de tecido — paleta RGB e thresholds padrão para o phantom
# ---------------------------------------------------------------------------

TISSUE_PALETTE: dict[str, tuple[int, int, int]] = {
    "Fundo":         (80,  80,  80),   # cinza escuro
    "Tecido mole":   (255, 140,  0),   # laranja
    "Esmalte/Osso":  (  0, 200, 255),  # ciano claro
    "Núcleo denso":  (255, 230,  0),   # amarelo
}

# Thresholds padrão calibrados para o phantom sintético (float32 [0, 1])
DEFAULT_THRESHOLDS: dict[str, tuple[float, float]] = {
    "Fundo":         (0.00, 0.12),
    "Tecido mole":   (0.20, 0.50),
    "Esmalte/Osso":  (0.55, 0.88),
    "Núcleo denso":  (0.88, 1.00),
}


# ---------------------------------------------------------------------------
# Segmentação (dados puros — sem plotly, sem streamlit)
# ---------------------------------------------------------------------------

def segment_volume(
    volume: np.ndarray,
    thresholds: dict[str, tuple[float, float]],
) -> dict[str, np.ndarray]:
    """
    Gera uma máscara booleana (Z, Y, X) para cada tecido.

    Opera exclusivamente sobre os voxels brutos (Princípio 1).
    Thresholds definem quais voxels pertencem a cada tecido; as métricas
    finais de volume (mm³) e área (mm²) serão calculadas sobre esses
    masks no Bloco 5 — nunca sobre renders ou imagens compositas.

    Args:
        volume:     np.ndarray float32 (Z, Y, X) — dados brutos
        thresholds: {"tecido": (lo, hi)} — limiar inferior e superior (inclusive)

    Returns:
        {"tecido": np.ndarray bool (Z, Y, X)}
    """
    return {
        name: (volume >= lo) & (volume <= hi)
        for name, (lo, hi) in thresholds.items()
    }


# ---------------------------------------------------------------------------
# Composição visual — overlay RGBA (sem plotly, sem streamlit)
# ---------------------------------------------------------------------------

def overlay_slice(
    gray_slice: np.ndarray,
    mask_slices: dict[str, np.ndarray],
    tissue_colors: dict[str, tuple[int, int, int]],
    alpha: float = 0.45,
) -> np.ndarray:
    """
    Composita um corte 2D em tons de cinza com overlay colorido por tecido.

    Retorna uma imagem RGBA uint8 para exibição — os dados brutos não são
    alterados; este array é apenas para visualização (Princípio 1).

    Args:
        gray_slice:    (H, W) float32 [0, 1] — voxels brutos normalizados
        mask_slices:   {"tecido": (H, W) bool} — máscara 2D por tecido
        tissue_colors: {"tecido": (R, G, B)} — cor 0-255 por tecido
        alpha:         opacidade do overlay (0 = invisível, 1 = sólido)

    Returns:
        RGBA uint8 (H, W, 4) — pronto para go.Image()
    """
    gray8 = np.clip(gray_slice * 255, 0, 255).astype(np.uint8)
    rgba = np.stack([gray8, gray8, gray8, np.full_like(gray8, 255)], axis=-1)

    for name, mask in mask_slices.items():
        if not mask.any() or name not in tissue_colors:
            continue
        r, g, b = tissue_colors[name]
        rgba[mask, 0] = np.clip(rgba[mask, 0] * (1 - alpha) + r * alpha, 0, 255).astype(np.uint8)
        rgba[mask, 1] = np.clip(rgba[mask, 1] * (1 - alpha) + g * alpha, 0, 255).astype(np.uint8)
        rgba[mask, 2] = np.clip(rgba[mask, 2] * (1 - alpha) + b * alpha, 0, 255).astype(np.uint8)

    return rgba
