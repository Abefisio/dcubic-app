# Decisões

## 2026-10-21 — Visualizador 3D sem eixos

Eixos 3D ocultos (visible=False, ranges mantidos) e hoverinfo='skip' em todos os Mesh3d, para visualização didática limpa.

## 2026-10-21 — Limpeza definitiva de eixos e hover

Criada limpar_figura_3d() em modules/viewer3d.py, aplicada antes de toda exibição 3D (st.plotly_chart e to_html do STL): eixos ocultos, spikes desligados, hover desativado.

## 2026-10-21 — Otimização FASE 2 (branch otimizacao/2026-10)

Itens 1, 2, 3, 4, 5, 7, 9 e 10 (este sob a forma de carregamento sob demanda) da `docs/ANALISE-OTIMIZACAO-2026-10.md`. Itens 6 e 8 ficaram para depois.

### Item 1 — Limite de envio do servidor e comando local

- `.streamlit/config.toml` versionado: `maxUploadSize = 200` (o Streamlit Cloud lê este arquivo; o secret `DCUBIC_MAX_UPLOAD_MB = 200` continua valendo).
- O limite exibido no app é o menor entre `DCUBIC_MAX_UPLOAD_MB`/padrão e o teto do servidor (`server.maxUploadSize`).
- **Comando local (Mac), para enviar arquivos de até 2 GB.** A opção de linha de comando tem precedência sobre o `config.toml` do projeto (que, por sua vez, tem precedência sobre `~/.streamlit/config.toml`). Iniciar sem `PYTHONDONTWRITEBYTECODE`, para o Python reaproveitar os `.pyc` (item 7):

```
cd ~/Developer/dcubic-app-repo
env -u PYTHONDONTWRITEBYTECODE python3 -m streamlit run app.py --server.headless true --server.port 8501 --server.address 127.0.0.1 --server.maxUploadSize 2048
```
