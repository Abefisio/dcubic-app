# Barra lateral em degradê azul-marinho — 27/11/2026

- **Pedido (Dr. Abe):** barra lateral "em um tom azul degradê", conforme amostra (azul-marinho profundo, ~#16237a no centro, ~#0e1650 nas bordas).
- **Antes:** a barra sempre foi o cinza padrão do tema escuro do Streamlit (#262730); nunca houve cor anterior.
- **Alteração:** uma regra CSS no bloco de estilo global de `app.py` (linhas 96-98):
  `[data-testid='stSidebar']` recebe `linear-gradient(180deg, #1a2a80 0%, #0b1240 100%)`.
  O `config.toml` só aceita cor sólida, por isso o degradê é feito por CSS; `secondaryBackgroundColor` **não** foi alterado
  (também mudaria campos e expanders do corpo da página).
- **Legibilidade:** texto #e6edf6 (inalterado). Contraste: texto pleno 10,6:1 (topo) e 15,2:1 (base); legendas (opacidade 0,6) 4,8:1 e 6,0:1.
- **Tela de login:** não tem barra lateral; sem efeito.
- **Teste local:** app executado com Streamlit 1.50.0 e conferido em navegador (capturas no relatório do Dr. Abe).
- **Deploy:** reconstruir a imagem na VPS (ver `docs/DEPLOY-VPS.md` e `docs/2026-11-27-fix-aviso-slider-cortes.md`). Aguarda aprovação explícita.
- **Reverter:** remover a regra do `stSidebar` em `app.py` (ou `git revert` do commit).
