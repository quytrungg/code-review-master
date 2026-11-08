import { useState, type FormEvent, type ReactNode } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input, Label } from "@/components/ui/Input";

export interface AuthFormProps {
  mode: "login" | "signup";
  title: string;
  subtitle: string;
  submitLabel: string;
  busyLabel: string;
  busy: boolean;
  error: string | null;
  onSubmit: (email: string, password: string) => void | Promise<void>;
  footer: ReactNode;
  passwordHint?: string;
  children?: ReactNode;
}

/** Shared frame for /login and /signup: one card, two fields, the error above the button. */
export function AuthForm({
  mode,
  title,
  subtitle,
  submitLabel,
  busyLabel,
  busy,
  error,
  onSubmit,
  footer,
  passwordHint,
  children,
}: AuthFormProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onSubmit(email, password);
  }

  return (
    <div className="grid min-h-screen place-items-center bg-canvas px-5">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-accentStrong/15 text-accent ring-1 ring-accent/30">
            <Sparkles className="h-4 w-4" />
          </span>
          <span className="text-sm font-semibold tracking-tight text-ink">
            Code Review<span className="text-inkMuted"> Assistant</span>
          </span>
        </div>

        <Card className="p-6">
          <h1 className="text-lg font-semibold text-ink">{title}</h1>
          <p className="mt-1 text-sm text-inkMuted">{subtitle}</p>

          <form className="mt-5 space-y-4" onSubmit={handleSubmit}>
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
                required
                minLength={8}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="At least 8 characters"
              />
              {passwordHint ? (
                <p className="text-[11px] text-inkMuted">{passwordHint}</p>
              ) : null}
            </div>

            {children}

            {error ? (
              <p role="alert" className="text-sm text-danger">
                {error}
              </p>
            ) : null}

            <Button type="submit" className="w-full justify-center" disabled={busy}>
              {busy ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> {busyLabel}
                </>
              ) : (
                submitLabel
              )}
            </Button>
          </form>

          <p className="mt-4 text-center text-xs text-inkMuted">{footer}</p>
        </Card>

        <p className="mt-4 text-center text-[11px] text-inkMuted">
          Local-first · credentials and reviews stay on this machine.
        </p>
      </div>
    </div>
  );
}
