# mine-tests

End-to-end checks for deployed InterMine instances: the web service, the
nginx front end, BlueGenes report pages, the tool store and the services
behind it (JBrowse, the sequence aligner, RCSB). InterMine and BlueGenes
have their own unit tests; this covers what those cannot, a running mine as
users see it. Run it before and after changing the backend, BlueGenes, a
tool, or the Docker deployment.

HumanMine, FlyMine and a local demo mine (`local`, see below) are configured
in [`mines.toml`](mines.toml); add a mine by adding a section there.

## Layout

| Path | What it checks | Needs |
|------|----------------|-------|
| `tests/service/test_webservice.py` | InterMine web service: version, model, a known gene by query and keyword search, templates, query schemas | Python only |
| `tests/service/test_frontend.py` | BlueGenes HTML, imjs available to tools, tool store list and files, favicon, classic webapp, no internal hostnames | Python only |
| `tests/service/test_jbrowse.py` | InterMine's JBrowse REST endpoints (track list, refseqs, features, sequence, stats, names) and the JBrowse site | Python only |
| `tests/service/test_tools.py` | Tool bundle patches, the `/align-sequence` route, RCSB v2 search for the fixture protein | Python only |
| `tests/browser/test_report_tools.py` | A gene report page in Chromium/Firefox/WebKit: every configured tool draws, no error text, no uncaught exceptions, RCSB v2 and aligner calls succeed, JBrowse iframe loads | Playwright |
| `tools/relay/relay.py` | Patch rehearsal: serve local files (e.g. a patched tool bundle) in place of a live site's, relay the rest | Python only |
| `.github/workflows/nightly.yml` | Runs everything daily against the configured mines | GitHub Actions |

Markers: `service`, `browser`, `external` (depends on a third party such as
RCSB), `patched` (checks the local bundle patches that docker_template
deployments apply; see that README, "BlueGenes tools that call dead
external services").

## Running

Service tests, from any machine with Python 3.11+:

```sh
git clone https://github.com/intermineorg/mine-tests.git
cd mine-tests
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
pytest tests/service                       # both mines, about a minute
pytest tests/service --mine flymine        # one mine
pytest tests/service -m "not external"     # skip third-party services
```

Browser tests, with Docker (no local browser installs):

```sh
./run-browser-tests.sh --browser chromium --browser firefox
./run-browser-tests.sh --browser chromium --mine humanmine -k jbrowse
```

Or natively after `playwright install chromium firefox`:

```sh
pytest tests/browser --browser chromium --browser firefox
```

Each report page takes one to two minutes to settle, once per mine and
browser; the individual tests then inspect what was captured. On failure a
screenshot and a Playwright trace are written under `test-results/` (open a
trace with `playwright show-trace <file>`).

Useful options:

| Option / variable | Effect |
|---|---|
| `--mine KEY` | test only this mine (repeatable) |
| `--config FILE` | another TOML file, e.g. for a staging mine |
| `--url-override KEY=URL` | replace a mine's public URL, e.g. to point at the relay or a local stack; the fixtures stay the same |
| `MINE_TESTS_PROXY=http://host:port` | browsers use this proxy (requests uses `HTTPS_PROXY` as usual); localhost and 127.0.0.1 bypass it, so a local mine works |
| `MINE_TESTS_IGNORE_TLS=1` | accept any certificate (proxied sandboxes, self-signed staging) |
| `MINE_TESTS_CDP=http://host:9222` | drive an already-running Chromium over the DevTools protocol instead of launching one |
| `MINE_TESTS_LOCAL_URL`, `MINE_TESTS_LOCAL_SERVICE_URL` | BlueGenes root and web service root of the `local` mine (see below) |
| `MINE_TESTS_BROWSER_PATH=/path/to/chromium` | launch this Chromium binary instead of Playwright's own (Chromium only; `run-browser-tests.sh` then runs natively instead of in Docker) |
| `MINE_TESTS_BROWSER_ARGS="--no-sandbox --disable-dev-shm-usage"` | extra Chromium command-line flags; `--disable-dev-shm-usage` is needed when `/dev/shm` is small (64 MB in some containers) |
| `MINE_TESTS_HTTP_TIMEOUT=120` | per-request timeout for the service tests, seconds |

## Mine options

Per mine in `mines.toml` (all optional except `url`, `webapp`, `taxon`):

| Key | Default | Effect |
|---|---|---|
| `service_url` | `<url>/<webapp>/service` | full web service root, when it is not under the BlueGenes URL; service tests use it, browser tests keep `url` |
| `has_locations` | `true` | `false` skips the JBrowse REST tests that need a chromosome (refseqs, features, sequence, stats, names) and drops chromosome/location from the fixture-gene query |
| `has_tool_store` | `true` | `false` skips the tool-store listing and the tool bundle patch tests |
| `min_templates` | `10` | the mine must publish at least this many templates |
| `jbrowse` | none | omit to skip the JBrowse site and iframe tests |
| `frontend.*` | none | docker_template nginx routes; omit or `false` to skip the matching tests |
| `gene.primary_identifier` / `gene.symbol` | none | how the fixture gene's object id is looked up at test start (primaryIdentifier preferred) |
| `gene.id` | none | fallback object id, used only when that lookup fails; ids change on rebuild |
| `gene.pdb` | none | omit to skip the RCSB structure check |

Any string in the file may use `${NAME}` or `${NAME:-default}`, read from the
environment when the file is loaded.

### The local demo mine

`[mines.local]` describes the [rdfc2im](https://github.com/intermine/rdfc2im)
demo mine (113 human genes, no chromosome locations, no JBrowse, no tool
store, no nginx front end) as run by its Docker stack: BlueGenes on
`http://localhost:5000`, web service on `http://localhost:8090/humanmine/service`.
For another host or port:

```sh
MINE_TESTS_LOCAL_URL=http://demo.example:5000 \
MINE_TESTS_LOCAL_SERVICE_URL=http://demo.example:8090/humanmine/service \
  pytest --mine local tests/service
```

The fixture gene is CYP2D6.  Its object id changes whenever the mine is
rebuilt, so the tests do not pin one: a session-scoped `gene_id` fixture looks
the gene up once per mine by `gene.primary_identifier` (else `gene.symbol`) and
the mine's `taxon`, through `/service/query/results`.  `gene.id` in
`mines.toml` is optional and only the fallback when that lookup cannot be done
(web service down, gene not found); the `local` mine configures none.  To test
a second local stack, for example the one on 18090/15000:

```sh
MINE_TESTS_LOCAL_URL=http://localhost:15000 \
MINE_TESTS_LOCAL_SERVICE_URL=http://localhost:18090/humanmine/service \
  pytest --mine local tests/service
```

The `local` mine has no tool store unless the stack has one: set
`MINE_TESTS_LOCAL_TOOL_STORE=true` for a BlueGenes started with
`BLUEGENES_TOOL_PATH` (the tool-store and `patched` bundle tests then run), and
`MINE_TESTS_LOCAL_ALIGN_SEQUENCE=true` when `/align-sequence` is routed on its
origin (the MSA bundle and route tests then run).  Unset, behaviour is as before.

Browser tests against it need the
CDN hosts BlueGenes loads scripts from (`cdn.intermine.org`,
`cdn.jsdelivr.net`, `code.jquery.com`, `cdnjs.cloudflare.com`); where they are
blocked, `test_imjs_present_for_tools`, `test_imjs_is_available` and
`test_page_scripts_load` fail by design.  `test_favicon` fails while the
deployment's BlueGenes redirects `/favicon.ico` to an internal Docker host name.

## Interpreting failures

- `test_frontend.py::test_imjs_present_for_tools` failing means every tool
  panel will be blank (`imjs is not defined`); fix the front end before
  looking at tools.
- `test_report_tools.py::test_page_scripts_load` failing means a CDN script
  (Vega, jQuery, Bootstrap) did not load; tools that need it then fail with
  what looks like a tool bug. In a firewalled environment allow
  `cdn.jsdelivr.net`, `cdnjs.cloudflare.com` and `code.jquery.com`.
- Headless Firefox in the Playwright image has no WebGL, so the protein
  visualizer cannot draw there; the tests report it as skipped, not failed,
  and still check that its RCSB request was made. Chromium has software
  WebGL and checks the structure list.
- `external` tests failing while everything else passes points at the third
  party, not the mine.
- The `patched` tests fail on a mine whose tool bundles were reinstalled
  from npm without re-applying the patches; the message says which patch.

## Rehearsing a change with the relay

To try a modified tool bundle against live data before deploying it:

```sh
mkdir -p patched/tools/@intermine/bluegenes-msa-viewer/dist
cp fixed-bundle.js patched/tools/@intermine/bluegenes-msa-viewer/dist/bundle.js
python3 tools/relay/relay.py https://www.humanmine.org patched 8099 &
pytest tests/browser --browser chromium --mine humanmine --url-override humanmine=http://localhost:8099
```

Anything under `patched/` whose path matches a request is served from
there; everything else comes from the real site. A browser can be pointed
at http://localhost:8099 for a manual look. (Features that depend on the
exact origin, such as cookies and same-origin checks against the public
hostname, behave differently through the relay.)

## Adding to the suite

- New mine: a `[mines.<key>]` section in `mines.toml` with a fixture gene
  whose data you have checked by hand, and the list of tool panels that
  render for it. Omit `jbrowse` or set `frontend.*` to false for features
  the deployment lacks.
- New check: a test function taking `http, mine` (service) or `report`
  (browser). Use `feature(mine, ...)` from `conftest.py` to skip cleanly when
  a mine does not configure what the test needs.
- A check for a BlueGenes or InterMine change under development: run the
  suite against the development instance with `--url-override` or a second
  config file, before and after.

## Findings so far

- FlyMine `Ubx` (and `bcd`, `ey`, `lab`, `pb`, `prd`, `Sxl`...): the protein
  visualizer and the MSA viewer both fail with "Failed to query for protein
  sequences". Some of the gene's proteins have no `primaryAccession`, the
  tools build one query per protein with `Protein.primaryAccession = <acc>`,
  and InterMine rejects the empty constraint with HTTP 400. Found by the
  first run of `test_report_tools.py` (October 2026); the fixture gene was
  changed to `Scr` so the suite stays green while the tools are unfixed.

## Background

Started in October 2026 after repairing HumanMine and FlyMine report pages:
the imjs script tag removed from BlueGenes, the protein visualizer calling a
retired RCSB API, the MSA viewer posting to a dead server and crashing in
modern browsers, the Firefox scrolling bug in the bundled `msa` library.
None of those would have been caught by the projects' own test suites; all
of them are caught here.

License: MIT.
