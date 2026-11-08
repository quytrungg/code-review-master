import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

import type { ReviewThread } from "@/types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Short, human-readable relative time for list rows. */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diff = Date.now() - then;
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function formatAbsolute(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

export function shortSha(sha: string | null | undefined): string {
  if (!sha) return "";
  return sha.slice(0, 7);
}

/**
 * Turn `#3` mentions into internal links so a comment can jump to that thread.
 * Only ordinals that exist are converted; fenced code and existing links are left alone.
 */
export function linkThreadRefs(markdown: string, maxOrdinal: number): string {
  if (!markdown || maxOrdinal < 1) return markdown;
  return markdown.replace(/(?<![\w&#])#(\d{1,3})\b/g, (match, digits: string) => {
    const ordinal = Number(digits);
    return ordinal >= 1 && ordinal <= maxOrdinal ? `[${match}](#thread-ref-${ordinal})` : match;
  });
}

/**
 * What the apply button still has to publish: accepted AI findings (Round 1) plus accepted reply
 * rounds. Undecided, resolved and published rounds contribute nothing.
 */
export interface PendingApply {
  findings: number;
  replies: number;
  total: number;
}

export function pendingApplyCount(threads: ReviewThread[]): PendingApply {
  let findings = 0;
  let replies = 0;
  for (const thread of threads) {
    for (const round of thread.rounds) {
      const isInitialFinding =
        thread.origin === "AI_GENERATED" && round.round_number === 1 && !thread.dropped;
      if (round.status !== "pending_apply") continue;
      if (isInitialFinding) {
        findings += 1;
      } else {
        replies += 1;
      }
    }
  }
  return { findings, replies, total: findings + replies };
}

export function applyButtonLabel(pending: PendingApply): string {
  if (pending.total === 0) return "Everything applied";
  if (pending.findings > 0 && pending.replies > 0) return `Apply ${pending.total} pending`;
  if (pending.findings > 0) {
    return `Apply ${pending.findings} pending finding${pending.findings === 1 ? "" : "s"}`;
  }
  return `Apply ${pending.replies} pending repl${pending.replies === 1 ? "y" : "ies"}`;
}
