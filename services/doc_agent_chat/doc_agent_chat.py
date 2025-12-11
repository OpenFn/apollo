import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from dotenv import load_dotenv
from util import create_logger, ApolloError
from doc_agent_chat.agent import Agent

logger = create_logger("doc_agent_chat")


@dataclass
class Payload:
    content: str
    context: dict
    history: Optional[List[Dict[str, str]]] = None
    api_key: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Payload":
        if "content" not in data:
            raise ValueError("'content' is required")
        if "context" not in data:
            raise ValueError("'context' is required")

        context = data["context"]
        required_context_fields = ["project_id", "project_name", "documents"]
        for field in required_context_fields:
            if field not in context:
                raise ValueError(f"'context.{field}' is required")

        return cls(
            content=data["content"],
            context=context,
            history=data.get("history", []),
            api_key=data.get("api_key")
        )


def main(data: dict) -> dict:
    try:
        logger.info("Starting doc agent chat...")
        payload = Payload.from_dict(data)

        load_dotenv(override=True)
        OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
        PINECONE_API_KEY = os.environ.get('PINECONE_API_KEY')

        missing_keys = []
        if not OPENAI_API_KEY:
            missing_keys.append("OPENAI_API_KEY")
        if not PINECONE_API_KEY:
            missing_keys.append("PINECONE_API_KEY")

        if missing_keys:
            msg = f"Missing API keys: {', '.join(missing_keys)}"
            logger.error(msg)
            raise ApolloError(500, msg, type="MISSING_API_KEY")

        agent = Agent(api_key=payload.api_key)
        result = agent.run(
            content=payload.content,
            context=payload.context,
            history=payload.history
        )

        return result

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        raise ApolloError(400, str(e), type="BAD_REQUEST")
    except Exception as e:
        logger.error(f"Error in doc agent chat: {str(e)}")
        raise ApolloError(500, str(e), type="INTERNAL_ERROR")


if __name__ == "__main__":
    main()
