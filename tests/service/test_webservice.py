"""The InterMine web service itself: the Java webapp behind <url>/<webapp>/service (or the mine's service_url)."""
import re

LOCATION_VIEW = " Gene.chromosome.primaryIdentifier Gene.chromosomeLocation.start Gene.chromosomeLocation.end"

GENE_QUERY = (
    '<query model="genomic" view="Gene.id Gene.symbol Gene.primaryIdentifier{location_view}">'
    '<constraint path="Gene.id" op="=" value="{id}"/></query>'
)


def test_version(http, mine):
    r = http.get(f"{mine.service}/version")
    r.raise_for_status()
    assert int(r.text.strip()) >= 30, "web service API version"


def test_release_and_intermine_version(http, mine):
    rel = http.get(f"{mine.service}/version/release")
    rel.raise_for_status()
    assert rel.text.strip().strip('"'), "release string is empty"
    im = http.get(f"{mine.service}/version/intermine")
    im.raise_for_status()
    assert re.match(r'"?\d+\.\d+', im.text.strip()), im.text


def test_model_has_core_classes(http, mine):
    r = http.get(f"{mine.service}/model", params={"format": "json"})
    r.raise_for_status()
    classes = r.json()["model"]["classes"]
    for cls in ("Gene", "Protein", "Organism", "Chromosome"):
        assert cls in classes, f"model lacks {cls}"


def test_web_properties(http, mine):
    r = http.get(f"{mine.service}/web-properties")
    r.raise_for_status()
    props = r.json()["web-properties"]
    assert props["project"]["title"], "project.title missing"


def test_query_fixture_gene(http, mine, gene_id):
    """The gene's identifiers always; its chromosome location only when the
    mine loads locations (has_locations) and the fixture records it."""
    g = mine.gene
    with_location = mine.has_locations and all(k in g for k in ("chromosome", "start", "end"))
    query = GENE_QUERY.format(id=gene_id, location_view=LOCATION_VIEW if with_location else "")
    r = http.get(f"{mine.service}/query/results", params={"query": query, "format": "json"})
    r.raise_for_status()
    body = r.json()
    assert body["wasSuccessful"], body.get("error")
    assert len(body["results"]) == 1, body["results"]
    row = body["results"][0]
    assert row[1] == g["symbol"]
    assert row[2] == g["primary_identifier"]
    if with_location:
        assert row[3] == g["chromosome"]
        assert row[4] == g["start"] and row[5] == g["end"], "chromosome location changed"


def test_keyword_search_finds_fixture_gene(http, mine, gene_id):
    r = http.get(f"{mine.service}/search", params={"q": mine.gene["symbol"], "format": "json"})
    r.raise_for_status()
    body = r.json()
    ids = [hit["id"] for hit in body["results"] if hit["type"] == "Gene"]
    assert gene_id in ids, f"keyword search for {mine.gene['symbol']} did not return the gene"


def test_templates_available(http, mine):
    r = http.get(f"{mine.service}/templates", params={"format": "json"})
    r.raise_for_status()
    n = len(r.json()["templates"])
    assert n >= mine.min_templates, f"{n} templates, expected at least {mine.min_templates} (min_templates)"


def test_fixture_gene_proteins(http, mine, gene_id):
    q = ('<query model="genomic" view="Gene.proteins.primaryAccession">'
         f'<constraint path="Gene.id" op="=" value="{gene_id}"/></query>')
    r = http.get(f"{mine.service}/query/results", params={"query": q, "format": "json"})
    r.raise_for_status()
    n = len(r.json()["results"])
    assert n >= mine.gene.get("min_proteins", 1), f"gene has {n} proteins"


def test_schemas_served_as_xml(http, mine):
    """InterMine fetches these from webapp.baseurl for every query; if the
    front end routes them to BlueGenes instead, queries silently stop
    validating (see docker_template nginx template)."""
    for name in ("query.xsd", "query.schema"):
        r = http.get(f"{mine.webapp_url}/webservice/{name}")
        r.raise_for_status()
        assert "html" not in r.headers.get("content-type", ""), f"{name} served as HTML"
