#!/bin/sh
# Run the browser tests in the official Playwright image, so no browsers need
# installing locally.  Extra arguments go to pytest, e.g.
#   ./run-browser-tests.sh --browser chromium --browser firefox --mine humanmine
# Environment passed through: MINE_TESTS_PROXY, MINE_TESTS_IGNORE_TLS,
# HTTP(S)_PROXY (for pip and the browsers), MINE_TESTS_HTTP_TIMEOUT.
#
# With MINE_TESTS_BROWSER_PATH=/path/to/chromium the tests run natively
# (no Docker) in the current Python environment, with Playwright driving that
# binary; MINE_TESTS_BROWSER_ARGS adds flags, e.g.
#   MINE_TESTS_BROWSER_PATH=/usr/bin/chromium \
#   MINE_TESTS_BROWSER_ARGS="--no-sandbox --disable-dev-shm-usage" \
#     ./run-browser-tests.sh --mine local
set -eu
IMAGE=mcr.microsoft.com/playwright/python:v1.58.0-noble   # keep in step with requirements.txt
cd "$(dirname "$0")"
mkdir -p test-results
if [ -n "${MINE_TESTS_BROWSER_PATH:-}" ]; then
  exec pytest tests/browser --screenshot only-on-failure --tracing retain-on-failure "$@"
fi
exec docker run --rm -v "$PWD:/work" -w /work \
  -e HTTPS_PROXY -e HTTP_PROXY -e NO_PROXY -e MINE_TESTS_PROXY -e MINE_TESTS_IGNORE_TLS -e MINE_TESTS_HTTP_TIMEOUT \
  "$IMAGE" bash -c 'pip install -q -r requirements.txt 2>&1 | grep -v -e "\[notice\]" -e WARNING || true
                    pytest tests/browser --screenshot only-on-failure --tracing retain-on-failure "$@"' -- "$@"
