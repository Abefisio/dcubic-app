# Envio e abertura de STL de até 3 GB (modo grande)

Implantado em 29/10/2026 (branch `feat/envio-3gb`). Ativo **somente** com `DCUBIC_ENVIO_GRANDE=1`
(VPS). Sem a variável — Streamlit Cloud — o app segue exatamente como antes: envio pelo websocket
em fatias de 16 MB, compactação comum (500 mil triângulos por estrutura) e os mesmos limites.

## Como funciona

### 1. Envio em partes, direto para o disco (`modules/envio_http.py`)

O Streamlit não tem rota HTTP própria, e o envio pelo componente (websocket) passa pela memória
do processo. Decisão: registrar um **handler Tornado no próprio servidor do Streamlit** (mesma
porta 8501 e mesmo endereço). Assim o Traefik não precisa de rota, porta nem serviço extra, e o
corpo de cada pedido vai para o disco em pedaços de 64 KB (`stream_request_body`), sem passar
pelo websocket nem pela sessão.

| Rota | O que faz |
|---|---|
| `POST /dcubic-envio/iniciar` | confere extensão, limite de 3 GB e disco livre (≥ 3 × o arquivo); retoma um envio igual já começado |
| `PUT /dcubic-envio/<id>?ini=<byte>` | parte de até 32 MiB (alinhada a 1 MiB, gzip opcional), gravada no lugar certo do arquivo |
| `GET /dcubic-envio/<id>` | mapa dos blocos de 1 MiB que já estão no disco (retomada) |
| `POST /dcubic-envio/<id>/concluir` | relê o arquivo, confere o tamanho, o SHA-256 de cada bloco e o hash composto |
| `DELETE /dcubic-envio/<id>` | Cancelar: apaga o parcial (ou o arquivo pronto) |

- **Autenticação:** cada sessão logada recebe um token aleatório (cabeçalho `X-DCubic-Token`),
  revogado no logout ou por inatividade. Sem token válido: HTTP 403. Cada envio pertence a quem o
  iniciou, e outro usuário recebe 403.
- **Integridade:** o navegador calcula o SHA-256 de cada bloco de 1 MiB. O servidor confere cada
  bloco na chegada e só então o marca como recebido. Ao concluir, o arquivo é relido do disco
  (numa thread à parte, sem travar o servidor), o tamanho e cada bloco são conferidos de novo, e o
  hash composto, SHA-256 dos SHA-256 dos blocos, tem de bater com o do navegador. Um bloco
  corrompido volta a "faltar" e é reenviado sozinho.
- **Retomada:** se a conexão cai, o componente espera (até a rede voltar), pergunta ao servidor o
  mapa e manda só os blocos que faltam. Se a página for recarregada, basta escolher o mesmo arquivo
  de novo (mesmo nome, tamanho e data): o envio continua de onde parou.
- **Tamanho da parte:** começa com 8 MiB e se ajusta à velocidade medida, até 32 MiB, para cada
  pedido levar uns 20 s. O Traefik v3 da VPS corta pedidos com mais de 60 s (`readTimeout` padrão
  do entrypoint, que não alteramos): em conexões lentas as partes ficam menores e o envio não trava.
- **Tela:** barra de progresso com %, MB/s e tempo estimado, e o aviso "Loading…". O botão
  Cancelar interrompe o envio e apaga o parcial no servidor.
- **Limites:** 3 GB por arquivo (3.221.225.472 bytes), com mensagem clara no navegador e no
  servidor. Disco livre de pelo menos 3 × o tamanho do arquivo antes de aceitar o envio.
- **Limpeza automática:** parciais, arquivos prontos e cache com mais de 24 h são apagados na
  partida do app e a cada envio novo (só dentro de `DCUBIC_UPLOAD_DIR`).
- **Pasta:** `DCUBIC_UPLOAD_DIR` (padrão `./uploads`), com as subpastas `parciais/`, `prontos/` e `cache/`.

### 2. Abertura sem estourar a memória (`modules/stl_compactar.py`)

- **Leitura:** STL binário com `numpy.memmap` (registro de 50 bytes), um bloco por vez, sem
  mapear o arquivo inteiro. STL ASCII convertido em fluxo, linha a linha, em blocos de 200 mil
  triângulos.
- **Redução:** agrupamento de vértices em blocos, com o **envio inteiro** (todas as estruturas do
  dente) em até **1,5 milhão de triângulos**, e uma grade comum (mesma origem e célula) para as
  camadas continuarem alinhadas.
- **Célula adaptativa (canais finos):** na grade comum, um canal mais fino que a célula cai inteiro
  numa célula e some. A 1ª passada mede, em blocos 2 × 2 × 2 de células, a soma vetorial das normais
  ponderadas pela área. Numa superfície lisa ela fica perto da área total; num canal ou parede fina,
  a superfície se fecha e a soma vai a ~0. Essas células são subdivididas 2 a 16 vezes por eixo, com
  pelo menos 4 subcélulas no diâmetro estimado. Um orçamento garante o teto de 1,5 milhão. O ponto
  de cada agrupamento é o de menor erro quadrático aos planos dos triângulos (QEM, Lindstrom 2000),
  e não a média, que encolhe canais e superfícies curvas. Tudo é automático, a partir do STL bruto.
- **Processo à parte:** no modo grande, a redução roda num processo Python separado (só numpy).
  A memória dela volta inteira ao sistema no fim, e o servidor não fica com o heap fragmentado.
- **Cache em disco:** a malha reduzida fica em `cache/<hash>_<grade>/` (o hash é o do arquivo
  enviado). O mesmo arquivo enviado de novo não é reprocessado. A malha de exibição (200 mil
  triângulos por estrutura) também fica em cache (`.dcubic_cache.ply`).
- **Volume:** a 1ª leitura calcula o volume da malha original (teorema da divergência). A tabela de
  métricas mostra o volume da original e a diferença em % da reduzida (`<malha>.original.json`).
  As unidades são as nativas do STL: mm³ só quando o STL estiver em mm (calibração de voxel pendente,
  ver `docs/MODO-STL.md`).

## Resultados medidos (29/10/2026)

Ver o relatório `~/Desktop/RELATORIOS-CLAUDE/dcubic-3gb-vps.txt` (saída bruta). Resumo:

**Local (Mac M1 Pro, Chromium via Playwright, Python 3.12):**

| Teste | Resultado |
|---|---|
| Sintético 3 GB (3.199.993.684 bytes, 63.999.872 triângulos; esfera + canais de 2, 4 e 8 un.) | envio pelo componente com a rede derrubada em 31%: retomou sozinho, 3.084 MiB enviados para 3.052 (só a parte em voo foi repetida); reduzido para 1.355.521 triângulos, volume −0,07%, canais preservados (volume 0,987 / 0,988 / 0,953 do original; no agrupamento comum, os de 2 e 4 un. sumiam) |
| O mesmo arquivo enviado de novo | malha do cache, 3D aberto 2,4 s depois do envio (sem reprocessar) |
| Real 3 GB (raiz do molar superior subdividida × 4: 3.118.772.884 bytes, 62.375.456 triângulos) | página recarregada em 40%: ao escolher o mesmo arquivo, o servidor retomou com 1.200 MB e nada foi reenviado; redução + abertura em 67 s; 1.319.594 triângulos, volume +0,01% |
| Esmalte + Dentina + Canal (incisivo, 609 MB num envio só) | 1.143.387 triângulos no total; caixas com desvio ≤ 1,09 un. (0,10% da extensão) e centróides ≤ 1,40 un. (0,11%): camadas alinhadas, canal dentro da dentina |
| Memória (`/usr/bin/time -l`) | pico de RSS 773 MB (1ª rodada) e 1.206 MB (2ª rodada, maior processo, inclusive a redução); pico de footprint do servidor 497 MB / 848 MB; memória em uso na redução de 3 GB: 298 MB (tracemalloc; o resto é memória livre retida pelo alocador do macOS) |
| Sem `DCUBIC_ENVIO_GRANDE` | envio antigo pelo websocket e redução comum (500 mil) funcionando; rota `/dcubic-envio` inexistente |

**VPS:** ver o relatório (teste 13).

## Como atualizar e reverter

- Atualizar a VPS: ver `docs/DEPLOY-VPS.md` (`git -C app pull --ff-only` e `docker compose up -d --build`).
- Reverter o código para antes do envio de 3 GB: a tag `backup-antes-envio-3gb` (e o bundle em
  `~/Backups/DCUBIC/`). Na VPS: `git -C app checkout backup-antes-envio-3gb && docker compose up -d --build`.
  Para desligar só o envio grande, sem mexer no código: remova `DCUBIC_ENVIO_GRANDE=1` do compose e
  rode `docker compose up -d`. O app volta ao envio pelo websocket.

## Testes

- `python modules/envio_http.py`: protocolo HTTP de ponta a ponta (servidor Tornado de verdade).
- `python modules/stl_compactar.py`: compactação, Drive e envio pelo websocket (modo de antes).
- `python tools/gerar_stl_teste.py sintetico <saida.stl>`: STL de ~3 GB com canais finos (2, 4 e 8 un.).
  `subdividir <entrada.stl> <saida.stl>` gera um real de 4 × triângulos (mesma superfície).
