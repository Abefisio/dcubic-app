# Análise de otimização do DCUBIC (FASE 1, somente leitura) — 21/10/2026

- Repositório: `Abefisio/dcubic-app`, branch `feature/upload-link-drive` (código analisado em `ddd01ea`; nenhum arquivo de código alterado).
- Máquina: Apple M1 Pro, 16 GB, Python 3.9.6 (CommandLineTools), Streamlit 1.50.0. O Cloud usa Python 3.12 (`runtime.txt`): os tempos lá podem diferir.
- Método: funções dos módulos chamadas diretamente, `streamlit.testing.v1.AppTest` (login simulado por `session_state`, sem ler senha), servidor temporário na porta 8502 (encerrado), `/usr/bin/time -l`, cProfile, `ast`, `importtime`. O servidor da porta 8501 (PID 20821) não foi tocado.
- Backup: tag `backup-fase1-20261021-1615`.
- **Nada foi otimizado.** A FASE 2 só começa depois que o Dr. Abe escolher os itens.

## Resumo dos números principais

| Medição | Valor |
|---|---|
| Servidor até responder `/_stcore/health` | 0,64–0,73 s; RSS ocioso 72–73 MB |
| Imports do app (sem .pyc / com .pyc) | 1,96–2,15 s / 0,92–0,98 s; ~147 MB |
| Tela de login (1ª execução / rerun) | 3,37 s / 0,79 s; 218 MB |
| Abrir dente, disco frio (Molar / MOLAR-SUP / Incisivo / 34-PRE) | 0,21 / 0,79 / 1,18 / 1,31 s |
| Abrir dente, disco quente | 0,03–0,07 s |
| Cortes 3 eixos | 0,13–0,23 s (+ preparo 0,04–0,10 s) |
| Montagem do 3D (Plotly + interior + HTML) | 0,23–0,29 s; HTML de 5,3–12,6 MB |
| App inteiro, aba 3D, 1ª execução (disco quente / frio) | 3,51–3,71 s / 4,98 s |
| Rerun com caches em memória | 0,11–0,16 s |
| Pico de memória medido | 732 MB (34-PRE, disco frio, aba 3D) |
| Não medido | Esmalte, Dentina e Pré-molar-sup (não estão em `/tmp/dcubic_samples`; exigiriam baixar do Drive) e renderização no navegador (exigiria login no navegador) |

Os 5 pontos mais lentos (cProfile, 34-PRE a frio): 1) `import trimesh` em `modules/slices.py:17` (1,20 s; mais `compile` de 1,10 s por causa de `PYTHONDONTWRITEBYTECODE=1`); 2) `decimate_pro` em `modules/mesh_loader.py:114` (0,81 s); 3) `gerar_corte` em `modules/slices.py:120` (0,24 s, `_secao` 0,17 s); 4) `preencher_interior` em `modules/mesh_fill.py:76` (0,14–0,17 s); 5) `carregar_trimesh` + `bbox_combinado` em `modules/slices.py:47,58` (0,10 + 0,12 s).

## Tabela (ordenada por ganho/risco, 10 itens)

| # | problema | impacto medido | correção proposta | risco | esforço |
|---|---|---|---|---|---|
| 1 | O limite real de envio do servidor é 2048 MB: `.streamlit/config.toml:8` (`maxUploadSize = 2048`) é lido na partida (`server.py:179`); o rebaixamento para 200 MB em `app.py:366-369` só vale para o seletor no navegador. O envio fica em RAM e o endpoint só exige sessão ativa, não login. | Até 2048 MB aceitos por envio contra ~1 GB de RAM no Cloud; pico já medido localmente de 2,9 GB com 780 MB enviados. Ataque direto (sem navegador) não testado. | `maxUploadSize = 200` no `config.toml` versionado; 2048 apenas no Mac (`--server.maxUploadSize 2048` ou `~/.streamlit/config.toml`). Também elimina uma das duas fontes de configuração. | Baixo | Baixo (1 linha + comando local) |
| 2 | "Zip bomb" no envio direto de .zip: só há limite por membro (2 GB, `stl_compactar.py:47,156`); sem limite de soma, de razão nem de espaço em disco (a checagem de disco existe só no caminho do Drive, `stl_compactar.py:254-259`). Falha na etapa 1 deixa arquivos em `recebidos/` (`app.py:432-434`). | Teste real: zip de 51.322 B gravou 52.428.800 B (razão 1022:1) sem objeção. | Reaproveitar a checagem do Drive (`1,1 × soma descompactada ≤ espaço livre` e soma ≤ limite) também em `receber`; limpar `recebidos/` no erro da etapa 1. | Baixo | Baixo |
| 3 | Login sem limite de tentativas (`app.py:186`, sem `max_login_attempts`); logins (e-mails) visíveis no repositório público; backup `auth/users.yaml.bak-*` (com hashes e chave do cookie) protegido só por `.git/info/exclude`, regra que não vale em outro clone. | 0 limite de tentativas; 9 linhas com logins em 3 arquivos públicos (`secrets.toml.template` 4, `DEPLOY-STREAMLIT.md` 4, `DEPLOY-HUGGINGFACE.md` 1); 0 senhas e 0 hashes no histórico (108 commits). | `auth/*` no `.gitignore` (mantendo os templates); trocar os e-mails dos documentos por exemplos fictícios; limite de tentativas com contador em `st.session_state` (o contador da biblioteca é recriado a cada rerun, `app.py:157`). | Baixo | Baixo–médio |
| 4 | Disco e concorrência no Cloud: `DCUBIC_MAX_DRIVE_MB` ainda não definido (padrão 2048, `stl_compactar.py:167`); com `FATOR_DISCO = 2.5` cada importação de 2 GB exige ~5 GB livres; cache `/tmp/dcubic_upload_cache` nunca é limpo; nome fixo `drive_{fid[:8]}.part` (`stl_compactar.py:224`) faz dois usuários com o mesmo link sobrescreverem um ao outro. | 2048 MB × 2,5 = ~5 GB por importação; 0 rotinas de limpeza do cache; corrida não reproduzida (análise de código). | Criar o secret `DCUBIC_MAX_DRIVE_MB = 1024` no Cloud (ação do Dr. Abe no painel); nome temporário único (`tempfile`); apagar pastas do cache com mais de N dias na partida. | Baixo | Baixo |
| 5 | `_load_stl_from_paths.clear()` (`app.py:638-640`) esvazia o cache inteiro a cada troca de dente/seleção, anulando o `max_entries=2`. | Voltar a um dente já aberto relê do disco: 0,03–0,07 s (disco quente) até 0,79–1,31 s (disco frio) em vez de ~0 s. | Remover o `.clear()` e confiar no `max_entries=2` (já limita a 2 dentes na RAM). | Baixo (memória continua limitada) | Baixo (3 linhas) |
| 6 | Na aba 3D, cada ajuste de Aparência (opacidade, tom, vista) reenvia o HTML inteiro do Plotly, porque o estado `_ap` vai embutido na mesma string (`app.py:1030-1041`); o iframe recarrega a malha. O cache `_fragmento_3d_cached` guarda até 4 strings desse tamanho. | 12,63 MB reenviados por ajuste (Incisivo); 11,2–12,6 MB nos outros dentes (MOLAR-SUP 5,3 MB); rerun no servidor só 108–149 ms — o custo está na rede/navegador (não medido no navegador). | Separar a malha (HTML fixo, enviado uma vez) do estado de aparência (mensagem pequena via `postMessage`/componente); opcionalmente arredondar coordenadas para reduzir o HTML. | Médio (mexe no visualizador 3D) | Médio |
| 7 | Inicialização lenta por imports: `trimesh` importado no topo de `modules/slices.py`; `reportlab` e módulos do modo volume importados no topo de `app.py:47-57`; `PYTHONDONTWRITEBYTECODE=1` no ambiente local recompila tudo a cada partida. | Imports 1,96–2,15 s sem .pyc vs 0,92–0,98 s com .pyc (`compile` 1,10 s; 1.361 módulos); `trimesh` 1,07–1,20 s; modo volume +200–340 ms (`reportlab` ~200 ms). | Imports tardios (`trimesh` dentro das funções de corte; `report`/volume só quando o modo volume abrir); no Mac, iniciar o servidor sem `PYTHONDONTWRITEBYTECODE`. | Baixo | Baixo |
| 8 | Implantação dispersa: a demo (`teste/frenteB-corte`, 4f8d9dc) está defasada e é, na prática, outro app; `DEPLOY-HUGGINGFACE.md` e o ramo `AUTH_CONFIG_JSON` (`app.py:138-146`) sem uso; `DEPLOY-STREAMLIT.md` desatualizado; limites lidos de fontes diferentes (`LIMITE_SEGURO_MB` só do ambiente, os demais de secrets → ambiente). | Demo 20 commits atrás da `main` e 7 próprios; diff de 8 arquivos (+299/−1291), sem `stl_compactar.py` nem `slices.py`, `maxUploadSize = 100`. Ambas as URLs respondem `/_stcore/health` 200 em 0,41–0,43 s. | Decisão do Dr. Abe no painel do Cloud: apontar a demo para a `main` (ou para uma branch de teste atualizada) ou desativá-la; remover a documentação/ramo do HuggingFace; atualizar `DEPLOY-STREAMLIT.md`; ler todos os `DCUBIC_*` pela mesma função. | Baixo | Baixo |
| 9 | Reruns duplos e cálculos sem cache no modo STL: `st.rerun()` em 7 pontos (`app.py:438, 459, 557, 593, 623, 778, 1348`); 0 `st.fragment`; `slices.bbox_combinado` (`app.py:799`) roda a cada rerun. | Botão de olho: 2 execuções do script por clique (122–160 ms); envio: 3 execuções; `bbox_combinado` 59–117 ms por rerun. | Trocar o `st.rerun()` do olho (e similares) por `on_click`; colocar `bbox_combinado` em `st.cache_data`. | Baixo | Baixo |
| 10 | Modo volume com dados sintéticos: só acessível pelo botão "Abrir modo volume (dados sintéticos)" (`app.py:1068`); `_load_uploaded_vol` (`app.py:224-243`) e `slices.tempo_corte` sem nenhuma chamada; pydicom/tifffile/nibabel inalcançáveis; exportações STL/OBJ recalculadas a cada rerun (`app.py:1420,1428`). | ~1.462 de 3.905 linhas .py (37%); 0 referências a `_load_uploaded_vol`; rerun do modo volume 525 ms, dos quais 281 ms são as exportações; 3 dependências mortas. | Decisão do Dr. Abe: (a) remover o modo volume e as 3 dependências (apagar arquivos exige aprovação); ou (b) mantê-lo e gerar as exportações só ao clicar (cache/botão). Manter `shapely`, `networkx` e `scikit-image` (usados pelo trimesh e por "Revelar interior"). | Médio (remove uma função visível) | Médio |

Itens 1, 2, 3, 4, 5, 7 e 9 não mudam o que o usuário vê; os itens 8 e 10 dependem de decisão do Dr. Abe; o item 6 é o que mais deve melhorar a sensação de velocidade no Cloud, mas é o de maior risco técnico.

## Saídas brutas

Saídas copiadas dos arquivos de medição (sem senhas, hashes, chaves ou e-mails). Scripts e saídas completas ficaram no scratchpad da sessão (`perf/`, `codigo/`, `seg/`).

### Molar.frio.txt

```
inicio (python+psutil)                0.000 s   RSS=   11.8 MB  pico=   11.8 MB
import numpy                          0.111 s   RSS=   28.5 MB  pico=   28.5 MB
import streamlit                      0.438 s   RSS=   73.7 MB  pico=   73.7 MB
import pyvista                        0.411 s   RSS=  153.5 MB  pico=  153.5 MB
import plotly.graph_objects           0.000 s   RSS=  153.5 MB  pico=  153.5 MB
import modules (loader/3d/slices/fill)    1.283 s   RSS=  213.1 MB  pico=  215.7 MB
# exemplo=Molar  arquivos=['Molar.stl']  cache_disco=FRIO
1) load_meshes (abrir dente)          0.211 s   RSS=  249.5 MB  pico=  249.5 MB
   Molar: faces_orig=200000 faces_exib=200000 err=None
2) carregar_trimesh (todas)           0.038 s   RSS=  307.3 MB  pico=  307.3 MB
3) gerar_corte Axial (Z)              0.124 s   RSS=  317.9 MB  pico=  320.0 MB
3) gerar_corte Coronal (Y)            0.037 s   RSS=  318.7 MB  pico=  320.0 MB
3) gerar_corte Sagital (X)            0.046 s   RSS=  319.5 MB  pico=  320.0 MB
3) cortes 3 eixos (soma)              0.207 s   RSS=  319.5 MB  pico=  320.0 MB
4a) create_plotly_3d                  0.067 s   RSS=  332.8 MB  pico=  332.8 MB
4b) preencher_interior(128)           0.171 s   RSS=  353.4 MB  pico=  353.4 MB
4c) add_trace+layout+limpar           0.012 s   RSS=  373.3 MB  pico=  373.3 MB
4d) fig.to_html                       0.053 s   RSS=  442.5 MB  pico=  442.5 MB
   html=12.6 MB  interior_faces=236610
TOTAL abrir+cortes+3D                 0.797 s   RSS=  442.5 MB  pico=  442.5 MB
        3.20 real         3.91 user         0.87 sys
           463962112  maximum resident set size
                   0  average shared memory size
                   0  average unshared data size
                   0  average unshared stack size
               55404  page reclaims
                 415  page faults
                   0  swaps
                   0  block input operations
                   0  block output operations
                   0  messages sent
                   0  messages received
                   0  signals received
                 151  voluntary context switches
                3140  involuntary context switches
         39670693001  instructions retired
         14577828816  cycles elapsed
           386958272  peak memory footprint
```

### 34-PRE.frio.txt

```
inicio (python+psutil)                0.000 s   RSS=   11.9 MB  pico=   11.9 MB
import numpy                          0.112 s   RSS=   28.2 MB  pico=   28.2 MB
import streamlit                      0.436 s   RSS=   73.7 MB  pico=   73.7 MB
import pyvista                        0.403 s   RSS=  153.9 MB  pico=  153.9 MB
import plotly.graph_objects           0.000 s   RSS=  153.9 MB  pico=  153.9 MB
import modules (loader/3d/slices/fill)    1.162 s   RSS=  213.5 MB  pico=  216.1 MB
# exemplo=34-PRE  arquivos=['34pre__rec_tra(1)_reduzido.stl', '34pre__rec_tra_reduzido.stl']  cache_disco=FRIO
1) load_meshes (abrir dente)          1.313 s   RSS=  307.1 MB  pico=  307.1 MB
   34pre__rec_tra(1)_reduzido: faces_orig=309290 faces_exib=200000 err=None
   34pre__rec_tra_reduzido: faces_orig=308229 faces_exib=255755 err=None
2) carregar_trimesh (todas)           0.102 s   RSS=  487.1 MB  pico=  487.1 MB
3) gerar_corte Axial (Z)              0.094 s   RSS=  515.7 MB  pico=  517.8 MB
3) gerar_corte Coronal (Y)            0.095 s   RSS=  517.9 MB  pico=  518.2 MB
3) gerar_corte Sagital (X)            0.044 s   RSS=  518.0 MB  pico=  518.2 MB
3) cortes 3 eixos (soma)              0.233 s   RSS=  518.0 MB  pico=  518.2 MB
4a) create_plotly_3d                  0.069 s   RSS=  549.5 MB  pico=  549.5 MB
4b) preencher_interior(128)           0.145 s   RSS=  558.9 MB  pico=  558.9 MB
4c) add_trace+layout+limpar           0.006 s   RSS=  558.9 MB  pico=  558.9 MB
4d) fig.to_html                       0.041 s   RSS=  551.8 MB  pico=  571.4 MB
   html=11.2 MB  interior_faces=24534
TOTAL abrir+cortes+3D                 2.030 s   RSS=  551.8 MB  pico=  571.4 MB
        4.30 real         5.18 user         0.77 sys
           599179264  maximum resident set size
                   0  average shared memory size
                   0  average unshared data size
                   0  average unshared stack size
               64391  page reclaims
                  23  page faults
                   0  swaps
                   0  block input operations
                   0  block output operations
                   0  messages sent
                   0  messages received
                   0  signals received
                   8  voluntary context switches
                3319  involuntary context switches
         49441595903  instructions retired
         18404293087  cycles elapsed
           522519560  peak memory footprint
```

### apptest_34-PRE_3D_FRIO.txt

```
2026-10-21 16:20:44.910 WARNING streamlit.runtime.scriptrunner_utils.script_run_context: Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:20:44.910 WARNING streamlit.runtime.scriptrunner_utils.script_run_context: Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:20:44.910 WARNING streamlit.runtime.scriptrunner_utils.script_run_context: Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:20:44.910 WARNING streamlit.runtime.scriptrunner_utils.script_run_context: Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:20:44.910 WARNING streamlit.runtime.scriptrunner_utils.script_run_context: Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:20:44.910 WARNING streamlit.runtime.scriptrunner_utils.script_run_context: Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
/Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
2026-10-21 16:20:49.890 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:20:49.890 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:20:49.890 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:20:49.890 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:20:49.890 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:20:49.890 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:20:49.890 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
import AppTest                   0.478 s  RSS=   69.9 MB  pico=   69.9 MB
run 1 (a / 3D)    4.979 s  RSS=  647.2 MB  pico=  647.4 MB  excecoes=[]  erros=[]  imagens=0  html=1
run 2 (a / 3D)    0.151 s  RSS=  698.4 MB  pico=  698.5 MB  excecoes=[]  erros=[]  imagens=0  html=1
        5.84 real         6.26 user         1.23 sys
           732381184  maximum resident set size
                   0  average shared memory size
                   0  average unshared data size
                   0  average unshared stack size
               79062  page reclaims
                  19  page faults
                   0  swaps
                   0  block input operations
                   0  block output operations
                   0  messages sent
                   0  messages received
                   0  signals received
                2204  voluntary context switches
                6516  involuntary context switches
         60886565181  instructions retired
         23340301929  cycles elapsed
           634389824  peak memory footprint
```

### import1.txt

```
2026-10-21 16:20:13.689 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:20:13.690 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:20:13.691 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:20:13.691 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
/Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
2026-10-21 16:20:13.873 No runtime found, using MemoryCacheStorageManager
streamlit                     0.444 s  RSS=  66.8 MB
numpy                         0.106 s  RSS=  74.8 MB
yaml                          0.026 s  RSS=  75.5 MB
extra_streamlit_components    0.035 s  RSS=  75.6 MB
streamlit_authenticator       0.209 s  RSS=  91.2 MB
modules.loader                0.000 s  RSS=  91.2 MB
modules.viewer2d              0.000 s  RSS=  91.2 MB
modules.segmentation          0.000 s  RSS=  91.2 MB
modules.viewer3d              0.047 s  RSS=  92.7 MB
modules.metrics               0.000 s  RSS=  92.7 MB
modules.report                0.176 s  RSS= 100.8 MB
modules.anatomy               0.374 s  RSS= 121.5 MB
modules.references            0.000 s  RSS= 121.5 MB
modules.mesh_loader           0.000 s  RSS= 121.5 MB
modules.slices                0.538 s  RSS= 146.9 MB
TOTAL imports                 1.956 s  pico= 147.3 MB
        2.11 real         3.15 user         0.62 sys
           154435584  maximum resident set size
                   0  average shared memory size
                   0  average unshared data size
                   0  average unshared stack size
               24129  page reclaims
                  18  page faults
                   0  swaps
                   0  block input operations
                   0  block output operations
                   0  messages sent
                   0  messages received
                   0  signals received
                   2  voluntary context switches
                2576  involuntary context switches
         29700457365  instructions retired
         11417250034  cycles elapsed
           128991784  peak memory footprint
```

### import_pyc1.txt

```
2026-10-21 16:21:27.145 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:21:27.147 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:21:27.148 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:21:27.149 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
/Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
2026-10-21 16:21:27.276 No runtime found, using MemoryCacheStorageManager
streamlit                     0.193 s  RSS=  59.6 MB
numpy                         0.033 s  RSS=  67.3 MB
yaml                          0.014 s  RSS=  68.1 MB
extra_streamlit_components    0.041 s  RSS=  68.6 MB
streamlit_authenticator       0.138 s  RSS=  84.1 MB
modules.loader                0.000 s  RSS=  84.1 MB
modules.viewer2d              0.000 s  RSS=  84.2 MB
modules.segmentation          0.000 s  RSS=  84.2 MB
modules.viewer3d              0.025 s  RSS=  86.3 MB
modules.metrics               0.000 s  RSS=  86.3 MB
modules.report                0.054 s  RSS=  90.8 MB
modules.anatomy               0.219 s  RSS= 110.5 MB
modules.references            0.000 s  RSS= 110.6 MB
modules.mesh_loader           0.000 s  RSS= 110.6 MB
modules.slices                0.265 s  RSS= 137.0 MB
TOTAL imports                 0.983 s  pico= 137.1 MB
        1.12 real         2.04 user         0.40 sys
           143785984  maximum resident set size
                   0  average shared memory size
                   0  average unshared data size
                   0  average unshared stack size
               22746  page reclaims
                  28  page faults
                   0  swaps
                   0  block input operations
                   0  block output operations
                   0  messages sent
                   0  messages received
                   0  signals received
                   2  voluntary context switches
                3713  involuntary context switches
         17257083943  instructions retired
          7168587390  cycles elapsed
           118342184  peak memory footprint
```

### server_health.txt

```
GET / http=200 t=0.002140s bytes=1522
run 1: PID=23094  health 200 apos 0.719 s
   RSS ocioso (servidor sem sessao) = 73.0 MB  PID=23094
GET / http=200 t=0.001732s bytes=1522
run 2: PID=23133  health 200 apos 0.636 s
   RSS ocioso (servidor sem sessao) = 72.5 MB  PID=23133
GET / http=200 t=0.001361s bytes=1522
run 3: PID=23169  health 200 apos 0.725 s
   RSS ocioso (servidor sem sessao) = 72.4 MB  PID=23169
```

### cprofile_top15.txt

```
============================== frio
Wed Oct 21 16:20:54 2026    out/prof_34-PRE_frio.prof

         1460846 function calls (1408229 primitive calls) in 4.350 seconds

   Ordered by: cumulative time
   List reduced from 7333 to 15 due to restriction <15>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
   1919/1    0.013    0.000    4.351    4.351 {built-in method builtins.exec}
        1    0.000    0.000    4.351    4.351 bench_dente.py:1(<module>)
 2163/156    0.005    0.000    2.372    0.015 <frozen importlib._bootstrap>:1002(_find_and_load)
  1895/36    0.004    0.000    2.370    0.066 <frozen importlib._bootstrap>:967(_find_and_load_unlocked)
  1840/38    0.004    0.000    2.367    0.062 <frozen importlib._bootstrap>:659(_load_unlocked)
  1659/37    0.002    0.000    2.366    0.064 <frozen importlib._bootstrap_external>:844(exec_module)
  3896/61    0.001    0.000    2.365    0.039 <frozen importlib._bootstrap>:220(_call_with_frames_removed)
   847/43    0.001    0.000    2.011    0.047 {built-in method builtins.__import__}
 2051/305    0.001    0.000    1.940    0.006 <frozen importlib._bootstrap>:1033(_handle_fromlist)
        1    0.000    0.000    1.328    1.328 /Users/abeyuujirou/Developer/dcubic-app-repo/modules/mesh_loader.py:151(load_meshes)
        2    0.000    0.000    1.328    0.664 /Users/abeyuujirou/Developer/dcubic-app-repo/modules/mesh_loader.py:13(load_mesh)
    65/30    0.000    0.000    1.233    0.041 /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/pyvista/_deprecate_positional_args.py:191(inner_f)
     1659    0.006    0.000    1.216    0.001 <frozen importlib._bootstrap_external>:916(get_code)
        1    0.000    0.000    1.200    1.200 /Users/abeyuujirou/Developer/dcubic-app-repo/modules/slices.py:1(<module>)
        1    0.000    0.000    1.189    1.189 /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/trimesh/__init__.py:1(<module>)


============================== quente
Wed Oct 21 16:20:58 2026    out/prof_34-PRE_quente.prof

         1450151 function calls (1399804 primitive calls) in 3.149 seconds

   Ordered by: cumulative time
   List reduced from 7250 to 15 due to restriction <15>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
   1919/1    0.013    0.000    3.150    3.150 {built-in method builtins.exec}
        1    0.000    0.000    3.149    3.149 bench_dente.py:1(<module>)
 2163/156    0.005    0.000    2.402    0.015 <frozen importlib._bootstrap>:1002(_find_and_load)
  1895/36    0.004    0.000    2.400    0.067 <frozen importlib._bootstrap>:967(_find_and_load_unlocked)
  1840/38    0.004    0.000    2.397    0.063 <frozen importlib._bootstrap>:659(_load_unlocked)
  1659/37    0.002    0.000    2.396    0.065 <frozen importlib._bootstrap_external>:844(exec_module)
  3896/61    0.001    0.000    2.394    0.039 <frozen importlib._bootstrap>:220(_call_with_frames_removed)
   847/43    0.001    0.000    2.039    0.047 {built-in method builtins.__import__}
 2051/305    0.001    0.000    1.968    0.006 <frozen importlib._bootstrap>:1033(_handle_fromlist)
     1659    0.006    0.000    1.223    0.001 <frozen importlib._bootstrap_external>:916(get_code)
        1    0.000    0.000    1.220    1.220 /Users/abeyuujirou/Developer/dcubic-app-repo/modules/slices.py:1(<module>)
        1    0.000    0.000    1.209    1.209 /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/trimesh/__init__.py:1(<module>)
     1770    1.098    0.001    1.098    0.001 {built-in method builtins.compile}
     1361    0.001    0.000    1.097    0.001 <frozen importlib._bootstrap_external>:908(source_to_code)
        1    0.000    0.000    0.819    0.819 /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/trimesh/bounds.py:1(<module>)


```

### cprofile_frio_app_funcs.txt

```
Wed Oct 21 16:20:54 2026    out/prof_34-PRE_frio.prof

         1460846 function calls (1408229 primitive calls) in 4.350 seconds

   Ordered by: cumulative time
   List reduced from 7333 to 73 due to restriction <'dcubic-app-repo|decimate|triangulate|pyvista/core/utilities/fileio.py.*read|save|to_html|binary_closing|marching|_inside_fallback|section|trimesh/exchange/load'>
   List reduced from 73 to 25 due to restriction <25>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
        1    0.000    0.000    1.328    1.328 /Users/abeyuujirou/Developer/dcubic-app-repo/modules/mesh_loader.py:151(load_meshes)
        2    0.000    0.000    1.328    0.664 /Users/abeyuujirou/Developer/dcubic-app-repo/modules/mesh_loader.py:13(load_mesh)
        1    0.000    0.000    1.200    1.200 /Users/abeyuujirou/Developer/dcubic-app-repo/modules/slices.py:1(<module>)
        2    0.000    0.000    0.808    0.404 /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/pyvista/core/filters/poly_data.py:1073(decimate_pro)
        3    0.003    0.001    0.240    0.080 /Users/abeyuujirou/Developer/dcubic-app-repo/modules/slices.py:120(gerar_corte)
        2    0.000    0.000    0.203    0.101 /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/pyvista/core/pointset.py:1442(save)
        2    0.000    0.000    0.193    0.096 /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/pyvista/core/utilities/fileio.py:172(read)
        6    0.000    0.000    0.167    0.028 /Users/abeyuujirou/Developer/dcubic-app-repo/modules/slices.py:69(_secao)
        1    0.000    0.000    0.144    0.144 /Users/abeyuujirou/Developer/dcubic-app-repo/modules/mesh_fill.py:76(preencher_interior)
        6    0.000    0.000    0.128    0.021 /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/trimesh/base.py:2310(section)
        1    0.000    0.000    0.119    0.119 /Users/abeyuujirou/Developer/dcubic-app-repo/modules/slices.py:58(bbox_combinado)
        1    0.000    0.000    0.119    0.119 /Users/abeyuujirou/Developer/dcubic-app-repo/modules/slices.py:60(<listcomp>)
        6    0.046    0.008    0.100    0.017 /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/trimesh/intersections.py:17(mesh_plane)
        2    0.000    0.000    0.099    0.049 /Users/abeyuujirou/Developer/dcubic-app-repo/modules/slices.py:47(carregar_trimesh)
        2    0.000    0.000    0.085    0.043 /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/trimesh/exchange/load.py:73(load)
        2    0.000    0.000    0.085    0.043 /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/trimesh/exchange/load.py:157(load_scene)
        1    0.000    0.000    0.077    0.077 /Users/abeyuujirou/Developer/dcubic-app-repo/modules/viewer3d.py:67(create_plotly_3d)
        2    0.000    0.000    0.075    0.037 /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/trimesh/exchange/load.py:396(_load_kwargs)
        2    0.000    0.000    0.075    0.037 /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/trimesh/exchange/load.py:454(handle_mesh)
        1    0.010    0.010    0.067    0.067 /Users/abeyuujirou/Developer/dcubic-app-repo/modules/mesh_fill.py:33(_inside_fallback)
        2    0.000    0.000    0.067    0.033 /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/pyvista/core/dataobject.py:120(save)
        1    0.000    0.000    0.058    0.058 /Users/abeyuujirou/Developer/dcubic-app-repo/modules/viewer3d.py:1(<module>)
        1    0.000    0.000    0.041    0.041 /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/plotly/basedatatypes.py:3517(to_html)
        3    0.000    0.000    0.039    0.013 /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/PIL/Image.py:2474(save)
        1    0.000    0.000    0.037    0.037 /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/plotly/io/_html.py:35(to_html)


```

### final_check.txt

```
  PID    RSS ELAPSED COMMAND
20821  66976   21:45 /Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python -m streamlit run app.py --server.headless true --server.port 8501 --server.address 127.0.0.1
--- escutando 8501/8502:
COMMAND   PID        USER   FD   TYPE             DEVICE SIZE/OFF NODE NAME
Python  20821 abeyuujirou    7u  IPv4 0x6bbdf4c7602016b3      0t0  TCP 127.0.0.1:8501 (LISTEN)
--- processos streamlit:
20821 /Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python -m streamlit run app.py --server.headless true --server.port 8501 --server.address 127.0.0.1
--- git status do repo:
(fim git status)
```

### 00_base.txt

```
CHANGELOG.md
app.py
assets
auth
docs
modules
packages.txt
requirements.txt
runtime.txt
tools
modules:
__init__.py
anatomy.py
loader.py
mesh_fill.py
mesh_loader.py
metrics.py
references.py
report.py
segmentation.py
slices.py
stl_compactar.py
viewer2d.py
viewer3d.py

tools:
gen_site_shots.py
reduzir_stl.py
    1466 app.py
       0 modules/__init__.py
     124 modules/anatomy.py
     225 modules/loader.py
     166 modules/mesh_fill.py
     166 modules/mesh_loader.py
      86 modules/metrics.py
     130 modules/references.py
     174 modules/report.py
      99 modules/segmentation.py
     190 modules/slices.py
     530 modules/stl_compactar.py
     122 modules/viewer2d.py
     177 modules/viewer3d.py
     118 tools/gen_site_shots.py
     132 tools/reduzir_stl.py
    3905 total
streamlit==1.50.0
numpy>=1.24.0
scipy>=1.11.0
scikit-image>=0.22.0
pydicom>=2.4.0
tifffile>=2023.9.26
nibabel>=5.2.0
pyvista>=0.43.0
plotly>=5.18.0
reportlab>=4.0.0
extra-streamlit-components>=0.1.71
streamlit-authenticator==0.4.2
pyyaml>=6.0
gdown>=5.0.0
trimesh>=4.0.0
shapely>=2.0.0
networkx>=3.0
pillow>=10.0.0
---
libgl1
libglx-mesa0
libglu1-mesa
xvfb
python-3.12
```

### 01_cache.txt

```
== cache
app.py:219:@st.cache_data(show_spinner=False)
app.py:224:@st.cache_data(show_spinner="Carregando volume enviado...")
app.py:252:@st.cache_resource(max_entries=2)  # 2 dentes na RAM, no máximo
app.py:268:@st.cache_resource(show_spinner="Preparando cortes…", max_entries=2)  # só as estruturas recentes na RAM
app.py:274:@st.cache_data(show_spinner=False, max_entries=64)
app.py:283:@st.cache_data(hash_funcs={np.ndarray: _arr_hash}, show_spinner=False)
app.py:289:@st.cache_data(hash_funcs={np.ndarray: _arr_hash}, show_spinner=False)
app.py:295:@st.cache_resource(show_spinner="Gerando interior…", max_entries=2)
app.py:844:            @st.cache_data(show_spinner="Montando o 3D…", max_entries=4)  # ~2 dentes (com e sem plano)
== rerun/fragment/on_change
app.py:325:# Opções da aba Cortes: reatribuídas ANTES dos botões que chamam st.rerun() (troca de
app.py:438:    st.rerun()
app.py:459:    st.rerun()
app.py:557:                st.rerun()
app.py:593:            st.rerun()
app.py:623:    st.rerun()
app.py:750:                      on_change=_ap_marca, args=("ap_opac_on",))
app.py:753:                     on_change=_ap_marca, args=("ap_cor_on",))
app.py:756:                          on_change=_ap_marca, args=("ap_cor_on",))
app.py:759:                                on_change=_ap_marca, args=("ap_cor_on",))
app.py:761:                     on_change=_ap_vista)
app.py:762:    st.sidebar.button("🏠 Resetar vista", key="ap_reset", on_click=_ap_reset, width="stretch")
app.py:778:            st.rerun()
app.py:1069:              on_click=lambda: st.session_state.update(modo_volume=True))
app.py:1348:                st.rerun()
== imports app.py
6:import hashlib
7:import json
8:import os
9:import traceback as _tb
10:import streamlit as st
11:import numpy as np
14:    import yaml
15:    import extra_streamlit_components as stx
35:import sys as _sys
45:import streamlit_authenticator as stauth
47:from modules.loader import load_volume
48:from modules.viewer2d import render_triplanar, make_overlay_fig
49:from modules.segmentation import segment_volume, TISSUE_PALETTE, DEFAULT_THRESHOLDS
50:from modules.viewer3d import build_all_meshes, create_plotly_3d, limpar_figura_3d
51:from modules.metrics import (
55:from modules.report import generate_pdf
56:from modules.anatomy import compute_anatomy
57:from modules import references
58:from modules.mesh_loader import load_meshes
59:from modules import slices as _slices
72:import base64 as _b64mod
73:import streamlit.components.v1 as _components
168:    import time
231:    import os, tempfile
299:    from modules.mesh_fill import preencher_interior
365:from streamlit import config as _st_config
394:    from modules import stl_compactar as _cmp
414:        from streamlit.runtime import Runtime
415:        from streamlit.runtime.scriptrunner import get_script_run_ctx
425:    from modules import stl_compactar as _cmp
440:    from modules import stl_compactar as _cmp
457:    import gc as _gc
521:            import gdown, zipfile as _zf, glob as _glob_ex
538:            import glob as _glob_ex
564:                import gdown
598:    import glob as _glob
717:    import time as _time
870:                            import plotly.graph_objects as _go
890:                    import plotly.graph_objects as _gop
960:            import streamlit.components.v1 as _components
```

### 05_deps.txt

```
pacote                       import                       n  locais (modo)
streamlit                    streamlit                    6  app.py:10, app.py:73, app.py:365, app.py:414, app.py:415, app.py:960  [app]
numpy                        numpy                       10  app.py:11, modules/anatomy.py:16, modules/loader.py:12, modules/mesh_fill.py:16, modules/metrics.py:12, modules/segmentation.py:11, modules/slices.py:17, modules/stl_compactar.py:32, modules/viewer2d.py:9, modules/viewer3d.py:16  [ambos/app/stl/volume]
scipy                        scipy                        3  modules/anatomy.py:17, modules/mesh_fill.py:25, modules/slices.py:20  [stl/volume]
scikit-image                 skimage                      3  modules/anatomy.py:20, modules/mesh_fill.py:28, modules/viewer3d.py:18  [ambos/stl/volume]
pydicom                      pydicom                      1  modules/loader.py:20  [volume]
tifffile                     tifffile                     1  modules/loader.py:45  [volume]
nibabel                      nibabel                      1  modules/loader.py:67  [volume]
pyvista                      pyvista                      4  modules/mesh_fill.py:18, modules/mesh_loader.py:32, modules/viewer3d.py:41, tools/reduzir_stl.py:19  [ambos/stl/tools]
plotly                       plotly                       4  app.py:890, app.py:870, modules/viewer2d.py:10, modules/viewer3d.py:17  [ambos/app/volume]
reportlab                    reportlab                    5  modules/report.py:12, modules/report.py:13, modules/report.py:14, modules/report.py:15, modules/report.py:16  [volume]
extra-streamlit-components   extra_streamlit_components   1  app.py:15  [app]
streamlit-authenticator      streamlit_authenticator      1  app.py:45  [app]
pyyaml                       yaml                         1  app.py:14  [app]
gdown                        gdown                        4  app.py:521, app.py:564, modules/stl_compactar.py:217, modules/stl_compactar.py:218  [app/stl]
trimesh                      trimesh                      1  modules/slices.py:18  [stl]
shapely                      shapely                      0  -  [NENHUM import direto]
networkx                     networkx                     0  -  [NENHUM import direto]
pillow                       PIL                          1  modules/slices.py:19  [stl]

== tamanho instalado (du -sk do diretório do pacote)
streamlit                        26.5 MB  /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/streamlit
numpy                            20.4 MB  /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/numpy
scipy                            91.4 MB  /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/scipy
scikit-image                     28.3 MB  /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/skimage
pydicom                      NÃO INSTALADO neste Python (/Library/Developer/CommandLineTools/usr/bin/python3)
tifffile                          1.0 MB  /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/tifffile
nibabel                      NÃO INSTALADO neste Python (/Library/Developer/CommandLineTools/usr/bin/python3)
pyvista                           6.6 MB  /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/pyvista
plotly                           40.0 MB  /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/plotly
reportlab                         4.8 MB  /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/reportlab
extra-streamlit-components        9.7 MB  /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/extra_streamlit_components
streamlit-authenticator           0.2 MB  /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/streamlit_authenticator
pyyaml                            0.6 MB  /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/yaml
gdown                             0.1 MB  /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/gdown
trimesh                           2.2 MB  /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/trimesh
shapely                           4.6 MB  /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/shapely
networkx                          6.9 MB  /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/networkx
pillow                           12.9 MB  /Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/PIL
```

### 07_import_cadeia.txt

```
2026-10-21 16:19:05.085 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:05.086 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:05.087 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:05.088 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
/Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
2026-10-21 16:19:05.270 No runtime found, using MemoryCacheStorageManager
streamlit numpy yaml extra_streamlit_components streamlit_authenticator modules.loader modules.viewer2d modules.segmentation modules.viewer3d modules.metrics modules.report modules.anatomy modules.references modules.mesh_loader modules.slices: 2125 ms
2026-10-21 16:19:07.332 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:07.333 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:07.334 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:07.335 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
/Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
2026-10-21 16:19:07.515 No runtime found, using MemoryCacheStorageManager
streamlit numpy yaml extra_streamlit_components streamlit_authenticator modules.viewer3d modules.mesh_loader modules.slices: 1787 ms
2026-10-21 16:19:09.262 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:09.263 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:09.264 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:09.265 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
/Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
2026-10-21 16:19:09.449 No runtime found, using MemoryCacheStorageManager
streamlit numpy yaml extra_streamlit_components streamlit_authenticator modules.viewer3d modules.mesh_loader modules.slices modules.report: 1998 ms
2026-10-21 16:19:11.375 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:11.376 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:11.377 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:11.378 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
/Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
2026-10-21 16:19:11.557 No runtime found, using MemoryCacheStorageManager
streamlit numpy yaml extra_streamlit_components streamlit_authenticator modules.loader modules.viewer2d modules.segmentation modules.viewer3d modules.metrics modules.report modules.anatomy modules.references modules.mesh_loader modules.slices: 1983 ms
2026-10-21 16:19:13.481 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:13.482 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:13.483 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:13.483 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
/Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
2026-10-21 16:19:13.663 No runtime found, using MemoryCacheStorageManager
streamlit numpy yaml extra_streamlit_components streamlit_authenticator modules.viewer3d modules.mesh_loader modules.slices: 1752 ms
2026-10-21 16:19:15.348 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:15.350 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:15.351 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-10-21 16:19:15.352 Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
/Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
2026-10-21 16:19:15.530 No runtime found, using MemoryCacheStorageManager
streamlit numpy yaml extra_streamlit_components streamlit_authenticator modules.viewer3d modules.mesh_loader modules.slices modules.report: 1944 ms
```

### 12_apptest_cronometro.txt

```
STLs: ['Canal_reduzido.stl', 'Dentina_reduzido.stl']
1a execução (cache Streamlit frio, cache de disco .ply quente)      2121 ms  execuções_script=1  iframe_srcdoc=12.63 MB  exc=[]
      funções: preencher_interior=145ms/1x, bbox_combinado=117ms/1x, carregar_trimesh=102ms/2x, load_meshes=78ms/1x, create_plotly_3d=71ms/1x, html=30ms/1x, limpar_figura_3d=4ms/1x
rerun sem mudança (aba 3D)                                    153 ms  execuções_script=1  iframe_srcdoc=12.63 MB  exc=[]
      funções: bbox_combinado=45ms/1x, html=30ms/1x
slider Opacidade 100->50 (aba 3D)                             109 ms  execuções_script=1  iframe_srcdoc=12.63 MB  exc=[]
      funções: html=29ms/1x, bbox_combinado=0ms/1x
slider Tom 235->120 (aba 3D)                                  149 ms  execuções_script=1  iframe_srcdoc=12.63 MB  exc=[]
      funções: html=28ms/1x, bbox_combinado=0ms/1x
radio Vista=Topo (aba 3D)                                     108 ms  execuções_script=1  iframe_srcdoc=12.63 MB  exc=[]
      funções: html=30ms/1x, bbox_combinado=0ms/1x
botão olho Canal_reduzido (oculta; st.rerun app.py:778)       157 ms  execuções_script=2  iframe_srcdoc=7.75 MB  exc=[]
      funções: html=17ms/1x, create_plotly_3d=12ms/1x, limpar_figura_3d=3ms/1x, bbox_combinado=0ms/1x
botão olho Canal_reduzido (mostra de novo, fragmento já em cache)       122 ms  execuções_script=2  iframe_srcdoc=12.63 MB  exc=[]
      funções: html=31ms/1x, bbox_combinado=0ms/1x
checkbox Revelar interior OFF                                 168 ms  execuções_script=1  iframe_srcdoc=12.17 MB  exc=[]
      funções: html=27ms/1x, create_plotly_3d=17ms/1x, limpar_figura_3d=3ms/1x, bbox_combinado=0ms/1x
checkbox Revelar interior ON (cache)                          147 ms  execuções_script=1  iframe_srcdoc=12.63 MB  exc=[]
      funções: html=26ms/1x, bbox_combinado=0ms/1x
aba Cortes (1a vez)                                           312 ms  execuções_script=1  iframe_srcdoc=0.00 MB  exc=[]
      funções: gerar_corte=229ms/3x, bbox_combinado=0ms/1x
slider corte_Axial (Z)_399.5_-231.0_-255.0_1772.5_200.0_248.0 -> 30% (corte novo)       205 ms  execuções_script=1  iframe_srcdoc=0.00 MB  exc=[]
      funções: gerar_corte=65ms/1x, bbox_combinado=59ms/1x
slider corte_Axial (Z)_399.5_-231.0_-255.0_1772.5_200.0_248.0 -> 30% de novo (cache)       137 ms  execuções_script=1  iframe_srcdoc=0.00 MB  exc=[]
      funções: bbox_combinado=59ms/1x
1a execução modo volume (cache frio)                         2163 ms  execuções_script=1  iframe_srcdoc=0.00 MB  exc=[]
      funções: mesh_to_obj_bytes=167ms/3x, mesh_to_stl_bytes=115ms/3x, compute_anatomy=64ms/1x, render_triplanar=62ms/1x, st.plotly_chart=50ms/1x, build_all_meshes=49ms/1x, create_plotly_3d=30ms/1x, make_overlay_fig=23ms/3x, compute_surface_areas=10ms/1x, segment_volume=6ms/2x, limpar_figura_3d=4ms/1x, compute_volumes=1ms/1x
rerun sem mudança (modo volume)                               525 ms  execuções_script=1  iframe_srcdoc=0.00 MB  exc=[]
      funções: mesh_to_obj_bytes=166ms/3x, mesh_to_stl_bytes=115ms/3x, st.plotly_chart=47ms/1x, make_overlay_fig=16ms/3x, create_plotly_3d=14ms/1x, render_triplanar=11ms/1x, compute_surface_areas=10ms/1x, segment_volume=6ms/2x, limpar_figura_3d=4ms/1x, compute_volumes=1ms/1x
slider Axial Z (z_idx) +5                                     526 ms  execuções_script=1  iframe_srcdoc=0.00 MB  exc=[]
      funções: mesh_to_obj_bytes=166ms/3x, mesh_to_stl_bytes=115ms/3x, st.plotly_chart=49ms/1x, make_overlay_fig=16ms/3x, create_plotly_3d=15ms/1x, render_triplanar=11ms/1x, compute_surface_areas=10ms/1x, segment_volume=6ms/2x, limpar_figura_3d=3ms/1x, compute_volumes=1ms/1x
slider thresh_Tecido mole (threshold)                        1175 ms  execuções_script=1  iframe_srcdoc=0.00 MB  exc=[]
      funções: st.plotly_chart=298ms/1x, build_all_meshes=221ms/1x, mesh_to_obj_bytes=166ms/3x, mesh_to_stl_bytes=113ms/3x, create_plotly_3d=38ms/1x, make_overlay_fig=16ms/3x, render_triplanar=11ms/1x, compute_surface_areas=10ms/1x, segment_volume=6ms/2x, limpar_figura_3d=4ms/1x, compute_volumes=1ms/1x
slider opacidade 3D op3d_*                                    833 ms  execuções_script=1  iframe_srcdoc=0.00 MB  exc=[]
      funções: st.plotly_chart=296ms/1x, mesh_to_obj_bytes=167ms/3x, mesh_to_stl_bytes=113ms/3x, create_plotly_3d=44ms/1x, make_overlay_fig=16ms/3x, render_triplanar=11ms/1x, compute_surface_areas=10ms/1x, segment_volume=7ms/2x, limpar_figura_3d=3ms/1x, compute_volumes=1ms/1x
```

### 13_widgets.txt

```
widget  total  linhas1-1061(login/STL)  linhas1062-1466(volume)
slider 10 3 7
selectbox 3 1 2
radio 3 3 0
checkbox 4 2 2
toggle 1 1 0
button 9 6 3
download_button 3 0 3
text_input 2 2 0
number_input 6 0 6
color_picker 2 1 1
multiselect 1 1 0
file_uploader 1 1 0
segmented_control 1 1 0
== st.rerun
325:# Opções da aba Cortes: reatribuídas ANTES dos botões que chamam st.rerun() (troca de
438:    st.rerun()
459:    st.rerun()
557:                st.rerun()
593:            st.rerun()
623:    st.rerun()
778:            st.rerun()
1348:                st.rerun()
== st.fragment
0
== on_change/on_click
7
== bbox_combinado
58:def bbox_combinado(malhas: dict) -> np.ndarray:
59-    """(2,3) min/max em (x,y,z) de todas as malhas."""
60-    b = np.array([m.bounds for m in malhas.values()])
61-    return np.array([b[:, 0].min(axis=0), b[:, 1].max(axis=0)])
62-
63-
64-def _ordem_desenho(nome: str, area: float):
65-    r = next((r for k, r in _RANK_NOME if k in nome.lower()), 1)
66-    return (r, -area)  # esmalte -> dentina -> canal; desconhecidos: maior área primeiro
== download_button data= (calcula bytes a cada rerun)
1420:                data=mesh_to_stl_bytes(mesh_e),
1428:                data=mesh_to_obj_bytes(mesh_e),
```

### 15_linhas_mortas.txt

```
loader.py:_load_dicom 19-41 (23 lin)
loader.py:_load_tiff_stack 44-63 (20 lin)
loader.py:_load_nifti 66-87 (22 lin)
loader.py:_load_synthetic_phantom 90-136 (47 lin)
loader.py:_to_display01 142-160 (19 lin)
loader.py:_finalize 163-178 (16 lin)
loader.py:load_volume 185-225 (41 lin)
modules/loader.py 225
modules/segmentation.py 99
modules/anatomy.py 124
modules/metrics.py 86
modules/viewer2d.py 122
modules/report.py 174
modules/references.py 130
subtotal módulos exclusivos do modo volume: 960
app.py:219-248 (_load_synthetic_vol,_load_uploaded_vol,_arr_hash) 30
app.py:283-292 (_build_meshes_cached,_compute_anatomy_cached) 10
app.py:1062-1466 (bloco modo volume) 405
app.py:47-57 (imports do modo volume) 11
viewer3d.py:21-66 (build_mesh, build_all_meshes) 46
TOTAL modo volume (aprox.): 1462 de 3905 linhas .py = 37%
assets/anatomy_refs.json usado só por references.py
```

### 01_auth_git.txt

```
== branch
feature/upload-link-drive
6d11338 docs: registra decisão de manter o repositório público
== ls-files auth/
== log auth count
       0
== .gitignore
     1	# Credenciais e secrets — NUNCA no repositório
     2	auth/users.yaml
     3	auth/hf_secret.local.json
     4	.env
     5	*.env
     6	secrets.toml
     7	.streamlit/secrets.toml
     8	
     9	# Configuração local Claude Code (paths absolutos locais)
    10	.claude/
    11	
    12	# Python
    13	__pycache__/
    14	*.py[cod]
    15	*.pyo
    16	*.pyd
    17	.Python
    18	venv/
    19	env/
    20	.venv/
    21	*.egg-info/
    22	dist/
    23	build/
    24	
    25	# Sistema
    26	.DS_Store
    27	Thumbs.db
    28	
    29	# Exports temporários gerados pelo app
    30	exports/
    31	
    32	# Cache de malhas decimadas (gerado automaticamente pelo mesh_loader)
    33	*.dcubic_cache.ply
    34	*.dcubic_cache.json
    35	
    36	# Pytest / cobertura
    37	.pytest_cache/
    38	.coverage
    39	htmlcov/
== ls auth
total 24
drwxr-xr-x@  5 abeyuujirou  staff  160 Oct 21 10:03 .
drwxr-xr-x@ 18 abeyuujirou  staff  576 Oct 21 15:49 ..
-rw-r--r--@  1 abeyuujirou  staff  614 Aug 27 23:17 hf_secret.local.json
-rw-r--r--@  1 abeyuujirou  staff  927 Oct 21 10:04 users.yaml
-rw-r--r--@  1 abeyuujirou  staff  927 Sep 14 18:49 users.yaml.bak-20261021-100357
== tree
.gitignore
.python-version
.streamlit/config.toml
.streamlit/secrets.toml.template
CHANGELOG.md
app.py
assets/anatomy_refs.json
assets/landing.html
assets/login.html
assets/molar.mp4
assets/molar.webm
docs/DECISAO-2026-10-20-lentidao.md
docs/DECISOES-REFINO-CORTES-UPLOAD.md
docs/DECISOES.md
docs/DEPLOY-HUGGINGFACE.md
docs/DEPLOY-STREAMLIT.md
docs/MODO-STL.md
docs/REFINAMENTO_CANAL_MOLAR.md
docs/REFINAMENTO_STL.md
docs/REQUISITOS.md
docs/decisoes/2026-08-28-dentes-de-exemplo.md
modules/__init__.py
modules/anatomy.py
modules/loader.py
modules/mesh_fill.py
modules/mesh_loader.py
modules/metrics.py
modules/references.py
modules/report.py
modules/segmentation.py
modules/slices.py
modules/stl_compactar.py
modules/viewer2d.py
modules/viewer3d.py
packages.txt
requirements.txt
runtime.txt
tools/gen_site_shots.py
tools/reduzir_stl.py
```

### 10_git_deploy.txt

```
$ git branch -a
* feature/upload-link-drive
  main
  refino/cortes-upload-painel
+ teste/frenteA-solido
+ teste/frenteB-corte
  wip/bloco2-cortes
  remotes/origin/HEAD -> origin/main
  remotes/origin/feature/upload-link-drive
  remotes/origin/main
  remotes/origin/refino/cortes-upload-painel
  remotes/origin/teste/frenteB-corte
$ git log --oneline -1 origin/main
b782a3b merge: refino cortes, upload grande, título na barra lateral
$ git log --oneline -1 origin/teste/frenteB-corte
4f8d9dc Visualizador 3D: limpeza definitiva de eixos e hover antes de toda exibição
2026-10-21 09:21:56 -0300
2026-10-21 15:49:39 -0300
$ git rev-list --left-right --count origin/main...origin/teste/frenteB-corte
20	7
$ git rev-list --left-right --count origin/main...feature/upload-link-drive
0	2
$ git rev-list --left-right --count origin/main...main
0	0
$ git log --oneline origin/main..feature/upload-link-drive
6d11338 docs: registra decisão de manter o repositório público
ddd01ea feat(upload): importação por link do Google Drive
$ git diff --stat origin/main origin/teste/frenteB-corte | tail -5
 modules/mesh_loader.py                |  37 +-
 modules/slices.py                     | 190 ---------
 modules/stl_compactar.py              | 394 -----------------
 requirements.txt                      |   6 +-
 8 files changed, 299 insertions(+), 1291 deletions(-)
$ git diff --stat origin/main feature/upload-link-drive | tail -8
 app.py                                |  39 ++++++++--
 docs/DECISOES-REFINO-CORTES-UPLOAD.md |  59 +++++++++++++++
 modules/stl_compactar.py              | 136 ++++++++++++++++++++++++++++++++++
 3 files changed, 227 insertions(+), 7 deletions(-)
$ git status --short
$ ultimo fetch (FETCH_HEAD mtime)
Oct 21 15:54:55 2026
```

### 13_curl.txt

```
GET https://dcubic-app-23dgjhjdnngusjjbdryizq.streamlit.app/ -> 303 0.816188s redirect=https://share.streamlit.io/-/auth/app?redirect_uri=https%3A%2F%2Fdcubic-app-23dgjhjdnngusjjbdryizq.streamlit.app%2F
GET https://dcubic-app-23dgjhjdnngusjjbdryizq.streamlit.app/_stcore/health -> 303 0.822616s redirect=https://share.streamlit.io/-/auth/app?redirect_uri=https%3A%2F%2Fdcubic-app-23dgjhjdnngusjjbdryizq.streamlit.app%2F_stcore%2Fhealth
GET https://dcubic-app-23dgjhjdnngusjjbdryizq.streamlit.app/~/+/_stcore/health -> 200 0.411895s redirect=
GET https://dcubic-image-system.streamlit.app/ -> 303 0.802628s redirect=https://share.streamlit.io/-/auth/app?redirect_uri=https%3A%2F%2Fdcubic-image-system.streamlit.app%2F
GET https://dcubic-image-system.streamlit.app/_stcore/health -> 303 0.440738s redirect=https://share.streamlit.io/-/auth/app?redirect_uri=https%3A%2F%2Fdcubic-image-system.streamlit.app%2F_stcore%2Fhealth
GET https://dcubic-image-system.streamlit.app/~/+/_stcore/health -> 200 0.430858s redirect=
https://dcubic-app-23dgjhjdnngusjjbdryizq.streamlit.app/~/+/_stcore/health body: ok
https://dcubic-app-23dgjhjdnngusjjbdryizq.streamlit.app/~/+/ -> 200 0.492752s
https://dcubic-image-system.streamlit.app/~/+/_stcore/health body: ok
https://dcubic-image-system.streamlit.app/~/+/ -> 200 0.215955s
```

### 14_zip_teste.txt

```
zip comprimido: 51322 bytes
membro-> evil.stl | gravado em recebidos/5f142c8f34d438d06b4342d23f2f8a1ed4e52068.stl | bytes 17
membro-> abs.stl | gravado em recebidos/e89536d65322dea1b9c725d7ba1f96a27c094ac5.stl | bytes 17
membro-> zeros.stl | gravado em recebidos/49886561f8e26ed5e2ae549897a28aaab44881bd.stl | bytes 52428800
razao zeros.stl: 1022 :1 aceito sem checagem de razao
arquivos fora de pasta? []
```

### 15_streamlit_upload.txt

```
$ max_body_size / maxUploadSize no servidor streamlit 1.50
/Users/abeyuujirou/Library/Python/3.9/lib/python/site-packages/streamlit/web/server/server.py:179:        max_buffer_size=config.get_option("server.maxUploadSize") * 1024 * 1024,
$ upload handler valida sessao?
25:from streamlit.web.server.server_util import is_xsrf_enabled
37:        is_active_session: Callable[[str], bool],
45:        is_active_session:
46:            A function that returns true if a session_id belongs to an active
50:        self._is_active_session = is_active_session
55:        if is_xsrf_enabled():
88:    def put(self, **kwargs: Any) -> None:
94:        session_id = self.path_kwargs["session_id"]
105:            if not self._is_active_session(session_id):
106:                self.send_error(400, reason="Invalid session_id")
131:        self._file_mgr.add_file(session_id=session_id, file=uploaded_files[0])
136:        session_id = self.path_kwargs["session_id"]
139:        self._file_mgr.remove_file(session_id=session_id, file_id=file_id)
$ uploaded_file_mgr guarda em memoria?
33:class MemoryUploadedFileManager(UploadedFileManager):
39:        self.file_storage: dict[str, dict[str, UploadedFileRec]] = defaultdict(dict)
60:        session_storage = self.file_storage[session_id]
72:        self.file_storage.pop(session_id, None)
93:        self.file_storage[session_id][file.file_id] = file
```

### 17_tokens.txt

```
$ tokens com formato conhecido no historico (contagem por tipo)
hf_[A-Za-z0-9]{30,}: 0
ghp_[A-Za-z0-9]{30,}: 0
github_pat_[A-Za-z0-9_]{30,}: 0
AKIA[0-9A-Z]{16}: 0
sk-[A-Za-z0-9]{20,}: 0
\$2[aby]\$[0-9]{2}\$: 0
BEGIN (RSA|OPENSSH|PRIVATE): 0
$ commits totais
108
$ e-mails de usuarios no repo HEAD (contagem de linhas)
HEAD:.streamlit/secrets.toml.template:4
HEAD:docs/DEPLOY-HUGGINGFACE.md:1
HEAD:docs/DEPLOY-STREAMLIT.md:4
```
