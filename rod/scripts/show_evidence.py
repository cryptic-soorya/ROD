# """
# scripts/show_evidence.py

# Prints the exact provenance for one investigation: the final report's
# root_cause/confidence, then every tool call the agent made in order (tool
# name, exact arguments, exact result JSON) read straight from
# investigations/orchestration.db's tool_calls table — no re-running the
# agent, just showing what it actually saw. Also re-runs the grounding check
# (agent/grounding.py) against the stored evidence so any entity in
# root_cause that never appeared in a tool result, or any implied link
# between two entities that never co-occurred in one tool result, is called
# out explicitly.

# Usage (from rod/):
#     python scripts/show_evidence.py <investigation_id>
# """

# import json
# import sqlite3
# import sys
# from pathlib import Path

# sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# from agent.grounding import check_grounding

# DB_PATH = Path(__file__).resolve().parent.parent / "investigations" / "orchestration.db"


# def main(investigation_id: int) -> None:
#     conn = sqlite3.connect(DB_PATH)
#     conn.row_factory = sqlite3.Row

#     inv = conn.execute(
#         "SELECT id, query, status, report FROM investigations WHERE id = ?",
#         (investigation_id,),
#     ).fetchone()
#     if inv is None:
#         print(f"No investigation with id {investigation_id}")
#         return

#     report = json.loads(inv["report"]) if inv["report"] else {}
#     root_cause = report.get("root_cause", "")

#     print("=" * 100)
#     print(f"Investigation {inv['id']}: {inv['query']!r}  [status={inv['status']}]")
#     print("=" * 100)
#     print(f"\nroot_cause:\n  {root_cause}\n")
#     print(f"confidence_score: {report.get('confidence_score')}")
#     print(f"anomaly_category: {report.get('anomaly_category')}\n")

#     rows = conn.execute(
#         "SELECT tool_name, input_args, output, error, called_at FROM tool_calls "
#         "WHERE investigation_id = ? ORDER BY id",
#         (investigation_id,),
#     ).fetchall()

#     print("-" * 100)
#     print(f"Tool calls made ({len(rows)}) — this is everything the model actually saw:")
#     print("-" * 100)
#     evidence_trail = []
#     for i, row in enumerate(rows, 1):
#         args = json.loads(row["input_args"]) if row["input_args"] else {}
#         output = json.loads(row["output"]) if row["output"] else row["error"]
#         print(f"\n[{i}] {row['tool_name']}({json.dumps(args)})")
#         print(f"    -> {json.dumps(output)}")
#         evidence_trail.append({"step": i, "tool": row["tool_name"], "args": args, "finding": output})

#     print("\n" + "-" * 100)
#     warnings = check_grounding(root_cause, evidence_trail)
#     if warnings:
#         print(f"GROUNDING CHECK: {len(warnings)} issue(s) found — root_cause is NOT fully supported by the tool calls above:")
#         for w in warnings:
#             print(f"  ! {w}")
#     else:
#         print("GROUNDING CHECK: every entity in root_cause was observed in the tool calls above. No unsupported links found.")
#     print("-" * 100)

#     conn.close()


# if __name__ == "__main__":
#     if len(sys.argv) != 2:
#         print("usage: python scripts/show_evidence.py <investigation_id>")
#         sys.exit(1)
#     main(int(sys.argv[1]))
