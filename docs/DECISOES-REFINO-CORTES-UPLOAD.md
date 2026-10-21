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
