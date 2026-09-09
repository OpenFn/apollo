## Echo

A simple test service which returns whatever is passed into it.

## Usage

Call the endpoint at `services/echo`

```bash
curl -X POST localhost:3000/services/echo --json @tmp/data.json
```

Whatever you include in the body will be returned straight back, with one
exception: values the server fills in itself, such as `api_key`, come back as
`[REDACTED]`, as does anything else shaped like a key. Those belong to the
deployment rather than to the caller, so echo does not hand them out.
