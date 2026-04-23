export function oaOk<T>(data: T, message = "操作成功"): Response {
  return Response.json(
    {
      code: 0,
      message,
      data,
    },
    { status: 200 },
  );
}

export function oaApiError(
  httpStatus: number,
  message: string,
  code = httpStatus,
): Response {
  return Response.json(
    {
      code,
      message,
    },
    { status: httpStatus },
  );
}
