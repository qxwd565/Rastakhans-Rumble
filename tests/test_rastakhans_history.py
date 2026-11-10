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
        cls.render=read(ROOT/"render.json")
        cls.render_cards={c["id"]:c for c in cls.render["cards"]}
        cls.schema=read(ROOT/"sources"/"rast-schema-s002.json")
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
        self.assertEqual(self.cards["TRL_900"]["2026-03-11"]["nativeTagRolesDelta"]["owned"]["set"],{"47":"4","48":"4"})
        self.assertNotIn("791",self.cards["TRL_900"]["2026-03-11"]["nativeTagRolesDelta"]["owned"]["set"])
        dated=self.cards["TRL_900"]["_meta"]["datedStringTagObservations"]
        self.assertEqual(len(dated),1)
        self.assertEqual((dated[0]["date"],dated[0]["build"],dated[0]["tagId"]),("2026-03-11",237510,184))
        before=dated[0]["before"]; after=dated[0]["after"]
        launch=self.cards["TRL_900"]["_meta"]["launchStringTags"]["184"]
        prepatch=self.cards["TRL_900"]["_meta"]["halazziPrePatchStringTagSnapshot"]
        self.assertEqual(before,prepatch)
        self.assertEqual(prepatch["locales"]["koKR"],launch["locales"]["koKR"])
        self.assertEqual(prepatch["locales"]["enUS"],launch["locales"]["enUS"])
        undated=self.cards["TRL_900"]["_meta"]["undatedStringTagObservations"]
        self.assertEqual({x["locale"] for x in undated[0]["differences"]},{"thTH","zhCN"})
        self.assertIsNone(undated[0]["differences"][0]["date"])
        self.assertEqual(prepatch["locales"]["thTH"]["value"],"<b>คำรามสู้ศึก:</b> เพิ่มแมวป่า_1/1_ที่มี <b>จู่โจม</b>_จนเต็มมือคุณ")
        self.assertEqual(prepatch["locales"]["zhCN"]["value"],"<b>战吼：</b>用1/1并具有\\n<b>突袭</b>的山猫填满你的手牌。")
        self.assertEqual(before["type"],"LocString")
        self.assertFalse(before["valueAttributePresent"])
        self.assertEqual(before["locales"]["koKR"]["value"],"<b>전투의_함성:</b> 내 손을 <b>속공</b> 능력이 있는 1/1 스라소니로 가득 채웁니다.")
        self.assertEqual(before["locales"]["enUS"]["value"],"<b>Battlecry:</b> Fill your hand with 1/1 Lynxes that have_<b>Rush</b>.")
        self.assertEqual(after["locales"]["koKR"]["value"],"<b>속공</b>, <b>전투의_함성:</b>\n내 손을 <b>속공</b> 능력이 있는 1/1 스라소니로 가득 채웁니다.")
        self.assertEqual(after["locales"]["enUS"]["value"],"<b>Rush</b>. <b>Battlecry:</b> Fill your hand with 1/1 Lynxes\nthat have <b>Rush</b>.")
        self.assertIn("&",self.cards["TRL_900"]["_meta"]["currentStringTags"]["184"]["locales"]["koKR"]["value"])
        self.assertNotIn("&",after["locales"]["koKR"]["value"])
        public=self.render_cards["TRL_900"]["nativeStringTags"]["datedChanges"]
        self.assertEqual(public,dated)
        self.assertNotIn("datedChanges",self.render_cards["TRL_901"]["nativeStringTags"])

    def test_preserved_zero_false_and_empty_values(self):
        for cid in ("TRL_128","TRL_243","TRL_310"):
            self.assertEqual(self.cards[cid]["_current"]["cost"],0)
        self.assertEqual(self.cards["TRL_065"]["_current"]["health"],30)
        self.assertEqual(self.cards["TRL_065"]["_current"]["armor"],5)
        self.assertEqual(sum(1 for c in self.catalog["cards"] if c.get("collectible") is False and c.get("flavor")=="") ,29)
        self.assertEqual(tag(self.cards["TRL_351"]["_current"]["nativeTags"],215),"3")
        for cid in ("TRL_254a","TRL_254b"):
            self.assertNotIn("cost",self.cards[cid]["2018-12-05"])
            self.assertEqual(self.cards[cid]["_current"]["cost"],4)

    def test_all_dated_raw_role_events(self):
        events=[(cid,day,row) for cid,doc in self.cards.items()
                for day,row in doc.items() if re.fullmatch(r"\d{4}-\d{2}-\d{2}",day)
                and "nativeTagRolesDelta" in row]
        self.assertEqual(len(events),51)
        self.assertEqual(self.cards["TRL_060"]["2022-11-30"]["nativeTagRolesDelta"]["owned"]["set"],{"200":"11","2542":"1"})
        self.assertEqual(self.cards["TRL_060"]["2023-09-29"]["nativeTagRolesDelta"]["owned"]["set"],{"48":"5"})
        self.assertEqual(self.cards["TRL_124"]["2019-05-23"]["nativeTagRolesDelta"]["owned"]["set"],{"48":"4"})
        self.assertEqual(self.cards["TRL_124"]["2020-03-18"]["nativeTagRolesDelta"]["owned"]["set"],{"48":"3"})
        self.assertEqual(self.cards["TRL_252"]["2022-04-06"]["nativeTagRolesDelta"]["owned"]["set"],{"45":"5"})
        self.assertEqual(self.cards["TRL_501"]["2024-10-30"]["nativeTagRolesDelta"]["owned"]["set"],{"2525":"1"})
        self.assertEqual(self.cards["TRL_060"]["_meta"]["launchPrintedText"]["koKR"],"1턴 동안 <b>은신</b>을 얻습니다.\n내가 주문을 시전할 때마다 내 덱에서 그 주문보다 비용이 (1) 높은 주문을 뽑습니다.")

    def test_s002_type_inapplicable_fields_are_absent_only_from_history(self):
        self.assertEqual(self.schema["numericFieldCount"],406)
        self.assertEqual(self.schema["emptyChoiceFieldCount"],220)
        self.assertEqual(len(self.schema["cards"]),164)
        for row in self.schema["cards"]:
            src=self.cards[row["id"]]
            for day in [k for k in src if re.fullmatch(r"\d{4}-\d{2}-\d{2}",k)]:
                for field in list(row["omitNumeric"])+list(row["omitChoice"]):
                    self.assertNotIn(field,src[day],(row["id"],day,field))
            for field in row["omitNumeric"]:
                self.assertIn(field,src["_current"])
            for field in row["omitChoice"]:
                self.assertIn(field,src["_current"])
        self.assertEqual(self.cards["TRL_065"]["_current"]["health"],30)
        self.assertEqual(self.cards["TRL_065"]["_current"]["armor"],5)
        self.assertEqual(sum(1 for c in self.catalog["cards"] if c["type"]=="MINION" and c.get("attack")==0),15)
        self.assertEqual(sum(1 for c in self.catalog["cards"] if c.get("text")==""),10)

    def test_public_reverse_history_uses_complete_current_relative_diff(self):
        frog=self.render_cards["TRL_060"]["history"]
        launch=next(x for x in frog if x["from"]=="2018-12-05")
        undead=next(x for x in frog if x["from"]=="2022-11-30")
        self.assertEqual(launch["changes"]["cost"],3)
        self.assertEqual(undead["changes"]["cost"],3)
        for cid in ("TRL_254a","TRL_254b"):
            card=self.render_cards[cid]
            self.assertEqual(card["cost"],4)
            hist=card["history"]
            self.assertEqual({x["from"] for x in hist},{"2018-12-05","2021-03-26"})
            self.assertTrue(all("cost" in x["removedFields"] for x in hist))
            self.assertTrue(all("cost" not in x["changes"] for x in hist))
            self.assertIsNone(next(x for x in hist if x["from"]=="2021-03-26")["before"])

if __name__=="__main__":unittest.main()
