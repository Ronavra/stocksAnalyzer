"""Read only official current-report primary documents and earnings exhibits."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import re
import httpx


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
            result=await client.get(url)
            if result.is_error:
                raise RuntimeError(f"SEC earnings exhibit failed with HTTP {result.status_code}")
            if len(result.content)>8_000_000:
                raise RuntimeError("SEC earnings exhibit exceeds parser size limit")
            documents.append((url,result.text))
        return documents
