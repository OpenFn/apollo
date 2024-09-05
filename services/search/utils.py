import os
import glob
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

def read_md_files(file_paths):
    """Read markdown files given a list of file paths."""
    docs = []
    for file_path in file_paths:
        if os.path.isfile(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    docs.append((file_path, f.read()))
            except Exception as e:
                print(f"Error reading file {file_path}: {e}")
        else:
            print(f"Warning: File {file_path} does not exist.")
    
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

def read_paths_config(config_file, repo_path):
    """Read paths from the configuration file and prepend repo_path to each path."""
    paths = []
    if not os.path.isfile(config_file):
        raise FileNotFoundError(f"Configuration file {config_file} does not exist.")
    
    with open(config_file, 'r') as file:
        for line in file:
            pattern = line.strip()
            if pattern:
                # Prepend the repo_path to the pattern
                full_pattern = os.path.join(repo_path, pattern)
                
                # Expand user home directory if present
                full_pattern = os.path.expanduser(full_pattern)
                
                # Print the pattern being processed
                print(f"Processing pattern: {full_pattern}")
                
                # Use glob to find matching paths
                matched_paths = glob.glob(full_pattern, recursive=True)
                
                # Print the matched paths
                print(f"Matched paths: {matched_paths}")
                
                # Ensure matched_paths is not empty
                if matched_paths:
                    paths.extend(matched_paths)
                else:
                    print(f"No matches found for pattern: {full_pattern}")
                                    
    return paths