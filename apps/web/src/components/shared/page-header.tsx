import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface PageHeaderProps {
  title: string;
  description: string;
  actions?: ReactNode;
  className?: string;
}

export function PageHeader({ title, description, actions, className }: PageHeaderProps) {
  return (
    <header className={cn("mb-[22px] flex items-start justify-between gap-5 max-[700px]:flex-col max-[700px]:items-stretch", className)}>
      <div>
        <h2 className="mb-[5px] mt-0 font-[var(--font-manrope)] text-[length:var(--text-3xl)] font-semibold leading-[1.2] tracking-[-.035em]">{title}</h2>
        <p className="m-0 text-[length:var(--text-base)] leading-6 text-[var(--ink-soft)]">{description}</p>
      </div>
      {actions && <div className="flex items-center gap-2 max-[700px]:flex-wrap">{actions}</div>}
    </header>
  );
}
