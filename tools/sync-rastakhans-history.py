#!/usr/bin/env python3
"""Synchronize the central date-first ledger from per-card canonical v2 sources."""
from __future__ import annotations
import copy,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
DATE=re.compile(r"^\d{4}-\d{2}-\d{2}$")
RESERVED={"schemaVersion","_meta","_current"}

def read(p):return json.loads(p.read_text(encoding="utf-8"))
def write(p,o):p.write_text(json.dumps(o,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")

def main():
    catalog=read(ROOT/"cards.json")
    cards=catalog["cards"]
    events={}
    observations={"undatedRawTags":{},"undatedReferencedTags":{},"undatedStringTags":{},
                  "undatedFields":{},"undatedCurrentDifferences":{},"undatedStringTagsByObservation":{},"datedStringTags":{},"halazziRush":None,"nativeTagCorrections":{}}
    initial=followups=0
    dated_role_events=0
    for card in cards:
        cid=card["id"]; src=read(DATA/(cid+".json"))
        if src.get("schemaVersion")!=2 or src.get("_meta",{}).get("timezone")!="Asia/Seoul":
            raise ValueError(f"{cid}: canonical date-first v2 source missing")
        date_keys=[k for k in src if DATE.fullmatch(k)]
        if not date_keys or date_keys[0]!="2018-12-05":
            raise ValueError(f"{cid}: launch state missing or not first")
        if any(a>=b for a,b in zip(date_keys,date_keys[1:])):
            raise ValueError(f"{cid}: date keys are not strictly sorted")
        initial+=1; followups+=len(date_keys)-1
        for day in date_keys:
            if cid in events.setdefault(day,{}):raise ValueError(f"duplicate central event {day}/{cid}")
            events[day][cid]=copy.deepcopy(src[day])
            if day!= "2018-12-05" and "nativeTagRolesDelta" in src[day]: dated_role_events+=1
        meta=src["_meta"]
        if meta.get("undatedRawTagTransitions"):
            observations["undatedRawTags"][cid]=copy.deepcopy(meta["undatedRawTagTransitions"])
        if meta.get("undatedReferencedTagTransitions"):
            observations["undatedReferencedTags"][cid]=copy.deepcopy(meta["undatedReferencedTagTransitions"])
        if meta.get("undatedFieldObservations"):
            observations["undatedFields"][cid]=copy.deepcopy(meta["undatedFieldObservations"])
        if meta.get("undatedCurrentDifferences"):
            observations["undatedCurrentDifferences"][cid]=copy.deepcopy(meta["undatedCurrentDifferences"])
        if meta.get("nativeTagCorrections"):
            observations["nativeTagCorrections"][cid]=copy.deepcopy(meta["nativeTagCorrections"])
        if meta.get("undatedStringTagObservations"):
            observations["undatedStringTagsByObservation"][cid]=copy.deepcopy(meta["undatedStringTagObservations"])
        if meta.get("datedStringTagObservations"):
            observations["datedStringTags"][cid]=copy.deepcopy(meta["datedStringTagObservations"])
        if meta.get("halazziRushEvidence"):
            observations["halazziRush"]=copy.deepcopy(meta["halazziRushEvidence"])
        launch=meta.get("launchStringTags",{})
        current=meta.get("currentStringTags",{})
        diffs=[]
        for tid in sorted(set(launch)|set(current),key=int):
            before=launch.get(tid,"ABSENT"); after=current.get(tid,"ABSENT")
            if before!=after:
                diffs.append({"tagId":int(tid),"before":copy.deepcopy(before),"after":copy.deepcopy(after),"date":None})
        if diffs:observations["undatedStringTags"][cid]=diffs
    if initial!=164 or followups!=51 or initial+followups!=215:
        raise ValueError(f"Expected 164 initial + 51 follow-up = 215, got {initial}+{followups}")
    if len(events.get("2018-12-05",{}))!=164:
        raise ValueError("central launch event must contain all 164 cards")
    if dated_role_events!=51:
        raise ValueError(f"Expected 51 dated raw-role events, got {dated_role_events}")
    if observations["datedStringTags"].get("TRL_900",[]).__len__()!=1:
        raise ValueError("Expected exactly one independently sourced dated TRL_900 Tag 184 observation")
    # Each of the seven 32.0 representation events must be present and must not
    # change logical durability or add a gameplay stat field.
    weapons=("TRL_074","TRL_111","TRL_304","TRL_325","TRL_352","TRL_360","TRL_543")
    for cid in weapons:
        ev=read(DATA/(cid+".json"))["2025-03-19"]
        if not {"nativeTags","nativeTagRolesDelta","source"}.issubset(ev) or "durability" in ev or ev["source"].get("isGameplayBuff") is not False:
            raise ValueError(f"{cid}: 32.0 weapon event must remain representation-only; keys={sorted(ev)} source={ev.get('source')}")
    old=read(DATA/"history.json") if (DATA/"history.json").exists() else {}
    out={"schema":2,"timezone":"Asia/Seoul","format":"date-first-sparse-delta",
         "initialStates":initial,"followupEvents":followups,"totalStates":initial+followups,
         "events":{day:{cid:day_cards[cid] for cid in sorted(day_cards)} for day,day_cards in sorted(events.items())},
         "observations":observations,
         "sources":{"launchBuild":27845,"launchCommit":"0565689bc30e7fe550053066d033958f1f90033f",
                   "currentBuild":256589,"currentCommit":"31b034c26f24b8a66ece845ffd03c1ca397b9a02",
                   "archiveParts":["sources/archive-238-part-1.txt","sources/archive-238-part-2.txt","sources/archive-238-part-3.txt"],
                   "archiveJsonSha256":"e9b8a4bb39895852903de414e6f74fda6b645b6e73293efc3df70fe0a4a9201a"},
         "verification":{"archiveBuilds":238,"originalCardObservations":39032,
                         "weaponRepresentationEvents":7,"datedGameplayEventsAdded":5,"datedRawRoleEvents":dated_role_events,
                         "undatedStringDifferences":sum(len(x) for x in observations["undatedStringTags"].values()),
                         "datedStringTagObservations":sum(len(x) for x in observations["datedStringTags"].values())},
         "notes":["Missing or empty values are distinct from 0, false, empty string and empty arrays.",
                  "Raw Tag and ReferencedTag roles are separate from flattened nativeTags.",
                  "Undated observations never become invented dated events.",
                  "BOT_900 own Rush effective day remains unresolved."]}
    write(DATA/"history.json",out)
    print(json.dumps({"initialStates":initial,"followupEvents":followups,"totalStates":initial+followups,
                      "dates":len(events),"undatedStringCards":len(observations["undatedStringTags"]),
                      "undatedRawCards":len(observations["undatedRawTags"]),"datedRawRoleEvents":dated_role_events},ensure_ascii=False))
if __name__=="__main__":main()
