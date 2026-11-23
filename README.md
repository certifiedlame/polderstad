# Polderstad

A Dutch city-builder in one HTML file (three.js), made for animated-documentary footage, plus Houdini/Redshift import tools.

## Run the game

Open `polderstad.html` in Chrome or Edge. It needs an internet connection: three.js loads from the jsDelivr CDN.

## Houdini 20.5 + Redshift

The tools are in `houdini_tools/`. `houdini_tools/README.txt` has the full instructions.

1. Copy `houdini_tools/polderstad.shelf` to `Documents/houdini20.5/toolbar/`, restart Houdini, then click **+** → Shelves → **Polderstad**.
2. In the game, record a take (**M**) and press **🏠 Houdini scene .zip** (or use Build it up, Photo mode moves and flights — they can save the zip automatically).
3. In Houdini, click **Import Polderstad Scene** and pick the zip.

You get a classic `/obj` scene: the town with its build animation, the traffic, a keyframed camera, a Redshift material per part, a sun, and a Redshift ROP.

The shelf points to the tools folder on the studio drive. If you clone this repo somewhere else, edit the `TOOLS` path in `polderstad.shelf`.
