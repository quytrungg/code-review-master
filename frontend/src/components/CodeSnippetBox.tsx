import { forwardRef, useState } from "react";
import { Bot, Check, Copy, Github } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { DiffViewer } from "@/components/DiffViewer";
import { cn } from "@/lib/utils";
import type { ReviewThread } from "@/types";

export interface CodeSnippetBoxProps {
  index: number;
  thread: ReviewThread;
  selected: boolean;
  onSelect: () => void;
}

export const CodeSnippetBox = forwardRef<HTMLDivElement, CodeSnippetBoxProps>(
  ({ index, thread, selected, onSelect }, ref) => {
    const [copied, setCopied] = useState(false);

    async function copyPath() {
      try {
        await navigator.clipboard.writeText(thread.file_path);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1600);
      } catch {
        setCopied(false);
      }
    }

    return (
      <div
        ref={ref}
        role="button"
        tabIndex={0}
        onClick={onSelect}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onSelect();
          }
        }}
        className={cn(
          "surface-card cursor-pointer overflow-hidden border-l-2 transition-all",
          thread.origin === "GITHUB_EXISTING" ? "border-l-accentStrong" : "border-l-accent",
          selected
            ? "border-accent/60 ring-2 ring-accent/40"
            : "hover:border-borderStrong hover:shadow-[0_10px_30px_-24px_rgba(124,139,255,0.7)]",
        )}
        aria-pressed={selected}
      >
        <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-border bg-surface/95 px-3 py-2 backdrop-blur">
          <span className="grid h-5 w-5 place-items-center rounded bg-accent/15 text-[11px] font-semibold text-accent">
            {thread.ordinal || index + 1}
          </span>
          {thread.origin === "GITHUB_EXISTING" ? (
            <Github className="h-3.5 w-3.5 shrink-0 text-inkMuted" />
          ) : (
            <Bot className="h-3.5 w-3.5 shrink-0 text-inkMuted" />
          )}
          <span className="truncate font-mono text-xs text-ink" title={thread.file_path}>
            {thread.file_path}
          </span>
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              void copyPath();
            }}
            title="Copy the file path"
            aria-label="Copy the file path"
            className="shrink-0 rounded p-0.5 text-inkMuted transition-colors hover:text-ink"
          >
            {copied ? (
              <Check className="h-3 w-3 text-success" />
            ) : (
              <Copy className="h-3 w-3" />
            )}
          </button>
          <Badge tone="neutral" className="ml-auto shrink-0 font-mono">
            L{thread.line_number}
          </Badge>
        </div>
        <div className="max-h-[340px] overflow-y-auto">
          <DiffViewer hunk={thread.diff_hunk} filePath={thread.file_path} />
        </div>
      </div>
    );
  },
);
CodeSnippetBox.displayName = "CodeSnippetBox";
