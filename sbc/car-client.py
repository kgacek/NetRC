#!/usr/bin/env python3
import asyncio
import json
import signal
import sys
import subprocess
import threading
from typing import Optional, Any, Dict

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
    print(*a, flush=True)

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
    # Pipeline: fdsrc -> h264parse -> rtph264pay -> application/x-rtp -> webrtcbin
    #
    # Uwaga: "wb." prosi webrtcbin o dynamiczny sink pad (to jest OK)
    #
    desc = (
        f"fdsrc fd={rfd} ! queue ! h264parse ! "
        f"rtph264pay pt=96 config-interval=1 ! "
        f"application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000 ! "
        f"queue ! wb. "
        f"webrtcbin name=wb bundle-policy=max-bundle "
        f"stun-server=stun://stun.l.google.com:19302 "
        f"turn-server=turn://webrtc:webrtc@turn.anyfirewall.com:443?transport=tcp "
    )

    p = Gst.parse_launch(desc)
    wb = p.get_by_name("wb")
    # wb.emit("add-transceiver", GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY, Gst.Caps.from_string("application/x-rtp,media=video,encoding-name=H264,payload=96"))
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
    # UJEDNOLICONE Z INDEX.HTML:
    # wysyłamy: {type:"ice", candidate:{candidate, sdpMLineIndex, sdpMid}}
    _run_coro_threadsafe(
        ws_send({
            "type": "ice",
            "candidate": {
                "candidate": str(candidate),
                "sdpMLineIndex": int(mlineindex),
                "sdpMid": "0"
            }
        })
    )

def on_data_channel(wb, channel):
    def _on_open(ch):
        log("[DC] open")

    def _on_msg(ch, msg: str):
        try:
            data = json.loads(msg)

            # JS wysyła: { t, throttle, steering } (+ opcjonalnie flags)
            thr = float(data.get("throttle", 0.0))
            st  = float(data.get("steering", data.get("steer", 0.0)))  # kompatybilność wstecz
            flags = int(data.get("flags", 0))

            # clamp -1..1
            thr = max(-1.0, min(1.0, thr))
            st  = max(-1.0, min(1.0, st))

            # mapowanie do protokołu UART:
            # throttle: w ESP oczekuje 0..1000
            # steering: -1000..1000
            throttle = int((thr + 1.0) * 0.5 * 1000)   # -1..1 -> 0..1000
            throttle = max(0, min(1000, throttle))

            steer = int(st * 1000)                    # -1..1 -> -1000..1000
            steer = max(-1000, min(1000, steer))

            uart_send(throttle, steer, flags)
        except Exception as e:
            log("[DC] parse error:", e)

    channel.connect("on-open", _on_open)
    channel.connect("on-message-string", _on_msg)


def add_ice_candidate_from_msg(msg: Dict[str, Any]):
    # Przyjmujemy oba formaty (na wszelki wypadek):
    # 1) msg.candidate = {candidate, sdpMLineIndex, sdpMid}
    # 2) msg.ice = {candidate, sdpMLineIndex} (stare)
    if webrtc is None:
        return

    ice = msg.get("candidate") or msg.get("ice") or {}
    cand = ice.get("candidate")
    mline = ice.get("sdpMLineIndex", 0)

    if cand:
        webrtc.emit("add-ice-candidate", int(mline), str(cand))

def set_remote_description(sdp_type: str, sdp_text: str):
    if webrtc is None:
        return

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
    # remote SDP ustawione
    if webrtc is None:
        return

    promise.wait()
    reply = promise.get_reply()
    if reply is None:
        log("[SDP] set-remote-description failed: reply is None")
        return
    log("[SDP] remote description set")

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

def create_offer():
    # create data channel
    dc = webrtc.emit("create-data-channel", "control", None)

    # connect dc callbacks
    def _on_open(ch):
        log("[DC] open")

    def _on_msg(ch, msg: str):
        try:
            data = json.loads(msg)
            thr = float(data.get("throttle", 0.0))
            st = float(data.get("steer", 0.0))
            flags = int(data.get("flags", 0))

            throttle = max(-1000, min(1000, int(thr * 1000)))
            steer = max(-1000, min(1000, int(st * 1000)))

            uart_send(throttle, steer, flags)
        except Exception as e:
            log("[DC] parse error:", e)

    dc.connect("on-open", _on_open)
    dc.connect("on-message-string", _on_msg)

    # create offer
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
    # webrtc.connect("on-data-channel", on_data_channel)  # dc created by us

    # add transceiver for sending video
    # webrtc.emit("add-transceiver", GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY, Gst.Caps.from_string("application/x-rtp,media=video,encoding-name=H264,payload=96"))
    #webrtc.emit("add-transceiver", GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY, None)
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
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    asyncio.run(ws_loop())
