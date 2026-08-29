# Refinamento do Modo STL — DCubic Image System Platform

_Registro de decisões e estado. Atualizado em 29/08/2026._

## Contexto

App técnico Streamlit publicado (Streamlit Cloud), repo `~/Developer/dcubic-app-repo`.
O modo STL renderiza malhas de micro-CT (dentes) exportadas do Bruker CTAnalyser.
Renderização via Plotly Mesh3d dentro de `components.html` (iframe), com controles
client-side para não resetar a câmera.

## Já refinado (concluído)

| Commit | O que foi feito |
|--------|----------------|
| `1dee6fe` | `key` no `plotly_chart` STL, reordena abas para abrir em Render 3D |
| `33e67d9` | Opacidade STL via slider Plotly client-side (restyle, sem rerun) |
| `fd4d544` | Modo STL migrado para `to_html + components.html`; slider opacidade e LOCK em JS; câmera não reseta |
| `7fcec42` | Controles de aparência (tom, cor, visibilidade) migrados para client-side via `Plotly.restyle` |
| `e5c8888` | Cena STL +70% (height 1156), iframe 1250, barras compactadas, modebar scale 1.6 vertical |
| `4a2781a` | Largura total da tela (`max-width 100%`), modebar ancorada à esquerda |
| `5d0ce71` | Painel lateral esquerdo retrátil (CAMADAS/COR/ESTRUTURAS) com botão toggle |
| `78e8242` | Botões "Resetar vista" e "Baixar imagem PNG" no painel; modebar nativa ocultada; reset destrava o LOCK |

### Resumo funcional do estado atual

- **Câmera estável**: opacidade e demais controles não resetam mais a câmera (render via
  `to_html + components.html`; controles via `Plotly.restyle` client-side, sem rerun do Streamlit).
- **Botão LOCK**: trava a rotação da câmera (azul quando ativo); "Resetar vista" destrava e
  volta à posição inicial (`eye: {x:1.5, y:1.5, z:1.2}`).
- **Painel lateral retrátil (esquerda)** com toggle `‹ ›`, contendo:
  - **CAMADAS** — slider de opacidade global (todos os traces simultaneamente)
  - **COR** — Cinza (tom ajustável 0–255) / Cor personalizada (color picker)
  - **ESTRUTURAS** — checkboxes de visibilidade por trace (`Plotly.restyle({visible})`)
  - **VISTA** — "Resetar vista" (câmera padrão + destravar LOCK) e "Baixar imagem PNG"
- **Modebar nativa do Plotly ocultada** (`display:none`); funções essenciais recriadas no painel.
- **Layout**: largura total da tela (`max-width:100%`), cena 3D com `height:1156`, iframe `1250px`.

## Refinamento PENDENTE (próximo)

### Opacidade independente por estrutura

**Objetivo didático**: permitir que a camada EXTERNA (coroa/superfície) fique TRANSPARENTE
enquanto a camada INTERNA (raiz/canal) permanece SÓLIDA — para estudar formato, estrutura e
volume da estrutura interna sem perder a referência externa.

**Situação atual**: o slider "CAMADAS" aplica a MESMA opacidade a todos os traces
simultaneamente (`Plotly.restyle({opacity})` sem índice). Não há controle por estrutura.

**Solução proposta**: substituir o slider único de opacidade por UM slider de opacidade
POR estrutura (cada trace tem índice próprio, como já acontece nos checkboxes de visibilidade).
Cada slider chama `Plotly.restyle(gd, {opacity: valor}, [traceIndex])` só do seu trace.
Assim o usuário regula externa e interna de forma independente.

**Pré-requisito**: confirmar que as estruturas internas (raiz/canal) estão disponíveis como
STL SEPARADOS do externo. Se hoje só há um STL único ("Molar"), este refinamento exige
carregar os STL separados (raiz, canal, coroa) — pendência de dados, não só de código.

## Objetivo maior (fora do escopo deste refinamento)

Transformar o app em um "pack" para professores e alunos (aulas e pesquisas), com dados
reais e acesso controlado por turma.
