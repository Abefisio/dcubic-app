"""
DCubic Image System Platform
Análise de volumes 3D micro-CT — USP/FOUSP — Pesquisa acadêmica
"""

import hashlib
import json
import os
import traceback as _tb
import streamlit as st
import numpy as np

try:
    import yaml
    import extra_streamlit_components as stx
except Exception as _e_top:
    st.error(f"**Erro de inicialização — contate o suporte:**\n```\n{_tb.format_exc()}\n```")
    st.stop()

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
from modules.viewer3d import build_all_meshes, create_plotly_3d, limpar_figura_3d
from modules.metrics import (
    compute_volumes, compute_surface_areas, compute_distance,
    mesh_to_stl_bytes, mesh_to_obj_bytes,
)
from modules.report import generate_pdf
from modules.anatomy import compute_anatomy
from modules import references
from modules.mesh_loader import load_meshes
from modules import slices as _slices

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
    ".block-container{padding-top:0rem!important;padding-left:1rem!important;padding-right:1rem!important;max-width:100%!important}"
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
def _load_stl_from_paths(path_mtime_pairs, decimate_target: int = 200_000):
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
    return load_meshes(_files, cache_keys=_cache_keys, decimate_target=decimate_target)


@st.cache_resource(show_spinner="Preparando cortes…")
def _trimesh_cached(caminho, mtime, n_faces_original, _malha_pv):
    """Malha trimesh carregada 1x por arquivo (chave: caminho + mtime)."""
    return _slices.carregar_trimesh(caminho, n_faces_original, _malha_pv)


@st.cache_data(show_spinner=False, max_entries=64)
def _corte_cached(chave_arquivos, visiveis, nome_eixo, pos_q, _malhas, _cores, _bbox):
    """PNG do corte. Chave: arquivos+mtime, estruturas visíveis, eixo e posição
    arredondada a 0,05 (pos_q = posição em passos de 0,05)."""
    ms = {n: m for n, m in _malhas.items() if n in visiveis}
    return _slices.gerar_corte(ms, _cores, nome_eixo, pos_q * _slices.PASSO_MM, _bbox,
                               _slices.px_por_mm_padrao(_bbox))


@st.cache_data(hash_funcs={np.ndarray: _arr_hash}, show_spinner=False)
def _build_meshes_cached(masks, spacing, exclude_tuple):
    """Malhas 3D (marching cubes) — re-calcula só quando masks ou spacing mudam."""
    return build_all_meshes(masks, spacing, exclude=set(exclude_tuple))


@st.cache_data(hash_funcs={np.ndarray: _arr_hash}, show_spinner=False)
def _compute_anatomy_cached(volume, spacing, crown_at_high, cervical_frac):
    """Volumes anatômicos — re-calcula só quando o volume ou parâmetros mudam."""
    return compute_anatomy(volume, spacing, crown_at_high=crown_at_high, cervical_frac=cervical_frac)


@st.cache_resource(show_spinner="Gerando interior…")
def _interior_cached(_mesh, chave, resolucao: int = 128):
    """Preenchimento interno (voxelização) — calcula 1x por malha, não a cada rerun.
    _mesh não é hasheado (PolyData); a chave identifica a malha."""
    from modules.mesh_fill import preencher_interior
    return preencher_interior(_mesh, resolucao=resolucao)



# ---------------------------------------------------------------------------
# MODO STL — ativado quando há pelo menos um .stl no upload OU quando o
# usuário carrega da pasta local. Caminho paralelo ao pipeline de volume.
# ---------------------------------------------------------------------------

# Caminho A: leitura da pasta local — só disponível quando o diretório padrão existe.
_LOCAL_DEFAULT = os.path.expanduser("~/Desktop/DCUBIC-SITE/STL")
_local_available = os.path.isdir(_LOCAL_DEFAULT)

if _local_available:
    with st.sidebar.expander("Configurações avançadas", expanded=False):
        _stl_folder = st.text_input(
            "Pasta com STL (leitura local)",
            placeholder="Caminho da pasta com arquivos .stl",
            key="stl_folder_path",
        )
        _load_folder_btn = st.button("Carregar STL da pasta", key="stl_load_folder")
else:
    _stl_folder = ""
    _load_folder_btn = False

# ---------------------------------------------------------------------------
# DENTES DE EXEMPLO — Drive (arquivo único) ou Drive (zip com múltiplas estruturas)
# ---------------------------------------------------------------------------
_DRIVE_SAMPLES = {
    "Esmalte": "1OmWWs6kaUc6bT3gD2jjHMFX41r1g_45P",
    "Dentina": "1_bbDyFS2QG9qL8xecflwTjuwlKVrjm7J",
    "Molar":   "1B9z0GMQzHxYegnGY69KLVuPs-U8m38gH",
}
_DRIVE_ZIP_SAMPLES = {
    "34-PRE":        "1PZ7QYy2xVxSPrzCGysI_jqA58W5YJBV8",
    "MOLAR-SUP":     "1uqU_6-O9MqrwWzavr74CJU_KQJIJWDV1",
    "Pré-molar-sup": "1nELLBu4B1sQuFPFK1yWpyM2ix_42DF35",
    "Incisivo":      "1he-TVm2aVnp3p6CT_JddtEj2rAySlX5g",
}
_SAMPLE_DIR = "/tmp/dcubic_samples"

st.sidebar.markdown("---")
st.sidebar.subheader("Dentes de exemplo")
_sample_sel = st.sidebar.selectbox(
    "Estrutura de exemplo",
    ["— selecione —"] + list(_DRIVE_SAMPLES.keys()) + list(_DRIVE_ZIP_SAMPLES.keys()),
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
    elif _sample_sel in _DRIVE_ZIP_SAMPLES:
        _fid_zip = _DRIVE_ZIP_SAMPLES[_sample_sel]
        _zip_dest = os.path.join(_SAMPLE_DIR, f"{_sample_sel}.zip")
        _pasta = os.path.join(_SAMPLE_DIR, _sample_sel)
        _erro_msg = ""
        try:
            import gdown, zipfile as _zf, glob as _glob_ex
            os.makedirs(_SAMPLE_DIR, exist_ok=True)
            with st.spinner("Baixando dente de exemplo…"):
                if not os.path.isfile(_zip_dest):
                    gdown.download(
                        f"https://drive.google.com/uc?id={_fid_zip}",
                        _zip_dest, quiet=True,
                    )
                if not os.path.isdir(_pasta) or not os.listdir(_pasta):
                    os.makedirs(_pasta, exist_ok=True)
                    with _zf.ZipFile(_zip_dest, "r") as _z:
                        _z.extractall(_pasta)
        except Exception as _e:
            _erro_msg = str(_e)
        if _erro_msg:
            st.sidebar.error(f"Erro ao baixar/extrair: {_erro_msg[:300]}")
        else:
            import glob as _glob_ex
            _stls = sorted(_glob_ex.glob(os.path.join(_pasta, "*.stl")))
            _stls += sorted(_glob_ex.glob(os.path.join(_pasta, "*.STL")))
            _validos = [p for p in _stls if _stl_valido(p)]
            # ponytail: 30 MB ceiling — arquivos maiores crasham o Cloud (1 GB RAM);
            # remova quando o ZIP do Drive for re-exportado com meshes menores.
            _grandes = [p for p in _validos if os.path.getsize(p) > 30 * 1024 * 1024]
            for _pg in _grandes:
                _mb = os.path.getsize(_pg) // 1024 // 1024
                st.sidebar.warning(
                    f"⚠️ '{os.path.basename(_pg)}' ({_mb} MB) é grande demais "
                    "para o Streamlit Cloud e foi ignorado. "
                    "Faça upload manual do STL se precisar desta estrutura."
                )
            _validos = [p for p in _validos if p not in _grandes]
            if not _validos:
                st.sidebar.warning(f"Nenhum STL válido encontrado em {_pasta}.")
            else:
                _existing = st.session_state.get("stl_paths", [])
                _novos = [p for p in _validos if p not in _existing]
                if _novos:
                    st.session_state["stl_paths"] = _existing + _novos
                st.rerun()
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
            _existing_paths = st.session_state.get("stl_paths", [])
            if _dest not in _existing_paths:
                st.session_state["stl_paths"] = _existing_paths + [_dest]
            st.rerun()

# Quando o botão for clicado: persiste apenas CAMINHOS em session_state.
# Bytes (~1,3 GB) não são guardados — seriam copiados a cada rerun.
if _load_folder_btn:
    import glob as _glob
    _folder_path = _stl_folder.strip() or _LOCAL_DEFAULT
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
            st.session_state.pop("_stl_selected", None)

if st.sidebar.button("Limpar STL", key="stl_clear"):
    st.session_state.pop("stl_paths", None)
    st.session_state.pop("_stl_selected", None)
    st.session_state.pop("_stl_last", None)
    st.rerun()

# Seletor de estruturas — unifica uploads e pasta na mesma lista
_stl_path_mtime_dedup = []

_opcoes = st.session_state.get("stl_paths", [])
if _opcoes:
    _sel_paths = st.sidebar.multiselect(
        "Estruturas a exibir",
        options=_opcoes,
        default=_opcoes,
        format_func=lambda p: os.path.splitext(os.path.basename(p))[0],
        key="_stl_selected",
    )
    _sel_tuple = tuple(sorted(_sel_paths))
    if _sel_tuple != st.session_state.get("_stl_last"):
        _load_stl_from_paths.clear()
        st.session_state["_stl_last"] = _sel_tuple
    _stl_path_mtime_dedup = [
        (_p, os.path.getmtime(_p)) for _p in _sel_paths if _p and os.path.isfile(_p)
    ]

_is_stl = bool(_stl_path_mtime_dedup)

_revelar_interior = st.sidebar.checkbox("Revelar interior", value=True, key="revelar_interior")

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
        _all_cached = all(
            os.path.isfile(os.path.splitext(_p)[0] + ".dcubic_cache.ply")
            and os.path.isfile(os.path.splitext(_p)[0] + ".dcubic_cache.json")
            for _p, _ in _stl_path_mtime_dedup
        )
        if _all_cached:
            _cb(100, "Carregado do cache")
        else:
            _cb(25, "Lendo e decimando STL…")
        _decimate_target = 200_000
        _mi_disk = _load_stl_from_paths(tuple(_stl_path_mtime_dedup), _decimate_target)
        if not _all_cached:
            _cb(100, "Pronto")

    _meshes_info = _mi_disk
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

    # Cores e opacidades por estrutura (match no nome, case-insensitive); fallback por índice.
    # Esmalte/Dentina/molar/raiz = translúcidos (casca externa); canal = opaco (camada interna).
    _STL_COLOR_MAP = {
        "esmalte": (230, 235, 240),
        "dentina": (170, 180, 190),
        "molar":   (170, 175, 185),
        "raiz":    (170, 175, 185),
        "canal":   (90,  70,  220),
    }
    _OPAC_MAP = {"esmalte": 0.15, "dentina": 0.22, "molar": 0.22, "raiz": 0.22}
    _PALETTE = [
        (230, 235, 240), (170, 180, 190), (170, 175, 185),
        (170, 200, 220), (220, 170, 200), (170, 220, 190),
    ]
    _meshes_dict = {}
    _tissue_colors_stl = {}
    _opac_dict = {}
    for _vi, _mi in enumerate(_stl_ok):
        _nl = _mi["name"].lower()
        _col = next((v for k, v in _STL_COLOR_MAP.items() if k in _nl), _PALETTE[_vi % len(_PALETTE)])
        _tissue_colors_stl[_mi["name"]] = _col
        _meshes_dict[_mi["name"]] = _mi["mesh"]
        _opac_dict[_mi["name"]] = _OPAC_MAP.get(next((k for k in _OPAC_MAP if k in _nl), ""), 1.0)

    # ── Aparência — controles que antes ficavam no painel JS sobre o 3D ──
    # Cada ajuste gera rerun, mas o fragmento pesado do Plotly vem do cache;
    # só um pequeno objeto JS (AP) muda e é aplicado no navegador.
    import time as _time
    _ss = st.session_state
    # Padrões via session_state (sem value= nos widgets); a reatribuição mantém o valor
    # do controle oculto ao alternar Cinza/Cor personalizada.
    for _k, _padrao in (("ap_opac", 100), ("ap_tom", 235), ("ap_cor", "#ebebeb")):
        _ss[_k] = _ss.get(_k, _padrao)
    # Padrão enquadra o dente inteiro, centralizado e com folga
    _CAM_PADRAO = {"eye": {"x": 1.6, "y": 1.6, "z": 1.3}, "up": {"x": 0, "y": 0, "z": 1},
                   "center": {"x": 0, "y": 0, "z": 0}}
    _VISTAS = {
        "Topo":        {"eye": {"x": 0, "y": 0, "z": 2.2}, "up": {"x": 0, "y": 1, "z": 0}},
        "Frente":      {"eye": {"x": 0, "y": -2.2, "z": 0}, "up": {"x": 0, "y": 0, "z": 1}},
        "Lado":        {"eye": {"x": 2.2, "y": 0, "z": 0}, "up": {"x": 0, "y": 0, "z": 1}},
        "Perspectiva": {"eye": {"x": 1.6, "y": 1.6, "z": 1.3}, "up": {"x": 0, "y": 0, "z": 1}},
    }

    def _ap_marca(_chave):
        # Como no painel antigo: o padrão por estrutura só é sobrescrito após o 1º ajuste.
        _ss[_chave] = True

    def _ap_vista():
        if _ss.get("ap_vista"):
            # nonce = instante em ms; o iframe aplica a câmera uma única vez por nonce
            _ss["_ap_cmd"] = {"n": int(_time.time() * 1000), "cam": _VISTAS[_ss["ap_vista"]]}

    def _ap_reset():
        _ss["_ap_cmd"] = {"n": int(_time.time() * 1000), "cam": _CAM_PADRAO}
        _ss["ap_lock"] = False
        _ss["ap_vista"] = None

    st.sidebar.markdown("---")
    st.sidebar.subheader("Aparência")
    st.sidebar.slider("Opacidade (%)", 0, 100, key="ap_opac",
                      on_change=_ap_marca, args=("ap_opac_on",))
    st.sidebar.toggle("🔒 Lock (travar câmera)", key="ap_lock")
    st.sidebar.radio("Cor", ["Cinza", "Cor personalizada"], horizontal=True, key="ap_cor_modo",
                     on_change=_ap_marca, args=("ap_cor_on",))
    if _ss.get("ap_cor_modo", "Cinza") == "Cinza":
        st.sidebar.slider("Tom (Escuro → Claro)", 0, 255, key="ap_tom",
                          on_change=_ap_marca, args=("ap_cor_on",))
    else:
        st.sidebar.color_picker("Cor personalizada", key="ap_cor",
                                on_change=_ap_marca, args=("ap_cor_on",))
    st.sidebar.radio("Vista", list(_VISTAS), index=None, horizontal=True, key="ap_vista",
                     on_change=_ap_vista)
    st.sidebar.button("🏠 Resetar vista", key="ap_reset", on_click=_ap_reset, width="stretch")

    # ── Botões de olho para visibilidade por estrutura ──
    st.sidebar.markdown("---")
    st.sidebar.subheader("Estruturas visíveis")
    for _mi in _stl_ok:
        _nome = _mi["name"]
        _vkey = f"visivel_{_nome}"
        if _vkey not in st.session_state:
            st.session_state[_vkey] = True
        _vis = st.session_state[_vkey]
        if st.sidebar.button(
            f"{'👁️' if _vis else '🚫'}  {_nome}",
            key=f"btn_visivel_{_nome}",
        ):
            st.session_state[_vkey] = not _vis
            st.rerun()
    _visible_dict = {
        _mi["name"]: st.session_state.get(f"visivel_{_mi['name']}", True)
        for _mi in _stl_ok
    }

    # ── Abas: 3D | Cortes. A aba Cortes é executada ANTES do 3D para que o plano
    #    de corte (opcional) já use os valores atuais dos sliders. ──
    _tab_3d, _tab_cortes = st.tabs(["3D", "Cortes"])
    _plano_3d = None   # (eixo xyz do Plotly 0/1/2, valor) quando "Mostrar plano no 3D" está ligado
    with _tab_cortes:
        _por_nome = {os.path.splitext(os.path.basename(_p))[0]: (_p, _mt)
                     for _p, _mt in _stl_path_mtime_dedup}
        _tm = {}
        for _mi in _stl_ok:
            if _mi["name"] in _por_nome:
                _pp, _mt = _por_nome[_mi["name"]]
                _tm[_mi["name"]] = _trimesh_cached(_pp, _mt, _mi["n_faces"], _mi["mesh"])
        _vis_tm = tuple(n for n in _tm if _visible_dict.get(n, True))
        if not _vis_tm:
            st.info("Ative ao menos uma estrutura na barra lateral para ver os cortes.")
        else:
            _bb = _slices.bbox_combinado(_tm)
            _ext_max = float(max(_bb[1] - _bb[0]))
            _passo = _slices.PASSO_MM if _ext_max < 50 else 1.0
            _chave_arq = tuple(_stl_path_mtime_dedup)
            _sig = "_".join(f"{v:.1f}" for v in _bb.ravel())
            _cc1, _cc2 = st.columns([1, 2])
            _mostrar_plano = _cc1.checkbox("Mostrar plano no 3D", key="cortes_plano")
            _eixo_plano = _cc2.radio("Plano no 3D", list(_slices.EIXOS), horizontal=True,
                                     key="cortes_plano_eixo", label_visibility="collapsed")
            _cols = st.columns(3)
            for _col, _ne in zip(_cols, _slices.EIXOS):
                _ax = _slices.EIXOS[_ne][0]
                _lo, _hi = float(_bb[0][_ax]), float(_bb[1][_ax])
                with _col:
                    _pos = st.slider(f"{_ne} — posição ({_slices.UNIDADE})", _lo, _hi,
                                     (_lo + _hi) / 2, step=_passo, key=f"corte_{_ne}_{_sig}")
                    _pq = int(round(_pos / _slices.PASSO_MM))
                    _png, _inf = _corte_cached(_chave_arq, _vis_tm, _ne, _pq, _tm,
                                               {n: _tissue_colors_stl[n] for n in _tm}, _bb)
                    if _png is None:
                        st.warning("Fora do dente nesta posição")
                    else:
                        st.image(_png, width="stretch")
                if _mostrar_plano and _ne == _eixo_plano:
                    _plano_3d = (_ax, _pq * _slices.PASSO_MM)
            st.caption("Cortes calculados direto do STL bruto, sem tratamento manual. "
                       f"Escala em {_slices.UNIDADE} (unidades nativas do STL; calibração pendente).")

    with _tab_3d:
        st.subheader("Render 3D — malhas STL")
        if _meshes_dict:
            _meshes_filtrado = {n: m for n, m in _meshes_dict.items() if _visible_dict.get(n, True)}

            @st.cache_data(show_spinner="Montando o 3D…", max_entries=8)
            def _fragmento_3d_cached(chave, _meshes_filtrado, _tissue_colors_stl, _opac_dict,
                                     _meshes_dict, _stl_ok, _revelar_interior, _plano):
                """HTML pesado do Plotly. chave = arquivos+mtime+visibilidade+revelar_interior;
                mudar só opacidade/cor/vista/lock NÃO regenera este fragmento."""
                _fig_stl = create_plotly_3d(
                    _meshes_filtrado, _tissue_colors_stl, opacities=_opac_dict,
                    # Plano ligado: recorta o modelo no corte atual. _plano usa eixos do Plotly
                    # (x,y,z); clip_plane usa colunas de mesh.points (x=col2, y=col1, z=col0).
                    clip_plane=({"axis": 2 - _plano[0], "value": _plano[1]} if _plano else None),
                    bbox_meshes=_meshes_dict,
                )

                if _revelar_interior and _stl_ok:
                    try:
                        _casca_mi = next(
                            (m for m in _stl_ok if any(k in m["name"].lower() for k in ("molar", "raiz"))),
                            max(_stl_ok, key=lambda m: m["mesh"].n_cells),
                        )
                        _casca_pv = _casca_mi["mesh"]
                        _interior = _interior_cached(
                            _casca_pv,
                            (_casca_mi["name"], _casca_pv.n_points, _casca_pv.n_cells, tuple(_casca_pv.bounds)),
                            128,
                        )
                        if _interior is not None:
                            import plotly.graph_objects as _go
                            _verts_i = _interior.points
                            _faces_i = _interior.faces.reshape(-1, 4)[:, 1:]
                            if _plano is not None:  # mesmo recorte do clip_plane
                                _faces_i = _faces_i[_verts_i[:, 2 - _plano[0]][_faces_i].max(axis=1) <= _plano[1]]
                            _fig_stl.add_trace(_go.Mesh3d(
                                x=_verts_i[:, 2], y=_verts_i[:, 1], z=_verts_i[:, 0],
                                i=_faces_i[:, 0], j=_faces_i[:, 1], k=_faces_i[:, 2],
                                color="#7B2FBE", opacity=1.0,
                                name="Interior",
                                showlegend=False,
                                hoverinfo="skip",
                            ))
                    except ValueError as _ve:
                        st.warning("Não foi possível gerar o interior: " + str(_ve))
                    except Exception as _ie:
                        st.warning("Não foi possível gerar o interior: " + str(_ie))

                if _plano is not None:
                    # Plano de corte semitransparente (mesma convenção de eixos do viewer3d: x,y,z do Plotly)
                    import plotly.graph_objects as _gop
                    _pp = np.concatenate([m.points[:, [2, 1, 0]] for m in _meshes_dict.values() if m is not None])
                    _bbp = np.array([_pp.min(axis=0), _pp.max(axis=0)])  # (x,y,z) do Plotly
                    _ea, _va = _plano
                    _o = [i for i in range(3) if i != _ea]
                    _quad = np.zeros((4, 3))
                    for _k, (_a, _b) in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
                        _quad[_k, _ea] = _va
                        _quad[_k, _o[0]] = _bbp[_a, _o[0]]
                        _quad[_k, _o[1]] = _bbp[_b, _o[1]]
                    _fig_stl.add_trace(_gop.Mesh3d(
                        x=_quad[:, 0], y=_quad[:, 1], z=_quad[:, 2],
                        i=[0, 0], j=[1, 2], k=[2, 3],
                        color="#00c8ff", opacity=0.3, name="Plano de corte",
                        showlegend=False, hoverinfo="skip", flatshading=True,
                    ))

                _fig_stl.update_layout(
                    uirevision="constant",  # preserva câmera entre reruns do Streamlit
                    modebar=dict(orientation="v"),
                    legend=dict(x=0.01, y=0.99, xanchor="left"),  # libera o canto direito para o ícone de câmera
                    autosize=True, height=None,  # sem altura/largura fixas (anula o 520 do viewer3d): ocupa 100% da div
                    margin=dict(l=0, r=0, t=0, b=0),
                    scene=dict(
                        dragmode="orbit",
                        camera=_CAM_PADRAO,
                        xaxis=dict(title=dict(font=dict(size=18)), tickfont=dict(size=15)),
                        yaxis=dict(title=dict(font=dict(size=18)), tickfont=dict(size=15)),
                        zaxis=dict(title=dict(font=dict(size=18)), tickfont=dict(size=15)),
                    ),
                )
                limpar_figura_3d(_fig_stl)
                return _fig_stl.to_html(
                    include_plotlyjs="cdn", full_html=False, div_id="stl_plot",
                    config={
                        "displayModeBar": True, "displaylogo": False,
                        "modeBarButtons": [["toImage"]],  # só o ícone de câmera (Baixar imagem)
                        "toImageButtonOptions": {"format": "png", "width": 1600,
                                                 "height": 1200, "filename": "modelo_stl"},
                    },
                )

            _chave_3d = (
                tuple(_stl_path_mtime_dedup),
                tuple(sorted(_visible_dict.items())),
                bool(_revelar_interior),
                _plano_3d,  # parâmetros do plano de corte entram na chave do fragmento
            )
            _plot_frag = _fragmento_3d_cached(
                _chave_3d, _meshes_filtrado, _tissue_colors_stl, _opac_dict,
                _meshes_dict, _stl_ok, _revelar_interior, _plano_3d,
            )

            # Valores da seção "Aparência" -> pequeno objeto JS injetado ANTES do fragmento.
            if _ss.get("ap_cor_on"):
                _ap_cor = (_ss.get("ap_cor", "#ebebeb") if _ss.get("ap_cor_modo") == "Cor personalizada"
                           else "rgb({0},{0},{0})".format(_ss.get("ap_tom", 235)))
            else:
                _ap_cor = None
            _ap = {
                "opac": _ss.get("ap_opac", 100) if _ss.get("ap_opac_on") else None,
                "cor": _ap_cor,
                "lock": bool(_ss.get("ap_lock")),
                "cmd": _ss.get("_ap_cmd"),
                "cam_padrao": _CAM_PADRAO,
                # Uma chave de câmera por dente (hash dos nomes dos arquivos carregados):
                # dente novo não herda a câmera de outro.
                "kcam": "dcubic_stl_camera_" + hashlib.md5("|".join(sorted(
                    os.path.basename(_p) for _p in _ss.get("stl_paths", []))).encode()).hexdigest()[:12],
            }
            import streamlit.components.v1 as _components
            _ctrl_html = """
<style>
html,body{margin:0;padding:0;overflow:hidden;height:100%;background:#0f0f0f;color:#eee;font-family:sans-serif}
#stl_plot{width:100%;height:100%}
</style>
<script>
(function(){
  var AP=__AP__;
  var K=AP.kcam, KN='dcubic_stl_cmd_n';
  var savedCamera=null, applying=false;
  function ler(k){try{return localStorage.getItem(k);}catch(e){return null;}}
  function gravar(k,v){try{localStorage.setItem(k,v);}catch(e){}}
  function apagar(k){try{localStorage.removeItem(k);}catch(e){}}
  apagar('dcubic_stl_camera');  // chave global antiga (podia guardar câmera fora da cena)

  // Altura do 3D = 85% da janela do navegador (mínimo 600 px); o vh é resolvido na página-mãe.
  try{ if(window.frameElement) window.frameElement.style.height='max(600px, 85vh)'; }catch(e){}

  // Câmera utilizável? center em [-1,1], distância eye–center em [0.3, 6], sem NaN.
  function camValida(c){
    if(!c||!c.eye) return false;
    var ce=c.center||{x:0,y:0,z:0}, e=c.eye, u=c.up||{x:0,y:0,z:1};
    var v=[ce.x,ce.y,ce.z,e.x,e.y,e.z,u.x,u.y,u.z];
    for(var i=0;i<v.length;i++) if(typeof v[i]!=='number'||!isFinite(v[i])) return false;
    if(Math.abs(ce.x)>1||Math.abs(ce.y)>1||Math.abs(ce.z)>1) return false;
    var d=Math.sqrt(Math.pow(e.x-ce.x,2)+Math.pow(e.y-ce.y,2)+Math.pow(e.z-ce.z,2));
    return d>=0.3&&d<=6;
  }

  function init(){
    var gd=document.getElementById('stl_plot');
    if(!gd||!gd._fullLayout){setTimeout(init,100);return;}

    // ---- Opacidade / Cor (aplicadas a todas as malhas, como no painel antigo) ----
    var idx=[];gd.data.forEach(function(t,i){if(t.name!=='Plano de corte')idx.push(i);});
    if(AP.opac!==null) Plotly.restyle(gd,{opacity:AP.opac/100,visible:AP.opac>0},idx);
    if(AP.cor!==null) Plotly.restyle(gd,{color:AP.cor},idx);

    // ---- Câmera: comando novo (Vista/Resetar, por nonce) ou a salva no localStorage ----
    var cam=null;
    if(AP.cmd&&String(AP.cmd.n)!==ler(KN)){
      cam=AP.cmd.cam; gravar(KN,String(AP.cmd.n)); gravar(K,JSON.stringify(cam));
    } else {
      try{var s=ler(K); if(s) cam=JSON.parse(s);}catch(e){cam=null;}
      if(cam&&!camValida(cam)){cam=null; apagar(K);}  // corrompida: descarta e apaga
    }
    if(!cam) cam=AP.cam_padrao;
    savedCamera=cam;
    var lay={'scene.dragmode':AP.lock?false:'orbit','scene.camera':cam};
    applying=true;
    Plotly.relayout(gd,lay).then(function(){applying=false; Plotly.Plots.resize(gd);});

    // Canvas acompanha o tamanho da div (iframe redimensionado junto com a janela)
    window.addEventListener('resize',function(){Plotly.Plots.resize(gd);});

    // ---- LOCK: câmera fixa; sem lock, cada movimento é salvo no localStorage ----
    gd.on('plotly_relayout',function(ev){
      if(applying||!ev['scene.camera']) return;
      if(AP.lock&&savedCamera){
        applying=true;
        Plotly.relayout(gd,{'scene.camera':savedCamera}).then(function(){applying=false;});
      } else if(!AP.lock&&camValida(ev['scene.camera'])){
        savedCamera=JSON.parse(JSON.stringify(ev['scene.camera']));
        gravar(K,JSON.stringify(savedCamera));
      }
    });
  }
  setTimeout(init,100);
})();
</script>""".replace("__AP__", json.dumps(_ap))
            _full_html = (
                "<!DOCTYPE html><html><head>"
                "<meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "</head><body>"
                + _ctrl_html
                + _plot_frag
                + "</body></html>"
            )
            # 800 px é só o valor inicial: o script ajusta o iframe para max(600px, 85vh).
            _components.html(_full_html, height=800, scrolling=False)
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
    limpar_figura_3d(fig_3d)
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
