const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const backendDir = path.resolve(__dirname, "backend");
const venvBin = process.platform === "win32"
  ? path.join(backendDir, "venv", "Scripts", "python.exe")
  : path.join(backendDir, "venv", "bin", "python3");

if (!fs.existsSync(venvBin)) {
  console.error(`[!] Python venv not found at: ${venvBin}`);
  console.error("[!] Run start.sh (Mac/Linux) or start.bat (Windows) first to create the venv.");
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
