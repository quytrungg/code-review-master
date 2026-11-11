import { useEffect, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { BarChart3, BookOpen, GitPullRequest, Inbox, LogOut, Settings2, Sparkles } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { api } from "@/services/api";
import { cn } from "@/lib/utils";

const links = [
  { to: "/inbox", label: "PR Inbox", icon: Inbox, end: true, badge: true },
  { to: "/", label: "Reviews", icon: GitPullRequest, end: true, badge: false },
  { to: "/skills", label: "Skills", icon: BookOpen, end: false, badge: false },
  { to: "/analytics", label: "Analytics", icon: BarChart3, end: false, badge: false },
  { to: "/settings", label: "Settings", icon: Settings2, end: false, badge: false },
];

export function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    // A failure here must never break the chrome: the badge is best-effort.
    let cancelled = false;
    api
      .listInbox({ unread: true })
      .then((rows) => {
        if (!cancelled) setUnread(rows.length);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [location.pathname]);

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
          {links.map(({ to, label, icon: Icon, end, badge }) => (
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
              {badge && unread > 0 ? (
                <span className="grid h-4 min-w-4 place-items-center rounded-full bg-accentStrong px-1 text-[10px] font-semibold text-white">
                  {unread}
                </span>
              ) : null}
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
