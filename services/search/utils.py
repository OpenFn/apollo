import os
import glob
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

def read_md_files(directories):
    docs = []
    for directory in directories:
        md_files = glob.glob(f"{directory}/**/*.md", recursive=True)
        for file in md_files:
            with open(file, "r", encoding="utf-8") as f:
                docs.append((file, f.read()))  # Returning a tuple with file name and content
    return docs

def split_docs(file_name, content):
    headers_to_split_on = [
        ("##", "Header 2"),	
        ("###", "Header 3"),	     
    ]	  
    markdown_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=headers_to_split_on, 
        strip_headers=False
    )	    
    md_header_splits = markdown_splitter.split_text(content)
    
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1024, 
        chunk_overlap=256, 
        length_function=len, 
        is_separator_regex=False
    )
    splits = text_splitter.split_documents(md_header_splits)

    # Write the sections to disk
    output_dir = "./tmp/split_sections"
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, f"{os.path.basename(file_name)}_sections.md"), "w", encoding="utf-8") as out_file:
        for section in splits:
            out_file.write(f"## Section Start: " + "\n------\n")
            out_file.write(section.page_content + "\n------\n")

    return splits