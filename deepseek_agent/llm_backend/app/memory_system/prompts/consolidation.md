# AutoDream Consolidation

Phase 1 - Orient:
Review the memory manifest and MEMORY.md indexes. Treat Markdown memory files as the long-term memory source of truth.

Phase 2 - Gather recent signal:
Read only the relevant transcript snippets. Do not read every large transcript file unless necessary.

Phase 3 - Consolidate:
Merge duplicate memories, correct contradictions, and mark stale or superseded memory. Preserve trusted source metadata for business_rule entries.

Phase 4 - Prune and index:
Update MEMORY.md. Remove stale or superseded index pointers. Do not store memory bodies in MEMORY.md.

Safety rules:

- Do not call business systems.
- Do not inspect source code, git history, API implementation details, secrets, or database files.
- Do not convert ordinary customer statements into business_rule memory.
- business_rule memory must keep source_type, effective_from, effective_to, verified_by, and verified_at.
- Realtime facts such as order status, inventory count, current price, logistics status, and after-sales progress must remain tool evidence, not long-term memory.
