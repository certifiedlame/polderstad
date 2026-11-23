POLDERSTAD -> HOUDINI 20.5 + REDSHIFT 2025
==========================================

Files
  polderstad_houdini_scene.py   the importer (classic /obj, no USD, no Solaris)
  polderstad_materials.py       Redshift material builder used by the importer
  polderstad.shelf              shelf "Polderstad" with one button: "Import Polderstad Scene"

Install the shelf (once)  - already done on this PC: Documents/houdini20.5/toolbar/polderstad.shelf
  Restart Houdini, click the "+" at the right end of the shelf tabs > Shelves > Polderstad.

GETTING A TAKE OUT OF THE GAME
  Any of these records a "motion take" (camera + traffic + everything that is built or removed):
    - Motion only (M), or video recording (V) with "Record motion along with video" ticked
    - a camera move in Photo mode with "record motion take" ticked
    - Build it up (B): the whole city building up from scratch. With "Export Houdini scene when done"
      ticked (on by default) the zip downloads by itself when the build finishes.
  Then press "Houdini scene .zip" in Motion export.

IMPORT
  In Houdini (normal Build desktop): shelf Polderstad > Import Polderstad Scene, pick the zip.
  It unzips next to itself and builds in /obj:
    <name>_town       the town. Its "Build Animation" tab: on/off, time offset, pop / drop / demolish
                      durations, drop height. Inside: File > Normal > build_animation (wrangle) > materials.
    <name>_traffic    cars, bikes, trains, boats, people, emergency vehicles (prototypes copied onto per-frame points)
    <name>_cam        the camera with NORMAL KEYFRAMES on tx ty tz rx ry rz and focal (rotate order ZXY).
                      Edit it in the Animation Editor like any camera; keys are on every frame, use
                      Animation Editor > Reduce Keyframes to thin them out first if you like.
    <name>_materials  one Redshift material per part (wall, roof, glass, road, foliage ...)
    <name>_CONTROLS   Global Texture Size / Global Bump Strength
    <name>_sun        Redshift Sun & Sky, aimed like the game's sun (rotate it to change the time of day)
    /out/<name>_redshift   Redshift ROP: camera, frame range, $HIP/render/<name>.####.exr -> Render to Disk
  Look through the camera: viewport camera menu (top right) > <name>_cam. Render view / IPR as usual.
  Everything is plain Houdini: you can move objects, replace houses, add your own geometry.

BIRDS, CLOUDS & WEATHER  (separate _fx.zip, same timing as the scene zip)
  In the game: keep "Include birds, clouds & weather" ticked while recording, then press
  "Birds, clouds & weather .zip" (automatic exports save it next to the scene zip).
  In Houdini: shelf Polderstad > Import Polderstad FX (Import Polderstad Scene also recognises it). Builds in /obj:
    <name>_weather    null with keyframed channels: rain, wind, wind_dirx, wind_dirz, wind_angle, storm,
                      cloud_cover, wet, lightning (flash), cloud_speed. Use anywhere: ch("/obj/<name>_weather/rain")
    <name>_birds      BIRD_POINTS = one point per bird per frame (birds/birds.$F4.geo):
                        P, v (m/s), orient (model faces +Z, up +Y), pscale (1 starling, 2.6 goose), flap (wing angle),
                        id (stable per bird), kind (0 starling, 1 goose)
                      Copy to Points your own bird onto BIRD_POINTS. The game's bird is copied on by default, with
                      its wings flapping from the flap attribute (Bird Size / Flap Amount on the node).
    <name>_clouds     CLOUD_POINTS = one point per visible cloud per frame: P, orient, scale, fade, id, name.
                      The game's 150 cloud shapes are copied on by name; swap in your own clouds / volumes.
    <name>_rain       procedural rain streaks (polylines with width) in a box following the camera, amount and slant
                      from the weather channels. Box size, fall speed, streak length/width on the node.
    <name>_lightning  the lightning bolts, each shown ~0.9 s from its strike frame (prim attrib flash fades out)

OTHER EXPORTS
  Camera .py     camera (+ traffic nulls) only. Houdini: Windows > Python Source Editor, paste, Apply.
  Scene .obj     the town as it is right now (static, metres, vertex colours, UVs) - for any 3D app.

MATERIALS
Each material (select it inside <name>_materials) has two tabs:
  Look      Tint (multiplies the base colour), Roughness (0.35 by default; glass 0.05, water 0.04),
            Metalness, Transmission (glass starts at 0.85), Thin Walled, Emission
  Textures  Load Texture Set...  pick ANY image of a set (e.g. Bricks_Roughness.png): Base Colour,
                                 Roughness, Metalness, Normal and Bump/Height next to it are found by name
            Clear Textures
            Base Colour / Roughness / Metalness / Normal Map / Bump-Height   (file slots, drop images in)
            Tint Base Texture by Game Colour   one neutral brick texture, coloured per house by the game colour
            Texture Size (m)   real-world size of one tile (UVs are in metres)
            Texture Rotate, Normal Strength, Bump Strength

  Base colour = the game colour (Cd, read with a Redshift User Data Color node)
                or the texture as soon as a Base Colour path is set, times Tint.
  Roughness / metalness use the slider until a texture is set. A normal map wins over a bump map.
  Colour spaces: base colour = sRGB, the other maps = Raw.

UVs
  Box-projected per face, 1 UV unit = 1 metre, so tileable textures line up between houses.
