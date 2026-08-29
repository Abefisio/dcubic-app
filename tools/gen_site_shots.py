"""Gera os 4 screenshots do site DCubic a partir dos STL reais."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from modules.mesh_loader import load_mesh
from modules.viewer3d import create_plotly_3d

MICROTOMO = os.path.expanduser("~/Desktop/DCUBIC-SITE/MICROTOMO")
SHOTS_DIR = os.path.expanduser("~/Desktop/DCUBIC-SITE/screenshots")

STL_FILES = {
    "molar":    "molar_sup__raiz_voi_.stl",
    "Dentina":  "Dentina.stl",
    "Esmalte":  "Esmalte.stl",
}

BG = "#0e1117"
GRAY_LIGHT = (220, 220, 220)
GRAY_MED   = (180, 180, 180)

SHOTS = [
    dict(
        out="screen_render3d.png",
        name="molar",
        color=GRAY_MED,
        opacity=0.4,
        camera=dict(eye=dict(x=1.5, y=1.5, z=1.2)),
        desc="molar translúcido, perspectiva",
    ),
    dict(
        out="screen_triplanar.png",
        name="Dentina",
        color=GRAY_LIGHT,
        opacity=1.0,
        camera=dict(eye=dict(x=0, y=-2.2, z=0)),
        desc="Dentina sólida, vista frontal",
    ),
    dict(
        out="screen_segmentacao.png",
        name="Esmalte",
        color=GRAY_LIGHT,
        opacity=1.0,
        camera=dict(eye=dict(x=2.2, y=0, z=0)),
        desc="Esmalte sólido, vista lateral",
    ),
    dict(
        out="screen_metricas.png",
        name="molar",
        color=GRAY_MED,
        opacity=1.0,
        camera=dict(eye=dict(x=0, y=0, z=2.2), up=dict(x=0, y=1, z=0)),
        desc="molar sólido, vista de topo",
    ),
]


def load(name):
    path = os.path.join(MICROTOMO, STL_FILES[name])
    cache_key = os.path.splitext(path)[0]
    with open(path, "rb") as fh:
        data = fh.read()
    result = load_mesh(data, STL_FILES[name], cache_key=cache_key)
    if "error" in result:
        raise RuntimeError(f"Erro ao carregar {name}: {result['error']}")
    return result["mesh"]


def main():
    print("Carregando malhas (usa cache se disponível)…")
    meshes = {}
    for key in set(s["name"] for s in SHOTS):
        print(f"  {key}…", end=" ", flush=True)
        meshes[key] = load(key)
        print("OK")

    os.makedirs(SHOTS_DIR, exist_ok=True)

    for shot in SHOTS:
        name = shot["name"]
        mesh = meshes[name]
        color = shot["color"]
        opacity = shot["opacity"]
        camera = shot["camera"]
        out_path = os.path.join(SHOTS_DIR, shot["out"])

        fig = create_plotly_3d(
            {name: mesh},
            {name: color},
            opacities={name: opacity},
            clip_z_mm=None,
        )
        fig.update_layout(
            width=1200,
            height=800,
            paper_bgcolor=BG,
            margin=dict(l=0, r=0, t=0, b=0),
            scene=dict(
                bgcolor=BG,
                camera=camera,
                aspectmode="data",
                xaxis=dict(showticklabels=False, title=""),
                yaxis=dict(showticklabels=False, title=""),
                zaxis=dict(showticklabels=False, title=""),
            ),
            showlegend=False,
        )
        fig.write_image(out_path, scale=1)
        size_kb = os.path.getsize(out_path) // 1024
        print(f"  {out_path}  [{size_kb} KB]  — {shot['desc']}")

    print("\nConcluído.")


if __name__ == "__main__":
    main()
