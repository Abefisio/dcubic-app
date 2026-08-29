"""Reduz faces de um STL e salva versão leve em <pasta_origem>/leve/<nome>.stl."""
import os
import sys

import pyvista as pv

os.environ.setdefault("PYVISTA_OFF_SCREEN", "true")


def reduzir(src: str, alvo: int = 200_000) -> None:
    src = os.path.abspath(src)
    nome = os.path.basename(src)
    tamanho_orig = os.path.getsize(src)

    mesh = pv.read(src)
    if mesh.n_points == 0:
        raise ValueError(f"Malha vazia: {src}")
    mesh = mesh.triangulate()

    n_orig = int(mesh.n_cells)
    print(f"ORIGINAL  {nome}: {n_orig:,} faces  |  {tamanho_orig / 1024:.1f} KB")

    if n_orig <= alvo:
        print(f"  → já tem {n_orig:,} faces (≤ {alvo:,}), cópia sem decimação.")
        reduzida = mesh
    else:
        def _decimate_pass(m, target):
            n = int(m.n_cells)
            if n <= target:
                return m
            ratio = max(0.0, min(0.99, 1.0 - target / n))
            try:
                return m.decimate_pro(ratio, preserve_topology=False)
            except Exception as e1:
                print(f"  decimate_pro falhou ({e1}), usando decimate simples…")
                return m.decimate(ratio)

        reduzida = _decimate_pass(mesh, alvo)
        print(f"  passagem 1: {int(reduzida.n_cells):,} faces")
        if int(reduzida.n_cells) > alvo * 1.25:
            reduzida = _decimate_pass(reduzida, alvo)
            print(f"  passagem 2: {int(reduzida.n_cells):,} faces")

    pasta_leve = os.path.join(os.path.dirname(src), "leve")
    os.makedirs(pasta_leve, exist_ok=True)
    dest = os.path.join(pasta_leve, nome)

    reduzida.save(dest, binary=True)

    tamanho_leve = os.path.getsize(dest)
    n_leve = int(reduzida.n_cells)
    print(f"LEVE      {nome}: {n_leve:,} faces  |  {tamanho_leve / 1024:.1f} KB")
    print(f"Salvo em: {dest}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 reduzir_stl.py <arquivo.stl> [alvo_faces]")
        sys.exit(1)
    alvo = int(sys.argv[2]) if len(sys.argv) > 2 else 200_000
    reduzir(sys.argv[1], alvo)
