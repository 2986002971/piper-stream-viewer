/* Optional statistics; load before creating a stream connection. */
(() => {
  if (window.piperProbe) return;
  const mode = new URLSearchParams(location.search).get('transport') || 'turn';
  if (!['relay', 'turn'].includes(mode)) throw new Error('Unknown transport mode');
  const pcs = new Map();
  const rows = [];
  let recording = false, timer = null, busy = false, stopTimer = null, measureTimer = null;
  let run = null, nextId = 0;
  const emit = row => {
    if (!recording) return;
    const record = {wall_ms: Date.now(), mono_ms: performance.now(), ...row};
    rows.push(record);
  };
  const delta = (r, p, key) => Number.isFinite(r[key]) && Number.isFinite(p?.[key]) && r[key] >= p[key]
    ? r[key] - p[key] : null;
  const rate = (v, dt, multiplier = 1) => v == null || !(dt > 0) ? null : v * multiplier / dt;
  function event(pc, id, type) {
    emit({type, pc: id, ice: pc.iceConnectionState, connection: pc.connectionState,
      signaling: pc.signalingState});
  }
  async function sample() {
    if (busy) return;
    busy = true;
    try {
      for (const [pc, state] of pcs) {
        if (pc.connectionState === 'closed') continue;
        try {
          const stats = await pc.getStats();
          const all = [...stats.values()];
          const transports = all.filter(r => r.type === 'transport');
          const selected = new Set(transports.map(r => r.selectedCandidatePairId).filter(Boolean));
          const pairs = all.filter(r => r.type === 'candidate-pair').map(r => ({...r,
            selected: r.selected === true || selected.has(r.id),
            local: stats.get(r.localCandidateId), remote: stats.get(r.remoteCandidateId)}));
          const pair = pairs.find(r => r.selected) || pairs.find(r => r.nominated && r.state === 'succeeded');
          emit({type: 'pc', pc: state.id, ice: pc.iceConnectionState,
            connection: pc.connectionState, pairs, rtt_ms: pair?.currentRoundTripTime == null
              ? null : pair.currentRoundTripTime * 1000});
          for (const r of all.filter(r => r.type === 'inbound-rtp' && (r.kind || r.mediaType) === 'video')) {
            const p = state.previous.get(r.id);
            const dt = p ? (r.timestamp - p.timestamp) / 1000 : null;
            const frames = delta(r, p, 'framesDecoded');
            emit({type: 'video', pc: state.id, stream: r.id,
              interval_s: dt, raw: r, codec: stats.get(r.codecId),
              bitrate_bps: rate(delta(r, p, 'bytesReceived'), dt, 8),
              decoded_fps: rate(frames, dt),
              decode_ms_per_frame: frames > 0 ? rate(delta(r, p, 'totalDecodeTime'), frames, 1000) : null,
              jitter_ms: r.jitter == null ? null : r.jitter * 1000,
              freeze_s: delta(r, p, 'totalFreezesDuration'), freeze_count: delta(r, p, 'freezeCount'),
              // Proxy only: this is NOT browser freeze duration or interaction latency.
              no_decoded_frame_s: frames === 0 && dt > 0 ? dt : 0,
              visibility: document.visibilityState});
            state.previous.set(r.id, {...r});
          }
        } catch (e) { emit({type: 'stats-error', pc: state.id, error: String(e)}); }
      }
    } finally { busy = false; }
  }
  const NativePC = window.RTCPeerConnection;
  window.RTCPeerConnection = new Proxy(NativePC, {
    construct(Target, args) {
      const pcArgs = args;
      const pc = Reflect.construct(Target, pcArgs);
      const id = ++nextId;
      pcs.set(pc, {id, previous: new Map()});
      emit({type: 'pc-created', pc: id, iceTransportPolicy: pcArgs[0]?.iceTransportPolicy || 'all'});
      for (const name of ['iceconnectionstatechange', 'connectionstatechange', 'signalingstatechange'])
        pc.addEventListener(name, () => event(pc, id, name));
      pc.addEventListener('icecandidate', e => emit({type: 'candidate', pc: id,
        candidate: e.candidate?.toJSON() || null}));
      pc.addEventListener('icecandidateerror', e => emit({type: 'candidate-error', pc: id,
        code: e.errorCode, text: e.errorText, address: e.address, port: e.port, url: e.url}));
      return pc;
    },
  });
  const NativeWS = window.WebSocket;
  window.WebSocket = new Proxy(NativeWS, {
    construct(Target, args) {
      const ws = Reflect.construct(Target, args);
      const requested = new URL(String(args[0]));
      emit({type: 'ws-created', protocol: requested.protocol, host: requested.host,
        path: requested.pathname, query_keys: [...requested.searchParams.keys()]});
      const nativeSend = ws.send.bind(ws);
      ws.send = data => {
        let shape = {kind: typeof data, bytes: typeof data === 'string' ? data.length : null};
        if (typeof data === 'string') {
          try { const value = JSON.parse(data); shape = {kind:'json', keys:Object.keys(value),
            type: value.type || value.message_type || value.event_type || null,
            action: value.action || null}; } catch {}
        }
        emit({type: 'ws-send', shape});
        return nativeSend(data);
      };
      ws.addEventListener('open', () => emit({type: 'ws-open'}));
      ws.addEventListener('message', e => {
        let shape = {kind: typeof e.data, bytes: typeof e.data === 'string' ? e.data.length : null};
        if (typeof e.data === 'string') {
          try { const value = JSON.parse(e.data); shape = {kind:'json', keys:Object.keys(value),
            type: value.type || value.message_type || value.event_type || null,
            action: value.action || null}; } catch {}
        }
        emit({type: 'ws-message', shape});
      });
      ws.addEventListener('close', e => emit({type: 'ws-close', code: e.code, clean: e.wasClean}));
      return ws;
    },
  });
  for (const type of ['pointerdown', 'pointerup', 'keydown', 'keyup'])
    document.addEventListener(type, e => emit({type: 'input', input: type,
      key: e.key, button: e.button, x: e.clientX, y: e.clientY, trusted: e.isTrusted}), true);
  document.addEventListener('visibilitychange', () => emit({type: 'visibility', value: document.visibilityState}));
  window.piperProbe = {
    mode, rows, pcs,
    get recording() { return recording; },
    start(metadata = {}, options = {}) {
      if (recording) throw new Error('Already collecting');
      rows.length = 0;
      for (const state of pcs.values()) state.previous.clear();
      run = {mode, browser: navigator.userAgent, ...metadata};
      recording = true;
      emit({type: 'start', metadata: run});
      for (const [pc, state] of pcs) event(pc, state.id, 'initial-state');
      sample(); timer = setInterval(sample, 1000);
      const warmup = Math.max(0, Number(options.warmup_s || 0));
      measureTimer = setTimeout(() => emit({type: 'measurement-start'}), warmup * 1000);
      if (options.duration_s) stopTimer = setTimeout(() => this.stop(), (options.duration_s + warmup) * 1000);
    },
    async stop() {
      clearInterval(timer); clearTimeout(stopTimer); clearTimeout(measureTimer);
      while (busy) await new Promise(r => setTimeout(r, 10));
      await sample(); emit({type: 'stop'}); recording = false;
      return {rows: rows.length};
    },
    download() {
      const blob = new Blob([rows.map(r => JSON.stringify(r)).join('\n') + '\n'], {type: 'application/x-ndjson'});
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
      a.download = `${run?.run_id || 'precheck'}-${mode}.jsonl`; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    },
    mark(label) { emit({type: 'mark', label}); },
  };
  const capture = new URLSearchParams(location.search);
  if (capture.get('capture') === '1') {
    const duration = Number(capture.get('duration') || 600);
    const runId = capture.get('run_id') || mode + '-precheck';
    const warmup = Number(capture.get('warmup') || 0);
    if (!(duration > 0 && Number.isFinite(duration) && warmup >= 0 && Number.isFinite(warmup)))
      throw new Error('Invalid capture duration or warmup');
    // Start before a stream connection creates its PC or WebSocket.
    (() => {
      try {
        const metadata = {run_id: runId, sdk: '5.6.0'};
        for (const key of ['instance_tag', 'gpu', 'scene_sha256', 'encoder_settings'])
          if (capture.has(key)) metadata[key] = capture.get(key);
        window.piperProbe.start(metadata, {
          duration_s: duration,
          warmup_s: warmup,
        });
      } catch (error) {
        console.error('Piper WebRTC probe failed to start', error);
      }
    })();
  }
})();
