import { TextDecoder } from "node:util";
import { SaxesParser } from "saxes";
import yauzl, { type Entry, type ZipFile } from "yauzl";
import type { RecipeV01 } from "../recipe/types.js";
import type { ParsedWorkbook } from "../workbook/types.js";

export type WorkerLimits = {
  timeoutMs: number;
  maxInputBytes: number;
  maxOutputBytes: number;
  maxWorkbookCompressedBytes: number;
  maxZipEntries: number;
  maxZipEntryUncompressedBytes: number;
  maxZipTotalUncompressedBytes: number;
  maxSheets: number;
  maxCells: number;
  maxMerges: number;
  maxMergeExpansionCells: number;
  maxSelectorCells: number;
  maxOutputRows: number;
};

export class LimitViolation extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

type StructureCounts = {
  sheets: number;
  cells: number;
  merges: number;
  expandedMergeCells: bigint;
};

/**
 * Inflate every entry through yauzl before ExcelJS sees the workbook. This
 * intentionally does not trust central-directory uncompressed sizes: actual
 * bytes are counted while streaming, and worksheet XML is structurally
 * counted in the same bounded pass.
 */
export async function preflightXlsxZip(
  bytes: Uint8Array,
  limits: WorkerLimits,
): Promise<void> {
  await preflightXlsxZipWithMode(bytes, limits, true);
}

/**
 * Validate ZIP paths, compression, declared and actual byte limits, entry
 * counts, and worksheet counts without expanding worksheet cell/merge
 * geometry. This is only for a caller that separately performs a bounded
 * direct worksheet parse under an immutable workbook digest.
 */
export async function preflightXlsxZipArchive(
  bytes: Uint8Array,
  limits: WorkerLimits,
): Promise<void> {
  await preflightXlsxZipWithMode(bytes, limits, false);
}

async function preflightXlsxZipWithMode(
  bytes: Uint8Array,
  limits: WorkerLimits,
  inspectWorksheetStructure: boolean,
): Promise<void> {
  if (bytes.byteLength > limits.maxWorkbookCompressedBytes)
    throw new LimitViolation(
      "WORKBOOK_COMPRESSED_LIMIT_EXCEEDED",
      `Workbook is ${bytes.byteLength} bytes; limit is ${limits.maxWorkbookCompressedBytes}.`,
    );

  const buffer = Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let zip: ZipFile | undefined;
  try {
    zip = await openZip(buffer);
    await scanZip(zip, limits, inspectWorksheetStructure);
  } catch (error) {
    if (error instanceof LimitViolation) throw error;
    throw new LimitViolation(
      "INVALID_XLSX_ZIP",
      error instanceof Error ? error.message : "Workbook ZIP is invalid.",
    );
  } finally {
    zip?.close();
  }
}

async function openZip(buffer: Buffer): Promise<ZipFile> {
  return await new Promise((resolve, reject) => {
    yauzl.fromBuffer(
      buffer,
      {
        autoClose: false,
        lazyEntries: true,
        // We verify actual streamed sizes ourselves so a forged undersized
        // central-directory value cannot bypass the configured limits.
        validateEntrySizes: false,
      },
      (error, zip) => {
        if (error || !zip) reject(error ?? new Error("ZIP did not open."));
        else resolve(zip);
      },
    );
  });
}

async function scanZip(
  zip: ZipFile,
  limits: WorkerLimits,
  inspectWorksheetStructure: boolean,
): Promise<void> {
  const structure: StructureCounts = {
    sheets: 0,
    cells: 0,
    merges: 0,
    expandedMergeCells: 0n,
  };
  let entries = 0;
  let actualTotal = 0;
  let declaredTotal = 0;

  await new Promise<void>((resolve, reject) => {
    let settled = false;
    const fail = (error: unknown) => {
      if (settled) return;
      settled = true;
      reject(error);
    };
    zip.once("error", fail);
    zip.once("end", () => {
      if (settled) return;
      settled = true;
      resolve();
    });
    zip.on("entry", (entry: Entry) => {
      void (async () => {
        entries += 1;
        if (entries > limits.maxZipEntries)
          throw new LimitViolation(
            "ZIP_ENTRY_LIMIT_EXCEEDED",
            `Workbook has more than ${limits.maxZipEntries} ZIP entries.`,
          );
        assertSupportedEntry(entry);
        declaredTotal += entry.uncompressedSize;
        if (entry.uncompressedSize > limits.maxZipEntryUncompressedBytes)
          throw new LimitViolation(
            "ZIP_ENTRY_SIZE_LIMIT_EXCEEDED",
            `ZIP entry ${entry.fileName} declares ${entry.uncompressedSize} bytes; per-entry limit is ${limits.maxZipEntryUncompressedBytes}.`,
          );
        if (declaredTotal > limits.maxZipTotalUncompressedBytes)
          throw new LimitViolation(
            "ZIP_TOTAL_SIZE_LIMIT_EXCEEDED",
            `ZIP entries declare more than ${limits.maxZipTotalUncompressedBytes} bytes.`,
          );

        if (entry.fileName.endsWith("/")) {
          zip.readEntry();
          return;
        }
        const worksheet = /^xl\/worksheets\/[^/]+\.xml$/i.test(entry.fileName);
        if (worksheet) {
          structure.sheets += 1;
          enforceStructureCounts(structure, limits);
        }
        const actualEntry = await scanEntry(
          zip,
          entry,
          limits,
          actualTotal,
          inspectWorksheetStructure && worksheet ? structure : undefined,
        );
        actualTotal += actualEntry;
        if (actualTotal > limits.maxZipTotalUncompressedBytes)
          throw new LimitViolation(
            "ZIP_TOTAL_SIZE_LIMIT_EXCEEDED",
            `ZIP entries expand to more than ${limits.maxZipTotalUncompressedBytes} bytes.`,
          );
        if (actualEntry !== entry.uncompressedSize)
          throw new LimitViolation(
            "ZIP_SIZE_METADATA_MISMATCH",
            `ZIP entry ${entry.fileName} expanded to ${actualEntry} bytes but declares ${entry.uncompressedSize}.`,
          );
        zip.readEntry();
      })().catch(fail);
    });
    zip.readEntry();
  });
}

function assertSupportedEntry(entry: Entry): void {
  const flags = entry.generalPurposeBitFlag;
  if ((flags & 0x0001) !== 0 || (flags & 0x0040) !== 0)
    throw new LimitViolation(
      "ENCRYPTED_ZIP_UNSUPPORTED",
      `Encrypted ZIP entry ${entry.fileName} is not supported.`,
    );
  if ((flags & 0x2020) !== 0)
    throw new LimitViolation(
      "UNSUPPORTED_ZIP_FEATURE",
      `ZIP entry ${entry.fileName} uses an unsupported feature flag.`,
    );
  if (entry.compressionMethod !== 0 && entry.compressionMethod !== 8)
    throw new LimitViolation(
      "UNSUPPORTED_ZIP_COMPRESSION",
      `ZIP entry ${entry.fileName} uses unsupported compression method ${entry.compressionMethod}.`,
    );
  if (
    entry.fileName.includes("\\") ||
    entry.fileName.startsWith("/") ||
    entry.fileName.split("/").some((part) => part === "..")
  )
    throw new LimitViolation(
      "UNSAFE_ZIP_ENTRY_PATH",
      "Workbook ZIP contains an unsafe entry path.",
    );
}

async function scanEntry(
  zip: ZipFile,
  entry: Entry,
  limits: WorkerLimits,
  totalBefore: number,
  structure?: StructureCounts,
): Promise<number> {
  const stream = await new Promise<NodeJS.ReadableStream>((resolve, reject) => {
    zip.openReadStream(entry, (error, value) => {
      if (error || !value)
        reject(error ?? new Error(`Could not read ${entry.fileName}.`));
      else resolve(value);
    });
  });
  const scanner = structure ? new WorksheetXmlScanner(structure, limits) : null;
  let count = 0;
  for await (const raw of stream) {
    const chunk = Buffer.isBuffer(raw) ? raw : Buffer.from(raw);
    count += chunk.byteLength;
    if (count > limits.maxZipEntryUncompressedBytes)
      throw new LimitViolation(
        "ZIP_ENTRY_SIZE_LIMIT_EXCEEDED",
        `ZIP entry ${entry.fileName} expands beyond ${limits.maxZipEntryUncompressedBytes} bytes.`,
      );
    if (totalBefore + count > limits.maxZipTotalUncompressedBytes)
      throw new LimitViolation(
        "ZIP_TOTAL_SIZE_LIMIT_EXCEEDED",
        `ZIP entries expand to more than ${limits.maxZipTotalUncompressedBytes} bytes.`,
      );
    scanner?.write(chunk);
  }
  scanner?.close();
  return count;
}

class WorksheetXmlScanner {
  private readonly decoder = new TextDecoder("utf-8", { fatal: true });
  private readonly parser = new SaxesParser({ xmlns: false });

  constructor(
    private readonly counts: StructureCounts,
    private readonly limits: WorkerLimits,
  ) {
    this.parser.on("opentag", (node) => {
      const localName = node.name.includes(":")
        ? node.name.slice(node.name.lastIndexOf(":") + 1)
        : node.name;
      if (localName === "c") this.counts.cells += 1;
      if (localName === "mergeCell") {
        this.counts.merges += 1;
        const ref = node.attributes.ref;
        if (typeof ref !== "string")
          throw new LimitViolation(
            "INVALID_WORKSHEET_XML",
            "Worksheet mergeCell has no string ref attribute.",
          );
        this.counts.expandedMergeCells += a1RangeArea(ref);
      }
      enforceStructureCounts(this.counts, this.limits);
    });
  }

  write(chunk: Uint8Array): void {
    this.parser.write(this.decoder.decode(chunk, { stream: true }));
  }

  close(): void {
    this.parser.write(this.decoder.decode());
    this.parser.close();
  }
}

function enforceStructureCounts(
  counts: StructureCounts,
  limits: WorkerLimits,
): void {
  if (counts.sheets > limits.maxSheets)
    throw new LimitViolation(
      "SHEET_LIMIT_EXCEEDED",
      `Workbook exceeds the ${limits.maxSheets} worksheet limit before parsing.`,
    );
  if (counts.cells > limits.maxCells)
    throw new LimitViolation(
      "CELL_LIMIT_EXCEEDED",
      `Workbook exceeds the ${limits.maxCells} explicit-cell limit before parsing.`,
    );
  if (counts.merges > limits.maxMerges)
    throw new LimitViolation(
      "MERGE_LIMIT_EXCEEDED",
      `Workbook exceeds the ${limits.maxMerges} merge limit before parsing.`,
    );
  if (counts.expandedMergeCells > BigInt(limits.maxMergeExpansionCells))
    throw new LimitViolation(
      "MERGE_EXPANSION_LIMIT_EXCEEDED",
      `Workbook merged ranges expand beyond ${limits.maxMergeExpansionCells} cells before parsing.`,
    );
}

function a1RangeArea(ref: string): bigint {
  const match = /^\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?$/i.exec(
    ref,
  );
  if (!match)
    throw new LimitViolation(
      "INVALID_WORKSHEET_XML",
      `Invalid worksheet merge range ${JSON.stringify(ref)}.`,
    );
  const startColumn = a1Column(match[1]);
  const endColumn = a1Column(match[3] ?? match[1]);
  const startRow = BigInt(match[2]);
  const endRow = BigInt(match[4] ?? match[2]);
  if (
    startColumn < 1n ||
    startRow < 1n ||
    endColumn < startColumn ||
    endRow < startRow
  )
    throw new LimitViolation(
      "INVALID_WORKSHEET_XML",
      `Invalid worksheet merge range ${JSON.stringify(ref)}.`,
    );
  return (endColumn - startColumn + 1n) * (endRow - startRow + 1n);
}

function a1Column(raw: string): bigint {
  let value = 0n;
  for (const character of raw.toUpperCase())
    value = value * 26n + BigInt(character.charCodeAt(0) - 64);
  return value;
}

export function enforceWorkbookLimits(
  workbook: ParsedWorkbook,
  limits: WorkerLimits,
): void {
  if (workbook.sheets.length > limits.maxSheets)
    throw new LimitViolation(
      "SHEET_LIMIT_EXCEEDED",
      `Workbook has ${workbook.sheets.length} sheets; limit is ${limits.maxSheets}.`,
    );
  let cells = 0;
  let merges = 0;
  for (const sheet of workbook.sheets) {
    cells += sheet.cells.length;
    merges += sheet.merges.length;
    if (cells > limits.maxCells)
      throw new LimitViolation(
        "CELL_LIMIT_EXCEEDED",
        `Workbook exceeds the ${limits.maxCells} cell limit.`,
      );
    if (merges > limits.maxMerges)
      throw new LimitViolation(
        "MERGE_LIMIT_EXCEEDED",
        `Workbook exceeds the ${limits.maxMerges} merge limit.`,
      );
  }
}

export function enforceRecipeSelectorLimit(
  recipe: RecipeV01,
  maxSelectorCells: number,
): void {
  let total = 0;
  for (const table of recipe.tables) {
    total += selectorCardinality(table.values.cells);
    for (const header of table.headers)
      total += selectorCardinality(header.cells);
    if (total > maxSelectorCells)
      throw new LimitViolation(
        "SELECTOR_LIMIT_EXCEEDED",
        `Recipe selectors declare more than ${maxSelectorCells} cells.`,
      );
  }
}

function selectorCardinality(
  selector: RecipeV01["tables"][number]["values"]["cells"],
): number {
  if (typeof selector === "string")
    return selector.includes(":") ? rangeArea(selector) : 1;
  if (Array.isArray(selector)) return selector.length;
  return (
    (selector.range ? rangeArea(selector.range) : 0) +
    (selector.cells?.length ?? 0)
  );
}

function rangeArea(range: string): number {
  const match = /^R(\d+)C(\d+):R(\d+)C(\d+)$/.exec(range);
  if (!match) return 0;
  return (
    (Math.abs(Number(match[3]) - Number(match[1])) + 1) *
    (Math.abs(Number(match[4]) - Number(match[2])) + 1)
  );
}
