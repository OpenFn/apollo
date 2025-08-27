import json
import os
from typing import Dict, Any, Optional
from anthropic import Anthropic
import redis
from util import ApolloError, create_logger

logger = create_logger("filter_docs")

FILTERED_DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "filtered_docs")

class DocsFilter:
    def __init__(self, api_key: str = None, redis_url: str = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("API key must be provided")
        self.client = Anthropic(api_key=self.api_key)
        
        # Redis setup - defaults to local Redis
        redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        try:
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            # Test connection
            self.redis_client.ping()
            logger.info("Connected to Redis")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}")
            self.redis_client = None
    
    def save_to_redis(self, adaptor_specifier: str, filtered_data: Dict[str, Any]) -> None:
        """Save filtered docs to Redis"""
        if not self.redis_client:
            return
        
        try:
            json_data = json.dumps(filtered_data)
            self.redis_client.set(adaptor_specifier, json_data)
            logger.info(f"Saved filtered docs to Redis for {adaptor_specifier}")
        except Exception as e:
            logger.warning(f"Error saving to Redis: {e}")
        """Build the system prompt for filtering documentation"""
        return f"""You are tasked with filtering OpenFn adaptor documentation to keep only the most relevant information for an AI assistant that will help users write workflow code.

The AI assistant already has extensive knowledge of:
- Basic JavaScript concepts and syntax
- Common TypeScript definitions and interfaces
- Standard Node.js patterns and modules
- Generic utility functions and common programming patterns

Your job is to filter the documentation for the {package_name} adaptor to keep ONLY:
1. Adaptor-specific functions and their exact signatures
2. Adaptor-specific configuration options and parameters
3. Unique data structures or types specific to this adaptor
4. Authentication and connection details specific to this service
5. Examples showing how to use adaptor functions
6. Any quirks, limitations, or important usage notes

REMOVE:
- Generic TypeScript utility types (Partial, Pick, Omit, etc.)
- Basic JavaScript/Node.js concepts the AI already knows
- Common HTTP/REST patterns unless adaptor-specific
- Generic error handling patterns
- Standard callback or Promise patterns unless adaptor-specific

Return a clean, filtered version of the documentation that focuses on what makes this adaptor unique and how to use it specifically. Keep all function signatures and examples intact, but remove redundant type definitions and generic concepts."""

    def filter_documentation(self, package_data: Dict[str, Any]) -> Dict[str, Any]:
        """Filter documentation for each package using Claude"""
        filtered_data = {}
        
        for package_name, package_info in package_data.items():
            logger.info(f"Filtering documentation for {package_name}")
            
            try:
                system_prompt = self.build_filter_prompt(package_name, package_info['description'])
                
                message = self.client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=16384,
                    system=system_prompt,
                    messages=[{
                        "role": "user", 
                        "content": f"Filter this documentation:\n\n{package_info['description']}"
                    }]
                )
                
                filtered_content = ""
                for content_block in message.content:
                    if content_block.type == "text":
                        filtered_content += content_block.text
                
                filtered_data[package_name] = {
                    'name': package_name,
                    'description': filtered_content.strip()
                }
                
                logger.info(f"Successfully filtered {package_name}")
                
            except Exception as e:
                logger.error(f"Error filtering {package_name}: {str(e)}")
                # Fall back to original content if filtering fails
                filtered_data[package_name] = package_info
        
        return filtered_data
    
    def save_filtered_docs(self, adaptor_specifier: str, filtered_data: Dict[str, Any]) -> str:
        """Save filtered documentation to local JSON file"""
        os.makedirs(FILTERED_DOCS_DIR, exist_ok=True)
        
        # Create filename from adaptor specifier
        name, version = adaptor_specifier.rsplit('@', 1) if '@' in adaptor_specifier else (adaptor_specifier, 'latest')
        safe_name = name.replace('/', '_').replace('@', '_')
        filename = f"{safe_name}_{version}_filtered.json"
        filepath = os.path.join(FILTERED_DOCS_DIR, filename)
        
        try:
            with open(filepath, 'w') as f:
                json.dump(filtered_data, f, indent=2)
            
            logger.info(f"Saved filtered docs to {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"Error saving filtered docs: {str(e)}")
            raise


def filter_and_save_docs(adaptor_specifier: str, package_data: Dict[str, Any], api_key: str = None, redis_url: str = None) -> str:
    """
    Main function to filter documentation and save to JSON file and Redis.
    
    Args:
        adaptor_specifier: The adaptor name and version (e.g., "@openfn/language-http@4.2.0")
        package_data: The raw package data from describe_package
        api_key: Optional API key for Anthropic
        redis_url: Optional Redis URL (defaults to localhost)
    
    Returns:
        str: Path to the saved filtered documentation file
    """
    try:
        filter_client = DocsFilter(api_key=api_key, redis_url=redis_url)
        
        filtered_data = filter_client.filter_documentation(package_data)
        
        filepath = filter_client.save_filtered_docs(adaptor_specifier, filtered_data)
        filter_client.save_to_redis(adaptor_specifier, filtered_data)
        
        return filepath
        
    except Exception as e:
        logger.error(f"Error in filter_and_save_docs: {str(e)}")
        raise ApolloError(500, f"Failed to filter documentation: {str(e)}")


def main(data_dict: dict) -> dict:
    """
    Main entry point that can be called with a payload.
    
    Expected payload:
    {
        "adaptor_specifier": "@openfn/language-http@4.2.0",
        "package_data": {...},  # Output from describe_package
        "api_key": "optional_api_key",
        "redis_url": "optional_redis_url"
    }
    """
    try:
        if "adaptor_specifier" not in data_dict:
            raise ValueError("'adaptor_specifier' is required")
        if "package_data" not in data_dict:
            raise ValueError("'package_data' is required")
        
        adaptor_specifier = data_dict["adaptor_specifier"]
        package_data = data_dict["package_data"]
        api_key = data_dict.get("api_key")
        redis_url = data_dict.get("redis_url")
        
        filepath = filter_and_save_docs(adaptor_specifier, package_data, api_key, redis_url)
        
        return {
            "success": True,
            "filepath": filepath,
            "adaptor_specifier": adaptor_specifier
        }
        
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise ApolloError(400, str(e), type="BAD_REQUEST")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise ApolloError(500, str(e), type="INTERNAL_ERROR")