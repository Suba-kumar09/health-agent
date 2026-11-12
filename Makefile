.PHONY: run-server

run-server:
	uvicorn server.main:app --reload --port 8001
