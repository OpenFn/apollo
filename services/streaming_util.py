"""
Stateful manager for Anthropic-formatted streaming events.

Handles content block lifecycle, indexing, and event formatting
to simplify streaming implementations across services.
"""

from typing import Optional, Any, Dict
from dataclasses import dataclass
import uuid
import json


@dataclass
class ContentBlock:
    """Represents an active streaming content block."""
    index: int
    block_type: str  # "thinking" or "text"
    is_open: bool = True

class StreamManager:
    """
    Manages Anthropic-formatted streaming events with automatic
    block lifecycle and index tracking.

    Example usage:
        manager = StreamManager()
        manager.start_stream()
        manager.send_thinking("Researching...")
        manager.send_text("Here's what I found...")
        manager.send_text(" More content...")
        manager.end_stream()
    """

    def __init__(self, model: str = "claude-3-7-sonnet-20250219", stream = True):
        """
        Initialize the stream manager.

        Args:
            model: Model name to include in message_start event
        """
        self.stream = stream
        self.model = model
        self.message_id: Optional[str] = None
        self.stream_started = False
        self.stream_ended = False

        # Track all content blocks
        self.blocks: list[ContentBlock] = []
        self.current_index = -1

    def _emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Send event through bridge to be forwarded as SSE.

        Args:
            event_type: SSE event type (e.g., 'message_start', 'content_block_delta')
            data: Event data dictionary
        """
        # Use EVENT: prefix format that bridge.ts expects
        # Bridge will convert this to proper SSE format
        if self.stream:
            print(f"EVENT:{event_type}:{json.dumps(data)}", flush=True)
    
    def start_stream(self) -> None:
        """
        Start a new stream by sending message_start event.
        Should be called once at the beginning of streaming.
        """
        if self.stream_started:
            raise RuntimeError("Stream already started")
        
        self.message_id = f"msg_{uuid.uuid4().hex[:24]}"
        self.stream_started = True

        self._emit_event('message_start', {
            "type": "message_start",
            "message": {
                "id": self.message_id,
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": self.model,
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0}
            }
        })
    
    def send_thinking(
        self, 
        thinking_text: str,
        signature: Optional[str] = "signature_filler"
    ) -> None:
        """
        Send a thinking block with the given text.
        Creates a new content block, sends the thinking, and closes it.
        
        Args:
            thinking_text: The thinking content to send
            signature: Optional signature to include with the thinking
        """
        if self.stream_ended:
            raise RuntimeError("Stream already ended")
        
        if not self.stream_started:
            self.start_stream()

        self._close_open_blocks()
        
        # Create new thinking block
        index = self._next_index()
        block = ContentBlock(index=index, block_type="thinking")
        self.blocks.append(block)
        
        # Send block start
        self._emit_event('content_block_start', {
            "type": "content_block_start",
            "index": index,
            "content_block": {"type": "thinking", "thinking": ""}
        })

        # Send thinking delta
        self._emit_event('content_block_delta', {
            "type": "content_block_delta",
            "index": index,
            "delta": {"type": "thinking_delta", "thinking": thinking_text}
        })

        # Send an Anthropic signature string
        self._emit_event('content_block_delta', {
            "type": "content_block_delta",
            "index": index,
            "delta": {"type": "signature_delta", "signature": signature}
        })
        
        self._close_block(block)
    
    def send_text(self, text_chunk: str) -> None:
        """
        Send a text chunk. Automatically manages text content block lifecycle.
        Creates a new text block on first call, then streams to the same block
        on subsequent calls until another block type is sent or stream ends.
        """
        if self.stream_ended:
            raise RuntimeError("Stream already ended")

        if not self.stream_started:
            self.start_stream()

        # Check if we have an open text block
        current_text_block = self._get_current_text_block()
        
        if current_text_block is None:
            # Create new text block
            index = self._next_index()
            current_text_block = ContentBlock(index=index, block_type="text")
            self.blocks.append(current_text_block)
            
            # Send block start
            self._emit_event('content_block_start', {
                "type": "content_block_start",
                "index": index,
                "content_block": {"type": "text", "text": ""}
            })

        # Send text delta
        self._emit_event('content_block_delta', {
            "type": "content_block_delta",
            "index": current_text_block.index,
            "delta": {"type": "text_delta", "text": text_chunk}
        })
        
    
    def end_stream(self, stop_reason: str = "end_turn") -> None:
        """
        End the stream by closing all open blocks and sending final events.
        """
        
        if self.stream_ended or not self.stream_started:
            return

        # Close any remaining open blocks
        self._close_open_blocks()

        # Send message_delta
        self._emit_event('message_delta', {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": 0}
        })

        # Send message_stop
        self._emit_event('message_stop', {
            "type": "message_stop"
        })
        
        self.stream_ended = True
        
    def _next_index(self) -> int:
        """Get the next content block index."""
        self.current_index += 1
        return self.current_index
    
    def _get_current_text_block(self) -> Optional[ContentBlock]:
        """Get the currently open text block, if any."""
        for block in reversed(self.blocks):
            if block.is_open and block.block_type == "text":
                return block
        return None
    
    def _close_block(self, block: ContentBlock) -> None:
        """Close a specific content block."""
        if not block.is_open:
            return

        self._emit_event('content_block_stop', {
            "type": "content_block_stop",
            "index": block.index
        })
        block.is_open = False
    
    def _close_open_blocks(self) -> None:
        """Close all currently open content blocks."""
        for block in self.blocks:
            if block.is_open:
                self._close_block(block)