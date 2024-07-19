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

### Example Output

```yaml:-
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
