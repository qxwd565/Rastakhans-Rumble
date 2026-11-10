#!/usr/bin/env python3
"""One-time migration of the verified Rastakhan date-first ledger.

The old per-card four-key files are preserved as provenance metadata; this script
will refuse to regenerate an already-migrated v2 source from the old baseline.
"""
from __future__ import annotations
import base64, copy, gzip, hashlib, json, re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
INITIAL_DATE="2018-12-05"
ARCHIVE_SHA="e9b8a4bb39895852903de414e6f74fda6b645b6e73293efc3df70fe0a4a9201a"
ARCHIVE_BYTES=529892
WEAPON_DURABILITY={"TRL_074":3,"TRL_111":2,"TRL_304":3,"TRL_325":4,"TRL_352":3,"TRL_360":4,"TRL_543":2}
SPIRIT_IDS=("TRL_060","TRL_092","TRL_223","TRL_251","TRL_309","TRL_319","TRL_327","TRL_901")

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def write(path,obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")

def archive_json():
    parts=[]
    for n in (1,2,3):
        p=ROOT/"sources"/f"archive-238-part-{n}.txt"
        raw=p.read_text(encoding="utf-8")
        m=re.search(r"BASE64_START\s*(.*?)\s*BASE64_END",raw,re.S)
        if not m: raise ValueError(f"{p.name}: BASE64 section missing")
        parts.append(re.sub(r"\s+","",m.group(1)))
    packed=base64.b64decode("".join(parts),validate=True)
    decoded=gzip.decompress(packed)
    if len(decoded)!=ARCHIVE_BYTES or hashlib.sha256(decoded).hexdigest()!=ARCHIVE_SHA:
        raise ValueError("238-build evidence JSON size/SHA mismatch")
    return json.loads(decoded)

def tag_replace(tags,tag_id,value):
    result=copy.deepcopy(tags)
    found=False
    for tag in result:
        if int(tag["id"])==tag_id:
            tag["value"]=value
            found=True
            break
    if not found:
        names={45:"생명력",47:"공격력",48:"마나 비용",200:"종족",2525:"게임 태그 2525",2542:"게임 태그 2542"}
        result.append({"id":tag_id,"name":names.get(tag_id,f"게임 태그 {tag_id}"),"value":value})
    return sorted(result,key=lambda x:int(x["id"]))

def tag_remove(tags,tag_id):
    return [copy.deepcopy(x) for x in tags if int(x["id"])!=tag_id]

def get_tag(tags,tag_id):
    for x in tags:
        if int(x["id"])==tag_id: return str(x["value"])
    return "ABSENT"

def add_event(events,date,cid,event):
    if date in events and cid in events[date]:
        raise ValueError(f"duplicate event {date}/{cid}")
    events.setdefault(date,{})[cid]=copy.deepcopy(event)

def replay(initial,events):
    state=copy.deepcopy(initial)
    for day in sorted(events):
        ev=events[day]
        for key,value in ev.items():
            if key in ("nativeTagRolesDelta","source","confidence","removedFields"):
                continue
            state[key]=copy.deepcopy(value)
        for key in ev.get("removedFields",[]):
            state.pop(key,None)
    return state

def main():
    archive=archive_json()
    manifest=archive.get("archiveManifest",[])
    if len(manifest)!=238 or archive.get("summaryCounts",{}).get("cards")!=164:
        raise ValueError("Unexpected archive scope")
    cards_doc=read(ROOT/"cards.json")
    central=read(DATA/"history.json")
    cards=cards_doc.get("cards",[])
    if len(cards)!=164 or len(central.get("events",{}).get(INITIAL_DATE,{}))!=164:
        raise ValueError("Expected 164 cards and 164 launch states")
    ids={x["id"] for x in cards}
    if set(central["events"][INITIAL_DATE])!=ids:
        raise ValueError("launch ledger IDs differ from cards.json")
    existing=[read(DATA/(cid+".json")) for cid in sorted(ids)]
    if all(x.get("schemaVersion")==2 for x in existing):
        print(json.dumps({"migration":"already-v2","cards":len(existing),"noBaselineReplay":True}))
        return
    if any(x.get("schemaVersion")==2 for x in existing):
        raise ValueError("partial v2 migration detected; refusing baseline overwrite")

    # Move only the documented Korean-effective dates; preserve each row's content
    # except the two explicitly identified future-value contamination cases.
    date_moves={
        ("2020-03-27","TRL_124"):"2020-03-18",
        ("2024-11-06","TRL_363t"):"2024-10-30",
        ("2024-11-06","TRL_524"):"2026-02-10",
    }
    byid={x["id"]:x for x in cards}
    per_card={cid:{"initial":copy.deepcopy(central["events"][INITIAL_DATE][cid]),"events":{},"old":None}
              for cid in ids}
    for old_day,day_cards in central["events"].items():
        if old_day==INITIAL_DATE: continue
        for cid,stored in day_cards.items():
            day=date_moves.get((old_day,cid),"2022-11-30" if old_day=="2022-12-07" else old_day)
            ev=copy.deepcopy(stored)
            if cid=="TRL_060" and old_day=="2022-12-07":
                ev.pop("cost",None)
                if "nativeTags" in ev:
                    ev["nativeTags"]=tag_replace(ev["nativeTags"],48,3)
            if cid=="TRL_501" and old_day=="2022-12-07":
                ev["races"]=["UNDEAD"]
                ev["race"]="언데드"
                if "nativeTags" in ev:
                    ev["nativeTags"]=tag_remove(ev["nativeTags"],2525)
            if day in per_card[cid]["events"]:
                raise ValueError(f"date collision {cid}/{day}")
            per_card[cid]["events"][day]=ev

    # Correct launch states that had later values copied backwards.
    for cid in SPIRIT_IDS:
        st=per_card[cid]["initial"]
        st["races"]=[]
        st["race"]=""
        st["nativeTags"]=tag_remove(tag_remove(st["nativeTags"],200),2542)
    st=per_card["TRL_060"]["initial"]
    st["cost"]=3
    st["nativeTags"]=tag_replace(st["nativeTags"],48,3)
    st=per_card["TRL_252"]["initial"]
    st["health"]=4
    st["nativeTags"]=tag_replace(st["nativeTags"],45,4)
    st=per_card["TRL_311"]["initial"]
    st["races"]=["ELEMENTAL"]
    st["race"]="정령"
    st["nativeTags"]=tag_remove(st["nativeTags"],2542)
    st=per_card["TRL_900"]["initial"]
    st["cost"]=5
    st["attack"]=3
    st["text"]="<b>전투의 함성:</b> 내 손을 <b>속공</b> 능력이 있는 1/1 스라소니로 가득 채웁니다."
    st["nativeTags"]=tag_replace(tag_replace(st["nativeTags"],48,5),47,3)

    # The two choice-only spells have no launch COST Tag. Their current UI cost
    # remains in _current, but no fictitious launch cost or dated change is made.
    for cid in ("TRL_254a","TRL_254b"):
        per_card[cid]["initial"].pop("cost",None)

    # Add the five independently verified missing gameplay events.
    launch=per_card["TRL_252"]["initial"]
    add_event(per_card["TRL_252"]["events"],"2022-04-06","TRL_252",{
        "health":5,"nativeTags":tag_replace(launch["nativeTags"],45,5),
        "source":{"findingId":"RAST-BAL-M001","confidence":"high"}
    })
    launch=per_card["TRL_311"]["initial"]
    add_event(per_card["TRL_311"]["events"],"2022-11-30","TRL_311",{
        "races":["ELEMENTAL","BEAST"],"race":"정령, 야수",
        "nativeTags":tag_replace(launch["nativeTags"],2542,1),
        "source":{"findingId":"RAST-BAL-M002","confidence":"high"}
    })
    before=per_card["TRL_060"]["initial"]
    before=replay(before,{"2022-11-30":per_card["TRL_060"]["events"]["2022-11-30"]})
    add_event(per_card["TRL_060"]["events"],"2023-09-29","TRL_060",{
        "cost":5,"nativeTags":tag_replace(before["nativeTags"],48,5),
        "source":{"findingId":"RAST-BAL-M003","confidence":"high"}
    })
    before=per_card["TRL_501"]["initial"]
    before=replay(before,{"2022-11-30":per_card["TRL_501"]["events"]["2022-11-30"]})
    add_event(per_card["TRL_501"]["events"],"2024-10-30","TRL_501",{
        "races":["UNDEAD","DRAENEI"],"race":"언데드, 드레나이",
        "nativeTags":tag_replace(before["nativeTags"],2525,1),
        "source":{"findingId":"RAST-BAL-M004","confidence":"high"}
    })
    before=per_card["TRL_900"]["initial"]
    halazzi_after_text="<b>속공</b>, <b>전투의 함성</b>: 내 손을 <b>속공</b> 능력이 있는 1/1 스라소니로 가득 채웁니다."
    add_event(per_card["TRL_900"]["events"],"2026-03-11","TRL_900",{
        "cost":4,"attack":4,"text":halazzi_after_text,
        "nativeTags":tag_replace(tag_replace(before["nativeTags"],48,4),47,4),
        "source":{"findingId":"RAST-BAL-M005","confidence":"high","officialIntent":"35.0 adds Rush to Halazzi; first effective operation day remains unresolved"}
    })

    # The seven weapon Tag 187 -> Tag 45 moves are representation-only events.
    for cid,durability in WEAPON_DURABILITY.items():
        add_event(per_card[cid]["events"],"2025-03-19",cid,{
            "nativeTags":copy.deepcopy(byid[cid]["nativeTags"]),
            "nativeTagRolesDelta":{
                "owned":{"removed":["187"],"set":{"45":str(durability)}},
                "referenced":{"removed":[],"set":{}}
            },
            "source":{"findingId":"RAST-EXP-32-0","officialPatch":"32.0","buildBefore":217489,"buildAfter":217964,
                      "durabilityBefore":durability,"durabilityAfter":durability,"isGameplayBuff":False,
                      "note":"Tag ownership migration only; no weapon durability buff"}
        })

    # Apply the sole allowed current flattened-tag correction: own OVERLOAD 215=3.
    byid["TRL_351"]["nativeTags"]=tag_replace(byid["TRL_351"]["nativeTags"],215,3)
    for cid in ids:
        if cid=="TRL_351":
            per_card[cid]["initial"]["nativeTags"]=tag_replace(per_card[cid]["initial"]["nativeTags"],215,3)
        old=read(DATA/(cid+".json"))
        if old.get("card",{}).get("id")!=cid or old.get("card",{}).get("dbfId")!=byid[cid].get("dbfId"):
            raise ValueError(f"{cid}: existing source identity mismatch")
        current=copy.deepcopy(byid[cid])
        if cid=="TRL_351":
            current["nativeTags"]=tag_replace(current["nativeTags"],215,3)
        events=per_card[cid]["events"]
        # All follow-up changes are sparse; reject duplicates and unchanged logical values.
        for day,ev in events.items():
            if not day or day==INITIAL_DATE: raise ValueError(f"{cid}: invalid event date")
        meta={
            "schemaVersion":2,"timezone":"Asia/Seoul",
            "releaseDate":INITIAL_DATE,
            "releaseConfidence":"verified" if current.get("collectible") is True else "estimated",
            "launchSource":{"build":27845,"commit":"0565689bc30e7fe550053066d033958f1f90033f"},
            "currentSource":{"build":256589,"commit":"31b034c26f24b8a66ece845ffd03c1ca397b9a02"},
            "originalFourKeySource":{"schemaVersion":old.get("schemaVersion"),"mode":old.get("mode"),
                                     "artworkProvenance":copy.deepcopy(old.get("artworkProvenance"))},
            "artworkProvenance":copy.deepcopy(old.get("artworkProvenance")),
            "undatedFieldObservations":(
                [{"field":"cost","launchRawTag":"ABSENT","currentUiValue":4,"date":None,"reason":"choice-only option COST; not an independently playable card cost"}]
                if cid in ("TRL_254a","TRL_254b") else []),
            "nativeTagCorrections":(
                [{"tagId":215,"role":"owned","before":"1","after":"3","date":None,"reason":"all 238 archive observations and printed Overload (3) agree"}]
                if cid=="TRL_351" else []),
            "undatedGameplayObservations":(
                [{"field":"rush","officialIntentDate":"2026-03-11","ownTagFirstObservedBuild":247416,
                  "referencedRushAtLaunch":True,"actualFirstEffectiveDay":None,
                  "reason":"own Tag 791 observation is not an effective-date proof"}]
                if cid=="TRL_900" else [])
        }
        doc={"schemaVersion":2,"_meta":meta,"_current":current,
             INITIAL_DATE:copy.deepcopy(per_card[cid]["initial"])}
        for day in sorted(events):
            doc[day]=copy.deepcopy(events[day])
        write(DATA/(cid+".json"),doc)

    # Update only current API card 351's allowed numeric value. All other current
    # fields, false/empty values, art, portrait, mode and provenance remain untouched.
    write(ROOT/"cards.json",cards_doc)
    print(json.dumps({"migration":"v2","cards":len(ids),
        "initialStates":len(ids),"followupEvents":sum(len(x["events"]) for x in per_card.values()),
        "expectedTotalStates":len(ids)+sum(len(x["events"]) for x in per_card.values()),
        "dateCorrections":19,"missingGameplayEvents":5,"expressionEvents":7,
        "baselineRecreated":False},ensure_ascii=False))

if __name__=="__main__":
    main()
