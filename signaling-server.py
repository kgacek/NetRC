#!/usr/bin/env python3
"""
Minimal signaling server for WebRTC using Cloudflare Calls
Stores session information to coordinate between RPi and Browser
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import time
from urllib.parse import urlparse, parse_qs

# In-memory storage (use Redis/DB for production)
sessions = {}

class SignalingHandler(BaseHTTPRequestHandler):
    # Suppress logging of errors
    def log_error(self, format, *args):
        # Only log actual application errors, not connection errors
        if args and isinstance(args[0], int) and args[0] in [400, 404]:
            return  # Suppress 400/404 logs
        super().log_error(format, *args)
    
    def _send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
    
    def _safe_send(self, data):
        """Safely send data, catching BrokenPipeError"""
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            # Client disconnected before receiving response - this is normal
            pass
    
    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()
    
    def do_POST(self):
        if self.path == '/api/publish':
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            data = json.loads(body.decode('utf-8'))
            
            session_id = data.get('sessionId')
            sessions[session_id] = {
                'sessionId': session_id,
                'type': 'publisher',
                'timestamp': time.time(),
                'controlSessionId': None  # Will be set when browser connects
            }
            
            self.send_response(200)
            self._send_cors_headers()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self._safe_send(json.dumps({'success': True}).encode())
            print(f"Publisher registered: {session_id}")
        
        elif self.path == '/api/control':
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            data = json.loads(body.decode('utf-8'))
            
            video_session_id = data.get('videoSessionId')
            control_session_id = data.get('controlSessionId')
            
            if video_session_id and video_session_id in sessions:
                sessions[video_session_id]['controlSessionId'] = control_session_id
                print(f"Control session linked: {video_session_id} -> {control_session_id}")
                
                self.send_response(200)
                self._send_cors_headers()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self._safe_send(json.dumps({'success': True}).encode())
            else:
                self.send_response(404)
                self._send_cors_headers()
                self.end_headers()
        
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_GET(self):
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == '/api/sessions':
            # Return all active publisher sessions
            active_sessions = [
                s for s in sessions.values()
                if s.get('type') == 'publisher' and 
                   time.time() - s.get('timestamp', 0) < 3600
            ]
            
            self.send_response(200)
            self._send_cors_headers()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self._safe_send(json.dumps(active_sessions).encode())
        
        elif parsed_path.path == '/api/session':
            query = parse_qs(parsed_path.query)
            session_id = query.get('id', [None])[0]
            
            if session_id and session_id in sessions:
                self.send_response(200)
                self._send_cors_headers()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self._safe_send(json.dumps(sessions[session_id]).encode())
            else:
                self.send_response(404)
                self._send_cors_headers()
                self.end_headers()
        
        elif parsed_path.path == '/api/control-session':
            # Get control session ID for a video session
            query = parse_qs(parsed_path.query)
            video_session_id = query.get('id', [None])[0]
            
            if video_session_id and video_session_id in sessions:
                control_session_id = sessions[video_session_id].get('controlSessionId')
                if control_session_id:
                    self.send_response(200)
                    self._send_cors_headers()
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self._safe_send(json.dumps({'controlSessionId': control_session_id}).encode())
                else:
                    self.send_response(404)
                    self._send_cors_headers()
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self._safe_send(json.dumps({'error': 'No control session'}).encode())
            else:
                self.send_response(404)
                self._send_cors_headers()
                self.end_headers()
        
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == '__main__':
    PORT = 8080
    server = HTTPServer(('0.0.0.0', PORT), SignalingHandler)
    print(f"Signaling server running on port {PORT}")
    print(f"Publisher endpoint: http://localhost:{PORT}/api/publish")
    print(f"Sessions list: http://localhost:{PORT}/api/sessions")
    server.serve_forever()
