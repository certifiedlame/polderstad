POLDERSTAD -> HOUDINI 20.5 + REDSHIFT 2025
==========================================

RECOMMENDED: CLASSIC /obj, NO USD  ("Import Polderstad Scene")
  1. In Polderstad: record a take (M), then press "Houdini scene (no USD)" -> saves a .zip.
  2. In Houdini (normal Build desktop, no Solaris): shelf Polderstad > Import Polderstad Scene, pick the zip.
     It unzips next to itself and builds in /obj:
       <name>_town       the town. Its "Build Animation" tab: on/off, time offset, pop / drop / demolish
                         durations, drop height. Inside: File > Normal > build_animation (wrangle) > materials.
       <name>_traffic    cars, bikes, trains, people, emergency vehicles (prototypes copied onto per-frame points)
       <name>_cam        the camera with NORMAL KEYFRAMES on tx ty tz rx ry rz and focal (rotate order ZXY).
                         Edit it in the Animation Editor like any camera; keys are on every frame, use
                         Animation Editor > Reduce Keyframes to thin them out first if you like.
       <name>_materials  one Redshift material per part (same Look / Textures tabs as below, colour from Cd)
       <name>_CONTROLS   Global Texture Size / Global Bump Strength
       <name>_sun        Redshift Sun & Sky, aimed like the game's sun (rotate it to change the time of day)
       /out/<name>_redshift   Redshift ROP: camera, frame range, $HIP/render/<name>.####.exr -> Render to Disk
  3. Look through the camera: viewport camera menu (top right) > <name>_cam. Render view / IPR as usual.
  Everything is plain Houdini: you can move objects, replace houses, add your own geometry.

ALTERNATIVE: SOLARIS / USD  ("Import Polderstad USD (Solaris)") - everything below.

Files
  polderstad_redshift.py   the importer (Solaris / LOPs)
  polderstad.shelf         a shelf with one button: "Import Polderstad USD"

Install the shelf (once)  - already done on this PC: Documents/houdini20.5/toolbar/polderstad.shelf
  Restart Houdini, click the "+" at the right end of the shelf tabs > Shelves > Polderstad.

SOLARIS FOR FIRST-TIMERS (5 minutes)
  Solaris is Houdini's USD context. Instead of objects in /obj, you work in /stage with LOP nodes;
  each node edits the "stage" (the USD scene) and passes it down the chain, top to bottom.

  1. Switch desktop: top bar, desktop menu (shows "Build") > Solaris.
     You get: viewport, network editor (now at /stage), Scene Graph Tree (the USD hierarchy),
     and parameters. Save your .hip first so $HIP (render output folder) has a place.
  2. Click Polderstad > Import Polderstad USD, pick the .usda from the game. You get this chain:
        <name>_usd -> _materials -> _assign -> _OUT -> _placeholder_lights_off -> _sun -> _sky -> _RENDER
     The blue display flag sits on _sky: the viewport shows the stage as it is at that node.
  3. Look through the game camera: viewport top-right camera menu ("No cam") > render_CAM.
     Scrub the timeline to see the build animation and traffic.
  4. Interactive Redshift preview: viewport top-right renderer menu ("Houdini GL") > Redshift.
     Switch back to Houdini GL while editing heavy things; it is much faster.
  5. Materials: double-click _materials to go inside, click e.g. "wall" - its Look and Textures tabs
     are in the parameter pane. Press U (or the up arrow in the network bar) to go back up.
     Don't need the inner nodes; only the tabs on the material itself.
  6. Lighting: click _sun (Rotate X = height, Rotate Y = direction, Light tab = intensity/colour)
     and _sky (intensity/colour, or an HDRI in Texture File). Bypass _placeholder_lights_off
     (yellow bypass flag) if you want the game's own lights back.
  7. Render: click _RENDER, set the resolution on its Main/Camera tabs if you like,
     press "Render to Disk" (whole take, camera render_CAM) or "Render to MPlay" for a quick look.
     Frames go to $HIP/render/<name>.####.exr.
  Tips: the Scene Graph Tree lets you find any house (/World/town_GRP/...). Middle-click a node in the
  network to see what it changed. Ctrl+Z undoes the whole import.

Use
  1. In Polderstad: record a take (M, or video + motion) and press "Animated scene .usda".
  2. In Houdini: Solaris desktop, click "Import Polderstad USD", pick the .usda.
  The tool builds in /stage:
     <name>_usd        Sublayer LOP that loads the file (town, build animation, traffic, camera, placeholder lights)
     <name>_materials  Material Library with one Redshift Material Builder per part
                       (wall, roof, glass, road, pavement, foliage, water, lamp, ... ~35 in a full town)
     <name>_assign     Assign Material LOP: every mesh <part>_GEO / <part>2_GEO ... gets the material of its part
     <name>_OUT        global controls: USD file, Reload USD, Global Texture Size, Global Bump Strength
  The scene frame rate and frame range are set from the file (25 fps by default).
  Render with Redshift as usual: viewport renderer "Redshift", or a USD Render ROP with the Redshift delegate.
  render_CAM is the recorded camera. sun_LGT / sky_LGT are placeholders: replace or delete them.

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

How it works
  Base colour = the game colour (USD primvar displayColor, read with a Redshift User Data Color node)
                or the texture as soon as a Base Colour path is set, times Tint.
  Roughness / metalness use the slider until a texture is set. A normal map wins over a bump map.
  Colour spaces: base colour = sRGB, the other maps = Raw.

UVs
  Polderstad now exports UVs: USD primvars:st, OBJ vt (model templates and scene .obj).
  They are box-projected per face, 1 UV unit = 1 metre, so tileable textures line up between houses.
  Older .usda files from before this update have no UVs: re-export from the game.

Tested on this machine with Houdini 20.5.613 + Redshift (hython build of the network, plus husk renders
of a test scene and of a full town take).
