.PHONY: install dev adk-web server test lint typecheck hygiene eval docker-build tf-validate

install:
	python3 -m pip install -e ".[dev]"

dev:
	adk web --session_service_uri "$${SESSION_DB_URL:-sqlite+aiosqlite:///./pathfinder_sessions.db}" .

adk-web:
	adk web --session_service_uri "$${SESSION_DB_URL:-sqlite+aiosqlite:///./pathfinder_sessions.db}" .

server:
	python3 server.py

test:
	pytest -v evals/test_agent_evals.py

lint:
	ruff check app evals server.py

typecheck:
	mypy app

hygiene:
	python3 evals/check_repo_hygiene.py

eval:
	adk eval app evals/college_advisor.evalset.json --config_file_path evals/test_config.json --print_detailed_results

docker-build:
	docker build -t pathfinder-college-advisor:local .

tf-validate:
	cd deployment/terraform && terraform init -backend=false && terraform validate
