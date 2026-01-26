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
import requests
import serial

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstWebRTC", "1.0")
gi.require_version("GstSdp", "1.0")
gi.require_version("GLib", "2.0")

from gi.repository import Gst, GstWebRTC, GstSdp, GLib  # type: ignore

Gst.init(None)

# ===== CONFIG =====
# Cloudflare Realtime SFU
CF_REALTIME_APP_ID = os.environ.get("CF_REALTIME_APP_ID", "")
CF_REALTIME_TOKEN = os.environ.get("CF_REALTIME_TOKEN", "")
CF_REALTIME_API = "https://rtc.live.cloudflare.com/v1/apps"

UART_DEV = "/dev/serial0"
UART_BAUD = 115200

# Control ranges
THROTTLE_MIN, THROTTLE_MAX = 0, 1000
STEER_MIN, STEER_MAX = -1000, 1000
CONTROL_RANGE = 1.0  # ±1.0 from browser

# Kamera: H264 w stdout
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
pipe: Optional[Gst.Pipeline] = None
webrtc: Optional[Any] = None
rpicam_proc: Optional[subprocess.Popen] = None
stopping = False
glib_loop: Optional[GLib.MainLoop] = None
session_id: Optional[str] = None
track_id: Optional[str] = None

def log(*a):
    """Log with timestamp."""
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)

# ===== Control helpers =====
def clamp_control(value: float, min_val: float = -CONTROL_RANGE, max_val: float = CONTROL_RANGE) -> float:
    """Clamp control value to valid range."""
    return max(min_val, min(max_val, value))

def parse_control_input(data: Dict[str, Any]) -> tuple[int, int, int]:
    """Parse and convert control input to UART format."""
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
            "hello": "from rpi",
            "sessionId": session_id
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
    # Simple pipeline for Cloudflare SFU
    desc = (
        f"fdsrc fd={rfd} ! queue ! h264parse ! "
        f"rtph264pay pt=96 config-interval=1 ! "
        f"application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000 ! "
        f"queue ! wb. "
        f"webrtcbin name=wb bundle-policy=max-bundle "
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
    return True

def on_ice_candidate(wb, mlineindex, candidate):
    """Handle ICE candidate - send to Cloudflare."""
    cand_str = str(candidate)
    log(f"[ICE] Local candidate: {cand_str[:80]}")
    
    # Send to Cloudflare SFU
    if session_id and track_id:
        asyncio.create_task(send_ice_candidate(mlineindex, cand_str))

def on_data_channel(wb: Any, channel: Any) -> None:
    """Handle incoming data channel from browser."""
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


def set_remote_description(sdp_text: str):
    """Set remote SDP answer from Cloudflare."""
    if webrtc is None:
        return

    log(f"[SDP] Setting remote answer, length: {len(sdp_text)}")
    
    res, sdpmsg = GstSdp.SDPMessage.new()
    if res != GstSdp.SDPResult.OK:
        raise RuntimeError(f"SDPMessage.new() failed: {res}")

    res = GstSdp.sdp_message_parse_buffer(sdp_text.encode("utf-8"), sdpmsg)
    if res != GstSdp.SDPResult.OK:
        raise RuntimeError(f"sdp_message_parse_buffer failed: {res}")

    desc = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdpmsg)
    
    promise = Gst.Promise.new()
    webrtc.emit("set-remote-description", desc, promise)
    promise.wait()
    
    log("[SDP] Remote description set")

def on_offer_created(promise: Gst.Promise, *_):
    """Handle offer creation - send to Cloudflare SFU."""
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

    # Set local description
    webrtc.emit("set-local-description", offer, Gst.Promise.new())

    sdp_text = sdp_text_from_desc(offer)
    log("[SDP] Created offer, sending to Cloudflare SFU")

    # Send to Cloudflare SFU
    asyncio.create_task(send_offer_to_cloudflare(sdp_text))

async def send_offer_to_cloudflare(offer_sdp: str):
    """Send offer to Cloudflare Realtime SFU and get answer."""
    global session_id, track_id
    
    if not CF_REALTIME_APP_ID or not CF_REALTIME_TOKEN:
        log("[CF] Missing credentials - set CF_REALTIME_APP_ID and CF_REALTIME_TOKEN")
        return
    
    try:
        # Create new session
        url = f"{CF_REALTIME_API}/{CF_REALTIME_APP_ID}/sessions/new"
        headers = {
            "Authorization": f"Bearer {CF_REALTIME_TOKEN}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "sessionDescription": {
                "type": "offer",
                "sdp": offer_sdp
            }
        }
        
        log(f"[CF] Creating session at {url}")
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        if response.status_code == 201:
            data = response.json()
            session_id = data.get("sessionId")
            answer_sdp = data.get("sessionDescription", {}).get("sdp")
            
            # Extract track info if needed
            tracks = data.get("tracks", [])
            if tracks:
                track_id = tracks[0].get("trackName")
            
            log(f"[CF] Session created: {session_id}")
            log(f"[CF] Track: {track_id}")
            
            if answer_sdp:
                set_remote_description(answer_sdp)
            else:
                log("[CF] No answer SDP received")
        else:
            log(f"[CF] Error: status {response.status_code}")
            log(f"[CF] Response: {response.text}")
            
    except Exception as e:
        log(f"[CF] Request error: {e}")

async def send_ice_candidate(mline: int, candidate: str):
    """Send ICE candidate to Cloudflare SFU."""
    if not session_id:
        return
    
    try:
        url = f"{CF_REALTIME_API}/{CF_REALTIME_APP_ID}/sessions/{session_id}/tracks/new"
        headers = {
            "Authorization": f"Bearer {CF_REALTIME_TOKEN}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "iceCandidate": {
                "candidate": candidate,
                "sdpMLineIndex": mline
            }
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        if response.status_code != 200:
            log(f"[CF] ICE candidate error: {response.status_code}")
            
    except Exception as e:
        log(f"[CF] ICE send error: {e}")

def create_offer() -> None:
    """Create WebRTC offer."""
    if webrtc is None:
        log("[OFFER] webrtc is None")
        return
    
    promise = Gst.Promise.new_with_change_func(on_offer_created, None, None)
    webrtc.emit("create-offer", None, promise)

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

async def cloudflare_sfu_loop():
    """Main loop for Cloudflare Realtime SFU."""
    global pipe, webrtc
    
    if not CF_REALTIME_APP_ID or not CF_REALTIME_TOKEN:
        log("[CF] ERROR: Missing credentials!")
        log("[CF] Set CF_REALTIME_APP_ID and CF_REALTIME_TOKEN environment variables")
        return
    
    # GLib mainloop in background
    t = threading.Thread(target=start_glib_mainloop, daemon=True)
    t.start()
    
    try:
        # Start camera
        cam_fd = start_rpicam()
        log("[CAM] rpicam-vid started, fd:", cam_fd)
        
        # Create pipeline
        pipe, webrtc = make_pipeline(cam_fd)
        
        # Setup bus
        bus = pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message", on_bus_message)
        
        # Setup WebRTC callbacks
        webrtc.connect("on-ice-candidate", on_ice_candidate)
        webrtc.connect("on-data-channel", on_data_channel)
        
        # Monitor states
        def on_notify_ice_gathering_state(obj, pspec):
            state = webrtc.get_property("ice-gathering-state")
            log(f"[ICE] Gathering state: {state}")
        
        def on_notify_ice_connection_state(obj, pspec):
            state = webrtc.get_property("ice-connection-state")
            log(f"[ICE] Connection state: {state}")
        
        webrtc.connect("notify::ice-gathering-state", on_notify_ice_gathering_state)
        webrtc.connect("notify::ice-connection-state", on_notify_ice_connection_state)
        
        # Start pipeline
        pipe.set_state(Gst.State.PLAYING)
        log("[GST] Pipeline PLAYING")
        
        # Add video transceiver
        webrtc.emit(
            "add-transceiver",
            GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY,
            Gst.Caps.from_string("application/x-rtp,media=video,encoding-name=H264,payload=96")
        )
        
        # Create and send offer
        create_offer()
        
        # Keep running
        log("[CF] Streaming to Cloudflare Realtime SFU...")
        while not stopping:
            await asyncio.sleep(1)
            
    except Exception as e:
        log(f"[CF] Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if pipe:
            pipe.set_state(Gst.State.NULL)
            log("[GST] Pipeline stopped")

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
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    
    log("[CF] Starting Cloudflare Realtime SFU client")
    asyncio.run(cloudflare_sfu_loop())
