import json,re,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
WEAPONS={"TRL_074":3,"TRL_111":2,"TRL_304":3,"TRL_325":4,"TRL_352":3,"TRL_360":4,"TRL_543":2}
SPIRITS=("TRL_060","TRL_092","TRL_223","TRL_251","TRL_309","TRL_319","TRL_327","TRL_901")

def read(p):return json.loads(p.read_text(encoding="utf-8"))
def tag(tags,tid):
    return next((str(x["value"]) for x in tags if int(x["id"])==tid),"ABSENT")

class RastakhansHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=read(ROOT/"cards.json")
        cls.central=read(DATA/"history.json")
        cls.cards={c["id"]:read(DATA/(c["id"]+".json")) for c in cls.catalog["cards"]}

    def test_exact_scope(self):
        self.assertEqual(len(self.cards),164)
        self.assertEqual(self.central["initialStates"],164)
        self.assertEqual(self.central["followupEvents"],51)
        self.assertEqual(self.central["totalStates"],215)
        self.assertEqual(sum(len(x) for x in self.central["events"].values()),215)

    def test_launch_corrections(self):
        for cid in SPIRITS:
            s=self.cards[cid]["2018-12-05"]
            self.assertEqual(s["races"],[])
            self.assertEqual(s["race"],"")
            self.assertEqual(tag(s["nativeTags"],200),"ABSENT")
            self.assertEqual(tag(s["nativeTags"],2542),"ABSENT")
        self.assertEqual(self.cards["TRL_060"]["2018-12-05"]["cost"],3)
        self.assertEqual(self.cards["TRL_252"]["2018-12-05"]["health"],4)
        self.assertEqual(self.cards["TRL_311"]["2018-12-05"]["races"],["ELEMENTAL"])
        self.assertEqual(self.cards["TRL_900"]["2018-12-05"]["cost"],5)
        self.assertEqual(self.cards["TRL_900"]["2018-12-05"]["attack"],3)

    def test_date_corrections_and_missing_events(self):
        self.assertIn("2020-03-18",self.cards["TRL_124"])
        self.assertNotIn("2020-03-27",self.cards["TRL_124"])
        self.assertIn("2022-11-30",self.cards["TRL_060"])
        self.assertIn("2024-10-30",self.cards["TRL_363t"])
        self.assertIn("2026-02-10",self.cards["TRL_524"])
        self.assertEqual(self.cards["TRL_252"]["2022-04-06"]["health"],5)
        self.assertEqual(self.cards["TRL_311"]["2022-11-30"]["races"],["ELEMENTAL","BEAST"])
        self.assertEqual(self.cards["TRL_060"]["2023-09-29"]["cost"],5)
        self.assertEqual(self.cards["TRL_501"]["2024-10-30"]["races"],["UNDEAD","DRAENEI"])
        self.assertEqual(self.cards["TRL_900"]["2026-03-11"]["cost"],4)

    def test_2022_rows_are_not_contaminated(self):
        self.assertNotIn("cost",self.cards["TRL_060"]["2022-11-30"])
        self.assertEqual(tag(self.cards["TRL_060"]["2022-11-30"]["nativeTags"],48),"3")
        self.assertEqual(self.cards["TRL_501"]["2022-11-30"]["races"],["UNDEAD"])
        self.assertEqual(tag(self.cards["TRL_501"]["2022-11-30"]["nativeTags"],2525),"ABSENT")

    def test_weapon_tag_migration_is_not_a_buff(self):
        for cid,dur in WEAPONS.items():
            e=self.cards[cid]["2025-03-19"]
            self.assertNotIn("durability",e)
            self.assertEqual(e["source"]["durabilityBefore"],dur)
            self.assertEqual(e["source"]["durabilityAfter"],dur)
            self.assertEqual(e["nativeTagRolesDelta"]["owned"]["removed"],["187"])
            self.assertEqual(e["nativeTagRolesDelta"]["owned"]["set"],{"45":str(dur)})
            self.assertEqual(tag(e["nativeTags"],45),str(dur))
            self.assertEqual(tag(e["nativeTags"],187),"ABSENT")

    def test_raw_roles_strings_and_halazzi_undated_status(self):
        for cid,src in self.cards.items():
            meta=src["_meta"]
            self.assertIn("launchNativeTagsOwned",meta)
            self.assertIn("launchNativeTagsReferenced",meta)
            self.assertIn("currentNativeTagsOwned",meta)
            self.assertIn("currentNativeTagsReferenced",meta)
            self.assertIn("launchStringTags",meta)
            self.assertIn("currentStringTags",meta)
            for stage in ("launch","current"):
                for t in meta[stage+"StringTags"].values():
                    self.assertIn(t["type"],("String","LocString",None))
                    self.assertIn("valueAttributePresent",t)
                    self.assertIn("textContent",t)
        h=self.cards["TRL_900"]["_meta"]["undatedGameplayObservations"][0]
        self.assertIsNone(h["date"])
        self.assertIsNone(h["actualFirstEffectiveDay"])
        self.assertEqual(h["firstObservedBuild"],247416)
        self.assertNotIn("nativeTagRolesDelta",self.cards["TRL_900"]["2026-03-11"])

    def test_preserved_zero_false_and_empty_values(self):
        for cid in ("TRL_128","TRL_243","TRL_310"):
            self.assertEqual(self.cards[cid]["_current"]["cost"],0)
        self.assertEqual(self.cards["TRL_065"]["_current"]["health"],30)
        self.assertEqual(self.cards["TRL_065"]["_current"]["armor"],5)
        self.assertEqual(self.cards["TRL_351"]["_current"]["flavor"],self.cards["TRL_351"]["_current"]["flavor"])
        self.assertEqual(tag(self.cards["TRL_351"]["_current"]["nativeTags"],215),"3")
        for cid in ("TRL_254a","TRL_254b"):
            self.assertNotIn("cost",self.cards[cid]["2018-12-05"])
            self.assertEqual(self.cards[cid]["_current"]["cost"],4)

if __name__=="__main__":unittest.main()
