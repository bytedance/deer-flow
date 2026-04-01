import assert from "node:assert/strict";
import test from "node:test";

const { shouldSplitAnimatedText } = await import(
  new URL("./index.ts", import.meta.url).href,
);

void test("animates plain Chinese prose", () => {
  assert.equal(shouldSplitAnimatedText("这是正常的中文说明文本"), true);
});

void test("skips URL-like text", () => {
  assert.equal(
    shouldSplitAnimatedText("https://project.feishu.cn/t03o4q/issue/detail/6924970696"),
    false,
  );
});

void test("skips shell command text", () => {
  assert.equal(
    shouldSplitAnimatedText(
      'python scripts/autodrive_feishu_data_tool.py --mode auto --issue_url "https://project.feishu.cn/t03o4q/issue/detail/6924970696"',
    ),
    false,
  );
});

void test("skips filesystem paths", () => {
  assert.equal(
    shouldSplitAnimatedText("/mnt/user-data/workspace/coding_issues_D4Q2"),
    false,
  );
});
