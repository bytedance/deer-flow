import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));
rs.mock("@/core/clipboard", () => ({ writeTextToClipboard: rs.fn() }));

import { SidebarProvider } from "@/components/ui/sidebar";
import { ThreadSidebarItem } from "@/components/workspace/recent-chat-list";
import { ThreadDeleteDialogProvider } from "@/components/workspace/thread-delete-dialog";
import { AuthProvider } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";
import { writeTextToClipboard } from "@/core/clipboard";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";

type HappyDOMWindow = Window & {
  happyDOM: { setURL: (url: string) => void };
};

const THREAD_ID = "83d5133d-f8aa-4095-9bba-2aca03f8f61c";
const writeText = rs.mocked(writeTextToClipboard);
const initialURL = window.location.href;

function renderItem(metadata: Record<string, unknown> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const user = {
    id: "user-1",
    email: "user@example.test",
    system_role: "user",
  } as User;
  const thread = {
    thread_id: THREAD_ID,
    updated_at: "2026-01-01T00:00:00Z",
    metadata,
    values: { title: "A thread" },
  } as never;
  return render(
    <I18nProvider initialLocale={DEFAULT_LOCALE}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider initialUser={user}>
          <SidebarProvider>
            <ThreadDeleteDialogProvider>
              <ThreadSidebarItem thread={thread} isActive={false} />
            </ThreadDeleteDialogProvider>
          </SidebarProvider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>,
  );
}

/** Opens the row's "more" menu and selects Share. Radix opens on pointerdown. */
async function share(): Promise<string> {
  const trigger = await screen.findByRole("button", { name: /more/i });
  fireEvent.pointerDown(trigger, { button: 0, pointerType: "mouse" });
  fireEvent.click(trigger);
  fireEvent.click(await screen.findByText("Share"));
  await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
  return writeText.mock.calls[0]![0];
}

afterEach(() => {
  cleanup();
  writeText.mockReset();
  (window as unknown as HappyDOMWindow).happyDOM.setURL(initialURL);
});

describe("ThreadSidebarItem Share", () => {
  // The default `make dev` and Docker entry points are localhost:2026 and
  // 127.0.0.1:2026. The link must stay on the deployment that holds the
  // thread rather than point at a hosted demo.
  for (const origin of [
    "http://localhost:2026",
    "http://127.0.0.1:2026",
    "http://localhost:3000",
    "http://[::1]:2026",
    "http://192.168.1.20:2026",
    "https://deerflow.example.com",
  ]) {
    it(`copies a link on the current origin (${origin})`, async () => {
      (window as unknown as HappyDOMWindow).happyDOM.setURL(
        `${origin}/workspace/chats`,
      );
      writeText.mockResolvedValue(true);
      renderItem();
      expect(await share()).toBe(`${origin}/workspace/chats/${THREAD_ID}`);
    });
  }

  it("copies the custom agent route on the current origin", async () => {
    (window as unknown as HappyDOMWindow).happyDOM.setURL(
      "http://localhost:2026/workspace",
    );
    writeText.mockResolvedValue(true);
    renderItem({ agent_name: "research bot" });
    expect(await share()).toBe(
      `http://localhost:2026/workspace/agents/research%20bot/chats/${THREAD_ID}`,
    );
  });
});
