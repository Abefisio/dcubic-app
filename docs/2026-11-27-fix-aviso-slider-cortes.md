# Aviso amarelo no slider da aba Cortes — 27/11/2026

- **Sintoma (produção):** em "3D | Cortes", ao mover o slider de posição, o Streamlit mostrou uma vez
  "The widget with key "corte_..." was created with a default value but also had its value set via the
  Session State API". O aviso é emitido só uma vez por processo do servidor (flag global do Streamlit 1.50),
  por isso pareceu ligado ao teclado e "sumiu" ao arrastar com o mouse.
- **Causa raiz:** o `st.slider` do corte recebia `value=(lo+hi)/2` e a mesma chave `corte_<eixo>_<bbox>` é
  reatribuída na Session State a cada execução (necessário para preservar a posição com a aba 3D ativa).
  `value=` + escrita na Session State na mesma execução = aviso.
- **Correção:** o centro passa a ser gravado na Session State só quando a chave ainda não existe, e o slider
  não recebe mais `value=` (mesmo padrão já usado em `ap_opac`/`ap_tom`). Comportamento idêntico: posição
  inicial no centro, preservada ao alternar 3D/Cortes, e de volta ao centro ao trocar de dente (a chave inclui
  a caixa delimitadora do dente). "Resetar vista" só reposiciona a câmera, como antes.
- **Auditoria dos demais widgets com chave escrita na Session State:** `cortes_plano`, `cortes_plano_eixo`,
  `ap_opac`, `ap_tom`, `ap_cor`, `ap_lock`, `ap_vista` são criados sem padrão explícito (ou com o padrão neutro
  que o Streamlit trata como ausente); `_stl_selected` só é removido. Nenhum outro caso.
- **Prova (Streamlit AppTest rodando o `app.py` real, dente INCISIVO reduzido):** antes, 1 aviso na primeira
  interação; depois, 0 avisos em: +1 passo (teclado) e salto ao mínimo (mouse) nos 3 eixos, alternância
  3D/Cortes com plano ligado e troca de dente.
- **Deploy:** reconstruir a imagem na VPS (ver `docs/DEPLOY-VPS.md`). Aguarda aprovação do Dr. Abe.

## Publicação em produção (27/11/2026, aprovada pelo Dr. Abe)

- `fix/aviso-slider-cortes` juntado ao `main` (ba8c1a0); VPS: `docker compose up -d --build`, exit 0, contêiner healthy,
  0 erros nos logs; `users.yaml` intacto (sha256 e3e67b1a...0f33c, 4 usuários).
- Teste: roteiro AppTest dentro do contêiner de produção (MOLAR-SUP e 34-PRE, 3 eixos, alternância 3D/Cortes,
  troca de dente) → 0 avisos de Session State, sem exceções. Conferência visual no navegador pendente (sessão exigiu login).
- Reverter: `cd /docker/dcubic && docker tag dcubic:backup-antes-aviso-slider-20261127 dcubic:latest && docker compose up -d`
  (tag git `backup-antes-aviso-slider-20261127`).
