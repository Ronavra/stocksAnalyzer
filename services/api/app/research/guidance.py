"""Conservative range extraction from official releases, with reviewable evidence."""
import re
from html.parser import HTMLParser
from hashlib import sha256


class ReleaseText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]; self.hidden=0

    def handle_starttag(self,tag,attrs):
        if tag in ("script","style"):
            self.hidden+=1
        if tag in ("p","div","tr","li","h1","h2","h3","br"):
            self.parts.append("\n")

    def handle_endtag(self,tag):
        if tag in ("script","style") and self.hidden:
            self.hidden-=1
        if tag in ("p","div","tr","li"):
            self.parts.append("\n")

    def handle_data(self,text):
        if not self.hidden:
            self.parts.append(text)


def release_text(html):
    parser=ReleaseText(); parser.feed(html)
    return "\n".join(re.sub(r"\s+"," ",line).strip() for line in "".join(parser.parts).splitlines() if line.strip())


def extract_guidance(html,company_id,event):
    text=release_text(html)
    ranges=[]
    # Restrict this parser to explicitly named full fiscal years. Quarter,
    # growth-rate, margin and historical result ranges are not interchangeable.
    number=r"\$?\s*(-?\d+(?:\.\d+)?)"
    for line in text.splitlines():
        if len(line)>2500 or not re.search(r"\b(expect\w*|guidance|outlook|forecast\w*|project\w*)\b",line,re.I):
            continue
        if re.search(r"\b(no|not|withdraw\w*|suspend\w*)\b.{0,35}\b(guidance|outlook|forecast)\b",line,re.I):
            continue
        year_match=re.search(r"\b(?:full[- ]year|fiscal(?: year)?|FY)\s*(?:for\s*)?(20\d{2})\b|\b(20\d{2})\s+full[- ]year\b",line,re.I)
        if not year_match:
            continue
        year=int(year_match.group(1) or year_match.group(2))
        if not int(event["filing_date"][:4])-1 <= year <= int(event["filing_date"][:4])+2:
            continue
        # Require a labelled numeric interval, rather than inferring a value
        # from a financial table whose year / GAAP columns may be ambiguous.
        patterns={
            "eps":rf"(?P<method>adjusted|GAAP|diluted)?\s*(?:diluted\s+)?(?:EPS|earnings per (?:diluted )?share)\s+(?:guidance\s+)?(?:of\s+|in (?:the )?range (?:of )?|between\s+|to (?:be(?: in (?:the )?range (?:of )?)?|range)\s+|is\s+)?{number}\s*(?:to|and|[-–])\s*{number}",
            "revenue":rf"(?:revenue|sales)\s+(?:guidance\s+)?(?:of\s+|in (?:the )?range (?:of )?|between\s+|to (?:be(?: in (?:the )?range (?:of )?)?|range)\s+|is\s+)?{number}\s*(million|billion)?\s*(?:to|and|[-–])\s*{number}\s*(million|billion)",
        }
        for metric,pattern in patterns.items():
            match=re.search(pattern,line,re.I)
            if not match:
                continue
            groups=match.groups()
            if metric=="eps":
                method,low,high=groups; scale=1.; method=(method or "unspecified").lower()
            else:
                low,left_unit,high,right_unit=groups
                if left_unit and left_unit.lower()!=right_unit.lower():
                    continue
                scale=1e9 if right_unit.lower()=="billion" else 1e6; method="reported"
            low=float(low)*scale; high=float(high)*scale
            if low>high:
                continue
            ranges.append((year,metric,low,high,method,line[:700]))
    # Separate accounting methods; never mix GAAP and adjusted EPS. Multiple
    # contradictory ranges are left unparsed instead of choosing arbitrarily.
    out=[]
    for year,metric,low,high,method,evidence in sorted(set(ranges)):
        conflicts={(r[2],r[3]) for r in ranges if r[0]==year and r[1]==metric and r[4]==method}
        if len(conflicts)!=1:
            continue
        identity=f"{event['accession_number']}:{year}:{metric}:{method}:{low}:{high}"
        payload={"company_id":company_id,"event_date":event["filing_date"],"fiscal_year":year,"fiscal_period":"FY",
                 "release_type":"official_filing","source":"sec_release","source_record_id":sha256(identity.encode()).hexdigest(),
                 "captured_at":event["observed_at"],"published_at":event["published_at"],"source_url":event["source_url"],
                 "evidence":{"metric":metric,"excerpt":evidence,"parser":"explicit_annual_range_v1"},
                 "eps_method":method if metric=="eps" else None,"revenue_method":method if metric=="revenue" else None,
                 f"{metric}_guidance_low":low,f"{metric}_guidance_high":high}
        if not any(r["source_record_id"]==payload["source_record_id"] for r in out):
            out.append(payload)
    return out
