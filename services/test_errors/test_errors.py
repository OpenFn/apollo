from util import ApolloError

def main(data: dict) -> dict:
    trigger = data.get("trigger", "SUCCESS")
    
    if trigger == "RATE_LIMIT":
        raise ApolloError(
            429,
            "Rate limit exceeded, please try again later",
            type="RATE_LIMIT",
            details={"retry_after": 60}
        )
    
    if trigger == "UNEXPECTED":
        raise Exception("Something went wrong!")
    
    return {"success": True}