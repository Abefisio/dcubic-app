# Decisões

## 2026-10-21 — Visualizador 3D sem eixos

Eixos 3D ocultos (visible=False, ranges mantidos) e hoverinfo='skip' em todos os Mesh3d, para visualização didática limpa.

## 2026-10-21 — Limpeza definitiva de eixos e hover

Criada limpar_figura_3d() em modules/viewer3d.py, aplicada antes de toda exibição 3D (st.plotly_chart e to_html do STL): eixos ocultos, spikes desligados, hover desativado.
