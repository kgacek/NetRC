import asyncio
import os
import sys
import logging
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack, RTCConfiguration, RTCIceServer
from aiortc.contrib.media import MediaPlayer
from av import VideoFrame
import aiohttp
import json
from fractions import Fraction
import time
import serial
import serial.tools.list_ports

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cloudflare configuration
CLOUDFLARE_APP_ID = os.getenv('CF_REALTIME_APP_ID', 'your-app-id')
CLOUDFLARE_APP_SECRET = os.getenv('CF_REALTIME_TOKEN', 'your-app-secret')
CLOUDFLARE_API_BASE = 'https://rtc.live.cloudflare.com/v1'

W=640
H=480

# Signaling server configuration
SIGNALING_SERVER = os.getenv('SIGNALING_SERVER', 'https://79-76-127-159.nip.io')

# UART configuration for car control
UART_DEV = os.getenv('UART_DEV', '/dev/ttyS0')
UART_BAUD = int(os.getenv('UART_BAUD', '115200'))

class V4L2CameraTrack(VideoStreamTrack):
    """
    Video track from V4L2 camera (Radxa Zero 3W with IMX219)
    """
    def __init__(self):
        super().__init__()
        self.camera_dev = "/dev/video0"
        
        # Configure camera exposure/gain for optimal image quality
        self._configure_camera()
        
        # Initialize video capture
        try:
            import cv2
            self.cap = cv2.VideoCapture(self.camera_dev, cv2.CAP_V4L2)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YUYV'))
            
            # Test read
            ret, _ = self.cap.read()
            if not ret:
                raise Exception("Failed to read from camera")
            
            logger.info(f"V4L2 Camera initialized: {W}x{H} @ 30fps")
            self.use_camera = True
            
        except Exception as e:
            logger.warning(f"Camera not available: {e}, using test pattern")
            self.use_camera = False
            self.counter = 0
        
    def _configure_camera(self):
        """Configure V4L2 camera controls for optimal quality"""
        import subprocess
        try:
            # Optimal settings based on tests: exposure=3000, gain=6000, analogue_gain=1600
            subprocess.run([
                'v4l2-ctl', '-d', self.camera_dev,
                '--set-ctrl=exposure=3000',
                '--set-ctrl=gain=6000',
                '--set-ctrl=analogue_gain=1600'
            ], check=False, capture_output=True)
            logger.info("Camera configured: exposure=3000, gain=6000, analogue_gain=1600")
        except Exception as e:
            logger.warning(f"Could not configure camera: {e}")

    async def recv(self):
        """
        Generate video frames
        """
        pts, time_base = await self.next_timestamp()
        
        if self.use_camera:
            import cv2
            # Read frame from camera
            ret, frame_bgr = self.cap.read()
            
            if not ret:
                logger.error("Failed to read frame from camera")
                # Fallback to black frame
                import numpy as np
                frame_bgr = np.zeros((H, W, 3), dtype=np.uint8)
            
            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            frame = VideoFrame.from_ndarray(frame_rgb, format="rgb24")
            
            # FPS monitoring
            current_time = time.time()
            if not hasattr(self, 'last_log_time'):
                self.last_log_time = current_time
                self.frames_since_log = 0
            
            self.frames_since_log += 1
            time_elapsed = current_time - self.last_log_time
            
            if time_elapsed >= 5.0:
                actual_fps = self.frames_since_log / time_elapsed
                logger.info(f"Actual streaming FPS: {actual_fps:.2f}")
                self.last_log_time = current_time
                self.frames_since_log = 0
        else:
            # Test pattern fallback
            import numpy as np
            frame = VideoFrame.from_ndarray(
                np.full((H, W, 3), self.counter % 256, dtype=np.uint8),
                format="rgb24"
            )
            self.counter += 1
            
        frame.pts = pts
        frame.time_base = time_base
        
        return frame

    def stop(self):
        if self.use_camera and hasattr(self, 'cap'):
            self.cap.release()


def extract_mid_from_sdp(sdp, track_kind='video'):
    """
    Extract mid (media stream ID) from SDP for specific track kind
    """
    lines = sdp.split('\n')
    current_mid = None
    current_kind = None
    
    for line in lines:
        if line.startswith('a=mid:'):
            current_mid = line.split(':', 1)[1].strip()
        elif line.startswith('m='):
            # m=video or m=audio
            current_kind = line.split(' ', 1)[0][2:]
            if current_kind == track_kind and current_mid:
                return current_mid
    
    return current_mid


async def create_session():
    """
    Create a new session on Cloudflare Calls
    """
    url = f"{CLOUDFLARE_API_BASE}/apps/{CLOUDFLARE_APP_ID}/sessions/new"
    headers = {
        'Authorization': f'Bearer {CLOUDFLARE_APP_SECRET}',
        'Content-Type': 'application/json'
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers) as response:
            if response.status != 201:
                text = await response.text()
                raise Exception(f"Failed to create session: {response.status} - {text}")
            
            data = await response.json()
            return data['sessionId']


async def send_offer(session_id, offer_sdp):
    """
    Send WebRTC offer to Cloudflare Calls
    """
    url = f"{CLOUDFLARE_API_BASE}/apps/{CLOUDFLARE_APP_ID}/sessions/{session_id}/tracks/new"
    headers = {
        'Authorization': f'Bearer {CLOUDFLARE_APP_SECRET}',
        'Content-Type': 'application/json'
    }
    
    # Extract mid from SDP
    video_mid = extract_mid_from_sdp(offer_sdp, 'video')
    if not video_mid:
        raise Exception("Could not extract video mid from SDP")
    
    logger.info(f"Extracted video mid: {video_mid}")
    
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
    
    # Log full request for debugging
    logger.debug(f"Sending to URL: {url}")
    logger.debug(f"Payload: {json.dumps(payload, indent=2)}")
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as response:
            response_text = await response.text()
            logger.info(f"Response status: {response.status}")
            logger.info(f"Response body: {response_text}")
            
            if response.status not in [200, 201]:
                raise Exception(f"Failed to send offer: {response.status} - {response_text}")
            
            data = json.loads(response_text)
            
            # Check for track errors
            if 'tracks' in data:
                for track in data['tracks']:
                    if 'errorCode' in track:
                        logger.error(f"Track error: {track}")
                        raise Exception(f"Track error: {track.get('errorDescription', 'Unknown error')}")
            
            return data


async def register_session(session_id):
    """
    Register session in signaling server
    """
    url = f"{SIGNALING_SERVER}/api/publish"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={'sessionId': session_id}, timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status != 200:
                    logger.warning(f"Failed to register with signaling server: {response.status}")
                else:
                    logger.info("Session registered with signaling server")
    except Exception as e:
        logger.warning(f"Could not connect to signaling server: {e}")


class CarController:
    """
    Controls the RC car via UART based on commands from DataChannel
    """
    def __init__(self, uart_dev=UART_DEV, uart_baud=UART_BAUD):
        self.uart_dev = uart_dev
        self.uart_baud = uart_baud
        self.ser = None
        self.seq = 0
        self.command_queue = asyncio.Queue(maxsize=5)  # Drop old commands if queue full
        self.running = False
        
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
    
    async def _uart_sender_loop(self):
        """Background task that sends commands from queue without blocking"""
        self.running = True
        while self.running:
            try:
                throttle, steer = await asyncio.wait_for(
                    self.command_queue.get(), 
                    timeout=0.1
                )
                
                if not self.ser:
                    continue
                
                self.seq = (self.seq + 1) & 0xFFFF
                cmd = f"T,{int(throttle)},{int(steer)},0,{self.seq}\n"
                
                # Run blocking UART in executor to not block event loop
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._send_uart, cmd.encode('ascii'))
                
                if throttle != 0 or steer != 0:
                    logger.info(f"UART: T={throttle}, S={steer}")
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"UART sender error: {e}")
    
    def _send_uart(self, data):
        """Blocking UART send - runs in executor"""
        try:
            self.ser.write(data)
            self.ser.flush()
        except Exception as e:
            logger.error(f"UART write error: {e}")
    
    async def send_command(self, throttle, steer):
        """Queue command for sending (non-blocking)"""
        # Clamp values
        throttle = max(-300, min(300, throttle))
        steer = max(-1000, min(1000, steer))
        
        # Drop old command if queue full (keep only latest)
        if self.command_queue.full():
            try:
                self.command_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        
        try:
            self.command_queue.put_nowait((throttle, steer))
        except asyncio.QueueFull:
            pass  # Skip if still full
    
    def process_control_message(self, message):
        """Process control message from DataChannel"""
        try:
            data = json.loads(message)
            throttle = int(data.get('throttle', 0))
            steer = int(data.get('steer', 0))
            
            # Schedule async send without blocking
            asyncio.create_task(self.send_command(throttle, steer))
            
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in control message: {message}")
        except Exception as e:
            logger.error(f"Error processing control message: {e}")
    
    async def stop(self):
        """Stop the car and close UART"""
        self.running = False
        if self.ser:
            await self.send_command(0, 0)
            await asyncio.sleep(0.2)
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
        
        # Create our own session
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as response:
                if response.status != 201:
                    logger.error(f"Failed to create subscriber session: {await response.text()}")
                    return None
                data = await response.json()
                subscriber_session_id = data['sessionId']
                logger.info(f"Created subscriber session: {subscriber_session_id}")
        
        establish_url = f"{CLOUDFLARE_API_BASE}/apps/{CLOUDFLARE_APP_ID}/sessions/{subscriber_session_id}/datachannels/establish"
        establish_payload = {
            'dataChannel': {
                'location': 'remote',
                'dataChannelName': 'server-events'
            }
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(establish_url, headers=headers, json=establish_payload) as response:
                response_text = await response.text()
                
                if response.status in [200, 201]:
                    data = json.loads(response_text)
                    
                    if data.get('requiresImmediateRenegotiation'):
                        await pc_control.setRemoteDescription(RTCSessionDescription(
                            sdp=data['sessionDescription']['sdp'],
                            type=data['sessionDescription']['type']
                        ))
                        
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
                        
                        async with aiohttp.ClientSession() as renegotiate_session:
                            async with renegotiate_session.put(renegotiate_url, headers=headers, json=renegotiate_payload) as renegotiate_response:
                                if renegotiate_response.status not in [200, 201]:
                                    logger.error(f"Failed to send answer: {await renegotiate_response.text()}")
                                    return None
                    elif data.get('sessionDescription'):
                        await pc_control.setRemoteDescription(RTCSessionDescription(
                            sdp=data['sessionDescription']['sdp'],
                            type=data['sessionDescription']['type']
                        ))
                else:
                    logger.error(f"Failed to establish transport: {response_text}")
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
        
        async with aiohttp.ClientSession() as session:
            async with session.post(dc_new_url, headers=headers, json=dc_new_payload) as response:
                response_text = await response.text()
                
                if response.status in [200, 201]:
                    data = json.loads(response_text)
                    
                    # Create negotiated DataChannel with ID from API
                    dc_id = data['dataChannels'][0]['id']
                    logger.info(f"Creating negotiated DataChannel with ID: {dc_id}")
                    
                    # Create negotiated DataChannel - this will trigger ondatachannel when connected
                    control_dc = pc_control.createDataChannel('control-subscribed', negotiated=True, id=dc_id)
                    
                    @control_dc.on('open')
                    def on_open():
                        logger.info(f"Control DataChannel opened!")
                    
                    @control_dc.on('message')
                    def on_message(message):
                        # Don't log every message - only errors
                        if car_controller:
                            car_controller.process_control_message(message)
                    
                    @control_dc.on('close')
                    def on_close():
                        logger.info("Control DataChannel closed")
                        if car_controller:
                            car_controller.send_command(0, 0)
                    
                    @control_dc.on('error')
                    def on_error(error):
                        logger.error(f"Control DataChannel error: {error}")
                else:
                    logger.error(f"Failed to subscribe to DataChannel: {response_text}")
                    return None
        
        return pc_control
        
    except Exception as e:
        logger.error(f"Error in control subscriber: {e}", exc_info=True)
        return None

async def run_stream():
    """
    Main function to stream video from Pi Camera
    """
    car_controller = None
    pc_control = None
    uart_task = None
    
    try:
        # Initialize car controller
        car_controller = CarController()
        if car_controller.init_uart():
            # Start UART sender loop in background
            uart_task = asyncio.create_task(car_controller._uart_sender_loop())
        
        # Create session for video
        logger.info("Creating Cloudflare session for video...")
        session_id = await create_session()
        logger.info(f"Video session created: {session_id}")
        
        # Register with signaling server
        await register_session(session_id)
        
        print(f"\n{'='*60}")
        print(f"SESSION ID: {session_id}")
        print(f"Signaling Server: {SIGNALING_SERVER}")
        print(f"Use this Session ID in the browser to connect!")
        print(f"Or browse to {SIGNALING_SERVER} to see available sessions")
        print(f"{'='*60}\n")
        
        # Create peer connection with proper configuration
        pc = RTCPeerConnection(
            configuration=RTCConfiguration(
                iceServers=[RTCIceServer(urls=['stun:stun.cloudflare.com:3478'])]
            )
        )
        
        # Add video track
        logger.info("Initializing camera...")
        camera_track = V4L2CameraTrack()
        pc.addTrack(camera_track)
        
        # Create offer
        logger.info("Creating WebRTC offer...")
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        
        # Wait for ICE gathering
        logger.info("Gathering ICE candidates...")
        while pc.iceGatheringState != 'complete':
            await asyncio.sleep(0.1)
        
        # Send offer to Cloudflare
        logger.info("Sending offer to Cloudflare...")
        response_data = await send_offer(session_id, pc.localDescription.sdp)
        
        # Set remote description
        logger.info("Setting remote description...")
        
        if 'sessionDescription' in response_data:
            await pc.setRemoteDescription(RTCSessionDescription(
                sdp=response_data['sessionDescription']['sdp'],
                type=response_data['sessionDescription']['type']
            ))
        else:
            logger.warning("No sessionDescription in response, connection may not work properly")
        
        logger.info("Streaming started! Press Ctrl+C to stop.")
        logger.info(f"Track published with name: camera")
        
        logger.info("Waiting for browser control connection...")
        
        # Poll signaling server for control session
        control_session_id = None
        for attempt in range(60):  # Wait up to 60 seconds
            try:
                url = f"{SIGNALING_SERVER}/api/control-session?id={session_id}"
                async with aiohttp.ClientSession() as http_session:
                    async with http_session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as response:
                        if response.status == 200:
                            data = await response.json()
                            control_session_id = data.get('controlSessionId')
                            if control_session_id:
                                logger.info(f"Got control session ID: {control_session_id}")
                                break
            except Exception as e:
                pass
            
            await asyncio.sleep(1)
        
        if control_session_id and car_controller:
            logger.info("Setting up control subscriber...")
            pc_control = await run_control_subscriber(car_controller, control_session_id)
        else:
            logger.warning("No control session found - running video-only")
        
        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
                if pc.connectionState == 'failed' or pc.connectionState == 'closed':
                    logger.warning("Connection failed or closed")
                    break
        except KeyboardInterrupt:
            logger.info("Stopping stream...")
        
        # Cleanup
        camera_track.stop()
        await pc.close()
        
        if pc_control:
            await pc_control.close()
        
        if car_controller:
            await car_controller.stop()
            if uart_task:
                await uart_task
        
        logger.info("Stream stopped")
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        if car_controller:
            await car_controller.stop()
        sys.exit(1)


if __name__ == '__main__':
    # Check environment variables
    if CLOUDFLARE_APP_ID == 'your-app-id' or CLOUDFLARE_APP_SECRET == 'your-app-secret':
        print("ERROR: Please set CF_APP_ID and CF_APP_SECRET environment variables")
        print("Example:")
        print("  export CF_APP_ID=your-app-id")
        print("  export CF_APP_SECRET=your-app-secret")
        sys.exit(1)
    
    asyncio.run(run_stream())
