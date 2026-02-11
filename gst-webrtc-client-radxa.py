#!/usr/bin/env python3
"""
Hardware-accelerated WebRTC streaming using GStreamer for Radxa Zero 3W
Camera -> Rockchip MPP H.264 -> WebRTC
"""
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstWebRTC', '1.0')
gi.require_version('GstSdp', '1.0')
gi.require_version('GstRtp', '1.0')
from gi.repository import Gst, GstWebRTC, GstSdp, GLib
import json
import os
import sys
import logging
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
            logger.info(f">>> Radxa subscribing to remote DataChannel with ID: {dc_id}")
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
        self.fps_count = 0
        self.fps_last_time = time.monotonic()
        self.negotiation_started = False
    
    def create_pipeline(self):
        """Create GStreamer pipeline using V4L2 with Rockchip MPP hardware encoder"""
        
        # Working pipeline for Radxa Zero 3W:
        # v4l2src (NV12) -> videoconvert -> I420 -> mpph264enc (hardware)
        # Note: Direct NV12->mpph264enc causes RGA errors, need I420 conversion
        
        # Build pipeline without linking to webrtcbin (will link manually after transceiver)
        pipeline_str = f"""
        v4l2src device=/dev/video0 name=src !
        video/x-raw,format=NV12,width={WIDTH},height={HEIGHT},framerate={FRAMERATE}/1 !
        videoconvert !
        video/x-raw,format=I420 !
        queue leaky=downstream max-size-time={QUEUE_MAX_TIME_NS} max-size-bytes=0 max-size-buffers={QUEUE_MAX_BUFFERS} !
        mpph264enc bps={BITRATE} bps-max={BITRATE} gop={FRAMERATE} rc-mode=cbr profile=baseline header-mode=each-idr !
        h264parse config-interval=1 !
        video/x-h264,stream-format=avc,alignment=au !
        rtph264pay name=pay pt=96 mtu=1200 config-interval=1 aggregate-mode=zero-latency
        """
        
        logger.info("Creating GStreamer pipeline (Radxa Zero 3W with Rockchip MPP)")
        self.pipe = Gst.parse_launch(pipeline_str)
        
        # Create webrtcbin separately
        self.webrtc = Gst.ElementFactory.make('webrtcbin', 'sendrecv')
        self.webrtc.set_property('bundle-policy', GstWebRTC.WebRTCBundlePolicy.MAX_BUNDLE)
        self.webrtc.set_property('stun-server', 'stun://stun.cloudflare.com:3478')
        self.pipe.add(self.webrtc)
        
        # Connect signals
        self.webrtc.connect('on-negotiation-needed', self.on_negotiation_needed)
        self.webrtc.connect('on-ice-candidate', self.on_ice_candidate)
        self.webrtc.connect('notify::ice-connection-state', self.on_ice_connection_state)
        self.webrtc.connect('notify::ice-gathering-state', self.on_ice_gathering_state)
        
        # Get rtph264pay element
        pay = self.pipe.get_by_name('pay')
        if not pay:
            raise RuntimeError("rtph264pay element not found")
        
        pay_src = pay.get_static_pad('src')
        if not pay_src:
            raise RuntimeError("rtph264pay src pad not found")
        
        # Request sink pad from webrtcbin using old API (GStreamer 1.18)
        webrtc_sink = self.webrtc.get_request_pad('sink_%u')
        if not webrtc_sink:
            raise RuntimeError("Could not request sink pad from webrtcbin")
        
        logger.info(f"Linking {pay_src.get_name()} to {webrtc_sink.get_name()}")
        ret = pay_src.link(webrtc_sink)
        if ret != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"Failed to link pads: {ret}")
        
        logger.info("Linked rtph264pay to webrtcbin")
        
        # Get transceiver that was auto-created
        self.transceiver = webrtc_sink.get_property('transceiver')
        logger.info(f"Auto-created transceiver: {self.transceiver}")
        
        # Setup FPS monitoring
        self.setup_fps_probe()
        
    def on_negotiation_needed(self, element):
        """Handle negotiation needed"""
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
        
        # Set local description
        set_promise = Gst.Promise.new()
        element.emit('set-local-description', offer, set_promise)
        
        # Send offer immediately (ice-lite mode)
        logger.info("Sending offer to Cloudflare (ice-lite mode)...")
        sdp = offer.sdp.as_text()
        threading.Thread(target=self.send_offer_to_cloudflare, args=(sdp,), daemon=True).start()
    
    def on_ice_candidate(self, element, mlineindex, candidate):
        """Handle ICE candidate - not needed with ice-lite server"""
        logger.debug(f"ICE candidate: {candidate}")
    
    def on_ice_gathering_state(self, element, pspec):
        """Monitor ICE gathering state"""
        state = element.get_property('ice-gathering-state')
        logger.info(f"ICE gathering state: {state}")
    
    def on_ice_connection_state(self, element, pspec):
        """Monitor ICE connection state"""
        state = element.get_property('ice-connection-state')
        logger.info(f"ICE connection state: {state}")
    
    def send_offer_to_cloudflare(self, offer_sdp):
        """Send offer to Cloudflare Calls API"""
        
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
        
        # Extract video mid
        video_mid = "0"
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
            
            # Print session info
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
        
        logger.info(f"Pipeline started: {ret}")
        
        # Monitor pipeline stats
        GLib.timeout_add_seconds(5, self.print_stats)
        
        # Trigger negotiation after pipeline is running
        GLib.timeout_add(2000, self.trigger_negotiation)
    
    def trigger_negotiation(self):
        """Trigger WebRTC negotiation"""
        if self.negotiation_started:
            return False
        logger.info("Triggering negotiation...")
        self.on_negotiation_needed(self.webrtc)
        return False
    
    def setup_fps_probe(self):
        """Attach a buffer probe to measure real FPS"""
        pay = self.pipe.get_by_name('rtph264pay0')
        if not pay:
            logger.warning("rtph264pay not found for FPS probe")
            return
        
        src_pad = pay.get_static_pad('src')
        if not src_pad:
            logger.warning("rtph264pay src pad not found")
            return
        
        src_pad.add_probe(Gst.PadProbeType.BUFFER, self.on_frame_buffer)
        GLib.timeout_add_seconds(1, self.report_fps)
    
    def on_frame_buffer(self, pad, info):
        """Count RTP packets"""
        if info.type & Gst.PadProbeType.BUFFER:
            self.fps_count += 1
        return Gst.PadProbeReturn.OK
    
    def report_fps(self):
        """Report measured FPS"""
        now = time.monotonic()
        elapsed = now - self.fps_last_time
        if elapsed > 0:
            fps = self.fps_count / elapsed
            logger.info(f"RTP packets/sec: {fps:.1f}")
        self.fps_count = 0
        self.fps_last_time = now
        return True
    
    def print_stats(self):
        """Print pipeline statistics"""
        if self.webrtc:
            state = self.webrtc.get_property('ice-connection-state')
            logger.info(f"ICE connection state: {state}")
        return True
    
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
                try:
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(self.pc_control.close())
                except:
                    pass
    
    def initialize(self):
        """Initialize pipeline"""
        try:
            # Initialize car controller
            self.car_controller = CarController()
            self.car_controller.init_uart()
            
            # Create and start pipeline
            self.create_pipeline()
            self.start_pipeline()
            
            # Start polling for control session ID
            GLib.timeout_add_seconds(2, self.check_control_session)
            
        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            self.main_loop.quit()
        
        return False
    
    def check_control_session(self):
        """Poll signaling server for control session ID"""
        if self.control_session_id:
            return False
        
        try:
            url = f"{SIGNALING_SERVER}/api/control-session?id={self.session_id}"
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                data = response.json()
                control_session_id = data.get('controlSessionId')
                if control_session_id:
                    logger.info(f"Got control session ID: {control_session_id}")
                    self.control_session_id = control_session_id
                    threading.Thread(target=self.setup_control_subscriber, daemon=True).start()
                    return False
        except Exception as e:
            logger.debug(f"Polling for control session: {e}")
        
        return True
    
    def setup_control_subscriber(self):
        """Setup control subscriber in asyncio loop"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def run_subscriber():
                self.pc_control = await run_control_subscriber(self.car_controller, self.control_session_id)
                if self.pc_control:
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
