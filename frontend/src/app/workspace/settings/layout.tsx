import { SettingsShell } from "@/components/workspace/settings/settings-shell";

export default function SettingsLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return <SettingsShell>{children}</SettingsShell>;
}
