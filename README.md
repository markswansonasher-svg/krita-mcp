# Krita MCP

Lets Claude (or any [MCP](https://modelcontextprotocol.io) client) **paint in Krita**: Krita's brush engine with pressure, clean tapered ink, pencil and charcoal grain, gradient fills, SVG, blend modes, clipping, masks, shaped selections, soft blur, procedural marks (scatter, hatching), pixel art, layers, filters, and export to PNG/JPG/KRA. Every tool call is a single undo step.

![A sci-fi soldier in a spaceship hallway, seen from a low angle](docs/scifi-soldier.png)

*Painted entirely through the MCP's tools by [`examples/scifi_soldier.py`](examples/scifi_soldier.py): a projected low-angle hallway, the soldier built from depth-ordered parts, separate clipped shading, key and rim light layers, emissive glow with bloom, light beams, haze, dust, vignette, color grade and grain. All of it stays as editable layers in the saved `.kra`.*

## Realism tools (v0.3)

Paint parts flat, then let the server compute the light:

![Flat shapes turned into lit forms: plastic, bevelled metal with grime and scratches, stone, skin, leaves, with cast shadows](docs/realism-forms.png)

- **`render_form`** builds a height field from each flat-colored part and lights it: rounded, dome or beveled volume, key, fill and sky light, ambient occlusion, specular highlights, rim light, environment reflections on metal, and a warm glow at the shadow edge for skin and leaves. Materials: matte, plastic, metal, painted_metal, skin, cloth, stone, wood, glass, leaf.
- **Organic shapes:** `tube` (a spine with a radius at each point, for limbs, fingers, tentacles, branches) and `blob` (rocks, clouds, muscles) work in `paint`, `select` and `add_mask`.
- **`cast_shadow`** grounds objects with a projected shadow that's sharp at the contact point and softer farther away.
- **`texture`** adds grime, rust, scratches, stone, cell, fabric, grain and cloud patterns.
- **`painterly`** repaints with brush strokes that follow the forms, coarse to fine, with bristle texture:

![The same scene after the painterly pass](docs/realism-painterly.png)

- **Natural lines:** `draw_strokes(natural=0.5)` adds wobble, pressure and overshoot; `passes=3` gives a sketchy look.

The soldier scene again, with `render_form` on the hallway and armor, texture, and a 45% painterly layer (`python examples/scifi_soldier.py all out real`):

![The sci-fi soldier with computed lighting, metal reflections and a painterly finish](docs/scifi-soldier-real.png)

The same soldier **drawn as line art** ([`examples/scifi_soldier_drawn.py`](examples/scifi_soldier_drawn.py)), produced on the first run:

![The soldier drawn as line art, colored and lit](docs/scifi-soldier-drawn.png)

Line-art drawing is built into `draw_strokes`, so it works on the first try:

![Line-art tools: a limb drawn as a tube outline, a plate in front occluding it, a seam that snaps shut, all colored automatically](docs/lineart-tools.png)

- **`"outline"`**: a stroke can be a shape's contour. A `tube` (a spine with a radius at each point) gives limbs and fingers natural tapering contours; `blob`, rounded-corner polygons and smooth paths cover the rest.
- **`"fill"`**: an outline carries its color. `fill_line_art` then colors every enclosed area that lies mostly inside it, even when seams or parts in front split it into pieces. No seed coordinates needed.
- **`"occlude"`**: a part in front erases the lines behind it exactly up to its own contour. No hand-sized erasers, so no stubs or gaps.
- **`"joins"`**: seams and panel lines get solid ends that snap onto the contour they meet, so areas close for coloring.
- **`fill_line_art(debug_view=true)`** shows every enclosed area in its own color, with the seeds marked, if something still leaks.
- **`edge_light`** adds rim or kicker light only on the edges that face the light.

The heavy image work (numpy, SciPy, Pillow) runs in the MCP server, so the Krita plugin stays lightweight. The installer sets these up for you.

## Posed figures (v0.4)

`draw_figure` draws a human figure from a **pose**: a few numbers for stance, twist, lean and head turn, plus where the hands and feet go. Elbows and knees are solved automatically (two-bone IK). Arms and legs are single anatomical contours through the joints (calf bulge, forearm swell, thigh tapering to the knee). Armor, clothing and gear are attached to bones, so they follow any pose. `sketch_pose` draws a quick stick skeleton to check a pose first.

![Three poses drawn from pose numbers](docs/poses.png)

The soldier, posed and armored through bone attachments, with the rifle placed by his hands:

![Posed soldier](docs/scifi-soldier-posed.png)

## Depth: making things part of the scene (v0.4)

Every document has a **depth buffer**. `add_depth` writes the environment's 3D polygons into it, and `draw_figure` writes the figure's depth automatically. These tools use it:

- **`atmosphere`**: haze by real distance.
- **`depth_of_field`**: focus and blur by distance.
- **`ambient_occlusion`**: contact darkness where things meet.
- **`scene_light`**: the environment's own 3D lamps light each figure by position, with falloff.
- **`figure_shadow`**: a cast shadow computed from the 3D pose and a lamp, plus contact shadows.
- **`integrate_subject`**: background light wraps over a figure's edges, and its colors shift toward the scene's palette.
- **`show_depth`**: look at the depth buffer to check it.

`draw_figure` also scales line weight by distance and, by default, draws each contour in a darker shade of the color it outlines instead of black.

Two simple characters at different depths in the same hallway, lit by the same lamps, from one run of [`examples/depth_demo.py`](examples/depth_demo.py):

![Two figures at different depths](docs/depth-demo.png)

## Where this stands next to image generators

Diffusion models (the image generators in ChatGPT, Gemini and others) are still far ahead at photorealism, painterly texture and natural anatomy. This MCP is good at different things:

- **Exact control:** composition, perspective and proportions come from numbers, so a revision changes only what you asked for.
- **Editable output:** a layered `.kra` file with separate light, shade and glow layers, so you or Claude can keep working on it.
- **Precise graphics:** clean text, logos, game UI, diagrams, technical shapes, and true pixel art.
- **Consistency:** the same character or asset can be redrawn from a script, so a series stays on-model.

A strong workflow is to combine them: use a generated image as a reference with `place_image`, then build a clean, layered, controllable version on top.

## How it works

```
Claude ──MCP (stdio)──> server.py ──JSON over 127.0.0.1:9877──> Krita plugin (krita_mcp) ──> Krita's Python API
```

- **`plugin/krita_mcp`** is a Krita Python plugin. It opens a small socket server inside Krita, on this computer only (`127.0.0.1`). Commands run on Krita's main thread, so they use Krita's own brush engine, layers and undo history.
- **`server.py`** is the MCP server. It turns tool calls into commands for the plugin. It's plain Python; the installer sets it up in its own environment.

## Install

Works on **Windows, macOS and Linux**. You need **Krita 5.2 or newer** (tested on 5.3.4) and **Python 3.10 or newer**. Nothing else: no uv, no manual pip.

Close Krita, then run the installer from this folder:

| OS | Command |
|---|---|
| Windows | double-click `install.cmd`, or run `python install.py` |
| macOS | `python3 install.py` |
| Linux | `python3 install.py` (Flatpak Krita is detected automatically; `--flatpak` forces it) |

It does everything in one go:

1. copies the plugin into Krita's `pykrita` folder;
2. turns it on in Krita's settings (the old settings file is kept as `kritarc.before-krita-mcp`);
3. creates a private Python environment in `.venv` here and installs the server's packages into it (`mcp`, `numpy`, `scipy`, `pillow`). Nothing is installed system-wide;
4. registers the server with Claude Code if the `claude` command exists, and prints the config snippet for Claude Desktop or any other MCP client.

Then start Krita and restart Claude. To check the plugin is running, use *Tools › Scripts › Krita MCP (Claude): status* in Krita.

Options: `--plugin-only` (just the plugin, if you run the server yourself), `--no-register` (don't touch Claude Code's config), `--dry-run` (show what would happen).

<details>
<summary>Where things go, and manual install</summary>

| OS | Plugin folder (`pykrita`) | Krita settings (`kritarc`) |
|---|---|---|
| Windows | `%APPDATA%\krita\pykrita` | `%LOCALAPPDATA%\kritarc` |
| macOS | `~/Library/Application Support/krita/pykrita` | `~/Library/Preferences/kritarc` |
| Linux | `~/.local/share/krita/pykrita` | `~/.config/kritarc` |
| Linux (Flatpak) | `~/.var/app/org.kde.krita/data/krita/pykrita` | `~/.var/app/org.kde.krita/config/kritarc` |

By hand: copy `plugin/krita_mcp/` and `plugin/kritapykrita_krita_mcp.desktop` into the plugin folder, start Krita, enable **Krita MCP (Claude)** in *Settings › Configure Krita › Python Plugin Manager*, and restart Krita. Then run the server any of these ways:

```bash
pip install -r requirements.txt && python server.py      # plain Python
uv run server.py                                         # uv reads the dependencies from server.py itself
```

Claude Code: `claude mcp add krita -s user -- python /path/to/krita-mcp/server.py`

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "krita": { "command": "/path/to/krita-mcp/.venv/bin/python", "args": ["/path/to/krita-mcp/server.py"] }
  }
}
```

On Windows the Python inside the environment is `.venv\Scripts\python.exe`.

</details>

`launch_krita` finds Krita in its usual places: Program Files on Windows, `/Applications` or `~/Applications` on macOS, and on Linux the `krita` command, Flatpak, Snap, or an AppImage in `~/Applications`, `~/Downloads`, `~/bin` or `~/.local/bin`. Anywhere else, set `KRITA_PATH`.

Optional environment variables:

| Variable | Default | What it does |
|---|---|---|
| `KRITA_MCP_PORT` | `9877` | Port the bridge uses. Set it for both Krita and the server. |
| `KRITA_PATH` | found automatically | Path to the Krita program, used by `launch_krita`. |

## Tools

| Area | Tools |
|---|---|
| General | `status`, `launch_krita`, `look` (canvas, one layer or a region; `grid` overlay with coordinates; `grayscale` to check values) |
| Documents | `new_document`, `open_document`, `list_documents`, `switch_document`, `resize_canvas`, `scale_image`, `save` (.kra/.psd/.ora), `export_image` (.png/.jpg/.webp…, resize, crop, single layer), `close_document` |
| Layers | `list_layers`, `add_layer`, `set_layer` (rename, opacity, blend mode, visibility, lock, alpha lock, `clipped` for clipping-mask style layers, reorder), `select_layer`, `delete_layer`, `duplicate_layer`, `merge_down`, `flatten`, `clear_layer`, `fill_layer`, `place_image` |
| Brushes | `list_brushes`, `set_brush` (preset, size, color, opacity, flow, blend, eraser), `get_brush` |
| Painting | `draw_strokes` (line-art keys `outline`, `fill`, `occlude`, `joins`; engines: `brush` = Krita presets with pressure; `ink`, `pencil`, `charcoal`, `marker` = clean variable-width strokes with tapers and grain; each stroke has one opacity, so segments don't overlap darker), `draw_shapes` (brush-outlined shapes), `set_pixels`, `get_pixels` |
| Rendering | `paint` (antialiased shapes with flat colors or linear, radial or conical gradients, per-shape erase), `paint_svg` (SVG with gradients straight onto a layer), `add_svg` (editable vector layer). All take `mode` (blend mode), `clip` (only where paint exists), `blur` (soft edges, glows) and `new_layer`. |
| Procedural | `scatter_strokes` (grass, fur, scratches, sparks, dust), `hatch` (hatching and cross-hatching in any polygon) |
| Selection & masks | `select` (rect, ellipse, circle, polygon, smooth path, shapes, SVG, a layer's paint, invert; add, subtract or intersect; feather, grow, shrink), `add_mask` (transparency mask) |
| Figures | `sketch_pose`, `draw_figure` (pose, IK, anatomy, bone attachments, depth-aware lines) |
| Depth | `add_depth`, `show_depth`, `atmosphere`, `depth_of_field`, `ambient_occlusion`, `scene_light`, `figure_shadow`, `integrate_subject` |
| Realism | `fill_line_art` (color drawn line art between its lines), `edge_light` (rim light on light-facing edges), `render_form` (lit 3D forms from flat shapes, with materials), `texture`, `cast_shadow`, `painterly`; `tube` and `blob` shapes; `natural` and `passes` for strokes |
| Other | `art_guide` (workflow advice for complex pictures), `list_filters`, `filter_settings`, `apply_filter`, `run_action`, `list_actions`, `undo` (a whole call), `redo`, `execute_python` |

Coordinates are document pixels with the origin at the top left. Stroke points can be `[x, y]` or `[x, y, pressure]`:

```json
{"strokes": [{"points": [[100, 300, 0.1], [250, 200, 1.0], [400, 300, 0.1]]}],
 "preset": "Ink-3 Gpen", "size": 16, "color": "#24323f"}
```

## How the painting works

Krita's scripting API can paint brush strokes but can't do gradients, variable-width ink or blend-mode compositing, and its raw pixel writes can't be undone. The plugin handles this as follows:

- **Brush strokes** are painted with your real brush presets into a hidden scratch document. They then land on your layer in one step, so a 200-segment pressure stroke is still one undo step and one even opacity.
- **Ink, gradients, SVG and fills** are rendered with Qt's painter, then committed through a temporary layer that is merged down. Merges are undoable, and the commit applies the blend mode, the selection, clipping and blur.
- **`undo`** reads Krita's undo history to count how many steps a call made, and undoes all of them.

## Development

- `tools/smoke_test.py [out_dir]` draws a simple test scene and exports PNG, KRA and a `look` image.
- `tools/feature_test.py [out_dir]` checks gradients, blur, clipping, selections, ink engines, masks and whole-call undo.
- `tools/realism_test.py [out_dir]` makes the realism study above (forms, materials, shadows, textures, natural lines, painterly).
- `examples/scifi_soldier.py [stage] [out_dir]` paints the picture at the top.
- `tools/restart_krita.py` restarts Krita so a changed plugin loads cleanly. This discards unsaved changes in open documents.
- `tools/dev_reload.py` hot-reloads the plugin without a restart. It's faster but can leave old code wired in, so restart Krita if anything behaves oddly.

## Security

The bridge listens only on `127.0.0.1`, but it has no authentication. Any program on your computer can send it commands, including `execute_python`, which runs arbitrary Python inside Krita. Only enable the plugin on a computer you trust.

## License

[MIT](LICENSE)
