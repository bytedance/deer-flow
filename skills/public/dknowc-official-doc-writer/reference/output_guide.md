# 输出规范（DeerFlow 版）

## 一、允许的 Markdown 结构

仅允许以下结构用于生成 Word：

```markdown
# 公文标题
## 一、一级标题
### （一）二级标题
#### 1.三级标题
正文段落
```

约束：
- 正文禁止使用列表、粗体、斜体、代码块、引用、分割线。
- 正文禁止插入 Markdown 链接。
- 【知识专库链接】区允许保留原始 `https://` URL（每行一个）。

## 二、普通公文命令

```bash
python3 scripts/format_document.py \
  --text "公文内容..." \
  --output ./output/文件名.docx
```

## 三、版本号规则

用户要求修改已生成公文时，脚本会自动追加版本号避免覆盖：
- 初始版本：`公文标题.docx`
- 第一次修改：`公文标题_v1.docx`
- 第二次修改：`公文标题_v2.docx`

## 四、输出目录规则

- 若设置环境变量 `OFFICIAL_DOC_OUTPUT_DIR`，优先输出到该目录。
- 否则输出到当前目录下 `./output/`。

## 五、说明

本 DeerFlow 公开版不包含红头模板处理能力。
