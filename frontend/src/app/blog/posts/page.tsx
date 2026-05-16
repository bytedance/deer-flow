import { PostList } from "@/components/landing/post-list";
import { getAllPosts, getPreferredBlogLang } from "@/core/blog";
import { getI18n } from "@/core/i18n/server";

import { useMDXComponents as getMDXComponents } from "../../../mdx-components";

// eslint-disable-next-line @typescript-eslint/unbound-method
const Wrapper = getMDXComponents().wrapper;

export const metadata = {
  title: "All Posts",
  filePath: "blog/index.mdx",
};

export default async function PostsPage() {
  const { locale } = await getI18n();
  const posts = await getAllPosts(getPreferredBlogLang(locale));

  return (
    <Wrapper toc={[]} metadata={metadata} sourceCode="">
      <PostList title={metadata.title} posts={posts} />
    </Wrapper>
  );
}
