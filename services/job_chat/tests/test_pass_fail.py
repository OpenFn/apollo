import pytest
import json
from .test_utils import call_job_chat_service, make_service_input, print_response_details


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

post('https://destination.org/upload', state => state.transformed);'''
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
    service_input = make_service_input(history=history, content=content, context=context, meta=meta)
    response = call_job_chat_service(service_input)
    print_response_details(response, "rename_variable", content=content)
    
    assert response is not None
    assert "response" in response
    assert "suggested_code" in response
    
    assert response["suggested_code"] == expected_code, f"Variable rename did not produce expected result.\nExpected:\n{expected_code}\n\nActual:\n{response['suggested_code']}"


def test_convert_get_to_post():
    print("==================TEST==================")
    print("Description: Testing conversion of GET to POST request")
    
    history = []
    content = "Change the GET request to a POST request"
    
    context = {
        "expression": '''
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
    }
    
    expected_code = '''
post('https://api.example.com/users/profile', {});

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

    expected_code_alternative = '''
post('https://api.example.com/users/profile');

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
    
    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta)
    response = call_job_chat_service(service_input)
    print_response_details(response, "convert_get_to_post", content=content)
    
    assert response is not None
    assert "response" in response
    assert "suggested_code" in response
    
    assert response["suggested_code"] == expected_code, f"GET to POST conversion did not produce expected result.\nExpected:\n{expected_code}\n\nActual:\n{response['suggested_code']}"

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
);'''
    }
    
    expected_code = '''// Custom helper functions
function fetchPatientRecords(patientId) {
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
  get(state => fetchPatientRecords(state.data.id)),
  fn(state => {
    const patient = state.data;
    // Enrich patient data
    patient.lastUpdated = formatDate(new Date());
    patient.dataSource = 'API';
    patient.endpoint = fetchPatientRecords(patient.id);
    
    return { ...state, patient };
  })
);

// Process the results
fn(state => {
  const patients = state.references.map(ref => ref.patient);
  console.log(`Retrieved data for ${patients.length} patients`);
  
  const summary = {
    count: patients.length,
    source: fetchPatientRecords('summary'),
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
        source: fetchPatientRecords(state.data.id),
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
    endpoint: fetchPatientRecords('summary')
  })
);'''
    
    meta = {}
    service_input = make_service_input(history=history, content=content, context=context, meta=meta)
    response = call_job_chat_service(service_input)
    print_response_details(response, "rename_function", content=content)
    
    assert response is not None
    assert "response" in response
    assert "suggested_code" in response
    
    assert response["suggested_code"] == expected_code, f"Function rename did not produce expected result.\nExpected:\n{expected_code}\n\nActual:\n{response['suggested_code']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])