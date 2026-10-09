#!/usr/bin/env python3
"""Headed, isolated-profile WebDriver checks. Raw evidence stays in a private directory."""
import argparse
import base64
import hashlib
import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode


def desktop_env():
    env = os.environ.copy()
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            if (proc / 'comm').read_text().strip() != 'plasmashell':
                continue
            for item in (proc / 'environ').read_bytes().split(b'\0'):
                key, _, value = item.decode(errors='replace').partition('=')
                if key in ['DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR']:
                    env[key] = value
            break
        except OSError:
            pass
    return env


class Driver:
    def __init__(self, port, base_url=None):
        self.base = base_url or f'http://127.0.0.1:{port}'
        self.session = None

    def request(self, method, path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base + path, data=body, method=method,
                                     headers={'Content-Type': 'application/json'})
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=90) as response:
                result = json.load(response)['value']
        except urllib.error.HTTPError as e:
            raise RuntimeError(e.read().decode()) from e
        if isinstance(result, dict) and result.get('error'):
            raise RuntimeError(str(result))
        return result

    def command(self, path, payload=None, method='POST'):
        return self.request(method, '/session/' + self.session + path, payload)

    def script(self, script):
        return self.command('/execute/sync', {'script': script, 'args': []})


SNAPSHOT = """
const p = window.piperProbe, v = document.querySelector('video');
const connected = p ? [...p.pcs].filter(([pc])=>pc.connectionState==='connected').map(([,s])=>s.id) : [];
const recent = r => connected.includes(r.pc) && performance.now()-r.mono_ms<4000;
return {status: document.querySelector('#status')?.textContent,
  video_status: document.querySelector('#video-status')?.textContent,
  visibility: document.visibilityState, video: v ? {width:v.videoWidth,height:v.videoHeight,time:v.currentTime} : null,
  pcs: p ? [...p.pcs].map(([pc,s])=>({id:s.id,ice:pc.iceConnectionState,connection:pc.connectionState})) : [],
  latest: p?.rows.filter(r=>r.type==='video' && recent(r)).slice(-1)[0],
  pair: p?.rows.filter(r=>r.type==='pc' && recent(r)).slice(-1)[0]};
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--browser', choices=['firefox', 'chromium'], required=True)
    p.add_argument('--driver', type=Path, required=True)
    p.add_argument('--binary', help='Portable Chromium/Firefox executable')
    p.add_argument('--headless', action='store_true', help='Use an isolated headless browser session')
    p.add_argument('--port', type=int, default=4444)
    p.add_argument('--viewer-port', type=int, default=5174)
    p.add_argument('--mode', choices=['relay', 'turn'], required=True)
    p.add_argument('--duration', type=int, default=120)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.duration < 120:
        p.error('Functional check requires at least 120 seconds of video')
    os.umask(0o077)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    env = desktop_env()
    log = (args.output / 'webdriver.log').open('wb')
    proc = subprocess.Popen([str(args.driver), '--port', str(args.port)], stdout=log, stderr=log,
                            env=env, start_new_session=True)
    driver = Driver(args.port)
    snapshots = []
    results = {'browser': args.browser, 'mode': args.mode, 'passed': False}
    try:
        until = time.monotonic() + 15
        while True:
            try:
                driver.request('GET', '/status'); break
            except (OSError, RuntimeError):
                if proc.poll() is not None or time.monotonic() > until:
                    raise RuntimeError('WebDriver did not start')
                time.sleep(.2)
        options = {'args': ['--width=1920', '--height=1080'] + (['--headless'] if args.headless else []),
                   'prefs': {'media.autoplay.default': 0}}
        if args.browser == 'chromium':
            options = {'args': ['--autoplay-policy=no-user-gesture-required', '--no-first-run',
                               '--disable-dev-shm-usage', '--window-size=1920,1080'] +
                               (['--headless=new'] if args.headless else [])}
        if args.binary:
            options['binary'] = args.binary
        vendor = 'moz:firefoxOptions' if args.browser == 'firefox' else 'goog:chromeOptions'
        session = driver.request('POST', '/session', {'capabilities': {'alwaysMatch': {
            'browserName': 'firefox' if args.browser == 'firefox' else 'chrome', vendor: options}}})
        driver.session = session['sessionId']
        results['browser_version'] = session['capabilities']['browserVersion']
        query = urlencode({'transport': args.mode, 'capture': '1', 'autoconnect': '1',
                           'duration': args.duration + 240, 'run_id': args.output.name})
        driver.command('/url', {'url': f'http://127.0.0.1:{args.viewer_port}/?{query}'})
        def snapshot():
            data = driver.script(SNAPSHOT)
            snapshots.append({'wall_ms': time.time()*1000, **data})
            return data
        def wait_video(timeout=90):
            until = time.monotonic() + timeout
            while time.monotonic() < until:
                data = snapshot()
                if (data.get('latest') or {}).get('raw', {}).get('framesDecoded', 0) > 5 and any(
                        pc['connection'] == 'connected' for pc in data['pcs']):
                    return data
                time.sleep(1)
            raise RuntimeError('ICE/video did not become ready; inspect candidate and server logs')
        start = wait_video()
        print('ICE connected and video decoding; starting sustained video check', flush=True)
        results['initial_video'] = True
        results['resolution'] = [start['video']['width'], start['video']['height']]
        until = time.monotonic() + args.duration
        previous_frames = start['latest']['raw']['framesDecoded']
        last_progress = time.monotonic()
        while time.monotonic() < until:
            data = snapshot()
            frames = (data.get('latest') or {}).get('raw', {}).get('framesDecoded', previous_frames)
            if frames != previous_frames:
                previous_frames = frames
                last_progress = time.monotonic()
            if time.monotonic() - last_progress > 5:
                raise RuntimeError('Video decode progress stalled for more than 5 seconds')
            if not any(pc['connection'] == 'connected' for pc in data['pcs']):
                raise RuntimeError('Disconnected during sustained video check')
            time.sleep(2)
        final = snapshot()
        if final['latest']['raw']['framesDecoded'] <= start['latest']['raw']['framesDecoded']:
            raise RuntimeError('Decoded frames did not increase')
        results['sustained_video_s'] = args.duration
        print('Sustained video verified; checking input, reconnect and refresh', flush=True)
        # Trusted input actions, with screenshots for human verification of the remote response.
        for name in ['before', 'after']:
            if name == 'after':
                driver.command('/actions', {'actions': [
                    {'type': 'pointer', 'id': 'mouse', 'parameters': {'pointerType': 'mouse'}, 'actions': [
                        {'type': 'pointerMove', 'x': 900, 'y': 500, 'duration': 200},
                        {'type': 'pointerDown', 'button': 2},
                        {'type': 'pointerMove', 'x': 1040, 'y': 550, 'duration': 700},
                        {'type': 'pointerUp', 'button': 2}]},
                    {'type': 'key', 'id': 'keyboard', 'actions': [
                        {'type': 'pause', 'duration': 1100}, {'type': 'keyDown', 'value': 'f'},
                        {'type': 'keyUp', 'value': 'f'}]}]})
                time.sleep(2)
            shot = base64.b64decode(driver.command('/screenshot', method='GET'))
            (args.output / (name + '.png')).write_bytes(shot)
            results[name + '_screenshot_sha256'] = hashlib.sha256(shot).hexdigest()
        results['trusted_input_sent'] = True
        # Explicit terminate/reconnect, then refresh with a fresh PC.
        driver.script("document.querySelector('#disconnect').click(); return true")
        time.sleep(4)
        disconnected = snapshot()
        if any(pc['connection'] == 'connected' for pc in disconnected['pcs']) or '已主动断开' not in (disconnected['status'] or ''):
            raise RuntimeError('Explicit disconnect did not close the stream and update its status')
        results['disconnect'] = True
        driver.script("document.querySelector('#connect').click(); return true")
        wait_video(); results['reconnect'] = True
        rows = driver.script('return window.piperProbe.rows')
        driver.command('/refresh', {})
        wait_video(); results['refresh'] = True
        time.sleep(3)
        driver.command('/execute/async', {'script':
            'const done=arguments[arguments.length-1];window.piperProbe.stop().then(done)', 'args': []})
        rows += driver.script('return window.piperProbe.rows')
        (args.output / 'browser.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        results['passed'] = results['resolution'] == [1920, 1080]
        # Screenshots/input transmission alone do not prove server-side control response.
        results['controls_visually_verified'] = False
        print(json.dumps(results), flush=True)
    except Exception as error:
        results['error'] = str(error)
        if driver.session:
            try:
                rows = driver.script('return window.piperProbe?.rows || []')
                (args.output / 'browser.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
                shot = base64.b64decode(driver.command('/screenshot', method='GET'))
                (args.output / 'failure.png').write_bytes(shot)
            except Exception:
                pass
        raise
    finally:
        (args.output / 'snapshots.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in snapshots))
        (args.output / 'result.json').write_text(json.dumps(results, indent=2))
        if driver.session:
            try:
                driver.command('', method='DELETE')
            except Exception:
                pass
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL); proc.wait()
        log.close()


if __name__ == '__main__':
    main()
