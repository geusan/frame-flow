"use client";

import * as React from "react";
import { Dialog as SheetPrimitive } from "radix-ui";

import { cn } from "@/lib/utils";

function Sheet(props: React.ComponentProps<typeof SheetPrimitive.Root>) {
  return <SheetPrimitive.Root data-slot="sheet" {...props} />;
}

const SheetClose = SheetPrimitive.Close;
const SheetTitle = SheetPrimitive.Title;
const SheetDescription = SheetPrimitive.Description;

function SheetContent({ className, overlayClassName, children, ...props }: React.ComponentProps<typeof SheetPrimitive.Content> & { overlayClassName?: string }) {
  return (
    <SheetPrimitive.Portal>
      <SheetPrimitive.Overlay className={cn("fixed inset-0 z-[90] bg-[rgba(24,25,22,.3)] backdrop-blur-[2px]", overlayClassName)} />
      <SheetPrimitive.Content
        data-slot="sheet-content"
        className={cn("fixed inset-y-0 right-0 z-[91] h-full outline-none", className)}
        {...props}
      >
        {children}
      </SheetPrimitive.Content>
    </SheetPrimitive.Portal>
  );
}

export { Sheet, SheetClose, SheetContent, SheetTitle, SheetDescription };
