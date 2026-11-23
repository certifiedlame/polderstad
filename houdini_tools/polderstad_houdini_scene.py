"""
Polderstad -> classic Houdini /obj scene
Houdini 20.5.613 + Redshift 2025.6

Input: the zip from Polderstad's "Houdini scene" button (or the unzipped folder):
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

The separate _fx.zip (birds, clouds & weather) builds:
    /obj/<name>_weather    keyframed rain / wind / storm / cloud cover / wet / lightning channels
    /obj/<name>_birds      per-frame bird points (BIRD_POINTS) + the game's bird with flapping wings copied onto them
    /obj/<name>_clouds     per-frame cloud points (CLOUD_POINTS) + the cloud shapes copied by name
    /obj/<name>_rain       procedural rain streaks driven by the weather channels, following the camera
    /obj/<name>_lightning  the lightning bolts
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
import polderstad_materials as PRS  # noqa: E402  (shared material builder)

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


def _folder_from(path, marker="anim.json"):
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
        if marker in files:
            return root.replace("\\", "/")
    raise hou.Error("No %s found in %s" % (marker, path))


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
        # one primitive wrangle instead of a Material SOP with a group per part: much faster on millions of prims
        m = parent.createNode("attribwrangle", "materials")
        m.setInput(0, after)
        m.parm("class").set("primitive")
        m.parm("snippet").set('s@shop_materialpath = "%s/" + s@part;' % matnet.path())
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


# ───────────────────────── birds, clouds & weather (the separate FX zip) ─────────────────────────
BIRD_VEX = r'''
// Rebuild every copied bird from its point: wings flap with the recorded flap angle.
// input 1 = bird points (P, orient, pscale, flap), input 2 = the bird model (point attrib "wing": +1 left, -1 right, 0 body)
int np = npoints(2);
int b = @ptnum / np, k = @ptnum % np;
vector rest = point(2, "P", k);
int side = point(2, "wing", k);
if (side != 0) {
    float a = point(1, "flap", b) * side * chf("../flap_scale");
    rest = set(rest.x * cos(a) - rest.y * sin(a), rest.x * sin(a) + rest.y * cos(a), rest.z);
}
vector4 o = point(1, "orient", b);
@P = point(1, "P", b) + qrotate(o, rest * point(1, "pscale", b) * chf("../bird_size"));
'''

RAIN_VEX = r'''
// Procedural rain, like the game: streaks falling through a box that follows the centre object, slanted by the wind.
// Amount, wind strength and direction come from the weather node's channels.
float pm(float a; float b) { return a - b * floor(a / b); }
string W = "%(weather)s";
float r = clamp(chf(W + "/rain"), 0, 1);
int n = int(chi("../max_drops") * r);
float S = chf("../box_size"), H = chf("../box_height"), fall = max(0.01, chf("../fall_speed")), len = chf("../streak_length");
float w = chf(W + "/wind");
vector slant = set(chf(W + "/wind_dirx"), 0, chf(W + "/wind_dirz")) * (1 + w * 7) * chf("../wind_push");
vector c = {0, 0, 0};
string co = chs("../centre_object");
if (co != "") c = cracktransform(0, 0, 0, {0, 0, 0}, optransform(co));
float t = @Time;
addpointattrib(0, "width", 0.0);
addpointattrib(0, "Cd", {1, 1, 1});
float wd = chf("../streak_width");
vector col = chv("../color");
for (int q = 0; q < n; q++) {
    float sp = 0.75 + rand(q * 5.71 + 0.4) * 0.5;
    float y = H - pm(rand(q * 1.93 + 0.3) * H + t * fall * sp, H);
    float drift = (H - y) / fall;
    float x = rand(q * 3.17 + 0.1) * S + slant.x * drift, z = rand(q * 7.31 + 0.2) * S + slant.z * drift;
    x = c.x - S / 2 + pm(x - (c.x - S / 2), S);
    z = c.z - S / 2 + pm(z - (c.z - S / 2), S);
    int a = addpoint(0, set(x, y, z));
    int b = addpoint(0, set(x - slant.x * len / fall, y + len, z - slant.z * len / fall));
    addprim(0, "polyline", a, b);
    setpointattrib(0, "width", a, wd); setpointattrib(0, "width", b, wd);
    setpointattrib(0, "Cd", a, col); setpointattrib(0, "Cd", b, col);
}
'''

LIGHTNING_PY = r'''
# Lightning bolts from weather.json: each strike is shown for ~0.9 s from its frame (prim attrib "flash" fades out).
import json, hou
node = hou.pwd(); geo = node.geometry()
path = node.parent().parm("weather_json").evalAsString()
cache = hou.session.__dict__.setdefault("_polderstad_weather", {})
key = (path, __import__("os").path.getmtime(path))
if key not in cache:
    cache.clear(); cache[key] = json.load(open(path))
D = cache[key]
geo.addAttrib(hou.attribType.Prim, "flash", 0.0)
f = hou.frame(); hold = 0.9 * D["fps"]
for s in D.get("lightning_strikes", []):
    age = f - s["frame"]
    if age < 0 or age > hold:
        continue
    poly = geo.createPolygon(); poly.setIsClosed(False)
    for p in s["points"]:
        pt = geo.createPoint(); pt.setPosition(p); poly.addVertex(pt)
    poly.setAttribValue("flash", max(0.0, 1.0 - age / hold))
'''

WEATHER_CHANNELS = ("rain", "wind", "wind_dirx", "wind_dirz", "wind_angle", "storm", "cloud_cover", "wet", "lightning", "cloud_speed")


def _file_seq(parent, name, pattern):
    f = parent.createNode("file", name)
    f.parm("file").set(pattern)
    if f.parm("missingframe"):
        f.parm("missingframe").set("empty")  # outside the take: no points instead of an error
    return f


def _box(parent, name, size, t):
    b = parent.createNode("box", name)
    b.parmTuple("size").set(size)
    b.parmTuple("t").set(t)
    return b


def build_fx(path, name=None):
    d = _folder_from(path, "weather.json")
    D = json.load(open(os.path.join(d, "weather.json")))
    name = re.sub(r"[^A-Za-z0-9_]", "_", name or D.get("town") or "polderstad").strip("_") or "polderstad"
    obj = hou.node("/obj")
    fps, frames = D["fps"], D["frames"]
    hou.setFps(fps)
    hou.playbar.setFrameRange(1, frames)
    hou.playbar.setPlaybackRange(1, frames)
    S = D.get("metresPerCell", 9.5)
    cams = [n for n in obj.children() if n.type().name() == "cam" and n.name().startswith(name)]

    # weather: keyframed channels everything else reads (and you can use anywhere: ch("/obj/<name>_weather/rain"))
    weather = obj.createNode("null", _unique(obj, name + "_weather"))
    weather.parm("geoscale").set(0.001) if weather.parm("geoscale") else None
    _spare(weather, [hou.FloatParmTemplate(c, c.replace("_", " ").title(), 1) for c in WEATHER_CHANNELS]
           + [hou.StringParmTemplate("weather_json", "Weather JSON", 1, default_value=(d + "/weather.json",), string_type=hou.stringParmType.FileReference)], "Weather")
    for c in WEATHER_CHANNELS:
        vals = D["channels"][c]
        if max(vals) - min(vals) < 1e-6:
            weather.parm(c).set(vals[0])  # constant during the take: no keys needed
        else:
            _keys(weather.parm(c), 1, vals)
    weather.setComment("rain, wind, storm, cloud cover, wet, lightning: 0..1 like the game sliders\nwind_dirx/z: direction the wind blows toward")
    weather.setGenericFlag(hou.nodeFlag.DisplayComment, True)

    # birds: per-frame points + the game's bird (body + flapping wings) copied onto them
    birds = obj.createNode("geo", _unique(obj, name + "_birds"))
    for c in birds.children():
        c.destroy()
    _spare(birds, [
        hou.FloatParmTemplate("bird_size", "Bird Size", 1, default_value=(1.0,), min=0.1, max=5, help="Multiplies pscale (the game's bird is ~1 m long, geese 2.6 m)."),
        hou.FloatParmTemplate("flap_scale", "Flap Amount", 1, default_value=(1.0,), min=0, max=2),
    ], "Birds")
    pts = _file_seq(birds, "bird_points", d + "/birds/birds.$F4.geo")
    out_pts = birds.createNode("null", "BIRD_POINTS")
    out_pts.setInput(0, pts)
    out_pts.setComment("P, v, orient, pscale, flap, id, kind (0 starling, 1 goose)\nCopy to Points your own bird onto this")
    out_pts.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    body = _box(birds, "body", (0.035 * S, 0.03 * S, 0.11 * S), (0, 0, 0))
    wl = _box(birds, "wing_left", (0.11 * S, 0.006 * S, 0.05 * S), (-0.055 * S, 0, 0.005 * S))
    wr = _box(birds, "wing_right", (0.11 * S, 0.006 * S, 0.05 * S), (0.055 * S, 0, 0.005 * S))
    # point attrib "wing": +1 = left wing, -1 = right wing, 0 = body (the wings rotate around the bird's Z axis)
    tagged = []
    for box, side in ((body, 0), (wl, 1), (wr, -1)):
        w = birds.createNode("attribwrangle", box.name() + "_tag")
        w.setInput(0, box)
        w.parm("snippet").set("i@wing = %d;" % side)
        tagged.append(w)
    mg = birds.createNode("merge", "bird_model_parts")
    for i, n in enumerate(tagged):
        mg.setInput(i, n)
    tag = birds.createNode("attribwrangle", "colour")
    tag.setInput(0, mg)
    tag.parm("snippet").set("v@Cd = {0.17, 0.17, 0.18};")
    model = birds.createNode("null", "BIRD_MODEL")
    model.setInput(0, tag)
    cp = birds.createNode("copytopoints::2.0", "copy_birds")
    cp.setInput(0, model)
    cp.setInput(1, out_pts)
    fl = birds.createNode("attribwrangle", "flap_wings")
    fl.setInput(0, cp)
    fl.setInput(1, out_pts)
    fl.setInput(2, model)
    fl.parm("snippet").set(BIRD_VEX.strip())
    bo = birds.createNode("null", "OUT")
    bo.setInput(0, fl)
    bo.setDisplayFlag(True)
    bo.setRenderFlag(True)
    birds.layoutChildren()

    # clouds: per-frame points + the cloud shapes copied by name
    clouds = obj.createNode("geo", _unique(obj, name + "_clouds"))
    for c in clouds.children():
        c.destroy()
    _spare(clouds, [hou.FloatParmTemplate("min_fade", "Hide Below Fade", 1, default_value=(0.02,), min=0, max=1,
                                          help="Clouds fade out at the edge of the game's cloud field (point attrib fade); hide the faintest ones.")], "Clouds")
    cpts = _file_seq(clouds, "cloud_points", d + "/clouds/clouds.$F4.geo")
    cf = clouds.createNode("attribwrangle", "hide_faded")
    cf.setInput(0, cpts)
    cf.parm("snippet").set('if (f@fade < chf("../min_fade")) removepoint(0, @ptnum);')
    cout = clouds.createNode("null", "CLOUD_POINTS")
    cout.setInput(0, cf)
    cout.setComment("P, orient, scale, fade, id, name (cloud_###)\nCopy to Points your own clouds / volumes onto this")
    cout.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    shapes = clouds.createNode("file", "cloud_shapes")
    shapes.parm("file").set(d + "/cloud_shapes.geo")
    ccp = clouds.createNode("copytopoints::2.0", "copy_clouds")
    ccp.setInput(0, shapes)
    ccp.setInput(1, cout)
    ccp.parm("useidattrib").set(1)
    ccp.parm("idattrib").set("name")
    co = clouds.createNode("null", "OUT")
    co.setInput(0, ccp)
    co.setDisplayFlag(True)
    co.setRenderFlag(True)
    clouds.layoutChildren()

    # rain: procedural streaks driven by the weather channels, following the camera
    rain = obj.createNode("geo", _unique(obj, name + "_rain"))
    for c in rain.children():
        c.destroy()
    _spare(rain, [
        hou.StringParmTemplate("centre_object", "Follow Object", 1, default_value=(cams[0].path() if cams else "",), string_type=hou.stringParmType.NodeReference,
                               help="The rain box stays centred under this object (the take's camera)."),
        hou.IntParmTemplate("max_drops", "Drops At Full Rain", 1, default_value=(9000,), min=0, max=200000),
        hou.FloatParmTemplate("box_size", "Box Size (m)", 1, default_value=(400.0,), min=10, max=5000),
        hou.FloatParmTemplate("box_height", "Box Height (m)", 1, default_value=(250.0,), min=5, max=2000),
        hou.FloatParmTemplate("fall_speed", "Fall Speed (m/s)", 1, default_value=(16 * S,), min=1, max=500, help="The game's miniature-scale speed. Real rain falls ~9 m/s."),
        hou.FloatParmTemplate("streak_length", "Streak Length (m)", 1, default_value=(0.6 * S,), min=0.01, max=50),
        hou.FloatParmTemplate("wind_push", "Wind Push", 1, default_value=(S,), min=0, max=100),
        hou.FloatParmTemplate("streak_width", "Streak Width (m)", 1, default_value=(0.05,), min=0.001, max=1),
        hou.FloatParmTemplate("color", "Colour", 3, default_value=(0.78, 0.83, 0.86), look=hou.parmLook.ColorSquare, naming_scheme=hou.parmNamingScheme.RGBA),
    ], "Rain")
    rw = rain.createNode("attribwrangle", "rain_streaks")
    rw.parm("class").set("detail")
    rw.parm("snippet").set((RAIN_VEX % {"weather": weather.path()}).strip())
    ro = rain.createNode("null", "OUT")
    ro.setInput(0, rw)
    ro.setDisplayFlag(True)
    ro.setRenderFlag(True)
    rain.layoutChildren()

    # lightning bolts
    light = obj.createNode("geo", _unique(obj, name + "_lightning"))
    for c in light.children():
        c.destroy()
    _spare(light, [hou.StringParmTemplate("weather_json", "Weather JSON", 1, default_value=(d + "/weather.json",), string_type=hou.stringParmType.FileReference)], "Lightning")
    lp = light.createNode("python", "bolts")
    lp.parm("python").set(LIGHTNING_PY.strip())
    lo = light.createNode("null", "OUT")
    lo.setInput(0, lp)
    lo.setDisplayFlag(True)
    lo.setRenderFlag(True)
    light.layoutChildren()

    nodes = (weather, birds, clouds, rain, light)
    for n, col in zip(nodes, ((0.3, 0.75, 0.35), (0.5, 0.5, 0.55), (0.9, 0.9, 0.95), (0.4, 0.6, 0.9), (1.0, 0.95, 0.4))):
        n.setColor(hou.Color(col))
    obj.layoutChildren(items=nodes)
    return {"folder": d, "weather": weather, "birds": birds, "clouds": clouds, "rain": rain, "lightning": light}


def _detect(path):
    """'scene' or 'fx' for a Polderstad zip / folder (unzips it once)."""
    path = hou.text.expandString(path)
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    else:
        names = [os.path.join(r, f) for r, _, fs in os.walk(path if os.path.isdir(path) else os.path.dirname(path)) for f in fs]
    if any(n.replace("\\", "/").endswith("/anim.json") or n == "anim.json" for n in names):
        return "scene"
    if any(n.replace("\\", "/").endswith("/weather.json") or n == "weather.json" for n in names):
        return "fx"
    raise hou.Error("This is not a Polderstad export (no anim.json or weather.json): %s" % path)


def run_fx(path=None):
    if path is None:
        path = hou.ui.selectFile(title="Polderstad birds, clouds & weather (_fx.zip or folder)", pattern="*.zip", file_type=hou.fileType.Any)
        if not path:
            return
    with hou.undos.group("Import Polderstad FX"):
        r = build_fx(path)
    hou.ui.displayMessage(
        "Imported into /obj:\n\n"
        "- %s: keyframed rain / wind / storm / cloud cover / wet / lightning channels\n"
        "- %s: birds (BIRD_POINTS inside has P, orient, pscale, flap... for your own model)\n"
        "- %s: clouds (CLOUD_POINTS inside, for your own clouds or volumes)\n"
        "- %s: procedural rain streaks, driven by the weather channels\n"
        "- %s: lightning bolts"
        % (r["weather"].name(), r["birds"].name(), r["clouds"].name(), r["rain"].name(), r["lightning"].name()), title="Polderstad")


def run():
    path = hou.ui.selectFile(title="Polderstad Houdini scene or FX zip (.zip or folder)", pattern="*.zip", file_type=hou.fileType.Any)
    if not path:
        return
    if _detect(path) == "fx":
        return run_fx(path)
    with hou.undos.group("Import Polderstad scene"):
        r = build(path)
    r["camera"].setSelected(True, clear_all_selected=True)
    hou.ui.displayMessage(
        "Imported into /obj:\n\n"
        "- %s: the town, with the build animation (timing sliders on its Build Animation tab)\n"
        "- %s: cars, bikes, trains, people\n"
        "- %s: the camera, with normal keyframes you can edit\n"
        "- %s: %d Redshift materials, one per part (sliders + texture slots)\n"
        "- %s: Redshift sun & sky\n"
        "- %s: Redshift ROP -> Render to Disk\n\n"
        "Look through the camera: viewport camera menu > %s.\n\n"
        "Birds, clouds & weather: import the matching _fx.zip too (Import Polderstad FX)."
        % (r["town"].name(), r["traffic"].name(), r["camera"].name(), r["materials"].name(), len(r["parts"]), r["sun"].name(), r["rop"].path(), r["camera"].name()),
        title="Polderstad")


if __name__ == "__main__":
    run()
