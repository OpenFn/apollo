# workflow_chat Service

** Workflow GENERATION AN EXPERIMENTAL FEATURE**

This is a chat service for generating a workflow.yaml. It can chat with a user and generate a YAML when required.

## Usage

Send a POST request to `/services/workflow_chat` with a JSON body containing a `content` and `history` field.

### CLI Call
  
  ```bash
   poetry run python services/entry.py workflow_chat tmp/input.json tmp/output.json
  ```

  - make sure to replace `tmp/input.json` with the path to the input file and `tmp/output.json` with the path to the output file, or you can create tmp directory in the root of the project and run the command as is.

### Example Input

Simple input:

```json
{
  "content": "Whenever fridge statistics are send to you, parse and aggregate the data and upload to a collection in redis.",
  "existing_yaml": "",
  "history": []
}
```

Second conversation turn example:

```json
{
  "content": "Actually I want to schedule it for midnight every day.",
  "existing_yaml": "name: fridge-statistics-processing\njobs:\n  parse-and-aggregate-fridge-data:\n    name: Parse and Aggregate Fridge Data\n    adaptor: '@openfn/language-common@latest'\n    body: '| // Add data parsing and aggregation operations here'\n  upload-to-redis:\n    name: Upload to Redis Collection\n    adaptor: '@openfn/language-redis@latest'\n    body: '| // Add Redis collection upload operations here'\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->parse-and-aggregate-fridge-data:\n    source_trigger: webhook\n    target_job: parse-and-aggregate-fridge-data\n    condition_type: always\n    enabled: true\n  parse-and-aggregate-fridge-data->upload-to-redis:\n    source_job: parse-and-aggregate-fridge-data\n    target_job: upload-to-redis\n    condition_type: on_job_success\n    enabled: true\n",
  "history": [
    {
      "role": "user",
      "content": "Whenever fridge statistics are send to you, parse and aggregate the data and upload to a collection in redis."
    },
    {
      "role": "assistant",
      "content": "I'll create a workflow that processes fridge statistics through a webhook trigger, then aggregates and stores the data in Redis.\n\n```\nname: fridge-statistics-processing\njobs:\n  parse-and-aggregate-fridge-data:\n    name: Parse and Aggregate Fridge Data\n    adaptor: \"@openfn/language-common@latest\"\n    body: \"| // Add data parsing and aggregation operations here\"\n  upload-to-redis:\n    name: Upload to Redis Collection\n    adaptor: \"@openfn/language-redis@latest\"\n    body: \"| // Add Redis collection upload operations here\"\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->parse-and-aggregate-fridge-data:\n    source_trigger: webhook\n    target_job: parse-and-aggregate-fridge-data\n    condition_type: always\n    enabled: true\n  parse-and-aggregate-fridge-data->upload-to-redis:\n    source_job: parse-and-aggregate-fridge-data\n    target_job: upload-to-redis\n    condition_type: on_job_success\n    enabled: true\n```"
    }
  ]
}
```

### Error input example

The service also takes an `errors` field, which triggers a modified prompt targeted at identifying and fixing an error. If there is any text in `errors`, the service will attempt to fix the YAML given in `existing_yaml`, or alternatively, the conversation history, given the error message in `errors`. It will return an answer whatever information is given, but it is best to give it the `existing_yaml` and conversation `history`.

See the `fix_yaml_error_system_prompt` in `gen_project_prompts.yaml` to see the exact instructions.

```json
{
  "existing_yaml": "name: fridge-statistics-processing\njobs:\n  parse-and-aggregate-fridge-data:\n    name: Parse and Aggregate Fridge Data\n    adaptor: '@openfn/language-commons@latest'\n    body: '| // Add data parsing and aggregation operations here'\n  upload-to-redis:\n    name: Upload to Redis Collection\n    adaptor: '@openfn/language-redis@latest'\n    body: '| // Add Redis collection upload operations here'\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->parse-and-aggregate-fridge-data:\n    source_trigger: webhook\n    target_job: parse-and-aggregate-fridge-data\n    condition_type: always\n    enabled: true\n  parse-and-aggregate-fridge-data->upload-to-redis:\n    source_job: parse-and-aggregate-fridge-data\n    target_job: upload-to-redis\n    condition_type: on_job_success\n    enabled: true\n",
  "errors": "adaptor error",
  "history": [
    {
      "role": "user",
      "content": "Whenever fridge statistics are send to you, parse and aggregate the data and upload to a collection in redis."
    },
    {
      "role": "assistant",
      "content": "I'll create a workflow that processes fridge statistics through a webhook trigger, then aggregates and stores the data in Redis.\n\n```\nname: fridge-statistics-processing\njobs:\n  parse-and-aggregate-fridge-data:\n    name: Parse and Aggregate Fridge Data\n    adaptor: \"@openfn/language-common@latest\"\n    body: \"| // Add data parsing and aggregation operations here\"\n  upload-to-redis:\n    name: Upload to Redis Collection\n    adaptor: \"@openfn/language-redis@latest\"\n    body: \"| // Add Redis collection upload operations here\"\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->parse-and-aggregate-fridge-data:\n    source_trigger: webhook\n    target_job: parse-and-aggregate-fridge-data\n    condition_type: always\n    enabled: true\n  parse-and-aggregate-fridge-data->upload-to-redis:\n    source_job: parse-and-aggregate-fridge-data\n    target_job: upload-to-redis\n    condition_type: on_job_success\n    enabled: true\n```"
    }
  ]
}
```

### Example Output

The serivce returns a JSON object which will have a `response`, `response_yaml`, `history`, and `usage` field. The `response_yaml` might be `None`.


```json
{'response': "This workflow will handle incoming fridge statistics via a webhook, process the data, and store it in Redis. I've chosen a webhook trigger since you're receiving data, and used the Redis adaptor for the final storage step.", 'response_yaml': "name: Fridge-Statistics-Processing\njobs:\n  parse-fridge-data:\n    name: Parse and Aggregate Fridge Data\n    adaptor: '@openfn/language-common@latest'\n    body: '| // Add data parsing and aggregation operations here'\n  upload-to-redis:\n    name: Upload to Redis Collection\n    adaptor: '@openfn/language-redis@latest'\n    body: '| // Add Redis collection storage operations here'\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->parse-fridge-data:\n    source_trigger: webhook\n    target_job: parse-fridge-data\n    condition_type: always\n    enabled: true\n  parse-fridge-data->upload-to-redis:\n    source_job: parse-fridge-data\n    target_job: upload-to-redis\n    condition_type: on_job_success\n    enabled: true\n", 'history': [{'role': 'user', 'content': 'Whenever fridge statistics are send to you, parse and aggregate the data and upload to a collection in redis.'}, {'role': 'assistant', 'content': 'This workflow will handle incoming fridge statistics via a webhook, process the data, and store it in Redis. I\'ve chosen a webhook trigger since you\'re receiving data, and used the Redis adaptor for the final storage step.\n\n```\nname: Fridge-Statistics-Processing\njobs:\n  parse-fridge-data:\n    name: Parse and Aggregate Fridge Data\n    adaptor: "@openfn/language-common@latest"\n    body: "| // Add data parsing and aggregation operations here"\n  upload-to-redis:\n    name: Upload to Redis Collection\n    adaptor: "@openfn/language-redis@latest"\n    body: "| // Add Redis collection storage operations here"\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->parse-fridge-data:\n    source_trigger: webhook\n    target_job: parse-fridge-data\n    condition_type: always\n    enabled: true\n  parse-fridge-data->upload-to-redis:\n    source_job: parse-fridge-data\n    target_job: upload-to-redis\n    condition_type: on_job_success\n    enabled: true\n```'}], 'usage': {'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'input_tokens': 3250, 'output_tokens': 281}}

```

### Error handling

See above for using the service to correct a YAML given an error message (Error input example).

Errors in the service output: The service could output invalid YAML or an invalid OpenFn workflow.yaml. If the model output JSON or YAML are invalid, the service will attempt to re-generate an answer (max once) before returning an answer. If the validation fails twice, it could return invalid YAML in the `yaml` output key. The tokens from the retry are summed before adding to the `usage` key.

Invalid adaptors: Currently we log a warning if there are invalid adaptor names in a valid YAML.