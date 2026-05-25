# Plan — Aggiungere `set_clip_color` (e cugini) al fork

Stato: **plan, non ancora implementato**. Da fare in una sessione dedicata al fork.

## Motivazione

La convenzione `project_jam_naming_convention.md` di Almost Humans prevede che ogni jam abbia un **colore identitario** applicato a tutti i suoi clip nello slot di Session View. Oggi questa operazione resta **manuale** in Ableton (multi-select clip → tasto destro → palette colori), come documentato in `feedback_mcp_limits_scene_color.md`. Su una jam da 28 clip (es. Phantom Halo, slot 15-19) è un'operazione ripetitiva di click-click che vale la pena automatizzare via MCP.

In più, lavorando in **auto mode**, il compositore-AI dovrebbe poter chiudere il loop "scrivo la jam → la coloro" senza handoff manuale.

## Cosa serve

Quattro tool nuovi, tutti con la stessa shape, basati sul LOM:

| Tool | LOM attribute | Use case |
|---|---|---|
| `set_clip_color(track, clip, color)` | `clip.color` (int 0xRRGGBB) | colorare un singolo clip MIDI/audio nella Session View — primario |
| `set_clip_color_palette(track, clip, palette_index)` | `clip.color_index` (int 0–69) | scegliere via indice della palette Ableton standard (snap automatico ai 70 colori della palette) |
| `set_track_color(track, color)` | `track.color` (int 0xRRGGBB) | colorare l'intera traccia (header + tutti i clip nuovi ereditano) |
| `set_scene_color(scene, color)` | `scene.color` (int 0xRRGGBB) | colorare la riga master della scena |

Il tool primario per la convenzione jam è **`set_clip_color`**. Gli altri tre sono bonus utili (in particolare `set_track_color` per il setup iniziale della scaletta).

`get_scene_info` già restituisce `color` come intero — quindi il roundtrip read/write è coerente.

## Pattern — copia incolla da `set_clip_name` + `set_scene_name`

Il fork ha già due esempi pari-pari da cui copiare.

### A) `MCP_Server/server.py` — 3 punti

**1. Tool definition** (vicino a `set_clip_name`, ~riga 370):

```python
@mcp.tool()
def set_clip_color(ctx: Context, track_index: int, clip_index: int, color: int) -> str:
    """
    Set the color of a clip in Session View.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - color: RGB packed integer (e.g. 0x6633CC = dark purple). Use 0xRRGGBB.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_color", {
            "track_index": track_index,
            "clip_index": clip_index,
            "color": color
        })
        return f"Set color of clip at track {track_index}, slot {clip_index} to 0x{color:06X}"
    except Exception as e:
        logger.error(f"Error setting clip color: {str(e)}")
        return f"Error setting clip color: {str(e)}"
```

Replicare quasi identico per `set_clip_color_palette` (param `palette_index: int`, range 0–69), `set_track_color` (no clip_index), `set_scene_color` (scene_index invece di track/clip).

**2. Whitelist `is_modifying_command`** (~riga 104):
Aggiungere a quella lista: `"set_clip_color", "set_clip_color_palette", "set_track_color", "set_scene_color"`.

### B) `AbletonMCP_Remote_Script/__init__.py` — 3 punti

**1. Whitelist main-thread dispatch** (~riga 236):
Aggiungere `"set_clip_color", "set_clip_color_palette", "set_track_color", "set_scene_color"` alla lista dei command_type che vanno schedulati sul main thread (gli attributi `color` sono main-thread-only in LOM).

**2. Branch elif in `main_thread_task`** (~riga 296, vicino a `set_scene_name`):

```python
elif command_type == "set_clip_color":
    track_index = params.get("track_index", 0)
    clip_index = params.get("clip_index", 0)
    color = params.get("color", 0)
    result = self._set_clip_color(track_index, clip_index, color)
elif command_type == "set_clip_color_palette":
    track_index = params.get("track_index", 0)
    clip_index = params.get("clip_index", 0)
    palette_index = params.get("palette_index", 0)
    result = self._set_clip_color_palette(track_index, clip_index, palette_index)
elif command_type == "set_track_color":
    track_index = params.get("track_index", 0)
    color = params.get("color", 0)
    result = self._set_track_color(track_index, color)
elif command_type == "set_scene_color":
    scene_index = params.get("scene_index", 0)
    color = params.get("color", 0)
    result = self._set_scene_color(scene_index, color)
```

**3. Metodi handler** (~riga 543, vicino a `_set_clip_name`):

```python
def _set_clip_color(self, track_index, clip_index, color):
    """Set the color of a clip (RGB packed int)."""
    try:
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index out of range")
        clip_slot = track.clip_slots[clip_index]
        if not clip_slot.has_clip:
            raise Exception("No clip in slot")
        clip_slot.clip.color = int(color)
        return {"color": clip_slot.clip.color}
    except Exception as e:
        self.log_message("Error setting clip color: " + str(e))
        raise

def _set_clip_color_palette(self, track_index, clip_index, palette_index):
    """Set the color of a clip by palette index (0..69)."""
    # identica a _set_clip_color, ma clip.color_index = int(palette_index)
    ...

def _set_track_color(self, track_index, color):
    """Set the color of a track header."""
    # come sopra, ma su self._song.tracks[track_index].color
    ...

def _set_scene_color(self, scene_index, color):
    """Set the color of a scene (master column row)."""
    # come sopra, ma su self._song.scenes[scene_index].color
    ...
```

## Note tecniche LOM

- `clip.color` accetta un **int RGB packed** (0–0xFFFFFF). Ableton **snappa automaticamente** al colore più vicino della palette interna a 70 voci. Quindi anche se passi `0x123456`, ti ritroverai uno dei 70 colori predefiniti.
- `clip.color_index` accetta un **int 0..69**, indice diretto nella palette. Più preciso se vuoi "esattamente quel colore della palette".
- Tutti gli attributi `.color` sono **main-thread only** in Live API — quindi vanno schedulati con la stessa logica `main_thread_task` già usata per `set_clip_name` / `set_scene_name`. Non chiamare da background thread o si rompe Live.
- Il `color` di scene/clip si scrive così come si legge: `get_scene_info` già restituisce un intero, quindi è simmetrico.

## Palette indicativa per le jam Almost Humans

Da verificare al primo run (Ableton snappa, quindi il colore esatto potrebbe variare):

| Jam | Colore concettuale | RGB packed suggerito |
|---|---|---|
| Pontiac B01 | giallo ocra | `0xCC9933` |
| Iron Lung B11 | blu acciaio | `0x336699` |
| Rust Code B12 | rosso ruggine | `0xCC4422` |
| Phantom Halo B13 | viola scuro / indaco | `0x6633CC` |

Una volta implementato, il workflow tipico è:

```python
for slot in range(15, 20):           # Phantom Halo: scene 15..19
    for track in range(1, 8):        # 7 tracce versatili (Tr1..Tr7)
        set_clip_color(track, slot, 0x6633CC)
```

## Test plan

1. Implementare le 4 funzioni nel fork (branch `feat/clip-track-scene-color`).
2. Ricaricare il Remote Script in Ableton (Preferences → MIDI → Control Surface = ricicla AbletonMCP).
3. Restart `uvx --from ./tools/ableton-mcp ableton-mcp` lato MCP client.
4. Smoke test:
   - `set_clip_color(1, 15, 0x6633CC)` → controllare visivamente che il clip in Tr1 slot 15 sia viola.
   - `set_clip_color_palette(1, 15, 14)` → verificare snap al colore palette index 14.
   - `set_track_color(2, 0x336699)` → header di Tr2 diventa blu.
   - `set_scene_color(15, 0x6633CC)` → riga master della scena 15 viola.
5. Verifica `get_scene_info(15)["color"]` restituisce un int coerente con quello settato (potrebbe essere snappato).
6. Stress test: colorare tutti i 28 clip di Phantom Halo in batch parallelo, verificare nessun crash sul main thread.

## Out of scope (rinviato)

- `set_clip_color_rgb(r, g, b)` come syntactic sugar — non urgente, `color` come hex/int va bene.
- `set_return_track_color` — i return non hanno una palette colori esposta in modo affidabile in tutte le versioni Live.
- Color presets / palette named (es. `"jam:phantom-halo"`) — meglio gestito a livello del compositore-AI: legge la memoria della jam, ricava il colore, chiama il tool basico.

## Una volta mergiato

- Aggiornare `agents/tecnico-setup/references/setup-v3-dawless-current.md` con i 4 tool nuovi.
- Aggiornare `feedback_mcp_limits_scene_color.md` (rimuovendo i colori dalla lista limiti, lasciando solo "delete clip/track" + "automation lanes").
- Aggiornare `project_ableton_mcp_setup.md` con il count aggiornato (5 → 9 tool extra rispetto a upstream `ahujasid/ableton-mcp`).
- Refactor del workflow del compositore: nelle action di creazione jam, chiudere il loop colorando i clip al volo invece di lasciarlo "da fare a mano".
