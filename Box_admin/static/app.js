const toast = document.getElementById("toast");
const panels = Array.from(document.querySelectorAll(".page-panel"));
const navRoot = document.getElementById("sidebarNav");
const htmlCache = new Map();


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


function activatePage(key) {
  panels.forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.pageKey === key);
  });
  Array.from(navRoot.querySelectorAll(".nav-item")).forEach((button) => {
    button.classList.toggle("active", button.dataset.target === key);
  });
}


function buildNavigation() {
  navRoot.innerHTML = "";
  panels.forEach((panel, index) => {
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
    row.innerHTML = `
      <td>${item.index}</td>
      <td><input data-field="name" value="${item.name || ""}"></td>
      <td>
        <select data-field="enable">
          <option value="1" ${item.enable ? "selected" : ""}>启用</option>
          <option value="0" ${!item.enable ? "selected" : ""}>禁用</option>
        </select>
      </td>
      <td><input data-field="host" value="${item.host || ""}" placeholder="192.168.x.x"></td>
      <td><input data-field="username" value="${item.username || ""}" placeholder="admin"></td>
      <td><input data-field="password" value="${item.password || ""}" placeholder="密码"></td>
      <td><input data-field="path" value="${item.path || "/ch1/main"}" placeholder="/ch1/main"></td>
      <td><input data-field="uri" value="${item.uri || ""}" placeholder="rtsp://..."></td>
      <td><span class="badge ${item.enable ? "ok" : "warn"}">${item.enable ? "已启用" : "已禁用"}</span></td>
    `;
    bindCameraRow(row);
    root.appendChild(row);
  }
}


function generateRtspUriFromRow(row) {
  const host = row.querySelector('[data-field="host"]').value.trim();
  const username = row.querySelector('[data-field="username"]').value.trim();
  const password = row.querySelector('[data-field="password"]').value.trim();
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
  return `rtsp://${auth}${host}${safePath}`;
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

  ["host", "username", "password", "path"].forEach((field) => {
    row.querySelector(`[data-field="${field}"]`).addEventListener("input", () => {
      if (uriInput.dataset.manual === "1") {
        return;
      }
      uriInput.value = generateRtspUriFromRow(row);
    });
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
    port: 554,
    uri: row.querySelector('[data-field="uri"]').value.trim(),
  }));
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


function renderServiceStatus(services) {
  const root = document.getElementById("serviceList");
  setHtmlIfChanged(root, services.map((item) => `
    <div class="status-card">
      <span class="label">${item.display_name || item.name}</span>
      <div class="value">${statusBadge(item.status, item.status_label || item.status)}</div>
      <div class="value" style="margin-top:8px;">重启后自动启动：${statusBadge(item.autostart_enabled ? "ok" : "inactive", item.autostart_label || "未知")}</div>
      <div class="value" style="margin-top:8px; color: var(--muted); font-size: 13px;">系统服务：${item.name}</div>
    </div>
  `).join(""));
}


function renderServiceQuickActions(services) {
  const root = document.getElementById("serviceQuickActions");
  const html = services.map((item) => {
    const canChangeAutostart = !["static", "masked", "not-found"].includes(item.autostart || "");
    return `
    <div class="status-card">
      <span class="label">${item.display_name || item.name}</span>
      <div class="value">${statusBadge(item.status, item.status_label || item.status)}</div>
      <div class="value" style="margin-top:8px;">重启后自动启动：${statusBadge(item.autostart_enabled ? "ok" : "inactive", item.autostart_label || "未知")}</div>
      <div class="value" style="margin-top:8px; color: var(--muted); font-size: 13px;">系统服务：${item.name}</div>
      <div class="actions">
        <button class="btn secondary service-status-btn" data-service="${item.name}" data-action="status">刷新状态</button>
        <button class="btn secondary service-start-btn" data-service="${item.name}" data-action="start">启动服务</button>
        <button class="btn secondary service-restart-btn" data-service="${item.name}" data-action="restart">重启服务</button>
        <button class="btn secondary service-stop-btn" data-service="${item.name}" data-action="stop">暂停服务</button>
        <button class="btn secondary service-enable-btn" data-service="${item.name}" data-action="enable" ${(!canChangeAutostart || item.autostart_enabled) ? "disabled" : ""}>开启重启自动启动</button>
        <button class="btn secondary service-disable-btn" data-service="${item.name}" data-action="disable" ${(!canChangeAutostart || !item.autostart_enabled) ? "disabled" : ""}>关闭重启自动启动</button>
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


function renderMetricList(rootId, payload, unit) {
  const root = document.getElementById(rootId);
  const top = payload.top || [];
  if (!top.length) {
    setHtmlIfChanged(root, `<div class="metric-item"><span class="label">暂无数据</span><div class="value">${payload.file || "未找到对应文件"}</div></div>`);
    return;
  }
  setHtmlIfChanged(root, top.map((item) => `
    <div class="metric-item">
      <span class="label">车道 ${item.lane}</span>
      <div class="value">${item.value}${unit}</div>
    </div>
  `).join("") + `
    <div class="metric-item">
      <span class="label">最近时间</span>
      <div class="value">${payload.updated_at || "-"}</div>
    </div>
  `);
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
  renderServiceStatus(summary.services || []);
  renderServiceQuickActions(summary.services || []);
  const signal = summary.signal_controller || { host: "-", port: "-", ping: {}, tcp: {} };
  renderSignalStatus(signal, "signalRuntimeStatus", false);
  renderSignalStatus(signal, "signalStatus", true);
  renderMetricList("flowMetrics", summary.metrics?.flow || {}, "");
  renderMetricList("headwayMetrics", summary.metrics?.headway || {}, " s");
  renderMetricList("queueMetrics", summary.metrics?.queue || {}, " m");
  renderRecentEvents(summary.recent_events || []);
}


function wireActions() {
  document.getElementById("refreshAllBtn").addEventListener("click", async () => {
    clearToast();
    try {
      await Promise.all([loadStatus(), loadCameraBindings(), loadCalibrationStatus(), loadRuntimeSummary()]);
      showToast("已刷新全部页面数据", true);
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
    } catch (error) {
      showToast(error.message, false);
    }
  });

  document.getElementById("reloadCameraBtn").addEventListener("click", async () => {
    clearToast();
    try {
      await loadCameraBindings();
      showToast("相机配置已刷新", true);
    } catch (error) {
      showToast(error.message, false);
    }
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
      showToast(data.message, true);
    } catch (error) {
      showToast(error.message, false);
    }
  });

  document.getElementById("checkCameraBtn").addEventListener("click", async () => {
    clearToast();
    try {
      const data = await fetchJson("/api/camera-bindings/check", { method: "POST" });
      const resultMap = new Map((data.results || []).map((item) => [String(item.index), item]));
      Array.from(document.querySelectorAll("#cameraTableBody tr")).forEach((row) => {
        const result = resultMap.get(row.dataset.index);
        const cell = row.lastElementChild;
        if (!result) {
          return;
        }
        cell.innerHTML = `<span class="badge ${result.ok ? "ok" : "err"}">${result.ok ? "连接正常" : "连接失败"}</span>`;
      });
      const hasFailure = (data.results || []).some((item) => !item.ok);
      showToast(hasFailure ? "检查完成：有相机连接失败，请看表格红色结果。" : "检查完成：所有启用相机连接正常。", !hasFailure);
    } catch (error) {
      showToast(error.message, false);
    }
  });

  document.getElementById("iface").addEventListener("change", async (event) => {
    clearToast();
    try {
      await loadInterfaceDetail(event.target.value);
    } catch (error) {
      showToast(error.message, false);
    }
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
      renderSignalStatus(data.signal_controller || {}, "signalRuntimeStatus", false);
      showToast(data.message, data.signal_controller?.ping?.ok && data.signal_controller?.tcp?.ok);
    } catch (error) {
      showToast(error.message, false);
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
      renderSignalStatus(data.signal_controller || {}, "signalRuntimeStatus", false);
      showToast(data.message, true);
      await Promise.all([loadStatus(), loadRuntimeSummary()]);
    } catch (error) {
      showToast(error.message, false);
    }
  });
}


async function boot() {
  buildNavigation();
  wireActions();
  try {
    await Promise.all([loadStatus(), loadCameraBindings(), loadCalibrationStatus(), loadRuntimeSummary()]);
  } catch (error) {
    showToast(error.message, false);
  }
}


boot();
