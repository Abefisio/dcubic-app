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
import zlib
import time
import zipfile

import numpy as np

# Envio grande (VPS, DCUBIC_ENVIO_GRANDE=1, docs/ENVIO-3GB.md): arquivos de até 3 GB; o ENVIO inteiro
# (todas as estruturas do dente) fica em até 1,5 milhão de triângulos, com agrupamento adaptativo
# que refina as células onde a superfície se fecha (canais finos). Sem a variável: como antes.
GRANDE = os.environ.get("DCUBIC_ENVIO_GRANDE") == "1"
ALVO_TRIANGULOS = 1_500_000 if GRANDE else 500_000   # grande: soma do envio; senão: por estrutura
LIMITE_SAIDA_BYTES = 30 * 1024 * 1024   # mesmo teto de 30 MB do app (commit 76d235f); grande: só o alvo
BLOCO_TRIANGULOS = 250_000   # blocos menores = pico menor (1 milhão custava ~260 MB de trabalho)
# Memória: o app grava o envio em disco e libera os bytes do Streamlit ANTES de compactar
# (app.py, envio em duas etapas); a compactação usa ~TRABALHO_MB por bloco. O processo
# inteiro não deve passar de DCUBIC_LIMITE_MEMORIA_MB (padrão 800).
# ponytail: estimativa fixa de trabalho; ajuste DCUBIC_LIMITE_MEMORIA_MB conforme a RAM do servidor.
TRABALHO_MB = 150
# ponytail: estimativa fixa da malha REDUZIDA já aberta no app (3D + Cortes), por triângulo;
# medida no teste de 21/10/2026 (ver docs/DECISOES-REFINO-CORTES-UPLOAD.md). Recalibre se o 3D mudar.
BYTES_APP_POR_TRIANGULO = 400
LIMITE_LOCAL_MB = 2048   # teto local: servidor iniciado com --server.maxUploadSize 2048 (docs/DECISOES.md)
LIMITE_SEGURO_MB = int(os.environ.get("DCUBIC_LIMITE_MEMORIA_MB", "1500" if GRANDE else "800"))
LIMITE_MEMBRO_ZIP = (3 if GRANDE else 2) * 1024 ** 3   # recusa zip acima de 2 GB (grande: 3 GB) descompactados
# STL real comprime ~3–10:1 (zip de teste com 2 STL: 4,6:1); 1000:1 é "zip-bomba" (Fase 1: 51 KB -> 52 MB).
RAZAO_MAX_ZIP = 100
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


def devolver_memoria() -> None:
    """Devolve ao sistema a memória já liberada que o alocador do C retém (Linux: malloc_trim;
    macOS: malloc_zone_pressure_relief). Sem isso, a RSS do processo fica bem acima da memória em
    uso depois de cada bloco grande do numpy (medido: 298 MB em uso x 935 MB de RSS no Mac)."""
    gc.collect()
    try:
        import ctypes
        if sys.platform.startswith("linux"):
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        elif sys.platform == "darwin":
            ctypes.CDLL("libc.dylib").malloc_zone_pressure_relief(None, 0)
    except Exception:
        pass


def checar_tamanho(bytes_envio: int, limite_mb: int = LIMITE_LOCAL_MB) -> None:
    """Etapa 1 do envio: recusa, com mensagem clara, o envio acima do limite efetivo
    (DCUBIC_MAX_UPLOAD_MB; 200 MB no Streamlit Cloud). Não olha o RSS (os bytes do envio
    ainda estão na RAM do Streamlit, que os recebeu antes do app rodar)."""
    mb = bytes_envio / 1024 ** 2
    if mb > limite_mb:
        if limite_mb < LIMITE_LOCAL_MB:
            raise ValueError(f"O envio tem {mb:.0f} MB. Acima de {limite_mb} MB, use \"Arquivo grande? "
                             "Enviar do computador\" (ou o link do Google Drive).")
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
    tri = [triangulos_no_arquivo(cam) for _nome, cam, _sha, _tam in recebidos]
    tri = min(sum(tri), alvo) if GRANDE else sum(min(t, alvo) for t in tri)
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
    try:
        with os.fdopen(fd, "wb") as f:
            shutil.copyfileobj(origem, _GravadorComHash(f, h), 1024 * 1024)
    except BaseException:
        _apagar(tmp)   # disco cheio / zip corrompido: não deixa .part para trás
        raise
    sha = h.hexdigest()
    final = os.path.join(destino_dir, sha + ".stl")
    os.replace(tmp, final)
    return final, sha, os.path.getsize(final)


def _stls_do_zip(z):
    """Membros .stl que serão extraídos (sem pastas, __MACOSX e arquivos ocultos)."""
    for m in z.infolist():
        base = os.path.basename(m.filename)   # basename: sem caminhos do zip
        if not (m.is_dir() or "__MACOSX" in m.filename or base.startswith(".")
                or not base.lower().endswith(".stl")):
            yield base, m


def _checar_zip(z, pasta: str) -> None:
    """Antes de extrair (envio direto e Drive): recusa membro ou soma acima de 2 GB descompactados,
    compressão anormal (zip-bomba) e falta de disco (1,1 × soma descompactada > espaço livre)."""
    membros = [m for _b, m in _stls_do_zip(z)]
    for m in membros:
        base = os.path.basename(m.filename)
        if m.file_size > LIMITE_MEMBRO_ZIP:
            raise ValueError(f"'{base}' tem mais de {LIMITE_MEMBRO_ZIP // 1024 ** 3} GB descompactado.")
        if m.file_size > 1024 ** 2 and m.file_size > RAZAO_MAX_ZIP * max(m.compress_size, 1):
            raise ValueError(f"'{base}' tem compressão anormal ({m.file_size // max(m.compress_size, 1)}:1) e "
                             "não parece um STL de verdade (possível \"zip-bomba\"). O .zip foi recusado: "
                             "envie os arquivos .stl originais, compactados normalmente.")
    precisa = sum(m.file_size for m in membros)
    if precisa > LIMITE_MEMBRO_ZIP:
        raise ValueError(f"O .zip descompactado tem {precisa / 1024 ** 2:.0f} MB e passa do limite de "
                         f"{LIMITE_MEMBRO_ZIP // 1024 ** 3} GB.")
    os.makedirs(pasta, exist_ok=True)
    livre = shutil.disk_usage(pasta).free
    if 1.1 * precisa > livre:
        raise ValueError(f"Espaço em disco insuficiente no servidor: o .zip descompactado tem "
                         f"{precisa / 1024 ** 2:.0f} MB e há {livre / 1024 ** 2:.0f} MB livres.")


def receber(envios, pasta: str = PASTA_CACHE):
    """envios: objetos-arquivo com .name (.stl ou .zip). -> lista (nome, caminho, sha1, bytes).
    Em qualquer erro, apaga o que este envio já gravou em recebidos/ e repassa o erro."""
    recebidos = []
    try:
        for arq in envios:
            nome = os.path.basename(arq.name)
            if hasattr(arq, "seek"):
                arq.seek(0)
            if nome.lower().endswith(".zip"):
                with zipfile.ZipFile(arq) as z:
                    _checar_zip(z, pasta)
                    for base, m in _stls_do_zip(z):
                        with z.open(m) as src:
                            recebidos.append((base, *_gravar(src, pasta)))
            elif nome.lower().endswith(".stl"):
                recebidos.append((nome, *_gravar(arq, pasta)))
    except BaseException:
        for _nome, cam, _sha, _tam in recebidos:
            _apagar(cam)
        raise
    return recebidos


# ── 1b. Recebendo por link do Google Drive (contorna o limite de envio do Cloud) ────

LIMITE_DRIVE_MB = 2048   # padrão de DCUBIC_MAX_DRIVE_MB (o app lê secrets/ambiente)
FATOR_DISCO = 2.5        # download (1×) + cópia/extração em recebidos/ (1×) + folga (saída, ASCII->binário)


def _apagar(caminho):
    if os.path.isfile(caminho):
        os.remove(caminho)


def _checar_limite(n, limite_bytes, livre_bytes):
    """Drive e envio em partes: recusa ao passar do limite (DCUBIC_MAX_DRIVE_MB) ou quando
    FATOR_DISCO × bytes recebidos passa do espaço livre medido no início."""
    if n > limite_bytes:
        raise ValueError(f"O arquivo passa do limite de {limite_bytes // 1024 ** 2} MB "
                         "(DCUBIC_MAX_DRIVE_MB). A transferência foi interrompida.")
    if FATOR_DISCO * n > livre_bytes:
        precisa_mb = max(1, math.ceil(FATOR_DISCO * n / 1024 ** 2))
        raise ValueError(f"Espaço em disco insuficiente no servidor: são necessários cerca de "
                         f"{precisa_mb} MB livres e há apenas {livre_bytes // 1024 ** 2} MB. "
                         "A transferência foi interrompida.")


class _GravadorLimitado:
    """Destino do gdown (que grava em blocos de 512 KB): conta os bytes e interrompe o
    download ao passar do limite ou ao faltar disco; avisa o progresso a cada ~8 MB."""

    def __init__(self, f, limite_bytes, livre_bytes, progresso):
        self.f, self.limite, self.livre, self.p = f, limite_bytes, livre_bytes, progresso
        self.n = self._ultimo = 0

    def write(self, b):
        self.n += len(b)
        _checar_limite(self.n, self.limite, self.livre)
        if self.n - self._ultimo >= 8 * 1024 ** 2:
            self._ultimo = self.n
            mb = self.n / 1024 ** 2
            # ponytail: o gdown não expõe o tamanho total; barra assintótica + MB baixados
            self.p(0.9 * mb / (mb + 300), f"Baixando… {mb:.0f} MB")
        return self.f.write(b)

    def flush(self):
        self.f.flush()

    def __getattr__(self, nome):   # repassa ao arquivo real qualquer outro atributo que o gdown pedir
        f = self.__dict__.get("f")
        if f is None:
            raise AttributeError(nome)
        return getattr(f, nome)


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
    # nome único por importação: dois usuários com o mesmo link não gravam no mesmo arquivo
    fd, bruto = tempfile.mkstemp(dir=destino_dir, prefix=f"drive_{fid[:8]}_", suffix=".part")
    p(0.0, "Baixando…")
    try:
        with os.fdopen(fd, "wb") as f:
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
        import traceback; traceback.print_exc()
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
        if not eh_zip:   # .zip: limites, razão e disco checados em receber() (_checar_zip)
            try:
                tipo_stl(caminho)
            except (ValueError, struct.error):
                raise ValueError("O arquivo não é um .stl nem um .zip válido (se veio do Drive, o link pode "
                                 "exigir login ou apontar para outro tipo de arquivo).") from None
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


# ── 1c. Recebendo do computador em partes (componente assets/envio_grande) ──────────
# O seletor nativo do Streamlit segura o arquivo inteiro na RAM (880 MiB -> pico de ~3 GB, acima
# dos 2,7 GB do Cloud). Aqui o navegador lê o arquivo em fatias (File.slice) e manda uma por vez;
# cada fatia é anexada a um .part na pasta do Drive: só uma fatia fica na memória do servidor.

def iniciar_envio(nome: str, total: int, limite_mb: int = LIMITE_DRIVE_MB, pasta: str = PASTA_CACHE) -> dict:
    """Antes da 1ª fatia: recusa extensão, tamanho declarado e falta de disco; cria o .part (nome
    único: duas sessões nunca gravam no mesmo arquivo). -> estado do envio."""
    nome = os.path.basename(nome or "")
    if not nome.lower().endswith((".stl", ".zip")):
        raise ValueError("Envie um arquivo .stl ou .zip.")
    destino_dir = os.path.join(pasta, "drive")
    os.makedirs(destino_dir, exist_ok=True)
    livre = shutil.disk_usage(destino_dir).free
    _checar_limite(int(total), limite_mb * 1024 ** 2, livre)
    fd, part = tempfile.mkstemp(dir=destino_dir, prefix="envio_", suffix=".part")
    os.close(fd)
    return {"nome": nome, "total": int(total), "n": 0, "part": part,
            "limite": limite_mb * 1024 ** 2, "livre": livre}


def cancelar_envio(estado) -> None:
    if estado:
        _apagar(estado["part"])


def receber_parte(estado, valor, limite_mb: int = LIMITE_DRIVE_MB, pasta: str = PASTA_CACHE, progresso=None):
    """Uma fatia do componente. valor = 4 bytes (tamanho do cabeçalho, little-endian) + cabeçalho JSON
    {id, nome, total, ini, ultimo} + dados. estado = envio em andamento (ou None).
    Só grava a fatia que começa em estado['n']: repetida (rerun) é ignorada e, fora de ordem, o
    navegador reenvia a partir de estado['n'] (o "ack"). Arquivo completo -> receber_baixado (mesma
    validação e cópia para recebidos/ do Drive). Em erro apaga o .part e repassa o erro.
    -> (estado, recebidos): recebidos = lista (nome, caminho, sha1, bytes) no fim, senão None."""
    tam = int.from_bytes(valor[:4], "little")
    cab = json.loads(bytes(valor[4:4 + tam]))
    dados = memoryview(valor)[4 + tam:]
    if not estado or estado["id"] != cab["id"]:   # envio novo: o anterior, se houver, é abandonado
        cancelar_envio(estado)
        # ultimo: False nos arquivos que não são o último de um envio com vários (o app junta o lote)
        estado = dict(iniciar_envio(cab["nome"], cab["total"], limite_mb, pasta), id=cab["id"],
                      ultimo=cab.get("ultimo", True))
    if estado.get("feito"):   # fatia repetida de um arquivo já completo (lote com vários)
        return estado, None
    try:
        if cab["ini"] == estado["n"]:
            if cab.get("gz"):   # fatia compactada (gzip) no navegador: STL encolhe ~6×, o envio fica mais rápido
                z = zlib.decompressobj(31)
                try:
                    dados = z.decompress(dados, 64 * 1024 ** 2)   # teto contra "gzip-bomba" (a fatia tem 16 MB)
                except zlib.error:
                    z = None
                if not z or z.unconsumed_tail or not z.eof:
                    raise ValueError("O envio recebeu uma parte compactada inválida. Tente importar de novo.")
            fim = estado["n"] + len(dados)
            if fim > estado["total"]:
                raise ValueError("O envio recebeu mais dados do que o tamanho do arquivo.")
            _checar_limite(fim, estado["limite"], estado["livre"])
            with open(estado["part"], "ab") as f:
                f.write(dados)
            estado["n"] = fim
        if estado["n"] < estado["total"]:
            return estado, None
        rec = receber_baixado(estado["part"], pasta, progresso)   # apaga o .part em qualquer caso
    except BaseException:
        cancelar_envio(estado)
        raise
    estado["feito"] = True
    if len(rec) == 1 and estado["nome"].lower().endswith(".stl"):   # .stl único: mantém o nome original
        rec = [(estado["nome"], *rec[0][1:])]
    return estado, rec


def limpar_cache_antigo(pasta: str = PASTA_CACHE, dias: float = 2) -> list:
    """Apaga arquivos com mais de `dias` dias DENTRO da pasta de cache do app (e as subpastas que
    ficarem vazias); a própria pasta fica. Recusa qualquer pasta que não se chame
    dcubic_upload_cache (protege contra caminho vazio, raiz, home, /tmp). Não segue links. -> apagados."""
    real = os.path.realpath(pasta) if pasta else ""
    if not pasta or os.path.basename(real) != os.path.basename(PASTA_CACHE) or real == os.path.dirname(real):
        raise ValueError(f"Limpeza recusada: {pasta!r} não é a pasta de cache do app.")
    if not os.path.isdir(real):
        return []
    limite = time.time() - dias * 86400
    apagados = []
    for raiz, subpastas, arquivos in os.walk(real, topdown=False):
        for nome in arquivos:
            cam = os.path.join(raiz, nome)
            try:
                if os.lstat(cam).st_mtime < limite:
                    os.remove(cam)
                    apagados.append(cam)
            except OSError:
                pass   # em uso / já apagado por outra sessão
        if raiz != real:
            try:
                os.rmdir(raiz)   # só apaga se vazia
                apagados.append(raiz)
            except OSError:
                pass
    return apagados


def processar_recebidos(recebidos, pasta: str = PASTA_CACHE, progresso=None):
    """Pós-recebimento comum ao envio e ao Drive: checagem de memória (D1) + compactação.
    Envio grande: a compactação roda num processo Python à parte (só numpy), e a memória dela volta
    inteira ao sistema no fim; o servidor do Streamlit não cresce nem fica com o heap fragmentado."""
    checar_memoria(recebidos)
    if not GRANDE:
        return compactar_recebidos(recebidos, pasta, progresso=progresso)
    import subprocess
    p = progresso or (lambda frac, texto: None)
    proc = subprocess.Popen([sys.executable, "-m", "modules.stl_compactar", "--processar"],
                            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    proc.stdin.write(json.dumps({"recebidos": [list(r) for r in recebidos], "pasta": pasta}))
    proc.stdin.close()
    fim = None
    for linha in proc.stdout:   # uma linha JSON por evento: ["p", fração, texto] | ["ok", res] | ["erro", tipo, msg]
        m = json.loads(linha)
        if m[0] == "p":
            p(m[1], m[2])
        else:
            fim = m
    proc.wait()
    if not fim:
        raise ValueError(f"A redução da malha foi interrompida (código {proc.returncode}). Tente novamente.")
    if fim[0] == "erro":
        raise (MemoriaInsuficiente if fim[1] == "MemoriaInsuficiente" else ValueError)(fim[2])
    return fim[1]


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


def _blocos(caminho: str, bloco: int = BLOCO_TRIANGULOS):
    """Itera (início, vértices float32 (b,3,3) com coordenadas finitas). Cada bloco é um
    np.memmap só do seu trecho, desfeito em seguida: o arquivo nunca fica todo mapeado."""
    n = (os.path.getsize(caminho) - 84) // 50
    for i in range(0, n, bloco):
        b = min(bloco, n - i)
        mm = np.memmap(caminho, dtype=_DT, mode="r", offset=84 + 50 * i, shape=(b,))
        v = np.array(mm["v"], dtype=np.float32)   # float32 como no STL: metade da RAM
        del mm
        ok = np.isfinite(v).all(axis=(1, 2))
        yield i, (v if ok.all() else v[ok])   # tolera triângulos com NaN/inf


def medir(caminho_bin: str) -> dict:
    """Área total, volume (teorema da divergência, unidades do STL³), caixa envolvente e nº de
    triângulos (leitura em blocos)."""
    n = (os.path.getsize(caminho_bin) - 84) // 50
    area, vol, lo, hi = 0.0, 0.0, np.full(3, np.inf), np.full(3, -np.inf)
    for _, v in _blocos(caminho_bin):
        if len(v):
            area += 0.5 * float(np.linalg.norm(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1).sum(dtype=np.float64))
            vol += _volume(v)
            lo = np.minimum(lo, v.min(axis=(0, 1)))
            hi = np.maximum(hi, v.max(axis=(0, 1)))
    return {"n": int(n), "area": float(area), "volume": abs(vol), "min": lo.tolist(), "max": hi.tolist()}


def _volume(tri) -> float:
    """Volume com sinal de triângulos (k,3,3): soma de v0·(v1×v2)/6, em float64."""
    t = np.asarray(tri, dtype=np.float64)
    return float(np.einsum("ij,ij->", t[:, 0], np.cross(t[:, 1], t[:, 2]))) / 6


# ── 3. Compactando ──────────────────────────────────────────────────────────────

def grade_comum(infos: list, alvo: int = ALVO_TRIANGULOS, total: bool = False):
    """Origem e célula únicas para o envio. A célula é a maior entre as estruturas
    (nenhuma passa do alvo); estruturas menores ficam com a mesma resolução absoluta.
    total=True (envio grande): a célula é calculada para a SOMA das áreas caber no alvo."""
    origem = np.min([i["min"] for i in infos], axis=0)
    if total:
        celula = np.sqrt(_K_GRADE * sum(i["area"] for i in infos) / alvo)
    else:
        celula = max(np.sqrt(_K_GRADE * i["area"] / alvo) for i in infos if i["area"] > 0)
    return origem, float(celula)


# ── 3b. Agrupamento ADAPTATIVO (envio grande): preserva canais e paredes finas ──────
# Na grade comum, um canal mais fino que a célula cai inteiro numa célula e vira um ponto (some).
# 1ª passada: por célula da grade base, soma VETORIAL das normais (ponderadas pela área) e soma
# das áreas. A detecção olha blocos 2×2×2 de células (um canal mais fino que a célula sempre cabe
# inteiro em algum bloco, mesmo cortado pelas bordas da grade): superfície lisa -> razão ~1; canal
# fino / parede fina / bolha (a superfície se fecha dentro do bloco) -> razão ~0 -> as células do
# bloco são subdivididas 2-16× por eixo, com >= 4 subcélulas no diâmetro estimado do canal.
# 2ª passada: cada VÉRTICE usa a subcélula da sua célula (a chave depende só da posição: sem
# rachaduras entre células finas e grossas). Chave: 3×16 bits da célula base + nível + subcélula.
# O ponto de cada agrupamento é o de menor erro quadrático aos planos dos triângulos (QEM,
# Lindstrom 2000), não a média: a média encolhe canais finos e superfícies curvas.
_BITS_BASE = 16          # até 65.536 células por eixo na grade base
LIMIAR_FINA = 0.6        # razão |Σ normal·área| / Σ área (bloco 2×2×2) abaixo da qual refina
FATOR_MAX = 16           # subdivisão máxima por eixo (célula / 16)
_VIZ = np.array([(a, b, c) for a in (0, 1) for b in (0, 1) for c in (0, 1)], dtype=np.int64)


def _chave_base(ijk):
    return (ijk[..., 0] << 32) | (ijk[..., 1] << 16) | ijk[..., 2]


def _ijk_base(k):
    return np.stack([k >> 32, (k >> 16) & 0xFFFF, k & 0xFFFF], -1)


def estatistica(caminho_bin: str, origem, celula: float):
    """1ª passada. -> (chaves base ordenadas, Σ (2·área·normal) (m,3), Σ 2·área (m,))."""
    o = np.asarray(origem, dtype=np.float64)
    ks, ss, aa = [], [], []
    for _, v in _blocos(caminho_bin):
        cr = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]).astype(np.float64)   # 2·área·normal
        k = _chave_base(np.floor((v.mean(axis=1) - o) / celula).astype(np.int64))  # pelo centróide
        uk, inv = np.unique(k, return_inverse=True)
        ks.append(uk)
        ss.append(np.stack([np.bincount(inv, cr[:, d], len(uk)) for d in range(3)], 1))
        aa.append(np.bincount(inv, np.linalg.norm(cr, axis=1), len(uk)))
        del cr, k, inv, v
        if len(ks) >= _CONSOLIDAR:
            ks, ss, aa = _somar_por_chave(ks, ss, aa)
            devolver_memoria()
    (uk,), (s,), (a,) = _somar_por_chave(ks, ss, aa)
    return uk, s, a


BLOCO_ADAPTATIVO = 100_000   # adaptativo: blocos menores (chaves e quádricas em float64 por canto)
_CONSOLIDAR = 32   # adaptativo: junta os parciais a cada 32 blocos (memória ~ malha reduzida, não o arquivo)


def _somar_por_chave(chaves, *valores):
    """Listas de (chaves únicas do bloco, somas) -> ([chaves], [somas]) com uma entrada por chave."""
    uk, inv = np.unique(np.concatenate(chaves), return_inverse=True)
    out = [[uk]]
    for lista in valores:
        x = np.concatenate(lista)
        out.append([np.stack([np.bincount(inv, x[:, j], len(uk)) for j in range(x.shape[1])], 1) if x.ndim > 1
                    else np.bincount(inv, x, len(uk))])
    return out


def _sem_repetidos(tris):
    """Triângulos (chaves) repetidos, em qualquer orientação, saem; fica a 1ª ocorrência."""
    t = np.concatenate(tris)
    _, primeiro = np.unique(np.sort(t, axis=1), axis=0, return_index=True)
    return t[np.sort(primeiro)]


def _achar(uk, ijk):
    """Posição de cada célula ijk (n,3) em uk, ou -1."""
    ok = ((ijk >= 0) & (ijk < 2 ** _BITS_BASE)).all(axis=1)
    k = _chave_base(np.where(ok[:, None], ijk, 0))
    pos = np.minimum(np.searchsorted(uk, k), len(uk) - 1)
    return np.where(ok & (uk[pos] == k), pos, -1)


def fatores(uk, soma, area2, celula: float):
    """Subdivisão por célula: 1 (lisa) ou 2..16 (canal/parede fina, detectado no bloco 2×2×2)."""
    ijk = _ijk_base(uk)
    s8, a8 = np.zeros_like(soma), np.zeros_like(area2)
    for d in _VIZ:   # bloco ancorado em cada célula: ela + 7 vizinhas (+x, +y, +z)
        pos = _achar(uk, ijk + d)
        ok = pos >= 0
        s8[ok] += soma[pos[ok]]
        a8[ok] += area2[pos[ok]]
    fino = np.linalg.norm(s8, axis=1) < LIMIAR_FINA * a8
    diam = (a8 / 2) / (np.pi * 2 * celula)   # modelo de tubo no bloco: área ≈ π · diâmetro · 2·célula
    fb = np.clip(2.0 ** np.ceil(np.log2(np.maximum(4 * celula / np.maximum(diam, 1e-12), 2))), 2, FATOR_MAX)
    f = np.ones(len(uk), np.int64)
    for d in _VIZ:   # cada célula fica com o maior fator dos blocos finos que a contêm
        pos = _achar(uk, ijk - d)
        ok = pos >= 0
        ok[ok] = fino[pos[ok]]
        f[ok] = np.maximum(f[ok], fb[pos[ok]].astype(np.int64))
    return f


def triangulos_estimados(area2, f, celula: float) -> float:
    return _K_GRADE * float((area2 / 2 * f.astype(np.float64) ** 2).sum()) / celula ** 2


def _chaves_adaptativas(v, o, celula: float, fk, ff):
    """(b,3,3) -> chaves (b,3) int64: célula base (48 bits) << 15 | nível (3) | subcélula (3×4)."""
    w = (v.reshape(-1, 3) - o) / celula
    ijk = np.floor(w).astype(np.int64)
    kb = _chave_base(ijk)
    f = np.ones(len(kb), np.int64)
    if len(fk):
        pos = np.minimum(np.searchsorted(fk, kb), len(fk) - 1)
        achou = fk[pos] == kb
        f[achou] = ff[pos[achou]]
    sub = np.minimum(np.floor((w - ijk) * f[:, None]).astype(np.int64), (f - 1)[:, None])
    nivel = np.round(np.log2(f)).astype(np.int64)
    return ((kb << 15) | (nivel << 12) | (sub[:, 0] << 8) | (sub[:, 1] << 4) | sub[:, 2]).reshape(-1, 3)


def _quadricas(v, inv, m):
    """Planos dos triângulos ponderados pela área, somados por agrupamento nos 3 cantos (6 termos de
    A = Σ w·n·nᵀ e 3 de b = Σ w·(n·v0)·n) para o ponto de menor erro quadrático (QEM). -> (m, 9)."""
    cr = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]).astype(np.float64)
    a2 = np.linalg.norm(cr, axis=1)
    n = cr / np.maximum(a2, 1e-300)[:, None]
    w = a2 / 2
    dlt = (n * v[:, 0]).sum(axis=1)
    n = np.ascontiguousarray(n.T)
    q = (w * n[0] * n[0], w * n[0] * n[1], w * n[0] * n[2], w * n[1] * n[1], w * n[1] * n[2], w * n[2] * n[2],
         w * dlt * n[0], w * dlt * n[1], w * dlt * n[2])
    cantos = [np.ascontiguousarray(inv[c::3]) for c in range(3)]
    return np.stack([sum(np.bincount(ic, x, m) for ic in cantos) for x in q], 1)


def _pontos_qem(media, q, lado, fatia: int = 200_000):
    """Ponto de menor erro aos planos de cada agrupamento (pseudo-inversa truncada: direções sem
    informação, como o eixo de um canal, ficam na média), limitado a meia subcélula da média."""
    if len(q) > fatia:
        return np.concatenate([_pontos_qem(media[i:i + fatia], q[i:i + fatia], lado[i:i + fatia])
                               for i in range(0, len(q), fatia)])
    A = np.empty((len(q), 3, 3))
    A[:, 0, 0], A[:, 0, 1], A[:, 0, 2], A[:, 1, 1], A[:, 1, 2], A[:, 2, 2] = q[:, :6].T
    A[:, 1, 0], A[:, 2, 0], A[:, 2, 1] = A[:, 0, 1], A[:, 0, 2], A[:, 1, 2]
    lam, U = np.linalg.eigh(A)
    inv = np.where(lam > 1e-3 * lam[:, -1:], 1 / np.maximum(lam, 1e-300), 0)
    r = q[:, 6:] - np.einsum("nij,nj->ni", A, media)
    dx = np.einsum("nij,nj->ni", U, inv * np.einsum("nji,nj->ni", U, r))
    lim = 0.5 * lado[:, None]
    return media + np.clip(dx, -lim, lim)


def compactar(caminho_bin: str, origem, celula: float, destino: str, finas=None):
    """Agrupamento de vértices (célula = média dos vértices). Grava STL binário.
    finas = (chaves base ordenadas, fatores) -> agrupamento adaptativo; None = grade única.
    -> (nº triângulos, volume com sinal da malha reduzida)."""
    origem32, celula32 = np.asarray(origem, dtype=np.float32), np.float32(celula)
    origem64 = np.asarray(origem, dtype=np.float64)
    chaves, somas, contagens, tris, quads = [], [], [], [], []
    for _, v in _blocos(caminho_bin, BLOCO_TRIANGULOS if finas is None else BLOCO_ADAPTATIVO):
        if finas is not None:
            k = _chaves_adaptativas(v, origem64, celula, *finas)
        else:
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
        if finas is not None:
            quads.append(_quadricas(v, inv, len(uk)))
        ok = (k[:, 0] != k[:, 1]) & (k[:, 1] != k[:, 2]) & (k[:, 0] != k[:, 2])   # não degenerados
        tris.append(k[ok])
        del k, inv, vf, ok, v
        if finas is not None and len(chaves) >= _CONSOLIDAR:
            chaves, somas, contagens, quads = _somar_por_chave(chaves, somas, contagens, quads)
            tris = [_sem_repetidos(tris)]
            devolver_memoria()
    if not tris:
        raise ValueError("STL sem triângulos válidos.")
    uk, inv = np.unique(np.concatenate(chaves), return_inverse=True)
    s, c = np.concatenate(somas), np.concatenate(contagens)
    verts = np.stack([np.bincount(inv, s[:, d], len(uk)) for d in range(3)], 1) / np.bincount(inv, c, len(uk))[:, None]
    if quads:   # adaptativo: ponto QEM (lado da subcélula pelo nível gravado na chave)
        qq = np.concatenate(quads)
        quads = True
        qq = np.stack([np.bincount(inv, qq[:, j], len(uk)) for j in range(9)], 1)
        verts = _pontos_qem(verts, qq, celula / (2.0 ** ((uk >> 12) & 7)))
        del qq
    else:
        quads = None
    t = np.concatenate(tris)
    if quads is not None and len(uk) < 2 ** 21:   # adaptativo: 3 índices de 21 bits numa chave (menos memória)
        del tris
        t = np.searchsorted(uk, t)
        o = np.sort(t, axis=1)
        _, primeiro = np.unique((o[:, 0] << 42) | (o[:, 1] << 21) | o[:, 2], return_index=True)
        del o
        faces = t[np.sort(primeiro)]
        verts = verts.astype(np.float32)   # o STL grava float32; o volume é o da malha gravada
    else:
        _, primeiro = np.unique(np.sort(t, axis=1), axis=0, return_index=True)   # duplicados (qualquer orientação)
        faces = np.searchsorted(uk, t[np.sort(primeiro)])
        del tris
    del chaves, somas, contagens, s, c, t, primeiro, inv
    tri = verts[faces]
    _gravar_stl(destino, tri)
    n, vol = len(faces), _volume(tri)
    del verts, faces, uk, tri
    devolver_memoria() if finas is not None else gc.collect()
    return n, vol


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


def compactar_recebidos(recebidos, pasta: str = PASTA_CACHE, alvo: int = ALVO_TRIANGULOS, progresso=None,
                        adaptativo: bool = GRANDE):
    """Mede e compacta, UM ARQUIVO POR VEZ e com grade comum, os arquivos já gravados por
    `receber`. Devolve uma lista de dicts: nome, caminho (STL compactado), bytes_antes,
    bytes_depois, tri_antes, tri_depois, cache, volume_original, volume_reduzida.
    adaptativo (envio grande): o envio INTEIRO fica em até `alvo` triângulos, com agrupamento
    adaptativo (canais finos preservados). Ao lado de cada saída fica <nome>.original.json
    (triângulos e volume da malha original), lido pelo app na tabela de métricas."""
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

    def binario(i):   # medida em cache, mas compactação nova (outra grade): lê o original
        if binarios[i] is None:
            cam = recebidos[i][1]
            binarios[i] = cam
            if tipo_stl(cam) == "ascii":
                binarios[i] = cam[:-4] + "_bin.stl"
                ascii_para_binario(cam, binarios[i])
        return binarios[i]

    if adaptativo:   # o alvo vale para a SOMA: memória limitada com qualquer nº de arquivos
        reduzir = [sum(info["n"] for info in infos) > alvo] * len(infos)
    else:
        reduzir = [info["n"] > alvo for info in infos]   # até o alvo, a malha passa intacta
    grandes = [info for info, r in zip(infos, reduzir) if r]
    origem, celula = (grade_comum(grandes, int(0.7 * alvo) if adaptativo else alvo, total=adaptativo)
                      if grandes else (np.zeros(3), 0.0))   # adaptativo: 30% do alvo para o refino
    if adaptativo and grandes:   # chave adaptativa: no máximo 65.536 células por eixo
        ext = float(np.max(np.max([info["max"] for info in grandes], axis=0) - origem))
        celula = max(celula, ext / (2 ** _BITS_BASE - 2))
    resultados = []
    for _tentativa in range(4):   # passou do limite: engrossa a grade e refaz
        tag = hashlib.md5(json.dumps([np.round(origem, 6).tolist(), round(celula, 9)]
                                     + (["adaptativo", alvo] if adaptativo else [])).encode()).hexdigest()[:10]
        saidas = [os.path.join(pasta, f"{sha}_{tag if reduzir[i] else 'original'}", os.path.splitext(nome)[0] + ".stl")
                  for i, (nome, _cam, sha, _tam) in enumerate(recebidos)]
        finas = [None] * len(recebidos)
        if adaptativo and any(r and not os.path.isfile(s_) for r, s_ in zip(reduzir, saidas)):
            est = {}
            for i, (nome, *_r) in enumerate(recebidos):
                if reduzir[i]:
                    p(0.35 + 0.15 * i / len(recebidos), f"Analisando {nome}…")
                    uk, soma, area2 = estatistica(binario(i), origem, celula)
                    est[i] = (uk, area2, fatores(uk, soma, area2, celula))
                    del soma
                    gc.collect()
            # orçamento: se o refino estimado passar do alvo, reduz a subdivisão de todas as células
            while (sum(triangulos_estimados(a, f, celula) for _uk, a, f in est.values()) > alvo
                   and any(f.max() > 1 for _uk, _a, f in est.values())):
                est = {i: (uk, a, np.maximum(f // 2, 1)) for i, (uk, a, f) in est.items()}
            finas = [(est[i][0][est[i][2] > 1], est[i][2][est[i][2] > 1]) if i in est else None
                     for i in range(len(recebidos))]
            del est
        resultados = []
        for i, ((nome, cam, sha, tam), info) in enumerate(zip(recebidos, infos)):
            p(0.5 + 0.45 * i / len(recebidos), f"{'Reduzindo' if reduzir[i] else 'Preparando'} {nome}…")
            saida = saidas[i]
            lado = os.path.splitext(saida)[0] + ".original.json"
            em_cache = os.path.isfile(saida)
            if em_cache:
                n_out = (os.path.getsize(saida) - 84) // 50
                vol_red = None
                if os.path.isfile(lado):
                    with open(lado) as f:
                        vol_red = json.load(f).get("volume_reduzida")
                os.utime(saida)   # em uso: a limpeza de 24 h conta a partir do último uso
            else:
                os.makedirs(os.path.dirname(saida), exist_ok=True)
                if reduzir[i]:
                    n_out, vol_red = compactar(binario(i), origem, celula, saida + ".part", finas[i])
                    vol_red = abs(vol_red)
                    os.replace(saida + ".part", saida)
                else:   # mesma malha, só em binário: origem espacial intacta
                    os.replace(binario(i), saida)
                    n_out, vol_red = info["n"], info.get("volume")
                with open(lado, "w") as f:
                    json.dump({"tri": info["n"], "volume": info.get("volume"), "volume_reduzida": vol_red}, f)
            resultados.append({"nome": os.path.splitext(nome)[0], "caminho": saida, "bytes_antes": tam,
                               "bytes_depois": os.path.getsize(saida), "tri_antes": info["n"],
                               "tri_depois": int(n_out), "cache": em_cache, "celula": celula,
                               "reduzida": reduzir[i], "volume_original": info.get("volume"),
                               "volume_reduzida": vol_red})
        if adaptativo:
            total = sum(r["tri_depois"] for r, red in zip(resultados, reduzir) if red)
            if total <= alvo:
                break
            celula *= float(np.sqrt(total / (0.9 * alvo)))
            continue
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


if __name__ == "__main__" and sys.argv[1:] == ["--processar"]:   # processo à parte (processar_recebidos)
    def _evento(*m):
        print(json.dumps(m), flush=True)
    try:
        _e = json.loads(sys.stdin.read())
        _evento("ok", compactar_recebidos([tuple(r) for r in _e["recebidos"]], _e["pasta"],
                                          progresso=lambda f, t: _evento("p", f, t)))
    except Exception as _x:
        _evento("erro", type(_x).__name__, str(_x))
    sys.exit(0)

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
    # Envio em partes: ordem, fatia repetida, fora de ordem, limite, disco, cancelamento, conclusão.
    with open(r[0]["caminho"], "rb") as a:
        cubo_bin = a.read()   # 84 + 12 × 50 = 684 bytes

    def fatia(id_, ini, dados, nome="dente.stl", total=len(cubo_bin), gz=False):
        c = json.dumps({"id": id_, "nome": nome, "total": total, "ini": ini, "gz": gz}).encode()
        return len(c).to_bytes(4, "little") + c + (_gzip(dados) if gz else dados)

    def _gzip(b):
        z = zlib.compressobj(6, zlib.DEFLATED, 31)
        return z.compress(b) + z.flush()

    def parts():
        return [x for x in os.listdir(os.path.join(d, "drive")) if x.startswith("envio_")]
    est, rec = receber_parte(None, fatia("a", 0, cubo_bin[:300]), pasta=d)
    assert est["n"] == 300 and rec is None and len(parts()) == 1
    est, rec = receber_parte(est, fatia("a", 0, cubo_bin[:300]), pasta=d)        # repetida (rerun)
    assert est["n"] == 300 and os.path.getsize(est["part"]) == 300
    est, rec = receber_parte(est, fatia("a", 600, cubo_bin[600:]), pasta=d)      # adiantada: não grava
    assert est["n"] == 300 and rec is None
    est, rec = receber_parte(est, fatia("a", 300, cubo_bin[300:]), pasta=d)      # conclui -> receber_baixado
    assert rec and rec[0][0] == "dente.stl" and rec[0][3] == len(cubo_bin) and os.path.isfile(rec[0][1])
    assert not parts(), "o .part deveria ter sido apagado"
    for erro, chamada in [
        ("limite", lambda: receber_parte(None, fatia("b", 0, b"", total=3 * 1024 ** 2), limite_mb=2, pasta=d)),
        ("extensão", lambda: receber_parte(None, fatia("c", 0, b"", nome="x.exe"), pasta=d)),
    ]:
        try:
            chamada()
            raise AssertionError(f"{erro} aceito")
        except ValueError:
            assert not parts()
    est, _ = receber_parte(None, fatia("d", 0, cubo_bin[:100]), pasta=d)
    est["livre"] = 300   # falta de disco simulada: 2,5 × 200 bytes > 300
    try:
        receber_parte(est, fatia("d", 100, cubo_bin[100:200]), pasta=d)
        raise AssertionError("falta de disco não detectada")
    except ValueError as e:
        assert "disco" in str(e) and not parts()
    est, _ = receber_parte(None, fatia("e", 0, cubo_bin[:100]), pasta=d)
    est2, _ = receber_parte(est, fatia("f", 0, cubo_bin[:100]), pasta=d)        # envio novo abandona o anterior
    assert not os.path.exists(est["part"]) and len(parts()) == 1
    cancelar_envio(est2)                                                           # botão Cancelar
    assert not parts()
    html = b"<!DOCTYPE html><title>x</title>"
    try:   # conclusão chama a validação: conteúdo que não é STL é recusado e o .part apagado
        receber_parte(None, fatia("g", 0, html, total=len(html)), pasta=d)
        raise AssertionError("HTML aceito")
    except ValueError:
        assert not parts()
    # Vários arquivos (seletor único): "ultimo" vem do cabeçalho (ausente = True); fatia repetida de um
    # arquivo já completo é ignorada (não chama receber_baixado de novo sobre o .part apagado).
    c = json.dumps({"id": "h", "nome": "Dentina.stl", "total": len(cubo_bin), "ini": 0, "ultimo": False}).encode()
    est, rec = receber_parte(None, len(c).to_bytes(4, "little") + c + cubo_bin, pasta=d)
    assert est["ultimo"] is False and est["feito"] and rec[0][0] == "Dentina.stl"
    assert receber_parte(est, len(c).to_bytes(4, "little") + c + cubo_bin, pasta=d) == (est, None)
    est, rec2 = receber_parte(est, fatia("i", 0, cubo_bin, nome="Canal.stl"), pasta=d)
    assert est["ultimo"] is True and rec2[0][0] == "Canal.stl" and not parts()
    # Fatias compactadas (gzip) pelo navegador: o "ack" conta bytes do arquivo original.
    est, rec = receber_parte(None, fatia("j", 0, cubo_bin[:300], gz=True), pasta=d)
    assert est["n"] == 300 and rec is None
    est, rec = receber_parte(est, fatia("j", 300, cubo_bin[300:], gz=True), pasta=d)
    assert rec and rec[0][3] == len(cubo_bin) and not parts()
    est, _ = receber_parte(None, fatia("k", 0, cubo_bin[:100]), pasta=d)
    ruim = fatia("k", 100, cubo_bin[100:200], gz=True)
    try:   # gzip corrompido (cortado) é recusado e o .part apagado
        receber_parte(est, ruim[:-10], pasta=d)
        raise AssertionError("gzip inválido aceito")
    except ValueError:
        assert not parts()
    print("envio em partes OK")
    # Envio grande (adaptativo): canais de 2, 4 e 8 un. numa grade de ~7 un. continuam inteiros
    # (no agrupamento comum eles somem); o total respeita o alvo; o volume quase não muda.
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
    import gerar_stl_teste as _g
    _g.sintetico(os.path.join(d, "sint.stl"), 400_000)
    r, = compactar_recebidos([("sint.stl", os.path.join(d, "sint.stl"), "sint", 0)], pasta=d, alvo=300_000,
                             adaptativo=True)
    v = np.fromfile(r["caminho"], dtype=_DT, offset=84)["v"].astype(np.float64)
    cen = v.mean(axis=1)
    for x, y, diam in _g.CANAIS:
        sel = np.hypot(cen[:, 0] - x, cen[:, 1] - y) < diam / 2 + 3 * r["celula"]
        razao = abs(_volume(v[sel])) / (math.pi * (diam / 2) ** 2 * (_g.Z1 - _g.Z0))
        assert razao > 0.8, (diam, razao, r["celula"])
    assert r["tri_depois"] <= 300_000 and abs(r["volume_reduzida"] / r["volume_original"] - 1) < 0.01, r
    print(f"adaptativo OK: {r['tri_antes']} -> {r['tri_depois']} triângulos, célula {r['celula']:.1f} un., "
          "canais de 2, 4 e 8 un. preservados")
