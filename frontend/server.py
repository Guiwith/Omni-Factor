from http.server import HTTPServer, SimpleHTTPRequestHandler
import socketserver

class CustomHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        SimpleHTTPRequestHandler.end_headers(self)

if __name__ == '__main__':
    with socketserver.TCPServer(("", 8080), CustomHandler) as httpd:
        print("服务器运行在 http://localhost:8080")
        httpd.serve_forever()