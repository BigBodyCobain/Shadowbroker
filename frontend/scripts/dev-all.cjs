const { spawn } = require("child_process");
const path = require("path");

const frontendDir = path.resolve(__dirname, "..");
const backendLauncher = path.resolve(frontendDir, "..", "start-backend.js");
const nextBin = require.resolve("next/dist/bin/next");

/** @type {import("child_process").ChildProcess[]} */
const children = [];

function start(label, file, args, cwd) {
  const child = spawn(file, args, {
    cwd,
    env: process.env,
    stdio: "inherit",
    windowsHide: false,
  });

  child.on("error", (error) => {
    console.error(`[${label}] failed to start:`, error);
    shutdown(1);
  });

  child.on("exit", (code, signal) => {
    if (signal || (code ?? 0) !== 0) {
      console.error(`[${label}] exited with ${signal ?? code}`);
      shutdown(typeof code === "number" ? code : 1);
      return;
    }
    shutdown(0);
  });

  children.push(child);
  return child;
}

let shuttingDown = false;

function shutdown(exitCode) {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  for (const child of children) {
    if (!child.killed) {
      child.kill();
    }
  }
  process.exit(exitCode);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

start(
  "frontend",
  process.execPath,
  [nextBin, "dev", "--hostname", "127.0.0.1", "--port", "3000"],
  frontendDir,
);
start("backend", process.execPath, [backendLauncher], frontendDir);
