import { AsyncLocalStorage } from "node:async_hooks";
import { randomUUID } from "node:crypto";
import { constants as fsConstants } from "node:fs";
import { hostname, type as operatingSystemType } from "node:os";
import {
  link,
  lstat,
  mkdir,
  open,
  readFile,
  readdir,
  realpath,
  rename,
  unlink,
} from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import { resolveContainedPath } from "../../harvest/path-safety";
import {
  assertNoIncompleteArtifacts,
  digestCanonicalJson,
  readContainedArtifact,
  sha256Bytes,
} from "./artifact-io";
import {
  parseCellRoleSketchV02,
  validateCellRoleSketchV02ForCompilation,
} from "./cell-role-sketch-v02";
import {
  validateEvidencePayload,
  writeImmutableEvidenceFile,
} from "./evidence-io";
import type { ExperimentPlan, ExperimentUnit } from "./plan";
import {
  digestJson,
  digestLiveValidationResult,
  readPersistedResults,
} from "./plan";
import type { PairedAssetResult, ProviderRequest } from "./types";

const sha256Schema = z.string().regex(/^[a-f0-9]{64}$/);
const recordIdSchema = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._-]*$/);
const generationSettingsSchema = z
  .object({
    provider: z.enum(["openrouter", "pi", "claude"]),
    model: z.string().min(1),
    temperature: z.number().finite().min(0).max(2),
    reasoning: z.enum(["low", "medium", "high"]),
    timeoutMs: z.number().int().positive(),
    maxAttempts: z.literal(1),
  })
  .strict();

export const LIVE_STAGE_KEYS = [
  "baseline",
  "semantics",
  "translation",
  "llm-translation-research",
] as const;
export type LiveStageKey = (typeof LIVE_STAGE_KEYS)[number];

const stageAllowanceSchema = z
  .object({
    stage: z.enum(LIVE_STAGE_KEYS),
    maximumCalls: z.number().int().nonnegative(),
  })
  .strict();

export const unsignedLiveAuthorizationSchema = z
  .object({
    schemaVersion: z.literal("cell-role-live-authorization-v1"),
    authorizationId: recordIdSchema,
    planDigest: sha256Schema,
    implementationProvenanceDigest: sha256Schema,
    implementationTree: z.string().regex(/^[a-f0-9]{40,64}$/),
    executable: z
      .object({
        path: z.string().min(1),
        sha256: sha256Schema,
      })
      .strict(),
    provider: z.literal("openai-codex"),
    model: z.string().min(1),
    settings: generationSettingsSchema,
    settingsDigest: sha256Schema,
    maximumTotalCalls: z.number().int().positive(),
    stageAllowances: z.array(stageAllowanceSchema).min(1),
    allowedAssets: z.array(z.string().min(1)).min(1),
    expiresAt: z.string().datetime(),
    authMode: z.literal("oauth"),
    approval: z
      .object({
        approvedBy: z.string().min(1),
        approvedAt: z.string().datetime(),
        method: z.string().min(1),
        reference: z.string().min(1),
      })
      .strict(),
  })
  .strict()
  .superRefine((value, ctx) => {
    if (new Set(value.allowedAssets).size !== value.allowedAssets.length) {
      ctx.addIssue({ code: "custom", message: "Duplicate authorized asset." });
    }
    const stages = value.stageAllowances.map((entry) => entry.stage);
    if (new Set(stages).size !== stages.length) {
      ctx.addIssue({ code: "custom", message: "Duplicate stage allowance." });
    }
    if (
      value.stageAllowances.reduce(
        (sum, entry) => sum + entry.maximumCalls,
        0,
      ) < value.maximumTotalCalls
    ) {
      ctx.addIssue({
        code: "custom",
        message: "Total call allowance exceeds stage allowances.",
      });
    }
  });

export const liveAuthorizationSchema = unsignedLiveAuthorizationSchema.extend({
  digest: sha256Schema,
});
export type LiveAuthorization = z.infer<typeof liveAuthorizationSchema>;

export const oauthReadinessSchema = z
  .object({
    schemaVersion: z.literal("cell-role-oauth-readiness-v1"),
    provider: z.literal("openai-codex"),
    model: z.string().min(1),
    authMode: z.literal("oauth-bearer"),
    executablePath: z.string().min(1),
    executableDigest: sha256Schema,
    checkedAt: z.string().datetime(),
    readinessMethod: z.literal("pi-auth-print-bearer-token-exit-status"),
    credentialOutputDiscarded: z.literal(true),
    ready: z.literal(true),
    digest: sha256Schema,
  })
  .strict();
export type OAuthReadinessAttestation = z.infer<typeof oauthReadinessSchema>;

const claimCoreSchema = z
  .object({
    schemaVersion: z.literal("cell-role-live-claim-v1"),
    claimId: sha256Schema,
    sequence: z.number().int().positive(),
    planDigest: sha256Schema,
    implementationProvenanceDigest: sha256Schema,
    authorizationDigest: sha256Schema,
    oauthReadinessDigest: sha256Schema,
    unitDigest: sha256Schema,
    asset: z.string().min(1),
    arm: z.enum(["baseline", "staged", "llm-translation-research"]),
    stage: z.enum(["baseline", "semantics", "translation"]),
    stageKey: z.enum(LIVE_STAGE_KEYS),
    promptDigest: sha256Schema,
    settingsDigest: sha256Schema,
    executableDigest: sha256Schema,
    orderedPredecessorEvidenceDigests: z.array(sha256Schema).min(1),
    claimedAt: z.string().datetime(),
  })
  .strict();
export const liveClaimSchema = claimCoreSchema.extend({ digest: sha256Schema });
export type LiveClaim = z.infer<typeof liveClaimSchema>;

const safeUsageSchema = z
  .object({
    promptTokens: z.number().finite().nonnegative().optional(),
    completionTokens: z.number().finite().nonnegative().optional(),
    totalTokens: z.number().finite().nonnegative().optional(),
    cachedTokens: z.number().finite().nonnegative().optional(),
    cacheCreationInputTokens: z.number().finite().nonnegative().optional(),
    cacheReadInputTokens: z.number().finite().nonnegative().optional(),
    cacheWriteInputTokens: z.number().finite().nonnegative().optional(),
    reasoningTokens: z.number().finite().nonnegative().optional(),
    catalogPricedUsd: z.number().finite().nonnegative().optional(),
    apiEquivalentUsd: z.number().finite().nonnegative().optional(),
    usageSource: z
      .enum(["provider_observed", "char_estimate", "mixed", "unknown"])
      .optional(),
  })
  .strict();

export const safeProviderOutcomeSchema = z.union([
  z
    .object({
      ok: z.literal(true),
      content: z.string(),
      usage: safeUsageSchema.optional(),
      durationMs: z.number().finite().nonnegative(),
    })
    .strict(),
  z
    .object({
      ok: z.literal(false),
      code: z.string().regex(/^[A-Z0-9_]+$/),
      status: z.number().int().optional(),
      message: z.string(),
      durationMs: z.number().finite().nonnegative(),
    })
    .strict(),
]);
export type SafeProviderOutcome = z.infer<typeof safeProviderOutcomeSchema>;

const responseCoreSchema = z
  .object({
    schemaVersion: z.literal("cell-role-live-response-v1"),
    claimDigest: sha256Schema,
    planDigest: sha256Schema,
    unitDigest: sha256Schema,
    authorizationDigest: sha256Schema,
    implementationProvenanceDigest: sha256Schema,
    promptDigest: sha256Schema,
    settingsDigest: sha256Schema,
    orderedPredecessorEvidenceDigests: z.array(sha256Schema).min(2),
    completedAt: z.string().datetime(),
    outcome: safeProviderOutcomeSchema,
  })
  .strict();
export const liveResponseSchema = responseCoreSchema.extend({
  digest: sha256Schema,
});
export type LiveResponse = z.infer<typeof liveResponseSchema>;

const validationCoreSchema = z
  .object({
    schemaVersion: z.literal("cell-role-live-validation-v1"),
    planDigest: sha256Schema,
    unitDigest: sha256Schema,
    authorizationDigest: sha256Schema,
    implementationProvenanceDigest: sha256Schema,
    promptDigests: z.array(sha256Schema).min(2),
    settingsDigest: sha256Schema,
    responseDigests: z.array(sha256Schema).min(1),
    orderedPredecessorEvidenceDigests: z.array(sha256Schema).min(2),
    resultDigest: sha256Schema,
    validatedAt: z.string().datetime(),
  })
  .strict();
export const liveValidationSchema = validationCoreSchema.extend({
  digest: sha256Schema,
});
export type LiveValidation = z.infer<typeof liveValidationSchema>;

export type VerifiedLiveRunState = {
  authorization?: LiveAuthorization;
  oauth?: OAuthReadinessAttestation;
  claims: LiveClaim[];
  responses: LiveResponse[];
  validations: LiveValidation[];
  orphanClaims: LiveClaim[];
};

export type LiveExecutionBinding = {
  authorizationDigest: string;
  implementationProvenanceDigest: string;
  executableDigest: string;
  oauthReadinessDigest: string;
  responseDigests: string[];
  orderedPredecessorEvidenceDigests: string[];
};

export function authorizationDigest(
  unsigned: z.infer<typeof unsignedLiveAuthorizationSchema>,
): string {
  return digestCanonicalJson(unsignedLiveAuthorizationSchema.parse(unsigned));
}

export function parseLiveAuthorization(value: unknown): LiveAuthorization {
  const parsed = liveAuthorizationSchema.parse(value);
  const { digest, ...unsigned } = parsed;
  if (authorizationDigest(unsigned) !== digest) {
    throw new Error("AUTHORIZATION_DIGEST_MISMATCH");
  }
  return parsed;
}

export async function readVerifiedLiveAuthorization(options: {
  plan: ExperimentPlan;
  authorizationPath: string;
  repoRoot?: string;
  now?: Date;
}): Promise<LiveAuthorization> {
  const repoRoot = options.repoRoot ?? process.cwd();
  const bytes = await readContainedArtifact({
    repoRoot,
    target: options.authorizationPath,
    pathErrorCode: "AUTHORIZATION_PATH_ESCAPE",
  });
  const authorization = parseLiveAuthorization(
    validateEvidencePayload({
      bytes,
      mediaType: "application/json",
      role: "live-authorization",
    }),
  );
  await verifyAuthorizationBinding({
    plan: options.plan,
    authorization,
    now: options.now,
  });
  await verifyPinnedExecutable(authorization);
  return authorization;
}

export async function verifyAuthorizationBinding(options: {
  plan: ExperimentPlan;
  authorization: LiveAuthorization;
  now?: Date;
}): Promise<void> {
  const { plan, authorization } = options;
  if (plan.schemaVersion === "cell-role-experiment-plan-v1") {
    throw new Error("AUTHORIZATION_REQUIRES_IMPLEMENTATION_PROVENANCE");
  }
  if (
    authorization.planDigest !== plan.digest ||
    authorization.implementationProvenanceDigest !==
      plan.implementationProvenanceDigest ||
    authorization.implementationTree !== plan.implementationProvenance.gitTree
  ) {
    throw new Error("AUTHORIZATION_IMPLEMENTATION_OR_PLAN_MISMATCH");
  }
  if (
    plan.providerAdapter !== "pi-json-v1" ||
    plan.generationSettings.provider !== "pi" ||
    authorization.provider !== "openai-codex" ||
    authorization.model !== plan.generationSettings.model ||
    digestJson(authorization.settings) !== authorization.settingsDigest ||
    authorization.settingsDigest !== digestJson(plan.generationSettings)
  ) {
    throw new Error("AUTHORIZATION_PROVIDER_MODEL_SETTINGS_MISMATCH");
  }
  if (
    (options.now ?? new Date()).getTime() >= Date.parse(authorization.expiresAt)
  ) {
    throw new Error("AUTHORIZATION_EXPIRED");
  }
  const planAssets = new Set(plan.units.map((unit) => unit.asset));
  if (authorization.allowedAssets.some((asset) => !planAssets.has(asset))) {
    throw new Error("AUTHORIZATION_ASSET_MISMATCH");
  }
  const planMaximum =
    plan.schemaVersion === "cell-role-experiment-plan-v3" ||
    plan.schemaVersion === "cell-role-experiment-plan-v4"
      ? plan.providerCallBudget.maximumTotal
      : plan.units.length * 3;
  if (authorization.maximumTotalCalls > planMaximum) {
    throw new Error("AUTHORIZATION_CALL_CAP_EXCEEDS_PLAN");
  }
  const allowedCount = authorization.allowedAssets.length;
  const deterministic =
    plan.schemaVersion === "cell-role-experiment-plan-v3" ||
    plan.schemaVersion === "cell-role-experiment-plan-v4";
  const permittedMaximums: Record<LiveStageKey, number> = {
    baseline: allowedCount,
    semantics: allowedCount,
    translation: deterministic ? 0 : allowedCount,
    "llm-translation-research":
      deterministic && plan.researchArms.includes("llm-translation-research")
        ? allowedCount
        : 0,
  };
  for (const allowance of authorization.stageAllowances) {
    if (allowance.maximumCalls > permittedMaximums[allowance.stage]) {
      throw new Error("AUTHORIZATION_STAGE_CAP_EXCEEDS_PLAN");
    }
  }
}

export async function verifyPinnedExecutable(
  authorization: LiveAuthorization,
): Promise<void> {
  if (!path.isAbsolute(authorization.executable.path)) {
    throw new Error("PI_EXECUTABLE_PATH_NOT_ABSOLUTE");
  }
  const resolved = await realpath(authorization.executable.path);
  if (resolved !== authorization.executable.path) {
    throw new Error("PI_EXECUTABLE_PATH_NOT_CANONICAL");
  }
  const executableStat = await lstat(resolved);
  if (!executableStat.isFile() || executableStat.isSymbolicLink()) {
    throw new Error("PI_EXECUTABLE_NOT_REGULAR_FILE");
  }
  const actual = sha256Bytes(await readFile(resolved));
  if (actual !== authorization.executable.sha256) {
    throw new Error("PI_EXECUTABLE_DIGEST_MISMATCH");
  }
}

export async function persistAuthorizationSnapshot(options: {
  plan: ExperimentPlan;
  authorization: LiveAuthorization;
  repoRoot: string;
}): Promise<void> {
  const root = await liveRunRoot(options.plan, options.repoRoot);
  await ensurePrivateDirectory(root, options.repoRoot);
  await writeLiveJson(
    options.repoRoot,
    path.join(root, "authorization.json"),
    options.authorization,
    "live-authorization-snapshot",
  );
}

export async function persistOAuthReadiness(options: {
  plan: ExperimentPlan;
  authorization: LiveAuthorization;
  repoRoot: string;
  check: () => Promise<Omit<OAuthReadinessAttestation, "digest">>;
}): Promise<OAuthReadinessAttestation> {
  const target = path.join(
    await liveRunRoot(options.plan, options.repoRoot),
    "oauth-readiness.json",
  );
  try {
    const existing = oauthReadinessSchema.parse(
      validateEvidencePayload({
        bytes: await readContainedArtifact({
          repoRoot: options.repoRoot,
          target,
          pathErrorCode: "LIVE_STATE_PATH_ESCAPE",
        }),
        mediaType: "application/json",
        role: "oauth-readiness",
      }),
    );
    const { digest, ...unsigned } = existing;
    if (digestCanonicalJson(unsigned) !== digest)
      throw new Error("OAUTH_READINESS_DIGEST_MISMATCH");
    assertOAuthBinding(existing, options.authorization);
    return existing;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  const unsigned = await options.check();
  const attestation = oauthReadinessSchema.parse({
    ...unsigned,
    digest: digestCanonicalJson(unsigned),
  });
  assertOAuthBinding(attestation, options.authorization);
  await writeLiveJson(options.repoRoot, target, attestation, "oauth-readiness");
  return attestation;
}

export type EvidenceRunLockIdentity = {
  runId: string;
  planDigest: string;
};

export type EvidenceRunLockFilesystem = {
  readFile(target: string): Promise<{
    bytes: Buffer;
    identity: {
      dev: number;
      ino: number;
      mtimeNs: string;
      sha256: string;
    };
  }>;
  readDirectoryFiles(
    target: string,
  ): Promise<Array<{ name: string; kind: "file"; bytes: Buffer }>>;
  ensurePrivateDirectory(target: string): Promise<void>;
  writeImmutable(
    target: string,
    bytes: Uint8Array,
    mode?: number,
  ): Promise<{ created: boolean }>;
  createExclusive(
    target: string,
    bytes: Uint8Array,
    mode?: number,
  ): Promise<unknown>;
  unlinkIfIdentity(
    target: string,
    identity: { dev: number; ino: number; sha256: string },
  ): Promise<void>;
  moveNoReplace(
    source: string,
    destination: string,
    identity: { dev: number; ino: number; sha256: string },
  ): Promise<void>;
};

const evidenceRunLockFilesystem =
  new AsyncLocalStorage<EvidenceRunLockFilesystem>();

export async function acquireExclusiveRunLock(options: {
  plan: ExperimentPlan;
  repoRoot: string;
  staleAfterMs?: number;
  lockRecoveryHooks?: LockRecoveryHooks;
}): Promise<{ release: () => Promise<void>; lockPath: string }> {
  return acquireExclusiveEvidenceRunLock({
    root: await liveRunRoot(options.plan, options.repoRoot),
    repoRoot: options.repoRoot,
    identity: { runId: options.plan.runId, planDigest: options.plan.digest },
    staleAfterMs: options.staleAfterMs,
    lockRecoveryHooks: options.lockRecoveryHooks,
  });
}

/**
 * Generic form of the PRD 008 process lock. Callers supply an already
 * contained evidence root and a digest-bound identity; the lock and recovery
 * journal semantics remain identical to the original live runner.
 */
export async function acquireExclusiveEvidenceRunLock(options: {
  root: string;
  repoRoot: string;
  identity: EvidenceRunLockIdentity;
  staleAfterMs?: number;
  lockRecoveryHooks?: LockRecoveryHooks;
  filesystem?: EvidenceRunLockFilesystem;
}): Promise<{ release: () => Promise<void>; lockPath: string }> {
  if (options.filesystem)
    return evidenceRunLockFilesystem.run(options.filesystem, () =>
      acquireExclusiveEvidenceRunLock({ ...options, filesystem: undefined }),
    );
  const strictFilesystem = evidenceRunLockFilesystem.getStore();
  const root = path.resolve(options.root);
  if (strictFilesystem) await strictFilesystem.ensurePrivateDirectory(root);
  else {
    await resolveContainedPath({
      root: options.repoRoot,
      value: root,
      mustExist: false,
      code: "LIVE_STATE_PATH_ESCAPE",
    });
    await ensurePrivateDirectory(root, options.repoRoot);
  }
  const lockPath = path.join(root, "run.lock");
  const token = randomUUID();
  const record = {
    schemaVersion: "cell-role-run-lock-v1",
    runId: options.identity.runId,
    planDigest: options.identity.planDigest,
    lockKey: digestCanonicalJson(options.identity),
    pid: process.pid,
    hostname: hostname(),
    os: operatingSystemType(),
    acquiredAt: new Date().toISOString(),
    token,
  };
  let recoveryIntent: LockRecoveryIntent | undefined;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    if (!recoveryIntent) {
      await assertNoUnresolvedLockRecoveries(root, options.repoRoot);
    }
    try {
      const lockBytes = Buffer.from(`${JSON.stringify(record)}\n`);
      if (strictFilesystem)
        await strictFilesystem.createExclusive(lockPath, lockBytes, 0o600);
      else {
        const handle = await open(lockPath, "wx", 0o600);
        try {
          await handle.writeFile(lockBytes);
          await handle.sync();
        } finally {
          await handle.close();
        }
      }
      const release = () =>
        strictFilesystem
          ? evidenceRunLockFilesystem.run(strictFilesystem, () =>
              releaseOwnedRunLock(lockPath, options.repoRoot, token),
            )
          : releaseOwnedRunLock(lockPath, options.repoRoot, token);
      try {
        if (recoveryIntent) {
          await options.lockRecoveryHooks?.beforeRecoveryCompletion?.();
          await completeLockRecovery({
            root,
            repoRoot: options.repoRoot,
            intent: recoveryIntent,
            outcome: "recovered-and-acquired",
          });
          recoveryIntent = undefined;
          await waitForNoUnresolvedLockRecoveries(root, options.repoRoot);
        } else {
          await waitForNoUnresolvedLockRecoveries(root, options.repoRoot);
        }
        await assertOwnedRunLock(lockPath, options.repoRoot, token);
        return { lockPath, release };
      } catch (error) {
        await release().catch(() => undefined);
        throw error;
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      if (recoveryIntent) {
        await completeLockRecovery({
          root,
          repoRoot: options.repoRoot,
          intent: recoveryIntent,
          outcome: "peer-acquired",
        });
        throw new Error("RUN_LOCK_ACTIVE");
      }
      recoveryIntent = await beginLockRecovery({
        identity: options.identity,
        root,
        repoRoot: options.repoRoot,
      });
      await options.lockRecoveryHooks?.afterRecoveryIntent?.();
      const recovered = await quarantineStaleLock({
        lockPath,
        root,
        repoRoot: options.repoRoot,
        staleAfterMs: options.staleAfterMs ?? 30_000,
        allowMalformed: false,
        hooks: options.lockRecoveryHooks,
        intent: recoveryIntent,
      });
      if (!recovered.recovered) {
        await completeLockRecovery({
          root,
          repoRoot: options.repoRoot,
          intent: recoveryIntent,
          outcome: recovered.outcome,
          snapshotDigest: recovered.snapshotDigest,
        });
        throw new Error("RUN_LOCK_ACTIVE");
      }
    }
  }
  throw new Error("RUN_LOCK_ACTIVE");
}

export async function verifyLiveRunState(options: {
  plan: ExperimentPlan;
  repoRoot?: string;
  authorization?: LiveAuthorization;
  oauth?: OAuthReadinessAttestation;
  committedResults?: PairedAssetResult[];
}): Promise<VerifiedLiveRunState> {
  const repoRoot = options.repoRoot ?? process.cwd();
  const root = await liveRunRoot(options.plan, repoRoot);
  await assertNoIncompleteArtifacts(root);

  const persistedAuthorizationRecord = await readOptionalJson(
    path.join(root, "authorization.json"),
    repoRoot,
    liveAuthorizationSchema,
    "live-authorization-snapshot",
  );
  const persistedAuthorization = persistedAuthorizationRecord
    ? parseLiveAuthorization(persistedAuthorizationRecord)
    : undefined;
  const authorization = options.authorization ?? persistedAuthorization;
  if (
    options.authorization &&
    persistedAuthorization &&
    options.authorization.digest !== persistedAuthorization.digest
  ) {
    throw new Error("LIVE_AUTHORIZATION_SNAPSHOT_CONFLICT");
  }
  if (authorization) {
    assertAuthorizationStateBinding(options.plan, authorization);
  }

  const persistedOAuth = await readOptionalJson(
    path.join(root, "oauth-readiness.json"),
    repoRoot,
    oauthReadinessSchema,
    "oauth-readiness",
  );
  const oauth = options.oauth ?? persistedOAuth;
  if (
    options.oauth &&
    persistedOAuth &&
    options.oauth.digest !== persistedOAuth.digest
  ) {
    throw new Error("OAUTH_READINESS_SNAPSHOT_CONFLICT");
  }
  if (oauth) {
    assertRecordDigest(oauth, "OAUTH_READINESS_DIGEST_MISMATCH");
    if (!authorization)
      throw new Error("OAUTH_READINESS_WITHOUT_AUTHORIZATION");
    assertOAuthBinding(oauth, authorization);
  }

  const namedClaims = await readNamedRecordDirectory(
    path.join(root, "claims"),
    repoRoot,
    liveClaimSchema,
    "live-claim",
  );
  const namedResponses = await readNamedRecordDirectory(
    path.join(root, "responses"),
    repoRoot,
    liveResponseSchema,
    "live-response",
  );
  const namedValidations = await readNamedRecordDirectory(
    path.join(root, "validations"),
    repoRoot,
    liveValidationSchema,
    "live-validation",
  );
  const claims = namedClaims.map(({ record }) => record);
  const responses = namedResponses.map(({ record }) => record);
  const validations = namedValidations.map(({ record }) => record);
  if (
    (claims.length || responses.length || validations.length) &&
    (!authorization || !oauth)
  ) {
    throw new Error("LIVE_STATE_BINDING_SNAPSHOT_MISSING");
  }
  if (!authorization) {
    if (
      options.committedResults?.some(
        (result) => result.schemaVersion === "cell-role-paired-result-v4",
      )
    ) {
      throw new Error("LIVE_RESULT_VALIDATION_MISSING");
    }
    return {
      authorization,
      oauth,
      claims,
      responses,
      validations,
      orphanClaims: [],
    };
  }

  const planUnits = new Map(
    options.plan.units.map((unit) => [unit.asset, unit]),
  );
  const seenClaimIds = new Set<string>();
  const seenClaimSequences = new Set<number>();
  for (const { name, record: claim } of namedClaims) {
    assertRecordDigest(claim, "LIVE_CLAIM_DIGEST_MISMATCH");
    assertClaimStageBinding(claim);
    const expectedClaimId = digestCanonicalJson({
      unitDigest: claim.unitDigest,
      arm: claim.arm,
      stage: claim.stage,
    });
    if (claim.claimId !== expectedClaimId || name !== `${claim.claimId}.json`) {
      throw new Error("LIVE_CLAIM_FILENAME_OR_ID_MISMATCH");
    }
    const plannedUnit = planUnits.get(claim.asset);
    if (
      !plannedUnit ||
      claim.planDigest !== options.plan.digest ||
      claim.authorizationDigest !== authorization.digest ||
      claim.implementationProvenanceDigest !==
        authorization.implementationProvenanceDigest ||
      claim.oauthReadinessDigest !== oauth!.digest ||
      claim.unitDigest !== digestJson(plannedUnit) ||
      !authorization.allowedAssets.includes(claim.asset) ||
      claim.settingsDigest !== authorization.settingsDigest ||
      claim.executableDigest !== authorization.executable.sha256 ||
      (claim.stage === "baseline" &&
        claim.promptDigest !== digestJson(plannedUnit.baselinePrompt)) ||
      (claim.stage === "semantics" &&
        claim.promptDigest !== digestJson(plannedUnit.semanticsPrompt))
    ) {
      throw new Error("STALE_OR_CONFLICTING_LIVE_CLAIM");
    }
    if (
      seenClaimIds.has(claim.claimId) ||
      seenClaimSequences.has(claim.sequence)
    ) {
      throw new Error("AMBIGUOUS_LIVE_CLAIM");
    }
    seenClaimIds.add(claim.claimId);
    seenClaimSequences.add(claim.sequence);
  }
  const expectedSequences = claims
    .map((claim) => claim.sequence)
    .sort((a, b) => a - b);
  if (expectedSequences.some((sequence, index) => sequence !== index + 1)) {
    throw new Error("LIVE_CLAIM_SEQUENCE_GAP");
  }
  assertAuthorizationAllowance(claims, authorization);

  const claimsByDigest = new Map(claims.map((claim) => [claim.digest, claim]));
  const respondedClaims = new Set<string>();
  const responsesByDigest = new Map<string, LiveResponse>();
  const responsesByClaimDigest = new Map<string, LiveResponse>();
  for (const { name, record: response } of namedResponses) {
    assertRecordDigest(response, "LIVE_RESPONSE_DIGEST_MISMATCH");
    const claim = claimsByDigest.get(response.claimDigest);
    if (!claim) throw new Error("ORPHAN_LIVE_RESPONSE");
    if (name !== `${claim.claimId}.json`) {
      throw new Error("LIVE_RESPONSE_FILENAME_MISMATCH");
    }
    if (respondedClaims.has(response.claimDigest)) {
      throw new Error("AMBIGUOUS_LIVE_RESPONSE");
    }
    if (
      response.planDigest !== claim.planDigest ||
      response.unitDigest !== claim.unitDigest ||
      response.authorizationDigest !== claim.authorizationDigest ||
      response.implementationProvenanceDigest !==
        claim.implementationProvenanceDigest ||
      response.promptDigest !== claim.promptDigest ||
      response.settingsDigest !== claim.settingsDigest ||
      digestCanonicalJson(response.orderedPredecessorEvidenceDigests) !==
        digestCanonicalJson([
          ...claim.orderedPredecessorEvidenceDigests,
          claim.digest,
        ])
    ) {
      throw new Error("LIVE_RESPONSE_CLAIM_MISMATCH");
    }
    respondedClaims.add(response.claimDigest);
    responsesByDigest.set(response.digest, response);
    responsesByClaimDigest.set(response.claimDigest, response);
  }

  const predecessorChainByUnit = new Map<string, string[]>();
  let unresolvedOrphan: LiveClaim | undefined;
  for (const claim of [...claims].sort(
    (left, right) => left.sequence - right.sequence,
  )) {
    assertDynamicClaimPromptBinding(
      claim,
      claims,
      responsesByClaimDigest,
      options.plan,
    );
    if (unresolvedOrphan) {
      throw new Error("LIVE_CLAIM_AFTER_ORPHAN");
    }
    const priorResponses = predecessorChainByUnit.get(claim.unitDigest) ?? [];
    const expectedPredecessors = [authorization.digest, ...priorResponses];
    if (
      digestCanonicalJson(claim.orderedPredecessorEvidenceDigests) !==
      digestCanonicalJson(expectedPredecessors)
    ) {
      throw new Error("LIVE_CLAIM_PREDECESSOR_MISMATCH");
    }
    const response = responsesByClaimDigest.get(claim.digest);
    if (response) {
      predecessorChainByUnit.set(claim.unitDigest, [
        ...priorResponses,
        response.digest,
      ]);
    } else {
      unresolvedOrphan = claim;
    }
  }

  const validationsByUnit = new Set<string>();
  const validationsByUnitDigest = new Map<string, LiveValidation>();
  for (const { name, record: validation } of namedValidations) {
    assertRecordDigest(validation, "LIVE_VALIDATION_DIGEST_MISMATCH");
    const unit = options.plan.units.find(
      (candidate) => digestJson(candidate) === validation.unitDigest,
    );
    if (
      !unit ||
      name !== `${validation.unitDigest}.json` ||
      validationsByUnit.has(validation.unitDigest) ||
      validation.planDigest !== options.plan.digest ||
      validation.authorizationDigest !== authorization.digest ||
      validation.implementationProvenanceDigest !==
        authorization.implementationProvenanceDigest ||
      validation.settingsDigest !== authorization.settingsDigest
    ) {
      throw new Error("LIVE_VALIDATION_BINDING_MISMATCH");
    }
    const unitClaims = claims
      .filter((claim) => claim.unitDigest === validation.unitDigest)
      .sort((left, right) => left.sequence - right.sequence);
    const expectedPromptDigests = unitClaims.map((claim) => claim.promptDigest);
    const unitResponses = unitClaims.map((claim) =>
      responsesByClaimDigest.get(claim.digest),
    );
    if (
      unitResponses.some((response) => !response) ||
      digestCanonicalJson(validation.promptDigests) !==
        digestCanonicalJson(expectedPromptDigests) ||
      digestCanonicalJson(validation.responseDigests) !==
        digestCanonicalJson(
          unitResponses.map((response) => response!.digest),
        ) ||
      digestCanonicalJson(validation.orderedPredecessorEvidenceDigests) !==
        digestCanonicalJson([
          authorization.digest,
          ...unitResponses.map((response) => response!.digest),
        ]) ||
      validation.responseDigests.some(
        (digest) => !responsesByDigest.has(digest),
      )
    ) {
      throw new Error("LIVE_VALIDATION_EVIDENCE_MISMATCH");
    }
    validationsByUnit.add(validation.unitDigest);
    validationsByUnitDigest.set(validation.unitDigest, validation);
  }

  for (const result of options.committedResults ?? []) {
    if (result.schemaVersion !== "cell-role-paired-result-v4") continue;
    const unit = options.plan.units.find(
      (candidate) => digestJson(candidate) === result.unitDigest,
    );
    const validation = validationsByUnitDigest.get(result.unitDigest);
    if (!unit || !validation || !oauth) {
      throw new Error("LIVE_RESULT_VALIDATION_MISSING");
    }
    const unitClaims = claims
      .filter((claim) => claim.unitDigest === result.unitDigest)
      .sort((left, right) => left.sequence - right.sequence);
    const unitResponses = unitClaims.map((claim) =>
      responsesByClaimDigest.get(claim.digest),
    );
    if (unitResponses.some((response) => !response)) {
      throw new Error("LIVE_RESULT_RESPONSE_MISSING");
    }
    const responseDigests = unitResponses.map((response) => response!.digest);
    const researchPromptDigest = unitClaims.find(
      (claim) => claim.stageKey === "llm-translation-research",
    )?.promptDigest;
    const expectedResultPredecessors = [
      authorization.digest,
      ...responseDigests,
      validation.digest,
    ];
    const live = result.liveExecution;
    if (!live) throw new Error("LIVE_RESULT_VALIDATION_MISSING");
    if (
      result.asset !== unit.asset ||
      live.authorizationDigest !== authorization.digest ||
      live.implementationProvenanceDigest !==
        authorization.implementationProvenanceDigest ||
      live.executableDigest !== authorization.executable.sha256 ||
      live.oauthReadinessDigest !== oauth.digest ||
      live.validationDigest !== validation.digest ||
      live.promptDigests.baseline !== digestJson(unit.baselinePrompt) ||
      live.promptDigests.semantics !== digestJson(unit.semanticsPrompt) ||
      live.promptDigests.translationResearch !== researchPromptDigest ||
      live.settingsDigest !== authorization.settingsDigest ||
      digestCanonicalJson(live.responseDigests) !==
        digestCanonicalJson(responseDigests) ||
      digestCanonicalJson(live.orderedPredecessorEvidenceDigests) !==
        digestCanonicalJson(expectedResultPredecessors) ||
      validation.resultDigest !== digestLiveValidationResult(result)
    ) {
      throw new Error("LIVE_RESULT_EVIDENCE_MISMATCH");
    }
  }

  const orphanClaims = claims.filter(
    (claim) => !respondedClaims.has(claim.digest),
  );
  return {
    authorization,
    oauth,
    claims,
    responses,
    validations,
    orphanClaims,
  };
}

export async function inspectLiveRunState(options: {
  plan: ExperimentPlan;
  repoRoot?: string;
}): Promise<{
  providerFree: true;
  runId: string;
  planDigest: string;
  lock: "absent" | "active" | "stale" | "malformed";
  claims: number;
  responses: number;
  orphanClaims: Array<{ claimId: string; claimDigest: string }>;
  orphanResponses: string[];
  unresolvedLockRecoveries: string[];
}> {
  const repoRoot = options.repoRoot ?? process.cwd();
  const root = await liveRunRoot(options.plan, repoRoot);
  const committedResults = await readPersistedResults(options.plan, repoRoot, {
    verifyLiveState: false,
  });
  const state = await verifyLiveRunState({
    plan: options.plan,
    repoRoot,
    committedResults,
  });
  const claimDigests = new Set(state.claims.map((claim) => claim.digest));
  const lock = await inspectLock(path.join(root, "run.lock"), repoRoot);
  const unresolvedLockRecoveries = await readUnresolvedLockRecoveries(
    root,
    repoRoot,
  );
  return {
    providerFree: true,
    runId: options.plan.runId,
    planDigest: options.plan.digest,
    lock,
    claims: state.claims.length,
    responses: state.responses.length,
    orphanClaims: state.orphanClaims.map((claim) => ({
      claimId: claim.claimId,
      claimDigest: claim.digest,
    })),
    orphanResponses: state.responses
      .filter((response) => !claimDigests.has(response.claimDigest))
      .map((response) => response.digest),
    unresolvedLockRecoveries: unresolvedLockRecoveries.map(
      (intent) => intent.recoveryId,
    ),
  };
}

export async function recoverOrphanClaimAsFailure(options: {
  plan: ExperimentPlan;
  claimDigest: string;
  repoRoot?: string;
}): Promise<{
  providerFree: true;
  claimDigest: string;
  responseDigest: string;
}> {
  if (!/^[a-f0-9]{64}$/.test(options.claimDigest)) {
    throw new Error("RECOVERY_CLAIM_DIGEST_INVALID");
  }
  const repoRoot = options.repoRoot ?? process.cwd();
  const root = await liveRunRoot(options.plan, repoRoot);
  const lockState = await inspectLock(path.join(root, "run.lock"), repoRoot);
  if (lockState !== "absent") {
    throw new Error(`RECOVERY_REQUIRES_NO_RUN_LOCK: ${lockState}`);
  }
  await assertNoUnresolvedLockRecoveries(root, repoRoot);
  const committedResults = await readPersistedResults(options.plan, repoRoot, {
    verifyLiveState: false,
  });
  const state = await verifyLiveRunState({
    plan: options.plan,
    repoRoot,
    committedResults,
  });
  const matches = state.orphanClaims.filter(
    (claim) => claim.digest === options.claimDigest,
  );
  if (matches.length !== 1) {
    throw new Error("RECOVERY_CLAIM_NOT_UNIQUE");
  }
  const claim = matches[0];
  if (
    claim.planDigest !== options.plan.digest ||
    !options.plan.units.some(
      (unit) =>
        digestJson(unit) === claim.unitDigest && unit.asset === claim.asset,
    )
  ) {
    throw new Error("RECOVERY_CLAIM_PLAN_MISMATCH");
  }
  const existing = await readLiveResponse({
    plan: options.plan,
    claim,
    repoRoot,
  });
  if (existing) throw new Error("RECOVERY_CLAIM_ALREADY_RESPONDED");
  const response = await persistLiveResponse({
    plan: options.plan,
    claim,
    outcome: {
      ok: false,
      code: "INTERRUPTED_CALL_OUTCOME_UNAVAILABLE",
      message:
        "Exact claimed call has no durable response; explicit provider-free recovery records a terminal failure and never redispatches it.",
      durationMs: 0,
    },
    repoRoot,
  });
  return {
    providerFree: true,
    claimDigest: claim.digest,
    responseDigest: response.digest,
  };
}

export async function recoverStaleRunLock(options: {
  plan: ExperimentPlan;
  repoRoot?: string;
  staleAfterMs?: number;
  lockRecoveryHooks?: LockRecoveryHooks;
}): Promise<{ providerFree: true; recovered: boolean }> {
  const repoRoot = options.repoRoot ?? process.cwd();
  return recoverStaleEvidenceRunLock({
    root: await liveRunRoot(options.plan, repoRoot),
    repoRoot,
    identity: { runId: options.plan.runId, planDigest: options.plan.digest },
    staleAfterMs: options.staleAfterMs,
    lockRecoveryHooks: options.lockRecoveryHooks,
  });
}

export async function recoverStaleEvidenceRunLock(options: {
  root: string;
  repoRoot?: string;
  identity: EvidenceRunLockIdentity;
  staleAfterMs?: number;
  lockRecoveryHooks?: LockRecoveryHooks;
  filesystem?: EvidenceRunLockFilesystem;
}): Promise<{ providerFree: true; recovered: boolean }> {
  if (options.filesystem)
    return evidenceRunLockFilesystem.run(options.filesystem, () =>
      recoverStaleEvidenceRunLock({ ...options, filesystem: undefined }),
    );
  const repoRoot = options.repoRoot ?? process.cwd();
  const strictFilesystem = evidenceRunLockFilesystem.getStore();
  const root = path.resolve(options.root);
  if (strictFilesystem) await strictFilesystem.ensurePrivateDirectory(root);
  else
    await resolveContainedPath({
      root: repoRoot,
      value: root,
      mustExist: false,
      code: "LIVE_STATE_PATH_ESCAPE",
    });
  const lockPath = path.join(root, "run.lock");
  const recoveredInterrupted = await reconcileInterruptedLockRecoveries({
    root,
    repoRoot,
    lockPath,
  });
  if ((await inspectLock(lockPath, repoRoot)) === "absent") {
    return { providerFree: true, recovered: recoveredInterrupted };
  }
  await assertNoUnresolvedLockRecoveries(root, repoRoot);
  const intent = await beginLockRecovery({
    identity: options.identity,
    root,
    repoRoot,
  });
  await options.lockRecoveryHooks?.afterRecoveryIntent?.();
  const result = await quarantineStaleLock({
    lockPath,
    root,
    repoRoot,
    staleAfterMs: options.staleAfterMs ?? 30_000,
    allowMalformed: false,
    hooks: options.lockRecoveryHooks,
    intent,
  });
  await options.lockRecoveryHooks?.beforeRecoveryCompletion?.();
  await completeLockRecovery({
    root,
    repoRoot,
    intent,
    outcome: result.recovered ? "recovered" : result.outcome,
    snapshotDigest: result.snapshotDigest,
  });
  return { providerFree: true, recovered: result.recovered };
}

export async function claimLiveStage(options: {
  plan: ExperimentPlan;
  authorization: LiveAuthorization;
  oauth: OAuthReadinessAttestation;
  unit: ExperimentUnit;
  request: ProviderRequest;
  orderedPredecessorEvidenceDigests: string[];
  repoRoot: string;
}): Promise<{ claim: LiveClaim; created: boolean }> {
  if (Date.now() >= Date.parse(options.authorization.expiresAt)) {
    throw new Error("AUTHORIZATION_EXPIRED");
  }
  const root = await liveRunRoot(options.plan, options.repoRoot);
  await persistAuthorizationSnapshot({
    plan: options.plan,
    authorization: options.authorization,
    repoRoot: options.repoRoot,
  });
  assertRecordDigest(options.oauth, "OAUTH_READINESS_DIGEST_MISMATCH");
  assertOAuthBinding(options.oauth, options.authorization);
  await writeLiveJson(
    options.repoRoot,
    path.join(root, "oauth-readiness.json"),
    options.oauth,
    "oauth-readiness",
  );
  await assertStateHealthy(
    root,
    options.repoRoot,
    options.plan,
    options.authorization,
  );
  const unitDigest = digestJson(options.unit);
  const stageKey = requestStageKey(options.request);
  const callKey = digestCanonicalJson({
    unitDigest,
    arm: options.request.arm,
    stage: options.request.stage,
  });
  const target = path.join(root, "claims", `${callKey}.json`);
  const existing = await readOptionalJson(
    target,
    options.repoRoot,
    liveClaimSchema,
    "live-claim",
  );
  const stable = {
    planDigest: options.plan.digest,
    implementationProvenanceDigest:
      options.authorization.implementationProvenanceDigest,
    authorizationDigest: options.authorization.digest,
    oauthReadinessDigest: options.oauth.digest,
    unitDigest,
    asset: options.unit.asset,
    arm: options.request.arm,
    stage: options.request.stage,
    stageKey,
    promptDigest: digestJson(options.request.prompt),
    settingsDigest: digestJson(options.request.settings),
    executableDigest: options.authorization.executable.sha256,
    orderedPredecessorEvidenceDigests:
      options.orderedPredecessorEvidenceDigests,
  } as const;
  if (existing) {
    assertRecordDigest(existing, "LIVE_CLAIM_DIGEST_MISMATCH");
    for (const [key, value] of Object.entries(stable)) {
      if (
        digestCanonicalJson(existing[key as keyof LiveClaim]) !==
        digestCanonicalJson(value)
      ) {
        throw new Error(`LIVE_CLAIM_CONFLICT: ${key}`);
      }
    }
    return { claim: existing, created: false };
  }
  assertRequestAuthorized(
    options.authorization,
    options.unit,
    stageKey,
    options.request,
  );
  const claims = await readClaims(root, options.repoRoot);
  const stageMaximum =
    options.authorization.stageAllowances.find(
      (entry) => entry.stage === stageKey,
    )?.maximumCalls ?? 0;
  if (
    claims.length >= options.authorization.maximumTotalCalls ||
    claims.filter((claim) => claim.stageKey === stageKey).length >= stageMaximum
  ) {
    throw new Error("AUTHORIZATION_CALL_ALLOWANCE_EXHAUSTED");
  }
  const core = claimCoreSchema.parse({
    schemaVersion: "cell-role-live-claim-v1",
    claimId: callKey,
    sequence: claims.length + 1,
    ...stable,
    claimedAt: new Date().toISOString(),
  });
  const claim = liveClaimSchema.parse({
    ...core,
    digest: digestCanonicalJson(core),
  });
  const result = await writeLiveJson(
    options.repoRoot,
    target,
    claim,
    "live-claim",
  );
  return { claim, created: result.created };
}

export async function readLiveResponse(options: {
  plan: ExperimentPlan;
  claim: LiveClaim;
  repoRoot: string;
}): Promise<LiveResponse | undefined> {
  assertRecordDigest(options.claim, "LIVE_CLAIM_DIGEST_MISMATCH");
  const root = await liveRunRoot(options.plan, options.repoRoot);
  const response = await readOptionalJson(
    path.join(root, "responses", `${options.claim.claimId}.json`),
    options.repoRoot,
    liveResponseSchema,
    "live-response",
  );
  if (!response) return undefined;
  assertRecordDigest(response, "LIVE_RESPONSE_DIGEST_MISMATCH");
  if (
    response.claimDigest !== options.claim.digest ||
    response.planDigest !== options.claim.planDigest ||
    response.unitDigest !== options.claim.unitDigest ||
    response.authorizationDigest !== options.claim.authorizationDigest ||
    response.promptDigest !== options.claim.promptDigest ||
    response.settingsDigest !== options.claim.settingsDigest
  ) {
    throw new Error("LIVE_RESPONSE_CLAIM_MISMATCH");
  }
  return response;
}

export async function persistLiveResponse(options: {
  plan: ExperimentPlan;
  claim: LiveClaim;
  outcome: SafeProviderOutcome;
  repoRoot: string;
}): Promise<LiveResponse> {
  assertRecordDigest(options.claim, "LIVE_CLAIM_DIGEST_MISMATCH");
  const root = await liveRunRoot(options.plan, options.repoRoot);
  const core = responseCoreSchema.parse({
    schemaVersion: "cell-role-live-response-v1",
    claimDigest: options.claim.digest,
    planDigest: options.claim.planDigest,
    unitDigest: options.claim.unitDigest,
    authorizationDigest: options.claim.authorizationDigest,
    implementationProvenanceDigest:
      options.claim.implementationProvenanceDigest,
    promptDigest: options.claim.promptDigest,
    settingsDigest: options.claim.settingsDigest,
    orderedPredecessorEvidenceDigests: [
      ...options.claim.orderedPredecessorEvidenceDigests,
      options.claim.digest,
    ],
    completedAt: new Date().toISOString(),
    outcome: safeProviderOutcomeSchema.parse(options.outcome),
  });
  const response = liveResponseSchema.parse({
    ...core,
    digest: digestCanonicalJson(core),
  });
  await writeLiveJson(
    options.repoRoot,
    path.join(root, "responses", `${options.claim.claimId}.json`),
    response,
    "live-response",
  );
  return response;
}

export async function persistLiveValidation(options: {
  plan: ExperimentPlan;
  authorization: LiveAuthorization;
  unit: ExperimentUnit;
  promptDigests: string[];
  settingsDigest: string;
  responseDigests: string[];
  orderedPredecessorEvidenceDigests: string[];
  result: PairedAssetResult;
  repoRoot: string;
}): Promise<LiveValidation> {
  const root = await liveRunRoot(options.plan, options.repoRoot);
  const target = path.join(
    root,
    "validations",
    `${digestJson(options.unit)}.json`,
  );
  const existing = await readOptionalJson(
    target,
    options.repoRoot,
    liveValidationSchema,
    "live-validation",
  );
  const stable = {
    planDigest: options.plan.digest,
    unitDigest: digestJson(options.unit),
    authorizationDigest: options.authorization.digest,
    implementationProvenanceDigest:
      options.authorization.implementationProvenanceDigest,
    promptDigests: options.promptDigests,
    settingsDigest: options.settingsDigest,
    responseDigests: options.responseDigests,
    orderedPredecessorEvidenceDigests:
      options.orderedPredecessorEvidenceDigests,
    resultDigest: digestLiveValidationResult(options.result),
  };
  if (existing) {
    assertRecordDigest(existing, "LIVE_VALIDATION_DIGEST_MISMATCH");
    for (const [key, value] of Object.entries(stable)) {
      if (
        digestCanonicalJson(existing[key as keyof LiveValidation]) !==
        digestCanonicalJson(value)
      ) {
        throw new Error(`LIVE_VALIDATION_CONFLICT: ${key}`);
      }
    }
    return existing;
  }
  const core = validationCoreSchema.parse({
    schemaVersion: "cell-role-live-validation-v1",
    ...stable,
    validatedAt: new Date().toISOString(),
  });
  const validation = liveValidationSchema.parse({
    ...core,
    digest: digestCanonicalJson(core),
  });
  await writeLiveJson(options.repoRoot, target, validation, "live-validation");
  return validation;
}

export async function liveRunRoot(
  plan: ExperimentPlan,
  repoRoot: string,
): Promise<string> {
  return resolveContainedPath({
    root: repoRoot,
    value: path.join(plan.outputRoot, plan.runId, "live-v1"),
    mustExist: false,
    code: "LIVE_STATE_PATH_ESCAPE",
  });
}

function assertDynamicClaimPromptBinding(
  claim: LiveClaim,
  claims: LiveClaim[],
  responsesByClaimDigest: Map<string, LiveResponse>,
  plan: ExperimentPlan,
): void {
  if (claim.stage !== "translation") return;
  const unit = plan.units.find(
    (candidate) => digestJson(candidate) === claim.unitDigest,
  );
  const semanticsClaim = claims.find(
    (candidate) =>
      candidate.unitDigest === claim.unitDigest &&
      candidate.stage === "semantics" &&
      candidate.sequence < claim.sequence,
  );
  const semanticsResponse = semanticsClaim
    ? responsesByClaimDigest.get(semanticsClaim.digest)
    : undefined;
  if (!unit || !semanticsResponse?.outcome.ok) {
    throw new Error("LIVE_TRANSLATION_PROMPT_PREDECESSOR_MISSING");
  }
  const bounds =
    "worksheetBounds" in unit
      ? unit.worksheetBounds
      : "summary" in unit
        ? unit.summary
        : undefined;
  if (!bounds) throw new Error("LIVE_TRANSLATION_PROMPT_BOUNDS_MISSING");
  const parsed = parseCellRoleSketchV02(semanticsResponse.outcome.content, {
    rowCount: bounds.rowCount,
    columnCount: bounds.columnCount,
  });
  if (
    !parsed.ok ||
    !validateCellRoleSketchV02ForCompilation(parsed.sketch).ok
  ) {
    throw new Error("LIVE_TRANSLATION_PROMPT_PREDECESSOR_INVALID");
  }
  const preamble =
    claim.arm === "llm-translation-research"
      ? "research" in unit
        ? unit.research?.translationPromptPreamble
        : undefined
      : "translationPromptPreamble" in unit
        ? unit.translationPromptPreamble
        : undefined;
  if (
    !preamble ||
    claim.promptDigest !== digestJson(`${preamble}\n${parsed.canonical}`)
  ) {
    throw new Error("LIVE_TRANSLATION_PROMPT_DIGEST_MISMATCH");
  }
}

function assertClaimStageBinding(claim: LiveClaim): void {
  const valid =
    (claim.stage === "baseline" &&
      claim.arm === "baseline" &&
      claim.stageKey === "baseline") ||
    (claim.stage === "semantics" &&
      claim.arm === "staged" &&
      claim.stageKey === "semantics") ||
    (claim.stage === "translation" &&
      ((claim.arm === "staged" && claim.stageKey === "translation") ||
        (claim.arm === "llm-translation-research" &&
          claim.stageKey === "llm-translation-research")));
  if (!valid) throw new Error("LIVE_CLAIM_STAGE_BINDING_MISMATCH");
}

function requestStageKey(request: ProviderRequest): LiveStageKey {
  if (request.arm === "llm-translation-research")
    return "llm-translation-research";
  return request.stage;
}

function assertRequestAuthorized(
  authorization: LiveAuthorization,
  unit: ExperimentUnit,
  stage: LiveStageKey,
  request: ProviderRequest,
): void {
  if (!authorization.allowedAssets.includes(unit.asset))
    throw new Error("ASSET_NOT_AUTHORIZED");
  if (
    !authorization.stageAllowances.some(
      (entry) => entry.stage === stage && entry.maximumCalls > 0,
    )
  ) {
    throw new Error("STAGE_NOT_AUTHORIZED");
  }
  if (digestJson(request.settings) !== authorization.settingsDigest) {
    throw new Error("CLAIM_SETTINGS_NOT_AUTHORIZED");
  }
  if (
    (request.stage === "baseline" &&
      (request.arm !== "baseline" || request.prompt !== unit.baselinePrompt)) ||
    (request.stage === "semantics" &&
      (request.arm !== "staged" || request.prompt !== unit.semanticsPrompt))
  ) {
    throw new Error("CLAIM_PROMPT_NOT_BOUND_TO_PLAN");
  }
  if (request.stage === "translation") {
    const preamble =
      request.arm === "llm-translation-research"
        ? "research" in unit
          ? unit.research?.translationPromptPreamble
          : undefined
        : "translationPromptPreamble" in unit
          ? unit.translationPromptPreamble
          : undefined;
    if (!preamble || !request.prompt.startsWith(`${preamble}\n`)) {
      throw new Error("CLAIM_PROMPT_NOT_BOUND_TO_PLAN");
    }
  }
}

async function assertStateHealthy(
  root: string,
  repoRoot: string,
  plan: ExperimentPlan,
  authorization: LiveAuthorization,
): Promise<void> {
  void root;
  const committedResults = await readPersistedResults(plan, repoRoot, {
    verifyLiveState: false,
  });
  const state = await verifyLiveRunState({
    plan,
    repoRoot,
    authorization,
    committedResults,
  });
  if (state.orphanClaims.length) {
    throw new Error(
      `ORPHAN_LIVE_CLAIM: ${state.orphanClaims
        .map((claim) => claim.claimId)
        .join(",")}`,
    );
  }
}

async function readClaims(
  root: string,
  repoRoot: string,
): Promise<LiveClaim[]> {
  return readRecordDirectory(
    path.join(root, "claims"),
    repoRoot,
    liveClaimSchema,
    "live-claim",
  );
}
async function readRecordDirectory<T>(
  directory: string,
  repoRoot: string,
  schema: z.ZodType<T>,
  role: string,
): Promise<T[]> {
  return (
    await readNamedRecordDirectory(directory, repoRoot, schema, role)
  ).map(({ record }) => record);
}

async function readNamedRecordDirectory<T>(
  directory: string,
  repoRoot: string,
  schema: z.ZodType<T>,
  role: string,
): Promise<Array<{ name: string; record: T }>> {
  const strictFilesystem = evidenceRunLockFilesystem.getStore();
  if (strictFilesystem) {
    let files;
    try {
      files = await strictFilesystem.readDirectoryFiles(directory);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
      throw error;
    }
    if (files.some(({ name }) => !/^[a-f0-9]{64}\.json$/.test(name)))
      throw new Error(`MALFORMED_LIVE_STATE_DIRECTORY: ${role}`);
    return files.map(({ name, bytes }) => ({
      name,
      record: schema.parse(
        validateEvidencePayload({ bytes, mediaType: "application/json", role }),
      ),
    }));
  }
  let names: string[];
  try {
    await assertNoIncompleteArtifacts(directory);
    names = await readdir(directory);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
  if (names.some((name) => !/^[a-f0-9]{64}\.json$/.test(name))) {
    throw new Error(`MALFORMED_LIVE_STATE_DIRECTORY: ${role}`);
  }
  const records: Array<{ name: string; record: T }> = [];
  for (const name of names.sort()) {
    const bytes = await readContainedArtifact({
      repoRoot,
      target: path.join(directory, name),
      pathErrorCode: "LIVE_STATE_PATH_ESCAPE",
    });
    records.push({
      name,
      record: schema.parse(
        validateEvidencePayload({ bytes, mediaType: "application/json", role }),
      ),
    });
  }
  return records;
}

async function readOptionalJson<T>(
  target: string,
  repoRoot: string,
  schema: z.ZodType<T>,
  role: string,
): Promise<T | undefined> {
  try {
    const bytes = await readContainedArtifact({
      repoRoot,
      target,
      pathErrorCode: "LIVE_STATE_PATH_ESCAPE",
    });
    return schema.parse(
      validateEvidencePayload({ bytes, mediaType: "application/json", role }),
    );
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    throw error;
  }
}

function assertRecordDigest(record: { digest: string }, code: string): void {
  const { digest, ...unsigned } = record;
  if (digestCanonicalJson(unsigned) !== digest) throw new Error(code);
}

async function writeLiveJson(
  repoRoot: string,
  target: string,
  value: unknown,
  role: string,
) {
  const strictFilesystem = evidenceRunLockFilesystem.getStore();
  if (strictFilesystem) {
    const bytes = Buffer.from(`${JSON.stringify(value, null, 2)}\n`);
    validateEvidencePayload({ bytes, mediaType: "application/json", role });
    return strictFilesystem.writeImmutable(target, bytes, 0o600);
  }
  return writeImmutableEvidenceFile({
    repoRoot,
    target,
    bytes: Buffer.from(`${JSON.stringify(value, null, 2)}\n`),
    mediaType: "application/json",
    role,
    mode: 0o600,
    pathErrorCode: "LIVE_STATE_PATH_ESCAPE",
  });
}

function assertAuthorizationStateBinding(
  plan: ExperimentPlan,
  authorization: LiveAuthorization,
): void {
  if (plan.schemaVersion === "cell-role-experiment-plan-v1") {
    throw new Error("AUTHORIZATION_REQUIRES_IMPLEMENTATION_PROVENANCE");
  }
  if (
    authorization.planDigest !== plan.digest ||
    authorization.implementationProvenanceDigest !==
      plan.implementationProvenanceDigest ||
    authorization.implementationTree !==
      plan.implementationProvenance.gitTree ||
    authorization.provider !== "openai-codex" ||
    authorization.model !== plan.generationSettings.model ||
    authorization.settingsDigest !== digestJson(plan.generationSettings) ||
    digestJson(authorization.settings) !== authorization.settingsDigest
  ) {
    throw new Error("LIVE_AUTHORIZATION_STATE_BINDING_MISMATCH");
  }
  const planAssets = new Set(plan.units.map((unit) => unit.asset));
  if (authorization.allowedAssets.some((asset) => !planAssets.has(asset))) {
    throw new Error("AUTHORIZATION_ASSET_MISMATCH");
  }
}

function assertAuthorizationAllowance(
  claims: LiveClaim[],
  authorization: LiveAuthorization,
): void {
  if (claims.length > authorization.maximumTotalCalls) {
    throw new Error("AUTHORIZATION_CALL_ALLOWANCE_EXCEEDED");
  }
  for (const allowance of authorization.stageAllowances) {
    if (
      claims.filter((claim) => claim.stageKey === allowance.stage).length >
      allowance.maximumCalls
    ) {
      throw new Error("AUTHORIZATION_STAGE_ALLOWANCE_EXCEEDED");
    }
  }
  if (
    claims.some(
      (claim) =>
        !authorization.stageAllowances.some(
          (allowance) =>
            allowance.stage === claim.stageKey && allowance.maximumCalls > 0,
        ),
    )
  ) {
    throw new Error("STAGE_NOT_AUTHORIZED");
  }
}

function assertOAuthBinding(
  attestation: OAuthReadinessAttestation,
  authorization: LiveAuthorization,
): void {
  if (
    !attestation.ready ||
    attestation.provider !== authorization.provider ||
    attestation.model !== authorization.model ||
    attestation.executablePath !== authorization.executable.path ||
    attestation.executableDigest !== authorization.executable.sha256
  )
    throw new Error("OAUTH_READINESS_BINDING_MISMATCH");
}

async function ensurePrivateDirectory(
  directory: string,
  repoRoot: string,
): Promise<void> {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const lexicalDirectory = path.resolve(directory);
  const lexicalStat = await lstat(lexicalDirectory);
  if (!lexicalStat.isDirectory() || lexicalStat.isSymbolicLink()) {
    throw new Error("LIVE_STATE_DIRECTORY_UNSAFE");
  }
  const resolved = await resolveContainedPath({
    root: repoRoot,
    value: directory,
    mustExist: true,
    code: "LIVE_STATE_PATH_ESCAPE",
  });
  const directoryStat = await lstat(resolved);
  if (!directoryStat.isDirectory() || directoryStat.isSymbolicLink())
    throw new Error("LIVE_STATE_DIRECTORY_UNSAFE");
  if ((directoryStat.mode & 0o077) !== 0)
    throw new Error("LIVE_STATE_DIRECTORY_NOT_PRIVATE");
}

type SafeRunLockFile = {
  path: string;
  bytes: Buffer;
  digest: string;
  dev: number;
  ino: number;
  mtimeMs: number;
};

type LockInspectionState = "absent" | "active" | "stale" | "malformed";

export type LockRecoveryHooks = {
  afterRecoveryIntent?: () => Promise<void>;
  afterStaleSnapshot?: () => Promise<void>;
  beforeReplacementRestore?: (options: {
    lockPath: string;
    movedPath: string;
  }) => Promise<void>;
  beforeRecoveryCompletion?: () => Promise<void>;
};

const lockRecoveryIntentCoreSchema = z
  .object({
    schemaVersion: z.literal("cell-role-lock-recovery-intent-v1"),
    recoveryId: sha256Schema,
    runId: z.string().min(1),
    planDigest: sha256Schema,
    pid: z.number().int().positive(),
    hostname: z.string().min(1),
    startedAt: z.string().datetime(),
    quarantineRelativePath: z.string().min(1),
  })
  .strict();
const lockRecoveryIntentSchema = lockRecoveryIntentCoreSchema
  .extend({ digest: sha256Schema })
  .strict();
type LockRecoveryIntent = z.infer<typeof lockRecoveryIntentSchema>;

const lockRecoverySnapshotCoreSchema = z
  .object({
    schemaVersion: z.literal("cell-role-lock-recovery-snapshot-v1"),
    recoveryId: sha256Schema,
    intentDigest: sha256Schema,
    sourceDigest: sha256Schema,
    sourceDev: z.number().int().nonnegative(),
    sourceIno: z.number().int().nonnegative(),
    sourceMtimeMs: z.number().finite(),
    classification: z.enum(["active", "stale", "malformed"]),
  })
  .strict();
const lockRecoverySnapshotSchema = lockRecoverySnapshotCoreSchema
  .extend({ digest: sha256Schema })
  .strict();
type LockRecoverySnapshot = z.infer<typeof lockRecoverySnapshotSchema>;

const LOCK_RECOVERY_OUTCOMES = [
  "active",
  "fresh",
  "peer-recovered",
  "peer-acquired",
  "recovered",
  "recovered-and-acquired",
  "replacement-restored",
  "interrupted-before-snapshot",
  "interrupted-before-move",
  "interrupted-recovered",
  "interrupted-replacement-restored",
  "superseded",
] as const;
type LockRecoveryOutcome = (typeof LOCK_RECOVERY_OUTCOMES)[number];
const lockRecoveryCompletionCoreSchema = z
  .object({
    schemaVersion: z.literal("cell-role-lock-recovery-completion-v1"),
    recoveryId: sha256Schema,
    intentDigest: sha256Schema,
    snapshotDigest: sha256Schema.optional(),
    outcome: z.enum(LOCK_RECOVERY_OUTCOMES),
    completedAt: z.string().datetime(),
  })
  .strict();
const lockRecoveryCompletionSchema = lockRecoveryCompletionCoreSchema
  .extend({ digest: sha256Schema })
  .strict();
type LockRecoveryCompletion = z.infer<typeof lockRecoveryCompletionSchema>;

async function readSafeRunLockFile(
  lockPath: string,
  repoRoot: string,
): Promise<SafeRunLockFile | undefined> {
  const lexicalLockPath = path.resolve(lockPath);
  const strictFilesystem = evidenceRunLockFilesystem.getStore();
  if (strictFilesystem) {
    try {
      const { bytes, identity } =
        await strictFilesystem.readFile(lexicalLockPath);
      return {
        path: lexicalLockPath,
        bytes,
        digest: sha256Bytes(bytes),
        dev: identity.dev,
        ino: identity.ino,
        mtimeMs: Number(identity.mtimeNs) / 1_000_000,
      };
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
      throw error;
    }
  }
  let handle;
  try {
    await resolveContainedPath({
      root: repoRoot,
      value: lexicalLockPath,
      mustExist: false,
      code: "LIVE_STATE_PATH_ESCAPE",
    });
    const lexicalStat = await lstat(lexicalLockPath);
    if (!lexicalStat.isFile() || lexicalStat.isSymbolicLink()) {
      throw new Error("RUN_LOCK_NOT_REGULAR_FILE");
    }
    handle = await open(
      lexicalLockPath,
      fsConstants.O_RDONLY | (fsConstants.O_NOFOLLOW ?? 0),
    );
    const openedStat = await handle.stat();
    const currentStat = await lstat(lexicalLockPath);
    if (
      !openedStat.isFile() ||
      !currentStat.isFile() ||
      currentStat.isSymbolicLink() ||
      openedStat.dev !== currentStat.dev ||
      openedStat.ino !== currentStat.ino
    ) {
      throw new Error("RUN_LOCK_NOT_REGULAR_FILE");
    }
    const bytes = await handle.readFile();
    const finalStat = await handle.stat();
    if (
      finalStat.dev !== openedStat.dev ||
      finalStat.ino !== openedStat.ino ||
      finalStat.mtimeMs !== openedStat.mtimeMs ||
      finalStat.size !== bytes.length
    ) {
      throw new Error("RUN_LOCK_MUTATED_DURING_READ");
    }
    return {
      path: lexicalLockPath,
      bytes,
      digest: sha256Bytes(bytes),
      dev: openedStat.dev,
      ino: openedStat.ino,
      mtimeMs: openedStat.mtimeMs,
    };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    if ((error as NodeJS.ErrnoException).code === "ELOOP") {
      throw new Error("RUN_LOCK_NOT_REGULAR_FILE");
    }
    throw error;
  } finally {
    await handle?.close().catch(() => undefined);
  }
}

async function assertOwnedRunLock(
  lockPath: string,
  repoRoot: string,
  token: string,
): Promise<SafeRunLockFile> {
  const currentFile = await readSafeRunLockFile(lockPath, repoRoot);
  if (!currentFile) throw new Error("RUN_LOCK_OWNERSHIP_LOST");
  let current: { token?: string };
  try {
    current = JSON.parse(currentFile.bytes.toString("utf8")) as {
      token?: string;
    };
  } catch {
    throw new Error("RUN_LOCK_OWNERSHIP_LOST");
  }
  if (current.token !== token) throw new Error("RUN_LOCK_OWNERSHIP_LOST");
  return currentFile;
}

async function releaseOwnedRunLock(
  lockPath: string,
  repoRoot: string,
  token: string,
): Promise<void> {
  const currentFile = await assertOwnedRunLock(lockPath, repoRoot, token);
  const strictFilesystem = evidenceRunLockFilesystem.getStore();
  if (strictFilesystem) {
    await strictFilesystem.unlinkIfIdentity(currentFile.path, {
      dev: currentFile.dev,
      ino: currentFile.ino,
      sha256: currentFile.digest,
    });
    return;
  }
  await resolveContainedPath({
    root: repoRoot,
    value: path.dirname(currentFile.path),
    mustExist: true,
    code: "LIVE_STATE_PATH_ESCAPE",
  });
  let currentStat;
  try {
    currentStat = await lstat(currentFile.path);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      throw new Error("RUN_LOCK_OWNERSHIP_LOST");
    }
    throw error;
  }
  if (
    !currentStat.isFile() ||
    currentStat.isSymbolicLink() ||
    currentStat.dev !== currentFile.dev ||
    currentStat.ino !== currentFile.ino
  ) {
    throw new Error("RUN_LOCK_OWNERSHIP_LOST");
  }
  await unlink(currentFile.path);
}

function classifyLockFile(
  lockFile: SafeRunLockFile,
): Exclude<LockInspectionState, "absent"> {
  let parsed: { pid?: number; hostname?: string };
  try {
    parsed = JSON.parse(lockFile.bytes.toString("utf8")) as {
      pid?: number;
      hostname?: string;
    };
  } catch {
    return "malformed";
  }
  if (
    !parsed ||
    typeof parsed !== "object" ||
    !Number.isInteger(parsed.pid) ||
    typeof parsed.hostname !== "string"
  ) {
    return "malformed";
  }
  return isProcessAlive(parsed.pid as number, parsed.hostname)
    ? "active"
    : "stale";
}

async function inspectLock(
  lockPath: string,
  repoRoot: string,
): Promise<LockInspectionState> {
  const lockFile = await readSafeRunLockFile(lockPath, repoRoot);
  return lockFile ? classifyLockFile(lockFile) : "absent";
}

function sameLockIdentity(
  left: SafeRunLockFile,
  right: SafeRunLockFile,
): boolean {
  return (
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.digest === right.digest
  );
}

function lockRecoveryDirectories(root: string): {
  intents: string;
  snapshots: string;
  completions: string;
} {
  const recoveryRoot = path.join(root, "lock-recovery");
  return {
    intents: path.join(recoveryRoot, "intents"),
    snapshots: path.join(recoveryRoot, "snapshots"),
    completions: path.join(recoveryRoot, "completions"),
  };
}

async function ensureLockRecoveryDirectories(
  root: string,
  repoRoot: string,
): Promise<ReturnType<typeof lockRecoveryDirectories>> {
  const directories = lockRecoveryDirectories(root);
  const strictFilesystem = evidenceRunLockFilesystem.getStore();
  if (strictFilesystem) {
    await strictFilesystem.ensurePrivateDirectory(directories.intents);
    await strictFilesystem.ensurePrivateDirectory(directories.snapshots);
    await strictFilesystem.ensurePrivateDirectory(directories.completions);
  } else {
    await ensurePrivateDirectory(directories.intents, repoRoot);
    await ensurePrivateDirectory(directories.snapshots, repoRoot);
    await ensurePrivateDirectory(directories.completions, repoRoot);
  }
  return directories;
}

async function readLockRecoveryJournal(
  root: string,
  repoRoot: string,
): Promise<{
  intents: LockRecoveryIntent[];
  snapshots: Map<string, LockRecoverySnapshot>;
  completions: Map<string, LockRecoveryCompletion>;
}> {
  const directories = lockRecoveryDirectories(root);
  const [namedIntents, namedSnapshots, namedCompletions] = await Promise.all([
    readNamedRecordDirectory(
      directories.intents,
      repoRoot,
      lockRecoveryIntentSchema,
      "lock-recovery-intent",
    ),
    readNamedRecordDirectory(
      directories.snapshots,
      repoRoot,
      lockRecoverySnapshotSchema,
      "lock-recovery-snapshot",
    ),
    readNamedRecordDirectory(
      directories.completions,
      repoRoot,
      lockRecoveryCompletionSchema,
      "lock-recovery-completion",
    ),
  ]);
  const intents = namedIntents.map(({ name, record }) => {
    assertRecordDigest(record, "RUN_LOCK_RECOVERY_INTENT_DIGEST_MISMATCH");
    if (name !== `${record.recoveryId}.json`) {
      throw new Error("RUN_LOCK_RECOVERY_INTENT_FILENAME_MISMATCH");
    }
    const expectedRelativePath = path.join(
      "stale-locks",
      record.recoveryId,
      "run.lock.json",
    );
    if (record.quarantineRelativePath !== expectedRelativePath) {
      throw new Error("RUN_LOCK_RECOVERY_TARGET_MISMATCH");
    }
    return record;
  });
  const intentById = new Map(
    intents.map((intent) => [intent.recoveryId, intent]),
  );
  const snapshots = new Map<string, LockRecoverySnapshot>();
  for (const { name, record } of namedSnapshots) {
    assertRecordDigest(record, "RUN_LOCK_RECOVERY_SNAPSHOT_DIGEST_MISMATCH");
    const intent = intentById.get(record.recoveryId);
    if (
      name !== `${record.recoveryId}.json` ||
      !intent ||
      record.intentDigest !== intent.digest ||
      snapshots.has(record.recoveryId)
    ) {
      throw new Error("RUN_LOCK_RECOVERY_SNAPSHOT_BINDING_MISMATCH");
    }
    snapshots.set(record.recoveryId, record);
  }
  const completions = new Map<string, LockRecoveryCompletion>();
  for (const { name, record } of namedCompletions) {
    assertRecordDigest(record, "RUN_LOCK_RECOVERY_COMPLETION_DIGEST_MISMATCH");
    const intent = intentById.get(record.recoveryId);
    const snapshot = snapshots.get(record.recoveryId);
    if (
      name !== `${record.recoveryId}.json` ||
      !intent ||
      record.intentDigest !== intent.digest ||
      (record.snapshotDigest !== undefined &&
        record.snapshotDigest !== snapshot?.digest) ||
      completions.has(record.recoveryId)
    ) {
      throw new Error("RUN_LOCK_RECOVERY_COMPLETION_BINDING_MISMATCH");
    }
    completions.set(record.recoveryId, record);
  }
  return { intents, snapshots, completions };
}

async function readUnresolvedLockRecoveries(
  root: string,
  repoRoot: string,
): Promise<LockRecoveryIntent[]> {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      const journal = await readLockRecoveryJournal(root, repoRoot);
      return journal.intents.filter(
        (intent) => !journal.completions.has(intent.recoveryId),
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      const concurrentImmutableWrite =
        message.startsWith("INCOMPLETE_ARTIFACT:") ||
        message === "MALFORMED_LIVE_STATE_DIRECTORY: lock-recovery-intent" ||
        message === "MALFORMED_LIVE_STATE_DIRECTORY: lock-recovery-snapshot" ||
        message === "MALFORMED_LIVE_STATE_DIRECTORY: lock-recovery-completion";
      if (!concurrentImmutableWrite || attempt === 49) throw error;
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
  }
  throw new Error("RUN_LOCK_RECOVERY_REQUIRED");
}

async function assertNoUnresolvedLockRecoveries(
  root: string,
  repoRoot: string,
): Promise<void> {
  if ((await readUnresolvedLockRecoveries(root, repoRoot)).length) {
    throw new Error("RUN_LOCK_RECOVERY_REQUIRED");
  }
}

async function waitForNoUnresolvedLockRecoveries(
  root: string,
  repoRoot: string,
): Promise<void> {
  const deadline = Date.now() + 5_000;
  while (Date.now() < deadline) {
    if ((await readUnresolvedLockRecoveries(root, repoRoot)).length === 0)
      return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error("RUN_LOCK_RECOVERY_REQUIRED");
}

async function writeLockRecoveryJson(options: {
  repoRoot: string;
  target: string;
  value: unknown;
  role: string;
}): Promise<void> {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      await writeLiveJson(
        options.repoRoot,
        options.target,
        options.value,
        options.role,
      );
      return;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (!message.startsWith("INCOMPLETE_ARTIFACT:") || attempt === 49) {
        throw error;
      }
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
  }
}

async function beginLockRecovery(options: {
  identity: EvidenceRunLockIdentity;
  root: string;
  repoRoot: string;
}): Promise<LockRecoveryIntent> {
  const directories = await ensureLockRecoveryDirectories(
    options.root,
    options.repoRoot,
  );
  const token = randomUUID();
  const recoveryId = digestCanonicalJson({
    ...options.identity,
    token,
  });
  const core = lockRecoveryIntentCoreSchema.parse({
    schemaVersion: "cell-role-lock-recovery-intent-v1",
    recoveryId,
    runId: options.identity.runId,
    planDigest: options.identity.planDigest,
    pid: process.pid,
    hostname: hostname(),
    startedAt: new Date().toISOString(),
    quarantineRelativePath: path.join(
      "stale-locks",
      recoveryId,
      "run.lock.json",
    ),
  });
  const intent = lockRecoveryIntentSchema.parse({
    ...core,
    digest: digestCanonicalJson(core),
  });
  await writeLockRecoveryJson({
    repoRoot: options.repoRoot,
    target: path.join(directories.intents, `${recoveryId}.json`),
    value: intent,
    role: "lock-recovery-intent",
  });
  return intent;
}

async function persistLockRecoverySnapshot(options: {
  root: string;
  repoRoot: string;
  intent: LockRecoveryIntent;
  source: SafeRunLockFile;
  classification: Exclude<LockInspectionState, "absent">;
}): Promise<LockRecoverySnapshot> {
  const directories = await ensureLockRecoveryDirectories(
    options.root,
    options.repoRoot,
  );
  const core = lockRecoverySnapshotCoreSchema.parse({
    schemaVersion: "cell-role-lock-recovery-snapshot-v1",
    recoveryId: options.intent.recoveryId,
    intentDigest: options.intent.digest,
    sourceDigest: options.source.digest,
    sourceDev: options.source.dev,
    sourceIno: options.source.ino,
    sourceMtimeMs: options.source.mtimeMs,
    classification: options.classification,
  });
  const snapshot = lockRecoverySnapshotSchema.parse({
    ...core,
    digest: digestCanonicalJson(core),
  });
  await writeLockRecoveryJson({
    repoRoot: options.repoRoot,
    target: path.join(
      directories.snapshots,
      `${options.intent.recoveryId}.json`,
    ),
    value: snapshot,
    role: "lock-recovery-snapshot",
  });
  return snapshot;
}

async function completeLockRecovery(options: {
  root: string;
  repoRoot: string;
  intent: LockRecoveryIntent;
  outcome: LockRecoveryOutcome;
  snapshotDigest?: string;
}): Promise<LockRecoveryCompletion> {
  const directories = await ensureLockRecoveryDirectories(
    options.root,
    options.repoRoot,
  );
  const core = lockRecoveryCompletionCoreSchema.parse({
    schemaVersion: "cell-role-lock-recovery-completion-v1",
    recoveryId: options.intent.recoveryId,
    intentDigest: options.intent.digest,
    ...(options.snapshotDigest
      ? { snapshotDigest: options.snapshotDigest }
      : {}),
    outcome: options.outcome,
    completedAt: new Date().toISOString(),
  });
  const completion = lockRecoveryCompletionSchema.parse({
    ...core,
    digest: digestCanonicalJson(core),
  });
  await writeLockRecoveryJson({
    repoRoot: options.repoRoot,
    target: path.join(
      directories.completions,
      `${options.intent.recoveryId}.json`,
    ),
    value: completion,
    role: "lock-recovery-completion",
  });
  return completion;
}

async function restoreMovedReplacement(options: {
  moved: SafeRunLockFile;
  lockPath: string;
  repoRoot: string;
}): Promise<void> {
  const strictFilesystem = evidenceRunLockFilesystem.getStore();
  if (strictFilesystem) {
    try {
      await strictFilesystem.moveNoReplace(
        options.moved.path,
        options.lockPath,
        {
          dev: options.moved.dev,
          ino: options.moved.ino,
          sha256: options.moved.digest,
        },
      );
      return;
    } catch {
      throw new Error("RUN_LOCK_RECOVERY_CONFLICT");
    }
  }
  await resolveContainedPath({
    root: options.repoRoot,
    value: path.dirname(options.lockPath),
    mustExist: true,
    code: "LIVE_STATE_PATH_ESCAPE",
  });
  await resolveContainedPath({
    root: options.repoRoot,
    value: path.dirname(options.moved.path),
    mustExist: true,
    code: "LIVE_STATE_PATH_ESCAPE",
  });
  try {
    await link(options.moved.path, options.lockPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      throw new Error("RUN_LOCK_RECOVERY_CONFLICT");
    }
    throw error;
  }
  const restored = await readSafeRunLockFile(
    options.lockPath,
    options.repoRoot,
  );
  if (!restored || !sameLockIdentity(restored, options.moved)) {
    throw new Error("RUN_LOCK_RECOVERY_CONFLICT");
  }
  try {
    await unlink(options.moved.path);
  } catch {
    throw new Error("RUN_LOCK_RECOVERY_CONFLICT");
  }
}

function lockMatchesRecoverySnapshot(
  lockFile: SafeRunLockFile,
  snapshot: LockRecoverySnapshot,
): boolean {
  return (
    lockFile.dev === snapshot.sourceDev &&
    lockFile.ino === snapshot.sourceIno &&
    lockFile.digest === snapshot.sourceDigest
  );
}

async function reconcileInterruptedLockRecoveries(options: {
  root: string;
  repoRoot: string;
  lockPath: string;
}): Promise<boolean> {
  let recovered = false;
  const journal = await readLockRecoveryJournal(options.root, options.repoRoot);
  const unresolved = journal.intents.filter(
    (intent) => !journal.completions.has(intent.recoveryId),
  );
  for (const intent of unresolved) {
    if (isProcessAlive(intent.pid, intent.hostname)) {
      throw new Error("RUN_LOCK_RECOVERY_ACTIVE");
    }
    const snapshot = journal.snapshots.get(intent.recoveryId);
    if (!snapshot) {
      await completeLockRecovery({
        root: options.root,
        repoRoot: options.repoRoot,
        intent,
        outcome: "interrupted-before-snapshot",
      });
      continue;
    }
    const targetPath = path.join(options.root, intent.quarantineRelativePath);
    const [source, target] = await Promise.all([
      readSafeRunLockFile(options.lockPath, options.repoRoot),
      readSafeRunLockFile(targetPath, options.repoRoot),
    ]);
    if (target) {
      if (lockMatchesRecoverySnapshot(target, snapshot)) {
        if (source && lockMatchesRecoverySnapshot(source, snapshot)) {
          throw new Error("RUN_LOCK_RECOVERY_CONFLICT");
        }
        await completeLockRecovery({
          root: options.root,
          repoRoot: options.repoRoot,
          intent,
          outcome: "interrupted-recovered",
          snapshotDigest: snapshot.digest,
        });
        recovered = true;
        continue;
      }
      if (!source) {
        await restoreMovedReplacement({
          moved: target,
          lockPath: options.lockPath,
          repoRoot: options.repoRoot,
        });
      } else if (!sameLockIdentity(source, target)) {
        throw new Error("RUN_LOCK_RECOVERY_CONFLICT");
      }
      await completeLockRecovery({
        root: options.root,
        repoRoot: options.repoRoot,
        intent,
        outcome: "interrupted-replacement-restored",
        snapshotDigest: snapshot.digest,
      });
      recovered = true;
      continue;
    }
    if (!source) throw new Error("RUN_LOCK_RECOVERY_CONFLICT");
    await completeLockRecovery({
      root: options.root,
      repoRoot: options.repoRoot,
      intent,
      outcome: lockMatchesRecoverySnapshot(source, snapshot)
        ? "interrupted-before-move"
        : "superseded",
      snapshotDigest: snapshot.digest,
    });
  }
  return recovered;
}

async function quarantineStaleLock(options: {
  lockPath: string;
  root: string;
  repoRoot: string;
  staleAfterMs: number;
  allowMalformed: boolean;
  hooks?: LockRecoveryHooks;
  intent: LockRecoveryIntent;
}): Promise<{
  recovered: boolean;
  outcome: LockRecoveryOutcome;
  snapshotDigest?: string;
}> {
  const staleSnapshot = await readSafeRunLockFile(
    options.lockPath,
    options.repoRoot,
  );
  if (!staleSnapshot) {
    return { recovered: true, outcome: "peer-recovered" };
  }
  const state = classifyLockFile(staleSnapshot);
  const snapshot = await persistLockRecoverySnapshot({
    root: options.root,
    repoRoot: options.repoRoot,
    intent: options.intent,
    source: staleSnapshot,
    classification: state,
  });
  if (Date.now() - staleSnapshot.mtimeMs < options.staleAfterMs) {
    return {
      recovered: false,
      outcome: "fresh",
      snapshotDigest: snapshot.digest,
    };
  }
  if (
    state === "active" ||
    (state === "malformed" && !options.allowMalformed)
  ) {
    return {
      recovered: false,
      outcome: "active",
      snapshotDigest: snapshot.digest,
    };
  }

  await options.hooks?.afterStaleSnapshot?.();

  const staleDirectory = path.join(options.root, "stale-locks");
  const archiveDirectory = path.join(
    options.root,
    path.dirname(options.intent.quarantineRelativePath),
  );
  const strictFilesystem = evidenceRunLockFilesystem.getStore();
  let target: string;
  if (strictFilesystem) {
    await strictFilesystem.ensurePrivateDirectory(staleDirectory);
    await strictFilesystem.ensurePrivateDirectory(archiveDirectory);
    target = path.join(options.root, options.intent.quarantineRelativePath);
  } else {
    await ensurePrivateDirectory(staleDirectory, options.repoRoot);
    await mkdir(archiveDirectory, { recursive: true, mode: 0o700 });
    await ensurePrivateDirectory(archiveDirectory, options.repoRoot);
    target = await resolveContainedPath({
      root: options.repoRoot,
      value: path.join(options.root, options.intent.quarantineRelativePath),
      mustExist: false,
      code: "LIVE_STATE_PATH_ESCAPE",
    });

    // Revalidate both parents immediately before the atomic move. The recovery
    // ID owns a deterministic private archive directory and its target is absent.
    await resolveContainedPath({
      root: options.repoRoot,
      value: path.dirname(staleSnapshot.path),
      mustExist: true,
      code: "LIVE_STATE_PATH_ESCAPE",
    });
    await resolveContainedPath({
      root: options.repoRoot,
      value: archiveDirectory,
      mustExist: true,
      code: "LIVE_STATE_PATH_ESCAPE",
    });
  }
  try {
    if (strictFilesystem)
      await strictFilesystem.moveNoReplace(staleSnapshot.path, target, {
        dev: staleSnapshot.dev,
        ino: staleSnapshot.ino,
        sha256: staleSnapshot.digest,
      });
    else await rename(staleSnapshot.path, target);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return {
        recovered: true,
        outcome: "peer-recovered",
        snapshotDigest: snapshot.digest,
      };
    }
    throw error;
  }

  const moved = await readSafeRunLockFile(target, options.repoRoot);
  if (!moved) throw new Error("RUN_LOCK_RECOVERY_CONFLICT");
  if (sameLockIdentity(staleSnapshot, moved)) {
    return {
      recovered: true,
      outcome: "recovered",
      snapshotDigest: snapshot.digest,
    };
  }

  await options.hooks?.beforeReplacementRestore?.({
    lockPath: staleSnapshot.path,
    movedPath: moved.path,
  });
  await restoreMovedReplacement({
    moved,
    lockPath: staleSnapshot.path,
    repoRoot: options.repoRoot,
  });
  return {
    recovered: false,
    outcome: "replacement-restored",
    snapshotDigest: snapshot.digest,
  };
}

function isProcessAlive(pid: number, ownerHostname: string): boolean {
  if (ownerHostname !== hostname()) return true;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== "ESRCH";
  }
}
