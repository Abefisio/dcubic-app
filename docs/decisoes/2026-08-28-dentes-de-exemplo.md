# Dentes de exemplo — download sob demanda via Google Drive

## Problema
Upload manual dos STL de micro-CT era lento para o usuário (arquivos originais até 744 MB).

## Solução implementada
- 3 dentes (Esmalte, Dentina, Molar) reduzidos para ~9,5 MB cada (script tools/reduzir_stl.py, alvo 200000 faces), originais intactos em ~/Desktop/DCUBIC-SITE/MICROTOMO/.
- Versões leves hospedadas no Google Drive, pasta DCUBIC-STL, públicas como "Leitor":
  - Esmalte: 1OmWWs6kaUc6bT3gD2jjHMFX41r1g_45P
  - Dentina: 1_bbDyFS2QG9qL8xecflwTjuwlKVrjm7J
  - Molar: 1B9z0GMQzHxYegnGY69KLVuPs-U8m38gH
- Menu "Dentes de exemplo" na barra lateral (app.py), baixa via gdown sob demanda, com cache em /tmp/dcubic_samples.
- Validação _stl_valido(): arquivo existe, tamanho > 100 KB, primeiros bytes não indicam página HTML de erro do Drive.
- Em caso de falha: exceção real capturada e exibida em st.warning (não mais silenciada); arquivo parcial/corrompido removido do cache automaticamente.

## Commit
c0aa8d3 — "feat: menu 'Dentes de exemplo' com download gdown do Drive (cache + validação STL)" (app.py + requirements.txt, gdown>=5.0.0)

## Teste
Testado em produção (https://dcubic-app-23dgjhjdnngusjjbdryizq.streamlit.app) em 28/08/2026: os 3 dentes carregaram e renderizaram corretamente em 3D.

## Status
Concluído. Sem pendências.
