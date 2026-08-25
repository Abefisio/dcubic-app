"""
DCubic Image System Platform
Análise de volumes 3D micro-CT — USP/FOUSP — Pesquisa acadêmica
"""

import os
import yaml
import streamlit as st
import numpy as np
import extra_streamlit_components as stx

# Patch: extra-streamlit-components 0.1.81 cria um novo CookieManager (e
# renderiza um componente iframe) a cada rerun, causando um loop infinito de
# reruns que deixa a página em branco. O cache_resource garante que o componente
# seja instanciado apenas uma vez por ciclo de vida do servidor.
# Patch IDEMPOTENTE do CookieManager.
# O Streamlit re-executa o app.py a cada rerun, mas o modulo stx persiste na
# memoria. Sem o guard abaixo, cada rerun re-empacotava o CookieManager,
# capturando a versao ja modificada como "original" -> recursao infinita.
# O guard garante que o original seja capturado UMA unica vez.
# A key fixa evita o loop de remontagem do widget de cookie.
if not getattr(stx.CookieManager, "_dcubic_patched", False):
    _dcubic_original_cm = stx.CookieManager

    def _patched_cookie_manager(*args, **kwargs):
        kwargs.setdefault("key", "dcubic_cookie_manager")
        return _dcubic_original_cm(*args, **kwargs)

    _patched_cookie_manager._dcubic_patched = True
    stx.CookieManager = _patched_cookie_manager

import streamlit_authenticator as stauth

from modules.loader import load_volume
from modules.viewer2d import render_triplanar, make_overlay_fig
from modules.segmentation import segment_volume, TISSUE_PALETTE, DEFAULT_THRESHOLDS
from modules.viewer3d import build_all_meshes, create_plotly_3d
from modules.metrics import (
    compute_volumes, compute_surface_areas, compute_distance,
    mesh_to_stl_bytes, mesh_to_obj_bytes,
)
from modules.report import generate_pdf

st.set_page_config(
    page_title="DCubic Image System Platform",
    page_icon="🔬",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Autenticação — credenciais via Streamlit Secrets (nunca hardcoded)
# ---------------------------------------------------------------------------
_USERS_YAML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth", "users.yaml")

if os.path.exists(_USERS_YAML):
    with open(_USERS_YAML, "r") as _f:
        _auth_config = yaml.safe_load(_f)
else:
    # Streamlit Cloud: credenciais injetadas via st.secrets (objeto imutável).
    # Convertido para dict comum (mutável), pois streamlit-authenticator
    # modifica credentials["usernames"] internamente.
    def _to_plain(_o):
        if hasattr(_o, "items"):
            return {_k: _to_plain(_v) for _k, _v in _o.items()}
        if isinstance(_o, list):
            return [_to_plain(_v) for _v in _o]
        return _o
    _raw_auth = st.secrets.get("auth", None)
    if _raw_auth is None:
        st.error("Configuração de autenticação não encontrada. Configure st.secrets['auth'].")
        st.stop()
    _auth_config = _to_plain(_raw_auth)

authenticator = stauth.Authenticate(
    _auth_config["credentials"],
    _auth_config["cookie"]["name"],
    _auth_config["cookie"]["key"],
    _auth_config["cookie"]["expiry_days"],
)

# Idle-timeout: força re-login após 30 min de inatividade
_IDLE_MINUTES = 30
if st.session_state.get("authentication_status"):
    import time
    _now = time.time()
    _last = st.session_state.get("_last_active", _now)
    if _now - _last > _IDLE_MINUTES * 60:
        authenticator.cookie_controller.delete_cookie()
        for _k in ("authentication_status", "name", "username"):
            st.session_state.pop(_k, None)
        st.session_state["_idle_logout"] = True
    else:
        st.session_state["_last_active"] = _now

authenticator.login(location="main")

_auth_status = st.session_state.get("authentication_status")

if _auth_status is not True:
    if st.session_state.get("_idle_logout"):
        st.warning("Sessão encerrada por inatividade (30 min). Faça login novamente.")
    elif _auth_status is False:
        st.error("Usuário ou senha incorretos.")
    else:
        st.info("Faça login para acessar o DCubic Image System Platform.")
    st.stop()

# Login bem-sucedido — exibe o app abaixo
authenticator.logout(location="sidebar")
st.sidebar.caption(f"Logado como: {st.session_state.get('name', '')}")

# ---------------------------------------------------------------------------
# App principal
# ---------------------------------------------------------------------------
st.title("DCubic Image System Platform")
st.caption("Análise de volumes 3D micro-CT · USP/FOUSP · Pesquisa acadêmica")


@st.cache_data
def _load_vol():
    return load_volume(synthetic=True)


vol_data = _load_vol()
volume   = vol_data["volume"]
Z, Y, X  = volume.shape

with st.expander("ℹ️ Dataset carregado", expanded=False):
    if "warning" in vol_data:
        st.warning(vol_data["warning"])
    st.json({
        "fonte": vol_data["source"],
        "shape (Z, Y, X)": list(vol_data["shape"]),
        "espaçamento (z, y, x)": [round(s, 4) for s in vol_data["spacing"]],
        "dtype_original": vol_data["dtype_original"],
        "valor_min": round(float(np.min(volume)), 6),
        "valor_max": round(float(np.max(volume)), 6),
        "RAM estimada (MB)": round(volume.nbytes / 1e6, 2),
    })

st.divider()

st.subheader("Navegação por corte")
c1, c2, c3 = st.columns(3)
with c1:
    z_idx = st.slider("Axial (Z)", 0, Z - 1, Z // 2, key="z_idx")
with c2:
    y_idx = st.slider("Coronal (Y)", 0, Y - 1, Y // 2, key="y_idx")
with c3:
    x_idx = st.slider("Sagital (X)", 0, X - 1, X // 2, key="x_idx")

tissue_names        = list(DEFAULT_THRESHOLDS.keys())
render_tissue_names = [n for n in tissue_names if n != "Fundo"]

tab_2d, tab_seg, tab_3d, tab_met = st.tabs(["📐 Triplanar", "🔍 Segmentação", "🫙 Render 3D", "📊 Métricas & Export"])

# ---------------------------------------------------------------------------
# Aba 1 — Visualização 2D triplanar
# ---------------------------------------------------------------------------
with tab_2d:
    fig_ax, fig_sag, fig_cor = render_triplanar(volume, z_idx, y_idx, x_idx)
    col_ax, col_sag, col_cor = st.columns(3)
    col_ax.plotly_chart(fig_ax,  use_container_width=True)
    col_sag.plotly_chart(fig_sag, use_container_width=True)
    col_cor.plotly_chart(fig_cor, use_container_width=True)
    st.caption(
        f"Escala de cinza global [0, 1] · "
        f"Volume {Z}×{Y}×{X} voxels · "
        f"Espaçamento {vol_data['spacing'][0]:.4f} mm/voxel"
    )

# ---------------------------------------------------------------------------
# Aba 2 — Segmentação por threshold multi-tecido
# ---------------------------------------------------------------------------
with tab_seg:
    st.markdown("**Thresholds por tecido** — ajuste os limiares; o overlay atualiza em tempo real.")

    thresholds: dict[str, tuple[float, float]] = {}
    th_cols = st.columns(len(tissue_names))
    for i, name in enumerate(tissue_names):
        r, g, b = TISSUE_PALETTE[name]
        with th_cols[i]:
            st.markdown(
                f"<span style='color:#{r:02x}{g:02x}{b:02x};font-size:18px'>■</span> **{name}**",
                unsafe_allow_html=True,
            )
            lo, hi = DEFAULT_THRESHOLDS[name]
            thresholds[name] = st.slider(
                "limiar", 0.0, 1.0, (lo, hi), step=0.01, key=f"thresh_{name}"
            )

    st.divider()

    masks = segment_volume(volume, thresholds)

    st.markdown("**Voxels segmentados** (contagem sobre dados brutos — métricas em mm³ no Bloco 5):")
    cnt_cols = st.columns(len(tissue_names))
    for i, name in enumerate(tissue_names):
        cnt_cols[i].metric(name, f"{int(masks[name].sum()):,}")

    st.divider()

    ax_masks  = {n: masks[n][z_idx, :, :]   for n in tissue_names}
    sag_masks = {n: masks[n][:, :, x_idx]   for n in tissue_names}
    cor_masks = {n: masks[n][:, y_idx, :]   for n in tissue_names}

    fig_ax_ov  = make_overlay_fig(volume[z_idx, :, :],   ax_masks,  TISSUE_PALETTE, f"Axial   Z={z_idx}",  y_idx, x_idx)
    fig_sag_ov = make_overlay_fig(volume[:, :, x_idx],   sag_masks, TISSUE_PALETTE, f"Sagital X={x_idx}", z_idx, y_idx)
    fig_cor_ov = make_overlay_fig(volume[:, y_idx, :],   cor_masks, TISSUE_PALETTE, f"Coronal Y={y_idx}", z_idx, x_idx)

    ov_ax, ov_sag, ov_cor = st.columns(3)
    ov_ax.plotly_chart(fig_ax_ov,  use_container_width=True)
    ov_sag.plotly_chart(fig_sag_ov, use_container_width=True)
    ov_cor.plotly_chart(fig_cor_ov, use_container_width=True)

    st.caption(
        "Princípio 1: os thresholds acima definem segmentação e overlay visual. "
        "Métricas de volume (mm³) e área (mm²) calculadas sobre os voxels brutos na aba Métricas."
    )

# ---------------------------------------------------------------------------
# Aba 3 — Render 3D
# ---------------------------------------------------------------------------
with tab_3d:
    st.markdown(
        "**Render 3D por tecido segmentado** — malha gerada via marching cubes "
        "a partir dos masks de voxels brutos (Princípio 1). "
        "Rotacione e amplie diretamente no gráfico."
    )

    op_cols = st.columns(len(render_tissue_names))
    opacities: dict[str, float] = {}
    for i, name in enumerate(render_tissue_names):
        r, g, b = TISSUE_PALETTE[name]
        with op_cols[i]:
            st.markdown(
                f"<span style='color:#{r:02x}{g:02x}{b:02x}'>■</span> **{name}**",
                unsafe_allow_html=True,
            )
            opacities[name] = st.slider(
                "opacidade", 0.0, 1.0,
                0.35 if name == "Tecido mole" else 1.0,
                step=0.05,
                key=f"op3d_{name}",
            )

    spacing_z = vol_data["spacing"][0]
    max_z_mm  = float(Z * spacing_z)
    clip_z_mm = st.slider(
        "Plano de corte Z (mm) — arraste para a esquerda para revelar o interior",
        0.0, max_z_mm, max_z_mm,
        step=round(spacing_z, 4),
        key="clip_z_mm",
    )
    apply_clip = clip_z_mm < max_z_mm

    with st.spinner("Gerando malhas 3D (marching cubes)…"):
        meshes_3d = build_all_meshes(masks, vol_data["spacing"], exclude={"Fundo"})

    mesh_info = {n: (m.n_points if m else 0) for n, m in meshes_3d.items()}
    st.caption(
        "Vértices: "
        + " · ".join(f"{n} {v:,}" for n, v in mesh_info.items())
        + " (Fundo/ar excluído)"
    )

    fig_3d = create_plotly_3d(
        meshes_3d,
        TISSUE_PALETTE,
        opacities=opacities,
        clip_z_mm=clip_z_mm if apply_clip else None,
    )
    st.plotly_chart(fig_3d, use_container_width=True)

    st.caption(
        "Princípio 1: a malha 3D é gerada a partir dos masks de voxels brutos. "
        "Métricas quantitativas disponíveis na aba 📊 Métricas & Export."
    )

# ---------------------------------------------------------------------------
# Aba 4 — Métricas quantitativas e exportação
# ---------------------------------------------------------------------------
with tab_met:
    st.markdown(
        "**Métricas calculadas sobre os voxels brutos** (Princípio 1). "
        "Nenhum valor depende da imagem renderizada ou das configurações visuais."
    )

    masks_met = segment_volume(volume, {
        n: (DEFAULT_THRESHOLDS[n]) for n in tissue_names
    })

    with st.spinner("Calculando métricas e gerando malhas…"):
        volumes_mm3 = compute_volumes(masks_met, vol_data["spacing"])
        meshes_met  = build_all_meshes(masks_met, vol_data["spacing"], exclude={"Fundo"})
        areas_mm2   = compute_surface_areas(meshes_met)

    st.subheader("Volume e área de superfície por tecido")
    met_cols = st.columns(len(tissue_names))
    for i, name in enumerate(tissue_names):
        r, g, b = TISSUE_PALETTE[name]
        with met_cols[i]:
            st.markdown(
                f"<span style='color:#{r:02x}{g:02x}{b:02x}'>■</span> **{name}**",
                unsafe_allow_html=True,
            )
            st.metric("Volume (mm³)",          f"{volumes_mm3[name]:.4f}")
            st.metric("Área de superfície (mm²)", f"{areas_mm2.get(name, 0.0):.4f}")

    st.caption(
        "Volume = nº de voxels × espaçamento³. "
        "Área = soma das áreas dos triângulos da malha marching cubes."
    )
    st.divider()

    st.subheader("Distância entre dois pontos (voxel → mm)")
    dcol1, dcol2 = st.columns(2)
    with dcol1:
        st.markdown("**Ponto A**")
        az = st.number_input("Z_A", 0, Z - 1, z_idx, key="dist_az")
        ay = st.number_input("Y_A", 0, Y - 1, y_idx, key="dist_ay")
        ax = st.number_input("X_A", 0, X - 1, x_idx, key="dist_ax")
    with dcol2:
        st.markdown("**Ponto B**")
        bz = st.number_input("Z_B", 0, Z - 1, min(z_idx + 10, Z - 1), key="dist_bz")
        by_ = st.number_input("Y_B", 0, Y - 1, min(y_idx + 10, Y - 1), key="dist_by")
        bx = st.number_input("X_B", 0, X - 1, min(x_idx + 10, X - 1), key="dist_bx")

    dist_mm = compute_distance((az, ay, ax), (bz, by_, bx), vol_data["spacing"])
    st.metric("Distância A → B", f"{dist_mm:.4f} mm")
    distances_for_report = [{"label": "A → B", "mm": dist_mm}]
    st.divider()

    st.subheader("Exportação de malhas 3D")
    st.markdown("Malhas geradas por marching cubes a partir dos masks de voxels brutos.")

    export_cols = st.columns(len(render_tissue_names) * 2)
    col_idx = 0
    for name in render_tissue_names:
        mesh_e = meshes_met.get(name)
        if mesh_e is None:
            col_idx += 2
            continue
        with export_cols[col_idx]:
            st.download_button(
                label=f"⬇ {name} STL",
                data=mesh_to_stl_bytes(mesh_e),
                file_name=f"dcubic_{name.replace('/', '_').replace(' ', '_')}.stl",
                mime="application/octet-stream",
                key=f"dl_stl_{name}",
            )
        with export_cols[col_idx + 1]:
            st.download_button(
                label=f"⬇ {name} OBJ",
                data=mesh_to_obj_bytes(mesh_e),
                file_name=f"dcubic_{name.replace('/', '_').replace(' ', '_')}.obj",
                mime="text/plain",
                key=f"dl_obj_{name}",
            )
        col_idx += 2
    st.divider()

    st.subheader("Relatório PDF")
    if st.button("Gerar relatório PDF", key="gen_pdf"):
        with st.spinner("Gerando PDF…"):
            pdf_bytes = generate_pdf(
                vol_data=vol_data,
                thresholds={n: DEFAULT_THRESHOLDS[n] for n in tissue_names},
                volumes_mm3=volumes_mm3,
                areas_mm2=areas_mm2,
                distances=distances_for_report,
            )
        st.download_button(
            label="⬇ Baixar relatório PDF",
            data=pdf_bytes,
            file_name="dcubic_relatorio.pdf",
            mime="application/pdf",
            key="dl_pdf",
        )
    st.caption(
        "Princípio 1: todas as métricas no relatório são calculadas sobre os "
        "voxels brutos, nunca sobre imagens renderizadas."
    )
