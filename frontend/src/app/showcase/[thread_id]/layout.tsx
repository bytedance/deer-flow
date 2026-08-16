import "katex/dist/katex.min.css";
import "streamdown/styles.css";

import { Toaster } from "sonner";

import { QueryClientProvider } from "@/components/query-client-provider";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { ChatProviders } from "@/components/workspace/chats/chat-providers";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { I18nProvider } from "@/core/i18n/context";
import { detectLocaleServer } from "@/core/i18n/server";

export default async function PublicShowcaseLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = await detectLocaleServer();

  return (
    <I18nProvider initialLocale={locale}>
      <AuthProvider initialUser={null}>
        <QueryClientProvider>
          <SidebarProvider className="h-screen" defaultOpen={false}>
            <SidebarInset className="min-w-0">
              <ChatProviders>{children}</ChatProviders>
            </SidebarInset>
          </SidebarProvider>
          <Toaster position="top-center" />
        </QueryClientProvider>
      </AuthProvider>
    </I18nProvider>
  );
}
