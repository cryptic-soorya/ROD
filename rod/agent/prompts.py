"""
agent/prompts.py
OWNER: Teammate C

System prompt given to Claude Sonnet at the start of each investigation.
Also contains the tool descriptions (registered tool list) fed to the LLM.

Key constraint: JWT / MCP_AUTH_TOKEN must NEVER appear in this file or in any message to the LLM.
"""
