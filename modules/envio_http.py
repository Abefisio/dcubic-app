"""
DCubic — envio de STL de até 3 GB direto para o disco (modo grande: DCUBIC_ENVIO_GRANDE=1, VPS).

Por que assim: o Streamlit não tem rota HTTP própria e o envio pelo componente (websocket) passa
pela memória do processo. Aqui um handler Tornado é registrado NO MESMO servidor do Streamlit
(mesma porta e mesmo endereço: nada muda no Traefik) e cada parte vai direto para o disco, em
pedaços de 64 KB (stream_request_body), sem passar pelo websocket nem pela sessão do Streamlit.

  POST   /dcubic-envio/iniciar          {nome, total, chave} -> {id, bloco, max, mapa}
  PUT    /dcubic-envio/<id>?ini=<byte>  parte de até 32 MiB, alinhada a 1 MiB (gzip opcional:
                                        X-DCubic-Gz: 1); X-DCubic-Sha = SHA-256 de cada bloco de 1 MiB
  GET    /dcubic-envio/<id>             -> {mapa}: "1" = bloco já no disco (retomada)
  POST   /dcubic-envio/<id>/concluir    {hash} -> confere tamanho + hash relendo o disco
  DELETE /dcubic-envio/<id>             cancela: apaga o parcial (ou o arquivo pronto)

Autenticação: token aleatório da sessão logada (emitir_token), no cabeçalho X-DCubic-Token; cada
envio pertence ao usuário que o iniciou. Sem token válido: 403.
Integridade: cada bloco de 1 MiB é conferido (SHA-256) na chegada e só então marcado no mapa; ao
concluir, o arquivo é relido, o tamanho e cada bloco conferidos de novo, e o hash composto
SHA-256(SHA-256 dos blocos, em ordem) tem de bater com o calculado pelo navegador.
Retomada: o mapa diz quais blocos já estão no disco; o navegador reenvia só os que faltam (queda
de conexão, ou o mesmo arquivo escolhido de novo: mesma "chave" = nome|tamanho|data).
Disco: recusa se houver menos que 3 × o tamanho livre. Limpeza: parciais, prontos e cache com
mais de 24 h (na partida do app e a cada envio novo).
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import time
import zlib

import tornado.ioloop
import tornado.web

PASTA = os.path.abspath(os.environ.get("DCUBIC_UPLOAD_DIR", "./uploads"))
LIMITE_BYTES = 3 * 1024 ** 3   # 3 GB por arquivo (3.221.225.472 bytes)
BLOCO = 1024 ** 2              # unidade de conferência e de retomada
PARTE_MAX = 32 * BLOCO         # cada requisição leva até 32 MiB
FATOR_DISCO = 3                # recusa se o disco livre < 3 × o arquivo
VALIDADE_S = 24 * 3600         # limpeza (24 h) e validade do token sem uso
ROTA = "/dcubic-envio"

_tokens: dict = {}             # token -> [usuário, expira]


def _gb(n):
    return f"{n / 1024 ** 3:.2f}".replace(".", ",")


def _sub(*p):
    d = os.path.join(PASTA, *p)
    os.makedirs(d, exist_ok=True)
    return d


def pasta_cache() -> str:
    """Pasta da etapa 2 (stl_compactar): medidas, malhas reduzidas e o cache de exibição."""
    return _sub("cache")


# ── Token da sessão ─────────────────────────────────────────────────────────────

def emitir_token(usuario: str, atual: str | None = None) -> str:
    """Token da sessão logada; renovado a cada execução do app (vale 24 h sem uso)."""
    if not atual or _tokens.get(atual, [None])[0] != usuario:
        atual = secrets.token_urlsafe(32)
    _tokens[atual] = [usuario, time.time() + VALIDADE_S]
    return atual


def revogar_token(token) -> None:
    _tokens.pop(token, None)


def _usuario(token):
    t = _tokens.get(token or "")
    if not t or t[1] < time.time():
        return None
    t[1] = time.time() + VALIDADE_S   # em uso: renova
    return t[0]


# ── Estado em disco ─────────────────────────────────────────────────────────────

def _cam(id_, ext):
    return os.path.join(PASTA, "parciais", id_ + ext)


def _estado(id_):
    try:
        with open(_cam(id_, ".json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _nblocos(total):
    return -(-total // BLOCO)


def _mapa(id_, n) -> str:
    with open(_cam(id_, ".sha"), "rb") as f:
        h = f.read()
    zero = b"\0" * 32
    return "".join("0" if h[32 * b:32 * b + 32] in (zero, b"") else "1" for b in range(n))


def _marcar(id_, blocos: dict) -> None:
    """Grava o SHA-256 de blocos conferidos ({índice: digest}); digest zero = falta."""
    with open(_cam(id_, ".sha"), "r+b") as f:
        for b, d in blocos.items():
            f.seek(32 * b)
            f.write(d)


def _apagar_parcial(id_):
    for ext in (".part", ".sha", ".json"):
        try:
            os.remove(_cam(id_, ext))
        except OSError:
            pass


def limpar_antigos(agora: float | None = None) -> list:
    """Apaga envios parciais, arquivos prontos e cache com mais de 24 h (pelo arquivo mais recente
    de cada envio). Só mexe nas subpastas do app (parciais, prontos, cache) de DCUBIC_UPLOAD_DIR."""
    limite = (agora or time.time()) - VALIDADE_S
    apagados = []
    grupos = {}
    for nome in os.listdir(_sub("parciais")):
        try:
            m = os.lstat(os.path.join(PASTA, "parciais", nome)).st_mtime
        except OSError:
            continue
        id_ = nome.split(".")[0]
        grupos[id_] = max(grupos.get(id_, 0), m)
    for id_, m in grupos.items():
        if m < limite:
            _apagar_parcial(id_)
            apagados.append(f"parciais/{id_}")
    for id_ in os.listdir(_sub("prontos")):
        d = os.path.join(PASTA, "prontos", id_)
        try:
            m = max([os.lstat(d).st_mtime] + [os.lstat(os.path.join(d, x)).st_mtime for x in os.listdir(d)])
        except OSError:
            continue
        if m < limite:
            shutil.rmtree(d, ignore_errors=True)
            apagados.append(f"prontos/{id_}")
    raiz = _sub("cache")
    for dirpath, _subs, arquivos in os.walk(raiz, topdown=False):
        for nome in arquivos:
            c = os.path.join(dirpath, nome)
            try:
                if os.lstat(c).st_mtime < limite:
                    os.remove(c)
                    apagados.append(os.path.relpath(c, PASTA))
            except OSError:
                pass
        if dirpath != raiz:
            try:
                os.rmdir(dirpath)   # só se vazia
            except OSError:
                pass
    return apagados


# ── Arquivo pronto -> etapa 2 do app ────────────────────────────────────────────

def recebidos(id_: str, usuario: str) -> list:
    """Envio concluído (e conferido) deste usuário -> lista (nome, caminho, sha, bytes) para
    stl_compactar.compactar_recebidos. .zip: extraído pela mesma rotina do Drive."""
    if not id_.isalnum():
        raise ValueError("Envio inválido.")
    d = os.path.join(PASTA, "prontos", id_)
    try:
        with open(os.path.join(d, "envio.json")) as f:
            e = json.load(f)
    except (OSError, ValueError):
        raise ValueError("O arquivo enviado não foi encontrado no servidor (expirou ou foi cancelado). "
                         "Envie de novo.") from None
    if e["usuario"] != usuario:
        raise ValueError("Este envio pertence a outro usuário.")
    cam = os.path.join(d, e["nome"])
    if e["nome"].lower().endswith(".zip"):
        from modules import stl_compactar as c
        destino = os.path.join(_sub("cache", "drive"), id_ + ".zip")
        os.replace(cam, destino)
        return c.receber_baixado(destino, pasta_cache())   # extrai e apaga o .zip
    return [(e["nome"], cam, e["hash"], e["total"])]


def apagar(id_: str, usuario: str) -> None:
    """Cancela/descarta um envio deste usuário (parcial ou pronto)."""
    if not id_.isalnum():
        return
    est = _estado(id_)
    if est and est["usuario"] == usuario:
        _apagar_parcial(id_)
    d = os.path.join(PASTA, "prontos", id_)
    try:
        with open(os.path.join(d, "envio.json")) as f:
            dono = json.load(f)["usuario"]
    except (OSError, ValueError, KeyError):
        return
    if dono == usuario:
        shutil.rmtree(d, ignore_errors=True)


def _conferir(id_, n):
    """Relê o arquivo do disco: blocos que não batem com o SHA-256 gravado na chegada e o hash
    composto (SHA-256 dos SHA-256 dos blocos). Roda numa thread à parte (não trava o servidor)."""
    with open(_cam(id_, ".sha"), "rb") as f:
        esperado = f.read()
    ruins, composto = [], hashlib.sha256()
    with open(_cam(id_, ".part"), "rb") as f:
        for b in range(n):
            d = hashlib.sha256(f.read(BLOCO)).digest()
            composto.update(d)
            if d != esperado[32 * b:32 * b + 32]:
                ruins.append(b)
    return ruins, composto.hexdigest()


# ── Handler HTTP (Tornado, dentro do servidor do Streamlit) ─────────────────────

class _Erro(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


class _Gravacao:
    """Uma parte (PUT): escreve no .part a partir de `ini`, confere e marca cada bloco de 1 MiB."""

    def __init__(self, id_, est, ini, shas, gz):
        total = est["total"]
        if ini < 0 or ini % BLOCO or ini >= total:
            raise _Erro(400, "Início da parte inválido.")
        self.esperados = [bytes.fromhex(h) for h in shas.split(",") if h]
        self.comprimento = min(len(self.esperados) * BLOCO, total - ini)
        if not self.esperados or self.comprimento > PARTE_MAX or _nblocos(self.comprimento) != len(self.esperados):
            raise _Erro(400, "Parte inválida (até 32 MiB, um SHA-256 por bloco de 1 MiB).")
        self.id, self.total, self.b = id_, total, ini // BLOCO
        self.b0 = self.b
        self.falta, self.nb, self.h = self.comprimento, 0, hashlib.sha256()
        self.z = zlib.decompressobj(31) if gz else None
        self.f = open(_cam(id_, ".part"), "r+b")
        self.f.seek(ini)
        self.erro = None

    def escrever(self, dados):
        if self.erro:
            return
        try:
            if self.z:
                dados = self.z.decompress(dados, self.falta + 1)   # teto: nunca além do anunciado
            if len(dados) > self.falta:
                raise _Erro(400, "A parte tem mais dados do que o anunciado.")
            self.falta -= len(dados)
            mv = memoryview(dados)
            while mv:
                tam_bloco = min(BLOCO, self.total - self.b * BLOCO)
                k = min(len(mv), tam_bloco - self.nb)
                self.f.write(mv[:k])
                self.h.update(mv[:k])
                self.nb += k
                mv = mv[k:]
                if self.nb == tam_bloco:   # bloco completo: confere e marca (retomada fina)
                    d = self.h.digest()
                    if d != self.esperados[self.b - self.b0]:
                        raise _Erro(422, "Uma parte chegou corrompida (SHA-256 diferente); será reenviada.")
                    self.f.flush()
                    _marcar(self.id, {self.b: d})
                    self.b, self.nb, self.h = self.b + 1, 0, hashlib.sha256()
        except _Erro as e:
            self.erro = e
        except OSError as e:
            self.erro = _Erro(507, f"Não foi possível gravar no disco do servidor ({e.strerror}).")
        except zlib.error:
            self.erro = _Erro(400, "Parte compactada inválida.")
        if self.erro:
            self.fechar()

    def concluir(self):
        if not self.erro and (self.falta or (self.z and (not self.z.eof or self.z.unused_data))):
            self.erro = _Erro(400, "A parte chegou incompleta.")
        self.fechar()
        if self.erro:
            raise self.erro

    def fechar(self):
        if not self.f.closed:
            self.f.close()


@tornado.web.stream_request_body
class _Handler(tornado.web.RequestHandler):
    _g = None   # gravação da parte (PUT); definido no prepare

    def check_xsrf_cookie(self):
        """Proteção própria: token no cabeçalho X-DCubic-Token (cookie não basta para gravar)."""

    def prepare(self):
        self.usuario = _usuario(self.request.headers.get("X-DCubic-Token"))
        if not self.usuario:
            raise tornado.web.HTTPError(403)
        self._corpo, self._g = bytearray(), None
        if self.request.method == "PUT":
            try:
                id_ = self.path_args[0]
                est = self._meu(id_)
                self._g = _Gravacao(id_, est, int(self.get_query_argument("ini", "-1")),
                                    self.request.headers.get("X-DCubic-Sha", ""),
                                    self.request.headers.get("X-DCubic-Gz") == "1")
            except _Erro as e:
                self._responder(e.status, {"erro": str(e)})
            except ValueError:
                self._responder(400, {"erro": "Parte inválida."})
            except OSError:
                self._responder(404, {"erro": "Envio não encontrado no servidor. Escolha o arquivo de novo."})

    def data_received(self, chunk):
        if self._finished:
            return
        if self._g:
            self._g.escrever(chunk)
        else:
            self._corpo += chunk
            if len(self._corpo) > 65536:
                self._responder(413, {"erro": "Pedido grande demais."})

    def on_connection_close(self):   # queda no meio da parte: os blocos completos já ficaram marcados
        if self._g:
            self._g.fechar()

    def _responder(self, status, dados):
        if not self._finished:
            self.set_status(status)
            self.finish(dados)

    def _meu(self, id_):
        est = _estado(id_)
        if not est:
            raise _Erro(404, "Envio não encontrado no servidor (expirou ou foi cancelado). Escolha o arquivo de novo.")
        if est["usuario"] != self.usuario:
            raise _Erro(403, "Este envio pertence a outro usuário.")
        return est

    def _json(self):
        try:
            return json.loads(bytes(self._corpo) or b"{}")
        except ValueError:
            raise _Erro(400, "Pedido inválido.") from None

    async def _executar(self, fn, *a):
        if self._finished:
            return
        try:
            r = fn(*a)
            if hasattr(r, "__await__"):
                r = await r
            self._responder(200, r)
        except _Erro as e:
            self._responder(e.status, {"erro": str(e)})

    # rotas
    async def post(self, id_=None):
        if id_ is None:
            await self._executar(self._iniciar)
        else:
            await self._executar(self._concluir, id_)

    async def put(self, id_):
        await self._executar(self._parte)

    async def get(self, id_):
        await self._executar(lambda: {"mapa": _mapa(id_, _nblocos(self._meu(id_)["total"]))})

    async def delete(self, id_):
        await self._executar(lambda: apagar(id_, self.usuario) or {"ok": True})

    def _parte(self):
        self._g.concluir()
        return {"ok": True}

    def _iniciar(self):
        d = self._json()
        nome, chave = os.path.basename(str(d.get("nome", ""))), str(d.get("chave", ""))[:400]
        try:
            total = int(d.get("total", 0))
        except (TypeError, ValueError):
            total = 0
        if not nome.lower().endswith((".stl", ".zip")):
            raise _Erro(400, "Envie um arquivo .stl ou .zip.")
        if total <= 0:
            raise _Erro(400, f"\"{nome}\" está vazio.")
        if total > LIMITE_BYTES:
            raise _Erro(413, f"\"{nome}\" tem {_gb(total)} GB e passa do limite de 3 GB por arquivo "
                             f"({LIMITE_BYTES:,} bytes).".replace(",", "."))
        limpar_antigos()
        n = _nblocos(total)
        for x in os.listdir(_sub("parciais")):   # retomada: mesmo usuário e mesmo arquivo (nome|tamanho|data)
            est = _estado(x[:-5]) if x.endswith(".json") else None
            if est and est["usuario"] == self.usuario and est["chave"] == chave and est["total"] == total:
                print(f"[dcubic-envio {time.strftime('%H:%M:%S')}] retomada {est['id']} {nome} ({total} bytes)", flush=True)
                return {"id": est["id"], "bloco": BLOCO, "max": PARTE_MAX, "mapa": _mapa(est["id"], n)}
        livre = shutil.disk_usage(_sub("parciais")).free
        if livre < FATOR_DISCO * total:
            raise _Erro(507, f"Espaço em disco insuficiente no servidor: \"{nome}\" ({_gb(total)} GB) precisa de "
                             f"{_gb(FATOR_DISCO * total)} GB livres (3 × o tamanho) e há {_gb(livre)} GB.")
        id_ = secrets.token_hex(16)
        open(_cam(id_, ".part"), "wb").close()
        with open(_cam(id_, ".sha"), "wb") as f:
            f.write(b"\0" * 32 * n)
        with open(_cam(id_, ".json"), "w") as f:
            json.dump({"id": id_, "usuario": self.usuario, "nome": nome, "total": total, "chave": chave,
                       "criado": time.time()}, f)
        print(f"[dcubic-envio {time.strftime('%H:%M:%S')}] iniciado {id_} {nome} ({total} bytes)", flush=True)
        return {"id": id_, "bloco": BLOCO, "max": PARTE_MAX, "mapa": "0" * n}

    async def _concluir(self, id_):
        est, hash_cliente = self._meu(id_), str(self._json().get("hash", ""))
        n = _nblocos(est["total"])
        mapa = _mapa(id_, n)
        if "0" in mapa:
            return {"ok": False, "mapa": mapa}
        if os.path.getsize(_cam(id_, ".part")) != est["total"]:
            _marcar(id_, {b: b"\0" * 32 for b in range(n)})
            raise _Erro(422, "O tamanho do arquivo no servidor não confere; o envio será refeito.")
        t0 = time.time()
        ruins, composto = await tornado.ioloop.IOLoop.current().run_in_executor(None, _conferir, id_, n)
        if ruins:   # bloco corrompido no disco: volta a faltar e o navegador o reenvia
            _marcar(id_, {b: b"\0" * 32 for b in ruins})
            return {"ok": False, "mapa": _mapa(id_, n)}
        if composto != hash_cliente:
            raise _Erro(422, "O hash do arquivo recebido não confere com o do computador.")
        d = os.path.join(_sub("prontos"), id_)
        os.makedirs(d, exist_ok=True)
        os.replace(_cam(id_, ".part"), os.path.join(d, est["nome"]))
        with open(os.path.join(d, "envio.json"), "w") as f:
            json.dump({"usuario": est["usuario"], "nome": est["nome"], "total": est["total"], "hash": composto}, f)
        _apagar_parcial(id_)
        print(f"[dcubic-envio {time.strftime('%H:%M:%S')}] concluído {id_} {est['nome']} ({est['total']} bytes, tamanho e SHA-256 "
              f"conferidos em {time.time() - t0:.1f} s)", flush=True)
        return {"ok": True, "hash": composto}


def registrar() -> bool:
    """Registra as rotas /dcubic-envio no servidor Tornado do Streamlit (1× por processo; chamado
    a cada execução do app). O app Tornado vem do cliente websocket da sessão atual.
    ponytail: usa o objeto interno do Streamlit 1.50 (Runtime.get_client -> .application)."""
    from streamlit.runtime import Runtime
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    ctx = get_script_run_ctx()
    app = getattr(Runtime.instance().get_client(ctx.session_id) if ctx else None, "application", None)
    if app is None:
        return False
    if not getattr(app, "_dcubic_envio", False):
        app._dcubic_envio = True
        id_ = "([0-9a-f]{32})"
        app.add_handlers(r".*", [(rf"{ROTA}/iniciar", _Handler), (rf"{ROTA}/{id_}", _Handler),
                                 (rf"{ROTA}/{id_}/concluir", _Handler)])
        limpar_antigos()
    return True


if __name__ == "__main__":
    # Autoverificação: servidor Tornado só com estas rotas, numa pasta temporária, falando HTTP de verdade.
    import asyncio
    import gzip
    import tempfile
    import threading
    import urllib.error
    import urllib.request

    PASTA = tempfile.mkdtemp()
    app = tornado.web.Application([(rf"{ROTA}/iniciar", _Handler), (rf"{ROTA}/([0-9a-f]{{32}})", _Handler),
                                   (rf"{ROTA}/([0-9a-f]{{32}})/concluir", _Handler)])
    pronto = threading.Event()
    porta = []

    def _servir():
        asyncio.set_event_loop(asyncio.new_event_loop())
        s, = tornado.netutil.bind_sockets(0, "127.0.0.1")
        porta.append(s.getsockname()[1])
        tornado.httpserver.HTTPServer(app).add_sockets([s])
        pronto.set()
        tornado.ioloop.IOLoop.current().start()

    import tornado.httpserver
    import tornado.netutil
    threading.Thread(target=_servir, daemon=True).start()
    pronto.wait()

    def req(metodo, caminho, corpo=None, token=None, cab=None):
        r = urllib.request.Request(f"http://127.0.0.1:{porta[0]}{ROTA}/{caminho}", data=corpo, method=metodo,
                                   headers={**({"X-DCubic-Token": token} if token else {}), **(cab or {})})
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            corpo = e.read()
            return e.code, json.loads(corpo) if corpo.startswith(b"{") else {}

    def js(d):
        return json.dumps(d).encode()

    dados = os.urandom(2 * BLOCO + BLOCO // 2)   # 3 blocos: 1 MiB, 1 MiB, 0,5 MiB
    shas = [hashlib.sha256(dados[i:i + BLOCO]).hexdigest() for i in range(0, len(dados), BLOCO)]
    composto = hashlib.sha256(b"".join(bytes.fromhex(h) for h in shas)).hexdigest()
    ana, bia = emitir_token("ana"), emitir_token("bia")
    novo = {"nome": "dente.stl", "total": len(dados), "chave": "dente.stl|2621440|1"}

    assert req("POST", "iniciar", js(novo))[0] == 403                                     # sem token
    assert req("POST", "iniciar", js({**novo, "nome": "x.exe"}), ana)[0] == 400           # extensão
    st_, r = req("POST", "iniciar", js({**novo, "total": LIMITE_BYTES + 1}), ana)         # acima de 3 GB
    assert st_ == 413 and "3 GB" in r["erro"], r
    FATOR_DISCO = 10 ** 15                                                                # disco "cheio"
    st_, r = req("POST", "iniciar", js(novo), ana)
    assert st_ == 507 and "3 × o tamanho" in r["erro"], r
    FATOR_DISCO = 3
    st_, r = req("POST", "iniciar", js(novo), ana)
    assert st_ == 200 and r["mapa"] == "000", r
    id_ = r["id"]
    st_, r = req("PUT", f"{id_}?ini=0", gzip.compress(dados[:2 * BLOCO]), ana,            # 2 blocos, gzip
                 {"X-DCubic-Sha": ",".join(shas[:2]), "X-DCubic-Gz": "1"})
    assert st_ == 200, r
    assert req("GET", id_, token=ana)[1]["mapa"] == "110"
    assert req("GET", id_, token=bia)[0] == 403                                          # outro usuário
    st_, r = req("PUT", f"{id_}?ini={2 * BLOCO}", dados[2 * BLOCO:], ana, {"X-DCubic-Sha": shas[0]})
    assert st_ == 422 and req("GET", id_, token=ana)[1]["mapa"] == "110", r              # SHA errado: não marca
    assert req("PUT", f"{id_}?ini=7", dados[:10], ana, {"X-DCubic-Sha": shas[0]})[0] == 400   # desalinhado
    st_, r = req("POST", "iniciar", js(novo), ana)                                        # retomada (mesma chave)
    assert r["id"] == id_ and r["mapa"] == "110", r
    assert req("PUT", f"{id_}?ini={2 * BLOCO}", dados[2 * BLOCO:], ana, {"X-DCubic-Sha": shas[2]})[0] == 200
    assert req("POST", f"{id_}/concluir", js({"hash": "0" * 64}), ana)[0] == 422          # hash composto errado
    st_, r = req("POST", f"{id_}/concluir", js({"hash": composto}), ana)
    assert st_ == 200 and r["ok"] and r["hash"] == composto, r
    (nome, cam, sha, tam), = recebidos(id_, "ana")
    with open(cam, "rb") as f:
        assert f.read() == dados and sha == composto and tam == len(dados) and nome == "dente.stl"
    apagar(id_, "ana")
    assert not os.path.exists(os.path.dirname(cam))
    # bloco corrompido no disco depois de conferido: o concluir devolve o mapa e o bloco volta a faltar
    st_, r = req("POST", "iniciar", js({**novo, "chave": "outro"}), ana)
    id2 = r["id"]
    req("PUT", f"{id2}?ini=0", dados, ana, {"X-DCubic-Sha": ",".join(shas)})
    with open(_cam(id2, ".part"), "r+b") as f:
        f.seek(BLOCO + 5)
        f.write(b"X")
    st_, r = req("POST", f"{id2}/concluir", js({"hash": composto}), ana)
    assert st_ == 200 and not r["ok"] and r["mapa"] == "101", r
    assert req("DELETE", id2, token=ana)[0] == 200 and not os.path.exists(_cam(id2, ".part"))   # Cancelar
    # limpeza de 24 h e token revogado
    st_, r = req("POST", "iniciar", js({**novo, "chave": "velho"}), ana)
    for ext in (".part", ".sha", ".json"):
        os.utime(_cam(r["id"], ext), (time.time() - 25 * 3600,) * 2)
    assert f"parciais/{r['id']}" in limpar_antigos() and not _estado(r["id"])
    revogar_token(ana)
    assert req("POST", "iniciar", js(novo), ana)[0] == 403
    print("envio_http OK: protocolo, limite de 3 GB, disco 3×, SHA-256 por bloco, retomada, hash final, "
          "corrupção, cancelar, limpeza de 24 h e token")
