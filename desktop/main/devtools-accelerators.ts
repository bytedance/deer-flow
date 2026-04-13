export function getDevtoolsAccelerators(platform: NodeJS.Platform = process.platform) {
  return platform === "darwin"
    ? ["F12", "CommandOrControl+Shift+I"]
    : ["F12", "Control+Shift+I"];
}
