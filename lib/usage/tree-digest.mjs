import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { join, relative } from "node:path";


const IGNORED_NAMES = new Set([".DS_Store", "__pycache__"]);


async function listDigestFiles(root, directory = root) {
  const files = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (IGNORED_NAMES.has(entry.name)) continue;
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await listDigestFiles(root, path)));
    } else if (entry.isFile()) {
      files.push(path);
    } else {
      throw new Error(`Unsupported entry in digest payload: ${relative(root, path)}`);
    }
  }
  return files;
}


export async function treeDigest(root) {
  const digest = createHash("sha256");
  const files = (await listDigestFiles(root))
    .map((path) => ({ path, name: relative(root, path).split("\\").join("/") }))
    .sort((left, right) =>
      left.name < right.name ? -1 : left.name > right.name ? 1 : 0,
    );
  for (const { path, name } of files) {
    digest.update(name);
    digest.update("\0");
    digest.update(await readFile(path));
    digest.update("\0");
  }
  return digest.digest("hex");
}
