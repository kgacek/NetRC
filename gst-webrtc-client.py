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
import asyncio
import aiohttp
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
        self.loop = None
        
    async def create_cloudflare_session(self):
        """Create new Cloudflare session"""
        url = f"{CLOUDFLARE_API_BASE}/apps/{CLOUDFLARE_APP_ID}/sessions/new"
        headers = {'Authorization': f'Bearer {CLOUDFLARE_APP_SECRET}'}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as response:
                if response.status != 201:
                    raise Exception(f"Failed to create session: {response.status}")
                data = await response.json()
                self.session_id = data['sessionId']
                logger.info(f"Session created: {self.session_id}")
                
        # Register with signaling server
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{SIGNALING_SERVER}/api/sessions",
                json={'sessionId': self.session_id}
            ) as response:
                if response.status == 200:
                    logger.info("Session registered with signaling server")
    
    def create_pipeline(self):
        """Create GStreamer pipeline with hardware H.264 encoding"""
        # Try different hardware encoders for Raspberry Pi
        # Priority: v4l2h264enc (best) > omxh264enc (deprecated but works) > x264enc (software fallback)
        
        pipeline_str = f"""
        libcamerasrc ! 
        video/x-raw,width={WIDTH},height={HEIGHT},framerate={FRAMERATE}/1,format=NV12 ! 
        v4l2h264enc extra-controls="controls,video_bitrate={BITRATE},repeat_sequence_header=1" ! 
        video/x-h264,profile=baseline,level=(string)4.0 ! 
        h264parse config-interval=-1 ! 
        rtph264pay config-interval=-1 pt=96 mtu=1200 ! 
        webrtcbin name=sendrecv bundle-policy=max-bundle stun-server=stun://stun.cloudflare.com:3478
        """
        
        logger.info("Creating GStreamer pipeline with hardware H.264 encoding")
        logger.info(f"Resolution: {WIDTH}x{HEIGHT} @ {FRAMERATE}fps, Bitrate: {BITRATE/1000000}Mbps")
        
        try:
            self.pipe = Gst.parse_launch(pipeline_str)
        except Exception as e:
            logger.error(f"Failed with v4l2h264enc: {e}")
            # Fallback to omxh264enc
            logger.info("Trying omxh264enc...")
            pipeline_str = pipeline_str.replace('v4l2h264enc', 'omxh264enc target-bitrate=' + str(BITRATE))
            try:
                self.pipe = Gst.parse_launch(pipeline_str)
            except Exception as e2:
                logger.error(f"Failed with omxh264enc: {e2}")
                # Final fallback to software encoding
                logger.warning("Falling back to software x264enc")
                pipeline_str = f"""
                libcamerasrc ! 
                video/x-raw,width={WIDTH},height={HEIGHT},framerate={FRAMERATE}/1 ! 
                videoconvert ! 
                x264enc bitrate={BITRATE//1000} speed-preset=ultrafast tune=zerolatency ! 
                video/x-h264,profile=baseline ! 
                h264parse ! 
                rtph264pay pt=96 ! 
                webrtcbin name=sendrecv bundle-policy=max-bundle stun-server=stun://stun.cloudflare.com:3478
                """
                self.pipe = Gst.parse_launch(pipeline_str)
        
        self.webrtc = self.pipe.get_by_name('sendrecv')
        
        # Connect signals
        self.webrtc.connect('on-negotiation-needed', self.on_negotiation_needed)
        self.webrtc.connect('on-ice-candidate', self.on_ice_candidate)
        self.webrtc.connect('on-ice-gathering-state-notify', self.on_ice_gathering_state)
        
        # Add data channel for stats
        self.webrtc.emit('create-data-channel', 'stats', None)
        
    def on_negotiation_needed(self, element):
        """Handle negotiation needed"""
        logger.info("Negotiation needed, creating offer...")
        promise = Gst.Promise.new_with_change_func(self.on_offer_created, element, None)
        element.emit('create-offer', None, promise)
    
    def on_offer_created(self, promise, element, _):
        """Handle offer created"""
        promise.wait()
        reply = promise.get_reply()
        offer = reply['offer']
        
        promise = Gst.Promise.new()
        element.emit('set-local-description', offer, promise)
        promise.interrupt()
        
        # Send offer to Cloudflare
        sdp = offer.sdp.as_text()
        asyncio.run_coroutine_threadsafe(
            self.send_offer_to_cloudflare(sdp),
            self.loop
        )
    
    async def send_offer_to_cloudflare(self, offer_sdp):
        """Send offer to Cloudflare Calls API"""
        logger.info("Sending offer to Cloudflare...")
        
        # Extract video mid
        video_mid = None
        for line in offer_sdp.split('\r\n'):
            if line.startswith('m=video'):
                # Find corresponding a=mid line
                lines = offer_sdp.split('\r\n')
                m_idx = lines.index(line)
                for i in range(m_idx, len(lines)):
                    if lines[i].startswith('a=mid:'):
                        video_mid = lines[i].split(':')[1]
                        break
                break
        
        if not video_mid:
            logger.error("Could not find video mid in SDP")
            return
        
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
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.error(f"Failed to send offer: {response.status} - {text}")
                    return
                
                data = await response.json()
                logger.info("Received answer from Cloudflare")
                
                # Set remote description
                answer_sdp = data['sessionDescription']['sdp']
                self.set_remote_description(answer_sdp)
    
    def set_remote_description(self, answer_sdp):
        """Set remote description from Cloudflare answer"""
        ret, sdp = GstSdp.SDPMessage.new_from_text(answer_sdp)
        answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdp)
        
        promise = Gst.Promise.new()
        self.webrtc.emit('set-remote-description', answer, promise)
        promise.interrupt()
        
        logger.info("Remote description set, streaming started!")
    
    def on_ice_candidate(self, element, mlineindex, candidate):
        """Handle ICE candidate - not needed with ice-lite server"""
        pass
    
    def on_ice_gathering_state(self, element, pspec):
        """Monitor ICE gathering state"""
        state = element.get_property('ice-gathering-state')
        logger.info(f"ICE gathering state: {state}")
    
    def start_pipeline(self):
        """Start the GStreamer pipeline"""
        logger.info("Starting pipeline...")
        ret = self.pipe.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            logger.error("Failed to start pipeline")
            sys.exit(1)
        
        # Monitor pipeline stats
        GLib.timeout_add_seconds(5, self.print_stats)
    
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
    
    async def run(self):
        """Main run loop"""
        self.loop = asyncio.get_event_loop()
        
        # Create Cloudflare session
        await self.create_cloudflare_session()
        
        # Create and start pipeline
        self.create_pipeline()
        self.start_pipeline()
        
        # Run GLib main loop
        logger.info("Streaming started! Press Ctrl+C to stop.")
        main_loop = GLib.MainLoop()
        
        try:
            main_loop.run()
        except KeyboardInterrupt:
            logger.info("Stopping...")
        finally:
            self.pipe.set_state(Gst.State.NULL)

def main():
    if not CLOUDFLARE_APP_ID or not CLOUDFLARE_APP_SECRET:
        logger.error("Missing CF_REALTIME_APP_ID or CF_REALTIME_TOKEN environment variables")
        sys.exit(1)
    
    client = GStreamerWebRTC()
    asyncio.run(client.run())

if __name__ == '__main__':
    main()
