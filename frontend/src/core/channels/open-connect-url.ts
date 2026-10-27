export type ChannelConnectWindow = Window | null;

export function prepareConnectWindow(): ChannelConnectWindow {
  const opened = window.open("about:blank", "_blank");
  if (opened) {
    opened.opener = null;
  }
  return opened;
}

export function openConnectUrl(
  url: string,
  connectWindow: ChannelConnectWindow = prepareConnectWindow(),
) {
  if (connectWindow && !connectWindow.closed) {
    connectWindow.location.replace(url);
    return;
  }

  window.location.assign(url);
}

export function closeConnectWindow(connectWindow: ChannelConnectWindow) {
  if (connectWindow && !connectWindow.closed) {
    connectWindow.close();
  }
}
