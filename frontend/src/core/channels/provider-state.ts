import type { ChannelProvider } from "./types";

export function providerCanConnect(provider: ChannelProvider): boolean {
  return (
    (provider.connectable ?? (provider.enabled && provider.configured)) &&
    provider.connection_status !== "connected"
  );
}

export function providerNeedsRuntimeConfig(provider: ChannelProvider): boolean {
  return (
    provider.enabled &&
    !provider.configured &&
    (provider.credential_fields?.length ?? 0) > 0
  );
}

export function providerCanEditRuntimeConfig(
  provider: ChannelProvider,
): boolean {
  return provider.enabled && (provider.credential_fields?.length ?? 0) > 0;
}
