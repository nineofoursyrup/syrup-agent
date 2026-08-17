"""syrup-agent — a minimal, transparent, local-first Syrup.

Four pillars, one module each:
  harness  → syrup/runtime + syrup/gateway  (scaffolding around the raw LLM)
  loop     → syrup/loop                      (observe → reason → act → repeat)
             syrup/graph                     (opt-in structure around the loop — extends this pillar)
  memory   → syrup/memory                    (procedural / semantic / episodic)
  ops      → syrup/ops + evals/              (trace → eval → gate → release)
"""

__version__ = "0.1.0"
