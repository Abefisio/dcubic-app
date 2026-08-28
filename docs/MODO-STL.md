# Modo STL — DCubic Image System Platform

Caminho paralelo ao pipeline de volume (voxels), ativado quando há pelo menos
um arquivo `.stl` disponível (upload ou pasta local).

---

## Carregamento

### Upload via browser
O seletor de arquivo aceita `.stl` junto com os formatos de volume. Limitado pelo
`maxUploadSize` do Streamlit (configurado em 1 GB em `.streamlit/config.toml`).
Para arquivos maiores, use a leitura local.

### Leitura local (Caminho A)
Campo de texto na sidebar aceita o caminho absoluto de uma pasta. O botão
"Carregar STL da pasta" faz `glob` de `*.stl` nessa pasta, excluindo arquivos
de cache (`*.dcubic_cache.*`), e persiste a lista de caminhos em
`st.session_state["stl_paths"]`. Bytes **não** são guardados em session_state
(~1,3 GB/arquivo seria copiado a cada rerun).

### Seleção de um arquivo por vez
Após carregar a pasta, um `st.radio` exibe os stems dos arquivos encontrados.
Trocar a seleção dispara `_load_stl_from_paths.clear()` e atualiza
`st.session_state["_stl_last"]`, limpando o cache de memória e forçando nova
leitura apenas do arquivo escolhido.

---

## Pipeline de processamento (`modules/mesh_loader.py`)

### `load_mesh(data, name, *, decimate_target, cache_key, progress_cb)`

1. **Cache de disco (leitura rápida):** se `<cache_key>.dcubic_cache.ply` e
   `<cache_key>.dcubic_cache.json` existirem, lê direto sem reprocessar o STL.
2. **Processamento normal:**
   - Escreve `data` num arquivo temporário, lê com `pyvista.read()`.
   - Triangula com `.triangulate()`.
   - **Mede na malha ORIGINAL** (antes de decimar): `volume`, `area`, `bounds`,
     `n_faces`, `n_points`.
   - Decima com `decimate_pro(ratio, preserve_topology=True)` até
     `decimate_target` faces (default 200 000).
   - Grava `.ply` (malha decimada) e `.json` (métricas) como cache em disco.
3. **Callbacks de progresso:** `progress_cb(pct, label)` é chamado nos marcos
   25 / 50 / 75 / 100 para alimentar a barra de progresso no app.

### Cache em disco
| Arquivo | Conteúdo |
|---------|----------|
| `<stem>.dcubic_cache.ply` | Malha decimada (exibição) |
| `<stem>.dcubic_cache.json` | volume_native, area_native, n_faces, n_faces_display, bounds, n_points |

Os arquivos de cache são ignorados pelo `.gitignore` e pelo glob de STL.

---

## Cache de memória (`@st.cache_resource`)

`_load_stl_from_paths(path_mtime_pairs)` é decorada com `@st.cache_resource`.
A chave de cache é uma tupla `(path, mtime)` por arquivo — invalida
automaticamente se o STL for modificado em disco. `progress_cb` **não** é
passado para dentro dessa função (callbacks não são serializáveis como chave
de cache); o feedback de progresso para o caminho de disco é gerenciado
diretamente no `app.py` verificando a presença dos arquivos `.dcubic_cache.*`.

---

## Apresentação didática (sidebar)

| Controle | Descrição |
|----------|-----------|
| Botão "Sólido" | Reset de opacidade para 1,0 |
| Slider "Opacidade" | 0,05 – 1,0, step 0,05 |
| Radio "Aparência" | **Cinza (tom ajustável)** ou **Cor personalizada** |
| Slider "Tom (claro ↔ escuro)" | 0–255, default 235; gera `(tone, tone, tone)` |
| Color picker "Cor da estrutura" | Ativo somente no modo "Cor personalizada" |
| Checkbox de visibilidade | Mostra/oculta a estrutura no render |

---

## Layout do render 3D

- **Altura:** 720 px, largura 100% do container.
- **Dragmode:** `orbit` — permite rotação livre em qualquer ângulo, inclusive
  vista de cima, sem travar o eixo Z.
- **Aspect:** `data` — escala proporcional aos dados reais do STL.
- **Fontes dos eixos:** título 18 px, ticks 15 px.
- **Botões de câmera** (acima do gráfico, via `updatemenus`):

| Botão | `camera.eye` |
|-------|-------------|
| Topo | `(0, 0, 2.2)`, up `(0, 1, 0)` |
| Frente | `(0, -2.2, 0)` |
| Lado | `(2.2, 0, 0)` |
| Perspectiva | `(1.5, 1.5, 1.2)` |

---

## Limitações conhecidas

| Limitação | Status |
|-----------|--------|
| **Calibração de voxel** | Pendente. `volume_native` e `area_native` estão nas unidades de coordenada do STL exportado pelo Bruker CTAnalyser (possivelmente µm, não mm). Conversão para mm³/mm² exige o `pixel size` do log de reconstrução do scan. |
| **Densidade** | Não é calculável a partir de STL. STL representa apenas superfície; densidade requer o volume de voxels do scan original (DICOM/TIFF). |
| **Múltiplas estruturas simultâneas** | O modo STL-5 exibe uma estrutura por vez. Para comparação entre estruturas, seria necessário selecionar múltiplos arquivos — funcionalidade futura. |
| **Deploy em nuvem** | A leitura local (Caminho A) acessa o sistema de arquivos do servidor. Antes de qualquer deploy na USP/Streamlit Cloud, revisar essa decisão e trocar a senha do usuário `admin` (hoje `admin123`, fraca, uso local apenas). |
