"""
DCubic — recebimento e compactação automática de STL enviados pelo usuário (Bloco 3).

Princípio: o aluno envia o STL bruto (ou um .zip com ele) e o app faz o resto, sem
tratamento manual. Fluxo de `receber_e_compactar`:
  1. recebendo  — grava cada arquivo em disco por blocos (zip membro a membro, com
                  shutil.copyfileobj), calculando o SHA-1 no caminho; nada inteiro na RAM;
  2. lendo      — detecta binário x ASCII (ASCII é convertido em fluxo para binário) e
                  mede área e caixa envolvente lendo o binário com np.memmap em blocos;
  3. compactando— só nas estruturas com mais de ALVO_TRIANGULOS (as menores passam intactas):
                  agrupamento de vértices numa grade com célula ABSOLUTA (mesmas unidades
                  do STL), calculada para ~ALVO_TRIANGULOS por estrutura; cada célula vira a
                  média dos seus vértices; triângulos degenerados e duplicados são removidos.
                  A MESMA grade (origem e célula) vale para todas as estruturas do envio,
                  para que as camadas continuem sobrepostas;
  4. pronto     — STL binário compactado, em cache de disco por SHA-1 do original.
Sem limpeza topológica: malhas abertas ou defeituosas passam como estão.
"""
from __future__ import annotations

import gc
import hashlib
import json
import math
import os
import shutil
import struct
import sys
import tempfile
import zipfile

import numpy as np

ALVO_TRIANGULOS = 500_000          # por estrutura; só reduz acima disso (≈ 25 MB em STL binário)
LIMITE_SAIDA_BYTES = 30 * 1024 * 1024   # mesmo teto de 30 MB do app (commit 76d235f)
BLOCO_TRIANGULOS = 250_000   # blocos menores = pico menor (1 milhão custava ~260 MB de trabalho)
# Memória: o app grava o envio em disco e libera os bytes do Streamlit ANTES de compactar
# (app.py, envio em duas etapas); a compactação usa ~TRABALHO_MB por bloco. O processo
# inteiro não deve passar de DCUBIC_LIMITE_MEMORIA_MB (padrão 800).
# ponytail: estimativa fixa de trabalho; ajuste DCUBIC_LIMITE_MEMORIA_MB conforme a RAM do servidor.
TRABALHO_MB = 150
# ponytail: estimativa fixa da malha REDUZIDA já aberta no app (3D + Cortes), por triângulo;
# medida no teste de 21/10/2026 (ver docs/DECISOES-REFINO-CORTES-UPLOAD.md). Recalibre se o 3D mudar.
BYTES_APP_POR_TRIANGULO = 400
LIMITE_LOCAL_MB = 2048   # mesmo valor de server.maxUploadSize em .streamlit/config.toml
LIMITE_SEGURO_MB = int(os.environ.get("DCUBIC_LIMITE_MEMORIA_MB", "800"))
LIMITE_MEMBRO_ZIP = 2 * 1024 ** 3   # recusa membros de zip acima de 2 GB descompactados
PASTA_CACHE = os.path.join(tempfile.gettempdir(), "dcubic_upload_cache")
_K_GRADE = 2.4   # triângulos ≈ _K_GRADE * área / célula² (agrupamento de vértices; calibrável)

_DT = np.dtype([("n", "<f4", (3,)), ("v", "<f4", (3, 3)), ("a", "<u2")])  # registro STL binário


class MemoriaInsuficiente(Exception):
    """O envio excede o limite seguro de memória do servidor."""


def rss_mb():
    """Memória residente do processo em MB (Linux: /proc; senão psutil, se instalado; senão None)."""
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1024 ** 2
    except (OSError, ValueError, IndexError):
        pass
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1024 ** 2
    except Exception:
        return None


def checar_tamanho(bytes_envio: int, limite_mb: int = LIMITE_LOCAL_MB) -> None:
    """Etapa 1 do envio: recusa, com mensagem clara, o envio acima do limite efetivo
    (DCUBIC_MAX_UPLOAD_MB; 200 MB no Streamlit Cloud). Não olha o RSS (os bytes do envio
    ainda estão na RAM do Streamlit, que os recebeu antes do app rodar)."""
    mb = bytes_envio / 1024 ** 2
    if mb > limite_mb:
        if limite_mb < LIMITE_LOCAL_MB:
            raise ValueError(f"O envio tem {mb:.0f} MB. Arquivos acima de {limite_mb} MB só podem "
                             "ser abertos na versão local/servidor USP.")
        raise ValueError(f"O envio tem {mb:.0f} MB e passa do limite de {limite_mb} MB por envio.")


def triangulos_no_arquivo(caminho: str) -> int:
    """Nº de triângulos pelo cabeçalho (binário) ou estimado pelo tamanho (ASCII, ~250 B/triângulo)."""
    try:
        if tipo_stl(caminho) == "binario":
            return (os.path.getsize(caminho) - 84) // 50
    except ValueError:
        pass
    return os.path.getsize(caminho) // 250


def memoria_necessaria_mb(recebidos, alvo: int = ALVO_TRIANGULOS) -> float:
    """Trabalho da compactação + malhas REDUZIDAS abertas no app (não o arquivo bruto)."""
    tri = sum(min(triangulos_no_arquivo(cam), alvo) for _nome, cam, _sha, _tam in recebidos)
    return TRABALHO_MB + tri * BYTES_APP_POR_TRIANGULO / 1024 ** 2


def checar_memoria(recebidos=(), alvo: int = ALVO_TRIANGULOS) -> None:
    """Etapa 2 do envio (bytes do envio já liberados): recusa com mensagem clara quando a
    memória atual, somada à necessária (trabalho + malhas reduzidas), passa do limite.
    No macOS o RSS não é usado: o alocador retém memória já liberada (MallocLargeCache,
    Etapa D1) e o número inflado recusaria arquivos grandes sem motivo."""
    gc.collect()
    precisa = memoria_necessaria_mb(recebidos, alvo)
    atual = None if sys.platform == "darwin" else rss_mb()
    if (atual or 0) + precisa > LIMITE_SEGURO_MB:
        raise MemoriaInsuficiente(
            (f"O servidor está usando {atual:.0f} MB de memória; " if atual else "")
            + f"abrir este envio precisa de ~{precisa:.0f} MB (compactação + malhas reduzidas) e "
            f"passaria do limite seguro ({LIMITE_SEGURO_MB} MB). "
            "Clique em 'Limpar STL', aguarde alguns segundos e envie novamente."
        )


# ── 1. Recebendo ────────────────────────────────────────────────────────────────

class _GravadorComHash:
    def __init__(self, f, h):
        self.f, self.h = f, h

    def write(self, b):
        self.h.update(b)
        return self.f.write(b)


def _gravar(origem, pasta: str):
    """Copia um objeto-arquivo para pasta/recebidos/<sha1>.stl por blocos. -> (caminho, sha1, bytes)."""
    destino_dir = os.path.join(pasta, "recebidos")
    os.makedirs(destino_dir, exist_ok=True)
    h = hashlib.sha1()
    fd, tmp = tempfile.mkstemp(dir=destino_dir, suffix=".part")
    with os.fdopen(fd, "wb") as f:
        shutil.copyfileobj(origem, _GravadorComHash(f, h), 1024 * 1024)
    sha = h.hexdigest()
    final = os.path.join(destino_dir, sha + ".stl")
    os.replace(tmp, final)
    return final, sha, os.path.getsize(final)


def receber(envios, pasta: str = PASTA_CACHE):
    """envios: objetos-arquivo com .name (.stl ou .zip). -> lista (nome, caminho, sha1, bytes)."""
    recebidos = []
    for arq in envios:
        nome = os.path.basename(arq.name)
        if hasattr(arq, "seek"):
            arq.seek(0)
        if nome.lower().endswith(".zip"):
            with zipfile.ZipFile(arq) as z:
                for m in z.infolist():
                    base = os.path.basename(m.filename)   # basename: sem caminhos do zip
                    if m.is_dir() or "__MACOSX" in m.filename or base.startswith(".") \
                            or not base.lower().endswith(".stl"):
                        continue
                    if m.file_size > LIMITE_MEMBRO_ZIP:
                        raise ValueError(f"'{base}' tem mais de 2 GB descompactado.")
                    with z.open(m) as src:
                        recebidos.append((base, *_gravar(src, pasta)))
        elif nome.lower().endswith(".stl"):
            recebidos.append((nome, *_gravar(arq, pasta)))
    return recebidos


# ── 1b. Recebendo por link do Google Drive (contorna o limite de envio do Cloud) ────

LIMITE_DRIVE_MB = 2048   # padrão de DCUBIC_MAX_DRIVE_MB (o app lê secrets/ambiente)
FATOR_DISCO = 2.5        # download (1×) + cópia/extração em recebidos/ (1×) + folga (saída, ASCII->binário)


def _apagar(caminho):
    if os.path.isfile(caminho):
        os.remove(caminho)


class _GravadorLimitado:
    """Destino do gdown (que grava em blocos de 512 KB): conta os bytes e interrompe o
    download ao passar do limite ou ao faltar disco; avisa o progresso a cada ~8 MB."""

    def __init__(self, f, limite_bytes, livre_bytes, progresso):
        self.f, self.limite, self.livre, self.p = f, limite_bytes, livre_bytes, progresso
        self.n = self._ultimo = 0

    def write(self, b):
        self.n += len(b)
        if self.n > self.limite:
            raise ValueError(f"O arquivo do Drive passa do limite de {self.limite // 1024 ** 2} MB "
                             "(DCUBIC_MAX_DRIVE_MB). O download foi interrompido.")
        if FATOR_DISCO * self.n > self.livre:
            precisa_mb = max(1, math.ceil(FATOR_DISCO * self.n / 1024 ** 2))
            raise ValueError(f"Espaço em disco insuficiente no servidor: são necessários cerca de "
                             f"{precisa_mb} MB livres e há apenas {self.livre // 1024 ** 2} MB. "
                             "O download foi interrompido.")
        if self.n - self._ultimo >= 8 * 1024 ** 2:
            self._ultimo = self.n
            mb = self.n / 1024 ** 2
            # ponytail: o gdown não expõe o tamanho total; barra assintótica + MB baixados
            self.p(0.9 * mb / (mb + 300), f"Baixando… {mb:.0f} MB")
        return self.f.write(b)


def id_do_drive(link: str) -> str:
    """ID do arquivo em links /file/d/ID/... ou ...?id=ID (aceita também o ID puro)."""
    import re
    link = (link or "").strip()
    m = (re.search(r"/file/d/([\w-]{10,})", link) or re.search(r"[?&]id=([\w-]{10,})", link)
         or re.fullmatch(r"([\w-]{20,})", link))
    if not m:
        raise ValueError("Link do Google Drive não reconhecido. Use o link de compartilhamento "
                         "(…/file/d/ID/… ou …?id=ID).")
    return m.group(1)


def baixar_do_drive(link: str, limite_mb: int = LIMITE_DRIVE_MB, pasta: str = PASTA_CACHE, progresso=None):
    """Baixa o arquivo público do Drive direto para disco (gdown, blocos de 512 KB) e o
    entrega a `receber_baixado`. -> lista (nome, caminho, sha1, bytes), igual a `receber`."""
    import gdown
    from gdown.exceptions import FileURLRetrievalError
    p = progresso or (lambda frac, texto: None)
    fid = id_do_drive(link)
    destino_dir = os.path.join(pasta, "drive")
    os.makedirs(destino_dir, exist_ok=True)
    livre = shutil.disk_usage(destino_dir).free
    bruto = os.path.join(destino_dir, f"drive_{fid[:8]}.part")
    p(0.0, "Baixando…")
    try:
        with open(bruto, "wb") as f:
            gdown.download(f"https://drive.google.com/uc?id={fid}",
                           _GravadorLimitado(f, limite_mb * 1024 ** 2, livre, p), quiet=True)
    except Exception as e:
        _apagar(bruto)
        if isinstance(e, ValueError):   # limite ou disco (mensagem já pronta)
            raise
        if isinstance(e, FileURLRetrievalError):
            raise ValueError("Não foi possível baixar do Google Drive: o arquivo não está público ou o "
                             "Drive bloqueou temporariamente o download (excesso de acessos). No Google "
                             "Drive: Compartilhar > Acesso geral: Qualquer pessoa com o link.") from None
        raise ValueError(f"Falha ao baixar do Google Drive ({type(e).__name__}). "
                         "Verifique a conexão e tente novamente.") from None
    return receber_baixado(bruto, pasta, progresso=p)


def receber_baixado(caminho: str, pasta: str = PASTA_CACHE, progresso=None):
    """Pós-download: valida (.zip pela assinatura PK, .stl pelo cabeçalho binário 84+50n ou
    'solid' ASCII), extrai/copia para recebidos/ por blocos (via `receber`) e apaga o bruto —
    SÓ quando ele está na pasta de downloads do app (pasta/drive); arquivo de fora nunca é apagado.
    -> lista (nome, caminho, sha1, bytes)."""
    p = progresso or (lambda frac, texto: None)
    meu = os.path.dirname(os.path.realpath(caminho)) == os.path.realpath(os.path.join(pasta, "drive"))
    try:
        with open(caminho, "rb") as f:
            eh_zip = f.read(4) == b"PK\x03\x04"
        if eh_zip:
            with zipfile.ZipFile(caminho) as z:
                precisa = sum(m.file_size for m in z.infolist() if m.filename.lower().endswith(".stl"))
            livre = shutil.disk_usage(os.path.dirname(os.path.realpath(caminho))).free
            if 1.1 * precisa > livre:
                raise ValueError(f"Espaço em disco insuficiente no servidor: o .zip descompactado tem "
                                 f"{precisa / 1024 ** 2:.0f} MB e há {livre / 1024 ** 2:.0f} MB livres.")
        else:
            try:
                tipo_stl(caminho)
            except (ValueError, struct.error):
                raise ValueError("O arquivo baixado não é um .stl nem um .zip válido (o link pode exigir "
                                 "login ou apontar para outro tipo de arquivo).") from None
        if meu:   # receber() escolhe .zip/.stl pelo nome
            final = os.path.splitext(caminho)[0] + (".zip" if eh_zip else ".stl")
            os.replace(caminho, final)
            caminho = final
        p(0.05, "Extraindo…" if eh_zip else "Recebendo…")
        with open(caminho, "rb") as f:
            return receber([f], pasta)
    finally:
        if meu:
            _apagar(caminho)


def processar_recebidos(recebidos, pasta: str = PASTA_CACHE, progresso=None):
    """Pós-recebimento comum ao envio e ao Drive: checagem de memória (D1) + compactação."""
    checar_memoria(recebidos)
    return compactar_recebidos(recebidos, pasta, progresso=progresso)


# ── 2. Lendo ────────────────────────────────────────────────────────────────────

def tipo_stl(caminho: str) -> str:
    tam = os.path.getsize(caminho)
    with open(caminho, "rb") as f:
        cab = f.read(84)
    if tam >= 84 and 84 + 50 * struct.unpack("<I", cab[80:84])[0] == tam:
        return "binario"
    if cab.lstrip().lower().startswith(b"solid"):
        return "ascii"
    raise ValueError("o arquivo não é um STL válido (nem binário nem ASCII).")


def ascii_para_binario(origem: str, destino: str) -> int:
    """Converte STL ASCII em binário lendo linha a linha (sem carregar o arquivo). -> nº triângulos."""
    n, buf = 0, []
    with open(origem, "r", errors="ignore") as f, open(destino, "wb") as o:
        o.write(b"DCubic: convertido de STL ASCII".ljust(80, b" ") + b"\0\0\0\0")

        def despejar():
            nonlocal n, buf
            k = len(buf) // 9
            if k:
                rec = np.zeros(k, _DT)
                rec["v"] = np.asarray(buf[:k * 9], np.float32).reshape(k, 3, 3)
                rec.tofile(o)
                n += k
            buf = []

        for linha in f:
            linha = linha.strip()
            if linha.startswith("vertex"):
                buf.extend(float(x) for x in linha.split()[1:4])
                if len(buf) >= 9 * 200_000:
                    despejar()
        despejar()
        o.seek(80)
        o.write(struct.pack("<I", n))
    return n


def _blocos(caminho: str):
    """Itera (início, vértices float32 (b,3,3) com coordenadas finitas). Cada bloco é um
    np.memmap só do seu trecho, desfeito em seguida: o arquivo nunca fica todo mapeado."""
    n = (os.path.getsize(caminho) - 84) // 50
    for i in range(0, n, BLOCO_TRIANGULOS):
        b = min(BLOCO_TRIANGULOS, n - i)
        mm = np.memmap(caminho, dtype=_DT, mode="r", offset=84 + 50 * i, shape=(b,))
        v = np.array(mm["v"], dtype=np.float32)   # float32 como no STL: metade da RAM
        del mm
        ok = np.isfinite(v).all(axis=(1, 2))
        yield i, (v if ok.all() else v[ok])   # tolera triângulos com NaN/inf


def medir(caminho_bin: str) -> dict:
    """Área total, caixa envolvente e nº de triângulos (leitura em blocos)."""
    n = (os.path.getsize(caminho_bin) - 84) // 50
    area, lo, hi = 0.0, np.full(3, np.inf), np.full(3, -np.inf)
    for _, v in _blocos(caminho_bin):
        if len(v):
            area += 0.5 * float(np.linalg.norm(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1).sum(dtype=np.float64))
            lo = np.minimum(lo, v.min(axis=(0, 1)))
            hi = np.maximum(hi, v.max(axis=(0, 1)))
    return {"n": int(n), "area": float(area), "min": lo.tolist(), "max": hi.tolist()}


# ── 3. Compactando ──────────────────────────────────────────────────────────────

def grade_comum(infos: list, alvo: int = ALVO_TRIANGULOS):
    """Origem e célula únicas para o envio. A célula é a maior entre as estruturas
    (nenhuma passa do alvo); estruturas menores ficam com a mesma resolução absoluta."""
    origem = np.min([i["min"] for i in infos], axis=0)
    celula = max(np.sqrt(_K_GRADE * i["area"] / alvo) for i in infos if i["area"] > 0)
    return origem, float(celula)


def compactar(caminho_bin: str, origem, celula: float, destino: str) -> int:
    """Agrupamento de vértices (célula = média dos vértices). Grava STL binário. -> nº triângulos."""
    origem32, celula32 = np.asarray(origem, dtype=np.float32), np.float32(celula)
    chaves, somas, contagens, tris = [], [], [], []
    for _, v in _blocos(caminho_bin):
        w = v - origem32
        w /= celula32
        np.floor(w, out=w)
        ijk = w.astype(np.int32)   # (b,3,3)
        del w
        np.clip(ijk, 0, 2 ** 20 - 1, out=ijk)
        k = ijk[..., 0].astype(np.int64) << 40   # (b,3) chave da célula
        k |= ijk[..., 1].astype(np.int64) << 20
        k |= ijk[..., 2]
        del ijk
        uk, inv = np.unique(k.ravel(), return_inverse=True)
        vf = v.reshape(-1, 3)
        chaves.append(uk)
        somas.append(np.stack([np.bincount(inv, vf[:, d], len(uk)) for d in range(3)], 1))
        contagens.append(np.bincount(inv, minlength=len(uk)))
        ok = (k[:, 0] != k[:, 1]) & (k[:, 1] != k[:, 2]) & (k[:, 0] != k[:, 2])   # não degenerados
        tris.append(k[ok])
        del k, inv, vf, ok, v
    if not tris:
        raise ValueError("STL sem triângulos válidos.")
    uk, inv = np.unique(np.concatenate(chaves), return_inverse=True)
    s, c = np.concatenate(somas), np.concatenate(contagens)
    verts = np.stack([np.bincount(inv, s[:, d], len(uk)) for d in range(3)], 1) / np.bincount(inv, c, len(uk))[:, None]
    t = np.concatenate(tris)
    _, primeiro = np.unique(np.sort(t, axis=1), axis=0, return_index=True)   # duplicados (qualquer orientação)
    faces = np.searchsorted(uk, t[np.sort(primeiro)])
    del chaves, somas, contagens, tris, s, c, t, primeiro, inv
    _gravar_stl(destino, verts[faces])
    n = len(faces)
    del verts, faces, uk
    gc.collect()
    return n


def _gravar_stl(destino: str, tri: np.ndarray) -> None:
    rec = np.zeros(len(tri), _DT)
    rec["v"] = tri
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    rec["n"] = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    with open(destino, "wb") as f:
        f.write(b"DCubic: compactado por agrupamento de vertices".ljust(80, b" "))
        f.write(struct.pack("<I", len(tri)))
        rec.tofile(f)


# ── Fluxo completo ──────────────────────────────────────────────────────────────

def receber_e_compactar(envios, pasta: str = PASTA_CACHE, alvo: int = ALVO_TRIANGULOS, progresso=None):
    """Recebe (.stl/.zip) e compacta. O app usa as duas etapas separadas (receber ->
    liberar o envio da RAM -> compactar_recebidos); esta função junta as duas."""
    return compactar_recebidos(receber(envios, pasta), pasta, alvo, progresso)


def compactar_recebidos(recebidos, pasta: str = PASTA_CACHE, alvo: int = ALVO_TRIANGULOS, progresso=None):
    """Mede e compacta, UM ARQUIVO POR VEZ e com grade comum, os arquivos já gravados por
    `receber`. Devolve uma lista de dicts: nome, caminho (STL compactado), bytes_antes,
    bytes_depois, tri_antes, tri_depois, cache."""
    p = progresso or (lambda frac, texto: None)
    os.makedirs(os.path.join(pasta, "info"), exist_ok=True)
    if not recebidos:
        raise ValueError("Nenhum arquivo .stl encontrado no envio.")

    infos, binarios = [], []
    for i, (nome, cam, sha, tam) in enumerate(recebidos):
        p(0.10 + 0.25 * i / len(recebidos), f"Lendo {nome}…")
        j = os.path.join(pasta, "info", sha + ".json")
        if os.path.isfile(j):
            with open(j) as f:
                info = json.load(f)
            binarios.append(None)   # só será lido se a compactação não estiver em cache
        else:
            cam_bin = cam
            if tipo_stl(cam) == "ascii":
                cam_bin = cam[:-4] + "_bin.stl"
                ascii_para_binario(cam, cam_bin)
            info = medir(cam_bin)
            gc.collect()
            with open(j, "w") as f:
                json.dump(info, f)
            binarios.append(cam_bin)
        infos.append(info)

    reduzir = [info["n"] > alvo for info in infos]   # até o alvo, a malha passa intacta
    grandes = [info for info, r in zip(infos, reduzir) if r]
    origem, celula = grade_comum(grandes, alvo) if grandes else (np.zeros(3), 0.0)
    resultados = []
    for _tentativa in range(3):   # se alguma estrutura passar de 30 MB, engrossa a grade e refaz
        tag = hashlib.md5(json.dumps([np.round(origem, 6).tolist(), round(celula, 9)]).encode()).hexdigest()[:10]
        resultados = []
        for i, ((nome, cam, sha, tam), info) in enumerate(zip(recebidos, infos)):
            p(0.35 + 0.6 * i / len(recebidos), f"{'Reduzindo' if reduzir[i] else 'Preparando'} {nome}…")
            pasta_saida = os.path.join(pasta, f"{sha}_{tag if reduzir[i] else 'original'}")
            saida = os.path.join(pasta_saida, os.path.splitext(nome)[0] + ".stl")
            em_cache = os.path.isfile(saida)
            if em_cache:
                n_out = (os.path.getsize(saida) - 84) // 50
            else:
                cam_bin = binarios[i]
                if cam_bin is None:   # medida em cache, mas compactação nova (outra grade)
                    cam_bin = cam
                    if tipo_stl(cam) == "ascii":
                        cam_bin = cam[:-4] + "_bin.stl"
                        ascii_para_binario(cam, cam_bin)
                    binarios[i] = cam_bin
                os.makedirs(pasta_saida, exist_ok=True)
                if reduzir[i]:
                    n_out = compactar(cam_bin, origem, celula, saida + ".part")
                    os.replace(saida + ".part", saida)
                else:   # mesma malha, só em binário: origem espacial intacta
                    os.replace(cam_bin, saida)
                    n_out = info["n"]
            resultados.append({"nome": os.path.splitext(nome)[0], "caminho": saida, "bytes_antes": tam,
                               "bytes_depois": os.path.getsize(saida), "tri_antes": info["n"],
                               "tri_depois": int(n_out), "cache": em_cache, "celula": celula,
                               "reduzida": reduzir[i]})
        maior = max(r["bytes_depois"] for r, red in zip(resultados, reduzir) if red) if grandes else 0
        if maior <= LIMITE_SAIDA_BYTES:
            break
        celula *= float(np.sqrt(maior / (0.8 * LIMITE_SAIDA_BYTES)))

    for nome, cam, sha, tam in recebidos:   # originais não ficam no disco (o cache é a compactação)
        for c in (cam, cam[:-4] + "_bin.stl"):
            if os.path.isfile(c):
                os.remove(c)
    p(1.0, "Pronto")
    return resultados


if __name__ == "__main__":
    # Autoverificação mínima: cubo ASCII -> binário -> compactar mantém 12 triângulos e a caixa.
    d = tempfile.mkdtemp()
    v = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
    f = [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
         [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]]
    with open(os.path.join(d, "cubo.stl"), "w") as a:
        a.write("solid cubo\n")
        for t in f:
            a.write(" facet normal 0 0 0\n  outer loop\n")
            for i in t:
                a.write("   vertex %g %g %g\n" % tuple(v[i]))
            a.write("  endloop\n endfacet\n")
        a.write("endsolid cubo\n")
    import io
    with open(os.path.join(d, "cubo.stl"), "rb") as a:
        env = io.BytesIO(a.read())
    env.name = "cubo.stl"
    r = receber_e_compactar([env], pasta=d, alvo=10_000)
    assert r[0]["tri_antes"] == 12 and r[0]["tri_depois"] == 12 and not r[0]["reduzida"], r
    assert tipo_stl(r[0]["caminho"]) == "binario"
    print("stl_compactar OK:", r[0]["tri_antes"], "->", r[0]["tri_depois"], "triângulos")
    # Drive: ID nos dois formatos; arquivo de fora de pasta/drive não é apagado; HTML é recusado.
    _fid = "1uqU_6-O9MqrwWzavr74CJU_KQJIJWDV1"
    assert id_do_drive(f"https://drive.google.com/file/d/{_fid}/view?usp=sharing") == _fid
    assert id_do_drive(f"https://drive.google.com/open?id={_fid}") == _fid
    with open(os.path.join(d, "cubo.stl"), "rb") as a, open(os.path.join(d, "fora.stl"), "wb") as b:
        b.write(a.read())
    assert receber_baixado(os.path.join(d, "fora.stl"), pasta=d) and os.path.isfile(os.path.join(d, "fora.stl"))
    os.makedirs(os.path.join(d, "drive"), exist_ok=True)
    with open(os.path.join(d, "drive", "x.part"), "w") as b:
        b.write("<!DOCTYPE html><title>Sign in</title>")
    try:
        receber_baixado(os.path.join(d, "drive", "x.part"), pasta=d)
        raise AssertionError("HTML aceito")
    except ValueError:
        assert not os.path.exists(os.path.join(d, "drive", "x.part"))
    print("drive OK")
