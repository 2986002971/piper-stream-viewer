# 浏览器诊断与延迟测量

正常客户端只需Python和浏览器。以下命令工具在源码checkout中提供，是可选诊断，需要WebDriver；raw输出目录必须在仓库外。
Firefox可见模式需桌面会话、Firefox和geckodriver；脚本按Linux桌面环境发现DISPLAY/Wayland，不据此宣称其他系统自动化已实测。

```bash
python3 diagnostics/browser_check.py --browser firefox --driver /path/to/geckodriver \
  --mode turn --duration 120 --output /private/results/firefox-turn
```

默认页面端口5174，可用 `--viewer-port` 选择已启动的页面服务。默认有头；`--headless`仅用于诊断，不替代可见交互验证。
工具检查实际PeerConnection、解码帧增长、1920×1080、可信键鼠输入、断开重连和刷新；
前后截图供检查远端响应，`trusted_input_sent`不能单独证明控制成功，`controls_visually_verified`需要检查证据后另行记录。
脚本不启动服务端、不读取管理SSH配置，不依赖服务端checkout。

仅收集TURN候选（不证明视频/控制）可运行 `python3 diagnostics/turn_smoke_check.py --help`，按该脚本的参数提供私有runtime配置。
常规SDK兼容适配在transport.js中；piper-probe.js只在显式diagnostics/capture时加载。
`?diagnostics=1`只加载探针，调用`window.piperProbe.start()`开启周期getStats收集；`?capture=1`自动开始采集。
默认数据保存在浏览器内存，`await window.piperProbe.stop()`后可调用`window.piperProbe.download()`下载JSONL；WebDriver工具自行导出到指定目录。
SDK不使用探针也会获得ICE配置。WS改写限于本次config指定的host/port，其他WebSocket保持原协议。

快速操作响应测量需要现有可见WebDriver会话，ROI位置按自己的页面调整。
它可以用于未开启统计探针的普通Viewer页面；`browser_check.py`结束后会关闭其会话，不能沿用已结束的会话ID。

```bash
python3 diagnostics/quick_latency.py --port 4446 --session "$FIREFOX_SESSION_ID" \
  --point 45 68 --roi 35 30 220 170 --count 50 --interval 3 \
  --output /private/results/latency-50
```

口径是可信浏览器pointerdown→首次变化视频帧回调，不包含实体鼠标或显示器扫描输出，不等于网络单程延迟。
超时不按零计；紧跟超时的响应可能属于上一操作迟到画面，主分位数排除这些样本。
`responses`保留所有响应，`latency_samples`计入无归属疑义响应，`excluded_after_timeout`单列排除数。
历史50次结果：relay48/50响应、2次超时，主分位数46样本P50 130ms/P95 792ms；TURN50/50响应，P50 93ms/P95 615ms。
两边都有约一秒长尾；单轮短测、Isaac重启、ROI阈值与帧回调调度限制了可比性，不能推断长期稳定性。
完整历史报告在服务端仓库docs/isaac-turn-latency-quick.md，本工具已统一到46样本口径。

候选/SDP统计、输入截图和profile都属于原始诊断，不提交源码或客户端包。
HTTP409先更新独立配置；1005/1006检查信令/Isaac及会话归属；黑屏/停顿结合真实视频与服务端NVENC日志；
远端排障由管理者按服务端部署指南执行。连接状态和视频更新分别显示；视频停顿时检查解码帧增长及服务端日志。
