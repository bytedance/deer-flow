"""
Fix assembled knowledge graph:
1. Fix malformed file: node IDs
2. Update edge references for renamed IDs
3. Add missing file nodes
4. Remove dangling edges
5. Add missing import edges
6. Check node quality
"""
import json
import os
import sys

GRAPH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assembled-graph.json")
SCAN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scan-result.json")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fix_malformed_ids(graph):
    """Fix file: prefixed IDs that should not have file: prefix."""
    rename_map = {}  # old_id -> new_id

    for node in graph["nodes"]:
        old_id = node["id"]
        new_id = None

        # Group A: file:file-backend-X -> file:backend/X
        if old_id.startswith("file:file-backend-"):
            filename = old_id[len("file:file-backend-"):]
            new_id = f"file:backend/{filename}"

        # Group B: file:backend/...py::SubNode -> class/variable:backend/...py:SubNode
        elif old_id.startswith("file:backend/") and "::" in old_id:
            parts = old_id.split("::", 1)
            filepath = parts[0][len("file:"):]  # remove "file:" prefix
            symbol = parts[1]

            # Determine the type based on symbol naming convention
            if symbol.isupper() or (symbol.startswith("_") and symbol[1:].isupper()):
                # Constants like CLOSURE_READ, _TRANSITIONS
                new_type = "variable"
            elif symbol.startswith("export::"):
                # Re-exports like export::EmbeddingCache
                actual_symbol = symbol[len("export::"):]
                new_id = f"class:{filepath}:{actual_symbol}"
            elif symbol[0].isupper():
                # Classes like AuthErrorCategory, ClosureMetadata
                new_type = "class"
            else:
                # Functions/variables like _UPDATE_ALLOWED_FIELDS
                new_type = "variable"

            if new_id is None:
                new_id = f"{new_type}:{filepath}:{symbol}"

        # Group C: file:method:Class.method -> function:guardrails/builtin.py:Class.method
        elif old_id.startswith("file:method:"):
            method_name = old_id[len("file:method:"):]
            new_id = f"function:backend/packages/harness/deerflow/guardrails/builtin.py:{method_name}"

        # Group D: file:dataclass:Name -> class:guardrails/provider.py:Name
        elif old_id.startswith("file:dataclass:"):
            class_name = old_id[len("file:dataclass:"):]
            new_id = f"class:backend/packages/harness/deerflow/guardrails/provider.py:{class_name}"

        # Group E: file:protocol:Name -> class:guardrails/provider.py:Name
        elif old_id.startswith("file:protocol:"):
            proto_name = old_id[len("file:protocol:"):]
            new_id = f"class:backend/packages/harness/deerflow/guardrails/provider.py:{proto_name}"

        if new_id and new_id != old_id:
            rename_map[old_id] = new_id
            node["id"] = new_id

    # Update edge references
    edge_updates = 0
    for edge in graph.get("edges", []):
        if edge["source"] in rename_map:
            edge["source"] = rename_map[edge["source"]]
            edge_updates += 1
        if edge["target"] in rename_map:
            edge["target"] = rename_map[edge["target"]]
            edge_updates += 1

    return len(rename_map), edge_updates, rename_map


def add_missing_file_nodes(graph, scan):
    """Add file nodes for scan files not represented in the graph."""
    # Collect existing file: node IDs
    existing_file_ids = set(n["id"] for n in graph["nodes"] if n["id"].startswith("file:"))
    # Also collect service: node paths to know which files have some representation
    service_paths = set()
    for n in graph["nodes"]:
        if n["id"].startswith("service:"):
            path = n.get("path", n["id"][len("service:"):])
            service_paths.add(path)

    # Build scan file lookup
    scan_files = {}
    for f in scan["files"]:
        scan_files[f["path"]] = f

    # Summary templates for different file types
    summary_templates = {
        "agents/memory/domain_queue.py": "领域消息队列定义，提供内存子系统的领域队列数据结构。",
        "agents/memory/domain_retrieval.py": "领域消息检索逻辑，提供从存储中按条件检索领域消息的实现。",
        "agents/memory/domain_storage.py": "领域消息持久化存储，提供领域消息的保存和查询接口。",
        "agents/memory/message_processing.py": "消息处理管道，负责内存消息的转换、验证和入库。",
        "agents/memory/prompt.py": "内存提示词模板，为内存更新和检索提供 LLM 提示词构建。",
        "agents/memory/queue.py": "内存更新队列，管理待处理的内存消息的入队和出队。",
        "agents/memory/retrieval.py": "内存检索接口，提供基于相关性的历史消息检索。",
        "agents/memory/session_queue.py": "会话消息队列，管理单个会话内的消息排队和批处理。",
        "agents/memory/session_storage.py": "会话消息存储，提供会话级别消息的持久化操作。",
        "agents/memory/storage.py": "内存存储抽象层，统一领域和会话消息的存储接口。",
        "agents/memory/summarization_hook.py": "摘要钩子，在会话达到阈值时自动触发历史消息压缩摘要。",
        "agents/memory/updater.py": "内存更新器，协调消息入库、摘要生成和过期清理。",
        "agents/middlewares/rag_middleware.py": "RAG 中间件，在智能体调用前自动注入检索增强上下文。",
        "agents/middlewares/summarization_middleware.py": "摘要中间件，在长对话时自动压缩历史消息以节省上下文。",
        "agents/middlewares/memory_middleware.py": "内存中间件，在智能体运行时管理内存事实的加载和保存。",
        "config/domain_memory_config.py": "领域内存配置，定义领域事实存储、检索和过期策略参数。",
        "config/memory_config.py": "内存总配置，聚合会话内存、领域内存和内存 API 的全局设置。",
        "config/rag_config.py": "RAG 配置，定义检索增强生成的分块、嵌入和检索参数。",
        "config/session_memory_config.py": "会话内存配置，定义会话事实存储、检索和隔离策略。",
        "config/tenant.py": "租户配置模型，定义多租户环境下的租户级别参数和隔离规则。",
        "persistence/run/sql.py": "运行记录 SQL 操作，提供运行相关数据的原生 SQL 查询。",
        "persistence/tenant/repository.py": "租户仓库实现，提供租户数据的 CRUD 和查询操作。",
        "persistence/thread_meta/base.py": "线程元数据基类，定义线程元数据仓库的抽象接口。",
        "persistence/thread_meta/memory.py": "线程元数据内存实现，提供基于内存的线程元数据存储。",
        "persistence/thread_meta/sql.py": "线程元数据 SQL 操作，提供线程元数据的原生 SQL 查询。",
        "runtime/events/store/base.py": "事件存储基类，定义运行时事件持久化的抽象接口。",
        "runtime/events/store/db.py": "事件数据库存储，提供基于数据库的运行时事件持久化。",
        "runtime/events/store/jsonl.py": "事件 JSONL 存储，提供基于 JSON Lines 文件的轻量事件持久化。",
        "runtime/events/store/memory.py": "事件内存存储，提供基于内存的运行时事件暂存。",
        "runtime/runs/store/base.py": "运行存储基类，定义运行记录持久化的抽象接口。",
        "runtime/runs/store/memory.py": "运行内存存储，提供基于内存的运行记录暂存实现。",
    }

    # Find missing files
    missing = []
    for path, info in scan_files.items():
        file_id = f"file:{path}"
        if file_id in existing_file_ids:
            continue
        if path in service_paths:
            # Has service: representation, still add file: node for completeness
            pass
        if info.get("fileCategory") == "docs" and info.get("sizeLines", 0) <= 1:
            # Skip trivial doc files (empty or single-line)
            continue
        missing.append((path, info))

    # Create file nodes
    added = 0
    for path, info in missing:
        file_id = f"file:{path}"
        filename = path.rsplit("/", 1)[-1] if "/" in path else path

        # Get summary from template or generate generic one
        short_path = path
        if short_path.startswith("backend/packages/harness/deerflow/"):
            short_path = short_path[len("backend/packages/harness/deerflow/"):]
        elif short_path.startswith("backend/"):
            short_path = short_path[len("backend/"):]

        summary = summary_templates.get(short_path)
        if not summary:
            lang = info.get("language", "unknown")
            cat = info.get("fileCategory", "code")
            if cat == "docs":
                summary = f"{filename} 文档文件，包含项目说明或配置指南。"
            elif cat == "config":
                summary = f"{filename} 配置文件，定义项目或工具的运行参数。"
            elif lang == "python":
                if filename.startswith("test_"):
                    # Generate test file summary from name
                    test_target = filename[len("test_"):-len(".py")]
                    summary = f"{test_target} 的单元测试，覆盖核心逻辑和边界条件。"
                else:
                    summary = f"{filename} 模块，提供相关的功能和接口实现。"
            elif lang == "sql":
                summary = f"{filename} 数据库迁移脚本，定义表结构和索引。"
            elif lang == "toml":
                summary = f"{filename} 项目配置文件，定义依赖和构建参数。"
            elif lang == "json":
                summary = f"{filename} 数据文件，存储结构化配置或测试数据。"
            elif lang == "jsonl":
                summary = f"{filename} 数据文件，以 JSON Lines 格式存储记录。"
            elif lang == "dockerfile":
                summary = f"{filename} 容器构建文件，定义镜像构建步骤。"
            elif lang == "makefile":
                summary = f"{filename} 构建脚本，定义常用开发命令和自动化任务。"
            elif lang == "markdown":
                summary = f"{filename} Markdown 文档，包含说明或参考资料。"
            else:
                summary = f"{filename} 文件。"

        node = {
            "id": file_id,
            "type": "file",
            "label": filename,
            "path": path,
            "language": info.get("language", "unknown"),
            "fileCategory": info.get("fileCategory", "code"),
            "sizeLines": info.get("sizeLines", 0),
            "summary": summary,
            "complexity": "simple" if info.get("sizeLines", 0) < 50 else "moderate"
        }
        graph["nodes"].append(node)
        added += 1

    return added


def remove_dangling_edges(graph):
    """Remove edges that reference non-existent nodes."""
    node_ids = set(n["id"] for n in graph["nodes"])
    valid_edges = []
    removed = 0
    for edge in graph.get("edges", []):
        if edge["source"] in node_ids and edge["target"] in node_ids:
            valid_edges.append(edge)
        else:
            removed += 1
    graph["edges"] = valid_edges
    return removed


def add_missing_import_edges(graph, scan):
    """Add import edges from scan importMap where both nodes exist."""
    node_ids = set(n["id"] for n in graph["nodes"])

    # Build set of existing import edges
    existing_import_edges = set()
    for e in graph.get("edges", []):
        if e.get("type") == "imports":
            existing_import_edges.add((e["source"], e["target"]))

    import_map = scan.get("importMap", {})
    added = 0
    for src_path, targets in import_map.items():
        src_id = f"file:{src_path}"
        if src_id not in node_ids:
            continue
        for tgt_path in targets:
            tgt_id = f"file:{tgt_path}"
            if tgt_id not in node_ids:
                continue
            if (src_id, tgt_id) not in existing_import_edges:
                graph["edges"].append({
                    "source": src_id,
                    "target": tgt_id,
                    "type": "imports",
                    "weight": 0.7,
                    "direction": "forward"
                })
                existing_import_edges.add((src_id, tgt_id))
                added += 1

    return added


def check_node_quality(graph):
    """Report nodes with empty or generic summaries."""
    empty_count = 0
    generic_count = 0
    for node in graph["nodes"]:
        summary = node.get("summary", "").strip()
        if not summary:
            empty_count += 1
        elif summary in ("TODO", "placeholder", "No description"):
            generic_count += 1
    return empty_count, generic_count


def main():
    print("Loading files...")
    graph = load_json(GRAPH_PATH)
    scan = load_json(SCAN_PATH)

    print(f"Initial: {len(graph['nodes'])} nodes, {len(graph.get('edges', []))} edges")

    # Step 1: Fix malformed IDs
    print("\n--- Step 1: Fix malformed IDs ---")
    renamed, edge_updates, rename_map = fix_malformed_ids(graph)
    print(f"  Renamed {renamed} node IDs, updated {edge_updates} edge references")
    if rename_map:
        for old, new in list(rename_map.items())[:10]:
            print(f"    {old} -> {new}")
        if len(rename_map) > 10:
            print(f"    ... and {len(rename_map) - 10} more")

    # Step 2: Add missing file nodes
    print("\n--- Step 2: Add missing file nodes ---")
    added_nodes = add_missing_file_nodes(graph, scan)
    print(f"  Added {added_nodes} missing file nodes")

    # Step 3: Remove dangling edges
    print("\n--- Step 3: Remove dangling edges ---")
    removed = remove_dangling_edges(graph)
    print(f"  Removed {removed} dangling edges")

    # Step 4: Add missing import edges
    print("\n--- Step 4: Add missing import edges ---")
    added_edges = add_missing_import_edges(graph, scan)
    print(f"  Added {added_edges} missing import edges")

    # Step 5: Quality check
    print("\n--- Step 5: Node quality check ---")
    empty, generic = check_node_quality(graph)
    print(f"  Nodes with empty summaries: {empty}")
    print(f"  Nodes with generic summaries: {generic}")

    # Final stats
    print(f"\n=== FINAL STATS ===")
    print(f"Nodes: {len(graph['nodes'])} (was {len(graph['nodes']) - added_nodes}, +{added_nodes})")
    print(f"Edges: {len(graph.get('edges', []))}")

    # Save
    print(f"\nSaving to {GRAPH_PATH}...")
    save_json(GRAPH_PATH, graph)
    print("Done!")

    return {
        "renamed_ids": renamed,
        "edge_ref_updates": edge_updates,
        "added_nodes": added_nodes,
        "removed_dangling": removed,
        "added_edges": added_edges,
        "empty_summaries": empty,
        "final_nodes": len(graph["nodes"]),
        "final_edges": len(graph.get("edges", []))
    }


if __name__ == "__main__":
    result = main()
    print(f"\n=== SUMMARY ===")
    print(f"Nodes renamed (malformed ID fix): {result['renamed_ids']}")
    print(f"Edge references updated: {result['edge_ref_updates']}")
    print(f"File nodes added (recovery): {result['added_nodes']}")
    print(f"Dangling edges removed: {result['removed_dangling']}")
    print(f"Import edges added (cross-batch): {result['added_edges']}")
    print(f"Nodes with empty summaries: {result['empty_summaries']}")
    print(f"Final node count: {result['final_nodes']}")
    print(f"Final edge count: {result['final_edges']}")
