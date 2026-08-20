"use client";

// Pass-through page wrapper. The observatory skin (and its page-enter
// animation) was removed; only the classic skin remains.
export function PageEnter({ children }: { children: React.ReactNode }) {
  return children;
}
