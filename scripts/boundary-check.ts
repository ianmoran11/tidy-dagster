import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const sourceWorktree = new RegExp(
  ["tidy", "cell|tidy", "bank|sem", "bla|justice"].join(""),
  "i",
);
const pathCall =
  /\b(?:readFile|readFileSync|open|writeFile|copyFile|cp|rename|rm|readdir|stat|lstat|realpath)\s*\(\s*["'`]([^"'`]+)["'`]/g;
const processCall =
  /\b(?:spawn|spawnSync|execFile|execFileSync)\s*\(([^;\n]*)\)/g;

export function scanSource(file: string, source: string): string[] {
  const failures: string[] = [];
  for (const match of source.matchAll(
    /(?:from\s+|import\s*\(|require\s*\()\s*["']([^"']+)["']/g,
  )) {
    const specifier = match[1];
    if (
      specifier &&
      (path.isAbsolute(specifier) || sourceWorktree.test(specifier))
    )
      failures.push(`${file}: forbidden runtime import ${specifier}`);
  }
  for (const match of source.matchAll(pathCall)) {
    const argument = match[1];
    if (
      argument &&
      (path.isAbsolute(argument) ||
        argument === ".." ||
        argument.startsWith("../") ||
        sourceWorktree.test(argument))
    )
      failures.push(
        `${file}: forbidden filesystem/process path argument ${argument}`,
      );
  }
  for (const call of source.matchAll(processCall)) {
    for (const literal of call[1]?.matchAll(/["'`]([^"'`]+)["'`]/g) ?? []) {
      const argument = literal[1];
      if (
        argument &&
        (path.isAbsolute(argument) ||
          argument === ".." ||
          argument.startsWith("../") ||
          sourceWorktree.test(argument))
      )
        failures.push(
          `${file}: forbidden filesystem/process path argument ${argument}`,
        );
    }
  }
  if (source.includes("/" + "Users/") || source.includes("C:" + "\\Users\\"))
    failures.push(`${file}: absolute workstation path`);
  return failures;
}

const executableSourceExtension = /\.(?:[cm]?js|ts)$/;

export async function runBoundaryCheck(
  roots = ["apps", "scripts", "tools"],
): Promise<string[]> {
  const failures: string[] = [];
  for (const root of roots) {
    for (const file of await walk(root)) {
      if (!executableSourceExtension.test(file)) continue;
      failures.push(...scanSource(file, await readFile(file, "utf8")));
    }
  }
  return failures;
}

if (
  process.argv[1] &&
  fileURLToPath(import.meta.url) === path.resolve(process.argv[1])
) {
  const failures = await runBoundaryCheck();
  if (failures.length) {
    console.error(failures.join("\n"));
    process.exitCode = 1;
  } else {
    console.log(
      "boundary-check: no sibling source-worktree imports or path arguments",
    );
  }
}

async function walk(root: string): Promise<string[]> {
  const entries = await readdir(root, { withFileTypes: true });
  const files: string[] = [];
  for (const entry of entries) {
    const file = path.join(root, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(file)));
    else files.push(file);
  }
  return files;
}
