import { describe, expect, it } from "vitest";
import { scanSource } from "./boundary-check.js";

describe("repository boundary scanner", () => {
  it("rejects sibling worktree imports and filesystem/process probes", () => {
    const sibling = "../" + "tidy" + "cell/private.json";
    expect(scanSource("probe.ts", `readFile('${sibling}')`)).toEqual([
      `probe.ts: forbidden filesystem/process path argument ${sibling}`,
    ]);
    expect(scanSource("probe.ts", `spawn('node', ['${sibling}'])`)).toEqual([
      `probe.ts: forbidden filesystem/process path argument ${sibling}`,
    ]);
    expect(scanSource("probe.ts", `import value from '${sibling}'`)).toEqual([
      `probe.ts: forbidden runtime import ${sibling}`,
    ]);
  });

  it("allows ordinary internal imports and allowlisted documentation provenance", () => {
    expect(
      scanSource("app.ts", "import { x } from '../../packages/x.js'"),
    ).toEqual([]);
    expect(
      scanSource(
        "docs/source-evidence.md",
        "Source: ../tidycell at a pinned commit",
      ),
    ).toEqual([]);
  });
});
