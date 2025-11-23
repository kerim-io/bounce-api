#!/usr/bin/env python
"""
CLI tool for pydantic-llm-mixin development and testing.

Usage:
    uv run python cli.py --help
    uv run python cli.py login
    uv run python cli.py generate "Create a bookstore in Paris"
    uv run python cli.py test-auth
"""

import os

import httpx
import typer
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel

app = typer.Typer(help="pydantic-llm-mixin CLI tool")
console = Console()

BASE_URL = os.getenv("API_URL", "http://localhost:8200")
TOKEN_FILE = ".jwt_token"


def save_token(token: str) -> None:
    """Save JWT token to file"""
    with open(TOKEN_FILE, "w") as f:
        f.write(token)
    console.print(f"[green]Token saved to {TOKEN_FILE}[/green]")


def load_token() -> str | None:
    """Load JWT token from file"""
    try:
        with open(TOKEN_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


@app.command()
def health() -> None:
    """Check API health"""
    try:
        response = httpx.get(f"{BASE_URL}/")
        response.raise_for_status()
        console.print(Panel(JSON(response.text), title="Health Check", border_style="green"))
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def login(
    email: str = typer.Option(..., prompt=True, help="Your email address"),
    password: str = typer.Option(..., prompt=True, hide_input=True, help="Your password"),
) -> None:
    """Login and get JWT token"""
    try:
        response = httpx.post(
            f"{BASE_URL}/auth/login",
            json={"email": email, "password": password},
        )
        response.raise_for_status()
        data = response.json()
        token = data["access_token"]
        save_token(token)
        console.print(Panel(JSON(response.text), title="Login Success", border_style="green"))
    except Exception as e:
        console.print(f"[red]Login failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def me() -> None:
    """Get current user info"""
    token = load_token()
    if not token:
        console.print("[red]Not logged in. Run: uv run python cli.py login[/red]")
        raise typer.Exit(1)

    try:
        response = httpx.get(
            f"{BASE_URL}/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        console.print(Panel(JSON(response.text), title="Current User", border_style="blue"))
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print("[yellow]Token may be expired. Run: uv run python cli.py login[/yellow]")
        raise typer.Exit(1)


@app.command()
def generate(query: str) -> None:
    """Generate a bookstore from natural language query"""
    token = load_token()
    if not token:
        console.print("[red]Not logged in. Run: uv run python cli.py login[/red]")
        raise typer.Exit(1)

    console.print(f"[yellow]Generating bookstore for: {query}[/yellow]")

    try:
        response = httpx.post(
            f"{BASE_URL}/generate",
            json={"query": query},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        bookstore = data["bookstore"]

        console.print(Panel(f"[green]{bookstore['name']}[/green]", title="Bookstore", border_style="green"))
        console.print(f"[blue]Location:[/blue] {bookstore['location']}")
        console.print(f"[blue]Specialty:[/blue] {bookstore['specialty']}\n")

        console.print("[yellow]Inventory:[/yellow]")
        for item in bookstore["inventory"]:
            if "author" in item:
                console.print(f"  📚 Book: {item['title']} by {item['author']} (${item['price']})")
            elif "director" in item:
                console.print(f"  🎬 DVD: {item['title']} directed by {item['director']} (${item['price']})")
            elif "artist" in item:
                console.print(f"  🖼️  Poster: {item['title']} by {item['artist']} (${item['price']})")

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            console.print("[red]Unauthorized. Token may be expired.[/red]")
            console.print("[yellow]Run: uv run python cli.py login[/yellow]")
        else:
            console.print(f"[red]Error: {e.response.text}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def test_auth() -> None:
    """Full auth flow test: login -> me -> generate"""
    console.print("[yellow]Starting auth flow test...[/yellow]\n")

    # Step 1: Health check
    console.print("[blue]1. Checking API health...[/blue]")
    health()

    # Step 2: Login
    console.print("\n[blue]2. Logging in...[/blue]")
    login()

    # Step 3: Get user info
    console.print("\n[blue]3. Getting user info...[/blue]")
    me()

    # Step 4: Generate bookstore
    console.print("\n[blue]4. Generating test bookstore...[/blue]")
    generate("Create a bookstore in Paris")

    console.print("\n[green]✅ Auth flow test complete![/green]")


@app.command()
def logout() -> None:
    """Remove saved token"""
    try:
        import os

        os.remove(TOKEN_FILE)
        console.print("[green]Logged out successfully[/green]")
    except FileNotFoundError:
        console.print("[yellow]Already logged out[/yellow]")


@app.command()
def geocode(address: str) -> None:
    """Geocode an address to coordinates"""
    token = load_token()
    if not token:
        console.print("[red]Not logged in. Run: uv run python cli.py login[/red]")
        raise typer.Exit(1)

    console.print(f"[yellow]Geocoding: {address}[/yellow]")

    try:
        response = httpx.get(
            f"{BASE_URL}/geocode",
            params={"address": address},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()

        console.print(Panel(JSON(response.text), title="Geocoding Result", border_style="green"))
        lat = data['coordinates']['latitude']
        lon = data['coordinates']['longitude']
        console.print(f"\n[blue]Coordinates:[/blue] {lat}, {lon}")
        console.print(f"[blue]Address:[/blue] {data['address']['formatted_address']}")
        if data['address'].get('city'):
            console.print(f"[blue]City:[/blue] {data['address']['city']}")
        if data['address'].get('state'):
            console.print(f"[blue]State:[/blue] {data['address']['state']}")
        if data['address'].get('country'):
            console.print(f"[blue]Country:[/blue] {data['address']['country']}")

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            console.print("[red]Unauthorized. Token may be expired.[/red]")
            console.print("[yellow]Run: uv run python cli.py login[/yellow]")
        elif e.response.status_code == 404:
            console.print(f"[red]Address not found: {address}[/red]")
        else:
            console.print(f"[red]Error: {e.response.text}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def reverse(latitude: float, longitude: float) -> None:
    """Reverse geocode coordinates to address"""
    token = load_token()
    if not token:
        console.print("[red]Not logged in. Run: uv run python cli.py login[/red]")
        raise typer.Exit(1)

    console.print(f"[yellow]Reverse geocoding: {latitude}, {longitude}[/yellow]")

    try:
        response = httpx.get(
            f"{BASE_URL}/reverse",
            params={"lat": latitude, "lon": longitude},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()

        console.print(Panel(JSON(response.text), title="Reverse Geocoding Result", border_style="green"))
        console.print(f"\n[blue]Address:[/blue] {data['address']['formatted_address']}")
        if data['address'].get('city'):
            console.print(f"[blue]City:[/blue] {data['address']['city']}")
        if data['address'].get('state'):
            console.print(f"[blue]State:[/blue] {data['address']['state']}")
        if data['address'].get('postal_code'):
            console.print(f"[blue]Postal Code:[/blue] {data['address']['postal_code']}")
        if data['address'].get('country'):
            console.print(f"[blue]Country:[/blue] {data['address']['country']}")

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            console.print("[red]Unauthorized. Token may be expired.[/red]")
            console.print("[yellow]Run: uv run python cli.py login[/yellow]")
        elif e.response.status_code == 404:
            console.print(f"[red]Location not found: {latitude}, {longitude}[/red]")
        else:
            console.print(f"[red]Error: {e.response.text}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
