"""Tests for graph/communities.py — Louvain 社区检测纯函数（spec §4 P1）。

着色稳定性的全部保证都在这里：固定随机种子（同数据两次调用同划分）+
社区 id 按规模降序重编号（0 = 最大社区，前端色板主色稳定）。
"""

from __future__ import annotations

from deerflow.knowledge.graph.communities import assign_communities

# 两个明显簇 + 一个孤立点：{A,B,C} 三角连通，{D,E} 单链，F 无边。
NODES = ["A", "B", "C", "D", "E", "F"]
EDGES = [("A", "B"), ("B", "C"), ("A", "C"), ("D", "E")]


def test_deterministic_with_fixed_seed() -> None:
    first = assign_communities(NODES, EDGES)
    second = assign_communities(NODES, EDGES)
    assert first == second
    assert set(first) == set(NODES)


def test_community_ids_sorted_by_size_desc() -> None:
    result = assign_communities(NODES, EDGES)
    # 大簇 {A,B,C} 拿社区 0，小簇 {D,E} 拿 1，孤立点 F 拿 2。
    assert result["A"] == result["B"] == result["C"] == 0
    assert result["D"] == result["E"] == 1
    assert result["F"] == 2


def test_isolated_nodes_form_singleton_communities() -> None:
    result = assign_communities(["独一", "独二"], [])
    assert result["独一"] != result["独二"]


def test_empty_graph_returns_empty() -> None:
    assert assign_communities([], []) == {}


def test_single_node_gets_community_zero() -> None:
    assert assign_communities(["独苗"], []) == {"独苗": 0}


def test_self_loops_are_ignored() -> None:
    # 自环边（抽取噪声）不得炸掉社区检测，也不影响 A/B 的同簇判定。
    result = assign_communities(["A", "B"], [("A", "A"), ("A", "B")])
    assert result["A"] == result["B"]


def test_edges_referencing_unknown_nodes_are_ignored() -> None:
    # 关系端点不在实体表（脏数据防御）：跳过该边，不引入幻影节点。
    result = assign_communities(["A"], [("A", "幽灵")])
    assert result == {"A": 0}
