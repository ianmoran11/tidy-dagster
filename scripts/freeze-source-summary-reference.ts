#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  cpSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  realpathSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";

const project = path.resolve(import.meta.dirname, "..");
const schemaVersion = "tidy.historical-source-summary-reference/v1";
const caseVersion = "tidy.historical-source-summary-reference-case/v1";
const timestampPattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const expectedCases = ["multi-table", "simple-crosstab", "sparse-headers"];

type Args = { bundle: string; output: string; recordedAt: string };

function main(): void {
  const args = parseArgs(process.argv.slice(2));
  if (process.platform !== "darwin" || !pathExists("/usr/bin/sandbox-exec"))
    throw new Error("Historical summary reference requires macOS sandbox-exec");
  verifyBundle(args.bundle);
  const bundle = realpathSync(args.bundle);
  const output = path.resolve(args.output);
  if (output === bundle || output.startsWith(`${bundle}${path.sep}`))
    throw new Error("Reference output must be outside the immutable bundle");
  const commit = parseObject(readFileSync(path.join(bundle, "COMMITTED.json")));
  const discovery = parseObject(
    readFileSync(path.join(bundle, "DISCOVERY.json")),
  );
  if (commit.closureManifestDigest !== discovery.manifestDigest)
    throw new Error("Bundle evidence identities differ");
  const tidycell = asObjectArray(discovery.sources).find(
    (source) => source.sourceSystem === "tidycell",
  );
  if (!tidycell) throw new Error("Copied TidyCell source is missing");
  const items = asObjectArray(tidycell.items);
  const itemByPath = new Map(
    items.map((item) => [String(item.relativePath), item]),
  );
  const copiedLock = itemByPath.get("package-lock.json");
  if (!copiedLock) throw new Error("Copied TidyCell lockfile is missing");

  const replayParent = path.join(project, ".source-replays");
  mkdirSync(replayParent, { recursive: true, mode: 0o700 });
  const replay = mkdtempSync(path.join(replayParent, "summary-reference-"));
  try {
    const root = path.join(replay, "tidycell");
    cpSync(path.join(bundle, "sources/tidycell"), root, {
      recursive: true,
      dereference: false,
      errorOnExist: true,
    });
    const before = treeDigest(root);
    const rawOutput = path.join(replay, "source-summary-output.json");
    const runner = path.join(replay, "source-summary-reference-runner.ts");
    cpSync(
      path.join(project, "scripts/source-summary-reference-runner.ts"),
      runner,
      {
        errorOnExist: true,
      },
    );
    const profile = seatbeltProfile(replay, project);
    const profilePath = path.join(replay, "source-summary-reference.sb");
    writeFileSync(profilePath, profile, { mode: 0o600, flag: "wx" });
    mkdirSync(path.join(replay, "home"), { mode: 0o700 });
    mkdirSync(path.join(replay, "tmp"), { mode: 0o700 });
    const node = realpathSync(process.execPath);
    const tsx = path.join(project, "node_modules/tsx/dist/loader.mjs");
    const child = spawnSync(
      "/usr/bin/sandbox-exec",
      ["-f", profilePath, node, "--import", tsx, runner],
      {
        cwd: replay,
        env: {
          PATH: `${path.dirname(node)}:/usr/bin:/bin`,
          HOME: path.join(replay, "home"),
          TMPDIR: path.join(replay, "tmp"),
          TZ: "UTC",
          LANG: "C.UTF-8",
          LC_ALL: "C.UTF-8",
          CI: "1",
          NO_COLOR: "1",
          TSX_TSCONFIG_PATH: path.join(root, "tsconfig.json"),
          TIDY_SOURCE_REFERENCE_ROOT: root,
          TIDY_SOURCE_REFERENCE_OUTPUT: rawOutput,
          NODE_OPTIONS: "--max-old-space-size=1024 --disable-proto=throw",
        },
        encoding: "utf8",
        maxBuffer: 1024 * 1024,
        timeout: 10 * 60 * 1000,
      },
    );
    if (child.status !== 0) {
      const diagnostic = `${child.stdout ?? ""}\n${child.stderr ?? ""}`.slice(
        -16_384,
      );
      throw new Error(
        `Historical summary reference failed (${child.status}):\n${diagnostic}`,
      );
    }
    const raw = parseObject(readFileSync(rawOutput));
    const rawCases = asObjectArray(raw.cases);
    if (
      rawCases.length !== expectedCases.length ||
      rawCases.some((entry, index) => entry.caseId !== expectedCases[index])
    )
      throw new Error("Historical summary reference returned unexpected cases");
    const cases = rawCases.map((entry) => {
      const caseId = String(entry.caseId);
      const workbookRelativePath = String(entry.workbookRelativePath);
      if (workbookRelativePath !== `fixtures/workbooks/${caseId}.xlsx`)
        throw new Error(
          "Historical summary case has an unexpected workbook path",
        );
      const sourceItem = itemByPath.get(workbookRelativePath);
      if (!sourceItem || sourceItem.role !== "fixture")
        throw new Error("Historical summary workbook lacks copied custody");
      if (!Array.isArray(entry.summaries) || entry.summaries.length < 1)
        throw new Error("Historical summary case has no summaries");
      const sheetNames = entry.summaries.map((summary: unknown) => {
        if (!summary || typeof summary !== "object" || Array.isArray(summary))
          throw new Error("Historical summary is not an object");
        const sheet = (summary as Record<string, unknown>).sheet;
        if (typeof sheet !== "string" || !sheet)
          throw new Error("Summary sheet is invalid");
        return sheet;
      });
      if (new Set(sheetNames).size !== sheetNames.length)
        throw new Error("Historical summary sheets are duplicated");
      const semanticCase = {
        caseId,
        workbookRelativePath,
        workbookContentDigest: String(sourceItem.contentDigest),
        sheetCount: entry.summaries.length,
        summaries: entry.summaries,
      };
      return {
        ...semanticCase,
        caseDigest: domainDigest(caseVersion, semanticCase),
      };
    });
    const after = treeDigest(root);
    if (before !== after)
      throw new Error(
        "Historical summary execution changed copied source bytes",
      );
    verifyBundle(bundle);

    const harnessDigest = domainDigest(
      "tidy.historical-source-summary-reference-harness/v1",
      {
        files: [
          "scripts/freeze-source-summary-reference.ts",
          "scripts/source-summary-reference-runner.ts",
          "contracts/reference-summary/v1/reference.schema.json",
          "package.json",
          "package-lock.json",
          ".node-version",
          "node_modules/tsx/dist/loader.mjs",
        ].map((relativePath) => ({
          relativePath,
          contentDigest: sha256File(path.join(project, relativePath)),
        })),
        nodeExecutableDigest: sha256File(node),
        normalizedSeatbeltProfileDigest: sha256Bytes(
          Buffer.from(profile.replaceAll(replay, "<REPLAY_ROOT>")),
        ),
      },
    );
    const semantic = {
      schemaVersion,
      closureManifestDigest: String(discovery.manifestDigest),
      copyCommitDigest: String(commit.commitDigest),
      referenceKind: "sheet-summary-default-options",
      summaryOptions: {
        checked: true,
        allOtherOptions: "historical-defaults",
      },
      cases,
      sourceTreeDigestBefore: before,
      sourceTreeDigestAfter: after,
      harnessDigest,
      runtime: {
        nodeVersion: process.version,
        tsxVersion: String(
          parseObject(
            readFileSync(path.join(project, "node_modules/tsx/package.json")),
          ).version,
        ),
        tidyDagsterLockDigest: sha256File(
          path.join(project, "package-lock.json"),
        ),
        copiedSourceLockDigest: String(copiedLock.contentDigest),
        dependencyRuntime: "tidy-dagster-locked-node-modules",
      },
      bundleVerifiedBefore: true,
      bundleVerifiedAfter: true,
      relocated: true,
      runtimeSiblingDependencyUsed: false,
      networkIsolationEnforced: true,
      candidateImplementationUsed: false,
      independentReview: false,
      parityEstablished: false,
      limitations: [
        "This is a historical-source reference generated under implementing-agent self-review.",
        "The reference uses Tidy Dagster's locked node_modules rather than installing the copied full lockfile.",
        "Candidate parity and independent review are recorded separately.",
      ],
      recordedAt: args.recordedAt,
    };
    const record = {
      ...semantic,
      referenceDigest: domainDigest(schemaVersion, semantic),
    };
    writeAtomic(output, Buffer.from(`${canonicalJson(record)}\n`));
    process.stdout.write(
      `${canonicalJson({
        ok: true,
        referenceDigest: record.referenceDigest,
        caseCount: cases.length,
        sheetCount: cases.reduce((total, entry) => total + entry.sheetCount, 0),
        parityEstablished: false,
      })}\n`,
    );
  } finally {
    rmSync(replay, { recursive: true, force: true });
  }
}

function parseArgs(argv: string[]): Args {
  const values = new Map<string, string>();
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (!flag?.startsWith("--") || !value || values.has(flag))
      throw new Error("Invalid historical summary reference arguments");
    values.set(flag, value);
  }
  if (values.size !== 3) throw new Error("Reference requires three arguments");
  const bundle = values.get("--bundle");
  const output = values.get("--output");
  const recordedAt = values.get("--recorded-at");
  if (
    !bundle ||
    !output ||
    !recordedAt ||
    !timestampPattern.test(recordedAt) ||
    Number.isNaN(Date.parse(recordedAt)) ||
    new Date(recordedAt).toISOString() !== `${recordedAt.slice(0, -1)}.000Z`
  )
    throw new Error("Reference arguments are incomplete or invalid");
  return { bundle, output, recordedAt };
}

function verifyBundle(bundle: string): void {
  const result = spawnSync(
    path.join(project, ".venv/bin/tidy-source-closure-copy"),
    ["verify", "--directory", bundle],
    {
      cwd: project,
      env: { PATH: "/usr/bin:/bin", LANG: "C", LC_ALL: "C", TZ: "UTC" },
      encoding: "utf8",
      maxBuffer: 1024 * 1024,
      timeout: 120_000,
    },
  );
  if (result.status !== 0)
    throw new Error(`Source bundle verification failed: ${result.stderr}`);
}

function treeDigest(root: string): string {
  const files: Array<{
    relativePath: string;
    byteLength: number;
    contentDigest: string;
  }> = [];
  const pending = [root];
  while (pending.length) {
    const directory = pending.pop()!;
    for (const name of readdirSync(directory).sort()) {
      if (name === "node_modules") continue;
      const absolute = path.join(directory, name);
      const info = lstatSync(absolute);
      if (info.isSymbolicLink())
        throw new Error("Reference source contains a symlink");
      if (info.isDirectory()) pending.push(absolute);
      else if (info.isFile())
        files.push({
          relativePath: path.relative(root, absolute).split(path.sep).join("/"),
          byteLength: info.size,
          contentDigest: sha256File(absolute),
        });
      else throw new Error("Reference source contains a special file");
    }
  }
  files.sort((left, right) =>
    compareText(left.relativePath, right.relativePath),
  );
  return domainDigest("tidy.source-closure-replay-tree/v1", files);
}

function seatbeltProfile(replay: string, projectRoot: string): string {
  const quote = (value: string) =>
    value.replaceAll("\\", "\\\\").replaceAll('"', '\\"');
  return `(version 1)
(deny default)
(import "system.sb")
(allow process*)
(allow signal (target same-sandbox))
(allow sysctl-read)
(allow mach-lookup
  (global-name "com.apple.system.notification_center")
  (global-name "com.apple.system.opendirectoryd.libinfo"))
(allow file-read-metadata)
(allow file-read*
  (subpath "/System")
  (subpath "/usr")
  (subpath "/bin")
  (subpath "/sbin")
  (subpath "/Library")
  (subpath "/private/etc")
  (subpath "/private/var/db")
  (subpath "/dev")
  (subpath "/opt/homebrew")
  (subpath "${quote(path.join(projectRoot, "node_modules"))}")
  (literal "${quote(path.join(projectRoot, "package.json"))}")
  (subpath "${quote(replay)}"))
(allow file-write* (subpath "${quote(replay)}"))
(deny network*)
`;
}

function writeAtomic(target: string, data: Buffer): void {
  const parent = path.dirname(target);
  mkdirSync(parent, { recursive: true });
  if (pathExists(target)) throw new Error("Reference output already exists");
  const temporary = path.join(
    parent,
    `.${path.basename(target)}.${process.pid}.tmp`,
  );
  writeFileSync(temporary, data, { mode: 0o600, flag: "wx" });
  renameSync(temporary, target);
}

function parseObject(data: Buffer): Record<string, any> {
  const value = JSON.parse(data.toString("utf8"));
  if (!value || Array.isArray(value) || typeof value !== "object")
    throw new Error("Expected a JSON object");
  return value as Record<string, any>;
}

function asObjectArray(value: unknown): Array<Record<string, any>> {
  if (
    !Array.isArray(value) ||
    value.some(
      (entry) => !entry || typeof entry !== "object" || Array.isArray(entry),
    )
  )
    throw new Error("Expected an object array");
  return value as Array<Record<string, any>>;
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string")
    return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("Non-finite canonical number");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object")
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => compareText(left, right))
      .map(([key, entry]) => `${JSON.stringify(key)}:${canonicalJson(entry)}`)
      .join(",")}}`;
  throw new Error("Unsupported canonical JSON value");
}

function compareText(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function domainDigest(domain: string, value: unknown): string {
  return sha256Bytes(
    Buffer.concat([
      Buffer.from(`${domain}\0`),
      Buffer.from(canonicalJson(value)),
    ]),
  );
}

function sha256File(file: string): string {
  return sha256Bytes(readFileSync(file));
}

function sha256Bytes(data: Buffer): string {
  return `sha256:${createHash("sha256").update(data).digest("hex")}`;
}

function pathExists(value: string): boolean {
  try {
    lstatSync(value);
    return true;
  } catch {
    return false;
  }
}

main();
