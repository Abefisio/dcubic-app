# Identidade do app: DCubic Image System → Endo Atlas 3D — 26/11/2026

## Decisão

A identidade visível do app foi alterada de **DCubic Image System** para **Endo Atlas 3D**.

## Motivo

Alinhar o app ao padrão de identidade do site de apresentação, cujo hero passou a ser
"Estudo Morfológico Estrutural – Endo Atlas 3D". O app publicado (https://app.dcubic.reloadcursos.com)
passa a exibir o mesmo nome e a mesma composição de título.

## Arquivos alterados (commit `386c361`)

14 arquivos, 26 inserções e 24 remoções:

| Arquivo | Mudança |
|---|---|
| `app.py` | `page_title` "Endo Atlas 3D" (linha 82); comentário (linha 88); ajuda do login "…administrador do Endo Atlas 3D." (linha 212); altura do componente de cabeçalho 180 → 200 px (linha 219); barra lateral "### Endo Atlas 3D" (linha 261); arquivos exportados `endo_atlas_3d_<nome>.stl`/`.obj` e `endo_atlas_3d_relatorio.pdf` (linhas 1567, 1575 e 1605); primeira linha da docstring |
| `assets/login.html` | Cabeçalho do login em duas linhas: `<small>` "Estudo Morfológico Estrutural –" (branco, 17 px; 14 px no celular) e `<span>` "Endo Atlas 3D" (`#00c2c9`, 44 px; 32 px no celular) |
| `modules/report.py` | Título do PDF (linha 71) e primeira linha da docstring |
| `modules/anatomy.py`, `envio_http.py`, `loader.py`, `mesh_loader.py`, `metrics.py`, `references.py`, `segmentation.py`, `slices.py`, `stl_compactar.py`, `viewer2d.py`, `viewer3d.py` | Somente a primeira linha da docstring |

## O que NÃO foi alterado, e por quê

| Item | Motivo |
|---|---|
| URLs e domínios (`app.dcubic.reloadcursos.com` etc.) | Mudança de infraestrutura (DNS, Traefik, certificados), fora do escopo |
| Rota `/dcubic-envio`, cabeçalhos `X-DCubic-*`, `User-Agent` `DCubic/1.0` | Contrato entre front-end e servidor; trocar quebraria o envio |
| Variáveis de ambiente `DCUBIC_*` | Configuração da VPS e do `docker-compose`; trocar exigiria mudar o ambiente |
| Cookie `dcubic_auth` | Trocar o nome encerraria todas as sessões abertas |
| Chaves de `localStorage` `dcubic_stl_*` e caches `.dcubic_cache.*` | Dados já gravados nos navegadores e no disco deixariam de ser encontrados |
| Caminhos de pastas e cabeçalhos binários de STL | Compatibilidade com arquivos existentes |
| `docs/` e `CHANGELOG` | Registro histórico; não se reescreve o passado |
| `tools/`, `auth/users.yaml`, autenticação, dados e processamento | Fora do escopo (identidade visual apenas) |

## Testes

- `py_compile` dos arquivos alterados: exit 0.
- `grep -rniE "d-?cubic"`: 281 ocorrências antes, 260 depois (as restantes estão em `docs/`, `tools/`,
  `CHANGELOG` ou na lista acima); 18 linhas com "Endo Atlas 3D".
- Teste local (http://localhost:8502, cópia do código sem `auth/`, usuário de teste descartável via
  `AUTH_CONFIG_JSON`): `document.title` = "Endo Atlas 3D", login aceito, cabeçalho sem corte em
  1280x800 e 375x812. Capturas em `~/Desktop/BACKUPS-CLAUDE/teste-local-endo-atlas/`. Servidor local encerrado.

## Deploy (aprovação separada do Dr. Abe)

- Push `bf67846..386c361` na `main` (GitHub).
- VPS (`/docker/dcubic`): fast-forward `098ea00..386c361` (15 arquivos: os 14 acima e
  `docs/2026-10-31-fix-gdown-flush.md`, já na `main` desde `bf67846`); build de cerca de 8 min.
- Contêiner `dcubic-dcubic-1` `healthy`, `/_stcore/health` = `ok`, HTTP 200, `document.title` = "Endo Atlas 3D"
  e cabeçalho conferido em produção (tela de login).

## Pontos de reversão

- Imagem na VPS: `dcubic:backup-antes-endo-atlas-20261126` (ID `2721e193632a`).
- Tag git `backup-antes-endo-atlas-20261126` em `098ea00a5177e31af0a0cf66b8765402d8737a5b`
  (somente no clone da VPS).
- Arquivo `/root/backup-dcubic-app-antes-endo-atlas-20261126.tgz` (1.901.656 bytes) na VPS.
- Backup local do código: `~/Desktop/BACKUPS-CLAUDE/dcubic-app-20261126-0947` (sem `.git`, venv e `node_modules`).
- Reverter o contêiner e o código na VPS:
  ```bash
  cd /docker/dcubic && docker tag dcubic:backup-antes-endo-atlas-20261126 dcubic:latest \
    && git -C app checkout backup-antes-endo-atlas-20261126 && docker compose up -d
  ```
- Reverter na `main`: `git revert 386c361`, push e, na VPS, `git -C app pull --ff-only && docker compose up -d --build`.

## Pendências

- `auth/teste-local-login.txt` (ignorado pelo git) guarda em texto aberto a senha de um usuário de teste
  antigo; remoção recomendada, mediante autorização.
- Opcional: a altura do componente de cabeçalho poderia ir a 160 px (sobram cerca de 70 px).
