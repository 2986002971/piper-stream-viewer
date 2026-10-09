/* Required SDK compatibility, independent of optional statistics collection. */
(() => {
  const mode = new URLSearchParams(location.search).get('transport') || 'turn';
  if (!['turn', 'relay'].includes(mode)) throw new Error('Unknown transport');
  const NativePC = window.RTCPeerConnection;
  window.piperConnections = new Set();
  window.RTCPeerConnection = new Proxy(NativePC, {
    construct(Target, args) {
      if (mode === 'turn') {
        const ice = window.__piperRtcConfiguration;
        if (!ice?.iceServers?.length || ice.iceTransportPolicy !== 'relay')
          throw new Error('Missing TURN configuration');
        args = [{...(args[0] || {}), ...ice}, ...args.slice(1)];
      }
      const pc = Reflect.construct(Target, args);
      window.piperConnections.add(pc);
      pc.addEventListener('connectionstatechange', () => {
        window.dispatchEvent(new CustomEvent('piper-connection', {detail: pc.connectionState}));
        if (pc.connectionState === 'closed') window.piperConnections.delete(pc);
      });
      if (mode === 'relay') {
        const nativeRemote = pc.setRemoteDescription.bind(pc);
        pc.setRemoteDescription = async description => {
          const sdp = description?.sdp || '';
          const password = sdp.includes('a=ice-lite') ? /^a=ice-pwd:(.+)$/m.exec(sdp)?.[1]?.trim() : null;
          if (password) {
            const response = await fetch('http://127.0.0.1:16009/ice-password', {
              method: 'POST', headers: {'Content-Type': 'text/plain'}, body: password,
            });
            if (!response.ok) throw new Error('Legacy ICE password submission failed');
          }
          return nativeRemote(description);
        };
      }
      return pc;
    },
  });
  const NativeWS = window.WebSocket;
  window.WebSocket = new Proxy(NativeWS, {
    construct(Target, args) {
      const url = new URL(String(args[0]));
      const endpoint = window.__piperPlainWsEndpoint;
      if (endpoint && url.protocol === 'wss:' && url.hostname === endpoint.hostname &&
          url.port === String(endpoint.port)) {
        url.protocol = 'ws:';
        args = [url.toString(), ...args.slice(1)];
      }
      return Reflect.construct(Target, args);
    },
  });
})();
