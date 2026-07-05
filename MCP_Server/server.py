# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import socket
import json
import logging
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Union

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AbletonMCPServer")

@dataclass
class AbletonConnection:
    host: str
    port: int
    sock: socket.socket = None
    
    def connect(self) -> bool:
        """Connect to the Ableton Remote Script socket server"""
        if self.sock:
            return True
            
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Ableton at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Ableton: {str(e)}")
            self.sock = None
            return False
    
    def disconnect(self):
        """Disconnect from the Ableton Remote Script"""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Ableton: {str(e)}")
            finally:
                self.sock = None

    def receive_full_response(self, sock, buffer_size=8192):
        """Receive the complete response, potentially in multiple chunks"""
        chunks = []
        sock.settimeout(15.0)  # Increased timeout for operations that might take longer
        
        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        if not chunks:
                            raise Exception("Connection closed before receiving any data")
                        break
                    
                    chunks.append(chunk)
                    
                    # Check if we've received a complete JSON object
                    try:
                        data = b''.join(chunks)
                        json.loads(data.decode('utf-8'))
                        logger.info(f"Received complete response ({len(data)} bytes)")
                        return data
                    except json.JSONDecodeError:
                        # Incomplete JSON, continue receiving
                        continue
                except socket.timeout:
                    logger.warning("Socket timeout during chunked receive")
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Socket connection error during receive: {str(e)}")
                    raise
        except Exception as e:
            logger.error(f"Error during receive: {str(e)}")
            raise
            
        # If we get here, we either timed out or broke out of the loop
        if chunks:
            data = b''.join(chunks)
            logger.info(f"Returning data after receive completion ({len(data)} bytes)")
            try:
                json.loads(data.decode('utf-8'))
                return data
            except json.JSONDecodeError:
                raise Exception("Incomplete JSON response received")
        else:
            raise Exception("No data received")

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to Ableton and return the response"""
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Ableton")
        
        command = {
            "type": command_type,
            "params": params or {}
        }
        
        # Check if this is a state-modifying command
        is_modifying_command = command_type in [
            "create_midi_track", "create_audio_track", "set_track_name",
            "create_clip", "add_notes_to_clip", "set_clip_name",
            "set_tempo", "fire_clip", "stop_clip", "set_device_parameter",
            "start_playback", "stop_playback", "load_instrument_or_effect",
            "set_clip_color", "set_clip_color_palette",
            "set_track_color", "set_scene_color",
            "set_scale", "set_scale_mode",
            "set_device_parameters", "toggle_device",
            "delete_device", "move_device",
            "clear_clip_notes", "replace_clip_notes", "remove_notes"
        ]
        
        try:
            logger.info(f"Sending command: {command_type} with params: {params}")
            
            # Send the command
            self.sock.sendall(json.dumps(command).encode('utf-8'))
            logger.info(f"Command sent, waiting for response...")
            
            # For state-modifying commands, add a small delay to give Ableton time to process
            if is_modifying_command:
                import time
                time.sleep(0.1)  # 100ms delay
            
            # Set timeout based on command type
            timeout = 15.0 if is_modifying_command else 10.0
            self.sock.settimeout(timeout)
            
            # Receive the response
            response_data = self.receive_full_response(self.sock)
            logger.info(f"Received {len(response_data)} bytes of data")
            
            # Parse the response
            response = json.loads(response_data.decode('utf-8'))
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")
            
            if response.get("status") == "error":
                logger.error(f"Ableton error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Ableton"))
            
            # For state-modifying commands, add another small delay after receiving response
            if is_modifying_command:
                import time
                time.sleep(0.1)  # 100ms delay
            
            return response.get("result", {})
        except socket.timeout:
            logger.error("Socket timeout while waiting for response from Ableton")
            self.sock = None
            raise Exception("Timeout waiting for Ableton response")
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.error(f"Socket connection error: {str(e)}")
            self.sock = None
            raise Exception(f"Connection to Ableton lost: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from Ableton: {str(e)}")
            if 'response_data' in locals() and response_data:
                logger.error(f"Raw response (first 200 bytes): {response_data[:200]}")
            self.sock = None
            raise Exception(f"Invalid response from Ableton: {str(e)}")
        except Exception as e:
            logger.error(f"Error communicating with Ableton: {str(e)}")
            self.sock = None
            raise Exception(f"Communication error with Ableton: {str(e)}")

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    try:
        logger.info("AbletonMCP server starting up")
        
        try:
            ableton = get_ableton_connection()
            logger.info("Successfully connected to Ableton on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Ableton on startup: {str(e)}")
            logger.warning("Make sure the Ableton Remote Script is running")
        
        yield {}
    finally:
        global _ableton_connection
        if _ableton_connection:
            logger.info("Disconnecting from Ableton on shutdown")
            _ableton_connection.disconnect()
            _ableton_connection = None
        logger.info("AbletonMCP server shut down")

# Create the MCP server with lifespan support
mcp = FastMCP(
    "AbletonMCP",
    lifespan=server_lifespan
)

# Global connection for resources
_ableton_connection = None

def get_ableton_connection():
    """Get or create a persistent Ableton connection"""
    global _ableton_connection
    
    if _ableton_connection is not None:
        try:
            # Test the connection with a simple ping
            # We'll try to send an empty message, which should fail if the connection is dead
            # but won't affect Ableton if it's alive
            _ableton_connection.sock.settimeout(1.0)
            _ableton_connection.sock.sendall(b'')
            return _ableton_connection
        except Exception as e:
            logger.warning(f"Existing connection is no longer valid: {str(e)}")
            try:
                _ableton_connection.disconnect()
            except:
                pass
            _ableton_connection = None
    
    # Connection doesn't exist or is invalid, create a new one
    if _ableton_connection is None:
        # Try to connect up to 3 times with a short delay between attempts
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Connecting to Ableton (attempt {attempt}/{max_attempts})...")
                _ableton_connection = AbletonConnection(host="localhost", port=9877)
                if _ableton_connection.connect():
                    logger.info("Created new persistent connection to Ableton")
                    
                    # Validate connection with a simple command
                    try:
                        # Get session info as a test
                        _ableton_connection.send_command("get_session_info")
                        logger.info("Connection validated successfully")
                        return _ableton_connection
                    except Exception as e:
                        logger.error(f"Connection validation failed: {str(e)}")
                        _ableton_connection.disconnect()
                        _ableton_connection = None
                        # Continue to next attempt
                else:
                    _ableton_connection = None
            except Exception as e:
                logger.error(f"Connection attempt {attempt} failed: {str(e)}")
                if _ableton_connection:
                    _ableton_connection.disconnect()
                    _ableton_connection = None
            
            # Wait before trying again, but only if we have more attempts left
            if attempt < max_attempts:
                import time
                time.sleep(1.0)
        
        # If we get here, all connection attempts failed
        if _ableton_connection is None:
            logger.error("Failed to connect to Ableton after multiple attempts")
            raise Exception("Could not connect to Ableton. Make sure the Remote Script is running.")
    
    return _ableton_connection


# Core Tool endpoints

@mcp.tool()
def get_session_info(ctx: Context) -> str:
    """Get detailed information about the current Ableton session"""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_session_info")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting session info from Ableton: {str(e)}")
        return f"Error getting session info: {str(e)}"

@mcp.tool()
def get_track_info(ctx: Context, track_index: int) -> str:
    """
    Get detailed information about a specific track in Ableton.
    
    Parameters:
    - track_index: The index of the track to get information about
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_info", {"track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting track info from Ableton: {str(e)}")
        return f"Error getting track info: {str(e)}"

@mcp.tool()
def create_midi_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new MIDI track in the Ableton session.
    
    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_midi_track", {"index": index})
        return f"Created new MIDI track: {result.get('name', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating MIDI track: {str(e)}")
        return f"Error creating MIDI track: {str(e)}"


@mcp.tool()
def set_track_name(ctx: Context, track_index: int, name: str) -> str:
    """
    Set the name of a track.

    Parameters:
    - track_index: The index of the track to rename
    - name: The new name for the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_name", {"track_index": track_index, "name": name})
        return f"Renamed track to: {result.get('name', name)}"
    except Exception as e:
        logger.error(f"Error setting track name: {str(e)}")
        return f"Error setting track name: {str(e)}"

@mcp.tool()
def set_track_color(ctx: Context, track_index: int, color: int) -> str:
    """
    Set the color of a track header (and the default color new clips inherit).

    Parameters:
    - track_index: The index of the track to color
    - color: RGB packed integer (e.g. 0x6633CC). Ableton snaps to the nearest
             of its 70 palette colors.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_color", {
            "track_index": track_index,
            "color": color
        })
        actual = result.get("color", color)
        return f"Set color of track {track_index} to 0x{actual:06X}"
    except Exception as e:
        logger.error(f"Error setting track color: {str(e)}")
        return f"Error setting track color: {str(e)}"

@mcp.tool()
def create_clip(ctx: Context, track_index: int, clip_index: int, length: float = 4.0) -> str:
    """
    Create a new MIDI clip in the specified track and clip slot.
    
    Parameters:
    - track_index: The index of the track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - length: The length of the clip in beats (default: 4.0)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_clip", {
            "track_index": track_index, 
            "clip_index": clip_index, 
            "length": length
        })
        return f"Created new clip at track {track_index}, slot {clip_index} with length {length} beats"
    except Exception as e:
        logger.error(f"Error creating clip: {str(e)}")
        return f"Error creating clip: {str(e)}"

@mcp.tool()
def add_notes_to_clip(
    ctx: Context, 
    track_index: int, 
    clip_index: int, 
    notes: List[Dict[str, Union[int, float, bool]]]
) -> str:
    """
    Add MIDI notes to a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - notes: List of note dictionaries, each with pitch, start_time, duration, velocity, and mute
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("add_notes_to_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "notes": notes
        })
        return f"Added {len(notes)} notes to clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error adding notes to clip: {str(e)}")
        return f"Error adding notes to clip: {str(e)}"

@mcp.tool()
def set_clip_name(ctx: Context, track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - name: The new name for the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_name", {
            "track_index": track_index,
            "clip_index": clip_index,
            "name": name
        })
        return f"Renamed clip at track {track_index}, slot {clip_index} to '{name}'"
    except Exception as e:
        logger.error(f"Error setting clip name: {str(e)}")
        return f"Error setting clip name: {str(e)}"

@mcp.tool()
def set_clip_color(ctx: Context, track_index: int, clip_index: int, color: int) -> str:
    """
    Set the color of a clip in Session View.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - color: RGB packed integer (e.g. 0x6633CC). Ableton snaps to the nearest
             of its 70 palette colors.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_color", {
            "track_index": track_index,
            "clip_index": clip_index,
            "color": color
        })
        actual = result.get("color", color)
        return f"Set color of clip at track {track_index}, slot {clip_index} to 0x{actual:06X}"
    except Exception as e:
        logger.error(f"Error setting clip color: {str(e)}")
        return f"Error setting clip color: {str(e)}"

@mcp.tool()
def set_clip_color_palette(ctx: Context, track_index: int, clip_index: int, palette_index: int) -> str:
    """
    Set the color of a clip by Ableton palette index (0..69). More precise than
    set_clip_color when you want an exact palette swatch instead of letting Live
    snap an arbitrary RGB.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - palette_index: Integer 0..69 — index into Ableton's color palette
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_color_palette", {
            "track_index": track_index,
            "clip_index": clip_index,
            "palette_index": palette_index
        })
        return (f"Set palette color of clip at track {track_index}, slot {clip_index} "
                f"to palette index {result.get('color_index', palette_index)}")
    except Exception as e:
        logger.error(f"Error setting clip color palette: {str(e)}")
        return f"Error setting clip color palette: {str(e)}"

@mcp.tool()
def set_tempo(ctx: Context, tempo: float) -> str:
    """
    Set the tempo of the Ableton session.

    Parameters:
    - tempo: The new tempo in BPM
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_tempo", {"tempo": tempo})
        return f"Set tempo to {tempo} BPM"
    except Exception as e:
        logger.error(f"Error setting tempo: {str(e)}")
        return f"Error setting tempo: {str(e)}"

@mcp.tool()
def get_clip_notes(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Read all MIDI notes from a clip. Returns clip metadata and a list of notes,
    each with pitch (0-127), start_time (beats), duration (beats), velocity (1-127), mute (bool).

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_clip_notes", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting clip notes: {str(e)}")
        return f"Error getting clip notes: {str(e)}"

@mcp.tool()
def get_scene_info(ctx: Context, scene_index: int) -> str:
    """
    Get information about a scene (name, tempo override, color, triggered state, total scenes).

    Parameters:
    - scene_index: The index of the scene in the master column (0-based)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_scene_info", {"scene_index": scene_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting scene info: {str(e)}")
        return f"Error getting scene info: {str(e)}"

@mcp.tool()
def set_scene_name(ctx: Context, scene_index: int, name: str) -> str:
    """
    Set the name of a scene (the label shown in the master column of Session View).

    Parameters:
    - scene_index: The index of the scene (0-based)
    - name: The new name for the scene
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_scene_name", {
            "scene_index": scene_index,
            "name": name
        })
        return f"Renamed scene {scene_index} to '{result.get('name', name)}'"
    except Exception as e:
        logger.error(f"Error setting scene name: {str(e)}")
        return f"Error setting scene name: {str(e)}"

@mcp.tool()
def create_scene(ctx: Context, scene_index: int = -1) -> str:
    """
    Create a new empty scene in Session View. Existing scenes at or after the
    insertion index slide down by one position (clips move with their scenes).

    Parameters:
    - scene_index: Position to insert the new scene at (0-based).
                   Use -1 to append at the end of the scene list.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_scene", {"scene_index": scene_index})
        return (f"Created scene at index {result.get('created_at')}. "
                f"Total scenes now: {result.get('total_scenes')}")
    except Exception as e:
        logger.error(f"Error creating scene: {str(e)}")
        return f"Error creating scene: {str(e)}"

@mcp.tool()
def set_scene_tempo(ctx: Context, scene_index: int, tempo: float) -> str:
    """
    Set the tempo override for a scene. When the scene is fired, the global tempo
    will change to this value. Pass tempo=-1 to clear the override (scene will not
    change tempo when fired).

    Parameters:
    - scene_index: The index of the scene (0-based)
    - tempo: BPM value between 20 and 999, or -1 to clear the override
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_scene_tempo", {
            "scene_index": scene_index,
            "tempo": tempo
        })
        actual = result.get("tempo", tempo)
        if actual == -1:
            return f"Cleared tempo override on scene {scene_index}"
        return f"Set tempo override on scene {scene_index} to {actual} BPM"
    except Exception as e:
        logger.error(f"Error setting scene tempo: {str(e)}")
        return f"Error setting scene tempo: {str(e)}"

@mcp.tool()
def set_scene_color(ctx: Context, scene_index: int, color: int) -> str:
    """
    Set the color of a scene (the row in the master column of Session View).

    Parameters:
    - scene_index: The index of the scene (0-based)
    - color: RGB packed integer (e.g. 0x6633CC). Ableton snaps to the nearest
             of its 70 palette colors.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_scene_color", {
            "scene_index": scene_index,
            "color": color
        })
        actual = result.get("color", color)
        return f"Set color of scene {scene_index} to 0x{actual:06X}"
    except Exception as e:
        logger.error(f"Error setting scene color: {str(e)}")
        return f"Error setting scene color: {str(e)}"


@mcp.tool()
def load_instrument_or_effect(ctx: Context, track_index: int, uri: str) -> str:
    """
    Load an instrument or effect onto a track using its URI.
    
    Parameters:
    - track_index: The index of the track to load the instrument on
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": uri
        })
        
        # Check if the instrument was loaded successfully
        if result.get("loaded", False):
            new_devices = result.get("new_devices", [])
            if new_devices:
                return f"Loaded instrument with URI '{uri}' on track {track_index}. New devices: {', '.join(new_devices)}"
            else:
                devices = result.get("devices_after", [])
                return f"Loaded instrument with URI '{uri}' on track {track_index}. Devices on track: {', '.join(devices)}"
        else:
            return f"Failed to load instrument with URI '{uri}'"
    except Exception as e:
        logger.error(f"Error loading instrument by URI: {str(e)}")
        return f"Error loading instrument by URI: {str(e)}"

@mcp.tool()
def fire_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Start playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("fire_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Started playing clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error firing clip: {str(e)}")
        return f"Error firing clip: {str(e)}"

@mcp.tool()
def stop_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Stop playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Stopped clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error stopping clip: {str(e)}")
        return f"Error stopping clip: {str(e)}"

@mcp.tool()
def start_playback(ctx: Context) -> str:
    """Start playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("start_playback")
        return "Started playback"
    except Exception as e:
        logger.error(f"Error starting playback: {str(e)}")
        return f"Error starting playback: {str(e)}"

@mcp.tool()
def stop_playback(ctx: Context) -> str:
    """Stop playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_playback")
        return "Stopped playback"
    except Exception as e:
        logger.error(f"Error stopping playback: {str(e)}")
        return f"Error stopping playback: {str(e)}"


# --- Arrangement View tools ---

@mcp.tool()
def list_arrangement_clips(ctx: Context, track_index: int) -> str:
    """
    List clips currently in the Arrangement View for a given track.

    Returns name, start_time/end_time/length (in beats), is_midi_clip, color
    and an `index` you can pass to add_notes_to_arrangement_clip.

    Parameters:
    - track_index: The index of the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("list_arrangement_clips", {
            "track_index": track_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error listing arrangement clips: {str(e)}")
        return f"Error listing arrangement clips: {str(e)}"

@mcp.tool()
def create_arrangement_midi_clip(
    ctx: Context,
    track_index: int,
    start_time: float,
    length: float,
    name: str = None,
) -> str:
    """
    Create an empty MIDI clip in the Arrangement View at start_time, of given length (beats).
    Track must be a MIDI track. Returns the new clip's arrangement_clip_index.

    Parameters:
    - track_index: The index of the MIDI track
    - start_time: Position in beats where the clip starts (1 bar in 4/4 = 4 beats)
    - length: Clip length in beats
    - name: Optional clip name
    """
    try:
        ableton = get_ableton_connection()
        params = {
            "track_index": track_index,
            "start_time": start_time,
            "length": length,
        }
        if name is not None:
            params["name"] = name
        result = ableton.send_command("create_arrangement_midi_clip", params)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error creating arrangement midi clip: {str(e)}")
        return f"Error creating arrangement midi clip: {str(e)}"

@mcp.tool()
def add_notes_to_arrangement_clip(
    ctx: Context,
    track_index: int,
    arrangement_clip_index: int,
    notes: List[Dict[str, Union[int, float, bool]]],
) -> str:
    """
    Add MIDI notes to an existing Arrangement View clip.

    Use list_arrangement_clips first to get the arrangement_clip_index of the
    clip you want to edit. Note schema matches add_notes_to_clip:
    pitch, start_time, duration, velocity, mute.

    Parameters:
    - track_index: The index of the track containing the clip
    - arrangement_clip_index: Index of the clip in track.arrangement_clips
    - notes: List of note dicts {pitch, start_time, duration, velocity, mute}
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("add_notes_to_arrangement_clip", {
            "track_index": track_index,
            "arrangement_clip_index": arrangement_clip_index,
            "notes": notes,
        })
        return f"Added {len(notes)} notes to arrangement clip {arrangement_clip_index} on track {track_index}"
    except Exception as e:
        logger.error(f"Error adding notes to arrangement clip: {str(e)}")
        return f"Error adding notes to arrangement clip: {str(e)}"

@mcp.tool()
def duplicate_session_clip_to_arrangement(
    ctx: Context,
    track_index: int,
    clip_index: int,
    time: float,
) -> str:
    """
    Stamp an existing Session View clip into the Arrangement View at the given time (beats).
    The Session clip stays where it is; a copy is placed in arrangement.

    Parameters:
    - track_index: The index of the track (must be the same track in both views)
    - clip_index: The session clip slot index containing the source clip
    - time: Beat position where the duplicated clip should land in arrangement
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_session_clip_to_arrangement", {
            "track_index": track_index,
            "clip_index": clip_index,
            "time": time,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error duplicating session clip to arrangement: {str(e)}")
        return f"Error duplicating session clip to arrangement: {str(e)}"


@mcp.tool()
def get_browser_tree(ctx: Context, category_type: str = "all") -> str:
    """
    Get a hierarchical tree of browser categories from Ableton.
    
    Parameters:
    - category_type: Type of categories to get ('all', 'instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_tree", {
            "category_type": category_type
        })
        
        # Check if we got any categories
        if "available_categories" in result and len(result.get("categories", [])) == 0:
            available_cats = result.get("available_categories", [])
            return (f"No categories found for '{category_type}'. "
                   f"Available browser categories: {', '.join(available_cats)}")
        
        # Format the tree in a more readable way
        total_folders = result.get("total_folders", 0)
        formatted_output = f"Browser tree for '{category_type}' (showing {total_folders} folders):\n\n"
        
        def format_tree(item, indent=0):
            output = ""
            if item:
                prefix = "  " * indent
                name = item.get("name", "Unknown")
                path = item.get("path", "")
                has_more = item.get("has_more", False)
                
                # Add this item
                output += f"{prefix}• {name}"
                if path:
                    output += f" (path: {path})"
                if has_more:
                    output += " [...]"
                output += "\n"
                
                # Add children
                for child in item.get("children", []):
                    output += format_tree(child, indent + 1)
            return output
        
        # Format each category
        for category in result.get("categories", []):
            formatted_output += format_tree(category)
            formatted_output += "\n"
        
        return formatted_output
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        else:
            logger.error(f"Error getting browser tree: {error_msg}")
            return f"Error getting browser tree: {error_msg}"

@mcp.tool()
def get_browser_items_at_path(ctx: Context, path: str) -> str:
    """
    Get browser items at a specific path in Ableton's browser.
    
    Parameters:
    - path: Path in the format "category/folder/subfolder"
            where category is one of the available browser categories in Ableton
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_items_at_path", {
            "path": path
        })
        
        # Check if there was an error with available categories
        if "error" in result and "available_categories" in result:
            error = result.get("error", "")
            available_cats = result.get("available_categories", [])
            return (f"Error: {error}\n"
                   f"Available browser categories: {', '.join(available_cats)}")
        
        return json.dumps(result, indent=2)
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        elif "Unknown or unavailable category" in error_msg:
            logger.error(f"Invalid browser category: {error_msg}")
            return f"Error: {error_msg}. Please check the available categories using get_browser_tree."
        elif "Path part" in error_msg and "not found" in error_msg:
            logger.error(f"Path not found: {error_msg}")
            return f"Error: {error_msg}. Please check the path and try again."
        else:
            logger.error(f"Error getting browser items at path: {error_msg}")
            return f"Error getting browser items at path: {error_msg}"

@mcp.tool()
def load_drum_kit(ctx: Context, track_index: int, rack_uri: str, kit_path: str) -> str:
    """
    Load a drum rack and then load a specific drum kit into it.
    
    Parameters:
    - track_index: The index of the track to load on
    - rack_uri: The URI of the drum rack to load (e.g., 'Drums/Drum Rack')
    - kit_path: Path to the drum kit inside the browser (e.g., 'drums/acoustic/kit1')
    """
    try:
        ableton = get_ableton_connection()
        
        # Step 1: Load the drum rack
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": rack_uri
        })
        
        if not result.get("loaded", False):
            return f"Failed to load drum rack with URI '{rack_uri}'"
        
        # Step 2: Get the drum kit items at the specified path
        kit_result = ableton.send_command("get_browser_items_at_path", {
            "path": kit_path
        })
        
        if "error" in kit_result:
            return f"Loaded drum rack but failed to find drum kit: {kit_result.get('error')}"
        
        # Step 3: Find a loadable drum kit
        kit_items = kit_result.get("items", [])
        loadable_kits = [item for item in kit_items if item.get("is_loadable", False)]
        
        if not loadable_kits:
            return f"Loaded drum rack but no loadable drum kits found at '{kit_path}'"
        
        # Step 4: Load the first loadable kit
        kit_uri = loadable_kits[0].get("uri")
        load_result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": kit_uri
        })
        
        return f"Loaded drum rack and kit '{loadable_kits[0].get('name')}' on track {track_index}"
    except Exception as e:
        logger.error(f"Error loading drum kit: {str(e)}")
        return f"Error loading drum kit: {str(e)}"

# --- A. Global Scale (Live 12) tools ---

@mcp.tool()
def get_scale(ctx: Context) -> str:
    """
    Read the global Scale settings of the Live 12 project: root_note (0-11, C=0..B=11),
    scale_name (e.g. "Major", "Minor"), scale_intervals (read-only semitone pattern),
    and scale_mode (whether the global Scale feature is enabled).

    On a Live version without the global Scale feature, fields come back null and
    scale_supported is false.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_scale")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting scale: {str(e)}")
        return f"Error getting scale: {str(e)}"

@mcp.tool()
def set_scale(ctx: Context, root_note: int, scale_name: str) -> str:
    """
    Set the global scale of the Live 12 project.

    Parameters:
    - root_note: Root note as an int 0-11 (C=0, C#=1, D=2 ... B=11). E.g. 5 = F.
    - scale_name: Name of the scale as Live spells it (e.g. "Major", "Minor",
      "Dorian", "Phrygian", "Mixolydian", "Aeolian", "Harmonic Minor").
    Requires Live 12 (returns an error on older versions).
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_scale", {
            "root_note": root_note,
            "scale_name": scale_name
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting scale: {str(e)}")
        return f"Error setting scale: {str(e)}"

@mcp.tool()
def set_scale_mode(ctx: Context, enabled: bool) -> str:
    """
    Toggle the global Scale mode of the Live 12 project on or off.

    Parameters:
    - enabled: True to turn the global Scale on, False to turn it off.
    Requires Live 12.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_scale_mode", {"enabled": enabled})
        return f"Set global scale_mode to {result.get('scale_mode', enabled)}"
    except Exception as e:
        logger.error(f"Error setting scale mode: {str(e)}")
        return f"Error setting scale mode: {str(e)}"


# --- B. Device & parameter tools ---

@mcp.tool()
def get_device_list(ctx: Context, track_index: int) -> str:
    """
    List the devices on a track. For each device returns index, name, class_name,
    type, is_active, can_have_chains and num_parameters.

    Parameters:
    - track_index: The index of the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_device_list", {"track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting device list: {str(e)}")
        return f"Error getting device list: {str(e)}"

@mcp.tool()
def get_device_parameters(ctx: Context, track_index: int, device_index: int) -> str:
    """
    List every parameter of a device on a track. For each parameter returns index,
    name, value, min, max, is_quantized, display_value and (for quantized/enum
    parameters) value_items.

    Use this to discover parameter names/indices before calling set_device_parameter.

    Parameters:
    - track_index: The index of the track
    - device_index: The index of the device on that track (see get_device_list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_device_parameters", {
            "track_index": track_index,
            "device_index": device_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting device parameters: {str(e)}")
        return f"Error getting device parameters: {str(e)}"

@mcp.tool()
def set_device_parameter(
    ctx: Context,
    track_index: int,
    device_index: int,
    parameter: Union[int, str],
    value: float
) -> str:
    """
    Set a single device parameter (turn one knob). The value is clamped to the
    parameter's [min, max] range.

    Parameters:
    - track_index: The index of the track
    - device_index: The index of the device on that track
    - parameter: Parameter identifier — either an integer index or a parameter
      name (e.g. 3 or "Frequency"). Names are matched case-insensitively.
    - value: The target value (in the parameter's own units/range). For quantized
      parameters pass the enum's numeric value.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_device_parameter", {
            "track_index": track_index,
            "device_index": device_index,
            "parameter": parameter,
            "value": value
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting device parameter: {str(e)}")
        return f"Error setting device parameter: {str(e)}"

@mcp.tool()
def set_device_parameters(
    ctx: Context,
    track_index: int,
    device_index: int,
    parameters: Dict[str, float]
) -> str:
    """
    Batch-set multiple parameters of a device in one call (patch a synth/effect).

    Parameters:
    - track_index: The index of the track
    - device_index: The index of the device on that track
    - parameters: A mapping of parameter name (or index-as-string) to value,
      e.g. {"Frequency": 800, "Resonance": 0.4, "3": 1.0}. Each value is clamped
      to that parameter's range. Per-parameter failures are reported in `errors`
      without aborting the rest of the patch.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_device_parameters", {
            "track_index": track_index,
            "device_index": device_index,
            "parameters": parameters
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting device parameters: {str(e)}")
        return f"Error setting device parameters: {str(e)}"

@mcp.tool()
def toggle_device(ctx: Context, track_index: int, device_index: int, on: bool) -> str:
    """
    Enable or bypass a device. Live's LOM drives this through the device's
    'Device On' parameter (Device.is_active itself is read-only), so this works
    for native Live devices. Returns an error if the device has no 'Device On'
    parameter.

    Parameters:
    - track_index: The index of the track
    - device_index: The index of the device on that track
    - on: True to enable the device, False to bypass it
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("toggle_device", {
            "track_index": track_index,
            "device_index": device_index,
            "on": on
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error toggling device: {str(e)}")
        return f"Error toggling device: {str(e)}"

@mcp.tool()
def delete_device(ctx: Context, track_index: int, device_index: int) -> str:
    """
    Delete a device from a track's device chain. Device indices shift down after
    the deleted device, so re-fetch get_device_list before further edits.

    Parameters:
    - track_index: The index of the track
    - device_index: The index of the device to delete
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_device", {
            "track_index": track_index,
            "device_index": device_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error deleting device: {str(e)}")
        return f"Error deleting device: {str(e)}"

@mcp.tool()
def move_device(ctx: Context, track_index: int, device_index: int, new_index: int) -> str:
    """
    Reorder a device within a track's device chain.

    NOTE: reliable device reordering is not guaranteed to be exposed in every
    Live version's LOM. If Track.move_device is unavailable this returns a clear
    error rather than faking the move — verify in Live 12 before relying on it.

    Parameters:
    - track_index: The index of the track
    - device_index: The current index of the device
    - new_index: The target index within the device chain
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("move_device", {
            "track_index": track_index,
            "device_index": device_index,
            "new_index": new_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error moving device: {str(e)}")
        return f"Error moving device: {str(e)}"


# --- C. Note editing beyond append ---

@mcp.tool()
def clear_clip_notes(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Remove ALL MIDI notes from a clip, leaving the (empty) clip in place.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("clear_clip_notes", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Cleared all notes from clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error clearing clip notes: {str(e)}")
        return f"Error clearing clip notes: {str(e)}"

@mcp.tool()
def replace_clip_notes(
    ctx: Context,
    track_index: int,
    clip_index: int,
    notes: List[Dict[str, Union[int, float, bool]]]
) -> str:
    """
    Replace the entire content of a MIDI clip: clears existing notes and writes the
    supplied notes (clear + add). Uses Live's extended note API, so notes may carry
    extended fields in addition to the basics.

    Note dict fields:
    - pitch (0-127), start_time (beats), duration (beats), velocity (1-127), mute (bool)
    - probability (0.0-1.0, optional), velocity_deviation (optional),
      release_velocity (0-127, optional)

    Notes are validated/built before the clip is cleared, so a malformed payload
    will not wipe the clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - notes: List of note dictionaries (see fields above)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("replace_clip_notes", {
            "track_index": track_index,
            "clip_index": clip_index,
            "notes": notes
        })
        return f"Replaced clip at track {track_index}, slot {clip_index} with {result.get('note_count', len(notes))} notes"
    except Exception as e:
        logger.error(f"Error replacing clip notes: {str(e)}")
        return f"Error replacing clip notes: {str(e)}"

@mcp.tool()
def remove_notes(
    ctx: Context,
    track_index: int,
    clip_index: int,
    from_time: float = 0.0,
    to_time: float = None,
    from_pitch: int = 0,
    to_pitch: int = 128
) -> str:
    """
    Remove MIDI notes inside a time/pitch rectangle from a clip (selective delete).
    Notes whose start falls in [from_time, to_time) and [from_pitch, to_pitch) are
    removed.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - from_time: Start of the time window in beats (default 0.0)
    - to_time: End of the time window in beats (default: end of clip)
    - from_pitch: Lowest pitch to remove, inclusive (default 0)
    - to_pitch: Upper pitch bound, exclusive (default 128 = all pitches)
    """
    try:
        ableton = get_ableton_connection()
        params = {
            "track_index": track_index,
            "clip_index": clip_index,
            "from_time": from_time,
            "from_pitch": from_pitch,
            "to_pitch": to_pitch,
        }
        if to_time is not None:
            params["to_time"] = to_time
        result = ableton.send_command("remove_notes", params)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error removing notes: {str(e)}")
        return f"Error removing notes: {str(e)}"


# Main execution
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()