"""
Gera STL binários GRANDES para testar o envio e a abertura de arquivos de até 3 GB
(docs/ENVIO-3GB.md). Tudo é gravado por blocos: nada do arquivo inteiro fica na RAM.

    python3 tools/gerar_stl_teste.py sintetico <saida.stl> [--tri 64000000]
    python3 tools/gerar_stl_teste.py subdividir <entrada.stl> <saida.stl>

sintetico  — "dente" de teste nas unidades dos STL do app (~1.400 un.): esfera de raio 600
             (superfície externa) + 3 canais finos fechados (diâmetros 2, 4 e 8 un., 800 un. de
             comprimento) dentro dela. Os diâmetros ficam perto da célula da redução (~3 un.):
             é onde o agrupamento de vértices comum faz o canal sumir.
subdividir — divide cada triângulo de um STL binário real em 4 (pontos médios das arestas):
             mesma superfície e mesmo volume, 4 × mais triângulos.
"""
from __future__ import annotations

import os
import struct
import sys

import numpy as np

_DT = np.dtype([("n", "<f4", (3,)), ("v", "<f4", (3, 3)), ("a", "<u2")])
CENTRO = np.array([700.0, 700.0, 700.0])
RAIO = 600.0
CANAIS = [  # (x, y, diâmetro): eixo paralelo a z, de z = 300 a 1100
    (640.0, 700.0, 2.0),
    (700.0, 700.0, 4.0),
    (760.0, 700.0, 8.0),
]
Z0, Z1 = 300.0, 1100.0


def _gravar(f, tri: np.ndarray) -> int:
    """tri (k,3,3) float64 -> registros STL (normal calculada)."""
    rec = np.zeros(len(tri), _DT)
    rec["v"] = tri
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    rec["n"] = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
    rec.tofile(f)
    return len(tri)


def _icosaedro():
    t = (1 + 5 ** 0.5) / 2
    v = np.array([[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t],
                  [0, -1, -t], [0, 1, -t], [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]], float)
    f = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2],
         [10, 7, 6], [7, 1, 8], [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5],
         [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]]
    return v / np.linalg.norm(v, axis=1, keepdims=True), np.array(f)


def _grade_triangular(n: int):
    """Índices (i, j) dos pontos e as n² faces de um triângulo dividido em n partes por lado."""
    i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing="ij")
    ok = i + j <= n
    i, j = i[ok], j[ok]
    idx = -np.ones((n + 1, n + 1), np.int64)
    idx[i, j] = np.arange(len(i))
    a, b = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    cima = (a + b) <= n - 1
    baixo = (a + b) <= n - 2
    f1 = np.stack([idx[a[cima], b[cima]], idx[a[cima] + 1, b[cima]], idx[a[cima], b[cima] + 1]], 1)
    f2 = np.stack([idx[a[baixo] + 1, b[baixo]], idx[a[baixo] + 1, b[baixo] + 1], idx[a[baixo], b[baixo] + 1]], 1)
    return i / n, j / n, np.concatenate([f1, f2])


def _esfera(f, n: int) -> int:
    v, faces = _icosaedro()
    u, w, ft = _grade_triangular(n)
    total = 0
    for a, b, c in faces:
        p = v[a] + np.outer(u, v[b] - v[a]) + np.outer(w, v[c] - v[a])
        p /= np.linalg.norm(p, axis=1, keepdims=True)
        tri = p[ft] * RAIO + CENTRO
        # orientação para fora
        nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        dentro = (nrm * (tri.mean(axis=1) - CENTRO)).sum(axis=1) < 0
        tri[dentro] = tri[dentro][:, ::-1]
        total += _gravar(f, tri)
        del p, tri, nrm
    return total


def _canal(f, x, y, d, n_volta: int, n_compr: int) -> int:
    r = d / 2
    th = np.linspace(0, 2 * np.pi, n_volta, endpoint=False)
    anel = np.stack([x + r * np.cos(th), y + r * np.sin(th)], 1)   # (n_volta, 2)
    m0, m1 = np.arange(n_volta), (np.arange(n_volta) + 1) % n_volta
    total = 0
    zs = np.linspace(Z0, Z1, n_compr + 1)
    for k0 in range(0, n_compr, 20000):   # blocos de anéis
        k1 = min(k0 + 20000, n_compr)
        za, zb = zs[k0:k1, None], zs[k0 + 1:k1 + 1, None]
        def P(m, z):
            return np.stack([np.broadcast_to(anel[m, 0], (len(z), len(m))),
                             np.broadcast_to(anel[m, 1], (len(z), len(m))),
                             np.broadcast_to(z, (len(z), len(m)))], -1)
        a, b, c, e = P(m0, za), P(m1, za), P(m1, zb), P(m0, zb)
        tri = np.concatenate([np.stack([a, b, c], -2).reshape(-1, 3, 3),
                              np.stack([a, c, e], -2).reshape(-1, 3, 3)])
        total += _gravar(f, tri)
    for z, sinal in ((Z0, -1), (Z1, 1)):   # tampas (leque)
        cen = np.broadcast_to([x, y, z], (n_volta, 3))
        p0 = np.column_stack([anel[m0], np.full(n_volta, z)])
        p1 = np.column_stack([anel[m1], np.full(n_volta, z)])
        tri = np.stack([cen, p0, p1] if sinal > 0 else [cen, p1, p0], 1)
        total += _gravar(f, tri)
    return total


def _cabecalho(f, texto: bytes):
    f.write(texto.ljust(80, b" ")[:80])
    f.write(b"\0\0\0\0")


def sintetico(saida: str, tri: int = 64_000_000) -> int:
    n = int((0.8 * tri / 20) ** 0.5)          # ~80% dos triângulos na esfera
    resto = tri - 20 * n * n
    n_volta = 64
    n_compr = max(1, (resto // len(CANAIS) - 2 * n_volta) // (2 * n_volta))
    with open(saida, "wb") as f:
        _cabecalho(f, b"DCubic: STL sintetico de teste (esfera + canais finos)")
        total = _esfera(f, n)
        for x, y, d in CANAIS:
            total += _canal(f, x, y, d, n_volta, n_compr)
        f.seek(80)
        f.write(struct.pack("<I", total))
    return total


def subdividir(entrada: str, saida: str) -> int:
    n = (os.path.getsize(entrada) - 84) // 50
    if 84 + 50 * n != os.path.getsize(entrada):
        raise SystemExit("subdividir: só STL binário")
    total = 0
    with open(saida, "wb") as f:
        _cabecalho(f, b"DCubic: STL real subdividido (x4) para teste")
        for i in range(0, n, 1_000_000):
            b = min(1_000_000, n - i)
            mm = np.memmap(entrada, dtype=_DT, mode="r", offset=84 + 50 * i, shape=(b,))
            v = np.array(mm["v"], dtype=np.float64)
            nrm = np.array(mm["n"])
            del mm
            a, b_, c = v[:, 0], v[:, 1], v[:, 2]
            ab, bc, ca = (a + b_) / 2, (b_ + c) / 2, (c + a) / 2
            tri = np.concatenate([np.stack(t, 1) for t in ((a, ab, ca), (ab, b_, bc), (ca, bc, c), (ab, bc, ca))])
            rec = np.zeros(len(tri), _DT)
            rec["v"] = tri
            rec["n"] = np.tile(nrm, (4, 1))
            rec.tofile(f)
            total += len(tri)
        f.seek(80)
        f.write(struct.pack("<I", total))
    return total


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "sintetico":
        t = int(sys.argv[sys.argv.index("--tri") + 1]) if "--tri" in sys.argv else 64_000_000
        n = sintetico(sys.argv[2], t)
    elif len(sys.argv) == 4 and sys.argv[1] == "subdividir":
        n = subdividir(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(__doc__)
    saida = sys.argv[2] if sys.argv[1] == "sintetico" else sys.argv[3]
    tam = os.path.getsize(saida)
    assert tam == 84 + 50 * n, (tam, n)
    print(f"{saida}: {n:,} triângulos, {tam:,} bytes ({tam / 1024 ** 3:.2f} GiB)".replace(",", "."))
