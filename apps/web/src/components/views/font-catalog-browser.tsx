"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { GoogleFontBrowser } from "@/components/views/google-font-browser";
import { NoonnuFontBrowser } from "@/components/views/noonnu-font-browser";
import type { RegisteredFont } from "@/lib/api";

export function FontCatalogBrowser(props: {
  fonts: RegisteredFont[];
  onImported: (font: RegisteredFont) => void;
  onApply?: (font: RegisteredFont) => void;
}) {
  return <Tabs defaultValue="google" className="font-catalog-browser">
    <TabsList className="font-catalog-tabs" aria-label="폰트 제공처">
      <TabsTrigger value="google">Google Fonts</TabsTrigger>
      <TabsTrigger value="noonnu">눈누</TabsTrigger>
    </TabsList>
    <TabsContent value="google"><GoogleFontBrowser {...props} /></TabsContent>
    <TabsContent value="noonnu"><NoonnuFontBrowser {...props} /></TabsContent>
  </Tabs>;
}
