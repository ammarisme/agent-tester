# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use your code
host's private vulnerability reporting (on GitHub: *Security → Report a
vulnerability*). Include steps to reproduce and the version (`agent-tester
--version`, or the version shown in the UI sidebar).

We aim to acknowledge reports within three business days and to ship a fix or
mitigation for confirmed high-severity issues within 30 days.

## Supported versions

Security fixes are made on the latest minor release.

## Deployment guidance

Agent Tester sends HTTP requests to URLs that its users configure, so it is an
SSRF surface by design. Before exposing it to more than your own team, read
[docs/security.md](docs/security.md). In short:

- Put the UI behind your SSO or VPN, and set `API_TOKEN`.
- Run the controller in a network segment that should be reachable by the
  people who can create agents.
- Set `AGENT_TESTER_SECRET_PATTERN` so contracts can only read the environment
  variables meant for them.
- Treat stored trajectories as potentially sensitive: they contain request and
  response bodies.
