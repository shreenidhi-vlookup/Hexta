"use client";

import {
  ChevronLeft,
  ChevronRight,
  FileText,
  HelpCircle,
  LayoutDashboard,
  Plus,
  ScrollText,
  Settings,
  ThumbsUp,
  Users,
  AlertTriangle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ComponentType } from "react";
import type { RecentChat } from "@/lib/conversations";

export type AdminSection =
  | "dashboard"
  | "users"
  | "documents"
  | "audit"
  | "feedback"
  | "gaps";

export type NavView = "chat" | AdminSection | "settings" | "help";

interface NavItem {
  key: NavView;
  label: string;
  icon: ComponentType<{ className?: string }>;
}

const CHAT_ITEMS: NavItem[] = [
  { key: "chat", label: "New chat", icon: Plus },
];

const ADMIN_ITEMS: NavItem[] = [
  { key: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { key: "users", label: "Users", icon: Users },
  { key: "documents", label: "Documents", icon: FileText },
  { key: "audit", label: "Audit log", icon: ScrollText },
  { key: "feedback", label: "Feedback", icon: ThumbsUp },
  { key: "gaps", label: "Knowledge gaps", icon: AlertTriangle },
];

const FOOTER_ITEMS: NavItem[] = [
  { key: "settings", label: "Settings", icon: Settings },
  { key: "help", label: "Help", icon: HelpCircle },
];

export interface HomeSidebarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
  isAdmin: boolean;
  active: NavView;
  onSelect: (view: NavView) => void;
  onNewChat: () => void;
  onHome: () => void;
  recent: RecentChat[];
  onSelectRecent: (chat: RecentChat) => void;
  onDeleteRecent: (chat: RecentChat) => void;
}

export function HomeSidebar({
  collapsed,
  onToggleCollapse,
  isAdmin,
  active,
  onSelect,
  onNewChat,
  onHome,
  recent,
  onSelectRecent,
  onDeleteRecent,
}: HomeSidebarProps) {
  const visibleAdmin = isAdmin ? ADMIN_ITEMS : [];

  const chatClick = (item: NavItem) => {
    if (item.label === "New chat") onNewChat();
    else onHome();
  };

  return (
    <aside
      className={cn(
        "flex h-screen flex-col overflow-y-auto overflow-x-hidden border-r border-border bg-card",
        "transition-all duration-300",
        collapsed ? "w-14" : "w-56"
      )}
    >
      <div className="flex items-center justify-between border-b border-border p-3">
        {!collapsed && <span className="text-sm font-semibold">Hexta</span>}
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className={cn("h-7 w-7", collapsed && "mx-auto")}
          onClick={onToggleCollapse}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand" : "Collapse"}
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronLeft className="h-4 w-4" />
          )}
        </Button>
      </div>

      <nav className="flex-1 py-2">
        {CHAT_ITEMS.map((item) => (
          <NavRow
            key={item.label}
            item={item}
            active={active === item.key && (item.label !== "New chat" || true)}
            collapsed={collapsed}
            onClick={() => chatClick(item)}
          />
        ))}

        {recent.length > 0 && (
          <>
            {!collapsed && (
              <p className="px-3 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Recent
              </p>
            )}
            {recent.map((chat) => (
              <div
                key={chat.id}
                className={cn(
                  "group flex items-center",
                  collapsed ? "justify-center px-0" : "px-2"
                )}
              >
                <button
                  type="button"
                  className={cn(
                    "flex-1 overflow-hidden rounded-md px-2.5 py-1.5 text-left align-top text-sm",
                    "hover:bg-accent hover:text-accent-foreground",
                  )}
                  onClick={() => onSelectRecent(chat)}
                  title={chat.title}
                >
                  <span className="block w-full overflow-hidden text-ellipsis whitespace-nowrap">
                    {chat.title}
                  </span>
                </button>
                {!collapsed && (
                  <button
                    type="button"
                    className="shrink-0 rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100"
                    onClick={() => onDeleteRecent(chat)}
                    aria-label={`Delete ${chat.title}`}
                    title={`Delete ${chat.title}`}
                  >
                    ×
                  </button>
                )}
              </div>
            ))}
          </>
        )}

        {visibleAdmin.length > 0 && (
          <>
            {!collapsed && (
              <div className="px-3 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Administration
              </div>
            )}
            {visibleAdmin.map((item) => (
              <NavRow
                key={item.key}
                item={item}
                active={active === item.key}
                collapsed={collapsed}
                onClick={() => onSelect(item.key)}
              />
            ))}
          </>
        )}
      </nav>

      <div className="border-t border-border p-2">
        {FOOTER_ITEMS.map((item) => (
          <NavRow
            key={item.key}
            item={item}
            active={active === item.key}
            collapsed={collapsed}
            onClick={() => onSelect(item.key)}
          />
        ))}
      </div>
    </aside>
  );
}

function NavRow({
  item,
  active,
  collapsed,
  onClick,
}: {
  item: NavItem;
  active: boolean;
  collapsed: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={cn(
        "mx-2 my-0.5 flex items-center gap-3 rounded-md px-2.5 py-1.5 text-sm font-medium",
        "transition-colors hover:bg-accent hover:text-accent-foreground",
        active && "bg-accent text-accent-foreground",
        collapsed && "justify-center px-2",
      )}
      onClick={onClick}
      aria-label={item.label}
      title={item.label}
    >
      <item.icon className="h-4 w-4 shrink-0" />
      {!collapsed && (
        <span className="overflow-hidden text-ellipsis">{item.label}</span>
      )}
    </button>
  );
}
