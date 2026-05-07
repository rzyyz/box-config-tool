# 盒子内置配置工具源码说明

这份源码用于开发“边缘计算盒子运维管理工具”。当前重点是 `Box_admin` 前端配置工具，运行在盒子本地浏览器中，默认访问地址为：

```text
http://<盒子IP>:8090
```

正式部署时，所有盒子统一放到固定目录：

```bash
/home/nvidia/Project/box_config_tool
```

项目运行日志统一落在：

```bash
/home/<当前用户>/Project/box_config_tool/logs
```

其中：

- `logs/box_admin/`
- `logs/config_agent/`
- `logs/traffic_detect/`

现场诊断日志可一键打包：

```bash
bash scripts/collect_box_logs.sh
```

会在：

```bash
release/diagnostics_时间戳.tar.gz
```

生成可直接带回来的日志包。

这样后续更新时，只需要覆盖同名目录，服务文件和桌面图标路径都不需要重新适配。

## 浏览器离线交付

为了让盒子本机在无外网环境下也尽量能直接打开 `http://127.0.0.1:8090`，交付包建议同时带两套浏览器资源：

```text
offline_browser/
├── browser_snaps_export/   # Chromium snap 离线包
└── epiphany_debs/          # Epiphany .deb 离线包
```

安装逻辑：

- 优先尝试 Chromium 离线 snap。
- 如果 Chromium 离线安装失败，不再中断整个安装。
- 若 `epiphany-browser` 未安装，且 `offline_browser/epiphany_debs/` 已准备好，则自动离线安装 Epiphany 作为本地浏览器兜底。
- 再不行时，若盒子联网且 `apt-get` 可用，脚本会尝试在线安装 Epiphany。

## Java17 离线交付

`preplan-control.service` 运行 `preplan-control.jar` 需要 Java 17。最终离线包建议提前准备本机同系统、同架构的 OpenJDK 17 deb 包：

```text
offline_java/
└── openjdk17_debs/       # OpenJDK 17 及依赖 .deb 包
```

在一台能联网、系统版本和目标盒子一致的 aarch64 盒子上执行：

```bash
bash scripts/prepare_openjdk17_offline_debs.sh
```

脚本会把 `openjdk-17-jre-headless` 及依赖下载到 `offline_java/openjdk17_debs/`。之后把这个目录随安装包一起拷贝到现场盒子。一键安装时会优先离线安装 Java17；如果目录未准备好，才会按 `PREPLAN_AUTO_INSTALL_JAVA=1` 尝试联网安装。

## 1. 源码结构

```text
box_config_tool/
├── Box_admin/
│   ├── app.py                         # Flask 后端入口，同时提供页面和接口
│   ├── templates/
│   │   └── index.html                 # 前端页面骨架，所有分页 section 都在这里
│   ├── static/
│   │   ├── app.css                    # 页面样式
│   │   └── app.js                     # 页面交互、接口请求、分页切换
│   ├── start.sh                       # 启动配置工具
│   ├── open_box_admin.sh              # 桌面图标调用脚本
│   ├── box_admin.desktop              # 桌面图标配置
│   ├── box_admin.service.example      # 配置工具 systemd 服务模板
│   ├── README.md                      # Box_admin 单独说明
│   └── FRONTEND_COLLAB_GUIDE.md       # 前端协作规范
├── Config_agent/
│   ├── app.py                         # 给外部标定/配置工具调用的接口服务
│   ├── deepstream_cfg.py              # 写 DeepStream RTSP 配置
│   ├── validators.py                  # 入参校验
│   ├── restart_manager.py             # 重启检测服务
│   ├── settings.py                    # 路径和服务名配置
│   ├── start.sh
│   └── config_agent.service.example
├── Traffic_detect/
│   ├── main.py                        # 路口感知检测主程序
│   ├── config/                        # 标定与业务配置
│   ├── queue_csv/                     # 运行后生成的统计 CSV
│   ├── log/                           # 运行日志
│   ├── start.sh
│   └── traffic_detect.service.example
├── DeepStream-Yolo/
│   └── deepstream_app_config.txt      # 视频源 RTSP 配置文件
├── scripts/
│   ├── install_onekey.sh              # 正式交付一键安装、开机自启和启动
│   ├── fix_package_line_endings.sh    # 安全修复 Windows CRLF 换行，不处理 Miniforge 等二进制
│   ├── install_epiphany_offline.sh    # 从本地 deb 包离线安装 Epiphany 浏览器
│   ├── install_openjdk17_offline.sh   # 从本地 deb 包离线安装 Java17
│   ├── prepare_openjdk17_offline_debs.sh # 在联网同架构盒子上准备 Java17 离线 deb
│   ├── install_manual_services.sh     # 安装服务，但默认不开机自启
│   ├── install_preplan_control_service.sh # 安装步进/智能控制 Java 服务
│   ├── disable_all_autostart.sh       # 关闭项目服务自启和定时重启
│   ├── install_daily_reboot_timer.sh  # 安装每天 03:30 自动重启
│   ├── box_daily_reboot.service
│   └── box_daily_reboot.timer
├── test/
│   └── preplan-control-server/        # 可选 Java 步进/智能控制服务（含 jar）
├── NEW_BOARD_SAFE_GUIDE.md            # 新开发板安全启动说明
└── README.md                          # 当前文件
```

开发人员主要改：

```text
Box_admin/templates/index.html
Box_admin/static/app.css
Box_admin/static/app.js
```

如果新增页面需要读取或保存盒子配置，再让后端在 `Box_admin/app.py` 增加对应 `/api/...` 接口。

## 2. 当前页面

当前 `Box_admin` 已有页面：

- `联网设置`：查看和设置网卡 IP、网关、DNS、网口备注。
- `绑定相机`：填写相机名称、IP、账号、密码、路径，自动生成 RTSP，并检查相机连通性。
- `画面标定`：当前先检查标定文件是否齐全，后续可接入真正标定页面。
- `运行状态`：查看服务状态、服务启停、重启后自动启动开关、信号机心跳摘要。
- `信号机设置`：配置和检查信号机 IP、端口，保存后自动重启路口感知检测服务。
- `步进控制状态`：查看步进工具状态、发送信号机连接参数、获取控制状态、同步配置，并可跳转到信号机页面由操作人员手动下载配置文件。
- `数据检测`：显示全部车道的车流、车头时距、排队长度，以及近期异常日志。
- `数据日志`：展示最近 30 分钟检测数据，按 5 秒采样绘制趋势图，并支持分钟级时间段查询与导出。
- `运行日志`：汇总配置工具、配置接收、感知检测、信号机连通、智能控制等链路状态，并支持导出最近诊断日志。
- `批量更新`：每台盒子都可作为主控更新器，自动保存目标表格，自动比对白名单差异，只做增量同步。

## 3. 新增页面方法

左侧菜单不需要手写，`app.js` 会自动扫描页面里的 `section.page-panel`。

新增页面时，在 `Box_admin/templates/index.html` 加一个 section：

```html
<section class="page-panel" data-page-key="your-page" data-page-title="你的页面名">
  <div class="section-head">
    <h2>你的页面名</h2>
    <p>这里写给销售或现场人员看的说明，不写给开发人员看的技术说明。</p>
  </div>

  <article class="card">
    <div id="yourPageRoot"></div>
    <div class="actions">
      <button id="refreshYourPageBtn" class="btn secondary">刷新</button>
      <button id="saveYourPageBtn" class="btn primary">保存</button>
    </div>
  </article>
</section>
```

约定：

- `data-page-key` 用英文小写和短横线，例如 `calibration-step`。
- `data-page-title` 是左侧菜单显示名。
- 页面说明写给销售和现场人员看，避免写“调用 API”“渲染 DOM”等开发说明。
- 需要新样式时优先复用 `card`、`card-grid`、`field`、`actions`、`data-table`、`summary-item`、`status-card`、`metric-item`。

## 4. JS 开发约定

在 `Box_admin/static/app.js` 中按三段式写：

```js
function renderYourPage(data) {
  // 只负责把数据渲染到页面
}

async function loadYourPage() {
  const data = await fetchJson("/api/your-page");
  renderYourPage(data);
}

function bindYourPageActions() {
  document.getElementById("refreshYourPageBtn").addEventListener("click", loadYourPage);
}
```

然后在 `wireActions()` 中调用 `bindYourPageActions()`，在 `boot()` 的初始加载中加入 `loadYourPage()`。

注意：

- 所有接口请求统一使用 `fetchJson()`。
- 不要把渲染、请求、事件绑定揉成一个很长的函数。
- 不要频繁整页刷新，局部更新即可。
- 如果一块 HTML 内容没变化，优先使用已有的 `setHtmlIfChanged()` 减少页面卡顿。

## 5. API 返回约定

接口统一返回 JSON。

成功：

```json
{
  "ok": true,
  "data": {}
}
```

失败：

```json
{
  "ok": false,
  "message": "错误原因"
}
```

约定：

- 查询用 `GET`。
- 保存、检查、启动、重启等动作用 `POST`。
- 字段名确定后不要随意改，否则会影响前端页面。
- 如果接口会执行 Linux 命令，必须由后端封装，前端不要拼命令。

## 6. 本地和盒子运行

在盒子上运行：

```bash
cd /home/nvidia/Project/box_config_tool/Box_admin
bash start.sh
```

浏览器访问：

```text
http://127.0.0.1:8090
```

局域网访问：

```text
http://<盒子IP>:8090
```

如果服务已安装：

```bash
sudo systemctl start box_admin.service
sudo systemctl start config_agent.service
```

开发板调试阶段不要随便启动 `traffic_detect.service`，它会拉 DeepStream，配置不对时可能造成桌面卡顿或黑屏。

## 7. 部署与安全约定

正式交付盒子推荐使用一键脚本。盒子需已预装 DeepStream、CUDA/TensorRT，工程根目录放入 `Miniforge3-Linux-aarch64.sh`，并准备好已安装依赖的 conda 环境或本地 Python wheels。

如果需要离线安装 Chromium，请提前把 snap 包放到：

```text
offline_browser/snaps/
```

当前离线脚本按下面这些文件名查找：

```text
bare_5.snap
core22_2412.snap
core24_1588.snap
cups_1171.snap
gnome-46-2404_147.snap
gtk-common-themes_1535.snap
mesa-2404_1166.snap
chromium_3318.snap
```

如果当前账号不是 `nvidia`，脚本会默认使用当前账号作为服务运行用户，并把正式目录设为：

```bash
~/Project/box_config_tool
```

如果你把整包先放在下载目录或 U 盘目录运行，脚本会自动创建上面的正式目录，并把整包复制过去再安装。也可以直接先复制到正式目录后运行：

```bash
cd /home/nvidia/Project/box_config_tool
chmod +x scripts/install_onekey.sh
bash scripts/install_onekey.sh
```

一键脚本默认会：

- 安装 Miniforge 到当前用户的 `~/miniforge3`，如果已存在则跳过。
- 如果 `~/miniforge3` 是上次失败留下的残缺目录，脚本会自动改名备份后重新安装。
- 自动创建 `~/Project/box_config_tool`，并在需要时把当前安装包复制到该目录。
- 自动修复包内文本脚本的 Windows CRLF 换行，但会跳过 `Miniforge3-Linux-aarch64.sh`、wheels、snap、deb、jar、engine 等二进制文件。
- 优先使用 `yolo11_py310` conda 环境；如果不存在，会尝试离线创建，失败后使用 `base`。
- 检查 `flask`、`fastapi`、`uvicorn`、`flask_cors`、`paramiko`，缺少时从 `python_wheels/`、`wheels/`、`offline_wheels/`、`packages/` 或 `PIP_WHEEL_DIR` 指定目录离线安装。
- 批量更新主控能力依赖 `paramiko`，安装包内必须同时准备 `paramiko`、`bcrypt`、`cryptography`、`PyNaCl` 的离线 wheel；否则配置工具能打开，但“批量更新”页在新盒子上会报缺少 SSH 依赖。
- 安装 `box_admin.service`、`config_agent.service`、`traffic_detect.service`。
- 如果 `preplan-control.jar` 存在于 `preplan-control-server/` 或 `test/preplan-control-server/`，则一并安装 `preplan-control.service`。
- `preplan-control.service` 需要 Java 17；如果盒子已预装 Java 会直接使用，否则优先从 `offline_java/openjdk17_debs/` 离线安装，最后才按 `PREPLAN_AUTO_INSTALL_JAVA=1` 尝试联网补装。
- 如 `offline_browser/snaps/` 已准备好，则自动离线安装 Chromium。
- 安装最小 sudoers，让页面可以执行网卡修改和服务启停。
- 当前默认按“现场模式”交付：
  - `box_admin.service`
  - `config_agent.service`
  - `traffic_detect.service`
  - `preplan-control.service`
  都会安装、开机自启并立即启动。
- 如果现场是 4G 盒子或调试环境，需要减载时，再显式设置 `START_TRAFFIC=0`、`START_PREPLAN=0`、`ENABLE_TRAFFIC_AUTOSTART=0`、`ENABLE_PREPLAN_AUTOSTART=0`。
- Java17 和浏览器兜底默认只使用包内离线资源，不再自动访问 apt 源；如确实允许联网补装，再显式设置 `PREPLAN_AUTO_INSTALL_JAVA=1` 或 `BROWSER_AUTO_INSTALL_APT=1`。
- 默认启用每天 `03:30` 自动重启盒子。
- 如桌面存在 `~/Desktop`，自动安装“盒子配置工具”桌面图标。
- 自动创建 `logs/` 和 `release/`，便于现场采集日志。

如果现场先遇到 `$'\r'`、`bad interpreter` 或类似换行符错误，可先执行安全修复脚本，再重新安装：

```bash
bash scripts/fix_package_line_endings.sh
bash scripts/install_onekey.sh
```

不要对整个安装包直接执行 `sed -i 's/\r$//' *`，`Miniforge3-Linux-aarch64.sh` 是带二进制 payload 的自解压脚本，直接改它会导致 `md5sum mismatch`。

常用可选项：

```bash
# 本次直接启动 traffic_detect 重服务
START_TRAFFIC=1 bash scripts/install_onekey.sh

# 允许 traffic_detect 开机自启
ENABLE_TRAFFIC_AUTOSTART=1 bash scripts/install_onekey.sh

# 安装服务但不设置开机自启
ENABLE_AUTOSTART=0 bash scripts/install_onekey.sh

# 指定离线 Python wheel 目录
PIP_WHEEL_DIR=/home/nvidia/offline_wheels bash scripts/install_onekey.sh

# 本次不装 Chromium
INSTALL_CHROMIUM_OFFLINE=0 bash scripts/install_onekey.sh

# 本次不装 preplan-control Java 服务
INSTALL_PREPLAN_CONTROL=0 bash scripts/install_onekey.sh

# 本次直接启动 preplan-control Java 服务
START_PREPLAN=1 bash scripts/install_onekey.sh

# 允许 preplan-control 开机自启
ENABLE_PREPLAN_AUTOSTART=1 bash scripts/install_onekey.sh

# 禁止脚本尝试安装包内离线 Java17
PREPLAN_INSTALL_OFFLINE_JAVA=0 bash scripts/install_onekey.sh

# 缺少 Java 时，允许脚本在线安装 OpenJDK 17
PREPLAN_AUTO_INSTALL_JAVA=1 bash scripts/install_onekey.sh

# 允许脚本在线安装 Epiphany 浏览器兜底
BROWSER_AUTO_INSTALL_APT=1 bash scripts/install_onekey.sh

# 指定服务运行用户和正式部署目录
SERVICE_USER=box TARGET_PROJECT_ROOT=/home/box/Project/box_config_tool bash scripts/install_onekey.sh

# 只在当前目录安装，不复制到 ~/Project/box_config_tool
AUTO_INSTALL_TO_TARGET=0 bash scripts/install_onekey.sh

# 不启用每天 03:30 自动重启
INSTALL_DAILY_REBOOT=0 bash scripts/install_onekey.sh
```

一键安装完成后访问：

```text
http://127.0.0.1:8090
http://<盒子IP>:8090
```

如果页面要在盒子本机桌面打开，`open_box_admin.sh` 会优先尝试：

- `google-chrome`
- `chromium-browser`
- `chromium`
- `/snap/bin/chromium`

安装服务：

```bash
cd /home/nvidia/Project/box_config_tool
bash scripts/install_manual_services.sh
```

这个脚本会安装服务文件，但默认执行 `disable`，不会开机自启。

最终交付盒子如果需要每天凌晨 `03:30` 自动重启：

```bash
bash scripts/install_daily_reboot_timer.sh
systemctl list-timers box_daily_reboot.timer
```

开发调试时如果要一键关闭项目自启、定时重启和 DeepStream 进程：

```bash
bash scripts/disable_all_autostart.sh
```

如果新盒子开机后黑屏闪光标，优先怀疑重服务自启导致桌面或网络未正常起来。能进入 TTY 或 recovery shell 时，先执行：

```bash
cd ~/Project/box_config_tool
bash scripts/rescue_disable_heavy_services.sh
sudo reboot
```

## 8. 协作开发建议包含

建议直接发送整个目录：

```text
Project/盒子内置配置工具/
```

如果文件太大，页面开发人员最低需要：

```text
Box_admin/
Config_agent/README.md
scripts/
README.md
NEW_BOARD_SAFE_GUIDE.md
```

如果需要联调真实数据、服务状态、相机和信号机配置，则必须保留：

```text
Traffic_detect/
DeepStream-Yolo/
```

发送前注意不要外发现场真实 RTSP、账号、密码、内网 IP 等敏感信息。

## 9. 开发人员开始工作前的检查清单

- 先读本文件和 `Box_admin/FRONTEND_COLLAB_GUIDE.md`。
- 明确要新增的页面名称和 `data-page-key`。
- 明确页面需要哪些数据，以及是否已有 API。
- 只改自己页面相关的 HTML/CSS/JS，不要顺手改已有页面业务逻辑。
- 如果需要新增 API，先约定返回 JSON 结构，再写前端。
