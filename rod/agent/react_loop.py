"""
agent/react_loop.py
OWNER: Teammate C

The core ReAct engine loop. Pattern per iteration:
    Thought  → LLM reasons about what to do next
    Action   → LLM picks a tool + arguments
    Observation → Tool result returned, appended to evidence trail

Loop terminates when:
    (a) LLM returns end_turn with final answer, OR
    (b) 10 iterations reached (hard cap — never infinite loops)

After termination:
    - confidence >= 0.7  → status = completed, report generated
    - confidence < 0.7   → status = escalated, partial evidence preserved

Calls:
    - mcp_server/server.py tools for data
    - knowledge_base/ for semantic search
    - reports/generator.py when end_turn reached
"""
