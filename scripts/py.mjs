#!/usr/bin/env node
/**
 * Run a Python entry point with the project's interpreter.
 *
 * Without this, `npm run test` calls whatever `python` happens to be on PATH, which on a
 * fresh machine is the system interpreter with none of the project's packages installed.
 * The error that produces ("No module named pytest") sends people looking in the wrong
 * place. Prefer the project venv, fall back to PATH, and say which one was used.
 *
 *   node scripts/py.mjs -m pytest tests -q
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

const candidates = [
  join(root, ".venv", "Scripts", "python.exe"), // Windows
  join(root, ".venv", "bin", "python"),         // macOS / Linux
];

const python = candidates.find(existsSync) ?? (process.platform === "win32" ? "python" : "python3");

if (!candidates.some(existsSync)) {
  console.warn(
    `[py] no .venv found, falling back to "${python}" on PATH.\n` +
    `[py] create one with:  python -m venv .venv && ${python} -m pip install -r requirements.txt`
  );
}

const { status } = spawnSync(python, process.argv.slice(2), { stdio: "inherit", cwd: root });
process.exit(status ?? 1);
