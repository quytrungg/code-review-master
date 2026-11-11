/**
 * A tiny unified-diff parser for the skill evolution workbench.
 *
 * The server already computed the diff with `difflib`; the browser only has to render it. The
 * split view pairs the deleted and added lines of a hunk side by side, the way GitHub does.
 */

export type DiffRowKind = "context" | "add" | "del" | "hunk";

export interface DiffRow {
  kind: DiffRowKind;
  /** The text without its leading `-`, `+` or space marker. */
  text: string;
}

/** One side-by-side row: the left pane's line and the right pane's line. */
export interface SplitRow {
  left: DiffRow | null;
  right: DiffRow | null;
}

/** Parse a unified diff into rows. Lines outside a hunk (the `---`/`+++` headers) are dropped. */
export function parseUnifiedDiff(diff: string): DiffRow[] {
  const rows: DiffRow[] = [];
  let inHunk = false;

  for (const line of diff.split("\n")) {
    if (line.startsWith("@@")) {
      inHunk = true;
      rows.push({ kind: "hunk", text: line });
      continue;
    }
    if (!inHunk) continue;
    if (line.startsWith("---") || line.startsWith("+++")) continue;
    if (line.startsWith("\\")) continue; // "\ No newline at end of file"
    if (line.startsWith("+")) {
      rows.push({ kind: "add", text: line.slice(1) });
      continue;
    }
    if (line.startsWith("-")) {
      rows.push({ kind: "del", text: line.slice(1) });
      continue;
    }
    if (line.startsWith(" ")) {
      rows.push({ kind: "context", text: line.slice(1) });
      continue;
    }
    // An empty line is an empty context line in a unified diff.
    if (line === "") {
      rows.push({ kind: "context", text: "" });
    }
  }
  return rows;
}

/**
 * Pair the rows of a hunk into side-by-side rows.
 *
 * A run of deletions followed by a run of additions is zipped together; the extra lines of the
 * longer run get an empty counterpart on the other side.
 */
export function toSplitRows(rows: DiffRow[]): SplitRow[] {
  const split: SplitRow[] = [];
  let index = 0;

  while (index < rows.length) {
    const row = rows[index];
    if (row.kind === "hunk") {
      split.push({ left: null, right: row });
      index += 1;
      continue;
    }
    if (row.kind === "context") {
      split.push({ left: row, right: row });
      index += 1;
      continue;
    }

    // A change block: deletions, then additions.
    const deletions: DiffRow[] = [];
    const additions: DiffRow[] = [];
    while (index < rows.length && rows[index].kind === "del") {
      deletions.push(rows[index]);
      index += 1;
    }
    while (index < rows.length && rows[index].kind === "add") {
      additions.push(rows[index]);
      index += 1;
    }
    const height = Math.max(deletions.length, additions.length);
    for (let line = 0; line < height; line += 1) {
      split.push({ left: deletions[line] ?? null, right: additions[line] ?? null });
    }
  }
  return split;
}

/** How many lines a file gained and lost, from its diff. */
export function diffStats(rows: DiffRow[]): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const row of rows) {
    if (row.kind === "add") added += 1;
    if (row.kind === "del") removed += 1;
  }
  return { added, removed };
}
