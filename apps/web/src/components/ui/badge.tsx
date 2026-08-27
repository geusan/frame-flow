import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex min-h-[21px] items-center gap-1 whitespace-nowrap rounded-[5px] px-[7px] text-[length:var(--text-xs)] font-semibold",
  {
    variants: {
      variant: {
        default: "bg-[var(--neutral-badge)] text-[var(--neutral-badge-foreground)]",
        primary: "bg-[var(--brand-soft)] text-[var(--primary-muted-foreground)]",
        success: "bg-[var(--green-soft)] text-[var(--green)]",
        warning: "bg-[var(--amber-soft)] text-[var(--amber)]",
        danger: "bg-[var(--red-soft)] text-[var(--red)]",
        info: "bg-[var(--info-surface)] text-[var(--blue)]",
        outline: "border border-[var(--line)] bg-transparent text-[var(--ink-soft)]",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

function Badge({ className, variant, ...props }: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
