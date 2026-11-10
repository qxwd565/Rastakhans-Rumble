#!/usr/bin/env python3
"""Enrich canonical card sources with immutable raw Tag/ReferencedTag and strings."""
from __future__ import annotations
import copy,hashlib,json,xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
LOCALES=("deDE","enUS","esES","esMX","frFR","itIT","jaJP","koKR","plPL","ptBR","ruRU","thTH","zhCN","zhTW")
WEAPONS={"TRL_074":3,"TRL_111":2,"TRL_304":3,"TRL_325":4,"TRL_352":3,"TRL_360":4,"TRL_543":2}

def read(p): return json.loads(p.read_text(encoding="utf-8"))
def write(p,o): p.write_text(json.dumps(o,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")

def extract_xml(path,expected_sha,expected_count,ids):
    raw=path.read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    if digest!=expected_sha: raise ValueError(f"{path.name}: immutable XML SHA mismatch {digest}")
    result={}
    for _,entity in ET.iterparse(path,events=("end",)):
        if entity.tag.rsplit("}",1)[-1]!="Entity": continue
        cid=entity.attrib.get("CardID")
        if cid not in ids:
            entity.clear(); continue
        owned={}; referenced={}; strings={}
        for tag in list(entity):
            kind=tag.tag.rsplit("}",1)[-1]
            if kind not in ("Tag","ReferencedTag") or "enumID" not in tag.attrib: continue
            tid=str(int(tag.attrib["enumID"]))
            record={"present":True,"valueAttributePresent":"value" in tag.attrib,
                    "value":tag.attrib.get("value"),"type":tag.attrib.get("type")}
            if kind=="Tag":
                owned[tid]=record
                if tag.attrib.get("type") in ("String","LocString") or any(
                    child.tag.rsplit("}",1)[-1] in LOCALES for child in list(tag)
                ):
                    locales={}
                    for child in list(tag):
                        locale=child.tag.rsplit("}",1)[-1]
                        if locale in LOCALES:
                            locales[locale]={"present":True,"value":"".join(child.itertext())}
                    strings[tid]={
                        "present":True,"type":tag.attrib.get("type"),
                        "valueAttributePresent":"value" in tag.attrib,
                        "valueAttribute":tag.attrib.get("value"),
                        "locales":locales,"textContent":"".join(tag.itertext())
                    }
            else:
                referenced[tid]=record
        dbf=entity.attrib.get("ID")
        result[cid]={"dbfId":int(dbf) if dbf and dbf.isdigit() else None,
                     "owned":owned,"referenced":referenced,"stringTags":strings}
        entity.clear()
    if len(result)!=expected_count: raise ValueError(f"{path.name}: {len(result)} cards != {expected_count}")
    return result

def main():
    archive_parts=[(ROOT/"sources"/f"archive-238-part-{i}.txt").read_text(encoding="utf-8") for i in (1,2,3)]
    import re,base64,gzip
    b64="".join(re.sub(r"\s+","",re.search(r"BASE64_START\s*(.*?)\s*BASE64_END",p,re.S).group(1)) for p in archive_parts)
    archive=json.loads(gzip.decompress(base64.b64decode(b64,validate=True)))
    manifest={int(x["build"]):x for x in archive["archiveManifest"]}
    cards=read(ROOT/"cards.json")["cards"]
    ids={c["id"] for c in cards}
    initial=extract_xml(ROOT/"sources"/"xml-27845.xml",manifest[27845]["xmlSha256"],164,ids)
    current=extract_xml(ROOT/"sources"/"xml-256589.xml",manifest[256589]["xmlSha256"],164,ids)
    before=extract_xml(ROOT/"sources"/"xml-217489.xml",manifest[217489]["xmlSha256"],len(WEAPONS),set(WEAPONS))
    after=extract_xml(ROOT/"sources"/"xml-217964.xml",manifest[217964]["xmlSha256"],len(WEAPONS),set(WEAPONS))
    raw_transitions=archive.get("observedRawTransitionReview",[])
    ref_transitions=archive.get("observedReferencedTagTransitions",[])
    updated=0
    for card in cards:
        cid=card["id"]; path=DATA/(cid+".json"); src=read(path)
        if src.get("schemaVersion")!=2: raise ValueError(f"{cid}: migrate step must run before enrich")
        if src["_current"].get("dbfId")!=initial[cid]["dbfId"] or src["_current"].get("dbfId")!=current[cid]["dbfId"]:
            raise ValueError(f"{cid}: immutable launch/current DBF mismatch")
        meta=src["_meta"]
        meta["launchNativeTagsOwned"]=copy.deepcopy(initial[cid]["owned"])
        meta["launchNativeTagsReferenced"]=copy.deepcopy(initial[cid]["referenced"])
        meta["currentNativeTagsOwned"]=copy.deepcopy(current[cid]["owned"])
        meta["currentNativeTagsReferenced"]=copy.deepcopy(current[cid]["referenced"])
        meta["launchStringTags"]=copy.deepcopy(initial[cid]["stringTags"])
        meta["currentStringTags"]=copy.deepcopy(current[cid]["stringTags"])
        meta["undatedRawTagTransitions"]=[copy.deepcopy(x) for x in raw_transitions if x.get("id")==cid]
        meta["undatedReferencedTagTransitions"]=[copy.deepcopy(x) for x in ref_transitions if x.get("id")==cid]
        # Original text and string tags are evidence, never substituted into display text.
        meta["launchPrintedText"]={
            "koKR":initial[cid]["stringTags"].get("185",{}).get("locales",{}).get("koKR",{}).get("value"),
            "enUS":initial[cid]["stringTags"].get("185",{}).get("locales",{}).get("enUS",{}).get("value")}
        meta["currentPrintedText"]={
            "koKR":current[cid]["stringTags"].get("185",{}).get("locales",{}).get("koKR",{}).get("value"),
            "enUS":current[cid]["stringTags"].get("185",{}).get("locales",{}).get("enUS",{}).get("value")}
        if cid in WEAPONS:
            old=before[cid]; new=after[cid]; n=str(WEAPONS[cid])
            if old["owned"].get("187",{}).get("value")!=n or old["owned"].get("45",{}).get("present") is True:
                raise ValueError(f"{cid}: 217489 weapon raw state mismatch")
            if new["owned"].get("187",{}).get("present") is True or new["owned"].get("45",{}).get("value")!=n:
                raise ValueError(f"{cid}: 217964 weapon raw state mismatch")
            if WEAPONS[cid] != int(n): raise ValueError(f"{cid}: durability changed")
            meta["weaponDurabilityTagMigrationEvidence"]={
                "date":"2025-03-19","beforeBuild":217489,"afterBuild":217964,
                "beforeOwn":{"187":n,"45":"ABSENT"},"afterOwn":{"187":"ABSENT","45":n},
                "logicalDurabilityBefore":WEAPONS[cid],"logicalDurabilityAfter":WEAPONS[cid],
                "officialPatch":"32.0","officialPublishedUTC":"2025-03-17T17:00:00Z",
                "officialSource":"https://news.blizzard.com/ko-kr/article/24187196/32-0",
                "isGameplayBuff":False
            }
        if cid=="TRL_900":
            meta["halazziRushEvidence"]=copy.deepcopy(archive["halazziRushEvidence"])
            meta["undatedGameplayObservations"]=[{
                "field":"own Tag 791","firstObservedBuild":247416,"date":None,
                "launchReferencedRush":True,"actualFirstEffectiveDay":None,
                "interpretation":"observation is not an effective-date proof; missing own tag does not prove no operation"}]
        if cid=="TRL_351":
            if initial[cid]["owned"].get("215",{}).get("value")!="3" or current[cid]["owned"].get("215",{}).get("value")!="3":
                raise ValueError("TRL_351: all-archive own OVERLOAD must be 3")
            if get_value(src["_current"]["nativeTags"],215)!="3":
                raise ValueError("TRL_351: flattened current nativeTags must be corrected to 3")
        write(path,src); updated+=1
    print(json.dumps({"enrichedCards":updated,
        "launchOwnTags":sum(len(x["owned"]) for x in initial.values()),
        "launchReferencedTags":sum(len(x["referenced"]) for x in initial.values()),
        "currentOwnTags":sum(len(x["owned"]) for x in current.values()),
        "currentReferencedTags":sum(len(x["referenced"]) for x in current.values()),
        "launchStringTags":sum(len(x["stringTags"]) for x in initial.values()),
        "currentStringTags":sum(len(x["stringTags"]) for x in current.values()),
        "weaponRepresentationEvents":len(WEAPONS),"datedGameplayEventsAdded":0},ensure_ascii=False))

def get_value(tags,tag_id):
    for t in tags:
        if int(t["id"])==tag_id:return str(t["value"])
    return "ABSENT"

if __name__=="__main__": main()
