from openai import OpenAI

def summarize_context(api_key: str, context: list[str], query: str) -> str:
    client = OpenAI(api_key=api_key)

    # Combine all the context into a single string
    context_text = "\n".join(context)

    # Create the system prompt
    system_prompt = (
        "You are an expert assistant for OpenFn specialized in workflow automation."
        "Your task is to help the user summarize information in a way that is highly relevant to their query. "
        "Include everything that is directly related to the query."
        "Add as many code snippets that might be available to you."
        "DO NOT answer any query which is not related to the context."
    )

    # Create the user message with the context and the query
    user_prompt = (
        f"The user is asking for information related to the following query: '{query}'.\n\n"
        "Here is the context:\n"
        f"{context_text}\n\n"
        "Please summarize the context based on the query, including all relevant information"
    )

    # Define the messages to be sent to the OpenAI API
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # Call the OpenAI API to get the summary
    response = client.chat.completions.create(
        messages=messages,
        model="gpt-3.5-turbo",
        temperature=0.3,
        max_tokens=512,
    )

    # Extract the summary from the response
    summary = response.choices[0].message.content.strip()

    return [summary]