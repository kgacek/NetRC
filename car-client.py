import asyncio
import json
import os
import cv2
import aiohttp
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.contrib.media import frame_from_ndarray

SIGNALING_URL = os.getenv("CF_REALTIME_WS", "wss://your-worker.example.workers.dev/realtime")
ROOM = os.getenv("CF_REALTIME_ROOM", "car-stream")
TOKEN = os.getenv("CF_REALTIME_TOKEN", "replace_me_token")
CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))

class PiCameraTrack(VideoStreamTrack):
    def __init__(self, camera_index=0):
        super().__init__()
        self.cap = cv2.VideoCapture(camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FPS, 20)

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        ok, frame = self.cap.read()
        if not ok:
            raise RuntimeError("Camera read failed")
        video_frame = frame_from_ndarray(frame, format="bgr24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame

async def publish():
    pc = RTCPeerConnection()
    pc.addTrack(PiCameraTrack(CAMERA_INDEX))

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(SIGNALING_URL, headers={"Authorization": f"Bearer {TOKEN}"}) as ws:
            await ws.send_str(json.dumps({"type": "join", "room": ROOM, "token": TOKEN}))

            @pc.on("icecandidate")
            async def on_icecandidate(candidate):
                if candidate is None:
                    return  # trickle off; only final offer is sent
                await ws.send_str(json.dumps({"type": "candidate", "room": ROOM, "candidate": candidate.to_dict()}))

            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            await ws.send_str(json.dumps({"type": "offer", "room": ROOM, "token": TOKEN, "sdp": pc.localDescription.sdp}))

            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                data = json.loads(msg.data)
                if data.get("type") == "answer":
                    await pc.setRemoteDescription(RTCSessionDescription(sdp=data["sdp"], type="answer"))
                    print("Answer applied; streaming…")
                elif data.get("type") == "candidate":
                    if data.get("candidate"):
                        await pc.addIceCandidate(data["candidate"])
                elif data.get("type") == "ping":
                    await ws.send_str(json.dumps({"type": "pong"}))

if __name__ == "__main__":
    try:
        asyncio.run(publish())
    except KeyboardInterrupt:
        pass
