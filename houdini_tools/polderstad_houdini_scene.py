"""
Polderstad -> classic Houdini /obj scene (no USD, no Solaris)
Houdini 20.5.613 + Redshift 2025.6

Input: the zip from Polderstad's "Houdini scene (no USD)" button (or the unzipped folder):
    town.geo      whole town in metres, Y-up. point Cd (game colour), pivot, birth, death (s), kind; vertex uv; prim name, part
    traffic.geo   one prototype per moving thing (prim name = id)
    anim.json     camera keys, traffic transforms per frame, fps, resolution, sun

Builds:
    /obj/<name>_CONTROLS   global texture size / bump strength (used by every material)
    /obj/<name>_materials  material network: one Redshift Standard Material per part (sliders + texture slots)
    /obj/<name>_town       File -> Normal -> build animation (procedural pop-in / demolition from birth & death) -> materials
    /obj/<name>_traffic    prototypes copied onto points that follow the recorded traffic
    /obj/<name>_cam        real keyframes on translate / rotate / focal: edit it like any camera
    /obj/<name>_sun        Redshift sun & sky, aimed like the game's sun
    /out/<name>_redshift   Redshift ROP: camera, frame range, $HIP/render/<name>.$F4.exr
"""
import json
import os
import re
import sys
import zipfile

import hou

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import polderstad_redshift as PRS  # noqa: E402  (shared material builder)

BUILD_VEX = r'''
// Polderstad build animation: every object pops in at its birth time and shrinks away before its death time.
// Times are in seconds from the start of the take (Houdini frame 1 = 0 s).
if (chi("../anim_enable") == 0) return;
float t = @Time - chf("../time_offset");
int k = i@kind;                       // 0 = ground tile (drops in), 1 = building / tree (grows up)
float dur = k == 0 ? chf("../tile_dur") : chf("../pop_dur");
float dd = k == 0 ? chf("../tile_demolish") : chf("../pop_demolish");
float drop = chf("../drop_height");
vector pv = v@pivot, s = {1, 1, 1};
float yoff = 0;
float x = (t - f@birth) / max(dur, 1e-4);
if (x < 0) s = {0, 0, 0};
else if (x < 1) {
    float c1 = 1.70158, c3 = c1 + 1, e = 1 + c3 * pow(x - 1, 3) + c1 * pow(x - 1, 2);   // ease-out-back, like the game
    if (k == 0) { float ss = max(0.001, e); s = set(ss, clamp(e, 0.001, 1.25), ss); yoff = pow(1 - x, 2) * drop; }
    else { float h = 0.85 + 0.15 * min(1, x * 1.4); s = set(h, max(0.01, e), h); }
}
float ds = f@death - dd;
if (t >= f@death) s = {0, 0, 0};
else if (t > ds) {
    float y = (t - ds) / max(dd, 1e-4);
    if (k == 0) { float q = y < 0.25 ? 1 + 0.12 * (y / 0.25) : 1.12 * (1 - pow((y - 0.25) / 0.75, 1.6)); s *= max(q, 0.001); yoff -= y * y * drop * 0.36; }
    else { float q = y < 0.2 ? 1 + 0.06 * (y / 0.2) : 1.06 * (1 - pow((y - 0.2) / 0.8, 1.4)); float h = 0.85 + 0.15 * max(0, q); s *= set(h, max(0.01, q), h); }
}
@P = pv + (@P - pv) * s + set(0, yoff, 0);
'''

TRAFFIC_PY = r'''
# Polderstad traffic: one point per moving object at the current frame (P, orient, name).
import json, hou
node = hou.pwd(); geo = node.geometry()
path = node.parent().parm("anim_json").evalAsString()
cache = hou.session.__dict__.setdefault("_polderstad_anim", {})
key = (path, __import__("os").path.getmtime(path))
if key not in cache:
    cache.clear(); cache[key] = json.load(open(path))
D = cache[key]
geo.addAttrib(hou.attribType.Point, "name", "")
geo.addAttrib(hou.attribType.Point, "kind", "")
geo.addAttrib(hou.attribType.Point, "orient", (0.0, 0.0, 0.0, 1.0))
f = hou.frame()
for a in D["traffic"]:
    ks = a["k"]; i = f - a["f0"]
    if i < 0 or i > len(ks) - 1:
        continue
    i0 = int(i); i1 = min(len(ks) - 1, i0 + 1); u = i - i0
    k0, k1 = ks[i0], ks[i1]
    v = [k0[j] + (k1[j] - k0[j]) * u for j in range(6)]
    q = hou.Quaternion(hou.hmath.buildRotate((v[3], v[4], v[5]), "zxy").extractRotationMatrix3())
    p = geo.createPoint(); p.setPosition((v[0], v[1], v[2]))
    p.setAttribValue("name", a["name"]); p.setAttribValue("kind", a["kind"]); p.setAttribValue("orient", tuple(q))
'''


def _unique(parent, name):
    n, i = name, 2
    while parent.node(n):
        n = "%s%d" % (name, i)
        i += 1
    return n


def _folder_from(path):
    path = hou.text.expandString(path)
    if os.path.isdir(path):
        d = path
    elif path.lower().endswith(".zip"):
        out = os.path.splitext(path)[0]
        with zipfile.ZipFile(path) as z:
            z.extractall(out)
        d = out
    else:
        d = os.path.dirname(path)
    for root, _, files in os.walk(d):  # the zip contains one sub folder
        if "anim.json" in files:
            return root.replace("\\", "/")
    raise hou.Error("No anim.json found in %s" % path)


def _keys(parm, f0, vals):
    ks = []
    for i, v in enumerate(vals):
        k = hou.Keyframe()
        k.setFrame(f0 + i)
        k.setValue(v)
        k.setExpression("linear()", hou.exprLanguage.Hscript)
        ks.append(k)
    parm.setKeyframes(ks)


def _spare(node, templates, folder="Polderstad"):
    g = node.parmTemplateGroup()
    f = hou.FolderParmTemplate("polder_" + re.sub(r"\W", "_", folder.lower()), folder, folder_type=hou.folderType.Tabs)
    for t in templates:
        f.addParmTemplate(t)
    g.append(f)
    node.setParmTemplateGroup(g)


def build(path, name=None):
    d = _folder_from(path)
    D = json.load(open(os.path.join(d, "anim.json")))
    name = re.sub(r"[^A-Za-z0-9_]", "_", name or D.get("town") or "polderstad").strip("_") or "polderstad"
    obj, out = hou.node("/obj"), hou.node("/out")
    fps, frames = D["fps"], D["frames"]
    hou.setFps(fps)
    hou.playbar.setFrameRange(1, frames)
    hou.playbar.setPlaybackRange(1, frames)
    S = D.get("metresPerCell", 9.5)

    # parts present in the geometry (for the materials)
    parts = set()
    for f in ("town.geo", "traffic.geo"):
        g = hou.Geometry()
        g.loadFromFile(os.path.join(d, f))
        a = g.findPrimAttrib("part")
        if a:
            parts.update(a.strings())
    parts = sorted(p for p in parts if p)

    # global controls (texture size / bump used by every material)
    ctrl = obj.createNode("null", _unique(obj, name + "_CONTROLS"))
    ctrl.parm("geoscale").set(0.001) if ctrl.parm("geoscale") else None
    _spare(ctrl, [
        hou.StringParmTemplate("scene_folder", "Scene Folder", 1, default_value=(d,), string_type=hou.stringParmType.FileReference, file_type=hou.fileType.Directory),
        hou.FloatParmTemplate("global_tex_scale", "Global Texture Size", 1, default_value=(1.0,), min=0.05, max=10, help="Multiplies every material's Texture Size (m)."),
        hou.FloatParmTemplate("global_bump_scale", "Global Bump Strength", 1, default_value=(1.0,), min=0, max=5),
    ])

    # materials
    matnet = obj.createNode("matnet", _unique(obj, name + "_materials"))
    for p in parts:
        PRS.build_material(matnet, p, ctrl.path(), color_attr="Cd")
    matnet.layoutChildren()

    def material_sop(parent, after):
        m = parent.createNode("material", "materials")
        m.setInput(0, after)
        m.parm("num_materials").set(len(parts))
        for i, p in enumerate(parts, 1):
            m.parm("group%d" % i).set("@part=%s" % p)
            m.parm("shop_materialpath%d" % i).set("%s/%s" % (matnet.path(), p))
        return m

    # town with procedural build animation
    town = obj.createNode("geo", _unique(obj, name + "_town"))
    for c in town.children():
        c.destroy()
    _spare(town, [
        hou.ToggleParmTemplate("anim_enable", "Build Animation", default_value=True, help="Off = the town as it is at the end of the take."),
        hou.FloatParmTemplate("time_offset", "Time Offset (s)", 1, default_value=(0.0,), min=-10, max=10, help="Shift the whole build animation in time."),
        hou.FloatParmTemplate("pop_dur", "Building Pop Duration (s)", 1, default_value=(0.55,), min=0.05, max=3),
        hou.FloatParmTemplate("tile_dur", "Tile Drop Duration (s)", 1, default_value=(0.45,), min=0.05, max=3),
        hou.FloatParmTemplate("drop_height", "Tile Drop Height (m)", 1, default_value=(0.7 * S,), min=0, max=30),
        hou.FloatParmTemplate("pop_demolish", "Building Demolish Duration (s)", 1, default_value=(0.75,), min=0.05, max=3),
        hou.FloatParmTemplate("tile_demolish", "Tile Demolish Duration (s)", 1, default_value=(0.5,), min=0.05, max=3),
    ], "Build Animation")
    f = town.createNode("file", "town_geo")
    f.parm("file").set(d + "/town.geo")
    nrm = town.createNode("normal", "flat_normals")
    nrm.setInput(0, f)
    nrm.parm("cuspangle").set(1)
    w = town.createNode("attribwrangle", "build_animation")
    w.setInput(0, nrm)
    w.parm("snippet").set(BUILD_VEX.strip())
    mt = material_sop(town, w)
    o = town.createNode("null", "OUT")
    o.setInput(0, mt)
    o.setDisplayFlag(True)
    o.setRenderFlag(True)
    town.layoutChildren()

    # traffic: prototypes copied onto per-frame points
    traffic = obj.createNode("geo", _unique(obj, name + "_traffic"))
    for c in traffic.children():
        c.destroy()
    _spare(traffic, [hou.StringParmTemplate("anim_json", "Anim JSON", 1, default_value=(d + "/anim.json",), string_type=hou.stringParmType.FileReference)], "Traffic")
    tf = traffic.createNode("file", "prototypes")
    tf.parm("file").set(d + "/traffic.geo")
    pts = traffic.createNode("python", "traffic_points")
    pts.parm("python").set(TRAFFIC_PY.strip())
    cp = traffic.createNode("copytopoints::2.0", "copy_traffic")
    cp.setInput(0, tf)
    cp.setInput(1, pts)
    cp.parm("useidattrib").set(1)
    cp.parm("idattrib").set("name")
    tmt = material_sop(traffic, cp)
    to = traffic.createNode("null", "OUT")
    to.setInput(0, tmt)
    to.setDisplayFlag(True)
    to.setRenderFlag(True)
    traffic.layoutChildren()

    # camera with real keyframes
    C = D["cam"]
    cam = obj.createNode("cam", _unique(obj, name + "_cam"))
    cam.parm("resx").set(D["resx"])
    cam.parm("resy").set(D["resy"])
    cam.parm("aperture").set(D.get("aperture", 36))
    cam.parm("near").set(0.5)
    cam.parm("far").set(20000)
    cam.parm("rOrd").set("zxy")
    for p in ("tx", "ty", "tz", "rx", "ry", "rz"):
        _keys(cam.parm(p), C["f0"], C[p])
    _keys(cam.parm("focal"), C["f0"], C["focal"])
    if C.get("orthowidth"):
        cam.parm("projection").set("ortho")
        _keys(cam.parm("orthowidth"), C["f0"], C["orthowidth"])

    # Redshift sun & sky, aimed like the game's sun
    sun = obj.createNode("rslightsun", _unique(obj, name + "_sun"))
    sd = (D.get("sun") or {}).get("dir") or [0.5, 0.7, 0.5]
    v = hou.Vector3(sd).normalized()
    if v[1] < 0.15:  # night / dusk take: keep a usable daylight sun
        v = hou.Vector3(v[0], 0.5, v[2]).normalized()
    m = hou.hmath.buildRotateLookAt(v * 100.0, hou.Vector3(0, 0, 0), hou.Vector3(0, 1, 0))
    sun.setWorldTransform(m * hou.hmath.buildTranslate(v * 100.0))

    # Redshift ROP
    rop = out.createNode("Redshift_ROP", _unique(out, name + "_redshift"))
    rop.parm("RS_renderCamera").set(cam.path())
    rop.parm("trange").set(1)
    for p, val in (("f1", 1), ("f2", frames)):
        rop.parm(p).deleteAllKeyframes()
        rop.parm(p).set(val)
    rop.parm("RS_outputFileNamePrefix").set("$HIP/render/%s.$F4.exr" % name)

    for n, col in ((ctrl, (0.3, 0.75, 0.35)), (matnet, (0.99, 0.6, 0.2)), (town, (0.29, 0.56, 0.89)), (traffic, (0.29, 0.56, 0.89)), (cam, (0.85, 0.85, 0.3)), (sun, (1.0, 0.85, 0.3))):
        n.setColor(hou.Color(col))
    obj.layoutChildren(items=(ctrl, matnet, town, traffic, cam, sun))
    return {"folder": d, "controls": ctrl, "materials": matnet, "town": town, "traffic": traffic, "camera": cam, "sun": sun, "rop": rop, "parts": parts}


def run():
    path = hou.ui.selectFile(title="Polderstad Houdini scene (.zip or folder)", pattern="*.zip", file_type=hou.fileType.Any)
    if not path:
        return
    with hou.undos.group("Import Polderstad scene"):
        r = build(path)
    r["camera"].setSelected(True, clear_all_selected=True)
    hou.ui.displayMessage(
        "Imported into /obj (no USD):\n\n"
        "- %s: the town, with the build animation (timing sliders on its Build Animation tab)\n"
        "- %s: cars, bikes, trains, people\n"
        "- %s: the camera, with normal keyframes you can edit\n"
        "- %s: %d Redshift materials, one per part (sliders + texture slots)\n"
        "- %s: Redshift sun & sky\n"
        "- %s: Redshift ROP -> Render to Disk\n\n"
        "Look through the camera: viewport camera menu > %s."
        % (r["town"].name(), r["traffic"].name(), r["camera"].name(), r["materials"].name(), len(r["parts"]), r["sun"].name(), r["rop"].path(), r["camera"].name()),
        title="Polderstad")


if __name__ == "__main__":
    run()
