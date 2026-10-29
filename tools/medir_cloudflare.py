#!/usr/bin/env python3
"""
Medição do envio grande: caminho DIRETO x caminho pela CLOUDFLARE (proxy, nuvem laranja), contra o
contêiner temporário "teste-envio" da VPS (feat/envio-rapido 446ea16, tools/servidor_teste_envio.py).
Não toca em app.dcubic nem no contêiner de produção.

Replica o protocolo do navegador (assets/envio_grande/index.html + modules/envio_http.py):
  POST iniciar -> 4 PUTs em paralelo (a parte começa em 4 MiB e acompanha a velocidade: ~20 s por
  pedido, teto de 16 MiB; SHA-256 por bloco de 1 MiB) -> POST concluir (o servidor relê e confere) -> DELETE.
Os dados são gerados em memória e são incompressíveis (o navegador também os mandaria sem gzip, pela
regra dos 8 %). Motivo: o Mac está sem espaço livre e o sintetico-3gb.stl existe só no iCloud.
ponytail: sem gzip e sem GET do mapa após uma queda (reenvia a faixa inteira); 4 conexões HTTP/1.1,
enquanto o navegador multiplexa em HTTP/2 até a Cloudflare.

  caffeinate -i python3 tools/medir_cloudflare.py             completa: sink + 300 MiB ×3 + 3 GB ×2 por caminho
  caffeinate -i python3 tools/medir_cloudflare.py --rapido    conferência: sink + 300 MiB ×1 por caminho
  python3 tools/medir_cloudflare.py --autoteste               protocolo contra um servidor local (sem VPS)
Relatório (regravado a cada rodada): ~/Desktop/RELATORIOS-CLAUDE/cloudflare-teste-medicao.txt
"""
import argparse
import collections
import hashlib
import http.client
import json
import os
import socket
import ssl
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

VPS_IP = "152.239.113.183"
SSH = ["ssh", "-i", os.path.expanduser("~/.ssh/unlock_vps_ed25519"), "-o", "IdentitiesOnly=yes",
       "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", f"root@{VPS_IP}"]
CAMINHOS = {"direto": "https://teste-envio-direto.dcubic.reloadcursos.com",
            "proxy": "https://teste-envio.dcubic.reloadcursos.com"}
RELATORIO = os.path.expanduser("~/Desktop/RELATORIOS-CLAUDE/cloudflare-teste-medicao.txt")
MiB, MB = 1024 ** 2, 1e6
BLOCO, PARTE_MAX, PARALELO = MiB, 16 * MiB, 4
TAM_3GB = 3_199_993_684   # mesmo tamanho do sintetico-3gb.stl das medições anteriores
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130 Safari/537.36 dcubic-medicao")
BASE = os.urandom(BLOCO)


def ssh(cmd):
    return subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=120).stdout


def bloco(k, total):
    """Bloco k do "arquivo": determinístico (o reenvio é idêntico) e incompressível."""
    return (k.to_bytes(8, "little") + BASE[8:])[:min(BLOCO, total - k * BLOCO)]


def conectar(base, timeout=180):
    u = urlsplit(base)
    if u.scheme == "https":
        return http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=timeout,
                                           context=ssl.create_default_context())
    return http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)


def pedir_json(base, metodo, caminho, corpo=None, token=None, timeout=300, tentativas=6):
    """Pedido pequeno numa conexão nova; repete em queda de rede e 5xx. -> (status, json)."""
    for t in range(tentativas):
        c = conectar(base, timeout)
        try:
            c.request(metodo, caminho, body=None if corpo is None else json.dumps(corpo),
                      headers={"User-Agent": UA, "Content-Type": "application/json",
                               **({"X-DCubic-Token": token} if token else {})})
            r = c.getresponse()
            dados = r.read()
            try:
                j = json.loads(dados or b"{}")
            except ValueError:
                j = {"texto": dados[:300].decode("utf-8", "replace")}
            if r.status < 500 or t == tentativas - 1:
                return r.status, j
        except (OSError, http.client.HTTPException) as e:
            if t == tentativas - 1:
                return 0, {"erro": f"{type(e).__name__}: {e}"}
        finally:
            c.close()
        time.sleep(5)


class Envio:
    def __init__(self, base, token, total, nome):
        self.base, self.token, self.total, self.nome = base, token, total, nome
        self.n = -(-total // BLOCO)
        self.id, self.lock, self.abortar = None, threading.Lock(), None
        self.tem = bytearray(self.n)          # 0 = falta, 1 = no servidor, 2 = em voo
        self.shas = [b""] * self.n
        self.nb, self.vel, self.falhas = 4, 0.0, 0   # partes de 4 MiB no início (como o navegador)
        self.partes = []                      # (início s, duração s, bytes, status, cf-ray, blocos)
        self.erros = collections.Counter()

    def rodar(self):
        """-> (segundos até o último PUT, segundos do concluir). Exceção se o envio falhar."""
        t0 = time.time()
        st, j = pedir_json(self.base, "POST", "/dcubic-envio/iniciar", {
            "nome": self.nome, "total": self.total, "chave": f"{self.nome}|{self.total}|{t0}"}, self.token)
        if st != 200:
            raise RuntimeError(f"iniciar: {st} {j}")
        self.id = j["id"]
        while True:
            ts = [threading.Thread(target=self._trabalhador, args=(t0,)) for _ in range(PARALELO)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            if self.abortar:
                raise RuntimeError(self.abortar)
            if 0 in self.tem:   # faixa devolvida depois que os outros já tinham saído
                continue
            t_envio = time.time() - t0
            comp = hashlib.sha256(b"".join(self.shas)).hexdigest()
            st, j = pedir_json(self.base, "POST", f"/dcubic-envio/{self.id}/concluir", {"hash": comp}, self.token)
            if st != 200:
                raise RuntimeError(f"concluir: {st} {j}")
            if j.get("ok"):
                if j.get("hash") != comp:
                    raise RuntimeError("concluir: hash diferente do calculado")
                return t_envio, time.time() - t0 - t_envio
            self.tem = bytearray(1 if ch == "1" else 0 for ch in j["mapa"])   # bloco ruim: reenvia

    def _trabalhador(self, t0):
        conn = None
        while True:
            with self.lock:
                b = self.tem.find(0)
                if b < 0 or self.abortar:
                    break
                e = b + 1
                while e < self.n and e - b < self.nb and self.tem[e] == 0:
                    e += 1
                self.tem[b:e] = b"\x02" * (e - b)
            blocos = [bloco(k, self.total) for k in range(b, e)]
            for k, x in zip(range(b, e), blocos):
                self.shas[k] = hashlib.sha256(x).digest()
            corpo = b"".join(blocos)
            ti, status, ray, detalhe = time.time(), 0, "", ""
            try:
                conn = conn or conectar(self.base)
                conn.request("PUT", f"/dcubic-envio/{self.id}?ini={b * BLOCO}", body=corpo, headers={
                    "User-Agent": UA, "X-DCubic-Token": self.token,
                    "X-DCubic-Sha": ",".join(self.shas[k].hex() for k in range(b, e))})
                r = conn.getresponse()
                resposta = r.read()
                status, ray = r.status, r.getheader("cf-ray", "")
                detalhe = resposta[:200].decode("utf-8", "replace")
                if r.will_close:
                    conn.close()
                    conn = None
            except (OSError, http.client.HTTPException) as ex:
                detalhe = type(ex).__name__
                if conn:
                    conn.close()
                conn = None
            dur = time.time() - ti
            with self.lock:
                self.partes.append((ti - t0, dur, len(corpo), status, ray, e - b))
                if status == 200:
                    self.tem[b:e] = b"\x01" * (e - b)
                    v = len(corpo) / max(dur, 0.05)
                    self.vel = 0.7 * self.vel + 0.3 * v if self.vel else v
                    self.nb = max(1, min(PARTE_MAX // BLOCO, int(self.vel * 20 / BLOCO)))
                    self.falhas = 0
                    continue
                self.erros[status or detalhe] += 1
                self.tem[b:e] = bytes(e - b)   # devolve a faixa: outra volta a reenvia
                if (400 <= status < 500 and status not in (408, 429)) or self.falhas >= 40:
                    self.abortar = f"PUT {status}: {detalhe}"
                    break
                self.falhas += 1
                self.nb = max(1, self.nb >> 1)
                espera = min(30, 2 ** min(self.falhas, 5))
            time.sleep(espera)
        if conn:
            conn.close()


def sink(base):
    """4 PUTs de 32 MiB em paralelo para /sink (descartados no servidor): banda bruta do caminho."""
    corpo, res = BASE * 32, []

    def um():
        ti = time.time()
        try:
            c = conectar(base)
            c.request("PUT", "/sink", body=corpo, headers={"User-Agent": UA})
            r = c.getresponse()
            r.read()
            res.append((r.status, time.time() - ti, r.getheader("cf-ray", "")))
            c.close()
        except (OSError, http.client.HTTPException) as e:
            res.append((type(e).__name__, time.time() - ti, ""))
    t0 = time.time()
    ts = [threading.Thread(target=um) for _ in range(PARALELO)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return PARALELO * len(corpo) / MB / (time.time() - t0), res


CPU_CMD = ('grep usage_usec /sys/fs/cgroup/system.slice/docker-$(docker inspect -f "{{.Id}}" teste-envio).scope/cpu.stat;'
           ' head -1 /proc/stat')


def cpu():
    try:
        linhas = ssh(CPU_CMD).split("\n")
        return time.time(), int(linhas[0].split()[1]), [int(x) for x in linhas[1].split()[1:9]]
    except (IndexError, ValueError, subprocess.SubprocessError):
        return None


def cpu_delta(a, b):
    """-> (CPU do contêiner %, CPU da VPS %, steal %) entre duas leituras."""
    if not a or not b:
        return None
    tot = sum(b[2]) - sum(a[2])
    ocioso = (b[2][3] + b[2][4]) - (a[2][3] + a[2][4])
    return (100 * (b[1] - a[1]) / 1e6 / (b[0] - a[0]), 100 * (tot - ocioso) / tot, 100 * (b[2][7] - a[2][7]) / tot)


def sondar(base):
    try:
        c = conectar(base, 20)
        c.request("GET", "/", headers={"User-Agent": UA})
        r = c.getresponse()
        r.read()
        c.close()
        return r.status, r.getheader("server", ""), r.getheader("cf-ray", ""), r.getheader("location", "")
    except ssl.SSLCertVerificationError:
        return "certificado-invalido", "", "", ""
    except (OSError, http.client.HTTPException) as e:
        return type(e).__name__, "", "", ""


def preparar():
    """DNS dos 2 nomes + certificado válido nos 2 caminhos. -> linhas para o cabeçalho do relatório."""
    linhas = []
    for nome, base in CAMINHOS.items():
        host = urlsplit(base).hostname
        try:
            ips = sorted({a[4][0] for a in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})
        except socket.gaierror:
            sys.exit(f"{host} ainda não existe no DNS. Crie o registro no painel Cloudflare e rode de novo.")
        if (nome == "direto") != (VPS_IP in ips):
            sys.exit(f"{host} -> {ips}: o esperado é "
                     + ("152.239.113.183 (nuvem cinza)." if nome == "direto" else "IPs da Cloudflare (nuvem laranja)."))
        linhas.append(f"{host} -> {', '.join(ips)}")
    # O Traefik só consegue o certificado depois que o DNS existe; reiniciar SÓ o contêiner de teste
    # faz o Traefik pedir de novo (até 2 vezes, dentro do limite do Let's Encrypt de 5 falhas/hora).
    for reinicio in range(3):
        fim = time.time() + (0 if reinicio == 0 else 180)
        while True:
            st = {n: sondar(b) for n, b in CAMINHOS.items()}
            if all(s[0] == 200 for s in st.values()):
                return linhas + [f"sondagem {n}: status={s[0]} server={s[1]} cf-ray={s[2]}" for n, s in st.items()]
            if any(s[0] in (301, 302, 307, 308) for s in st.values()):
                sys.exit(f"Redirecionamento em vez de 200 ({st}): o modo SSL do teste-envio deve ser Full (strict) "
                         "(Configuration Rule do passo a passo).")
            if any(s[0] == 403 for s in st.values()):
                sys.exit(f"403 na sondagem ({st}): confira Bot Fight Mode desligado.")
            if time.time() >= fim:
                break
            print("  aguardando o certificado:", st, flush=True)
            time.sleep(15)
        if reinicio < 2:
            print("  reiniciando só o contêiner teste-envio para o Traefik pedir o certificado", flush=True)
            ssh("docker restart teste-envio")
            time.sleep(10)
    log = ssh("docker logs traefik-traefik-1 --since 15m 2>&1 | grep -i acme | tail -3 | cut -c1-400")
    sys.exit(f"O certificado não saiu ({st}). Confira 'Always Use HTTPS' DESLIGADO. Log do Traefik:\n{log}")


def p95(xs):
    return statistics.quantiles(xs, n=20)[18] if len(xs) >= 2 else (xs[0] if xs else 0)


def mmss(s):
    return f"{int(s // 60)}:{int(s % 60):02d}"


def medir(caminho, total, rotulo, token):
    nome = f"medicao-{rotulo.replace(' ', '')}-{caminho}-{int(time.time())}.stl"
    e = Envio(CAMINHOS[caminho], token, total, nome)
    print(f"[{time.strftime('%H:%M:%S')}] {rotulo} {caminho}: enviando {total / MB:.0f} MB...", flush=True)
    a = cpu()
    try:
        t_envio, t_conf = e.rodar()
        erro = None
    except RuntimeError as ex:
        t_envio, t_conf, erro = None, None, str(ex)
    finally:
        if e.id:
            pedir_json(CAMINHOS[caminho], "DELETE", f"/dcubic-envio/{e.id}", token=token, tentativas=3)
    c = cpu_delta(a, cpu())
    durs = [p[1] for p in e.partes if p[3] == 200]
    r = {"rotulo": rotulo, "caminho": caminho, "total": total, "envio": t_envio, "conf": t_conf, "erro": erro,
         "partes": e.partes, "erros": dict(e.erros), "cpu": c,
         "colos": sorted({p[4].rsplit("-", 1)[-1] for p in e.partes if p[4]}),
         "p50": statistics.median(durs) if durs else 0, "p95": p95(durs), "max": max(durs, default=0),
         "nb_final": e.nb}
    print("   ", linha(r), flush=True)
    return r


def linha(r):
    if r["erro"]:
        return f"{r['rotulo']:<8} {r['caminho']:<6} FALHOU: {r['erro']} | erros {r['erros']}"
    cpu_txt = "CPU contêiner {:.0f}% | VPS {:.0f}% | steal {:.0f}%".format(*r["cpu"]) if r["cpu"] else "CPU n/d"
    return (f"{r['rotulo']:<8} {r['caminho']:<6} envio {mmss(r['envio'])} ({r['total'] / MB / r['envio']:.2f} MB/s) "
            f"+ conferência {r['conf']:.0f} s = {mmss(r['envio'] + r['conf'])} | partes {len(r['partes'])} "
            f"(p50 {r['p50']:.1f} s, p95 {r['p95']:.1f} s, máx {r['max']:.1f} s, final {r['nb_final']} MiB) "
            f"| erros {r['erros'] or 'nenhum'} | colo {','.join(r['colos']) or '-'} | {cpu_txt}")


def gravar(cabecalho, sinks, res):
    out = ["MEDIÇÃO CLOUDFLARE x DIRETO — envio grande (feat/envio-rapido 446ea16, 4 PUTs em paralelo)",
           f"Gerado por tools/medir_cloudflare.py em {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
           "MB = 1.000.000 bytes. Dados incompressíveis gerados em memória; 4 conexões HTTP/1.1.",
           "Contêiner de teste limitado a 0,8 CPU e 512 MiB (CPU contêiner perto de 80% = limite atingido).", "",
           "== DNS e sondagem ==", *cabecalho, "", "== Banda bruta: 4 × 32 MiB em paralelo para /sink =="]
    for caminho, (mbs, rs) in sinks.items():
        out.append(f"{caminho:<6} {mbs:.2f} MB/s   {rs}")
    out += ["", "== Rodadas (na ordem em que rodaram) =="] + [linha(r) for r in res]
    out += ["", "== Resumo (média das rodadas sem falha) =="]
    medias = {}
    for rot in dict.fromkeys(r["rotulo"] for r in res):
        for caminho in CAMINHOS:
            ok = [r for r in res if r["rotulo"] == rot and r["caminho"] == caminho and not r["erro"]]
            if ok:
                t = statistics.mean(r["envio"] + r["conf"] for r in ok)
                v = statistics.mean(r["total"] / MB / r["envio"] for r in ok)
                medias[rot, caminho] = t
                out.append(f"{rot:<8} {caminho:<6} {len(ok)} rodada(s): tempo total médio {mmss(t)}, {v:.2f} MB/s "
                           f"(mín {min(r['total'] / MB / r['envio'] for r in ok):.2f}, "
                           f"máx {max(r['total'] / MB / r['envio'] for r in ok):.2f})")
        if (rot, "direto") in medias and (rot, "proxy") in medias:
            out.append(f"{rot:<8} proxy / direto: {medias[rot, 'direto'] / medias[rot, 'proxy']:.2f}× mais rápido")
    out += ["Referência anterior: 3 GB levaram 18 a 24 min (main, 1 conexão, navegador).", "",
            "== APÊNDICE: partes (saída bruta) — rodada | início s | duração s | bytes | status | cf-ray | blocos =="]
    for r in res:
        for p in r["partes"]:
            out.append(f"{r['rotulo']}/{r['caminho']} | {p[0]:.1f} | {p[1]:.2f} | {p[2]} | {p[3]} | {p[4]} | {p[5]}")
    with open(RELATORIO, "w") as f:
        f.write("\n".join(out) + "\n")


def autoteste():
    """Sobe tools/servidor_teste_envio.py local (HTTP) e confere: envio com tamanho quebrado, partes em
    paralelo com tamanho adaptativo, hash composto, DELETE apagando do disco, /sink e token inválido."""
    raiz, token = os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "autoteste"
    with tempfile.TemporaryDirectory() as dados:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
        s.close()
        srv = subprocess.Popen([sys.executable, "tools/servidor_teste_envio.py", str(porta), token], cwd=raiz,
                               env={**os.environ, "DCUBIC_UPLOAD_DIR": dados}, stdout=subprocess.PIPE)
        try:
            srv.stdout.readline()
            base = f"http://127.0.0.1:{porta}"
            for total in (5 * MiB + 123, 70 * MiB):
                e = Envio(base, token, total, "auto.stl")
                e.rodar()
                assert all(x == 1 for x in e.tem) and len(e.partes) >= 2 and not e.erros, (total, e.erros)
                pronto = os.path.join(dados, "prontos", e.id, "auto.stl")
                with open(pronto, "rb") as f:
                    assert f.read(BLOCO) == bloco(0, total) and os.path.getsize(pronto) == total
                assert pedir_json(base, "DELETE", f"/dcubic-envio/{e.id}", token=token)[0] == 200
                assert not os.path.exists(os.path.dirname(pronto))
            assert max(p[5] for p in e.partes) > 4, "a parte não cresceu com a velocidade"
            mbs, rs = sink(base)
            assert all(x[0] == 200 for x in rs), rs
            try:
                Envio(base, "token-errado", MiB, "x.stl").rodar()
                raise AssertionError("token errado deveria falhar")
            except RuntimeError as ex:
                assert "403" in str(ex)
        finally:
            srv.terminate()
    print(f"autoteste OK: protocolo, partes em paralelo e adaptativas, hash, DELETE, sink ({mbs:.0f} MB/s local), token")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rapido", action="store_true", help="sink + 300 MiB ×1 por caminho")
    ap.add_argument("--autoteste", action="store_true", help="confere o protocolo contra um servidor local")
    a = ap.parse_args()
    if a.autoteste:
        return autoteste()
    token = ssh("cat /root/teste-envio/token").strip()
    if not token:
        sys.exit("Não consegui ler o token do contêiner de teste na VPS (/root/teste-envio/token).")
    print("Conferindo DNS e certificados...", flush=True)
    cabecalho = preparar()
    print("\n".join(cabecalho), flush=True)
    sinks, res = {}, []
    for caminho in CAMINHOS:
        sinks[caminho] = sink(CAMINHOS[caminho])
        print(f"sink {caminho}: {sinks[caminho][0]:.2f} MB/s {sinks[caminho][1]}", flush=True)
    for total, rotulo, vezes in ((300 * MiB, "300 MiB", 1 if a.rapido else 3), (TAM_3GB, "3 GB", 0 if a.rapido else 2)):
        for _ in range(vezes):
            for caminho in ("direto", "proxy"):   # alternando
                res.append(medir(caminho, total, rotulo, token))
                gravar(cabecalho, sinks, res)
    print(f"\nRelatório: {RELATORIO}")


if __name__ == "__main__":
    main()
