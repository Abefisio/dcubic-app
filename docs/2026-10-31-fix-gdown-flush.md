# Correção do "Importar do Drive" (gdown 6.5.1 e `flush`) — 31/10/2026

## Sintoma

No app publicado, o botão **Importar do Drive** falhava sempre com
"Falha ao baixar do Google Drive (AttributeError). Verifique a conexão e tente novamente."

## Causa

- `requirements.txt` pedia `gdown>=5.0.0`; a imagem `dcubic:latest` (Python 3.12.16) instalou o **gdown 6.5.1**.
- No gdown 6.5.1, `gdown/download.py:686` faz `flush=f.flush` no objeto de destino.
- `baixar_do_drive` (`modules/stl_compactar.py`) entrega ao gdown um `_GravadorLimitado`, que só tinha `write()`:
  `AttributeError: '_GravadorLimitado' object has no attribute 'flush'`.
- O `except` genérico transformava o erro na mensagem acima, sem traceback no log. Com gdown 5.2.2 a mesma chamada funcionava.

## Correção (commit `9e1e3b1`, branch `fix/gdown-flush`, merge na `main`)

- `_GravadorLimitado`: novos `flush()` (repassa a `self.f.flush()`) e `__getattr__` (repassa ao arquivo real
  qualquer outro atributo que o gdown pedir).
- Ramo genérico do `except` de `baixar_do_drive`: `traceback.print_exc()` antes do `raise`, para o erro real
  aparecer em `docker logs dcubic-dcubic-1`.
- `requirements.txt`: `gdown==6.5.1` (versão fixa, testada).

Observação: o `__getattr__` entra em recursão se o objeto for copiado ou serializado (`copy.copy`/pickle),
porque `self.f` ainda não existe na cópia (verificado: `RecursionError`). O gdown não faz isso, então não afeta
o uso atual; se um dia for necessário, basta usar `self.__dict__["f"]` dentro do `__getattr__`.

## Testes (saída bruta em `~/Desktop/RELATORIOS-CLAUDE/dcubic-fix-drive.txt`)

Link público usado: https://drive.google.com/file/d/1PZ7QYy2xVxSPrzCGysI_jqA58W5YJBV8/view?usp=sharing

| Onde | gdown | Resultado |
|---|---|---|
| Mac, venv isolado | 6.5.1 | 2 STL: 15.464.584 e 15.411.534 bytes |
| Contêiner `dcubic-dcubic-1` após o rebuild | 6.5.1 | os mesmos 2 STL, mesmos bytes e SHA-1 |

O app publicado respondeu HTTP 200 e `/_stcore/health` = `ok` depois do rebuild.

## Pontos de reversão

- Git: tag `backup-antes-gdown-flush` (commit `17534b1`, no GitHub).
- Imagem na VPS: `dcubic:backup-antes-gdown-flush` (ID `832f395bbd38`, a imagem anterior).
- Reverter o contêiner:
  ```bash
  ssh -i ~/.ssh/unlock_vps_ed25519 -o IdentitiesOnly=yes root@152.239.113.183
  cd /docker/dcubic
  docker tag dcubic:backup-antes-gdown-flush dcubic:latest && docker compose up -d
  ```
- Reverter o código (antes de um novo build): `git revert 9e1e3b1` na `main`, push e, na VPS,
  `git -C app pull --ff-only && docker compose up -d --build`.

## Teste manual aprovado

Teste manual do **Importar do Drive** no app publicado (https://app.dcubic.reloadcursos.com), após o commit
`9e1e3b1`: **aprovado pelo Dr. Abe em 31/10/2026**.

## Blindagem do `__getattr__` (commit `098ea00`)

O risco descrito na observação acima foi eliminado. Em `_GravadorLimitado.__getattr__` o arquivo real agora
é lido por `self.__dict__`, sem passar de novo pelo `__getattr__`:

```python
f = self.__dict__.get("f")
if f is None:
    raise AttributeError(nome)
return getattr(f, nome)
```

### Testes (saída bruta em `~/Desktop/RELATORIOS-CLAUDE/dcubic-finalizacao-drive.txt`)

| Onde | gdown | `copy.copy` | Drive (mesmo link) |
|---|---|---|---|
| Mac, `venv-app` | 6.5.1 | OK, sem `RecursionError`; objeto sem `f` dá `AttributeError` | 2 STL: 15.464.584 e 15.411.534 bytes (iguais no disco) |
| Contêiner `dcubic-dcubic-1` após o rebuild (imagem `2721e193632a`, `healthy`) | 6.5.1 | idem | os mesmos 2 STL, mesmos bytes e SHA-1 |

SHA-1: `e2384bde69a6699a8905cc08c2169ec7bb217c21` (`34pre__rec_tra(1)_reduzido.stl`) e
`5614ca2d9084821f453f4ff49ad626eecc4414b7` (`34pre__rec_tra_reduzido.stl`).
App publicado: HTTP 200; `/_stcore/health` = `ok` (HTTP 200).

### Pontos de reversão desta etapa

- Git: tag `backup-antes-blindagem` (commit `e0668bb`, no GitHub).
- Imagem na VPS: `dcubic:backup-antes-blindagem` (ID `c33396e411ed`, a imagem com o `flush`, antes da blindagem).
- Reverter o contêiner:
  ```bash
  ssh -i ~/.ssh/unlock_vps_ed25519 -o IdentitiesOnly=yes root@152.239.113.183
  cd /docker/dcubic
  docker tag dcubic:backup-antes-blindagem dcubic:latest && docker compose up -d
  ```
- Reverter o código (antes de um novo build): `git revert 098ea00` na `main`, push e, na VPS,
  `git -C app pull --ff-only && docker compose up -d --build`.
