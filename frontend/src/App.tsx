import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Outlet } from "react-router";

import { ThemeProvider } from "@/components/theme-provider";
import { OfflineIndicator } from "@/components/ui/offline-indicator";
import { UpdateBanner } from "@/components/ui/update-banner";
import { AuthProvider } from "@/core/auth";
import { I18nProvider } from "@/core/i18n/context";
import { detectLocaleClient } from "@/core/i18n/detect";

/**
 * Root application component
 * Provides theme, i18n, and auth context to all routes
 */
const queryClient = new QueryClient();

export function App() {
  const locale = detectLocaleClient();

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider
        attribute="class"
        defaultTheme="dark"
        enableSystem
        disableTransitionOnChange
      >
        <I18nProvider initialLocale={locale}>
          <AuthProvider>
            <UpdateBanner />
            <Outlet />
            <OfflineIndicator />
          </AuthProvider>
        </I18nProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
