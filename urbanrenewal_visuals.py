"""Lightweight schematic SVG for indoor floor and outdoor ground area."""

from html import escape
from math import isfinite, sqrt

PALETTE = {
    "办公与工作室": "#72978E", "展览": "#C4A47D", "零售": "#B88977",
    "活动与演艺": "#8590B3", "广场": "#A4A4AD", "绿地": "#86A578",
    "保留建筑": "#7A998B", "新建建筑": "#A5B9B0", "室外地面": "#A5AF88",
}
OTHER_COLORS = ("#839AB0", "#A888AC", "#9584AB", "#91A192", "#B8A47E", "#95A5B3")


def function_color(name):
    return PALETTE.get(name, OTHER_COLORS[sum(map(ord, name)) % len(OTHER_COLORS)])


def _shade(color, factor):
    parts = [int(color[index:index + 2], 16) * factor for index in (1, 3, 5)]
    return "#" + "".join(f"{int(max(0, min(value, 255))):02x}" for value in parts)


def _polygon(points, color, stroke="#f2f4ef"):
    coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return f'<polygon points="{coords}" fill="{color}" stroke="{stroke}" stroke-width="1.1"/>'


def _group(units, space):
    areas = {}
    for unit in units:
        name, value = unit.get("function"), unit.get("area_sqm")
        if (unit.get("space_type") != space or not isinstance(name, str) or not name
                or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0):
            continue
        areas[name] = areas.get(name, 0) + value
    return sorted(areas.items(), key=lambda pair: (-pair[1], pair[0]))


def area_schematic(units, *, stacked=False):
    """Return one SVG with separate scale and denominators for indoor/outdoor panels."""
    panels = [
        ("室内建筑面积", "按各功能建筑面积比例", _group(units, "indoor"), True),
        ("室外地面面积", "按各功能地面面积比例", _group(units, "outdoor"), False),
    ]
    panel_w, item_cols = (460, 3) if stacked else (580, 4)
    panel_heights = [110 + max(1, (len(items) + item_cols - 1) // item_cols) * 125
                     for _, _, items, _ in panels]
    if not stacked:
        panel_heights = [max(panel_heights)] * 2
    width = panel_w + 28 if stacked else panel_w * 2 + 42
    height = sum(panel_heights) + 42 if stacked else panel_heights[0] + 28
    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
        'aria-label="功能面积示意，非实际建筑布局" style="width:100%;height:auto;display:block">',
        '<defs><pattern id="ground-grid" width="18" height="18" patternUnits="userSpaceOnUse">'
        '<path d="M 18 0 L 0 0 0 18" fill="none" stroke="#dce5dd" stroke-width="0.75"/></pattern></defs>',
    ]
    for index, ((label, subtitle, items, indoor), panel_h) in enumerate(zip(panels, panel_heights)):
        x = 14 if stacked else 14 + index * (panel_w + 14)
        y = 14 + index * (panel_heights[0] + 14) if stacked else 14
        elements.extend([
            f'<rect x="{x}" y="{y}" width="{panel_w}" height="{panel_h}" rx="13" fill="#f2f6f1" stroke="#dbe5dc"/>',
            f'<rect x="{x+12}" y="{y+70}" width="{panel_w-24}" height="{panel_h-84}" rx="7" fill="url(#ground-grid)"/>',
            f'<text x="{x+20}" y="{y+28}" fill="#173e34" font-size="17" font-weight="700">{label}</text>',
            f'<text x="{x+20}" y="{y+49}" fill="#5a7065" font-size="12">{subtitle}</text>',
            f'<text x="{x+panel_w-20}" y="{y+29}" fill="#1e5748" font-size="16" font-weight="700" '
            f'text-anchor="end">{sum(area for _, area in items):,.0f} ㎡</text>',
        ])
        if not items:
            elements.append(f'<text x="{x+28}" y="{y+133}" fill="#66796d" font-size="14">暂无已分配面积</text>')
            continue
        max_area = max(area for _, area in items)
        step = (panel_w - 36) / item_cols
        for number, (name, area) in enumerate(items):
            col, row = number % item_cols, number // item_cols
            cx = x + 18 + step * (col + 0.5)
            cy = y + 124 + 125 * row
            length = 46 * sqrt(area / max_area)
            depth = length * 0.49
            lift = 27 if indoor else 0
            color = function_color(name)
            top = [(cx, cy-depth-lift), (cx+length, cy-lift), (cx, cy+depth-lift), (cx-length, cy-lift)]
            if indoor:
                elements.append(_polygon([top[3], top[2], (cx, cy+depth), (cx-length, cy)], _shade(color, 0.82)))
                elements.append(_polygon([top[2], top[1], (cx+length, cy), (cx, cy+depth)], _shade(color, 0.68)))
            elements.append(_polygon(top, color))
            elements.append(f'<circle cx="{cx-49}" cy="{cy+37}" r="3.5" fill="{color}"/>'
                            f'<text x="{cx-40}" y="{cy+41}" fill="#25463b" font-size="12.5" '
                            f'font-weight="700">{escape(name)}</text>'
                            f'<text x="{cx-40}" y="{cy+58}" fill="#64766c" font-size="11.5">{area:,.0f} ㎡</text>')
    return "".join([*elements, "</svg>"])
