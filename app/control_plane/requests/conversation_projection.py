"""Conversation-projection control-plane payloads.

Legacy request types (BindConversationRequest, PublishTimelineRequest) have been
removed.  Conversation projection now uses create_conversation / publish_events
with inline JSON payloads.
"""
