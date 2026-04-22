# Box_admin

盒子本地配置工具，默认监听 `8090`。当前版本用于把“车辆感知与标定工具”的常用现场配置集中到一个销售也能看懂的页面里。

当前已包含：

- 盒子联网设置：选择网卡，查看当前 IP / 网关 / DNS，填写网口备注，应用静态网络配置。
- 绑定相机：填写相机 IP、端口、账号、密码、路径，自动生成 RTSP，也允许手工修改 RTSP。
- 画面标定：检查车道线、区域、排队区等标定文件是否存在。
- 运行状态：以中文名称查看路口感知检测、检测线数据接收、配置工具服务状态，并支持启动、停止、重启、开启/关闭重启后自动启动。
- 信号机配置：修改信号机 IP / 端口，保存后写入 `Traffic_detect/runtime.env`，并可重启感知服务生效。

## 默认访问地址

- 本机显示器接盒子时：`http://127.0.0.1:8090`
- 局域网访问时：`http://<盒子IP>:8090`

## 目录部署建议

新开发板和离线盒子都统一部署到：

```bash
/home/nvidia/Project/box_config_tool
```

后续每台离线盒子都按这个目录部署，更新时直接覆盖该目录下的 `Box_admin`、`Config_agent`、`Traffic_detect`、`DeepStream-Yolo` 和 `scripts` 即可。若现场用户名不是 `nvidia`，需要同步修改 service 示例文件里的 `User=`。

## 启动

```bash
cd /home/nvidia/Project/box_config_tool/Box_admin
python app.py
```

或者：

```bash
bash start.sh
```

## 桌面图标

如果希望销售在盒子桌面直接双击打开配置工具，部署后执行：

```bash
chmod +x /home/nvidia/Project/box_config_tool/Box_admin/start.sh
chmod +x /home/nvidia/Project/box_config_tool/Box_admin/open_box_admin.sh
cp /home/nvidia/Project/box_config_tool/Box_admin/box_admin.desktop /home/nvidia/Desktop/
chmod +x /home/nvidia/Desktop/box_admin.desktop
gio set /home/nvidia/Desktop/box_admin.desktop metadata::trusted true
```

完成后，桌面会出现“盒子配置工具”图标。

双击图标时会：

- 优先检查 `8090` 服务是否已经可访问
- 如果系统里已安装 `box_admin.service`，尝试先启动服务
- 如果服务不存在，再直接拉起 `start.sh`
- 自动在浏览器打开 `http://127.0.0.1:8090`

如果桌面环境没有立即显示图标为可执行应用，注销后重新登录一次桌面即可。

## 权限说明

网络修改和服务启停需要管理员权限。

如果 `Box_admin` 不是以 `root` 运行，需要为运行用户配置最小免密码 sudo，至少允许：

- `nmcli`
- `systemctl start/stop/restart/enable/disable traffic_detect.service`
- `systemctl start/stop/restart/enable/disable config_agent.service`
- `systemctl start/stop/restart/enable/disable box_admin.service`

## 新板安全约定

开发板调试阶段默认禁止开机自启，避免 `traffic_detect.service` 开机自动拉起 DeepStream 导致桌面黑屏或卡死。页面里的“重启后自动启动”开关只应在现场配置、相机、信号机都确认正常后再打开。

服务文件示例：

- `box_admin.service.example`
- `../Config_agent/config_agent.service.example`
- `../Traffic_detect/traffic_detect.service.example`

这些示例支持 `systemctl enable/disable`。安装脚本会在安装后立即执行 `disable`，因此默认仍然不会开机自启。

需要安装手动服务时，在工程根目录执行：

```bash
bash scripts/install_manual_services.sh
```

如果是最终交付盒子，需要每天凌晨 `03:30` 自动重启来降低长时间运行后的内存卡死风险，执行：

```bash
bash scripts/install_daily_reboot_timer.sh
```

检查下一次重启时间：

```bash
systemctl list-timers box_daily_reboot.timer
```

只启动前端时，优先使用：

```bash
bash scripts/safe_start_box_admin.sh
```

## 可调环境变量

- `BOX_ADMIN_PORT`：默认 `8090`
- `BOX_ADMIN_HOST`：默认 `0.0.0.0`
- `BOX_ADMIN_INTERFACE`：固定网卡名时可设置，例如 `eth0`
- `BOX_ADMIN_DEEPSTREAM_CONFIG`：DeepStream 配置文件路径
- `BOX_ADMIN_SERVICES`：默认 `traffic_detect.service,config_agent.service,box_admin.service`
- `BOX_ADMIN_LOG_PATH`：默认 `/tmp/box_admin.log`
