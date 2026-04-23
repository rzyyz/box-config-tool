# Windows 到内网盒子离线部署指南

本文档用于把 Windows 上的完整工程打包，部署到只预装了 DeepStream、CUDA/TensorRT 的内网盒子上，实现“一包拷贝 + 一个 sh 一键安装启动”。

## 1. 部署目标

盒子最终运行目录：

```bash
~/Project/box_config_tool
```

如果登录用户是 `nvidia`，实际路径通常是：

```bash
/home/nvidia/Project/box_config_tool
```

如果登录用户不是 `nvidia`，一键脚本会默认使用当前用户，并部署到：

```bash
/home/<当前用户>/Project/box_config_tool
```

## 2. 盒子前置条件

盒子需要已经具备：

- Linux aarch64 系统。
- DeepStream 已安装，`deepstream-app` 可用。
- CUDA/TensorRT 已安装。
- 可使用当前账户执行 `sudo`。
- 工程运行所需模型、DeepStream 配置和检测配置已包含在工程包内。

建议在盒子上先检查：

```bash
uname -m
which deepstream-app
deepstream-app --version-all
sudo -v
```

## 3. Windows 工程包应包含

完整交付包至少应包含：

```text
Box_admin/
Config_agent/
Traffic_detect/
DeepStream-Yolo/
scripts/
README.md
AGENTS.md
python_requirements_offline.txt
python_wheels/
Miniforge3-Linux-aarch64.sh
```

说明：

- `Miniforge3-Linux-aarch64.sh` 放在工程根目录。
- `python_wheels/` 放离线 Python 依赖包。
- `DeepStream-Yolo/` 需要包含模型、配置、解析库等运行文件。
- 不要把 `.git/`、`release/`、日志、CSV、运行输出打进正式包。

## 4. Windows 上制作离线包

在 PowerShell 中执行。根据你的实际路径修改 `$src`：

```powershell
$src = "F:\2026-边缘计算盒子\Project\盒子内置配置工具"
$pkgRoot = Join-Path $src "release\offline_package"
$stage = Join-Path $pkgRoot "box_config_tool"
$out = Join-Path $src "release\box_config_tool_offline.tar.gz"

Remove-Item $pkgRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $pkgRoot | Out-Null

robocopy $src $stage /E `
  /XD .git release __pycache__ .pytest_cache .mypy_cache .ruff_cache `
  /XD "DeepStream-Yolo\output_kitti_data" "DeepStream-Yolo\generated_runtime" `
  /XD "Traffic_detect\log" "Traffic_detect\logs" "Traffic_detect\queue_csv" `
  /XF *.log *.jsonl *.tar *.tar.gz *.zip

if ($LASTEXITCODE -ge 8) {
  throw "robocopy failed with exit code $LASTEXITCODE"
}

tar -czf $out -C $pkgRoot box_config_tool
Write-Host "Package created: $out"
```

打包后检查：

```powershell
tar -tzf .\release\box_config_tool_offline.tar.gz | Select-String "scripts/install_onekey.sh|Miniforge3-Linux-aarch64.sh|python_wheels|DeepStream-Yolo"
```

## 5. 拷贝到内网盒子

### 方式 A：网络可达时用 scp

```powershell
scp .\release\box_config_tool_offline.tar.gz <盒子用户>@<盒子IP>:/home/<盒子用户>/
```

示例：

```powershell
scp .\release\box_config_tool_offline.tar.gz nvidia@192.168.9.125:/home/nvidia/
```

### 方式 B：完全内网或不通网络时用 U 盘

把 `box_config_tool_offline.tar.gz` 拷贝到 U 盘，然后在盒子上复制到当前用户家目录，例如：

```bash
cp /media/$USER/<U盘名>/box_config_tool_offline.tar.gz ~/
```

## 6. 盒子上一键安装

进入盒子后执行：

```bash
cd ~
tar -xzf box_config_tool_offline.tar.gz
cd ~/box_config_tool
chmod +x scripts/install_onekey.sh
bash scripts/install_onekey.sh
```

脚本会自动：

- 复制工程到 `~/Project/box_config_tool`。
- 安装或复用 `~/miniforge3`。
- 创建或复用 conda 环境。
- 从 `python_wheels/` 离线安装 Flask、FastAPI、Uvicorn 等依赖。
- 安装 `box_admin.service`、`config_agent.service`、`traffic_detect.service`。
- 写入最小 sudoers，让页面可以执行服务启停和网卡配置。
- 设置服务开机自启。
- 启动服务。
- 如桌面存在 `~/Desktop`，安装“盒子配置工具”快捷方式。

如果首次部署还没有确认相机和信号机配置，建议先不启动重服务：

```bash
START_TRAFFIC=0 bash scripts/install_onekey.sh
```

之后配置确认完成，再启动：

```bash
sudo systemctl restart traffic_detect.service
```

## 7. 常用安装选项

不启用开机自启：

```bash
ENABLE_AUTOSTART=0 bash scripts/install_onekey.sh
```

指定服务用户和部署路径：

```bash
SERVICE_USER=box TARGET_PROJECT_ROOT=/home/box/Project/box_config_tool bash scripts/install_onekey.sh
```

指定离线 wheel 目录：

```bash
PIP_WHEEL_DIR=/home/nvidia/offline_wheels bash scripts/install_onekey.sh
```

安装每天 03:30 自动重启：

```bash
INSTALL_DAILY_REBOOT=1 bash scripts/install_onekey.sh
```

只在当前目录安装，不复制到 `~/Project/box_config_tool`：

```bash
AUTO_INSTALL_TO_TARGET=0 bash scripts/install_onekey.sh
```

## 8. 安装后验证

检查服务：

```bash
systemctl status box_admin.service --no-pager
systemctl status config_agent.service --no-pager
systemctl status traffic_detect.service --no-pager
```

检查页面接口：

```bash
curl http://127.0.0.1:8090/api/status
curl http://127.0.0.1:8090/api/runtime-summary
curl http://127.0.0.1:8090/api/camera-bindings
```

浏览器访问：

```text
http://127.0.0.1:8090
http://<盒子IP>:8090
```

如果有步进工具并运行在本机 `8080`：

```bash
curl http://127.0.0.1:8090/api/step-tool/status
curl http://127.0.0.1:8090/api/step-tool/tsc-config
```

## 9. 无线网自动连接关闭

如果盒子同时连接信控有线网和无线网，为避免网络边界风险，建议关闭 Wi-Fi 开机自动连接，只保留手动连接。

查看连接：

```bash
nmcli -t -f NAME,TYPE,AUTOCONNECT,DEVICE connection show
```

关闭某个 Wi-Fi 配置的自动连接：

```bash
sudo nmcli connection modify '<wifi连接名>' connection.autoconnect no
```

示例：

```bash
sudo nmcli connection modify 'ZHZX' connection.autoconnect no
```

验证：

```bash
nmcli -t -f NAME,TYPE,AUTOCONNECT,DEVICE connection show
```

该操作不会立即断开当前 Wi-Fi，但重启后不会自动连接。

## 10. 常见问题

### 账户不是 nvidia 会失败吗

不会。`install_onekey.sh` 默认使用当前登录用户作为服务运行用户，并部署到当前用户的：

```bash
~/Project/box_config_tool
```

如果要固定用户或路径，用：

```bash
SERVICE_USER=<用户> TARGET_PROJECT_ROOT=/home/<用户>/Project/box_config_tool bash scripts/install_onekey.sh
```

### 安装是否需要盒子账户密码

需要。安装 systemd 服务、sudoers、开机自启时需要 `sudo` 权限，所以安装阶段需要输入当前账户密码。

安装完成后，页面执行服务启停、网卡配置会走脚本写入的最小 sudoers，不需要在页面输入系统密码。

### 后续账户密码变了怎么办

服务本身不依赖账户密码，systemd 使用的是用户名和路径。账户密码变化通常不影响已安装服务。

如果用户名、家目录或部署路径变了，需要重新运行：

```bash
SERVICE_USER=<新用户> TARGET_PROJECT_ROOT=/home/<新用户>/Project/box_config_tool bash scripts/install_onekey.sh
```

### Python 离线依赖安装失败

检查：

```bash
ls python_wheels
cat python_requirements_offline.txt
```

手工测试：

```bash
source ~/miniforge3/etc/profile.d/conda.sh
conda activate yolo11_py310 || conda activate base
python -m pip install --no-index --find-links ./python_wheels -r python_requirements_offline.txt
python - <<'PY'
import flask, fastapi, uvicorn, flask_cors
print("python deps ok")
PY
```

### 页面打不开

检查：

```bash
systemctl status box_admin.service --no-pager
journalctl -u box_admin.service -n 80 --no-pager
ss -ltnp | grep 8090
```

### 感知服务启动失败

检查：

```bash
systemctl status traffic_detect.service --no-pager
journalctl -u traffic_detect.service -n 120 --no-pager
which deepstream-app
```

常见原因：

- DeepStream 未安装或环境变量不完整。
- RTSP 地址、账号、密码、端口、路径错误。
- 模型或解析库缺失。
- 首次 TensorRT engine 生成需要较长时间。

### 步进工具接口失败

配置工具默认代理本机：

```text
http://127.0.0.1:8080
```

检查：

```bash
curl http://127.0.0.1:8080/api/v1/status
curl http://127.0.0.1:8090/api/step-tool/status
```

步进工具 POST/上传接口如果启用了 CSRF，配置工具会自动获取 `/login` 的 `_csrf` 后再转发。

## 11. 交付前检查清单

- `Miniforge3-Linux-aarch64.sh` 已放在工程根目录。
- `python_wheels/` 已放在工程根目录。
- `python_requirements_offline.txt` 存在。
- `DeepStream-Yolo/` 包含模型、配置和解析库。
- `Traffic_detect/config/` 包含现场标定配置。
- 没有把无关日志、CSV、运行输出打进交付包。
- 内网盒子不需要自动连 Wi-Fi 时，已执行 `connection.autoconnect no`。
- `box_admin.service`、`config_agent.service`、`traffic_detect.service` 状态符合预期。
