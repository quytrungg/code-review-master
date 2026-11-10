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

/** 940 → "940", 61_100 → "61.1k", 2_400_000 → "2.4M". */
export function compactNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const scaled = (divisor: number) => (value / divisor).toFixed(1).replace(/\.0$/, "");
  if (Math.abs(value) < 1000) return String(Math.round(value));
  if (Math.abs(value) < 1_000_000) return `${scaled(1000)}k`;
  return `${scaled(1_000_000)}M`;
}

/** An *estimated* dollar figure; never render a bare `$` for a model with no price. */
export function estimatedCost(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value === 0) return "~$0.00";
  return `~$${value >= 0.01 ? value.toFixed(2) : value.toFixed(4)}`;
}

/** A plain dollar amount (a cap, not an estimate). */
export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `$${value.toFixed(2)}`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(1)}%`;
}

/** 820 → "820ms", 8_200 → "8.2s", 134_000 → "2m 14s", 3_600_000 → "1h 00m". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${String(Math.round(seconds % 60)).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
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
