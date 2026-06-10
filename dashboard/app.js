const HPC_PRESETS = {
  custom: {
    host: "frontera.tacc.utexas.edu",
    user: "tg848932",
    remote_workdir: "/scratch2/05594/tg848932/2023/F2F/s17_new_mpi_decay",
  },
  nersc: {
    host: "perlmutter-p1.nersc.gov",
    remote_workdir: "/global/homes/u/",
  },
  polaris: {
    host: "polaris.alcf.anl.gov",
    remote_workdir: "/home/",
  },
  tacc: {
    host: "frontera.tacc.utexas.edu",
    user: "tg848932",
    remote_workdir: "/scratch2/05594/tg848932/2023/F2F/s17_new_mpi_decay",
  },
};

function applyHpcPreset() {
  const preset = document.querySelector("#hpcPreset").value;
  const data = HPC_PRESETS[preset] || HPC_PRESETS.custom;
  form.elements["cluster.host"].value = data.host || "";
  form.elements["cluster.user"].value = data.user || "";
  form.elements["cluster.remote_workdir"].value = data.remote_workdir || "";
}

const form = document.querySelector("#configForm");
const commandOutput = document.querySelector("#commandOutput");
const buttons = Array.from(document.querySelectorAll("button"));

let latestState = null;

const fields = [
  "restart",
  "cluster.host",
  "cluster.user",
  "cluster.ssh_key",
  "cluster.remote_workdir",
  "cluster.remote_script_path",
  "job.script",
  "job.job_id_file",
  "reporting.poll_interval_seconds",
  "preprocess.enabled",
  "preprocess.mode",
  "preprocess.command",
  "preprocess.slurm_script",
  "preprocess.python_script",
  "sync.enabled",
  "sync.remote_results_path",
  "sync.local_results_path",
  "analysis.enabled",
  "analysis.mode",
  "analysis.command",
  "analysis.slurm_script",
  "analysis.python_script",
  "analysis.job_id_file",
];

function getNested(source, dotted) {
  return dotted.split(".").reduce((obj, key) => (obj ? obj[key] : undefined), source);
}

function setNested(target, dotted, value) {
  const parts = dotted.split(".");
  let cursor = target;
  while (parts.length > 1) {
    const key = parts.shift();
    cursor[key] = cursor[key] || {};
    cursor = cursor[key];
  }
  cursor[parts[0]] = value;
}

function readForm() {
  const data = {};
  for (const name of fields) {
    const input = form.elements[name];
    if (!input) continue;
    let value = input.type === "checkbox" ? input.checked : input.value;
    if (name === "reporting.poll_interval_seconds") {
      value = Number.parseInt(value || "0", 10);
    }
    setNested(data, name, value);
  }
  Object.assign(data, collectJobScripts());
  return data;
}

function writeForm(config) {
  for (const name of fields) {
    const input = form.elements[name];
    if (!input) continue;
    const value = getNested(config, name);
    if (input.type === "checkbox") {
      input.checked = Boolean(value);
    } else {
      input.value = value ?? "";
    }
  }
  renderJobScripts(config.jobs);
  toggleModeFields();
  togglePreprocessModeFields();
}

let jobScriptIndex = 0;

function renderJobScripts(jobs) {
  const list = document.querySelector("#jobScriptsList");
  list.innerHTML = "";
  jobScriptIndex = 0;
  const scripts = jobs && typeof jobs === "object" ? Object.values(jobs).filter(Boolean) : [];
  if (scripts.length === 0) scripts.push("");
  for (const script of scripts) {
    addJobScriptRow(script);
  }
}

function addJobScriptRow(value) {
  const list = document.querySelector("#jobScriptsList");
  const div = document.createElement("div");
  div.className = "job-script-row";
  const input = document.createElement("input");
  input.name = "jobs.script_" + jobScriptIndex++;
  input.autocomplete = "off";
  input.value = value || "";
  div.appendChild(input);
  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "remove-btn";
  removeBtn.textContent = "✕";
  removeBtn.addEventListener("click", () => {
    div.remove();
  });
  div.appendChild(removeBtn);
  list.appendChild(div);
}

function collectJobScripts() {
  const scripts = [];
  document.querySelectorAll("#jobScriptsList input").forEach((input) => {
    if (input.value.trim()) scripts.push(input.value.trim());
  });
  const data = {};
  scripts.forEach((s, i) => setNested(data, "jobs.script_" + i, s));
  return data;
}

function toggleModeFields() {
  const mode = form.elements["analysis.mode"]?.value;
  document.querySelectorAll("[data-show-for]").forEach((el) => {
    el.hidden = el.dataset.showFor !== mode;
  });
}

function togglePreprocessModeFields() {
  const mode = form.elements["preprocess.mode"]?.value;
  document.querySelectorAll("[data-show-for-pre]").forEach((el) => {
    el.hidden = el.dataset.showForPre !== mode;
  });
}

function text(id, value) {
  document.querySelector(`#${id}`).textContent = value || "";
}

function renderUI(state) {
  latestState = state;
  const cluster = state.config.cluster || {};
  text("clusterTarget", cluster.user && cluster.host ? `${cluster.user}@${cluster.host}` : cluster.host || "Not configured");
  text("jobId", state.jobId || "None");
  text("latestStatus", state.latestStatus || "No status yet");
  text("statusLog", state.statusLog.length ? state.statusLog.join("\n") : "No status log yet.");
  text("runLog", state.runLog.length ? state.runLog.join("\n") : "No dashboard run log yet.");
  text("statusLogPath", state.paths.statusLog);
  text("runLogPath", state.paths.runLog);

  const queue = state.queue || {};
  const pending = (queue.PENDING || 0) + (queue.CONFIGURING || 0) + (queue.REQUEUE || 0) + (queue.SUSPENDED || 0);
  const running = (queue.RUNNING || 0) + (queue.COMPLETING || 0);
  const completed = queue.COMPLETED || 0;
  let failed = 0;
  let other = 0;
  for (const [s, n] of Object.entries(queue)) {
    if (["PENDING","CONFIGURING","REQUEUE","SUSPENDED","RUNNING","COMPLETING","COMPLETED"].includes(s)) continue;
    if (["BOOT_FAIL","CANCELLED","DEADLINE","FAILED","NODE_FAIL","OUT_OF_MEMORY","PREEMPTED","TIMEOUT"].includes(s)) {
      failed += n;
    } else {
      other += n;
    }
  }
  text("queuePending", pending || "-");
  text("queueRunning", running || "-");
  text("queueCompleted", completed || "-");
  text("queueFailed", failed || "-");
  text("queueOther", other || "-");

  const monitor = document.querySelector("#monitorState");
  monitor.classList.remove("state-running", "state-stopped", "state-error");
  if (state.process.running) {
    monitor.textContent = `Running (${state.process.pid})`;
    monitor.classList.add("state-running");
  } else if (state.process.returncode && state.process.returncode !== 0) {
    monitor.textContent = `Exited ${state.process.returncode}`;
    monitor.classList.add("state-error");
  } else {
    monitor.textContent = "Stopped";
    monitor.classList.add("state-stopped");
  }

  if (state.analysisProcess && state.analysisProcess.running) {
    const runLog = state.runLog || [];
    const recent = runLog.slice(-10).join("\n");
    if (recent) commandOutput.textContent = recent;
  }

  if (state.process.running) {
    const runLog = state.runLog || [];
    const recent = runLog.slice(-10).join("\n");
    if (recent) commandOutput.textContent = recent;
  }

  document.querySelectorAll(".phase").forEach((el) => {
    el.removeAttribute("data-active");
  });
  const phases = document.querySelectorAll(".phase");
  if (state.currentPhase) {
    if (state.currentPhase === "preprocess") phases[0].setAttribute("data-active", "");
    else if (state.currentPhase === "submit" || state.currentPhase === "monitor") phases[1].setAttribute("data-active", "");
    else if (state.currentPhase === "analysis" || state.currentPhase === "sync") phases[2].setAttribute("data-active", "");
  } else {
    if (state.preprocessProcess && state.preprocessProcess.running) phases[0].setAttribute("data-active", "");
    if (state.process.running) phases[1].setAttribute("data-active", "");
    if (state.analysisProcess && state.analysisProcess.running) phases[2].setAttribute("data-active", "");
  }

  document.querySelectorAll(".button-grid button").forEach((btn) => btn.removeAttribute("data-active"));
  if (state.process.running) {
    document.querySelector("#monitorBtn")?.setAttribute("data-active", "");
  }
  if (state.preprocessProcess && state.preprocessProcess.running) {
    document.querySelector("#preprocessBtn")?.setAttribute("data-active", "");
  }
  if (state.analysisProcess && state.analysisProcess.running) {
    document.querySelector("#analyzeBtn")?.setAttribute("data-active", "");
  }
}

function renderState(state) {
  latestState = state;
  writeForm(state.config);
  renderUI(state);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.message || payload.stderr || "Request failed");
  }
  return payload;
}

async function refresh() {
  const state = await api("/api/state");
  renderState(state);
}

async function refreshUI() {
  const state = await api("/api/state");
  renderUI(state);
}

async function saveConfig() {
  const payload = await api("/api/config", {
    method: "POST",
    body: JSON.stringify(readForm()),
  });
  renderState(payload.state);
  commandOutput.textContent = "Saved config.toml";
}

async function action(actionName) {
  const manualJobId = document.querySelector("#manualJobId").value.trim();
  buttons.forEach((button) => (button.disabled = true));
  try {
    await api("/api/config", { method: "POST", body: JSON.stringify(readForm()) });
    commandOutput.textContent = `Running ${actionName}...`;
    const payload = await api("/api/action", {
      method: "POST",
      body: JSON.stringify({ action: actionName, jobId: manualJobId }),
    });
    renderUI(payload.state);
    commandOutput.textContent = [
      payload.message,
      payload.stdout,
      payload.stderr,
    ].filter(Boolean).join("\n").trim() || "Done.";
  } catch (error) {
    commandOutput.textContent = error.message;
  } finally {
    buttons.forEach((button) => (button.disabled = false));
  }
}

function setTheme(dark) {
  const root = document.documentElement;
  root.classList.toggle("dark", dark);
  root.classList.toggle("light", !dark);
  localStorage.setItem("theme", dark ? "dark" : "light");
  document.querySelector("#themeBtn").textContent = dark ? "☀️" : "🌙";
}

function loadTheme() {
  const saved = localStorage.getItem("theme");
  if (saved === "dark") setTheme(true);
  else if (saved === "light") setTheme(false);
  else setTheme(window.matchMedia("(prefers-color-scheme: dark)").matches);
}

document.querySelector("#themeBtn").addEventListener("click", () => {
  setTheme(!document.documentElement.classList.contains("dark"));
});

document.querySelector("#refreshBtn").addEventListener("click", refresh);
document.querySelector("#saveBtn").addEventListener("click", saveConfig);
document.querySelector("#submitBtn").addEventListener("click", () => action("submit"));
document.querySelector("#statusBtn").addEventListener("click", () => action("status"));
document.querySelector("#monitorBtn").addEventListener("click", () => action("start-monitor"));
document.querySelector("#stopBtn").addEventListener("click", () => action("stop-monitor"));
document.querySelector("#syncBtn").addEventListener("click", () => action("sync"));
document.querySelector("#preprocessBtn").addEventListener("click", () => action("preprocess"));
document.querySelector("#analyzeBtn").addEventListener("click", () => action("analyze"));
document.querySelector("#stopAnalysisBtn").addEventListener("click", () => action("stop-analysis"));

loadTheme();
document.querySelector("#hpcPreset")?.addEventListener("change", applyHpcPreset);
form.elements["analysis.mode"]?.addEventListener("change", toggleModeFields);
form.elements["preprocess.mode"]?.addEventListener("change", togglePreprocessModeFields);
toggleModeFields();
togglePreprocessModeFields();
document.querySelector("#addJobScriptBtn")?.addEventListener("click", () => addJobScriptRow(""));
refresh();
setInterval(() => {
  if (!document.hidden && latestState) refreshUI();
}, 10000);
