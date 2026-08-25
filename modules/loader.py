"""
DCubic Image System Platform — carregador universal de volumes.

Princípio fundamental: este módulo NUNCA altera os dados brutos.
A matriz numpy retornada em 'volume' é sempre float32 com valores preservados
do arquivo original. Toda configuração visual (paleta, brilho, threshold)
acontece nas camadas de exibição, nunca aqui.
"""

from __future__ import annotations  # habilita X | Y no Python 3.9
from pathlib import Path
import numpy as np


# ---------------------------------------------------------------------------
# Carregadores por formato
# ---------------------------------------------------------------------------

def _load_dicom(path: Path) -> dict:
    import pydicom

    files = sorted(path.glob("*.dcm"))
    if not files:
        raise ValueError(f"Nenhum arquivo .dcm encontrado em {path}")

    slices = [pydicom.dcmread(str(f)) for f in files]
    slices.sort(key=lambda s: float(s.ImagePositionPatient[2]))

    volume = np.stack([s.pixel_array for s in slices]).astype(np.float32)

    ds = slices[0]
    ps = ds.PixelSpacing
    spacing_z = float(ds.SliceThickness) if hasattr(ds, "SliceThickness") else 1.0

    return {
        "volume": volume,
        "spacing": (spacing_z, float(ps[0]), float(ps[1])),  # (z, y, x) em mm
        "source": "DICOM",
        "shape": volume.shape,
        "dtype_original": str(slices[0].pixel_array.dtype),
    }


def _load_tiff_stack(path: Path) -> dict:
    import tifffile

    files = sorted(path.glob("*.tif")) + sorted(path.glob("*.tiff"))
    if not files:
        raise ValueError(f"Nenhum arquivo TIFF encontrado em {path}")

    volume = np.stack([tifffile.imread(str(f)) for f in files]).astype(np.float32)

    return {
        "volume": volume,
        "spacing": (1.0, 1.0, 1.0),  # desconhecido sem metadados externos
        "source": "TIFF stack",
        "shape": volume.shape,
        "dtype_original": "uint16",
        "warning": (
            "Espaçamento de voxel não disponível em TIFF sem metadados. "
            "Defina manualmente via interface (µm por voxel)."
        ),
    }


def _load_nifti(path: Path) -> dict:
    import nibabel as nib

    img = nib.load(str(path))
    volume = np.asarray(img.dataobj, dtype=np.float32)
    if volume.ndim == 4:
        volume = volume[..., 0]  # primeiro volume se 4D

    zooms = img.header.get_zooms()
    spacing = (
        (float(zooms[2]), float(zooms[1]), float(zooms[0]))
        if len(zooms) >= 3
        else (1.0, 1.0, 1.0)
    )

    return {
        "volume": volume,
        "spacing": spacing,  # (z, y, x) em mm
        "source": "NIfTI",
        "shape": volume.shape,
        "dtype_original": str(img.get_data_dtype()),
    }


def _load_synthetic_phantom() -> dict:
    """
    Volume fantasma gerado em memória — sem downloads, sem rede.

    Simula contraste de micro-CT dental com três regiões:
      - Fundo (ar):      ~0.0
      - Tecido mole:     ~0.3  (dentina/polpa)
      - Esmalte/osso:    ~0.8
      - Núcleo denso:    ~1.0  (câmara hipermineralizada simulada)

    Shape: (64, 128, 128), espaçamento simulado 20 µm/voxel.

    AVISO: usado APENAS para validação técnica do pipeline.
    Substituir por arquivo real de micro-CT assim que disponível.
    """
    shape = (64, 128, 128)
    center = (shape[0] / 2, shape[1] / 2, shape[2] / 2)

    z, y, x = np.ogrid[: shape[0], : shape[1], : shape[2]]
    dist = np.sqrt(
        ((z - center[0]) / (shape[0] / 2)) ** 2
        + ((y - center[1]) / (shape[1] / 2)) ** 2
        + ((x - center[2]) / (shape[2] / 2)) ** 2
    )

    volume = np.zeros(shape, dtype=np.float32)
    volume[dist < 1.0] = 0.3   # tecido mole (dentina/polpa)
    volume[dist < 0.7] = 0.8   # esmalte/osso
    volume[dist < 0.3] = 1.0   # núcleo denso

    # ponytail: ruído gaussiano leve para simular textura real de micro-CT
    rng = np.random.default_rng(seed=42)
    volume += rng.normal(0, 0.02, shape).astype(np.float32)
    volume = np.clip(volume, 0.0, 1.0)

    return {
        "volume": volume,
        "spacing": (0.020, 0.020, 0.020),  # 20 µm/voxel simulado
        "source": "synthetic:phantom",
        "shape": volume.shape,
        "dtype_original": "float32",
        "warning": (
            "DATASET SINTÉTICO — volume fantasma gerado em memória, NÃO é micro-CT real. "
            "Usado apenas para validação técnica do pipeline. "
            "Substituir por arquivo real de micro-CT assim que disponível."
        ),
    }


# ---------------------------------------------------------------------------
# Normalização de intensidade (aceita micro-CT em qualquer escala: uint16/HU)
# ---------------------------------------------------------------------------
def _to_display01(vol):
    """Normaliza para [0,1] apenas para exibição/segmentação.

    - Se o volume já está em [0,1] (ex.: phantom sintético), NÃO altera.
    - Caso contrário, aplica janela robusta por percentis (P0.5–P99.5),
      ignorando outliers extremos comuns em micro-CT.
    Retorna (volume_norm float32, (lo, hi), foi_normalizado).
    """
    v = vol.astype(np.float32, copy=False)
    vmin = float(np.nanmin(v))
    vmax = float(np.nanmax(v))
    if vmin >= -0.01 and vmax <= 1.01:
        return v, (vmin, vmax), False
    lo, hi = np.percentile(v, [0.5, 99.5])
    lo = float(lo); hi = float(hi)
    if hi <= lo:
        hi = lo + 1.0
    out = np.clip((v - lo) / (hi - lo), 0.0, 1.0).astype(np.float32)
    return out, (lo, hi), True


def _finalize(d):
    """Pós-processa o dict do loader: normaliza intensidade p/ [0,1] e anota metadados.

    Princípio 1: as métricas (volume, área, distância) são geométricas
    (contagem de voxels × espaçamento³, malha, espaçamento) e NÃO dependem
    da magnitude de intensidade — logo, a normalização não afeta os números.
    """
    norm, (lo, hi), was = _to_display01(d["volume"])
    d["volume"] = norm
    d["intensity_window"] = (round(lo, 6), round(hi, 6))
    d["normalized"] = bool(was)
    if was:
        _msg = ("Intensidades normalizadas para [0,1] (janela robusta P0.5-P99.5) "
                "apenas para exibicao e thresholds; metricas geometricas nao sao afetadas.")
        d["warning"] = (d.get("warning", "") + " " + _msg).strip()
    return d


# ---------------------------------------------------------------------------
# Ponto de entrada único
# ---------------------------------------------------------------------------

def load_volume(path: str | None = None, *, synthetic: bool = False) -> dict:
    """
    Carregador universal de volumes 3D.

    Args:
        path: caminho para pasta DICOM, pasta TIFF, arquivo .nii ou .nii.gz.
        synthetic: se True, ignora `path` e carrega o phantom sintético para validação técnica.

    Returns:
        dict com:
            volume         – np.ndarray float32 (Z, Y, X), dados brutos preservados
            spacing        – tuple (z, y, x) em mm (ou µm para sintético)
            source         – string identificando a origem
            shape          – tuple com dimensões
            dtype_original – dtype antes da conversão para float32
            warning        – (opcional) aviso sobre limitações do dataset
    """
    if synthetic:
        return _finalize(_load_synthetic_phantom())

    if path is None:
        raise ValueError("Forneça 'path' ou use synthetic=True.")

    p = Path(path)

    if p.is_dir():
        if any(p.glob("*.dcm")):
            return _finalize(_load_dicom(p))
        if any(p.glob("*.tif")) or any(p.glob("*.tiff")):
            return _finalize(_load_tiff_stack(p))
        raise ValueError(
            f"Pasta {p} não contém arquivos .dcm ou .tif/.tiff reconhecidos."
        )

    if p.suffix == ".nii" or str(p).endswith(".nii.gz"):
        return _finalize(_load_nifti(p))

    raise ValueError(
        f"Formato não reconhecido: {p}. "
        "Forneça pasta DICOM, pasta TIFF, .nii ou .nii.gz"
    )
