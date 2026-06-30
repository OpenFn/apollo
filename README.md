# Apollo Server

Apollo is OpenFn's knowledge, AI and data platform, providing services to
support the OpenFn toolchain.

Apollo is known as the God of (among other things) truth, prophecy and oracles.

This repo contains:

- A bunjs-based webserver
- A number of python-based AI services
- A number of Typescript-based data services

## Documentation

This README covers running, debugging and deploying the server. Deeper docs live
alongside the code:

- **Architecture** - see [Server Architecture](#server-architecture) below, and
  each service's own README for service-specific detail.
- **Contributing & service conventions** - [`CONTRIBUTING.md`](CONTRIBUTING.md)
  explains how to add and structure a Python service (entry.py, imports,
  logging, code quality).
- **Services** - every service has its own README with payload specs and
  examples. See the [Services](#services) index below.
- **Instance auth** -
  [`platform/src/auth/README.md`](platform/src/auth/README.md) covers
  authenticating `/services/*` per client and managing per-client Anthropic
  keys.
- **Testing** - [`services/testing/README.md`](services/testing/README.md)
  documents the shared acceptance-test harness (YAML specs + LLM-as-judge);
  per-service guides live in each service's `tests/`.

## Requirements

To run this server locally, you'll need the following dependencies to be
installed:

- python 3.11 (yes, 3.11 exactly, see Python Setup)
- poetry
- bunjs

We recommend using asdf with the
[python plugin](https://github.com/asdf-community/asdf-python) installed.

## Getting Started

To run the server locally, you need to install the python dependencies

```bash
poetry install
```

Then start the server (note that bun install is not needed, see below)

```bash
bun start
```

To start a hot-reloading development server which watches your typescript, run:

```bash
bun dev
```

To see an index of the available language services, head to `localhost:3000`.

## Python Setup

This repo uses `poetry` to manage dependencies.

We use an "in-project" venv , which means a `.venv` folder will be created when
you run `poetry install`.

All python is invoked through `entry.py`, which loads the environment properly
so that relative imports work.

You can invoke entry.py directly (ie, without HTTP or any intermediate js)
through bun from the root:

```
bun py echo --input tmp/payload.json
```

## Bun installation

Bun does not require an installation, like npm does. You can run `bun start`
right after cloning the repo.

Bun will then install dependencies against the global cache on your machine.
This still uses the lockfile (`bun.lockb`).

To update a module version, run `bun add <module>@<version>`, which will update
your lockfile.

One drawback of this is that there is no intellisense, because IDEs rely on
node_modules to load d.ts files. You are welcome to run `bun install` to run
from a node_modules. None of this affects python.

See [bun's install docs](https://bun.sh/docs/cli/install) for more details.

## CLI

To communicate with and test the server, you can use `@openfn/cli`.

Use the `apollo` command with your service name and pass a json file:

```
openfn apollo echo tmp/payload.json
```

Pass `--staging`, `--production` or `--local` to call different deployments of
apollo.

To default to using your local server, you can set an env var:

```
export OPENFN_APOLLO_DEFAULT_ENV=local
```

Or pass an explicit URL if you're not running on the default port:

```
export OPENFN_APOLLO_DEFAULT_ENV=http://localhost:6666
```

Output will be shown in stdout by default. Pass `-o path/to/output/.json` to
save the output to disk.

You can get more help with:

```
openfn apollo help
```

Note that if a service returns a `{ files: {} }` object in the payload, and you
pass `-o` with a folder, those files will be written to disk.

## API Keys & Env vars

Some services require API keys.

Rather than coding these into your JSON payloads directly, keys can be loaded
from the `.env` file at the root. See [`.env.example`](.env.example) for the
full list of keys and env vars Apollo reads.

Also note that `tmp` dirs are untracked, so if you do want to store credentials
in your json, keep it inside a tmp dir and it'll remain safe and secret.

## Debugging

The server defaults to port 3000. You can test any service directly with curl to
confirm Apollo is working independently of Lightning (or any other client).

For example, to trigger a `workflow_chat` stream:

```bash
curl -N -X POST http://localhost:3000/services/workflow_chat/stream \
    -H "Content-Type: application/json" \
    -d '{"content":"make a simple http workflow","history":[],"api_key":"<your-anthropic-api-key>"}'
```

The `api_key` field is your Anthropic API key. If `ANTHROPIC_API_KEY` is already
set in your `.env`, you can omit it. In Lightning, this is configured via the
`ANTHROPIC_API_KEY` environment variable and passed through to Apollo on each
request.

The `-N` flag disables buffering so SSE events appear as they arrive. You should
see a stream of `event: log` lines followed by `event: complete`. An
`event: error` response means the issue is inside Apollo.

If the stream returns successfully here but Lightning isn't receiving it, the
issue is on the Lightning side -- check that
`APOLLO_ENDPOINT=http://localhost:3000` is set correctly in Lightning's
environment (no trailing slash).

To check API key connectivity (Anthropic, OpenAI, Pinecone), hit the status
service:

```bash
curl http://localhost:3000/services/status
```

## Troubleshooting

If you get errors like `poetry: command not found` (error code 127), and poetry
is set up on your machine, you may need to add these env vars to your `.bashrc`
(or whatever you use):

```
export BUN_INSTALL="$HOME/.bun"
export PATH="$BUN_INSTALL/bin:$PATH"
```

## Server Architecture

The Apollo server uses bunjs with the Elysia framework.

It is a very lightweight server. By default it includes no authentication, but
instance auth can be enabled (see [Database](#database) below).

Python services are hosted at `/services/<name>`. Each service expects a POST
request with a JSON body, and will return JSON.

There is very little standard for formality in the JSON structures to date. The
server may soon establish some conventions for better interopability with the
CLI.

Python scripts are invoked through a child process. Each call to a service runs
in its own context.

Python modules are pretty free-form but must adhere to a minimal structure. See
the [Contribution Guide](CONTRIBUTING.md) for details.

## Services

Each service lives in `services/<name>/` and is auto-mounted by service
discovery.

Start the server with `bun start` and head to `http://localhost:3000` to see an
overview of active services. Or go to `https://apollo.openfn.org` to see the
production services.

## Database

Apollo uses Postgres for two tables: `adaptor_function_docs` (parsed adaptor
docs, used by `load_adaptor_docs` / `search_adaptor_docs`) and
`lightning_clients` (the instance-auth allow-list).

There is no migration framework. The schema is just two `schema.sql` files you
apply with `psql`, both written with `CREATE TABLE IF NOT EXISTS` so re-running
them is safe:

- [`services/load_adaptor_docs/schema.sql`](services/load_adaptor_docs/schema.sql)
  - `adaptor_function_docs`. This table is also created lazily the first time
    `load_adaptor_docs` runs, so applying it by hand is optional.
- `lightning_clients` - created and kept current by the migration runner
  (`platform/src/db/migrate.ts`, migrations under
  [`platform/migrations/`](platform/migrations/)). It is applied automatically
  at Apollo startup when `POSTGRES_URL` is set; no manual `psql` step is needed.

First, make sure you've configured your desired `POSTGRES_URL` in your `.env`
file.

### Create the DB

Create a Postgres DB matching your POSTGRES_URL from the `.env` file

### To reset the DB

`set -a; . ./.env; set +a; psql "$POSTGRES_URL" -c "DROP TABLE IF EXISTS lightning_clients, adaptor_function_docs CASCADE;"`

### Run the migrations

`lightning_clients` is migrated automatically at Apollo startup (see
`platform/src/db/migrate.ts`). Apply the adaptor-docs schema separately:

`set -a; . ./.env; set +a; psql "$POSTGRES_URL" -f services/load_adaptor_docs/schema.sql`

### Instance authentication (optional)

`/services/*` is authenticated so that only known clients (e.g. specific
Lightning instances) may call it, with Apollo using **each client's own
Anthropic API key** for that client's requests.

The auth hook is always active. A request that carries an `api_key` must resolve
to a known Lightning client or it is **rejected**. Clients are looked up in the
`lightning_clients` table via `APOLLO_CLIENTS_DB_URL` (falling back to
`POSTGRES_URL` when unset).

To enable it and provision clients, see
[`platform/src/auth/`](platform/src/auth/README.md).

#### Deploying: pin `APOLLO_INTERNAL_TOKEN` in production

`APOLLO_INTERNAL_TOKEN` is the mechanism that lets internal `apollo()`
self-calls through the auth hook: a self-call carries it in the
`x-apollo-internal` header and the hook matches it. Because the global
`ANTHROPIC_API_KEY` is dev-only, a token that fails to match is a dead end (a
`401`), not a soft fallback to the global key - so the match has to work in
every topology.

- **Always set `APOLLO_INTERNAL_TOKEN` to a shared value across the deployment
  in production.** When it is set, the per-process minting path never runs.
- The per-process random mint is a **dev-only convenience**. Apollo assumes one
  Bun process per host; the `apollo()` self-call relies on loopback calls
  landing on the same process, so a minted token only works
  single-process-per-host.
- If `reusePort` clustering is ever enabled, a shared `APOLLO_INTERNAL_TOKEN` is
  **required**, not optional: a self-call can otherwise be routed to a sibling
  process that minted a different token and will `401`. Startup logs the token's
  provenance (env vs minted) and warns when this dangerous combination is
  detected; a mismatch at the hook is logged as a distinct, greppable warning.

## Websockets

Every service can receive connections in one of two ways:

- HTTP POST method
- Websocket connection

The same URL is used for both connections, clients must request upgrade to a
websocket.

Websocket connections will receive a live log stream.

Websockets use the following events:

`start`: sent by the client with a JSON payload in the `data` key.

`complete`: sent by the server when the python script has completed. The result
is a JSON payload in the `data` key.

`log`: sent by the server whenever the python process logs a line through a
logger object.

Note that `print()` statements do not get sent out to the web socket, as these
are intended for local debugging. Only logs from a logger object are diverted.

## Docker

To build the docker image:

```bash
docker build .  -t openfn-apollo
```

To run it on port 3000

```bash
docker run -p 3000:3000 openfn-apollo
```

## Contributing

See the [Contribution Guide](CONTRIBUTING.md) for more details about how and
where to contribute to the Apollo platform.

## Release

New releases are assembled as Docker images whenever a version tag of the form
`@openfn/apollo@x.y.x` is pushed to GitHub.

This tag is automatically generated upon merging to main.

Github's `main` should represent the latest production version of apollo.
Ideally, releases should be assembled on a branch - usually `release/next` or
`release/1.2.3`. But this is not required - releases can be cut straight from a
fix or feature branch, or even from main.

To release a new apollo version:

- Checkout the branch that contains the release
- Run `bun changeset version`
- (if there are no changesets, you can either run `bun changeset` to create one,
  or manually bump `package.json` and update `changelog.md`)
- Sanity check the new version number and changelog updates, just to be sure
  there's no funny stuff.
- Commit changes and push
- When the PR is merged to main, a new tag is generated and a new Docker image
  is built
