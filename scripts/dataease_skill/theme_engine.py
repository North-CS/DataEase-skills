from __future__ import annotations

import colorsys
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any

from .errors import DataEaseError


BUILTIN_THEMES: dict[str, dict[str, Any]] = {
    "business-light": {"dark": False, "background": "#F5F6F7", "accent": "#1E90FF", "text": "#1F2329",
                       "colors": ["#1E90FF", "#20B2AA", "#7C5CFF", "#FFB347", "#FF6B8A"]},
    "minimal-light": {"dark": False, "background": "#FFFFFF", "accent": "#5B5BD6", "text": "#242424",
                      "colors": ["#5B5BD6", "#7A9CC6", "#52B788", "#E9C46A", "#E76F51"]},
    "neon-dark": {"dark": True, "background": "#050B1A", "accent": "#00D9FF", "text": "#DDF8FF",
                  "colors": ["#00D9FF", "#7C5CFF", "#20E3B2", "#FFB347", "#FF5DA2"]},
    "deep-ocean": {"dark": True, "background": "#031525", "accent": "#26C6DA", "text": "#D8F3FF",
                   "colors": ["#26C6DA", "#4D96FF", "#20E3B2", "#7C5CFF", "#FFB347"]},
    "dark-gold": {"dark": True, "background": "#15120B", "accent": "#D6A84B", "text": "#F8E8BD",
                  "colors": ["#D6A84B", "#F3CC75", "#9D7B3D", "#E07A5F", "#81B29A"]},
    "tech-blue": {"dark": True, "background": "#071A3D", "accent": "#4D96FF", "text": "#E5F0FF",
                  "colors": ["#4D96FF", "#00C2FF", "#20E3B2", "#7C5CFF", "#FFB347"]},
    "chinese-red": {"dark": True, "background": "#210A0A", "accent": "#D9A441", "text": "#FFF3D6",
                    "colors": ["#C53B32", "#D9A441", "#8F1D21", "#E8C77B", "#4F6D4A"]},
    "government-blue": {"dark": False, "background": "#EEF5FC", "accent": "#165DAD", "text": "#102A43",
                        "colors": ["#165DAD", "#2F80ED", "#14B8A6", "#F59E0B", "#64748B"]},
    "medical-health": {"dark": False, "background": "#F2FBFA", "accent": "#008C85", "text": "#163C3A",
                       "colors": ["#008C85", "#33B5AA", "#4D96FF", "#7CC576", "#F2B134"]},
    "energy-green": {"dark": True, "background": "#071B16", "accent": "#35D07F", "text": "#E2FFF1",
                     "colors": ["#35D07F", "#00B8A9", "#8DD35F", "#F2C94C", "#4D96FF"]},
    "retail-vibrant": {"dark": False, "background": "#FFF8F4", "accent": "#FF5A5F", "text": "#3B2530",
                       "colors": ["#FF5A5F", "#FF9F1C", "#7C5CFF", "#20B2AA", "#4D96FF"]},
}

_CUSTOM_KEYS = {
    "base", "name", "accent", "primary", "background", "text", "colors",
    "logo", "background_image", "dark",
}


def _hex(value: Any, field: str) -> str:
    text = str(value or "").strip().upper()
    if not re.fullmatch(r"#[0-9A-F]{6}", text):
        raise DataEaseError(f"theme.{field} 必须是 #RRGGBB", code="invalid_theme", stage="input")
    return text


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[pos:pos + 2], 16) for pos in (0, 2, 4))


def color_with_alpha(color: str, alpha: float) -> str:
    red, green, blue = _rgb(color)
    return f"rgba({red},{green},{blue},{max(0, min(alpha, 1)):.2f})"


def relative_luminance(color: str) -> float:
    channels = []
    for item in _rgb(color):
        value = item / 255
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(first: str, second: str) -> float:
    light, dark = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def accessible_text(background: str, preferred: str | None = None) -> tuple[str, float, bool]:
    if preferred:
        preferred_ratio = contrast_ratio(background, preferred)
        if preferred_ratio >= 4.5:
            return preferred, preferred_ratio, False
    candidates = [preferred] if preferred else []
    candidates.extend(["#FFFFFF", "#111827"])
    scored = [(color, contrast_ratio(background, color)) for color in candidates if color]
    color, ratio = max(scored, key=lambda item: item[1])
    return color, ratio, bool(preferred and color != preferred)


def _derived_palette(accent: str) -> list[str]:
    red, green, blue = (value / 255 for value in _rgb(accent))
    hue, saturation, lightness = colorsys.rgb_to_hls(red, green, blue)
    result = [accent]
    for offset, sat, light in ((.08, .72, .58), (.33, .65, .48), (.55, .68, .56), (.83, .70, .60)):
        rgb = colorsys.hls_to_rgb((hue + offset) % 1, light, sat)
        result.append("#" + "".join(f"{round(channel * 255):02X}" for channel in rgb))
    return result


def extract_asset_palette(path_value: str | Path) -> list[str]:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise DataEaseError(f"主题素材不存在: {path}", code="theme_asset_not_found", stage="input")
    if path.suffix.lower() == ".svg":
        colors = re.findall(r"#[0-9a-fA-F]{6}", path.read_text(encoding="utf-8", errors="ignore"))
        unique = list(dict.fromkeys(color.upper() for color in colors))
        if unique:
            return unique[:5]
    try:
        from PIL import Image

        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((160, 160))
            quantized = image.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
            palette = quantized.getpalette() or []
            counts = sorted(quantized.getcolors() or [], reverse=True)
            colors = []
            for _, index in counts:
                red, green, blue = palette[index * 3:index * 3 + 3]
                color = f"#{red:02X}{green:02X}{blue:02X}"
                if max(red, green, blue) - min(red, green, blue) >= 18:
                    colors.append(color)
            if colors:
                return list(dict.fromkeys(colors))[:5]
    except ImportError as exc:
        raise DataEaseError(
            "PNG/JPG 主题取色需要 Pillow；请重新安装 requirements.txt",
            code="missing_theme_dependency", stage="runtime",
        ) from exc
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return ["#" + digest[position:position + 6].upper() for position in range(0, 30, 6)]


def resolve_theme(value: Any, *, skill_root: Path | None = None) -> dict[str, Any]:
    if isinstance(value, str):
        if value not in BUILTIN_THEMES:
            raise DataEaseError(
                f"未知主题: {value}",
                code="invalid_theme", stage="input",
                details={"supported": sorted(BUILTIN_THEMES)},
            )
        theme = {**BUILTIN_THEMES[value], "name": value, "contrast_adjusted": False}
        ratio = contrast_ratio(theme["background"], theme["text"])
        theme.update({
            "contrast_ratio": round(ratio, 2),
            "accessibility": {"wcag_aa_normal_text": ratio >= 4.5, "wcag_aa_large_text": ratio >= 3},
        })
        return theme
    if not isinstance(value, dict):
        raise DataEaseError("theme 必须是主题名称或对象", code="invalid_theme", stage="input")
    unknown = set(value) - _CUSTOM_KEYS
    if unknown:
        raise DataEaseError(
            "自定义主题包含未知字段", code="invalid_theme", stage="input",
            details={"fields": sorted(unknown)},
        )
    base_name = str(value.get("base") or "business-light")
    if base_name == "corporate-brand":
        base_name = "business-light"
    if base_name not in BUILTIN_THEMES:
        raise DataEaseError(f"未知基础主题: {base_name}", code="invalid_theme", stage="input")
    theme = dict(BUILTIN_THEMES[base_name])
    root = skill_root or Path.cwd()
    asset = value.get("logo") or value.get("background_image")
    if asset:
        asset_path = Path(str(asset))
        if not asset_path.is_absolute():
            asset_path = root / asset_path
        extracted = extract_asset_palette(asset_path)
        theme["colors"] = extracted + [item for item in theme["colors"] if item not in extracted]
        theme["accent"] = extracted[0]
    if value.get("accent") or value.get("primary"):
        theme["accent"] = _hex(value.get("accent") or value.get("primary"), "accent")
        if not value.get("colors"):
            theme["colors"] = _derived_palette(theme["accent"])
    if value.get("background"):
        theme["background"] = _hex(value["background"], "background")
    if value.get("colors"):
        if not isinstance(value["colors"], list) or len(value["colors"]) < 3:
            raise DataEaseError("theme.colors 至少包含 3 个颜色", code="invalid_theme", stage="input")
        theme["colors"] = [_hex(item, "colors") for item in value["colors"][:12]]
    text_setting = value.get("text")
    preferred_text = _hex(text_setting, "text") if text_setting not in (None, "auto") else None
    if "text" not in value:
        preferred_text = theme.get("text")
    text, ratio, adjusted = accessible_text(theme["background"], preferred_text)
    theme.update({
        "name": str(value.get("name") or value.get("base") or "custom"),
        "text": text,
        "dark": bool(value.get("dark", relative_luminance(theme["background"]) < 0.46)),
        "contrast_ratio": round(ratio, 2),
        "contrast_adjusted": adjusted,
        "accessibility": {"wcag_aa_normal_text": ratio >= 4.5, "wcag_aa_large_text": ratio >= 3},
    })
    if value.get("background_image"):
        image = Path(str(value["background_image"]))
        theme["background_image"] = str((image if image.is_absolute() else root / image).resolve())
    return theme


def recommend_theme_names(title: str, busi_type: str, selected: Any = None) -> list[Any]:
    text = str(title or "").lower()
    first = selected or ("neon-dark" if busi_type == "dataV" else "business-light")
    industry = "tech-blue"
    for keywords, candidate in (
        (("政务", "政府", "治理"), "government-blue"),
        (("医疗", "医院", "健康"), "medical-health"),
        (("能源", "电力", "碳", "光伏"), "energy-green"),
        (("零售", "电商", "商品", "门店"), "retail-vibrant"),
        (("中国风", "党建", "文化"), "chinese-red"),
    ):
        if any(keyword in text for keyword in keywords):
            industry = candidate
            break
    contrast = "deep-ocean" if busi_type == "dataV" else "minimal-light"
    result = []
    for item in (
        first, industry, contrast,
        "business-light" if busi_type == "dataV" else "tech-blue",
        "dark-gold", "retail-vibrant",
    ):
        marker = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, dict) else str(item)
        if marker not in [entry[0] for entry in result]:
            result.append((marker, item))
        if len(result) == 3:
            break
    return [item for _, item in result]


def render_theme_previews(
    output_dir: Path, title: str, busi_type: str, themes: list[Any], *, skill_root: Path,
) -> list[dict[str, Any]]:
    directory = output_dir / "theme-previews"
    directory.mkdir(parents=True, exist_ok=True)
    artifacts = []
    safe_title = re.sub(r'[<>:"/\\|?*]+', "_", title)[:60] or "dashboard"
    for index, value in enumerate(themes, start=1):
        palette = resolve_theme(value, skill_root=skill_root)
        colors = palette["colors"]
        bars = "".join(
            f'<rect x="{90 + pos * 62}" y="{310 - height}" width="38" height="{height}" rx="8" fill="{colors[pos % len(colors)]}"/>'
            for pos, height in enumerate((70, 118, 92, 155, 126, 190, 144))
        )
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540">
<rect width="960" height="540" fill="{palette['background']}"/>
<text x="48" y="58" fill="{palette['text']}" font-size="28" font-family="Microsoft YaHei">{html.escape(title)}</text>
<text x="48" y="88" fill="{palette['text']}" opacity=".72" font-size="15">主题：{html.escape(palette['name'])} · 对比度 {palette.get('contrast_ratio', contrast_ratio(palette['background'], palette['text'])):.2f}:1</text>
<rect x="48" y="116" width="264" height="104" rx="16" fill="{palette['accent']}" opacity=".18" stroke="{palette['accent']}"/>
<text x="72" y="154" fill="{palette['text']}" font-size="16">核心指标</text><text x="72" y="198" fill="{palette['accent']}" font-size="34">¥ 12,860,000</text>
<rect x="336" y="116" width="576" height="220" rx="16" fill="{palette['text']}" opacity=".05" stroke="{palette['accent']}"/>
{bars}<polyline points="382,260 444,232 506,246 568,190 630,212 692,150 754,178" fill="none" stroke="{palette['accent']}" stroke-width="4"/>
<rect x="48" y="360" width="864" height="132" rx="16" fill="{palette['text']}" opacity=".05" stroke="{palette['accent']}"/>
<text x="72" y="400" fill="{palette['text']}" font-size="16">智能查询与明细表</text>
<rect x="72" y="422" width="220" height="40" rx="8" fill="{palette['background']}" stroke="{palette['accent']}"/>
<text x="90" y="448" fill="{palette['text']}" font-size="14">区域 / 日期 / 商品</text>
<rect x="316" y="422" width="96" height="40" rx="8" fill="{palette['accent']}"/><text x="344" y="448" fill="#FFFFFF" font-size="14">查询</text>
</svg>"""
        path = directory / f"{safe_title}-{index}-{palette['name']}.svg"
        path.write_text(svg, encoding="utf-8")
        artifacts.append({"theme": value, "resolved": palette, "preview": str(path.resolve())})
    return artifacts
