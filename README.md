# Krita MCP

Lets Claude (or any [MCP](https://modelcontextprotocol.io) client) **draw in Krita**: real brush strokes with pressure, filled shapes, SVG vector art, pixel art, layers, filters, and exports to PNG/JPG/KRA.

![A test scene drawn entirely through the MCP: shapes, an SVG house, pressure-tapered ink strokes and a pixel-art sprite](docs/smoke-test.png)

*Everything above was drawn through the MCP by [`tools/smoke_test.py`](tools/smoke_test.py).*

## How it works

```
Claude ──MCP (stdio)──> server.py ──JSON over 127.0.0.1:9877──> Krita plugin (krita_mcp) ──> Krita's Python API
```

- **`plugin/krita_mcp`** is a Krita Python plugin. It opens a small socket server inside Krita, on this computer only (`127.0.0.1`). Commands run on Krita's main thread, so they use Krita's own brush engine, layers and undo history.
- **`server.py`** is the MCP server. It turns tool calls into commands for the plugin. It runs with [uv](https://docs.astral.sh/uv/) and needs no other setup.

## Install

Requires **Krita 5.2 or newer** (tested on 5.3.4) and **uv**.

### 1. Install the Krita plugin

**Windows:** close Krita, then run:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

This copies the plugin to `%APPDATA%\krita\pykrita` and enables it in Krita's settings.

**Manually (any OS):** copy `plugin/krita_mcp/` and `plugin/kritapykrita_krita_mcp.desktop` into Krita's `pykrita` folder (*Settings › Manage Resources › Open Resource Folder*, then `pykrita`). Restart Krita, enable **Krita MCP (Claude)** in *Settings › Configure Krita › Python Plugin Manager*, and restart Krita again.

To check it's running, use *Tools › Scripts › Krita MCP (Claude): status*.

### 2. Add the MCP server to your client

Claude Code:

```bash
claude mcp add krita -s user -- uv run --quiet /path/to/krita-mcp/server.py
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "krita": { "command": "uv", "args": ["run", "--quiet", "/path/to/krita-mcp/server.py"] }
  }
}
```

Optional environment variables:

| Variable | Default | What it does |
|---|---|---|
| `KRITA_MCP_PORT` | `9877` | Port the bridge uses. Set it for both Krita and the server. |
| `KRITA_PATH` | found automatically | Path to the Krita program, used by `launch_krita`. |

## Tools

| Area | Tools |
|---|---|
| General | `status`, `launch_krita`, `look` (shows Claude the canvas, a layer or a region) |
| Documents | `new_document`, `open_document`, `list_documents`, `switch_document`, `resize_canvas`, `scale_image`, `save` (.kra/.psd/.ora), `export_image` (.png/.jpg/.webp…, resize, crop, single layer), `close_document` |
| Layers | `list_layers`, `add_layer`, `set_layer` (rename, opacity, blend mode, visibility, lock, alpha lock, reorder), `select_layer`, `delete_layer`, `duplicate_layer`, `merge_down`, `flatten`, `clear_layer`, `fill_layer`, `place_image` |
| Brushes | `list_brushes`, `set_brush` (preset, size, color, opacity, flow, blend, eraser), `get_brush` |
| Painting | `draw_strokes` (brush strokes, optional per-point pressure, smoothed curves), `draw_shapes` (rect, ellipse, circle, polygon, line, smooth path with outline and/or fill), `add_svg` (vector layer, optionally rasterized), `set_pixels` (pixel art from character rows and a palette), `get_pixels` |
| Other | `select`, `list_filters`, `filter_settings`, `apply_filter`, `run_action`, `list_actions`, `undo`, `redo`, `execute_python` |

Coordinates are document pixels with the origin at the top left. Stroke points can be `[x, y]` or `[x, y, pressure]`:

```json
{"strokes": [{"points": [[100, 300, 0.1], [250, 200, 1.0], [400, 300, 0.1]]}],
 "preset": "Ink-3 Gpen", "size": 16, "color": "#24323f"}
```

## Development

- `tools/smoke_test.py [out_dir]` draws the test scene above and exports PNG, KRA and a `look` image.
- `tools/dev_reload.py` reloads the plugin code inside a running Krita after you copy the changed files into `pykrita/krita_mcp`, so you don't have to restart Krita.

## Security

The bridge listens only on `127.0.0.1`, but it has no authentication. Any program on your computer can send it commands, including `execute_python`, which runs arbitrary Python inside Krita. Only enable the plugin on a computer you trust.

## License

[MIT](LICENSE)
