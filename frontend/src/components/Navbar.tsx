import { NavLink, useNavigate } from "react-router-dom";
import { BookOpen, GitPullRequest, LogOut, Settings2, Sparkles } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/utils";

const links = [
  { to: "/", label: "Reviews", icon: GitPullRequest, end: true },
  { to: "/skills", label: "Skills", icon: BookOpen, end: false },
  { to: "/settings", label: "Settings", icon: Settings2, end: false },
];

export function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function signOut() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <header className="sticky top-0 z-30 border-b border-border/80 bg-canvas/80 backdrop-blur-xl">
      <div className="mx-auto flex h-16 w-full max-w-7xl items-center justify-between px-5">
        <NavLink to="/" className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accentStrong/15 text-accent ring-1 ring-accent/30">
            <Sparkles className="h-4 w-4" />
          </span>
          <span className="text-sm font-semibold tracking-tight text-ink">
            Code Review<span className="text-inkMuted"> Assistant</span>
          </span>
        </NavLink>

        <nav className="flex items-center gap-1">
          {links.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "inline-flex h-9 items-center gap-2 rounded-lg px-3 text-sm transition-colors",
                  isActive
                    ? "bg-surfaceMuted text-ink ring-1 ring-border"
                    : "text-inkMuted hover:bg-surfaceMuted/60 hover:text-ink",
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}

          <span className="mx-2 h-5 w-px bg-border" aria-hidden="true" />
          <span
            className="max-w-[180px] truncate text-xs text-inkMuted"
            title={user?.email ?? ""}
          >
            {user?.email}
          </span>
          <button
            type="button"
            onClick={() => void signOut()}
            aria-label="Sign out"
            title="Sign out"
            className="inline-flex h-9 items-center gap-2 rounded-lg px-2.5 text-sm text-inkMuted transition-colors hover:bg-surfaceMuted/60 hover:text-ink"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </nav>
      </div>
    </header>
  );
}
