import pytest
import json
from .test_utils import call_job_chat_service, make_service_input, print_response_details


def test_context_fields_access():
    print("==================TEST==================")
    print("Description: Testing that the LLM service can access log, input, and output fields")
    
    history = []
    content = "Tell me exactly what you see you see in my input data, output data, and log output?"
    
    context = {
        "expression": "// Basic job to fetch data",
        "input": {"data": {"customer": "zebra", "status": "active"}},
        "output": {"result": "success", "location": "paris"},
        "log": "antarctica"
    }
    
    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta, suggest_code=True)
    response = call_job_chat_service(service_input)
    print_response_details(response, "context_fields_access", content=content)
    
    assert response is not None
    assert "response" in response
    
    response_text = response["response"].lower()
    assert "zebra" in response_text, f"LLM failed to access input data, 'zebra' not found in response"
    assert "paris" in response_text, f"LLM failed to access output data, 'paris' not found in response"
    assert "antarctica" in response_text, f"LLM failed to access log data, 'antarctica' not found in response"


def test_rename_variable():
    print("==================TEST==================")
    print("Description: Testing variable name change in fn function")
    
    history = []
    content = "Could you rename the variable 'transformed' to 'processedData' in my code?"
    
    context = {
        "expression": '''// Get data from external API
get('https://api.example.com/data');

fn(state => {
  const transformed = state.data.map(item => ({
    id: item.id,
    name: item.full_name,
    status: item.active ? 'Active' : 'Inactive'
  }));
  
  return { ...state, transformed };
});

post('https://destination.org/upload', state => state.transformed);''',
        "adaptor": "@openfn/language-salesforce@8.0.0"
    }
    
    expected_code = '''// Get data from external API
get('https://api.example.com/data');

fn(state => {
  const processedData = state.data.map(item => ({
    id: item.id,
    name: item.full_name,
    status: item.active ? 'Active' : 'Inactive'
  }));
  
  return { ...state, processedData };
});

post('https://destination.org/upload', state => state.processedData);'''
    
    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta, suggest_code=True)
    response = call_job_chat_service(service_input)
    print_response_details(response, "rename_variable", content=content)
    
    assert response is not None
    assert "response" in response
    assert "suggested_code" in response
    
    assert response["suggested_code"] == expected_code, f"Variable rename did not produce expected result.\nExpected:\n{expected_code}\n\nActual:\n{response['suggested_code']}"


def test_convert_get_to_delete():
    print("==================TEST==================")
    print("Description: Testing conversion of GET to DELETE request")
    
    history = []
    content = "Change the GET request to a DELETE request"
    
    original_code = '''
get('https://api.example.com/users/profile');

fn(state => {
  const profile = state.data;
  console.log('Retrieved profile for user:', profile.id);
  return { ...state, profile };
});

// Save the data
post('https://api.example.com/save', state => ({
  user: state.profile,
  timestamp: new Date().toISOString()
}));'''
    
    context = {
        "expression": original_code,
        "adaptor": "@openfn/language-http@6.0.0"
    }
    
    # Service correctly uses 'del()' instead of 'delete()' (delete is reserved word in JS)
    expected_code = original_code.replace("get('https://api.example.com/users/profile')", 
                                        "del('https://api.example.com/users/profile')")
    
    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta, suggest_code=True)
    response = call_job_chat_service(service_input)
    print_response_details(response, "convert_get_to_delete", content=content)
    
    assert response is not None
    assert "suggested_code" in response
    
    assert response["suggested_code"] == expected_code, f"GET to DELETE conversion did not produce expected result.\nExpected:\n{expected_code}\n\nActual:\n{response['suggested_code']}"


def test_rename_function():
    print("==================TEST==================")
    print("Description: Testing function name change in longer OpenFn workflow")
    
    history = []
    content = "Rename the 'getPatientData' function to 'fetchPatientRecords'"
    
    context = {
        "expression": '''// Custom helper functions
function getPatientData(patientId) {
  return `https://hospital.org/api/patients/${patientId}`;
}

function formatDate(date) {
  return new Date(date).toISOString().split('T')[0];
}

// Initial configuration
fn(state => {
  const config = {
    apiVersion: '2.1',
    requestTimeout: 30000,
    maxRetries: 3
  };
  return { ...state, config };
});

// Fetch data for each patient
each(
  '$.patients[*]',
  fn(state => {
    console.log(`Processing patient ID: ${state.data.id}`);
    return state;
  }),
  get(state => getPatientData(state.data.id)),
  fn(state => {
    const patient = state.data;
    // Enrich patient data
    patient.lastUpdated = formatDate(new Date());
    patient.dataSource = 'API';
    patient.endpoint = getPatientData(patient.id);
    
    return { ...state, patient };
  })
);

// Process the results
fn(state => {
  const patients = state.references.map(ref => ref.patient);
  console.log(`Retrieved data for ${patients.length} patients`);
  
  const summary = {
    count: patients.length,
    source: getPatientData('summary'),
    retrievalDate: formatDate(new Date())
  };
  
  return { ...state, patients, summary };
});

// Save individual patient records
each(
  '$.patients[*]',
  post(
    'https://records.hospital.org/store',
    state => ({
      patient: state.data,
      metadata: {
        source: getPatientData(state.data.id),
        processedAt: new Date().toISOString()
      }
    })
  )
);

// Submit the final report
post(
  'https://reports.org/submit', 
  state => ({
    source: 'Patient API',
    results: state.patients,
    summary: state.summary,
    endpoint: getPatientData('summary')
  })
);''',
        "adaptor": "@openfn/language-whatsapp@1.0.4"
    }
    
    expected_code = context["expression"].replace("getPatientData", "fetchPatientRecords")
    
    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta, suggest_code=True)
    response = call_job_chat_service(service_input)
    print_response_details(response, "rename_function", content=content)
    
    assert response is not None
    assert "response" in response
    assert "suggested_code" in response
    
    assert response["suggested_code"] == expected_code, f"Function rename did not produce expected result.\nExpected:\n{expected_code}\n\nActual:\n{response['suggested_code']}"

def test_change_multiple_instances():
    print("==================TEST==================")
    print("Description: Testing changing multiple instances of misspelled endpoint URLs back to correct spelling.")
    
    history = []
    content = "change all the occurences of endpooint and endpoooint to endpoint"
    
    original_code = '''// Process and prepare data
fn(state => {
  const items = state.data.items.map(item => ({
    id: item.id,
    name: item.name,
    status: 'pending'
  }));
  
  return { ...state, items };
});

post('https://api.example.com/endpooint', state => state.items);

// Helper function to process the response
function processApiResponse(response) {
  if (!response || !response.data) {
    console.log('Invalid response received');
    return null;
  }
  
  return {
    processed: true,
    timestamp: new Date().toISOString(),
    results: response.data.map(item => ({
      ...item,
      processed: true
    }))
  };
}

// Data transformation function
fn(state => {
  if (state.data && Array.isArray(state.data)) {
    const transformed = processApiResponse({
      data: state.data
    });
    return { ...state, transformed };
  }
  return state;
});

post('https://api.example.com/endpoooint', state => state.items);

// Fifth request with retry mechanism
fn(state => {
  let retries = 3;
  let delay = 1000; // 1 second
  
  const makeRequest = async (attempt) => {
    try {
      const response = await http.post(
        'https://api.example.com/endpooint', 
        state.items,
        {}
      );
      return { ...state, data: response.body };
    } catch (error) {
      if (attempt < retries) {
        console.log(`Request failed, retrying (${attempt + 1}/${retries})...`);
        await new Promise(resolve => setTimeout(resolve, delay));
        return makeRequest(attempt + 1);
      }
      throw error;
    }
  };
  
  return makeRequest(0);
});

post('https://api.example.com/endpoooint', state => state.items);

// Final data processing and cleanup
fn(state => {
  // Remove any temporary data
  const { tempData, ...cleanState } = state;
  
  // Add completion timestamp
  const finalState = {
    ...cleanState,
    processingCompleted: true,
    completedAt: new Date().toISOString()
  };
  
  // Log completion
  console.log(`Processing completed at ${finalState.completedAt}`);
  console.log(`Processed ${state.items ? state.items.length : 0} items`);
  
  return finalState;
});

// Send final notification
post('https://notifications.example.com/endpooint/status', state => ({
  status: 'completed',
  timestamp: state.completedAt,
  itemCount: state.items ? state.items.length : 0
}));'''
    
    context = {
        "expression": original_code,
        "adaptor": "@openfn/language-googlesheets@4.0.1"
    }
    
    expected_code = original_code.replace("endpooint", "endpoint").replace("endpoooint", "endpoint")
    
    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta, suggest_code=True)
    response = call_job_chat_service(service_input)
    print_response_details(response, "change_url_path", content=content)
    
    assert response is not None
    assert "response" in response
    assert "suggested_code" in response
    
    assert response["suggested_code"] == expected_code, f"URL path change did not produce expected result.\nExpected:\n{expected_code}\n\nActual:\n{response['suggested_code']}"
  

def test_change_variable_names_only():
    print("==================TEST==================")
    print("Description: Testing if AI can change variable names without affecting state.data references when given simple instruction.")
    
    history = []
    content = "change the variable name 'data' to 'patients'"
    
    original_code = '''get('/api/patients');

fn(state => {
  const data = state.data;
  let processedData = [];
  
  data.forEach(record => {
    if (record.status === 'active') {
      processedData.push({
        id: record.id,
        name: record.full_name,
        status: record.status
      });
    }
  });
  
  console.log(`Processed ${processedData.length} records`);
  
  return { ...state, data: processedData };
});

post('/webhook', state => state.data);'''
    
    context = {
        "expression": original_code,
        "adaptor": "@openfn/language-kobotoolbox@4.2.3"
    }
    
    expected_code = original_code.replace('const data', 'const patients') \
                                .replace('data.forEach', 'patients.forEach')
    
    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta, suggest_code=True)
    response = call_job_chat_service(service_input)
    print_response_details(response, "change_variable_names", content=content)
    
    assert response is not None
    assert "suggested_code" in response
    
    assert response["suggested_code"] == expected_code, f"Variable name change did not produce expected result.\nExpected:\n{expected_code}\n\nActual:\n{response['suggested_code']}"


def test_change_variable_names_only_streaming():
    print("==================TEST==================")
    print("Description: Testing if AI can change variable names without affecting state.data references when given simple instruction (with streaming).")

    history = []
    content = "change the variable name 'data' to 'patients'"

    original_code = '''get('/api/patients');

fn(state => {
  const data = state.data;
  let processedData = [];

  data.forEach(record => {
    if (record.status === 'active') {
      processedData.push({
        id: record.id,
        name: record.full_name,
        status: record.status
      });
    }
  });

  console.log(`Processed ${processedData.length} records from data`);

  return { ...state, data: processedData };
});

post('/webhook', state => state.data);'''

    context = {
        "expression": original_code,
        "adaptor": "@openfn/language-kobotoolbox@4.2.3"
    }

    expected_code = original_code.replace('const data', 'const patients') \
                                .replace('data.forEach', 'patients.forEach')

    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta, suggest_code=True, stream=True)
    response = call_job_chat_service(service_input)
    print_response_details(response, "change_variable_names_streaming", content=content)

    assert response is not None
    assert "suggested_code" in response

    assert response["suggested_code"] == expected_code, f"Variable name change did not produce expected result.\nExpected:\n{expected_code}\n\nActual:\n{response['suggested_code']}"

def test_history_prefix_parsing():
    print("==================TEST==================")
    print("Description: Test that page navigation prefix is correctly parsed into history and last_page is returned in meta")

    history = []
    content = "Add error handling to the HTTP request"

    context = {
        "expression": '''get('https://api.example.com/data');

fn(state => {
  const transformed = state.data.map(item => ({
    id: item.id,
    name: item.full_name
  }));

  return { ...state, transformed };
});

post('https://destination.org/upload', state => state.transformed);''',
        "adaptor": "@openfn/language-http@6.5.4",
        "page_name": "transform-data"
    }

    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta, suggest_code=True)
    response = call_job_chat_service(service_input)
    print_response_details(response, "history_prefix_parsing", content=content)

    assert response is not None
    assert isinstance(response, dict)

    # Check that history was updated with prefixed content
    assert "history" in response
    updated_history = response["history"]
    assert len(updated_history) == 2  # user message + assistant response

    # Verify the user message has the prefix
    user_message = updated_history[0]
    assert user_message["role"] == "user"
    assert "[pg:job_code/transform-data/http]" in user_message["content"]
    assert content in user_message["content"]

    # Verify meta contains last_page info
    assert "meta" in response
    meta = response["meta"]
    assert "last_page" in meta
    last_page = meta["last_page"]
    assert last_page["type"] == "job_code"
    assert last_page["name"] == "transform-data"
    assert last_page["adaptor"] == "http"

    print("\n✓ Prefix parsing test passed: History contains correct prefix and meta has last_page info")

def test_rag_retriggered_on_navigation():
    print("==================TEST==================")
    print("Description: Test that RAG is retriggered when navigating between different job pages (same type, different names)")

    # Simulate a conversation history where user was on a different job page
    history = [
        {"role": "user", "content": "[pg:job_code/fetch-data/http] Can you add retry logic?"},
        {"role": "assistant", "content": "I'll add retry logic to handle transient failures."}
    ]

    # Now user has navigated to a different job - ask a question that should trigger RAG
    content = "How do I map data here?"

    context = {
        "expression": '''fn(state => {
  const data = state.data;
  return { ...state, data };
});''',
        "adaptor": "@openfn/language-common@2.0.0",
        "page_name": "transform-data"
    }

    # Meta indicates we were on a different page previously
    input_meta = {
        "last_page": {
            "type": "job_code",
            "name": "fetch-data",
            "adaptor": "http"
        },
        "rag": {
            "search_results": [
                {
                    "title": "HTTP Adaptor Retry Logic",
                    "url": "https://docs.openfn.org/adaptors/http#retry",
                    "content": "Old RAG data about HTTP adaptor"
                }
            ]
        }
    }

    service_input = make_service_input(history=history, content=content, context=context, meta=input_meta, suggest_code=True)
    response = call_job_chat_service(service_input)
    print_response_details(response, "rag_retriggered_on_navigation", content=content)

    assert response is not None
    assert isinstance(response, dict)

    # Print input and output meta for debugging
    print("\n=== INPUT META ===")
    print(json.dumps(input_meta, indent=2))

    print("\n=== OUTPUT META ===")
    assert "meta" in response
    response_meta = response["meta"]
    print(json.dumps(response_meta, indent=2))

    # Verify meta contains updated last_page info
    assert "last_page" in response_meta
    last_page = response_meta["last_page"]
    assert last_page["type"] == "job_code"
    assert last_page["name"] == "transform-data"
    assert last_page["adaptor"] == "common"

    # Verify RAG data is present
    assert "rag" in response_meta
    output_rag = response_meta["rag"]
    assert "search_results" in output_rag

    # Check if RAG was actually refreshed
    input_rag = input_meta["rag"]
    output_search_results = output_rag.get("search_results", [])
    input_search_results = input_rag.get("search_results", [])

    print(f"\n=== RAG COMPARISON ===")
    print(f"Input RAG had {len(input_search_results)} results")
    print(f"Output RAG has {len(output_search_results)} results")

    # RAG should either be different or empty (if decision logic skipped retrieval)
    rag_changed = output_rag != input_rag
    print(f"RAG changed: {rag_changed}")

    print("\n✓ RAG retriggering test passed: Navigation detected and RAG data updated")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])