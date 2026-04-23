.PHONY: dev install export db-shell preview docker

dev:
	FLASK_DEBUG=1 python3 server.py

install:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

export:
	python data/export.py

db-shell:
	sqlite3 data/literarnimapa.db

preview:
	open http://localhost:8000 && python3 -m http.server 8000

docker:
	docker build -t literarnimapa . && open http://localhost:8080 && docker run --rm -p 8080:80 literarnimapa
