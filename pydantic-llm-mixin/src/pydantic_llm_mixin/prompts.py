"""
Central LLM Prompt Registry - Single Source of Truth

All LLM prompts, docstrings, and field descriptions centralized here.
Import and reuse across models - no duplication, consistent formatting.

Philosophy:
- Trust the LLM's intelligence
- Concise > verbose
- Examples only when truly needed
- Field descriptions: 1-2 lines max
"""

# ============================================================================
# Conversation History Standards
# ============================================================================

CONVERSATION_HISTORY_STANDARD = """
All conversation history must use this exact format:

[
    {"role": "system", "content": "{pure JSON schema}"},      # First: Schema
    {"role": "user", "content": "..."},                       # Middle: 3-5 exchanges
    {"role": "assistant", "content": "..."},                  #
    {"role": "user", "content": "{current query}"}            # Final: Current query
]

Structure:
- System message: Pure JSON schema (no timestamp, no instructions)
- Middle: 3-5 recent user+assistant exchanges (complete pairs)
- Final: Current user query

Tool results: {"role": "assistant", "content": "[TOOL_RESULT: ToolName]\\n{content}"}
"""

# Conversation history limits
CONVERSATION_HISTORY_LIMITS = {
    "min_exchanges": 3,
    "max_exchanges": 5,
    "max_messages": 10,  # 5 exchanges = 10 messages (user+assistant pairs)
}

# Schema system message template
# Minimal prompting - schema + history is enough, LLM knows what to do
SCHEMA_SYSTEM_MESSAGE_TEMPLATE = """Today's date: {current_date}

Respond with JSON code block:
```json
{{response matching schema}}
```

Schema:
{schema_json}

{formatting_guidance}"""


# ============================================================================
# Schema Generation Notes
# ============================================================================

SCHEMA_GENERATION_NOTES = """
Schema generation via GenerativeMixin._generate_prompt():

1. Get schema: cls.model_json_schema() (filters system-managed fields)
2. Format: JSON.stringify with indent=2
3. Inject class docstring if exists
4. Final format:
   datetime is {utc_now}

   {class_docstring}

   Respond with ```json code block matching this schema:
   {schema_json}

Keep docstrings concise - LLM sees full schema field descriptions already.
"""
