#!/usr/bin/env node
/*
 * npm wrapper for sns-addict.
 *
 * The product is implemented in Python because it uses Patchright/FastAPI.
 * This wrapper gives non-developers an npm install path by creating a private
 * venv under ~/.sns-addict/npm-venv, installing this checked-out package into
 * that venv, then delegating to the Python console script.
 */
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const packageRoot = path.resolve(__dirname, "..");
const pyproject = path.join(packageRoot, "pyproject.toml");
const venvDir = process.env.SNS_ADDICT_NPM_VENV || path.join(os.homedir(), ".sns-addict", "npm-venv");
const stampFile = path.join(venvDir, ".sns-addict-installed");
const isWindows = process.platform === "win32";
const pythonInVenv = path.join(venvDir, isWindows ? "Scripts" : "bin", isWindows ? "python.exe" : "python");
const cliInVenv = path.join(venvDir, isWindows ? "Scripts" : "bin", isWindows ? "sns-addict.exe" : "sns-addict");

function fail(message, error) {
  console.error(`[sns-addict npm] ${message}`);
  if (error && error.message) console.error(error.message);
  process.exit(1);
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: options.stdio || "inherit",
    env: process.env,
    cwd: options.cwd || packageRoot,
  });
  if (result.error) fail(`Failed to run ${command}`, result.error);
  if (result.status !== 0) {
    process.exit(result.status === null ? 1 : result.status);
  }
  return result;
}

function findPython() {
  const candidates = process.env.PYTHON ? [process.env.PYTHON] : ["python3", "python"];
  for (const candidate of candidates) {
    const result = spawnSync(candidate, ["--version"], { stdio: "ignore" });
    if (!result.error && result.status === 0) return candidate;
  }
  fail("Python 3.10+ is required. Install Python, then run sns-addict again.");
}

function packageSignature() {
  const stat = fs.statSync(pyproject);
  return `${packageRoot}\n${stat.mtimeMs}\n${stat.size}`;
}

function needsInstall() {
  if (!fs.existsSync(pyproject)) fail(`Missing pyproject.toml at ${pyproject}`);
  if (!fs.existsSync(pythonInVenv)) return true;
  if (!fs.existsSync(cliInVenv)) return true;
  if (!fs.existsSync(stampFile)) return true;
  return fs.readFileSync(stampFile, "utf8") !== packageSignature();
}

function ensureVenv() {
  if (!needsInstall()) return;
  const python = findPython();
  fs.mkdirSync(path.dirname(venvDir), { recursive: true });
  if (!fs.existsSync(pythonInVenv)) {
    console.error(`[sns-addict npm] Creating Python venv at ${venvDir}`);
    run(python, ["-m", "venv", venvDir]);
  }
  console.error("[sns-addict npm] Installing Python package into private venv...");
  run(pythonInVenv, ["-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"]);
  run(pythonInVenv, ["-m", "pip", "install", "--upgrade", packageRoot]);
  fs.writeFileSync(stampFile, packageSignature(), "utf8");
}

ensureVenv();
const result = spawnSync(cliInVenv, process.argv.slice(2), { stdio: "inherit", env: process.env });
if (result.error) fail("Failed to launch Python sns-addict CLI", result.error);
process.exit(result.status === null ? 1 : result.status);
