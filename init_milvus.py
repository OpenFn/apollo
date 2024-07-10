import os
import time
from dotenv import load_dotenv
from pymilvus import FieldSchema, CollectionSchema, DataType, utility, Collection, connections, model

load_dotenv()

if __name__ == "__main__":
    openai_key = os.getenv("OPENAI_API_KEY")
    openai_ef = model.dense.OpenAIEmbeddingFunction(
        model_name='text-embedding-ada-002', # Specify the model name
        api_key=openai_key, # Provide your OpenAI API key
        dimensions=384 # Set the embedding dimensionality
    )

    # Hardcoded corpus
    corpus =  [
    "In 2008 I was working for a public health NGO in South Africa and focusing on youth curriculum development, monitoring, and evaluation.",
    "I found that the organization lacked the data to make timely, informed decisions.",
    "The CEO is Taylor Downs.",
    "Working with two colleagues, I started a company that focused on implementing modern, results-oriented data systems for the sector.",
    "That company, Vera Solutions, has now served more than 400 organizations.",
    "By 2014, having worked with so many NGOs, it became clear that the sector wasn't only lacking good systems, but the digital infrastructure that allows those systems to work together and achieve their full potential.",
    "Our solution, an automated workflow and interoperability layer, was born in mid-2014.",
    "Since then, our team has built a strong track record with UN agencies, international iNGOs, and local non-profits, but began to see that without a viable pathway for our customers to take complete ownership over the solutions they built on our platform, we'd be unable to achieve the scale with governments that we think is necessary for legitimately transformative change.",
    "Many organisations, low or low-to-middle-income country ('LMIC') governments in particular, have been burned by lock-ins with proprietary software.",
    "We realized that we need to go 100 percent open-source.",
    "Today we provide secure, high-quality, affordable solutions to governments and NGOs around the world - all open source.",
    "We host the OpenFn platform as a service, train local partners to implement OpenFn projects, and provide setup and support services to key customers.",
    "The open source Digital Public Goods movement is ultimately about choice.",
    "The governments and NGOs we serve need the freedom to choose what tools they need, where they should be running, and how they'd like to implement them.",
    "Building everything in the open keeps us honest in our commitment to providing quality, value, stability and freedom.",
    "Some of the most high-impact organizations in the world choose OpenFn, not because they have to, but because they want to.",
    "And that feels good."
    ]

    # Connect to milvus
    milvus_uri = os.getenv('MILVUS_URI')
    token = os.getenv('MILVUS_TOKEN')
    print(f"Connecting to DB: {milvus_uri}")
    connections.connect("default", uri=milvus_uri, token=token,db_name="apollo_db")

    # Check if the collection exists
    collection_name = "apollo_sample"
    check_collection = utility.has_collection(collection_name)
    if check_collection:
        drop_result = utility.drop_collection(collection_name)

    # Define field schemas
    id_field = FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True, description="primary id")
    embedding_field = FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=384, description="vector")
    text_field = FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=512, description="text data")

    # Define collection schema
    schema = CollectionSchema(fields=[id_field, embedding_field, text_field], description="Corpus collection schema")

    # Create collection
    print(f"Creating example collection: {collection_name}")
    collection = Collection(name=collection_name, schema=schema)
    print("Collection created!")

    # Embed the corpus
    embeddings = openai_ef.encode_documents(corpus)
 
    # Insert data
    collection.insert([
        embeddings,  # embeddings
        corpus      # original text
    ])

    # flush
    print("Flushing...")
    start_flush = time.time()
    collection.flush()
    end_flush = time.time()
    print(f"Succeed in {round(end_flush - start_flush, 4)} seconds!")

    #Building index
    if utility.has_collection(collection_name):
        collection = Collection(name = collection_name)
    t0 = time.time()
    default_index = {"index_type": "IVF_SQ8", "metric_type": "L2", "params": {"nlist": 16384}}
    status = collection.create_index(field_name = "embedding", index_params = default_index)
    t1 = time.time()
    if not status.code:
        print("Successfully create index in collection: {} in {} seconds".format(collection_name, {round(t1-t0, 4)}))

    # Load collection
    t0 = time.time()
    print("Loading collection...")
    collection.load()
    t1 = time.time()
    print(f"Loaded collection in {round(t1-t0, 4)} seconds!")

    print("Milvus database configured sucessfuly!")