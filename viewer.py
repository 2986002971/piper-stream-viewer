#!/usr/bin/env python3
"""Loopback static Viewer and reloadable client configuration. Python >=3.10, stdlib only."""
import argparse
import json
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

FIELDS = ('signalingServer', 'signalingPort', 'mediaServer', 'mediaPort', 'iceServerConfiguration')


def load_config(path, mode):
    data = json.loads(path.read_text())
    if mode not in ('turn', 'relay'):
        raise ValueError('Unknown transport')
    config = data.get(mode)
    if not isinstance(config, dict) or not all(config.get(k) for k in FIELDS[:4]):
        raise ValueError('Selected transport is not configured')
    if mode == 'turn':
        ice = config.get('iceServerConfiguration', {})
        if ice.get('iceTransportPolicy') != 'relay' or not ice.get('iceServers'):
            raise ValueError('TURN ICE configuration is required')
    return {key: config[key] for key in FIELDS if key in config}


def make_server(config_path, dist, port):
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def end_headers(self):
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            super().end_headers()

        def do_GET(self):
            actual_port = self.server.server_port
            if self.headers.get('Host') not in {f'127.0.0.1:{actual_port}', f'localhost:{actual_port}'}:
                self.send_error(403); return
            parsed = urlsplit(self.path)
            if parsed.path in ('/config.json', '/transports.json'):
                try:
                    if parsed.path == '/transports.json':
                        data = json.loads(config_path.read_text())
                        result = {'transports': [mode for mode in ('turn', 'relay') if data.get(mode)]}
                    else:
                        mode = parse_qs(parsed.query).get('transport', ['turn'])[0]
                        result = load_config(config_path, mode)
                except (OSError, ValueError, TypeError):
                    self.send_error(409, 'Client configuration missing or invalid; update exported config'); return
                body = json.dumps(result).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers(); self.wfile.write(body); return
            # Disallow directory listings and symlinks outside the public bundle.
            requested = Path(self.translate_path(parsed.path)).resolve()
            if not requested.is_relative_to(dist.resolve()) or requested.is_dir():
                if parsed.path != '/':
                    self.send_error(404); return
                if not (dist / 'index.html').resolve().is_relative_to(dist.resolve()):
                    self.send_error(404); return
            super().do_GET()

        def do_HEAD(self):
            if self.path.split('?', 1)[0] in ('/config.json', '/transports.json'):
                self.send_error(405); return
            if self.headers.get('Host') not in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}:
                self.send_error(403); return
            requested = Path(self.translate_path(self.path.split('?', 1)[0])).resolve()
            if not requested.is_relative_to(dist.resolve()):
                self.send_error(404); return
            super().do_HEAD()

    return ThreadingHTTPServer(('127.0.0.1', port), partial(Handler, directory=str(dist.resolve())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--port', type=int, default=5174)
    parser.add_argument('--dist', type=Path, default=Path(__file__).parent / 'web/dist')
    args = parser.parse_args()
    if not (args.dist / 'index.html').is_file():
        parser.error('Missing built Viewer; use a built package or run npm ci && npm run build in web/')
    if args.config.resolve().is_relative_to(args.dist.resolve()):
        parser.error('Private client configuration must be outside the public static directory')
    try:
        server = make_server(args.config, args.dist, args.port)
    except OSError:
        parser.error('Cannot bind loopback port; choose another --port or stop the existing page service')
    print(f'Viewer: http://127.0.0.1:{server.server_port}/?transport=turn', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    if sys.version_info < (3, 10):
        sys.exit('Python >=3.10 is required')
    main()
