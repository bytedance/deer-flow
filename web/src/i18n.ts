// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { cookies } from "next/headers";
import { getRequestConfig } from "next-intl/server";

// Can be imported from a shared config
const locales: Array<string> = ["zh", "en"];

export default getRequestConfig(async () => {
  // Get locale from cookie
  const cookieStore = await cookies();
  const cookieLocale = cookieStore.get("NEXT_LOCALE")?.value;

  // Validate that the incoming `locale` parameter is valid
  const locale =
    cookieLocale && locales.includes(cookieLocale) ? cookieLocale : "en";

  return {
    messages: (await import(`../messages/${locale}.json`)).default,
    locale,
  };
});
