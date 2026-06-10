#!/usr/bin/env node
/**
 * Hermes -> Codex safe dispatcher.
 *
 * Default mode is dry-run. Actual Codex execution is allowed only through this
 * wrapper, with a downgraded sandbox and a scrubbed environment.
 */

import { createHash } from "node:crypto";
import { spawn, execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(__dirname, "../../..");
export const DEFAULT_EVIDENCE_DIR = ".omx/logs/hermes-codex-dispatch";
export const CODEX_WRITE_SIGNOFF_ENV = "OWNER_SIGNOFF_CODEX_EXEC";

const MAX_TAIL = 6000;
const MODE_TO_SANDBOX = {
  read_only: "read-only",
  workspace_write: "workspace-write",
};

function usage() {
  return [
    "Usage:",
    "  node tools/hermes-agent/valuehire/vh-codex-dispatch.mjs --prompt 'review this repo' --json",
    "  node tools/hermes-agent/valuehire/vh-codex-dispatch.mjs --apply --mode read_only --prompt 'summarize status' --json",
    "  OWNER_SIGNOFF_CODEX_EXEC=approved node tools/hermes-agent/valuehire/vh-codex-dispatch.mjs --apply --mode workspace_write --prompt 'fix X' --json",
    "",
    "Default is dry-run. workspace_write execution requires OWNER_SIGNOFF_CODEX_EXEC=approved.",
  ].join("\n");
}

export function parseArgs(argv) {
  const parsed = {
    help: false,
    apply: false,
    json: false,
    prompt: "",
    mode: "read_only",
    timeoutSec: 600,
    evidenceDir: DEFAULT_EVIDENCE_DIR,
    evidenceFile: true,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    const next = argv[index + 1];
    if (token === "--help" || token === "-h") {
      parsed.help = true;
      continue;
    }
    if (token === "--apply") {
      parsed.apply = true;
      continue;
    }
    if (token === "--dry-run" || token === "--dry") {
      parsed.apply = false;
      continue;
    }
    if (token === "--json") {
      parsed.json = true;
      continue;
    }
    if (token === "--prompt" && next) {
      parsed.prompt = next;
      index += 1;
      continue;
    }
    if (token === "--mode" && next) {
      parsed.mode = next.replace(/-/g, "_");
      index += 1;
      continue;
    }
    if (token === "--timeout" && next) {
      parsed.timeoutSec = Number(next);
      index += 1;
      continue;
    }
    if (token === "--evidence-dir" && next) {
      parsed.evidenceDir = next;
      index += 1;
      continue;
    }
    if (token === "--no-evidence-file") {
      parsed.evidenceFile = false;
      continue;
    }
    throw new Error(`Unknown or incomplete argument: ${token}`);
  }

  return normalizeCodexOptions(parsed);
}

export function normalizeCodexOptions(raw = {}) {
  const prompt = String(raw.prompt ?? raw.task ?? "").trim();
  if (!prompt) throw new Error("prompt is required");

  const mode = String(raw.mode ?? "read_only").replace(/-/g, "_");
  if (!Object.prototype.hasOwnProperty.call(MODE_TO_SANDBOX, mode)) {
    throw new Error(`unsupported mode: ${mode}`);
  }

  const timeoutSecRaw = Number(raw.timeoutSec ?? raw.timeout_seconds ?? 600);
  const timeoutSec = Math.max(30, Math.min(3600, Number.isFinite(timeoutSecRaw) ? Math.floor(timeoutSecRaw) : 600));

  return {
    apply: Boolean(raw.apply),
    json: Boolean(raw.json),
    prompt,
    mode,
    sandbox: MODE_TO_SANDBOX[mode],
    timeoutSec,
    evidenceDir: raw.evidenceDir ?? DEFAULT_EVIDENCE_DIR,
    evidenceFile: raw.evidenceFile !== false,
  };
}

function resolveCodexBin({ env = process.env, execFileSyncFn = execFileSync } = {}) {
  const explicit = String(env.VALUEHIRE_CODEX_BIN ?? "").trim();
  if (explicit) return explicit;
  try {
    return execFileSyncFn("which", ["codex"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim() || "codex";
  } catch {
    return "codex";
  }
}

// workspace-write 폴백(예: Hermes 포지션 등록)이 ClickUp/Supabase 같은 외부 API 에
// 쓰려면 네트워크가 열려 있어야 한다. Codex 의 workspace-write 는 기본 네트워크 차단이라
// 이 한 가지 설정만 명시적으로 켠다. read-only(분석/리뷰) 폴백은 네트워크가 필요 없으므로 끈 채 둔다.
export const NETWORK_CONFIG_FLAG = "sandbox_workspace_write.network_access=true";

export function buildSafeCodexCommand(opts, deps = {}) {
  const normalized = normalizeCodexOptions(opts);
  const sandboxArgs = ["--sandbox", normalized.sandbox];
  if (normalized.sandbox === "workspace-write") {
    sandboxArgs.push("-c", NETWORK_CONFIG_FLAG);
  }
  const command = {
    cmd: resolveCodexBin(deps),
    args: [
      "exec",
      "-C",
      REPO_ROOT,
      ...sandboxArgs,
      "--ephemeral",
      "--ignore-user-config",
      normalized.prompt,
    ],
  };
  assertSafeCodexCommand(command);
  return {
    ...command,
    display: [path.basename(command.cmd), ...command.args.slice(0, -1), "<prompt>"].join(" "),
  };
}

export function assertSafeCodexCommand(command) {
  if (!command || typeof command.cmd !== "string" || !Array.isArray(command.args)) {
    throw new Error("codex command is invalid");
  }
  const args = command.args;
  if (path.basename(command.cmd) !== "codex" && !command.cmd.endsWith("/codex")) {
    throw new Error("command is not codex");
  }
  if (args[0] !== "exec") throw new Error("codex command must use exec");
  if (args.includes("--dangerously-bypass-approvals-and-sandbox")) {
    throw new Error("dangerous codex bypass flag is forbidden");
  }
  if (args.includes("--add-dir")) {
    throw new Error("codex add-dir is forbidden for Hermes dispatch");
  }
  const sandboxIndex = args.indexOf("--sandbox");
  if (sandboxIndex < 0) throw new Error("codex sandbox must be explicit");
  const sandbox = args[sandboxIndex + 1];
  if (!["read-only", "workspace-write"].includes(sandbox)) {
    throw new Error("codex sandbox must be read-only or workspace-write");
  }
  if (args.includes("danger-full-access")) {
    throw new Error("codex danger-full-access is forbidden");
  }
  // -c override 는 화이트리스트(네트워크 허용) 한 가지만 허용. 임의 config 주입 차단.
  for (let i = 0; i < args.length; i += 1) {
    if (args[i] === "-c") {
      if (args[i + 1] !== NETWORK_CONFIG_FLAG) {
        throw new Error(`codex -c override is restricted to ${NETWORK_CONFIG_FLAG}`);
      }
      if (sandbox !== "workspace-write") {
        throw new Error("network_access override is only allowed for workspace-write");
      }
    }
  }
  const cdIndex = args.indexOf("-C");
  if (cdIndex < 0 || path.resolve(String(args[cdIndex + 1] ?? "")) !== REPO_ROOT) {
    throw new Error("codex working root must be the Valuehire repo");
  }
  if (!args.includes("--ignore-user-config")) {
    throw new Error("codex must ignore user config for Hermes dispatch");
  }
  return true;
}

export function buildSafeCodexEnv(source = process.env) {
  const allowed = [
    "HOME",
    "PATH",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "TMPDIR",
    "CODEX_HOME",
    "VALUEHIRE_CODEX_BIN",
    CODEX_WRITE_SIGNOFF_ENV,
  ];
  const env = {};
  for (const key of allowed) {
    if (source[key] !== undefined) env[key] = source[key];
  }

  env.GIT_TERMINAL_PROMPT = "0";
  env.GIT_ASKPASS = "/usr/bin/false";
  env.SSH_ASKPASS = "/usr/bin/false";
  env.GCM_INTERACTIVE = "never";
  env.GIT_CONFIG_NOSYSTEM = "1";
  env.GIT_CONFIG_GLOBAL = "/dev/null";
  env.GIT_SSH_COMMAND = "ssh -F /dev/null -o BatchMode=yes -o IdentitiesOnly=yes -i /dev/null";
  return env;
}

function signoffOpen(env = process.env) {
  return String(env[CODEX_WRITE_SIGNOFF_ENV] ?? "").trim().toLowerCase() === "approved";
}

function tail(text, limit = MAX_TAIL) {
  const value = text || "";
  return value.length <= limit ? value : `...(truncated)...\n${value.slice(-limit)}`;
}

async function spawnAndCollect(command, { env, timeoutSec, spawnFn = spawn, cwd = REPO_ROOT } = {}) {
  assertSafeCodexCommand(command);
  return await new Promise((resolve) => {
    const child = spawnFn(command.cmd, command.args, {
      cwd,
      env,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try {
        child.kill("SIGTERM");
      } catch {
        // ignore
      }
      resolve({ exit_code: 124, timed_out: true, stdout, stderr });
    }, timeoutSec * 1000);

    child.stdout?.on("data", (chunk) => { stdout += Buffer.isBuffer(chunk) ? chunk.toString("utf8") : String(chunk); });
    child.stderr?.on("data", (chunk) => { stderr += Buffer.isBuffer(chunk) ? chunk.toString("utf8") : String(chunk); });
    child.on("error", (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ exit_code: 127, timed_out: false, stdout, stderr: `${stderr}${error.message}` });
    });
    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ exit_code: code ?? 1, timed_out: false, stdout, stderr });
    });
  });
}

async function writeEvidenceFile(record, { evidenceDir = DEFAULT_EVIDENCE_DIR, writeFileFn = writeFile, mkdirFn = mkdir } = {}) {
  const dir = path.resolve(REPO_ROOT, evidenceDir);
  await mkdirFn(dir, { recursive: true });
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  const file = path.join(dir, `${ts}.json`);
  await writeFileFn(file, JSON.stringify(record, null, 2) + "\n", "utf8");
  return file;
}

export async function runHermesCodexDispatch(rawOpts = {}, deps = {}) {
  const opts = normalizeCodexOptions(rawOpts);
  const command = deps.commandOverride ?? buildSafeCodexCommand(opts, deps);
  assertSafeCodexCommand(command);

  const evidence = {
    ok: false,
    mode: opts.apply ? "apply" : "dry-run",
    codex_mode: opts.mode,
    sandbox: opts.sandbox,
    prompt_sha256: createHash("sha256").update(opts.prompt).digest("hex"),
    prompt_chars: opts.prompt.length,
    allowed_command: command.display,
    side_effects: {
      shell: false,
      git_push: false,
      github_write: false,
      email_send: false,
      production_db_write: false,
    },
  };

  if (opts.apply && opts.mode === "workspace_write" && !signoffOpen(deps.env ?? process.env)) {
    return {
      ...evidence,
      error: `${CODEX_WRITE_SIGNOFF_ENV}=approved is required for workspace_write Codex execution`,
    };
  }

  if (!opts.apply) {
    return {
      ...evidence,
      ok: true,
      skipped: { reason: "dry_run" },
    };
  }

  const child = await spawnAndCollect(command, {
    spawnFn: deps.spawnFn ?? spawn,
    env: buildSafeCodexEnv(deps.env ?? process.env),
    timeoutSec: opts.timeoutSec,
    cwd: deps.cwd ?? REPO_ROOT,
  });

  const result = {
    ...evidence,
    ok: child.exit_code === 0,
    child: {
      exit_code: child.exit_code,
      timed_out: Boolean(child.timed_out),
      stdout_tail: tail(child.stdout),
      stderr_tail: tail(child.stderr),
    },
  };

  if (opts.evidenceFile !== false) {
    result.evidence_path = await writeEvidenceFile(result, {
      evidenceDir: opts.evidenceDir,
      writeFileFn: deps.writeFileFn ?? writeFile,
      mkdirFn: deps.mkdirFn ?? mkdir,
    });
  }

  return result;
}

function printHuman(result) {
  console.log(`Hermes Codex dispatch ${result.mode} (${result.codex_mode}, sandbox=${result.sandbox})`);
  console.log(`command=${result.allowed_command}`);
  if (result.skipped) console.log(`skipped=${result.skipped.reason}`);
  if (result.error) console.log(`error=${result.error}`);
  if (result.evidence_path) console.log(`evidence=${result.evidence_path}`);
  if (result.child) {
    console.log(`exit=${result.child.exit_code} timed_out=${result.child.timed_out}`);
    if (result.child.stdout_tail) console.log(result.child.stdout_tail);
    if (result.child.stderr_tail) console.error(result.child.stderr_tail);
  }
}

export async function main(argv = process.argv.slice(2), deps = {}) {
  const opts = parseArgs(argv);
  if (opts.help) {
    console.log(usage());
    return { ok: true, help: true };
  }
  const result = await runHermesCodexDispatch(opts, deps);
  if (opts.json) {
    console.log(JSON.stringify(result, null, 2));
  } else {
    printHuman(result);
  }
  if (!result.ok) process.exitCode = 2;
  return result;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error) => {
    console.error(`[vh-codex-dispatch] ${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  });
}
