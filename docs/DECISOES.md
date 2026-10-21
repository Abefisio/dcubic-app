# Decisões

## 2026-10-21 — Visualizador 3D sem eixos

Eixos 3D ocultos (visible=False, ranges mantidos) e hoverinfo='skip' em todos os Mesh3d, para visualização didática limpa.

## 2026-10-21 — Limpeza definitiva de eixos e hover

Criada limpar_figura_3d() em modules/viewer3d.py, aplicada antes de toda exibição 3D (st.plotly_chart e to_html do STL): eixos ocultos, spikes desligados, hover desativado.

## 2026-10-21 — Otimização FASE 2 (branch otimizacao/2026-10)

Itens 1, 2, 3, 4, 5, 7, 9 e 10 (este sob a forma de carregamento sob demanda) da `docs/ANALISE-OTIMIZACAO-2026-10.md`. Itens 6 e 8 ficaram para depois.

### Item 1 — Limite de envio do servidor e comando local

- `.streamlit/config.toml` versionado: `maxUploadSize = 200` (o Streamlit Cloud lê este arquivo; o secret `DCUBIC_MAX_UPLOAD_MB = 200` continua valendo).
- O limite exibido no app é o menor entre `DCUBIC_MAX_UPLOAD_MB`/padrão e o teto do servidor (`server.maxUploadSize`).
- **Comando local (Mac), para enviar arquivos de até 2 GB.** A opção de linha de comando tem precedência sobre o `config.toml` do projeto (que, por sua vez, tem precedência sobre `~/.streamlit/config.toml`). Iniciar sem `PYTHONDONTWRITEBYTECODE`, para o Python reaproveitar os `.pyc` (item 7):

```
cd ~/Developer/dcubic-app-repo
env -u PYTHONDONTWRITEBYTECODE python3 -m streamlit run app.py --server.headless true --server.port 8501 --server.address 127.0.0.1 --server.maxUploadSize 2048
```

### Item 2 — Zip-bomba no envio direto de .zip

- A checagem que só existia no caminho do Drive passou para `receber()` (`_checar_zip`), usada pelo envio direto e pelo Drive: soma descompactada ≤ 2 GB, `1,1 × soma ≤ espaço livre` e, por membro acima de 1 MB, razão de compressão ≤ 100:1 (`RAZAO_MAX_ZIP`). A razão foi acrescentada porque o zip de teste da Fase 1 (51 KB → 52 MB) passaria pelas checagens de soma e de disco; um zip real com 2 STL teve 4,6:1.
- Em qualquer erro, `receber()` apaga o que aquele envio já gravou em `recebidos/` (e `_gravar` apaga o `.part` incompleto). A correção ficou na função comum, e não em `app.py`, para valer também no Drive.

### Item 3 — Login

- **Limite de tentativas** (contador em `st.session_state`): 5 erros seguidos → pausa de 60 s naquela sessão, sem formulário; a tela diz quantos segundos faltam e oferece "Tentar novamente", recarregar a página e o contato com o administrador. Nunca é permanente e não grava nada em `users.yaml`: recarregar a página abre uma sessão nova, de modo que o dono nunca fica trancado para fora (regras de acesso). Antes da pausa, a mensagem de erro informa quantas tentativas restam; a tela de login mostra sempre a ajuda "Esqueceu a senha ou não tem acesso? Fale com o administrador do DCubic."
- Limitação conhecida: quem abre uma sessão nova a cada tentativa não é contido pelo contador (só pela espera de ~0,7 s por tentativa da biblioteca); um limite por IP exigiria um proxy na frente do app.
- `.gitignore`: `auth/*` (inclui `users.yaml` e os backups `users.yaml.bak-*`, que antes só eram ignorados por `.git/info/exclude`, regra local a este clone), com exceção `!auth/*.template` para modelos.
- E-mails de login reais trocados por `admin@exemplo.com` e `pesquisador@exemplo.com` em `.streamlit/secrets.toml.template`, `docs/DEPLOY-STREAMLIT.md` e `docs/DEPLOY-HUGGINGFACE.md`. Os e-mails antigos continuam no histórico do Git (repositório público); reescrever o histórico não foi feito.

### Item 4 — Download do Drive e limpeza do cache

- O download do Drive grava num arquivo temporário único (`tempfile.mkstemp`, `drive_<id>_<aleatório>.part`) em vez do nome fixo `drive_<id>.part`: dois usuários com o mesmo link não sobrescrevem mais um ao outro.
- `limpar_cache_antigo()` roda 1 vez por processo do servidor (`st.cache_resource` em `app.py`): apaga arquivos com mais de 2 dias **somente dentro** da pasta de cache do app (`PASTA_CACHE` = `<tmp>/dcubic_upload_cache`) e as subpastas que ficarem vazias. Recusa qualquer pasta que não se chame `dcubic_upload_cache` (caminho vazio, raiz, home, `/tmp`) e não segue links.
- Pendente (Dr. Abe, no painel do Streamlit Cloud): criar o secret `DCUBIC_MAX_DRIVE_MB = 1024`.

### Item 5 — Cache de dentes mantido ao trocar de seleção

- Removido `_load_stl_from_paths.clear()` (e o estado `_stl_last`, que só servia a ele). O `max_entries=2` do `st.cache_resource` continua limitando a 2 dentes na RAM; voltar a um dos 2 dentes mais recentes não relê o disco. A limpeza explícita antes de compactar um envio novo (etapa 2) foi mantida.

### Itens 7 e 10 — Imports tardios e modo volume sob demanda

- O modo volume **foi mantido** (será usado para volumes reconstruídos de micro-CT). Os módulos dele (`loader` com pydicom/tifffile/nibabel, `viewer2d`, `segmentation`, `metrics`, `report` com reportlab, `anatomy`, `references` e o `build_all_meshes`) são importados só depois do botão "Abrir modo volume", logo após o `st.stop()` que fecha o modo STL.
- `modules/slices.py`: `trimesh` importado dentro de `para_trimesh`/`carregar_trimesh` (1º corte), não no login. `modules/viewer3d.py`: `skimage.measure.marching_cubes` importado dentro de `build_mesh` (só o modo volume usa).
- `requirements.txt` **sem alteração**: todos os pacotes têm import em algum `.py` do repositório (inclusive pydicom/tifffile/nibabel no `loader.py`), exceto `shapely` e `networkx`, que são usados pelo trimesh (cortes) e pelo scikit-image — mantidos.
- Servidor local iniciado sem `PYTHONDONTWRITEBYTECODE` (comando no item 1), para reaproveitar os `.pyc`.

### Item 9 — Menos execuções por clique

- Botões de olho (estruturas visíveis) e "Limpar STL" usam `on_click` em vez de `st.rerun()`: 1 execução do script por clique (antes, 2). Os demais `st.rerun()` (envio em duas etapas, dentes de exemplo, pausa do login, referências do modo volume) foram mantidos: fazem E/S de arquivos ou dependem da ordem de desenho.
- `slices.bbox_combinado` em `st.cache_data` (`_bbox_cached`, chave = arquivos+mtime e nomes): deixa de custar 45–60 ms a cada rerun.
