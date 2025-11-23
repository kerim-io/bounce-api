"""
Railway Deployment Example - Bookstore Generator

Generate a complete bookstore with inventory using discriminated unions.
"""

import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from pydantic_llm_mixin import GenerationError, GenerativeMixin, get_groq_client

# Global client
groq_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    global groq_client

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    groq_client = await get_groq_client(api_key=api_key, temperature=0.6, max_tokens=3000)
    print("✅ Groq client initialized")

    yield

    if groq_client:
        await groq_client.close()


app = FastAPI(title="Bookstore Generator API", lifespan=lifespan)


# ============================================================================
# MODELS
# ============================================================================


class Book(BaseModel):
    """A book"""

    title: str = Field(..., description="Book title")
    author: str = Field(..., description="Author name")
    isbn: str = Field(..., description="ISBN")
    price: float = Field(..., description="Price in dollars")
    pages: int = Field(..., description="Number of pages")


class DVD(BaseModel):
    """A DVD"""

    title: str = Field(..., description="DVD title")
    director: str = Field(..., description="Director")
    runtime_minutes: int = Field(..., description="Runtime in minutes")
    price: float = Field(..., description="Price in dollars")
    rating: Literal["G", "PG", "PG-13", "R", "NC-17"] = Field(..., description="Rating")


class Poster(BaseModel):
    """A poster"""

    title: str = Field(..., description="Poster title")
    artist: str = Field(..., description="Artist")
    dimensions: str = Field(..., description="Dimensions like '24x36 inches'")
    price: float = Field(..., description="Price in dollars")
    material: Literal["paper", "canvas", "vinyl"] = Field(..., description="Material")


# Discriminated union
BookstoreItem = Book | DVD | Poster


class Bookstore(BaseModel, GenerativeMixin):
    """A bookstore with inventory"""

    name: str = Field(..., description="Bookstore name")
    location: str = Field(..., description="City and country")
    specialty: str = Field(..., description="What the store specializes in")
    inventory: list[BookstoreItem] = Field(..., description="Items in stock (Books, DVDs, Posters)")


class GenerateRequest(BaseModel):
    """Request to generate a bookstore"""

    query: str = Field(..., description="Describe the bookstore")


class GenerateResponse(BaseModel):
    """Response with generated bookstore"""

    bookstore: Bookstore
    success: bool = True


# ============================================================================
# ENDPOINTS
# ============================================================================


@app.get("/")
async def root():
    """Health check"""
    return {"status": "healthy", "service": "Bookstore Generator API"}


@app.post("/generate", response_model=GenerateResponse)
async def generate_bookstore(request: GenerateRequest):
    """
    Generate a bookstore from natural language.

    Example: {"query": "Create a bookstore in Paris"}
    """
    try:
        conversation = [{"role": "user", "content": request.query}]

        bookstore = await Bookstore.generate_instance(
            client=groq_client,
            conversation_history=conversation,
        )

        return GenerateResponse(bookstore=bookstore)

    except GenerationError as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
