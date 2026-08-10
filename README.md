# hello

Petit projet Python de test, packagé avec `pyproject.toml` et un layout `src/`.

## Structure

```
test-python/
├── pyproject.toml       # métadonnées du package et dépendances
├── src/
│   └── hello/
│       ├── __init__.py
│       └── main.py      # point d'entrée : fonction main()
└── tests/
    └── test_main.py     # tests pytest
```

## Installation (venv + pip)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

## Utilisation

```bash
hello
# ou
python -m hello.main
```

## Tests

```bash
pytest
```
