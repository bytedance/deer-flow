install:
	pnpm install

build:
	pnpm build

dev:
	pnpm dev

lint:
	pnpm lint

format:
	pnpm format:write

stop:
	@echo "Stopping Frontend..."
	@-pkill -f "next dev" 2>/dev/null || true
	@sleep 1
	@-pkill -9 -f "next dev" 2>/dev/null || true
	@echo "✓ Frontend stopped"