#!/usr/bin/env python3
"""
Simple HTTP server for Fantasy Baseball Civil War frontend.
Serves static files (HTML, JSON, images) on port 5000.
Handles API endpoints for opt-in functionality.
"""
import http.server
import socketserver
import os
import json
from urllib.parse import urlparse

PORT = 5000
HOST = "127.0.0.1"

class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def send_response(self, code, message=None):
        super().send_response(code, message)
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        # Handle API endpoints
        parsed_path = urlparse(self.path)

        if parsed_path.path == '/api/opt-in':
            self.handle_opt_in()
        else:
            self.send_error(404, "Not Found")

    def handle_opt_in(self):
        """Handle SMS opt-in API requests"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode('utf-8'))

            username = data.get('username')
            timestamp = data.get('timestamp')
            opted_in_sms = data.get('optedInSms')

            if not username or opted_in_sms is None:
                self.send_error(400, "Missing required fields")
                return

            # Update user_config.json
            config_path = os.path.join(os.path.dirname(__file__), 'data', 'auth', 'user_config.json')

            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)

                if username in config.get('users', {}):
                    config['users'][username]['opted_in_sms'] = opted_in_sms

                    with open(config_path, 'w') as f:
                        json.dump(config, f, indent=2)

                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        'success': True,
                        'message': f'User {username} SMS opt-in status updated to {opted_in_sms}'
                    }).encode('utf-8'))
                else:
                    self.send_error(404, f"User {username} not found")

            except Exception as e:
                print(f"Error updating user config: {e}")
                self.send_error(500, f"Server error: {str(e)}")

        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON in request body")
        except Exception as e:
            print(f"Error handling opt-in request: {e}")
            self.send_error(500, f"Server error: {str(e)}")

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    socketserver.TCPServer.allow_reuse_address = True

    with socketserver.TCPServer((HOST, PORT), MyHTTPRequestHandler) as httpd:
        print(f"Server running at http://{HOST}:{PORT}/")
        print("Serving Fantasy Baseball Civil War...")
        print("Press Ctrl+C to stop the server.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
