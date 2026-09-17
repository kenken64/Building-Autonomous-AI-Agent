"""Text-fit measurement for PowerPoint shapes using real Arial metrics.

python-pptx cannot measure rendered text, so we wrap each paragraph with Pillow
using the actual Arial faces PowerPoint would use, and compare the resulting
block height against the shape's usable height.
"""
from __future__ import annotations

from functools import lru_cache

from PIL import ImageFont
from pptx.util import Emu, Pt

EMU = 914400
FACES = {
    (False, False): "/System/Library/Fonts/Supplemental/Arial.ttf",
    (True, False): "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    (False, True): "/System/Library/Fonts/Supplemental/Arial Italic.ttf",
    (True, True): "/System/Library/Fonts/Supplemental/Arial Bold Italic.ttf",
}
# Pillow measures at integer pixel sizes; use a large size and scale for accuracy.
MEASURE_PX = 200
# PowerPoint's single line spacing for Arial is ~1.15-1.2 em; use 1.2 to stay safe.
LINE_FACTOR = 1.2


@lru_cache(maxsize=8)
def _font(bold: bool, italic: bool):
    return ImageFont.truetype(FACES[(bold, italic)], MEASURE_PX)


def text_width_pt(text: str, size_pt: float, bold=False, italic=False) -> float:
    if not text:
        return 0.0
    return _font(bool(bold), bool(italic)).getlength(text) * size_pt / MEASURE_PX


def wrap_lines(text: str, size_pt: float, avail_pt: float, bold=False, italic=False) -> int:
    """Greedy word wrap, matching how PowerPoint breaks on spaces."""
    if not text.strip():
        return 1
    if avail_pt <= 0:
        return 1
    words = text.split()
    lines, cur = 1, ""
    for word in words:
        trial = word if not cur else cur + " " + word
        if text_width_pt(trial, size_pt, bold, italic) <= avail_pt:
            cur = trial
        else:
            if cur:
                lines += 1
            cur = word
            # A single word longer than the line still occupies extra lines.
            while text_width_pt(cur, size_pt, bold, italic) > avail_pt and len(cur) > 1:
                cut = len(cur)
                while cut > 1 and text_width_pt(cur[:cut], size_pt, bold, italic) > avail_pt:
                    cut -= 1
                cur = cur[cut:]
                lines += 1
    return lines


def para_runs(para):
    """(text, size_pt, bold, italic) for each non-empty run, inheriting paragraph font."""
    out = []
    for run in para.runs:
        size = run.font.size or para.font.size
        out.append(
            (
                run.text,
                size.pt if size else 18.0,
                bool(run.font.bold or para.font.bold),
                bool(run.font.italic or para.font.italic),
            )
        )
    return out


def frame_height_pt(text_frame, width_emu: int, size_override=None) -> float:
    """Rendered height of a text frame's content, in points.

    `size_override` maps an old point size to a new one, so the same routine can
    measure the frame before and after a font bump.
    """
    li = text_frame.margin_left or 0
    ri = text_frame.margin_right or 0
    avail_pt = max((width_emu - li - ri) / EMU * 72.0, 1.0)

    total = 0.0
    for para in text_frame.paragraphs:
        runs = para_runs(para)
        if not runs:
            size = para.font.size
            total += (size.pt if size else 18.0) * LINE_FACTOR
            continue

        sizes = [size_override(s) if size_override else s for _, s, _, _ in runs]
        max_size = max(sizes)
        joined = "".join(t for t, _, _, _ in runs)
        bold = any(b for _, _, b, _ in runs)
        italic = any(i for _, _, _, i in runs)

        lines = wrap_lines(joined, max_size, avail_pt, bold, italic)

        line_h = max_size * LINE_FACTOR
        if para.line_spacing is not None:
            if isinstance(para.line_spacing, float):  # multiple
                line_h = max_size * para.line_spacing
            else:  # exact Length
                line_h = para.line_spacing.pt
        total += lines * line_h
        if para.space_before is not None:
            total += para.space_before.pt
        if para.space_after is not None:
            total += para.space_after.pt
    return total


def usable_height_pt(shape) -> float:
    tf = shape.text_frame
    ti = tf.margin_top or 0
    bi = tf.margin_bottom or 0
    return max((shape.height - ti - bi) / EMU * 72.0, 1.0)
