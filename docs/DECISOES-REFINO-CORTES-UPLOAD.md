# Decisões — Refino de cortes, upload e painel

Branch de trabalho: `refino/cortes-upload-painel` (backup: tag `backup-antes-refino-cortes-20261021-1020`
e zip em `~/Desktop/BACKUPS-DCUBIC/dcubic-app-repo-20261021-1020.zip`).

## Etapa 0 — Diagnóstico (2026-10-21)

- O painel antigo (Opacidade, LOCK, Cor, Vista) era HTML/JS dentro do iframe `components.html`
  (app.py ~641-844), sem rerun; as vistas Topo/Frente/Lado/Perspectiva eram `updatemenus` do Plotly.
- Não há `st.file_uploader` desde o commit 1c63048; `maxUploadSize = 100` sem uso.
- `mesh_loader` e `tools/reduzir_stl.py` carregam o arquivo inteiro na memória.

## Bloco 1 — Painel movido para a barra lateral (2026-10-21)

- Nova seção **"Aparência"** na barra lateral, entre "Revelar interior" e "Estruturas visíveis":
  Opacidade (0–100), Lock (toggle), Cor (Cinza + Tom 0–255 / Cor personalizada via color_picker),
  Vista (radio horizontal Topo/Frente/Lado/Perspectiva) e Resetar vista.
- Removidos do iframe: `#sidePanel`, `#toggleBtn` e `updatemenus`. O 3D ocupa a largura total;
  a altura foi mantida (figura 1156 px, iframe 1250 px).
- **Desempenho:** o fragmento pesado (`_fig_stl.to_html`) fica em `st.cache_data`
  (`_fragmento_3d_cached`), com chave = arquivos+mtime + visibilidade + revelar_interior.
  Opacidade, cor, vista e lock só alteram um pequeno objeto JS (`AP`) injetado antes do fragmento
  e aplicado no navegador com `Plotly.restyle` / `Plotly.relayout`.
- Como no painel antigo, opacidade e cor valem para todas as malhas e só sobrescrevem o padrão
  por estrutura depois do primeiro ajuste do usuário. Opacidade 0% oculta as malhas (`visible=false`).
- **Câmera:** mantida a lógica de localStorage `dcubic_stl_camera`. Vista e Resetar vista enviam um
  comando com nonce (instante em ms, gravado em `dcubic_stl_cmd_n`), aplicado uma única vez.
  Lock ligado = `scene.dragmode=false` + a câmera salva é restaurada a cada tentativa de mudança.
  Resetar vista desliga o Lock e limpa a seleção de Vista (como o botão antigo).
- **Baixar imagem:** o botão próprio foi removido; a barra do Plotly mostra só o ícone de câmera,
  com `toImageButtonOptions = {png, 1600x1200, modelo_stl}`. A legenda foi movida para o canto
  superior esquerdo para não cobrir o ícone.
- Vistas com câmera completa (eye + up); antes, Frente/Lado/Perspectiva só trocavam o `eye`.
- Limitação conhecida: o radio "Vista" não reaplica a mesma opção já selecionada; para voltar a ela,
  escolher outra vista ou usar Resetar vista.
- Cada ajuste recarrega o iframe (o HTML muda); medido ≈ 1,1–1,3 s do ajuste até o 3D pronto,
  com rerun no servidor de ≈ 0,08–0,12 s.

## Bloco 1 — Correção da câmera e do tamanho do 3D (2026-10-21)
Bug relatado na produção: câmera salva em `dcubic_stl_camera` com `center` fora da cena
(-7.39, -0.72, 4.90), restaurada a cada carga; vista padrão aproximada demais; canvas WebGL menor
que a div. Decisões (feitas no worktree `refino/correcao-camera`, a integrar à
`refino/cortes-upload-painel` após o Bloco 2):
- **Validação antes de restaurar:** a câmera salva só é usada se `center` ∈ [-1,1] nos 3 eixos,
  distância eye–center ∈ [0.3, 6] e nenhum valor NaN/ausente. Inválida → chave apagada, vale a padrão.
  Movimentos do usuário também só são gravados se passarem nessa validação.
- **Chave por dente:** `dcubic_stl_camera_` + md5 (12 caracteres) dos nomes dos arquivos carregados
  (`stl_paths`). Dente novo começa na vista padrão; voltar a um dente restaura a câmera dele.
  A chave global antiga `dcubic_stl_camera` é apagada ao abrir o 3D.
- **Câmera padrão:** center (0,0,0), eye (1.6, 1.6, 1.3) — também aplicada na própria figura.
- **Altura:** o iframe recebe `height: max(600px, 85vh)` (vh da página-mãe); a figura usa
  `autosize=True` sem altura/largura fixas (anulando o `height=520` do viewer3d).
- **Canvas:** `Plotly.Plots.resize(gd)` após o primeiro desenho e em `window.resize`.

## Pendências (NÃO executar sem "prossiga")

- **Bloco 2:** reaproveitar `create_plotly_3d(clip_plane=...)` para mostrar o plano de corte no 3D,
  usando a mesma convenção de eixos do viewer3d (points[:,0]=Z, [:,1]=Y, [:,2]=X), para que os
  cortes batam com o modelo.
- **Bloco 3:** recriar o `st.file_uploader` (removido no commit 1c63048) sem usar o caminho atual de
  `mesh_loader`, que faz `fh.read()` do arquivo inteiro.

## Bloco 2 — Cortes (slices) ortogonais do STL

- **Módulo:** `modules/slices.py` (trimesh + shapely + Pillow). Interseção malha x plano (`section` -> `to_planar` -> `polygons_full`, respeitando furos), rasterização em PNG (~512 px, fundo preto, fora para dentro).
- **Convenção de eixos:** idêntica à de `viewer3d.create_plotly_3d` (Plotly x = coluna 2, y = coluna 1, z = coluna 0 dos pontos). As malhas são reordenadas para (x, y, z) do Plotly e o enrolamento das faces é invertido (a troca de eixos é uma reflexão). Axial = plano z, Coronal = plano y, Sagital = plano x. Observação: por essa convenção, o eixo longo do dente nos STL de exemplo cai em x (Sagital), e não em z.
- **Unidades:** os STL estão em unidades nativas (calibração de voxel pendente; extensão ~1400 un.). A régua e os sliders usam `slices.UNIDADE = "un."`; trocar para "mm" quando houver calibração.
- **Ordem de desenho:** por nome conhecido (Esmalte -> Dentina/Molar/Raiz -> Polpa/Canal); nomes desconhecidos, maior área primeiro. Furos da máscara revelam a camada de baixo.
- **Cache/memória:** `_trimesh_cached` (cache_resource, 1x por arquivo+mtime) e `_corte_cached` (cache_data; chave = arquivos+mtime, visíveis, eixo, posição em passos de 0,05). Acima de `LIMITE_FACES` (1.000.000 faces originais) usa-se a malha já decimada do `mesh_loader` — recurso provisório; o Bloco 3 (compactação) o substituirá.
- **Interface:** `st.tabs(["3D", "Cortes"])`; a aba Cortes tem 3 painéis (st.columns, empilham em tela estreita), slider por eixo (limites = bbox combinado), aviso "Fora do dente nesta posição" quando não há interseção. Respeita `_visible_dict`.
- **Plano no 3D:** opção "Mostrar plano no 3D" + eixo. Reaproveita `create_plotly_3d(clip_plane=...)`: o modelo é recortado na posição do corte (eixo Plotly x/y/z -> coluna 2/1/0 de `mesh.points`; o "Interior" recebe o mesmo recorte). Além disso, um `Mesh3d` semitransparente marca o plano. Os parâmetros entram na chave do cache do fragmento. O JS de Aparência (opacidade/cor) ignora a trace "Plano de corte". Conferido no navegador: faces do 3D com z <= posição do slider e plano exatamente nessa posição.
- **requirements.txt:** adicionados trimesh, shapely, networkx, pillow. Desvio consciente do pedido ("apenas trimesh, shapely e pillow"): `trimesh.section(...).polygons_full` importa networkx (testado: sem ele, `ModuleNotFoundError`).

### Etapa A (retomada do WIP, 21/10/2026)
- **Cherry-pick de d2bdb6b:** conflito único em `app.py`, causado pela reindentação do bloco 3D (entrou em `with _tab_3d:`). Resolução mecânica: versão de 3e5eb81 (câmera) reindentada (+4 espaços fora da string JS, que ficou byte a byte igual) + os acréscimos do WIP (assinatura com `_plano`, trace do plano, chave do cache, filtro `idx` no JS). Prova: `git diff -w 3e5eb81 -- app.py` só remove as 4 linhas que receberam `_plano`/`idx`.
- **Malhas com falhas (STL bruto):** vários STL têm contornos abertos no corte (ex.: Molar: 132 trechos, só 7 fechados). Quando o contorno está íntegro usam-se os `polygons_full` (furos respeitados); quando há trechos soltos, os segmentos são desenhados, fechados por morfologia (`FECHAR_PX = 3`) e preenchidos (`binary_fill_holes`). Limitação: nesse modo os furos internos ficam sólidos (a camada de dentro os recobre).
- **Tela dos cortes:** quadrada e do mesmo tamanho nos 3 eixos (corte centralizado) para que as 3 imagens tenham a mesma escala na interface.
- **Unidade:** mantida "un." (unidades nativas). O pedido falava em mm, mas os STL têm ~1.400 unidades de comprimento (voxels sem calibração); rotular como mm seria incorreto. A escala é preservada 1:1 em relação ao STL; basta trocar `slices.UNIDADE` (e, se preciso, aplicar o fator de voxel) quando houver calibração.
- **Chave do cache dos cortes:** (caminho + mtime) em vez de hash do conteúdo — equivalente para arquivos em disco e sem custo de reler arquivos grandes a cada rerun.
- **Observação de interface:** na primeira vez em que "Mostrar plano no 3D" é ligado numa sessão, o Streamlit volta para a aba 3D (comportamento do `st.tabs`); nas mudanças seguintes a aba Cortes permanece.

## Etapa B — Dente de exemplo substitui o anterior

- **Regra:** "Carregar dente de exemplo" chama `_trocar_dente(paths)`, que substitui `stl_paths` e limpa `_stl_selected`/`_stl_last` (equivale a "Limpar STL" + carregar). Todas as estruturas de um zip de exemplo entram juntas (mesmo dente).
- **Exemplos avulsos (Esmalte, Dentina, Molar):** tratados como estruturas do MESMO dente; continuam somando entre si quando a lista atual só tem avulsos. Vindo de outro dente (zip, pasta ou upload), substituem. Premissa: os três avulsos são do mesmo dente; se não forem, basta trocar o `if` por `_trocar_dente([_dest])`.
- **Câmera:** a chave de câmera por dente (3e5eb81) faz o dente novo abrir na câmera padrão (eye 1,6/1,6/1,3) sem alteração adicional.
- **Correção encontrada no teste:** o estado de "Mostrar plano no 3D" (e do eixo) era descartado pelo Streamlit nas execuções interrompidas por `st.rerun()` (troca de dente, Limpar STL), porque o widget não chegava a ser desenhado. Solução: reatribuir `cortes_plano` e `cortes_plano_eixo` em `st.session_state` antes desses botões (padrão recomendado pelo Streamlit).

## Etapa C — Bloco 3: envio de STL com compactação automática

- **Interface:** caixa "Enviar STL" na barra lateral (acima dos dentes de exemplo), aceita `.stl` e `.zip`, vários arquivos de uma vez (estruturas do mesmo dente). `maxUploadSize = 1024` em `.streamlit/config.toml`. Ajuda: "Arquivos acima de 200 MB: envie o STL compactado em .zip (no Mac: clique direito no arquivo > Comprimir)". O envio substitui o dente atual (`_trocar_dente`) e entra em `stl_paths`, no mesmo fluxo do 3D e dos Cortes. O resumo (tamanho e triângulos antes/depois, "do cache") fica abaixo da caixa.
- **Memória do envio:** o Streamlit guarda o arquivo enviado na RAM. Depois de gravado em disco, a chave do uploader é trocada (`upl_stl_<n>`) e o app reexecuta: o Streamlit descarta os bytes. O `.zip` é extraído membro a membro com `shutil.copyfileobj` (blocos de 1 MB, SHA-1 calculado no caminho); nada usa o `fh.read()` do `mesh_loader` sobre o arquivo bruto.
- **Módulo `modules/stl_compactar.py`:** detecção binário x ASCII (ASCII convertido linha a linha para binário); leitura com `np.memmap` em blocos de 1 milhão de triângulos (um memmap por bloco, desfeito em seguida, para não manter o arquivo todo mapeado); contas em float32 (precisão do próprio STL).
- **Agrupamento de vértices:** grade de célula absoluta (unidades do STL), `célula = sqrt(K * área / 300 mil)` com `K = 2,4` (calibrado: com K = 3 saíam ~0,8 × o alvo). Cada célula vira a média dos vértices; triângulos degenerados (dois vértices na mesma célula) e duplicados (mesmos 3 vértices, em qualquer orientação) são removidos. Sem limpeza topológica.
- **Mesma grade no envio:** origem = mínimo da caixa envolvente conjunta; célula = a maior entre as estruturas (nenhuma passa do alvo; as menores ficam com a mesma resolução absoluta e, portanto, menos triângulos — ex.: Canal do pré-molar 975.884 -> 50.336). Sobreposição conferida: desvio máximo das caixas envolventes <= 1,83 un. com célula de 4,26 un.
- **Teto de 30 MB:** se alguma estrutura passar de 30 MB, a célula é engrossada e a compactação refeita (até 3 tentativas). Nos testes, o maior resultado foi 15,0 MB.
- **Cache em disco:** fora do repositório, em `tempfile.gettempdir()/dcubic_upload_cache` (nada a ignorar no Git). Medidas por SHA-1 do original (`info/<sha1>.json`); compactação em `<sha1>_<grade>/<nome>.stl`. O original bruto é apagado após a compactação.
- **Limite seguro de memória:** `tamanho do envio (na RAM) + 450 MB de trabalho <= DCUBIC_LIMITE_MEMORIA_MB` (padrão 900). Acima disso, mensagem clara pedindo o `.zip`. Ex.: o STL bruto de 744 MB sem zip é recusado; o mesmo arquivo em `.zip` (114 MB) passa.
- **Memória dos cortes:** `_trimesh_cached` passou a ter `max_entries=6`, para não acumular na RAM as malhas de todos os dentes já abertos na sessão.
- **Unidade:** o cabeçalho dos STL do CTAnalyser diz "unit: mm", mas as coordenadas (~1.400 de comprimento) são de voxel; mantida a decisão da Etapa A ("un.").

## Resumo do refino (Etapas A, B e C) — 21/10/2026

- **A — Cortes (82f6faa):** aba "Cortes" com Axial/Coronal/Sagital calculados do STL bruto (trimesh + shapely + Pillow), tolerando malhas abertas; "Mostrar plano no 3D" recorta o modelo via `clip_plane` e marca o plano. Correção da câmera (3e5eb81) e painel Aparência (Bloco 1) preservados e conferidos no navegador. Cortes: 25–430 ms sem cache, < 0,4 ms com cache.
- **B — Exemplo substitui (a556942):** carregar um dente de exemplo troca o dente atual; o novo abre na câmera padrão. Estado de "Mostrar plano no 3D" preservado entre trocas.
- **C — Envio com compactação (a58945a):** `.stl`/`.zip` na barra lateral, até 1 GB; compactação por agrupamento de vértices com grade comum (~300 mil triângulos por estrutura, sobreposição mantida), cache por SHA-1, resultados de 2,4 a 15,0 MB (teto 30 MB). STL de 744 MB enviado em `.zip` de 114 MB: 7,6 s, pico 430 MB no teste isolado.
- **Pendências/limitações:** unidade "un." até haver calibração de voxel; o pico de RSS do servidor inteiro chegou a 1.299 MB durante os testes de envio pela interface (Streamlit + 3D + cortes + envio na RAM) — acima de 1 GB, o que pede atenção antes de publicar no Streamlit Cloud (ajustar `DCUBIC_LIMITE_MEMORIA_MB` e/ou reduzir caches do 3D); envio pela interface testado com arquivo injetado via JavaScript no navegador embutido, a conferir com o seletor de arquivos real.

## Etapa D1 — Memória (21/10/2026) — CONCLUÍDA (pico transitório aceito)
- Patch aprovado reaplicado (caches com max_entries=2, STL lido do disco, bytes do envio liberados).
- Modo volume sob demanda: no login só aparece o aviso + botão "Abrir modo volume (dados sintéticos)";
  dados, arrays e figuras do modo volume só são criados após o clique. RSS logo após o login: ~200 MB.
- `.streamlit/config.toml`: `maxUploadSize = 200`; legenda do envio com o limite de 200 MB e a orientação do .zip.
- Envio em duas etapas: etapa 1 usa `checar_tamanho` (só tamanho, sem RSS); etapa 2 limpa os caches,
  roda `gc.collect()` e só então `checar_memoria` (RSS).
- `use_container_width` → `width="stretch"` apenas em `st.dataframe`; `st.plotly_chart` no Streamlit 1.50
  não tem o parâmetro `width` (mantido o original nos 7 pontos).
- Medição (8504, limite 800 MB): no macOS padrão o envio C foi RECUSADO (RSS 1.044 MB na etapa 2), porque
  o macOS retém blocos grandes liberados (comprovado em teste isolado; `MallocLargeCache=0` desliga a retenção).
  Com `MallocLargeCache=0` (comportamento equivalente ao Linux) o envio C foi ACEITO, mas o pico foi 936 MB:
  o próprio Streamlit 1.50 recebe o envio inteiro na RAM (tornado + `parse_body_arguments`, ~4 cópias do zip
  por ~0,5 s) somado à base com o Molar carregado (~505 MB). Isso fica fora do código do app.
- **Decisão do Dr. Abe: opção 1 — ACEITOU o pico transitório de ~936 MB no envio** (causado por `parse_body_arguments` do Streamlit 1.50, que recebe o arquivo inteiro na RAM por ~0,5 s), medido com `MallocLargeCache=0` (equivalente ao Linux). No macOS padrão a checagem pode recusar o envio por retenção de memória do alocador.
- Medições: login 467,8 → 200,6 MB; A) Molar 701,8 → 491,5; B) Cortes + plano 696,6 → 514,9; C) envio zip 114 MB 1.528,8 → 936,4 MB.

## Etapa D2 — Cortes sem perder o canal (21/10/2026)
- Contornos abertos: desenho dos segmentos + fechamento morfológico com tolerância de ~0,5% da diagonal do bounding box (`TOL_FECHAR`, em px = 0,5% × diagonal × px/un ÷ 2 iterações). Não há mais `binary_fill_holes`.
- Preenchimento par-ímpar (even-odd) em raster (`_par_impar`): regiões separadas pelo traço formam um grafo; profundidade ímpar = sólido, par = vazio. Câmara pulpar/canais vazios ficam como furo.
- Tentativa vetorial (colar pontas com shapely) descartada: o STL "Molar" gera ~1.800 segmentos fragmentados por corte; o raster foi mais robusto.
- Limitação: lacunas maiores que a tolerância deixam o contorno aberto (ex.: Molar a 33% da altura, só contorno). Contorno íntegro (malhas fechadas) segue o caminho vetorial exato com furos.

## Etapa D3 — Aba Cortes não pula (21/10/2026)
- `st.tabs(["3D","Cortes"])` trocado por `st.segmented_control` com `key="aba_visualizacao"` (disponível no Streamlit 1.50): o rerun do checkbox "Mostrar plano no 3D" não volta mais ao 3D.
- Só a aba ativa é renderizada; o estado dos widgets de Cortes (plano, eixo, sliders) é preservado por reatribuição em `session_state`, e o plano do 3D é lido de lá (funciona também com a aba 3D ativa).

## Unidade dos STL (21/10/2026)
- As coordenadas dos STL exportados pelo CTAnalyser estão em **voxels**, não em mm, apesar do cabeçalho "unit: mm" (todas as coordenadas terminam em ,5, centro de voxel).
- Bounding box do Molar (idêntico ao de `molar_sup__raiz_voi_.stl`): 819 x 1233 x 1165 unidades.
- Voxel estimado: 15–19 µm (supondo dente de 18–22 mm de comprimento) — apenas referência, não calibração.
- Calibração pendente: obter o valor exato no arquivo .log de reconstrução (NRecon), linha "Pixel Size (um)". Até lá, `slices.UNIDADE` continua "un.".

## Upload de arquivos grandes (21/10/2026)
- **Limite configurável:** `.streamlit/config.toml` → `maxUploadSize = 2048`. Limite efetivo no app = `DCUBIC_MAX_UPLOAD_MB` (st.secrets tem prioridade; depois variável de ambiente). Sem ele: **200** no Streamlit Community Cloud (detectado por `/mount/src` ou `HOSTNAME` contendo "streamlit") e **2048** no Mac/servidor USP. Quando o efetivo é menor que o do config, o app reduz `server.maxUploadSize` em tempo de execução: o seletor de arquivos lê essa opção a cada exibição e recusa o arquivo no navegador, antes do envio (o Cloud não chega a receber 2 GB). Legenda: no Cloud, "Arquivos acima de 200 MB só podem ser abertos na versão local/servidor USP."; local, o limite e o aviso de redução automática. Envio acima do limite efetivo (soma de vários arquivos) é recusado na etapa 1 com a mesma mensagem.
- **No Cloud:** criar o secret `DCUBIC_MAX_UPLOAD_MB = 200` (a detecção automática é só reforço). A mudança só chega ao Cloud quando for para a `main`.
- **Disco, não RAM:** sem mudança — `receber` grava em blocos de 1 MB (`shutil.copyfileobj`) e o ZIP é extraído membro a membro direto para disco; os bytes do Streamlit são liberados logo após gravar (D1).
- **Redução automática:** alvo `ALVO_TRIANGULOS` 300 mil → **500 mil**, e só reduz estruturas **acima** de 500 mil (as menores passam intactas, só convertidas para binário). Algoritmo: o agrupamento de vértices de `modules/stl_compactar.py` (Bloco 3). `tools/reduzir_stl.py` usa `decimate` do PyVista (quádrico), que exige malha limpa e falhou com Esmalte.stl de PRE-MOLAR-SUP e INCISIVO; o agrupamento de vértices não depende de topologia e é a alternativa robusta (sem `fast-simplification`, sem dependência nova). Mesma grade (origem + célula) para as estruturas reduzidas do envio: sobreposição preservada. Aviso no app: "Malha original: X triângulos → reduzida para Y para visualização." Barra de progresso mantida (etapas Lendo/Reduzindo/Pronto).
- **Cache:** em disco por SHA-1 (já existia) e em memória pelos `st.cache_resource(max_entries=2)` de `_load_stl_from_paths` (3D) e `_trimesh_cached` (Cortes), com chave caminho + mtime da malha reduzida: não reprocessa a cada interação. O 3D ainda decima para 200 mil faces (exibição); os Cortes usam a malha reduzida de ~500 mil.
- **Checagem de memória (ajusta a D1):** etapa 2 estima `150 MB de trabalho + Σ min(triângulos, 500 mil) × 400 B` (malha REDUZIDA aberta no app, não o arquivo bruto). Medido: 3D + Cortes de uma malha de ~515 mil triângulos = ~200 B/triângulo; 400 B dá margem para a figura do Plotly. No macOS o RSS não entra na conta (retenção do alocador, D1) — arquivos grandes não são recusados no Mac; no Linux (Cloud/servidor) entra RSS + estimativa ≤ `DCUBIC_LIMITE_MEMORIA_MB` (800).
- **Testes (cache de disco novo e vazio a cada arquivo, mesmas funções do envio):** raiz do MOLAR-SUP (780 MB): 15.593.864 → 520.595 triângulos, 7,0 s, pico 298 MB, desvio máximo da caixa envolvente 2,13 un. (célula 5,33). Esmalte PRE-MOLAR-SUP (259 MB): 5.177.234 → 512.697, 5,3 s, pico 300 MB, desvio 1,16 un. (célula 3,00). O desvio vem das médias por célula (sempre menor que 1 célula); a grade comum mantém o alinhamento entre estruturas.
- **Alerta (não resolvido, fora do app):** o Streamlit 1.50 recebe o envio inteiro na RAM (`parse_body_arguments`, ~4 cópias por ~0,5 s) antes do código do app rodar. Com 2048 MB, um envio de ~2 GB pode gerar pico transitório estimado de ~8 GB só no Streamlit; ~780 MB → ~3 GB. No Mac de 16 GB cabe, mas com folga pequena para 2 GB; envio em `.zip` reduz esse pico na proporção da compressão.
- **Teste real pelo navegador:** Teste real pelo navegador com molar_sup__raiz_voi_.stl (780 MB, sem zip): pico de 2,9 GB por ~20 s na recepção do arquivo pelo próprio Streamlit (antes do processamento do app); após a redução, ~1 GB residual. Aceito para uso local (Mac 16 GB). Recomendação ao usuário: enviar arquivos grandes em .zip. Pendente antes do uso multiusuário no servidor USP: liberar o arquivo do file_uploader após gravar em disco e reduzir o pico. No Streamlit Cloud, definir DCUBIC_MAX_UPLOAD_MB = 200 no painel Secrets antes de levar esta branch à produção.

## Importação por link do Google Drive (21/10/2026)

**Motivo:** o Streamlit Cloud limita o envio a 200 MB (DCUBIC_MAX_UPLOAD_MB). Pelo link do Drive o
arquivo é baixado direto para o disco do servidor, sem passar pelo navegador nem pelo seletor.

**Interface (barra lateral, logo abaixo de "Enviar STL"):** campo "Arquivo grande? Cole o link do
Google Drive (.stl ou .zip)", ajuda com o passo a passo de compartilhamento e botão "Importar do Drive".

**Fluxo (modules/stl_compactar.py):**
1. `id_do_drive` — extrai o ID de `/file/d/ID/` ou `?id=ID` (aceita o ID puro).
2. `baixar_do_drive` — gdown 5.2.2 (já no requirements) grava a resposta em streaming, em blocos de
   512 KB, num objeto `_GravadorLimitado` que escreve em `<cache>/drive/drive_<id>.part`; nada inteiro na RAM.
3. `receber_baixado` — valida o conteúdo (zip pela assinatura `PK\x03\x04`; STL binário 84+50n ou ASCII
   "solid"; página HTML de login/erro é recusada), extrai o .zip membro a membro / copia o .stl para
   `recebidos/` com a função `receber` já existente e apaga o bruto.
4. `processar_recebidos` — pós-recebimento ÚNICO do envio e do Drive: `checar_memoria` (D1: no Linux,
   RSS + estimativa ≤ DCUBIC_LIMITE_MEMORIA_MB) + `compactar_recebidos` (~500 mil triângulos, grade
   comum, cache por SHA-1). No app, o Drive alimenta o mesmo `_upl_recebidos` da etapa 2 do envio e o
   dente novo substitui o anterior por `_trocar_dente`.

**Limites e mensagens:**
- `DCUBIC_MAX_DRIVE_MB` (secrets → ambiente; padrão 2048). O gdown não expõe o Content-Length, então o
  tamanho é conferido DURANTE o download: ao passar do limite, o download é interrompido e o parcial apagado.
- Disco: `shutil.disk_usage` na pasta do cache antes do download; o download é interrompido se
  2,5 × bytes baixados > espaço livre inicial (1× download + 1× cópia/extração + 0,5× folga para a
  saída reduzida e a conversão ASCII→binário). Para .zip, antes de extrair: 1,1 × soma descompactada ≤ livre.
- Link não público (ou cota do Drive excedida): `FileURLRetrievalError` do gdown vira mensagem em português
  com o caminho "Compartilhar > Acesso geral: Qualquer pessoa com o link".

**Temporários:** o bruto baixado é apagado logo após a extração/cópia; os extraídos em `recebidos/` são
apagados por `compactar_recebidos` (ou pelo tratamento de erro do app). Fica só o cache reduzido.
`receber_baixado` só apaga arquivos da própria pasta `<cache>/drive` — um arquivo de fora (ex.: Desktop)
nunca é apagado.

**Barra de progresso:** Baixando… N MB (barra assintótica, tamanho total desconhecido) → Extraindo/Recebendo
→ Lendo/Reduzindo (etapa 2) → Pronto.

**Limitação conhecida:** um .stl único baixado do Drive recebe o nome `drive_<8 primeiros do ID>` (o gdown
não informa o nome original quando grava num objeto-arquivo); estruturas de .zip mantêm os nomes dos membros.

**Testes (21/10/2026, macOS):** link real MOLAR-SUP (zip, 2 estruturas): 7,4 s, 1.603.244 → 395.896
triângulos (canal 311.303, sem redução), pico 283 MB. Pós-download com molar_sup__raiz_voi_.stl
(779,7 MB): 15.593.864 → 520.595 triângulos, 7,0 s, pico 293 MB; original do Desktop preservado.

## Visibilidade do repositório (21/10/2026)

**Decisão:** manter o repositório `Abefisio/dcubic-app` **público**.

**Motivos:**
- O plano gratuito do Streamlit Community Cloud permite apenas **1 app privado**; produção e demo
  são dois apps.
- Produção (`main`) e demo (`dcubic-image-system.streamlit.app`, branch `teste/frenteB-corte`)
  usam o **mesmo repositório**; tornar o repositório privado afetaria os dois.
- **Nenhuma senha no histórico:** as credenciais ficam em Secrets do Cloud / arquivos locais
  ignorados pelo Git.

**Condição para manter a decisão:** nenhuma senha, token ou dado de paciente pode entrar em commit.
Rever esta decisão se o plano do Cloud mudar ou se o app passar a usar dados sensíveis no repositório.

## Envio de arquivo grande em partes (26/10/2026)

**Pedido:** abrir STL de mais de 800 MB enviados direto do computador (PC ou Mac), no Streamlit Cloud.

**Por que não subir `maxUploadSize`:** o seletor nativo do Streamlit 1.50 recebe o arquivo inteiro na
RAM antes do app rodar. Medido com o handler real do Streamlit e um STL de 880 MiB: pico de 2.972 MB
de RSS (macOS) e 4.406 MB de alocação Python; o Cloud documenta no máximo 2,7 GB por app
(https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app). Teto prático do seletor
no Cloud: ~300 MB. `maxUploadSize` continua 200 (config.toml e secret `DCUBIC_MAX_UPLOAD_MB`).

**Por que não Cloudflare R2 agora:** resolveria com pico baixo, mas exige criar conta, bucket, chaves e
CORS, e uma dependência nova (boto3). O envio em partes pelo próprio Streamlit resolve sem conta externa.
R2 fica como opção se o envio em partes ficar lento demais na rede do usuário.

**Como funciona:**
- Barra lateral, abaixo do seletor nativo: "Arquivo grande (até `DCUBIC_MAX_DRIVE_MB` MB)? Enviar do
  computador" (1024 MB no Cloud). Componente próprio sem build em `assets/envio_grande/index.html`
  (`declare_component`, protocolo de componentes v1 por postMessage; não há `st.components.v2` no 1.50).
- O navegador lê o arquivo com `File.slice` e manda fatias de 8 MB como bytes (`dataType: "bytes"`),
  uma por vez, com cabeçalho JSON {id, nome, total, ini}. Mensagem do WebSocket: ~8,4 MB, contra
  `server.maxMessageSize` = 200 MB (margem de ~25 vezes).
- `stl_compactar.receber_parte` (callback do componente, dentro de `@st.fragment`: cada fatia reexecuta
  só o fragmento) anexa a fatia a `<cache>/drive/envio_*.part` (nome único por `tempfile`), só se ela
  começa no byte esperado (repetida é ignorada; fora de ordem, o navegador reenvia a partir do "ack").
  Limite (`DCUBIC_MAX_DRIVE_MB`) e disco (`FATOR_DISCO` = 2,5) usam a mesma checagem do Drive
  (`_checar_limite`), já no tamanho declarado e a cada fatia.
- Arquivo completo: `receber_baixado` (mesma validação e cópia para `recebidos/` do Drive) e a mesma
  etapa 2 (`_upl_recebidos` -> `processar_recebidos`). Um .stl único mantém o nome original.
- Fim, erro ou Cancelar: o .part é apagado, a chave do componente muda (a última fatia sai do estado do
  navegador; os reruns seguintes voltam a ~1,6 KB) e o app roda de novo (`st.rerun(scope="app")`).
- Legenda do seletor: "Até 200 MB: use o seletor acima. Maior que isso: use \"Enviar do computador\" logo
  abaixo (ou o link do Google Drive)." O seletor nativo e o Drive continuam como estavam.

**Testes (26/10/2026, macOS, servidor de teste sem `--server.maxUploadSize`, ou seja 200 MB como no Cloud):**
STL sintético de 880 MiB (922.746.834 B, 18.454.935 triângulos) enviado pelo Chrome: 110 fatias em
12,6 s, aberto no 3D em 23,7 s (reduzido para 305.795 triângulos), aba Cortes sem exceção; pico de RSS do
servidor 558 MB (seletor nativo: 2.972 MB). Cancelar no meio apaga o .part. Autoverificação em
`python modules/stl_compactar.py` (ordem, repetida, adiantada, limite, disco, cancelamento, conclusão).

**Limitações:** a velocidade depende do upload do usuário (cada fatia espera a confirmação do servidor);
fechar a aba no meio deixa um .part, apagado pela limpeza de 2 dias do cache.

## Seletor único de envio (26/10/2026)

**Motivo:** na produção, o Dr. Abe arrastou `Dentina.stl` (> 200 MB) para o seletor nativo do Streamlit (o
primeiro da barra lateral) e recebeu "File must be 200.0MB or smaller." — mensagem em inglês, gerada no
navegador, que o Python não consegue traduzir nem detectar. O bloco "Enviar do computador", mais abaixo,
passava despercebido. Dois seletores para a mesma tarefa eram um problema de usabilidade.

**Decisão:** o componente de envio em partes (`assets/envio_grande/index.html`) passa a ser o seletor
ÚNICO de "Enviar STL"; o `st.file_uploader` nativo foi retirado da barra lateral.
- Área "Arraste os arquivos aqui ou clique para escolher": arrastar e soltar + clique, `.stl` e `.zip`,
  vários arquivos de uma vez (estruturas do mesmo dente). Soltar em qualquer ponto do quadro do componente
  é aceito (o navegador não abre o arquivo).
- Recusa no navegador, antes de enviar: extensão diferente de .stl/.zip e arquivo acima de
  `DCUBIC_MAX_DRIVE_MB` (1024 MB no Cloud), com mensagem em português. O servidor repete as checagens.
- Vários arquivos vão um após o outro, cada um em fatias de 8 MB (mesmo protocolo). O cabeçalho ganhou
  `ultimo` (ausente = True); quando um arquivo que não é o último termina, `receber_parte` devolve o
  "ack" = tamanho total e o navegador começa o próximo. O app junta os recebidos em `_eg_lote` e, no fim
  do último, entrega o conjunto à mesma etapa 2 (`_upl_recebidos` -> `processar_recebidos`), como o
  seletor nativo fazia (grade de redução comum a todas as estruturas).
- `receber_parte` marca o arquivo completo (`feito`): uma fatia repetida depois do fim é ignorada.
- Erro em qualquer arquivo ou Cancelar no meio do lote: apaga o .part em curso e os arquivos do lote já
  recebidos (`_apagar_lote`).
- Progresso por arquivo ("Arquivo 1 de 2: … — X de Y MB") e total ("Total: X de Y MB (Z%)"); botão Cancelar.
- Legenda: "Arraste ou escolha os arquivos .stl/.zip do mesmo dente (até 1024 MB cada). Malhas acima de
  500.000 triângulos são reduzidas automaticamente." O link do Google Drive continua como alternativa
  ("Ou cole o link do Google Drive").
- Removidos do app: `_limite_envio_mb`, o rebaixamento de `server.maxUploadSize` em tempo de execução,
  `_liberar_envios` e a etapa 1 do seletor nativo. `DCUBIC_MAX_UPLOAD_MB` deixa de ser lido (o secret pode
  ficar; não tem efeito). `maxUploadSize = 200` continua no `config.toml`: sem seletor nativo, só limita o
  endpoint HTTP de upload do Streamlit (quanto menor, melhor). No Mac, `--server.maxUploadSize 2048` deixa
  de ser necessário.

**Por que não manter o seletor nativo para arquivos pequenos:** ele é o que o usuário encontra primeiro e
recusa acima de 200 MB com mensagem em inglês; o componente cobre arquivos pequenos e grandes com o mesmo
gesto e usa menos memória.

**Testes (26/10/2026, macOS, Chrome, servidor de teste sem `--server.maxUploadSize`, como o Cloud):**
pequeno escolhido e arrastado abre no 3D; dois arquivos de uma vez viram duas estruturas do mesmo dente;
.zip com duas estruturas; .stl inválido, extensão errada e arquivo de 1032 MB recusados; Cancelar
(arquivo único e no meio de um lote) apaga o .part e os já recebidos; STL sintético de 880 MiB enviado
em 111 fatias (~9,3 s), aberto em ~19,5 s, 3D e Cortes sem exceção, pico de RSS 565 MB. Relatório em
`~/Desktop/RELATORIOS-CLAUDE/envio-unico.txt`.

**Achado fora do escopo (não corrigido):** um STL sintético muito ruidoso (esfera com 2% de ruído por
vértice), depois de reduzido, fez a aba Cortes falhar com `ValueError: unable to recover polygon!`
(trimesh, em `slices.gerar_corte`). Não depende do envio: o arquivo chega idêntico (SHA-1 conferido) e
segue o mesmo processamento do Drive. Com ruído de 0,2% a aba Cortes funcionou.
