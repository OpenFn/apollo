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
post('https://destination.org/upload', state => state.transformed);'''
    }
    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta, use_new_prompt=False)
    response = call_job_chat_service(service_input)
    print_response_details(response, "basic_input", content=content)
    assert response is not None
    assert "response" in response

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
        "projectId": "project-xyz789"
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
    
    service_input = make_service_input(history=history, content=content, context=context, meta=meta, use_new_prompt=False)
    response = call_job_chat_service(service_input)
    print_response_details(response, "contextualised_input", content=content)
    assert response is not None
    assert "response" in response
    assert "meta" in response
    assert "usage" in response

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
);'''
    }
    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta, use_new_prompt=False)
    response = call_job_chat_service(service_input)
    print_response_details(response, "odk_duplicate_sections", content=content)
    assert response is not None
    assert "response" in response

def test_duplicate_sections_additional():
    print("==================TEST==================")
    print("Description: Another test to check if the service can handle duplicate sections, this time with more duplicates."
          "Check whether it's able to provide enough context for the match to be unique, and check it doesn't accidentally delete")
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

post('https://api.example.com/endpoint', state => state.items);'''
    }
    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta, use_new_prompt=False)
    response = call_job_chat_service(service_input)
    print_response_details(response, "duplicate_post_sections", content=content)
    assert response is not None
    assert "response" in response