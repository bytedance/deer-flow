install:
	pnpm install

build:
	pnpm build

dev:
	pnpm dev

test:
	pnpm test

test-e2e:
	pnpm test:e2e

lint:
	pnpm lint

format:
	pnpm format:write

build-static:
	NEXT_CONFIG_BUILD_OUTPUT=standalone SKIP_ENV_VALIDATION=1 NEXT_PUBLIC_STATIC_WEBSITE_ONLY=true pnpm build
	@if [ -d .next/static ]; then mkdir -p .next/standalone/.next && cp -R .next/static .next/standalone/.next/static; fi
