# Pydantic LLM Mixin - Development Makefile
# Follows Mari-OS patterns for consistency

# Get the directory where this Makefile lives
MAKEFILE_DIR := $(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))

.PHONY: help setup install install-dev test test-verbose lint lint-fix type-check quality check-quality fix-quality clean build publish dep-status dep-upgrade deploy-railway railway-local railway-docker railway-build railway-stop health run-demo

# ============================================================================
# COLORS & DEFAULTS
# ============================================================================

BLUE := \033[34m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
RESET := \033[0m

.DEFAULT_GOAL := help

# ============================================================================
# HELP
# ============================================================================

help: ## Show this help message
	@echo "$(BLUE)Pydantic LLM Mixin - Development Commands$(RESET)"
	@echo "$(BLUE)==========================================$(RESET)"
	@echo ""
	@echo "$(YELLOW)🚀 Quick Start:$(RESET)"
	@echo "  1. $(GREEN)make setup$(RESET)          - Setup development environment"
	@echo "  2. $(GREEN)make test$(RESET)           - Run tests"
	@echo "  3. $(GREEN)make quality$(RESET)        - Check code quality (lint + type)"
	@echo ""
	@echo "$(YELLOW)📦 Setup & Installation:$(RESET)"
	@echo "$(GREEN)  make setup              $(RESET) Setup development environment (UV, dependencies)"
	@echo "$(GREEN)  make install            $(RESET) Install package only"
	@echo "$(GREEN)  make install-dev        $(RESET) Install package with dev dependencies"
	@echo "$(GREEN)  make install-from-github$(RESET) Install from private GitHub repo (requires GITHUB_TOKEN)"
	@echo ""
	@echo "$(YELLOW)🧪 Testing:$(RESET)"
	@echo "$(GREEN)  make test           $(RESET) Run tests with pytest"
	@echo "$(GREEN)  make test-verbose   $(RESET) Run tests with verbose output"
	@echo ""
	@echo "$(YELLOW)✨ Code Quality:$(RESET)"
	@echo "$(GREEN)  make quality        $(RESET) Run all quality checks (lint + type)"
	@echo "$(GREEN)  make lint           $(RESET) Check code with ruff"
	@echo "$(GREEN)  make lint-fix       $(RESET) Auto-fix with ruff"
	@echo "$(GREEN)  make type-check     $(RESET) Run type checking (if available)"
	@echo "$(GREEN)  make check-quality  $(RESET) Alias for 'make quality'"
	@echo "$(GREEN)  make fix-quality    $(RESET) Auto-fix then check quality"
	@echo ""
	@echo "$(YELLOW)🏗️  Build & Publish:$(RESET)"
	@echo "$(GREEN)  make build          $(RESET) Build distribution packages"
	@echo "$(GREEN)  make publish        $(RESET) Publish to PyPI (requires credentials)"
	@echo ""
	@echo "$(YELLOW)🚂 Railway Deployment:$(RESET)"
	@echo "$(GREEN)  make railway-local  $(RESET) Run locally with Railway environment variables"
	@echo "$(GREEN)  make railway-docker $(RESET) Run Docker with Railway env vars (hot reload)"
	@echo "$(GREEN)  make railway-build  $(RESET) Build Docker image with Railway env vars"
	@echo "$(GREEN)  make deploy-railway $(RESET) Deploy to Railway"
	@echo "$(GREEN)  make health         $(RESET) Check Railway deployment health"
	@echo ""
	@echo "$(YELLOW)📚 Dependencies:$(RESET)"
	@echo "$(GREEN)  make dep-status     $(RESET) Show dependency status"
	@echo "$(GREEN)  make dep-upgrade    $(RESET) Upgrade all dependencies"
	@echo ""
	@echo "$(YELLOW)🧹 Cleanup:$(RESET)"
	@echo "$(GREEN)  make clean          $(RESET) Remove build artifacts and caches"
	@echo ""

# ============================================================================
# SETUP & INSTALLATION
# ============================================================================

setup: ## Setup development environment (UV, Claude CLI, Railway CLI)
	@echo "$(BLUE)Setting up development environment...$(RESET)"
	@echo ""
	@echo "$(YELLOW)Detecting OS...$(RESET)"
	@OS_TYPE=$$(uname -s); \
	if [ "$$OS_TYPE" = "Darwin" ]; then \
		echo "$(GREEN)Detected macOS$(RESET)"; \
		PACKAGE_MANAGER="brew"; \
	elif [ "$$OS_TYPE" = "Linux" ]; then \
		echo "$(GREEN)Detected Linux$(RESET)"; \
		if command -v apt-get >/dev/null 2>&1; then \
			PACKAGE_MANAGER="apt"; \
		elif command -v yum >/dev/null 2>&1; then \
			PACKAGE_MANAGER="yum"; \
		else \
			echo "$(RED)Unsupported Linux distribution$(RESET)"; \
			exit 1; \
		fi; \
	else \
		echo "$(RED)Unsupported OS: $$OS_TYPE$(RESET)"; \
		exit 1; \
	fi; \
	echo ""; \
	echo "$(YELLOW)Installing UV...$(RESET)"; \
	if command -v uv >/dev/null 2>&1; then \
		echo "$(GREEN)UV already installed$(RESET)"; \
		uv --version; \
	else \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
		echo "$(GREEN)UV installed$(RESET)"; \
	fi; \
	echo ""; \
	echo "$(YELLOW)Installing Railway CLI...$(RESET)"; \
	if command -v railway >/dev/null 2>&1; then \
		echo "$(GREEN)Railway CLI already installed$(RESET)"; \
		railway --version; \
	else \
		if [ "$$PACKAGE_MANAGER" = "brew" ]; then \
			brew install railway; \
		else \
			echo "$(YELLOW)Installing Railway via npm (requires Node.js)...$(RESET)"; \
			if ! command -v npm >/dev/null 2>&1; then \
				echo "$(RED)npm not found - install Node.js first$(RESET)"; \
				echo "$(YELLOW)Visit: https://nodejs.org/$(RESET)"; \
				exit 1; \
			fi; \
			npm install -g @railway/cli; \
		fi; \
		echo "$(GREEN)Railway CLI installed$(RESET)"; \
	fi; \
	echo ""; \
	echo "$(YELLOW)Installing Claude Code...$(RESET)"; \
	if command -v claude >/dev/null 2>&1; then \
		echo "$(GREEN)Claude Code already installed$(RESET)"; \
		claude --version; \
	else \
		if [ "$$PACKAGE_MANAGER" = "brew" ]; then \
			brew install --cask claude-code; \
		else \
			curl -fsSL https://claude.ai/install.sh | bash; \
		fi; \
		echo "$(GREEN)Claude Code installed$(RESET)"; \
	fi; \
	echo ""; \
	echo "$(YELLOW)Installing Python dependencies...$(RESET)"; \
	$(MAKE) install-dev; \
	echo ""; \
	echo "$(GREEN)✅ Development environment ready!$(RESET)"; \
	echo ""; \
	echo "$(YELLOW)Next steps:$(RESET)"; \
	echo "  1. Set GROQ_API_KEY: export GROQ_API_KEY='your-key-here'"; \
	echo "  2. Login to Railway: railway login"; \
	echo "  3. Login to Claude: claude login"; \
	echo "  4. Run tests: make test"

install: ## Install package only
	@echo "$(BLUE)Installing pydantic-llm-mixin...$(RESET)"
	@uv pip install -e .
	@echo "$(GREEN)Package installed$(RESET)"

install-dev: ## Install package with dev dependencies
	@echo "$(BLUE)Installing pydantic-llm-mixin with dev dependencies...$(RESET)"
	@uv pip install -e ".[dev]"
	@echo "$(GREEN)Package and dev dependencies installed$(RESET)"

install-from-github: ## Install from GitHub (requires GITHUB_TOKEN)
	@echo "$(BLUE)Installing pydantic-llm-mixin from GitHub (private repo)...$(RESET)"
	@if [ -z "$$GITHUB_TOKEN" ]; then \
		echo "$(RED)ERROR: GITHUB_TOKEN not set$(RESET)"; \
		echo "$(YELLOW)Set your GitHub token:$(RESET)"; \
		echo "  export GITHUB_TOKEN='ghp_your_token_here'"; \
		echo ""; \
		echo "$(YELLOW)Get a token at: https://github.com/settings/tokens$(RESET)"; \
		echo "$(YELLOW)Required scopes: repo (for private repos)$(RESET)"; \
		exit 1; \
	fi
	@echo "$(YELLOW)Installing from GitHub with authentication...$(RESET)"
	@uv pip install "git+https://$$GITHUB_TOKEN@github.com/aceeyz/pydantic-llm-mixin.git"
	@echo "$(GREEN)Package installed from GitHub$(RESET)"

# ============================================================================
# TESTING
# ============================================================================

test: ## Run tests with pytest
	@echo "$(BLUE)Running tests...$(RESET)"
	@if [ -z "$$GROQ_API_KEY" ]; then \
		echo "$(YELLOW)Warning: GROQ_API_KEY not set - some tests will be skipped$(RESET)"; \
	fi
	@uv run pytest tests/ -v
	@echo "$(GREEN)Tests complete$(RESET)"

test-verbose: ## Run tests with verbose output
	@echo "$(BLUE)Running tests (verbose)...$(RESET)"
	@if [ -z "$$GROQ_API_KEY" ]; then \
		echo "$(YELLOW)Warning: GROQ_API_KEY not set - some tests will be skipped$(RESET)"; \
	fi
	@uv run pytest tests/ -vv -s
	@echo "$(GREEN)Tests complete$(RESET)"

# ============================================================================
# CODE QUALITY
# ============================================================================

quality: lint type-check ## Run all quality checks (lint + type)
	@echo "$(GREEN)✅ All quality checks passed$(RESET)"

check-quality: quality ## Alias for 'make quality'

lint: ## Check code with ruff
	@echo "$(BLUE)Running ruff check...$(RESET)"
	@uv run ruff check .
	@echo "$(GREEN)Linting complete$(RESET)"

lint-fix: ## Auto-fix with ruff
	@echo "$(BLUE)Running ruff check --fix...$(RESET)"
	@uv run ruff check --fix .
	@echo "$(GREEN)Auto-fix complete$(RESET)"

type-check: ## Run type checking with ty
	@echo "$(BLUE)Running ty check...$(RESET)"
	@uv run ty check
	@echo "$(GREEN)Type checking complete$(RESET)"

fix-quality: lint-fix quality ## Auto-fix then check quality
	@echo "$(GREEN)✅ Quality fixes applied and verified$(RESET)"

# ============================================================================
# BUILD & PUBLISH
# ============================================================================

build: clean ## Build distribution packages
	@echo "$(BLUE)Building distribution packages...$(RESET)"
	@uv pip install build
	@python -m build
	@echo "$(GREEN)Build complete$(RESET)"
	@echo "$(YELLOW)Artifacts in dist/$(RESET)"
	@ls -lh dist/

publish: build ## Publish to PyPI (requires credentials)
	@echo "$(BLUE)Publishing to PyPI...$(RESET)"
	@echo "$(YELLOW)Ensure you have configured PyPI credentials$(RESET)"
	@uv pip install twine
	@python -m twine upload dist/*
	@echo "$(GREEN)Published to PyPI$(RESET)"

# ============================================================================
# RAILWAY DEPLOYMENT
# ============================================================================

railway-local: ## Run locally with Railway environment variables
	@echo "$(BLUE)🚂 Running locally with Railway environment...$(RESET)"
	@if ! command -v railway >/dev/null 2>&1; then \
		echo "$(RED)Railway CLI not installed$(RESET)"; \
		echo "$(YELLOW)Install: npm i -g @railway/cli$(RESET)"; \
		exit 1; \
	fi
	@echo "$(YELLOW)Starting FastAPI server with Railway env vars on port 8200...$(RESET)"
	@railway run uv run uvicorn examples.railway_deployment:app --host 0.0.0.0 --port 8200 --reload

railway-docker: ## Run Docker with Railway env vars
	@echo "$(BLUE)🚂 Running Docker with Railway environment...$(RESET)"
	@if ! command -v railway >/dev/null 2>&1; then \
		echo "$(RED)Railway CLI not installed$(RESET)"; \
		echo "$(YELLOW)Install: npm i -g @railway/cli$(RESET)"; \
		exit 1; \
	fi
	@echo "$(YELLOW)Stopping old containers...$(RESET)"
	@docker stop bookstore-test 2>/dev/null || true
	@echo "$(YELLOW)Starting Docker container with Railway env vars...$(RESET)"
	@railway run sh -c 'docker run --rm -d \
		-p 8200:8200 \
		-e GROQ_API_KEY="$$GROQ_API_KEY" \
		-e PORT=8200 \
		--name bookstore-test \
		pydantic-llm-mixin:latest'
	@sleep 3
	@echo "$(GREEN)FastAPI running at http://localhost:8200$(RESET)"
	@echo "$(YELLOW)Logs: docker logs -f bookstore-test$(RESET)"
	@echo "$(YELLOW)Stop: make railway-stop$(RESET)"

railway-stop: ## Stop Railway Docker container
	@echo "$(BLUE)Stopping Docker container...$(RESET)"
	@docker stop bookstore-test 2>/dev/null || true
	@echo "$(GREEN)Container stopped$(RESET)"

railway-build: ## Build Docker image with Railway env vars
	@echo "$(BLUE)🚂 Building Docker image with Railway environment...$(RESET)"
	@if ! command -v railway >/dev/null 2>&1; then \
		echo "$(RED)Railway CLI not installed$(RESET)"; \
		echo "$(YELLOW)Install: npm i -g @railway/cli$(RESET)"; \
		exit 1; \
	fi
	@echo "$(YELLOW)Building Docker image with Railway environment variables...$(RESET)"
	@railway run sh -c 'docker build \
		--build-arg GROQ_API_KEY="$$GROQ_API_KEY" \
		--build-arg PORT=8200 \
		-t pydantic-llm-mixin:latest .'
	@echo "$(GREEN)Docker build complete$(RESET)"
	@echo ""
	@echo "$(YELLOW)Test the image:$(RESET)"
	@echo "  railway run docker run --rm -p 8200:8200 pydantic-llm-mixin:latest"

deploy-railway: ## Deploy to Railway
	@echo "$(BLUE)🚂 Deploying to Railway...$(RESET)"
	@if ! command -v railway >/dev/null 2>&1; then \
		echo "$(RED)Railway CLI not installed$(RESET)"; \
		echo "$(YELLOW)Install: npm i -g @railway/cli$(RESET)"; \
		exit 1; \
	fi
	@echo "$(YELLOW)Pushing to GitHub (triggers Railway deployment)...$(RESET)"
	@git push origin main
	@echo "$(GREEN)Deployment triggered$(RESET)"
	@echo "$(YELLOW)Monitor logs: railway logs$(RESET)"

health: ## Check Railway deployment health
	@echo "$(BLUE)Checking Railway deployment health...$(RESET)"
	@if ! command -v railway >/dev/null 2>&1; then \
		echo "$(RED)Railway CLI not installed$(RESET)"; \
		exit 1; \
	fi
	@railway status
	@echo ""
	@echo "$(YELLOW)View logs: railway logs$(RESET)"

# ============================================================================
# DEPENDENCIES
# ============================================================================

dep-status: ## Show dependency status
	@echo "$(BLUE)Dependency Status$(RESET)"
	@echo "$(BLUE)=================$(RESET)"
	@echo ""
	@echo "$(YELLOW)Installed packages:$(RESET)"
	@uv pip list
	@echo ""
	@echo "$(YELLOW)Outdated packages:$(RESET)"
	@uv pip list --outdated || echo "$(GREEN)All packages up to date$(RESET)"

dep-upgrade: ## Upgrade all dependencies
	@echo "$(BLUE)Upgrading dependencies...$(RESET)"
	@echo "$(YELLOW)Removing version pins from pyproject.toml...$(RESET)"
	@python3 -c "import re; \
		content = open('$(MAKEFILE_DIR)/pyproject.toml').read(); \
		updated = re.sub(r'\"([a-z0-9_-]+)>=[\\d.a-z]+\"', r'\"\\1\"', content); \
		open('$(MAKEFILE_DIR)/pyproject.toml', 'w').write(updated)"
	@echo "$(YELLOW)Running uv pip install --upgrade...$(RESET)"
	@uv pip install --upgrade -e ".[dev]"
	@echo "$(GREEN)Dependencies upgraded$(RESET)"
	@echo "$(YELLOW)Commit changes:$(RESET)"
	@echo "  git add pyproject.toml"
	@echo "  git commit -m 'chore: upgrade dependencies'"

# ============================================================================
# CLEANUP
# ============================================================================

clean: ## Remove build artifacts and caches
	@echo "$(YELLOW)Cleaning build artifacts and caches...$(RESET)"
	@echo "$(BLUE)Removing __pycache__ directories...$(RESET)"
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@echo "$(BLUE)Removing .pyc files...$(RESET)"
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "$(BLUE)Removing .pytest_cache...$(RESET)"
	@rm -rf .pytest_cache 2>/dev/null || true
	@echo "$(BLUE)Removing .ruff_cache...$(RESET)"
	@rm -rf .ruff_cache 2>/dev/null || true
	@echo "$(BLUE)Removing build artifacts...$(RESET)"
	@rm -rf build/ dist/ *.egg-info 2>/dev/null || true
	@echo "$(GREEN)Clean complete$(RESET)"

# ============================================================================
# CLI TOOLS
# ============================================================================

cli-login: ## Login to API and save JWT token
	@echo "$(BLUE)🔐 Logging in to API...$(RESET)"
	@uv run python cli.py login

cli-generate: ## Generate a bookstore (requires login first)
	@echo "$(BLUE)🏪 Generating bookstore...$(RESET)"
	@uv run python cli.py generate "Create a bookstore in Paris"

cli-test: ## Run full auth flow test
	@echo "$(BLUE)🧪 Running auth flow test...$(RESET)"
	@uv run python cli.py test-auth

run-demo: ## Run geocoding demo with Railway environment variables
	@echo "$(BLUE)📍 Running geocoding demo...$(RESET)"
	@if ! command -v railway >/dev/null 2>&1; then \
		echo "$(RED)Railway CLI not installed$(RESET)"; \
		echo "$(YELLOW)Install: npm i -g @railway/cli$(RESET)"; \
		exit 1; \
	fi
	@echo "$(YELLOW)Starting demo server with Railway env vars on http://localhost:8200/demo$(RESET)"
	@railway run uv run uvicorn examples.geocoding_api:app --host 0.0.0.0 --port 8200
