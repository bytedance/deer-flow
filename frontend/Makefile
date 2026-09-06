ifeq ($(OS),Windows_NT)
    PYTHON ?= python
else
    PYTHON ?= python3
endif

PNPM = $(PYTHON) ../scripts/pnpm.py

install:
	$(PNPM) install

build:
	$(PNPM) build

dev:
	$(PNPM) dev

test:
	$(PNPM) test

test-e2e:
	$(PNPM) test:e2e

lint:
	$(PNPM) lint

format:
	$(PNPM) format:write

build-static:
	NEXT_CONFIG_BUILD_OUTPUT=standalone SKIP_ENV_VALIDATION=1 NEXT_PUBLIC_STATIC_WEBSITE_ONLY=true $(PNPM) build
	@if [ -d .next/static ]; then mkdir -p .next/standalone/.next && cp -R .next/static .next/standalone/.next/static; fi
