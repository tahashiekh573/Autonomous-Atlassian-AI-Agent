// Starts the API (port 8765) and the dashboard (port 5173) together: `npm start`.
// Ctrl+C stops both. No extra dependencies.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const isWin = process.platform === "win32";
const uvicorn = join(root, ".venv", isWin ? "Scripts" : "bin", isWin ? "uvicorn.exe" : "uvicorn");

if (!existsSync(uvicorn)) {
  console.error(`Python environment not found (${uvicorn}).\nRun: python -m venv .venv && .venv\\Scripts\\pip install -e ".[dev]"`);
  process.exit(1);
}
if (!existsSync(join(root, "web", "node_modules"))) {
  console.error("Dashboard dependencies missing. Run: npm run setup");
  process.exit(1);
}

const procs = [
  { name: "api", color: "\x1b[36m", cmd: `"${uvicorn}"`, args: ["app.main:app", "--reload", "--port", "8765"], cwd: root },
  { name: "web", color: "\x1b[35m", cmd: "npm", args: ["--prefix", "web", "run", "dev"], cwd: root },
];

const children = procs.map(({ name, color, cmd, args, cwd }) => {
  const child = spawn(cmd, args, { cwd, shell: true, env: { ...process.env, API_URL: "http://127.0.0.1:8765" } });
  const prefix = `${color}[${name}]\x1b[0m `;
  const pipe = (stream) => stream.on("data", (data) => {
    for (const line of data.toString().split(/\r?\n/)) if (line.trim()) process.stdout.write(prefix + line + "\n");
  });
  pipe(child.stdout);
  pipe(child.stderr);
  child.on("exit", (code) => {
    console.log(`${prefix}exited (${code ?? "signal"}) — stopping everything.`);
    shutdown(code ?? 0);
  });
  return child;
});

let stopping = false;
function shutdown(code) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (child.exitCode !== null) continue;
    if (isWin) spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    else child.kill("SIGTERM");
  }
  setTimeout(() => process.exit(code), 500);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
console.log("Starting API on http://127.0.0.1:8765 and dashboard on http://localhost:5173 … (Ctrl+C to stop)");
