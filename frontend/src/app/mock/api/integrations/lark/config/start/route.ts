export function POST() {
  return Response.json({
    verification_url: "https://open.feishu.cn/page/cli?user_code=config",
    device_code: "mock-config-device-code",
    expires_in: 600,
    interval: 5,
    user_code: "config",
    brand: "feishu",
  });
}
