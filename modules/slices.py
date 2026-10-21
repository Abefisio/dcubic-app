"""
DCubic — cortes (slices) ortogonais de malhas STL, no estilo dos visualizadores de micro-CT.

Convenção de eixos IDÊNTICA à de modules/viewer3d.create_plotly_3d (para o corte bater
com o modelo mostrado no 3D): as colunas de mesh.points são (c0, c1, c2) e o Plotly usa
x = c2, y = c1, z = c0. Aqui as malhas são reordenadas para (x, y, z) do Plotly:
  Axial   (Z) -> plano z = const, imagem em (x, y)
  Coronal (Y) -> plano y = const, imagem em (x, z)
  Sagital (X) -> plano x = const, imagem em (y, z)
Unidades: as nativas do STL (ver UNIDADE).
"""
from __future__ import annotations

import io
import time

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

# eixo -> (índice da coordenada fixa, (índice u horizontal, índice v vertical), rótulo)
EIXOS = {
    "Axial (Z)":   (2, (0, 1)),
    "Coronal (Y)": (1, (0, 2)),
    "Sagital (X)": (0, (1, 2)),
}
LIMITE_FACES = 1_000_000   # acima disto não se carrega o STL bruto (memória)
PASSO_MM = 0.05
# Os STL do app estão em unidades nativas (calibração de voxel pendente, ver métricas do app).
# Troque para "mm" quando a calibração existir.
UNIDADE = "un."
LADO_PX = 512
TOL_FECHAR = 0.005   # contornos abertos: fecha lacunas de até ~0,5% da diagonal do bounding box

_RANK_NOME = (("esmalte", 0), ("dentina", 1), ("molar", 1), ("raiz", 1),
              ("polpa", 2), ("canal", 2))


def para_trimesh(pontos: np.ndarray, faces: np.ndarray) -> trimesh.Trimesh:
    """Pontos/faces (colunas c0,c1,c2) -> Trimesh em coordenadas do Plotly (x,y,z)."""
    v = np.asarray(pontos, dtype=np.float64)[:, [2, 1, 0]]
    f = np.asarray(faces)[:, ::-1]  # a troca de eixos é uma reflexão: inverte o enrolamento
    return trimesh.Trimesh(vertices=v, faces=f, process=False)


def carregar_trimesh(caminho: str, n_faces_original: int, malha_pv) -> trimesh.Trimesh:
    """Malha trimesh de um STL. Acima de LIMITE_FACES usa a malha já decimada do app
    (mesh_loader). ponytail: o Bloco 3 (compactação) substituirá esse recurso."""
    if n_faces_original <= LIMITE_FACES:
        m = trimesh.load(caminho, file_type="stl", process=False)
        # STL do trimesh já vem como (x, y, z) do arquivo = (c0, c1, c2) do pyvista
        return para_trimesh(m.vertices, m.faces)
    faces = malha_pv.faces.reshape(-1, 4)[:, 1:]
    return para_trimesh(malha_pv.points, faces)


def bbox_combinado(malhas: dict) -> np.ndarray:
    """(2,3) min/max em (x,y,z) de todas as malhas."""
    b = np.array([m.bounds for m in malhas.values()])
    return np.array([b[:, 0].min(axis=0), b[:, 1].max(axis=0)])


def _ordem_desenho(nome: str, area: float):
    r = next((r for k, r in _RANK_NOME if k in nome.lower()), 1)
    return (r, -area)  # esmalte -> dentina -> canal; desconhecidos: maior área primeiro


def _secao(malha: trimesh.Trimesh, eixo: int, pos: float, uv):
    """Interseção malha x plano axial-alinhado, em (u,v).
    Retorna (poligonos_shapely_com_furos, segmentos (n,2,2), contorno_fechado)."""
    normal = np.zeros(3); normal[eixo] = 1.0
    origem = np.zeros(3); origem[eixo] = pos
    secao = malha.section(plane_origin=origem, plane_normal=normal)
    if secao is None:
        return [], np.empty((0, 2, 2)), True
    m4 = np.eye(4)
    m4[:3, :3] = 0
    m4[0, uv[0]] = 1; m4[1, uv[1]] = 1; m4[2, eixo] = 1  # (u,v) viram x,y planares
    plano, _ = secao.to_planar(to_2D=m4, check=False)
    segs = np.concatenate([plano.vertices[e.points][np.c_[np.arange(len(e.points) - 1),
                                                            np.arange(1, len(e.points))]]
                           for e in plano.entities]) if len(plano.entities) else np.empty((0, 2, 2))
    return list(plano.polygons_full), segs, len(plano.dangling) == 0


def _par_impar(linhas: np.ndarray) -> np.ndarray:
    """Máscara booleana (h,w) de contornos já desenhados (True = traço): preenche pela regra
    par-ímpar. Regiões separadas pelo traço formam um grafo; profundidade ímpar = sólido,
    par = vazio (câmara/canais dentro da dentina viram furo). Não preenche furos por fechamento."""
    reg, n = ndimage.label(~linhas)          # regiões livres (4-conectadas)
    ar = set()
    for k in (1, 2, 3, 4):                   # regiões vizinhas através de um traço de até k px
        for a, b in ((reg[:, :-k], reg[:, k:]), (reg[:-k], reg[k:])):
            m = (a != b) & (a > 0) & (b > 0)
            ar.update(zip(a[m].tolist(), b[m].tolist()))
    viz = {i: set() for i in range(1, n + 1)}
    for a, b in ar:
        viz[a].add(b); viz[b].add(a)
    prof = {reg[0, 0]: 0}                    # (0,0) é fundo exterior (há margem)
    fila = [reg[0, 0]]
    for r in fila:
        for v in viz.get(r, ()):
            if v not in prof:
                prof[v] = prof[r] + 1; fila.append(v)
    impar = np.zeros(n + 1, dtype=bool)
    for r, p in prof.items():
        impar[r] = p % 2 == 1
    return impar[reg] | linhas


def _barra_nice(mm_visivel: float) -> float:
    alvo = mm_visivel / 4
    for passo in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50):
        if passo >= alvo:
            return passo
    return 50


def gerar_corte(malhas: dict, cores: dict, nome_eixo: str, pos: float, bbox: np.ndarray,
                px_por_mm: float):
    """Retorna (png_bytes | None, info). None = o plano não intersecta nenhuma estrutura.
    Fundo preto; estruturas de fora para dentro; escala px/mm fixa (igual nos 3 eixos)."""
    eixo, uv = EIXOS[nome_eixo]
    ext = bbox[1] - bbox[0]
    margem = 28
    # Tela quadrada do mesmo tamanho nos 3 eixos (corte centralizado): na interface as
    # três imagens ficam com a mesma escala px/mm.
    lado = int(float(ext.max()) * px_por_mm) + 2 * margem
    w, h = lado, lado + 22
    du = (lado - 2 * margem - ext[uv[0]] * px_por_mm) / 2
    dv = (lado - 2 * margem - ext[uv[1]] * px_por_mm) / 2
    camadas = []
    for nome, m in malhas.items():
        polis, segs, fechado = _secao(m, eixo, pos, uv)
        if len(segs):
            area = sum(p.area for p in polis) if fechado else float(np.ptp(segs[:, :, 0]) * np.ptp(segs[:, :, 1]))
            camadas.append((nome, (polis, segs, fechado), area))
    if not camadas:
        return None, {"estruturas": []}
    camadas.sort(key=lambda c: _ordem_desenho(c[0], c[2]))

    img = Image.new("RGB", (w, h), (0, 0, 0))
    o_u, o_v = bbox[0][uv[0]], bbox[0][uv[1]]

    def px(coords):  # (u,v) mm -> pixel (v cresce para cima)
        return [((u - o_u) * px_por_mm + margem + du, h - 22 - margem - dv - (v - o_v) * px_por_mm)
                for u, v in coords]

    for nome, (polis, segs, fechado), _ in camadas:
        mascara = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(mascara)
        if fechado:  # contorno íntegro: polígonos exatos, furos respeitados
            for p in polis:
                d.polygon(px(p.exterior.coords), fill=255)
                for furo in p.interiors:
                    d.polygon(px(furo.coords), fill=0)  # furo revela o que está por baixo
        else:
            # Malha com falhas (STL bruto aberto): desenha os segmentos, une pontas próximas
            # (fechamento de ~0,5% da diagonal) e preenche pela regra par-ímpar.
            # ponytail: lacunas maiores que a tolerância ficam abertas (região vaza para o fundo).
            for a, b in segs:
                d.line(px((a, b)), fill=255, width=2)
            tol_px = max(1, int(round(TOL_FECHAR * float(np.linalg.norm(ext)) * px_por_mm / 2)))
            arr = ndimage.binary_closing(np.asarray(mascara) > 0, iterations=tol_px)
            mascara = Image.fromarray((_par_impar(arr) * 255).astype(np.uint8))
        img.paste(tuple(cores.get(nome, (200, 200, 200))), mask=mascara)

    d = ImageDraw.Draw(img)
    fonte = ImageFont.load_default()
    barra = _barra_nice(w / px_por_mm)
    x0, y0 = margem, h - 14
    d.line([(x0, y0), (x0 + barra * px_por_mm, y0)], fill=(255, 255, 255), width=2)
    for x in (x0, x0 + barra * px_por_mm):
        d.line([(x, y0 - 4), (x, y0 + 4)], fill=(255, 255, 255), width=2)
    d.text((x0 + barra * px_por_mm + 8, y0 - 5), f"{barra:g} {UNIDADE}", fill=(255, 255, 255), font=fonte)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), {"estruturas": [c[0] for c in camadas]}


def px_por_mm_padrao(bbox: np.ndarray) -> float:
    return (LADO_PX - 56) / float(max(bbox[1] - bbox[0]))


def tempo_corte(malhas, cores, nome_eixo, pos, bbox, n=5) -> float:
    t = time.perf_counter()
    for _ in range(n):
        gerar_corte(malhas, cores, nome_eixo, pos, bbox, px_por_mm_padrao(bbox))
    return (time.perf_counter() - t) / n
