"""Uploads (J11-5, B9): a file or tenderer name of "." or ".." is refused; a file is a PDF
by its bytes, not its name; a request over MAX_UPLOAD_MB, or without a length, is refused
before its body is read; and a refused request leaves none of its files, and no folder it
created, behind."""
from test.test_api import make_client

PDF = b"%PDF-1.4\n" + b"0" * 2000


def _post(client, path, *files):
    return client.post(path, files=[("files", (name, body, "application/pdf")) for name, body in files])


def _files(tmp_path, pid, *parts):
    folder = tmp_path.joinpath("data", "projects", pid, *parts)
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def test_dot_names_are_refused_as_tenderer_and_as_file(tmp_path, monkeypatch):
    import pytest
    from fastapi import HTTPException

    from backend import deps
    for name in (".", "..", "...", " .. ", "a/..", ""):
        with pytest.raises(HTTPException) as err:
            deps._safe_name(name)
        assert err.value.status_code == 400, name
    assert deps._safe_name("..offer.pdf") == "..offer.pdf" and deps._safe_name("x/../Tenderer B") == "Tenderer B"

    client = make_client(tmp_path, monkeypatch)
    pid = client.post("/projects", json={"name": "u"}).json()["id"]
    r = _post(client, f"/projects/{pid}/bids/%2E%2E", ("offer.pdf", PDF))       # ".." once the path is decoded
    assert r.status_code in (400, 404, 405)
    assert not (tmp_path / "data" / "projects" / pid / "offer.pdf").exists(), "nothing escaped the bids folder"
    assert _post(client, f"/projects/{pid}/tender", ("..", PDF)).status_code == 400


def test_a_pdf_is_known_by_its_bytes_and_a_refusal_leaves_nothing(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    pid = client.post("/projects", json={"name": "u"}).json()["id"]
    r = _post(client, f"/projects/{pid}/tender", ("terms.pdf", PDF), ("fake.pdf", b"MZ\x90\x00" + b"x" * 3000))
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request" and "fake.pdf is not a PDF" in r.text
    assert _files(tmp_path, pid, "tender") == [], "the good file of a refused request is not kept either"
    short = _post(client, f"/projects/{pid}/tender", ("short.pdf", b"not a pdf"))
    assert short.status_code == 400, "a file shorter than a kilobyte is checked too"
    junk_first = b"\x00" * 100 + PDF
    assert _post(client, f"/projects/{pid}/tender", ("terms.pdf", junk_first)).json() == {"saved": ["terms.pdf"]}
    assert _files(tmp_path, pid, "tender") == ["terms.pdf"], "the header may follow up to 1 KB of junk"


def test_a_refused_upload_for_a_new_tenderer_leaves_no_folder_to_count_as_a_bidder(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    pid = client.post("/projects", json={"name": "u"}).json()["id"]
    assert _post(client, f"/projects/{pid}/bids/Gamma", ("offer.pdf", b"not a pdf at all")).status_code == 400
    assert not (tmp_path / "data" / "projects" / pid / "bids" / "Gamma").exists()
    assert client.get(f"/projects/{pid}").json()["bidders"] == []


def test_a_request_over_the_cap_is_refused_before_its_body_is_read(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    monkeypatch.setenv("MAX_UPLOAD_MB", "0.001")                       # 1,049 bytes, the whole request
    pid = client.post("/projects", json={"name": "u"}).json()["id"]
    r = _post(client, f"/projects/{pid}/bids/Alpha", ("offer.pdf", PDF))
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large" and "the 0.001 MB limit" in r.text
    assert not (tmp_path / "data" / "projects" / pid / "bids" / "Alpha").exists(), "the route never ran"
    assert _post(client, f"/projects/{pid}/bids/Alpha", ("offer.pdf", PDF[:600])).status_code == 200
    assert client.post(f"/projects/{pid}/bids/Alpha/extraction").status_code != 413, "only the two upload routes"


def test_an_upload_without_a_length_is_refused(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    pid = client.post("/projects", json={"name": "u"}).json()["id"]

    def chunks():                                    # a generator body goes out chunked, with no Content-Length
        yield b"--x\r\nContent-Disposition: form-data; name=\"files\"; filename=\"t.pdf\"\r\n\r\n"
        yield PDF + b"\r\n--x--\r\n"
    r = client.post(f"/projects/{pid}/tender", content=chunks(), headers={"content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 411 and r.json()["error"]["code"] == "length_required"
