"""
Reduz um STL grande para caber dentro de um tamanho-alvo em MB,
usando busca binária sobre a taxa de decimação para maximizar a qualidade.

Uso:
    python3 reduzir_stl.py <arquivo.stl> [alvo_mb]

    alvo_mb  — tamanho-alvo do arquivo de saída em MB (padrão: 80)

Salva o resultado como <nome_original>_reduzido.stl na mesma pasta do original.
Nunca sobrescreve o arquivo original.
"""
import os
import sys
import tempfile

os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")

import pyvista as pv


def _tamanho_stl(mesh) -> int:
    """Serializa em memória e retorna o tamanho em bytes do STL binário resultante."""
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        mesh.save(tmp_path, binary=True)
        return os.path.getsize(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def reduzir(src: str, alvo_mb: float = 80.0) -> None:
    src = os.path.abspath(src)
    nome = os.path.basename(src)
    tamanho_orig = os.path.getsize(src)
    alvo_bytes = int(alvo_mb * 1024 * 1024)
    tolerancia = 0.05  # ±5 %

    mesh = pv.read(src)
    if mesh.n_points == 0:
        raise ValueError(f"Malha vazia: {src}")
    mesh = mesh.triangulate()

    n_orig = int(mesh.n_cells)
    print(f"\nOriginal : {nome}")
    print(f"  Faces  : {n_orig:>12,}")
    print(f"  Tam    : {tamanho_orig / 1024**2:>10.1f} MB")

    if tamanho_orig <= alvo_bytes:
        print(f"\nArquivo já está dentro do limite de {alvo_mb:.0f} MB — nenhuma decimação necessária.")
        return

    # Busca binária sobre reduction (fração de faces REMOVIDAS, 0..1)
    # Quanto maior o reduction, mais agressiva a decimação.
    lo, hi = 0.0, 0.99
    melhor_mesh = None
    melhor_reduction = None
    melhor_tam = None

    print(f"\nBusca binária (alvo ≤ {alvo_mb:.0f} MB, tolerância ±{tolerancia*100:.0f}%):")

    for iteracao in range(12):
        reduction = (lo + hi) / 2.0
        try:
            candidato = mesh.decimate_pro(reduction, preserve_topology=True)
        except Exception as exc:
            print(f"  iter {iteracao+1:2d}  reduction={reduction:.4f}  ERRO: {exc}")
            lo = reduction
            continue

        tam = _tamanho_stl(candidato)
        dentro = tam <= alvo_bytes
        tam_mb = tam / 1024**2
        print(f"  iter {iteracao+1:2d}  reduction={reduction:.4f}  faces={int(candidato.n_cells):>10,}  tam={tam_mb:>7.1f} MB  {'✓' if dentro else '✗'}")

        if dentro:
            # Está dentro do alvo — guarda e tenta qualidade maior (reduction menor)
            melhor_mesh = candidato
            melhor_reduction = reduction
            melhor_tam = tam
            hi = reduction
            # Convergiu se a diferença está na tolerância
            if tam >= alvo_bytes * (1 - tolerancia):
                break
        else:
            # Ainda grande — precisa de mais decimação
            lo = reduction

        if hi - lo < 1e-4:
            break

    if melhor_mesh is None:
        print("\nNão foi possível atingir o tamanho-alvo nem com decimação máxima.")
        sys.exit(1)

    # Salva resultado
    raiz, _ = os.path.splitext(src)
    dest = raiz + "_reduzido.stl"
    melhor_mesh.save(dest, binary=True)

    n_final = int(melhor_mesh.n_cells)
    tam_final = os.path.getsize(dest)
    reducao_faces = (1 - n_final / n_orig) * 100
    reducao_tam   = (1 - tam_final / tamanho_orig) * 100

    print(f"""
┌──────────────────────────────────────────────────────────┐
│  RESULTADO                                               │
├──────────────────────┬───────────────┬───────────────────┤
│                      │   Original    │    Reduzido       │
├──────────────────────┼───────────────┼───────────────────┤
│ Arquivo              │ {nome[:13]:<13s} │ {os.path.basename(dest)[:17]:<17s} │
│ Tamanho              │ {tamanho_orig/1024**2:>10.1f} MB  │ {tam_final/1024**2:>12.1f} MB    │
│ Faces                │ {n_orig:>13,} │ {n_final:>17,} │
│ Taxa de decimação    │               │ {melhor_reduction*100:>14.1f} %   │
│ Redução de faces     │               │ {reducao_faces:>14.1f} %   │
│ Redução de tamanho   │               │ {reducao_tam:>14.1f} %   │
└──────────────────────┴───────────────┴───────────────────┘
Salvo em: {dest}
""")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 reduzir_stl.py <arquivo.stl> [alvo_mb]")
        sys.exit(1)
    alvo = float(sys.argv[2]) if len(sys.argv) > 2 else 80.0
    reduzir(sys.argv[1], alvo)
