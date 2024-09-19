## Search (RAG)

** RAG SEARCH IS AN EXPERIMENTAL FEATURE. IT IS NOT SUPPORTED BY THE STAGING SERVER**

The Search Service integrates Retrieval-Augmented Generation (RAG) with Apollo to enhance the accuracy and relevance of data retrieval based on user queries. By leveraging this service, clients can obtain pertinent information from documents, provided they include sufficient context in their queries.

## Usage - Search Service

### To make a search with `curl`:

```bash
curl -X POST https://apollo-staging.openfn.org/services/search --json @tmp/payload.json
```

### With the CLI, returning to stdout:

```bash
openfn apollo search tmp/payload.json
```
To run directly from this repo (note that the server must be started):

```bash
bun py search tmp/payload.json -O
```

## Config Paths
To make it easier to specify which documents should be embedded, we use a configuration file named `path.config` located at the root of the repository.

### Adding Document Paths

1. **Open the `path.config` file**: This file contains the paths to the markdown files that you want to embed into the vector database.

2. **Specify one path per line**: Add each document path you wish to include, with one path per line. These paths should be relative to the docs folder within the repository.

3. **Use standard glob patterns**: You can use standard glob patterns to match multiple files or directories. For example:
   - `docs/jobs/*.md`: This pattern matches all markdown files in the `docs/jobs` directory.
   - `docs/adaptors/**/*.md`: This pattern matches all markdown files within the `docs/adaptors` directory and any of its subdirectories.

### Example `path.config`

```plaintext
docs/jobs/*.md
docs/adaptors/**/*.md
```
In this example, all markdown files under docs/jobs and docs/adaptors (including subdirectories) will be processed and embedded.

#### Important Note: 
The paths specified in the `path.config` file are relative to the `docs` directory within your repository, not from the root folder.

By following these instructions, you can easily manage and update the list of documents to be embedded without needing to dive into the underlying code.

## Usage - Embedding OpenFn Docs
This service also includes the embedding of OpenFn docs to a vector database. The vector database used here is Zilliz. To obtain the env variables follow these steps:

1. Create an account on [Zilliz](https://zilliz.com/) and set up a free cluster.
2. Obtain the URL and token for the cluster and add them to the `.env` file.
3. You'll also need an OpenAI API key to generate embeddings.

There are two ways to run the embed the docs:

### Running the Generate Embeddings File
Use the poetry command to run the service. You will need to clone the docs repo in this case using:

```bash
git clone --depth 1 https://github.com/OpenFn/docs.git tmp
```

Then run:
```bash
poetry run python services/search/generate_docs_embeddings.py tmp/docs openfn_docs
```
Here, tmp/docs is the path to the OpenFn docs and openfn_docs is the name of the collection in the vector database.

### Docker
Alternatively, run the Docker file directly using:

```bash
docker build --secret id=_env,src=.env -t apollo .
```

**NOTE**:   The docs are split into chunks which can be seen in the `tmp/split_sections` folder.

## Implementation
The service retrieves data from job documents stored in a vector database. It uses the OpenAI Embedding Function to embed the OpenFn Documentation, allowing for relevant context retrieval and enhancing the performance of other Apollo services. You can also configure the number of chunks retrieved from the database.

## Payload Reference
The input payload is a JSON object with the following structure:

```js
{
    "api_key": "<OpenAI api key>",
    "query": "What are jobs in OpenFn?",
    "limit": 10, // Custom limit for number of chunks retrieved (1 to 15). Default value is 5. (optional)
    "partition_name": "openfn_docs", // Name of the partition in the vector database. (optional)
}
```
The `partition_name` is optional and the expected values are `normal_docs` or `adaptor_docs`.

## Response Reference
The server returns an array of relevant strings from the documents based on the provided query.