import {AppStreamer, StreamType, LogLevel, type DirectConfig} from '@nvidia/omniverse-webrtc-streaming-library';

const query = new URLSearchParams(location.search);
const mode = query.get('transport') || 'turn';
const status = document.querySelector<HTMLSpanElement>('#status')!;
const videoStatus = document.querySelector<HTMLSpanElement>('#video-status')!;
const video = document.querySelector<HTMLVideoElement>('#remote-video')!;
const connectButton = document.querySelector<HTMLButtonElement>('#connect')!;
const disconnectButton = document.querySelector<HTMLButtonElement>('#disconnect')!;
const link = document.querySelector<HTMLAnchorElement>('#switch')!;
const globals = window as any;
let active = false, connecting = false, generation = 0, lastFrame = 0;
let lastPresented = 0;
document.querySelector('#mode')!.textContent = mode === 'turn' ? 'TURN' : 'Legacy relay';

// Statistics wrappers are loaded only on explicit request, before a session starts.
const probePath = '/piper-probe.js';
const diagnosticsReady = query.get('capture') === '1' || query.get('diagnostics') === '1'
  ? import(/* @vite-ignore */ probePath) : Promise.resolve();
void fetch('/transports.json', {cache: 'no-store'}).then(r => r.json()).then(data => {
  if (data.transports.includes('relay')) {
    link.hidden = false;
    link.href = '?transport=' + (mode === 'turn' ? 'relay' : 'turn');
    link.textContent = mode === 'turn' ? 'Legacy relay' : 'TURN';
  }
}).catch(() => {});

window.addEventListener('piper-connection', (event: Event) => {
  if (!active) return;
  const state = (event as CustomEvent<string>).detail;
  status.textContent = ({connected: '已连接', failed: '连接失败', disconnected: '连接中断',
    closed: '连接已关闭', connecting: '连接中'} as Record<string, string>)[state] || state;
  if (state === 'failed' || state === 'disconnected' || state === 'closed') videoStatus.textContent = '视频已中断';
});

function presentedFrame() {
  if (active) {
    lastFrame = performance.now();
    videoStatus.textContent = '视频更新中';
    if (status.textContent === '会话已建立，等待视频更新') status.textContent = '会话已建立';
  }
}
if ('requestVideoFrameCallback' in video) {
  const nextFrame = () => video.requestVideoFrameCallback(() => { presentedFrame(); nextFrame(); });
  nextFrame();
}
setInterval(() => {
  if (!active) return;
  if (!('requestVideoFrameCallback' in video)) {
    const frames = (video as HTMLVideoElement).getVideoPlaybackQuality().totalVideoFrames;
    if (frames > lastPresented) { lastPresented = frames; presentedFrame(); }
  }
  if (lastFrame && performance.now() - lastFrame > 3000) {
    videoStatus.textContent = document.hidden ? '页面在后台，视频更新未确认' : '视频停顿超过 3 秒';
  }
}, 500);

async function disconnect() {
  generation++;
  active = false;
  connecting = false;
  connectButton.disabled = true;
  disconnectButton.disabled = true;
  try {
    await AppStreamer.terminate();
    status.textContent = '已主动断开';
  } catch (error) {
    status.textContent = '断开失败：' + String(error);
  } finally {
    // Close retained PCs to prevent a previous session updating the new session UI.
    for (const pc of globals.piperConnections || []) pc.close();
    video.srcObject = null;
    lastFrame = 0;
    videoStatus.textContent = '视频已停止';
    connectButton.disabled = false;
    disconnectButton.disabled = false;
  }
}

async function connect() {
  if (connecting || active) return;
  const session = ++generation;
  connecting = true;
  connectButton.disabled = true;
  status.textContent = '连接中（请求信令）';
  videoStatus.textContent = '等待视频';
  lastFrame = performance.now();
  lastPresented = 0;
  try {
    await diagnosticsReady;
    if (!['turn', 'relay'].includes(mode)) throw new Error('Unknown transport');
    const response = await fetch('/config.json?transport=' + mode, {cache: 'no-store'});
    if (!response.ok) throw new Error('配置不可用：HTTP ' + response.status);
    const config: DirectConfig = await response.json();
    if (session !== generation) return;
    globals.__piperRtcConfiguration = mode === 'turn' ? (config as any).iceServerConfiguration : null;
    const endpoint = new URL(`http://${config.signalingServer}`);
    globals.__piperPlainWsEndpoint = {hostname: endpoint.hostname, port: String(config.signalingPort)};
    active = true;
    await AppStreamer.connect({streamSource: StreamType.DIRECT, logLevel: LogLevel.INFO,
      streamConfig: {...config, authenticate: false, nativeTouchEvents: true,
        width: 1920, height: 1080, fps: 60, maxReconnects: 20,
        videoElementId: 'remote-video', audioElementId: 'remote-audio',
        onUpdate: event => {
          if (session !== generation || !active) return;
          if (event.status !== 'success') status.textContent = `${event.action}: ${event.status} ${event.info}`;
          console.info('OV WebRTC', event);
        },
        onStart: event => {
          if (session !== generation || !active) return;
          status.textContent = event.status === 'success' ? '会话已建立，等待视频更新' : `连接失败：${event.info}`;
        },
      }});
    if (session === generation) video.focus();
  } catch (error) {
    if (session !== generation) return;
    active = false;
    try { await AppStreamer.terminate(); } catch {}
    status.textContent = '连接失败：' + String(error);
    videoStatus.textContent = '视频未连接';
    connectButton.disabled = false;
  } finally {
    if (session === generation) connecting = false;
  }
}
connectButton.addEventListener('click', () => void connect());
disconnectButton.addEventListener('click', () => void disconnect());
if (query.get('autoconnect') === '1') void connect();
