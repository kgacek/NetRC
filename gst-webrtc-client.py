#!/usr/bin/env python3
"""
Hardware-accelerated WebRTC streaming using GStreamer
Camera -> Hardware H.264 -> WebRTC (no re-encoding)
"""
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstWebRTC', '1.0')
gi.require_version('GstSdp', '1.0')
from gi.repository import Gst, GstWebRTC, GstSdp, GLib
import json
import os
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cloudflare configuration
CLOUDFLARE_APP_ID = os.getenv('CF_REALTIME_APP_ID')
CLOUDFLARE_APP_SECRET = os.getenv('CF_REALTIME_TOKEN')
CLOUDFLARE_API_BASE = 'https://rtc.live.cloudflare.com/v1'
SIGNALING_SERVER = os.getenv('SIGNALING_SERVER', 'https://79-76-127-159.nip.io')

# Video configuration
WIDTH = 1920
HEIGHT = 1080
FRAMERATE = 30
BITRATE = 2000000  # 2 Mbps for 1080p

class GStreamerWebRTC:
    def __init__(self):
        Gst.init(None)
        self.pipe = None
        self.webrtc = None
        self.session_id = None
        
    def create_cloudflare_session(self):
        """Create new Cloudflare session"""
        import requests
        
        url = f"{CLOUDFLARE_API_BASE}/apps/{CLOUDFLARE_APP_ID}/sessions/new"
        headers = {'Authorization': f'Bearer {CLOUDFLARE_APP_SECRET}'}
        
        response = requests.post(url, headers=headers, timeout=10)
        if response.status_code != 201:
            raise Exception(f"Failed to create session: {response.status_code}")
        
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
    
    def create_pipeline(self):
        """Create GStreamer pipeline reading from rpicam-vid hardware encoder via FIFO"""
        # GStreamer pipeline reads from FIFO (rpicam-vid already running)
        pipeline_str = f"""
        filesrc location={self.fifo_path} ! 
        h264parse config-interval=-1 ! 
        video/x-h264,stream-format=byte-stream,alignment=au,profile=baseline ! 
        rtph264pay config-interval=-1 pt=96 mtu=1200 aggregate-mode=zero-latency ! 
        webrtcbin name=sendrecv bundle-policy=max-bundle stun-server=stun://stun.cloudflare.com:3478
        """
        
        logger.info("Creating GStreamer pipeline (reading from rpicam-vid FIFO)")
        
        self.pipe = Gst.parse_launch(pipeline_str)
        
        self.webrtc = self.pipe.get_by_name('sendrecv')
        
        # Connect signals
        self.webrtc.connect('on-negotiation-needed', self.on_negotiation_needed)
        self.webrtc.connect('on-ice-candidate', self.on_ice_candidate)
        self.webrtc.connect('notify::ice-gathering-state', self.on_ice_gathering_state)
        
        # Track ICE gathering state
        self.pending_offer_sdp = None
        
    def on_negotiation_needed(self, element):
        """Handle negotiation needed"""
        # Debug: check pipeline pads
        filesrc = self.pipe.get_by_name('filesrc0')
        if filesrc:
            src_pad = filesrc.get_static_pad('src')
            logger.info(f"filesrc src pad: {src_pad}, is-linked: {src_pad.is_linked() if src_pad else 'N/A'}")
        
        # Check webrtcbin sink pads
        iterator = element.iterate_sink_pads()
        pads = []
        while True:
            result, pad = iterator.next()
            if result != Gst.IteratorResult.OK:
                break
            pads.append(pad.get_name())
        logger.info(f"webrtcbin sink pads: {pads}")
        
        # Debug: check transceivers
        n_transceivers = element.emit('get-transceivers')
        logger.info(f"Number of transceivers: {len(n_transceivers) if n_transceivers else 0}")
        
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
    
    def on_ice_gathering_state(self, element, pspec):
        """Monitor ICE gathering state"""
        state = element.get_property('ice-gathering-state')
        logger.info(f"ICE gathering state: {state}")
    
    def send_offer_to_cloudflare(self, offer_sdp):
        """Send offer to Cloudflare Calls API (synchronous)"""
        import requests
        
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
    
    def trigger_negotiation(self):
        """Trigger WebRTC negotiation"""
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
            if hasattr(self, 'rpicam_process'):
                self.rpicam_process.terminate()
                self.rpicam_process.wait()
            if hasattr(self, 'fifo_path'):
                import os
                if os.path.exists(self.fifo_path):
                    os.remove(self.fifo_path)
    
    def initialize(self):
        """Initialize pipeline (called from GLib idle)"""
        try:
            # Create Cloudflare session
            self.create_cloudflare_session()
            
            # Start rpicam-vid process (returns immediately)
            self.start_rpicam()
            
            # Schedule pipeline creation after rpicam-vid initializes
            logger.info("Scheduling pipeline creation in 3 seconds...")
            GLib.timeout_add(3000, self.create_and_start_pipeline)
            
        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            self.main_loop.quit()
        
        return False  # Don't repeat idle callback
    
    def start_rpicam(self):
        """Start rpicam-vid process"""
        import subprocess
        
        # Create FIFO if it doesn't exist
        fifo_path = '/tmp/h264_fifo'
        if os.path.exists(fifo_path):
            os.remove(fifo_path)
        os.mkfifo(fifo_path)
        
        # Start rpicam-vid with hardware encoding in background
        self.rpicam_process = subprocess.Popen([
            'rpicam-vid',
            '--width', str(WIDTH),
            '--height', str(HEIGHT),
            '--framerate', str(FRAMERATE),
            '--codec', 'h264',
            '--profile', 'baseline',
            '--level', '4',
            '--bitrate', str(BITRATE),
            '--inline',              # SPS/PPS in every keyframe
            '--flush',               # Low latency
            '--timeout', '0',        # Run indefinitely
            '--nopreview',           # No preview
            '--denoise', 'cdn_off',  # Disable denoise for lower latency
            '-o', fifo_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        self.fifo_path = fifo_path
        logger.info(f"Started rpicam-vid: {WIDTH}x{HEIGHT} @ {FRAMERATE}fps, {BITRATE/1000000}Mbps")
    
    def create_and_start_pipeline(self):
        """Create and start GStreamer pipeline (called after rpicam-vid delay)"""
        try:
            # Create pipeline
            self.create_pipeline()
            
            # Start pipeline
            self.start_pipeline()
            
            logger.info("Pipeline started successfully!")
            
            # Schedule negotiation after pipeline has received data
            logger.info("Scheduling negotiation in 5 seconds...")
            GLib.timeout_add(5000, self.trigger_negotiation)
            
        except Exception as e:
            logger.error(f"Pipeline creation failed: {e}")
            self.main_loop.quit()
        
        return False  # Don't repeat

def main():
    if not CLOUDFLARE_APP_ID or not CLOUDFLARE_APP_SECRET:
        logger.error("Missing CF_REALTIME_APP_ID or CF_REALTIME_TOKEN environment variables")
        sys.exit(1)
    
    client = GStreamerWebRTC()
    client.run()

if __name__ == '__main__':
    main()
