import * as React from "react";

import { cn } from "@/lib/utils";

function Card({ className, ...props }: React.ComponentProps<"section">) {
  return <section data-slot="card" className={cn("rounded-[11px] border border-[var(--line)] bg-[var(--panel)] shadow-[var(--shadow-sm)]", className)} {...props} />;
}

function CardHeader({ className, ...props }: React.ComponentProps<"header">) {
  return <header data-slot="card-header" className={cn("flex min-h-12 items-center justify-between border-b border-[var(--line)] px-[15px]", className)} {...props} />;
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="card-content" className={cn("p-[15px]", className)} {...props} />;
}

function CardFooter({ className, ...props }: React.ComponentProps<"footer">) {
  return <footer data-slot="card-footer" className={cn("flex items-center justify-end gap-2 border-t border-[var(--line)] p-3", className)} {...props} />;
}

export { Card, CardHeader, CardContent, CardFooter };
