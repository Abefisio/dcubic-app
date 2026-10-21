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
