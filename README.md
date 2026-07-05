# AbletonMCP - Ableton Live Model Context Protocol Integration
[![smithery badge](https://smithery.ai/badge/@ahujasid/ableton-mcp)](https://smithery.ai/server/@ahujasid/ableton-mcp)

AbletonMCP connects Ableton Live to Claude AI through the Model Context Protocol (MCP), allowing Claude to directly interact with and control Ableton Live. This integration enables prompt-assisted music production, track creation, and Live session manipulation.

### Join the Community

Give feedback, get inspired, and build on top of the MCP: [Discord](https://discord.gg/3ZrMyGKnaU). Made by [Siddharth](https://x.com/sidahuj)

## Features

- **Two-way communication**: Connect Claude AI to Ableton Live through a socket-based server
- **Track manipulation**: Create, modify, and manipulate MIDI and audio tracks
- **Instrument and effect selection**: Claude can access and load the right instruments, effects and sounds from Ableton's library
- **Clip creation**: Create and edit MIDI clips with notes
- **Session control**: Start and stop playback, fire clips, and control transport

## Components

The system consists of two main components:

1. **Ableton Remote Script** (`Ableton_Remote_Script/__init__.py`): A MIDI Remote Script for Ableton Live that creates a socket server to receive and execute commands
2. **MCP Server** (`server.py`): A Python server that implements the Model Context Protocol and connects to the Ableton Remote Script

## Installation

### Installing via Smithery

To install Ableton Live Integration for Claude Desktop automatically via [Smithery](https://smithery.ai/server/@ahujasid/ableton-mcp):

```bash
npx -y @smithery/cli install @ahujasid/ableton-mcp --client claude
```

### Prerequisites

- Ableton Live 10 or newer
- Python 3.8 or newer
- [uv package manager](https://astral.sh/uv)

If you're on Mac, please install uv as:
```
brew install uv
```

Otherwise, install from [uv's official website][https://docs.astral.sh/uv/getting-started/installation/]

⚠️ Do not proceed before installing UV

### Claude for Desktop Integration

[Follow along with the setup instructions video](https://youtu.be/iJWJqyVuPS8)

1. Go to Claude > Settings > Developer > Edit Config > claude_desktop_config.json to include the following:

```json
{
    "mcpServers": {
        "AbletonMCP": {
            "command": "uvx",
            "args": [
                "ableton-mcp"
            ]
        }
    }
}
```

### Cursor Integration

Run ableton-mcp without installing it permanently through uvx. Go to Cursor Settings > MCP and paste this as a command:

```
uvx ableton-mcp
```

⚠️ Only run one instance of the MCP server (either on Cursor or Claude Desktop), not both

### Installing the Ableton Remote Script

[Follow along with the setup instructions video](https://youtu.be/iJWJqyVuPS8)

1. Download the `AbletonMCP_Remote_Script/__init__.py` file from this repo

2. Copy the folder to Ableton's MIDI Remote Scripts directory. Different OS and versions have different locations. **One of these should work, you might have to look**:

   **For macOS:**
   - Method 1: Go to Applications > Right-click on Ableton Live app → Show Package Contents → Navigate to:
     `Contents/App-Resources/MIDI Remote Scripts/`
   - Method 2: If it's not there in the first method, use the direct path (replace XX with your version number):
     `/Users/[Username]/Library/Preferences/Ableton/Live XX/User Remote Scripts`
   
   **For Windows:**
   - Method 1:
     C:\Users\[Username]\AppData\Roaming\Ableton\Live x.x.x\Preferences\User Remote Scripts 
   - Method 2:
     `C:\ProgramData\Ableton\Live XX\Resources\MIDI Remote Scripts\`
   - Method 3:
     `C:\Program Files\Ableton\Live XX\Resources\MIDI Remote Scripts\`
   *Note: Replace XX with your Ableton version number (e.g., 10, 11, 12)*

4. Create a folder called 'AbletonMCP' in the Remote Scripts directory and paste the downloaded '\_\_init\_\_.py' file

3. Launch Ableton Live

4. Go to Settings/Preferences → Link, Tempo & MIDI

5. In the Control Surface dropdown, select "AbletonMCP"

6. Set Input and Output to "None"

## Usage

### Starting the Connection

1. Ensure the Ableton Remote Script is loaded in Ableton Live
2. Make sure the MCP server is configured in Claude Desktop or Cursor
3. The connection should be established automatically when you interact with Claude

### Using with Claude

Once the config file has been set on Claude, and the remote script is running in Ableton, you will see a hammer icon with tools for the Ableton MCP.

## Capabilities

- Get session and track information
- Create and modify MIDI and audio tracks
- Create, edit, and trigger clips
- Control playback
- Load instruments and effects from Ableton's browser
- Add notes to MIDI clips
- Change tempo and other session parameters

## Tools

This fork exposes **42 MCP tools** (29 baseline + 13 added for Live 12 "deep control", P0).
The tables below list the new tools grouped by area. See each tool's docstring in
`MCP_Server/server.py` for full parameters.

### A. Tonalità / Global Scale (Live 12)

| Tool | What it does |
|---|---|
| `get_scale` | Read `root_note` (0-11), `scale_name`, `scale_intervals`, `scale_mode` |
| `set_scale(root_note, scale_name)` | Set the global scale root + name (e.g. 5 / "Minor") |
| `set_scale_mode(enabled)` | Toggle the global Scale feature on/off |

> Requires Live 12 (`Song.root_note` / `Song.scale_name` / `Song.scale_mode`). On
> older Live versions the reads return `null` and the setters return a clear error.
> Per-clip scale (Live 12.2) is **not** implemented yet (deferred stretch item).

### B. Device & parameters

| Tool | What it does |
|---|---|
| `get_device_list(track)` | List devices: index, name, class_name, type, is_active, can_have_chains, num_parameters |
| `get_device_parameters(track, device)` | List a device's parameters: index, name, value, min, max, is_quantized, value_items, display_value |
| `set_device_parameter(track, device, parameter, value)` | Set one parameter by **index or name** (value clamped to range) |
| `set_device_parameters(track, device, {name: value, ...})` | Batch-patch a device; per-parameter errors reported, not fatal |
| `toggle_device(track, device, on)` | Enable/bypass via the device's `Device On` parameter (`is_active` is read-only in the LOM) |
| `delete_device(track, device)` | Remove a device from the track's device chain |
| `move_device(track, device, new_index)` | ⚠️ **Not exposed in current LOM** — returns a clean error (see note) |

> **`move_device` — confirmed unsupported on Live 12** (smoke-tested 2026-07):
> `Track.move_device` is not exposed by the Live API, so device reordering cannot be
> done through the LOM. The handler's `hasattr` guard fires and it returns a clean,
> explicit error (no crash); the tool is kept as a forward-compat stub in case a
> future Live exposes the method. It deliberately does **not** fake the move via
> delete + re-add (that would lose device state/automation). If reordering is truly
> needed, `delete_device` + re-load is the documented follow-up.
>
> **Nested / rack chain access** (`get_device_chain`, devices inside Instrument/Audio
> Effect Racks) is **deferred** as a follow-up: the top-level `track.devices` path is
> clean, but chain traversal needs its own path scheme and is out of P0 scope.

### C. Note editing beyond append

| Tool | What it does |
|---|---|
| `clear_clip_notes(track, clip)` | Remove all notes from a MIDI clip |
| `replace_clip_notes(track, clip, notes)` | Clear + add (notes built before clearing, so a bad payload can't wipe the clip) |
| `remove_notes(track, clip, from_time, to_time, from_pitch, to_pitch)` | Delete notes inside a time/pitch rectangle |

These use Live 11+'s **extended note API** (`get_notes_extended` / `add_new_notes`
with `MidiNoteSpecification` / `remove_notes_extended`), so notes support the extended
fields `probability`, `velocity_deviation` and `release_velocity`. `get_clip_notes`
now also returns `note_id`, `probability`, `velocity_deviation` and `release_velocity`
for targeted editing (falling back to the legacy tuple API if the extended one is
unavailable). The legacy `add_notes_to_clip` (tuple `set_notes`) is unchanged and still
works.

## Example Commands

Here are some examples of what you can ask Claude to do:

- "Create an 80s synthwave track" [Demo](https://youtu.be/VH9g66e42XA)
- "Create a Metro Boomin style hip-hop beat"
- "Create a new MIDI track with a synth bass instrument"
- "Add reverb to my drums"
- "Create a 4-bar MIDI clip with a simple melody"
- "Get information about the current Ableton session"
- "Load a 808 drum rack into the selected track"
- "Add a jazz chord progression to the clip in track 1"
- "Set the tempo to 120 BPM"
- "Play the clip in track 2"


## Troubleshooting

- **Connection issues**: Make sure the Ableton Remote Script is loaded, and the MCP server is configured on Claude
- **Timeout errors**: Try simplifying your requests or breaking them into smaller steps
- **Have you tried turning it off and on again?**: If you're still having connection errors, try restarting both Claude and Ableton Live

## Technical Details

### Communication Protocol

The system uses a simple JSON-based protocol over TCP sockets:

- Commands are sent as JSON objects with a `type` and optional `params`
- Responses are JSON objects with a `status` and `result` or `message`

### Limitations & Security Considerations

- Creating complex musical arrangements might need to be broken down into smaller steps
- The tool is designed to work with Ableton's default devices and browser items
- Always save your work before extensive experimentation

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Disclaimer

This is a third-party integration and not made by Ableton.
