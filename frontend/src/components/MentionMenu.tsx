import { cn } from "@/lib/utils";
import type { ThreadOption } from "@/types";

export interface MentionMenuProps {
  options: ThreadOption[];
  activeIndex: number;
  query: string;
  onPick: (ordinal: number) => void;
  /** The composer measures the room in its scroll pane and picks the side. */
  placement?: "above" | "below";
  /** Pixels; capped by the room the composer measured. */
  maxHeight?: number;
}

/**
 * The `#` typeahead. Rendered by the composer directly under its textarea; the composer owns the
 * caret/state and the placement, this only lists what can be referenced and reports the pick.
 */
export function MentionMenu({
  options,
  activeIndex,
  query,
  onPick,
  placement = "below",
  maxHeight = 224,
}: MentionMenuProps) {
  return (
    <div
      role="listbox"
      aria-label="Referenced review threads"
      style={{ maxHeight }}
      className={cn(
        "absolute inset-x-0 z-20 overflow-y-auto rounded-lg border border-borderStrong bg-surface p-1 shadow-[0_18px_40px_-20px_rgba(0,0,0,0.9)]",
        placement === "above" ? "bottom-full mb-1" : "top-full mt-1",
      )}
    >
      {options.length === 0 ? (
        <p className="px-2 py-1.5 text-[11px] text-inkMuted">
          No thread matches {query ? `#${query}` : "that"} — only this review&apos;s threads can be
          referenced.
        </p>
      ) : (
        options.map((option, index) => (
          <button
            key={option.ordinal}
            type="button"
            role="option"
            aria-selected={index === activeIndex}
            // Keep the textarea focused so the caret position survives the click.
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onPick(option.ordinal)}
            className={cn(
              "flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left transition-colors",
              index === activeIndex ? "bg-accent/15 text-ink" : "text-inkMuted hover:bg-surfaceMuted",
            )}
          >
            <span className="mt-[1px] rounded bg-accent/15 px-1 font-mono text-[11px] font-semibold text-accent">
              #{option.ordinal}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-mono text-[11px] text-inkMuted">
                {option.file_path}:{option.line_number}
              </span>
              <span className="block truncate text-[11px]">{option.excerpt}</span>
            </span>
          </button>
        ))
      )}
    </div>
  );
}

/** Index of the `#` token the caret sits in, or null when the caret is elsewhere. */
export function activeMention(
  value: string,
  caret: number,
): { start: number; query: string } | null {
  const before = value.slice(0, caret);
  const match = /(?:^|[\s(])#(\d*)$/.exec(before);
  if (!match) return null;
  const query = match[1] ?? "";
  return { start: caret - query.length - 1, query };
}

export function filterOptions(
  options: ThreadOption[],
  query: string,
  currentOrdinal: number,
  limit = 6,
): ThreadOption[] {
  return options
    .filter((option) => option.ordinal !== currentOrdinal)
    .filter((option) => !query || String(option.ordinal).startsWith(query))
    .slice(0, limit);
}

/** Replace the `#…` token with `#ordinal ` and return the caret position after it. */
export function insertMention(
  value: string,
  start: number,
  end: number,
  ordinal: number,
): { value: string; caret: number } {
  const inserted = `#${ordinal} `;
  return {
    value: value.slice(0, start) + inserted + value.slice(end),
    caret: start + inserted.length,
  };
}
