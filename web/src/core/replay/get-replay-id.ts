// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

export function extractFromSearchParams(params: string, name = "replay") {
  const urlParams = new URLSearchParams(params);
  if (urlParams.has(name)) {
    return urlParams.get(name);
  }
  return null;
}