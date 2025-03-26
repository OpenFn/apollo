
needs_docs_system_prompt = """
You are an assistant for a solutions engineer helping a user write a job for our platform.
Our platform is OpenFn (Open Function Group), the world's leading digital public good for workflow automation.
Your job is to decide whether the user question requires consulting our documentation. If the question is
about general coding advice or other external information, we do not need to consult the documentation. 

Answer nothing but True or False.
"""

needs_docs_user_prompt = """{user_context}The user question is as follows: "{user_question}" """

search_docs_system_prompt = """
You are an assistant for a solutions engineer helping a user write a job for our platform.
Our platform is Open Function, a platform for workflow automation.
Your job is to run search queries on the documentation based on the user's question.  

Your answer should detail the searches that should be done on the documentation.
Stick to one search query only per topic. If the user question requires information across
distinct topics (e.g. two different adaptors; CLI and API instructions), then list additional queries.

A search consists of a query string, and an optional filter for doc_type. 
This can be either adaptor_docs or general_docs.
If the filter is adaptor_documentation, then the query should be just the name of the adaptor.

Return a JSON array of search queries:
[
  {"query": "your_query", "doc_type": null},
  {"query": "optional_second_query", "doc_type": "adaptor_docs"}
]

Return NOTHING but this JSON array.
"""

search_docs_user_prompt = """{user_context}The user question is as follows: "{user_question}" """

def retrieve_knowledge(user_question, top_k, threshold, adaptor=None):
    user_context = format_context(adaptor)
    docs_decision = needs_docs(user_question, user_context)

    search_results = []
    search_queries = []
    if docs_decision.lower().startswith("true"):
        search_queries = generate_queries(user_question, user_context="")
        search_results = search_docs(search_queries)
    
    results = {"search_results": search_results, "search_queries": search_queries}
    
    return results

def needs_docs(user_question, user_context=""):
    message = client.messages.create(
        model="claude-3-5-sonnet-20241022", # TODO change to cheaper model
        max_tokens=1000,
        temperature=0,
        system=needs_docs_system_prompt,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": needs_docs_user_prompt.format(user_context=user_context, user_question=user_question)
                    }
                ]
            }
        ]
    )
    return message.content[0].text


def generate_queries(user_question, user_context=""):
    message = client.messages.create(
        model="claude-3-5-sonnet-20241022", # TODO change to cheaper model
        max_tokens=1000,
        temperature=0,
        system=search_docs_system_prompt,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": search_docs_user_prompt.format(user_context=user_context, user_question=user_question)
                    }
                ]
            }
        ]
    )
    text = message.content[0].text
    answer_parsed = json.loads(text)

    return answer_parsed

def search_docs(search_queries):
    search_results = []
    for q in search_queries:
        query_search_result = docsite_search.search(q.get("query"), top_k=top_k, threshold=threshold, docs_type=q.get("doc_type"))
        search_results.extend(query_search_result)
    
    return search_results

def format_context(adaptor):
    return f"For context, the user is using the {adaptor} adaptor. " if adaptor else ""