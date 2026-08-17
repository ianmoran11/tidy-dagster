import { buildSemanticCellFormattingFacts } from "../catalog/format-aware-region-catalog-v2.js";
import {
  buildRoleAwareSemanticRegionCatalog,
  buildSemanticCellDataFacts,
  compileRoleAwareSemanticTableMap,
  correctionCandidateSubset,
} from "../catalog/role-aware-region-catalog-v5.js";
import { parseSemanticTableMapJson } from "../catalog/semantic-map-v1.js";
import {
  buildSemanticMapV13CorrectionPrompt,
  buildSemanticMapV13Prompt,
  formatSemanticMapCorrectionDiagnostics,
} from "../prompt/semanticMapV13.js";
import { extractCellFeatures } from "../prompt/ml/featuresV1.js";
import {
  canonicalDigest,
  encodeModelFeatures,
  MAX_ML_CELLS,
  ML_FEATURE_SCHEMA,
  ML_PACKAGE_ID,
  validateMlFeatureBatch,
  validateMlHints,
} from "../prompt/ml/contractsV1.js";
import { appendMlHintExtension } from "../prompt/ml/semanticMapHintsV1.js";
import {
  buildCompactContextSnapshot,
  buildCompactSemanticContext,
} from "../context/compactContext.js";
import { executeRecipe } from "../executor/executeRecipe.js";
import { buildGeometryEvidence } from "../executor/geometryEvidence.js";
import { rowsToCsv } from "../export/formatters.js";
import { resolveRecipeSelectors } from "../recipe/resolveSelectors.js";
import { buildSheetSummary } from "../summary/buildSheetSummary.js";
import { parseWorkbook } from "../workbook/parseWorkbook.js";
import {
  enforceRecipeSelectorLimit,
  enforceWorkbookLimits,
  preflightXlsxZip,
} from "./resourceLimits.js";
import type { RecipeV01 } from "../recipe/types.js";
import type { ResolvedRecipeSelectors } from "../recipe/resolveSelectors.js";
import {
  failure,
  jsonBytes,
  ProtocolError,
  publish,
  readVerifiedInput,
  type RootContext,
  type WorkerResult,
  type ProducedFile,
} from "./prototypeRuntime.js";

export type PrototypeWorkerRequest = Omit<
  import("./worker.js").WorkerRequest,
  "operation" | "parameters"
> & {
  operation:
    | "extract-ml-features-v1"
    | "prepare-semantic-map-v13"
    | "interpret-semantic-map-v13";
  parameters: {
    sheet?: string;
    correction?: boolean;
    evidenceProfile?: "m1-simple-v1" | "m2-deterministic-parity-v1";
    includeSummary?: boolean;
    includeCompactContext?: boolean;
    includeRegionCatalog?: boolean;
    csvMode?: "recipe-aware";
  };
};

export async function prepareSemanticMapV13(
  request: PrototypeWorkerRequest,
  roots: RootContext,
  inputRoot: string,
): Promise<WorkerResult> {
  if (
    !request.parameters.sheet ||
    request.parameters.evidenceProfile !== undefined ||
    request.parameters.includeSummary !== undefined ||
    request.parameters.includeCompactContext !== undefined ||
    request.parameters.includeRegionCatalog !== undefined ||
    request.parameters.csvMode !== undefined ||
    request.parameters.correction !== undefined
  )
    return failure(
      request.requestId,
      "INVALID_PARAMETERS",
      "protocol",
      "prepare-semantic-map-v13 requires exactly the sheet parameter.",
    );
  const inputByName = new Map(
    request.inputs.map((input) => [input.name, input]),
  );
  if (
    inputByName.size !== request.inputs.length ||
    !inputByName.has("workbook") ||
    (request.inputs.length === 3 &&
      (!inputByName.has("ml-features") || !inputByName.has("ml-hints"))) ||
    (request.inputs.length !== 1 && request.inputs.length !== 3)
  )
    return failure(
      request.requestId,
      "INVALID_INPUT_MANIFEST",
      "input",
      "prepare-semantic-map-v13 requires workbook and optional paired ml-features/ml-hints inputs.",
    );
  const workbookInput = inputByName.get("workbook")!;
  if (workbookInput.byteLength > request.limits.maxWorkbookCompressedBytes)
    throw new ProtocolError(
      "WORKBOOK_COMPRESSED_LIMIT_EXCEEDED",
      "limit",
      `Declared workbook size exceeds limit ${request.limits.maxWorkbookCompressedBytes}.`,
    );
  const workbookBytes = await readVerifiedInput(inputRoot, workbookInput);
  await preflightXlsxZip(workbookBytes, request.limits);
  const parsedWorkbook = await parseWorkbook(workbookBytes);
  if (!parsedWorkbook.ok)
    return failure(
      request.requestId,
      "INVALID_WORKBOOK",
      "parse",
      "Workbook parsing failed.",
      parsedWorkbook.errors,
    );
  enforceWorkbookLimits(parsedWorkbook.workbook, request.limits);
  const sheet = parsedWorkbook.workbook.sheets.find(
    (candidate) => candidate.name === request.parameters.sheet,
  );
  if (!sheet)
    return failure(
      request.requestId,
      "SHEET_NOT_FOUND",
      "parse",
      `Sheet ${JSON.stringify(request.parameters.sheet)} was not found.`,
    );
  const summary = buildSheetSummary(sheet, { checked: true });
  const snapshot = buildCompactContextSnapshot(sheet);
  const context = buildCompactSemanticContext(sheet);
  const formattingFacts = buildSemanticCellFormattingFacts(sheet.cells);
  const cellDataFacts = buildSemanticCellDataFacts(sheet.cells);
  const catalog = buildRoleAwareSemanticRegionCatalog(context, {
    formattingFacts,
    cellDataFacts,
  });
  const baselinePrompt = buildSemanticMapV13Prompt(snapshot, catalog);
  let prompt = baselinePrompt;
  if (inputByName.has("ml-hints")) {
    try {
      const featureBytes = await readVerifiedInput(
        inputRoot,
        inputByName.get("ml-features")!,
      );
      const features = validateMlFeatureBatch(
        JSON.parse(featureBytes.toString("utf8")),
        workbookInput.contentDigest,
        sheet.name,
      );
      const hintBytes = await readVerifiedInput(
        inputRoot,
        inputByName.get("ml-hints")!,
      );
      const hints = validateMlHints(
        JSON.parse(hintBytes.toString("utf8")),
        workbookInput.contentDigest,
        sheet.name,
        features.featureBatchDigest,
        features.cells.map((cell) => cell.address),
      );
      prompt = appendMlHintExtension(baselinePrompt, hints);
    } catch (error) {
      return failure(
        request.requestId,
        "ML_HINT_INTEGRITY_INVALID",
        "prompt",
        error instanceof Error ? error.message : "ML hints are invalid.",
      );
    }
  }
  return await publish(request, roots, [
    {
      name: "sheet-summary.json",
      relativePath: "sheet-summary.json",
      render: () => jsonBytes(summary),
    },
    {
      name: "compact-context.json",
      relativePath: "compact-context.json",
      render: () => jsonBytes(snapshot),
    },
    {
      name: "region-catalog.json",
      relativePath: "region-catalog.json",
      render: () => jsonBytes(catalog),
    },
    {
      name: "prompt.txt",
      relativePath: "prompt.txt",
      render: () => Buffer.from(prompt, "utf8"),
    },
  ]);
}

export async function extractMlFeaturesV1(
  request: PrototypeWorkerRequest,
  roots: RootContext,
  inputRoot: string,
): Promise<WorkerResult> {
  if (!request.parameters.sheet || Object.keys(request.parameters).length !== 1)
    return failure(
      request.requestId,
      "INVALID_PARAMETERS",
      "protocol",
      "extract-ml-features-v1 requires exactly the sheet parameter.",
    );
  if (request.inputs.length !== 1 || request.inputs[0]?.name !== "workbook")
    return failure(
      request.requestId,
      "INVALID_INPUT_MANIFEST",
      "input",
      "extract-ml-features-v1 requires exactly the workbook input.",
    );
  const workbookInput = request.inputs[0];
  const workbookBytes = await readVerifiedInput(inputRoot, workbookInput);
  await preflightXlsxZip(workbookBytes, request.limits);
  const parsed = await parseWorkbook(workbookBytes);
  if (!parsed.ok)
    return failure(
      request.requestId,
      "INVALID_WORKBOOK",
      "parse",
      "Workbook parsing failed.",
    );
  enforceWorkbookLimits(parsed.workbook, request.limits);
  const sheet = parsed.workbook.sheets.find(
    (item) => item.name === request.parameters.sheet,
  );
  if (!sheet)
    return failure(
      request.requestId,
      "SHEET_NOT_FOUND",
      "parse",
      "Requested sheet was not found.",
    );
  if (sheet.cells.length > MAX_ML_CELLS)
    return failure(
      request.requestId,
      "ML_CELL_LIMIT_EXCEEDED",
      "limit",
      `ML extraction is limited to ${MAX_ML_CELLS} explicit cells.`,
    );
  const cells = extractCellFeatures(sheet).map((feature) => ({
    address: feature.address,
    ...encodeModelFeatures(feature),
  }));
  const semantic = {
    schemaVersion: ML_FEATURE_SCHEMA,
    workbookDigest: workbookInput.contentDigest,
    sheet: sheet.name,
    packageId: ML_PACKAGE_ID,
    cells,
  };
  const batch = { ...semantic, featureBatchDigest: canonicalDigest(semantic) };
  return await publish(request, roots, [
    {
      name: "ml-features.json",
      relativePath: "ml-features.json",
      render: () => jsonBytes(batch),
    },
  ]);
}

export async function interpretSemanticMapV13(
  request: PrototypeWorkerRequest,
  roots: RootContext,
  inputRoot: string,
): Promise<WorkerResult> {
  if (
    !request.parameters.sheet ||
    request.parameters.evidenceProfile !== undefined ||
    request.parameters.includeSummary !== undefined ||
    request.parameters.includeCompactContext !== undefined ||
    request.parameters.includeRegionCatalog !== undefined ||
    request.parameters.csvMode !== undefined ||
    (request.parameters.correction !== undefined &&
      request.parameters.correction !== true)
  )
    return failure(
      request.requestId,
      "INVALID_PARAMETERS",
      "protocol",
      "interpret-semantic-map-v13 requires sheet and optional correction=true.",
    );
  const inputByName = new Map(
    request.inputs.map((input) => [input.name, input]),
  );
  if (
    request.inputs.length !== 2 ||
    inputByName.size !== 2 ||
    !inputByName.has("workbook") ||
    !inputByName.has("semantic-map")
  )
    return failure(
      request.requestId,
      "INVALID_INPUT_MANIFEST",
      "input",
      "interpret-semantic-map-v13 requires workbook and semantic-map inputs.",
    );
  const workbookInput = inputByName.get("workbook")!;
  if (workbookInput.byteLength > request.limits.maxWorkbookCompressedBytes)
    throw new ProtocolError(
      "WORKBOOK_COMPRESSED_LIMIT_EXCEEDED",
      "limit",
      `Declared workbook size exceeds limit ${request.limits.maxWorkbookCompressedBytes}.`,
    );
  const workbookBytes = await readVerifiedInput(inputRoot, workbookInput);
  await preflightXlsxZip(workbookBytes, request.limits);
  const mapBytes = await readVerifiedInput(
    inputRoot,
    inputByName.get("semantic-map")!,
  );
  let map: ReturnType<typeof parseSemanticTableMapJson>;
  try {
    map = parseSemanticTableMapJson(mapBytes.toString("utf8"));
  } catch (error) {
    return failure(
      request.requestId,
      "SEMANTIC_MAP_SCHEMA_INVALID",
      "semantic-map",
      error instanceof Error ? error.message : "Semantic map is invalid.",
    );
  }
  const parsedWorkbook = await parseWorkbook(workbookBytes);
  if (!parsedWorkbook.ok)
    return failure(
      request.requestId,
      "INVALID_WORKBOOK",
      "parse",
      "Workbook parsing failed.",
      parsedWorkbook.errors,
    );
  enforceWorkbookLimits(parsedWorkbook.workbook, request.limits);
  const sheet = parsedWorkbook.workbook.sheets.find(
    (candidate) => candidate.name === request.parameters.sheet,
  );
  if (!sheet)
    return failure(
      request.requestId,
      "SHEET_NOT_FOUND",
      "parse",
      `Sheet ${JSON.stringify(request.parameters.sheet)} was not found.`,
    );
  const context = buildCompactSemanticContext(sheet);
  const catalog = buildRoleAwareSemanticRegionCatalog(context, {
    formattingFacts: buildSemanticCellFormattingFacts(sheet.cells),
    cellDataFacts: buildSemanticCellDataFacts(sheet.cells),
  });
  const compiled = compileRoleAwareSemanticTableMap({ map, catalog, context });
  if (!compiled.ok) {
    if (
      request.parameters.correction === true &&
      (compiled.stage === "region-resolution" || compiled.stage === "geometry")
    ) {
      const snapshot = buildCompactContextSnapshot(sheet);
      const correctionCatalog = correctionCandidateSubset({
        catalog,
        map,
        geometryDiagnostics: compiled.diagnostics,
        completenessDiagnostics: [],
      });
      const correctionPrompt = buildSemanticMapV13CorrectionPrompt({
        context: snapshot,
        previousMap: map,
        diagnostics: formatSemanticMapCorrectionDiagnostics({
          failure: compiled,
          completenessDiagnostics: [],
        }),
        correctionCatalog,
      });
      return await publish(request, roots, [
        {
          name: "compilation-failure.json",
          relativePath: "compilation-failure.json",
          render: () => jsonBytes(compiled),
        },
        {
          name: "correction-catalog.json",
          relativePath: "correction-catalog.json",
          render: () => jsonBytes(correctionCatalog),
        },
        {
          name: "correction-prompt.txt",
          relativePath: "correction-prompt.txt",
          render: () => Buffer.from(correctionPrompt, "utf8"),
        },
      ]);
    }
    return failure(
      request.requestId,
      compiled.code,
      "semantic-map",
      compiled.message,
      { stage: compiled.stage, diagnostics: compiled.diagnostics },
    );
  }
  enforcePrototypeRecipeNames(compiled.recipe);
  enforceRecipeSelectorLimit(compiled.recipe, request.limits.maxSelectorCells);
  const selectors = resolveRecipeSelectors(compiled.recipe, sheet);
  enforcePrototypePredictedExecutionLimits(compiled.recipe, selectors, request);
  const geometry = buildGeometryEvidence(compiled.recipe, selectors);
  const execution = executeRecipe(compiled.recipe, sheet);
  const files: ProducedFile[] = [
    {
      name: "semantic-map.json",
      relativePath: "semantic-map.json",
      render: () => jsonBytes(compiled.map),
    },
    {
      name: "normalized-recipe.json",
      relativePath: "normalized-recipe.json",
      render: () => jsonBytes(compiled.recipe),
    },
    {
      name: "selectors.json",
      relativePath: "selectors.json",
      render: () => jsonBytes(selectors),
    },
    {
      name: "geometry.json",
      relativePath: "geometry.json",
      render: () => jsonBytes(geometry),
    },
    {
      name: "execution.json",
      relativePath: "execution.json",
      render: () => jsonBytes(execution),
    },
  ];
  execution.tables.forEach((table, index) => {
    const relativePath = prototypeCsvOutputPath(table.table);
    files.push({
      name: relativePath,
      relativePath,
      render: () =>
        Buffer.from(
          rowsToCsv(table.rows, {
            valueColumn: compiled.recipe.tables[index].values.name,
          }),
          "utf8",
        ),
    });
  });
  return await publish(
    request,
    roots,
    files,
    execution.warnings.map(({ code, message }) => ({ code, message })),
  );
}

const MAX_PROTOTYPE_NAME_LENGTH = 200;
const MAX_PROTOTYPE_PATH_LENGTH = 512;

function enforcePrototypeRecipeNames(recipe: RecipeV01): void {
  const names = recipe.tables.flatMap((table) => [
    table.name,
    table.values.name,
    ...table.headers.map((header) => header.name),
  ]);
  if (names.some((name) => name.length > MAX_PROTOTYPE_NAME_LENGTH))
    throw new ProtocolError(
      "NAME_LIMIT_EXCEEDED",
      "limit",
      `Recipe names may not exceed ${MAX_PROTOTYPE_NAME_LENGTH} characters.`,
    );
  if (names.some((name) => !isWellFormedUnicode(name)))
    throw new ProtocolError(
      "INVALID_NAME_ENCODING",
      "recipe",
      "Recipe names must contain well-formed Unicode scalar values.",
    );
  for (const table of recipe.tables) prototypeCsvOutputPath(table.name);
}

function enforcePrototypePredictedExecutionLimits(
  recipe: RecipeV01,
  selectors: ResolvedRecipeSelectors,
  request: PrototypeWorkerRequest,
): void {
  let predictedRows = 0;
  let warningUpperBound = selectors.warnings.length;
  for (const table of selectors.tables) {
    const values = table.values.addresses.length;
    predictedRows += values;
    warningUpperBound += (values === 0 ? 1 : 0) + values;
    for (const header of table.headers) {
      warningUpperBound +=
        (header.result.addresses.length === 0 ? 1 : 0) +
        2 * values +
        header.result.addresses.length;
    }
  }
  if (predictedRows > request.limits.maxOutputRows)
    throw new ProtocolError(
      "OUTPUT_ROW_LIMIT_EXCEEDED",
      "limit",
      `Resolved selectors could produce ${predictedRows} rows, exceeding limit ${request.limits.maxOutputRows}.`,
    );
  if (warningUpperBound > request.limits.maxWarnings)
    throw new ProtocolError(
      "WARNING_LIMIT_EXCEEDED",
      "limit",
      `Execution could produce more than ${request.limits.maxWarnings} warnings.`,
    );
  void recipe;
}

function prototypeCsvOutputPath(tableName: string): string {
  if (!isWellFormedUnicode(tableName))
    throw new ProtocolError(
      "INVALID_NAME_ENCODING",
      "recipe",
      "Table names must contain well-formed Unicode scalar values.",
    );
  const fileName = `${encodeURIComponent(tableName)}.csv`;
  const relativePath = `tables/${fileName}`;
  if (
    Buffer.byteLength(fileName, "utf8") > 255 ||
    Buffer.byteLength(relativePath, "utf8") > MAX_PROTOTYPE_PATH_LENGTH
  )
    throw new ProtocolError(
      "OUTPUT_PATH_LIMIT_EXCEEDED",
      "limit",
      "Encoded table output path exceeds the portable filesystem limit.",
    );
  return relativePath;
}

function isWellFormedUnicode(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (next < 0xdc00 || next > 0xdfff) return false;
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) return false;
  }
  return true;
}
