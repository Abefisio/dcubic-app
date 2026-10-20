# Decisão — 2026-10-20 — Lentidão do app em produção

## Problema
O app (Streamlit Cloud) estava lento no modo STL, sobretudo a cada interação
com controles da barra lateral (cada interação provoca um *rerun* do script).

## Causa
1. `preencher_interior()` (`modules/mesh_fill.py`) — voxelização da casca em
   grade 128³ — era chamada **sem cache** a cada rerun, pois o checkbox
   "Revelar interior" vem marcado por padrão.
2. `kaleido` e `bcrypt` constavam em `requirements.txt` sem serem importados
   pelo app:
   - `kaleido` só é usado por `tools/gen_site_shots.py` (ferramenta local, fora do app);
   - `bcrypt` não é importado diretamente; continua instalado como dependência
     transitiva do `streamlit-authenticator`.

## Correção aplicada
- `app.py`: nova função `_interior_cached(_mesh, chave, resolucao=128)` com
  `@st.cache_resource`. O parâmetro `_mesh` (PolyData, que não é hasheável) é
  ignorado no hash; a chave é `(nome, n_points, n_cells, tuple(bounds))`.
  O interior passa a ser calculado uma única vez por malha.
- `requirements.txt`: removidas as linhas `bcrypt>=4.0.0` e `kaleido>=0.2.1`.

## O que NÃO foi aplicado e por quê
- `_baixar_drive` (cache dos downloads via gdown): na proposta, a função validava
  o arquivo baixado com `_stl_valido`, inclusive os `.zip`, o que poderia quebrar
  o carregamento dos dentes distribuídos em zip. Os downloads já são evitados por
  verificação de arquivo existente em `/tmp/dcubic_samples`. Os trechos de gdown
  permaneceram idênticos ao original.

## Backup
- Tag git: `backup-antes-otimizacao-20261020-1850`
- Arquivo: `~/Desktop/BACKUPS-DCUBIC/dcubic-app-repo-20261020-1850.tar.gz`

## Como reverter
```bash
git revert <hash-do-commit-perf> && git push origin main
```
(o push na `main` republica automaticamente no Streamlit Cloud)
