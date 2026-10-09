/* Temporary browser-side measurement; injected by quick_latency.py. */
(() => {
  window.piperQuickLatency?.stop();
  const video = document.querySelector('video');
  if (!video?.requestVideoFrameCallback || !video.videoWidth)
    throw new Error('A playing video with requestVideoFrameCallback is required');
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d', {willReadFrequently: true});
  const samples = [], stats = [];
  let active = null, frameId = null, stopped = false, statsBusy = false;
  const pixels = () => {
    const r = active.roi;
    ctx.drawImage(video, r.x, r.y, r.width, r.height, 0, 0, canvas.width, canvas.height);
    return ctx.getImageData(0, 0, canvas.width, canvas.height).data;
  };
  function finish(result) {
    if (!active) return;
    clearTimeout(active.timer);
    const operation = active;
    active = null;
    const row = {...operation.record, ...result};
    samples.push(row);
    operation.resolve(row);
  }
  function frame(now, metadata) {
    if (stopped) return;
    if (active?.record.input_ms != null) {
      const current = pixels(), previous = active.baseline;
      let total = 0, changed = 0;
      for (let i = 0; i < current.length; i += 4) {
        const difference = (Math.abs(current[i] - previous[i]) +
          Math.abs(current[i + 1] - previous[i + 1]) +
          Math.abs(current[i + 2] - previous[i + 2])) / 3;
        total += difference;
        if (difference > 16) changed++;
      }
      const count = current.length / 4, mean = total / count, fraction = changed / count;
      active.record.observed_frames++;
      active.record.max_mean_difference = Math.max(active.record.max_mean_difference, mean);
      active.record.max_changed_fraction = Math.max(active.record.max_changed_fraction, fraction);
      // A large region change excludes the remote cursor and compression noise.
      if (mean >= 10 && fraction >= .15) {
        finish({status: 'response', response_ms: now, latency_ms: now - active.record.input_ms,
          mean_difference: mean, changed_fraction: fraction,
          frame: {mediaTime: metadata.mediaTime, presentedFrames: metadata.presentedFrames,
            presentationTime: metadata.presentationTime, expectedDisplayTime: metadata.expectedDisplayTime},
          after_png: canvas.toDataURL('image/png')});
      }
    }
    frameId = video.requestVideoFrameCallback(frame);
  }
  function input(event) {
    if (!active || active.record.input_ms != null || !event.isTrusted || event.button !== 0 ||
        event.target !== video) return;
    active.record.input_ms = performance.now();
    active.record.event_timestamp_ms = event.timeStamp;
    active.record.trusted = event.isTrusted;
  }
  async function sampleStats() {
    if (statsBusy || stopped) return;
    statsBusy = true;
    try {
      for (const pc of (window.piperConnections || [])) {
        if (pc.connectionState !== 'connected') continue;
        const values = await pc.getStats(), all = [...values.values()];
        const transport = all.find(r => r.type === 'transport' && r.selectedCandidatePairId);
        const pair = transport ? values.get(transport.selectedCandidatePairId) :
          all.find(r => r.type === 'candidate-pair' && r.nominated && r.state === 'succeeded');
        for (const r of all.filter(r => r.type === 'inbound-rtp' && (r.kind || r.mediaType) === 'video'))
          stats.push({mono_ms: performance.now(), timestamp: r.timestamp, stream: r.id,
            rtt_ms: Number.isFinite(pair?.currentRoundTripTime) ? pair.currentRoundTripTime * 1000 : null,
            framesDecoded: r.framesDecoded, bytesReceived: r.bytesReceived,
            width: r.frameWidth, height: r.frameHeight,
            local_candidate_type: values.get(pair?.localCandidateId)?.candidateType,
            visibility: document.visibilityState});
      }
    } finally { statsBusy = false; }
  }
  const timer = setInterval(sampleStats, 1000);
  document.addEventListener('pointerdown', input, true);
  frameId = video.requestVideoFrameCallback(frame);
  sampleStats();
  window.piperQuickLatency = {
    samples, stats,
    arm(id, roi, timeoutMs = 2000) {
      if (active) throw new Error('Operation already pending');
      if (roi.x < 0 || roi.y < 0 || roi.width <= 0 || roi.height <= 0 ||
          roi.x + roi.width > video.videoWidth || roi.y + roi.height > video.videoHeight)
        throw new Error('ROI is outside the video');
      canvas.width = Math.min(roi.width, 160);
      canvas.height = Math.max(1, Math.round(roi.height * canvas.width / roi.width));
      let resolve;
      const promise = new Promise(r => { resolve = r; });
      this.result = promise;
      active = {roi, resolve, record: {operation_id: id, armed_ms: performance.now(),
        input_ms: null, observed_frames: 0, max_mean_difference: 0, max_changed_fraction: 0}};
      active.baseline = pixels().slice();
      active.record.before_png = canvas.toDataURL('image/png');
      active.timer = setTimeout(() => finish({status: active.record.input_ms == null ?
        'no-input' : 'timeout', latency_ms: null}), timeoutMs);
    },
    stop() {
      stopped = true;
      clearInterval(timer);
      video.cancelVideoFrameCallback(frameId);
      document.removeEventListener('pointerdown', input, true);
      finish({status: 'cancelled', latency_ms: null});
      return {samples, stats};
    },
  };
  return {width: video.videoWidth, height: video.videoHeight};
})();
