# Contributing

Keep this project small and auditable. Before adding a Billit capability that broadens the MCP
surface, open an issue describing the concrete personal workflow and its side effects.

Every change should:

- include unit tests for endpoints, casing, validation, and mapping;
- update tool documentation when behavior changes;
- use sanitized fixtures with no real invoice or customer data;
- avoid logging secrets, authorization headers, or full invoice bodies;
- validate API-contract changes in a dedicated Billit sandbox;
- explicitly document side effects for every new write tool; and
- keep invoice sending out of scope unless it is separately designed and reviewed.

Do not put API keys, production IDs, or real customer data in commits, issues, test output, or pull
requests.
