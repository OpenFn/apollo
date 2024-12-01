from util import ApolloError

def main(data: dict) -> dict:
    trigger = data.get("trigger", "SUCCESS")
    
    if trigger == "RATE_LIMIT":
        return ApolloError(
            error_code=429,
            error_type="RATE_LIMIT",
            error_message="Rate limit exceeded, please try again later",
            error_details={"retry_after": 60}
        ).to_dict()
    
    if trigger == "UNEXPECTED":
        raise Exception("Something went wrong!")
    
    return {"success": True}