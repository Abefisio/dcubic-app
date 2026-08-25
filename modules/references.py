"""
DCubic Image System Platform — referências de anatomia dental (Requisito 7).

Base CURADA (notação FDI) de nº de raízes e canais típicos por dente, para
contextualizar a análise 3D (ex.: comparar o canal medido com o esperado).
Fonte: literatura endodôntica clássica (nº de raízes/canais; classificação de
canais de Vertucci). Valores são TÍPICOS — variações anatômicas são comuns.

- Ao importar, tenta carregar `assets/anatomy_refs.json` (se existir) para permitir
  atualização/curadoria externa; caso contrário usa DEFAULT_DATA embutido.
- `update_from_url(url)` baixa um JSON da internet (ex.: raw do GitHub do projeto),
  valida, grava em `assets/anatomy_refs.json` e retorna os dados — com fallback seguro.
"""
from __future__ import annotations

import os
import json
import urllib.request

# URL padrão (o próprio repositório do projeto) — pode ser sobrescrita.
DEFAULT_REF_URL = "https://raw.githubusercontent.com/Abefisio/dcubic-app/main/assets/anatomy_refs.json"

_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
_LOCAL_JSON = os.path.normpath(os.path.join(_ASSETS, "anatomy_refs.json"))

# Grupos por tipo de dente (superior/inferior).
GROUPS = {
    "ic_sup": {"nome": "Incisivo central superior", "raizes": "1", "canais": "1 (Vertucci I)",
               "notas": "Raiz única, cônica; canal amplo."},
    "il_sup": {"nome": "Incisivo lateral superior", "raizes": "1", "canais": "1 (Vertucci I)",
               "notas": "Raiz única; possível curvatura distal/palatina."},
    "c_sup":  {"nome": "Canino superior", "raizes": "1", "canais": "1 (Vertucci I)",
               "notas": "Raiz mais longa da arcada; canal único amplo."},
    "pm1_sup":{"nome": "1º pré-molar superior", "raizes": "2 (freq.)", "canais": "2 (vestibular + palatino)",
               "notas": "Comumente 2 raízes/2 canais; pode ser 1 raiz."},
    "pm2_sup":{"nome": "2º pré-molar superior", "raizes": "1", "canais": "1–2",
               "notas": "Geralmente 1 raiz; canais 1 ou 2 (Vertucci II/IV)."},
    "m1_sup": {"nome": "1º molar superior", "raizes": "3 (MV, DV, palatina)", "canais": "3–4 (MV2 frequente)",
               "notas": "Procurar o 2º canal mesiovestibular (MV2)."},
    "m2_sup": {"nome": "2º molar superior", "raizes": "3", "canais": "3 (variável)",
               "notas": "Raízes podem ser fusionadas; MV2 menos frequente."},
    "m3_sup": {"nome": "3º molar superior", "raizes": "1–3 (variável)", "canais": "variável",
               "notas": "Anatomia muito variável."},
    "ic_inf": {"nome": "Incisivo central inferior", "raizes": "1", "canais": "1 (às vezes 2)",
               "notas": "Pode ter 2 canais (V/L) — Vertucci III."},
    "il_inf": {"nome": "Incisivo lateral inferior", "raizes": "1", "canais": "1 (às vezes 2)",
               "notas": "Semelhante ao central; verificar 2º canal."},
    "c_inf":  {"nome": "Canino inferior", "raizes": "1", "canais": "1 (raramente 2)",
               "notas": "Raiz longa; raramente bifurca."},
    "pm1_inf":{"nome": "1º pré-molar inferior", "raizes": "1", "canais": "1 (às vezes 2)",
               "notas": "Pode ter 2 canais; anatomia enganosa."},
    "pm2_inf":{"nome": "2º pré-molar inferior", "raizes": "1", "canais": "1",
               "notas": "Geralmente 1 canal."},
    "m1_inf": {"nome": "1º molar inferior", "raizes": "2 (mesial, distal)", "canais": "3–4",
               "notas": "Mesial: 2 canais (MV/ML); distal: 1–2. Ver canal médio-mesial."},
    "m2_inf": {"nome": "2º molar inferior", "raizes": "2", "canais": "3 (variável)",
               "notas": "Raízes podem fundir; canal em 'C' possível."},
    "m3_inf": {"nome": "3º molar inferior", "raizes": "1–2 (variável)", "canais": "variável",
               "notas": "Anatomia muito variável."},
}

# Posição na arcada (dígito 2 do FDI) -> grupo, por quadrante
_POS_SUP = {1: "ic_sup", 2: "il_sup", 3: "c_sup", 4: "pm1_sup", 5: "pm2_sup", 6: "m1_sup", 7: "m2_sup", 8: "m3_sup"}
_POS_INF = {1: "ic_inf", 2: "il_inf", 3: "c_inf", 4: "pm1_inf", 5: "pm2_inf", 6: "m1_inf", 7: "m2_inf", 8: "m3_inf"}

def _build_fdi():
    m = {}
    for quad in (1, 2, 3, 4):
        table = _POS_SUP if quad in (1, 2) else _POS_INF
        for pos, grp in table.items():
            m[quad * 10 + pos] = grp
    return m

FDI_TO_GROUP = _build_fdi()

DEFAULT_DATA = {
    "fonte": "Literatura endodôntica (nº de raízes/canais; Vertucci). Valores típicos.",
    "grupos": GROUPS,
    "fdi": {str(k): v for k, v in FDI_TO_GROUP.items()},
}


def _load():
    try:
        with open(_LOCAL_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "grupos" in data and "fdi" in data:
            return data
    except Exception:
        pass
    return DEFAULT_DATA


_DATA = _load()


def all_teeth():
    """Lista [(fdi:int, nome:str)] ordenada por FDI."""
    fdi = _DATA["fdi"]; grupos = _DATA["grupos"]
    out = []
    for k in sorted(fdi, key=lambda s: int(s)):
        grp = fdi[k]
        out.append((int(k), grupos.get(grp, {}).get("nome", grp)))
    return out


def get_reference(fdi=None, group=None):
    grupos = _DATA["grupos"]
    if group is None and fdi is not None:
        group = _DATA["fdi"].get(str(int(fdi)))
    ref = dict(grupos.get(group, {})) if group else {}
    ref.setdefault("nome", "—"); ref.setdefault("raizes", "—")
    ref.setdefault("canais", "—"); ref.setdefault("notas", "")
    ref["fonte"] = _DATA.get("fonte", "")
    return ref


def update_from_url(url: str = DEFAULT_REF_URL, timeout: int = 8):
    """Baixa referências da internet, valida e grava localmente. Levanta em erro."""
    req = urllib.request.Request(url, headers={"User-Agent": "DCubic/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    if not (isinstance(data, dict) and "grupos" in data and "fdi" in data):
        raise ValueError("JSON de referências inválido (faltam 'grupos'/'fdi').")
    os.makedirs(_ASSETS, exist_ok=True)
    with open(_LOCAL_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    global _DATA
    _DATA = data
    return data
