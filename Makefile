.PHONY: install dev build lint typecheck clean

install:
	cd apps/web && npm install

dev:
	cd apps/web && npm run dev

build:
	cd apps/web && npm run build

lint:
	cd apps/web && npm run lint

typecheck:
	cd apps/web && npm run typecheck

clean:
	cd apps/web && rm -rf .next node_modules
