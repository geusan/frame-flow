"use client";

import * as React from "react";
import { AlertDialog as AlertDialogPrimitive } from "radix-ui";

import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";

const AlertDialog = AlertDialogPrimitive.Root;
const AlertDialogTrigger = AlertDialogPrimitive.Trigger;

function AlertDialogContent({ className, children, ...props }: React.ComponentProps<typeof AlertDialogPrimitive.Content>) {
  return (
    <AlertDialogPrimitive.Portal>
      <AlertDialogPrimitive.Overlay className="fixed inset-0 z-[130] bg-[rgba(20,21,18,.46)] backdrop-blur-[4px]" />
      <AlertDialogPrimitive.Content
        data-slot="alert-dialog-content"
        className={cn("fixed left-1/2 top-1/2 z-[131] w-[min(440px,calc(100vw-40px))] -translate-x-1/2 -translate-y-1/2 rounded-[14px] border border-white/50 bg-white p-5 shadow-[0_30px_80px_rgba(12,13,11,.3)] outline-none", className)}
        {...props}
      >
        {children}
      </AlertDialogPrimitive.Content>
    </AlertDialogPrimitive.Portal>
  );
}

function AlertDialogHeader({ className, ...props }: React.ComponentProps<"header">) {
  return <header className={cn("space-y-1.5", className)} {...props} />;
}

function AlertDialogFooter({ className, ...props }: React.ComponentProps<"footer">) {
  return <footer className={cn("mt-5 flex justify-end gap-2", className)} {...props} />;
}

function AlertDialogTitle({ className, ...props }: React.ComponentProps<typeof AlertDialogPrimitive.Title>) {
  return <AlertDialogPrimitive.Title className={cn("m-0 font-[var(--font-manrope)] text-[length:var(--text-lg)] font-semibold", className)} {...props} />;
}

function AlertDialogDescription({ className, ...props }: React.ComponentProps<typeof AlertDialogPrimitive.Description>) {
  return <AlertDialogPrimitive.Description className={cn("m-0 text-[length:var(--text-sm)] leading-6 text-[var(--ink-soft)]", className)} {...props} />;
}

function AlertDialogAction({ className, ...props }: React.ComponentProps<typeof AlertDialogPrimitive.Action>) {
  return <AlertDialogPrimitive.Action className={cn(buttonVariants({ variant: "danger" }), className)} {...props} />;
}

function AlertDialogCancel({ className, ...props }: React.ComponentProps<typeof AlertDialogPrimitive.Cancel>) {
  return <AlertDialogPrimitive.Cancel className={cn(buttonVariants({ variant: "secondary" }), className)} {...props} />;
}

export { AlertDialog, AlertDialogTrigger, AlertDialogContent, AlertDialogHeader, AlertDialogFooter, AlertDialogTitle, AlertDialogDescription, AlertDialogAction, AlertDialogCancel };
