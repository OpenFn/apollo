---
id: global-chat.job-code.long-history-workflow-then-code-change
service: global_chat
judges: [general, openfn_code_quality]
---

# notes

The conversation has touched several different parts of the workflow — earlier turns are about workflow structure (adding steps, fixing edges, asking about the cron trigger) and one turn was about a different step's code. Now the user is on a specific job step page and asks for a concrete code change to THAT step (the geocoding step). The router should send this to job_code_agent. The test verifies the model is not distracted by the earlier workflow-level discussion or by the different step the user previously asked about — the change must land on the geocode-facilities step only.

# quality_criteria

- The response updates the geocode-facilities step to call the geocoding API in batches (chunks of 25 facility addresses per call) rather than one per facility, as the user requested.
- The change is applied only to the geocode-facilities job body — the other jobs (fetch-facilities-from-erpnext, deduplicate-facility-records, write-facilities-to-supabase) are not modified.
- The response does NOT instead modify deduplicate-facility-records, which was discussed earlier in the conversation, and does NOT change the workflow structure (no edges/triggers/job-name changes).

# settings

## page

workflows/erpnext-facility-geo-supabase/geocode-facilities

## workflow_yaml

```yaml
name: erpnext-facility-geo-supabase
jobs:
  fetch-facilities-from-erpnext:
    id: job-fetch-erp-id
    name: Fetch Facilities from ERPNext
    adaptor: "@openfn/language-http@6.5.4"
    body: |
      get('https://erp.example.org/api/resource/Facility', {
        query: { limit_page_length: 500, fields: '["name","address","city","country","status"]' }
      });
      fn(state => {
        const facilities = state.data.data || [];
        return { ...state, facilities };
      });
  deduplicate-facility-records:
    id: job-dedupe-id
    name: Deduplicate Facility Records
    adaptor: "@openfn/language-common@2.3.0"
    body: |
      fn(state => {
        const seen = new Set();
        const unique = [];
        for (const f of state.facilities) {
          const key = `${f.name}|${f.city}|${f.country}`.toLowerCase();
          if (seen.has(key)) continue;
          seen.add(key);
          unique.push(f);
        }
        return { ...state, facilities: unique };
      });
  geocode-facilities:
    id: job-geocode-id
    name: Geocode Facilities
    adaptor: "@openfn/language-http@6.5.4"
    body: |
      each(
        $.facilities,
        post('https://api.geocoder.example/v1/geocode', state => ({
          address: `${state.data.address}, ${state.data.city}, ${state.data.country}`
        }))
      );
      fn(state => {
        const geocoded = state.facilities.map((f, i) => ({
          ...f,
          lat: state.references[i]?.results?.[0]?.lat,
          lng: state.references[i]?.results?.[0]?.lng
        }));
        return { ...state, facilities: geocoded };
      });
  write-facilities-to-supabase:
    id: job-write-supabase-id
    name: Write Facilities to Supabase
    adaptor: "@openfn/language-postgresql@6.5.1"
    body: |
      each(
        $.facilities,
        upsert('facilities', 'name', state => ({
          name: state.data.name,
          city: state.data.city,
          country: state.data.country,
          lat: state.data.lat,
          lng: state.data.lng,
          status: state.data.status
        }))
      );
triggers:
  cron:
    id: trigger-cron-id
    type: cron
    cron_expression: "0 3 * * 1"
    enabled: true
edges:
  cron->fetch-facilities-from-erpnext:
    id: edge-cron-fetch
    source_trigger: cron
    target_job: fetch-facilities-from-erpnext
    condition_type: always
    enabled: true
  fetch-facilities-from-erpnext->deduplicate-facility-records:
    id: edge-fetch-dedupe
    source_job: fetch-facilities-from-erpnext
    target_job: deduplicate-facility-records
    condition_type: on_job_success
    enabled: true
  deduplicate-facility-records->geocode-facilities:
    id: edge-dedupe-geocode
    source_job: deduplicate-facility-records
    target_job: geocode-facilities
    condition_type: on_job_success
    enabled: true
  geocode-facilities->write-facilities-to-supabase:
    id: edge-geocode-write
    source_job: geocode-facilities
    target_job: write-facilities-to-supabase
    condition_type: on_job_success
    enabled: true
```

## meta.session_id

sess-job-code-long-history-workflow-then-code-0008

# history

## turn

### role

user

### content

[pg:workflows/erpnext-facility-geo-supabase] I have a workflow that pulls facility records from ERPNext and writes them to Supabase. I want to add deduplication and geocoding between fetch and write.

## turn

### role

assistant

### content

Got it — I'll add a Deduplicate Facility Records step right after Fetch Facilities from ERPNext, and a Geocode Facilities step before the Supabase write. Edges will be on_job_success in sequence.

## turn

### role

user

### content

[pg:workflows/erpnext-facility-geo-supabase] How often should this run? We refresh ERPNext nightly but geocoding has rate limits.

## turn

### role

assistant

### content

Weekly is a reasonable starting point given geocoding rate limits — I've set the cron trigger to run at 03:00 every Monday. You can raise the frequency later once we batch the geocoding calls.

## turn

### role

user

### content

[pg:workflows/erpnext-facility-geo-supabase/deduplicate-facility-records] Looking at deduplicate-facility-records — what is the composite key it builds doing exactly?

## turn

### role

assistant

### content

It lowercases and joins `name`, `city`, and `country` with `|` characters, then keeps only the first occurrence of each composite. So two facilities with the same name in the same city of the same country are treated as duplicates, even if their casing differs.

## turn

### role

user

### content

[pg:workflows/erpnext-facility-geo-supabase] Got it. Can you also make sure the workflow only runs on success — I don't want geocoding firing if dedupe failed.

## turn

### role

assistant

### content

Already in place — every downstream edge uses `on_job_success`, so dedupe failing will stop the run before geocoding.

# turn

## role

user

## content

OK now I'm looking at the geocoding step itself. The geocoder API supports batch requests of up to 25 addresses per call. Change this step to call the API in batches of 25 facility addresses at a time instead of one request per facility — it should be much faster.
