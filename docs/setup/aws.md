# Optional hosting: one persistent host

TerraSentry's default is an API/cockpit on a developer machine with SQLite files; a tunnel lets
the Joule proxy on SAP BTP Cloud Foundry reach the API. No AWS resources are required or created.
`infra/cdk` remains an empty shell.

If the API must leave the laptop, use a host with a persistent local filesystem and run the API
and web containers there. The existing Compose configuration mounts `sqlite-data` at
`/app/data/sqlite`, containing `audit.db` and `cache.db`. Keep that volume when replacing containers.
An arbitrary stateless container host is insufficient unless durable storage is explicitly configured.

- Run one API process/replica; review locks, SSE subscribers and run recovery are process-local.
- Do not put SQLite WAL files on a shared network filesystem or share them between API replicas.
- Stop the API before running schema changes or the headless rehearsal against its audit file.
- Set `API_TOKEN` and the cockpit's `VITE_API_TOKEN` before exposing write endpoints publicly;
  configure the public API URL and allowed browser origins as described in the main setup runbook.
- Back up both files with writers stopped. Keep fixture exports to rebuild the disposable cache.
- `docker compose down` preserves the volume; `docker compose down -v` is a destructive demo reset.

Hosting credentials, instance choice and deployment automation are outside this hackathon change.
If you provision cloud resources, record their cost and teardown steps with that deployment; this
repository does not provision managed database or cache services.
