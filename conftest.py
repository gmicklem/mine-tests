"""Shared fixtures: mine configuration, an HTTP session, and Playwright
launch options that honour a proxy (needed when the tests run inside a
sandbox).  See README.md."""
import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import requests

# Playwright forces Chromium to send localhost traffic through a configured
# proxy, ignoring the proxy's bypass list, so a local mine behind
# MINE_TESTS_PROXY would get the proxy's 403.  Honour the bypass instead.
os.environ.setdefault("PLAYWRIGHT_DISABLE_FORCED_CHROMIUM_PROXIED_LOOPBACK", "1")

ROOT = Path(__file__).parent
TIMEOUT = float(os.environ.get("MINE_TESTS_HTTP_TIMEOUT", "60"))


@dataclass
class Mine:
    key: str
    url: str
    webapp: str
    taxon: int
    service_url: str | None = None
    jbrowse: str | None = None
    has_locations: bool = True      # chromosome locations are loaded
    has_tool_store: bool = True     # BlueGenes tool store with tools installed
    min_templates: int = 10         # templates the mine must publish (at least)
    frontend: dict = field(default_factory=dict)
    gene: dict = field(default_factory=dict)
    tools: dict = field(default_factory=dict)

    @property
    def service(self) -> str:
        """Web service root.  `service_url` when the mine's web service is not
        published under the BlueGenes URL, else <url>/<webapp>/service."""
        if self.service_url:
            return self.service_url.rstrip("/")
        return f"{self.url}/{self.webapp}/service"

    @property
    def webapp_url(self) -> str:
        """Root of the InterMine webapp (the service root without /service)."""
        svc = self.service
        return svc[: -len("/service")] if svc.endswith("/service") else svc

    def report(self, cls: str, obj_id) -> str:
        return f"{self.url}/{self.webapp}/report/{cls}/{obj_id}"

    def __str__(self) -> str:
        return self.key


def pytest_addoption(parser):
    parser.addoption("--config", default=str(ROOT / "mines.toml"),
                     help="TOML file describing the mines (default: mines.toml)")
    parser.addoption("--mine", action="append", default=[],
                     help="mine key from the config to test; repeatable; default all")
    parser.addoption("--url-override", action="append", default=[],
                     metavar="KEY=URL",
                     help="replace a mine's public url, e.g. humanmine=http://localhost:8099 "
                          "to point the tests at a relay or a staging copy")


_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand_env(value):
    """Replace ${NAME} / ${NAME:-default} in every string of a config value
    with the environment variable (or the default)."""
    if isinstance(value, str):
        def sub(m):
            got = os.environ.get(m.group(1), m.group(2))
            if got is None:
                raise pytest.UsageError(f"mines config refers to ${{{m.group(1)}}}, which is not set and has no default")
            return got
        return _ENV_REF.sub(sub, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def _load_mines(config) -> list[Mine]:
    with open(config.getoption("--config"), "rb") as fh:
        data = tomllib.load(fh)
    overrides = dict(o.split("=", 1) for o in config.getoption("--url-override"))
    wanted = config.getoption("--mine")
    mines = []
    for key, m in data["mines"].items():
        if wanted and key not in wanted:
            continue
        m = _expand_env(dict(m))
        for flag in ("has_locations", "has_tool_store"):     # "${VAR:-false}" arrives as a string
            if isinstance(m.get(flag), str):
                m[flag] = m[flag].strip().lower() in ("1", "true", "yes", "on")
        if key in overrides:
            m["url"] = overrides[key].rstrip("/")
        mines.append(Mine(key=key, **m))
    unknown = set(wanted) - set(data["mines"])
    if unknown:
        raise pytest.UsageError(f"unknown mine(s) {sorted(unknown)}; config has {sorted(data['mines'])}")
    return mines


def pytest_generate_tests(metafunc):
    if "mine" in metafunc.fixturenames:
        mines = _load_mines(metafunc.config)
        metafunc.parametrize("mine", mines, ids=[m.key for m in mines], scope="session")


def pytest_collection_modifyitems(items):
    """Mark tests by directory so `-m service` / `-m browser` work."""
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if "/tests/service/" in path:
            item.add_marker(pytest.mark.service)
        elif "/tests/browser/" in path:
            item.add_marker(pytest.mark.browser)


@pytest.fixture(scope="session")
def http():
    s = requests.Session()
    s.headers["User-Agent"] = "mine-tests (https://github.com/intermineorg/mine-tests)"
    if os.environ.get("MINE_TESTS_IGNORE_TLS") == "1":
        s.verify = False
        import urllib3
        urllib3.disable_warnings()
    orig = s.request

    def request(method, url, **kw):
        kw.setdefault("timeout", TIMEOUT)
        return orig(method, url, **kw)
    s.request = request
    return s


def _resolve_gene_id(http, mine: Mine) -> int:
    """InterMine object id of the mine's fixture gene, looked up by
    primaryIdentifier (else symbol) in the organism with the mine's taxon.
    Object ids change on every rebuild, so gene.id in the config is only the
    fallback for when the lookup cannot be done (the web service is down, or
    the gene is not found)."""
    g = mine.gene
    configured = g.get("id")
    if g.get("primary_identifier"):
        field, value = "primaryIdentifier", g["primary_identifier"]
    elif g.get("symbol"):
        field, value = "symbol", g["symbol"]
    else:
        if configured is None:
            pytest.fail(f"{mine.key}: gene needs primary_identifier, symbol or id")
        return configured
    query = (f'<query model="genomic" view="Gene.id">'
             f'<constraint path="Gene.{field}" op="=" value="{value}"/>'
             f'<constraint path="Gene.organism.taxonId" op="=" value="{mine.taxon}"/></query>')
    try:
        r = http.get(f"{mine.service}/query/results", params={"query": query, "format": "json"})
        r.raise_for_status()
        rows = r.json()["results"]
    except (requests.RequestException, ValueError, KeyError) as e:
        if configured is not None:
            return configured
        pytest.fail(f"{mine.key}: cannot look up Gene.{field} = {value} and gene.id is not configured: {e}")
    if len(rows) == 1:
        return rows[0][0]
    if configured is not None:
        return configured
    pytest.fail(f"{mine.key}: Gene.{field} = {value} matched {len(rows)} genes and gene.id is not configured")


@pytest.fixture(scope="session")
def gene_id(http, mine) -> int:
    """Object id of the fixture gene (report/Gene/<id>), resolved once per
    mine and session by Gene.primaryIdentifier or symbol."""
    return _resolve_gene_id(http, mine)


def feature(mine: Mine, section: str, name: str | None = None):
    """Return a configured feature value, skipping the test when the mine's
    config lacks or disables it.  feature(mine, "jbrowse"),
    feature(mine, "frontend", "imjs_vendor"), feature(mine, "gene", "pdb")."""
    value = getattr(mine, section)
    if name is not None:
        value = (value or {}).get(name)
    if not value:
        label = section if name is None else f"{section}.{name}"
        pytest.skip(f"{mine.key}: {label} not configured")
    return value


def require_locations(mine: Mine):
    """Skip unless the mine has chromosome locations and the fixture gene
    records where it is (gene.chromosome, start, end)."""
    if not mine.has_locations:
        pytest.skip(f"{mine.key}: has_locations = false (no chromosome locations loaded)")
    for name in ("chromosome", "start", "end"):
        feature(mine, "gene", name)


def require_tool_store(mine: Mine):
    """Skip when the mine's BlueGenes has no tool store / installed tools."""
    if not mine.has_tool_store:
        pytest.skip(f"{mine.key}: has_tool_store = false")


# ---- Playwright (tests/browser) -------------------------------------------
# pytest-playwright reads --browser (repeatable: chromium, firefox, webkit).
# These overrides add a proxy and relaxed TLS from the environment so the
# same tests run from a developer machine, CI, or a proxied sandbox.

@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args, browser_name):
    args = dict(browser_type_launch_args)
    # An existing Chromium instead of Playwright's own (MINE_TESTS_BROWSER_PATH),
    # for machines Playwright does not support.  MINE_TESTS_BROWSER_ARGS adds
    # command-line flags (space separated), e.g. "--no-sandbox --disable-dev-shm-usage".
    path = os.environ.get("MINE_TESTS_BROWSER_PATH")
    if path and browser_name == "chromium":
        args["executable_path"] = path
    extra = os.environ.get("MINE_TESTS_BROWSER_ARGS", "").split()
    if extra and browser_name == "chromium":
        args["args"] = list(args.get("args") or []) + extra
    proxy = os.environ.get("MINE_TESTS_PROXY")
    if proxy:
        args["proxy"] = {"server": proxy, "bypass": "localhost,127.0.0.1"}
    # Headless Firefox has no WebGL unless forced; the protein visualizer
    # (pv) needs it.  Ignored by the other browser types.
    args["firefox_user_prefs"] = {"webgl.force-enabled": True, "webgl.disabled": False,
                                  "layers.acceleration.disabled": True}
    return args


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    args = dict(browser_context_args)
    args["viewport"] = {"width": 1400, "height": 2400}
    if os.environ.get("MINE_TESTS_IGNORE_TLS") == "1":
        args["ignore_https_errors"] = True
    return args


@pytest.fixture(scope="session")
def browser(playwright, browser_type, browser_type_launch_args):
    """Launch a browser, or attach to one over the Chrome DevTools Protocol
    when MINE_TESTS_CDP is set (e.g. a Chromium container started with
    --remote-debugging-port, for environments that cannot download
    Playwright's own browsers)."""
    cdp = os.environ.get("MINE_TESTS_CDP")
    if cdp:
        b = playwright.chromium.connect_over_cdp(cdp)
    else:
        b = browser_type.launch(**browser_type_launch_args)
    yield b
    b.close()
