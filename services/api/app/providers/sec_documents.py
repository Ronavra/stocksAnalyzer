"""Read only official current-report primary documents and earnings exhibits."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import re
import httpx
from html import escape
from app.research.guidance import ReleaseText

MAX_DOCUMENT_BYTES=32_000_000
MAX_VISIBLE_CHARS=2_000_000


async def visible_document(client,url):
    # Inline images can make a short earnings release enormous. Bound the
    # decoded transfer AND visible text, while discarding image attributes,
    # scripts and styles incrementally instead of buffering the whole HTML.
    parser=ReleaseText(); chunks=[]; size=visible=0
    async with client.stream("GET",url) as response:
        if response.is_error:
            raise RuntimeError(f"SEC earnings exhibit failed with HTTP {response.status_code}")
        async for text in response.aiter_text():
            size+=len(text.encode("utf-8"))
            if size>MAX_DOCUMENT_BYTES:
                raise RuntimeError("SEC earnings exhibit exceeds bounded download limit")
            parser.feed(text)
            part="".join(parser.parts); parser.parts.clear()
            visible+=len(part)
            if visible>MAX_VISIBLE_CHARS:
                raise RuntimeError("SEC earnings exhibit exceeds visible-text limit")
            chunks.append(part)
        parser.close()
        tail="".join(parser.parts)
        if visible+len(tail)>MAX_VISIBLE_CHARS:
            raise RuntimeError("SEC earnings exhibit exceeds visible-text limit")
        chunks.append(tail)
    # Keep escaped line boundaries expected by the conservative range parser.
    return "<p>"+escape("".join(chunks)).replace("\n","</p><p>")+"</p>"


class ExhibitIndex(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_row=False; self.text=[]; self.links=[]; self.documents=[]

    def handle_starttag(self,tag,attrs):
        if tag=="tr":
            self.in_row=True; self.text=[]; self.links=[]
        if tag=="a" and self.in_row:
            self.links.extend(v for k,v in attrs if k=="href")

    def handle_data(self,text):
        if self.in_row:
            self.text.append(text)

    def handle_endtag(self,tag):
        if tag=="tr" and self.in_row:
            if re.search(r"\bEX-99(?:\.1)?\b", " ".join(self.text), re.I):
                self.documents.extend(self.links)
            self.in_row=False


async def release_documents(provider,event):
    parsed=urlparse(event["source_url"])
    if parsed.scheme!="https" or parsed.hostname!="www.sec.gov" or not parsed.path.startswith("/Archives/edgar/data/"):
        raise ValueError("Disclosure must have an official SEC archive URL")
    directory=event["source_url"].rsplit("/",1)[0]+"/"
    accession=event["accession_number"]
    urls=[event["source_url"]]
    async with httpx.AsyncClient(timeout=45,headers={"User-Agent":provider.user_agent}) as client:
        result=await client.get(directory+accession+"-index.html")
        if result.is_error:
            raise RuntimeError(f"SEC disclosure index failed with HTTP {result.status_code}")
        parser=ExhibitIndex(); parser.feed(result.text)
        for href in parser.documents:
            url=urljoin(directory,href)
            if url.startswith(directory) and url.lower().endswith((".htm",".html")) and url not in urls:
                urls.append(url)
        documents=[]
        for url in urls[:4]:
            documents.append((url,await visible_document(client,url)))
        return documents
