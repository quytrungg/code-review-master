import { useEffect, useRef, useState } from "react";
import { FolderUp, Loader2, Upload } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input, Label } from "@/components/ui/Input";
import { cn } from "@/lib/utils";

export interface FoundationUploadProps {
  onCreate: (name: string, files: File[], archive?: File) => Promise<void>;
  busy: boolean;
}

/** Creates a Core Skill Foundation from either a folder tree or a .zip archive. */
export function FoundationUpload({ onCreate, busy }: FoundationUploadProps) {
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"folder" | "zip">("folder");
  const [files, setFiles] = useState<File[]>([]);
  const [archive, setArchive] = useState<File | null>(null);
  const folderRef = useRef<HTMLInputElement>(null);

  // `webkitdirectory` is not part of the JSX typings.
  useEffect(() => {
    const input = folderRef.current;
    if (input) {
      input.setAttribute("webkitdirectory", "");
      input.setAttribute("directory", "");
    }
  }, []);

  const ready =
    name.trim().length > 0 &&
    (mode === "folder" ? files.length > 0 : Boolean(archive)) &&
    !busy;

  async function submit() {
    if (!ready) return;
    await onCreate(name.trim(), mode === "folder" ? files : [], archive ?? undefined);
    setName("");
    setFiles([]);
    setArchive(null);
    if (folderRef.current) folderRef.current.value = "";
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="foundation-name">Foundation name</Label>
          <Input
            id="foundation-name"
            value={name}
            placeholder="frontend-guidelines"
            onChange={(event) => setName(event.target.value)}
          />
          <p className="text-xs text-inkMuted">
            Lowercase letters, digits, <code>-</code> and <code>_</code>. Becomes the folder name.
          </p>
        </div>

        <div className="space-y-2">
          <Label>Source</Label>
          <div className="flex items-center gap-1.5">
            {(
              [
                { id: "folder" as const, label: "Folder", icon: FolderUp },
                { id: "zip" as const, label: ".zip archive", icon: Upload },
              ]
            ).map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => setMode(id)}
                className={cn(
                  "inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-xs font-medium transition-colors",
                  mode === id
                    ? "border-accent/50 bg-accent/15 text-accent"
                    : "border-border bg-surfaceMuted/40 text-inkMuted hover:text-ink",
                )}
              >
                <Icon className="h-3.5 w-3.5" /> {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {mode === "folder" ? (
        <div className="space-y-2">
          <input
            ref={folderRef}
            type="file"
            multiple
            onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
            className="block w-full cursor-pointer rounded-lg border border-border bg-canvas/70 p-2 text-xs text-inkMuted file:mr-3 file:rounded-md file:border-0 file:bg-surfaceMuted file:px-3 file:py-1.5 file:text-xs file:text-ink"
          />
          <p className="text-xs text-inkMuted">
            {files.length > 0
              ? `${files.length} file(s) selected — only .md and .txt are kept.`
              : "Pick a folder; its relative paths are preserved and one shared wrapper folder is stripped."}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          <input
            type="file"
            accept=".zip,application/zip"
            onChange={(event) => setArchive(event.target.files?.[0] ?? null)}
            className="block w-full cursor-pointer rounded-lg border border-border bg-canvas/70 p-2 text-xs text-inkMuted file:mr-3 file:rounded-md file:border-0 file:bg-surfaceMuted file:px-3 file:py-1.5 file:text-xs file:text-ink"
          />
          <p className="text-xs text-inkMuted">
            {archive
              ? `${archive.name} (${Math.round(archive.size / 1024)} KB)`
              : "The archive is extracted server-side; .md and .txt files are kept."}
          </p>
        </div>
      )}

      <div className="flex justify-end">
        <Button onClick={() => void submit()} disabled={!ready}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderUp className="h-4 w-4" />}
          Create foundation
        </Button>
      </div>
    </div>
  );
}
