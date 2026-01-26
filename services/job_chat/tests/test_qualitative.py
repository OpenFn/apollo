import pytest
import json
from .test_utils import call_job_chat_service, make_service_input, print_response_details


def test_basic_input():
    print("==================TEST==================")
    print("Description: Basic input test. Check if the service can handle a simple input and generate a response.")
    history = []
    content = "Can you add error handling to this job that will log the error message and retry the operation once if the API call fails?"
    context = {
        "expression": '''// Get data from external API
get('https://api.example.com/data');

// Process and transform data
fn(state => {
  const transformed = state.data.map(item => ({
    id: item.id,
    name: item.full_name,
    status: item.active ? 'Active' : 'Inactive'
  }));
  
  return { ...state, transformed };
});

// Send transformed data to destination
post('https://destination.org/upload', state => state.transformed);''',
        "adaptor": "@openfn/language-gmail@2.0.2"
    }
    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta, suggest_code=True)
    response = call_job_chat_service(service_input)
    print_response_details(response, "basic_input", content=content)
    assert response is not None
    assert "response" in response
    assert "suggested_code" in response

def test_contextualised_input():
    print("==================TEST==================")
    print("Description: Check if the service can handle an input that includes info for all fields (history, context, meta).")
    
    history = [
        {"role": "user", "content": "I need to add error handling to my API integration job. What's the best approach?"},
        {"role": "assistant", "content": "There are several approaches to handling errors in API calls. You can use try/catch blocks, implement retry logic, or use built-in error handling functions. Could you share your current job code so I can provide specific recommendations?"}
    ]
    
    content = "Can you add error handling to this job that will log the error message and retry the operation once if the API call fails?"
    
    context = {
        "expression": '''// Get data from external API
get('https://api.example.com/data');

// Process and transform data
fn(state => {
  const transformed = state.data.map(item => ({
    id: item.id,
    name: item.full_name,
    status: item.active ? 'Active' : 'Inactive'
  }));
  
  return { ...state, transformed };
});

// Send transformed data to destination
post('https://destination.org/upload', state => state.transformed);''',
        "adaptors": ["@openfn/language-http", "@openfn/language-common"],
        "jobId": "job-abc123",
        "projectId": "project-xyz789",
        "adaptor": "@openfn/language-fhir-4@0.1.10"
    }
    
    meta = {
        "rag": {
            "search_results": [
                {
                    "title": "HTTP Adaptor Error Handling",
                    "url": "https://docs.openfn.org/adaptors/http#error-handling",
                    "content": "The HTTP adaptor provides mechanisms for handling connection errors and retrying failed requests. Use the maxRetries option to specify retry attempts."
                },
                {
                    "title": "Common Adaptor Documentation",
                    "url": "https://docs.openfn.org/adaptors/common#error-handling",
                    "content": "Error handling can be implemented using standard JavaScript try/catch blocks or with the withError helper function."
                }
            ],
            "search_queries": ["http adaptor error handling", "openfn retry logic"]
        }
    }
    
    service_input = make_service_input(history=history, content=content, context=context, meta=meta, suggest_code=True)
    response = call_job_chat_service(service_input)
    print_response_details(response, "contextualised_input", content=content)
    assert response is not None
    assert "response" in response
    assert "suggested_code" in response
    assert "meta" in response
    assert "usage" in response
    assert response["suggested_code"] is not None, "JSON parsing failed - suggested_code is None"
    assert response["suggested_code"] != context["expression"], "Suggested code should be different from the original code"

def test_duplicate_sections():
    print("==================TEST==================")
    print("Description: Test if the service can apply a change to code with duplicate sections.")
    history = []
    content = "In this job, I want to add a validation step only for the second line item creation, to check if the Barcode__c is not empty before creating the record. How can I do that?"
    context = {
        "expression": '''each(
  dataPath('data[*]'),
  combine(
    create(
      'transaction__c',
      fields(
        field('Transaction_Date__c', dataValue('today')),
        relationship(
          'Person_Responsible__r',
          'Staff_ID_Code__c',
          dataValue('person_code')
        ),
        field('metainstanceid__c', dataValue('*meta-instance-id*'))
      )
    ),
    each(
      merge(
        dataPath('line_items[*]'),
        fields(
          field('end', dataValue('time_end')),
          field('parentId', lastReferenceValue('id'))
        )
      ),
      create(
        'line_item__c',
        fields(
          field('transaction__c', dataValue('parentId')),
          field('Barcode__c', dataValue('product_barcode')),
          field('ODK_Form_Completed__c', dataValue('end'))
        )
      ),
      create(
        'line_item__c',
        fields(
          field('transaction__c', dataValue('parentId')),
          field('Barcode__c', dataValue('product_barcode')),
          field('ODK_Form_Completed__c', dataValue('end'))
        )
      ),
      create(
        'line_item__c',
        fields(
          field('transaction__c', dataValue('parentId')),
          field('Barcode__c', dataValue('product_barcode')),
          field('ODK_Form_Completed__c', dataValue('end'))
        )
      )
    )
  )
);''',
        "adaptor": "@openfn/language-dhis2@8.0.1"
    }
    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta, suggest_code=True)
    response = call_job_chat_service(service_input)
    print_response_details(response, "odk_duplicate_sections", content=content)
    assert response is not None
    assert "response" in response
    assert "suggested_code" in response
    assert response["suggested_code"] is not None, "JSON parsing failed - suggested_code is None"
    assert response["suggested_code"] != context["expression"], "Suggested code should be different from the original code"

def test_duplicate_sections_additional():
    print("==================TEST==================")
    print("Description: Another test to check if the service can handle duplicate sections, this time with more duplicates."
          "Check whether it's able to provide enough context for the match to be unique, and check it doesn't accidentally delete sections")
    history = []
    content = "I need to add error handling only to the third POST request to retry once if it fails."
    context = {
        "expression": '''// Process and prepare data
fn(state => {
  const items = state.data.items.map(item => ({
    id: item.id,
    name: item.name,
    status: 'pending'
  }));
  
  return { ...state, items };
});

post('https://api.example.com/endpoint', state => state.items);

post('https://api.example.com/endpoint', state => state.items);

post('https://api.example.com/endpoint', state => state.items);

post('https://api.example.com/endpoint', state => state.items);

post('https://api.example.com/endpoint', state => state.items);

post('https://api.example.com/endpoint', state => state.items);''',
        "adaptor": "@openfn/language-mailchimp@1.0.19"
    }
    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta, suggest_code=True)
    response = call_job_chat_service(service_input)
    print_response_details(response, "duplicate_post_sections", content=content)
    assert response is not None
    assert "response" in response
    assert "suggested_code" in response
    assert response["suggested_code"] is not None, "JSON parsing failed - suggested_code is None"
    assert response["suggested_code"] != context["expression"], "Suggested code should be different from the original code"


def test_navigation_workflow_to_job():
    print("==================TEST==================")
    print("Description: Testing cross-service navigation from workflow editor to job editor - model should infer context change")

    # History shows user was on workflow page discussing workflow structure
    history = [
        {"role": "user", "content": "[pg:workflow/patient-sync] Create a workflow to sync patient data from source to destination"},
        {"role": "assistant", "content": "I'll create a workflow with jobs to fetch patient data, transform it, and sync to the destination system."},
        {"role": "user", "content": "[pg:workflow/patient-sync] Add validation between fetch and transform"},
        {"role": "assistant", "content": "I'll add a validation job that checks the patient data before transformation."}
    ]

    # Now user is on job editor with a different page - abrupt question about current code
    content = "Add a log statement at the start"

    # Current context is job code, not workflow
    context = {
        "expression": '''fn(state => {
  const patients = state.data.map(patient => ({
    id: patient.patient_id,
    name: patient.full_name,
    dob: patient.date_of_birth
  }));

  return { ...state, patients };
});

post('https://destination.api/patients', state => state.patients);''',
        "adaptor": "@openfn/language-common@latest",
        "page_name": "map-patient-data"
    }

    # Meta shows navigation happened
    meta = {
        "last_page": {
            "type": "workflow",
            "name": "patient-sync"
        }
    }

    service_input = make_service_input(history=history, content=content, context=context, meta=meta, suggest_code=True)
    response = call_job_chat_service(service_input)
    print_response_details(response, "navigation_workflow_to_job", content=content)

    # Assertions to verify model correctly inferred navigation and responded about job code
    assert response is not None
    assert "response" in response
    assert "suggested_code" in response
    assert response["suggested_code"] is not None, "Model should have generated code for the job"

    # Verify logging was added to the code
    assert "console.log" in response["suggested_code"], "Log statement not found in suggested code"

    # Verify response talks about job code, not workflow
    response_text = response["response"].lower()
    assert not any(word in response_text for word in ["workflow", "yaml", "trigger", "edge"]), \
        "Response should be about job code, not workflow structure"

    print("\n✓ Navigation test passed: Model correctly inferred navigation from workflow to job editor")

def test_adaptor_context_switching():
    print("==================TEST==================")
    print("Description: Test that the model pays attention to page prefix changes and provides adaptor-specific answers")

    # Simulate a conversation history where:
    # 1. User was on a Salesforce job page and asked "How do I get data?"
    # 2. Assistant answered with Salesforce-specific guidance (query, SOQL, etc.)
    # 3. User has now navigated to a DHIS2 job page and asks the SAME question again
    # Expected: The model should recognize the context switch and mention DHIS2-specific functions

    history = [
        {"role": "user", "content": "[pg:job_code/fetch-records/salesforce@9.0.3] How do I get data?"},
        {"role": "assistant", "content": "To get data from Salesforce, you can use the `query()` operation with SOQL (Salesforce Object Query Language). For example:\n\n```js\nquery('SELECT Id, Name FROM Account WHERE Status = \"Active\"');\n```\n\nThis will fetch records from Salesforce and store them in `state.data`."}
    ]

    # Now user has navigated to a DHIS2 job page and asks the same question
    content = "How do I get data?"

    context = {
        "expression": '''
fn(state => {
  return state;
});''',
        "adaptor": "@openfn/language-dhis2@8.0.7",
        "page_name": "fetch-data"
    }

    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta, suggest_code=False)
    response = call_job_chat_service(service_input)
    print_response_details(response, "adaptor_context_switching", content=content)

    assert response is not None
    assert "response" in response

    response_text = response["response"].lower()
    print(f"\n=== RESPONSE (DHIS2 Context) ===")
    print(response["response"])

    # Check that DHIS2-specific functions are mentioned
    dhis2_mentioned = "dhis" in response_text
    assert dhis2_mentioned, f"Expected DHIS2 to be mentioned in response when on DHIS2 page. Response: {response['response']}"

    # Check the history was properly prefixed with the new page context
    assert "history" in response
    updated_history = response["history"]
    assert len(updated_history) == 4  # 2 previous turns + 1 new turn = 4 messages

    # Verify the latest user message has the correct DHIS2 prefix (with version)
    latest_user_message = updated_history[2]
    assert latest_user_message["role"] == "user"
    assert "[pg:job_code/fetch-data/dhis2@8.0.7]" in latest_user_message["content"], "Expected DHIS2 page prefix with version in latest user message"

    print(f"\n=== CONTEXT SWITCH VERIFICATION ===")
    print(f"Previous context: Salesforce (from history)")
    print(f"Current context: DHIS2 (from page prefix)")
    print(f"DHIS2 mentioned in response: {dhis2_mentioned}")
    print(f"Latest user message prefix: [pg:job_code/fetch-data/dhis2]")

    print("\n✓ Adaptor context switching test passed: Model recognizes page prefix change and provides DHIS2-specific guidance")