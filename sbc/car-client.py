#!/usr/bin/env python3
import asyncio
import json
import os
import signal
import sys
import subprocess
import threading
from typing import Optional, Any, Dict
import time
import websockets
import serial

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstWebRTC", "1.0")
gi.require_version("GstSdp", "1.0")
gi.require_version("GLib", "2.0")

from gi.repository import Gst, GstWebRTC, GstSdp, GLib  # type: ignore

Gst.init(None)

# ===== CONFIG =====
SIGNALING_URL = "wss://79-76-127-159.nip.io/"   # nginx reverse proxy -> node ws
ROOM_ID = "test1"

UART_DEV = "/dev/serial0"
UART_BAUD = 115200

# Control ranges
THROTTLE_MIN, THROTTLE_MAX = 0, 1000
STEER_MIN, STEER_MAX = -1000, 1000
CONTROL_RANGE = 1.0  # ±1.0 from browser

# Kamera: H264 w stdout (ważne: --nopreview)
RPICAM_CMD = [
    "rpicam-vid",
    "-t", "0",
    "--width", "640",
    "--height", "480",
    "--framerate", "15",
    "--codec", "h264",
    "--inline",
    "--nopreview",
    "-o", "-"
]

# ===== UART =====
ser = serial.Serial(UART_DEV, UART_BAUD, timeout=0)

_seq = 0
def uart_send(throttle: int, steer: int, flags: int) -> None:
    global _seq
    _seq = (_seq + 1) & 0xFFFF
    line = f"T,{int(throttle)},{int(steer)},{int(flags)},{_seq}\n"
    ser.write(line.encode("ascii", "ignore"))

# ===== GLOBALS =====
ws: Optional[websockets.WebSocketClientProtocol] = None
pipe: Optional[Gst.Pipeline] = None
webrtc: Optional[Any] = None
rpicam_proc: Optional[subprocess.Popen] = None
asyncio_loop: Optional[asyncio.AbstractEventLoop] = None
stopping = False

glib_loop: Optional[GLib.MainLoop] = None

def log(*a):
    """Log with timestamp."""
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)

async def ws_send(obj: dict) -> None:
    if ws is None:
        return
    await ws.send(json.dumps(obj))

def _run_coro_threadsafe(coro):
    if asyncio_loop is None:
        return
    asyncio.run_coroutine_threadsafe(coro, asyncio_loop)

# ===== SDP helpers =====
def sdp_text_from_desc(desc) -> str:
    sdpmsg = None

    if hasattr(desc, "sdp"):
        sdpmsg = getattr(desc, "sdp")

    if sdpmsg is None:
        try:
            sdpmsg = desc.props.sdp
        except Exception:
            pass

    if sdpmsg is None:
        try:
            sdpmsg = desc.get_property("sdp")
        except Exception:
            pass

    if sdpmsg is None and hasattr(desc, "get_sdp"):
        try:
            sdpmsg = desc.get_sdp()
        except Exception:
            pass

    if sdpmsg is None:
        raise RuntimeError("Cannot extract SDP from WebRTCSessionDescription")

    if hasattr(sdpmsg, "as_text"):
        return sdpmsg.as_text()

    return GstSdp.sdp_message_as_text(sdpmsg)

# ===== GStreamer / WebRTC =====
def start_glib_mainloop():
    global glib_loop
    glib_loop = GLib.MainLoop()
    glib_loop.run()

def make_pipeline(rfd: int) -> tuple[Gst.Pipeline, Any]:
    """Create H264 video pipeline with WebRTC sink."""
    # Pipeline: fdsrc -> h264parse -> rtph264pay -> application/x-rtp -> webrtcbin
    # Note: "wb." requests dynamic sink pad from webrtcbin
    
    # Your TURN server configuration
    turn_usr = os.environ.get("TURN_USER", "pocuser")
    turn_pass = os.environ.get("TURN_PASS", "pocpass")
    turn_host = os.environ.get("TURN_HOST", "79-76-127-159.nip.io")
    turn_port = os.environ.get("TURN_PORT", "3478")
    
    log(f"[TURN] Using server: turn://{turn_usr}:***@{turn_host}:{turn_port}")
    
    # GStreamer webrtcbin requires simple URL without ?transport parameter
    # The transport is auto-negotiated
    turn_url = f"turn://{turn_usr}:{turn_pass}@{turn_host}:{turn_port}"
    
    desc = (
        f"fdsrc fd={rfd} ! queue ! h264parse ! "
        f"rtph264pay pt=96 config-interval=1 ! "
        f"application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000 ! "
        f"queue ! wb. "
        f"webrtcbin name=wb bundle-policy=max-bundle "
        f"turn-server=\"{turn_url}\" "
    )

    try:
        p = Gst.parse_launch(desc)
        if p is None:
            raise RuntimeError("Gst.parse_launch() returned None")
    except Exception as e:
        raise RuntimeError(f"Pipeline creation failed: {e}") from e

    wb = p.get_by_name("wb")
    if not wb:
        raise RuntimeError("Cannot find webrtcbin element 'wb'")
    
    # Don't force relay-only on car side - let it generate all candidates
    # Browser will select relay candidates due to its iceTransportPolicy
    # try:
    #     from gi.repository import GstWebRTC
    #     wb.set_property("ice-transport-policy", GstWebRTC.WebRTCICETransportPolicy.RELAY)
    #     log("[ICE] Set ice-transport-policy to RELAY")
    # except Exception as e:
    #     log(f"[ICE] Warning: Could not set ice-transport-policy: {e}")

    return p, wb

def on_bus_message(bus: Gst.Bus, message: Gst.Message):
    t = message.type
    if t == Gst.MessageType.ERROR:
        err, dbg = message.parse_error()
        log("[GST] ERROR:", err, dbg)
    elif t == Gst.MessageType.WARNING:
        err, dbg = message.parse_warning()
        log("[GST] WARN:", err, dbg)
    elif t == Gst.MessageType.EOS:
        log("[GST] EOS")
    elif t == Gst.MessageType.STATE_CHANGED:
        # Don't log all state changes, too verbose
        pass
    elif t == Gst.MessageType.INFO:
        info, dbg = message.parse_info()
        log(f"[GST] INFO: {info}, {dbg}")
    else:
        # Log other message types that might contain TURN errors
        struct = message.get_structure()
        if struct and "ice" in struct.get_name().lower():
            log(f"[GST] {message.type}: {struct.to_string()}")
    return True

def on_ice_candidate(wb, mlineindex, candidate):
    """Handle ICE candidate generation. Log and send to remote peer."""
    cand_str = str(candidate)
    
    # Log full candidate first
    log(f"[ICE] Local candidate (full): {cand_str}")
    
    # Parse candidate type from string
    cand_type = "unknown"
    if "typ host" in cand_str:
        cand_type = "host"
    elif "typ srflx" in cand_str:
        cand_type = "srflx"
    elif "typ relay" in cand_str:
        cand_type = "relay"
    
    # Extract IP address (4th field in candidate string)
    parts = cand_str.split()
    ip_addr = parts[4] if len(parts) > 4 else "?"
    
    log(f"[ICE] Type: {cand_type}, IP: {ip_addr}")
    
    # Send to remote peer via WebSocket
    _run_coro_threadsafe(
        ws_send({
            "type": "ice",
            "candidate": {
                "candidate": cand_str,
                "sdpMLineIndex": int(mlineindex),
                "sdpMid": "0"
            }
        })
    )

def on_data_channel(wb: Any, channel: Any) -> None:
    """Handle incoming data channel."""
    def _on_open(ch: Any) -> None:
        label = ch.get_property("label") if hasattr(ch, "get_property") else "unknown"
        log(f"[DC] open label={label}")
        _send_hello(ch)

    def _on_msg_string(ch: Any, msg: str) -> None:
        _handle_control_message(msg)

    def _on_msg_data(ch: Any, buf: Any) -> None:
        """Handle binary data from browser."""
        try:
            if hasattr(buf, "get_data"):  # GLib.Bytes
                raw = buf.get_data()
            else:
                raw = bytes(buf)
            msg = raw.decode("utf-8", errors="replace")
            log(f"[DC] got data (utf8): {msg}")
            _handle_control_message(msg)
        except Exception as e:
            log("[DC] data parse error:", e)

    def _on_error(ch: Any, err: str) -> None:
        log(f"[DC] error: {err}")

    def _on_close(ch: Any) -> None:
        log("[DC] close")

    channel.connect("on-open", _on_open)
    channel.connect("on-close", _on_close)
    channel.connect("on-error", _on_error)
    channel.connect("on-message-string", _on_msg_string)
    channel.connect("on-message-data", _on_msg_data)
    log("[DC] handlers connected")


def add_ice_candidate_from_msg(msg: Dict[str, Any]):
    """Add ICE candidate from message."""
    if webrtc is None:
        return

    ice = msg.get("candidate") or msg.get("ice") or {}
    cand = ice.get("candidate")
    mline = ice.get("sdpMLineIndex", 0)

    if not cand:
        return
    
    # Simply add candidate - GStreamer will queue internally if needed
    log(f"[ICE] Adding remote candidate: {cand[:50]}...")
    try:
        webrtc.emit("add-ice-candidate", int(mline), str(cand))
    except Exception as e:
        log(f"[ICE] Error adding candidate: {e}")


def process_queued_ice_candidates():
    """Process all queued ICE candidates after remote description is set."""
    global ice_candidate_queue
    if webrtc is None:
        return
    
    while ice_candidate_queue:
        mline, cand = ice_candidate_queue.pop(0)
        try:
            log(f"[ICE] Adding queued candidate: {cand[:50]}...")
            webrtc.emit("add-ice-candidate", mline, cand)
        except Exception as e:
            log(f"[ICE] Error adding queued candidate: {e}")


def clamp_control(value: float, min_val: float = -CONTROL_RANGE, max_val: float = CONTROL_RANGE) -> float:
    """Clamp control value to valid range."""
    return max(min_val, min(max_val, value))


def parse_control_input(data: Dict[str, Any]) -> tuple[int, int, int]:
    """Parse and convert control input to UART format.
    
    Returns: (throttle: 0-1000, steer: -1000-1000, flags: int)
    """
    thr = clamp_control(float(data.get("throttle", 0.0)))
    st = clamp_control(float(data.get("steering", data.get("steer", 0.0))))
    flags = int(data.get("flags", 0))
    
    throttle = int((thr + 1.0) * 0.5 * THROTTLE_MAX)
    throttle = max(THROTTLE_MIN, min(THROTTLE_MAX, throttle))
    
    steer = int(st * STEER_MAX)
    steer = max(STEER_MIN, min(STEER_MAX, steer))
    
    return throttle, steer, flags


def _send_hello(ch: Any) -> None:
    """Send hello message to browser on data channel."""
    try:
        ch.emit("send-string", json.dumps({
            "t": int(time.time() * 1000),
            "hello": "from rpi"
        }))
        log("[DC] sent hello to browser")
    except Exception as e:
        log("[DC] send-string failed:", e)


def _handle_control_message(msg_text: str) -> None:
    """Handle control message from browser."""
    try:
        data = json.loads(msg_text)
        throttle, steer, flags = parse_control_input(data)
        uart_send(throttle, steer, flags)
    except json.JSONDecodeError as e:
        log("[DC] JSON parse error:", e)
    except Exception as e:
        log("[DC] control error:", e)

def set_remote_description(sdp_type: str, sdp_text: str):
    if webrtc is None:
        return

    log(f"[SDP] Setting remote {sdp_type}, length: {len(sdp_text)}")
    
    res, sdpmsg = GstSdp.SDPMessage.new()
    if res != GstSdp.SDPResult.OK:
        raise RuntimeError(f"SDPMessage.new() failed: {res}")

    res = GstSdp.sdp_message_parse_buffer(sdp_text.encode("utf-8"), sdpmsg)
    if res != GstSdp.SDPResult.OK:
        raise RuntimeError(f"sdp_message_parse_buffer failed: {res}")

    sdp_t = GstWebRTC.WebRTCSDPType.OFFER if sdp_type == "offer" else GstWebRTC.WebRTCSDPType.ANSWER
    desc = GstWebRTC.WebRTCSessionDescription.new(sdp_t, sdpmsg)

    # WAŻNE: czekamy aż remote SDP faktycznie się ustawi
    promise = Gst.Promise.new_with_change_func(on_set_remote_done, None, None)
    webrtc.emit("set-remote-description", desc, promise)

def on_set_remote_done(promise: Gst.Promise, *_):
    """Remote SDP has been set. Process queued ICE candidates."""
    global remote_desc_set
    
    result = promise.wait()
    log(f"[SDP] promise.wait() result: {result}")
    
    # Check for errors in promise
    if result == Gst.PromiseResult.REPLIED:
        reply = promise.get_reply()
        # Reply can be None even on success for set-remote-description
        log(f"[SDP] Promise replied, reply: {reply}")
        remote_desc_set = True
        log("[SDP] Remote description set successfully")
        process_queued_ice_candidates()
    elif result == Gst.PromiseResult.INTERRUPTED:
        log("[SDP] Promise interrupted")
    elif result == Gst.PromiseResult.EXPIRED:
        log("[SDP] Promise expired")
    else:
        log(f"[SDP] Promise result unknown: {result}")

def on_offer_created(promise: Gst.Promise, *_):
    if webrtc is None:
        return

    promise.wait()
    reply = promise.get_reply()
    if reply is None:
        log("[SDP] create-offer failed: reply is None")
        return
    offer = reply.get_value("offer")
    if offer is None:
        log("[SDP] offer is None")
        return

    # ustaw local
    webrtc.emit("set-local-description", offer, Gst.Promise.new())

    sdp_text = sdp_text_from_desc(offer)
    log("[SDP] sending OFFER")

    _run_coro_threadsafe(
        ws_send({"type": "sdp", "sdp": {"type": "offer", "sdp": sdp_text}})
    )



def create_offer() -> None:
    """Create WebRTC offer with data channel."""
    if webrtc is None:
        log("[OFFER] webrtc is None")
        return
        
    # Create data channel
    dc = webrtc.emit("create-data-channel", "control", None)
    log("[DC] created (control)")

    def _on_open(ch: Any) -> None:
        log("[DC] open")
        _send_hello(ch)

    def _on_close(ch: Any) -> None:
        log("[DC] close")

    def _on_error(ch: Any, err: str) -> None:
        log(f"[DC] error: {err}")

    def _on_msg_string(ch: Any, msg: str) -> None:
        _handle_control_message(msg)

    def _on_msg_data(ch: Any, buf: Any) -> None:
        try:
            if hasattr(buf, "get_data"):
                raw = buf.get_data()
            else:
                raw = bytes(buf)
            msg = raw.decode("utf-8", errors="replace")
            log(f"[DC] got data (utf8): {msg}")
            _handle_control_message(msg)
        except Exception as e:
            log("[DC] data parse error:", e)

    dc.connect("on-open", _on_open)
    dc.connect("on-close", _on_close)
    dc.connect("on-error", _on_error)
    dc.connect("on-message-string", _on_msg_string)
    dc.connect("on-message-data", _on_msg_data)

    # Create offer
    promise = Gst.Promise.new_with_change_func(on_offer_created, None, None)
    webrtc.emit("create-offer", None, promise)


def on_answer_created(promise: Gst.Promise, *_):
    if webrtc is None:
        return

    promise.wait()
    reply = promise.get_reply()
    if reply is None:
        log("[SDP] create-answer failed: reply is None")
        return
    answer = reply.get_value("answer")
    if answer is None:
        log("[SDP] create-answer failed: answer is None")
        return

    # ustaw local
    webrtc.emit("set-local-description", answer, Gst.Promise.new())

    sdp_text = sdp_text_from_desc(answer)
    log("[SDP] sending ANSWER (first 200 chars):", sdp_text[:200].replace("\n", "\\n"))

    _run_coro_threadsafe(
        ws_send({"type": "sdp", "sdp": {"type": "answer", "sdp": sdp_text}})
    )

def start_rpicam() -> int:
    global rpicam_proc
    rpicam_proc = subprocess.Popen(
        RPICAM_CMD,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0
    )
    assert rpicam_proc.stdout is not None
    return rpicam_proc.stdout.fileno()

async def ws_loop():
    global ws, pipe, webrtc, asyncio_loop, stopping

    asyncio_loop = asyncio.get_running_loop()

    # GLib mainloop w tle (stabilizuje GStreamer/WeRTC)
    t = threading.Thread(target=start_glib_mainloop, daemon=True)
    t.start()

    cam_fd = start_rpicam()
    log("[CAM] rpicam-vid started, fd:", cam_fd)

    pipe, webrtc = make_pipeline(cam_fd)

    # bus watch
    bus = pipe.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_bus_message)

    # callbacks
    webrtc.connect("on-ice-candidate", on_ice_candidate)
    
    # Monitor ICE gathering state
    def on_notify_ice_gathering_state(obj, pspec):
        state = webrtc.get_property("ice-gathering-state")
        log(f"[ICE] Gathering state: {state}")
    
    def on_notify_ice_connection_state(obj, pspec):
        state = webrtc.get_property("ice-connection-state")
        log(f"[ICE] Connection state: {state}")
    
    webrtc.connect("notify::ice-gathering-state", on_notify_ice_gathering_state)
    webrtc.connect("notify::ice-connection-state", on_notify_ice_connection_state)
    # webrtc.connect("on-data-channel", on_data_channel)  # dc created by us
    # start pipeline
    pipe.set_state(Gst.State.PLAYING)
    log("[GST] pipeline PLAYING")

    async with websockets.connect(SIGNALING_URL, ping_interval=20, ping_timeout=20) as sock:
        ws = sock
        await ws_send({"type": "join", "roomId": ROOM_ID, "role": "car"})
        log("[WS] joined", ROOM_ID)

        # add transceiver for sending video
        webrtc.emit("add-transceiver", GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY, Gst.Caps.from_string("application/x-rtp,media=video,encoding-name=H264,payload=96"))

        create_offer()

        async for message in ws:
            msg = json.loads(message)

            if msg.get("type") == "sdp":
                sdp = msg.get("sdp", {})
                sdp_type = sdp.get("type")
                sdp_text = sdp.get("sdp", "")

                if sdp_type == "answer":
                    log("[WS] got ANSWER")
                    set_remote_description("answer", sdp_text)

            elif msg.get("type") == "ice":
                add_ice_candidate_from_msg(msg)

            if stopping:
                break

def shutdown(*_):
    global stopping, pipe, rpicam_proc, glib_loop
    stopping = True
    log("Shutting down...")

    try:
        uart_send(0, 0, 1)
    except Exception:
        pass

    try:
        if pipe:
            pipe.set_state(Gst.State.NULL)
    except Exception:
        pass

    try:
        if rpicam_proc:
            rpicam_proc.terminate()
            try:
                rpicam_proc.wait(timeout=2)
            except Exception:
                rpicam_proc.kill()
    except Exception:
        pass

    try:
        ser.close()
    except Exception:
        pass

    try:
        if glib_loop is not None:
            glib_loop.quit()
    except Exception:
        pass

    sys.exit(0)

if __name__ == "__main__":
    # Disable verbose debug for now
    # import os
    # os.environ["GST_DEBUG"] = "webrtcbin:5,nice:5,nicesrc:5,nicesink:5"
    
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    asyncio.run(ws_loop())
