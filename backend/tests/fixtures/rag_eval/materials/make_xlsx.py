"""Regenerate the two .xlsx evaluation materials (prep-time helper, not CI).

Requires ``openpyxl`` and ``Pillow`` (present in the backend dev venv).
Run from this directory:  ``python make_xlsx.py``

- ``collection-complexity.xlsx`` — the table-modality corpus (集合复杂度表).
- ``jvm-architecture.xlsx`` — the image-modality corpus: the sheet text plus an
  embedded architecture diagram whose captions answer the image question.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent

#: Windows 自带中文字体；缺失时回退默认字体（图仍可生成，字形会退化）。
_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size)


def build_collection_complexity(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "复杂度"
    ws.append(["集合", "随机访问", "插入", "删除", "查找"])
    ws.append(["ArrayList", "O(1)", "O(n)", "O(n)", "O(n)"])
    ws.append(["LinkedList", "O(n)", "O(1)", "O(1)", "O(n)"])
    ws.append(["HashSet", "不支持", "O(1)", "O(1)", "O(1)"])
    ws.append(["HashMap", "不支持", "O(1)", "O(1)", "O(1)"])
    ws.append(["TreeMap", "不支持", "O(log n)", "O(log n)", "O(log n)"])
    wb.save(path)


def build_jvm_architecture(path: Path) -> None:
    diagram = HERE / "jvm-architecture.png"
    width, height = 760, 420
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    title = _font(34)
    body = _font(26)
    small = _font(22)
    draw.rectangle((10, 10, width - 10, height - 10), outline="black", width=3)
    draw.text((30, 24), "JVM 架构图", fill="black", font=title)
    # 线程私有区
    draw.rectangle((30, 90, 350, 250), outline="#1d4ed8", width=3)
    draw.text((45, 100), "线程私有区域", fill="#1d4ed8", font=body)
    draw.text((45, 140), "程序计数器", fill="black", font=body)
    draw.text((45, 175), "虚拟机栈", fill="black", font=body)
    draw.text((45, 210), "本地方法栈", fill="black", font=body)
    # 线程共享区
    draw.rectangle((410, 90, 730, 250), outline="#b91c1c", width=3)
    draw.text((425, 100), "线程共享区域", fill="#b91c1c", font=body)
    draw.text((425, 140), "堆（Heap）", fill="black", font=body)
    draw.text((425, 175), "方法区（元空间）", fill="black", font=body)
    # 执行引擎
    draw.rectangle((30, 290, 730, 380), outline="#047857", width=3)
    draw.text((45, 300), "执行引擎", fill="#047857", font=body)
    draw.text((45, 340), "解释器 + 即时编译器（JIT） + 垃圾回收器", fill="black", font=small)
    draw.text((190, 260), "对象分配 / GC", fill="#b91c1c", font=small)
    img.save(diagram)

    # 图即内容（RFC v3 §8.1 的「含图文档」形态）：表格只放一句指路语，区域/组成等
    # 事实全部标注在图上、由 VLM 图注转写进切片正文——这样「依赖图片」的题目才是真的
    # 依赖图片链，而不是被表格文字顺手答掉。
    wb = Workbook()
    ws = wb.active
    ws.title = "架构"
    ws.append(["JVM 架构图（内容见下图，图中标注各内存区域的归属与执行引擎组成）"])
    pil_img = XLImage(str(diagram))
    pil_img.anchor = "A3"
    ws.add_image(pil_img)
    wb.save(path)
    diagram.unlink()  # 只保留工作簿内嵌副本


if __name__ == "__main__":
    build_collection_complexity(HERE / "collection-complexity.xlsx")
    build_jvm_architecture(HERE / "jvm-architecture.xlsx")
    print("materials regenerated")
