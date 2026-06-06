"""Analyze assembled graph vs scan result and fix issues."""
import json
import sys
import os

GRAPH_PATH = os.path.join(os.path.dirname(__file__), "assembled-graph.json")
SCAN_PATH = os.path.join(os.path.dirname(__file__), "scan-result.json")

def main():
    # Load files
    with open(GRAPH_PATH, "r", encoding="utf-8") as f:
        graph = json.load(f)
    with open(SCAN_PATH, "r", encoding="utf-8") as f:
        scan = json.load(f)

    nodes = graph["nodes"]
    edges = graph.get("edges", [])

    print(f"=== INITIAL STATS ===")
    print(f"Nodes: {len(nodes)}")
    print(f"Edges: {len(edges)}")

    # Collect node IDs
    node_ids = set(n["id"] for n in nodes)
    file_node_ids = set(nid for nid in node_ids if nid.startswith("file:"))
    print(f"File nodes: {len(file_node_ids)}")

    # All file paths from scan-result
    scan_files = {}
    for f in scan["files"]:
        scan_files[f["path"]] = f
    print(f"Files in scan: {len(scan_files)}")

    # 1. DROPPED NODES: files in scan but not in graph
    scan_file_ids = set(f"file:{p}" for p in scan_files.keys())
    missing_file_ids = scan_file_ids - file_node_ids
    print(f"\n=== MISSING FILE NODES: {len(missing_file_ids)} ===")
    for mid in sorted(missing_file_ids):
        path = mid[len("file:"):]
        info = scan_files[path]
        print(f"  {mid} (lang={info['language']}, lines={info['sizeLines']}, cat={info['fileCategory']})")

    # 2. DANGLING EDGES: edges referencing non-existent nodes
    dangling = []
    valid_edges = []
    for e in edges:
        if e["source"] not in node_ids or e["target"] not in node_ids:
            dangling.append(e)
        else:
            valid_edges.append(e)
    print(f"\n=== DANGLING EDGES: {len(dangling)} ===")
    for d in dangling:
        src_ok = "OK" if d["source"] in node_ids else "MISSING"
        tgt_ok = "OK" if d["target"] in node_ids else "MISSING"
        print(f"  {d['source']} [{src_ok}] -> {d['target']} [{tgt_ok}] (type={d['type']})")

    # 3. CROSS-BATCH EDGE GAPS: importMap entries not in edges
    import_map = scan.get("importMap", {})
    # Build set of existing import edges as (source, target)
    existing_import_edges = set()
    for e in edges:
        if e.get("type") == "imports":
            existing_import_edges.add((e["source"], e["target"]))

    missing_import_edges = []
    for src_path, targets in import_map.items():
        src_id = f"file:{src_path}"
        if src_id not in node_ids:
            continue  # source node doesn't exist
        for tgt_path in targets:
            tgt_id = f"file:{tgt_path}"
            if tgt_id not in node_ids:
                continue  # target node doesn't exist
            if (src_id, tgt_id) not in existing_import_edges:
                missing_import_edges.append((src_id, tgt_id))

    print(f"\n=== MISSING IMPORT EDGES: {len(missing_import_edges)} ===")
    for src, tgt in missing_import_edges[:30]:
        print(f"  {src} -> {tgt}")
    if len(missing_import_edges) > 30:
        print(f"  ... and {len(missing_import_edges) - 30} more")

    # 4. NODE QUALITY: nodes with empty summaries
    empty_summary_nodes = []
    for n in nodes:
        if not n.get("summary", "").strip():
            empty_summary_nodes.append(n["id"])
    print(f"\n=== NODES WITH EMPTY SUMMARIES: {len(empty_summary_nodes)} ===")
    for nid in empty_summary_nodes[:20]:
        print(f"  {nid}")
    if len(empty_summary_nodes) > 20:
        print(f"  ... and {len(empty_summary_nodes) - 20} more")

    # 5. Node type breakdown
    type_counts = {}
    for n in nodes:
        t = n.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    print(f"\n=== NODE TYPE BREAKDOWN ===")
    for t, c in sorted(type_counts.items()):
        print(f"  {t}: {c}")

    # 6. Edge type breakdown
    edge_type_counts = {}
    for e in edges:
        t = e.get("type", "unknown")
        edge_type_counts[t] = edge_type_counts.get(t, 0) + 1
    print(f"\n=== EDGE TYPE BREAKDOWN ===")
    for t, c in sorted(edge_type_counts.items()):
        print(f"  {t}: {c}")

    print("\n=== SUMMARY ===")
    print(f"Nodes to add (file recovery): {len(missing_file_ids)}")
    print(f"Import edges to add: {len(missing_import_edges)}")
    print(f"Dangling edges to remove: {len(dangling)}")
    print(f"Empty summary nodes: {len(empty_summary_nodes)}")


if __name__ == "__main__":
    main()
