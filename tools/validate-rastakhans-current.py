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
    snapshots={dates[0]:copy.deepcopy(state)}
    for day in dates[1:]:
        ev=src[day]
        for k,v in ev.items():
            if k in ("nativeTagRolesDelta","source","confidence"):continue
            if k=="removedFields":
                for field in v:state.pop(field,None)
            else:state[k]=copy.deepcopy(v)
        snapshots[day]=copy.deepcopy(state)
    return dates,state,snapshots

def set_tag(tags,tid):
    return next((str(x["value"]) for x in tags if int(x["id"])==tid),"ABSENT")

def role_values(role):
    return {str(tid):(str(rec["value"]) if rec.get("valueAttributePresent") else None)
            for tid,rec in role.items() if rec.get("present")}

def make_role_delta(raw_diff):
    owned={"set":{},"removed":[]}
    for tid,(before,after) in raw_diff.items():
        if after=="ABSENT":owned["removed"].append(str(tid))
        else:owned["set"][str(tid)]=str(after)
    owned["removed"].sort(key=int)
    return {"owned":owned,"referenced":{"set":{},"removed":[]}}

def apply_role_delta(state,delta):
    for tid in delta.get("removed",[]):state.pop(str(tid),None)
    for tid,value in delta.get("set",{}).items():state[str(tid)]=str(value)

FINDING_DATES={
    "RAST-BAL-E001":"2019-05-23","RAST-BAL-E002":"2020-03-18",
    **{f"RAST-BAL-E{i:03d}":"2021-03-26" for i in range(3,22)},
    "RAST-BAL-M001":"2022-04-06",
    **{f"RAST-BAL-E{i:03d}":"2022-11-30" for i in range(22,38)},
    "RAST-BAL-M002":"2022-11-30","RAST-BAL-M003":"2023-09-29",
    "RAST-BAL-E038":"2024-10-30","RAST-BAL-M004":"2024-10-30",
    "RAST-BAL-E039":"2026-02-10","RAST-BAL-M005":"2026-03-11",
}
PUBLIC_FIELDS=("id","dbfId","name","type","cardClass","rarity","collectible",
    "cost","text","attack","health","durability","armor","art","races","race",
    "spellSchool","set","nativeTags","mechanics","watermark","classes")

def expected_dated_role_rows(archive):
    rows={}
    for item in archive["observedRawTransitionReview"]:
        date=None
        if item["decision"]=="weapon_durability_tag_migration_same_value":
            date="2025-03-19"
        elif item["decision"].startswith("gameplay_"):
            ds={FINDING_DATES[x] for x in item.get("relatedFindings",[]) if x in FINDING_DATES}
            assert len(ds)==1,(item["id"],item.get("relatedFindings"),ds)
            date=ds.pop()
        if date:
            key=(item["id"],date)
            assert key not in rows,key
            rows[key]=item
    return rows

def validate_all_raw_role_transitions(archive,launch_xml,current_xml):
    state={"owned":{cid:role_values(x["owned"]) for cid,x in launch_xml.items()},
           "referenced":{cid:role_values(x["referenced"]) for cid,x in launch_xml.items()}}
    timeline=[]
    for row in archive["observedRawTransitionReview"]:
        timeline.append((int(row["build"]),0,row["id"],row["rawDiff"],"owned"))
    for group in archive["observedReferencedTagTransitions"]:
        for row in group.get("changes",[]):
            timeline.append((int(group["build"]),1,row["id"],row["diff"],"referenced"))
    for build,_,cid,diff,role in sorted(timeline,key=lambda x:(x[0],x[1],x[2])):
        values=state[role][cid]
        for tid,(before,after) in diff.items():
            tid=str(tid)
            assert values.get(tid,"ABSENT")==before,(cid,build,role,tid,before,values.get(tid,"ABSENT"))
            if after=="ABSENT":values.pop(tid,None)
            else:values[tid]=str(after)
    for cid in launch_xml:
        assert state["owned"][cid]==role_values(current_xml[cid]["owned"]),(cid,"full own-role archive replay")
        assert state["referenced"][cid]==role_values(current_xml[cid]["referenced"]),(cid,"full referenced-role archive replay")
    return len(timeline)

def validate_public_reverse_replay(cid,dates,snapshots,render_card):
    current={k:copy.deepcopy(render_card[k]) for k in PUBLIC_FIELDS if k in render_card}
    revisions=render_card.get("history",[])
    previous=[]
    for rev in revisions:
        assert isinstance(rev.get("from"),str) and rev["from"] in dates,(cid,rev)
        assert "before" in rev and (rev["before"] is None or rev["before"] in dates),(cid,rev)
        if rev["before"] is not None:assert rev["from"]<rev["before"],(cid,rev)
        previous.append(rev)
    checks=0
    for day in dates:
        expected={k:copy.deepcopy(v) for k,v in snapshots[day].items() if k in PUBLIC_FIELDS}
        matches=[r for r in revisions if r["from"]<=day and (r["before"] is None or day<r["before"])]
        assert len(matches)<=1,(cid,day,matches)
        actual=copy.deepcopy(current)
        if matches:
            rev=matches[0]
            changes=rev["changes"]
            removed=rev.get("removedFields",[])
            expected_changes={k:copy.deepcopy(v) for k,v in expected.items()
                if current.get(k,"__ABSENT__")!=v}
            expected_removed=sorted(k for k in current if k not in expected)
            assert changes==expected_changes,(cid,day,"changes not complete current-relative diff",set(changes)^set(expected_changes))
            assert removed==expected_removed,(cid,day,"removedFields not complete",removed,expected_removed)
            actual.update(copy.deepcopy(changes))
            for field in removed:actual.pop(field,None)
        else:
            assert expected==current,(cid,day,"segment omitted but differs from current")
        assert actual==expected,(cid,day,"public current+changes+removedFields replay mismatch")
        checks+=1
    return checks

def main():
    ev=archive()
    manifest={int(x["build"]):x for x in ev["archiveManifest"]}
    xml_dir=Path(os.environ.get("RASTAKHANS_XML_DIR",str(ROOT/"sources")))
    ids=set(read(ROOT/"cards.json")["cards"][i]["id"] for i in range(164))
    launch_xml=parse_xml(xml_dir/"xml-27845.xml",manifest[27845]["xmlSha256"],164,ids)
    current_xml=parse_xml(xml_dir/"xml-256589.xml",manifest[256589]["xmlSha256"],164,ids)
    before_xml=parse_xml(xml_dir/"xml-217489.xml",manifest[217489]["xmlSha256"],164,ids)
    after_xml=parse_xml(xml_dir/"xml-217964.xml",manifest[217964]["xmlSha256"],164,ids)
    halazzi_before_xml=parse_xml(xml_dir/"xml-236529.xml",manifest[236529]["xmlSha256"],164,ids)
    halazzi_after_xml=parse_xml(xml_dir/"xml-237510.xml",manifest[237510]["xmlSha256"],164,ids)
    assert len(manifest)==238 and ev["summaryCounts"]["originalCardObservations"]==39032
    assert halazzi_before_xml["TRL_900"]["stringTags"]["184"]["type"]=="LocString"
    assert halazzi_before_xml["TRL_900"]["stringTags"]["184"]["locales"]["koKR"]==launch_xml["TRL_900"]["stringTags"]["184"]["locales"]["koKR"]
    assert halazzi_before_xml["TRL_900"]["stringTags"]["184"]["locales"]["enUS"]==launch_xml["TRL_900"]["stringTags"]["184"]["locales"]["enUS"]
    assert halazzi_before_xml["TRL_900"]["stringTags"]["184"]["locales"]["thTH"]["value"]=="<b>คำรามสู้ศึก:</b> เพิ่มแมวป่า_1/1_ที่มี <b>จู่โจม</b>_จนเต็มมือคุณ"
    assert halazzi_before_xml["TRL_900"]["stringTags"]["184"]["locales"]["zhCN"]["value"]=="<b>战吼：</b>用1/1并具有\n<b>突袭</b>的山猫填满你的手牌。"
    launch_halazzi_tag=launch_xml["TRL_900"]["stringTags"]["184"]
    prepatch_halazzi_tag=halazzi_before_xml["TRL_900"]["stringTags"]["184"]
    expected_undated_locales=[]
    for locale in sorted(set(launch_halazzi_tag["locales"]) | set(prepatch_halazzi_tag["locales"])):
        old=launch_halazzi_tag["locales"].get(locale,"ABSENT")
        new=prepatch_halazzi_tag["locales"].get(locale,"ABSENT")
        if old!=new:
            expected_undated_locales.append({"locale":locale,"before":old,"after":new,"date":None})
    assert {x["locale"] for x in expected_undated_locales}=={"thTH","zhCN"}
    halazzi_mid=halazzi_after_xml["TRL_900"]["stringTags"]["184"]
    assert halazzi_mid["type"]=="LocString" and halazzi_mid["valueAttributePresent"] is False
    assert halazzi_mid["locales"]["koKR"]["value"]=="<b>속공</b>, <b>전투의_함성:</b>\n내 손을 <b>속공</b> 능력이 있는 1/1 스라소니로 가득 채웁니다."
    assert halazzi_mid["locales"]["enUS"]["value"]=="<b>Rush</b>. <b>Battlecry:</b> Fill your hand with 1/1 Lynxes\nthat have <b>Rush</b>."
    catalog=read(ROOT/"cards.json"); render=read(ROOT/"render.json"); legacy=read(ROOT/"history.json")
    central=read(DATA/"history.json")
    assert len(central["observations"]["datedStringTags"]["TRL_900"])==1
    schema_manifest=read(ROOT/"sources"/"rast-schema-s002.json")
    dated_role_rows=expected_dated_role_rows(ev)
    assert len(dated_role_rows)==51
    full_role_transition_count=validate_all_raw_role_transitions(ev,launch_xml,current_xml)
    assert full_role_transition_count==121
    assert schema_manifest["schema"]=="RAST-SCHEMA-S002"
    assert schema_manifest["numericFieldCount"]==406 and schema_manifest["emptyChoiceFieldCount"]==220
    cards={x["id"]:x for x in catalog["cards"]}
    for cid in ids:
        assert before_xml[cid]["dbfId"]==cards[cid]["dbfId"]
        assert after_xml[cid]["dbfId"]==cards[cid]["dbfId"]
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
    reverse_checks=0
    undated_checks=0
    for cid,src in source_docs.items():
        assert src["schemaVersion"]==2 and src["_meta"]["timezone"]=="Asia/Seoul"
        meta=src["_meta"]
        dates,state,snapshots=replay(src)
        assert dates[0]=="2018-12-05" and dates==sorted(dates)
        assert len(dates)==1+sum(1 for d in dates[1:])
        assert state["id"]==cid and state["dbfId"]==cards[cid]["dbfId"]
        schema_fields=set(meta.get("schemaNormalization",{}).get("removedFields",[]))
        for field in SPEC:
            actual=state.get(field,"ABSENT"); expected=src["_current"].get(field,"ABSENT")
            if actual!=expected:
                if field in schema_fields:
                    assert actual=="ABSENT" and expected==0 or (actual=="ABSENT" and expected=="" ) or (actual=="ABSENT" and expected==[]),(cid,field,actual,expected,"S002")
                else:
                    obs=[x for x in meta.get("undatedCurrentDifferences",[]) if x["field"]==field and x["date"] is None]
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
        schema_row=next(x for x in schema_manifest["cards"] if x["id"]==cid)
        assert schema_row["type"]==src["_current"]["type"]
        expected_omit={}
        for field,value in schema_row["omitNumeric"].items():expected_omit[field]=0
        for field,value in schema_row["omitChoice"].items():expected_omit[field]=[] if value=="[]" else ""
        assert set(meta["schemaNormalization"]["removedFields"])==set(expected_omit)
        for day in dates:
            for field in expected_omit:
                assert field not in snapshots[day],(cid,day,field,"S002 field remains in canonical state")
        for field,value in expected_omit.items():
            assert src["_current"].get(field,"ABSENT")==value,(cid,field,"current compatibility value")
            assert cards[cid].get(field,"ABSENT")==value
            assert rc.get(field,"ABSENT")==value
        # Date-first role deltas are independently derived from immutable audit rawDiff.
        expected_card_deltas={}
        for (row_id,day),row in dated_role_rows.items():
            if row_id==cid:expected_card_deltas[day]=make_role_delta(row["rawDiff"])
        actual_card_deltas={day:src[day]["nativeTagRolesDelta"] for day in dates if "nativeTagRolesDelta" in src[day]}
        assert actual_card_deltas==expected_card_deltas,(cid,"canonical dated raw-role deltas")
        public_role_changes=rc["nativeTagRoles"]["datedChanges"]
        assert public_role_changes==[{"date":day,"delta":expected_card_deltas[day]} for day in sorted(expected_card_deltas)]
        assert rc["nativeTagRoles"]["undatedOwnedTransitions"]==meta["undatedRawTagTransitions"]
        assert rc["nativeTagRoles"]["undatedReferencedTransitions"]==meta["undatedReferencedTagTransitions"]
        # Replay own/reference maps through each of this card's 215 date segments.
        own_state=role_values(launch_xml[cid]["owned"])
        ref_state=role_values(launch_xml[cid]["referenced"])
        for day in dates:
            row=dated_role_rows.get((cid,day))
            if row:
                for tag_id,(before,after) in row["rawDiff"].items():
                    assert own_state.get(str(tag_id),"ABSENT")==before,(cid,day,tag_id,"independent raw before")
                    if after=="ABSENT":own_state.pop(str(tag_id),None)
                    else:own_state[str(tag_id)]=str(after)
            assert role_values(launch_xml[cid]["owned"]) is not None
            # The canonical event replay must equal the independently sourced role state.
            canonical_role_state=role_values(launch_xml[cid]["owned"])
            for prior_day in dates:
                if prior_day>day:break
                delta=src[prior_day].get("nativeTagRolesDelta")
                if delta:apply_role_delta(canonical_role_state,delta["owned"])
            assert canonical_role_state==own_state,(cid,day,"dated owned-role replay")
            assert ref_state==role_values(launch_xml[cid]["referenced"]),(cid,day,"dated referenced-role replay")
        # Tag 184, not Tag 185, supplies printed descriptions; absence != empty.
        def printed(xml):
            tag=xml["stringTags"].get("184"); locales=tag.get("locales",{}) if tag else {}
            return {"tagId":184,"present":tag is not None,"koKR":locales.get("koKR",{}).get("value"),
                "enUS":locales.get("enUS",{}).get("value"),"koKRPresent":"koKR" in locales,"enUSPresent":"enUS" in locales}
        assert meta["launchPrintedText"]==printed(launch_xml[cid])
        assert meta["currentPrintedText"]==printed(current_xml[cid])
        for field in ("id","dbfId","name","type","cardClass","rarity","collectible","cost","text","attack","health","durability","armor","art","races","race","spellSchool","set","nativeTags","mechanics","watermark","classes"):
            if field in src["_current"]:assert rc.get(field)==src["_current"][field],(cid,field,"render current")
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
        assert rc["nativeStringTags"]["launchPrintedText"]==meta["launchPrintedText"]
        assert rc["nativeStringTags"]["currentPrintedText"]==meta["currentPrintedText"]
        if cid=="TRL_900":
            observation=meta["datedStringTagObservations"][0]
            assert observation["date"]=="2026-03-11" and observation["build"]==237510 and observation["tagId"]==184
            assert observation["before"]==halazzi_before_xml[cid]["stringTags"]["184"]
            assert meta["halazziPrePatchStringTagSnapshot"]==halazzi_before_xml[cid]["stringTags"]["184"]
            assert meta["undatedStringTagObservations"]==central["observations"]["undatedStringTagsByObservation"][cid]
            assert rc["nativeStringTags"]["undatedObservations"]==meta["undatedStringTagObservations"]
            assert {x["locale"] for x in meta["undatedStringTagObservations"][0]["differences"]}=={"thTH","zhCN"}
            assert meta["undatedStringTagObservations"][0]["differences"]==expected_undated_locales
            assert all(x["date"] is None for x in meta["undatedStringTagObservations"][0]["differences"])
            assert meta["halazziPrePatchStringTagSnapshot"]==halazzi_before_xml[cid]["stringTags"]["184"]
            assert rc["nativeStringTags"]["undatedObservations"]==meta["undatedStringTagObservations"]
            assert {x["locale"] for x in meta["undatedStringTagObservations"][0]["differences"]}=={"thTH","zhCN"}
            assert all(x["date"] is None for x in meta["undatedStringTagObservations"][0]["differences"])
            assert observation["after"]==halazzi_after_xml[cid]["stringTags"]["184"]
            assert central["observations"]["datedStringTags"][cid]==meta["datedStringTagObservations"]
            assert rc["nativeStringTags"]["datedChanges"]==meta["datedStringTagObservations"]
        reverse_checks+=validate_public_reverse_replay(cid,dates,snapshots,rc)
    assert len(all_dates)>=10
    assert raw_role_event_count==51
    assert central["verification"]["datedRawRoleEvents"]==51
    assert reverse_checks==215
    assert all(str(card["dbfId"]) in legacy["cards"] for card in cards.values())
    for cid,rc in renders.items():
        assert legacy["cards"][str(cards[cid]["dbfId"])]["history"]==rc.get("history",[])
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
    assert halazzi["nativeTagRolesDelta"]["owned"]=={"set":{"47":"4","48":"4"},"removed":[]}
    assert "791" not in halazzi["nativeTagRolesDelta"]["owned"]["set"]

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
    assert sum(1 for c in cards.values() if c.get("type")=="MINION" and c.get("attack")==0)==15
    assert sum(1 for c in cards.values() if c.get("text")=="")==10

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
        "weaponRepresentationEvents":7,"datedRawRoleEvents":raw_role_event_count,"reverseReplaySegments":reverse_checks,"fullRawRoleTransitions":full_role_transition_count,"schemaNumericOmissions":406,"schemaChoiceOmissions":220,"currentReferencedTags":ref_count,
        "explicitRelationships":relation_count,"logicalReplayChecks":logical_replay_checks,
        "undatedCurrentDifferenceChecks":undated_checks,"archiveBuilds":238,
        "xmlSnapshotsIndependentlyParsed":6,"datedRawStringObservations":1,"result":"PASS"},ensure_ascii=False))

if __name__=="__main__":main()
