"""Raise body text in the lecture decks to a minimum font size, then repair layout.

`build_slides_branded.py` cannot be re-run here: it points at a Windows path and
needs `BL_Video_MasterTemplate_16-9.pptx`, which is not in the repo. So this
script edits the built .pptx files in place instead, and is safe to re-run.

What it changes
---------------
Body text is raised to MIN_PT. Deck chrome is deliberately left alone, because
raising it is what breaks the layout:

  * the running footer and slide number (9pt, in a 0.3in-high box)
  * the eyebrow labels above each title ("COURSE CONTEXT", 12pt)
  * micro-labels inside diagram cards (8-12.5pt, e.g. the slide-42 stack)
  * source/reference footnotes (10-11pt)

The rule: a text run is body text if it is already >= TF_FLOOR (13pt). Table
cells are always raised, since they carry real content at 12-12.5pt.

After raising the text it re-measures every shape with real Arial metrics and
grows boxes into adjacent free space so nothing overflows. That matters beyond
looks: 38 of the shapes use PowerPoint's "shrink text on overflow" autofit, so a
box left too small would silently render below MIN_PT and undo the whole point.

Usage:
    python enforce_min_font.py --check      # report only, write nothing
    python enforce_min_font.py              # fix both decks in place
"""

from __future__ import annotations

import argparse
import copy
import glob
import sys
from pathlib import Path

from pptx import Presentation
from pptx.oxml.ns import qn
from pptx.util import Emu

from fit_metrics import (
    EMU,
    LINE_FACTOR,
    frame_height_pt,
    para_runs,
    usable_height_pt,
    wrap_lines,
)

MIN_PT = 18.0
# Runs below this are chrome (footers, eyebrows, diagram micro-labels) and are
# left at their original size.
TF_FLOOR = 13.0
# Leave this much of a box empty. PowerPoint's line metrics differ slightly from
# ours, and an exactly-full box is what triggers autofit shrinking.
TARGET_FILL = 0.90
CLEARANCE_IN = 0.06


def bump(size_pt: float) -> float:
    return MIN_PT if TF_FLOOR <= size_pt < MIN_PT else size_pt


# ---------------------------------------------------------------------------
# font changes
# ---------------------------------------------------------------------------
def raise_text_frame(text_frame) -> int:
    changed = 0
    for para in text_frame.paragraphs:
        if para.font.size is not None and TF_FLOOR <= para.font.size.pt < MIN_PT:
            para.font.size = Emu(int(MIN_PT * 12700))
            changed += 1
        for run in para.runs:
            size = run.font.size or para.font.size
            if size is not None and TF_FLOOR <= size.pt < MIN_PT:
                run.font.size = Emu(int(MIN_PT * 12700))
                changed += 1
    return changed


def raise_table(table) -> int:
    """Table cells always go to MIN_PT, including the 12-12.5pt content rows."""
    changed = 0
    for row in table.rows:
        for cell in row.cells:
            for para in cell.text_frame.paragraphs:
                if para.font.size is not None and para.font.size.pt < MIN_PT:
                    para.font.size = Emu(int(MIN_PT * 12700))
                    changed += 1
                for run in para.runs:
                    size = run.font.size or para.font.size
                    if size is not None and size.pt < MIN_PT:
                        run.font.size = Emu(int(MIN_PT * 12700))
                        changed += 1
    return changed


# ---------------------------------------------------------------------------
# layout repair
# ---------------------------------------------------------------------------
def geometry(shape):
    """(left, top, right, bottom) in EMU, or None when the shape has no explicit box."""
    if shape.left is None or shape.top is None:
        return None
    if shape.width is None or shape.height is None:
        return None
    return shape.left, shape.top, shape.left + shape.width, shape.top + shape.height


def vertical_limits(shape, siblings, slide_height: int):
    """How far this shape may grow up and down before touching a neighbour.

    A shape that fully surrounds this one is a background card, not an obstacle:
    it clamps the target instead of blocking it.
    """
    box = geometry(shape)
    if box is None:
        return None
    left, top, right, bottom = box
    clear = int(CLEARANCE_IN * EMU)
    limit_top, limit_bottom = 0, slide_height

    for other in siblings:
        if other is shape:
            continue
        obox = geometry(other)
        if obox is None:
            continue
        oleft, otop, oright, obottom = obox
        if oright <= left or oleft >= right:  # no horizontal overlap
            continue
        if otop <= top and obottom >= bottom and oleft <= left and oright >= right:
            limit_top = max(limit_top, otop)
            limit_bottom = min(limit_bottom, obottom)
            continue
        if obottom <= top:
            limit_top = max(limit_top, obottom)
        elif otop >= bottom:
            limit_bottom = min(limit_bottom, otop)

    return limit_top + clear, limit_bottom - clear


def fill_ratio(shape) -> float:
    return frame_height_pt(shape.text_frame, shape.width) / usable_height_pt(shape)


def make_room_below(shape, wanted: int, siblings, slide_height: int) -> int:
    """Free up vertical space under `shape` by leaning on slack neighbours.

    Two ways a neighbour can yield: slide down into empty space beneath it, or
    (if it is a text box with plenty of headroom) give up some of its own height.
    Returns the EMU actually freed.
    """
    box = geometry(shape)
    if box is None:
        return 0
    left, _, right, bottom = box
    clear = int(CLEARANCE_IN * EMU)

    blockers = []
    for other in siblings:
        obox = geometry(other)
        if other is shape or obox is None:
            continue
        oleft, otop, oright, obottom = obox
        if oright <= left or oleft >= right:
            continue
        if otop >= bottom - clear:
            blockers.append(other)
    if not blockers:
        return 0

    # The row of shapes sitting directly beneath us. Anything centred inside that
    # band belongs to the row too — connector arrows between diagram cards sit
    # slightly lower than the cards but must travel with them.
    band_top = min(s.top for s in blockers)
    seed = [s for s in blockers if s.top < band_top + int(0.2 * EMU)]
    band_bottom = max(s.top + s.height for s in seed)
    row = [s for s in blockers if (s.top + s.height / 2) < band_bottom]
    rest = [s for s in blockers if s not in row]
    row_bottom = max(s.top + s.height for s in row)

    # Never disturb the footer / slide number pinned near the slide bottom.
    floor = slide_height - int(0.45 * EMU)
    next_top = min((s.top for s in rest), default=floor)
    slide_room = max(0, min(next_top, floor) - row_bottom - clear)

    shrink_room = 0
    if len(row) == 1 and row[0].has_text_frame and row[0].text_frame.text.strip():
        target = row[0]
        current = fill_ratio(target)
        if current < TARGET_FILL:
            spare = target.height - int(target.height * current / TARGET_FILL)
            shrink_room = max(0, spare)

    freed = min(wanted, slide_room + shrink_room)
    if freed <= 0:
        return 0

    by_slide = min(freed, slide_room)
    by_shrink = freed - by_slide
    for s in row:
        s.top = s.top + by_slide
    if by_shrink and len(row) == 1:
        row[0].top = row[0].top + by_shrink
        row[0].height = row[0].height - by_shrink
    return freed


def grow_shape(shape, siblings, slide_height: int) -> str | None:
    """Expand a too-full text box into free space. Returns a description if moved."""
    limits = vertical_limits(shape, siblings, slide_height)
    if limits is None:
        return None
    limit_top, limit_bottom = limits

    needed_pt = frame_height_pt(shape.text_frame, shape.width) / TARGET_FILL
    tf = shape.text_frame
    insets = (tf.margin_top or 0) + (tf.margin_bottom or 0)
    needed = int(needed_pt / 72.0 * EMU) + insets

    room = limit_bottom - limit_top
    if room < needed:
        # Not enough free space: ask the shapes below to yield some.
        freed = make_room_below(shape, needed - room, siblings, slide_height)
        if freed:
            limits = vertical_limits(shape, siblings, slide_height)
            limit_top, limit_bottom = limits
            room = limit_bottom - limit_top
    if room <= shape.height:
        return None

    new_height = min(needed, room)
    if new_height <= shape.height:
        return None

    old_top, old_height = shape.top, shape.height
    extra = new_height - shape.height
    # Prefer growing downward; borrow upward only if the gap below is too small.
    down = min(extra, limit_bottom - (shape.top + shape.height))
    up = min(extra - down, shape.top - limit_top)
    shape.top = shape.top - up
    shape.height = shape.height + up + down
    if shape.height == old_height:
        return None
    return (
        f"{old_top/EMU:.2f}->{shape.top/EMU:.2f}in top, "
        f"{old_height/EMU:.2f}->{shape.height/EMU:.2f}in high"
    )


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------
def retable(shape) -> tuple[float, float]:
    """Set row heights to fit MIN_PT text. Returns (old_total_in, new_total_in)."""
    table = shape.table
    widths = [col.width for col in table.columns]
    old_total = sum(row.height for row in table.rows)

    for row in table.rows:
        tallest = 0.0
        for idx, cell in enumerate(row.cells):
            width = widths[idx] if idx < len(widths) else shape.width
            avail_pt = max((width - (cell.margin_left or 0) - (cell.margin_right or 0)) / EMU * 72.0, 1.0)
            height = 0.0
            for para in cell.text_frame.paragraphs:
                runs = para_runs(para)
                if not runs:
                    continue
                size = max(s for _, s, _, _ in runs)
                text = "".join(t for t, _, _, _ in runs)
                bold = any(b for _, _, b, _ in runs)
                height += wrap_lines(text, size, avail_pt, bold) * size * LINE_FACTOR
            insets = ((cell.margin_top or 0) + (cell.margin_bottom or 0)) / EMU * 72.0
            tallest = max(tallest, height + insets)
        needed = int(tallest / 72.0 * EMU)
        if needed > row.height:
            row.height = needed

    return old_total / EMU, sum(row.height for row in table.rows) / EMU


def reflow_below(slide, table_shape, new_bottom: int, slide_height: int) -> list[str]:
    """Push shapes that sat below a grown table further down, preserving their gaps."""
    notes = []
    old_bottom = table_shape.top + table_shape.height
    shift = new_bottom - old_bottom
    if shift <= 0:
        return notes

    below = []
    for shape in slide.shapes:
        box = geometry(shape)
        if box is None or shape is table_shape:
            continue
        if box[1] >= old_bottom - int(0.02 * EMU):
            below.append(shape)
    if not below:
        return notes

    # Footer and slide number stay pinned to the bottom of the slide.
    movable = [s for s in below if s.top + s.height < slide_height - int(0.45 * EMU)]
    if not movable:
        return notes

    floor = min(
        (s.top for s in below if s not in movable),
        default=slide_height - int(0.1 * EMU),
    ) - int(CLEARANCE_IN * EMU)

    block_top = min(s.top for s in movable)
    block_bottom = max(s.top + s.height for s in movable)
    # Close the existing gap first, then push down only as far as the floor allows.
    gap = block_top - old_bottom
    desired = new_bottom + min(gap, int(0.15 * EMU))
    delta = desired - block_top
    if block_bottom + delta > floor:
        delta = floor - block_bottom
    if delta == 0:
        return notes
    for shape in movable:
        shape.top = shape.top + delta
    notes.append(f"moved {len(movable)} shape(s) below the table by {delta/EMU:+.2f}in")
    return notes


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------
def process(path: Path, check_only: bool) -> tuple[int, list[str]]:
    prs = Presentation(str(path))
    slide_height = prs.slide_height
    runs_changed = 0
    notes: list[str] = []

    for index, slide in enumerate(prs.slides, 1):
        shapes = list(slide.shapes)

        for shape in shapes:
            if shape.has_table:
                before = raise_table(shape.table)
                runs_changed += before
                if before and not check_only:
                    old_in, new_in = retable(shape)
                    if new_in > old_in + 0.01:
                        notes.append(
                            f"  slide {index}: table {old_in:.2f}->{new_in:.2f}in tall"
                        )
                        new_bottom = shape.top + int(new_in * EMU)
                        notes += [f"  slide {index}: {n}" for n in
                                  reflow_below(slide, shape, new_bottom, slide_height)]
                        shape.height = int(new_in * EMU)
            elif shape.has_text_frame:
                runs_changed += raise_text_frame(shape.text_frame)

        if check_only:
            continue

        # Second pass: grow any box the larger text no longer fits.
        for shape in shapes:
            if not shape.has_text_frame or not shape.text_frame.text.strip():
                continue
            if shape.width is None or shape.height is None:
                continue
            if fill_ratio(shape) <= TARGET_FILL:
                continue
            moved = grow_shape(shape, shapes, slide_height)
            if moved:
                notes.append(f"  slide {index}: grew box ({moved})")

    if not check_only:
        prs.save(str(path))
    return runs_changed, notes


def audit(path: Path) -> None:
    """Report any body text still below MIN_PT, and any box still over-full."""
    prs = Presentation(str(path))
    small, tight = [], []
    for index, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            if shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        for para in cell.text_frame.paragraphs:
                            for run in para.runs:
                                size = run.font.size or para.font.size
                                if run.text.strip() and size and size.pt < MIN_PT:
                                    small.append((index, size.pt, run.text[:34], "table"))
            elif shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    for run in para.runs:
                        size = run.font.size or para.font.size
                        if run.text.strip() and size and TF_FLOOR <= size.pt < MIN_PT:
                            small.append((index, size.pt, run.text[:34], "body"))
                if shape.text_frame.text.strip() and shape.width and shape.height:
                    ratio = fill_ratio(shape)
                    if ratio > 1.0:
                        tight.append((index, ratio, shape.text_frame.text[:34].replace("\n", " / ")))

    print(f"  body runs still below {MIN_PT:.0f}pt : {len(small)}")
    for entry in small[:10]:
        print(f"    slide {entry[0]} {entry[1]}pt [{entry[3]}] {entry[2]!r}")
    print(f"  boxes still over 100% full    : {len(tight)}")
    for entry in tight[:10]:
        print(f"    slide {entry[0]} {entry[1]*100:.0f}% {entry[2]!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="Report only; write nothing.")
    parser.add_argument("decks", nargs="*", help="Deck paths (default: slides/*.pptx).")
    args = parser.parse_args()

    here = Path(__file__).parent
    paths = [Path(p) for p in args.decks] or sorted(here.glob("*.pptx"))
    if not paths:
        print("No .pptx files found.", file=sys.stderr)
        return 1

    for path in paths:
        print(f"\n=== {path.name} ===")
        changed, notes = process(path, args.check)
        print(f"  runs raised to {MIN_PT:.0f}pt: {changed}")
        for note in notes:
            print(note)
        if not args.check:
            audit(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
