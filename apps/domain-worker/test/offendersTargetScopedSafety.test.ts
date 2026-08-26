import { describe, expect, it } from "vitest";
import { mkdir, readFile, symlink, writeFile } from "node:fs/promises";
import { existsSync, rmSync, unlinkSync } from "node:fs";
import { execFileSync } from "node:child_process";
import {
  assertContained,
  assertSafeAncestors,
  beginTargetTransaction,
  computeNodeModulesClosure,
  digestFileRecords,
  readRegularFile,
  sha256,
  stable,
  verifyNodeModulesClosure,
} from "../../../scripts/offenders-target-scoped-safety.js";

const scratch = ".product-prototype/offenders-remaining-phase1/c2-safety-test";

describe("Offenders target-scoped filesystem safety", () => {
  it("rejects paths outside the isolated C2 root", () => {
    expect(() =>
      assertContained(
        "/tmp/escape",
        ".product-prototype/offenders-remaining-phase1/target-scoped-c2",
        "test",
      ),
    ).toThrow("UNSAFE_PATH");
  });
  it("uses canonical record order for root digests", () => {
    const a = [
      { path: "b", byteLength: 1, sha256: sha256("b") },
      { path: "a", byteLength: 1, sha256: sha256("a") },
    ];
    expect(digestFileRecords(a)).toBe(digestFileRecords([...a].reverse()));
  });
  it("restores prior trees and leaves no temp or backup residue", async () => {
    for (const mode of ["before-swap", "after-swap"]) {
      const path = `.product-prototype/offenders-remaining-phase1/target-scoped-c2/run-vitest-${mode}`;
      rmSync(path, { recursive: true, force: true });
      await mkdir(path, { recursive: true });
      await writeFile(`${path}/prior.txt`, "prior\n");
      const tx = await beginTargetTransaction(path, mode);
      await mkdir(tx.temporaryPath, { recursive: true });
      await writeFile(`${tx.temporaryPath}/new.txt`, "new\n");
      await expect(tx.commit()).rejects.toThrow(`INJECTED_FAILURE:${mode}`);
      expect((await readFile(`${path}/prior.txt`)).toString()).toBe("prior\n");
      expect(existsSync(tx.temporaryPath)).toBe(false);
      expect(existsSync(tx.backupPath)).toBe(false);
      rmSync(path, { recursive: true, force: true });
    }
  });
  it("atomically excludes concurrent transactions before mutation", async () => {
    const path =
      ".product-prototype/offenders-remaining-phase1/target-scoped-c2/run-vitest-concurrent";
    rmSync(path, { recursive: true, force: true });
    await mkdir(path, { recursive: true });
    await writeFile(`${path}/prior.txt`, "prior\n");
    const first = await beginTargetTransaction(path);
    await expect(beginTargetTransaction(path)).rejects.toThrow(
      "TRANSACTION_LOCKED",
    );
    expect((await readFile(`${path}/prior.txt`)).toString()).toBe("prior\n");
    await first.abort();
    expect(existsSync(first.lockPath)).toBe(false);
    expect(existsSync(first.temporaryPath)).toBe(false);
    rmSync(path, { recursive: true, force: true });
  });
  it("defines commit before cleanup and safely reaps owned stale backups", async () => {
    const path =
      ".product-prototype/offenders-remaining-phase1/target-scoped-c2/run-vitest-cleanup";
    rmSync(path, { recursive: true, force: true });
    await mkdir(path, { recursive: true });
    await writeFile(`${path}/prior.txt`, "prior\n");
    const first = await beginTargetTransaction(path, "cleanup-failure");
    await writeFile(`${first.temporaryPath}/new.txt`, "new\n");
    await expect(first.commit()).rejects.toThrow("POST_COMMIT_CLEANUP_FAILURE");
    expect((await readFile(`${path}/new.txt`)).toString()).toBe("new\n");
    expect(existsSync(`${path}/prior.txt`)).toBe(false);
    expect(existsSync(first.backupPath)).toBe(true);
    expect(existsSync(first.lockPath)).toBe(false);
    const second = await beginTargetTransaction(path);
    expect(existsSync(first.backupPath)).toBe(false);
    await second.abort();
    expect((await readFile(`${path}/new.txt`)).toString()).toBe("new\n");
    expect(existsSync(second.lockPath)).toBe(false);
    rmSync(path, { recursive: true, force: true });
  });
  it("detects added, removed, and drifted simulated dependency closure bytes", async () => {
    const root = `${scratch}/node_modules`;
    rmSync(scratch, { recursive: true, force: true });
    await mkdir(`${root}/pkg`, { recursive: true });
    await writeFile(`${root}/pkg/index.js`, "export const x=1;\n");
    await symlink("pkg/index.js", `${root}/entry`);
    const closure = computeNodeModulesClosure(root);
    const manifest = {
      schemaVersion: "tidy.node-modules-closure/v1",
      policy: {
        include: "all regular files and symlinks with regular in-root targets",
        excluded: [
          ".DS_Store (Finder metadata, never imported)",
          ".cache/** (Jiti/Pi compile cache outside project runtime imports)",
          ".vite/** (Vitest result cache, never imported by replay)",
        ],
      },
      root,
      regularFiles: closure.regularFiles,
      symlinks: closure.symlinks,
      totalBytes: closure.totalBytes,
      entryCount: closure.entries.length,
      merkleRoot: closure.merkleRoot,
      entries: closure.entries,
    };
    expect(() => verifyNodeModulesClosure(root, manifest)).not.toThrow();
    await writeFile(`${root}/pkg/index.js`, "drift\n");
    expect(() => verifyNodeModulesClosure(root, manifest)).toThrow(
      "NODE_MODULES_CLOSURE_DRIFT",
    );
    await writeFile(`${root}/pkg/index.js`, "export const x=1;\n");
    await writeFile(`${root}/added.js`, "added\n");
    expect(() => verifyNodeModulesClosure(root, manifest)).toThrow(
      "NODE_MODULES_CLOSURE_DRIFT",
    );
    rmSync(`${root}/added.js`);
    unlinkSync(`${root}/entry`);
    expect(() => verifyNodeModulesClosure(root, manifest)).toThrow(
      "NODE_MODULES_CLOSURE_DRIFT",
    );
    rmSync(scratch, { recursive: true, force: true });
  });
  it("rejects symlink ancestors and symlink/special inputs before reads", async () => {
    rmSync(scratch, { recursive: true, force: true });
    await mkdir(`${scratch}/real`, { recursive: true });
    await writeFile(`${scratch}/real/input.json`, "{}\n");
    await symlink("real", `${scratch}/linked`);
    expect(() =>
      assertSafeAncestors(`${scratch}/linked/input.json`, ".", "test-ancestor"),
    ).toThrow("SYMLINK_ANCESTOR");
    await symlink("real/input.json", `${scratch}/input-link.json`);
    await expect(
      readRegularFile(`${scratch}/input-link.json`, ".", "test-input"),
    ).rejects.toThrow("SYMLINK");
    execFileSync("mkfifo", [`${scratch}/input-fifo`]);
    await expect(
      readRegularFile(`${scratch}/input-fifo`, ".", "test-input"),
    ).rejects.toThrow("SPECIAL_INPUT");
    execFileSync("mkfifo", [`${scratch}/special-ancestor`]);
    expect(() =>
      assertSafeAncestors(
        `${scratch}/special-ancestor/child.json`,
        ".",
        "special-ancestor",
      ),
    ).toThrow("SPECIAL_ANCESTOR");
    const transactionLink =
      ".product-prototype/offenders-remaining-phase1/target-scoped-c2/run-vitest-symlink-root";
    const transactionSpecial =
      ".product-prototype/offenders-remaining-phase1/target-scoped-c2/run-vitest-special-root";
    if (existsSync(transactionLink)) unlinkSync(transactionLink);
    if (existsSync(transactionSpecial)) unlinkSync(transactionSpecial);
    await symlink("/tmp", transactionLink);
    await expect(beginTargetTransaction(transactionLink)).rejects.toThrow(
      "SYMLINK_ANCESTOR",
    );
    unlinkSync(transactionLink);
    execFileSync("mkfifo", [transactionSpecial]);
    await expect(beginTargetTransaction(transactionSpecial)).rejects.toThrow(
      "UNSAFE_FINAL_ROOT",
    );
    rmSync(transactionSpecial, { force: true });
    rmSync(scratch, { recursive: true, force: true });
  });
  it("preserves -0 in stable evidence", () =>
    expect(stable(-0)).not.toBe(stable(0)));
});
