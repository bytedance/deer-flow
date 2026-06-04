import Link from "next/link";

export default function WorkspaceNotFound() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-32 text-center">
      <h1 className="text-6xl font-bold tracking-tight text-muted-foreground">
        404
      </h1>
      <p className="text-lg text-muted-foreground">工作区页面未找到</p>
      <div className="flex gap-4">
        <Link
          href="/workspace/chats"
          className="text-primary hover:underline text-sm"
        >
          返回对话列表
        </Link>
        <Link
          href="/"
          className="text-primary hover:underline text-sm"
        >
          返回首页
        </Link>
      </div>
    </div>
  );
}
