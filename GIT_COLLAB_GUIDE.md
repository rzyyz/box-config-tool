# Git 协作提交范围说明

这份说明用于多人协作开发 `Box_admin` 新页面。当前协作目标是：页面开发人员只补充页面和各自程序所需接口，不需要接触感知主程序、DeepStream、标注工具接收服务或现场配置。

## 推荐 Git 仓库内容

建议上传这些文件和目录：

```text
README.md
GIT_COLLAB_GUIDE.md
NEW_BOARD_SAFE_GUIDE.md
.gitignore
Box_admin/
scripts/
```

其中 `Box_admin/` 是核心源码：

```text
Box_admin/
├── app.py
├── templates/
│   └── index.html
├── static/
│   ├── app.css
│   └── app.js
├── start.sh
├── open_box_admin.sh
├── box_admin.desktop
├── box_admin.service.example
├── README.md
└── FRONTEND_COLLAB_GUIDE.md
```

`scripts/` 可以保留，因为里面是服务安装、自启关闭、每日重启 timer 等部署辅助脚本，不包含感知业务源码。

## 不建议上传的内容

不要上传这些目录：

```text
Traffic_detect/
DeepStream-Yolo/
Config_agent/
release/
```

原因：

- `Traffic_detect/` 是路口感知检测主程序，不是页面开发人员当前工作范围。
- `DeepStream-Yolo/` 可能包含 RTSP、模型、engine、推理配置和现场路径。
- `Config_agent/` 是外部标定/配置工具接收服务。如果只做页面和各自程序接口，不需要它。
- `release/`、压缩包、离线包属于交付产物，不适合放源码仓库。

也不要上传这些运行产物或敏感文件：

```text
__pycache__/
*.pyc
*.log
queue_csv/
output/
outputs/
runtime.env
*.engine
*.onnx
*.pt
*.zip
*.tar.gz
```

## 新增页面时主要改哪里

页面开发人员通常只需要改这三个文件：

```text
Box_admin/templates/index.html
Box_admin/static/app.css
Box_admin/static/app.js
```

如果需要给各自程序做接口，可以在 `Box_admin/app.py` 里新增 `/api/...` 路由；接口只负责和对应程序通信，不要引用 `Traffic_detect` 或 `Config_agent` 的源码。

## 新增页面约定

在 `Box_admin/templates/index.html` 新增一个 `section.page-panel`：

```html
<section class="page-panel" data-page-key="partner-page" data-page-title="协作功能页">
  <div class="section-head">
    <h2>协作功能页</h2>
    <p>这里写给销售或现场人员看的说明。</p>
  </div>

  <article class="card">
    <div id="partnerPageRoot"></div>
  </article>
</section>
```

左侧菜单会自动出现，不需要单独改导航。

## 建议分支流程

```bash
git checkout -b feature/partner-page
```

开发完成后提交：

```bash
git add Box_admin/templates/index.html Box_admin/static/app.css Box_admin/static/app.js Box_admin/app.py
git commit -m "feat: add partner configuration page"
```

再通过 Pull Request 或直接合并到主分支。

## 初始化仓库示例

在 `Project/盒子内置配置工具` 目录执行：

```bash
git init
git add README.md GIT_COLLAB_GUIDE.md NEW_BOARD_SAFE_GUIDE.md .gitignore Box_admin scripts
git status
git commit -m "init box admin frontend collaboration source"
```

确认 `git status` 里没有出现以下目录：

```text
Traffic_detect/
DeepStream-Yolo/
Config_agent/
release/
```

如果出现，说明 `.gitignore` 没生效或之前已经 add 过，需要先取消暂存：

```bash
git restore --staged Traffic_detect DeepStream-Yolo Config_agent release
```

## 本地运行提醒

`Box_admin` 最适合在 Ubuntu/Jetson 上运行。没有 `nmcli`、`systemctl`、`ip` 的 Windows 环境也能打开基础页面，但涉及网卡、服务启停、Ping/TCP 检查的功能需要在盒子或 Linux 环境里验证。

启动：

```bash
cd Box_admin
bash start.sh
```

访问：

```text
http://127.0.0.1:8090
```

## 安全提醒

提交前检查是否有现场敏感信息：

```bash
git grep -n "rtsp://\\|password\\|Htgx\\|GB_TSC\\|192\\.168\\|172\\.16"
```

如果只是 placeholder 示例可以保留；如果是真实现场账号、密码、RTSP、客户内网 IP，必须删除或脱敏。
