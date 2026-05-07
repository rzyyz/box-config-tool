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
- 如 Chromium snap 在新盒子上因 `snap-confine` 权限链路异常无法本地打开页面，可改用 `epiphany-browser http://127.0.0.1:8090` 作为兜底浏览器。
- RustDesk 已安装，版本 `1.4.6`，ID `327799673`。
- RustDesk 中文字体方格问题已补充字体：`fonts-noto-cjk`、`fonts-wqy-microhei`、`fonts-wqy-zenhei`。
- 项目服务路径按 `/home/nvidia/Project/box_config_tool` 组织，后续更新应保持该路径不变。
- 最近一次更新已同步到测试板，`box_admin.service` 和 `traffic_detect.service` 验证为 `active`。
- 测试板更新时优先覆盖源码并重启相关服务，不要在已有安装上重复执行完整安装流程，除非用户明确要求。
- Chromium 离线 snap 包可从测试板导出到 `/home/nvidia/browser_snaps_export/`，再拷回工程的 `offline_browser/snaps/`。
- 最近一次信控网排障涉及两台无线接入盒子：
  - `192.168.9.101`
  - `192.168.9.102`
- 两台盒子的 Wi-Fi 自连已关闭：
  - `192.168.9.101`：`ZHZX -> connection.autoconnect no`
  - `192.168.9.102`：`ZHZX -> no`，`rzyyz的nova 10 -> no`
- 两台盒子的有线 `Wired connection 1` 已补静态路由：
  - `172.16.14.0/24 via 172.16.16.1`
- 其中：
  - `192.168.9.101` 当前有线路由配置已写入，但最近一次排障时物理链路是 `linkdown`
  - `192.168.9.102` 最近一次排障时 `enP8p1s0` 为 `UP`，静态路由已生效

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
  - `install_chromium_offline.sh` 负责从 `offline_browser/snaps/` 离线安装 Chromium。
  - `install_epiphany_offline.sh` 负责从 `offline_browser/epiphany_debs/` 离线安装 Epiphany 浏览器兜底。
  - `collect_box_logs.sh` 负责打包现场诊断日志。
- `offline_browser/`
  - `browser_snaps_export/` 存放 Chromium snap 离线包。
  - `epiphany_debs/` 存放 Epiphany 浏览器 arm64 `.deb` 离线包。
- `release/`
  - 临时交付包目录，不作为优先源码修改目标。

## 当前功能状态

`Box_admin` 已具备：

- 联网设置：查看和配置网卡 IP、网关、DNS、网口备注。
- 绑定相机：输入相机 IP、账号、密码、端口、路径，自动生成 RTSP，支持新增相机、禁用相机、高级彻底删除 source。
- 相机检查分两类：IP Ping 只检查主机可达；视频流拉流使用 GStreamer `gst-launch-1.0 rtspsrc ... fakesink` 验证 RTSP 账号、密码、路径是否可用。
- 绑定相机点击“检查连通性”后会立即显示“检查中”，禁用刷新/保存/检查按钮，避免用户误以为页面卡死。
- 画面标定：当前先检查标定配置文件是否齐全。
- 运行状态：只保留“服务状态与操作”一个区块，集中显示服务状态、启停、重启、开机自启开关，避免重复状态栏。
- 信号机设置：可配置信号机 IP 和端口，保存后自动重启路口感知检测服务；信号机心跳检测显示在本页。
- 步进控制状态：按 1 检查步进工具状态、2 信号机连接参数、3 信号机控制状态、4 配置同步上传的顺序展示。
- 步进控制状态可读取当前步进工具参数：`GET http://127.0.0.1:8080/api/v1/tsc/config`，回填 IP、端口、账户、密码，密码在页面上按原文显示。
- 步进工具 POST/上传接口需要 Spring Security CSRF；`Box_admin` 代理请求会先访问 `/login` 取得 `_csrf` 和 `JSESSIONID`，再带 `X-CSRF-TOKEN` 转发。
- 配置同步上传里的“下载”按钮只新开 `http://<当前信号机IP>/`，由操作人员在信号机页面手动下载配置文件。
- 数据检测：以表格展示全部车道数据，支持统计最近 N 小时流量，点击刷新才读取数据。
- 数据日志：展示最近 30 分钟检测数据，按 5 秒采样绘制平滑趋势图，横轴显示开始时间 / 中间时间 / 最新时间；支持分钟级选择起止时间做查询和导出。
- 运行日志：面向现场人员汇总配置工具、配置接收、感知检测、信号机连通、智能控制等链路状态，给出问题摘要、可能原因，并可导出最近诊断日志包。
- 批量更新：每台盒子都内置主控更新页，页面位于左侧最后一项；平时不常驻重后台，只在发起任务时按需启动批量更新线程。
- 批量更新当前规则：
  - 不让客户手工选择文件。
  - 点击“开始批量更新”前会自动保存当前目标盒子表格。
  - 系统只同步白名单范围内真正发生变化的文件，也就是增量更新。
  - `Box_admin/`、相关 `scripts/`、`Traffic_detect` 恢复脚本、`preplan-control-server/` 或 `test/preplan-control-server/` 中除 `config/`、`logs/`、`__pycache__/`、`.log`、`.bak_...`、临时文件外的变更都会自动纳入。
  - 主控盒子不会在同一轮任务里更新自己。
  - 主控盒子更新别人前会尽量暂停 `traffic_detect.service` 和 `preplan-control.service`，失败时只告警，不阻断整轮任务；任务结束后再尽量恢复。

近期性能优化：

- 页面已改成按页面懒加载。
- 打开首页只加载联网设置。
- 切到绑定相机才加载相机列表。
- 切到运行状态才加载服务状态和信号机心跳。
- 切到数据检测后由按钮刷新 CSV 和日志。
- CSV 读取只 tail 最近数据，不全文件扫描。
- 日志读取只 tail 最近几百行，不全文件扫描。
- 数据日志、运行日志、批量更新都按页面懒加载，只有切到对应页面才请求接口或启动轮询。
- `open_box_admin.sh` 已增加防重复打开保护，避免桌面图标双击时连续打开多个相同页面。
- 运行状态页“运行正常 / 未运行”已恢复图标化状态块，不再只显示文字。

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
- `preplan-control.service`：智能控制服务

统一日志目录：

```bash
/home/<当前用户>/Project/box_config_tool/logs
```

现场日志打包：

```bash
bash scripts/collect_box_logs.sh
```

## 近期现场问题记录

1. 旧 `config-agent.service` 残留问题

- 现场盒子可能同时残留：
  - `config_agent.service`
  - `config-agent.service`
  - `config-agent.servicec`
- 老服务常见路径：
  - `/home/aaeon/Project/Config_agent/app.py`
- 典型现象：
  - `config_agent.service` 页面里偶尔变成未运行
  - `18080` 端口被旧进程占用
  - 新服务日志出现：

```text
ERROR: [Errno 98] error while attempting to bind on address ('0.0.0.0', 18080): address already in use
```

- 排查命令：

```bash
systemctl status config_agent.service --no-pager
systemctl cat config_agent.service
ss -ltnp | grep 18080
ps -ef | grep -E "Config_agent|config_agent" | grep -v grep
```

- 修复方向：
  - 先执行新版 `cleanup_old_box_tool.sh`
  - 重点清掉旧 `config-agent.service` / `config-agent.servicec`
  - 必要时执行：

```bash
fuser -k 18080/tcp
sudo systemctl restart config_agent.service
```

2. `config_agent` 收不到现场标定配置的排查路径

- 当前正式接收接口是：

```text
GET/POST/PUT /api/config
GET          /api/status
```

- 现场如果说“标定工具发送了，但盒子参数没变化”，优先按下面顺序排查：
  1. 请求是否真的打到 `18080`
  2. 请求路径是否是 `/api/config`
  3. 是否被 token 拦截
  4. body 是否符合当前代码结构
  5. 配置写成功后 `traffic_detect.service` 是否重启失败

- 当前代码会保存三类关键排障信息：
  - `logs/config_agent/service.log`
  - `logs/config_agent/config_agent.log`
  - `/tmp/config_agent/raw_req_*.json`

- 其中：
  - `config_agent.log` 会记录：
    - `[REQ]`
    - `[REQ][BODY]`
    - `[REQ][RESULT]`
    - `validation failed`
    - `reindex failed`
    - `transform failed`
    - `restart failed`
  - `/tmp/config_agent/raw_req_*.json` 是现场最重要的原始请求体证据

- 现场最短排查命令：

```bash
systemctl status config_agent.service --no-pager
ss -ltnp | grep 18080
tail -n 80 /home/<当前用户>/Project/box_config_tool/logs/config_agent/config_agent.log
ls -lt /tmp/config_agent | head
tail -n 80 /home/<当前用户>/Project/box_config_tool/logs/traffic_detect/service.log
journalctl -u traffic_detect.service -n 80 --no-pager
```

3. `traffic_detect` 与信号机未连通时的当前行为

- 家庭/离线环境下，`traffic_detect` 可能无法拿到 GB43229 的 `Receiver ID`。
- 现版本已加保护：
  - `receiver_id` 未准备好时，只告警并跳过本轮连接请求/上传
  - 不再因：

```text
ValueError: Sender ID and Receiver ID must be set
```

直接把主程序打崩。
- 如果现场仍出现该错误，优先确认盒子上实际运行的 `Traffic_detect/main.py` 是否为最新修复版。

4. 信控网阶段“很多时候没有检测到数据”的典型根因

- 这类现象不一定是算法没识别，现场更常见的是：
  - RTSP 视频流根本没有稳定打开
  - DeepStream 在反复拉起、超时、退出、再重拉
- `192.168.9.101` 的实测结论：
  - 时间段：`2026-04-29 18:00` 到 `2026-04-30 08:18`
  - `enP8p1s0` 在 `2026-04-29 18:13:25` 掉线，直到 `2026-04-30 08:18:05` 才重新 `link connected`
  - 4 路 source 每小时大约重拉 `245-246` 次
  - 典型日志：

```text
ERROR from source: Could not open resource for reading and writing.
Failed to connect. (Timeout while waiting for server response)
```

- `192.168.9.102` 的实测结论：
  - 时间段：`2026-04-29 20:00` 到 `2026-04-29 20:42` 左右有一小段检测输出
  - 之后开始大量出现 `PERF: 0.00`，随后同样转成 RTSP timeout / open resource failed
  - 历史输出统计里：
    - `source_2` 曾出现 `1000` 个文件全部为空
    - `source_0/1/3` 也有大量空文件，说明不是稳定检测，只是间歇性有流
- 两台盒子的共同风险：
  - 有线地址是 `172.16.16.243/24` 或 `172.16.16.244/24`
  - 相机 RTSP 地址却在 `172.16.14.0/24`
  - 如果 `172.16.16.1` 没有正确转发到 `172.16.14.0/24`，或盒子默认路由被无线网抢走，就会出现“页面在跑、服务 active、但长时间没检测数据”
- 当前建议和已落地操作：
  - 保留有线 profile：

```bash
sudo nmcli connection modify 'Wired connection 1' +ipv4.routes "172.16.14.0/24 172.16.16.1"
sudo nmcli connection up 'Wired connection 1'
```

  - 关闭无线自连，避免重启后默认走 Wi-Fi：

```bash
sudo nmcli connection modify 'ZHZX' connection.autoconnect no
```

  - 如有多个保存过的 Wi-Fi，也一起关闭：

```bash
nmcli -t -f NAME,TYPE connection show | awk -F: '$2 ~ /(wireless|wifi|802-11)/ {print $1}'
```

  - 然后逐个执行：

```bash
sudo nmcli connection modify '<wifi-name>' connection.autoconnect no
```

- 这类问题的最短排查命令：

```bash
ip -br addr
ip route
nmcli -t -f NAME,TYPE,AUTOCONNECT,DEVICE connection show
tail -n 120 /home/<当前用户>/Project/box_config_tool/logs/traffic_detect/service.log
find /home/<当前用户>/Project/box_config_tool/DeepStream-Yolo/output_kitti_data -maxdepth 2 -type f -mmin -10
```

- 如果 `service.log` 长时间刷下面几类内容，优先怀疑网络/路由，不要先怀疑检测算法：

```text
launch begin config=...
ERROR from source: Could not open resource for reading and writing.
Failed to connect. (Timeout while waiting for server response)
gst_rtspsrc_retrieve_sdp
PERF: 0.00 (0.00)
```

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
- `preplan-control.service` 为 Java 服务，在 4G 盒子上和 `traffic_detect.service` 同时自启时容易放大卡顿风险。

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
- 默认会安装 `box_admin.service`、`config_agent.service`、`traffic_detect.service`，检测到 `preplan-control.jar` 时还会安装 `preplan-control.service`。
- `install_onekey.sh` 当前默认是“现场模式”：
  - `START_TRAFFIC=1`
  - `START_PREPLAN=1`
  - `ENABLE_TRAFFIC_AUTOSTART=1`
  - `ENABLE_PREPLAN_AUTOSTART=1`
  - 也就是把整个安装包复制到新盒子后，执行 `bash scripts/install_onekey.sh`，会按固定路径安装整套系统并启动现场所需服务。
- 调试时建议使用 `START_TRAFFIC=0`，必要时再配合 `START_PREPLAN=0`，避免 4G 盒子开机直接把 DeepStream 和 Java 都拉起。
- 纯离线环境下，Chromium snap 安装失败不应中断整包安装；此时继续尝试 `offline_browser/epiphany_debs/` 里的离线 Epiphany 作为本地浏览器兜底。
- `cleanup_old_box_tool.sh` 负责停用旧同名服务、删除旧 unit，并清理 `preplan-control.service`。
- `scripts/install_preplan_control_service.sh` 已把 Java 堆默认降到 `-Xms256m -Xmx512m`，用于降低 4G 盒子压力。
- `scripts/apply_4g_low_memory_profile.sh` 可在 4G 盒子上补充低内存运行策略。
- `Traffic_detect/watchdog_main.py` 已接入 `Traffic_detect/start.sh`，用于断流恢复监测；当前阈值为：
  - 网络恢复观察期 `20s`
  - 网络恢复后无数据重启阈值 `60s`

4G 盒子资源建议：

- 4G 盒子长期同时运行 `GNOME + 本地浏览器 + 4 路 deepstream-app + preplan-control.service` 风险很高。
- 如现场主要是先配置、后联调，建议默认只自启：
  - `box_admin.service`
  - `config_agent.service`
- 现场确认网络、相机和信号机参数后，再手动启动：
  - `preplan-control.service`
  - `traffic_detect.service`
- 如出现“进桌面立刻卡死”，优先怀疑重服务自启过多，而不是先怀疑页面本身。

每日重启：

- `scripts/install_daily_reboot_timer.sh` 安装每天 `03:30` 自动重启。
- 如果排查黑屏、服务异常或内存问题，先检查 timer 是否真的启用。
- Chromium 离线安装脚本默认查找 `offline_browser/snaps/*.snap`；如果目录不存在或未准备好，则 `install_onekey.sh` 只跳过浏览器安装，不中断其余服务安装。

无线网自连：

- 内网交付盒子如同时连接信控有线网和无线网，可能造成网络边界风险。
- 如现场希望无线网只手动连接，使用：

```bash
nmcli -t -f NAME,TYPE,AUTOCONNECT,DEVICE connection show
sudo nmcli connection modify '<wifi-connection-name>' connection.autoconnect no
```

- 该操作不会立即断开当前 Wi-Fi，但重启后不会自动连接该无线配置。
- 最近已实际关闭的配置：
  - `192.168.9.101`：`ZHZX`
  - `192.168.9.102`：`ZHZX`、`rzyyz的nova 10`
- 关闭 Wi-Fi 自连后，仍建议检查默认路由是否落在有线信控网，而不是只看 `connection.autoconnect`：

```bash
ip route
ip -br addr
```

- 如果相机在 `172.16.14.0/24`，而盒子有线地址在 `172.16.16.0/24`，还需要补静态路由：

```bash
sudo nmcli connection modify 'Wired connection 1' +ipv4.routes "172.16.14.0/24 172.16.16.1"
sudo nmcli connection up 'Wired connection 1'
```

常用命令：

```bash
systemctl status box_admin.service --no-pager
systemctl status config_agent.service --no-pager
systemctl status traffic_detect.service --no-pager
journalctl -u config_agent.service -n 80 --no-pager
journalctl -u traffic_detect.service -n 80 --no-pager
systemctl list-timers --all | grep -E 'reboot|box'
```

旧同名服务残留注意：

- 现场盒子可能遗留旧工程路径，例如：
  - `/home/aaeon/Project/Config_agent`
  - `/home/aaeon/Project/Traffic_detect`
- 也可能遗留旧 unit：
  - `config-agent.service`
  - `config-agent.servicec`
- 旧 `config-agent.service` 常见风险是继续占用 `18080`，导致新的 `config_agent.service` 报：

```text
ERROR: [Errno 98] ... ('0.0.0.0', 18080): address already in use
```

- 交付前如果发现 `config_agent.service` 反复重启，先检查是否有旧进程或旧 unit 抢端口，不要先怀疑 FastAPI 代码本身。

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
- 如果现场问题需要排障，优先引导用户执行 `scripts/collect_box_logs.sh`，再基于日志包分析，不要让用户手工逐个截图。

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
node --check Box_admin/static/app.js
```

## 远程盒子验证

页面验证：

```bash
curl http://127.0.0.1:8090/api/status
curl http://127.0.0.1:8090/api/runtime-summary
curl "http://127.0.0.1:8090/api/data-summary?hours=1"
curl http://127.0.0.1:8090/api/step-tool/tsc-config
```

资源排查：

```bash
free -h
uptime
ps -eo pid,user,comm,rss,args --sort=-rss | head -40
ss -ltnp | grep -E '8090|8080|18080'
ip -br addr
ip route
nmcli -t -f NAME,TYPE,AUTOCONNECT,DEVICE connection show
```

常见内存占用判断：

- 多个 `deepstream-app` 是主要重负载。
- Chromium 会占用数百 MB。
- `epiphany-browser` 和 WebKit 进程也会额外吃内存，但通常比 Chromium snap 更稳。
- `box_admin.service` 和 `config_agent.service` 通常较轻。
- `preplan-control.service` 作为 Java 服务常见会占用数百 MB。
- Linux `buff/cache` 不等于泄漏，应重点看 `available`、swap 和具体进程 RSS。

## 安装包约定

最终交付用的安装包目录至少应包含：

- `Box_admin/`
- `Config_agent/`
- `Traffic_detect/`
- `DeepStream-Yolo/`
- `preplan-control-server/` 或 `test/preplan-control-server/`
- `scripts/`
- `python_wheels/`
- `python_wheels/` 交付时必须包含批量更新所需离线依赖 wheel：
  - `paramiko`
  - `bcrypt`
  - `cryptography`
  - `PyNaCl`
- `offline_browser/browser_snaps_export/`
- `offline_browser/epiphany_debs/`
- `cleanup_old_box_tool.sh`
- `Miniforge3-Linux-aarch64.sh`
- `python_requirements_offline.txt`

`python_requirements_offline.txt` 交付前必须至少包含：

- `flask`
- `flask-cors`
- `fastapi`
- `uvicorn`
- `paramiko`
- `bcrypt`
- `cryptography`
- `PyNaCl`

当前安装包交付目标：

- 将整个安装包目录复制到新盒子。
- 在盒子上执行：

```bash
chmod +x scripts/install_onekey.sh
bash scripts/install_onekey.sh
```

- 即可按固定部署路径 `/home/<当前用户>/Project/box_config_tool` 一键安装整套系统。
- 若离线资源已准备完整，安装过程不依赖外网。

`Traffic_detect/` 交付前必须确认至少包含：

- `main.py`
- `start.sh`
- `runtime.env`

历史上出现过安装包里 `Traffic_detect/main.py` 丢失，导致：

```text
python: can't open file '.../Traffic_detect/main.py': [Errno 2] No such file or directory
```

遇到这种报错优先检查安装包是否残缺，不要先怀疑 DeepStream 或网络。

## 安全注意

- 该目录可能包含现场 IP、RTSP、账号密码，外发前必须脱敏。
- Windows 本地路径和盒子 Linux 路径要分清。
- 修改 DeepStream 配置时，最终运行路径必须是盒子上的 Linux 绝对路径。
- 不要把运行产物当源码修复目标。
- 不要执行破坏性 Git 或文件命令，除非用户明确要求。
