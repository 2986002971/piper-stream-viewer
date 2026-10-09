#!/usr/bin/env python3
"""Check standard browser TURN candidate gathering separately from Isaac signaling."""
import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from browser_check import Driver, desktop_env


SCRIPT = r"""
const done = arguments[arguments.length - 1];
(async () => {
  let config = arguments[0];
  if (!config) {
    const response = await fetch('/config.json?transport=turn', {cache:'no-store'});
    if (!response.ok) throw new Error('TURN config HTTP ' + response.status);
    config = await response.json();
  }
  const ice = config.iceServerConfiguration;
  const overrideUrl = arguments[1];
  if (overrideUrl) ice.iceServers = ice.iceServers.map(server => ({...server, urls:overrideUrl}));
  const errors = [];
  const pc = new RTCPeerConnection({iceServers:ice.iceServers, iceTransportPolicy:'relay'});
  pc.addEventListener('icecandidateerror', e => errors.push({code:e.errorCode,
    text:e.errorText, scheme:(e.url || '').split(':')[0], transport:(e.url || '').split('?').pop()}));
  pc.createDataChannel('turn-smoke');
  await pc.setLocalDescription(await pc.createOffer());
  await Promise.race([new Promise(resolve => pc.addEventListener('icegatheringstatechange',
    () => {if (pc.iceGatheringState === 'complete') resolve();})),
    new Promise(resolve => setTimeout(resolve, 20000))]);
  const candidates = (pc.localDescription?.sdp || '').split(/\r?\n/)
    .filter(line => line.startsWith('a=candidate:'))
    .map(line => ({protocol:/\s(udp|tcp)\s/i.exec(line)?.[1]?.toLowerCase() || null,
      type:/\styp\s(host|srflx|prflx|relay)(?:\s|$)/.exec(line)?.[1] || null}));
  const result = {gatheringState:pc.iceGatheringState, policy:ice.iceTransportPolicy,
    turnUrlCount:ice.iceServers.length, candidates, errors};
  pc.close();
  return result;
})().then(done).catch(e => done({error:String(e)}));
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', choices=['firefox', 'chromium'], default='firefox')
    parser.add_argument('--driver', type=Path, required=True)
    parser.add_argument('--headless', action='store_true', help='Use an isolated headless browser session')
    parser.add_argument('--webdriver-url', help='Use an already running WebDriver endpoint')
    parser.add_argument('--viewer-url', help='Viewer URL reachable from the browser')
    parser.add_argument('--config-json', type=Path, help='Private JSON containing browser ICE configuration')
    parser.add_argument('--port', type=int, default=4445)
    parser.add_argument('--viewer-port', type=int, default=5174)
    parser.add_argument('--turn-url', help='Optional TURN URL override for isolating platform-forward behavior')
    args = parser.parse_args()
    proc = None if args.webdriver_url else subprocess.Popen(
        [str(args.driver), '--port', str(args.port)], env=desktop_env(),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    driver = Driver(args.port, args.webdriver_url)
    try:
        until = time.monotonic() + 15
        while True:
            try:
                driver.request('GET', '/status')
                break
            except (OSError, RuntimeError):
                if (proc is not None and proc.poll() is not None) or time.monotonic() > until:
                    raise RuntimeError('WebDriver did not start')
                time.sleep(.2)
        options = {'args': ['--width=1280', '--height=720'] + (['--headless'] if args.headless else []),
                   'prefs': {'media.autoplay.default': 0}}
        browser = 'firefox' if args.browser == 'firefox' else 'chrome'
        vendor = 'moz:firefoxOptions' if browser == 'firefox' else 'goog:chromeOptions'
        session = driver.request('POST', '/session', {'capabilities': {'alwaysMatch': {
            'browserName': browser, vendor: options}}})
        driver.session = session['sessionId']
        viewer_url = args.viewer_url or ('about:blank' if args.config_json else
                                          f'http://127.0.0.1:{args.viewer_port}/?transport=turn')
        driver.command('/url', {'url': viewer_url})
        config = json.loads(args.config_json.read_text()) if args.config_json else None
        result = driver.command('/execute/async', {'script': SCRIPT, 'args': [config, args.turn_url]})
        print(json.dumps(result, indent=2))
    finally:
        if driver.session:
            try:
                driver.command('', method='DELETE')
            except Exception:
                pass
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()


if __name__ == '__main__':
    main()
