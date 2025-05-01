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

```json
{
  "content": "Whenever fridge statistics are send to you, parse and aggregate the data and upload to a collection in redis.",
  "history": []
}

```

### Example Output

The serivce returns a JSON object which will have a `response`, `response_yaml`, `history`, and `usage` field. The `response_yaml` might be `None`.


```json
{'response': "This workflow will handle incoming fridge statistics via a webhook, process the data, and store it in Redis. I've chosen a webhook trigger since you're receiving data, and used the Redis adaptor for the final storage step.", 'response_yaml': "name: Fridge-Statistics-Processing\njobs:\n  parse-fridge-data:\n    name: Parse and Aggregate Fridge Data\n    adaptor: '@openfn/language-common@latest'\n    body: '| // Add data parsing and aggregation operations here'\n  upload-to-redis:\n    name: Upload to Redis Collection\n    adaptor: '@openfn/language-redis@latest'\n    body: '| // Add Redis collection storage operations here'\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->parse-fridge-data:\n    source_trigger: webhook\n    target_job: parse-fridge-data\n    condition_type: always\n    enabled: true\n  parse-fridge-data->upload-to-redis:\n    source_job: parse-fridge-data\n    target_job: upload-to-redis\n    condition_type: on_job_success\n    enabled: true\n", 'history': [{'role': 'user', 'content': 'Whenever fridge statistics are send to you, parse and aggregate the data and upload to a collection in redis.'}, {'role': 'assistant', 'content': 'This workflow will handle incoming fridge statistics via a webhook, process the data, and store it in Redis. I\'ve chosen a webhook trigger since you\'re receiving data, and used the Redis adaptor for the final storage step.\n\n```\nname: Fridge-Statistics-Processing\njobs:\n  parse-fridge-data:\n    name: Parse and Aggregate Fridge Data\n    adaptor: "@openfn/language-common@latest"\n    body: "| // Add data parsing and aggregation operations here"\n  upload-to-redis:\n    name: Upload to Redis Collection\n    adaptor: "@openfn/language-redis@latest"\n    body: "| // Add Redis collection storage operations here"\ntriggers:\n  webhook:\n    type: webhook\n    enabled: false\nedges:\n  webhook->parse-fridge-data:\n    source_trigger: webhook\n    target_job: parse-fridge-data\n    condition_type: always\n    enabled: true\n  parse-fridge-data->upload-to-redis:\n    source_job: parse-fridge-data\n    target_job: upload-to-redis\n    condition_type: on_job_success\n    enabled: true\n```'}], 'usage': {'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'input_tokens': 3250, 'output_tokens': 281}}

```