# Apollo Server

Apollo is OpenFn's knowledge, AI and data platform, providing services to
support the OpenFn toolchain.

Apollo is known as the God of (among other things) truth, prophecy and oracles.

This repo contains:

- A bunjs-based webserver
- A number of python-based AI services
- (soon) A numberof Typescript-based data services

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

## Troubleshooting

If you get errors like `poetry: command not found` (error code 127), and poetry
is set up on your machine, you may need to add these env vars to your `.bashrc`
(or whatever you use):

```
export BUN_INSTALL= "$HOME/.bun"
export PATH= "$BUN_INSTALL/bin:$PATH"
```

## Bun installation

Bun does not require an installation, like npm does. You can run `bun start`
right after cloning the repo.

Bun will then install dependencies against the global cache on your machine.
This still uses package.lock.

To update a module version, run `bun add <module>@version>`, which will update
your lockfile.

One drawback of this is that there is no intelliense, because IDEs rely on
node_modules to load d.ts files. You are welcome to run `bun install` to run
from a node_modules. None of this affects python.

See [bun auto-install]() for more details.

## Python Setup

This repo uses `poetry` to manage dependencies.

We use an "in-project" venv , which means a `.venv` folder will be created when
you run `poetry install`.

All python is invoked through `entry.py`, which loads the environment properly
so that relative imports work.

You can invoke entry.py directly (ie, without HTTP or any intermedia js) through
bun from the root:

```
bun py echo tmp/payload.json
```

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
export OPENFN_APOLLO_DEFAULT_ENV=http://locahost:6666
```

Output will be shown in stdout by default. Pass `-o path/to/output/.json` to
save the output to disk.

You can get more help with:

```
openfn apollo help
```

Note that if a service returns `{ files: {} }` object in the payload, an you
pass `-o` with a folder, those files will be written to disk .

## API Keys & Env vars

Some services require API keys.

Rather than coding these into your JSON payloads directly, keys can be loaded
from the `.env` file at the root.

Also note that `tmp` dirs are untracked, so if you do want to store credentials
in your json, keep in inside a tmp dir and it'll remain safe and secret.

## Server Architecture

The Apollo server uses bunjs with the Elysia framework.

It is a very lightweight server, with at the time of writing no authentication
or governance included.

Python services are hosted at `/services/<name>`. Each services expects a POST
request with a JSON body, and will return JSON.

There is very little standard for formality in the JSON structures to date. The
server may soon establish some conventions for better interopability with the
CLI.

Python scripts are invoked through a child process. Each call to a service runs
in its own context.

Python modules are pretty free-form but must adhere to a minimal structure. See
the Contribution Guide for details.

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

`log`: send by the server whenever a `print()` line is logged by the python
process.

Note that `print()` statements do not get send out to the web socket, as these
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

## Finetuning and poetry dependency groups

`poetry install` will only install the main dependencies - the stuff used in the
docker image.

Dependencies for finetuning (which include huge models) are in a special
optional `ft` group in the `pyproject.toml`.

To install these, do `poetry install --with ft`

## Contributing

See the Contribution Guide for more details about how and where to contribute to
the Apollo platform.
