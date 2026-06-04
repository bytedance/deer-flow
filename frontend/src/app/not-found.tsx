import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 text-center">
      <h1 className="text-6xl font-bold tracking-tight text-muted-foreground">
        404
      </h1>
      <p className="text-lg text-muted-foreground">页面未找到</p>
      <Link
        href="/"
        className="text-primary hover:underline text-sm"
      >
        返回首页
      </Link>
    </div>
  );
}
