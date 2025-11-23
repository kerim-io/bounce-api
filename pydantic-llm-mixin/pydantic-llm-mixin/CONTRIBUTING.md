# Contributing to Pydantic LLM Mixin

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

## Development Setup

1. Clone the repository:
```bash
git clone https://github.com/eyzaguirre-co/pydantic-llm-mixin.git
cd pydantic-llm-mixin
```

2. Install development dependencies:
```bash
pip install -e ".[dev]"
```

3. Set up your Groq API key:
```bash
export GROQ_API_KEY="your-api-key-here"
```

## Code Quality Standards

### Linting

Run ruff to check code quality:
```bash
ruff check --fix .
```

### Type Safety

This project follows Mari-OS type safety standards:
- All functions must have type annotations
- No `Any` types in public APIs
- Use `assert isinstance()` for runtime type narrowing
- Zero type warnings required

### Testing

Run the test suite:
```bash
pytest tests/ -v
```

All tests must pass before submitting a PR.

### Code Style

- **Concise over verbose** - Trust the LLM philosophy applies to code comments too
- **Fail-fast** - Use assertions and raise exceptions with full tracebacks
- **One execution path** - No fallbacks, no legacy branches
- **Delete before create** - Remove old code completely before adding new

## Pull Request Process

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes following the code quality standards
4. Run linting: `ruff check --fix .`
5. Run tests: `pytest tests/ -v`
6. Commit your changes: `git commit -m "feat: your feature description"`
7. Push to your fork: `git push origin feature/your-feature`
8. Open a Pull Request

### Commit Message Format

Use conventional commits:
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `refactor:` - Code refactoring
- `test:` - Test additions or changes
- `chore:` - Maintenance tasks

## Adding New Providers

To add a new LLM provider beyond Groq:

1. Create `src/pydantic_llm_mixin/providers/your_provider/` directory
2. Implement:
   - `models.py` - Request/response Pydantic models
   - `client.py` - Async client with retry logic and rate limiting
   - `__init__.py` - Public API exports
3. Update `factory.py` to support the new provider
4. Add tests in `tests/test_your_provider.py`
5. Update README.md with usage examples

## Questions?

Open an issue on GitHub for questions or discussions.

## Code of Conduct

Be respectful and constructive. This is a collaborative project.
