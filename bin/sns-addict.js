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
    env: options.env || process.env,
    cwd: options.cwd || packageRoot,
  });
  if (result.error) fail(`Failed to run ${command}`, result.error);
  if (result.status !== 0) {
    process.exit(result.status === null ? 1 : result.status);
  }
  return result;
}

function pythonMeetsMinimumVersion(candidate) {
  const result = spawnSync(
    candidate,
    ["-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"],
    { stdio: "ignore" },
  );
  return !result.error && result.status === 0;
}

function findPython() {
  const candidates = process.env.PYTHON ? [process.env.PYTHON] : ["python3", "python"];
  for (const candidate of candidates) {
    if (pythonMeetsMinimumVersion(candidate)) return candidate;
  }
  fail("Python 3.10+ is required. Install Python, set PYTHON=/path/to/python3.10+, then run sns-addict again.");
}

function packageSignature() {
  const stat = fs.statSync(pyproject);
  return `${packageRoot}\n${stat.mtimeMs}\n${stat.size}`;
}

function pathHasHermesAuxiliary(candidate) {
  if (!candidate) return false;
  return fs.existsSync(path.join(candidate, "agent", "auxiliary_client.py"));
}

function detectHermesSource() {
  const candidates = [
    process.env.SNS_ADDICT_HERMES_SOURCE,
    process.env.HERMES_AGENT_HOME,
    path.join(os.homedir(), "hermes-agent"),
    path.join(os.homedir(), ".hermes", "hermes-agent"),
  ];

  const whichHermes = spawnSync(process.platform === "win32" ? "where" : "which", ["hermes"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
  });
  if (whichHermes.status === 0 && whichHermes.stdout) {
    for (const line of whichHermes.stdout.split(/\r?\n/)) {
      const hermesBin = line.trim();
      if (!hermesBin) continue;
      candidates.push(path.resolve(path.dirname(hermesBin), "..", ".."));
      candidates.push(path.resolve(path.dirname(hermesBin), ".."));
    }
  }

  for (const candidate of candidates) {
    if (pathHasHermesAuxiliary(candidate)) return candidate;
  }
  return null;
}

function hermesPythonPaths(hermesSource) {
  const paths = [hermesSource];
  for (const venvName of [".venv", "venv"]) {
    const libDir = path.join(hermesSource, venvName, "lib");
    if (!fs.existsSync(libDir)) continue;
    for (const entry of fs.readdirSync(libDir)) {
      const sitePackages = path.join(libDir, entry, "site-packages");
      if (fs.existsSync(sitePackages)) paths.push(sitePackages);
    }
  }
  return paths;
}

function getVenvSitePackages() {
  const script = "import site; print(site.getsitepackages()[0])";
  const result = spawnSync(pythonInVenv, ["-c", script], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
  if (result.error || result.status !== 0) return null;
  return result.stdout.trim();
}

function configureHermesBridge() {
  const hermesSource = detectHermesSource();
  if (!hermesSource) return null;
  const sitePackages = getVenvSitePackages();
  if (!sitePackages) return hermesSource;
  const bridgeFile = path.join(sitePackages, "sns_addict_hermes_bridge.pth");
  // Use a .pth bridge instead of PYTHONPATH. .pth entries are appended after
  // the npm private venv's own site-packages, so the private venv keeps its
  // matching compiled wheels (pydantic-core, uvloop, etc.) while Hermes-only
  // dependencies can still be imported from the local Hermes install.
  fs.writeFileSync(bridgeFile, `${hermesPythonPaths(hermesSource).join("\n")}\n`, "utf8");
  return hermesSource;
}

function buildRuntimeEnv(hermesSource) {
  const env = { ...process.env };
  if (hermesSource) env.SNS_ADDICT_HERMES_SOURCE = hermesSource;
  return env;
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
const hermesSource = configureHermesBridge();
const runtimeEnv = buildRuntimeEnv(hermesSource);
const result = spawnSync(cliInVenv, process.argv.slice(2), { stdio: "inherit", env: runtimeEnv });
if (result.error) fail("Failed to launch Python sns-addict CLI", result.error);
process.exit(result.status === null ? 1 : result.status);
