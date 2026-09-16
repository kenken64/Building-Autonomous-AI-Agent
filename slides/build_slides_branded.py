# Generates the branded lecture deck: Building Autonomous AI Agents
# OpenClaw, Hermes & NanoClaw - one-day full lesson
# Rebuilds the 43-slide deck on the BL master template (SR layouts).
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

TPL = r"D:\Projects\Building-Autonomous-AI-Agent\slides\BL_Video_MasterTemplate_16-9.pptx"
OUT = r"D:\Projects\Building-Autonomous-AI-Agent\slides\Building-Autonomous-AI-Agents-Lecture.pptx"

# ---------------- Template palette ----------------
BLUE   = RGBColor(0x00, 0x42, 0x82)   # template title blue
DBLUE  = RGBColor(0x2C, 0x57, 0x99)   # divider blue
ORANGE = RGBColor(0xF9, 0x9D, 0x1F)   # divider orange
TURQ   = RGBColor(0x00, 0xC2, 0xE5)   # divider turquoise
GREY   = RGBColor(0x49, 0x49, 0x49)   # divider grey
SLATE  = RGBColor(0x25, 0x25, 0x25)   # divider slate
INK    = RGBColor(0x2B, 0x34, 0x3F)   # body text
GRAY   = RGBColor(0x7B, 0x88, 0x98)   # template secondary gray
LIGHT  = RGBColor(0xF2, 0xF5, 0xF9)   # light panel bg
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
LT_TX  = RGBColor(0xE8, 0xEE, 0xF5)   # light text on dark bg
DK_ON_BRIGHT = RGBColor(0x1F, 0x2A, 0x36)  # dark text on orange/turq chips
RED_BG = RGBColor(0xFB, 0xEA, 0xE6)
GRN_BG = RGBColor(0xE7, 0xF4, 0xEC)
RED_TX = RGBColor(0xA3, 0x32, 0x1E)
GRN_TX = RGBColor(0x1E, 0x5E, 0x3A)

FONT = "Arial"

prs = Presentation(TPL)
SW, SH = prs.slide_width, prs.slide_height

# ---------------- Remove template demo slides + section list ----------------
xml_slides = prs.slides._sldIdLst
for sld in list(xml_slides):
    rId = sld.get(qn("r:id"))
    prs.part.drop_rel(rId)
    xml_slides.remove(sld)

pres_el = prs.part._element
extLst = pres_el.find(qn("p:extLst"))
if extLst is not None:
    for ext in list(extLst):
        if ext.find("{http://schemas.microsoft.com/office/powerpoint/2010/main}sectionLst") is not None:
            extLst.remove(ext)

LAYS = prs.slide_masters[0].slide_layouts
L_TITLE, L_DIV_W, L_DIV_O, L_DIV_T, L_DIV_B, L_DIV_G, L_DIV_S = 3, 5, 6, 7, 8, 9, 10
L_OUTCOME, L_BLOCKS, L_BULLETS, L_2COL, L_END = 16, 22, 25, 27, 29

slide_no = [0]

# ---------------- Text helpers ----------------
def _bullets_off(p):
    pPr = p._p.get_or_add_pPr()
    for tag in ("buChar", "buAutoNum", "buNone"):
        for el in pPr.findall(qn("a:" + tag)):
            pPr.remove(el)
    pPr.append(pPr.makeelement(qn("a:buNone"), {}))

def _bullet_on(p, char, marl, indent, color=None):
    pPr = p._p.get_or_add_pPr()
    pPr.set("marL", str(marl))
    pPr.set("indent", str(indent))
    for tag in ("buChar", "buAutoNum", "buNone"):
        for el in pPr.findall(qn("a:" + tag)):
            pPr.remove(el)
    if color is not None:
        buClr = pPr.makeelement(qn("a:buClr"), {})
        srgb = pPr.makeelement(qn("a:srgbClr"), {"val": "%02X%02X%02X" % (color[0], color[1], color[2]) if isinstance(color, tuple) else str(color)})
        buClr.append(srgb)
        pPr.append(buClr)
    pPr.append(pPr.makeelement(qn("a:buFont"), {"typeface": FONT}))
    pPr.append(pPr.makeelement(qn("a:buChar"), {"char": char}))

def _set_text(tf, items, default_size=16, default_color=INK, align=PP_ALIGN.LEFT,
              space_after=6, line_spacing=1.0):
    """items: list of dicts {t, lvl, size, bold, color, italic, align, space_before, bullet}
    '**bold**' markers inside t are parsed into bold runs."""
    tf.word_wrap = True
    first = True
    for it in items:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        lvl = it.get("lvl", 0)
        p.alignment = it.get("align", align)
        use_bullet = it.get("bullet", True)
        if use_bullet:
            char = {0: "\u25AA", 1: "\u2013", 2: "\u00B7"}.get(lvl, "\u00B7")
            marl = Inches(0.26 + 0.3 * lvl)
            _bullet_on(p, char, marl, -Inches(0.22),
                       color="F99D1F" if lvl == 0 else "7B8898")
        else:
            _bullets_off(p)
        p.space_after = Pt(it.get("space_after", space_after))
        if it.get("space_before"):
            p.space_before = Pt(it["space_before"])
        if line_spacing:
            p.line_spacing = it.get("line_spacing", line_spacing)
        text = it.get("t", "")
        size = it.get("size", default_size)
        color = it.get("color", default_color)
        bold = it.get("bold", False)
        italic = it.get("italic", False)
        segs = text.split("**")
        for i, seg in enumerate(segs):
            if not seg:
                continue
            r = p.add_run(); r.text = seg
            r.font.size = Pt(size); r.font.name = FONT
            r.font.bold = bold or (i % 2 == 1)
            r.font.italic = italic
            r.font.color.rgb = color
    return tf

def box(slide, x, y, w, h, fill=None, line=None, line_w=None,
        shape=MSO_SHAPE.RECTANGLE, radius=None):
    sp = slide.shapes.add_shape(shape, x, y, w, h)
    if fill is None:
        sp.fill.background()
    else:
        sp.fill.solid(); sp.fill.fore_color.rgb = fill
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line
        sp.line.width = line_w or Pt(1)
    sp.shadow.inherit = False
    if radius is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        try:
            sp.adjustments[0] = radius
        except Exception:
            pass
    return sp

def txt(slide, x, y, w, h, items, anchor=MSO_ANCHOR.TOP, **kw):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Emu(0)
    tf.margin_top = tf.margin_bottom = Emu(0)
    _set_text(tf, items, **kw)
    return tb

def chip(slide, x, y, w, h, text, fill, tcolor=WHITE, size=13, bold=True, sub=None,
         sub_color=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.14):
    b = box(slide, x, y, w, h, fill=fill, shape=shape, radius=radius)
    tf = b.text_frame; tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    items = [{"t": text, "size": size, "bold": bold, "color": tcolor, "bullet": False,
              "align": PP_ALIGN.CENTER, "space_after": 0}]
    if sub:
        items.append({"t": sub, "size": size - 3.5, "bold": False,
                      "color": sub_color or tcolor, "bullet": False,
                      "align": PP_ALIGN.CENTER, "space_after": 0})
    _set_text(tf, items)
    return b

def arrow(slide, x, y, w=Inches(0.5), h=Inches(0.34), color=ORANGE, right=True):
    return box(slide, x, y, w, h, fill=color,
               shape=MSO_SHAPE.RIGHT_ARROW if right else MSO_SHAPE.DOWN_ARROW)

# ---------------- Slide scaffolding ----------------
def add(layout_idx):
    slide_no[0] += 1
    return prs.slides.add_slide(LAYS[layout_idx])

def ph(slide, idx):
    return slide.placeholders[idx]

def drop_ph(slide, idx):
    try:
        sp = slide.placeholders[idx]
    except KeyError:
        return
    sp._element.getparent().remove(sp._element)

def footer(slide):
    txt(slide, Inches(0.92), Inches(7.12), Inches(7), Inches(0.3),
        [{"t": "Building Autonomous AI Agents  |  OpenClaw \u00B7 Hermes \u00B7 NanoClaw",
          "size": 9, "color": GRAY, "bullet": False}])
    txt(slide, Inches(12.55), Inches(7.12), Inches(0.5), Inches(0.3),
        [{"t": str(slide_no[0]), "size": 9, "color": GRAY, "bullet": False,
          "align": PP_ALIGN.RIGHT}])

def content_slide(layout_idx, title, kicker=None, title_size=30):
    s = add(layout_idx)
    t = ph(s, 0)
    t.left, t.top, t.width, t.height = Inches(0.92), Inches(0.55), Inches(11.6), Inches(0.9)
    _set_text(t.text_frame,
              [{"t": title, "size": title_size, "bold": True, "color": BLUE, "bullet": False}])
    if kicker:
        txt(s, Inches(0.92), Inches(0.26), Inches(11.6), Inches(0.28),
            [{"t": kicker.upper(), "size": 12, "bold": True, "color": ORANGE, "bullet": False}])
    footer(s)
    return s

def bullets_slide(title, items, kicker=None, default_size=16, title_size=30):
    s = content_slide(L_BULLETS, title, kicker, title_size)
    body = ph(s, 11)
    body.left, body.top, body.width, body.height = Inches(0.92), Inches(1.62), Inches(11.6), Inches(5.3)
    _set_text(body.text_frame, items, default_size=default_size, space_after=8,
              line_spacing=1.04)
    return s

def two_col_slide(title, left_head, left_items, right_head, right_items,
                  kicker=None, left_color=BLUE, right_color=ORANGE, size=14):
    s = content_slide(L_2COL, title, kicker)
    for idx, head, items, c in ((1, left_head, left_items, left_color),
                                (2, right_head, right_items, right_color)):
        body = ph(s, idx)
        head_items = [{"t": head, "size": 15.5, "bold": True, "color": c,
                       "bullet": False, "space_after": 10}]
        _set_text(body.text_frame, head_items + items, default_size=size, space_after=7,
                  line_spacing=1.03)
    return s

def divider(layout_idx, part_no, title, subtitle, duration=None):
    s = add(layout_idx)
    kicker = ("PART %s" % part_no) if part_no else "SECTION"
    if duration:
        kicker += "  \u00B7  " + duration.upper()
    txt(s, Inches(0.92), Inches(2.24), Inches(11.3), Inches(0.4),
        [{"t": kicker, "size": 15, "bold": True, "color": WHITE, "bullet": False}])
    _set_text(ph(s, 0).text_frame,
              [{"t": title, "size": 40, "bold": True, "color": WHITE, "bullet": False}])
    _set_text(ph(s, 10).text_frame,
              [{"t": subtitle, "size": 17, "color": LT_TX, "bullet": False}])
    return s

# ================= SLIDE 1: TITLE =================
s = add(L_TITLE)
t = ph(s, 0)
t.left, t.top, t.width, t.height = Inches(0.92), Inches(2.95), Inches(11.5), Inches(1.0)
_set_text(t.text_frame,
          [{"t": "Building Autonomous AI Agents", "size": 40, "bold": True, "color": BLUE,
            "bullet": False}])
sub = ph(s, 1)
sub.left, sub.top, sub.width, sub.height = Inches(0.92), Inches(4.05), Inches(11.5), Inches(2.4)
_set_text(sub.text_frame, [
    {"t": "OpenClaw, Hermes & NanoClaw", "size": 26, "bold": True, "color": ORANGE,
     "bullet": False},
    {"t": "Orchestration \u00B7 Models \u00B7 Edge \u00B7 Heartbeats \u00B7 Skills \u00B7 Channels \u00B7 A2A",
     "size": 16, "color": INK, "bullet": False, "space_before": 12},
    {"t": "Audience: working professionals / graduate learners", "size": 13,
     "color": GRAY, "bullet": False, "space_before": 8},
])

# ================= SLIDE 2: COURSE CONTEXT =================
s = content_slide(L_BULLETS, "Where Today Fits: The Three-Day Progression", "Course context")
drop_ph(s, 11)
steps = [("DAY 1", "Build an Agent", TURQ, DK_ON_BRIGHT),
         ("DAY 2", "Build an Agent Team", DBLUE, WHITE),
         ("DAY 3", "Build an Agent Ecosystem", ORANGE, DK_ON_BRIGHT)]
x = Inches(0.92)
for i, (d, t_, c, tc) in enumerate(steps):
    chip(s, x, Inches(1.62), Inches(3.55), Inches(0.9), t_, c, tcolor=tc, size=16, sub=d,
         sub_color=tc)
    if i < 2:
        arrow(s, x + Inches(3.62), Inches(1.9), w=Inches(0.42), h=Inches(0.34))
    x += Inches(4.02)
txt(s, Inches(0.92), Inches(2.78), Inches(11.6), Inches(0.75),
    [{"t": "**Day 3 (today):** build **MyShopper**, a personal buying agent owned by the customer \u2014 it represents the **customer**, not AgentMart.",
      "size": 15, "bullet": False}])
rows = [("Customer", "Telegram / WhatsApp / WebChat", TURQ, DK_ON_BRIGHT),
        ("MyShopper", "Personal buying agent \u2014 talks to AgentMart over A2A", DBLUE, WHITE),
        ("AgentMart", "Shopping \u00B7 Pricing \u00B7 Inventory \u00B7 Fulfilment \u00B7 Order agents", ORANGE, DK_ON_BRIGHT)]
y = Inches(3.62)
for name, desc, c, tc in rows:
    chip(s, Inches(1.35), y, Inches(2.7), Inches(0.62), name, c, tcolor=tc, size=14.5)
    txt(s, Inches(4.35), y + Inches(0.11), Inches(8.1), Inches(0.5),
        [{"t": desc, "size": 13.5, "color": INK, "bullet": False}])
    if y < Inches(5.0):
        arrow(s, Inches(2.5), y + Inches(0.64), w=Inches(0.4), h=Inches(0.3),
              color=GRAY, right=False)
    y += Inches(1.02)

# ================= SLIDE 3: AGENDA =================
s = content_slide(L_BULLETS, "Full-Day Agenda", "Session outline")
drop_ph(s, 11)
rows = [
    ("0:00 \u2013 0:15", "Opening & framing"),
    ("0:15 \u2013 1:00", "Part 1: OpenClaw \u2014 the orchestration layer"),
    ("1:00 \u2013 1:45", "Part 2: Hermes \u2014 the model layer"),
    ("1:45 \u2013 1:55", "Break"),
    ("1:55 \u2013 2:40", "Part 3: NanoClaw \u2014 the edge layer"),
    ("2:40 \u2013 3:40", "Part 4: Heartbeat mechanisms (deep dive)"),
    ("3:40 \u2013 3:50", "Break"),
    ("3:50 \u2013 4:50", "Part 5: Skill writing (deep dive)"),
    ("4:50 \u2013 5:00", "Break"),
    ("5:00 \u2013 6:00", "Part 6: Channel integration \u2014 messaging & voice"),
    ("6:00 \u2013 7:00", "Part 7: A2A setup \u2014 a one-of-its-kind protocol"),
    ("7:00 \u2013 7:20", "Combined lab: end-to-end channel-to-skill flow over custom A2A"),
    ("7:20 \u2013 7:30", "Wrap-up & Q&A"),
]
tbl_shape = s.shapes.add_table(len(rows) + 1, 2, Inches(0.92), Inches(1.5),
                               Inches(11.5), Inches(5.15))
tbl = tbl_shape.table
tbl.columns[0].width = Inches(2.0)
tbl.columns[1].width = Inches(9.5)
hdr = tbl.rows[0].cells
hdr[0].text = "Time"; hdr[1].text = "Segment"
for c in hdr:
    c.fill.solid(); c.fill.fore_color.rgb = BLUE
    for p in c.text_frame.paragraphs:
        for r in p.runs:
            r.font.bold = True; r.font.size = Pt(13); r.font.color.rgb = WHITE
            r.font.name = FONT
for i, (t_, seg) in enumerate(rows, start=1):
    cells = tbl.rows[i].cells
    cells[0].text = t_; cells[1].text = seg
    for j, c in enumerate(cells):
        c.fill.solid()
        c.fill.fore_color.rgb = LIGHT if i % 2 else WHITE
        for p in c.text_frame.paragraphs:
            for r in p.runs:
                r.font.size = Pt(12); r.font.name = FONT
                r.font.color.rgb = INK
                r.font.bold = ("Break" not in seg and j == 1 and
                               ("Part" in seg or "lab" in seg.lower()))
txt(s, Inches(0.92), Inches(6.78), Inches(11.6), Inches(0.35),
    [{"t": "Can also split into three sessions: A = Parts 1\u20133 \u00B7 B = Parts 4\u20135 + lab \u00B7 C = Parts 6\u20137 + final lab.",
      "size": 11, "italic": True, "color": GRAY, "bullet": False}])

# ================= SLIDE 4: LEARNING OBJECTIVES =================
s = content_slide(L_OUTCOME, "Learning Objectives", "Objectives")
body = ph(s, 11)
body.left, body.top, body.width, body.height = Inches(0.92), Inches(1.62), Inches(11.6), Inches(5.3)
_set_text(body.text_frame, [
    {"t": "By the end of today, you will be able to:", "bullet": False, "bold": True,
     "size": 16, "color": BLUE, "space_after": 10},
    {"t": "**Explain** how OpenClaw (orchestration), Hermes (model layer) and NanoClaw (edge deployment) fit together"},
    {"t": "**Design a heartbeat / liveness mechanism** for agents \u2014 including edge agents on unreliable networks"},
    {"t": "**Write agent skills** whose descriptions reliably trigger correct invocation, with basic security hardening"},
    {"t": "**Wire an agent to real-world channels** \u2014 messaging (Telegram / WhatsApp) and voice \u2014 and handle their distinct failure modes"},
    {"t": "**Design a custom agent-to-agent (A2A) protocol** on Redis Streams + MCP, distinct from off-the-shelf A2A implementations"},
    {"t": "**Build an end-to-end flow:** user messages/speaks \u2192 orchestrator dispatches to a healthy edge agent over custom A2A \u2192 skill invocation \u2192 reply over the same channel"},
], default_size=15.5, space_after=8, line_spacing=1.04)

# ================= SLIDE 5: STACK AT A GLANCE =================
s = content_slide(L_BULLETS, "The Stack at a Glance", "Framing")
drop_ph(s, 11)
layers = [("OpenClaw", "Orchestration layer", "Redis Streams + MCP multi-agent backbone", DBLUE, WHITE),
          ("Hermes", "Model layer", "Open-weight function-calling model", TURQ, DK_ON_BRIGHT),
          ("NanoClaw", "Edge layer", "Pi-class on-device deployment", ORANGE, DK_ON_BRIGHT)]
x = Inches(0.92)
for i, (name, role, desc, c, tc) in enumerate(layers):
    chip(s, x, Inches(1.66), Inches(3.55), Inches(1.1), name, c, tcolor=tc, size=19,
         sub=role, sub_color=tc)
    txt(s, x + Inches(0.1), Inches(2.85), Inches(3.35), Inches(0.6),
        [{"t": desc, "size": 12, "color": GRAY, "bullet": False, "align": PP_ALIGN.CENTER}])
    if i < 2:
        arrow(s, x + Inches(3.62), Inches(2.02), w=Inches(0.42), h=Inches(0.36))
    x += Inches(4.02)
txt(s, Inches(0.92), Inches(3.72), Inches(11.6), Inches(0.4),
    [{"t": "Four cross-cutting concerns make the stack trustworthy in production:",
      "size": 15, "bold": True, "color": BLUE, "bullet": False}])
conc = [("Heartbeats", "trust in state"), ("Skill writing", "trust in capability"),
        ("Channels", "trust in delivery"), ("Custom A2A", "trust in coordination")]
x = Inches(0.92)
for name, tag in conc:
    chip(s, x, Inches(4.28), Inches(2.68), Inches(0.9), name, LIGHT, tcolor=BLUE,
         size=14.5, sub=tag, sub_color=GRAY)
    x += Inches(2.94)
txt(s, Inches(0.92), Inches(5.55), Inches(11.6), Inches(0.9),
    [{"t": "By the end of the day you will build a small end-to-end system touching every one of these pieces.",
      "size": 14, "italic": True, "color": GRAY, "bullet": False}])

# ================= SLIDE 6: THREE LAYERS COMPARISON =================
s = content_slide(L_BULLETS, "The Three Layers: a Comparison", "Framing")
drop_ph(s, 11)
cmp_rows = [
    ("Role in the stack", "Orchestration layer", "Model layer", "Edge layer"),
    ("What it is", "Redis Streams + MCP multi-agent backbone",
     "Open-weight function-calling model",
     "Slimmed OpenClaw + Hermes runtime on Pi-class hardware"),
    ("Why it matters", "Durable, replayable, multi-consumer messaging between agents",
     "Cost, latency, no vendor lock-in; structured tool calls as first-class output",
     "Privacy, offline operation, no per-call cost; data stays on device"),
    ("Watch out for", "Stream-topology design + Redis operational overhead",
     "Smaller open models still trail frontier-model quality",
     "Tight RAM, quantization, slower on-device inference"),
]
tbl_shape = s.shapes.add_table(len(cmp_rows) + 1, 4, Inches(0.92), Inches(1.62),
                               Inches(11.5), Inches(4.3))
tbl = tbl_shape.table
tbl.columns[0].width = Inches(2.2)
for ci in (1, 2, 3):
    tbl.columns[ci].width = Inches(3.1)
hdr = tbl.rows[0].cells
hdr[0].text = ""
hdr[1].text = "OpenClaw"; hdr[2].text = "Hermes"; hdr[3].text = "NanoClaw"
hdr_fills = [BLUE, DBLUE, TURQ, ORANGE]
hdr_txt = [WHITE, WHITE, DK_ON_BRIGHT, DK_ON_BRIGHT]
for ci, c in enumerate(hdr):
    c.fill.solid(); c.fill.fore_color.rgb = hdr_fills[ci]
    for p in c.text_frame.paragraphs:
        for r in p.runs:
            r.font.bold = True; r.font.size = Pt(15); r.font.name = FONT
            r.font.color.rgb = hdr_txt[ci]
for ri, row in enumerate(cmp_rows, start=1):
    cells = tbl.rows[ri].cells
    for ci, val in enumerate(row):
        cells[ci].text = val
        cells[ci].fill.solid()
        cells[ci].fill.fore_color.rgb = LIGHT if ci == 0 else (WHITE if ri % 2 else LIGHT)
        for p in cells[ci].text_frame.paragraphs:
            for r in p.runs:
                r.font.size = Pt(12.5); r.font.name = FONT
                r.font.color.rgb = BLUE if ci == 0 else INK
                r.font.bold = (ci == 0)
txt(s, Inches(0.92), Inches(6.1), Inches(11.6), Inches(0.5),
    [{"t": "One stack, three layers \u2014 the rest of today is about making them trustworthy: heartbeats, skills, channels, A2A.",
      "size": 13, "italic": True, "color": GRAY, "bullet": False}])
ref_url = ("https://medium.com/redis-with-raphael-de-lio/"
           "openclaw-is-going-enterprise-rfc-27-redis-agent-file-system-dfe256c3b12f")
ref = txt(s, Inches(0.92), Inches(6.62), Inches(11.6), Inches(0.5), [])
tf = ref.text_frame
tf.word_wrap = True
p0 = tf.paragraphs[0]
p0.space_after = Pt(2)
r = p0.add_run()
r.text = ("Reference: Raphael De Lio, \u201COpenClaw is Going Enterprise \u2014 "
          "RFC-27: Redis Agent File System\u201D, Medium")
r.font.size = Pt(11); r.font.name = FONT; r.font.color.rgb = GRAY
p1 = tf.add_paragraph()
r = p1.add_run()
r.text = "medium.com/redis-with-raphael-de-lio/openclaw-is-going-enterprise-rfc-27-redis-agent-file-system-dfe256c3b12f"
r.font.size = Pt(10); r.font.name = FONT
r.font.color.rgb = RGBColor(0x2F, 0x6F, 0xD0)
r.hyperlink.address = ref_url

# ================= PART 1 =================
divider(L_DIV_B, "1", "OpenClaw \u2014 the Orchestration Layer",
        "Multi-agent architecture on Redis Streams + MCP, and where the ecosystem plug-ins attach.",
        "45 min")
bullets_slide("OpenClaw: Multi-Agent Architecture", [
    {"t": "**Redis Streams + MCP** are the backbone for agent-to-agent communication", "size": 16.5},
    {"t": "Redis Streams give **durable, replayable, multi-consumer** messaging between agents", "lvl": 1},
    {"t": "MCP standardises how agents expose and call tools", "lvl": 1},
    {"t": "**Live demo:** spin up two agents talking to each other via Redis Streams", "size": 16.5, "space_before": 10},
    {"t": "Watch: a message published by Agent A appears in Agent B's inbox stream and is consumed independently", "lvl": 1},
    {"t": "**Ecosystem plug-ins at this layer:**", "size": 16.5, "space_before": 10},
    {"t": "**ClawHub** \u2014 the skill marketplace (where reusable skills are published & discovered)", "lvl": 1},
    {"t": "**MoltGuard** \u2014 the guardrail proxy (policy & safety checks in the request path)", "lvl": 1},
], kicker="Part 1 \u00B7 OpenClaw")

# ================= PART 2 =================
divider(L_DIV_T, "2", "Hermes \u2014 the Model Layer",
        "Why an open-weight function-calling model is the right brain for self-hosted and edge agents.",
        "45 min")
two_col_slide("Hermes: Open-Weight Function Calling",
    "Why open-weight matters", [
        {"t": "**Cost** \u2014 no per-token API bill at agent scale"},
        {"t": "**Latency** \u2014 runs next to (or on) the agent; no network round-trip to a hosted API"},
        {"t": "**No vendor lock-in** \u2014 self-hosted, portable to edge hardware"},
        {"t": "**Function calling built in** \u2014 structured tool use is a first-class output, not a prompt hack"},
    ],
    "Hermes vs Claude / GPT tool calling", [
        {"t": "Compare Hermes' **tool-calling output format** against Claude / GPT function calling"},
        {"t": "Key check: does it emit **OpenAI-style `tool_calls`**? This decides whether agent frameworks need a translation shim"},
        {"t": "**Hands-on:** get Hermes making a structured tool call through an OpenClaw agent"},
    ],
    kicker="Part 2 \u00B7 Hermes")

# ================= SLIDE 11: HERMES CORE FEATURES =================
bullets_slide("Hermes Core Features: the Automation Engine", [
    {"t": "**Natural-language cron** \u2014 \u201Cevery weekday at 9am, summarize my inbox and post to Slack\u201D is all it takes; agents can also **self-schedule wake-ups**; **script mode** (`--script --no-agent`) runs with **zero LLM tokens**", "size": 15},
    {"t": "**Kanban coordination** \u2014 a shared Kanban board lets 7+ agents manage themselves: the board reads each profile\u2019s **SOUL.md** for name + role; tasks flow proposed \u2192 in-progress \u2192 done without you relaying anything", "size": 15},
    {"t": "**Subagent delegation** \u2014 talk to **one lead agent**; it delegates to specialist subagents (e.g. a 9-role dev team). Authority is enforced by **toolset restrictions**, not just system prompts; the orchestrator grades work **pass / rework / failed**", "size": 15},
    {"t": "**Self-improving skills** \u2014 writes its own skill files after solving hard problems; reusing a skill updates it from what it learns **(deep dive in Part 5)**", "size": 15},
    {"t": "**Memory & profiles** \u2014 three-layer memory; separate profiles with their own credentials, memory and scope", "size": 15},
    {"t": "**Safety & control** \u2014 approval gates, **/rollback** (rewind files + context), **/steer** (inject instructions mid-run) **\u2192 Part 5 security**", "size": 15},
], kicker="Part 2 \u00B7 Hermes", default_size=15)

# ================= SLIDE 12: HERMES AUTOMATION STORIES =================
s = two_col_slide("Hermes in the Wild: Automation Stories",
    "Cron in production", [
        {"t": "**3am \u201CDreaming\u201D job** \u2014 28 cron jobs, 30+ skills; every night it reads the day\u2019s conversations \u2192 decisions, bugs, mistakes \u2192 writes tomorrow\u2019s context", "size": 13.5},
        {"t": "**Gumroad** \u2014 cron jobs check support tickets, watch X mentions, update finance docs; every mistake becomes a **dated policy rule** the agent must read", "size": 13.5},
        {"t": "**20 cron \u201Csignals\u201D** \u2014 skills log to a daily ledger; an agentic triage job highlights what matters", "size": 13.5},
    ],
    "Agent teams in production", [
        {"t": "**7 agents, one Kanban** \u2014 given a shared board, they started managing themselves", "size": 13.5},
        {"t": "**Hermes Swarm** \u2014 teams of agents 24/7, messaging peer-to-peer, delegating work, self-scheduling wake-ups", "size": 13.5},
        {"t": "**12 instances in parallel** \u2014 Nous Research runs 12 Hermes instances daily to build Hermes itself", "size": 13.5},
    ],
    kicker="Part 2 \u00B7 Hermes \u00B7 Community")
ref = txt(s, Inches(0.92), Inches(6.76), Inches(11.6), Inches(0.35), [])
tf = ref.text_frame
tf.word_wrap = True
p0 = tf.paragraphs[0]
r = p0.add_run()
r.text = "Reference: Hermes Agent Docs \u2014 User Stories & Use Cases (326 stories, 15 categories): "
r.font.size = Pt(10.5); r.font.name = FONT; r.font.color.rgb = GRAY
r = p0.add_run()
r.text = "hermes-agent.nousresearch.com/docs/user-stories"
r.font.size = Pt(10.5); r.font.name = FONT
r.font.color.rgb = RGBColor(0x2F, 0x6F, 0xD0)
r.hyperlink.address = "https://hermes-agent.nousresearch.com/docs/user-stories"

# ================= SLIDE 13: HERMES DEEP CUTS =================
s = bullets_slide("Hermes Deep Cuts: LSP, Curator, SOUL.md & Media", [
    {"t": "**LSP \u2014 semantic diagnostics** \u2014 Hermes runs ~20 real language servers (pyright, typescript-language-server, rust-analyzer, gopls, clangd\u2026) as background subprocesses; after every `write_file` / `patch` the agent sees only the **new** diagnostics its edit introduced \u2014 type errors, undefined names, missing imports. The same architecture top-tier coding agents use, shipped self-contained", "size": 14.5},
    {"t": "**Curator** \u2014 background maintenance for agent-created skills: usage telemetry, **active \u2192 stale \u2192 archived** lifecycle, optional LLM consolidation of near-duplicates, snapshots + rollback, **pin** to protect \u2014 keeps the self-improvement loop from polluting the skill catalog", "size": 14.5},
    {"t": "**Personality & SOUL.md** \u2014 `SOUL.md` is **slot #1 of the system prompt** \u2014 the agent's identity; loaded only from `~/.hermes` so it stays predictable; `/personality` presets (teacher, technical, creative, pirate\u2026) as session overlays. Rule of thumb: **SOUL.md = who the agent is; AGENTS.md = how the project works**", "size": 14.5},
    {"t": "**Image & video generation** \u2014 **image generation built in** via FAL.ai (11 models: FLUX 2, GPT-Image, Ideogram V3, Recraft V4\u2026); **video generation** via skills & integrations (e.g. Higgsfield UGC ad studio) \u2014 the same tool-extensibility story as MCP", "size": 14.5},
], kicker="Part 2 \u00B7 Hermes", default_size=14.5)
ref = txt(s, Inches(0.92), Inches(6.8), Inches(11.6), Inches(0.3), [])
tf = ref.text_frame
tf.word_wrap = True
p0 = tf.paragraphs[0]
r = p0.add_run()
r.text = "Docs: hermes-agent.nousresearch.com/docs/user-guide/features (LSP \u00B7 Curator \u00B7 Personality \u00B7 Image Generation)"
r.font.size = Pt(10.5); r.font.name = FONT; r.font.color.rgb = GRAY
r = p0.add_run()
r.text = ""
r.hyperlink.address = "https://hermes-agent.nousresearch.com/docs/user-guide/features/overview"

# ================= SLIDE 14: HERMES PERSISTENT MEMORY =================
bullets_slide("Hermes Persistent Memory", [
    {"t": "**Two curated files** \u2014 `MEMORY.md` (agent's notes: environment, conventions, lessons \u2014 2,200 chars) + `USER.md` (your profile: preferences, style \u2014 1,375 chars), stored in `~/.hermes/memories/`", "size": 14.5},
    {"t": "**Frozen snapshot** \u2014 injected into the system prompt once at session start (preserves the prefix cache); the `memory` tool (**add / replace / remove**) writes through to disk immediately \u2014 visible next session", "size": 14.5},
    {"t": "**Bounded by design** \u2014 hard char limits; when full, the agent **consolidates entries in the same turn**; duplicates rejected; every entry scanned for injection / exfiltration (it lands in the system prompt)", "size": 14.5},
    {"t": "**`session_search`** \u2014 FTS5 full-text search over **all past sessions** (SQLite), free \u2014 no LLM call. Memory = key facts always in context; session search = on-demand \u201Cdid we discuss X last week?\u201D", "size": 14.5},
    {"t": "**Consent controls** \u2014 `write_approval` stages saves for review (`/memory pending`); the background self-improvement review saves lessons post-turn; `/journey` shows the learning timeline", "size": 14.5},
], kicker="Part 2 \u00B7 Hermes", default_size=14.5)

# ================= SLIDE 15: HONCHO MEMORY =================
bullets_slide("Honcho Memory: Dialectic User Modeling", [
    {"t": "**Beyond key-value memory** \u2014 Honcho is an AI-native memory backend (a memory-provider plugin) that **reasons about conversations after they happen**, building a running model of who the user is \u2014 preferences, goals, patterns", "size": 14.5},
    {"t": "**Dialectic reasoning** \u2014 after each turn (cadence-gated), Honcho derives insights; optional **multi-pass depth (1\u20133): assess \u2192 self-audit \u2192 reconcile**; conclusions accumulate server-side", "size": 14.5},
    {"t": "**Two-layer context injection** \u2014 base context (session summary + user representation + peer card) refreshed per turn, plus the dialectic supplement \u2014 \u201Cwhat matters right now\u201D", "size": 14.5},
    {"t": "**Multi-agent isolation** \u2014 per-peer profiles: your coding assistant and your personal assistant each see only their own observations \u2014 **no cross-contamination**", "size": 14.5},
    {"t": "**One of 8 memory providers** \u2014 Honcho, Mem0, Hindsight, Supermemory, OpenViking, RetainDB, ByteRover, Holographic \u2014 all run **alongside** built-in memory, never replace it; setup: `hermes memory setup`", "size": 14.5},
], kicker="Part 2 \u00B7 Hermes \u00B7 Memory Providers", default_size=14.5)

# ================= SLIDE 16: HERMES PLUGINS =================
bullets_slide("Hermes Plugins: Extend Everything", [
    {"t": "**Drop-in extensibility** \u2014 a directory in `~/.hermes/plugins/` with `plugin.yaml` + a `register(ctx)` \u2014 your tools appear alongside built-ins, no core-code changes", "size": 14.5},
    {"t": "**Wide surface** \u2014 tools, **27 lifecycle hooks** (pre/post tool call, kanban events\u2026), slash + CLI commands, bundled skills, gateway platforms, **image-gen & video-gen backends**, memory providers, context engines, model providers, approval transports, MCP calls", "size": 14.5},
    {"t": "**Four plugin types** \u2014 general (multi-select) \u00B7 memory providers (one active) \u00B7 context engines (one active) \u00B7 model providers (pick one)", "size": 14.5},
    {"t": "**Opt-in by default** \u2014 third-party plugins never run until allow-listed (`plugins.enabled`); bundled infrastructure loads automatically", "size": 14.5},
    {"t": "**Supply-chain security** \u2014 install-time static scanning (safe / caution / **dangerous = blocked**), SHA-pinned installs + curated catalog, **capability consent** with re-consent on update \u2014 the OWASP posture from Part 5", "size": 14.5},
], kicker="Part 2 \u00B7 Hermes", default_size=14.5)

# ================= PART 3 =================
divider(L_DIV_O, "3", "NanoClaw \u2014 the Edge Layer",
        "Running agents on Raspberry Pi\u2013class hardware \u2014 and what you give up versus the cloud.",
        "45 min")
two_col_slide("NanoClaw: Agents at the Edge",
    "Pi-class hardware constraints", [
        {"t": "**Memory** \u2014 tight RAM budgets force small models"},
        {"t": "**Quantization** \u2014 Hermes runs as a quantized build to fit"},
        {"t": "**Latency** \u2014 on-device inference trades speed for independence"},
        {"t": "**Demo:** deploy a slimmed-down OpenClaw + Hermes agent on NanoClaw"},
    ],
    "Edge vs cloud-hosted (Bedrock / Claude)", [
        {"t": "**Edge wins:** privacy, offline operation, no per-call cost, data stays on device"},
        {"t": "**Cloud wins:** model quality, throughput, zero hardware management"},
        {"t": "This trade-off returns in **Part 6** \u2014 voice latency budgets force the cloud-vs-local choice"},
        {"t": "And in **Part 4** \u2014 edge connectivity breaks naive heartbeat assumptions"},
    ],
    kicker="Part 3 \u00B7 NanoClaw")

# ================= PART 4 =================
divider(L_DIV_G, "4", "Heartbeat Mechanisms \u2014 Deep Dive",
        "Liveness, readiness and health for agents \u2014 including edge agents on unreliable networks.",
        "60 min")
bullets_slide("4.1  Three Signals That Are Often Conflated", [
    {"t": "**Liveness** \u2014 is the process running at all?", "size": 17.5},
    {"t": "**Readiness** \u2014 can it currently accept work?", "size": 17.5},
    {"t": "**Health** \u2014 is it running within acceptable performance / error bounds?", "size": 17.5},
    {"t": "A process can be alive but not ready, or ready but unhealthy \u2014 your detection design must say which signal it actually tracks.", "bullet": False, "italic": True, "color": GRAY, "size": 14.5, "space_before": 12},
], kicker="Part 4 \u00B7 Heartbeats")
two_col_slide("4.1  Push vs Pull Heartbeats",
    "PUSH \u2014 agent pings orchestrator", [
        {"t": "Agent proactively sends heartbeats on an interval"},
        {"t": "**+** Lower orchestrator load"},
        {"t": "**\u2212** Agent must stay well-behaved; a hung agent that keeps beating looks alive"},
    ],
    "PULL \u2014 orchestrator polls agent", [
        {"t": "Orchestrator actively checks each agent"},
        {"t": "**+** Simpler, more trustworthy failure detection"},
        {"t": "**\u2212** Scales worse as agent count grows"},
    ],
    kicker="Part 4 \u00B7 Heartbeats")
bullets_slide("4.1  Interval & TTL Design", [
    {"t": "**Too frequent** \u2192 noisy streams, wasted Redis throughput", "size": 16.5},
    {"t": "**Too infrequent** \u2192 slow failure detection, stale work assignment", "size": 16.5},
    {"t": "**Rule of thumb: TTL \u2248 2\u20133\u00D7 the heartbeat interval**, tuned to the cost of reassigning work", "size": 17, "color": BLUE, "space_before": 8},
    {"t": "Cheap reassignment \u2192 shorter TTL, faster detection", "lvl": 1},
    {"t": "Expensive reassignment \u2192 longer TTL, tolerate transient misses", "lvl": 1},
], kicker="Part 4 \u00B7 Heartbeats")
bullets_slide("4.2  OpenClaw-Specific Mechanics", [
    {"t": "**Transport:** dedicated Redis Stream per agent, or a **TTL'd key per agent** that expires if not refreshed", "size": 16},
    {"t": "**Detection loop (orchestrator side):** identify a dead / unreachable agent \u2192 trigger reassignment of its work", "size": 16},
    {"t": "**Flapping agents need debounce logic:**", "size": 16, "space_before": 8},
    {"t": "Require **N consecutive misses** before declaring an agent \u201Cdown\u201D", "lvl": 1},
    {"t": "Single-miss detection causes **thrashing** \u2014 agents oscillate between up/down and work gets needlessly reassigned", "lvl": 1},
], kicker="Part 4 \u00B7 Heartbeats")
bullets_slide("4.3  Edge Case: NanoClaw Agents", [
    {"t": "**Intermittent connectivity** on Pi-class hardware breaks naive heartbeat assumptions", "size": 16},
    {"t": "**Exponential backoff** on reconnect attempts \u2014 don't hammer the orchestrator after a dropout", "size": 16},
    {"t": "**Last-known-state caching** \u2014 the orchestrator doesn't prematurely kill / reassign work during a transient blip", "size": 16},
    {"t": "**The core trade-off:**", "size": 16, "space_before": 8},
    {"t": "**Aggressive detection** \u2192 fast reassignment, but more false positives", "lvl": 1},
    {"t": "**Lenient detection** \u2192 fewer false positives, but slower recovery", "lvl": 1},
], kicker="Part 4 \u00B7 Heartbeats")
bullets_slide("4.4  Hands-On Lab: Kill and Detect", [
    {"t": "**1.** Write an agent process that pushes a heartbeat entry every **N** seconds", "size": 16},
    {"t": "**2.** Write an orchestrator loop that flags an agent \u201Cdown\u201D after **M** consecutive missed beats", "size": 16},
    {"t": "**3.** Kill the agent process mid-session and **measure detection time**", "size": 16},
    {"t": "**4.** Adjust N and M, re-test \u2014 discuss the resulting **trade-off curve**", "size": 16},
    {"t": "Discussion: what N / M values would you choose for a **cloud-hosted agent** vs a **NanoClaw edge agent** \u2014 and why?", "bullet": False, "bold": True, "color": BLUE, "size": 15, "space_before": 12},
], kicker="Part 4 \u00B7 Lab")

# ================= PART 5 =================
divider(L_DIV_S, "5", "Skill Writing \u2014 Deep Dive",
        "Skills are the agent's capabilities \u2014 and the description is the interface, not documentation.",
        "60 min")
bullets_slide("5.1  Anatomy of a Skill", [
    {"t": "Every skill has **two halves:**", "size": 16.5},
    {"t": "**Metadata** \u2014 name, description, trigger conditions", "lvl": 1, "size": 16},
    {"t": "**Execution logic** \u2014 the code that actually runs", "lvl": 1, "size": 16},
    {"t": "\u201CThe description is not documentation \u2014 it is **the interface the agent's tool-selection step reads**.\u201D", "bullet": False, "size": 19, "bold": True, "color": ORANGE, "space_before": 16},
    {"t": "If the description is wrong, the skill may never fire \u2014 no matter how good the code is.", "bullet": False, "italic": True, "color": GRAY, "size": 14.5, "space_before": 8},
], kicker="Part 5 \u00B7 Skills")
s = content_slide(L_BULLETS, "5.2  Writing for Discoverability", "Part 5 \u00B7 Skills")
drop_ph(s, 11)
box(s, Inches(0.92), Inches(1.62), Inches(5.6), Inches(2.5), fill=RED_BG,
    shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
txt(s, Inches(1.22), Inches(1.85), Inches(5.05), Inches(2.1), [
    {"t": "BAD", "size": 13, "bold": True, "color": RED_TX, "bullet": False},
    {"t": "\u201CHandles data stuff\u201D", "size": 20, "bold": True, "color": RED_TX, "bullet": False, "space_before": 6},
    {"t": "Vague descriptions cause **missed or misfired** skill invocations.", "size": 13.5, "color": INK, "bullet": False, "space_before": 8},
])
box(s, Inches(6.85), Inches(1.62), Inches(5.6), Inches(2.5), fill=GRN_BG,
    shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
txt(s, Inches(7.15), Inches(1.85), Inches(5.05), Inches(2.1), [
    {"t": "GOOD", "size": 13, "bold": True, "color": GRN_TX, "bullet": False},
    {"t": "\u201CFetches current weather for a given city and date; use only when the user asks about weather conditions, not climate history.\u201D", "size": 15, "bold": True, "color": GRN_TX, "bullet": False, "space_before": 6},
    {"t": "Specific scope + explicit **when-to-use / when-not-to-use** boundaries.", "size": 13.5, "color": INK, "bullet": False, "space_before": 8},
])
txt(s, Inches(0.92), Inches(4.45), Inches(11.6), Inches(2.2), [
    {"t": "**Exercise:** critique 3\u20134 deliberately weak skill descriptions and rewrite them.", "size": 16},
    {"t": "A good description names the action, the inputs, and the boundaries of when it applies.", "size": 14.5, "color": GRAY, "bullet": False, "space_before": 6},
])
bullets_slide("5.3  Security Angle (OWASP Agentic Applications)", [
    {"t": "**Sandboxing execution** \u2014 isolate skill code so a malicious or buggy skill can't escalate privileges", "size": 16},
    {"t": "**Input validation** \u2014 validate **agent-generated parameters** before execution (the model is an untrusted caller)", "size": 16},
    {"t": "**Output validation** \u2014 sanitize skill output **before it re-enters the agent's context / loop**", "size": 16},
    {"t": "Reference: **OWASP Agentic Applications Cheat Sheet**", "bullet": False, "italic": True, "color": GRAY, "size": 14, "space_before": 12},
], kicker="Part 5 \u00B7 Skills")
bullets_slide("5.4  Hands-On Lab: Make It Fire (and Only When It Should)", [
    {"t": "**1.** Write a simple skill (e.g. a unit converter) with a clear description", "size": 16},
    {"t": "**2.** Register it and confirm **correct invocation** on a matching prompt", "size": 16},
    {"t": "**3.** \u201CVague-ify\u201D the description and re-test \u2014 observe **misfire / no-invoke**", "size": 16},
    {"t": "**4.** Restore the description, add basic **input validation**, try an adversarial input \u2014 confirm rejection", "size": 16},
], kicker="Part 5 \u00B7 Lab")

# ================= PART 6 =================
divider(L_DIV_B, "6", "Channel Integration \u2014 Messaging & Voice",
        "Telegram, WhatsApp and voice: getting real users connected to your agents \u2014 and handling each channel's failure modes.",
        "60 min")
bullets_slide("6.1  Messaging Channels: Telegram & WhatsApp", [
    {"t": "**Webhook vs long-polling ingestion** \u2014 how an inbound message becomes an event on the OpenClaw Redis Stream", "size": 15.5},
    {"t": "**Session mapping** \u2014 map chat / session ID \u2192 agent instance so multi-turn conversation state stays coherent", "size": 15.5},
    {"t": "**Channel-specific quirks** \u2014 message length limits, rich media (images, voice notes sent as files), delivery / read receipts", "size": 15.5},
    {"t": "**Rate limits** \u2014 both platforms throttle aggressively; send replies with retry / backoff", "size": 15.5},
    {"t": "**Demo:** inbound Telegram message \u2192 OpenClaw agent \u2192 skill invocation \u2192 reply back to the same chat", "size": 15.5, "color": BLUE, "space_before": 8},
], kicker="Part 6 \u00B7 Channels", default_size=15.5)
bullets_slide("6.2  Voice Channels", [
    {"t": "**Two integration patterns:**", "size": 16},
    {"t": "**Turn-based:** record \u2192 transcribe \u2192 agent \u2192 synthesize \u2192 play", "lvl": 1, "size": 15.5},
    {"t": "**Streaming:** continuous ASR / TTS with **barge-in** support", "lvl": 1, "size": 15.5},
    {"t": "**ASR / TTS sit outside Hermes** \u2014 transcription happens before the model call, synthesis after; the agent still reasons over text", "size": 16, "space_before": 6},
    {"t": "**Latency budget** \u2014 voice has a much tighter round-trip tolerance than messaging; this drives the **cloud vs NanoClaw-local inference** choice", "size": 16},
    {"t": "**Interruptions / barge-in and silence detection** \u2014 a UX problem, not just a technical one", "size": 16},
    {"t": "**Demo / walkthrough:** a short voice round-trip through the same OpenClaw agent from the messaging demo", "size": 15, "color": BLUE, "space_before": 6},
], kicker="Part 6 \u00B7 Channels", default_size=15.5)
bullets_slide("6.3  Channel Abstraction in OpenClaw", [
    {"t": "Channels are a **thin adapter layer**, not baked into agent logic \u2014 the agent shouldn't know if it's talking to Telegram, WhatsApp, or a mic", "size": 16},
    {"t": "**Normalize inbound events** (text, voice-transcribed-to-text, media) into **one internal message format** before they hit the Redis Stream", "size": 16},
    {"t": "**Intersection with heartbeats (Part 4):** the channel adapter itself needs liveness tracking \u2014 a dead webhook listener is as bad as a dead agent", "size": 16},
], kicker="Part 6 \u00B7 Channels")
bullets_slide("6.4  Hands-On Lab: Wire a Channel", [
    {"t": "**1.** Wire one messaging channel (Telegram or WhatsApp sandbox / test account) to your Part 1 OpenClaw agent", "size": 16},
    {"t": "**2.** Send a message that triggers the Part 5 skill; confirm the **reply round-trips** correctly", "size": 16},
    {"t": "**3.** Discuss: what would need to change to add a **second channel** without touching agent logic?", "size": 16},
], kicker="Part 6 \u00B7 Lab")

# ================= PART 7 =================
divider(L_DIV_T, "7", "A2A Setup \u2014 a One-of-its-Kind Protocol",
        "Designing a custom agent-to-agent protocol that is natively stream-based, heartbeat-aware and channel-agnostic.",
        "60 min")
bullets_slide("7.1  Why Not Just Use an Off-the-Shelf A2A Standard?", [
    {"t": "**The emerging A2A landscape:** agent-card discovery, task-based request / response protocols", "size": 15.5},
    {"t": "They assume infrastructure OpenClaw doesn't need: **HTTP-centric, synchronous request / response**", "size": 15.5},
    {"t": "**OpenClaw's differentiator: Redis Streams as the transport**", "size": 16.5, "color": BLUE, "space_before": 8},
    {"t": "Durable, replayable, multi-consumer messaging **for free** \u2014 most A2A protocols bolt this on top of plain HTTP", "lvl": 1},
    {"t": "**Design goal:** an A2A layer that is natively **stream-based**, **heartbeat-aware** (Part 4) and **channel-agnostic** (Part 6) \u2014 not a generic point-to-point RPC", "size": 15.5, "space_before": 8},
], kicker="Part 7 \u00B7 A2A", default_size=15.5)
bullets_slide("7.2  Anatomy of the Custom Protocol", [
    {"t": "**Message envelope:** sender agent ID \u00B7 recipient agent ID (or broadcast topic) \u00B7 task ID \u00B7 payload \u00B7 **correlation ID** for multi-turn task tracking", "size": 15},
    {"t": "**Stream topology:** one stream per agent inbox **vs** shared topic streams with consumer groups", "size": 15},
    {"t": "**Fan-out** (broadcast to many agents) vs **fan-in** (many agents reporting to one orchestrator) trade-offs", "lvl": 1},
    {"t": "**Task lifecycle states:** proposed \u2192 accepted \u2192 in-progress \u2192 completed / failed", "size": 15, "space_before": 6},
    {"t": "Mirrored as stream entries \u2014 any consumer can **reconstruct task history from the stream itself** (replayability as a debugging feature)", "lvl": 1},
    {"t": "**Key difference:** typical A2A treats discovery & negotiation as separate from transport; here they're **unified \u2014 the stream itself is the source of truth**", "size": 15, "color": BLUE, "space_before": 6},
], kicker="Part 7 \u00B7 A2A", default_size=15)
bullets_slide("7.3  Integrating Heartbeats and Skills into A2A", [
    {"t": "**Reuse the Part 4 heartbeat stream as a capability-advertisement channel**", "size": 16},
    {"t": "The heartbeat payload includes which **skills (Part 5)** the agent currently has registered \u2192 the orchestrator's routing decision uses **one lookup instead of two**", "lvl": 1},
    {"t": "**Routing logic:**", "size": 16, "space_before": 8},
    {"t": "Incoming task \u2192 match required skill \u2192 find agents advertising that skill \u2192 filter to agents with a **live heartbeat** \u2192 dispatch", "lvl": 1},
    {"t": "**Failure handling unique to this design:** tasks live on a replayable stream, so a newly-spun-up agent (or a recovering NanoClaw device) **catches up on missed assignments by re-reading from its last acknowledged offset**", "size": 16, "space_before": 8},
], kicker="Part 7 \u00B7 A2A")
bullets_slide("7.4  Hands-On Lab: Kill, Restart, Resume", [
    {"t": "**1.** Define the **message envelope schema** for the custom A2A protocol", "size": 16},
    {"t": "**2.** Implement a two-agent exchange: Agent A proposes a task; Agent B accepts and reports progress via stream entries", "size": 16},
    {"t": "**3.** Kill and restart Agent B **mid-task** \u2014 confirm it resumes from the stream rather than losing task state", "size": 16},
    {"t": "**4.** Discuss: what would break if you swapped this for a standard **synchronous** A2A protocol? What would you lose \u2014 and what would you gain?", "size": 16},
], kicker="Part 7 \u00B7 Lab")

# ================= COMBINED LAB =================
s = content_slide(L_BULLETS, "Combined Lab: End-to-End Channel-to-Skill Flow",
                  "20 min \u00B7 ties all 7 parts together")
drop_ph(s, 11)
txt(s, Inches(0.92), Inches(1.5), Inches(11.6), Inches(0.95), [
    {"t": "**Goal:** a message (or voice input) arrives over a real channel \u2192 routed via the custom A2A protocol to a NanoClaw edge agent running Hermes \u2192 invokes a registered skill \u2014 while the OpenClaw orchestrator only dispatches to agents with **healthy heartbeats** advertising the **right capability**.",
     "size": 14, "bullet": False}])
flow = [("Channel message", TURQ, DK_ON_BRIGHT), ("A2A routing", DBLUE, WHITE),
        ("Healthy edge agent", GREY, WHITE), ("Skill invocation", ORANGE, DK_ON_BRIGHT),
        ("Reply on same channel", TURQ, DK_ON_BRIGHT)]
x = Inches(0.92)
for i, (t_, c, tc) in enumerate(flow):
    chip(s, x, Inches(2.6), Inches(2.05), Inches(0.8), t_, c, tcolor=tc, size=12)
    if i < 4:
        arrow(s, x + Inches(2.09), Inches(2.83), w=Inches(0.3), h=Inches(0.3))
    x += Inches(2.42)
txt(s, Inches(0.92), Inches(3.8), Inches(11.6), Inches(3.0), [
    {"t": "**1.** Confirm your Part 6 channel-wired agent is the same NanoClaw + Hermes agent from Part 3 \u2014 with the Part 5 skill, Part 4 heartbeat producer and Part 7 A2A envelope handling in place", "size": 14},
    {"t": "**2.** Send a channel message that requires the skill to be invoked", "size": 14},
    {"t": "**3.** Orchestrator uses Part 7 routing (skill match + live heartbeat) to select and dispatch to the edge agent", "size": 14},
    {"t": "**4.** Simulate the edge agent going down mid-task \u2014 confirm the orchestrator reroutes / queues, and a recovering agent resumes from the stream", "size": 14},
    {"t": "**5.** Discuss: how does replayability change \u201Cwhat happens to an in-flight task\u201D \u2014 and how does that surface to the user over **messaging vs voice** differently?", "size": 14},
], space_after=7)

# ================= WRAP-UP =================
s = content_slide(L_BULLETS, "Wrap-Up: The Seven-Layer Story", "Recap")
drop_ph(s, 11)
recap = [("OpenClaw", "orchestration", DBLUE, WHITE), ("Hermes", "model", TURQ, DK_ON_BRIGHT),
         ("NanoClaw", "edge", ORANGE, DK_ON_BRIGHT), ("Heartbeats", "trust in state", GREY, WHITE),
         ("Skills", "trust in capability", GREY, WHITE), ("Channels", "trust in delivery", GREY, WHITE),
         ("Custom A2A", "trust in coordination", GREY, WHITE)]
x = Inches(0.92)
for name, tag, c, tc in recap:
    chip(s, x, Inches(1.66), Inches(1.5), Inches(0.95), name, c, tcolor=tc, size=11.5,
         sub=tag, sub_color=tc)
    if x < Inches(10.4):
        arrow(s, x + Inches(1.52), Inches(1.99), w=Inches(0.16), h=Inches(0.28), color=GRAY)
    x += Inches(1.67)
txt(s, Inches(0.92), Inches(3.1), Inches(11.6), Inches(3.4), [
    {"t": "**Open Q&A**", "size": 16.5},
    {"t": "**Stretch topics for advanced learners:**", "size": 16.5, "space_before": 12},
    {"t": "A combined **health + capability registry** so orchestrator routing uses one signal instead of two (foreshadowed in 7.3)", "lvl": 1},
    {"t": "**Streaming voice with barge-in** as a follow-up deep dive", "lvl": 1},
    {"t": "**Benchmarking the custom A2A protocol** against a standard synchronous A2A implementation", "lvl": 1},
])

# ================= MATERIALS =================
bullets_slide("Materials Checklist", [
    {"t": "**Redis instance** (local or shared) \u2014 orchestration, heartbeat and A2A stream labs"},
    {"t": "**NanoClaw device** or Pi-class emulation environment"},
    {"t": "**Hermes model weights** \u2014 quantized build suitable for the edge demo"},
    {"t": "**Starter OpenClaw agent scaffold** with Redis Streams + MCP pre-wired"},
    {"t": "**3\u20134 deliberately weak skill descriptions** for the critique exercise"},
    {"t": "**Telegram and/or WhatsApp sandbox / test account** with webhook access"},
    {"t": "**Basic ASR / TTS setup** (cloud API or local model) for the voice demo"},
    {"t": "Reference: **OWASP Agentic Applications Cheat Sheet**"},
    {"t": "Reference: **overview of at least one standard A2A protocol spec** (for the Part 7.1 comparison)"},
], kicker="Setup", default_size=15.5)

# ================= APPENDIX =================
divider(L_DIV_G, None, "Technical Appendix",
        "Configuring A2A + Hermes with LangGraph \u2014 implementation-level detail for learners who want to build past the guided demo.",
        "Instructor reference / handout")
bullets_slide("A.1  Why LangGraph Fits Here", [
    {"t": "Each OpenClaw agent's internal reasoning loop \u2014 **receive task \u2192 call Hermes \u2192 optionally invoke a skill / tool \u2192 respond** \u2014 maps naturally onto a LangGraph **StateGraph**", "size": 15},
    {"t": "Nodes: \u201Ccall model\u201D, \u201Cinvoke skill\u201D, \u201Cawait tool result\u201D", "lvl": 1},
    {"t": "Edges: conditional routing based on whether Hermes emitted a tool call", "lvl": 1},
    {"t": "LangGraph's built-in **checkpointer** lines up with the Part 7.2 task lifecycle (proposed \u2192 accepted \u2192 in-progress \u2192 completed / failed)", "size": 15, "space_before": 8},
    {"t": "A checkpoint after each node execution gives the same **replayability** benefit as reading task state back from the Redis Stream", "lvl": 1},
], kicker="Appendix \u00B7 LangGraph")
bullets_slide("A.2  Wiring Hermes into a LangGraph Node", [
    {"t": "Hermes isn't a first-party LangChain / LangGraph integration \u2192 serve it behind an **OpenAI-compatible endpoint** (vLLM, or Ollama / TGI exposing `/v1/chat/completions`)", "size": 15},
    {"t": "Bind it via **ChatOpenAI-style config** pointed at that local endpoint", "size": 15},
    {"t": "Confirm Hermes' tool-calling output matches what LangGraph expects (**OpenAI-style `tool_calls`**) \u2014 this is the thing **most likely to need a translation shim**", "size": 15},
    {"t": "Bind Part 5 skills to the graph as **LangGraph tools** \u2014 the tool's `description` field is exactly the skill description from 5.2; **the same discoverability rules apply**", "size": 15},
], kicker="Appendix \u00B7 LangGraph")
bullets_slide("A.3  Connecting the Graph to the Redis Streams Transport", [
    {"t": "The graph handles **a single agent's internal turn**; the Part 7.2 envelope (sender, recipient, task ID, payload, correlation ID) becomes the **input state** that triggers a graph invocation, and the **output state** serialized back onto the outbound stream", "size": 14.5},
    {"t": "**Pattern:** a thin consumer loop reads new entries from the agent's inbox stream \u2192 maps each to a LangGraph input state \u2192 invokes the graph \u2192 writes the result back as a new stream entry (status update or final response)", "size": 14.5},
    {"t": "The graph **doesn't need to know about Redis at all** \u2014 the two concerns stay cleanly separated", "size": 14.5},
    {"t": "Use the checkpointer with a **Redis-backed implementation** so an in-progress task's graph state survives an agent restart \u2014 the 7.3 \u201Crecovering agent resumes from stream offset\u201D behaviour now also resumes **mid-graph-execution**, not just mid-task", "size": 14.5},
], kicker="Appendix \u00B7 LangGraph", default_size=14.5)
bullets_slide("A.4  Heartbeats & Capability Advertisement from Inside the Graph", [
    {"t": "The graph **doesn't own the heartbeat loop** \u2014 keep heartbeat emission (Part 4) as a **separate lightweight process** alongside the graph consumer, not a graph node", "size": 15},
    {"t": "It must keep beating even while the graph is mid-execution on a long task", "lvl": 1},
    {"t": "The heartbeat process can **introspect the graph's currently-bound tools** to build the capability-advertisement payload from 7.3", "size": 15, "space_before": 8},
    {"t": "Skill registration stays a **single source of truth** (the graph's tool list) rather than a separately maintained config", "lvl": 1},
], kicker="Appendix \u00B7 LangGraph")
bullets_slide("A.5  Suggested Demo / Lab Extension", [
    {"t": "**1.** Stand up Hermes behind an OpenAI-compatible local endpoint", "size": 15.5},
    {"t": "**2.** Build a two-node LangGraph (model call \u2192 conditional tool invocation) using one Part 5 skill as a bound tool", "size": 15.5},
    {"t": "**3.** Wrap it with the thin Redis Streams consumer / producer loop from A.3", "size": 15.5},
    {"t": "**4.** Re-run the Part 7.4 kill-and-resume test \u2014 confirm the **LangGraph checkpoint** (not just the task ID) is what allows correct resumption", "size": 15.5},
    {"t": "**5.** Compare latency / complexity against the **framework-free** agent loop built in the main Part 7 lab", "size": 15.5},
], kicker="Appendix \u00B7 LangGraph")

# ================= CLOSING =================
s = add(L_END)
txt(s, Inches(1.5), Inches(2.15), Inches(10.33), Inches(1.0),
    [{"t": "Thank You \u2014 Questions?", "size": 40, "bold": True, "color": BLUE,
      "bullet": False, "align": PP_ALIGN.CENTER}])
txt(s, Inches(1.5), Inches(4.5), Inches(10.33), Inches(1.2),
    [{"t": "Take-home extensions: the four independent labs (heartbeat producer/consumer, skill critique-and-rewrite, channel wiring, A2A message envelope) + a follow-up review session.",
      "size": 14, "color": GRAY, "bullet": False, "align": PP_ALIGN.CENTER}])

prs.save(OUT)
print("Saved:", OUT, "| slides:", len(prs.slides._sldIdLst))
