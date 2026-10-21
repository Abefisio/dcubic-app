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
