const toast = document.getElementById("toast");
const panels = Array.from(document.querySelectorAll(".page-panel"));
const navRoot = document.getElementById("sidebarNav");
const htmlCache = new Map();
const loadedPages = new Set();
let activePageKey = panels.find((panel) => panel.classList.contains("active"))?.dataset.pageKey || "network";
const CTRL_MODE_LABELS = {
  0: "本地时段控制",
  1: "关灯控制",
  2: "黄闪控制",
  3: "全红控制",
  4: "定周期控制",
  5: "协调绿波控制",
  6: "协议红波控制",
  7: "全感应控制",
  8: "半感应控制",
  9: "协调绿波全感应控制",
  10: "步进控制",
  12: "行人过街控制",
  13: "单点自适应控制",
  14: "静态干线控制",
  15: "动态干线控制",
  16: "区域优化控制",
  17: "单点优化控制",
  18: "公交优先控制",
};


function showToast(message, ok = true) {
  toast.textContent = message;
  toast.className = `toast show ${ok ? "ok" : "err"}`;
}


function clearToast() {
  toast.className = "toast";
  toast.textContent = "";
}


async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.message || `请求失败: ${response.status}`);
  }
  return data;
}


function statusBadge(status, detail) {
  const text = detail || status || "-";
  const cls = status === "active" || status === "running" || status === "ok"
    ? "ok"
    : (status === "warning" || status === "inactive" ? "warn" : "err");
  return `<span class="badge ${cls}">${text}</span>`;
}


function setHtmlIfChanged(root, html) {
  if (!root) {
    return;
  }
  if (htmlCache.get(root.id) === html) {
    return;
  }
  root.innerHTML = html;
  htmlCache.set(root.id, html);
}


function setGlobalStatus(ok, text) {
  const dot = document.getElementById("globalStatusDot");
  const label = document.getElementById("globalStatusText");
  dot.classList.toggle("online", ok);
  label.textContent = text;
}


function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}


async function activatePage(key) {
  panels.forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.pageKey === key);
  });
  Array.from(navRoot.querySelectorAll(".nav-item")).forEach((button) => {
    button.classList.toggle("active", button.dataset.target === key);
  });
  activePageKey = key;
  try {
    await loadPageData(key);
  } catch (error) {
    showToast(error.message, false);
  }
}


function buildNavigation() {
  navRoot.innerHTML = "";
  const orderedPanels = panels.slice().sort((a, b) => {
    if (a.dataset.pageKey === "data-check") {
      return b.dataset.pageKey === "step-control" ? -1 : 1;
    }
    if (b.dataset.pageKey === "data-check") {
      return a.dataset.pageKey === "step-control" ? 1 : -1;
    }
    return panels.indexOf(a) - panels.indexOf(b);
  });
  orderedPanels.forEach((panel, index) => {
    const button = document.createElement("button");
    button.className = `nav-item ${index === 0 ? "active" : ""}`;
    button.type = "button";
    button.dataset.target = panel.dataset.pageKey;
    button.textContent = panel.dataset.pageTitle;
    button.addEventListener("click", () => activatePage(panel.dataset.pageKey));
    navRoot.appendChild(button);
  });
}


function renderNetworkSummary(data) {
  const root = document.getElementById("networkSummary");
  const current = data.current_network || {};
  setHtmlIfChanged(root, `
    <div class="summary-item"><span class="label">主机名</span><span class="value">${data.hostname || "-"}</span></div>
    <div class="summary-item"><span class="label">当前网卡</span><span class="value">${data.active_interface || "-"}</span></div>
    <div class="summary-item"><span class="label">当前地址</span><span class="value">${current.address || "-"} / ${current.prefix || "-"}</span></div>
    <div class="summary-item"><span class="label">当前网关</span><span class="value">${current.gateway || "-"}</span></div>
  `);
}


function renderInterfaces(data) {
  const iface = document.getElementById("iface");
  iface.innerHTML = "";
  for (const item of data.interfaces || []) {
    const option = document.createElement("option");
    option.value = item.device;
    option.textContent = item.display_name || `${item.device} (${item.type || "net"})`;
    if (item.device === data.active_interface) {
      option.selected = true;
    }
    iface.appendChild(option);
  }
}


function renderCameraBindings(items) {
  const root = document.getElementById("cameraTableBody");
  root.innerHTML = "";
  for (const item of items) {
    const row = document.createElement("tr");
    row.dataset.index = item.index;
    row.dataset.isNew = item.isNew ? "1" : "0";
    row.innerHTML = `
      <td>${item.index}</td>
      <td><input data-field="name" value="${escapeHtml(item.name || "")}"></td>
      <td>
        <select data-field="enable">
          <option value="1" ${item.enable ? "selected" : ""}>启用</option>
          <option value="0" ${!item.enable ? "selected" : ""}>禁用</option>
        </select>
      </td>
      <td><input data-field="host" value="${escapeHtml(item.host || "")}" placeholder="192.168.x.x"></td>
      <td><input data-field="username" value="${escapeHtml(item.username || "")}" placeholder="admin"></td>
      <td><input data-field="password" value="${escapeHtml(item.password || "")}" placeholder="密码"></td>
      <td><input data-field="port" value="${escapeHtml(item.port || 554)}" placeholder="554"></td>
      <td><input data-field="path" value="${escapeHtml(item.path || "/ch1/main")}" placeholder="/ch1/main"></td>
      <td><input data-field="uri" value="${escapeHtml(item.uri || "")}" placeholder="rtsp://..."></td>
      <td data-check="ping"><span class="badge ${item.enable ? "warn" : "warn"}">${item.enable ? "未检查" : "已禁用"}</span></td>
      <td data-check="stream"><span class="badge ${item.enable ? "warn" : "warn"}">${item.enable ? "未检查" : "已禁用"}</span></td>
      <td>
        <div class="row-actions">
          <button class="btn secondary small camera-check-row-btn" type="button">检测</button>
          <button class="btn secondary small camera-disable-btn" type="button">禁用</button>
          <button class="btn secondary small danger camera-delete-btn" type="button">彻底删除</button>
        </div>
      </td>
    `;
    bindCameraRow(row);
    root.appendChild(row);
  }
}


function nextCameraSourceId() {
  const ids = Array.from(document.querySelectorAll("#cameraTableBody tr")).map((row) => Number(row.dataset.index));
  const validIds = ids.filter((value) => Number.isFinite(value));
  return validIds.length ? Math.max(...validIds) + 1 : 0;
}


function addCameraBindingRow() {
  const sourceId = nextCameraSourceId();
  const items = collectCameraBindings();
  items.push({
    index: sourceId,
    name: `CAM_${String(sourceId).padStart(2, "0")}`,
    enable: true,
    host: "",
    username: "admin",
    password: "",
    port: 554,
    path: "/ch1/main",
    uri: "",
    isNew: true,
  });
  renderCameraBindings(items);
  showToast(`已新增 source${sourceId}，填写相机信息后点击保存绑定。`, true);
}


function generateRtspUriFromRow(row) {
  const host = row.querySelector('[data-field="host"]').value.trim();
  const username = row.querySelector('[data-field="username"]').value.trim();
  const password = row.querySelector('[data-field="password"]').value.trim();
  const port = Number(row.querySelector('[data-field="port"]')?.value.trim() || "554");
  const pathInput = row.querySelector('[data-field="path"]').value.trim() || "/ch1/main";
  if (!host) {
    return "";
  }
  const safePath = pathInput.startsWith("/") ? pathInput : `/${pathInput}`;
  const normalizedUser = decodeUriComponentSafe(username);
  const normalizedPassword = decodeUriComponentSafe(password);
  let auth = "";
  if (normalizedUser) {
    auth = encodeURIComponent(normalizedUser);
    if (normalizedPassword) {
      auth += `:${encodeURIComponent(normalizedPassword)}`;
    }
      auth += "@";
    }
  const portPart = Number.isFinite(port) && port !== 554 ? `:${port}` : "";
  return `rtsp://${auth}${host}${portPart}${safePath}`;
}


function decodeUriComponentSafe(value) {
  if (!value) {
    return "";
  }
  try {
    return decodeURIComponent(value);
  } catch (_error) {
    return value;
  }
}


function bindCameraRow(row) {
  const uriInput = row.querySelector('[data-field="uri"]');
  uriInput.addEventListener("input", () => {
    uriInput.dataset.manual = "1";
  });

  ["host", "username", "password", "port", "path"].forEach((field) => {
    row.querySelector(`[data-field="${field}"]`).addEventListener("input", () => {
      if (uriInput.dataset.manual === "1") {
        return;
      }
      uriInput.value = generateRtspUriFromRow(row);
    });
  });

  row.querySelector(".camera-disable-btn").addEventListener("click", () => {
    row.querySelector('[data-field="enable"]').value = "0";
    row.querySelector('[data-check="ping"]').innerHTML = '<span class="badge warn">待保存</span>';
    row.querySelector('[data-check="stream"]').innerHTML = '<span class="badge warn">待保存</span>';
    showToast(`source${row.dataset.index} 已标记为禁用，点击保存绑定后生效。`, true);
  });

  row.querySelector(".camera-check-row-btn").addEventListener("click", async (event) => {
    await checkCameraRows([row], event.currentTarget);
  });

  row.querySelector(".camera-delete-btn").addEventListener("click", async () => {
    const sourceId = Number(row.dataset.index);
    if (row.dataset.isNew === "1") {
      row.remove();
      showToast(`未保存的 source${sourceId} 已移除。`, true);
      return;
    }
    const confirmed = window.confirm(`彻底删除 source${sourceId} 会从 DeepStream 配置中移除此 source，且不会重排其他 source id。是否继续？`);
    if (!confirmed) {
      return;
    }
    clearToast();
    try {
      const data = await fetchJson(`/api/camera-bindings/${encodeURIComponent(sourceId)}/delete`, { method: "POST" });
      renderCameraBindings(data.items || []);
      loadedPages.add("camera");
      showToast(data.message, true);
    } catch (error) {
      showToast(error.message, false);
    }
  });
}


function collectCameraBindings() {
  return Array.from(document.querySelectorAll("#cameraTableBody tr")).map((row) => ({
    index: Number(row.dataset.index),
    name: row.querySelector('[data-field="name"]').value.trim(),
    enable: row.querySelector('[data-field="enable"]').value === "1",
    host: row.querySelector('[data-field="host"]').value.trim(),
    username: row.querySelector('[data-field="username"]').value.trim(),
    password: row.querySelector('[data-field="password"]').value.trim(),
    path: row.querySelector('[data-field="path"]').value.trim(),
    port: Number(row.querySelector('[data-field="port"]')?.value.trim() || "554"),
    uri: row.querySelector('[data-field="uri"]').value.trim(),
  }));
}


function collectCameraBindingsFromRows(rows) {
  return rows.map((row) => ({
    index: Number(row.dataset.index),
    name: row.querySelector('[data-field="name"]').value.trim(),
    enable: row.querySelector('[data-field="enable"]').value === "1",
    host: row.querySelector('[data-field="host"]').value.trim(),
    username: row.querySelector('[data-field="username"]').value.trim(),
    password: row.querySelector('[data-field="password"]').value.trim(),
    path: row.querySelector('[data-field="path"]').value.trim(),
    port: Number(row.querySelector('[data-field="port"]')?.value.trim() || "554"),
    uri: row.querySelector('[data-field="uri"]').value.trim(),
  }));
}


async function checkCameraRows(rows, triggerButton = null) {
  clearToast();
  const checkedRows = rows.length ? rows : Array.from(document.querySelectorAll("#cameraTableBody tr"));
  const checkButton = triggerButton || document.getElementById("checkCameraBtn");
  const saveButton = document.getElementById("saveCameraBtn");
  const reloadButton = document.getElementById("reloadCameraBtn");
  const previousText = checkButton?.textContent || "";
  if (checkButton) {
    checkButton.disabled = true;
    checkButton.textContent = "检查中...";
  }
  if (!triggerButton) {
    saveButton.disabled = true;
    reloadButton.disabled = true;
  }
  checkedRows.forEach((row) => {
    const enabled = row.querySelector('[data-field="enable"]').value === "1";
    const pingCell = row.querySelector('[data-check="ping"]');
    const streamCell = row.querySelector('[data-check="stream"]');
    if (!enabled) {
      pingCell.innerHTML = '<span class="badge warn">已禁用</span>';
      streamCell.innerHTML = '<span class="badge warn">已禁用</span>';
      return;
    }
    pingCell.innerHTML = '<span class="badge warn">测试中</span>';
    streamCell.innerHTML = '<span class="badge warn">测试中</span>';
  });
  showToast(triggerButton ? `正在检查 source${checkedRows[0]?.dataset.index}，请稍候...` : "正在检查相机连通性，请稍候...", true);
  try {
    const data = await fetchJson("/api/camera-bindings/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: collectCameraBindingsFromRows(checkedRows) }),
    });
    const resultMap = new Map((data.results || []).map((item) => [String(item.index), item]));
    checkedRows.forEach((row) => {
      const result = resultMap.get(row.dataset.index);
      if (!result) {
        return;
      }
      const pingCell = row.querySelector('[data-check="ping"]');
      const streamCell = row.querySelector('[data-check="stream"]');
      const ping = result.ping || {};
      const stream = result.stream || {};
      pingCell.innerHTML = `
        <span class="badge ${ping.ok ? "ok" : "err"}">${ping.ok ? "可达" : "失败"}</span>
        <div style="margin-top:6px;color:var(--muted);font-size:12px;">${ping.message || "-"}</div>
      `;
      streamCell.innerHTML = `
        <span class="badge ${stream.ok ? "ok" : "err"}">${streamCheckLabel(stream)}</span>
        <div style="margin-top:6px;color:var(--muted);font-size:12px;">${stream.message || "-"}</div>
      `;
    });
    const hasFailure = (data.results || []).some((item) => !item.ok);
    showToast(hasFailure ? "检查完成：有相机 Ping 或视频流拉流失败，请看表格红色结果。" : "检查完成：所选相机 Ping 和视频流拉流正常。", !hasFailure);
  } catch (error) {
    showToast(error.message, false);
  } finally {
    if (checkButton) {
      checkButton.disabled = false;
      checkButton.textContent = previousText;
    }
    if (!triggerButton) {
      saveButton.disabled = false;
      reloadButton.disabled = false;
    }
  }
}


function renderCalibration(items) {
  const root = document.getElementById("calibrationList");
  setHtmlIfChanged(root, items.map((item) => `
    <div class="status-card">
      <span class="label">${item.name}</span>
      <div class="value">${item.path}</div>
      <div class="value" style="margin-top:6px;">${statusBadge(item.exists ? "ok" : "failed", item.exists ? "文件存在" : "文件缺失")}</div>
      <div class="value" style="margin-top:8px; color: var(--muted); font-size: 13px;">最近更新：${item.updated_at || "-"}</div>
    </div>
  `).join(""));
}


function renderServiceQuickActions(services) {
  const root = document.getElementById("serviceQuickActions");
  const html = services.map((item) => {
    const canChangeAutostart = !["static", "masked", "not-found"].includes(item.autostart || "");
    const running = item.status === "active" || item.status === "running";
    const autostartAction = item.autostart_enabled ? "disable" : "enable";
    const autostartText = item.autostart_enabled ? "关闭开机自启" : "开启开机自启";
    return `
    <div class="status-card">
      <span class="label">${item.display_name || item.name}</span>
      <div class="service-state-bar">
        <div class="state-box ${running ? "active ok" : ""}">
          <span class="state-symbol">✓</span>
          <span>运行正常</span>
        </div>
        <div class="state-box ${running ? "" : "active err"}">
          <span class="state-symbol">×</span>
          <span>未运行</span>
        </div>
      </div>
      <div class="value">${statusBadge(item.status, item.status_label || item.status)}</div>
      <div class="value" style="margin-top:8px;">重启后自动启动：${statusBadge(item.autostart_enabled ? "ok" : "inactive", item.autostart_label || "未知")}</div>
      <div class="value" style="margin-top:8px; color: var(--muted); font-size: 13px;">系统服务：${item.name}</div>
      <div class="actions">
        <button class="btn secondary service-status-btn" data-service="${item.name}" data-action="status">刷新状态</button>
        <button class="btn secondary service-start-btn" data-service="${item.name}" data-action="start">启动服务</button>
        <button class="btn secondary service-restart-btn" data-service="${item.name}" data-action="restart">重启服务</button>
        <button class="btn secondary service-stop-btn" data-service="${item.name}" data-action="stop">暂停服务</button>
        <button class="btn secondary service-autostart-btn" data-service="${item.name}" data-action="${autostartAction}" ${!canChangeAutostart ? "disabled" : ""}>${autostartText}</button>
      </div>
    </div>
  `;
  }).join("");
  const changed = htmlCache.get(root.id) !== html;
  setHtmlIfChanged(root, html);
  if (!changed) {
    return;
  }

  root.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      clearToast();
      const wasDisabled = button.disabled;
      button.disabled = true;
      try {
        const data = await fetchJson(`/api/services/${encodeURIComponent(button.dataset.service)}/${encodeURIComponent(button.dataset.action)}`, { method: "POST" });
        showToast(data.message, true);
        await loadRuntimeSummary();
      } catch (error) {
        showToast(error.message, false);
      } finally {
        button.disabled = wasDisabled;
      }
    });
  });
}


function renderSignalStatus(signal, rootId = "signalStatus", syncInputs = true) {
  const root = document.getElementById(rootId);
  const hostInput = document.getElementById("signalHostInput");
  const portInput = document.getElementById("signalPortInput");
  if (syncInputs && hostInput && document.activeElement !== hostInput) {
    hostInput.value = signal.host || "";
  }
  if (syncInputs && portInput && document.activeElement !== portInput) {
    portInput.value = signal.port || "";
  }
  setHtmlIfChanged(root, `
    <div class="summary-item"><span class="label">目标</span><span class="value">${signal.host}:${signal.port}</span></div>
    <div class="summary-item"><span class="label">Ping</span><span class="value">${statusBadge(signal.ping.ok ? "ok" : "failed", signal.ping.ok ? "已连通" : "失败")}<div style="margin-top:8px;color:var(--muted);font-size:13px;">${signal.ping.message}</div></span></div>
    <div class="summary-item"><span class="label">TCP</span><span class="value">${statusBadge(signal.tcp.ok ? "ok" : "failed", signal.tcp.ok ? "端口可达" : "失败")}<div style="margin-top:8px;color:var(--muted);font-size:13px;">${signal.tcp.message}</div></span></div>
  `);
}


function syncSignalHostInputs(value, sourceId) {
  ["signalHostInput"].forEach((id) => {
    const input = document.getElementById(id);
    if (!input || id === sourceId || document.activeElement === input) {
      return;
    }
    input.value = value;
  });
  updateStepDownloadSignalHost(value);
}


function updateStepDownloadSignalHost(value) {
  const root = document.getElementById("stepDownloadSignalHost");
  if (!root) {
    return;
  }
  const host = (value || document.getElementById("signalHostInput")?.value || "").trim();
  root.textContent = host || "-";
}


function renderStepStatus(rootId, status, title, message) {
  const root = document.getElementById(rootId);
  if (!root) {
    return;
  }
  const success = status === "ok" || status === "active" || status === "running";
  const failed = status === "failed" || status === "err";
  setHtmlIfChanged(root, `
    <div class="summary-item">
      <span class="label">${title}</span>
      <div class="service-state-bar">
        <div class="state-box ${success ? "active ok" : ""}">
          <span class="state-symbol">✓</span>
          <span>成功</span>
        </div>
        <div class="state-box ${failed ? "active err" : ""}">
          <span class="state-symbol">×</span>
          <span>失败</span>
        </div>
      </div>
      <span class="value">${statusBadge(status, message)}</span>
    </div>
  `);
}


function renderStepControlPage() {
  const signalHost = document.getElementById("signalHostInput")?.value || window.BOX_ADMIN_BOOTSTRAP?.signalHost || "";
  const stepUsernameInput = document.getElementById("stepUsernameInput");
  const stepPortInput = document.getElementById("stepPortInput");
  if (stepUsernameInput && !stepUsernameInput.value) {
    stepUsernameInput.value = "admin";
  }
  if (stepPortInput && !stepPortInput.value) {
    stepPortInput.value = "29999";
  }
  updateStepDownloadSignalHost(signalHost);
  renderStepStatus("stepToolStatus", "inactive", "智能控制", "尚未查询");
  renderStepStatus("stepServiceStatus", "inactive", "智能控制服务", "尚未查询");
  renderStepStatus("stepParamStatus", "inactive", "参数发送", "等待发送");
  renderStepStatus("stepSyncStatus", "inactive", "同步 / 上传", "尚未操作");
  setPreplanRestartAvailable(true);
}


function setPreplanRestartAvailable(available) {
  const button = document.getElementById("restartPreplanServiceBtn");
  if (button) {
    button.disabled = false;
  }
}


function renderSignalControlOutput(data) {
  const output = document.getElementById("signalControlStatusOutput");
  const phaseText = data.phase_id ? `\n当前 phaseID：${data.phase_id}` : "";
  const stepText = typeof data.step_control === "boolean" ? `\n步进控制：${data.step_control ? "已开启" : "未开启"}` : "";
  output.classList.toggle("step-active", Boolean(data.step_control) || Number(data.ctrl_mode) === 10);
  output.textContent = `控制模式：${data.ctrl_mode_label || "-"}（${data.ctrl_mode ?? "-"}）${stepText}${phaseText}`;
}


function streamCheckLabel(stream) {
  if (stream.ok) {
    return "拉流成功";
  }
  const labels = {
    auth_failed: "账号或密码错误",
    path_failed: "路径错误",
    timeout: "拉流超时",
    connect_failed: "连接失败",
    open_failed: "无法打开",
    no_video: "无视频流",
    invalid_uri: "地址错误",
    empty_uri: "地址为空",
    missing_tool: "工具缺失",
  };
  return labels[stream.reason] || "拉流失败";
}


function showStepPending(rootId, title) {
  renderStepStatus(rootId, "warning", title, "接口格式待接入");
  showToast(`${title}接口待接入`, false);
}


function laneSortKey(lane) {
  const num = Number(lane);
  return Number.isFinite(num) ? num : String(lane);
}


function collectMetricLanes(metrics) {
  return Array.from(metrics?.lanes || []).sort((a, b) => {
    const ak = laneSortKey(a);
    const bk = laneSortKey(b);
    if (typeof ak === "number" && typeof bk === "number") {
      return ak - bk;
    }
    return String(a).localeCompare(String(b));
  });
}


function renderLatestMetricTable(metrics) {
  const table = document.getElementById("latestMetricTable");
  const meta = document.getElementById("latestMetricMeta");
  const lanes = collectMetricLanes(metrics || {});
  if (!lanes.length) {
    setHtmlIfChanged(table, `<tbody><tr><td>暂无车道数据</td></tr></tbody>`);
    meta.textContent = "未找到最近 3 分钟车道数据。";
    return;
  }
  const rows = [
    { label: "3分钟总流量", unit: "", values: metrics.flow_total || {} },
    { label: "3分钟平均车头时距", unit: " s", values: metrics.headway_avg || {} },
    { label: "基础排队长度", unit: " m", values: metrics.base_queue || {} },
    { label: "3分钟平均新增排队长度", unit: " m", values: metrics.queue_increment_avg || {} },
    { label: "3分钟平均排队长度", unit: " m", values: metrics.queue_avg || {} },
  ];
  const html = `
    <thead>
      <tr>
        <th>数据项</th>
        ${lanes.map((lane) => `<th>车道 ${lane}</th>`).join("")}
      </tr>
    </thead>
    <tbody>
      ${rows.map((row) => `
        <tr>
          <td>${row.label}</td>
          ${lanes.map((lane) => `<td>${Object.prototype.hasOwnProperty.call(row.values, lane) ? `${row.values[lane]}${row.unit}` : "-"}</td>`).join("")}
        </tr>
      `).join("")}
    </tbody>
  `;
  setHtmlIfChanged(table, html);
  const rowsUsed = metrics.rows_used || {};
  meta.textContent = metrics.updated_at
    ? `统计最近 3 分钟车道数据，最近时间：${metrics.updated_at}。流量 ${rowsUsed.flow || 0} 条，车头时距 ${rowsUsed.headway || 0} 条，排队长度 ${rowsUsed.queue || 0} 条。`
    : "已读取最近 3 分钟车道数据。";
}


function renderHourlyFlowStats(flowWindow) {
  const table = document.getElementById("hourlyFlowTable");
  const meta = document.getElementById("hourlyFlowMeta");
  const lanes = flowWindow?.lanes || [];
  if (!lanes.length) {
    setHtmlIfChanged(table, `<tbody><tr><td>暂无统计数据</td></tr></tbody>`);
    meta.textContent = flowWindow?.file ? "未找到可统计的车流记录。" : "未找到车流 CSV 文件。";
    return;
  }
  const html = `
    <thead>
      <tr>
        <th>统计项</th>
        ${lanes.map((lane) => `<th>车道 ${lane}</th>`).join("")}
        <th>合计</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>累计流量</td>
        ${lanes.map((lane) => `<td>${flowWindow.by_lane?.[lane] ?? 0}</td>`).join("")}
        <td>${flowWindow.total ?? 0}</td>
      </tr>
    </tbody>
  `;
  setHtmlIfChanged(table, html);
  meta.textContent = `统计最近 ${flowWindow.minutes} 分钟，使用 ${flowWindow.rows || 0} 条记录。`;
}


function renderRecentEvents(events) {
  const root = document.getElementById("recentEvents");
  root.textContent = events && events.length ? events.join("\n") : "暂无异常日志";
}


async function loadStatus() {
  const data = await fetchJson("/api/status");
  renderNetworkSummary(data);
  renderInterfaces(data);
  if (data.active_interface) {
    await loadInterfaceDetail(data.active_interface);
  }
  const ok = (data.services || []).every((item) => item.status === "active" || item.status === "running");
  setGlobalStatus(ok, ok ? "服务运行中" : "存在异常服务");
}


async function loadInterfaceDetail(iface) {
  const data = await fetchJson(`/api/interfaces/${encodeURIComponent(iface)}`);
  const current = data.interface || {};
  document.getElementById("ipAddress").value = current.address || "";
  document.getElementById("netmask").value = current.netmask || "";
  document.getElementById("gateway").value = current.gateway || "";
  document.getElementById("dns").value = (current.dns || []).join(" ");
  document.getElementById("ifaceNote").value = current.note || "";
}


async function loadCameraBindings() {
  const data = await fetchJson("/api/camera-bindings");
  renderCameraBindings(data.items || []);
}


async function loadCalibrationStatus() {
  const data = await fetchJson("/api/calibration-status");
  renderCalibration(data.items || []);
}


async function loadRuntimeSummary() {
  const data = await fetchJson("/api/runtime-summary");
  const summary = data.summary || {};
  renderServiceQuickActions(summary.services || []);
  const signal = summary.signal_controller || { host: "-", port: "-", ping: {}, tcp: {} };
  renderSignalStatus(signal, "signalStatus", true);
}


async function loadDataSummary() {
  const minutesInput = document.getElementById("dataMinutesInput");
  const minutes = minutesInput ? minutesInput.value.trim() || "60" : "60";
  const data = await fetchJson(`/api/data-summary?minutes=${encodeURIComponent(minutes)}`);
  const summary = data.summary || {};
  renderLatestMetricTable(summary.latest_metrics_3m || {});
  renderHourlyFlowStats(summary.flow_window || {});
  renderRecentEvents(summary.recent_events || []);
}


async function loadPageData(key, force = false) {
  if (!force && loadedPages.has(key)) {
    return;
  }
  if (key === "network") {
    await loadStatus();
  } else if (key === "camera") {
    await loadCameraBindings();
  } else if (key === "calibration") {
    await loadCalibrationStatus();
  } else if (key === "runtime") {
    await loadRuntimeSummary();
  } else if (key === "step-control") {
    await loadRuntimeSummary();
    renderStepControlPage();
  } else if (key === "data-check") {
    if (force) {
      await loadDataSummary();
    } else {
      renderRecentEvents([]);
    }
  }
  loadedPages.add(key);
}


function wireActions() {
  document.getElementById("refreshAllBtn").addEventListener("click", async () => {
    clearToast();
    try {
      loadedPages.delete(activePageKey);
      await loadPageData(activePageKey, true);
      showToast("已刷新当前页面数据", true);
    } catch (error) {
      showToast(error.message, false);
    }
  });

  document.getElementById("applyNetworkBtn").addEventListener("click", async () => {
    clearToast();
    try {
      const body = {
        interface: document.getElementById("iface").value,
        address: document.getElementById("ipAddress").value.trim(),
        netmask: document.getElementById("netmask").value.trim(),
        gateway: document.getElementById("gateway").value.trim(),
        dns: document.getElementById("dns").value.trim(),
        note: document.getElementById("ifaceNote").value.trim(),
      };
      const data = await fetchJson("/api/network", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      showToast(data.message, true);
      await loadStatus();
      loadedPages.add("network");
    } catch (error) {
      showToast(error.message, false);
    }
  });

  document.getElementById("reloadCameraBtn").addEventListener("click", async () => {
    clearToast();
    try {
      await loadCameraBindings();
      loadedPages.add("camera");
      showToast("相机配置已刷新", true);
    } catch (error) {
      showToast(error.message, false);
    }
  });

  document.getElementById("addCameraBtn").addEventListener("click", () => {
    clearToast();
    addCameraBindingRow();
  });

  document.getElementById("saveCameraBtn").addEventListener("click", async () => {
    clearToast();
    try {
      const data = await fetchJson("/api/camera-bindings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: collectCameraBindings() }),
      });
      renderCameraBindings(data.items || []);
      loadedPages.add("camera");
      showToast(data.message, true);
    } catch (error) {
      showToast(error.message, false);
    }
  });

  document.getElementById("checkCameraBtn").addEventListener("click", async () => {
    const rows = Array.from(document.querySelectorAll("#cameraTableBody tr"));
    await checkCameraRows(rows);
  });

  document.getElementById("iface").addEventListener("change", async (event) => {
    clearToast();
    try {
      await loadInterfaceDetail(event.target.value);
    } catch (error) {
      showToast(error.message, false);
    }
  });

  document.getElementById("refreshDataBtn").addEventListener("click", async () => {
    clearToast();
    try {
      await loadDataSummary();
      loadedPages.add("data-check");
      showToast("数据检测已刷新", true);
    } catch (error) {
      showToast(error.message, false);
    }
  });

  ["signalHostInput"].forEach((id) => {
    const input = document.getElementById(id);
    if (!input) {
      return;
    }
    input.addEventListener("input", () => {
      syncSignalHostInputs(input.value.trim(), id);
      updateStepDownloadSignalHost(input.value.trim());
    });
  });

  document.getElementById("checkSignalBtn").addEventListener("click", async () => {
    clearToast();
    try {
      const data = await fetchJson("/api/signal-controller/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          host: document.getElementById("signalHostInput").value.trim(),
          port: document.getElementById("signalPortInput").value.trim(),
        }),
      });
      renderSignalStatus(data.signal_controller || {}, "signalStatus", false);
      loadedPages.delete("runtime");
      loadedPages.delete("step-control");
      showToast(data.message, data.signal_controller?.ping?.ok && data.signal_controller?.tcp?.ok);
    } catch (error) {
      showToast(error.message, false);
    }
  });

  document.getElementById("checkStepToolBtn").addEventListener("click", async () => {
    clearToast();
    setPreplanRestartAvailable(true);
    try {
      const data = await fetchJson("/api/step-tool/status");
      renderStepStatus("stepToolStatus", data.online ? "ok" : "failed", "智能控制", data.message);
      setPreplanRestartAvailable(true);
      showToast(data.message, data.online);
    } catch (error) {
      renderStepStatus("stepToolStatus", "failed", "智能控制", error.message);
      setPreplanRestartAvailable(true);
      showToast(error.message, false);
    }
  });

  document.getElementById("restartPreplanServiceBtn").addEventListener("click", async () => {
    clearToast();
    const button = document.getElementById("restartPreplanServiceBtn");
    const previousText = button.textContent;
    button.disabled = true;
    button.textContent = "重启中...";
    try {
      renderStepStatus("stepToolStatus", "warning", "智能控制", "正在重启智能控制服务...");
      const data = await fetchJson("/api/step-tool/restart-service", { method: "POST" });
      renderStepStatus("stepToolStatus", "ok", "智能控制", data.message);
      showToast(data.message, true);
    } catch (error) {
      renderStepStatus("stepToolStatus", "failed", "智能控制", error.message);
      setPreplanRestartAvailable(true);
      showToast(error.message, false);
    } finally {
      button.textContent = previousText;
    }
  });

  document.getElementById("openStepToolPageBtn").addEventListener("click", () => {
    clearToast();
    const host = window.location.hostname || "127.0.0.1";
    const url = `http://${host}:8080/`;
    window.open(url, "_blank", "noopener,noreferrer");
    renderStepStatus("stepServiceStatus", "ok", "智能控制页面", `已打开 ${url}`);
    showToast("已打开智能控制页面", true);
  });

  document.getElementById("sendStepParamsBtn").addEventListener("click", async () => {
    clearToast();
    const host = document.getElementById("signalHostInput").value.trim();
    const username = document.getElementById("stepUsernameInput").value.trim();
    const password = document.getElementById("stepPasswordInput").value;
    const port = document.getElementById("stepPortInput").value.trim();
    if (!host || !username || !password || !port) {
      renderStepStatus("stepParamStatus", "failed", "登录测试 / 参数保存", "请先填写信号机 IP、账户、密码和端口号");
      showToast("请先填写完整参数", false);
      return;
    }
    try {
      const data = await fetchJson("/api/step-tool/tsc-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ip: host, username, password, port }),
      });
      const testMessage = data.connection_test ? "已先完成信号机登录测试。" : "";
      renderStepStatus("stepParamStatus", data.success ? "ok" : "failed", "登录测试 / 参数保存", `${data.message}${testMessage ? ` ${testMessage}` : ""}`);
      showToast(data.message, data.success);
    } catch (error) {
      renderStepStatus("stepParamStatus", "failed", "登录测试 / 参数保存", error.message);
      showToast(error.message, false);
    }
  });

  document.getElementById("fetchSignalControlStatusBtn").addEventListener("click", async () => {
    clearToast();
    try {
      const data = await fetchJson("/api/step-tool/tsc-status");
      renderSignalControlOutput(data);
      showToast(data.message, true);
    } catch (error) {
      document.getElementById("signalControlStatusOutput").textContent = error.message;
      showToast(error.message, false);
    }
  });

  document.getElementById("testStepControlBtn").addEventListener("click", async () => {
    clearToast();
    const button = document.getElementById("testStepControlBtn");
    const previousText = button.textContent;
    button.disabled = true;
    button.textContent = "测试中...";
    const duration = document.getElementById("stepDurationInput").value.trim() || "30";
    try {
      renderStepStatus("stepServiceStatus", "warning", "步进控制测试", `正在发送 ${duration} 秒步进控制并刷新控制状态...`);
      const data = await fetchJson("/api/step-tool/step-control-test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ duration }),
      });
      renderSignalControlOutput(data);
      renderStepStatus("stepServiceStatus", data.success ? "ok" : "warning", "步进控制测试", data.message);
      showToast(data.message, data.success);
    } catch (error) {
      renderStepStatus("stepServiceStatus", "failed", "步进控制测试", error.message);
      showToast(error.message, false);
    } finally {
      button.disabled = false;
      button.textContent = previousText;
    }
  });

  document.getElementById("cancelStepControlBtn").addEventListener("click", async () => {
    clearToast();
    const button = document.getElementById("cancelStepControlBtn");
    const previousText = button.textContent;
    button.disabled = true;
    button.textContent = "取消中...";
    try {
      const data = await fetchJson("/api/step-tool/step-control-cancel", { method: "POST" });
      if (data.after?.data) {
        const statusData = data.after.data || {};
        const ctrlMode = Number(statusData.ctrlMode);
        renderSignalControlOutput({
          ctrl_mode: Number.isFinite(ctrlMode) ? ctrlMode : statusData.ctrlMode,
          ctrl_mode_label: Number.isFinite(ctrlMode) ? (CTRL_MODE_LABELS?.[ctrlMode] || `未知控制模式 ${ctrlMode}`) : "-",
          step_control: Boolean(statusData.stepControl),
          phase_id: data.phase_id,
        });
      }
      renderStepStatus("stepServiceStatus", "ok", "取消步进控制", data.message);
      showToast(data.message, true);
    } catch (error) {
      renderStepStatus("stepServiceStatus", "failed", "取消步进控制", error.message);
      showToast(error.message, false);
    } finally {
      button.disabled = false;
      button.textContent = previousText;
    }
  });

  document.getElementById("syncStepConfigBtn").addEventListener("click", () => {
    clearToast();
    showStepPending("stepSyncStatus", "配置同步");
  });

  document.getElementById("openSignalConfigPageBtn").addEventListener("click", () => {
    clearToast();
    const host = document.getElementById("signalHostInput").value.trim();
    if (!host) {
      renderStepStatus("stepSyncStatus", "failed", "配置下载", "请先填写或读取信号机 IP");
      showToast("请先填写或读取信号机 IP", false);
      return;
    }
    const url = /^https?:\/\//i.test(host) ? host : `http://${host}/`;
    window.open(url, "_blank", "noopener,noreferrer");
    updateStepDownloadSignalHost(host);
    renderStepStatus("stepSyncStatus", "ok", "配置下载", `已打开 ${url}`);
    showToast("已打开信号机页面，请在新页面手动下载配置文件。", true);
  });

  document.getElementById("uploadStepConfigBtn").addEventListener("click", () => {
    clearToast();
    document.getElementById("stepConfigFileInput").click();
  });

  document.getElementById("stepConfigFileInput").addEventListener("change", async (event) => {
    clearToast();
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    try {
      renderStepStatus("stepSyncStatus", "warning", "配置上传", "正在上传配置文件...");
      const data = await fetchJson("/api/step-tool/tsc-config-upload", {
        method: "POST",
        body: formData,
      });
      const filename = data.file?.filename || file.name;
      const size = data.file?.size ?? file.size;
      renderStepStatus("stepSyncStatus", "ok", "配置上传", `${filename}（${size} 字节）上传成功`);
      showToast(data.message || "配置文件上传成功", true);
    } catch (error) {
      renderStepStatus("stepSyncStatus", "failed", "配置上传", error.message);
      showToast(error.message, false);
    } finally {
      event.target.value = "";
    }
  });

  document.getElementById("saveSignalBtn").addEventListener("click", async () => {
    clearToast();
    try {
      const data = await fetchJson("/api/signal-controller", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          host: document.getElementById("signalHostInput").value.trim(),
          port: document.getElementById("signalPortInput").value.trim(),
        }),
      });
      renderSignalStatus(data.signal_controller || {}, "signalStatus", true);
      showToast(data.message, true);
      loadedPages.delete("runtime");
      loadedPages.delete("step-control");
      await loadRuntimeSummary();
      loadedPages.add("runtime");
      loadedPages.add("step-control");
    } catch (error) {
      showToast(error.message, false);
    }
  });
}


async function boot() {
  buildNavigation();
  wireActions();
  try {
    await loadPageData(activePageKey);
  } catch (error) {
    showToast(error.message, false);
  }
}


boot();
