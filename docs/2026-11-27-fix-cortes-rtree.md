# Correção da função Cortes (rtree) e usuário convidado — 27/11/2026

## Cortes: `ModuleNotFoundError: No module named 'rtree'`

- **Sintoma (produção):** ao escolher "Cortes" no seletor "3D | Cortes", o app mostra
  `ModuleNotFoundError: No module named 'rtree'` (`modules/slices.py`, linha 85, `plano.polygons_full`).
- **Causa raiz:** o contêiner instala `trimesh>=4.0.0` sem versão fixa e recebeu o trimesh 5.2.2; o
  `Path2D.polygons_full` usa uma árvore espacial (`rtree`), que não está no `requirements.txt`.
- **Correção:** `rtree>=1.0.0` no `requirements.txt` (a roda binária para Linux x86_64 / Python 3.12
  já traz a libspatialindex; não é preciso pacote de sistema). Teste de regressão: `tools/teste_corte.py`.
- **Provas (venv Python 3.12 com as mesmas versões do contêiner: trimesh 5.2.2, shapely 2.2.0,
  networkx 3.7, scipy 1.18.1):** sem rtree, o teste repete o erro de produção; com rtree 1.4.1,
  `OK: PNG de 2420 bytes; trimesh 5.2.2`. `uv pip compile` para `x86_64-manylinux_2_28` / 3.12 resolve `rtree==1.4.1`.
- **Deploy:** exige reconstruir a imagem na VPS (`git -C app pull --ff-only && docker compose up -d --build`,
  ver `docs/DEPLOY-VPS.md`). Aguarda aprovação do Dr. Abe.

## Usuário convidado

- Login `GUEST` (chave `guest` no `auth/users.yaml`; o streamlit-authenticator 0.4.2 converte o usuário
  digitado para minúsculas), papel "Convidado", `protected: false`. A senha fica só no `users.yaml`
  (bcrypt, fora do git); os demais usuários, inclusive o do dono, ficaram idênticos.
- Local: `auth/users.yaml` atualizado (backup `auth/users.yaml.bak-20261127-guest`).
- VPS: falta copiar para `/docker/dcubic/segredos/users.yaml` (aguarda autorização). O app relê o
  arquivo a cada execução do script, então não é preciso reiniciar o contêiner.
