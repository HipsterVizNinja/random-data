"""Publish a .tdsx to Tableau Cloud (simple for small files, chunked for large)."""
import os
import requests
import tabapi

BOUNDARY = "b0undary0fthetableaupayload"
CHUNK = 16 * 1024 * 1024


def _multipart(parts):
    """parts: list of (name, filename|None, content_type, bytes)."""
    body = b""
    for name, filename, ctype, payload in parts:
        disp = f'name="{name}"'
        if filename:
            disp += f'; filename="{filename}"'
        body += (f"--{BOUNDARY}\r\nContent-Disposition: {disp}\r\n"
                 f"Content-Type: {ctype}\r\n\r\n").encode()
        body += payload + b"\r\n"
    body += f"--{BOUNDARY}--\r\n".encode()
    return body, f"multipart/mixed; boundary={BOUNDARY}"


def publish(token, site_id, project_id, name, tdsx_path, overwrite=True, description=None):
    size = os.path.getsize(tdsx_path)
    def attr(value):
        return (str(value).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace("'", "&apos;"))

    open_tag = f"<datasource name='{attr(name)}'"
    if description:
        open_tag += f" description='{attr(description)}'"
    payload = (f"<tsRequest>{open_tag}>"
               f"<project id='{project_id}' /></datasource></tsRequest>").encode()
    base = f"{tabapi.SERVER}/api/{tabapi.API}/sites/{site_id}"

    if size < 60 * 1024 * 1024:
        body, ctype = _multipart([
            ("request_payload", None, "text/xml", payload),
            ("tableau_datasource", os.path.basename(tdsx_path), "application/octet-stream",
             open(tdsx_path, "rb").read()),
        ])
        url = f"{base}/datasources?datasourceType=tdsx&overwrite={str(overwrite).lower()}"
        r = requests.post(url, data=body,
                          headers={**tabapi.hdr(token), "Content-Type": ctype})
        return r

    r = requests.post(f"{base}/fileUploads", headers=tabapi.hdr(token))
    r.raise_for_status()
    session = r.json()["fileUpload"]["uploadSessionId"]
    sent = 0
    with open(tdsx_path, "rb") as fh:
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            body, ctype = _multipart([
                ("request_payload", None, "text/xml", b""),
                ("tableau_file", "chunk", "application/octet-stream", chunk),
            ])
            rr = requests.put(f"{base}/fileUploads/{session}", data=body,
                              headers={**tabapi.hdr(token), "Content-Type": ctype})
            rr.raise_for_status()
            sent += len(chunk)
            print(f"  uploaded {sent/1e6:.0f} MB / {size/1e6:.0f} MB", flush=True)
    body, ctype = _multipart([("request_payload", None, "text/xml", payload)])
    url = (f"{base}/datasources?uploadSessionId={session}&datasourceType=tdsx"
           f"&overwrite={str(overwrite).lower()}")
    return requests.post(url, data=body,
                         headers={**tabapi.hdr(token), "Content-Type": ctype})
