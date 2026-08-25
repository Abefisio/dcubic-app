"""
DCubic Image System Platform — módulo de anatomia (Requisito 6).

Calcula volumes anatômicos por MORFOLOGIA 3D sobre os voxels brutos (Princípio 1):
  - externo_mm3           : envelope total do dente (sólido preenchido)
  - cavidade_interna_mm3  : câmara pulpar + canais (espaço oco interno)
  - canal_radicular_mm3   : cavidade interna localizada dentro da raiz
  - coroa_mm3 / raiz_mm3  : divididos pelo plano cervical (estimado no "pescoço")
  - solido_dente_mm3      : tecido mineralizado (sem a cavidade)

Todas as medidas são geométricas: nº de voxels × espaçamento³ (mm³).
Nenhuma depende da magnitude de intensidade — apenas da segmentação binária.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi

try:
    from skimage.filters import threshold_otsu
except Exception:  # pragma: no cover
    threshold_otsu = None


def _largest_cc(mask: np.ndarray) -> np.ndarray:
    """Mantém apenas o maior componente conexo (o dente), removendo ruído."""
    lbl, n = ndi.label(mask)
    if n <= 1:
        return mask
    sizes = ndi.sum(np.ones_like(lbl, dtype=np.uint8), lbl, index=range(1, n + 1))
    return lbl == (1 + int(np.argmax(sizes)))


def tooth_mask(volume: np.ndarray, air_thresh: float | None = None):
    """Binariza dente vs ar. air_thresh automático (Otsu) se não informado."""
    v = np.asarray(volume, dtype=np.float32)
    if air_thresh is None:
        if threshold_otsu is not None:
            try:
                air_thresh = float(threshold_otsu(v))
            except Exception:
                air_thresh = 0.15
        else:
            air_thresh = 0.15
    mask = v > air_thresh
    mask = ndi.binary_closing(mask, iterations=1)
    mask = _largest_cc(mask)
    return mask, float(air_thresh)


def _extent(mask: np.ndarray, axis: int) -> int:
    proj = np.any(mask, axis=tuple(i for i in range(3) if i != axis))
    idx = np.where(proj)[0]
    return int(idx.max() - idx.min() + 1) if idx.size else 0


def _long_axis(mask: np.ndarray, spacing) -> int:
    """Eixo de maior extensão física (comprimento do dente)."""
    return int(np.argmax([_extent(mask, ax) * float(spacing[ax]) for ax in range(3)]))


def _area_profile(mask: np.ndarray, axis: int) -> np.ndarray:
    """Área (nº de voxels) por fatia ao longo de `axis`."""
    other = tuple(i for i in range(3) if i != axis)
    return mask.sum(axis=other).astype(float)


def compute_anatomy(volume, spacing, *, air_thresh=None, long_axis=None,
                    crown_at_high=None, cervical_index=None, cervical_frac=None) -> dict:
    v = np.asarray(volume, dtype=np.float32)
    voxvol = float(spacing[0]) * float(spacing[1]) * float(spacing[2])

    mask, air_thresh = tooth_mask(v, air_thresh)          # tecido mineralizado
    filled = ndi.binary_fill_holes(mask)                  # envelope sólido
    cavity = filled & (~mask)                             # câmara pulpar + canais

    if long_axis is None:
        long_axis = _long_axis(filled, spacing)

    area = _area_profile(filled, long_axis)
    L = int(area.shape[0])

    # Qual extremo é a coroa? (coroa costuma ser mais volumosa que o ápice da raiz)
    if crown_at_high is None:
        band = max(1, L // 5)
        crown_at_high = float(area[-band:].mean()) >= float(area[:band].mean())

    # Plano cervical: fração explícita do eixo, ou "pescoço" (mínima área central)
    if cervical_index is None and cervical_frac is not None:
        cervical_index = int(round(float(cervical_frac) * (L - 1)))
    if cervical_index is None:
        lo, hi = int(L * 0.30), max(int(L * 0.70), int(L * 0.30) + 1)
        seg = area[lo:hi]
        if seg.size:
            cervical_index = lo + int(np.argmin(np.where(seg > 0, seg, np.inf)))
        else:
            cervical_index = L // 2

    shape_idx = [(-1 if i == long_axis else 1) for i in range(3)]
    idx = np.arange(L).reshape(shape_idx)
    if crown_at_high:
        crown_sel = idx >= cervical_index
        root_sel = idx < cervical_index
    else:
        crown_sel = idx <= cervical_index
        root_sel = idx > cervical_index

    def mm3(m) -> float:
        return round(float(np.count_nonzero(m)) * voxvol, 6)

    return {
        "air_thresh": round(float(air_thresh), 4),
        "long_axis": int(long_axis),
        "crown_at_high": bool(crown_at_high),
        "cervical_index": int(cervical_index),
        "voxel_mm3": round(voxvol, 9),
        "externo_mm3": mm3(filled),
        "solido_dente_mm3": mm3(mask),
        "cavidade_interna_mm3": mm3(cavity),
        "canal_radicular_mm3": mm3(cavity & root_sel),
        "camara_coroa_mm3": mm3(cavity & crown_sel),
        "coroa_mm3": mm3(filled & crown_sel),
        "raiz_mm3": mm3(filled & root_sel),
    }
