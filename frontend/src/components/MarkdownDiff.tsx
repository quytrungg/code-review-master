import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { diffStats, parseUnifiedDiff, toSplitRows, type DiffRow } from "@/lib/diff";

export type DiffViewMode = "unified" | "split";

function LineCell({ row }: { row: DiffRow | null }) {
  if (!row) {
    return <div className="flex whitespace-pre bg-surfaceMuted/20 px-2 py-0.5" />;
  }
  const isAdd = row.kind === "add";
  const isDel = row.kind === "del";
  const marker = isAdd ? "+" : isDel ? "-" : " ";
  const tint = isAdd ? "bg-add/70" : isDel ? "bg-del/70" : "";
  const markerTone = isAdd ? "text-success" : isDel ? "text-danger" : "text-inkMuted/40";
  return (
    <div className={cn("flex whitespace-pre", tint)}>
      <span
        className={cn(
          "w-6 shrink-0 select-none border-r border-border/50 px-1 text-center",
          markerTone,
        )}
      >
        {marker}
      </span>
      <span className="flex-1 px-2 text-ink">
        {row.kind === "hunk" ? (
          <span className="text-[11px] text-inkMuted">{row.text}</span>
        ) : (
          row.text
        )}
      </span>
    </div>
  );
}

/**
 * A GitHub-style diff of one proposed rule file.
 *
 * The unified view is a single column with `+`/`-` gutters; the split view puts the old text on
 * the left and the new text on the right. Markdown is rendered as plain monospace text — these
 * are rule files, and the point is to read the change, not to preview the formatting.
 */
export function MarkdownDiff({
  diff,
  mode = "unified",
}: {
  diff: string;
  mode?: DiffViewMode;
}) {
  const rows = useMemo(() => parseUnifiedDiff(diff), [diff]);
  const split = useMemo(() => toSplitRows(rows), [rows]);
  const stats = useMemo(() => diffStats(rows), [rows]);

  if (rows.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-borderStrong/70 px-3 py-6 text-center text-xs text-inkMuted">
        This proposal has no textual change.
      </p>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <div className="flex items-center justify-between border-b border-border bg-surfaceMuted/50 px-3 py-1.5 text-[11px] text-inkMuted">
        <span>
          <span className="text-success">+{stats.added}</span>{" / "}
          <span className="text-danger">−{stats.removed}</span> line(s)
        </span>
      </div>
      <div className="overflow-x-auto">
        <pre className="min-w-full font-mono text-[12px] leading-[1.6]">
          <code>
            {mode === "unified"
              ? rows.map((row, index) => <LineCell key={index} row={row} />)
              : split.map((row, index) => (
                  <div key={index} className="grid grid-cols-2 divide-x divide-border/50">
                    <LineCell row={row.left} />
                    <LineCell row={row.right} />
                  </div>
                ))}
          </code>
        </pre>
      </div>
    </div>
  );
}
