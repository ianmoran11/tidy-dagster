import { buildSemanticCellFormattingFacts } from "../catalog/format-aware-region-catalog-v2.js";
import {
  buildRoleAwareSemanticRegionCatalog,
  buildSemanticCellDataFacts,
  compileRoleAwareSemanticTableMap,
  correctionCandidateSubset,
} from "../catalog/role-aware-region-catalog-v5.js";
import { parseSemanticTableMapJson } from "../catalog/semantic-map-v1.js";
import {
  compileFederalDefendantsGroupedRecipeV1,
  estimateFederalGroupedOutputPreflightBytes,
  executeFederalDefendantsGroupedRecipeV1,
  isFederalDefendantsGroupedMapRaw,
  parseFederalDefendantsGroupedSemanticMapV1,
  preflightFederalDefendantsGroupedMapV1,
} from "../catalog/federal-defendants-grouped-recipe-v1.js";
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
import type { TidyOutputRow } from "../executor/types.js";
import { resolveRecipeSelectors } from "../recipe/resolveSelectors.js";
import { buildSheetSummary } from "../summary/buildSheetSummary.js";
import { parseWorkbook } from "../workbook/parseWorkbook.js";
import {
  FederalDefendantsBoundedWorkbookError,
  parseFederalDefendantsBoundedRawWorkbook,
  preflightFederalDefendantsWorkbookRoute,
  type FederalDefendantsWorkbookRouteResult,
} from "../workbook/parseFederalDefendantsBoundedWorkbook.js";
import {
  enforceRecipeSelectorLimit,
  enforceWorkbookLimits,
  LimitViolation,
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
  const declaredInputBytes = request.inputs.reduce(
    (total, input) => total + input.byteLength,
    0,
  );
  if (
    !Number.isSafeInteger(declaredInputBytes) ||
    declaredInputBytes > request.limits.maxInputBytes
  )
    throw new ProtocolError(
      "INPUT_LIMIT_EXCEEDED",
      "limit",
      `Declared inputs require ${declaredInputBytes} bytes, exceeding limit ${request.limits.maxInputBytes}.`,
    );
  const workbookInput = inputByName.get("workbook")!;
  const mapInput = inputByName.get("semantic-map")!;
  if (workbookInput.byteLength > request.limits.maxWorkbookCompressedBytes)
    throw new ProtocolError(
      "WORKBOOK_COMPRESSED_LIMIT_EXCEEDED",
      "limit",
      `Declared workbook size exceeds limit ${request.limits.maxWorkbookCompressedBytes}.`,
    );
  const mapBytes = await readVerifiedInput(inputRoot, mapInput);
  const mapRaw = mapBytes.toString("utf8");
  const isFederalGrouped = isFederalDefendantsGroupedMapRaw(mapRaw);
  let map: ReturnType<typeof parseSemanticTableMapJson> | undefined;
  let federalMap:
    | ReturnType<typeof parseFederalDefendantsGroupedSemanticMapV1>
    | undefined;
  let federalWorkbookRoute: FederalDefendantsWorkbookRouteResult | undefined;
  if (isFederalGrouped) {
    try {
      federalMap = parseFederalDefendantsGroupedSemanticMapV1(mapRaw);
    } catch (error) {
      return failure(
        request.requestId,
        "FEDERAL_GROUPED_SCHEMA_INVALID",
        "semantic-map",
        error instanceof Error
          ? error.message
          : "Federal grouped map is invalid.",
      );
    }
    if (request.limits.maxOutputFiles < 6)
      throw new ProtocolError(
        "OUTPUT_DESCRIPTOR_LIMIT_EXCEEDED",
        "limit",
        "Federal grouped execution requires exactly six output descriptors.",
      );
    const outputPreflightBytes = estimateFederalGroupedOutputPreflightBytes(
      mapRaw,
      federalMap!,
      workbookInput.byteLength,
    );
    if (request.limits.maxOutputBytes < outputPreflightBytes)
      throw new ProtocolError(
        "OUTPUT_LIMIT_EXCEEDED",
        "limit",
        `Federal grouped execution requires a preflight budget of at least ${outputPreflightBytes} bytes.`,
      );
    const geometryPreflight = preflightFederalDefendantsGroupedMapV1(
      federalMap!,
      {
        maxSelectorCells: request.limits.maxSelectorCells,
        maxOutputRows: request.limits.maxOutputRows,
      },
    );
    if (!geometryPreflight.ok)
      return failure(
        request.requestId,
        geometryPreflight.code,
        "semantic-map",
        geometryPreflight.message,
        { stage: geometryPreflight.stage },
      );
    federalWorkbookRoute = preflightFederalDefendantsWorkbookRoute({
      source: federalMap!.source,
      requestedSheet: request.parameters.sheet,
      declaredWorkbookDigest: workbookInput.contentDigest,
      declaredWorkbookBytes: workbookInput.byteLength,
    });
    if (!federalWorkbookRoute.ok)
      return failure(
        request.requestId,
        federalWorkbookRoute.code,
        "semantic-map",
        federalWorkbookRoute.message,
        { stage: federalWorkbookRoute.stage },
      );
  } else {
    try {
      map = parseSemanticTableMapJson(mapRaw);
    } catch (error) {
      return failure(
        request.requestId,
        "SEMANTIC_MAP_SCHEMA_INVALID",
        "semantic-map",
        error instanceof Error ? error.message : "Semantic map is invalid.",
      );
    }
  }
  const workbookBytes = await readVerifiedInput(inputRoot, workbookInput);
  let parsedWorkbook;
  if (
    isFederalGrouped &&
    federalWorkbookRoute?.ok &&
    federalWorkbookRoute.bounded
  ) {
    try {
      parsedWorkbook = await parseFederalDefendantsBoundedRawWorkbook({
        bytes: workbookBytes,
        source: federalMap!.source,
        requestedSheet: request.parameters.sheet,
        declaredWorkbookDigest: workbookInput.contentDigest,
        declaredWorkbookBytes: workbookInput.byteLength,
        limits: request.limits,
      });
    } catch (error) {
      if (error instanceof FederalDefendantsBoundedWorkbookError)
        return failure(
          request.requestId,
          error.code,
          error.stage === "source" ? "semantic-map" : error.stage,
          error.message,
        );
      if (error instanceof LimitViolation)
        return failure(request.requestId, error.code, "limit", error.message);
      return failure(
        request.requestId,
        "INVALID_WORKBOOK",
        "parse",
        error instanceof Error
          ? error.message
          : "Bounded workbook parsing failed.",
      );
    }
  } else {
    await preflightXlsxZip(workbookBytes, request.limits);
    parsedWorkbook = await parseWorkbook(workbookBytes);
  }
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
  if (isFederalGrouped) {
    if (request.parameters.correction === true)
      return failure(
        request.requestId,
        "FEDERAL_GROUPED_CORRECTION_UNSUPPORTED",
        "semantic-map",
        "Federal Defendants grouped replay is provider-free and does not permit correction prompts.",
      );
    const compiled = compileFederalDefendantsGroupedRecipeV1({
      mapRaw,
      expectedMapBytesDigest: mapInput.contentDigest,
      sheet,
      expectedExecutionWorkbookDigest: workbookInput.contentDigest,
      expectedSourceWorkbookDigest: workbookInput.contentDigest,
      limits: {
        maxSelectorCells: request.limits.maxSelectorCells,
        maxOutputRows: request.limits.maxOutputRows,
      },
    });
    if (!compiled.ok)
      return failure(
        request.requestId,
        compiled.code,
        "semantic-map",
        compiled.message,
        { stage: compiled.stage },
      );
    const execution = executeFederalDefendantsGroupedRecipeV1(
      compiled.envelope,
      {
        mapRaw,
        sheet,
        expectedExecutionWorkbookDigest: workbookInput.contentDigest,
        expectedSourceWorkbookDigest: workbookInput.contentDigest,
        trustedEnvelopeDigest: compiled.envelope.envelopeDigest,
      },
    );
    const table = execution.tables[0];
    let renderedFederalBytes = 0;
    const withinFederalBudget = (
      render: (maximum: number) => Buffer,
    ): Buffer => {
      const remaining = request.limits.maxOutputBytes - renderedFederalBytes;
      if (remaining < 0)
        throw new ProtocolError(
          "OUTPUT_LIMIT_EXCEEDED",
          "limit",
          "Federal grouped outputs exceeded the cumulative byte budget.",
        );
      const bytes = render(remaining);
      renderedFederalBytes += bytes.byteLength;
      return bytes;
    };
    const federalJson = (value: unknown): Buffer =>
      withinFederalBudget((maximum) => budgetedPrettyJsonBytes(value, maximum));
    return await publish(request, roots, [
      {
        name: "semantic-map.json",
        relativePath: "semantic-map.json",
        render: () =>
          federalJson(parseFederalDefendantsGroupedSemanticMapV1(mapRaw)),
      },
      {
        name: "normalized-recipe.json",
        relativePath: "normalized-recipe.json",
        render: () => federalJson(compiled.envelope.recipe),
      },
      {
        name: "selectors.json",
        relativePath: "selectors.json",
        render: () =>
          federalJson({
            panels: compiled.envelope.recipe.panels,
            sourceUniverses: compiled.envelope.recipe.sourceUniverses,
          }),
      },
      {
        name: "geometry.json",
        relativePath: "geometry.json",
        render: () =>
          federalJson({
            geometryAuthorityProof: compiled.envelope.geometryAuthorityProof,
            boundedSheetProof: compiled.envelope.boundedSheetProof,
            formulaProof: compiled.envelope.formulaProof,
            targetManifest: compiled.envelope.targetManifest,
            attachmentManifest: compiled.envelope.attachmentManifest,
            envelopeDigest: compiled.envelope.envelopeDigest,
          }),
      },
      {
        name: "execution.json",
        relativePath: "execution.json",
        render: () => federalJson(execution),
      },
      {
        name: prototypeCsvOutputPath(table.table),
        relativePath: prototypeCsvOutputPath(table.table),
        render: () =>
          withinFederalBudget((maximum) =>
            budgetedCsvBytes(
              table.rows as TidyOutputRow[],
              compiled.envelope.recipe.table.valuesName,
              maximum,
            ),
          ),
      },
    ]);
  }

  const legacyMap = map!;
  const context = buildCompactSemanticContext(sheet);
  const catalog = buildRoleAwareSemanticRegionCatalog(context, {
    formattingFacts: buildSemanticCellFormattingFacts(sheet.cells),
    cellDataFacts: buildSemanticCellDataFacts(sheet.cells),
  });
  const compiled = compileRoleAwareSemanticTableMap({
    map: legacyMap,
    catalog,
    context,
  });
  if (!compiled.ok) {
    if (
      request.parameters.correction === true &&
      (compiled.stage === "region-resolution" || compiled.stage === "geometry")
    ) {
      const snapshot = buildCompactContextSnapshot(sheet);
      const correctionCatalog = correctionCandidateSubset({
        catalog,
        map: legacyMap,
        geometryDiagnostics: compiled.diagnostics,
        completenessDiagnostics: [],
      });
      const correctionPrompt = buildSemanticMapV13CorrectionPrompt({
        context: snapshot,
        previousMap: legacyMap,
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

function budgetedPrettyJsonBytes(value: unknown, maximum: number): Buffer {
  const chunks: string[] = [];
  let byteLength = 0;
  const append = (chunk: string): void => {
    byteLength += Buffer.byteLength(chunk, "utf8");
    if (byteLength > maximum)
      throw new ProtocolError(
        "OUTPUT_LIMIT_EXCEEDED",
        "limit",
        "Federal JSON output exceeded the remaining byte budget.",
      );
    chunks.push(chunk);
  };
  const render = (candidate: unknown, depth: number): void => {
    if (Array.isArray(candidate)) {
      if (candidate.length === 0) {
        append("[]");
        return;
      }
      append("[\n");
      candidate.forEach((entry, index) => {
        append("  ".repeat(depth + 1));
        render(entry === undefined ? null : entry, depth + 1);
        append(index + 1 === candidate.length ? "\n" : ",\n");
      });
      append(`${"  ".repeat(depth)}]`);
      return;
    }
    if (candidate !== null && typeof candidate === "object") {
      const record = candidate as Record<string, unknown>;
      const keys = Object.keys(record).filter(
        (key) =>
          record[key] !== undefined &&
          typeof record[key] !== "function" &&
          typeof record[key] !== "symbol",
      );
      if (keys.length === 0) {
        append("{}");
        return;
      }
      append("{\n");
      keys.forEach((key, index) => {
        append(`${"  ".repeat(depth + 1)}${JSON.stringify(key)}: `);
        render(record[key], depth + 1);
        append(index + 1 === keys.length ? "\n" : ",\n");
      });
      append(`${"  ".repeat(depth)}}`);
      return;
    }
    const rendered = JSON.stringify(candidate);
    append(rendered === undefined ? "null" : rendered);
  };
  render(value, 0);
  append("\n");
  return Buffer.from(chunks.join(""), "utf8");
}

function budgetedCsvBytes(
  rows: TidyOutputRow[],
  valueColumn: string,
  maximum: number,
): Buffer {
  const headers = collectFederalCsvHeaders(rows, valueColumn);
  const chunks: string[] = [];
  let byteLength = 0;
  const append = (chunk: string): void => {
    byteLength += Buffer.byteLength(chunk, "utf8");
    if (byteLength > maximum)
      throw new ProtocolError(
        "OUTPUT_LIMIT_EXCEEDED",
        "limit",
        "Federal CSV output exceeded the remaining byte budget.",
      );
    chunks.push(chunk);
  };
  const escape = (value: string | number | boolean | null): string => {
    if (value === null) return "";
    const text = String(value);
    return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  };
  const writeValue = (
    value: string | number | boolean | null,
    index: number,
  ): void => {
    if (index > 0) append(",");
    append(escape(value));
  };
  headers.forEach(writeValue);
  append("\n");
  for (const row of rows) {
    headers.forEach((header, index) =>
      writeValue(federalCsvRowValue(row, header, valueColumn), index),
    );
    append("\n");
  }
  return Buffer.from(chunks.join(""), "utf8");
}

function collectFederalCsvHeaders(
  rows: TidyOutputRow[],
  valueColumn: string,
): string[] {
  const headers = new Set<string>();
  for (const row of rows) {
    for (const header of ["row", "col", "address"]) headers.add(header);
    headers.add(".value");
    for (const key of Object.keys(row)) {
      if (key !== "_source" && key !== valueColumn) headers.add(key);
    }
  }
  return [...headers];
}

function federalCsvRowValue(
  row: TidyOutputRow,
  header: string,
  valueColumn: string,
): string | number | boolean | null {
  if (header === "row") return row._source?.row ?? null;
  if (header === "col") return row._source?.col ?? null;
  if (header === "address") return row._source?.address ?? null;
  if (header === ".value") return federalCsvScalar(row[valueColumn]);
  return federalCsvScalar(row[header]);
}

function federalCsvScalar(
  value: TidyOutputRow[string],
): string | number | boolean | null {
  return value === undefined || value === null || typeof value === "object"
    ? null
    : value;
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
