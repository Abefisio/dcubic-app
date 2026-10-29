# Deploy na VPS (Docker + Traefik)

Instalado em 29/10/2026. Convive com o Unlock Guide e o Traefik já existentes na mesma VPS.

## Endereço

- App: https://app.dcubic.reloadcursos.com
- VPS: `root@152.239.113.183` (Ubuntu 24.04, 3,8 GiB RAM, **1 vCPU**, swap 4 GiB em `/swapfile`, `vm.swappiness=10`)
- DNS: registro A `app.dcubic` → `152.239.113.183` no Cloudflare (zona reloadcursos.com), **DNS only** (nuvem cinza),
  necessário para o Let's Encrypt (desafio HTTP) emitir o certificado.
- Acesso SSH: `ssh -i ~/.ssh/unlock_vps_ed25519 -o IdentitiesOnly=yes root@152.239.113.183`

## Pastas na VPS

| Caminho | Conteúdo |
|---|---|
| `/docker/dcubic/app` | clone da branch `main` de https://github.com/Abefisio/dcubic-app.git |
| `/docker/dcubic/Dockerfile` | imagem `python:3.12-slim` + libgl1/libglx-mesa0/libglu1-mesa/xvfb, usuário não-root UID 1000 |
| `/docker/dcubic/docker-compose.yml` | projeto compose `dcubic` (serviço `dcubic`, contêiner `dcubic-dcubic-1`) |
| `/docker/dcubic/.dockerignore` | impede que `segredos/`, `app/.git` e `app/auth` entrem na imagem |
| `/docker/dcubic/segredos/users.yaml` | credenciais reais (600, dono UID 1000), montado **somente leitura** em `/app/auth/users.yaml` |
| `/docker/dcubic-dados` | dentes de exemplo baixados via gdown, montado em `/tmp/dcubic_samples` (persiste entre reinícios) |

Observações:
- O app lê `auth/users.yaml` relativo à pasta do `app.py` e nunca grava nele; por isso a montagem é `:ro`.
- Não existe `.streamlit/secrets.toml` real (nem no Mac nem nos worktrees). Se for criado, copie para
  `/docker/dcubic/segredos/secrets.toml` (chmod 600, chown 1000:1000) e descomente a linha correspondente no compose.
- Não há `ports:`: o Traefik (modo host) alcança o contêiner pela rede `dcubic_default`; a porta 8501 não fica exposta.
- Labels do Traefik: router/service `dcubic`, entrypoint `websecure`, certresolver `letsencrypt`, porta 8501.

## Atualizar o app

```bash
ssh -i ~/.ssh/unlock_vps_ed25519 -o IdentitiesOnly=yes root@152.239.113.183
cd /docker/dcubic
git -C app pull --ff-only
docker compose up -d --build
docker compose ps          # aguardar "(healthy)"
```

Atualizar credenciais (a partir do Mac):

```bash
scp -i ~/.ssh/unlock_vps_ed25519 -o IdentitiesOnly=yes ~/Developer/dcubic-app-repo/auth/users.yaml \
  root@152.239.113.183:/docker/dcubic/segredos/users.yaml
ssh -i ~/.ssh/unlock_vps_ed25519 -o IdentitiesOnly=yes root@152.239.113.183 \
  'chown 1000:1000 /docker/dcubic/segredos/users.yaml && chmod 600 /docker/dcubic/segredos/users.yaml && cd /docker/dcubic && docker compose restart'
```

## Reverter

- Voltar a uma versão anterior do código:
  `cd /docker/dcubic && git -C app log --oneline -5 && git -C app checkout <hash> && docker compose up -d --build`
  (para retornar ao normal depois: `git -C app checkout main && git -C app pull --ff-only`).
- Tirar o app do ar sem afetar o restante: `cd /docker/dcubic && docker compose down` (Unlock Guide e Traefik seguem).
- Reversão total da VPS: snapshot criado no hPanel da Hostinger antes desta instalação.

## Limites de memória e CPU

- `mem_limit: 2g` no contêiner do DCubic; o Unlock Guide usa `512m`; sobra margem para o sistema e o Traefik.
- `cpus: 1.0`: a VPS tem só 1 vCPU e o Docker recusa valores acima disso (o pedido original era 1.5).
  Na prática o DCubic pode usar a CPU inteira quando o Unlock Guide estiver ocioso.
- Swap de 4 GiB (`/swapfile`, registrado no `/etc/fstab`) protege contra picos ao processar STL grandes.
- Uploads até 1024 MB (`--server.maxUploadSize 1024` no CMD, sobrepõe o 200 do `.streamlit/config.toml`).

## Certificado HTTPS

O Traefik pede o certificado ao detectar o router. Se o DNS não resolvia nesse momento, o pedido falha
(`NXDOMAIN` no log do Traefik). Depois que `dig +short app.dcubic.reloadcursos.com @1.1.1.1` retornar o IP,
recrie o contêiner para o Traefik tentar de novo (sem reiniciar o Traefik):

```bash
cd /docker/dcubic && docker compose up -d --force-recreate
docker logs --since 5m traefik-traefik-1 2>&1 | grep -i dcubic
```

Saúde: `curl -s https://app.dcubic.reloadcursos.com/_stcore/health` deve responder `ok`.
