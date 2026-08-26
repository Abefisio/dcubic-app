# DCubic Image System Platform — Requisitos & Especificação viva

> Documento de referência do que o app **deve fazer**, com o status atual de cada
> requisito. Atualizado a cada refinamento (Requisito 8).
> USP/FOUSP · pesquisa acadêmica · uso não comercial.

## Objetivo
Plataforma de análise quantitativa de volumes 3D de **micro-tomografia (micro-CT) dental**:
captar o exame, reconstruir/segmentar tecidos, visualizar em 3D interativo e medir volumes,
com foco em anatomia do dente e do sistema de canais radiculares.

---

## Requisitos

### 1. Captar as imagens de micro-tomografia
**Status: FEITO (base).**
Loader universal aceita DICOM (pasta `.dcm`), pilha TIFF (`.tif/.tiff`) e NIfTI (`.nii/.nii.gz`),
via upload na barra lateral. Normalização de intensidade adicionada — aceita qualquer escala
(uint16/HU) mapeando para [0,1] sem afetar as métricas geométricas.
*Refinar:* validação com exame real; suporte a metadados de espaçamento de voxel de mais scanners.

### 2. Áreas que não são sulcos → sólidas; contornos → transparentes
**Status: FEITO (robusto para micro-CT real).**
Modo "Contorno (casca translúcida)" no Render 3D: a camada **mais externa** é detectada
dinamicamente pelo maior bounding box entre as camadas com voxels > 0 (funciona com qualquer
ordenação de tecidos, inclusive quando "Tecido mole" está ausente no exame real). Camada
externa: opacidade 0.07 (casca quase invisível); demais: 1.0 (sólidas). O modo informa qual
camada foi detectada como externa. Princípio 1 mantido: opacidade é configuração visual.

### 3. Partes externas transparentes / partes internas visíveis
**Status: FEITO.**
Render 3D tem **Modo de transparência** com predefinições — "Externo transparente / interno opaco",
"Raio-X (tudo translúcido)", "Sólido" e "Personalizado" — além do plano de corte Z e dos sliders
de opacidade por camada. Permite enxergar as áreas internas captadas pela microtomografia.

### 4. Rotacionar o modelo em 3 dimensões
**Status: FEITO.**
Render 3D interativo (Plotly Mesh3d / WebGL): rotação, zoom e pan direto no navegador.

### 5. Ligar/desligar camada interna e externa + cores por paleta selecionável
**Status: FEITO.**
Seletor de cor por camada na barra lateral ("Cores das camadas"), aplicado em Segmentação,
Render 3D e Métricas. Liga/desliga por opacidade (0 = oculto) no Render 3D.

### 6. Calcular volume: área externa, interna e dentro da raiz do dente
**Status: FEITO (base) — aguarda calibração com exame real.**
Aba "Anatomia": externo (envelope preenchido), cavidade interna (câmara + canais),
canal radicular (cavidade dentro da raiz), coroa e raiz — por morfologia 3D (fill holes +
plano cervical automático/ajustável). Métricas geométricas; validado em dente sintético.
Relações conferem: Externo = Sólido + Cavidade; Coroa + Raiz = Externo.

### 7. Baixar da internet dados de anatomia do dente e das raízes p/ melhorar a análise
**Status: FEITO (base).**
Módulo `modules/references.py` com base CURADA por dente (notação FDI): nº de raízes e canais
típicos (literatura endodôntica/Vertucci) + notas. Expander "Referência anatômica" na aba Anatomia
mostra o esperado por dente e compara com o **canal radicular medido**. Botão "Atualizar referências
(online)" baixa um JSON do próprio repositório (`assets/anatomy_refs.json` via raw GitHub), com
fallback à base local. Base editável para curadoria contínua.

### 8. Sempre aprender a cada comando de refinamento
**Status: PROCESSO (ativo).**
Este documento é a especificação viva: a cada refinamento, atualizamos o status acima e
registramos a mudança no changelog abaixo.

---

## Changelog / aprendizado
- **2026-08-25** — Deploy do app no Streamlit Cloud (Bloco 7.3); correções de estabilidade
  (Secrets imutável, CookieManager). Projeto movido do iCloud para `~/Developer` (fim dos travamentos).
- **2026-08-25** — Identidade visual: landing inicial + tela de login com molar 3D + tema Vermont/Inter.
- **2026-08-25** — Loader: normalização de intensidade para aceitar micro-CT real em qualquer escala.
- **2026-08-25** — Registrados os 8 requisitos do app (este documento).
- **2026-08-25** — Requisito 6: aba "Anatomia" (externo/cavidade/canal/coroa/raiz) por morfologia 3D.
- **2026-08-25** — Requisito 5: seletor de cores por camada (paleta) na barra lateral.
- **2026-08-25** — Requisito 3: Modo de transparência no Render 3D (externo transparente / raio-X / sólido).
- **2026-08-25** — Requisito 7: módulo de referências de anatomia dental (FDI, raízes/canais, Vertucci) + atualização online.
- **2026-08-25** — Relatório PDF enriquecido: seções "Volumes anatômicos" e "Referência anatômica do dente".
- **2026-08-25** — Requisito 2: modo "Contorno (casca translúcida)" no Render 3D — superfície externa quase invisível (op. 0.07), estruturas internas sólidas (op. 1.0).
- **2026-08-25** — Robustez pré-calibração:
  - Req. 2: Contorno genérico — camada externa detectada por maior bounding box (funciona sem "Tecido mole").
  - Cache de desempenho: `_build_meshes_cached` e `_compute_anatomy_cached` com hash por (shape, dtype, sum) evitam recomputar marching cubes e morfologia 3D a cada slider de opacidade.
  - Guarda de memória: aviso quando volume > 12 M voxels; constante `_MAX_VOXELS` ajustável.

> **Todos os 8 requisitos têm ao menos a base implementada. App robusto para micro-CT real (pré-calibração).**

## Próximos passos sugeridos (ordem)
1. **Calibração com exame real** — validar Req. 6 (canal/plano cervical) e a segmentação; curar as referências (Req. 7).
2. Enriquecer o relatório PDF com imagem do render 3D (captura do Plotly).
