"""
Basic Usage Example for Pydantic LLM Mixin

Demonstrates how to use GenerativeMixin to generate Pydantic model instances from LLM responses.
"""

import asyncio
import os

from pydantic import BaseModel, Field

from pydantic_llm_mixin import GenerativeMixin, get_groq_client


class Person(BaseModel, GenerativeMixin):
    """A person with basic biographical information"""

    name: str = Field(..., description="Person's full name")
    age: int = Field(..., description="Person's age in years")
    occupation: str = Field(..., description="Current job title")
    notable_achievement: str = Field(..., description="Most significant accomplishment")


async def main():
    """Run the example"""
    # Get API key from environment
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("Error: GROQ_API_KEY environment variable not set")
        print("Get your API key at: https://console.groq.com/keys")
        return

    # Initialize Groq client
    print("Initializing Groq client...")
    client = await get_groq_client(api_key=api_key, temperature=0.6, max_tokens=2048)

    # Conversation history
    conversation = [{"role": "user", "content": "Tell me about Nikola Tesla"}]

    print("Generating Person instance from LLM...\n")

    # Generate validated instance
    person = await Person.generate_instance(client=client, conversation_history=conversation, debug=True)

    # Display results
    print("\n" + "=" * 60)
    print("Generated Person Instance:")
    print("=" * 60)
    print(f"Name: {person.name}")
    print(f"Age: {person.age}")
    print(f"Occupation: {person.occupation}")
    print(f"Notable Achievement: {person.notable_achievement}")
    print("=" * 60)

    # Clean up
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
