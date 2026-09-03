# Security policy

Do not report vulnerabilities with a Billit API key, PartyID, real invoice content, or customer
data in a public issue. Revoke any credential that may have been exposed and report the problem to
the repository owner through a private channel.

The server is designed for local stdio use. Hosted transports and OAuth are not in scope. Each
operator is responsible for protecting the process environment and MCP client configuration that
contain their credentials.

Write-capable tools can modify accounting data. Develop in Billit's sandbox, keep production
writes disabled by default, and review tool arguments at the MCP host boundary.
