"""
Polderstad -> Redshift material builder (used by polderstad_houdini_scene.py)
Built for Houdini 20.5.613 and Redshift 2025.6.

One Redshift Standard Material per part (wall, roof, glass, road, foliage ...):
    base colour  = the game colour (Cd), or a texture (optionally tinted by the game colour)
    roughness    = 0.35 by default (glass and water start glossier), or a texture
    metalness / transmission / emission sliders, normal map or bump/height map, texture size in metres.
The Polderstad export writes box-projected UVs (1 UV unit = 1 metre), so tileable textures just work.
"""
import os
import re
import sys

import hou

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# Per-part starting values. Everything else starts at the requested defaults (roughness 0.35, metalness 0).
PART_DEFAULTS = {
    "glass":     {"roughness": 0.05, "transmission": 0.85, "thin": 1},
    "water":     {"roughness": 0.04},
    "solar":     {"roughness": 0.15, "metalness": 0.4},
    "metal":     {"metalness": 1.0},
    "lamp":      {"emission": 0.0},
}

# Texture slots: (parm name, label, filename keywords for "Load texture set...", colour space)
TEX_SLOTS = [
    ("basecolor_tex", "Base Colour", ("basecolor", "base_color", "albedo", "diffuse", "diff", "color", "colour", "col"), "sRGB - Texture"),
    ("roughness_tex", "Roughness", ("roughness", "rough", "rgh"), "Raw"),
    ("metalness_tex", "Metalness", ("metalness", "metallic", "metal", "mtl"), "Raw"),
    ("normal_tex", "Normal Map", ("normal", "nrm", "norm", "nor"), "Raw"),
    ("bump_tex", "Bump / Height", ("height", "bump", "disp", "displacement", "hgt"), "Raw"),
]
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".tx", ".rstexbin", ".tga", ".bmp", ".hdr")

CALLBACK = 'import sys; sys.path.insert(0, r"%s"); import polderstad_materials as P; P.%s(kwargs["node"])'


# ───────────────────────── helpers ─────────────────────────
def _unique(parent, name):
    n, i = name, 2
    while parent.node(n):
        n = "%s%d" % (name, i)
        i += 1
    return n


def _expr(parm, text):
    parm.setExpression(text, hou.exprLanguage.Hscript)


def _ref(parm, src_parm):
    """Channel-reference parm to src_parm (works for float and string parms)."""
    parm.set(src_parm)


# ───────────────────────── material builder ─────────────────────────
def _add_spare_parms(builder, part):
    d = PART_DEFAULTS.get(part, {})
    g = builder.parmTemplateGroup()
    look = hou.FolderParmTemplate("polder_look", "Look", folder_type=hou.folderType.Tabs)
    look.addParmTemplate(hou.LabelParmTemplate("polder_info", "Part", column_labels=["Polderstad part: %s" % part]))
    look.addParmTemplate(hou.FloatParmTemplate("tint", "Tint", 3, default_value=(1, 1, 1), look=hou.parmLook.ColorSquare, naming_scheme=hou.parmNamingScheme.RGBA,
                                               help="Multiplies the final base colour (game colour or texture)."))
    look.addParmTemplate(hou.FloatParmTemplate("roughness", "Roughness", 1, default_value=(d.get("roughness", 0.35),), min=0, max=1))
    look.addParmTemplate(hou.FloatParmTemplate("metalness", "Metalness", 1, default_value=(d.get("metalness", 0.0),), min=0, max=1))
    look.addParmTemplate(hou.FloatParmTemplate("transmission", "Transmission", 1, default_value=(d.get("transmission", 0.0),), min=0, max=1,
                                               help="Refraction weight (glass)."))
    look.addParmTemplate(hou.ToggleParmTemplate("thin_walled", "Thin Walled", default_value=bool(d.get("thin", 0))))
    look.addParmTemplate(hou.FloatParmTemplate("emission", "Emission", 1, default_value=(d.get("emission", 0.0),), min=0, max=10,
                                               help="Emission weight; the emission colour is the base colour."))
    tex = hou.FolderParmTemplate("polder_tex", "Textures", folder_type=hou.folderType.Tabs)
    tex.addParmTemplate(hou.ButtonParmTemplate("load_texture_set", "Load Texture Set...", script_callback=CALLBACK % (HERE.replace("\\", "/"), "load_texture_set"),
                                               script_callback_language=hou.scriptLanguage.Python,
                                               help="Pick one image of a texture set; base colour / roughness / metalness / normal / height maps next to it are found by name."))
    tex.addParmTemplate(hou.ButtonParmTemplate("clear_textures", "Clear Textures", script_callback=CALLBACK % (HERE.replace("\\", "/"), "clear_textures"),
                                               script_callback_language=hou.scriptLanguage.Python))
    for parm, label, _, _ in TEX_SLOTS:
        tex.addParmTemplate(hou.StringParmTemplate(parm, label, 1, string_type=hou.stringParmType.FileReference, file_type=hou.fileType.Image))
    tex.addParmTemplate(hou.ToggleParmTemplate("tex_tint_by_game_color", "Tint Base Texture by Game Colour", default_value=False,
                                               help="One neutral brick/plaster texture, coloured per house by the game colour."))
    tex.addParmTemplate(hou.FloatParmTemplate("tex_size", "Texture Size (m)", 1, default_value=(2.0,), min=0.05, max=20,
                                              help="Real-world size of one texture tile. The UVs are in metres."))
    tex.addParmTemplate(hou.FloatParmTemplate("tex_rotate", "Texture Rotate", 1, default_value=(0.0,), min=-180, max=180))
    tex.addParmTemplate(hou.FloatParmTemplate("normal_strength", "Normal Strength", 1, default_value=(1.0,), min=0, max=3))
    tex.addParmTemplate(hou.FloatParmTemplate("bump_strength", "Bump Strength", 1, default_value=(0.3,), min=0, max=3,
                                              help="Used when only a bump/height map is set (a normal map wins when both are set)."))
    g.append(look)
    g.append(tex)
    builder.setParmTemplateGroup(g)


def _sampler(b, name, slot, colorspace, ctrl):
    t = b.createNode("redshift::TextureSampler", name)
    _ref(t.parm("tex0"), b.parm(slot))
    t.parm("tex0_colorSpace").set(colorspace)
    for p in ("scale1", "scale2"):
        _expr(t.parm(p), '1 / max(0.001, ch("../tex_size") * ch("%s/global_tex_scale"))' % ctrl)
    _ref(t.parm("rotate"), b.parm("tex_rotate"))
    return t


def _has(slot):
    return 'strlen(chs("../%s")) > 0' % slot


def build_material(matlib, part, ctrl, color_attr="Cd"):
    b = matlib.createNode("redshift_vopnet", part)
    _add_spare_parms(b, part)
    std = b.node("StandardMaterial1") or b.createNode("redshift::StandardMaterial", "StandardMaterial1")
    out = b.node("redshift_usd_material1") or b.node("redshift_material1") or b.createNode("redshift_usd_material", "redshift_usd_material1")  # Solaris / classic output node
    std.setName("standard_material", unique_name=True)
    out.setNamedInput("Surface", std, "outColor")

    # base colour: game colour (Cd point attribute) or texture (optionally tinted by the game colour), times tint
    game = b.createNode("redshift::RSUserDataColor", "game_color")
    game.parm("attribute").set(color_attr)  # Cd from town.geo
    for c, v in zip("rgb", (0.7, 0.7, 0.7)):
        game.parm("default" + c).set(v)
    tex_base = _sampler(b, "tex_basecolor", "basecolor_tex", "sRGB - Texture", ctrl)
    tint_src = b.createNode("redshift::RSColorMix", "texture_tint_source")
    for c in "rgb":
        tint_src.parm("input1" + c).set(1.0)
    tint_src.setNamedInput("input2", game, "out")
    _ref(tint_src.parm("mixAmount"), b.parm("tex_tint_by_game_color"))
    tex_x = b.createNode("redshift::RSMathMulVector", "texture_x_tint")
    tex_x.setNamedInput("input1", tex_base, "outColor")
    tex_x.setNamedInput("input2", tint_src, "outColor")
    base_sel = b.createNode("redshift::RSColorMix", "base_select")
    base_sel.setNamedInput("input1", game, "out")
    base_sel.setNamedInput("input2", tex_x, "out")
    _expr(base_sel.parm("mixAmount"), _has("basecolor_tex"))
    tint = b.createNode("redshift::RSMathMulVector", "tint")
    tint.setNamedInput("input1", base_sel, "outColor")
    for i, c in enumerate("rgb"):
        _ref(tint.parm("input2%d" % (i + 1)), b.parm("tint" + c))
    std.setNamedInput("base_color", tint, "out")
    std.setNamedInput("emission_color", tint, "out")
    _ref(std.parm("emission_weight"), b.parm("emission"))

    # roughness / metalness: slider, or texture when one is set
    for slot, sparm, inp, name in (("roughness_tex", "roughness", "refl_roughness", "roughness"), ("metalness_tex", "metalness", "metalness", "metalness")):
        tx = _sampler(b, "tex_" + name, slot, "Raw", ctrl)
        sel = b.createNode("redshift::RSColorMix", name + "_select")
        for c in "rgb":
            _ref(sel.parm("input1" + c), b.parm(sparm))
        sel.setNamedInput("input2", tx, "outColor")
        _expr(sel.parm("mixAmount"), _has(slot))
        std.setNamedInput(inp, sel, "outColor")
        _ref(std.parm(inp), b.parm(sparm))

    _ref(std.parm("refr_weight"), b.parm("transmission"))
    _ref(std.parm("refr_thin_walled"), b.parm("thin_walled"))

    # normal map (tangent space) or bump/height map -> one Bump Map node
    tex_n = _sampler(b, "tex_normal", "normal_tex", "Raw", ctrl)
    tex_h = _sampler(b, "tex_bump", "bump_tex", "Raw", ctrl)
    bsel = b.createNode("redshift::RSColorMix", "bump_select")
    bsel.setNamedInput("input1", tex_h, "outColor")
    bsel.setNamedInput("input2", tex_n, "outColor")
    _expr(bsel.parm("mixAmount"), _has("normal_tex"))
    bump = b.createNode("redshift::BumpMap", "bump")
    bump.setNamedInput("input", bsel, "outColor")
    _expr(bump.parm("inputType"), _has("normal_tex"))
    _expr(bump.parm("scale"), 'if(%s, ch("../normal_strength"), if(%s, ch("../bump_strength") * ch("%s/global_bump_scale"), 0))' % (_has("normal_tex"), _has("bump_tex"), ctrl))
    std.setNamedInput("bump_input", bump, "out")

    b.layoutChildren()
    b.setComment("Polderstad part: %s" % part)
    return b


# ───────────────────────── texture set helpers (button callbacks) ─────────────────────────
def _slot_for(filename):
    base = os.path.splitext(os.path.basename(filename))[0].lower()
    tokens = re.split(r"[^a-z0-9]+", base)
    for parm, _, keys, _ in TEX_SLOTS[1:] + TEX_SLOTS[:1]:  # check data maps before the generic 'color'
        for k in keys:
            if k in tokens or base.endswith(k):
                return parm
    return None


def load_texture_set(node, path=None):
    """Fill the texture slots of a Polderstad material from one image of a texture set."""
    if path is None:
        path = hou.ui.selectFile(title="Pick any image of the texture set", file_type=hou.fileType.Image, pattern="*")
        if not path:
            return
    path = hou.text.expandString(path)
    folder = os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    prefix = re.split(r"[_\-. ](?:basecolor|base_color|albedo|diffuse|diff|color|colour|col|roughness|rough|metalness|metallic|metal|normal|nrm|nor|height|bump|disp)", stem, flags=re.I)[0]
    found = {}
    for f in sorted(os.listdir(folder)):
        if not f.lower().endswith(IMAGE_EXT) or (prefix and not f.lower().startswith(prefix.lower())):
            continue
        slot = _slot_for(f)
        if slot and slot not in found:
            found[slot] = os.path.join(folder, f).replace("\\", "/")
    for slot, f in found.items():
        node.parm(slot).set(f)
    if hou.isUIAvailable():
        hou.ui.setStatusMessage("Polderstad: %s -> %s" % (node.name(), ", ".join(sorted(found)) or "no maps recognised"))
    return found


def clear_textures(node):
    for parm, _, _, _ in TEX_SLOTS:
        node.parm(parm).set("")
