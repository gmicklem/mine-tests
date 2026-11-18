"""InterMine's JBrowse 1 REST Store endpoints and the JBrowse deployment
that reads them (intermineorg/jbrowse)."""
import pytest

from conftest import feature, require_locations


def jb(mine):
    return f"{mine.service}/jbrowse"


def test_track_list(http, mine):
    r = http.get(f"{jb(mine)}/config/{mine.taxon}/trackList.json")
    r.raise_for_status()
    body = r.json()
    tracks = body["tracks"]
    assert len(tracks) > 5
    assert any(t.get("type") == "SequenceTrack" for t in tracks), "no reference sequence track"
    assert any(t.get("query", {}).get("type") == "Gene" for t in tracks), "no Gene track"
    for t in tracks:
        assert t["baseUrl"].startswith(mine.webapp_url), f"track {t['label']} baseUrl {t['baseUrl']} is not the public URL"
    assert body["names"]["url"].startswith(mine.webapp_url)


def test_reference_sequences_include_fixture_chromosome(http, mine):
    require_locations(mine)
    r = http.get(f"{jb(mine)}/config/{mine.taxon}/seq/refSeqs.json")
    r.raise_for_status()
    refs = {x["name"]: x for x in r.json()}
    chrom = mine.gene["chromosome"]
    assert chrom in refs, f"{chrom} not in {sorted(refs)[:20]}"
    assert refs[chrom]["end"] > mine.gene["end"]


def test_features_in_gene_region(http, mine):
    require_locations(mine)
    g = mine.gene
    r = http.get(f"{jb(mine)}/{mine.taxon}/features/{g['chromosome']}",
                 params={"start": g["start"] - 1, "end": g["end"], "type": "Gene"})
    r.raise_for_status()
    body = r.json()
    assert body["wasSuccessful"]
    symbols = {f.get("symbol") for f in body["features"]}
    assert g["symbol"] in symbols, f"{g['symbol']} not among {sorted(map(str, symbols))}"
    hit = next(f for f in body["features"] if f.get("symbol") == g["symbol"])
    assert hit["end"] == g["end"], "interbase/1-based mismatch or location changed"


def test_reference_sequence_fetch(http, mine):
    require_locations(mine)
    g = mine.gene
    start, end = g["start"], g["start"] + 50
    r = http.get(f"{jb(mine)}/{mine.taxon}/features/{g['chromosome']}",
                 params={"start": start, "end": end, "reference": "true"})
    r.raise_for_status()
    feats = r.json()["features"]
    assert len(feats) == 1
    assert len(feats[0]["seq"]) == end - start
    assert set(feats[0]["seq"].upper()) <= set("ACGTN")


def test_stats(http, mine):
    require_locations(mine)
    g = mine.gene
    r = http.get(f"{jb(mine)}/{mine.taxon}/stats/global")
    r.raise_for_status()
    assert r.json()["featureCount"] > 1000
    r = http.get(f"{jb(mine)}/{mine.taxon}/stats/region/{g['chromosome']}",
                 params={"start": g["start"], "end": g["end"]})
    r.raise_for_status()
    assert r.json()["featureCount"] >= 1


def test_name_search(http, mine):
    require_locations(mine)
    g = mine.gene
    r = http.get(f"{jb(mine)}/names/{mine.taxon}", params={"equals": g["symbol"]})
    r.raise_for_status()
    hits = [h for h in r.json() if h["name"] == g["symbol"]]
    assert hits, "name search returned nothing"
    loc = hits[0]["location"]
    assert loc["ref"] == g["chromosome"]
    assert loc["end"] == g["end"]


def test_jbrowse_site(http, mine):
    url = feature(mine, "jbrowse")
    r = http.get(url)
    r.raise_for_status()
    assert "JBrowse" in r.text
    assert 'allowCrossOriginDataRoot": true' in r.text or "allowCrossOriginDataRoot&quot;: true" in r.text, \
        "allowCrossOriginDataRoot is not true; JBrowse will refuse the mine's data URL"
    assert "x-frame-options" not in {k.lower() for k in r.headers}, "X-Frame-Options would block the report-page iframe"
    for asset in ("dist/main.bundle.js",):
        a = http.head(url.rstrip("/") + "/" + asset, allow_redirects=True)
        assert a.ok, f"{asset} -> {a.status_code}"


def test_jbrowse2_site(http, mine):
    """The JBrowse 2 deployment: its config.json lists the InterMine plugin and this
    mine's assembly, and the page can be put in an iframe."""
    url = feature(mine, "jbrowse2")
    r = http.get(url)
    r.raise_for_status()
    assert "JBrowse" in r.text
    assert "x-frame-options" not in {k.lower() for k in r.headers}, "X-Frame-Options would block the report-page iframe"
    cfg = http.get(url.rstrip("/") + "/config.json")
    cfg.raise_for_status()
    conf = cfg.json()
    assert any(p.get("name") == "InterMine" for p in conf.get("plugins", [])), "config.json has no InterMine plugin"
    assemblies = [a["name"] for a in conf.get("assemblies", [])]
    assert any(a.endswith(f"-{mine.taxon}") for a in assemblies), f"no assembly for taxon {mine.taxon}: {assemblies}"
    assert conf.get("tracks"), "config.json has no tracks"
    plugin = http.head(url.rstrip("/") + "/jbrowse-plugin-intermine.umd.production.min.js", allow_redirects=True)
    assert plugin.ok, f"plugin bundle -> {plugin.status_code}"
