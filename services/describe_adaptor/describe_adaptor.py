import aiohttp
import asyncio
import json
import re
import sentry_sdk
import os
import time
from typing import Dict, List, Optional, Any, Tuple
from util import ApolloError, create_logger

logger = create_logger("describe_adaptor_direct")

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
CACHE_TTL = 43200  # 12 hours in seconds


def get_cache_path(specifier: str) -> str:
    """Get the path to the cache file for the given adaptor specifier"""
    name, version = specifier.rsplit('@', 1) if '@' in specifier else (specifier, None)
    name = name.replace('/', '_')
    version = version or 'latest'
    
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    return os.path.join(CACHE_DIR, f"{name}_{version}.json")


async def read_from_cache(specifier: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    """
    Read data from cache if it exists and is not expired.
    Returns (cached_data, cache_hit)
    """
    cache_path = get_cache_path(specifier)
    
    if not os.path.exists(cache_path):
        return None, False
    
    try:
        with open(cache_path, 'r') as f:
            cached_data = json.load(f)
        
        timestamp = cached_data.get('_meta', {}).get('timestamp', 0)
        if time.time() - timestamp > CACHE_TTL:
            logger.info(f"Cache for {specifier} expired, will refresh")
            return None, False
            
        logger.info(f"Using cached data for {specifier}")

        if '_meta' in cached_data:
            del cached_data['_meta']
        return cached_data, True
    
    except Exception as e:
        logger.warning(f"Error reading cache for {specifier}: {str(e)}")
        return None, False


async def write_to_cache(specifier: str, data: Dict[str, Any]) -> None:
    """Write data to cache with timestamp"""
    cache_path = get_cache_path(specifier)
    
    try:
        cache_data = data.copy()
        cache_data['_meta'] = {
            'timestamp': time.time(),
            'specifier': specifier
        }
        
        with open(cache_path, 'w') as f:
            json.dump(cache_data, f)
        
        logger.info(f"Cached data for {specifier}")
    
    except Exception as e:
        logger.warning(f"Error writing cache for {specifier}: {str(e)}")


async def fetch_file(session: aiohttp.ClientSession, path: str) -> str:
    """Fetch a file from jsdelivr CDN"""
    resolved_path = f"https://cdn.jsdelivr.net/npm/{path}"
    logger.info(f"Fetching {resolved_path}")
    
    try:
        async with session.get(resolved_path, timeout=aiohttp.ClientTimeout(total=30)) as response:
            if response.status == 200:
                return await response.text()
            
            error_msg = f"Failed getting file at: {path} got: {response.status} {response.reason}"
            logger.error(error_msg)
            raise Exception(error_msg)
            
    except asyncio.TimeoutError:
        error_msg = f"Timeout fetching {path}"
        logger.error(error_msg)
        raise Exception(error_msg)
    except Exception as e:
        error_msg = f"Network error fetching {path}: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)


async def fetch_file_listing(session: aiohttp.ClientSession, package_name: str) -> List[str]:
    """Fetch file listing from jsdelivr API"""
    api_url = f"https://data.jsdelivr.com/v1/package/npm/{package_name}/flat"
    
    try:
        async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
            if response.status != 200:
                error_msg = f"Failed getting file listing for: {package_name} got: {response.status} {response.reason}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
            listing = await response.json()
            files = listing.get('files', [])
            file_names = [file_info['name'] for file_info in files]
            return file_names
            
    except asyncio.TimeoutError:
        error_msg = f"Timeout fetching file listing for {package_name}"
        logger.error(error_msg)
        raise Exception(error_msg)
    except Exception as e:
        error_msg = f"Error fetching file listing for {package_name}: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)


async def get_dts_files(session: aiohttp.ClientSession, package_name: str) -> List[str]:
    """Get list of .d.ts files for a package"""
    dts_pattern = re.compile(r'\.d\.ts$')
    
    try:
        file_names = await fetch_file_listing(session, package_name)
        return [filename for filename in file_names if dts_pattern.search(filename)]
        
    except Exception as e:
        logger.error(f"Error fetching .d.ts listing for {package_name}: {str(e)}")
        raise


async def describe_package_async(specifier: str, force_refresh: bool = False) -> Dict[str, Any]:
    """Describe a package by fetching its TypeScript definitions with caching"""
    if sentry_sdk.Hub.current.client:
        transaction = sentry_sdk.start_transaction(name="describe_package")
        sentry_sdk.set_tag("package_specifier", specifier)
    else:
        transaction = None
    
    try:
        if not force_refresh:
            cached_data, cache_hit = await read_from_cache(specifier)
            if cache_hit and cached_data:
                if sentry_sdk.Hub.current.client:
                    sentry_sdk.set_tag("cache_hit", "true")
                return cached_data
        
        name, version = specifier.rsplit('@', 1) if '@' in specifier else (specifier, None)
        
        logger.info(f"Describing package: {name}@{version}")
        if sentry_sdk.Hub.current.client:
            sentry_sdk.set_tag("cache_hit", "false")
        
        results = {}
        
        async with aiohttp.ClientSession() as session:
            if name != "@openfn/language-common":
                span = sentry_sdk.start_span(description="fetch_language_common") if sentry_sdk.Hub.current.client else None
                
                common_files = []
                results["@openfn/language-common"] = common_files
                
                try:
                    pkg_str = await fetch_file(session, f"{specifier}/package.json")
                    pkg = json.loads(pkg_str)
                    
                    common_dependency = pkg.get('dependencies', {}).get('@openfn/language-common')
                    if common_dependency:
                        common_version = common_dependency.replace('^', '')
                        common_specifier = f"@openfn/language-common@{common_version}"
                        
                        # Try to get language-common from cache
                        common_cached, common_hit = await read_from_cache(common_specifier)
                        if common_hit and common_cached:
                            for package_name, package_data in common_cached.items():
                                if package_name == "@openfn/language-common":
                                    common_files.append(package_data['description'])
                                    logger.info(f"Using cached language-common {common_specifier}")
                        else:
                            # Get .d.ts files and fetch them concurrently
                            common_dts_files = await get_dts_files(session, common_specifier)
                            common_file_paths = [f"{common_specifier}{file_name}" for file_name in common_dts_files]
                            
                            fetch_tasks = [fetch_file(session, file_path) for file_path in common_file_paths]
                            fetched_files = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                            
                            for i, result in enumerate(fetched_files):
                                if isinstance(result, Exception):
                                    logger.warning(f"Failed to fetch common file {common_file_paths[i]}: {str(result)}")
                                else:
                                    common_files.append(result)
                                    
                except Exception as e:
                    logger.error(f"Error processing language-common: {str(e)}")
                    # Continue processing main package even if common fails
                
                if span:
                    span.finish()

            span = sentry_sdk.start_span(description="fetch_main_package") if sentry_sdk.Hub.current.client else None
            package_files = []
            results[name] = package_files
            
            # Get .d.ts files and fetch them concurrently
            main_dts_files = await get_dts_files(session, specifier)
            main_file_paths = [f"{specifier}{file_name}" for file_name in main_dts_files 
                             if not re.search(r'beta\.d\.ts$', file_name)]
            
            fetch_tasks = [fetch_file(session, file_path) for file_path in main_file_paths]
            fetched_files = await asyncio.gather(*fetch_tasks, return_exceptions=True)
            
            for i, result in enumerate(fetched_files):
                if isinstance(result, Exception):
                    logger.warning(f"Failed to fetch file {main_file_paths[i]}: {str(result)}")
                else:
                    package_files.append(result)
            
            if span:
                span.finish()
        
        final_results = {}
        for k in results:
            final_results[k] = {
                'name': k,
                'description': '\n\n'.join(results[k])
            }
        
        if sentry_sdk.Hub.current.client:
            sentry_sdk.set_context("result_summary", {
                "packages_processed": len(final_results),
                "total_description_length": sum(len(pkg['description']) for pkg in final_results.values())
            })
        
        await write_to_cache(specifier, final_results)
        
        return final_results
        
    except Exception as e:
        logger.error(f"Error describing package {specifier}: {str(e)}")
        if sentry_sdk.Hub.current.client:
            sentry_sdk.capture_exception(e)
        raise
    finally:
        if transaction:
            transaction.finish()


def describe_package(specifier: str, force_refresh: bool = False) -> Dict[str, Any]:
    """Sync wrapper for describe_package_async - can be imported and used directly"""
    return asyncio.run(describe_package_async(specifier, force_refresh))


async def main_async(data_dict: dict) -> dict:
    """Async main entry point."""
    try:
        if sentry_sdk.Hub.current.client:
            sentry_sdk.set_context("request_data", data_dict)
        
        if "adaptor" not in data_dict:
            raise ValueError("'adaptor' is required")
        
        adaptor = data_dict["adaptor"]
        force_refresh = data_dict.get("force_refresh", False)
        result = await describe_package_async(adaptor, force_refresh)
        
        return result
    
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {str(e)}")
        raise ApolloError(502, "Invalid response from package registry", type="PARSE_ERROR")
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise ApolloError(400, str(e), type="BAD_REQUEST")
        
    except asyncio.TimeoutError as e:
        logger.error(f"Request timeout: {str(e)}")
        raise ApolloError(504, "Request timeout while fetching package data", type="TIMEOUT_ERROR")
        
    except Exception as e:
        logger.error(f"Unexpected error during package description: {str(e)}")
        if sentry_sdk.Hub.current.client:
            sentry_sdk.capture_exception(e)
        raise ApolloError(500, str(e), type="INTERNAL_ERROR")


def main(data_dict: dict) -> dict:
    """Sync main entry point - can be called with a payload directly"""
    return asyncio.run(main_async(data_dict))

if __name__ == "__main__":
    main()