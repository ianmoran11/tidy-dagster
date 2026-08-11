import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { CELL_ROLE_COMPILER_VERSION } from "./compiler-v02";
import {
  BASELINE_PROMPT_VERSION,
  SEMANTICS_PROMPT_VERSION,
  TRANSLATION_PROMPT_VERSION,
} from "./prompts";
import { digestCanonicalJson, sha256Bytes } from "./artifact-io";
import {
  implementationProvenanceSchema,
  type ImplementationProvenance,
} from "./evidence";

const execFileAsync = promisify(execFile);

const COMPONENT_SOURCES = [
  {
    role: "prompt" as const,
    path: "scripts/experiments/cell-role-pipeline/prompts.ts",
  },
  {
    role: "prompt" as const,
    path: "scripts/experiments/cell-role-pipeline/compact-context.ts",
  },
  {
    role: "parser" as const,
    path: "scripts/experiments/cell-role-pipeline/xml.ts",
  },
  {
    role: "parser" as const,
    path: "scripts/experiments/cell-role-pipeline/cell-role-sketch-v02.ts",
  },
  {
    role: "compiler" as const,
    path: "scripts/experiments/cell-role-pipeline/invariants.ts",
  },
  {
    role: "compiler" as const,
    path: "scripts/experiments/cell-role-pipeline/invariants-v02.ts",
  },
  {
    role: "compiler" as const,
    path: "scripts/experiments/cell-role-pipeline/compiler-v02.ts",
  },
  {
    role: "compiler" as const,
    path: "scripts/experiments/cell-role-pipeline/geometry-v02.ts",
  },
  {
    role: "compiler" as const,
    path: "scripts/experiments/cell-role-pipeline/pipeline.ts",
  },
  {
    role: "compiler" as const,
    path: "scripts/experiments/cell-role-pipeline/live.ts",
  },
  {
    role: "compiler" as const,
    path: "scripts/experiments/cell-role-pipeline/cli.ts",
  },
  {
    role: "compiler" as const,
    path: "scripts/experiments/run-cell-role-pipeline.ts",
  },
  {
    role: "compiler" as const,
    path: "scripts/experiments/cell-role-pipeline/live-state.ts",
  },
  {
    role: "compiler" as const,
    path: "scripts/experiments/cell-role-pipeline/live-pi-capability.ts",
  },
  { role: "compiler" as const, path: "src/server/llm/piClient.ts" },
  { role: "compiler" as const, path: "src/lib/recipe/schema.ts" },
  { role: "compiler" as const, path: "src/lib/executor/directions.ts" },
  {
    role: "compiler" as const,
    path: "src/lib/executor/relationshipResolution.ts",
  },
  {
    role: "compiler" as const,
    path: "src/lib/executor/executeRecipe.ts",
  },
  {
    role: "scorer" as const,
    path: "scripts/experiments/cell-role-pipeline/benchmark.ts",
  },
  { role: "scorer" as const, path: "scripts/benchmark/runner.ts" },
  { role: "scorer" as const, path: "scripts/benchmark/csv.ts" },
  {
    role: "scorer" as const,
    path: "scripts/benchmark/metrics/graphSimilarity.ts",
  },
  { role: "scorer" as const, path: "src/lib/address.ts" },
  {
    role: "report" as const,
    path: "scripts/experiments/cell-role-pipeline/report.ts",
  },
  {
    role: "report" as const,
    path: "scripts/experiments/cell-role-pipeline/plan.ts",
  },
  {
    role: "report" as const,
    path: "scripts/experiments/cell-role-pipeline/evidence.ts",
  },
  {
    role: "report" as const,
    path: "scripts/experiments/cell-role-pipeline/artifact-io.ts",
  },
  {
    role: "report" as const,
    path: "scripts/experiments/cell-role-pipeline/evidence-io.ts",
  },
  {
    role: "report" as const,
    path: "scripts/experiments/cell-role-pipeline/provenance.ts",
  },
  { role: "report" as const, path: "scripts/harvest/path-safety.ts" },
] as const;

export async function captureImplementationProvenance(
  repoRoot = process.cwd(),
): Promise<ImplementationProvenance> {
  const status = await git(repoRoot, [
    "status",
    "--porcelain=v1",
    "--untracked-files=all",
  ]);
  if (status.trim()) {
    throw new Error(
      `DIRTY_IMPLEMENTATION_TREE: commit or remove all tracked, staged, and untracked files before planning.\n${status.trim()}`,
    );
  }
  const gitCommit = await git(repoRoot, ["rev-parse", "HEAD"]);
  const gitTree = await git(repoRoot, ["rev-parse", "HEAD^{tree}"]);
  const confirmedTree = await git(repoRoot, [
    "rev-parse",
    `${gitCommit}^{tree}`,
  ]);
  if (gitTree !== confirmedTree)
    throw new Error("IMPLEMENTATION_TREE_MISMATCH");

  const sources = await Promise.all(
    COMPONENT_SOURCES.map(async (source) => {
      const bytes = await readFile(path.join(repoRoot, source.path));
      return {
        ...source,
        sha256: sha256Bytes(bytes),
        bytes: bytes.byteLength,
      };
    }),
  );
  return implementationProvenanceSchema.parse({
    schemaVersion: "cell-role-implementation-provenance-v1",
    gitCommit,
    gitTree,
    clean: true,
    versions: {
      plan: "cell-role-experiment-plan-v4",
      promptSemantics: SEMANTICS_PROMPT_VERSION,
      promptTranslation: TRANSLATION_PROMPT_VERSION,
      promptBaseline: BASELINE_PROMPT_VERSION,
      parser: "cell-role-sketch-parser-v2",
      compiler: CELL_ROLE_COMPILER_VERSION,
      scorer: "cell-role-benchmark-v1",
      report: "cell-role-report-v3",
    },
    sources: sources.sort((left, right) => left.path.localeCompare(right.path)),
  });
}

export async function verifyImplementationProvenance(
  provenance: ImplementationProvenance,
  repoRoot = process.cwd(),
): Promise<void> {
  implementationProvenanceSchema.parse(provenance);
  const expectedSources = COMPONENT_SOURCES.map((source) => source.path).sort();
  const actualSources = provenance.sources.map((source) => source.path).sort();
  if (JSON.stringify(actualSources) !== JSON.stringify(expectedSources)) {
    throw new Error("IMPLEMENTATION_SOURCE_SET_MISMATCH");
  }
  const status = await git(repoRoot, [
    "status",
    "--porcelain=v1",
    "--untracked-files=all",
  ]);
  if (status.trim()) throw new Error("DIRTY_IMPLEMENTATION_TREE");
  if (!(await isAncestor(repoRoot, provenance.gitCommit, "HEAD"))) {
    throw new Error("IMPLEMENTATION_COMMIT_NOT_ANCESTOR");
  }
  const commitTree = await git(repoRoot, [
    "rev-parse",
    `${provenance.gitCommit}^{tree}`,
  ]);
  if (commitTree !== provenance.gitTree)
    throw new Error("IMPLEMENTATION_TREE_MISMATCH");
  for (const source of provenance.sources) {
    const bytes = await readFile(path.join(repoRoot, source.path));
    if (
      bytes.byteLength !== source.bytes ||
      sha256Bytes(bytes) !== source.sha256
    ) {
      throw new Error(`IMPLEMENTATION_SOURCE_MISMATCH: ${source.path}`);
    }
  }
}

export async function verifyExactImplementationTree(
  provenance: ImplementationProvenance,
  repoRoot = process.cwd(),
): Promise<void> {
  implementationProvenanceSchema.parse(provenance);
  const currentTree = await git(repoRoot, ["rev-parse", "HEAD^{tree}"]);
  if (currentTree !== provenance.gitTree) {
    throw new Error("LIVE_IMPLEMENTATION_TREE_MISMATCH");
  }
}

export function implementationProvenanceDigest(
  provenance: ImplementationProvenance,
): string {
  return digestCanonicalJson(implementationProvenanceSchema.parse(provenance));
}

async function isAncestor(
  repoRoot: string,
  ancestor: string,
  descendant: string,
): Promise<boolean> {
  try {
    await execFileAsync(
      "git",
      ["-C", repoRoot, "merge-base", "--is-ancestor", ancestor, descendant],
      { encoding: "utf8", maxBuffer: 1024 * 1024 },
    );
    return true;
  } catch (error) {
    if ((error as { code?: number }).code === 1) return false;
    throw error;
  }
}

async function git(repoRoot: string, args: string[]): Promise<string> {
  const { stdout } = await execFileAsync("git", ["-C", repoRoot, ...args], {
    encoding: "utf8",
    maxBuffer: 1024 * 1024,
  });
  return stdout.trim();
}
