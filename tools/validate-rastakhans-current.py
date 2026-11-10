#!/usr/bin/env python3
"""Independent source, replay, compatibility and preservation validation."""
from __future__ import annotations
import base64,copy,gzip,hashlib,json,re,subprocess,xml.etree.ElementTree as ET,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
BASE="379a359058b8de937219cc317ee55f7186ea7528"
LOCALES={"deDE","enUS","esES","esMX","frFR","esMX","frFR","itIT","jaJP","koKR","plPL","ptBR","ruRU","thTH","zhCN","zhTW"}
WEAPONS={"TRL_074":3,"TRL_111":2,"TRL_304":3,"TRL_325":4,"TRL_352":3,"TRL_360":4,"TRL_543":2}
SPIRITS=("TRL_060","TRL_092","TRL_223","TRL_251","TRL_309","TRL_319","TRL_327","TRL_901")
SPEC=("name","type","cardClass","classes","rarity","collectible","cost","attack","health","durability","armor","text","races","race","spellSchool","mechanics")

def read(p):return json.loads(p.read_text(encoding="utf-8"))
def archive():
    parts=[]
    for i in (1,2,3):
        t=(ROOT/"sources"/f"archive-238-part-{i}.txt").read_text(encoding="utf-8")
        m=re.search(r"BASE64_START\s*(.*?)\s*BASE64_END",t,re.S)
        if not m:raise AssertionError(f"archive part {i} missing base64")
        parts.append(re.sub(r"\s+","",m.group(1)))
    raw=gzip.decompress(base64.b64decode("".join(parts),validate=True))
    assert len(raw)==529892
    assert hashlib.sha256(raw).hexdigest()=="e9b8a4bb39895852903de414e6f74fda6b645b6e73293efc3df70fe0a4a9201a"
    return json.loads(raw)

def parse_xml(path,expected_sha,expected_count,ids):
    raw=path.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==expected_sha,(path.name,"sha")
    out={}
    for _,entity in ET.iterparse(path,events=("end",)):
        if entity.tag.rsplit("}",1)[-1]!="Entity":continue
        cid=entity.attrib.get("CardID")
        if cid not in ids:
            entity.clear();continue
        owned={};refs={};strings={}
        for tag in list(entity):
            kind=tag.tag.rsplit("}",1)[-1]
            if kind not in ("Tag","ReferencedTag") or "enumID" not in tag.attrib:continue
            tid=str(int(tag.attrib["enumID"]))
            record={"present":True,"valueAttributePresent":"value" in tag.attrib,
                    "value":tag.attrib.get("value"),"type":tag.attrib.get("type")}
            if kind=="Tag":
                owned[tid]=record
                locales={}
                for child in list(tag):
                    loc=child.tag.rsplit("}",1)[-1]
                    if loc in LOCALES:locales[loc]={"present":True,"value":"".join(child.itertext())}
                if tag.attrib.get("type") in ("String","LocString") or locales:
                    strings[tid]={"present":True,"type":tag.attrib.get("type"),
                        "valueAttributePresent":"value" in tag.attrib,"valueAttribute":tag.attrib.get("value"),
                        "locales":locales,"textContent":"".join(tag.itertext())}
            else:refs[tid]=record
        dbf=entity.attrib.get("ID")
        out[cid]={"dbfId":int(dbf) if dbf and dbf.isdigit() else None,
                  "owned":owned,"referenced":refs,"stringTags":strings}
        entity.clear()
    assert len(out)==expected_count,(path.name,len(out),expected_count)
    return out

def replay(src):
    dates=sorted(k for k in src if re.fullmatch(r"\d{4}-\d{2}-\d{2}",k))
    state=copy.deepcopy(src[dates[0]])
    for day in dates[1:]:
        ev=src[day]
        for k,v in ev.items():
            if k in ("nativeTagRolesDelta","source","confidence"):continue
            if k=="removedFields":
                for field in v:state.pop(field,None)
            else:state[k]=copy.deepcopy(v)
    return dates,state

def set_tag(tags,tid):
    return next((str(x["value"]) for x in tags if int(x["id"])==tid),"ABSENT")

def main():
    ev=archive()
    manifest={int(x["build"]):x for x in ev["archiveManifest"]}
    xml_dir=Path(os.environ.get("RASTAKHANS_XML_DIR",str(ROOT/"sources")))
    ids=set(read(ROOT/"cards.json")["cards"][i]["id"] for i in range(164))
    launch_xml=parse_xml(xml_dir/"xml-27845.xml",manifest[27845]["xmlSha256"],164,ids)
    current_xml=parse_xml(xml_dir/"xml-256589.xml",manifest[256589]["xmlSha256"],164,ids)
    before_xml=parse_xml(xml_dir/"xml-217489.xml",manifest[217489]["xmlSha256"],164,ids)
    after_xml=parse_xml(xml_dir/"xml-217964.xml",manifest[217964]["xmlSha256"],164,ids)
    assert len(manifest)==238 and ev["summaryCounts"]["originalCardObservations"]==39032
    for cid in ids:
        assert before_xml[cid]["dbfId"]==cards[cid]["dbfId"]
        assert after_xml[cid]["dbfId"]==cards[cid]["dbfId"]
    catalog=read(ROOT/"cards.json"); render=read(ROOT/"render.json"); legacy=read(ROOT/"history.json")
    central=read(DATA/"history.json")
    cards={x["id"]:x for x in catalog["cards"]}
    renders={x["id"]:x for x in render["cards"]}
    assert len(cards)==164 and len(renders)==164
    assert central["initialStates"]==164 and central["followupEvents"]==51 and central["totalStates"]==215
    assert len(central["events"]["2018-12-05"])==164
    assert len({x["dbfId"] for x in cards.values()})==164
    assert set(cards)==set(central["events"]["2018-12-05"])
    source_docs={cid:read(DATA/(cid+".json")) for cid in cards}
    all_dates=set()
    raw_role_event_count=0
    logical_replay_checks=0
    undated_checks=0
    for cid,src in source_docs.items():
        assert src["schemaVersion"]==2 and src["_meta"]["timezone"]=="Asia/Seoul"
        dates,state=replay(src)
        assert dates[0]=="2018-12-05" and dates==sorted(dates)
        assert len(dates)==1+sum(1 for d in dates[1:])
        assert state["id"]==cid and state["dbfId"]==cards[cid]["dbfId"]
        for field in SPEC:
            actual=state.get(field,"ABSENT"); expected=src["_current"].get(field,"ABSENT")
            if actual!=expected:
                obs=[x for x in src["_meta"].get("undatedCurrentDifferences",[]) if x["field"]==field and x["date"] is None]
                assert len(obs)==1 and obs[0]["before"]==actual and obs[0]["after"]==expected,(cid,field,actual,expected)
                undated_checks+=1
            else:logical_replay_checks+=1
        for day in dates:
            all_dates.add(day)
            if day!="2018-12-05":
                evrow=src[day]
                if "nativeTagRolesDelta" in evrow:raw_role_event_count+=1
                assert central["events"].get(day,{}).get(cid)==evrow,(cid,day,"central differs from canonical")
        assert cards[cid]==src["_current"],(cid,"cards current != canonical _current")
        rc=renders[cid]
        for field in ("id","dbfId","name","type","cardClass","rarity","collectible","cost","text","attack","health","durability","armor","art","races","race","spellSchool","set","nativeTags","mechanics","watermark","classes"):
            if field in src["_current"]:assert rc.get(field)==src["_current"][field],(cid,field,"render current")
        meta=src["_meta"]
        baseline_raw=subprocess.check_output(["git","show",f"{BASE}:data/{cid}.json"],cwd=ROOT)
        baseline_doc=json.loads(baseline_raw)
        assert meta["originalFourKeySourceRaw"]==baseline_raw.decode("utf-8")
        assert meta["originalFourKeySourceSnapshot"]==baseline_doc
        assert meta["originalFourKeySourceSha256"]==hashlib.sha256(baseline_raw).hexdigest()
        baseline_card=copy.deepcopy(baseline_doc["card"])
        if cid=="TRL_351":
            for item in baseline_card["nativeTags"]:
                if int(item["id"])==215:item["value"]=3
        assert baseline_card==src["_current"],(cid,"original four-key current card preservation")
        assert central["observations"]["undatedCurrentDifferences"].get(cid,[])==meta.get("undatedCurrentDifferences",[])
        assert central["observations"]["undatedRawTags"].get(cid,[])==meta.get("undatedRawTagTransitions",[])
        assert central["observations"]["undatedReferencedTags"].get(cid,[])==meta.get("undatedReferencedTagTransitions",[])
        assert central["observations"]["undatedFields"].get(cid,[])==meta.get("undatedFieldObservations",[])
        launch_strings=meta.get("launchStringTags",{})
        current_strings=meta.get("currentStringTags",{})
        expected_string_diffs=[]
        for tid in sorted(set(launch_strings)|set(current_strings),key=int):
            before=launch_strings.get(tid,"ABSENT"); after=current_strings.get(tid,"ABSENT")
            if before!=after:
                expected_string_diffs.append({"tagId":int(tid),"before":before,"after":after,"date":None})
        assert central["observations"]["undatedStringTags"].get(cid,[])==expected_string_diffs
        assert meta["launchNativeTagsOwned"]==launch_xml[cid]["owned"],(cid,"launch owned raw tags")
        assert meta["launchNativeTagsReferenced"]==launch_xml[cid]["referenced"],(cid,"launch referenced raw tags")
        assert meta["currentNativeTagsOwned"]==current_xml[cid]["owned"],(cid,"current owned raw tags")
        assert meta["currentNativeTagsReferenced"]==current_xml[cid]["referenced"],(cid,"current referenced raw tags")
        assert meta["launchStringTags"]==launch_xml[cid]["stringTags"],(cid,"launch localized string tags")
        assert meta["currentStringTags"]==current_xml[cid]["stringTags"],(cid,"current localized string tags")
        assert rc["nativeTagRoles"]["launch"]["owned"]==meta["launchNativeTagsOwned"]
        assert rc["nativeTagRoles"]["launch"]["referenced"]==meta["launchNativeTagsReferenced"]
        assert rc["nativeTagRoles"]["current"]["owned"]==meta["currentNativeTagsOwned"]
        assert rc["nativeTagRoles"]["current"]["referenced"]==meta["currentNativeTagsReferenced"]
        assert rc["nativeStringTags"]["launch"]==meta["launchStringTags"]
        assert rc["nativeStringTags"]["current"]==meta["currentStringTags"]
    assert len(all_dates)>=10
    assert len(central["events"]["2022-11-30"])==17  # 16 corrected existing rows + missing TRL_311
    assert len(central["events"]["2025-03-19"])==7
    assert len(central["events"]["2026-03-11"])>=1

    # 11 launch logical-state corrections.
    for cid in SPIRITS:
        st=source_docs[cid]["2018-12-05"]
        assert st["races"]==[] and st["race"]==""
        assert set_tag(st["nativeTags"],200)=="ABSENT"
        assert set_tag(st["nativeTags"],2542)=="ABSENT"
    s=source_docs["TRL_060"]["2018-12-05"]
    assert s["cost"]==3 and set_tag(s["nativeTags"],48)=="3"
    s=source_docs["TRL_252"]["2018-12-05"]
    assert s["health"]==4 and set_tag(s["nativeTags"],45)=="4"
    s=source_docs["TRL_311"]["2018-12-05"]
    assert s["races"]==["ELEMENTAL"] and s["race"]=="정령" and set_tag(s["nativeTags"],2542)=="ABSENT"
    s=source_docs["TRL_900"]["2018-12-05"]
    assert s["cost"]==5 and s["attack"]==3 and "<b>속공</b>, <b>전투의 함성</b>" not in s["text"]
    assert "\u00a0" in s["text"]
    assert source_docs["TRL_900"]["_meta"]["launchNativeTagsOwned"].get("791",{}).get("present") is not True
    assert source_docs["TRL_900"]["_meta"]["launchNativeTagsReferenced"].get("791",{}).get("value")=="1"

    # Two contaminated existing rows are corrected without losing the 16 race events.
    s=source_docs["TRL_060"]["2022-11-30"]
    assert "cost" not in s and set_tag(s["nativeTags"],48)=="3"
    s=source_docs["TRL_501"]["2022-11-30"]
    assert s["races"]==["UNDEAD"] and s["race"]=="언데드"
    assert set_tag(s["nativeTags"],2525)=="ABSENT"
    s=source_docs["TRL_501"]["2024-10-30"]
    assert s["races"]==["UNDEAD","DRAENEI"] and set_tag(s["nativeTags"],2525)=="1"

    # Five missing dated gameplay events.
    assert source_docs["TRL_252"]["2022-04-06"]["health"]==5
    assert source_docs["TRL_311"]["2022-11-30"]["races"]==["ELEMENTAL","BEAST"]
    assert source_docs["TRL_060"]["2023-09-29"]["cost"]==5
    assert source_docs["TRL_501"]["2024-10-30"]["races"]==["UNDEAD","DRAENEI"]
    halazzi=source_docs["TRL_900"]["2026-03-11"]
    assert halazzi["cost"]==4 and halazzi["attack"]==4 and "<b>속공</b>" in halazzi["text"]
    assert "nativeTagRolesDelta" not in halazzi

    # Seven representation-only weapon events: full array replacement, raw role delta,
    # no logical durability field and same value before/after.
    for cid,dur in WEAPONS.items():
        b=before_xml[cid]; a=after_xml[cid]
        assert b["owned"].get("187",{}).get("value")==str(dur) and "45" not in b["owned"]
        assert "187" not in a["owned"] and a["owned"].get("45",{}).get("value")==str(dur)
        assert current_xml[cid]["owned"]==a["owned"] and current_xml[cid]["referenced"]==a["referenced"]
        e=source_docs[cid]["2025-03-19"]
        assert "durability" not in e
        assert e["source"]["durabilityBefore"]==dur==e["source"]["durabilityAfter"]
        assert e["nativeTagRolesDelta"]["owned"]=={"removed":["187"],"set":{"45":str(dur)}}
        assert set_tag(e["nativeTags"],45)==str(dur)
        assert set_tag(e["nativeTags"],187)=="ABSENT"
        assert source_docs[cid]["_meta"]["weaponDurabilityTagMigrationEvidence"]["isGameplayBuff"] is False

    # Current native raw correction and preserved exceptions.
    assert set_tag(cards["TRL_351"]["nativeTags"],215)=="3"
    assert set_tag(source_docs["TRL_351"]["2018-12-05"]["nativeTags"],215)=="3"
    assert source_docs["TRL_065"]["_current"]["health"]==30 and source_docs["TRL_065"]["_current"]["armor"]==5
    for cid in ("TRL_254a","TRL_254b"):
        assert "cost" not in source_docs[cid]["2018-12-05"]
        assert source_docs[cid]["_current"]["cost"]==4
        assert not any("cost" in source_docs[cid][d] for d in replay(source_docs[cid])[0][1:])
    for cid in ("TRL_128","TRL_243","TRL_310"):
        assert source_docs[cid]["_current"]["cost"]==0
    assert sum(1 for c in cards.values() if c.get("collectible") is False)==29
    assert sum(1 for c in cards.values() if c.get("collectible") is False and c.get("flavor")=="")==29

    # The 24 current referenced tags and 18 explicit relation records remain role-separated.
    ref_count=sum(len(x["_meta"]["currentNativeTagsReferenced"]) for x in source_docs.values())
    assert ref_count==24,(ref_count,"current ReferencedTag count")
    relation_count=sum(1 for x in source_docs.values()
                       for tid in ("380","1452") if tid in x["_meta"]["currentNativeTagsOwned"])
    assert relation_count==18,(relation_count,"explicit relationship tag count")

    # All localized String/LocString tags from the immutable initial/current XMLs.
    for cid,src in source_docs.items():
        for stage in ("launch","current"):
            tags=src["_meta"][stage+"StringTags"]
            for tid,tag in tags.items():
                assert tag["present"] is True and "type" in tag
                assert "valueAttributePresent" in tag and "valueAttribute" in tag and "textContent" in tag
                assert all(locale in LOCALES for locale in tag["locales"])
        assert src["_meta"]["launchNativeTagsOwned"] is not None
        assert src["_meta"]["currentNativeTagsReferenced"] is not None

    # Current cards.json differs from preserved baseline only by TRL_351 own OVERLOAD=3.
    baseline=json.loads(subprocess.check_output(["git","show",f"{BASE}:cards.json"],cwd=ROOT,text=True))
    expected=copy.deepcopy(baseline)
    c=next(x for x in expected["cards"] if x["id"]=="TRL_351")
    for t in c["nativeTags"]:
        if t["id"]==215:t["value"]=3
    assert expected==catalog,"current card data changed beyond the permitted TRL_351 Tag 215 correction"

    assert set(legacy["cards"]).issubset({str(x["dbfId"]) for x in cards.values()})
    print(json.dumps({"cards":len(cards),"initialStates":164,"followupEvents":51,"totalStates":215,
        "datedRows":sum(len(x) for x in central["events"].values()),
        "launchCorrections":11,"correctedExistingRows":2,"missingGameplayEvents":5,
        "weaponRepresentationEvents":7,"currentReferencedTags":ref_count,
        "explicitRelationships":relation_count,"logicalReplayChecks":logical_replay_checks,
        "undatedCurrentDifferenceChecks":undated_checks,"archiveBuilds":238,
        "xmlSnapshotsIndependentlyParsed":4,"result":"PASS"},ensure_ascii=False))

if __name__=="__main__":main()
