#!/usr/bin/env python3
"""Enrich canonical card sources with immutable raw Tag/ReferencedTag and strings."""
from __future__ import annotations
import copy,hashlib,json,xml.etree.ElementTree as ET,os,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
XML_DIR=Path(os.environ.get("RASTAKHANS_XML_DIR",str(ROOT/"sources")))
LOCALES=("deDE","enUS","esES","esMX","frFR","itIT","jaJP","koKR","plPL","ptBR","ruRU","thTH","zhCN","zhTW")
BASELINE_COMMIT="379a359058b8de937219cc317ee55f7186ea7528"
WEAPONS={"TRL_074":3,"TRL_111":2,"TRL_304":3,"TRL_325":4,"TRL_352":3,"TRL_360":4,"TRL_543":2}
FINDING_DATES={
    "RAST-BAL-E001":"2019-05-23","RAST-BAL-E002":"2020-03-18",
    **{f"RAST-BAL-E{i:03d}":"2021-03-26" for i in range(3,22)},
    "RAST-BAL-M001":"2022-04-06",
    **{f"RAST-BAL-E{i:03d}":"2022-11-30" for i in range(22,38)},
    "RAST-BAL-M002":"2022-11-30","RAST-BAL-M003":"2023-09-29",
    "RAST-BAL-E038":"2024-10-30","RAST-BAL-M004":"2024-10-30",
    "RAST-BAL-E039":"2026-02-10","RAST-BAL-M005":"2026-03-11",
}
TYPE_OMISSIONS={
    "MINION":({"durability":0,"armor":0},{"spellSchool":""}),
    "SPELL":({"attack":0,"health":0,"durability":0,"armor":0},{"races":[],"race":""}),
    "WEAPON":({"health":0,"armor":0},{"spellSchool":"","races":[],"race":""}),
    "HERO":({"attack":0,"durability":0},{"spellSchool":"","races":[],"race":""}),
    "HERO_POWER":({"attack":0,"health":0,"durability":0,"armor":0},{"spellSchool":"","races":[],"race":""}),
}

def tag_role_delta(raw_diff):
    owned={"set":{},"removed":[]}
    for tag_id,change in raw_diff.items():
        before,after=change
        if after=="ABSENT":
            owned["removed"].append(str(tag_id))
        else:
            owned["set"][str(tag_id)]=str(after)
    owned["removed"].sort(key=int)
    return {"owned":owned,"referenced":{"set":{},"removed":[]}}

def raw_value_map(role):
    return {str(k):(str(v["value"]) if v.get("valueAttributePresent") else None)
            for k,v in role.items() if v.get("present")}

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

def replay_raw_evidence(initial,raw_transitions,ref_transitions,current):
    state={"owned":{cid:raw_value_map(x["owned"]) for cid,x in initial.items()},
           "referenced":{cid:raw_value_map(x["referenced"]) for cid,x in initial.items()}}
    timeline=[]
    for row in raw_transitions:
        timeline.append((int(row["build"]),0,row["id"],row["rawDiff"],"owned"))
    for group in ref_transitions:
        for row in group.get("changes",[]):
            timeline.append((int(group["build"]),1,row["id"],row["diff"],"referenced"))
    for build,_,cid,diff,role in sorted(timeline,key=lambda x:(x[0],x[1],x[2])):
        values=state[role][cid]
        for tag_id,(before,after) in diff.items():
            tag_id=str(tag_id)
            actual=values.get(tag_id,"ABSENT")
            if actual!=before:
                raise ValueError(f"{cid}: raw {role} Tag {tag_id} build {build}: expected before={before}, got={actual}")
            if after=="ABSENT": values.pop(tag_id,None)
            else: values[tag_id]=str(after)
    for cid in initial:
        if state["owned"][cid]!=raw_value_map(current[cid]["owned"]):
            raise ValueError(f"{cid}: archive owned-role transitions do not reproduce current XML")
        if state["referenced"][cid]!=raw_value_map(current[cid]["referenced"]):
            raise ValueError(f"{cid}: archive referenced-role transitions do not reproduce current XML")
    return state

def main():
    archive_parts=[(ROOT/"sources"/f"archive-238-part-{i}.txt").read_text(encoding="utf-8") for i in (1,2,3)]
    import re,base64,gzip
    b64="".join(re.sub(r"\s+","",re.search(r"BASE64_START\s*(.*?)\s*BASE64_END",p,re.S).group(1)) for p in archive_parts)
    archive=json.loads(gzip.decompress(base64.b64decode(b64,validate=True)))
    manifest={int(x["build"]):x for x in archive["archiveManifest"]}
    cards=read(ROOT/"cards.json")["cards"]
    ids={c["id"] for c in cards}
    dbfs={c["id"]:c["dbfId"] for c in cards}
    initial=extract_xml(XML_DIR/"xml-27845.xml",manifest[27845]["xmlSha256"],164,ids)
    current=extract_xml(XML_DIR/"xml-256589.xml",manifest[256589]["xmlSha256"],164,ids)
    before=extract_xml(XML_DIR/"xml-217489.xml",manifest[217489]["xmlSha256"],164,ids)
    after=extract_xml(XML_DIR/"xml-217964.xml",manifest[217964]["xmlSha256"],164,ids)
    halazzi_before=extract_xml(XML_DIR/"xml-236529.xml",manifest[236529]["xmlSha256"],164,ids)
    halazzi_after=extract_xml(XML_DIR/"xml-237510.xml",manifest[237510]["xmlSha256"],164,ids)
    for cid in ids:
        if before[cid]["dbfId"]!=dbfs[cid] or after[cid]["dbfId"]!=dbfs[cid]:
            raise ValueError(f"{cid}: 217489/217964 immutable DBF mismatch")
    raw_transitions=archive.get("observedRawTransitionReview",[])
    ref_transitions=archive.get("observedReferencedTagTransitions",[])
    # The immutable audit review contains every own/reference role transition
    # from launch to current. Only explicitly classified gameplay/32.0 events
    # receive a Korean date; all other observations stay undated.
    dated_by_card={}
    undated_by_card={}
    for row in raw_transitions:
        date=None
        if row["decision"]=="weapon_durability_tag_migration_same_value":
            date="2025-03-19"
        elif row["decision"].startswith("gameplay_"):
            findings=row.get("relatedFindings",[])
            dates={FINDING_DATES[x] for x in findings if x in FINDING_DATES}
            if len(dates)!=1:
                raise ValueError(f"{row['id']}: gameplay raw transition has no unique confirmed Korean date: {findings}")
            date=dates.pop()
        if date:
            key=(row["id"],date)
            if key in dated_by_card: raise ValueError(f"duplicate dated raw transition {key}")
            dated_by_card[key]=row
        else:
            undated_by_card.setdefault(row["id"],[]).append(copy.deepcopy(row))
    expected_dated_count=51
    if len(dated_by_card)!=expected_dated_count:
        raise ValueError(f"Expected 51 confirmed dated raw-role events, got {len(dated_by_card)}")
    if sum(len(x.get("changes",[])) for x in ref_transitions)!=15:
        raise ValueError("Expected 15 separately preserved undated ReferencedTag transitions")
    # Verify all 106 own and 15 referenced transitions, including undated
    # bookkeeping, reproduce the immutable current XML role maps.
    replay_raw_evidence(initial,raw_transitions,ref_transitions,current)
    # Build the exact per-card schema omission manifest from the 164-card audit list.
    schema_cards=[]
    for card in cards:
        if card["type"] not in TYPE_OMISSIONS: raise ValueError(f"{card['id']}: unreviewed type {card['type']}")
        numeric,choice=TYPE_OMISSIONS[card["type"]]
        schema_cards.append({"id":card["id"],"type":card["type"],
            "omitNumeric":{k:str(v) for k,v in numeric.items()},
            "omitChoice":{k:("[]" if v==[] else '""') for k,v in choice.items()}})
    schema_manifest={"schema":"RAST-SCHEMA-S002","source":"Rastakhan audit 44, sections 29-34",
        "cards":schema_cards,"numericFieldCount":sum(len(x["omitNumeric"]) for x in schema_cards),
        "emptyChoiceFieldCount":sum(len(x["omitChoice"]) for x in schema_cards)}
    if len(schema_cards)!=164 or schema_manifest["numericFieldCount"]!=406 or schema_manifest["emptyChoiceFieldCount"]!=220:
        raise ValueError("RAST-SCHEMA-S002 scope/count mismatch")
    write(ROOT/"sources"/"rast-schema-s002.json",schema_manifest)
    updated=0
    for card in cards:
        cid=card["id"]; path=DATA/(cid+".json"); src=read(path)
        if src.get("schemaVersion")!=2: raise ValueError(f"{cid}: migrate step must run before enrich")
        if src["_current"].get("dbfId")!=initial[cid]["dbfId"] or src["_current"].get("dbfId")!=current[cid]["dbfId"]:
            raise ValueError(f"{cid}: immutable launch/current DBF mismatch")
        meta=src["_meta"]
        # Normalize only the explicitly audited type-inapplicable keys in
        # date-first snapshots. _current/cards/render and nativeTags are untouched.
        numeric_omit,choice_omit=TYPE_OMISSIONS[card["type"]]
        expected_omit={**numeric_omit,**choice_omit}
        removed_schema=[]
        for day in sorted(k for k in src if len(k)==10 and k[4]=="-" and k[7]=="-"):
            row=src[day]
            for field,expected_value in expected_omit.items():
                if field in row:
                    if row[field]!=expected_value:
                        raise ValueError(f"{cid}/{day}/{field}: expected S002 value {expected_value!r}, got {row[field]!r}")
                    removed_schema.append({"date":day,"field":field,"value":copy.deepcopy(row[field])})
                    del row[field]
        prior_schema=meta.get("schemaNormalization")
        if prior_schema is None:
            launch_removed=[x for x in removed_schema if x["date"]=="2018-12-05"]
            expected_launch_count=len(expected_omit)
            if len(launch_removed)!=expected_launch_count or len(removed_schema)!=expected_launch_count:
                raise ValueError(f"{cid}: S002 expected {expected_launch_count} launch-only omissions, got {len(removed_schema)}")
            meta["schemaNormalization"]={"findingId":"RAST-SCHEMA-S002","date":"2018-12-05",
                "removedFields":sorted(expected_omit)}
        else:
            if prior_schema.get("findingId")!="RAST-SCHEMA-S002" or set(prior_schema.get("removedFields",[]))!=set(expected_omit):
                raise ValueError(f"{cid}: prior S002 normalization record mismatch")
            if removed_schema:
                raise ValueError(f"{cid}: S002 fields reappeared after normalization")
        for field,value in expected_omit.items():
            if src["_current"].get(field,"ABSENT")!=value:
                raise ValueError(f"{cid}: current compatibility value for {field} must remain {value!r}")
        # Preserve the complete original four-key JSON exactly; never regenerate
        # canonical dates from this baseline snapshot.
        baseline_raw=subprocess.check_output(
            ["git","show",f"{BASELINE_COMMIT}:data/{cid}.json"],cwd=ROOT)
        baseline_doc=json.loads(baseline_raw)
        if set(baseline_doc)!={"schemaVersion","mode","card","artworkProvenance"}:
            raise ValueError(f"{cid}: original four-key source shape changed")
        baseline_card=copy.deepcopy(baseline_doc["card"])
        if cid=="TRL_351":
            for item in baseline_card["nativeTags"]:
                if int(item["id"])==215:item["value"]=3
        if baseline_card!=src["_current"]:
            raise ValueError(f"{cid}: current state differs from original four-key card beyond allowed Tag 215 correction")
        meta["originalFourKeySourceRaw"]=baseline_raw.decode("utf-8")
        meta["originalFourKeySourceSnapshot"]=baseline_doc
        meta["originalFourKeySourceSha256"]=hashlib.sha256(baseline_raw).hexdigest()
        meta["launchNativeTagsOwned"]=copy.deepcopy(initial[cid]["owned"])
        meta["launchNativeTagsReferenced"]=copy.deepcopy(initial[cid]["referenced"])
        meta["currentNativeTagsOwned"]=copy.deepcopy(current[cid]["owned"])
        meta["currentNativeTagsReferenced"]=copy.deepcopy(current[cid]["referenced"])
        meta["launchStringTags"]=copy.deepcopy(initial[cid]["stringTags"])
        meta["currentStringTags"]=copy.deepcopy(current[cid]["stringTags"])
        meta["undatedRawTagTransitions"]=copy.deepcopy(undated_by_card.get(cid,[]))
        meta["undatedReferencedTagTransitions"]=[{**copy.deepcopy(x),"build":group["build"]} for group in ref_transitions
            for x in group.get("changes",[]) if x.get("id")==cid]
        # Tag 184 is the printed description; Tag 185 is only the card name.
        # Preserve tag/locale absence separately from a present empty string.
        def printed_text(snapshot):
            tag=snapshot["stringTags"].get("184")
            locales=tag.get("locales",{}) if tag else {}
            return {"tagId":184,"present":tag is not None,
                "koKR":locales.get("koKR",{}).get("value"),
                "enUS":locales.get("enUS",{}).get("value"),
                "koKRPresent":"koKR" in locales,"enUSPresent":"enUS" in locales}
        meta["launchPrintedText"]=printed_text(initial[cid])
        meta["currentPrintedText"]=printed_text(current[cid])
        if cid=="TRL_900":
            # Preserve the exact Tag 184 state immediately before and after the
            # confirmed 35.0 text change. Later current-vs-middle formatting is
            # deliberately undated; never overwrite either immutable snapshot.
            middle_before=halazzi_before[cid]["stringTags"].get("184")
            middle_after=halazzi_after[cid]["stringTags"].get("184")
            if middle_before!=initial[cid]["stringTags"].get("184"):
                raise ValueError("TRL_900: 236529 Tag 184 does not match launch raw state")
            if not middle_after or middle_after.get("type")!="LocString":
                raise ValueError("TRL_900: 237510 Tag 184 LocString missing")
            if middle_after.get("locales",{}).get("koKR",{}).get("value") != "<b>속공</b>, <b>전투의_함성:</b>\\n내 손을 <b>속공</b> 능력이 있는 1/1 스라소니로 가득 채웁니다.":
                raise ValueError("TRL_900: 237510 Korean Tag 184 raw text mismatch")
            if middle_after.get("locales",{}).get("enUS",{}).get("value") != "<b>Rush</b>. <b>Battlecry:</b> Fill your hand with 1/1 Lynxes\\nthat have <b>Rush</b>.":
                raise ValueError("TRL_900: 237510 English Tag 184 raw text mismatch")
            meta["datedStringTagObservations"]=[{
                "date":"2026-03-11","build":237510,"tagId":184,
                "before":copy.deepcopy(middle_before),"after":copy.deepcopy(middle_after),
                "source":{"beforeBuild":236529,"beforeCommit":"0a5a61e3867ae9eea535bdbd4df714671ff87910",
                    "beforeXmlSha256":"7dac9874ff56544d1b2c43c6e446fad519f059b66073c3960318a01c32d66a26",
                    "afterCommit":"a770d899b7ea12594f2edfc7d097f6ee0a858eb8",
                    "afterXmlSha256":"a86b5126943a91ceb1e18decca646ce533f0a06c3fec34e12dc11f45e602c3e6"}
            }]
        # Attach the audited own-Tag delta to its confirmed date-first event.
        dated_row=dated_by_card.get((cid,"2018-12-05"))
        if dated_row: raise ValueError(f"{cid}: raw role event cannot be dated to launch")
        card_dated=[(day,row) for (card_id,day),row in dated_by_card.items() if card_id==cid]
        for day,row in card_dated:
            if day not in src: raise ValueError(f"{cid}: confirmed raw-role date {day} has no canonical event")
            delta=tag_role_delta(row["rawDiff"])
            event=src[day]
            if "nativeTagRolesDelta" in event and event["nativeTagRolesDelta"]!=delta:
                raise ValueError(f"{cid}/{day}: pre-existing nativeTagRolesDelta conflicts with immutable raw evidence")
            event["nativeTagRolesDelta"]=delta
            if not isinstance(event.get("source"),dict): event["source"]={}
            source=event["source"]
            source["rawRoleEvidence"]={"build":row["build"],"decision":row["decision"],
                "findingIds":copy.deepcopy(row.get("relatedFindings",[])),"rawDiff":copy.deepcopy(row["rawDiff"]),"sourceURL":row.get("sourceURL")}
        # Replay dated logical deltas to capture any remaining current-vs-dated
        # differences as explicitly undated observations, never as invented dates.
        dates=sorted(k for k in src if len(k)==10 and k[4]=="-" and k[7]=="-")
        replay_state=copy.deepcopy(src[dates[0]])
        for day in dates[1:]:
            ev=src[day]
            for field,value in ev.items():
                if field in ("nativeTagRolesDelta","source","confidence"): continue
                if field=="removedFields":
                    for removed in value: replay_state.pop(removed,None)
                else: replay_state[field]=copy.deepcopy(value)
        undated=[]
        schema_fields=set(meta.get("schemaNormalization",{}).get("removedFields",[]))
        for field in sorted(set(replay_state)|set(src["_current"])):
            if field in schema_fields: continue
            before_value=replay_state.get(field,"ABSENT")
            after_value=src["_current"].get(field,"ABSENT")
            if before_value!=after_value:
                undated.append({"field":field,"before":copy.deepcopy(before_value),
                                "after":copy.deepcopy(after_value),"date":None})
        meta["undatedCurrentDifferences"]=undated
        if cid in WEAPONS:
            old=before[cid]; new=after[cid]; n=str(WEAPONS[cid])
            if old["owned"].get("187",{}).get("value")!=n or old["owned"].get("45",{}).get("present") is True:
                raise ValueError(f"{cid}: 217489 weapon raw state mismatch")
            if new["owned"].get("187",{}).get("present") is True or new["owned"].get("45",{}).get("value")!=n:
                raise ValueError(f"{cid}: 217964 weapon raw state mismatch")
            if current[cid]["owned"]!=new["owned"] or current[cid]["referenced"]!=new["referenced"]:
                raise ValueError(f"{cid}: post-32.0 weapon raw roles changed again; do not absorb into 2025 event")
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
        "datedRawRoleEvents":len(dated_by_card),"undatedOwnTransitions":sum(len(x) for x in undated_by_card.values()),
        "undatedReferencedTransitions":sum(len(x.get("changes",[])) for x in ref_transitions),
        "schemaNumericOmissions":schema_manifest["numericFieldCount"],
        "schemaChoiceOmissions":schema_manifest["emptyChoiceFieldCount"],
        "weaponRepresentationEvents":len(WEAPONS),"weaponSnapshotCards":164},ensure_ascii=False))

def get_value(tags,tag_id):
    for t in tags:
        if int(t["id"])==tag_id:return str(t["value"])
    return "ABSENT"

if __name__=="__main__": main()
