import { useEffect, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { BarChart3, BookOpen, GitPullRequest, Inbox, LogOut, Moon, Settings2, Sparkles, Sun } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { getTheme, toggleTheme, type Theme } from "@/lib/theme";
import { api } from "@/services/api";
import { cn } from "@/lib/utils";

const links: {
  to: string;
  label: string;
  icon: typeof GitPullRequest;
  end: boolean;
  badge?: "inbox" | "reviews";
}[] = [
  { to: "/", label: "Reviews", icon: GitPullRequest, end: true, badge: "reviews" },
  { to: "/inbox", label: "PR Inbox", icon: Inbox, end: true, badge: "inbox" },
  { to: "/skills", label: "Skills", icon: BookOpen, end: false },
  { to: "/analytics", label: "Analytics", icon: BarChart3, end: false },
  { to: "/settings", label: "Settings", icon: Settings2, end: false },
];

export function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [badges, setBadges] = useState({ inbox: 0, reviews: 0 });
  const [theme, setThemeState] = useState<Theme>(getTheme);

  useEffect(() => {
    // A failure here must never break the chrome: the badges are best-effort.
    let cancelled = false;
    const loadInbox = () =>
      api
        .listInbox({ unread: true })
        .then((rows) => {
          if (!cancelled) setBadges((current) => ({ ...current, inbox: rows.length }));
        })
        .catch(() => {});
    const loadReviews = () =>
      api
        .reviewNotifications()
        .then((result) => {
          if (!cancelled) setBadges((current) => ({ ...current, reviews: result.unread_count }));
        })
        .catch(() => {});

    void loadInbox();
    void loadReviews();
    // A review can finish while the operator is reading another page, so the count is polled.
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void loadReviews();
    }, 5000);
    const onVisible = () => {
      if (document.visibilityState === "visible") void loadReviews();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
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
              {badge && badges[badge] > 0 ? (
                <span
                  className="grid h-4 min-w-4 place-items-center rounded-full bg-accentStrong px-1 text-[10px] font-semibold text-white"
                  title={`${badges[badge]} unread`}
                >
                  {badges[badge]}
                </span>
              ) : null}
            </NavLink>
          ))}

          <button
            type="button"
            onClick={() => setThemeState(toggleTheme())}
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-inkMuted transition-colors hover:bg-surfaceMuted/60 hover:text-ink"
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>

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
