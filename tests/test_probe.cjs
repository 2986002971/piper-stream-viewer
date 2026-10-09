const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

async function check(mode) {
  let timestamp = 0, submissions = 0, callback, wsUrl;
  class PC {
    constructor(configuration) { this.configuration=configuration; this.connectionState = 'connected'; this.iceConnectionState = 'connected'; }
    addEventListener() {}
    async setRemoteDescription(d) { this.description = d; }
    async getStats() {
      timestamp += 1000;
      return new Map([
        ['t', {id:'t', type:'transport', selectedCandidatePairId:'p'}],
        ['p', {id:'p', type:'candidate-pair', state:'succeeded', currentRoundTripTime:.05}],
        ['v', {id:'v', type:'inbound-rtp', kind:'video', timestamp,
          bytesReceived: timestamp * 100, framesDecoded: timestamp * .06, totalDecodeTime: timestamp * .00012,
          jitter:.003}],
      ]);
    }
  }
  class WS {
    constructor(url) { wsUrl=String(url); }
    addEventListener() {}
    send() {}
  }
  const context = {
    URLSearchParams, URL, Blob, Reflect, Map, Set, Promise,
    location:{search:'?transport='+mode}, navigator:{userAgent:'fixture'},
    performance:{now:()=>timestamp}, Date, document:{visibilityState:'visible', addEventListener(){}},
    setInterval:f=>{callback=f;return 1}, clearInterval(){}, setTimeout, clearTimeout,
    fetch:async()=>{submissions++;return {ok:true}},
    window:{RTCPeerConnection:PC, WebSocket:WS,
      __piperRtcConfiguration:mode==='turn'?{iceServers:[{urls:'turn:turn.example:27645?transport=tcp',username:'user',credential:'secret'}],iceTransportPolicy:'relay'}:null,
      __piperPlainWsEndpoint:mode==='turn'?{hostname:'signal.example',port:'50239'}:{hostname:'127.0.0.1',port:'16006'}},
  };
  vm.runInNewContext(fs.readFileSync(__dirname+'/../web/public/transport.js','utf8'),context);
  vm.runInNewContext(fs.readFileSync(__dirname+'/../web/public/piper-probe.js','utf8'),context);
  const p = context.window.piperProbe;
  new context.window.WebSocket('wss://unrelated.example:50239/socket');
  assert.equal(wsUrl,'wss://unrelated.example:50239/socket');
  const pc = new context.window.RTCPeerConnection();
  new context.window.WebSocket(mode==='turn'?'wss://signal.example:50239/sign_in':'wss://127.0.0.1:16006/sign_in');
  assert.equal(wsUrl,mode==='turn'?'ws://signal.example:50239/sign_in':'ws://127.0.0.1:16006/sign_in');
  if (mode === 'turn') {
    assert.equal(pc.configuration.iceTransportPolicy,'relay');
    assert.equal(pc.configuration.iceServers[0].credential,'secret');
  } else assert.equal(pc.configuration,undefined);
  await pc.setRemoteDescription({sdp:'a=ice-lite\r\na=ice-pwd:secret\r\n'});
  assert.equal(submissions, mode==='relay'?1:0);
  p.start({run_id:'test'});
  await new Promise(r=>setImmediate(r));
  await callback();
  const row = p.rows.filter(r=>r.type==='video').at(-1);
  assert.equal(row.decoded_fps,60);
  assert.equal(row.bitrate_bps,800000);
  assert.ok(Math.abs(row.decode_ms_per_frame-2)<1e-9);
  assert.equal(row.jitter_ms,3);
  assert.equal(row.freeze_s,null); // unavailable browser field must never become zero
  assert.equal(p.rows.find(r=>r.type==='pc').rtt_ms,50);
  assert.equal(p.rows.find(r=>r.type==='pc').pairs[0].selected,true);
  await p.stop();
  assert.equal(JSON.stringify(p.rows).includes('secret'),false);
}
async function captureStartsBeforePeer() {
  let uploads = 0;
  const context = {
    URLSearchParams, URL, Blob, Reflect, Map, Set, Promise,
    location:{search:'?transport=turn&capture=1&duration=60&warmup=10&run_id=fixture'},
    navigator:{userAgent:'fixture'}, performance:{now:()=>0}, Date,
    document:{visibilityState:'visible', addEventListener(){}},
    setInterval(){return 1}, clearInterval(){}, setTimeout(){return 1}, clearTimeout(){},
    fetch:async()=>{uploads++;return {ok:true}}, window:{RTCPeerConnection:class {addEventListener(){} async getStats(){return new Map()} async setRemoteDescription(){}},WebSocket:class {send(){} addEventListener(){}},__piperRtcConfiguration:{iceServers:[{urls:'turn:turn.example:27645?transport=tcp'}],iceTransportPolicy:'relay'}},
  };
  vm.runInNewContext(fs.readFileSync(__dirname+'/../web/public/transport.js','utf8'),context);
  vm.runInNewContext(fs.readFileSync(__dirname+'/../web/public/piper-probe.js','utf8'),context);
  const p = context.window.piperProbe;
  assert.equal(p.recording,true);
  assert.equal(p.rows[0].type,'start');
  new context.window.RTCPeerConnection();
  assert.equal(p.rows[1].type,'pc-created');
  assert.equal(p.rows[0].metadata.run_id,'fixture');
  await new Promise(r=>setImmediate(r));
  await p.stop();
  assert.equal(uploads,0);
}
async function quickStatsWithoutProbe() {
  class PC {
    constructor() { this.connectionState = 'connected'; }
    addEventListener() {}
    async getStats() {
      return new Map([
        ['t', {type:'transport', selectedCandidatePairId:'p'}],
        ['p', {type:'candidate-pair', localCandidateId:'c', currentRoundTripTime:.05}],
        ['c', {type:'local-candidate', candidateType:'relay'}],
        ['v', {id:'v', type:'inbound-rtp', kind:'video', framesDecoded:120, bytesReceived:9000}],
      ]);
    }
  }
  const video = {videoWidth:1920, videoHeight:1080,
    requestVideoFrameCallback(){return 1}, cancelVideoFrameCallback(){}};
  const context = {
    URLSearchParams, URL, Reflect, Map, Set, Promise,
    location:{search:'?transport=turn'}, performance:{now:()=>1000},
    document:{visibilityState:'visible',querySelector:()=>video,
      createElement:()=>({getContext:()=>({})}),addEventListener(){},removeEventListener(){}},
    setInterval(){return 1}, clearInterval(){}, clearTimeout(){},
    window:{RTCPeerConnection:PC,WebSocket:class {},
      __piperRtcConfiguration:{iceServers:[{urls:'turn:turn.example:27645?transport=tcp'}],iceTransportPolicy:'relay'}},
  };
  vm.runInNewContext(fs.readFileSync(__dirname+'/../web/public/transport.js','utf8'),context);
  new context.window.RTCPeerConnection();
  assert.equal(context.window.piperProbe,undefined);
  vm.runInNewContext(fs.readFileSync(__dirname+'/../diagnostics/quick-latency.js','utf8'),context);
  await new Promise(r=>setImmediate(r));
  const result = context.window.piperQuickLatency.stop();
  assert.equal(result.stats.length,1);
  assert.equal(result.stats[0].framesDecoded,120);
  assert.equal(result.stats[0].local_candidate_type,'relay');
  assert.equal(result.stats[0].rtt_ms,50);
}
(async()=>{await check('relay');await check('turn');await captureStartsBeforePeer();await quickStatsWithoutProbe();console.log('Transport, probe and independent quick measurement checks passed');})().catch(e=>{console.error(e);process.exit(1)});
