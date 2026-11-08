import { cn } from "@/lib/utils";

export type ThreadFilter = "all" | "ai" | "github" | "needs";

export interface FilterCounts {
  all: number;
  ai: number;
  github: number;
  needs: number;
}

const TABS: { value: ThreadFilter; label: string; emoji: string | null }[] = [
  { value: "all", label: "All", emoji: null },
  { value: "ai", label: "AI Findings", emoji: "🤖" },
  { value: "github", label: "GitHub Threads", emoji: "🐙" },
  { value: "needs", label: "Needs Response", emoji: "⚠️" },
];

export function ThreadFilterBar({
  value,
  counts,
  onChange,
}: {
  value: ThreadFilter;
  counts: FilterCounts;
  onChange: (value: ThreadFilter) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-border bg-surface/70 p-1.5">
      {TABS.map(({ value: tab, label, emoji }) => {
        const active = value === tab;
        return (
          <button
            key={tab}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(tab)}
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-xs font-medium transition-colors",
              active
                ? tab === "github"
                  ? "border-borderStrong bg-borderStrong/40 text-ink"
                  : "border-accent/45 bg-accent/12 text-accent"
                : "border-transparent text-inkMuted hover:bg-surfaceMuted hover:text-ink",
            )}
          >
            {emoji ? <span aria-hidden>{emoji}</span> : null}
            {label} ({counts[tab]})
          </button>
        );
      })}
    </div>
  );
}
