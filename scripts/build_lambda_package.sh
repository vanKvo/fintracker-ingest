#!/usr/bin/env bash
# Builds build/package: the service code, its data files and its dependencies, for Terraform's archive.
# Run from services/fintracker-ingest. Lambda runs Linux x86_64, Python 3.12.
set -euo pipefail
rm -rf build/package && mkdir -p build/package
poetry export --without-hashes --format requirements.txt --output build/requirements.txt
pip install --quiet --target build/package --platform manylinux2014_x86_64 --implementation cp \
  --python-version 3.12 --only-binary=:all: -r build/requirements.txt
cp -r src seed build/package/
find build/package -name "__pycache__" -prune -exec rm -rf {} +
echo "Built build/package"
