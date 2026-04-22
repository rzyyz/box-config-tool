# AGENTS.md

## 分支定位

该目录是“边缘计算盒子内置配置工具”的独立开发分支。处理这里的任务时，默认目标是把盒子上的运维配置页面、外部配置接收服务和感知服务部署流程打磨稳定。

不要把本目录和 `Project/GBT43229-master/` 混为一条线。除非用户明确要求回到 GBT43229 主工程，否则优先在本目录内处理。

## 固定部署约定

盒子统一部署路径：

```bash
/home/nvidia/Project/box_config_tool
```

当前无线网测试板：

```text
IP: 192.168.9.125
user: nvidia
password: 按现场约定，不提交到 git
```

当前测试板状态：

- Chromium 已安装，可打开 `http://127.0.0.1:8090` 或 `http://<盒子IP>:8090`。
- RustDesk 已安装，版本 `1.4.6`，ID `327799673`。
- RustDesk 中文字体方格问题已补充字体：`fonts-noto-cjk`、`fonts-wqy-microhei`、`fonts-wqy-zenhei`。
- 项目服务路径按 `/home/nvidia/Project/box_config_tool` 组织，后续更新应保持该路径不变。
- 最近一次更新已同步到测试板，`box_admin.service` 和 `traffic_detect.service` 验证为 `active`。
- 测试板更新时优先覆盖源码并重启相关服务，不要在已有安装上重复执行完整安装流程，除非用户明确要求。

## 目录职责

- `Box_admin/`
  - Flask 前端配置工具，默认端口 `8090`。
  - 面向销售/现场人员，不是开发人员调试页。
  - 当前重点是页面流畅度、配置易用性、服务状态、数据检测、信号机配置。
- `Config_agent/`
  - FastAPI 配置接收服务，默认端口 `18080`。
  - 给外部标定/配置工具提交相机、车道线、区域、排队区、车头时距、基准长度等配置。
- `Traffic_detect/`
  - 路口感知检测与 GB/T 43229 上传主服务。
  - 会拉起 DeepStream，属于重服务。
- `DeepStream-Yolo/`
  - 当前车辆检测 DeepStream 工程和 RTSP 配置。
- `scripts/`
  - 服务安装、关闭自启、每日重启等运维脚本。
- `release/`
  - 临时交付包目录，不作为优先源码修改目标。

## 当前功能状态

`Box_admin` 已具备：

- 联网设置：查看和配置网卡 IP、网关、DNS、网口备注。
- 绑定相机：输入相机 IP、账号、密码、端口、路径，自动生成 RTSP，支持新增相机、禁用相机、高级彻底删除 source。
- 相机检查分两类：IP Ping 只检查主机可达；视频流拉流使用 GStreamer `gst-launch-1.0 rtspsrc ... fakesink` 验证 RTSP 账号、密码、路径是否可用。
- 画面标定：当前先检查标定配置文件是否齐全。
- 运行状态：显示服务状态、启停、重启、开机自启开关。
- 信号机设置：可配置信号机 IP 和端口，保存后自动重启路口感知检测服务；信号机心跳检测显示在本页。
- 步进控制状态：检查本机步进工具 `http://127.0.0.1:8080` 是否在线，发送信号机连接参数，获取 `ctrlMode` 控制状态，上传信号机配置文件。
- 数据检测：以表格展示全部车道数据，支持统计最近 N 小时流量，点击刷新才读取数据。

近期性能优化：

- 页面已改成按页面懒加载。
- 打开首页只加载联网设置。
- 切到绑定相机才加载相机列表。
- 切到运行状态才加载服务状态和信号机心跳。
- 切到数据检测后由按钮刷新 CSV 和日志。
- CSV 读取只 tail 最近数据，不全文件扫描。
- 日志读取只 tail 最近几百行，不全文件扫描。

相机 source id 策略：

- source id 是稳定编号，永远不要因为删除、禁用或某一路故障而自动重排。
- 新增相机自动创建下一个 source id，也就是当前最大 source id + 1。
- 普通删除操作必须等价于“禁用此相机”，只改 `enable=0`。
- 只有高级危险操作才允许彻底删除 `[sourceN]` 段；彻底删除后也不能重排其他 source id。
- 如果禁用后重新填回同一个 URI，只需要保存并重启 `traffic_detect.service`；原 source id 的检测线、区域等配置仍然对应。
- 如果彻底删除中间 source 后再新增相同 URI，新 source id 可能变成新的最大编号，旧 source id 对应的标定配置不会自动迁移。
- 保存相机 IP、账号、密码、端口、路径或启用状态后，应自动重启 `traffic_detect.service`。

服务中文显示名：

- `traffic_detect.service`：路口感知检测服务
- `config_agent.service`：检测线数据接收服务
- `box_admin.service`：智能感知系统配置工具服务

## RTSP 与 Config_agent 约定

相机配置优先级：

- 收到 `rtsp_uri` 或 `uri` 时，认为是完整 RTSP，优先直接写入。
- 收到 `ip + username/password/port/path` 时，由服务生成 RTSP。
- 只收到 `ip` 时，只替换现有 DeepStream `uri=` 的主机 IP，保留原账号、密码、端口和路径。

注意：

- 用户密码里可能包含 `@`、`%`、`:` 等特殊字符，生成 RTSP 时必须做 URL 编码。
- DeepStream 配置里每路最终只能有一个 `uri=`，不要出现默认 URI 和新 URI 同时写入。
- 保存配置后通常需要重启 `traffic_detect.service`。
- 更新 `[sourceN]` 时只允许修改对应 source 段，不要误改 `[tiled-display]`、`[sink0]` 等非 source 段的 `enable=`。
- 新增 source 时复制现有 source 模板块并替换 header、`enable=`、`uri=`，插入到最后一个 source 块后面。

`Traffic_detect` source id 约定：

- `Traffic_detect/main.py` 必须按 DeepStream 原始 source id 运行，不允许把启用源重新枚举成 `0,1,2,3`。
- `get_enabled_deepstream_sources()` 返回真实启用 source id，例如 `[1, 3, 4]`。
- 每路运行配置应生成在 `DeepStream-Yolo/generated_runtime/source_<source_id>/`。
- 每路轨迹输出目录应是 `DeepStream-Yolo/output_kitti_data/source_<source_id>/`。
- worker 启动应使用真实 source id：`source_worker(source_id, source_<source_id>, ...)`。
- 如果 `source0` 视频流坏了，其他 source 的轨迹输出目录仍然是 `source_1`、`source_2` 等原编号目录，不能顺延。
- 首次生成共享 TensorRT engine 时，不要固定依赖 `source0`；当前逻辑优先选择非 0 的启用源作为 bootstrap source，可用 `DEEPSTREAM_ENGINE_BOOTSTRAP_SOURCE` 覆盖。

`Config_agent` 常更新：

- `Traffic_detect/config/lines_config.json`
- `Traffic_detect/config/headway_config.json`
- `Traffic_detect/config/zones_config.json`
- `Traffic_detect/config/zones_queue.json`
- `Traffic_detect/config/base_length.json`
- `DeepStream-Yolo/deepstream_app_config.txt`

鉴权：

- `CONFIG_AGENT_TOKEN` 默认为空。
- 若设置 token，写配置接口需带 `X-Config-Agent-Token` 或 `Authorization: Bearer <token>`。

## 服务与自启策略

开发板调试阶段：

- 默认不要开启项目服务开机自启。
- `box_admin.service` 和 `config_agent.service` 较轻，可按需启动。
- `traffic_detect.service` 会拉 DeepStream，确认配置前谨慎启动。

可用脚本：

```bash
bash scripts/install_onekey.sh
bash scripts/install_manual_services.sh
bash scripts/disable_all_autostart.sh
bash scripts/install_daily_reboot_timer.sh
```

一键交付：

- 正式内网盒子可使用 `scripts/install_onekey.sh` 做“一包拷贝 + 一个 sh 一键安装启动”。
- 盒子需预装 DeepStream、CUDA/TensorRT；工程根目录可放入 `Miniforge3-Linux-aarch64.sh`。
- 脚本默认使用当前登录用户作为服务用户，目标路径为 `~/Project/box_config_tool`，不是必须叫 `nvidia`。
- 如果目标目录不存在，脚本会创建；如果从 U 盘或下载目录运行，会复制整包到目标目录。
- 脚本会安装/复用 Miniforge、检查离线 Python wheels、安装 systemd 服务、配置最小 sudoers，并可设置开机自启。
- 默认会开启三个服务自启并启动服务；调试时可用 `START_TRAFFIC=0` 跳过启动重服务。

每日重启：

- `scripts/install_daily_reboot_timer.sh` 安装每天 `03:30` 自动重启。
- 如果排查黑屏、服务异常或内存问题，先检查 timer 是否真的启用。

常用命令：

```bash
systemctl status box_admin.service --no-pager
systemctl status config_agent.service --no-pager
systemctl status traffic_detect.service --no-pager
journalctl -u traffic_detect.service -n 80 --no-pager
systemctl list-timers --all | grep -E 'reboot|box'
```

## Box_admin 开发约定

主要修改文件：

- `Box_admin/templates/index.html`
- `Box_admin/static/app.css`
- `Box_admin/static/app.js`
- `Box_admin/app.py`

新增页面：

- 在 `index.html` 新增 `section.page-panel`。
- `data-page-key` 用英文小写和短横线。
- `data-page-title` 是左侧菜单名称。
- 左侧菜单由 `app.js` 自动扫描页面生成。
- 页面说明写给销售/现场人员看，避免写“调用接口”“渲染 DOM”等开发说明。

新增后端接口：

- 在 `Box_admin/app.py` 增加 `/api/...`。
- 优先返回清晰的业务结论，不要把命令输出或大段代码直接展示给用户。
- 涉及 sudo 的操作，优先走最小权限 sudoers，不要在前端暴露系统密码。

UI/体验：

- 避免页面一打开就轮询大量接口。
- 默认按页面懒加载，数据检测类页面尽量点击刷新才读取。
- 多车道数据优先表格化，避免卡片过多导致页面卡顿。
- 文案要面向非技术人员，解释“这项配置有什么用”和“当前是否正常”。

## Git 协作约定

远程仓库：

```text
https://github.com/rzyyz/box-config-tool.git
```

分支：

- `main` 已分享给开发人员，避免直接推实验性修改。
- 新优化优先从当前代码新建 `feature/<name>` 分支。
- 曾使用分支：`feature/data-check-table-stats`。

适合提交的内容：

- `Box_admin/`
- `scripts/`
- `README.md`
- `GIT_COLLAB_GUIDE.md`
- `NEW_BOARD_SAFE_GUIDE.md`
- `.gitignore`
- `AGENTS.md`

通常不要提交：

- `Traffic_detect/`
- `DeepStream-Yolo/`
- `Config_agent/`
- `release/`
- `*.zip`
- `*.tar.gz`
- 日志、CSV、模型、engine、运行输出、现场 RTSP、账号密码。

例外：

- 如果用户明确要求把感知服务源码修复同步到 git，且修改是小范围源码变更，可以单独 `git add -f Traffic_detect/main.py`。不要顺手提交 `Traffic_detect/config/`、日志、CSV 或运行输出。

提交前检查：

```bash
git status --short
git diff --stat
python -m py_compile Box_admin/app.py
```

## 远程盒子验证

页面验证：

```bash
curl http://127.0.0.1:8090/api/status
curl http://127.0.0.1:8090/api/runtime-summary
curl "http://127.0.0.1:8090/api/data-summary?hours=1"
```

资源排查：

```bash
free -h
uptime
ps -eo pid,user,comm,rss,args --sort=-rss | head -40
```

常见内存占用判断：

- 多个 `deepstream-app` 是主要重负载。
- Chromium 会占用数百 MB。
- `box_admin.service` 和 `config_agent.service` 通常较轻。
- Linux `buff/cache` 不等于泄漏，应重点看 `available`、swap 和具体进程 RSS。

## 安全注意

- 该目录可能包含现场 IP、RTSP、账号密码，外发前必须脱敏。
- Windows 本地路径和盒子 Linux 路径要分清。
- 修改 DeepStream 配置时，最终运行路径必须是盒子上的 Linux 绝对路径。
- 不要把运行产物当源码修复目标。
- 不要执行破坏性 Git 或文件命令，除非用户明确要求。
