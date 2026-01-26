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
    def _send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
    
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
                'timestamp': time.time()
            }
            
            self.send_response(200)
            self._send_cors_headers()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True}).encode())
            print(f"Publisher registered: {session_id}")
        
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
            self.wfile.write(json.dumps(active_sessions).encode())
        
        elif parsed_path.path == '/api/session':
            query = parse_qs(parsed_path.query)
            session_id = query.get('id', [None])[0]
            
            if session_id and session_id in sessions:
                self.send_response(200)
                self._send_cors_headers()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(sessions[session_id]).encode())
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
