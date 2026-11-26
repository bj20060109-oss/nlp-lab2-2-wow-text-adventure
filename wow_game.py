# -*- coding: utf-8 -*-



import os

import re

import sys

import json

import random

import logging

import argparse



import openai

import tiktoken



logger = logging.getLogger(__name__)

logging.basicConfig(

    format="%(asctime)s - %(funcName)s() - %(message)s",

    datefmt="%Y/%m/%d %H:%M:%S",

    level=logging.INFO,

)





def read_json(file, write_log=False):

    if write_log:

        logger.info(f"Reading {file}")

    with open(file, "r", encoding="utf8") as f:

        data = json.load(f)

    if write_log:

        objects = len(data)

        logger.info(f"Read {objects:,} objects")

    return data





def write_json(file, data, indent=2, write_log=False):

    if write_log:

        logger.info(f"Writing to {file}")

    with open(file, "w", encoding="utf8") as f:

        json.dump(data, f, indent=indent, ensure_ascii=False)

    if write_log:

        logger.info("Written")





def write_txt(file, text, write_log=False):

    if write_log:

        logger.info(f"Writing {len(text):,} chars to {file}")

    with open(file, "w", encoding="utf8") as f:

        f.write(text)

    if write_log:

        logger.info("Written")





def parse_json_obj(text):

    match = re.search(r"\{.*?\}", text, re.DOTALL)

    if match:

        try:

            return json.loads(match.group(0))

        except json.JSONDecodeError:

            pass

    return {}





class Config:

    def __init__(self, config_file):

        data = read_json(config_file)

        self.model = data["model"]

        self.static_dir = os.path.join(*data["static_dir"])

        self.state_dir = os.path.join(*data["state_dir"])

        self.output_dir = os.path.join(*data["output_dir"])

        os.makedirs(self.state_dir, exist_ok=True)

        os.makedirs(self.output_dir, exist_ok=True)





class GPT:

    def __init__(self, model):

        self.model = model

        self.tokenizer = tiktoken.encoding_for_model(self.model)

        self.model_candidate_tokens = {

            "gpt-3.5-turbo": {"gpt-3.5-turbo": 4096, "gpt-3.5-turbo-16k": 16384},

            "gpt-4": {"gpt-4": 8192, "gpt-4-32k": 32768},

            "gpt-4o-mini": {"gpt-4o-mini": 128000},

            "gpt-5-nano": {"gpt-5-nano": 400000},

        }



    def get_specific_tokens_model(self, text_in, out_tokens):

        in_tokens = len(self.tokenizer.encode(text_in))

        total = in_tokens + out_tokens

        for candidate, max_tokens in self.model_candidate_tokens.get(self.model, {}).items():

            if max_tokens >= total:

                return in_tokens, candidate

        return in_tokens, ""



    def run_gpt(self, text_in, out_tokens=300):

        in_tokens, specific_model = self.get_specific_tokens_model(text_in, out_tokens)

        if not specific_model:

            return ""

        logger.info("Calling LLM (%s, %d in_tokens)...", specific_model, in_tokens)

        extra_args = {}

        if specific_model.startswith("gpt-5"):

            extra_args["reasoning_effort"] = "minimal"



        completion = openai.ChatCompletion.create(

            model=specific_model,

            n=1,

            max_completion_tokens=out_tokens,

            messages=[{"role": "user", "content": text_in}],

            **extra_args,

        )

        return (completion.choices[0].message.content or "").strip()





class State:

    def __init__(self, save_file=""):

        self.save_file = save_file

        self.phase = "character_creation"  # character_creation -> starting_zone -> party_forming -> dungeon -> finished

        self.player_name = ""

        self.race_key = ""

        self.race_name = ""

        self.faction = ""

        self.class_key = ""

        self.class_name = ""

        self.role = ""  # tank / healer / dps

        self.level = 1

        self.exp = 0

        self.hp = 100

        self.max_hp = 100

        self.atk = 20

        self.skills = []

        self.completed_quests = []

        self.party = []  # list of teammate dicts (excluding player, total 5 with player)

        self.dungeon_stage_idx = 0

        self.campaign_digest = ""  # LLM-digested summary fed back to future LLM calls

        self.log = ""

        self.ended = False

        self.victory = False



    def to_dict(self):

        return {

            "phase": self.phase,

            "player_name": self.player_name,

            "race_key": self.race_key,

            "race_name": self.race_name,

            "faction": self.faction,

            "class_key": self.class_key,

            "class_name": self.class_name,

            "role": self.role,

            "level": self.level,

            "exp": self.exp,

            "hp": self.hp,

            "max_hp": self.max_hp,

            "atk": self.atk,

            "skills": self.skills,

            "completed_quests": self.completed_quests,

            "party": self.party,

            "dungeon_stage_idx": self.dungeon_stage_idx,

            "campaign_digest": self.campaign_digest,

            "log": self.log,

            "ended": self.ended,

            "victory": self.victory,

        }



    def save(self):

        if self.save_file:

            write_json(self.save_file, self.to_dict(), indent=2)



    def load(self):

        data = read_json(self.save_file)

        for k, v in data.items():

            if hasattr(self, k):

                setattr(self, k, v)





class WowGame:

    ROLE_LABELS = {

        "tank": "坦克 (Tank)",

        "healer": "治療 (Healer)",

        "dps": "輸出 (DPS)",

    }



    def __init__(self, config):

        self.config = config

        self.state_dir = config.state_dir

        self.output_dir = config.output_dir

        self.gpt = GPT(config.model)

        self.state = State()

        self.summary_file = ""



        self.races_classes = read_json(os.path.join(config.static_dir, "races_classes.json"))

        self.starting_zones = read_json(os.path.join(config.static_dir, "starting_zones.json"))

        self.teammates_pool = read_json(os.path.join(config.static_dir, "teammates.json"))

        self.dungeon = read_json(os.path.join(config.static_dir, "dungeon.json"))



    def append_log(self, text, print_it=False):

        line = text.strip()

        if not line:

            return

        self.state.log += f"\n{line}"

        if print_it:

            print(line)



    def check_level_up(self):

        # Level up every 60 EXP; unlock skills defined in class data

        class_info = self.races_classes["classes"][self.state.class_key]

        unlock_map = class_info.get("unlock_skills_by_level", {})

        leveled = False

        while self.state.exp >= self.state.level * 60 and self.state.level < 3:

            self.state.exp -= self.state.level * 60

            self.state.level += 1

            self.state.max_hp += 25

            self.state.hp = self.state.max_hp

            self.state.atk += 6

            leveled = True

            msg = f"【升級！】{self.state.player_name} 升到了 Lv.{self.state.level}（最大生命值 {self.state.max_hp}，攻擊力 {self.state.atk}）！"

            new_skill = unlock_map.get(str(self.state.level))

            if new_skill and new_skill not in self.state.skills:

                self.state.skills.append(new_skill)

                msg += f" 解鎖新技能：【{new_skill}】！"

            self.append_log(msg, print_it=True)

        return leveled



    def start_menu(self):

        print("\n=== 艾澤拉斯冒險誌：文字版魔獸世界 (Lab 2.2) ===")

        while True:

            choice = input("(1) 開始新冒險\n(2) 讀取既有存檔\n請選擇：").strip()

            if choice in ("1", "2"):

                mode = "new" if choice == "1" else "load"

                break



        print("\n存檔欄位：")

        for i in range(1, 5):

            path = os.path.join(self.state_dir, f"save_{i}.json")

            status = "已有存檔" if os.path.exists(path) else "空白存檔"

            print(f"({i}) save_{i}.json [{status}]")



        while True:

            slot = input("選擇存檔欄位 (1-4)：").strip()

            path = os.path.join(self.state_dir, f"save_{slot}.json")

            if slot in ("1", "2", "3", "4"):

                if mode == "new" or os.path.exists(path):

                    self.state = State(path)

                    self.summary_file = os.path.join(self.output_dir, f"summary_{slot}.txt")

                    if mode == "load":

                        self.state.load()

                        print(f"已讀取存檔 save_{slot}.json（目前階段：{self.state.phase}）")

                    break

                else:

                    print("該欄位尚無存檔，請重新選擇。")



        self.main_loop()



    def create_character(self):

        name = input("\n請輸入你的角色名稱：").strip()

        self.state.player_name = name or "冒險者"



        races = self.races_classes["races"]

        race_keys = list(races.keys())

        print("\n--- 選擇種族 ---")

        for idx, rk in enumerate(race_keys, 1):

            r = races[rk]

            print(f"({idx}) {r['name_zh']} [{r['faction']}] - {r['trait']}")

        while True:

            ans = input("請輸入種族編號：").strip()

            if ans.isdigit() and 1 <= int(ans) <= len(race_keys):

                rk = race_keys[int(ans) - 1]

                r = races[rk]

                self.state.race_key = rk

                self.state.race_name = r["name_zh"]

                self.state.faction = r["faction"]

                break



        classes = self.races_classes["classes"]

        class_keys = list(classes.keys())

        print("\n--- 選擇職業 ---")

        for idx, ck in enumerate(class_keys, 1):

            c = classes[ck]

            roles_str = " / ".join(self.ROLE_LABELS.get(rl, rl) for rl in c["available_roles"])

            print(f"({idx}) {c['name_zh']}（可選定位：{roles_str}；初始技能：{', '.join(c['starter_skills'])}）")

        while True:

            ans = input("請輸入職業編號：").strip()

            if ans.isdigit() and 1 <= int(ans) <= len(class_keys):

                ck = class_keys[int(ans) - 1]

                c = classes[ck]

                self.state.class_key = ck

                self.state.class_name = c["name_zh"]

                self.state.max_hp = c["base_hp"] + races[self.state.race_key].get("hp_bonus", 0)

                self.state.hp = self.state.max_hp

                self.state.atk = c["base_atk"]

                self.state.skills = list(c["starter_skills"])

                break



        zone_data = self.starting_zones["zones_by_race"][self.state.race_key]

        self.append_log(

            f"角色建立：{self.state.player_name}（{self.state.race_name}?{self.state.class_name}，陣營：{self.state.faction}）抵達【{zone_data['zone_name']}】。",

            print_it=True,

        )

        print(zone_data["description"])

        self.state.phase = "starting_zone"

        self.state.save()



    def run_starting_zone(self):

        zone_data = self.starting_zones["zones_by_race"][self.state.race_key]

        quests = zone_data["quests"]



        while True:

            print(f"\n=== 出生地：{zone_data['zone_name']} | Lv.{self.state.level} (EXP: {self.state.exp}) | 技能：{', '.join(self.state.skills)} ===")

            available = [q for q in quests if q["id"] not in self.state.completed_quests]

            if not available:

                print("出生地任務皆已完成！你可以前往組建 5 人副本小隊了。")

                ans = input("(1) 前往組建副本小隊\n(2) 在出生地自由修練拿經驗\n請選擇：").strip()

                if ans == "1":

                    self.state.phase = "party_forming"

                    self.state.save()

                    return

                elif ans == "2":

                    self.do_free_training(zone_data["zone_name"])

                    self.state.save()

                continue



            for idx, q in enumerate(available, 1):

                print(f"({idx}) 任務：【{q['title']}】 - {q['objective']}（獎勵 {q['exp_reward']} EXP）")

            print(f"({len(available) + 1}) 自由行動／修練（獲得少量 EXP）")

            if self.state.level >= 2 or len(self.state.completed_quests) >= 1:

                print(f"({len(available) + 2}) 結束出生地歷練，前往組建 5 人小隊")



            ans = input("請選擇行動：").strip()

            if ans.isdigit() and 1 <= int(ans) <= len(available):

                quest = available[int(ans) - 1]

                self.do_quest_action(zone_data["zone_name"], quest)

                self.state.save()

            elif ans == str(len(available) + 1):

                self.do_free_training(zone_data["zone_name"])

                self.state.save()

            elif ans == str(len(available) + 2) and (self.state.level >= 2 or len(self.state.completed_quests) >= 1):

                self.state.phase = "party_forming"

                self.state.save()

                return



    def do_quest_action(self, zone_name, quest):

        action = input(f"\n接下任務【{quest['title']}】。請輸入你的行動策略（例如：先用控場技能牽制再施放招式）：").strip()

        if not action:

            action = f"運用 {self.state.skills[0]} 執行任務目標"



        # LLM Task 1a: Draft narrative continuation

        draft_prompt = (

            f"在魔獸世界出生地「{zone_name}」，{self.state.player_name}（{self.state.race_name}{self.state.class_name}，"

            f"已掌握技能：{', '.join(self.state.skills)}）正在執行任務「{quest['title']}」（目標：{quest['objective']}）。\n"

            f"玩家行動：{action}\n"

            f"請用繁體中文寫出 2 到 3 句緊湊的冒險經過，只輸出劇情本身。"

        )

        draft = self.gpt.run_gpt(draft_prompt, 220)



        # LLM Task 1b: Digest & polish draft into clean narrative

        polish_prompt = (

            f"請將以下冒險片段潤飾得更流暢且符合魔獸世界氛圍，保留角色名稱與技能名稱，控制在 2 到 3 句繁體中文，只輸出潤飾後內容：\n{draft}"

        )

        story = self.gpt.run_gpt(polish_prompt, 220) or draft

        self.append_log(story, print_it=True)



        # LLM Task 2: Structured JSON judgment for quest outcome

        judge_prompt = (

            f"任務目標：{quest['objective']}\n"

            f"冒險經過：{story}\n"

            f"請判斷玩家是否成功完成此任務。只輸出 JSON，格式為 {{\"completed\": true, \"quality\": \"good\"}} 或 {{\"completed\": false, \"quality\": \"partial\"}}。"

        )

        verdict = parse_json_obj(self.gpt.run_gpt(judge_prompt, 120))

        completed = verdict.get("completed", True) is not False



        exp_bonus = 1.15 if self.state.race_key == "human" else 1.0

        gained_exp = int(quest["exp_reward"] * exp_bonus) if completed else int(quest["exp_reward"] * 0.5)

        self.state.exp += gained_exp

        if completed and quest["id"] not in self.state.completed_quests:

            self.state.completed_quests.append(quest["id"])



        msg = f"任務結算：{'完成！' if completed else '有驚無險推進中'} 獲得 {gained_exp} EXP（目前 EXP: {self.state.exp}）。"

        self.append_log(msg, print_it=True)

        self.check_level_up()



    def do_free_training(self, zone_name):

        action = input("\n輸入你的修練行動：").strip() or "練習核心技能與走位"

        prompt = (

            f"在「{zone_name}」，{self.state.player_name}（{self.state.race_name}{self.state.class_name}）進行修練：{action}。\n"

            f"請用 2 句繁體中文描述修練成果，只輸出內容。"

        )

        text = self.gpt.run_gpt(prompt, 180)

        self.append_log(text, print_it=True)

        self.state.exp += 25

        self.append_log("修練獲得 25 EXP。", print_it=True)

        self.check_level_up()



    def form_party(self):

        class_info = self.races_classes["classes"][self.state.class_key]

        avail_roles = class_info.get("available_roles", ["dps"])



        print("\n=== 選擇你的副本定位（團隊配置需求：1 坦克 / 1 治療 / 3 輸出）===")

        for idx, rl in enumerate(avail_roles, 1):

            print(f"({idx}) {self.ROLE_LABELS.get(rl, rl)}")



        while True:

            ans = input("請選擇你的定位編號：").strip()

            if ans.isdigit() and 1 <= int(ans) <= len(avail_roles):

                self.state.role = avail_roles[int(ans) - 1]

                break



        req = {"tank": 1, "healer": 1, "dps": 3}

        current = {"tank": 0, "healer": 0, "dps": 0}

        current[self.state.role] += 1



        self.state.party = []

        used_ids = set()



        print(f"\n你選擇了【{self.ROLE_LABELS[self.state.role]}】。接下來招募 AI 隊友，湊齊 1 坦 / 1 補 / 3 輸出！")



        while len(self.state.party) < 4:

            need_roles = [r for r, cnt in current.items() if cnt < req[r]]

            print(f"\n目前隊伍人數：{1 + len(self.state.party)}/5 | 已配置：坦 {current['tank']}/1、補 {current['healer']}/1、輸出 {current['dps']}/3")

            print(f"目前急需定位：{', '.join(self.ROLE_LABELS[r] for r in need_roles)}")



            candidates = [t for t in self.teammates_pool if t["id"] not in used_ids]

            if not candidates:

                break



            print("\n可招募隊友列表：")

            for idx, t in enumerate(candidates, 1):

                role_zh = self.ROLE_LABELS.get(t["role"], t["role"])

                tag = "（符合缺口）" if t["role"] in need_roles else "（該位置已滿）"

                print(f"({idx}) {t['name']} | 種族：{t['race']} | 職業：{t['class']} | 定位：{role_zh} | 等級：Lv.{t['level']} {tag}")



            pick = input("請輸入要招募的隊友編號：").strip()

            if pick.isdigit() and 1 <= int(pick) <= len(candidates):

                chosen = dict(candidates[int(pick) - 1])

                r_key = chosen["role"]

                if current[r_key] >= req[r_key]:

                    print(f"【{self.ROLE_LABELS[r_key]}】位置已滿（上限 {req[r_key]} 人），請選擇其他定位的隊友！")

                    continue



                used_ids.add(chosen["id"])

                current[r_key] += 1

                self.state.party.append(chosen)



                # LLM Task 3: Generate join banter based on player & teammate profile

                join_prompt = (

                    f"玩家 {self.state.player_name}（{self.state.race_name}{self.state.class_name}，定位：{self.ROLE_LABELS[self.state.role]}）"

                    f"招募了隊友 {chosen['name']}（{chosen['race']}{chosen['class']}，定位：{self.ROLE_LABELS[r_key]}，Lv.{chosen['level']}，性格：{chosen['personality']}）。\n"

                    f"請用 1 句繁體中文寫出該隊友加入小隊時的台詞，只輸出台詞。"

                )

                quote = self.gpt.run_gpt(join_prompt, 120)

                line = f"隊友入隊：{chosen['name']}（{chosen['race']}?{chosen['class']}?{self.ROLE_LABELS[r_key]}?Lv.{chosen['level']}）——「{quote}」"

                self.append_log(line, print_it=True)

                self.state.save()



        self.state.phase = "dungeon"

        self.state.save()

        print("\n5 人小隊組建完成！準備進入地下城！")



    def run_dungeon(self):
        stages = self.dungeon["stages"]
        dungeon_name = self.dungeon["dungeon_name"]

        while self.state.dungeon_stage_idx < len(stages):
            stage = stages[self.state.dungeon_stage_idx]
            stage_num = stage["stage"]
            enemy_hp = stage["enemy_hp"]
            enemy_max_hp = stage["enemy_hp"]
            armor_broken = False
            turn = 1

            print(f"\n================ {dungeon_name}・第 {stage_num} 階段：{stage['name']} ================")
            print(f"首領／敵軍：{stage['enemy_name']}（HP: {enemy_hp}）")
            print(f"機制提示：{stage['mechanic']}")

            while enemy_hp > 0 and self.state.hp > 0:
                print(
                    f"\n--- 第 {turn} 回合 | {stage['enemy_name']} HP: {max(0, enemy_hp)}/{enemy_max_hp} | "
                    f"{self.state.player_name} HP: {self.state.hp}/{self.state.max_hp} ---"
                )
                print(f"可用技能：{', '.join(self.state.skills)}")
                player_cmd = input("請輸入你的戰術指令（例如：使用衝鋒與英勇打擊穩住仇恨，提醒補師注意血線）：").strip()
                if not player_cmd:
                    player_cmd = f"使用 {self.state.skills[0]} 攻擊目標"

                party_summary = ", ".join(
                    f"{m['name']}（{m['class']}/{m['role']}，Lv.{m['level']}）" for m in self.state.party
                )

                # LLM Task 4a: Combat narrative + tactical multiplier (digests prior campaign_digest)
                combat_prompt = (
                    f"你是魔獸世界地下城「{dungeon_name}」第 {stage_num} 階段的戰鬥敘事與首領 AI。\n"
                    f"敵軍：{stage['enemy_name']}（目前 HP: {enemy_hp}/{enemy_max_hp}，基礎攻擊：{stage['enemy_atk']}，機制：{stage['mechanic']}）\n"
                    f"玩家：{self.state.player_name}（{self.state.race_name}・{self.state.class_name}/{self.state.role}，Lv.{self.state.level}，atk={self.state.atk}，HP: {self.state.hp}/{self.state.max_hp}）\n"
                    f"AI 隊友：{party_summary}\n"
                    f"先前戰役與首領觀察摘要（請據此讓敵軍展現針對性應變）：\n{self.state.campaign_digest or '尚無先前紀錄'}\n\n"
                    f"玩家本回合指令：{player_cmd}\n"
                    f"請用 3 到 4 句繁體中文描寫本回合小隊配合與敵軍反擊，並在最後一行只輸出 JSON 戰術修正：\n"
                    f"{{\"atk_mult\": 1.1, \"def_mult\": 0.9, \"heal_boost\": 1.2, \"apply_armor_break\": false}}"
                )
                raw_combat = self.gpt.run_gpt(combat_prompt, 360)
                verdict = parse_json_obj(raw_combat)
                narrative = re.sub(r"\{.*?\}", "", raw_combat, flags=re.DOTALL).strip()
                if not narrative:
                    narrative = f"{self.state.player_name} 執行了「{player_cmd}」，小隊與 {stage['enemy_name']} 展開激烈交鋒。"

                # Dynamic damage & healing calculation (skill + party + random variance + LLM tactical modifier)
                atk_mult = float(verdict.get("atk_mult", 1.0)) if verdict else random.uniform(0.85, 1.25)
                def_mult = float(verdict.get("def_mult", 1.0)) if verdict else random.uniform(0.85, 1.20)
                heal_boost = float(verdict.get("heal_boost", 1.0)) if verdict else 1.0
                atk_mult = max(0.6, min(1.6, atk_mult))
                def_mult = max(0.5, min(1.5, def_mult))
                heal_boost = max(0.5, min(1.8, heal_boost))

                skill_bonus = 0
                for sk in self.state.skills:
                    if sk in player_cmd:
                        if "破甲" in sk:
                            armor_broken = True
                            skill_bonus += 10
                        elif "英勇" in sk or "衝鋒" in sk or "火球" in sk or "射擊" in sk:
                            skill_bonus += 12

                if "破甲" in player_cmd:
                    armor_broken = True

                # 3 DPS teammates + player attack + armor break bonus + jitter
                dps_party_dmg = sum(m.get("level", 2) * random.randint(9, 15) for m in self.state.party if m.get("role") == "dps")
                armor_bonus = int(dps_party_dmg * 0.25) if armor_broken else 0
                player_dmg = int((self.state.atk + skill_bonus) * random.uniform(0.85, 1.2))
                dmg_enemy = max(12, int((player_dmg + dps_party_dmg + armor_bonus) * atk_mult))

                # Enemy damage & healer response
                tank_mitigation = 0.72 if self.state.role == "tank" else 1.0
                enrage_mult = 1.25 if (stage_num == 3 and enemy_hp <= enemy_max_hp * 0.4) else 1.0
                raw_enemy_dmg = stage["enemy_atk"] * random.uniform(0.75, 1.25) * tank_mitigation * enrage_mult * def_mult
                dmg_player = max(4, int(raw_enemy_dmg))

                # Healer teammate heals when player asks for heal or HP is below 75%
                asked_heal = any(k in player_cmd for k in ["補血", "治療", "奶", "抬血", "救"])
                hp_ratio_after_hit = max(0, self.state.hp - dmg_player) / max(1, self.state.max_hp)
                if asked_heal or hp_ratio_after_hit < 0.75:
                    healer_lv = max([m.get("level", 2) for m in self.state.party if m.get("role") == "healer"] or [2])
                    base_heal = healer_lv * random.randint(10, 16) + (12 if asked_heal else 0)
                    heal_player = max(8, int(base_heal * heal_boost))
                else:
                    heal_player = random.randint(0, 6)

                enemy_hp -= dmg_enemy
                self.state.hp = min(self.state.max_hp, max(0, self.state.hp - dmg_player + heal_player))

                armor_tag = " [破甲增傷中]" if armor_broken else ""
                self.append_log(
                    f"[第{stage_num}階段-第{turn}回合]{armor_tag} {narrative}（對敵造成 {dmg_enemy} 傷害，玩家受到 {dmg_player} 傷害、回復 {heal_player} HP）",
                    print_it=True,
                )

                # LLM Task 4b: Digest current turn + previous digest into updated campaign_digest
                digest_prompt = (
                    f"請將「先前摘要」與「本回合戰況」整合成一份精簡的戰役與首領觀察筆記（最多 4 點，每點一句繁體中文），"
                    f"重點記錄玩家常用戰術、隊友表現與首領需注意的應變：\n"
                    f"先前摘要：{self.state.campaign_digest or '無'}\n"
                    f"本回合戰況：{narrative}（對敵 {dmg_enemy}，玩家 HP {self.state.hp}/{self.state.max_hp}）"
                )
                new_digest = self.gpt.run_gpt(digest_prompt, 240)
                if new_digest:
                    self.state.campaign_digest = new_digest

                self.state.save()
                turn += 1

                if self.state.hp <= 0:
                    self.state.victory = False
                    self.state.phase = "finished"
                    self.append_log(f"小隊在【{stage['name']}】遭遇重創，本次地下城挑戰未能通關。", print_it=True)
                    self.state.save()
                    return

            self.append_log(f"成功擊敗【{stage['enemy_name']}】，突破第 {stage_num} 階段：{stage['name']}！", print_it=True)
            self.state.hp = min(self.state.max_hp, self.state.hp + 30)
            self.state.dungeon_stage_idx += 1
            self.state.save()

        self.state.victory = True
        self.state.phase = "finished"
        self.append_log(f"恭喜！5 人小隊成功通關地下城【{dungeon_name}】！", print_it=True)
        self.state.save()



    def generate_review(self):

        outcome_str = "順利通關地下城" if self.state.victory else "地下城挑戰止步"

        party_str = ", ".join(f"{m['name']}({m['class']}/{m['role']})" for m in self.state.party)

        trimmed_log = self.state.log[-3500:]



        # LLM Task 5a: Write an enjoyable, humorous & highlight-focused post-run review

        review_prompt = (

            f"你是一位艾澤拉斯酒館的說書人兼副本覆盤主播。請根據以下冒險紀錄與戰役摘要，寫出一份有趣、有畫面感且帶點幽默的「本局冒險覆盤」。\n"

            f"包含：1) 戰局總評（{outcome_str}） 2) 隊伍亮點與最秀／最驚險時刻 3) 戰術與首領應變回顧。\n"

            f"請使用繁體中文，約 250∼400 字。\n\n"

            f"隊伍成員：{self.state.player_name}({self.state.race_name}{self.state.class_name}/{self.state.role}, Lv.{self.state.level})、{party_str}\n"

            f"戰役摘要：{self.state.campaign_digest}\n"

            f"冒險紀錄：\n{trimmed_log}"

        )

        draft_review = self.gpt.run_gpt(review_prompt, 700)



        # LLM Task 5b: Digest & fact-check review against actual log to reduce hallucinations

        fact_prompt = (

            f"請對照「原始冒險紀錄」檢查以下「覆盤草稿」，修正任何與紀錄不符的角色名稱、技能、定位或通關結果，同時保留原本幽默生動的語氣與繁體中文輸出：\n\n"

            f"原始冒險紀錄：\n{trimmed_log}\n\n"

            f"覆盤草稿：\n{draft_review}"

        )

        final_review = self.gpt.run_gpt(fact_prompt, 800) or draft_review or self.state.log



        write_txt(self.summary_file, final_review)

        self.state.ended = True

        self.state.save()



        print(f"\n================ 冒險覆盤已儲存至 {self.summary_file} ================\n")

        print(final_review)



    def main_loop(self):

        while True:

            if self.state.phase == "character_creation":

                self.create_character()

            elif self.state.phase == "starting_zone":

                self.run_starting_zone()

            elif self.state.phase == "party_forming":

                self.form_party()

            elif self.state.phase == "dungeon":

                self.run_dungeon()

            elif self.state.phase == "finished":

                if not self.state.ended:

                    self.generate_review()

                break

            else:

                break





def main():

    parser = argparse.ArgumentParser()

    parser.add_argument("--config_file", type=str, default="wow_config.json")

    args = parser.parse_args()



    openai.api_key = input("OpenAI API Key: ").strip()

    config = Config(args.config_file)

    game = WowGame(config)

    game.start_menu()





if __name__ == "__main__":

    main()

    sys.exit()