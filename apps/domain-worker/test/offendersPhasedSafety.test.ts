import {
  mkdtemp,
  mkdir,
  readFile,
  realpath,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "vitest";
import {
  assertContained,
  assertDistinctPaths,
  assertSafeComponent,
  beginDirectoryTransaction,
  countJsonNodes,
  OFFENDERS_PHASED_ROUTED_RUNTIME_SOURCE_PATHS,
  readBoundedJson,
  sha256,
  verifyPinnedFileClosure,
} from "../../../scripts/offenders-phased-safety.js";

async function temporary(): Promise<string> {
  return realpath(await mkdtemp(join(tmpdir(), "offenders-phased-safety-")));
}

describe("Offenders phased filesystem and external-pin safety", () => {
  test("rejects traversal, unsafe components, and overlapping paths", () => {
    expect(() => assertSafeComponent("../escape", "family")).toThrow(
      /UNSAFE_PATH_COMPONENT/,
    );
    expect(() => assertContained("/tmp/outside", "/tmp/root", "input")).toThrow(
      /UNSAFE_PATH/,
    );
    expect(() =>
      assertDistinctPaths([
        ["a", "/tmp/root/a"],
        ["b", "/tmp/root/a/b"],
      ]),
    ).toThrow(/OVERLAPPING_PATHS/);
  });

  test("bounded JSON requires exact external bytes", async () => {
    const root = await temporary();
    try {
      const path = join(root, "value.json");
      const bytes = Buffer.from('{"ok":true}\n');
      await writeFile(path, bytes);
      await expect(
        readBoundedJson(path, {
          maxBytes: 100,
          maxNodes: 5,
          pin: { path, byteLength: bytes.length, sha256: sha256(bytes) },
        }),
      ).resolves.toMatchObject({ value: { ok: true } });
      await expect(
        readBoundedJson(path, { maxBytes: 5, maxNodes: 5 }),
      ).rejects.toThrow(/JSON_BYTE_LIMIT/);
      await expect(
        readBoundedJson(path, {
          maxBytes: 100,
          maxNodes: 5,
          pin: { path, byteLength: bytes.length, sha256: "sha256:wrong" },
        }),
      ).rejects.toThrow(/EXTERNAL_INPUT_PIN_MISMATCH/);
      expect(() => countJsonNodes({ a: { b: { c: true } } }, 2)).toThrow(
        /JSON_NODE_LIMIT/,
      );
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  test("requires an exact digest-pinned runtime source closure", async () => {
    const pins = await Promise.all(
      OFFENDERS_PHASED_ROUTED_RUNTIME_SOURCE_PATHS.map(async (path) => {
        const bytes = await readFile(path);
        return { path, byteLength: bytes.length, sha256: sha256(bytes) };
      }),
    );
    await expect(
      verifyPinnedFileClosure(
        pins,
        OFFENDERS_PHASED_ROUTED_RUNTIME_SOURCE_PATHS,
      ),
    ).resolves.toBeUndefined();
    await expect(
      verifyPinnedFileClosure(
        pins.slice(1),
        OFFENDERS_PHASED_ROUTED_RUNTIME_SOURCE_PATHS,
      ),
    ).rejects.toThrow(/RUNTIME_SOURCE_CLOSURE_PATH_MISMATCH/);
    await expect(
      verifyPinnedFileClosure(
        [{ ...pins[0], sha256: "sha256:wrong" }, ...pins.slice(1)],
        OFFENDERS_PHASED_ROUTED_RUNTIME_SOURCE_PATHS,
      ),
    ).rejects.toThrow(/RUNTIME_SOURCE_PIN_DRIFT/);
  });

  test("transaction rejects a symlinked output boundary before writing", async () => {
    const root = await temporary();
    const outside = await temporary();
    try {
      const linked = join(root, "linked");
      await symlink(outside, linked);
      await expect(
        beginDirectoryTransaction(join(linked, "run-test"), linked, undefined),
      ).rejects.toThrow(/UNSAFE_OUTPUT_ANCESTOR/);
      await expect(readFile(join(outside, "run-test"))).rejects.toThrow();
    } finally {
      await rm(root, { recursive: true, force: true });
      await rm(outside, { recursive: true, force: true });
    }
  });

  test.each(["before-swap", "after-swap"])(
    "atomic swap restores the prior tree after an injected %s failure",
    async (point) => {
      const root = await temporary();
      try {
        const finalPath = join(root, "run-test");
        await mkdir(finalPath);
        await writeFile(join(finalPath, "sentinel.txt"), "prior\n");
        const transaction = await beginDirectoryTransaction(
          finalPath,
          root,
          point,
        );
        await mkdir(transaction.temporaryPath, { recursive: true });
        await writeFile(join(transaction.temporaryPath, "new.txt"), "new\n");
        await expect(transaction.commit()).rejects.toThrow(/INJECTED_FAILURE/);
        await expect(
          readFile(join(finalPath, "sentinel.txt"), "utf8"),
        ).resolves.toBe("prior\n");
        await expect(
          readFile(join(finalPath, "new.txt"), "utf8"),
        ).rejects.toThrow();
      } finally {
        await rm(root, { recursive: true, force: true });
      }
    },
  );
});
