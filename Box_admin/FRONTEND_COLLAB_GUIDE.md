# Box_admin 前端协作开发规范

## 1. 当前工程结构

`Box_admin` 当前采用 `Flask + templates + static` 结构，不再把整页 HTML 内嵌在 `app.py` 里。

- `app.py`
  - Flask 入口
  - API 路由
  - 页面入口 `/`
- `templates/index.html`
  - 主页面骨架
  - 所有分页 `section`
- `static/app.css`
  - 全局样式
  - 页面通用布局和组件样式
- `static/app.js`
  - 页面初始化
  - 分页切换
  - 各页面数据加载和事件绑定
- `open_box_admin.sh`
  - 桌面图标打开页面
- `start.sh`
  - 启动 Flask 服务

## 2. 当前已实现页面

- `联网设置`
  - 读取网卡
  - 展示当前 IP / 网关 / DNS
  - 应用网络配置
- `绑定相机`
  - 读取 DeepStream source
  - 展示相机名 / 启用状态 / 相机 IP / RTSP
  - 保存相机绑定
  - 检查相机连通性
- `画面标定`
  - 先展示标定配置文件状态
  - 作为后续真正标定页面入口
- `运行状态`
  - 展示服务状态
  - 支持服务启动、暂停、重启
  - 支持服务重启后自动启动开关
  - 展示信号机心跳摘要
- `信号机设置`
  - 配置信号机 IP / 端口
  - 支持立即 Ping / TCP 检查
  - 保存后自动重启路口感知检测服务
- `数据检测`
  - 展示全部车道的 flow / headway / queue 文件摘要
  - 展示近期异常日志

说明：步进功能页当前明确先不做。

## 3. 分页机制约定

侧边栏导航不是手写死的，而是由页面区块自动生成。

新增一页时，只需要在 `templates/index.html` 新增一个 `section`：

```html
<section class="page-panel" data-page-key="new-feature" data-page-title="新功能页">
  ...
</section>
```

约定：

- `class` 必须包含 `page-panel`
- `data-page-key`
  - 页面唯一标识
  - 只能用英文小写、短横线或简短单词
- `data-page-title`
  - 侧边栏显示名称

这样 `static/app.js` 里的 `buildNavigation()` 会自动把它加入左侧菜单。

## 4. 新增页面的最小步骤

前端同事新增页面时，按下面顺序做：

1. 在 `templates/index.html` 添加新的 `section.page-panel`
2. 在 `static/app.css` 补该页需要的样式
3. 在 `static/app.js` 新增：
   - 页面渲染函数
   - 页面数据加载函数
   - 页面事件绑定函数
4. 如果需要后端支持，再到 `app.py` 增加对应 API

推荐模式：

- `renderXxx(...)`
  - 只负责渲染 DOM
- `loadXxx(...)`
  - 只负责请求接口并调用渲染
- `bindXxxActions(...)`
  - 只负责按钮点击、表单提交等交互

不要把三类逻辑揉在一个超长函数里。

## 5. API 约定

当前统一使用 JSON 接口。

成功返回格式：

```json
{
  "ok": true,
  ...
}
```

失败返回格式：

```json
{
  "ok": false,
  "message": "错误原因"
}
```

前端统一通过 `fetchJson()` 调接口。

约定：

- 查询类接口优先用 `GET`
- 保存、重启、检查等动作优先用 `POST`
- 返回字段尽量稳定，不要频繁改字段名
- 如果后端字段需要调整，先同步前端同事

## 6. DOM 与命名规范

命名统一采用可读英文。

推荐：

- 页面 key：`camera`、`runtime`、`calibration`
- DOM id：`cameraTableBody`、`runtimeSummary`
- JS 函数：`renderCameraBindings`、`loadRuntimeSummary`
- API 路径：`/api/camera-bindings`、`/api/runtime-summary`

避免：

- `data1`
- `temp`
- `testBtn2`
- 一个页面里出现大量中文拼音缩写变量

## 7. 样式约定

当前 UI 采用统一暗色运维台风格，后续扩展页面时保持一致。

约定：

- 优先复用已有类：
  - `card`
  - `card-grid`
  - `field`
  - `actions`
  - `data-table`
  - `summary-item`
  - `status-card`
  - `metric-item`
- 新样式尽量写到 `app.css`
- 不要在 HTML 里堆大量内联样式
- 如果要新增通用组件样式，优先抽成公共 class

## 8. 后端开发边界

`app.py` 当前已经承担：

- 页面入口
- 网络配置
- DeepStream source 管理
- 相机绑定管理
- 标定文件状态读取
- 运行状态摘要

新增功能时建议遵循：

- 与盒子运维直接相关的接口，继续放在 `app.py`
- 如果某个模块开始明显变大，再拆成单独模块文件

拆分时推荐：

- `services/network.py`
- `services/camera.py`
- `services/runtime.py`

当前阶段不强制拆，但新增功能超过 150 行时，优先考虑拆模块。

## 9. 前后端协作边界

建议分工：

- 你这边负责：
  - 需求梳理
  - Flask API
  - 盒子命令执行
  - 服务部署
  - Linux 路径和盒子联调
- 前端同事负责：
  - 新分页结构
  - 页面布局
  - 表单交互
  - 表格、状态卡片、错误提示等体验层

协作原则：

- 前端不要直接假设 Linux 命令细节
- 后端不要频繁改已有接口字段
- 每新增一页，先确定：
  - 页面 key
  - API 路径
  - 返回 JSON 结构

## 10. 建议新增页面方式

后面如果要加新页，建议按下面模板：

```html
<section class="page-panel" data-page-key="example" data-page-title="示例页面">
  <div class="section-head">
    <h2>示例页面</h2>
    <p>这里写这一页做什么。</p>
  </div>
  <article class="card">
    <div id="exampleRoot"></div>
    <div class="actions">
      <button id="refreshExampleBtn" class="btn secondary">刷新</button>
      <button id="saveExampleBtn" class="btn primary">保存</button>
    </div>
  </article>
</section>
```

JS 推荐同步补：

```js
function renderExample(data) {}
async function loadExample() {}
function bindExampleActions() {}
```

## 11. 当前已知限制

- 步进功能页还没接
- 标定页当前只是入口和状态展示，还不是 Web 标定器
- `数据检测` 页当前读取的是最新 csv 和日志摘要，不是实时流式推送
- 现在服务运行在 Flask development server，后面如需正式交付，可再换成 `gunicorn` 或 systemd 下更稳的启动方式

## 12. 当前无线网盒子验证结论

无线网盒子 `192.168.9.139` 上当前已验证：

- `box_admin.service` 已运行
- `http://127.0.0.1:8090` 返回 `200 OK`
- `http://192.168.9.139:8090` 可作为局域网访问地址
- 浏览器优先兼容：
  - `google-chrome`
  - `google-chrome-stable`
  - `chromium-browser`
  - `chromium`
  - `/snap/bin/chromium`
  - `epiphany-browser`

如果桌面图标偶发打不开，优先手工访问：

```text
http://127.0.0.1:8090
```

或从局域网机器访问：

```text
http://192.168.9.139:8090
```
