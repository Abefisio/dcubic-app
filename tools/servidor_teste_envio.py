"""
Servidor de TESTE do envio grande (não faz parte do app): sobe só as rotas de modules/envio_http.py,
a página do componente e uma rota /sink que descarta o que recebe (mede a banda sem gravar).
Serve para medir o envio de ponta a ponta (navegador -> rede -> Traefik -> Python) sem login nem Streamlit.

  DCUBIC_UPLOAD_DIR=/dados python tools/servidor_teste_envio.py <porta> <token>
  abrir  http(s)://<host>/#<token>   (o token vai no fragmento, nunca na URL enviada ao servidor)
  ?v=antigo usa o componente da pasta $ANTIGO (comparação A/B)
"""
import os
import sys
import time

import tornado.ioloop
import tornado.web
import tornado.websocket

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from modules import envio_http as h  # noqa: E402

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "envio_grande")

HARNESS = """<!doctype html><meta charset=utf-8><title>harness</title>
<iframe id=f style="width:100%;height:420px;border:0"></iframe>
<script>
window.valores = [];
document.getElementById("f").src = location.search.includes("v=antigo") ? "/antigo/index.html" : "/componente/index.html";
const tok = location.hash.slice(1);
window.addEventListener("message", (ev) => {
  const d = ev.data || {};
  if (d.type === "streamlit:componentReady")
    document.getElementById("f").contentWindow.postMessage({type: "streamlit:render", args: {modo: "http", token: tok,
      limite_bytes: 3 * 1024 ** 3}, theme: null}, "*");
  if (d.type === "streamlit:setComponentValue") window.valores.push(d.value);
});
</script>"""


class Sink(tornado.web.RequestHandler):
    """PUT /sink: lê o corpo e descarta (banda bruta, sem disco nem hash)."""
    def prepare(self):
        self.n = 0
        self.t0 = time.time()

    def data_received(self, chunk):
        self.n += len(chunk)

    def put(self):
        self.finish({"bytes": self.n, "s": round(time.time() - self.t0, 3)})

    def get(self):   # download (banda de descida / latência): ?mb=N
        n = int(self.get_argument("mb", "1"))
        self.set_header("Content-Type", "application/octet-stream")
        for _ in range(n):
            self.write(b"\x01" * 1024 ** 2)
        self.finish()


Sink = tornado.web.stream_request_body(Sink)


class SinkWS(tornado.websocket.WebSocketHandler):
    """/wsink: descarta cada mensagem binária e responde com o tamanho (banda por WebSocket)."""
    def check_origin(self, origin):
        return True

    def on_message(self, m):
        self.write_message(str(len(m)))


class Pagina(tornado.web.RequestHandler):
    def get(self):
        self.finish(HARNESS)


if __name__ == "__main__":
    porta, token = int(sys.argv[1]), sys.argv[2]
    h._tokens[token] = ["teste", time.time() + 10 ** 9]
    app = tornado.web.Application(websocket_max_message_size=64 * 1024 ** 2, handlers=[
        (r"/", Pagina), (r"/sink", Sink), (r"/wsink", SinkWS),
        (r"/componente/(.*)", tornado.web.StaticFileHandler, {"path": RAIZ}),
        (r"/antigo/(.*)", tornado.web.StaticFileHandler, {"path": os.environ.get("ANTIGO", RAIZ)}),   # A/B: versão anterior
        (rf"{h.ROTA}/iniciar", h._Handler), (rf"{h.ROTA}/([0-9a-f]{{32}})", h._Handler),
        (rf"{h.ROTA}/([0-9a-f]{{32}})/concluir", h._Handler)])
    app.listen(porta, address="0.0.0.0")
    print("servidor de teste em", porta, flush=True)
    tornado.ioloop.IOLoop.current().start()
