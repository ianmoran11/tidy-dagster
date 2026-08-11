import { createHash } from "node:crypto";
import {
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import ExcelJS from "exceljs";
import { afterEach, describe, expect, it } from "vitest";
import {
  MAX_RESPONSE_ENVELOPE_BYTES,
  normalizeWorkerResult,
  runWorker,
  serializeWorkerResult,
} from "../src/protocol/worker.js";

const roots: string[] = [];
afterEach(async () =>
  Promise.all(
    roots.splice(0).map((root) => rm(root, { recursive: true, force: true })),
  ),
);

function baseRequest() {
  return {
    protocolVersion: "tidy.worker/v1",
    requestId: "negative-test",
    operation: "execute-recipe-v01",
    inputs: [] as Array<{
      name: string;
      relativePath: string;
      contentDigest: string;
      byteLength: number;
    }>,
    parameters: {
      evidenceProfile: "m2-deterministic-parity-v1",
      csvMode: "recipe-aware",
    },
    limits: {
      timeoutMs: 30_000,
      maxInputBytes: 20_000_000,
      maxOutputBytes: 10_000_000,
      maxOutputFiles: 100,
      maxWarnings: 100,
      maxWorkbookCompressedBytes: 10_000_000,
      maxZipEntries: 1_000,
      maxZipEntryUncompressedBytes: 10_000_000,
      maxZipTotalUncompressedBytes: 20_000_000,
      maxSheets: 100,
      maxCells: 100_000,
      maxMerges: 10_000,
      maxMergeExpansionCells: 100_000,
      maxSelectorCells: 100_000,
      maxOutputRows: 100_000,
    },
  };
}

async function fixtureRoot() {
  const root = await mkdtemp(path.join(tmpdir(), "tidy-protocol-"));
  roots.push(root);
  const input = path.join(root, "input");
  const output = path.join(root, "output");
  await mkdir(input);
  await mkdir(output);
  return { root, input, output };
}

async function writeInput(
  root: string,
  relativePath: string,
  bytes: string | Uint8Array,
) {
  const target = path.join(root, relativePath);
  await mkdir(path.dirname(target), { recursive: true });
  const buffer = Buffer.from(bytes);
  await writeFile(target, buffer);
  return {
    relativePath,
    contentDigest: `sha256:${createHash("sha256").update(buffer).digest("hex")}`,
    byteLength: buffer.byteLength,
  };
}

async function expectCode(
  raw: unknown,
  code: string,
  suppliedRoots?: Awaited<ReturnType<typeof fixtureRoot>>,
) {
  const roots = suppliedRoots ?? (await fixtureRoot());
  const result = await runWorker(raw, roots.input, roots.output);
  expect(result).toMatchObject({ ok: false, error: { code } });
}

async function expectWorkbookCode(
  workbookBytes: Uint8Array,
  code: string,
  limitOverrides: Partial<ReturnType<typeof baseRequest>["limits"]> = {},
  recipeValue: unknown = {
    version: "0.1",
    sheet: "Data",
    tables: [
      { name: "t", values: { name: "v", cells: ["R1C1"] }, headers: [] },
    ],
  },
) {
  const roots = await fixtureRoot();
  const workbook = await writeInput(
    roots.input,
    "workbook.xlsx",
    workbookBytes,
  );
  const recipe = await writeInput(
    roots.input,
    "recipe.json",
    JSON.stringify(recipeValue),
  );
  const request = baseRequest();
  request.inputs = [
    { name: "workbook", ...workbook },
    { name: "recipe", ...recipe },
  ];
  request.limits = { ...request.limits, ...limitOverrides };
  await expectCode(request, code, roots);
  expect(await readdir(roots.output)).toEqual([]);
}

async function xlsxWithStructure(options: {
  sheets?: number;
  cells?: number;
  merges?: readonly string[];
}): Promise<Buffer> {
  const workbook = new ExcelJS.Workbook();
  for (
    let sheetIndex = 0;
    sheetIndex < (options.sheets ?? 1);
    sheetIndex += 1
  ) {
    const sheet = workbook.addWorksheet(
      sheetIndex === 0 ? "Data" : `Data${sheetIndex + 1}`,
    );
    for (let cell = 1; cell <= (options.cells ?? 0); cell += 1)
      sheet.getCell(cell, 1).value = cell;
    for (const merge of options.merges ?? []) sheet.mergeCells(merge);
  }
  return Buffer.from(await workbook.xlsx.writeBuffer());
}

function forgeLargestDeclaredUncompressedSize(bytes: Buffer): {
  bytes: Buffer;
  actualSize: number;
} {
  const forged = Buffer.from(bytes);
  let largest: { central: number; local: number; size: number } | undefined;
  for (let offset = 0; offset + 46 <= forged.length; offset += 1) {
    if (forged.readUInt32LE(offset) !== 0x02014b50) continue;
    const size = forged.readUInt32LE(offset + 24);
    const local = forged.readUInt32LE(offset + 42);
    if (!largest || size > largest.size)
      largest = { central: offset, local, size };
    offset +=
      45 +
      forged.readUInt16LE(offset + 28) +
      forged.readUInt16LE(offset + 30) +
      forged.readUInt16LE(offset + 32);
  }
  if (!largest || largest.size < 2) throw new Error("No forgeable ZIP entry.");
  forged.writeUInt32LE(1, largest.central + 24);
  forged.writeUInt32LE(1, largest.local + 22);
  return { bytes: forged, actualSize: largest.size };
}

describe("strict worker protocol", () => {
  it("normalizes schema-invalid and oversized response envelopes", () => {
    expect(
      normalizeWorkerResult({
        protocolVersion: "tidy.worker/v1",
        requestId: "bad",
        ok: true,
        outputs: [],
        warnings: [],
        extra: true,
      }),
    ).toMatchObject({
      ok: false,
      error: { code: "INVALID_WORKER_RESULT" },
    });

    const oversized = normalizeWorkerResult({
      protocolVersion: "tidy.worker/v1",
      requestId: "oversized",
      ok: true,
      outputs: [],
      warnings: Array.from({ length: 10_000 }, () => ({
        code: "W",
        message: "x".repeat(1_024),
      })),
    });
    expect(oversized).toMatchObject({
      ok: false,
      error: { code: "RESPONSE_LIMIT_EXCEEDED" },
    });
    expect(
      Buffer.byteLength(serializeWorkerResult(oversized), "utf8"),
    ).toBeLessThanOrEqual(MAX_RESPONSE_ENVELOPE_BYTES);
  });

  it.each([
    [
      "unknown version",
      { ...baseRequest(), protocolVersion: "tidy.worker/v2" },
    ],
    ["unknown operation", { ...baseRequest(), operation: "parse-workbook" }],
    ["unknown field", { ...baseRequest(), surprise: true }],
    [
      "unknown parameter",
      {
        ...baseRequest(),
        parameters: {
          evidenceProfile: "m2-deterministic-parity-v1",
          surprise: true,
        },
      },
    ],
  ])("rejects %s", async (_label, request) =>
    expectCode(request, "INVALID_REQUEST"),
  );

  it.each([
    "/tmp/workbook.xlsx",
    "../workbook.xlsx",
    "inputs/../workbook.xlsx",
    "inputs\\workbook.xlsx",
  ])("rejects unsafe path %s", async (relativePath) => {
    const roots = await fixtureRoot();
    const request = baseRequest();
    request.inputs = [
      {
        name: "workbook",
        relativePath,
        contentDigest: `sha256:${"0".repeat(64)}`,
        byteLength: 0,
      },
      {
        name: "recipe",
        relativePath: "inputs/recipe.json",
        contentDigest: `sha256:${"0".repeat(64)}`,
        byteLength: 0,
      },
    ];
    await expectCode(request, "UNSAFE_PATH", roots);
  });

  it("rejects symlink inputs", async () => {
    const roots = await fixtureRoot();
    await writeFile(path.join(roots.root, "outside.xlsx"), "outside");
    await mkdir(path.join(roots.input, "inputs"));
    await symlink(
      path.join(roots.root, "outside.xlsx"),
      path.join(roots.input, "inputs/workbook.xlsx"),
    );
    const recipe = await writeInput(roots.input, "inputs/recipe.json", "{}");
    const request = baseRequest();
    request.inputs = [
      {
        name: "workbook",
        relativePath: "inputs/workbook.xlsx",
        contentDigest: `sha256:${"0".repeat(64)}`,
        byteLength: 0,
      },
      { name: "recipe", ...recipe },
    ];
    await expectCode(request, "SYMLINK_PATH", roots);
  });

  it("rejects digest drift", async () => {
    const roots = await fixtureRoot();
    const workbook = await writeInput(
      roots.input,
      "inputs/workbook.xlsx",
      "not-xlsx",
    );
    const recipe = await writeInput(roots.input, "inputs/recipe.json", "{}");
    const request = baseRequest();
    request.inputs = [
      {
        name: "workbook",
        ...workbook,
        contentDigest: `sha256:${"0".repeat(64)}`,
        byteLength: workbook.byteLength,
      },
      { name: "recipe", ...recipe },
    ];
    await expectCode(request, "DIGEST_MISMATCH", roots);
  });

  it("rejects malformed recipe JSON", async () => {
    const roots = await fixtureRoot();
    const workbook = await writeInput(
      roots.input,
      "inputs/workbook.xlsx",
      await import("node:fs/promises").then(({ readFile }) =>
        readFile("fixtures/workbooks/simple-crosstab.xlsx"),
      ),
    );
    const recipe = await writeInput(roots.input, "inputs/recipe.json", "{");
    const request = baseRequest();
    request.inputs = [
      { name: "workbook", ...workbook },
      { name: "recipe", ...recipe },
    ];
    await expectCode(request, "MALFORMED_RECIPE_JSON", roots);
  });

  it("rejects malformed workbook", async () => {
    const roots = await fixtureRoot();
    const workbook = await writeInput(
      roots.input,
      "inputs/workbook.xlsx",
      "not-xlsx",
    );
    const recipe = await writeInput(
      roots.input,
      "inputs/recipe.json",
      JSON.stringify({
        version: "0.1",
        sheet: "X",
        tables: [
          { name: "t", values: { name: "v", cells: ["R1C1"] }, headers: [] },
        ],
      }),
    );
    const request = baseRequest();
    request.inputs = [
      { name: "workbook", ...workbook },
      { name: "recipe", ...recipe },
    ];
    await expectCode(request, "INVALID_XLSX_ZIP", roots);
  });

  it("rejects a missing sheet and output-size overflow", async () => {
    const roots = await fixtureRoot();
    const workbookBytes = await import("node:fs/promises").then(
      ({ readFile }) => readFile("fixtures/workbooks/simple-crosstab.xlsx"),
    );
    const workbook = await writeInput(
      roots.input,
      "inputs/workbook.xlsx",
      workbookBytes,
    );
    const recipe = await writeInput(
      roots.input,
      "inputs/recipe.json",
      JSON.stringify({
        version: "0.1",
        sheet: "Absent",
        tables: [
          { name: "t", values: { name: "v", cells: ["R1C1"] }, headers: [] },
        ],
      }),
    );
    const request = baseRequest();
    request.inputs = [
      { name: "workbook", ...workbook },
      { name: "recipe", ...recipe },
    ];
    await expectCode(request, "SHEET_NOT_FOUND", roots);

    const capRoots = await fixtureRoot();
    const health = {
      ...baseRequest(),
      operation: "health",
      inputs: [],
      parameters: {},
      limits: { ...baseRequest().limits, timeoutMs: 1, maxOutputBytes: 1 },
    };
    await expectCode(health, "OUTPUT_LIMIT_EXCEEDED", capRoots);
    expect(await readdir(capRoots.output)).toEqual([]);
  });

  it("rejects equal, nested, and canonically overlapping roots", async () => {
    const roots = await fixtureRoot();
    const health = {
      ...baseRequest(),
      operation: "health",
      inputs: [],
      parameters: {},
    };
    await expectCode(health, "OVERLAPPING_ROOTS", {
      ...roots,
      output: roots.input,
    });
    const nested = path.join(roots.input, "nested-output");
    await mkdir(nested);
    await expectCode(health, "OVERLAPPING_ROOTS", { ...roots, output: nested });

    const alias = path.join(roots.root, "input-alias");
    await symlink(roots.input, alias);
    await expectCode(health, "UNSAFE_ROOT", { ...roots, output: alias });
  });

  it("rejects intermediate symlinks and declared byte-length drift before reading", async () => {
    const roots = await fixtureRoot();
    const outside = path.join(roots.root, "outside");
    await mkdir(outside);
    await writeFile(path.join(outside, "workbook.xlsx"), "outside");
    await symlink(outside, path.join(roots.input, "inputs"));
    const request = baseRequest();
    request.inputs = [
      {
        name: "workbook",
        relativePath: "inputs/workbook.xlsx",
        contentDigest: `sha256:${"0".repeat(64)}`,
        byteLength: 7,
      },
      {
        name: "recipe",
        relativePath: "recipe.json",
        contentDigest: `sha256:${"0".repeat(64)}`,
        byteLength: 0,
      },
    ];
    await expectCode(request, "SYMLINK_PATH", roots);

    const lengthRoots = await fixtureRoot();
    const workbook = await writeInput(
      lengthRoots.input,
      "workbook.xlsx",
      "bytes",
    );
    const recipe = await writeInput(lengthRoots.input, "recipe.json", "{}");
    request.inputs = [
      { name: "workbook", ...workbook, byteLength: workbook.byteLength + 1 },
      { name: "recipe", ...recipe },
    ];
    await expectCode(request, "BYTE_LENGTH_MISMATCH", lengthRoots);
  });

  it("enforces declared compressed size and ZIP central-directory entry limits", async () => {
    const workbookBytes = await import("node:fs/promises").then(
      ({ readFile }) => readFile("fixtures/workbooks/simple-crosstab.xlsx"),
    );
    const recipeBytes = await import("node:fs/promises").then(({ readFile }) =>
      readFile("fixtures/recipes/simple-crosstab.json"),
    );
    for (const [code, limit] of [
      [
        "WORKBOOK_COMPRESSED_LIMIT_EXCEEDED",
        { maxWorkbookCompressedBytes: workbookBytes.byteLength - 1 },
      ],
      ["ZIP_ENTRY_LIMIT_EXCEEDED", { maxZipEntries: 1 }],
    ] as const) {
      const roots = await fixtureRoot();
      const workbook = await writeInput(
        roots.input,
        "workbook.xlsx",
        workbookBytes,
      );
      const recipe = await writeInput(roots.input, "recipe.json", recipeBytes);
      const request = baseRequest();
      request.inputs = [
        { name: "workbook", ...workbook },
        { name: "recipe", ...recipe },
      ];
      request.limits = { ...request.limits, ...limit };
      await expectCode(request, code, roots);
      expect(await readdir(roots.output)).toEqual([]);
    }
  });

  it("counts actual inflated bytes when ZIP metadata understates a large entry", async () => {
    const original = await readFile("fixtures/workbooks/simple-crosstab.xlsx");
    const forged = forgeLargestDeclaredUncompressedSize(original);
    await expectWorkbookCode(forged.bytes, "ZIP_ENTRY_SIZE_LIMIT_EXCEEDED", {
      maxZipEntryUncompressedBytes: forged.actualSize - 1,
    });
  });

  it.each([
    ["SHEET_LIMIT_EXCEEDED", { sheets: 2 }, { maxSheets: 1 }],
    ["CELL_LIMIT_EXCEEDED", { cells: 2 }, { maxCells: 1 }],
    ["MERGE_LIMIT_EXCEEDED", { merges: ["A1:B1", "A2:B2"] }, { maxMerges: 1 }],
    [
      "MERGE_EXPANSION_LIMIT_EXCEEDED",
      { merges: ["A1:Z100"] },
      { maxMergeExpansionCells: 10 },
    ],
  ] as const)(
    "enforces %s while streaming worksheet XML before ExcelJS",
    async (code, workbookOptions, limitOverrides) => {
      await expectWorkbookCode(
        await xlsxWithStructure(workbookOptions),
        code,
        limitOverrides,
      );
    },
  );

  it("rejects predicted rows and warning growth before execution", async () => {
    const workbook = await xlsxWithStructure({ cells: 2 });
    await expectWorkbookCode(
      workbook,
      "OUTPUT_ROW_LIMIT_EXCEEDED",
      { maxOutputRows: 1 },
      {
        version: "0.1",
        sheet: "Data",
        tables: [
          {
            name: "rows",
            values: { name: "v", cells: { range: "R1C1:R100C1" } },
            headers: [],
          },
        ],
      },
    );

    await expectWorkbookCode(
      workbook,
      "WARNING_LIMIT_EXCEEDED",
      { maxWarnings: 10 },
      {
        version: "0.1",
        sheet: "Data",
        tables: [
          {
            name: "warnings",
            values: { name: "v", cells: { range: "R1C1:R100C1" } },
            headers: Array.from({ length: 50 }, (_, index) => ({
              name: `h${index}`,
              direction: "N",
              cells: ["R1C1"],
              required: true,
            })),
          },
        ],
      },
    );
  });

  it("rejects Unicode output names that exceed portable path bytes", async () => {
    await expectWorkbookCode(
      await xlsxWithStructure({ cells: 1 }),
      "OUTPUT_PATH_LIMIT_EXCEEDED",
      {},
      {
        version: "0.1",
        sheet: "Data",
        tables: [
          {
            name: "😀".repeat(32),
            values: { name: "v", cells: ["R1C1"] },
            headers: [],
          },
        ],
      },
    );
  });

  it("rejects pre-existing undeclared output state", async () => {
    const roots = await fixtureRoot();
    await writeFile(path.join(roots.output, "undeclared.txt"), "x");
    const health = {
      ...baseRequest(),
      operation: "health",
      inputs: [],
      parameters: {},
    };
    await expectCode(health, "OUTPUT_ROOT_NOT_EMPTY", roots);
  });

  it("publishes the parity-locked sheet summary when requested", async () => {
    const fixture = await fixtureRoot();
    const workbookBytes = await readFile(
      path.join(process.cwd(), "fixtures/workbooks/simple-crosstab.xlsx"),
    );
    const recipeBytes = await readFile(
      path.join(process.cwd(), "fixtures/recipes/simple-crosstab.json"),
    );
    const workbook = await writeInput(
      fixture.input,
      "workbook.xlsx",
      workbookBytes,
    );
    const recipe = await writeInput(fixture.input, "recipe.json", recipeBytes);
    const request = {
      ...baseRequest(),
      parameters: { ...baseRequest().parameters, includeSummary: true },
    };
    request.inputs = [
      { name: "workbook", ...workbook },
      { name: "recipe", ...recipe },
    ];
    const result = await runWorker(request, fixture.input, fixture.output);
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("Expected summary execution to succeed");
    expect(result.outputs.map((output) => output.name)).toContain(
      "sheet-summary.json",
    );
    const summary = JSON.parse(
      await readFile(path.join(fixture.output, "sheet-summary.json"), "utf8"),
    );
    const reference = JSON.parse(
      await readFile(
        path.join(
          process.cwd(),
          "fixtures/reference-summary/historical-v1.json",
        ),
        "utf8",
      ),
    );
    expect(summary).toEqual(reference.cases[1].summaries[0]);
  });

  it("advertises the parity-locked historical summary contract", async () => {
    const roots = await fixtureRoot();
    const request = {
      ...baseRequest(),
      operation: "capabilities",
      inputs: [],
      parameters: {},
    };
    const result = await runWorker(request, roots.input, roots.output);
    expect(result.ok).toBe(true);
    if (result.ok) {
      const capabilities = JSON.parse(
        (
          await import("node:fs/promises").then(({ readFile }) =>
            readFile(path.join(roots.output, "capabilities.json"), "utf8"),
          )
        ).toString(),
      );
      expect(capabilities.summary).toEqual({
        supported: true,
        contract: "tidy-sheet-summary-v1",
        options: { checked: true, allOtherOptions: "historical-defaults" },
        historicalReferenceDigest:
          "sha256:0d0dca23d4f08204cbf02d6cc841fbd5ba15df32aeab92da77a0f91f5ff49c70",
      });
    }
  });
});
