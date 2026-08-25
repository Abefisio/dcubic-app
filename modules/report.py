"""
DCubic Image System Platform — geração de relatório PDF (reportlab).

Princípio 1: as métricas no relatório são as calculadas sobre voxels brutos,
recebidas como parâmetro — este módulo apenas formata e serializa.
"""

from __future__ import annotations
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _table(data: list[list], col_widths: list[float]) -> Table:
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#1a3a5c")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4f8")]),
        ("GRID",          (0, 0), (-1, -1), 0.5, colors.grey),
        ("PADDING",       (0, 0), (-1, -1), 6),
    ]))
    return t


def generate_pdf(
    vol_data: dict,
    thresholds: dict[str, tuple[float, float]],
    volumes_mm3: dict[str, float],
    areas_mm2: dict[str, float],
    distances: list[dict] | None = None,
) -> bytes:
    """
    Gera relatório PDF em memória e retorna os bytes prontos para download.

    Args:
        vol_data:     dict retornado por load_volume()
        thresholds:   thresholds aplicados na segmentação
        volumes_mm3:  {tecido: volume_mm3} — calculado sobre voxels brutos
        areas_mm2:    {tecido: area_mm2}   — calculado sobre malha marching cubes
        distances:    [{"label": str, "mm": float}, ...] (opcional)
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()

    title_s = ParagraphStyle("T", parent=styles["Title"],   fontSize=16, spaceAfter=4)
    sub_s   = ParagraphStyle("S", parent=styles["Normal"],  fontSize=9,  textColor=colors.grey)
    h2_s    = ParagraphStyle("H", parent=styles["Heading2"], fontSize=12, spaceBefore=12, spaceAfter=4)
    note_s  = ParagraphStyle("N", parent=styles["Normal"],  fontSize=8,  textColor=colors.grey, spaceAfter=6)
    disc_s  = ParagraphStyle("D", parent=styles["Normal"],  fontSize=7,  textColor=colors.grey)

    story = []

    story.append(Paragraph("DCubic Image System Platform", title_s))
    story.append(Paragraph(
        "Análise quantitativa de volume 3D micro-CT · USP/FOUSP · Pesquisa acadêmica", sub_s
    ))
    story.append(Paragraph(
        f"Relatório gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", sub_s
    ))
    story.append(HRFlowable(width="100%", spaceAfter=12))

    story.append(Paragraph("Dataset", h2_s))
    sp = vol_data["spacing"]
    sh = vol_data["shape"]
    story.append(_table([
        ["Parâmetro", "Valor"],
        ["Fonte", vol_data["source"]],
        ["Shape (Z × Y × X)", f"{sh[0]} × {sh[1]} × {sh[2]} voxels"],
        ["Espaçamento (z, y, x)", f"{sp[0]:.4f} × {sp[1]:.4f} × {sp[2]:.4f} mm/voxel"],
        ["FOV total", f"{sh[0]*sp[0]:.3f} × {sh[1]*sp[1]:.3f} × {sh[2]*sp[2]:.3f} mm"],
        ["Tipo original", vol_data["dtype_original"]],
    ], [6 * cm, 11 * cm]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Thresholds de segmentação aplicados", h2_s))
    story.append(_table(
        [["Tecido", "Limiar inferior", "Limiar superior"]] +
        [[name, f"{lo:.3f}", f"{hi:.3f}"] for name, (lo, hi) in thresholds.items()],
        [8 * cm, 4.25 * cm, 4.75 * cm],
    ))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Métricas quantitativas por tecido", h2_s))
    story.append(Paragraph(
        "Volume calculado a partir da contagem de voxels × volume unitário do voxel (Princípio 1). "
        "Área de superfície calculada sobre a malha gerada por marching cubes a partir dos voxels brutos.",
        note_s,
    ))
    met_rows = [["Tecido", "Volume (mm³)", "Área de superfície (mm²)"]]
    for name in volumes_mm3:
        met_rows.append([
            name,
            f"{volumes_mm3[name]:.4f}",
            f"{areas_mm2.get(name, 0.0):.4f}",
        ])
    t3 = _table(met_rows, [8 * cm, 4.25 * cm, 4.75 * cm])
    t3.setStyle(TableStyle([
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
    ]))
    story.append(t3)
    story.append(Spacer(1, 10))

    if distances:
        story.append(Paragraph("Distâncias medidas", h2_s))
        dist_rows = [["Rótulo", "Distância (mm)"]] + [
            [d["label"], f"{d['mm']:.4f}"] for d in distances
        ]
        story.append(_table(dist_rows, [12 * cm, 5 * cm]))
        story.append(Spacer(1, 10))

    story.append(HRFlowable(width="100%", spaceBefore=12))
    story.append(Paragraph(
        "Princípio 1 (inviolável): toda métrica numérica é calculada a partir da "
        "matriz de voxels original, nunca da imagem renderizada ou da malha 3D. "
        "A geração de malha (marching cubes) serve exclusivamente à visualização "
        "e exportação geométrica.",
        disc_s,
    ))

    doc.build(story)
    return buf.getvalue()
