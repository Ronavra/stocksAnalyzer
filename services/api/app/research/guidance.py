"""Conservative range extraction from official releases, with reviewable evidence."""
import re
from html.parser import HTMLParser
from hashlib import sha256

PARSER_VERSION="explicit_fiscal_range_v3"


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
        fiscal_period='FY'
        quarter_match=re.search(r'\bQ([1-4])\s*(?:of\s*)?(?:fiscal(?: year)?|FY)\s*(20\d{2})\b|\b(first|second|third|fourth) quarter\s+(?:of\s+)?fiscal(?: year)?\s+(20\d{2})\b',line,re.I)
        has_quarter=bool(re.search(r"\bquarter(?:ly)?\b|\bQ[1-4]\b",line,re.I))
        if has_quarter:
            if not quarter_match or re.search(r'full[- ]year',line,re.I): continue
            fiscal_period='Q'+(quarter_match.group(1) or str(('first','second','third','fourth').index(quarter_match.group(3).lower())+1))
        year_match=re.search(r"\b(?:full[- ]year|fiscal(?: year)?|FY)\s*(?:for\s*)?(20\d{2})\b|\b(20\d{2})\s+full[- ]year\b",line,re.I)
        if not year_match and not quarter_match:
            continue
        year=int((quarter_match.group(2) or quarter_match.group(4)) if has_quarter else (year_match.group(1) or year_match.group(2)))
        if not int(event["filing_date"][:4])-1 <= year <= int(event["filing_date"][:4])+2:
            continue
        # Require a labelled numeric interval, rather than inferring a value
        # from a financial table whose year / GAAP columns may be ambiguous.
        patterns={
            "eps":rf"(?P<method>adjusted|GAAP|diluted)?\s*(?:diluted\s+)?(?:EPS|earnings per (?:diluted )?share)\s+(?:guidance\s+)?(?:of\s+|in (?:the )?range (?:of )?|between\s+|to (?:be(?: in (?:the )?range(?: of)?)?|range)\s+|is\s+)?{number}\s*(?:to|and|[-–])\s*{number}",
            "revenue":rf"(?:revenue|sales)\s+(?:guidance\s+)?(?:of\s+|in (?:the )?range (?:of )?|between\s+|to (?:be(?: in (?:the )?range(?: of)?)?|range)\s+|is\s+)?{number}\s*(million|billion)?\s*(?:to|and|[-–])\s*{number}\s*(million|billion)",
        }
        revision_prefix=r"\s+(?:expectations|guidance|forecast)\s+from (?:a )?range (?:of )?"
        next_range=r"\s+to (?:a )?range (?:of )?"
        revision_patterns={
            "eps":rf"(?P<method>adjusted|GAAP|diluted)?\s*(?:diluted\s+)?(?:EPS|earnings per (?:diluted )?share){revision_prefix}{number}\s+to\s+{number}{next_range}{number}\s+to\s+{number}",
            "revenue":rf"(?:revenue|sales){revision_prefix}{number}\s*(million|billion)?\s+to\s+{number}\s*(million|billion){next_range}{number}\s*(million|billion)?\s+to\s+{number}\s*(million|billion)",
        }
        for metric,pattern in patterns.items():
            previous_low=previous_high=None
            revision=re.search(revision_patterns[metric],line,re.I)
            if revision:
                if metric=="eps":
                    method,previous_low,previous_high,low,high=revision.groups()
                    scale=1.; method=(method or "unspecified").lower()
                else:
                    previous_low,old_left,previous_high,old_right,low,left_unit,high,right_unit=revision.groups()
                    if old_left and old_left.lower()!=old_right.lower() or left_unit and left_unit.lower()!=right_unit.lower():
                        continue
                    old_scale=1e9 if old_right.lower()=="billion" else 1e6
                    previous_low=float(previous_low)*old_scale; previous_high=float(previous_high)*old_scale
                    scale=1e9 if right_unit.lower()=="billion" else 1e6; method="reported"
                low=float(low)*scale; high=float(high)*scale
                previous_low=float(previous_low); previous_high=float(previous_high)
                if low<=high and previous_low<=previous_high:
                    ranges.append((year,metric,low,high,method,line[:700],previous_low,previous_high,fiscal_period))
                continue
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
            ranges.append((year,metric,low,high,method,line[:700],None,None,fiscal_period))
    # Separate accounting methods; never mix GAAP and adjusted EPS. Multiple
    # contradictory ranges are left unparsed instead of choosing arbitrarily.
    out=[]
    for year,metric,low,high,method,evidence,previous_low,previous_high,fiscal_period in sorted(set(ranges),key=lambda r:tuple(str(x) for x in r)):
        conflicts={(r[2],r[3]) for r in ranges if r[0]==year and r[1]==metric and r[4]==method and r[8]==fiscal_period}
        if len(conflicts)!=1:
            continue
        identity=f"{event['accession_number']}:{year}:{metric}:{method}:{low}:{high}"+('' if fiscal_period=='FY' else ':'+fiscal_period)
        payload={"company_id":company_id,"event_date":event["filing_date"],"fiscal_year":year,"fiscal_period":fiscal_period,
                 "release_type":"official_filing","source":"sec_release","source_record_id":sha256(identity.encode()).hexdigest(),
                 "captured_at":event["observed_at"],"published_at":event["published_at"],"source_url":event["source_url"],
                 "evidence":{"metric":metric,"excerpt":evidence,"parser":PARSER_VERSION},
                 "eps_method":method if metric=="eps" else None,"revenue_method":method if metric=="revenue" else None,
                 f"{metric}_guidance_low":low,f"{metric}_guidance_high":high,
                 f"previous_{metric}_guidance_low":previous_low,f"previous_{metric}_guidance_high":previous_high}
        # PostgREST bulk inserts require a common column set across EPS and
        # revenue rows. Unreported fields remain explicit nulls.
        for kind in ("eps","revenue"):
            for bound in ("low","high"):
                payload.setdefault(f"{kind}_guidance_{bound}",None)
                payload.setdefault(f"previous_{kind}_guidance_{bound}",None)
        if not any(r["source_record_id"]==payload["source_record_id"] for r in out):
            out.append(payload)
    return out
