"use client";

import Link from "next/link";
import {
  Boxes,
  ChevronDown,
  CircleHelp,
  Film,
  Image as ImageIcon,
  Play,
  Settings,
  Sparkles,
  Workflow,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { API_BASE, type WorkspaceSummary } from "@/lib/api";
import { cn } from "@/lib/utils";

type WorkspaceCount = "canvases" | "images" | "videos" | "runs";

interface NavigationItem {
  href: string;
  label: string;
  icon: LucideIcon;
  count?: WorkspaceCount;
}

const workspaceNavigation: NavigationItem[] = [
  { href: "/workflows", label: "Canvas", icon: Workflow, count: "canvases" },
  { href: "/asset/images", label: "Images", icon: ImageIcon, count: "images" },
  { href: "/asset/videos", label: "Videos", icon: Film, count: "videos" },
  { href: "/runs", label: "Runs", icon: Play, count: "runs" },
];

const settingsNavigation: NavigationItem[] = [
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/settings/models", label: "Models", icon: Boxes },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/workflows") return pathname === href || pathname.startsWith("/workflows/");
  if (href.startsWith("/asset/")) return pathname === href || pathname.startsWith(`${href}/`);
  return pathname === href;
}

function SidebarNavItem({ item, pathname, workspace }: { item: NavigationItem; pathname: string; workspace: WorkspaceSummary | null }) {
  const active = isActive(pathname, item.href);
  const Icon = item.icon;
  return (
    <Button
      variant="ghost"
      asChild
      className={cn(
        "relative min-h-9 w-full justify-start gap-2.5 rounded-[7px] px-2.5 text-left text-[length:var(--text-ui)] text-[#aeb1aa] no-underline transition-colors duration-150 hover:bg-[#2a2d28] hover:text-white max-[980px]:justify-center max-[980px]:px-0",
        active && "bg-[#343730] text-white shadow-[inset_2px_0_#d6ff78] hover:bg-[#343730] [&_svg]:text-[#d6ff78]",
      )}
    >
      <Link href={item.href} aria-current={active ? "page" : undefined}>
        <Icon size={17} strokeWidth={1.9} />
        <span className="max-[980px]:hidden">{item.label}</span>
        {workspace && item.count && (
          <span className="ml-auto min-w-5 rounded-lg bg-[#44483f] px-[5px] py-0.5 text-center text-[length:var(--text-sm)] text-[#d8dad4] max-[980px]:absolute max-[980px]:right-0 max-[980px]:top-0.5 max-[980px]:min-w-3.5">
            {workspace[item.count]}
          </span>
        )}
      </Link>
    </Button>
  );
}

export function StudioSidebar({ pathname, workspace }: { pathname: string; workspace: WorkspaceSummary | null }) {
  return (
    <aside className="sticky top-0 z-20 flex h-screen flex-col bg-[#1e201d] px-3 pb-3 pt-[18px] text-[#f7f7f3] max-[980px]:px-2.5">
      <Link className="flex h-9 items-center gap-[9px] px-2 text-inherit no-underline max-[980px]:justify-center max-[980px]:px-0" href="/workflows" aria-label="Frameflow home">
        <span className="grid size-[25px] place-items-center rounded-[8px_8px_8px_3px] bg-[var(--lime)] text-[#1d1e1a]"><Sparkles size={17} strokeWidth={2.4} /></span>
        <span className="font-[var(--font-manrope)] text-[length:var(--text-xl)] font-bold leading-none tracking-[-.04em] max-[980px]:hidden">frameflow</span>
      </Link>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            className="my-[18px] mb-4 grid h-auto w-full grid-cols-[28px_minmax(0,1fr)_auto] gap-[9px] rounded-[9px] border-[#3a3d37] bg-[#292b27] p-[9px] text-left text-white hover:border-[#3a3d37] hover:bg-[#30332e] max-[980px]:flex max-[980px]:justify-center"
          >
            <span className="grid size-7 place-items-center rounded-[7px] bg-[#67605a] text-[length:var(--text-sm)] font-bold">FF</span>
            <span className="flex min-w-0 flex-col gap-0.5 max-[980px]:hidden">
              <strong className="overflow-hidden text-ellipsis whitespace-nowrap text-[length:var(--text-base)] font-semibold">{workspace?.service ?? "Connecting…"}</strong>
              <small className="overflow-hidden text-ellipsis whitespace-nowrap text-[length:var(--text-sm)] text-[#9da098]">{workspace ? `${workspace.environment} · ${workspace.storage_provider} · ${workspace.execution_backend}` : "Loading workspace state"}</small>
            </span>
            <ChevronDown className="max-[980px]:hidden" size={14} aria-hidden="true" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="right" align="start">
          <DropdownMenuLabel>Workspace</DropdownMenuLabel>
          <DropdownMenuItem disabled>{workspace?.service ?? "Connecting…"}</DropdownMenuItem>
          {workspace && <DropdownMenuItem disabled>{workspace.environment} · {workspace.storage_provider} · {workspace.execution_backend}</DropdownMenuItem>}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => window.open(`${API_BASE}/docs`, "_blank", "noopener,noreferrer")}><CircleHelp size={14} /> Open API docs</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <nav className="flex flex-col gap-[3px]" aria-label="Main navigation">
        <span className="px-2.5 pb-[7px] pt-[5px] text-[length:var(--text-sm)] font-bold uppercase tracking-[.1em] text-[#777b73] max-[980px]:hidden">Workspace</span>
        {workspaceNavigation.map((item) => <SidebarNavItem key={item.href} item={item} pathname={pathname} workspace={workspace} />)}
        <span className="mt-3.5 px-2.5 pb-[7px] pt-[5px] text-[length:var(--text-sm)] font-bold uppercase tracking-[.1em] text-[#777b73] max-[980px]:hidden">Configure</span>
        {settingsNavigation.map((item) => <SidebarNavItem key={item.href} item={item} pathname={pathname} workspace={workspace} />)}
      </nav>

      <div className="mt-auto flex flex-col gap-0.5">
        <Button
          type="button"
          variant="ghost"
          className="relative min-h-9 w-full justify-start gap-2.5 rounded-[7px] px-2.5 text-left text-[length:var(--text-ui)] text-[#aeb1aa] hover:bg-[#2a2d28] hover:text-white max-[980px]:justify-center max-[980px]:px-0"
          onClick={() => window.open(`${API_BASE}/docs`, "_blank", "noopener,noreferrer")}
        >
          <CircleHelp size={17} />
          <span className="max-[980px]:hidden">API docs</span>
        </Button>
      </div>
    </aside>
  );
}
