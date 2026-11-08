import { useMemo } from "react";
import { cn } from "@/lib/utils";

const KEYWORDS = new Set([
  "def", "class", "module", "end", "do", "begin", "rescue", "ensure", "raise", "return",
  "if", "elsif", "else", "unless", "while", "until", "for", "in", "case", "when", "then",
  "yield", "lambda", "proc", "self", "nil", "true", "false", "and", "or", "not",
  "function", "const", "let", "var", "async", "await", "import", "from", "export", "default",
  "try", "catch", "finally", "throw", "new", "this", "typeof", "interface", "type", "enum",
  "public", "private", "protected", "static", "readonly", "extends", "implements", "as",
  "import", "None", "True", "False", "with", "pass", "elif", "except", "lambda", "global",
]);

const TOKEN_RE = /(#[^\n]*|\/\/[^\n]*|--[^\n]*|\/\*.*?\*\/)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_$][A-Za-z0-9_$]*)/g;

type Span = { text: string; className: string };

function tokenize(line: string): Span[] {
  const spans: Span[] = [];
  let cursor = 0;
  TOKEN_RE.lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = TOKEN_RE.exec(line)) !== null) {
    if (match.index > cursor) {
      spans.push({ text: line.slice(cursor, match.index), className: "" });
    }
    const [full, comment, str, num, word] = match;
    if (comment) spans.push({ text: full, className: "text-inkMuted italic" });
    else if (str) spans.push({ text: full, className: "text-[#9ce49c]" });
    else if (num) spans.push({ text: full, className: "text-[#e0b0ff]" });
    else if (word) {
      const nextChar = line[TOKEN_RE.lastIndex];
      const cls = KEYWORDS.has(word)
        ? "text-[#8fb6ff]"
        : nextChar === "("
          ? "text-[#ffd479]"
          : "";
      spans.push({ text: full, className: cls });
    }
    cursor = TOKEN_RE.lastIndex;
    if (full.length === 0) TOKEN_RE.lastIndex += 1;
  }

  if (cursor < line.length) spans.push({ text: line.slice(cursor), className: "" });
  return spans;
}

function classify(rawLine: string) {
  if (rawLine.startsWith("@@")) return "hunk" as const;
  if (rawLine.startsWith("\\")) return "meta" as const;
  if (rawLine.startsWith("+")) return "add" as const;
  if (rawLine.startsWith("-")) return "del" as const;
  return "context" as const;
}

export function DiffViewer({ hunk, filePath }: { hunk: string; filePath: string }) {
  const rows = useMemo(() => hunk.split("\n"), [hunk]);
  const language = filePath.split(".").pop() ?? "";

  return (
    <div className="overflow-x-auto">
      <pre className="min-w-full font-mono text-[12.5px] leading-[1.55]">
        <code>
          {rows.map((row, index) => {
            const kind = classify(row);
            if (kind === "hunk") {
              return (
                <div
                  key={index}
                  className="whitespace-pre border-y border-border/60 bg-surfaceMuted/70 px-3 py-1 text-[11px] text-inkMuted"
                >
                  {row}
                </div>
              );
            }
            if (kind === "meta") {
              return (
                <div key={index} className="whitespace-pre px-3 text-[11px] text-inkMuted">
                  {row}
                </div>
              );
            }

            const sign = kind === "add" ? "+" : kind === "del" ? "-" : " ";
            const body = row.slice(1);
            return (
              <div
                key={index}
                className={cn(
                  "flex whitespace-pre",
                  kind === "add" && "bg-add/70",
                  kind === "del" && "bg-del/70",
                )}
              >
                <span
                  className={cn(
                    "w-7 shrink-0 select-none border-r border-border/50 px-1 text-center",
                    kind === "add" && "text-success",
                    kind === "del" && "text-danger",
                    kind === "context" && "text-inkMuted/50",
                  )}
                >
                  {sign}
                </span>
                <span className="flex-1 px-2 text-ink">
                  {tokenize(body).map((span, spanIndex) => (
                    <span key={spanIndex} className={span.className}>
                      {span.text}
                    </span>
                  ))}
                </span>
              </div>
            );
          })}
        </code>
      </pre>
      <span className="sr-only">{language} diff</span>
    </div>
  );
}
