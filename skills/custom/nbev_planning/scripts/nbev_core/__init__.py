"""nbev_core — nbev_planning skill 的自包含内部包。

把共享逻辑收在 skill 自己的 scripts/nbev_core/ 内，使 skill 完全自包含、
可被 DeerFlow 渐进加载，不依赖任何跨 skill 的兄弟目录或 sys.path 黑魔法。
"""
