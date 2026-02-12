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

# UART configuration for car control
UART_DEV = os.getenv('UART_DEV', '/dev/ttyS0')
UART_BAUD = int(os.getenv('UART_BAUD', '115200'))

# Video configuration
WIDTH = 1280
HEIGHT = 720
FRAMERATE = 25
BITRATE = 2500000  # 2.5 Mbps for 720p

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
        self.pipe = None
        self.webrtc = None
        self.session_id = None
        self.car_controller = None
        self.control_session_id = None
        self.pc_control = None
        self.fifo_path = '/tmp/h264_fifo'
        self.rpicam_process = None
        self.rpicam_restart_count = 0
        self.fps_count = 0
        self.fps_last_time = time.monotonic()
        self.appsrc = None
        self.reader_thread = None
        self.reader_stop = threading.Event()
        self.drop_until_idr = False
        self.appsrc_max_bytes = APPsrc_HIGH_WATERMARK
        self.drop_high_watermark = APPsrc_HIGH_WATERMARK
        self.drop_low_watermark = APPsrc_LOW_WATERMARK
        self.cached_sps = None
        self.cached_pps = None
        self.sps_pps_needed = False
        self.drop_count = 0
    
    def create_pipeline(self):
        """Create GStreamer pipeline reading from rpicam-vid hardware encoder via FIFO"""
        # GStreamer pipeline reads from FIFO (rpicam-vid already running)
        # otwierasz FIFO do czytania w trybie binarnym (blokujące)
        pipeline_str = f"""
        appsrc name=src is-live=true do-timestamp=true format=time block=false
            caps=video/x-h264,stream-format=byte-stream,alignment=nal !
        queue leaky=downstream max-size-time={QUEUE_MAX_TIME_NS} max-size-bytes=0 max-size-buffers={QUEUE_MAX_BUFFERS} !
        h264parse !
        video/x-h264,stream-format=avc,alignment=au,profile=baseline !
        rtph264pay pt=96 mtu=1200 config-interval=1 aggregate-mode=zero-latency !
        application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000 !
        webrtcbin name=sendrecv bundle-policy=max-bundle stun-server=stun://stun.cloudflare.com:3478
        """


        
        logger.info("Creating GStreamer pipeline (reading from rpicam-vid FIFO)")
        
        self.pipe = Gst.parse_launch(pipeline_str)
        
        self.webrtc = self.pipe.get_by_name('sendrecv')
        self.appsrc = self.pipe.get_by_name('src')
        if self.appsrc:
            self.appsrc.set_property('max-bytes', self.appsrc_max_bytes)
            self.appsrc.set_property('min-latency', 0)
            self.appsrc.set_property('max-latency', 0)
        
        # Connect signals
        self.webrtc.connect('on-negotiation-needed', self.on_negotiation_needed)
        self.webrtc.connect('on-ice-candidate', self.on_ice_candidate)
        self.webrtc.connect('notify::ice-connection-state', self.on_ice_connection_state)
        self.webrtc.connect('notify::ice-gathering-state', self.on_ice_gathering_state)
        self.webrtc.connect('pad-added', self.on_webrtc_pad_added)
        
        # Add video transceiver explicitly (fixes missing media section in SDP)
        caps = Gst.Caps.from_string("application/x-rtp,media=video,encoding-name=H264,payload=96")
        self.transceiver = self.webrtc.emit('add-transceiver', GstWebRTC.WebRTCRTPTransceiverDirection.SENDONLY, caps)
        logger.info(f"Added video transceiver: {self.transceiver}")
        
        # Monitor transceiver for when sender is ready
        if self.transceiver:
            self.transceiver.connect('notify::sender', self.on_transceiver_sender_ready)
        
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
        
        # With Cloudflare ice-lite, send offer immediately without waiting for ICE gathering
        # Server will provide ICE candidates in the answer
        logger.info("Sending offer to Cloudflare (ice-lite mode)...")
        sdp = offer.sdp.as_text()
        import threading
        threading.Thread(target=self.send_offer_to_cloudflare, args=(sdp,), daemon=True).start()
    
    def on_ice_candidate(self, element, mlineindex, candidate):
        """Handle ICE candidate - not needed with ice-lite server"""
        logger.debug(f"ICE candidate: {candidate}")
    
    def on_webrtc_pad_added(self, element, pad):
        """Called when pad is added to webrtcbin - trigger negotiation"""
        logger.info(f"WebRTC pad added: {pad.get_name()}, caps: {pad.get_current_caps()}")
        
        # Trigger negotiation once when first pad is added (means rtph264pay connected)
        if not self.negotiation_started:
            logger.info("RTP pad connected, triggering negotiation in 1 second...")
            GLib.timeout_add(1000, self.trigger_negotiation)
    
    def on_transceiver_sender_ready(self, transceiver, pspec):
        """Called when transceiver sender is ready"""
        sender = transceiver.get_property('sender')
        if sender and not self.negotiation_started:
            logger.info(f"Transceiver sender ready, triggering negotiation...")
            GLib.timeout_add(500, self.trigger_negotiation)
    
    def on_ice_gathering_state(self, element, pspec):
        """Monitor ICE gathering state"""
        state = element.get_property('ice-gathering-state')
        logger.info(f"ICE gathering state: {state}")
    
    def on_ice_connection_state(self, element, pspec):
        """Monitor ICE connection state"""
        state = element.get_property('ice-connection-state')
        logger.info(f"ICE connection state: {state}")
    
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
            if response.status_code != 200:
                logger.error(f"Failed to send offer: {response.status_code} - {response.text}")
                return
            
            data = response.json()
            logger.info("Received answer from Cloudflare")
            
            # Print session info on first successful connection
            if not hasattr(self, '_session_info_printed'):
                print(f"\n{'='*60}")
                print(f"SESSION ID: {self.session_id}")
                print(f"Signaling Server: {SIGNALING_SERVER}")
                print(f"Use this Session ID in the browser to connect!")
                print(f"Or browse to {SIGNALING_SERVER} to see available sessions")
                print(f"{'='*60}\n")
                self._session_info_printed = True
            
            # Set remote description
            answer_sdp = data['sessionDescription']['sdp']
            self.set_remote_description(answer_sdp)
        except Exception as e:
            logger.error(f"Error sending offer: {e}")
    
    def set_remote_description(self, answer_sdp):
        """Set remote description from Cloudflare answer"""
        ret, sdp = GstSdp.SDPMessage.new_from_text(answer_sdp)
        answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdp)
        
        promise = Gst.Promise.new()
        self.webrtc.emit('set-remote-description', answer, promise)
        promise.interrupt()
        
        logger.info("Remote description set, streaming started!")
    
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

    def ensure_fifo(self):
        """Ensure FIFO exists without removing it while in use"""
        if os.path.exists(self.fifo_path):
            if not stat.S_ISFIFO(os.stat(self.fifo_path).st_mode):
                raise RuntimeError(f"{self.fifo_path} exists and is not a FIFO")
            return
        os.mkfifo(self.fifo_path)
        logger.info(f"Created FIFO at {self.fifo_path}")

    def check_rtp_caps_ready(self):
        """Wait until rtph264pay has negotiated caps with a concrete payload"""
        if self.negotiation_started:
            return False

        self.rtp_caps_check_count += 1

        # If rpicam died, try to restart it (without touching FIFO)
        if self.rpicam_process and self.rpicam_process.poll() is not None:
            self.rpicam_restart_count += 1
            logger.warning(f"rpicam-vid exited, restarting (attempt {self.rpicam_restart_count})")
            self.start_rpicam()

        if self.rtp_caps_ready():
            logger.info("RTP caps negotiated (payload=96), triggering negotiation...")
            GLib.timeout_add(100, self.trigger_negotiation)
            return False

        if self.rtp_caps_check_count % 5 == 0:
            logger.info("Waiting for RTP caps negotiation...")

        return True

    def setup_fps_probe(self):
        """Attach a buffer probe to measure real FPS"""
        parser = self.pipe.get_by_name('h264parse0')
        if not parser:
            logger.warning("h264parse element not found for FPS probe")
            return

        src_pad = parser.get_static_pad('src')
        if not src_pad:
            logger.warning("h264parse src pad not found for FPS probe")
            return

        src_pad.add_probe(Gst.PadProbeType.BUFFER, self.on_frame_buffer)
        GLib.timeout_add_seconds(1, self.report_fps)

    def on_frame_buffer(self, pad, info):
        """Count H.264 frame buffers to estimate FPS"""
        if info.type & Gst.PadProbeType.BUFFER:
            self.fps_count += 1
        return Gst.PadProbeReturn.OK

    def report_fps(self):
        """Report measured FPS once per second"""
        now = time.monotonic()
        elapsed = now - self.fps_last_time
        if elapsed > 0:
            fps = self.fps_count / elapsed
            logger.info(f"Measured RTP FPS: {fps:.1f}")
        self.fps_count = 0
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
            if self.reader_stop:
                self.reader_stop.set()
            if self.reader_thread and self.reader_thread.is_alive():
                self.reader_thread.join(timeout=2)
            if hasattr(self, 'rpicam_process'):
                self.rpicam_process.terminate()
                self.rpicam_process.wait()
            if hasattr(self, 'fifo_path'):
                import os
                if os.path.exists(self.fifo_path):
                    os.remove(self.fifo_path)
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
            
            # Ensure FIFO exists before starting rpicam and pipeline
            self.ensure_fifo()

            # Start rpicam-vid process (returns immediately)
            self.start_rpicam()
            
            # Schedule pipeline creation after rpicam-vid initializes
            logger.info("Scheduling pipeline creation in 2 seconds...")
            GLib.timeout_add(2000, self.create_and_start_pipeline)
            
        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            self.main_loop.quit()
        
        return False  # Don't repeat idle callback
    
    def start_rpicam(self):
        """Start rpicam-vid process"""
        import subprocess

        if self.rpicam_process and self.rpicam_process.poll() is None:
            return

        # FIFO should already exist; don't remove it here
        self.ensure_fifo()

        stderr_log = open('/tmp/rpicam-vid.log', 'ab')
        
        # Start rpicam-vid with hardware encoding in background
        self.rpicam_process = subprocess.Popen([
            'gst-launch-1.0', '-e',
            'v4l2src', 'device=/dev/video0', '!',
            f'video/x-raw,format=NV12,width={WIDTH},height={HEIGHT},framerate={FRAMERATE}/1', '!',
            'videoconvert', '!',
            'video/x-raw,format=I420', '!',
            'mpph264enc', f'bps={BITRATE}', f'bps-max={BITRATE}', f'gop={FRAMERATE}', 
            'rc-mode=cbr', 'profile=baseline', 'header-mode=each-idr', '!',
            'h264parse', '!',
            'video/x-h264,stream-format=byte-stream,alignment=nal', '!',
            'filesink', f'location={self.fifo_path}'
        ], stdout=subprocess.DEVNULL, stderr=stderr_log)
        logger.info(f"Started v4l2src+mpph264enc: {WIDTH}x{HEIGHT} @ {FRAMERATE}fps, {BITRATE/1000000}Mbps")
    
    def create_and_start_pipeline(self):
        """Create and start GStreamer pipeline (called after rpicam-vid delay)"""
        try:
            # Create pipeline
            self.create_pipeline()
            
            # Start pipeline
            self.start_pipeline()
            
            logger.info("Pipeline started successfully!")

            # Start FIFO reader feeding appsrc
            self.start_fifo_reader()

            # Trigger negotiation only after caps are negotiated
            GLib.timeout_add(500, self.check_rtp_caps_ready)
            
            # Start polling for control session ID
            GLib.timeout_add_seconds(2, self.check_control_session)
            
        except Exception as e:
            logger.error(f"Pipeline creation failed: {e}")
            self.main_loop.quit()
        
        return False  # Don't repeat

    def start_fifo_reader(self):
        """Start background thread that reads FIFO and pushes to appsrc"""
        if not self.appsrc:
            logger.error("appsrc not available; cannot start FIFO reader")
            return
        if self.reader_thread and self.reader_thread.is_alive():
            return

        self.reader_stop.clear()
        self.reader_thread = threading.Thread(target=self._fifo_reader_loop, daemon=True)
        self.reader_thread.start()
        logger.info("Started FIFO reader thread")

    def _fifo_reader_loop(self):
        """Read H.264 byte-stream from FIFO, split by start codes, push to appsrc"""
        buffer = bytearray()

        while not self.reader_stop.is_set():
            try:
                with open(self.fifo_path, 'rb', buffering=0) as fifo:
                    while not self.reader_stop.is_set():
                        chunk = fifo.read(4096)
                        if not chunk:
                            time.sleep(0.005)
                            continue
                        buffer.extend(chunk)
                        self._drain_nals(buffer)
            except Exception as e:
                logger.warning(f"FIFO reader error: {e}")
                time.sleep(0.1)

    def _find_start_code(self, data, offset):
        """Return (index, length) of next H.264 start code or (-1, 0)"""
        i3 = data.find(b'\x00\x00\x01', offset)
        i4 = data.find(b'\x00\x00\x00\x01', offset)
        if i3 == -1 and i4 == -1:
            return -1, 0
        if i3 == -1:
            return i4, 4
        if i4 == -1:
            return i3, 3
        return (i3, 3) if i3 < i4 else (i4, 4)

    def _drain_nals(self, buffer):
        """Extract NAL units from buffer and push to appsrc"""
        while True:
            start, sc_len = self._find_start_code(buffer, 0)
            if start == -1:
                # keep last 3 bytes to detect a start code split across reads
                if len(buffer) > 3:
                    del buffer[:-3]
                return
            if start > 0:
                del buffer[:start]

            next_start, _ = self._find_start_code(buffer, sc_len)
            if next_start == -1:
                return

            nal = bytes(buffer[:next_start])
            del buffer[:next_start]

            self._push_nal(nal, sc_len)

    def _push_nal(self, nal, sc_len):
        """Push a single NAL unit to appsrc with simple drop strategy"""
        if not self.appsrc or len(nal) <= sc_len:
            return

        nal_type = nal[sc_len] & 0x1F

        if nal_type == 7:
            self.cached_sps = nal
        elif nal_type == 8:
            self.cached_pps = nal

        # Drop strategy when appsrc is backlogged: skip non-IDR slices until next IDR
        level_bytes = self.appsrc.get_property('current-level-bytes')
        if level_bytes > self.drop_high_watermark:
            self.drop_until_idr = True
            self.sps_pps_needed = True

        if self.drop_until_idr:
            if nal_type not in (5, 7, 8):
                self.drop_count += 1
                return
            if nal_type == 5:
                if self.sps_pps_needed:
                    self._push_cached_parameter_sets()
                self.drop_until_idr = False
                self.sps_pps_needed = False

        # If backlog is still above low watermark, drop non-IDR slices aggressively
        if level_bytes > self.drop_low_watermark and nal_type in (1, 2, 3, 4):
            self.drop_count += 1
            return

        buf = Gst.Buffer.new_allocate(None, len(nal), None)
        buf.fill(0, nal)
        ret = self.appsrc.emit('push-buffer', buf)
        if ret != Gst.FlowReturn.OK:
            logger.debug(f"appsrc push-buffer returned {ret}")

    def _push_cached_parameter_sets(self):
        """Push cached SPS/PPS before IDR if available"""
        if self.cached_sps:
            buf = Gst.Buffer.new_allocate(None, len(self.cached_sps), None)
            buf.fill(0, self.cached_sps)
            self.appsrc.emit('push-buffer', buf)
        if self.cached_pps:
            buf = Gst.Buffer.new_allocate(None, len(self.cached_pps), None)
            buf.fill(0, self.cached_pps)
            self.appsrc.emit('push-buffer', buf)
    
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
