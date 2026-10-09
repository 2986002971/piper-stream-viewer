#!/usr/bin/env python3
"""Estimate input-to-video response in an existing visible Firefox session."""
import argparse
import base64
import json
import os
import statistics
import time
from pathlib import Path

from browser_check import Driver


def summarize(samples, stats):
    responses = [r for r in samples if r['status'] == 'response']
    delays = [r['latency_ms'] for i, r in enumerate(samples) if r['status'] == 'response'
              and not (i > 0 and samples[i - 1]['status'] == 'timeout')]
    rtts = [r['rtt_ms'] for r in stats if r.get('rtt_ms') is not None]
    previous, fps = {}, []
    for row in stats:
        old = previous.get(row['stream'])
        if old and row['timestamp'] > old['timestamp']:
            count = row['framesDecoded'] - old['framesDecoded']
            if count >= 0:
                fps.append(1000 * count / (row['timestamp'] - old['timestamp']))
        previous[row['stream']] = row
    return {'metric': 'trusted browser pointerdown to changed-video frame callback',
            'operations': len(samples), 'responses': len(responses), 'latency_samples': len(delays),
            'excluded_after_timeout': len(responses) - len(delays),
            'timeouts': sum(r['status'] == 'timeout' for r in samples),
            'other_failures': sum(r['status'] not in ('response', 'timeout') for r in samples),
            'latency_ms': {'median': statistics.median(delays) if delays else None,
                           'p95': percentile(delays, 95),
                           'min': min(delays) if delays else None, 'max': max(delays) if delays else None},
            'rtt_ms_median': statistics.median(rtts) if rtts else None,
            'rtt_ms_max': max(rtts) if rtts else None,
            'decoded_fps_median': statistics.median(fps) if fps else None,
            'zero_decoded_frame_intervals': sum(f == 0 for f in fps),
            'hidden_stats': sum(r.get('visibility') != 'visible' for r in stats),
            'candidate_types': sorted({r['local_candidate_type'] for r in stats
                                       if r.get('local_candidate_type')}),
            'per_operation': [{'operation_id': r['operation_id'], 'status': r['status'],
                               'latency_ms': r.get('latency_ms'),
                               'follows_timeout': i > 0 and samples[i - 1]['status'] == 'timeout'}
                              for i, r in enumerate(samples)]}


def percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    rank = (len(values) - 1) * p / 100
    lower, upper = int(rank), int(rank + .999999999)
    return values[lower] + (values[upper] - values[lower]) * (rank - lower)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session', required=True, help='Existing geckodriver session ID')
    p.add_argument('--port', type=int, default=4446)
    p.add_argument('--point', type=int, nargs=2, required=True, metavar=('X', 'Y'),
                   help='Click coordinates in browser client pixels')
    p.add_argument('--roi', type=int, nargs=4, required=True, metavar=('X', 'Y', 'W', 'H'),
                   help='Response region in intrinsic video pixels')
    p.add_argument('--count', type=int, default=10)
    p.add_argument('--interval', type=float, default=3)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.count < 1 or args.interval < 0:
        p.error('count must be positive and interval nonnegative')
    os.umask(0o077)
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    driver = Driver(args.port)
    driver.session = args.session
    probe = Path(__file__).with_name('quick-latency.js').read_text()
    samples, stats = [], []
    context = driver.script("const v=document.querySelector('video');return {"
                            "browser:navigator.userAgent,transport:new URLSearchParams(location.search).get('transport'),"
                            "video:[v?.videoWidth,v?.videoHeight],started_wall_ms:Date.now()}")
    try:
        driver.script(probe)
        x, y = args.point
        driver.command('/actions', {'actions': [{'type': 'pointer', 'id': 'quick-mouse',
            'parameters': {'pointerType': 'mouse'}, 'actions': [
                {'type': 'pointerMove', 'x': x, 'y': y, 'duration': 0}]}]})
        time.sleep(.5)
        roi = dict(zip(('x', 'y', 'width', 'height'), args.roi))
        for i in range(1, args.count + 1):
            started = time.monotonic()
            driver.script(f'window.piperQuickLatency.arm({i}, {json.dumps(roi)}); return true')
            driver.command('/actions', {'actions': [{'type': 'pointer', 'id': 'quick-mouse',
                'parameters': {'pointerType': 'mouse'}, 'actions': [
                    {'type': 'pointerDown', 'button': 0},
                    {'type': 'pause', 'duration': 40}, {'type': 'pointerUp', 'button': 0}]}]})
            row = driver.command('/execute/async', {'script':
                'const done=arguments[arguments.length-1];window.piperQuickLatency.result.then(done)',
                'args': []})
            samples.append(row)
            print(json.dumps({'operation': i, 'status': row['status'],
                              'latency_ms': row.get('latency_ms')}), flush=True)
            if i < args.count:
                time.sleep(max(0, args.interval - (time.monotonic() - started)))
    finally:
        try:
            data = driver.script('return window.piperQuickLatency.stop()')
            samples, stats = data['samples'], data['stats']
        finally:
            driver.command('/actions', method='DELETE')
        for row in samples:
            for name in ('before_png', 'after_png'):
                encoded = row.pop(name, None)
                if encoded:
                    (args.output / f"{row['operation_id']:02d}-{name}.png").write_bytes(
                        base64.b64decode(encoded.split(',', 1)[1]))
        (args.output / 'raw.json').write_text(json.dumps({'samples': samples, 'stats': stats}, indent=2))
        result = summarize(samples, stats)
        result['point_client_px'] = args.point
        result['roi_video_px'] = args.roi
        result['context'] = context
        (args.output / 'summary.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
