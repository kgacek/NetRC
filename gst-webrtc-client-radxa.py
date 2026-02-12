#!/usr/bin/env python3
"""
Hardware-accelerated WebRTC streaming using GStreamer
Camera -> Hardware H.264 -> WebRTC (no re-encoding)
"""
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstWebRTC', '1.0')
gi.require_version('GstSdp', '1.0')
gi.require_version('GstRtp', '1.0')
gi.require_version('GstApp', '1.0')
from gi.repository import Gst, GstWebRTC, GstSdp, GstRtp, GstApp, GLib
import json
import re
import os
import sys
import logging
import stat
import time
import threading
import serial
import serial.tools.list_ports
import asyncio
import requests
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cloudflare configuration
CLOUDFLARE_APP_ID = os.getenv('CF_REALTIME_APP_ID')
CLOUDFLARE_APP_SECRET = os.getenv('CF_REALTIME_TOKEN')
CLOUDFLARE_API_BASE = 'https://rtc.live.cloudflare.com/v1'
SIGNALING_SERVER = os.getenv('SIGNALING_SERVER', 'https://79-76-127-159.nip.io')

# TURN configuration (optional)
TURN_URL = os.getenv('TURN_URL')
TURN_USER = os.getenv('TURN_USER')
TURN_PASS = os.getenv('TURN_PASS')
CF_TURN_KEY_ID = os.getenv('CF_TURN_KEY_ID')
CF_TURN_TOKEN = os.getenv('CF_TURN_TOKEN')
TURN_TTL_SECONDS = int(os.getenv('TURN_TTL_SECONDS', '3600'))

# UART configuration for car control
UART_DEV = os.getenv('UART_DEV', '/dev/ttyS0')
UART_BAUD = int(os.getenv('UART_BAUD', '115200'))

# Video configuration
WIDTH = 1920
HEIGHT = 1080
FRAMERATE = 30
BITRATE = 6000000  # 6 Mbps for 1080p30

# Low-latency tuning
QUEUE_MAX_TIME_NS = 20_000_000  # 20 ms
QUEUE_MAX_BUFFERS = 0
APPsrc_HIGH_WATERMARK = 128 * 1024  # bytes
APPsrc_LOW_WATERMARK = 64 * 1024    # bytes

class CarController:
    """
    Controls the RC car via UART based on commands from DataChannel
    """
    def __init__(self, uart_dev=UART_DEV, uart_baud=UART_BAUD):
        self.uart_dev = uart_dev
        self.uart_baud = uart_baud
        self.ser = None
        self.seq = 0
        
    def init_uart(self):
        """Initialize UART connection"""
        try:
            self.ser = serial.Serial(self.uart_dev, self.uart_baud, timeout=0.1)
            logger.info(f"UART initialized: {self.uart_dev} @ {self.uart_baud}")
            time.sleep(0.2)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            return True
        except Exception as e:
            logger.warning(f"UART not available: {e}. Running in video-only mode.")
            return False
    
    def send_command(self, throttle, steer):
        """Send command to ESP32 via UART"""
        if not self.ser:
            logger.warning("UART not available, cannot send command")
            return
        
        self.seq = (self.seq + 1) & 0xFFFF
        cmd = f"T,{int(throttle)},{int(steer)},0,{self.seq}\n"
        
        try:
            self.ser.write(cmd.encode('ascii'))
            self.ser.flush()
            # Only log non-zero commands to reduce spam
            if throttle != 0 or steer != 0:
                logger.info(f"UART: T={throttle}, S={steer}")
        except Exception as e:
            logger.error(f"UART send error: {e}")
    
    def process_control_message(self, message):
        """Process control message from DataChannel"""
        try:
            data = json.loads(message)
            throttle = int(data.get('throttle', 0))
            steer = int(data.get('steer', 0))
            if throttle != 0 or steer != 0:
                logger.info(f"Received control message: throttle={throttle}, steer={steer}")
            # Clamp values to safe ranges
            throttle = max(-200, min(200, throttle))
            steer = max(-1000, min(1000, steer))
            
            self.send_command(throttle, steer)
            
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in control message: {message}")
        except Exception as e:
            logger.error(f"Error processing control message: {e}")
    
    def stop(self):
        """Stop the car and close UART"""
        if self.ser:
            self.send_command(0, 0)
            time.sleep(0.1)
            self.ser.close()
            logger.info("UART closed")


async def run_control_subscriber(car_controller, control_session_id):
    """
    Separate PeerConnection to receive control DataChannel from browser
    """
    try:
        logger.info(f"Setting up control subscriber for session: {control_session_id}")
        
        # Create peer connection for receiving control
        pc_control = RTCPeerConnection(
            configuration=RTCConfiguration(
                iceServers=[RTCIceServer(urls=['stun:stun.cloudflare.com:3478'])]
            )
        )
        
        # Use Cloudflare /datachannels/establish API
        url = f"{CLOUDFLARE_API_BASE}/apps/{CLOUDFLARE_APP_ID}/sessions/new"
        headers = {
            'Authorization': f'Bearer {CLOUDFLARE_APP_SECRET}',
            'Content-Type': 'application/json'
        }
        
        # Create our own session - use requests (synchronous) for reliability
        logger.info("Creating subscriber session...")
        response = requests.post(url, headers=headers, timeout=10)
        if response.status_code != 201:
            logger.error(f"Failed to create subscriber session: {response.status_code} - {response.text}")
            return None
        data = response.json()
        subscriber_session_id = data['sessionId']
        logger.info(f"Created subscriber session: {subscriber_session_id}")
        
        # Step 1: Establish DataChannel transport (like Cloudflare example)
        establish_url = f"{CLOUDFLARE_API_BASE}/apps/{CLOUDFLARE_APP_ID}/sessions/{subscriber_session_id}/datachannels/establish"
        establish_payload = {
            'dataChannel': {
                'location': 'remote',
                'dataChannelName': 'server-events'
            }
        }
        
        logger.info(f"Establishing DataChannel transport...")
        
        response = requests.post(establish_url, headers=headers, json=establish_payload, timeout=10)
        response_text = response.text
        logger.info(f"Establish transport response: {response_text}")
        
        if response.status_code in [200, 201]:
            data = json.loads(response_text)
            
            if data.get('requiresImmediateRenegotiation'):
                # We got an offer from Cloudflare, need to answer
                await pc_control.setRemoteDescription(RTCSessionDescription(
                    sdp=data['sessionDescription']['sdp'],
                    type=data['sessionDescription']['type']
                ))
                logger.info("Received offer from Cloudflare, creating answer")
                
                # Create answer
                answer = await pc_control.createAnswer()
                await pc_control.setLocalDescription(answer)
                
                # Wait for ICE gathering
                while pc_control.iceGatheringState != 'complete':
                    await asyncio.sleep(0.1)
                
                # Send answer back to Cloudflare
                renegotiate_url = f"{CLOUDFLARE_API_BASE}/apps/{CLOUDFLARE_APP_ID}/sessions/{subscriber_session_id}/renegotiate"
                renegotiate_payload = {
                    'sessionDescription': {
                        'type': 'answer',
                        'sdp': pc_control.localDescription.sdp
                    }
                }
                
                renegotiate_response = requests.put(renegotiate_url, headers=headers, json=renegotiate_payload, timeout=10)
                if renegotiate_response.status_code in [200, 201]:
                    logger.info("Transport renegotiation complete")
                else:
                    logger.error(f"Failed to send answer: {renegotiate_response.status_code} - {renegotiate_response.text}")
                    return None
            elif data.get('sessionDescription'):
                # Got answer from Cloudflare directly
                await pc_control.setRemoteDescription(RTCSessionDescription(
                    sdp=data['sessionDescription']['sdp'],
                    type=data['sessionDescription']['type']
                ))
                logger.info("Transport established")
        else:
            logger.error(f"Failed to establish transport: {response.status_code} - {response_text}")
            return None
        
        # Step 2: Subscribe to remote 'control' DataChannel from browser session
        dc_new_url = f"{CLOUDFLARE_API_BASE}/apps/{CLOUDFLARE_APP_ID}/sessions/{subscriber_session_id}/datachannels/new"
        dc_new_payload = {
            'dataChannels': [
                {
                    'location': 'remote',
                    'sessionId': control_session_id,
                    'dataChannelName': 'control'
                }
            ]
        }
        
        logger.info(f"Subscribing to control DataChannel from session {control_session_id}")
        
        # Wait a bit for transport to be fully ready
        await asyncio.sleep(1)
        
        response = requests.post(dc_new_url, headers=headers, json=dc_new_payload, timeout=10)
        response_text = response.text
        logger.info(f"DataChannel subscription response: {response_text}")
        
        if response.status_code in [200, 201]:
            data = json.loads(response_text)
            
            # Create negotiated DataChannel with ID from API
            dc_id = data['dataChannels'][0]['id']
            logger.info(f">>> RPi subscribing to remote DataChannel with ID: {dc_id}")
            logger.info(f">>> Browser should have created local DataChannel with same ID: {dc_id}")
            
            # Wait a bit before creating DataChannel to ensure transport is ready
            await asyncio.sleep(1)
            
            # Create negotiated DataChannel - this will trigger ondatachannel when connected
            control_dc = pc_control.createDataChannel('control-subscribed', negotiated=True, id=dc_id)
            logger.info(f"DataChannel object created: {control_dc}")
            logger.info(f"DataChannel readyState: {control_dc.readyState}")
            logger.info(f"DataChannel label: {control_dc.label}")
            
            @control_dc.on('open')
            def on_open():
                logger.info(f"✓✓✓ Control DataChannel OPENED! ✓✓✓")
                logger.info(f"ReadyState: {control_dc.readyState}, Label: {control_dc.label}, ID: {control_dc.id}")
            
            @control_dc.on('message')
            def on_message(message):
                if car_controller:
                    car_controller.process_control_message(message)
            
            @control_dc.on('close')
            def on_close():
                logger.info("Control DataChannel closed")
                if car_controller:
                    car_controller.send_command(0, 0)
            
            @control_dc.on('error')
            def on_error(error):
                logger.error(f"✗ Control DataChannel error: {error}")
            
            # Monitor connection state
            @pc_control.on('connectionstatechange')
            async def on_connectionstatechange():
                logger.info(f"Control PC connectionState: {pc_control.connectionState}")
                if pc_control.connectionState in ['failed', 'closed']:
                    logger.warning("Control connection failed or closed")
                    if car_controller:
                        car_controller.send_command(0, 0)
            
            @pc_control.on('iceconnectionstatechange')
            async def on_iceconnectionstatechange():
                logger.info(f"Control PC iceConnectionState: {pc_control.iceConnectionState}")
            
            # Wait a bit to see if DataChannel opens
            await asyncio.sleep(2)
            logger.info(f"After 2s, DataChannel readyState: {control_dc.readyState}")
            
            logger.info(f"Control DataChannel subscribed successfully")
        else:
            logger.error(f"Failed to subscribe to DataChannel: {response.status_code} - {response_text}")
            return None
        
        return pc_control
        
    except Exception as e:
        logger.error(f"Error in control subscriber: {e}", exc_info=True)
        return None


class GStreamerWebRTC:
    def __init__(self):
        Gst.init(None)
        self.enable_gst_debug()
        self.log_gst_versions()
        self.pipe = None
        self.webrtc = None
        self.session_id = None
        self.car_controller = None
        self.control_session_id = None
        self.pc_control = None
        self.rpicam_restart_count = 0
        self.fps_count = 0
        self.rtp_pps_count = 0
        self.fps_last_time = time.monotonic()
        self.stats_poll_id = None
        self.ice_candidate_count = 0

    def log_gst_versions(self):
        try:
            logger.info(f"GStreamer version: {Gst.version_string()}")
        except Exception as e:
            logger.warning(f"Failed to read GStreamer version: {e}")

        try:
            registry = Gst.Registry.get()
            webrtc_plugin = registry.find_plugin("webrtc")
            if webrtc_plugin:
                logger.info(
                    f"webrtc plugin: {webrtc_plugin.get_version()} ({webrtc_plugin.get_filename()})"
                )
            nice_plugin = registry.find_plugin("nice")
            if nice_plugin:
                logger.info(
                    f"nice plugin: {nice_plugin.get_version()} ({nice_plugin.get_filename()})"
                )
        except Exception as e:
            logger.warning(f"Failed to read plugin versions: {e}")

    def enable_gst_debug(self):
        if os.getenv("GST_DEBUG_WEBRTC") != "1":
            return
        try:
            Gst.debug_set_threshold_from_string("webrtcbin:6,dtls:6,srtp:6,nice:6,libnice:6", True)
            logger.info("Enabled GStreamer debug for webrtc/dtls/srtp/nice")
        except Exception as e:
            logger.warning(f"Failed to enable GStreamer debug: {e}")

    def fetch_turn_credentials(self):
        """Fetch TURN credentials from Cloudflare TURN API."""
        if not CF_TURN_KEY_ID or not CF_TURN_TOKEN:
            return None, None, None

        url = f"{CLOUDFLARE_API_BASE}/turn/keys/{CF_TURN_KEY_ID}/credentials/generate-ice-servers"
        headers = {
            'Authorization': f'Bearer {CF_TURN_TOKEN}',
            'Content-Type': 'application/json'
        }
        payload = {'ttl': TURN_TTL_SECONDS}

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=5)
            if response.status_code not in (200, 201):
                logger.warning(f"TURN credentials fetch failed: {response.status_code} - {response.text}")
                return None, None, None

            data = response.json()
            ice_servers = data.get('iceServers', [])
            turn_server = next((s for s in ice_servers if 'username' in s and 'credential' in s), None)
            if not turn_server:
                logger.warning("TURN credentials response missing turn server")
                return None, None, None

            turn_urls = turn_server.get('urls', [])
            if not turn_urls:
                logger.warning("TURN credentials response missing turn URLs")
                return None, None, None

            return turn_urls[0], turn_server.get('username'), turn_server.get('credential')
        except Exception as e:
            logger.warning(f"TURN credentials fetch error: {e}")
            return None, None, None
    
    def create_pipeline(self):
        """Create GStreamer pipeline: v4l2src -> mpph264enc -> webrtcbin"""
        logger.info("Creating GStreamer pipeline (v4l2src -> mpph264enc -> webrtcbin)")

        self.pipe = Gst.Pipeline.new("pipeline0")

        v4l2src = Gst.ElementFactory.make("v4l2src", "v4l2src0")
        caps_raw = Gst.ElementFactory.make("capsfilter", "caps_raw")
        enc = Gst.ElementFactory.make("mpph264enc", "mpph264enc0")
        h264parse = Gst.ElementFactory.make("h264parse", "h264parse0")
        caps_h264 = Gst.ElementFactory.make("capsfilter", "caps_h264")
        pay = Gst.ElementFactory.make("rtph264pay", "rtph264pay0")
        queue = Gst.ElementFactory.make("queue", "queue0")
        caps_rtp = Gst.ElementFactory.make("capsfilter", "caps_rtp")
        self.webrtc = Gst.ElementFactory.make("webrtcbin", "sendrecv")

        if not all([v4l2src, caps_raw, enc, h264parse, caps_h264, pay, queue, caps_rtp, self.webrtc]):
            raise RuntimeError("Failed to create GStreamer elements")

        v4l2src.set_property("device", "/dev/video0")
        v4l2src.set_property("io-mode", 2)  # mmap

        caps_raw.set_property(
            "caps",
            Gst.Caps.from_string(
                f"video/x-raw,format=NV12,width={WIDTH},height={HEIGHT},framerate={FRAMERATE}/1"
            ),
        )

        enc.set_property("bps", BITRATE)
        enc.set_property("bps-max", BITRATE)
        enc.set_property("gop", FRAMERATE)
        enc.set_property("rc-mode", "cbr")
        enc.set_property("profile", "baseline")
        enc.set_property("header-mode", "each-idr")

        caps_h264.set_property(
            "caps",
            Gst.Caps.from_string("video/x-h264,stream-format=avc,alignment=au,profile=baseline"),
        )

        pay.set_property("pt", 96)
        pay.set_property("mtu", 1200)
        pay.set_property("config-interval", 1)
        pay.set_property("aggregate-mode", "zero-latency")

        queue.set_property("leaky", 2)  # downstream
        queue.set_property("max-size-time", QUEUE_MAX_TIME_NS)
        queue.set_property("max-size-buffers", 0)
        queue.set_property("max-size-bytes", 0)

        caps_rtp.set_property(
            "caps",
            Gst.Caps.from_string(
                "application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000"
            ),
        )

        self.webrtc.set_property("bundle-policy", "max-bundle")
        self.webrtc.set_property("stun-server", "stun://stun.cloudflare.com:3478")

        self.pipe.add(v4l2src)
        self.pipe.add(caps_raw)
        self.pipe.add(enc)
        self.pipe.add(h264parse)
        self.pipe.add(caps_h264)
        self.pipe.add(pay)
        self.pipe.add(queue)
        self.pipe.add(caps_rtp)
        self.pipe.add(self.webrtc)

        if not v4l2src.link(caps_raw):
            raise RuntimeError("Failed to link v4l2src -> caps_raw")
        if not caps_raw.link(enc):
            raise RuntimeError("Failed to link caps_raw -> mpph264enc")
        if not enc.link(h264parse):
            raise RuntimeError("Failed to link mpph264enc -> h264parse")
        if not h264parse.link(caps_h264):
            raise RuntimeError("Failed to link h264parse -> caps_h264")
        if not caps_h264.link(pay):
            raise RuntimeError("Failed to link caps_h264 -> rtph264pay")
        if not pay.link(queue):
            raise RuntimeError("Failed to link rtph264pay -> queue")
        if not queue.link(caps_rtp):
            raise RuntimeError("Failed to link queue -> caps_rtp")

        # Link RTP to webrtcbin request pad
        rtp_src_pad = caps_rtp.get_static_pad("src")
        webrtc_sink_pad = self.webrtc.get_request_pad("sink_%u")
        if not rtp_src_pad or not webrtc_sink_pad:
            raise RuntimeError("Failed to get pads for webrtcbin link")
        if rtp_src_pad.link(webrtc_sink_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError("Failed to link RTP to webrtcbin")
        
        # Connect signals
        self.webrtc.connect('on-negotiation-needed', self.on_negotiation_needed)
        self.webrtc.connect('on-ice-candidate', self.on_ice_candidate)
        self.webrtc.connect('notify::ice-connection-state', self.on_ice_connection_state)
        self.webrtc.connect('notify::ice-gathering-state', self.on_ice_gathering_state)
        self.webrtc.connect('notify::connection-state', self.on_connection_state)
        try:
            self.webrtc.connect('notify::dtls-connection-state', self.on_dtls_connection_state)
        except Exception:
            pass
        self.webrtc.connect('pad-added', self.on_webrtc_pad_added)

        # Watch bus messages for DTLS/SRTP/ICE issues
        bus = self.pipe.get_bus()
        if bus:
            bus.add_signal_watch()
            bus.connect('message', self.on_bus_message)

        # Configure TURN if provided
        turn_url = TURN_URL
        turn_user, turn_pass = (TURN_USER, TURN_PASS)

        if not (turn_url and turn_user and turn_pass):
            turn_url, turn_user, turn_pass = self.fetch_turn_credentials()

        if turn_url and turn_user and turn_pass:
            try:
                if turn_url.startswith('turn:') or turn_url.startswith('turns:'):
                    scheme, rest = turn_url.split(':', 1)
                    turn_uri = f"{scheme}://{turn_user}:{turn_pass}@{rest.lstrip('//')}"
                else:
                    turn_uri = f"turn://{turn_user}:{turn_pass}@{turn_url}"

                self.webrtc.set_property('turn-server', turn_uri)
                logger.info(f"webrtcbin TURN server configured: {turn_uri}")
            except Exception as e:
                logger.warning(f"Failed to set TURN server: {e}")

        # Prefer non-trickle ICE so candidates are embedded in SDP
        try:
            self.webrtc.set_property('trickle-ice', False)
            logger.info("webrtcbin trickle-ice disabled (embed candidates in SDP)")
        except Exception:
            logger.info("webrtcbin trickle-ice property not available")
        
        # Let webrtcbin create a single transceiver from the linked RTP pad.
        # Explicit add-transceiver can create a second m=video section and confuse SFU.
        self.transceiver = None
        
        # Flag to track if negotiation has been started
        self.negotiation_started = False
        self.rtp_caps_check_count = 0
        
        # Track ICE gathering state
        self.pending_offer_sdp = None

        # Start FPS measurement on H.264 parser output (frame-level)
        self.setup_fps_probe()
        
    def on_negotiation_needed(self, element):
        """Handle negotiation needed"""
        if not self.rtp_caps_ready():
            logger.info("Negotiation needed but RTP caps not ready yet.")
            return
        if self.negotiation_started:
            logger.info("Negotiation already started, ignoring.")
            return
        self.negotiation_started = True
        logger.info("Negotiation needed, creating offer...")
        promise = Gst.Promise.new_with_change_func(self.on_offer_created, element, None)
        element.emit('create-offer', None, promise)
    
    def on_offer_created(self, promise, element, _):
        """Handle offer created"""
        promise.wait()
        reply = promise.get_reply()
        offer = reply.get_value('offer')
        
        # Set local description in a separate promise
        set_promise = Gst.Promise.new()
        element.emit('set-local-description', offer, set_promise)
        
        # Wait for ICE gathering and then use local-description SDP (includes candidates)
        def _send_when_ice_ready():
            logger.info("Waiting for ICE gathering to complete before sending offer...")
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                state = self.webrtc.get_property('ice-gathering-state')
                if state == GstWebRTC.WebRTCICEGatheringState.COMPLETE:
                    break
                time.sleep(0.05)

            # Use local-description SDP (should contain a=candidate for non-trickle)
            local_desc = self.webrtc.get_property('local-description')
            sdp = local_desc.sdp.as_text() if local_desc else offer.sdp.as_text()

            # Force sendonly to avoid SFU treating this as recv-capable
            if "a=sendrecv" in sdp:
                sdp = sdp.replace("a=sendrecv\r\n", "a=sendonly\r\n")
                sdp = sdp.replace("a=sendrecv\n", "a=sendonly\n")

            # If we're embedding candidates in SDP, strip trickle hint
            if "a=ice-options:trickle" in sdp:
                sdp = sdp.replace("a=ice-options:trickle\r\n", "")
                sdp = sdp.replace("a=ice-options:trickle\n", "")

            logger.info("Sending offer to Cloudflare (ice-lite mode)...")
            self.send_offer_to_cloudflare(sdp)

        import threading
        threading.Thread(target=_send_when_ice_ready, daemon=True).start()
    
    def on_ice_candidate(self, element, mlineindex, candidate):
        """Handle ICE candidate - not needed with ice-lite server"""
        self.ice_candidate_count += 1
        logger.info(f"ICE candidate #{self.ice_candidate_count}: mline={mlineindex}")
        logger.debug(f"ICE candidate: {candidate}")
    
    def on_webrtc_pad_added(self, element, pad):
        """Called when pad is added to webrtcbin - set direction and trigger negotiation"""
        logger.info(f"WebRTC pad added: {pad.get_name()}, caps: {pad.get_current_caps()}")

        transceiver = None
        try:
            transceiver = pad.get_property('transceiver')
        except Exception:
            transceiver = None

        if transceiver:
            self.transceiver = transceiver
            try:
                self.transceiver.set_property(
                    'direction',
                    GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY
                )
                logger.info("Set transceiver direction to SENDONLY")
            except Exception as e:
                logger.warning(f"Failed to set transceiver direction: {e}")

        # Trigger negotiation once when first pad is added (means rtph264pay connected)
        if not self.negotiation_started:
            logger.info("RTP pad connected, triggering negotiation in 1 second...")
            GLib.timeout_add(1000, self.trigger_negotiation)
    
    def on_transceiver_sender_ready(self, transceiver, pspec):
        """Called when transceiver sender is ready"""
        sender = transceiver.get_property('sender')
        if sender and not self.negotiation_started:
            logger.info("Transceiver sender ready, triggering negotiation...")
            GLib.timeout_add(500, self.trigger_negotiation)
    
    def on_ice_gathering_state(self, element, pspec):
        """Monitor ICE gathering state"""
        state = element.get_property('ice-gathering-state')
        logger.info(f"ICE gathering state: {state}")
        if state == GstWebRTC.WebRTCICEGatheringState.COMPLETE and self.ice_candidate_count == 0:
            logger.warning("ICE gathering completed but no candidates were generated")
    
    def on_ice_connection_state(self, element, pspec):
        """Monitor ICE connection state"""
        state = element.get_property('ice-connection-state')
        logger.info(f"ICE connection state: {state}")

    def on_connection_state(self, element, pspec):
        """Monitor overall WebRTC connection state"""
        state = element.get_property('connection-state')
        logger.info(f"WebRTC connection state: {state}")

    def on_dtls_connection_state(self, element, pspec):
        try:
            state = element.get_property('dtls-connection-state')
            logger.info(f"DTLS connection state: {state}")
        except Exception:
            pass

    def on_bus_message(self, bus, message):
        mtype = message.type
        if mtype == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error(f"GST ERROR: {err} ({debug})")
        elif mtype == Gst.MessageType.WARNING:
            err, debug = message.parse_warning()
            logger.warning(f"GST WARNING: {err} ({debug})")
        elif mtype == Gst.MessageType.ELEMENT:
            s = message.get_structure()
            if not s:
                return
            name = s.get_name()
            if any(k in name.lower() for k in ["dtls", "srtp", "ice", "webrtc", "nice"]):
                try:
                    logger.info(f"GST ELEMENT: {name} {s.to_string()}")
                except Exception:
                    logger.info(f"GST ELEMENT: {name}")
    
    def send_offer_to_cloudflare(self, offer_sdp):
        """Send offer to Cloudflare Calls API (synchronous)"""
        import requests
        
        # Create session NOW, right before sending offer
        if not self.session_id:
            logger.info("Creating Cloudflare session...")
            url = f"{CLOUDFLARE_API_BASE}/apps/{CLOUDFLARE_APP_ID}/sessions/new"
            headers = {'Authorization': f'Bearer {CLOUDFLARE_APP_SECRET}'}
            
            response = requests.post(url, headers=headers, timeout=10)
            if response.status_code != 201:
                logger.error(f"Failed to create session: {response.status_code}")
                return
            
            data = response.json()
            self.session_id = data['sessionId']
            logger.info(f"Session created: {self.session_id}")
            
            # Register with signaling server
            try:
                response = requests.post(
                    f"{SIGNALING_SERVER}/api/publish",
                    json={'sessionId': self.session_id},
                    timeout=5
                )
                if response.status_code == 200:
                    logger.info("Session registered with signaling server")
            except Exception as e:
                logger.warning(f"Failed to register with signaling server: {e}")
        
        logger.info("Sending offer to Cloudflare...")
        logger.info(f"Offer SDP:\n{offer_sdp}")
        if "a=candidate" not in offer_sdp:
            logger.warning("Offer SDP contains no ICE candidates (SFU may not receive media)")
        if "typ srflx" not in offer_sdp and "typ relay" not in offer_sdp:
            logger.warning("No srflx/relay candidates in SDP (NAT traversal may fail without TURN)")
        
        # Extract video mid - GStreamer webrtcbin always uses mid=0 for first track
        video_mid = "0"
        
        # Try to find it in SDP anyway
        lines = offer_sdp.split('\r\n')
        in_video_section = False
        for line in lines:
            if line.startswith('m=video'):
                in_video_section = True
            elif line.startswith('m='):
                in_video_section = False
            elif in_video_section and line.startswith('a=mid:'):
                video_mid = line.split(':')[1].strip()
                logger.info(f"Found video mid in SDP: {video_mid}")
                break
        
        logger.info(f"Using video mid: {video_mid}")
        
        url = f"{CLOUDFLARE_API_BASE}/apps/{CLOUDFLARE_APP_ID}/sessions/{self.session_id}/tracks/new"
        headers = {
            'Authorization': f'Bearer {CLOUDFLARE_APP_SECRET}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'sessionDescription': {
                'type': 'offer',
                'sdp': offer_sdp
            },
            'tracks': [
                {
                    'location': 'local',
                    'trackName': 'camera',
                    'mid': video_mid
                }
            ]
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            if response.status_code not in (200, 201):
                logger.error(f"Failed to send offer: {response.status_code} - {response.text}")
                return
            
            data = response.json()
            logger.info("Received answer from Cloudflare")
            logger.info(f"Tracks response: {data.get('tracks')}")

            if data.get('tracks') and data['tracks'][0].get('errorCode'):
                logger.error(f"Track error: {data['tracks'][0].get('errorDescription')}")
                return

            if not data.get('sessionDescription'):
                logger.error("No sessionDescription in Cloudflare response")
                return

            answer_sdp = data['sessionDescription']['sdp']
            logger.info(f"Answer SDP (first 400 chars):\n{answer_sdp[:400]}")
            try:
                with open('/tmp/cf-answer.sdp', 'w') as f:
                    f.write(answer_sdp)
            except Exception as e:
                logger.warning(f"Failed to write /tmp/cf-answer.sdp: {e}")

            if "a=inactive" in answer_sdp:
                logger.warning("Answer SDP has a=inactive for video")
            if "a=recvonly" not in answer_sdp and "a=sendrecv" not in answer_sdp:
                logger.warning("Answer SDP missing recvonly/sendrecv for video")
            if "a=ice-pwd:" not in answer_sdp:
                logger.warning("Answer SDP missing ice-pwd")
            
            # Print session info on first successful connection
            if not hasattr(self, '_session_info_printed'):
                print(f"\n{'='*60}")
                print(f"SESSION ID: {self.session_id}")
                print(f"Signaling Server: {SIGNALING_SERVER}")
                print(f"Use this Session ID in the browser to connect!")
                print(f"Or browse to {SIGNALING_SERVER} to see available sessions")
                print(f"{'='*60}\n")
                self._session_info_printed = True
            
            # Set remote description in GLib thread
            GLib.idle_add(self.set_remote_description, answer_sdp)
        except Exception as e:
            logger.error(f"Error sending offer: {e}")
    
    def set_remote_description(self, answer_sdp):
        """Set remote description from Cloudflare answer (must run in GLib main loop)"""
        ret, sdp = GstSdp.SDPMessage.new_from_text(answer_sdp)
        answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdp)
        
        promise = Gst.Promise.new_with_change_func(self.on_set_remote_description, None, None)
        self.webrtc.emit('set-remote-description', answer, promise)
        return False

    def on_set_remote_description(self, promise, *_):
        try:
            res = promise.wait()
            logger.info(f"Remote description set, promise result: {res}")
        except Exception as e:
            logger.warning(f"Remote description promise error: {e}")
        GLib.idle_add(self.start_webrtc_stats)

    def start_webrtc_stats(self):
        """Start periodic WebRTC stats polling"""
        if self.stats_poll_id is None:
            self.stats_poll_id = GLib.timeout_add_seconds(2, self.poll_webrtc_stats)
        return False

    def poll_webrtc_stats(self):
        """Poll webrtcbin stats and log bytesSent if available"""
        if not self.webrtc:
            return True

        logger.info("Polling WebRTC stats...")
        promise = Gst.Promise.new()
        try:
            # None => all stats
            self.webrtc.emit('get-stats', None, promise)
        except Exception as e:
            logger.debug(f"get-stats not available: {e}")
            return True

        def _wait_stats():
            self.on_webrtc_stats_sync(promise)

        threading.Thread(target=_wait_stats, daemon=True).start()
        return True

    def on_webrtc_stats_sync(self, promise):
        """Handle webrtcbin stats promise (blocking wait in background thread)"""
        try:
            promise.wait()
            reply = promise.get_reply()
            stats = reply.get_value('stats') if reply else None
            if not stats:
                logger.info("WebRTC stats empty")
                # Try pad-specific stats as a fallback
                try:
                    pad = self._get_webrtc_any_pad()
                    if pad:
                        p = Gst.Promise.new()
                        self.webrtc.emit('get-stats', pad, p)
                        p.wait()
                        r = p.get_reply()
                        stats = r.get_value('stats') if r else None
                except Exception:
                    stats = None

                if not stats:
                    return

            stats_str = stats.to_string()
            match = re.search(r'bytesSent=(\d+)', stats_str)
            if match:
                logger.info(f"WebRTC bytesSent: {match.group(1)}")
            else:
                logger.info(f"WebRTC stats (no bytesSent found): {stats_str}")
        except Exception as e:
            logger.debug(f"Stats parsing error: {e}")

    def _get_webrtc_any_pad(self):
        """Return any src/sink pad from webrtcbin for stats"""
        try:
            it = self.webrtc.iterate_src_pads()
            while True:
                ok, pad = it.next()
                if ok and pad:
                    return pad
                if not ok:
                    break
        except Exception:
            pass

        try:
            it = self.webrtc.iterate_sink_pads()
            while True:
                ok, pad = it.next()
                if ok and pad:
                    return pad
                if not ok:
                    break
        except Exception:
            pass
        return None
    
    def start_pipeline(self):
        """Start the GStreamer pipeline"""
        logger.info("Starting pipeline...")
        ret = self.pipe.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            logger.error("Failed to start pipeline")
            sys.exit(1)
        elif ret == Gst.StateChangeReturn.ASYNC:
            logger.info("Pipeline state change is ASYNC, waiting...")
        
        logger.info(f"Pipeline set_state returned: {ret}")
        
        # Monitor pipeline stats
        GLib.timeout_add_seconds(5, self.print_stats)

    def check_rtp_caps_ready(self):
        """Wait until rtph264pay has negotiated caps with a concrete payload"""
        if self.negotiation_started:
            return False

        self.rtp_caps_check_count += 1

        if self.rtp_caps_ready():
            logger.info("RTP caps negotiated (payload=96), triggering negotiation...")
            GLib.timeout_add(100, self.trigger_negotiation)
            return False

        if self.rtp_caps_check_count % 5 == 0:
            logger.info("Waiting for RTP caps negotiation...")

        return True

    def setup_fps_probe(self):
        """Attach buffer probes to measure H.264 FPS and RTP PPS"""
        parser = self.pipe.get_by_name('h264parse0')
        if not parser:
            logger.warning("h264parse element not found for FPS probe")
            return

        src_pad = parser.get_static_pad('src')
        if not src_pad:
            logger.warning("h264parse src pad not found for FPS probe")
            return

        src_pad.add_probe(Gst.PadProbeType.BUFFER, self.on_frame_buffer)

        pay = self.pipe.get_by_name('rtph264pay0')
        if pay:
            pay_src = pay.get_static_pad('src')
            if pay_src:
                pay_src.add_probe(Gst.PadProbeType.BUFFER, self.on_rtp_buffer)
        GLib.timeout_add_seconds(1, self.report_fps)

    def on_frame_buffer(self, pad, info):
        """Count H.264 frame buffers to estimate FPS (pre-RTP)"""
        if info.type & Gst.PadProbeType.BUFFER:
            self.fps_count += 1
        return Gst.PadProbeReturn.OK

    def on_rtp_buffer(self, pad, info):
        """Count RTP packets leaving rtph264pay"""
        if info.type & Gst.PadProbeType.BUFFER:
            self.rtp_pps_count += 1
        return Gst.PadProbeReturn.OK

    def report_fps(self):
        """Report measured FPS once per second"""
        now = time.monotonic()
        elapsed = now - self.fps_last_time
        if elapsed > 0:
            fps = self.fps_count / elapsed
            pps = self.rtp_pps_count / elapsed
            logger.info(f"Measured H264 FPS (pre-RTP): {fps:.1f} | RTP PPS: {pps:.1f}")
        self.fps_count = 0
        self.rtp_pps_count = 0
        self.fps_last_time = now
        return True

    def rtp_caps_ready(self):
        """Return True when rtph264pay has negotiated payload=96"""
        pay = self.pipe.get_by_name('rtph264pay0')
        if not pay:
            return False

        src_pad = pay.get_static_pad('src')
        caps = src_pad.get_current_caps() if src_pad else None
        if not caps:
            return False

        return "payload=(int)96" in caps.to_string()
    
    def trigger_negotiation(self):
        """Trigger WebRTC negotiation"""
        if self.negotiation_started:
            return False
        logger.info("Triggering negotiation...")
        self.on_negotiation_needed(self.webrtc)
        return False  # Don't repeat
    
    def print_stats(self):
        """Print pipeline statistics"""
        if self.pipe:
            # Get libcamerasrc element
            libcamera = self.pipe.get_by_name('libcamerasrc0')
            if libcamera:
                # Query for statistics
                query = Gst.Query.new_latency()
                if libcamera.query(query):
                    live, min_lat, max_lat = query.parse_latency()
                    logger.info(f"Latency: {min_lat/Gst.MSECOND:.1f}ms - {max_lat/Gst.MSECOND:.1f}ms")
            
            # Check WebRTC stats
            if self.webrtc:
                state = self.webrtc.get_property('ice-connection-state')
                logger.info(f"ICE connection state: {state}")
        
        return True  # Keep calling
    
    def run(self):
        """Main run loop"""
        # Schedule initialization in GLib idle callback
        GLib.idle_add(self.initialize)
        
        # Run GLib main loop
        logger.info("Starting GLib main loop...")
        self.main_loop = GLib.MainLoop()
        
        try:
            self.main_loop.run()
        except KeyboardInterrupt:
            logger.info("Stopping...")
        finally:
            if self.pipe:
                self.pipe.set_state(Gst.State.NULL)
            if self.car_controller:
                self.car_controller.stop()
            if self.pc_control:
                # Close control connection if exists
                try:
                    import asyncio
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(self.pc_control.close())
                except:
                    pass
    
    def initialize(self):
        """Initialize pipeline (called from GLib idle)"""
        try:
            # Initialize car controller
            self.car_controller = CarController()
            self.car_controller.init_uart()
            
            # Don't create Cloudflare session yet - wait until we're ready to send offer
            # This prevents session timeout

            # Create pipeline immediately
            GLib.idle_add(self.create_and_start_pipeline)
            
        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            self.main_loop.quit()
        
        return False  # Don't repeat idle callback
    
    def create_and_start_pipeline(self):
        """Create and start GStreamer pipeline (called after rpicam-vid delay)"""
        try:
            # Create pipeline
            self.create_pipeline()
            
            # Start pipeline
            self.start_pipeline()
            
            logger.info("Pipeline started successfully!")

            # Trigger negotiation only after caps are negotiated
            GLib.timeout_add(500, self.check_rtp_caps_ready)
            
            # Start polling for control session ID
            GLib.timeout_add_seconds(2, self.check_control_session)
            
        except Exception as e:
            logger.error(f"Pipeline creation failed: {e}")
            self.main_loop.quit()
        
        return False  # Don't repeat

    
    def check_control_session(self):
        """Poll signaling server for control session ID"""
        if self.control_session_id:
            return False  # Already got it, stop polling
        
        try:
            import requests
            url = f"{SIGNALING_SERVER}/api/control-session?id={self.session_id}"
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                data = response.json()
                control_session_id = data.get('controlSessionId')
                if control_session_id:
                    logger.info(f"Got control session ID: {control_session_id}")
                    self.control_session_id = control_session_id
                    # Setup control subscriber in separate thread
                    threading.Thread(target=self.setup_control_subscriber, daemon=True).start()
                    return False  # Stop polling
        except Exception as e:
            logger.debug(f"Polling for control session: {e}")
        
        return True  # Continue polling
    
    def setup_control_subscriber(self):
        """Setup control subscriber in asyncio loop"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Create task and keep loop running
            async def run_subscriber():
                self.pc_control = await run_control_subscriber(self.car_controller, self.control_session_id)
                if self.pc_control:
                    # Keep loop alive while connection is active
                    while True:
                        await asyncio.sleep(1)
            
            loop.run_until_complete(run_subscriber())
        except Exception as e:
            logger.error(f"Error setting up control subscriber: {e}", exc_info=True)

def main():
    if not CLOUDFLARE_APP_ID or not CLOUDFLARE_APP_SECRET:
        logger.error("Missing CF_REALTIME_APP_ID or CF_REALTIME_TOKEN environment variables")
        sys.exit(1)
    
    client = GStreamerWebRTC()
    client.run()

if __name__ == '__main__':
    main()
