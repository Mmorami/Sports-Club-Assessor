# Agent Execution Rules
1. **Mock First Strategy**: NEVER execute live HTTP network requests during pytest/unit test generation. Always use fixtures from `data/mock/`.
2. **Subagent Delegation**: For task execution:
   - Use low-cost models for repetitive file generation or mock data creation.
   - Restrict full context reads. Use specific file paths only.
3. **Execution Plan**: Before modifying code, print a step-by-step checklist and wait for human approval.
4. **Search Strategy**: Before searching for functions or models, read docs/CODEBASE_MAP.md instead of running grep or glob across the entire codebase.
5. **Post-Task Protocol**: After creating or modifying any Python file in `src/`, always run `python scripts/generate_code_map.py` to keep `docs/CODEBASE_MAP.md` strictly updated before finishing the task.
