export function POST() {
  return Response.json({
    verification_url: "https://open.feishu.cn/auth/mock-device",
    device_code: "mock-device-code",
    expires_in: 600,
    user_code: null,
    hint: null,
  });
}
