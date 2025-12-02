#!/usr/bin/env python3
"""
Simple HTTP server for Fantasy Baseball Civil War frontend.
Serves static files (HTML, JSON, images) on port 5000.
"""
import http.server
import socketserver
import os

PORT = 5000
HOST = "0.0.0.0"

class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    with socketserver.TCPServer((HOST, PORT), MyHTTPRequestHandler) as httpd:
        httpd.allow_reuse_address = True
        print(f"Server running at http://{HOST}:{PORT}/")
        print("Serving Fantasy Baseball Civil War...")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
