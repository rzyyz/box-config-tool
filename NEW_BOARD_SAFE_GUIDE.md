# 新开发板安全开发说明

这份工程用于在新开发板上继续开发盒子内置配置工具。为了避免再次出现开机黑屏，默认策略是：

- 不开机自启 `traffic_detect.service`
- 不开机自启 `box_admin.service`
- 所有服务只允许手动启动
- 启动 `traffic_detect.service` 前，先确认相机网段、RTSP、信号机 IP 都配置正确

## 推荐目录

推荐直接将本目录复制到新开发板，例如：

```bash
/home/nvidia/Project/box_config_tool
```

固定目录内包含以下核心目录：

```bash
/home/nvidia/Project/box_config_tool/Box_admin
/home/nvidia/Project/box_config_tool/Config_agent
/home/nvidia/Project/box_config_tool/Traffic_detect
/home/nvidia/Project/box_config_tool/DeepStream-Yolo
```

`scripts/install_manual_services.sh` 会自动按当前目录生成 service 路径。如果新板用户名不是 `nvidia`，脚本也会默认使用当前登录用户。

如果你临时放在其他目录，安装服务时显式指定根目录：

```bash
PROJECT_ROOT=/actual/project/root bash scripts/install_manual_services.sh
```

## 第一件事：关闭所有开机自启

复制工程后，先执行：

```bash
cd /home/nvidia/Project/box_config_tool
chmod +x scripts/*.sh Box_admin/*.sh Config_agent/*.sh Traffic_detect/start.sh
bash scripts/disable_all_autostart.sh
```

如果你只复制了三个核心目录，也可以手工执行：

```bash
sudo systemctl stop traffic_detect.service config_agent.service box_admin.service || true
sudo systemctl disable traffic_detect.service config_agent.service box_admin.service || true
sudo pkill -f '[d]eepstream-app' || true
sudo systemctl daemon-reload
```

## 安装手动服务

服务文件可以安装，但不要 enable：

```bash
cd /home/nvidia/Project/box_config_tool
chmod +x scripts/*.sh Box_admin/*.sh Config_agent/*.sh Traffic_detect/start.sh
bash scripts/install_manual_services.sh
```

脚本会把 service 文件里的用户和路径改成当前开发板的实际值，并且安装后立即执行 `disable`，确保不开机自启。

配置工具页面里有“重启后自动启动”开关。调试阶段保持关闭；只有确认相机 RTSP、网卡路由、信号机 IP/端口都正常后，才建议开启。

最终交付盒子如需每天凌晨 `03:30` 自动重启，执行：

```bash
bash scripts/install_daily_reboot_timer.sh
systemctl list-timers box_daily_reboot.timer
```

开发板调试时不建议开启。若需要一键关闭所有项目自启与定时重启，执行 `bash scripts/disable_all_autostart.sh`。

安装后只能手动启动：

```bash
sudo systemctl start box_admin.service
sudo systemctl start config_agent.service
sudo systemctl start traffic_detect.service
```

检查是否没有开机自启：

```bash
systemctl is-enabled box_admin.service || true
systemctl is-enabled config_agent.service || true
systemctl is-enabled traffic_detect.service || true
```

期望输出是：

```text
disabled
disabled
```

## 安全启动顺序

1. 先只启动前端配置工具：

```bash
cd /home/nvidia/Project/box_config_tool/Box_admin
bash start.sh
```

2. 浏览器访问：

```text
http://127.0.0.1:8090
```

3. 在前端里配置：

- 网卡 IP / 网关 / DNS
- 相机 RTSP
- 信号机 IP / 端口

4. 确认相机和信号机连通后，再手动启动感知服务：

```bash
sudo systemctl start traffic_detect.service
```

5. 如果桌面卡顿或黑屏风险升高，立即停止：

```bash
sudo systemctl stop traffic_detect.service
sudo pkill -f '[d]eepstream-app'
```

## 当前工程状态

- `Box_admin`：前端配置工具，包含联网设置、相机绑定、标定文件检查、运行状态、信号机 IP/端口配置。
- `Config_agent`：外部标定/配置工具调用的 API 服务，写入感知配置和 DeepStream RTSP，并在成功后重启感知服务。
- `Traffic_detect`：车辆感知与 GB/T 43229 上传主程序，启动时读取 `runtime.env` 中的信号机配置。
- `DeepStream-Yolo`：车辆检测 DeepStream 工程，包含当前模型、engine、配置模板。

## 禁止事项

新开发板调试阶段不要执行：

```bash
sudo systemctl enable traffic_detect.service
sudo systemctl enable config_agent.service
sudo systemctl enable box_admin.service
sudo systemctl enable --now traffic_detect.service
```

如确需开机自启，必须先完成无显示/低资源模式验证。

## 黑屏盒子找回 IP

如果有问题的盒子接入当前网络后会自动获取 `192.168.x.x` 地址，可以在同一局域网内低频查找。这个过程只用于自己的设备，不建议做隐藏扫描或高频扫网，避免影响别的设备。

1. 先确认电脑自己的网段：

```bash
ip -4 addr
ip route
```

假设电脑在 `192.168.9.x/24`，优先只扫这个小网段。

2. 先看 ARP 邻居表，通常最安全：

```bash
ip neigh show | grep -E '192\.168\.9\.'
```

3. 如果没有发现，再做低频 ping 扫描：

```bash
for i in $(seq 1 254); do
  ping -c 1 -W 1 192.168.9.$i >/dev/null 2>&1 && echo 192.168.9.$i
done
```

4. 对疑似 IP 只尝试 SSH 端口，不扫全端口：

```bash
nc -vz -w 2 192.168.9.139 22
ssh nvidia@192.168.9.139
```

注意账号通常是 `nvidia`，不是 `nivida`。如果连上后第一件事是禁用自启：

```bash
sudo systemctl stop traffic_detect.service config_agent.service box_admin.service || true
sudo systemctl disable traffic_detect.service config_agent.service box_admin.service || true
sudo pkill -f '[d]eepstream-app' || true
sudo systemctl daemon-reload
```
