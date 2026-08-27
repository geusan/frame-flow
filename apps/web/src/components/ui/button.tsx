import * as React from "react";
import { Slot } from "radix-ui";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex min-h-8 shrink-0 cursor-pointer items-center justify-center gap-[7px] whitespace-nowrap rounded-[7px] border text-[length:var(--text-base)] font-semibold transition-[background-color,border-color,color,box-shadow,transform] duration-150 outline-none disabled:pointer-events-none disabled:opacity-55 focus-visible:ring-2 focus-visible:ring-[var(--brand-soft)] focus-visible:ring-offset-1 [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "border-[var(--brand)] bg-[var(--brand)] px-[13px] text-[var(--primary-foreground)] shadow-[0_2px_5px_rgba(103,92,246,.22)] hover:-translate-y-px hover:bg-[var(--brand-deep)]",
        secondary: "border-[var(--line)] bg-[var(--panel)] px-[11px] text-[var(--control-foreground)] hover:border-[var(--line-strong)] hover:bg-[var(--panel-muted)]",
        ghost: "border-transparent bg-transparent px-[11px] text-[var(--ink-soft)] hover:bg-[var(--panel-muted)]",
        danger: "border-[var(--danger-border)] bg-[var(--danger-surface)] px-[11px] text-[var(--red)] hover:border-[var(--red)] hover:bg-[var(--red-soft)]",
        lime: "border-[var(--lime-border)] bg-[var(--lime)] px-[13px] text-[var(--lime-foreground)] shadow-none hover:bg-[var(--lime-border)]",
        outline: "border-[var(--line)] bg-transparent px-[11px] text-[var(--ink-soft)] hover:border-[var(--line-strong)] hover:bg-[var(--panel-muted)]",
      },
      size: {
        default: "h-8",
        sm: "h-7 min-h-7 rounded-md px-2 text-[length:var(--text-xs)]",
        lg: "h-9 min-h-9 px-4",
        icon: "size-8 min-h-8 p-0 text-[var(--ink-soft)]",
        "icon-sm": "size-[27px] min-h-[27px] rounded-md p-0",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "button";
  return <Comp data-slot="button" className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

export { Button, buttonVariants };
