const { spawn, spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");

const backendDir = path.resolve(__dirname, "backend");
const isWindows = process.platform === "win32";
const configuredBasePython = String(process.env.BACKEND_BASE_PYTHON || process.env.PYTHON || "").trim();
const configuredVenvDir = String(process.env.BACKEND_VENV_DIR || "").trim();
const canonicalVenvDir = path.join(backendDir, "venv");
const venvMarkerPath = path.join(backendDir, ".venv-dir");

function venvPythonPath(dir) {
  return isWindows
    ? path.join(dir, "Scripts", "python.exe")
    : path.join(dir, "bin", "python3");
}

function readPersistedVenvDir() {
  try {
    const value = fs.readFileSync(venvMarkerPath, "utf8").trim();
    if (!value) {
      return "";
    }
    return path.isAbsolute(value) ? value : path.join(backendDir, value);
  } catch {
    return "";
  }
}

function persistSelectedVenv(pythonBin) {
  const envDir = path.dirname(path.dirname(pythonBin));
  const relativeDir = path.relative(backendDir, envDir);
  if (!relativeDir || relativeDir.startsWith("..") || path.isAbsolute(relativeDir)) {
    return;
  }
  try {
    fs.writeFileSync(venvMarkerPath, `${relativeDir}\n`, "utf8");
  } catch {
    // Best effort only. Startup should still succeed if the marker cannot be updated.
  }
}

const explicitVenvCandidate = configuredVenvDir
  ? venvPythonPath(path.isAbsolute(configuredVenvDir) ? configuredVenvDir : path.join(backendDir, configuredVenvDir))
  : "";
const persistedVenvDir = readPersistedVenvDir();
const persistedVenvCandidate = persistedVenvDir ? venvPythonPath(persistedVenvDir) : "";

const venvCandidates = [
  explicitVenvCandidate,
  persistedVenvCandidate,
  ...(isWindows
    ? [
        path.join(backendDir, "venv", "Scripts", "python.exe"),
        path.join(backendDir, "venv-repair", "Scripts", "python.exe"),
        path.join(backendDir, ".venv", "Scripts", "python.exe"),
        path.join(backendDir, ".venv-repair", "Scripts", "python.exe"),
      ]
    : [
        path.join(backendDir, "venv", "bin", "python3"),
        path.join(backendDir, "venv-repair", "bin", "python3"),
        path.join(backendDir, ".venv", "bin", "python3"),
        path.join(backendDir, ".venv-repair", "bin", "python3"),
      ]),
].filter(Boolean);
const repairTargetDir = isWindows
  ? path.join(backendDir, "venv-repair")
  : path.join(backendDir, "venv-repair");

function canRun(command, args) {
  const result = spawnSync(command, args, {
    cwd: backendDir,
    env: process.env,
    stdio: "ignore",
  });
  return !result.error && result.status === 0;
}

function findBasePython() {
  const candidates = isWindows
    ? [
        [configuredBasePython, []],
        ["python", []],
        ["py", ["-3.11"]],
        ["py", ["-3"]],
      ]
    : [
        [configuredBasePython, []],
        ["python3", []],
        ["python", []],
      ];

  for (const [command, prefixArgs] of candidates) {
    if (!command) {
      continue;
    }
    if (canRun(command, [...prefixArgs, "-V"])) {
      return { command, prefixArgs };
    }
  }
  return null;
}

function rebuildBackendVenv(targetDir, basePython) {
  console.log(`[*] Preparing backend Python environment at ${targetDir}...`);
  try {
    fs.rmSync(targetDir, { recursive: true, force: true });
  } catch (error) {
    console.warn(`[*] Could not clear ${targetDir} cleanly (${error.code || error.message}). Trying a fresh repair path...`);
    targetDir = `${targetDir}-${Date.now()}`;
  }

  let result = spawnSync(
    basePython.command,
    [...basePython.prefixArgs, "-m", "venv", targetDir],
    {
      cwd: backendDir,
      env: process.env,
      stdio: "inherit",
    }
  );
  if (result.error || result.status !== 0) {
    return null;
  }

  const repairedBin = isWindows
    ? path.join(targetDir, "Scripts", "python.exe")
    : path.join(targetDir, "bin", "python3");

  result = spawnSync(repairedBin, ["-m", "pip", "install", "-q", "."], {
    cwd: backendDir,
    env: process.env,
    stdio: "inherit",
  });
  if (result.error || result.status !== 0) {
    return null;
  }
  return canRun(repairedBin, ["-V"]) ? repairedBin : null;
}

function ensureBackendVenv() {
  for (const candidate of venvCandidates) {
    if (fs.existsSync(candidate) && canRun(candidate, ["-V"])) {
      persistSelectedVenv(candidate);
      return candidate;
    }
  }

  const hadExisting = venvCandidates.some((candidate) => fs.existsSync(candidate));
  console.log(
    hadExisting
      ? "[*] Backend venv exists but is stale. Rebuilding it automatically..."
      : "[*] Backend venv is missing. Creating it automatically..."
  );

  const basePython = findBasePython();
  if (!basePython) {
    return null;
  }

  const preferredRebuildDir = persistedVenvDir || canonicalVenvDir;
  const rebuilt = rebuildBackendVenv(hadExisting ? preferredRebuildDir : canonicalVenvDir, basePython);
  if (rebuilt) {
    persistSelectedVenv(rebuilt);
  }
  return rebuilt;
}

const venvBin = ensureBackendVenv();

if (!venvBin) {
  console.error(`[!] Unable to prepare backend Python venv. Checked: ${venvCandidates.join(", ")}`);
  console.error("[!] Install Python 3.10-3.12 and rerun start.sh/start.bat if the repair could not complete.");
  process.exit(1);
}

const backendArgs = ["-m", "uvicorn", "main:app", "--timeout-keep-alive", "120"];
if (["1", "true", "yes"].includes(String(process.env.BACKEND_RELOAD || "").toLowerCase())) {
  backendArgs.push("--reload");
}

console.log(`[*] Starting backend with: ${venvBin} ${backendArgs.join(" ")}`);
const backendProc = spawn(venvBin, backendArgs, {
  cwd: backendDir,
  stdio: "inherit",
  env: process.env,
});

const cleanupAll = () => {
  if (backendProc && !backendProc.killed) {
    backendProc.kill();
  }
};

process.on("exit", cleanupAll);
process.on("SIGINT", () => {
  cleanupAll();
  process.exit(0);
});
process.on("SIGTERM", () => {
  cleanupAll();
  process.exit(0);
});

backendProc.on("exit", (code) => {
  cleanupAll();
  process.exit(code ?? 0);
});
