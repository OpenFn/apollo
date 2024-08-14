# gen_project Service

This service generates a workflow definition based on provided steps and outputs the result in either JSON or YAML format.

## Usage

Send a POST request to `/services/gen_project` with a JSON body containing the workflow steps and the desired output format.

### CLI Call
  
  ```bash
   poetry run python services/entry.py gen_project tmp/input.json tmp/output.json
  ```

- make sure to replace `tmp/input.json` with the path to the input file and `tmp/output.json` with the path to the output file, or you can create tmp directory in the root of the project and run the command as is.

### Example Input

```json
{
  "steps": [
    "Get Data from DHIS2",
    "Filter out children under 2",
    "Aggregate the data",
    "Make a comment on Asana"
  ],
  "format": "yaml"
}

```

### Example of Output

```json:-
{"files": {"project.yaml": "workflow-1:\n  name: Generated Workflow\n  jobs:\n    Get-Data-Dhis2:\n      name: Get Data from DHIS2\n      adaptor: '@openfn/language-dhis2@latest'\n      body: '| // Add operations here'\n    Filter-Out-Children-Under-2:\n      name: Filter out children under 2\n      adaptor: '@openfn/language-common@latest'\n      body: '| // Add operations here'\n    Aggregate-Data:\n      name: Aggregate the data\n      adaptor: '@openfn/language-common@latest'\n      body: '| // Add operations here'\n    Make-Comment-On-Asana:\n      name: Make a comment on Asana\n      adaptor: '@openfn/language-asana@latest'\n      body: '| // Add operations here'\n  triggers:\n    webhook:\n      type: webhook\n      enabled: true\n  edges:\n  - webhook->Get-Data-Dhis2:\n      source_trigger: webhook\n      target_job: Get-Data-Dhis2\n      condition_type: always\n      enabled: true\n  - Get-Data-Dhis2->Filter-Out-Children-Under-2:\n      source_job: Get-Data-Dhis2\n      target_job: Filter-Out-Children-Under-2\n      condition_type: on_job_success\n      enabled: true\n  - Filter-Out-Children-Under-2->Aggregate-Data:\n      source_job: Filter-Out-Children-Under-2\n      target_job: Aggregate-Data\n      condition_type: on_job_success\n      enabled: true\n  - Aggregate-Data->Make-Comment-On-Asana:\n      source_job: Aggregate-Data\n      target_job: Make-Comment-On-Asana\n      condition_type: on_job_success\n      enabled: true\n"}}
```

> The output is a JSON object with a key `files` that contains the generated workflow definition in YAML/JSON format.

- For project to be imported in OpenFn Lightning, the file should be according to protability version v5 [here](https://docs.openfn.org/documentation/deploy/portability#the-project-spec) format.
- so for that we need to convert the above output to v5 format.

### Linting the output

```bash
python services/gen_project/lint_output.py tmp/output.json tmp/project.yaml
```

### Example of Output in v5 format

```yaml:-
name: Generated Project
description: Auto-generated workflow based on provided steps.
workflows:
  Workflow-1:
    name: Simple workflow
    jobs:
      Get-data-from-DHIS2:
        name: Get data from DHIS2
        adaptor: '@openfn/language-dhis2@latest'
        # credential:
        # globals:
        body: |

      Filter-out-children-under-2:
        name: Filter out children under 2
        adaptor: '@openfn/language-common@latest'
        # credential:
        # globals:
        body: |

      Aggregate-data-based-on-gender:
        name: Aggregate data based on gender
        adaptor: '@openfn/language-common@latest'
        # credential:
        # globals:
        body: |
    
      make-a-comment-on-Asana:
        name: make a comment on Asana
        adaptor: '@openfn/language-asana@latest'
        # credential:
        # globals:
        body: |
     
    triggers:
      webhook:
        type: webhook
        enabled: true
    edges:
      webhook->Get-data-from-DHIS2:
        source_trigger: webhook
        target_job: Get-data-from-DHIS2
        condition_type: always
        enabled: true
      Get-data-from-DHIS2->Filter-out-children-under-2:
        source_job: Get-data-from-DHIS2
        target_job: Filter-out-children-under-2
        condition_type: on_job_success
        enabled: true
      Filter-out-children-under-2->Aggregate-data-based-on-gender:
        source_job: Filter-out-children-under-2
        target_job: Aggregate-data-based-on-gender
        condition_type: on_job_success
        enabled: true
      Aggregate-data-based-on-gender->make-a-comment-on-Asana:
        source_job: Aggregate-data-based-on-gender
        target_job: make-a-comment-on-Asana
        condition_type: on_job_success
        enabled: true
```
