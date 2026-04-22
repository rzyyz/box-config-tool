# 盒子内置配置工具源码说明

这份源码用于开发“边缘计算盒子运维管理工具”。当前重点是 `Box_admin` 前端配置工具，运行在盒子本地浏览器中，默认访问地址为：

```text
http://<盒子IP>:8090
```

正式部署时，所有盒子统一放到固定目录：

```bash
/home/nvidia/Project/box_config_tool
```

这样后续更新时，只需要覆盖同名目录，服务文件和桌面图标路径都不需要重新适配。

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
│   ├── install_manual_services.sh     # 安装服务，但默认不开机自启
│   ├── disable_all_autostart.sh       # 关闭项目服务自启和定时重启
│   ├── install_daily_reboot_timer.sh  # 安装每天 03:30 自动重启
│   ├── box_daily_reboot.service
│   └── box_daily_reboot.timer
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
- 自动创建 `~/Project/box_config_tool`，并在需要时把当前安装包复制到该目录。
- 优先使用 `yolo11_py310` conda 环境；如果不存在，会尝试离线创建，失败后使用 `base`。
- 检查 `flask`、`fastapi`、`uvicorn`、`flask_cors`，缺少时从 `python_wheels/`、`wheels/`、`offline_wheels/`、`packages/` 或 `PIP_WHEEL_DIR` 指定目录离线安装。
- 安装 `box_admin.service`、`config_agent.service`、`traffic_detect.service`。
- 安装最小 sudoers，让页面可以执行网卡修改和服务启停。
- 默认开启三个服务的开机自启，并立即启动三个服务。
- 如桌面存在 `~/Desktop`，自动安装“盒子配置工具”桌面图标。

常用可选项：

```bash
# 只安装和自启服务，但本次不启动 traffic_detect 重服务
START_TRAFFIC=0 bash scripts/install_onekey.sh

# 安装服务但不设置开机自启
ENABLE_AUTOSTART=0 bash scripts/install_onekey.sh

# 指定离线 Python wheel 目录
PIP_WHEEL_DIR=/home/nvidia/offline_wheels bash scripts/install_onekey.sh

# 指定服务运行用户和正式部署目录
SERVICE_USER=box TARGET_PROJECT_ROOT=/home/box/Project/box_config_tool bash scripts/install_onekey.sh

# 只在当前目录安装，不复制到 ~/Project/box_config_tool
AUTO_INSTALL_TO_TARGET=0 bash scripts/install_onekey.sh

# 最终交付盒子同时启用每天 03:30 自动重启
INSTALL_DAILY_REBOOT=1 bash scripts/install_onekey.sh
```

一键安装完成后访问：

```text
http://127.0.0.1:8090
http://<盒子IP>:8090
```

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
