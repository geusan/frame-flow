"use client";

import * as React from "react";
import { Dialog as DialogPrimitive } from "radix-ui";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

function Dialog(props: React.ComponentProps<typeof DialogPrimitive.Root>) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />;
}

function DialogTrigger(props: React.ComponentProps<typeof DialogPrimitive.Trigger>) {
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />;
}

function DialogPortal(props: React.ComponentProps<typeof DialogPrimitive.Portal>) {
  return <DialogPrimitive.Portal data-slot="dialog-portal" {...props} />;
}

function DialogClose(props: React.ComponentProps<typeof DialogPrimitive.Close>) {
  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />;
}

function DialogOverlay({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay
      data-slot="dialog-overlay"
      className={cn("fixed inset-0 z-[100] bg-[rgba(20,21,18,.46)] backdrop-blur-[4px] data-[state=closed]:opacity-0 data-[state=open]:opacity-100", className)}
      {...props}
    />
  );
}

function DialogContent({
  className,
  overlayClassName,
  children,
  showCloseButton = false,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & { overlayClassName?: string; showCloseButton?: boolean }) {
  return (
    <DialogPortal>
      <DialogOverlay className={overlayClassName} />
      <DialogPrimitive.Content
        data-slot="dialog-content"
        className={cn("fixed left-1/2 top-1/2 z-[101] max-h-[calc(100vh-40px)] max-w-[calc(100vw-40px)] -translate-x-1/2 -translate-y-1/2 outline-none", className)}
        {...props}
      >
        {children}
        {showCloseButton && (
          <DialogPrimitive.Close className="absolute right-4 top-4 inline-grid size-8 place-items-center rounded-[7px] border border-[var(--line)] bg-white text-[var(--ink-soft)] outline-none hover:bg-[var(--panel-muted)] focus-visible:ring-2 focus-visible:ring-[var(--brand-soft)]" aria-label="Close dialog">
            <X size={16} />
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Content>
    </DialogPortal>
  );
}

function DialogHeader({ className, ...props }: React.ComponentProps<"header">) {
  return <header data-slot="dialog-header" className={cn("flex flex-col gap-1", className)} {...props} />;
}

function DialogFooter({ className, ...props }: React.ComponentProps<"footer">) {
  return <footer data-slot="dialog-footer" className={cn("flex items-center justify-end gap-2", className)} {...props} />;
}

function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return <DialogPrimitive.Title data-slot="dialog-title" className={cn("font-semibold", className)} {...props} />;
}

function DialogDescription({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return <DialogPrimitive.Description data-slot="dialog-description" className={cn("text-[var(--ink-soft)]", className)} {...props} />;
}

export { Dialog, DialogTrigger, DialogPortal, DialogClose, DialogOverlay, DialogContent, DialogHeader, DialogFooter, DialogTitle, DialogDescription };
