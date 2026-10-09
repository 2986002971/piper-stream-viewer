# Piper Stream Viewer

独立的本机 Viewer：浏览器直接经 TURN 收发视频及控制，Python 仅在 loopback 提供静态页面和配置。
已构建包只需要 Python ≥3.10 和普通浏览器，无 Node、SSH、TUN 或 Python 媒体relay依赖。
项目代码为 [MIT](LICENSE)，NVIDIA streaming SDK 及依赖保留各自许可证，见 [第三方声明](THIRD_PARTY_NOTICES.md)。

## 已构建客户端

解包到任意工作目录，客户端配置单独保存在 `web/dist` 之外。管理者从服务端 `export-client` 交付 `client.json`。
不要把管理SSH配置或服务端完整配置交给客户端。配置包含TURN凭据，可信交付和保存。

```bash
python3 viewer.py --config /path/to/private/client.json
```

Windows可使用 `py -3 viewer.py --config C:\private\client.json`；这只是启动方式，实机媒体验证范围见 [验证记录](docs/verification.md)。
打开 `http://127.0.0.1:5174/`，默认TURN，点击连接。主动断开后页面明确显示断开和视频停止。
连接状态与实际视频更新分别显示；视频状态使用真实frame presentation callback，而不是仅靠成功事件或播放时钟。
前台超过3秒无更新显示停顿，后台显示更新未确认。

配置每次请求重读；地址/凭据改变时替换 `client.json` 即可，无需重建或重启Python。配置缺失或损坏返回409，页面服务仍监听。
页面端口占用时启动明确失败；可用 `--port 5175`（legacy relay需5174）。静态目录缺失时提示使用已构建包或先构建。
Python服务只监听127.0.0.1，检查Host且拒绝静态目录外symlink；配置接口无CORS并返回no-store。
配置HTTP200不表示Isaac已就绪；服务端停止后导出的配置副本仍存在，应根据真实连接/视频判断。

一份Isaac只交接一份活跃会话。先由旧同事主动断开，再连接新页面；失败可断开后重连或刷新。
仅配置 `relay` 才显示模式切换。切换只选择客户端配置，不能启动或停止服务器；legacy回退由管理者另行启停。

## 从源码构建

构建基线 Node **22.20.0**、npm ≥10；`.nvmrc` 固定Node基线，SDK `5.6.0`、TypeScript `5.8.3`、Vite `6.3.5` 和lockfile固定。
日常运行已构建包不需要Node。

```bash
cd web
npm ci
npm run build
cd ..
python3 viewer.py --config /path/to/private/client.json
python3 package_client.py --output /path/outside/repo/piper-stream-viewer-client.zip
```

打包脚本只选择页面服务、静态页面和许可/使用说明，不包含配置、浏览器profile、诊断数据或模型。
`web/dist`、`node_modules`、`__pycache__` 已忽略；运行和构建不应产生新的待提交文件。

配置API保留 `/config.json?transport=turn`；`/transports.json`只返回可选模式名。
必要ICE配置和限定信令host/port的WS适配在 `web/public/transport.js`，独立于可选统计探针。
常规连接不会启动本项目的统计探针。显式 `?diagnostics=1` 加载探针，`?capture=1` 开始采集；原始候选/统计数据需保存在仓库外。
[诊断与测量](docs/diagnostics.md) 包含可见Firefox WebDriver、TURN候选预检和延迟口径。

当前页面本机HTTP、信令WS、TURN/TCP，WebRTC自身DTLS/SRTP不等于所有入口HTTPS。
统一托管、HTTPS/WSS网关、鉴权及长期可靠性验收尚未实现。服务端仍由Linux管理机SSH及75分钟watchdog管理；
页面刷新/模式切换不改变这个生命周期。
