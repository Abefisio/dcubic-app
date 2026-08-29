"""
DCubic Image System Platform
Análise de volumes 3D micro-CT — USP/FOUSP — Pesquisa acadêmica
"""

import json
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
# Pega a classe CookieManager ORIGINAL direto do submodulo em sys.modules.
# O Streamlit Cloud pode manter o processo vivo entre commits, deixando
# stx.CookieManager embrulhado por patches antigos (recursao). Buscar do
# submodulo ignora qualquer reatribuicao anterior e sempre embrulha a classe
# real. A key fixa evita o loop de remontagem do widget de cookie.
import sys as _sys
_cm_submod = _sys.modules.get("extra_streamlit_components.CookieManager")
_dcubic_original_cm = getattr(_cm_submod, "CookieManager", None) or stx.CookieManager

def _patched_cookie_manager(*args, **kwargs):
    kwargs.setdefault("key", "dcubic_cookie_manager")
    return _dcubic_original_cm(*args, **kwargs)

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
from modules.anatomy import compute_anatomy
from modules import references
from modules.mesh_loader import load_meshes

_MAX_VOXELS = 12_000_000  # ponytail: ajuste conforme RAM disponível (Streamlit Cloud ~1 GB)

st.set_page_config(
    page_title="DCubic Image System Platform",
    page_icon="🔬",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Identidade visual DCubic (tema + molar 3D)
# ---------------------------------------------------------------------------
import base64 as _b64mod
import streamlit.components.v1 as _components

st.markdown(
    "<style>@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500&display=swap');"
    "html,body,[class*='css'],.stApp,button,input,textarea,select{font-family:'Inter',sans-serif !important;}"
    "h1,h2,h3,h4{font-family:'Inter',sans-serif !important;letter-spacing:-.02em;}.stApp a{color:#00c2c9;}</style>",
    unsafe_allow_html=True,
)

_DC_DIR = os.path.dirname(os.path.abspath(__file__))
_DC_ASSETS = os.path.join(_DC_DIR, "assets")

def _dc_b64(_p):
    try:
        with open(_p, "rb") as _fh:
            return _b64mod.b64encode(_fh.read()).decode("ascii")
    except Exception:
        return ""

def _dc_read(_p):
    try:
        with open(_p, "r", encoding="utf-8") as _fh:
            return _fh.read()
    except Exception:
        return ""

def _dc_molar_sources():
    _s = ""
    _w = _dc_b64(os.path.join(_DC_ASSETS, "molar.webm"))
    _m = _dc_b64(os.path.join(_DC_ASSETS, "molar.mp4"))
    if _w:
        _s += '<source src="data:video/webm;base64,' + _w + '" type="video/webm">'
    if _m:
        _s += '<source src="data:video/mp4;base64,' + _m + '" type="video/mp4">'
    return _s


# ---------------------------------------------------------------------------
# Autenticação — credenciais via Streamlit Secrets (nunca hardcoded)
# ---------------------------------------------------------------------------
_USERS_YAML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth", "users.yaml")

def _to_plain(_o):
    if hasattr(_o, "items"):
        return {_k: _to_plain(_v) for _k, _v in _o.items()}
    if isinstance(_o, list):
        return [_to_plain(_v) for _v in _o]
    return _o

if os.path.exists(_USERS_YAML):
    # a) local: arquivo auth/users.yaml em disco
    with open(_USERS_YAML, "r", encoding="utf-8") as _f:
        _auth_config = yaml.safe_load(_f)
else:
    _auth_config = None

    # b) Streamlit Cloud: st.secrets["auth"]
    if _auth_config is None:
        try:
            _raw_auth = st.secrets.get("auth", None)
            if _raw_auth is not None:
                _auth_config = _to_plain(_raw_auth)
        except Exception:
            pass

    # c) Hugging Face Spaces (e qualquer ambiente com env vars): AUTH_CONFIG_JSON
    if _auth_config is None:
        _env_json = os.environ.get("AUTH_CONFIG_JSON")
        if _env_json:
            try:
                _auth_config = json.loads(_env_json)
            except Exception as _je:
                st.error(f"AUTH_CONFIG_JSON inválido: {_je}")
                st.stop()

    # d) nenhum caminho disponível
    if _auth_config is None:
        st.error(
            "Configuração de autenticação não encontrada. "
            "Configure st.secrets['auth'] (Streamlit Cloud) ou "
            "AUTH_CONFIG_JSON (Hugging Face / variável de ambiente)."
        )
        st.stop()

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

_dc_login_top = st.container()
st.markdown(
    "<style>"
    "[data-testid='stForm']{max-width:30% !important;min-width:320px;margin-left:auto !important;margin-right:auto !important;}"
    "</style>",
    unsafe_allow_html=True,
)
authenticator.login(location="main")

_auth_status = st.session_state.get("authentication_status")

if _auth_status is not True:
    with _dc_login_top:
        _dc_login = _dc_read(os.path.join(_DC_ASSETS, "login.html")).replace("__SRC__", _dc_molar_sources())
        if _dc_login:
            _components.html(_dc_login, height=180, scrolling=False)
    if st.session_state.get("_idle_logout"):
        st.warning("Sessão encerrada por inatividade (30 min). Faça login novamente.")
    elif _auth_status is False:
        st.error("Usuário ou senha incorretos.")
    st.stop()

# Login bem-sucedido — exibe o app abaixo
authenticator.logout(location="sidebar")
st.sidebar.caption(f"Logado como: {st.session_state.get('name', '')}")

# ---------------------------------------------------------------------------
# App principal
# ---------------------------------------------------------------------------
st.markdown(
    "<style>"
    ".block-container{padding-top:0rem !important;}"
    "header[data-testid='stHeader']{height:0;}"
    "[data-testid='stForm']{max-width:30% !important;min-width:320px;margin-left:auto !important;margin-right:auto !important;}"
    "</style>",
    unsafe_allow_html=True,
)
st.markdown(
    "<h4 style='margin:0;text-align:left'>DCubic Image System Platform</h4>",
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def _load_synthetic_vol():
    return load_volume(synthetic=True)


@st.cache_data(show_spinner="Carregando volume enviado...")
def _load_uploaded_vol(files):
    """files: tupla de (nome, bytes). Salva em pasta temporaria e carrega.

    DICOM (.dcm) e TIFF (.tif/.tiff) sao pilhas -> passa a pasta.
    NIfTI (.nii/.nii.gz) e arquivo unico -> passa o arquivo.
    """
    import os, tempfile
    tmpdir = tempfile.mkdtemp(prefix="dcubic_up_")
    saved = []
    for name, data in files:
        fp = os.path.join(tmpdir, os.path.basename(name))
        with open(fp, "wb") as fh:
            fh.write(data)
        saved.append(fp)
    nii = next((s for s in saved
                if s.lower().endswith(".nii") or s.lower().endswith(".nii.gz")), None)
    if nii is not None:
        return load_volume(nii)
    return load_volume(tmpdir)


# Chave de hash para ndarrays: shape + dtype + soma total (O(N) mas via SIMD, ~µs).
# Evita serializar arrays grandes; colisão improvável para volumes/masks distintos.
_arr_hash = lambda a: (a.shape, a.dtype.str, float(a.sum()))


@st.cache_resource
def _load_stl_from_paths(path_mtime_pairs):
    """Carrega e decima STLs a partir de caminhos de disco.

    Usa cache_resource (sem serialização) — objetos PolyData mantidos na
    memória entre reruns sem reconstrução. Chave: tupla de (caminho, mtime),
    então o cache invalida automaticamente se qualquer arquivo for modificado.
    Passa cache_key = caminho sem extensão para ativar cache decimado em disco.
    """
    _files = []
    _cache_keys = []
    for _p, _mt in path_mtime_pairs:
        try:
            with open(_p, "rb") as _fh:
                _files.append((os.path.basename(_p), _fh.read()))
                _cache_keys.append(os.path.splitext(_p)[0])
        except Exception:
            pass
    return load_meshes(_files, cache_keys=_cache_keys)


@st.cache_data(hash_funcs={np.ndarray: _arr_hash}, show_spinner=False)
def _build_meshes_cached(masks, spacing, exclude_tuple):
    """Malhas 3D (marching cubes) — re-calcula só quando masks ou spacing mudam."""
    return build_all_meshes(masks, spacing, exclude=set(exclude_tuple))


@st.cache_data(hash_funcs={np.ndarray: _arr_hash}, show_spinner=False)
def _compute_anatomy_cached(volume, spacing, crown_at_high, cervical_frac):
    """Volumes anatômicos — re-calcula só quando o volume ou parâmetros mudam."""
    return compute_anatomy(volume, spacing, crown_at_high=crown_at_high, cervical_frac=cervical_frac)


st.sidebar.header("Dados")
_uploads = st.sidebar.file_uploader(
    "Carregar micro-CT (DICOM .dcm, TIFF .tif/.tiff, NIfTI .nii/.nii.gz) "
    "ou malhas STL exportadas pelo Bruker CTAnalyser (.stl). "
    "Para DICOM/TIFF, selecione TODOS os cortes de uma vez.",
    type=["dcm", "tif", "tiff", "nii", "gz", "stl"],
    accept_multiple_files=True,
)

# ---------------------------------------------------------------------------
# MODO STL — ativado quando há pelo menos um .stl no upload OU quando o
# usuário carrega da pasta local. Caminho paralelo ao pipeline de volume.
# ---------------------------------------------------------------------------

# Caminho A: leitura da pasta local — só disponível quando o diretório padrão existe.
_LOCAL_DEFAULT = os.path.expanduser("~/Desktop/DCUBIC-SITE/MICROTOMO")
_local_available = os.path.isdir(_LOCAL_DEFAULT)

if _local_available:
    _stl_folder = st.sidebar.text_input(
        "Pasta com STL (leitura local)",
        value=_LOCAL_DEFAULT,
        key="stl_folder_path",
    )
    _load_folder_btn = st.sidebar.button("Carregar STL da pasta", key="stl_load_folder")
else:
    st.sidebar.info("Leitura de pasta local indisponível neste ambiente — use o upload de arquivos.")
    _stl_folder = ""
    _load_folder_btn = False

# ---------------------------------------------------------------------------
# DENTES DE EXEMPLO — download sob demanda do Google Drive
# ---------------------------------------------------------------------------
_DRIVE_SAMPLES = {
    "Esmalte": "1OmWWs6kaUc6bT3gD2jjHMFX41r1g_45P",
    "Dentina": "1_bbDyFS2QG9qL8xecflwTjuwlKVrjm7J",
    "Molar":   "1B9z0GMQzHxYegnGY69KLVuPs-U8m38gH",
}
_SAMPLE_DIR = "/tmp/dcubic_samples"

st.sidebar.markdown("---")
st.sidebar.subheader("Dentes de exemplo")
_sample_sel = st.sidebar.selectbox(
    "Estrutura de exemplo",
    ["— selecione —"] + list(_DRIVE_SAMPLES.keys()),
    key="drive_sample_sel",
)
def _stl_valido(_p):
    """Retorna True se _p é um STL plausível (existe, >100 KB, não é HTML de erro)."""
    if not os.path.isfile(_p):
        return False
    if os.path.getsize(_p) < 100 * 1024:
        return False
    try:
        with open(_p, "rb") as _fv:
            return not _fv.read(5).startswith(b"<")
    except Exception:
        return False

if st.sidebar.button("Carregar dente de exemplo", key="drive_sample_btn"):
    if _sample_sel == "— selecione —":
        st.sidebar.warning("Selecione uma estrutura antes de carregar.")
    else:
        _fid = _DRIVE_SAMPLES[_sample_sel]
        _dest = os.path.join(_SAMPLE_DIR, f"{_sample_sel}.stl")
        if not _stl_valido(_dest):
            _erro_msg = ""
            try:
                import gdown
                os.makedirs(_SAMPLE_DIR, exist_ok=True)
                with st.spinner("Baixando dente do Drive…"):
                    gdown.download(
                        f"https://drive.google.com/uc?id={_fid}", _dest, quiet=True
                    )
            except Exception as _e:
                _erro_msg = str(_e)
            if not _stl_valido(_dest):
                try:
                    if os.path.isfile(_dest):
                        os.remove(_dest)
                except Exception:
                    pass
                st.warning(
                    f"Não foi possível baixar do Drive agora. "
                    f"Detalhe: {_erro_msg[:200] or 'arquivo inválido ou incompleto'} "
                    "— tente em alguns minutos ou use o upload manual."
                )
                _dest = None
        if _dest and _stl_valido(_dest):
            st.session_state["stl_paths"] = [_dest]
            st.rerun()

# Coletar STLs do upload — filtra apenas .stl, ignora outros formatos silenciosamente
_stl_from_upload = []
for _uf in (_uploads or []):
    if _uf.name.lower().endswith(".stl"):
        try:
            _stl_from_upload.append((_uf.name, _uf.getvalue()))
        except Exception as _ue:
            st.sidebar.warning(f"Upload ignorado ({_uf.name}): {_ue}")

# Quando o botão for clicado: persiste apenas CAMINHOS em session_state.
# Bytes (~1,3 GB) não são guardados — seriam copiados a cada rerun.
if _load_folder_btn:
    import glob as _glob
    _folder_path = _stl_folder.strip()
    if not os.path.isdir(_folder_path):
        st.sidebar.warning(f"Pasta não encontrada: {_folder_path}")
    else:
        _found = sorted(
            p for p in _glob.glob(os.path.join(_folder_path, "*.stl"))
            if ".dcubic_cache." not in os.path.basename(p)
        )
        if not _found:
            _found = sorted(
                p for p in _glob.glob(os.path.join(_folder_path, "*.STL"))
                if ".dcubic_cache." not in os.path.basename(p)
            )
        if not _found:
            st.sidebar.warning(f"Nenhum arquivo .stl encontrado em: {_folder_path}")
        else:
            st.session_state["stl_paths"] = _found

if st.sidebar.button("Limpar STL", key="stl_clear"):
    st.session_state.pop("stl_paths", None)
    st.session_state.pop("stl_selected_path", None)
    st.session_state.pop("_stl_last", None)
    st.rerun()

# Seletor de arquivo único — renderiza somente se houver caminhos carregados.
# Disco tem prioridade: quando há pasta, upload é ignorado.
_stl_path_mtime_dedup = []
_stl_upload_dedup = []

_opcoes = st.session_state.get("stl_paths", [])
if _opcoes:
    _sel = st.sidebar.radio(
        "Estrutura a exibir (uma por vez)",
        options=_opcoes,
        format_func=lambda p: os.path.splitext(os.path.basename(p))[0],
        key="stl_selected_path",
    )
    # Limpar cache se a seleção mudou desde o último rerun
    if _sel != st.session_state.get("_stl_last"):
        _load_stl_from_paths.clear()
        st.session_state["_stl_last"] = _sel
    if _sel and os.path.isfile(_sel):
        _stl_path_mtime_dedup = [(_sel, os.path.getmtime(_sel))]
else:
    # Sem pasta carregada: aceita apenas o primeiro .stl do upload
    if _stl_from_upload:
        _stl_upload_dedup = [_stl_from_upload[0]]

_is_stl = bool(_stl_path_mtime_dedup or _stl_upload_dedup)

if _is_stl:
    _prog = st.progress(0, text="Preparando…")

    def _cb(pct, label):
        _prog.progress(int(pct), text=f"{label} ({int(pct)}%)")

    # Para _load_stl_from_paths (cacheada): não passa callback — callback
    # quebraria a chave do cache_resource. Em vez disso, verifica o cache de
    # disco antecipadamente para dar feedback honesto: cache-hit = 100% imediato;
    # cache-miss = 25% antes da chamada bloqueante, 100% após.
    _mi_disk = []
    if _stl_path_mtime_dedup:
        _sel_base = os.path.splitext(_stl_path_mtime_dedup[0][0])[0]
        _disk_cached = (
            os.path.isfile(_sel_base + ".dcubic_cache.ply")
            and os.path.isfile(_sel_base + ".dcubic_cache.json")
        )
        if _disk_cached:
            _cb(100, "Carregado do cache")
        else:
            _cb(25, "Lendo e decimando STL")
        _mi_disk = _load_stl_from_paths(tuple(_stl_path_mtime_dedup))
        if not _disk_cached:
            _cb(100, "Pronto")

    # Upload: progress_cb funciona plenamente (sem camada de cache)
    _mi_upload = load_meshes(_stl_upload_dedup, progress_cb=_cb) if _stl_upload_dedup else []
    _meshes_info = _mi_disk + _mi_upload
    _prog.empty()

    _stl_errors = [m for m in _meshes_info if "error" in m]
    if _stl_errors:
        st.warning(
            "Falha ao carregar: "
            + ", ".join(f"{m['name']} ({m['error']})" for m in _stl_errors)
        )

    _stl_ok = [m for m in _meshes_info if "error" not in m]
    if not _stl_ok:
        st.error("Nenhuma malha STL válida foi carregada.")
        st.stop()

    # Aparência e visibilidade migradas para client-side (HTML abaixo).
    _COL_INIT = (235, 235, 235)  # tom inicial — ajustável no slider HTML
    _meshes_dict = {}
    _tissue_colors_stl = {}
    _opac_dict = {}
    for _mi in _stl_ok:
        _tissue_colors_stl[_mi["name"]] = _COL_INIT
        _meshes_dict[_mi["name"]] = _mi["mesh"]
        _opac_dict[_mi["name"]] = 1.0

    st.subheader("Render 3D — malhas STL")
    if _meshes_dict:
        _fig_stl = create_plotly_3d(
            _meshes_dict, _tissue_colors_stl, opacities=_opac_dict, clip_z_mm=None
        )
        _fig_stl.update_layout(
            uirevision="constant",  # preserva câmera entre reruns do Streamlit
            modebar=dict(orientation="v"),
            height=1156,
            margin=dict(l=0, r=0, t=0, b=0),
            scene=dict(
                dragmode="orbit",
                aspectmode="data",
                xaxis=dict(title=dict(font=dict(size=18)), tickfont=dict(size=15)),
                yaxis=dict(title=dict(font=dict(size=18)), tickfont=dict(size=15)),
                zaxis=dict(title=dict(font=dict(size=18)), tickfont=dict(size=15)),
            ),
            updatemenus=[dict(
                type="buttons",
                direction="right",
                x=0,
                y=1.08,
                showactive=False,
                buttons=[
                    dict(label="Topo",
                         method="relayout",
                         args=[{"scene.camera.eye": {"x": 0, "y": 0, "z": 2.2},
                                "scene.camera.up":  {"x": 0, "y": 1, "z": 0}}]),
                    dict(label="Frente",
                         method="relayout",
                         args=[{"scene.camera.eye": {"x": 0, "y": -2.2, "z": 0}}]),
                    dict(label="Lado",
                         method="relayout",
                         args=[{"scene.camera.eye": {"x": 2.2, "y": 0, "z": 0}}]),
                    dict(label="Perspectiva",
                         method="relayout",
                         args=[{"scene.camera.eye": {"x": 1.5, "y": 1.5, "z": 1.2}}]),
                ],
            )],
        )
        # Render via iframe HTML: todos os controles em JS puro — sem rerun.
        import streamlit.components.v1 as _components
        _plot_frag = _fig_stl.to_html(
            include_plotlyjs="cdn", full_html=False, div_id="stl_plot",
            config={"displayModeBar": True},
        )
        _vis_html = "".join(
            f'<label class="vis-chk"><input type="checkbox" class="visChk" data-idx="{_vi}" checked> {_vm["name"]}</label>'
            for _vi, _vm in enumerate(_stl_ok)
        )
        _ctrl_html = """
<style>
body{margin:0;background:#0f0f0f;color:#eee;font-family:sans-serif}
#ctrl,#ctrl2,#ctrl3{display:flex;align-items:center;gap:8px;padding:4px 14px;
      background:#1a1a1a;border-bottom:1px solid #2a2a2a;flex-wrap:wrap}
#ctrl label,#ctrl2 label,#ctrl3 label{font-size:11px;font-weight:700;letter-spacing:.08em;color:#999;text-transform:uppercase}
.ends{font-size:11px;color:#666}
#opacRange{flex:1;min-width:120px;max-width:280px;accent-color:#4da6ff;cursor:pointer}
#opacVal{font-size:12px;color:#aaa;min-width:38px;text-align:right}
#lockBtn{padding:5px 18px;border:none;border-radius:4px;font-size:13px;font-weight:700;
         cursor:pointer;background:#3a3a3a;color:#ccc;box-shadow:none;
         transition:background .18s,box-shadow .18s,color .18s}
#lockBtn.on{background:#4da6ff;color:#000;box-shadow:0 0 12px #4da6ffaa}
.mode-btn{padding:3px 12px;border:1px solid #444;border-radius:4px;font-size:11px;
          font-weight:700;cursor:pointer;background:#2a2a2a;color:#aaa;
          transition:background .15s,color .15s}
.mode-btn.on{background:#555;color:#fff;border-color:#888}
#toneRange{flex:1;min-width:100px;max-width:220px;accent-color:#aaa;cursor:pointer}
#toneVal{font-size:11px;color:#aaa;min-width:28px}
#colorPick{width:32px;height:22px;border:none;border-radius:3px;cursor:pointer;padding:0}
.vis-chk{font-size:11px;color:#aaa;display:flex;align-items:center;gap:4px;cursor:pointer}
.vis-chk input{accent-color:#4da6ff;cursor:pointer}
.modebar{opacity:1!important;background:rgba(30,30,30,0.7)!important;
         border-radius:4px;padding:4px 2px}
.modebar-btn{margin:0 6px!important}
.modebar-btn svg{transform:scale(1.6);transform-origin:center}
.modebar-btn path{fill:#ddd!important}
.modebar-btn:hover path{fill:#fff!important}
</style>
<div id="ctrl">
  <label>CAMADAS</label>
  <span class="ends">Transparente</span>
  <input type="range" id="opacRange" min="1" max="100" step="1" value="100">
  <span class="ends">Sólido</span>
  <span id="opacVal">100%</span>
  <button id="lockBtn">&#x1F512; LOCK</button>
</div>
<div id="ctrl2">
  <label>COR</label>
  <button class="mode-btn on" id="modeGray">Cinza</button>
  <button class="mode-btn" id="modeColor">Cor personalizada</button>
  <span id="grayCtrl" style="display:flex;align-items:center;gap:8px;flex:1">
    <span class="ends">Escuro</span>
    <input type="range" id="toneRange" min="0" max="255" step="1" value="235">
    <span class="ends">Claro</span>
    <span id="toneVal">235</span>
  </span>
  <span id="colorCtrl" style="display:none;align-items:center;gap:8px">
    <input type="color" id="colorPick" value="#ebebeb">
  </span>
</div>
<div id="ctrl3">
  <label>ESTRUTURAS</label>__VIS__
</div>
<script>
(function(){
  var locked=false,savedCamera=null,lockApplying=false;

  function captureCamera(gd){
    try{
      var sc=gd._fullLayout&&gd._fullLayout.scene;
      if(sc&&sc.camera) return JSON.parse(JSON.stringify(sc.camera));
    }catch(e){}
    return null;
  }

  function init(){
    var gd=document.getElementById('stl_plot');
    if(!gd||!gd._fullLayout){setTimeout(init,250);return;}

    // ---- Opacidade ----
    var range=document.getElementById('opacRange');
    var opacVal=document.getElementById('opacVal');
    range.addEventListener('input',function(){
      opacVal.textContent=this.value+'%';
      Plotly.restyle(gd,{opacity:this.value/100});
    });

    // ---- Tom / Cor ----
    var toneRange=document.getElementById('toneRange');
    var colorPick=document.getElementById('colorPick');
    var modeGray=document.getElementById('modeGray');
    var modeColor=document.getElementById('modeColor');
    var grayCtrl=document.getElementById('grayCtrl');
    var colorCtrl=document.getElementById('colorCtrl');

    function applyColor(c){Plotly.restyle(gd,{color:c});}

    toneRange.addEventListener('input',function(){
      document.getElementById('toneVal').textContent=this.value;
      var v=this.value;
      applyColor('rgb('+v+','+v+','+v+')');
    });
    colorPick.addEventListener('input',function(){applyColor(this.value);});

    modeGray.addEventListener('click',function(){
      modeGray.classList.add('on');modeColor.classList.remove('on');
      grayCtrl.style.display='flex';colorCtrl.style.display='none';
      var v=toneRange.value;applyColor('rgb('+v+','+v+','+v+')');
    });
    modeColor.addEventListener('click',function(){
      modeColor.classList.add('on');modeGray.classList.remove('on');
      colorCtrl.style.display='flex';grayCtrl.style.display='none';
      applyColor(colorPick.value);
    });

    // ---- Visibilidade ----
    document.querySelectorAll('.visChk').forEach(function(chk){
      chk.addEventListener('change',function(){
        Plotly.restyle(gd,{visible:this.checked},[parseInt(this.dataset.idx)]);
      });
    });

    // ---- LOCK ----
    gd.on('plotly_relayout',function(ev){
      if(lockApplying) return;
      if(locked&&savedCamera&&ev['scene.camera']){
        lockApplying=true;
        Plotly.relayout(gd,{'scene.camera':savedCamera}).then(function(){lockApplying=false;});
      } else if(!locked&&ev['scene.camera']){
        savedCamera=JSON.parse(JSON.stringify(ev['scene.camera']));
      }
    });

    document.getElementById('lockBtn').addEventListener('click',function(){
      locked=!locked;
      if(locked){
        savedCamera=captureCamera(gd)||savedCamera;
        this.textContent='🔒 LOCK';
        this.classList.add('on');
      } else {
        this.textContent='🔓 LOCK';
        this.classList.remove('on');
        Plotly.relayout(gd,{'scene.dragmode':'orbit'});
      }
    });
  }
  setTimeout(init,400);
})();
</script>"""
        _full_html = (
            "<!DOCTYPE html><html><head>"
            "<meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "</head><body>"
            + _ctrl_html.replace("__VIS__", _vis_html)
            + _plot_frag
            + "</body></html>"
        )
        _components.html(_full_html, height=1250, scrolling=False)
    else:
        st.info("Ative ao menos uma estrutura na barra lateral para visualizar.")

    st.subheader("Métricas em unidades nativas do STL — calibração de voxel pendente (não são mm³)")
    st.dataframe(
        [
            {
                "Estrutura": m["name"],
                "Volume (un. nativas)": round(m["volume_native"], 2),
                "Área (un. nativas)": round(m["area_native"], 2),
                "Faces (original)": m["n_faces"],
                "Faces (exibição)": m["n_faces_display"],
            }
            for m in _stl_ok
        ],
        use_container_width=True,
    )

    st.stop()

# ---------------------------------------------------------------------------
# MODO VOLUME (voxels) — comportamento original inalterado
# ---------------------------------------------------------------------------
if _uploads:
    try:
        _files = tuple((f.name, f.getvalue()) for f in _uploads)
        vol_data = _load_uploaded_vol(_files)
        st.sidebar.success(f"Volume carregado: {vol_data['source']}")
    except Exception as _e:  # noqa: BLE001
        st.sidebar.error(f"Falha ao carregar o arquivo: {_e}")
        st.sidebar.info("Usando o volume sintetico (phantom).")
        vol_data = _load_synthetic_vol()
else:
    st.sidebar.caption("Nenhum arquivo enviado - usando o volume sintetico (phantom).")
    vol_data = _load_synthetic_vol()

volume   = vol_data["volume"]
Z, Y, X  = volume.shape

if volume.size > _MAX_VOXELS:
    st.warning(
        f"⚠️ Volume grande: {volume.size:,} voxels "
        f"(limite recomendado: {_MAX_VOXELS:,}). "
        "O Streamlit Cloud tem ~1 GB de RAM — volumes maiores podem causar falha de memória. "
        "Considere enviar um recorte ou versão reamostrada do exame."
    )

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

# ---------------------------------------------------------------------------
# Requisito 5 — paleta de cores selecionável por camada (barra lateral)
# As cores escolhidas substituem as fixas em Segmentação, Render 3D e Métricas.
# ---------------------------------------------------------------------------
def _dc_hex(_rgb):
    return "#%02x%02x%02x" % (int(_rgb[0]), int(_rgb[1]), int(_rgb[2]))

def _dc_rgb(_h):
    _h = _h.lstrip("#")
    return (int(_h[0:2], 16), int(_h[2:4], 16), int(_h[4:6], 16))

st.sidebar.header("Cores das camadas")
_PALETTE = {}
for _tn in tissue_names:
    _PALETTE[_tn] = _dc_rgb(
        st.sidebar.color_picker(_tn, _dc_hex(TISSUE_PALETTE[_tn]), key=f"dc_col_{_tn}")
    )
TISSUE_PALETTE = _PALETTE

tab_3d, tab_seg, tab_2d, tab_anat, tab_met = st.tabs(["🫙 Render 3D", "🔍 Segmentação", "📐 Triplanar", "🦷 Anatomia", "📊 Métricas & Export"])

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

    _modo_transp = st.selectbox(
        "Modo de transparência",
        ["Personalizado", "Contorno (casca translúcida)", "Externo transparente / interno opaco", "Raio-X (tudo translúcido)", "Sólido (tudo opaco)"],
        help="Deixe camadas translúcidas para enxergar as áreas internas captadas pela microtomografia. 'Contorno' exibe a superfície externa como casca quase invisível, mantendo as estruturas internas sólidas.",
        key="op3d_modo",
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

    # Camada mais externa = maior bounding box entre as camadas presentes nos masks.
    # Funciona para phantom e para micro-CT real (independente do nome ou índice).
    _outer_name = render_tissue_names[0] if render_tissue_names else None
    _best_bb = -1
    for _tn in render_tissue_names:
        _m = masks.get(_tn)
        if _m is None or not _m.any():
            continue
        _nz = np.nonzero(_m)
        _bb = int(np.prod([int(_v.max() - _v.min() + 1) for _v in _nz]))
        if _bb > _best_bb:
            _best_bb, _outer_name = _bb, _tn

    if _modo_transp != "Personalizado":
        _N = len(render_tissue_names)
        def _preset_op(i, n):
            if _modo_transp == "Contorno (casca translúcida)":
                # camada com maior bounding box = mais externa → casca; demais → sólidas
                return 0.07 if n == _outer_name else 1.0
            if _modo_transp == "Raio-X (tudo translúcido)":
                return 0.30
            if _modo_transp == "Sólido (tudo opaco)":
                return 1.0
            # externo transparente -> interno opaco: opacidade cresce com a profundidade/densidade
            return round(0.12 + 0.88 * (i / (_N - 1) if _N > 1 else 1.0), 2)
        opacities = {n: _preset_op(i, n) for i, n in enumerate(render_tissue_names)}
        st.caption(
            f"Opacidades definidas pelo modo selecionado — os sliders acima ficam como referência. "
            f"{'Camada externa detectada: ' + (_outer_name or '—') if _modo_transp == 'Contorno (casca translúcida)' else ''}"
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
        meshes_3d = _build_meshes_cached(masks, vol_data["spacing"], ("Fundo",))

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
# Aba — Anatomia (Requisito 6): externo / cavidade / canal / coroa / raiz
# ---------------------------------------------------------------------------
with tab_anat:
    st.markdown(
        "**Volumes anatômicos** — morfologia 3D sobre os voxels brutos (Princípio 1): "
        "envelope externo, cavidade interna (câmara + canais) e canal radicular; além de coroa e raiz."
    )
    _ac1, _ac2 = st.columns(2)
    with _ac1:
        _auto_cerv = st.checkbox("Plano cervical automático (pescoço)", value=True, key="an_autocerv")
    with _ac2:
        _crown_hi = st.checkbox("Coroa no topo do eixo (Z alto)", value=True, key="an_crownhi")
    _cerv_frac = None
    if not _auto_cerv:
        _cerv_frac = st.slider(
            "Plano cervical (fração do eixo do dente · 0 = ápice, 1 = topo)",
            0.0, 1.0, 0.55, 0.01, key="an_cervfrac",
        )
    with st.spinner("Calculando volumes anatômicos (morfologia 3D)…"):
        _anat = _compute_anatomy_cached(volume, vol_data["spacing"], _crown_hi, _cerv_frac)
    _r1 = st.columns(3)
    _r1[0].metric("Externo (total)", f"{_anat['externo_mm3']:.4f} mm³")
    _r1[1].metric("Cavidade interna", f"{_anat['cavidade_interna_mm3']:.4f} mm³")
    _r1[2].metric("Canal radicular", f"{_anat['canal_radicular_mm3']:.4f} mm³")
    _r2 = st.columns(3)
    _r2[0].metric("Coroa", f"{_anat['coroa_mm3']:.4f} mm³")
    _r2[1].metric("Raiz", f"{_anat['raiz_mm3']:.4f} mm³")
    _r2[2].metric("Sólido mineralizado", f"{_anat['solido_dente_mm3']:.4f} mm³")
    st.caption(
        f"Plano cervical na fatia {_anat['cervical_index']} (eixo {_anat['long_axis']}) · "
        f"limiar dente/ar (Otsu) = {_anat['air_thresh']} · "
        "Externo = Sólido + Cavidade; Coroa + Raiz = Externo. "
        "Métricas geométricas (nº de voxels × espaçamento³)."
    )

    with st.expander("📚 Referência anatômica — raízes e canais esperados (Req. 7)"):
        _teeth = references.all_teeth()
        _labels = [f"{fdi} — {nome}" for fdi, nome in _teeth]
        _sel = st.selectbox("Dente (notação FDI)", _labels, index=0, key="ref_tooth")
        _fdi = int(_sel.split(" — ")[0])
        _ref = references.get_reference(fdi=_fdi)
        _rc = st.columns(2)
        _rc[0].metric("Raízes (típico)", _ref["raizes"])
        _rc[1].metric("Canais (típico)", _ref["canais"])
        st.caption(
            _ref["notas"]
            + f"  ·  Canal radicular medido nesta aba: {_anat['canal_radicular_mm3']:.4f} mm³."
            + "  Fonte: " + _ref["fonte"]
        )
        if st.button("Atualizar referências (online)", key="ref_update"):
            try:
                references.update_from_url()
                st.success("Referências atualizadas da internet.")
                st.rerun()
            except Exception as _e:  # noqa: BLE001
                st.info(f"Base local em uso (online indisponível: {_e}).")


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
        meshes_met  = _build_meshes_cached(masks_met, vol_data["spacing"], ("Fundo",))
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
            _anat_pdf = compute_anatomy(volume, vol_data["spacing"])
            _ref_lbl = st.session_state.get("ref_tooth")
            _ref_pdf = None
            if _ref_lbl:
                try:
                    _ref_pdf = references.get_reference(fdi=int(str(_ref_lbl).split(" — ")[0]))
                except Exception:
                    _ref_pdf = None
            pdf_bytes = generate_pdf(
                vol_data=vol_data,
                thresholds={n: DEFAULT_THRESHOLDS[n] for n in tissue_names},
                volumes_mm3=volumes_mm3,
                areas_mm2=areas_mm2,
                distances=distances_for_report,
                anatomy=_anat_pdf,
                tooth_ref=_ref_pdf,
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
