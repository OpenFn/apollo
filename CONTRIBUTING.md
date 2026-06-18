# Contributing

Want to contribute to OpenFn Apollo? Read on.

For technical details about the server architecture (including how the JS server
calls python modules), see the main readme.

## Pull requests

When your fix or feature is completed, raise a pull request against
[openfn/apollo](https://www.github.com/openfn/apollo).

Make sure to include a changeset: run `bun changeset`, follow the prompts, and
commit the changes.

Changesets are release notes which are saved to a file in the repo. When the
release is prepared, all changesets are assembled into the changelog and the
server version is increased automatically.

To write a good changeset:

- Keep it short, usually just one sentence.
- Only include a single feature/fix/change per changeset
- You can include as many different changesets as you like
- Describe of the changes from the end user's perspective.
- Do not make it a sales pitch, do not sell the change.
- Do not justify or explain the change. No why or because.
- If there are breaking changes for users, include a migration guide.

## Adding a Python Module

Your python service can be your own little world inside Apollo. We give you a
subfolder and couple of conventions to stick to, and that's it.

Any subfolder not starting with `_` in the `services` folder will be
automatically mounted at

```
/services/<service_name>
```

You need a `<service-name>.py` file in the root folder with a `main()` function.
This will be called by the web server when someone makes a post request to your
endpoint, passing the JSON payload as a dict.

The main function will be called by the server and should return a JSON payload,
which will be appended to the response body and sent back to the client via
HTTP.

Inside your module folder, you can use whatever structure you like. Run
`poetry add <module>` to add dependencies (they'll be installed at the root
level `pyproject.toml`).

**You should use relative paths to import py files in the same service, or
absolute module names (relative to `/services/`) to import from other
services.**

ie, from `services/example/example.py`, to load `services/example/util.py`, do:

```python
from .util import my_function
```

To load from a different module (like `inference`), do:

```python
from inference import inference

inference.generate('gpt3', 'do the thing')
```

The Javascript bridge will always call into `entry.py` and dynamically invoke
your service's main function, so technically speaking all imports are relative
to `entry.py`.

## Logging

A utility library is provided for you to create a logger:

```python
from util import create_logger

logger = create_logger("myservice.filename")
```

You can use whatever name you like for the logger (including `__name__`).

All lines from this logger are diverted to the CLI (via websocket).

For "private" and debug logging, use `print()` statements. The end user will not
see these.

## Documentation

All modules should come with basic documentation.

Include a `README.md` (case sensitive) with your repo which explains basic
usage.

The readme will be displayed from the server root as documentation for users,
with the first text paragraph used as a summary.

For example best practice, see `services/adaptor_gen`

## Calling python Directly

Debugging through the web server can be hard because error messages are pretty
terse.

You can call straight into your python - with the poetry environment all set up
and everything - from the CLI.

From the repo root, just run:

```bash
bun py <service-name> [path/to/input.json]
```

For example:

```bash
bun py echo tmp/payload.json
```

This will call the `echo` service via `entry.py`, which sets up the right paths
etc. You can optionally include a path to the payload, which will be loaded as
JSON and passed to the module.

Running code this way is exactly the same as doing it through the webserver -
you're bypassing the HTTP layer but otherwise invoking your python the same way.

You don't need to create your own `if __name__ == "__main__":` logic inside oyur
python scripts - `entry.py` will do all that for you.

## Use Env

If your services requires an API key, you should:

- accept the key on your json payload
- if no key is provided, load a from the environment

Use a `.env` file at root and add your own keys to it (see `.env.example`)

dotenvs are only suitable for local development.

## Python Dependencies

Python dependencies are managed by poetry using a pyproject.toml in the root
directly.

To add a new dependency, run this anywhere in the repo:

```
poetry add numpy
```

## Installing models

To add models as python packages:

- Copy the `.whl` file to `/models` at the repo root
- Add the file to poetry (you should be able to do
  `poetry add models/<my-model>.whl`)
