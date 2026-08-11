import { lstat, realpath } from "node:fs/promises";
import path from "node:path";

function inside(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return (
    relative === "" ||
    (!relative.startsWith("..") && !path.isAbsolute(relative))
  );
}

async function exists(target: string): Promise<boolean> {
  try {
    await lstat(target);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
    throw error;
  }
}

export async function resolveContainedPath(options: {
  root: string;
  value: string;
  mustExist: boolean;
  code?: string;
}): Promise<string> {
  const code = options.code ?? "PATH_ESCAPE";
  const lexicalRoot = path.resolve(options.root);
  const root = await realpath(lexicalRoot);
  const target = path.resolve(lexicalRoot, options.value);
  // macOS commonly exposes /var through the /private/var realpath. Accept an
  // already-canonical child returned by an earlier containment check while
  // still rejecting paths outside both spellings of the root.
  if (!inside(lexicalRoot, target) && !inside(root, target)) {
    throw new Error(code);
  }

  if (options.mustExist) {
    const resolved = await realpath(target);
    if (!inside(root, resolved)) throw new Error(code);
    return resolved;
  }

  let ancestor = target;
  while (!(await exists(ancestor))) {
    const parent = path.dirname(ancestor);
    if (parent === ancestor) throw new Error(code);
    ancestor = parent;
  }
  const resolvedAncestor = await realpath(ancestor);
  if (!inside(root, resolvedAncestor)) throw new Error(code);
  const projected = path.resolve(
    resolvedAncestor,
    path.relative(ancestor, target),
  );
  if (!inside(root, projected)) throw new Error(code);
  return target;
}

export async function assertContainedExistingPath(
  root: string,
  target: string,
  code = "PATH_ESCAPE",
): Promise<void> {
  await resolveContainedPath({ root, value: target, mustExist: true, code });
}
