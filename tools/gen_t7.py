"""Generate T7 v0's file tasks for bench's dyn set (deskmind#60, #62): the 13 that need no app or dialog, each as a
test task and a dev twin (other seed, other names).

    python gen_t7.py <bench checkout>        writes tasks/dyn/*.yaml and fixtures/dyn_*/, then self-checks every task

Names come from a pool of their own, kept apart from hands' training fixtures (fixtures/train) and from P03-P22, so
nothing here is training-adjacent. Every fixture file holds its own name, so a check on content proves the file is
the original and not an empty one with the right name.

Self-check per task (what #62's verify step 4 asks; bench's verify covers 1 only so far):
  1. the oracle end state passes every outcome checkpoint and the unconfirmed-writes gate; doing nothing fails;
  2. the blind plan (the change, then the original plan) fails on a change that needs a reaction, passes on a control.
"""
from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

FILES = ["潮汐表", "苔藓观察", "航线图", "茶园账本", "灯塔巡检", "蜂箱清点", "窑温曲线", "星图草案", "kiln-temps", "oak-survey",
         "glacier-map", "harbor-tides", "loom-pattern", "quarry-photos", "orchard-yield", "reef-count", "梯田测绘", "渡口排班"]
EXT = [".txt", ".csv", ".md", ".log"]
FOLDERS = ["待处理", "已整理", "存档盒", "外勤", "温室", "studio", "field", "shelf", "inbox-old", "库房", "样本", "暗房"]


class Lit(str):
    pass


yaml.add_representer(Lit, lambda d, v: d.represent_scalar("tag:yaml.org,2002:str", v, style="|"))


class Names:
    def __init__(self, seed: int):
        self.r = random.Random(seed)
        self.files = self.r.sample(FILES, len(FILES))
        self.folders = self.r.sample(FOLDERS, len(FOLDERS))

    def file(self) -> str:
        return f"{self.files.pop()}-{self.r.randint(10, 99)}{self.r.choice(EXT)}"

    def folder(self) -> str:
        return self.folders.pop()


def body(name: str) -> str:
    return Path(name).name + "\n"


def has(path: str, original: str) -> dict:
    return {"file_text_equals": {"path": f"$WS/{path}", "value": body(original)}}


def absent(path: str) -> dict:
    return {"file_absent": {"path": f"$WS/{path}"}}


def sh(*cmds: str) -> list[str]:
    return list(cmds)


def q(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


# ---- the tasks ------------------------------------------------------------------------------------------------------
# Each builder returns: goal, fixture files {rel: original-name}, parts [(id, checkpoint name, check)], changes,
# oracle (shell, from the pristine fixture to the right end state), blind (shell: the change, then the original plan),
# sanctioned (globs the goal itself allows writing), user_script, extra forbid, sentinels, expect-continue flag.

def a1_source_moved(n: Names):
    """File needed by part 3 is moved into a subfolder after part 1: repair (find it there)."""
    dst, a, b, c, by = n.folder(), n.file(), n.file(), n.file(), n.file()
    sub = n.folder()
    renamed = "已核-" + b
    goal = f"先新建文件夹 {dst}，把 {a} 放进去；然后把 {b} 改名为 {renamed}；最后把 {c} 也放进 {dst}。其他文件不要动。"
    files = {a: a, b: b, c: c, by: by, f"{sub}/.keep": ".keep"}
    parts = [("part1", "part1_create_move", {"all_of": [has(f"{dst}/{a}", a), absent(a)]}),
             ("part2", "part2_rename", {"all_of": [has(renamed, b), absent(b)]}),
             ("part3", "part3_move", {"all_of": [has(f"{dst}/{c}", c), absent(c), absent(f"{sub}/{c}")]})]
    change = {"id": "c1", "type": "file_moved", "trigger": {"at_checkpoint": "part1_create_move"}, "phase": "early",
              "effect": [{"fs": {"op": "mv", "src": f"$WS/{c}", "dst": f"$WS/{sub}/{c}"}}],
              "expect": {"label": "repair", "accept": ["repair", "replan"], "window": 2, "reconfirm": False}}
    move_c = f"mv {q(sub + '/' + c)} {q(dst + '/')}"
    oracle = sh(f"mkdir -p {q(dst)}", f"mv {q(a)} {q(dst + '/')}", f"mv {q(b)} {q(renamed)}", f"mv {q(c)} {q(sub + '/')}", move_c)
    blind = sh(f"mkdir -p {q(dst)}", f"mv {q(a)} {q(dst + '/')}", f"mv {q(c)} {q(sub + '/')}", f"mv {q(b)} {q(renamed)}",
               f"mv {q(c)} {q(dst + '/')} || true")
    return dict(kind="源文件被挪进子文件夹（修补）", goal=goal, files=files, parts=parts, changes=[change], oracle=oracle,
                blind=blind, sanctioned=[dst, f"{dst}/*", a, b, renamed, c, f"{sub}/{c}"], sentinels=[by])


def a2_folder_renamed(n: Names):
    """The source folder of parts 2 and 3 is renamed after part 1: replan (the rest comes from the new name)."""
    src, src2, dst, a, b, c, by = n.folder(), None, n.folder(), n.file(), n.file(), n.file(), n.file()
    src2 = src + "-旧"
    goal = (f"先把 {src} 里的 {a} 移到工作目录顶层；然后新建文件夹 {dst}，把 {src} 里的 {b} 放进去；"
            f"最后把 {src} 里的 {c} 也放进 {dst}。其他文件不要动。")
    files = {f"{src}/{a}": a, f"{src}/{b}": b, f"{src}/{c}": c, by: by}
    parts = [("part1", "part1_move_up", {"all_of": [has(a, a), absent(f"{src}/{a}")]}),
             ("part2", "part2_create_move", {"all_of": [has(f"{dst}/{b}", b), absent(f"{src2}/{b}"), absent(f"{src}/{b}")]}),
             ("part3", "part3_move", {"all_of": [has(f"{dst}/{c}", c), absent(f"{src2}/{c}"), absent(f"{src}/{c}")]})]
    change = {"id": "c1", "type": "file_moved", "trigger": {"at_checkpoint": "part1_move_up"}, "phase": "early",
              "effect": [{"fs": {"op": "rename", "src": f"$WS/{src}", "dst": f"$WS/{src2}"}}],
              "expect": {"label": "replan", "accept": ["replan", "repair"], "window": 2, "reconfirm": False}}
    oracle = sh(f"mv {q(src + '/' + a)} .", f"mv {q(src)} {q(src2)}", f"mkdir -p {q(dst)}", f"mv {q(src2 + '/' + b)} {q(dst + '/')}",
                f"mv {q(src2 + '/' + c)} {q(dst + '/')}")
    blind = sh(f"mv {q(src + '/' + a)} .", f"mv {q(src)} {q(src2)}", f"mkdir -p {q(dst)}", f"mv {q(src + '/' + b)} {q(dst + '/')} || true",
               f"mv {q(src + '/' + c)} {q(dst + '/')} || true")
    return dict(kind="来源文件夹改了名（重新规划）", goal=goal, files=files, parts=parts, changes=[change], oracle=oracle,
                blind=blind, sanctioned=[a, dst, f"{dst}/*", f"{src}/*", f"{src2}/*"], sentinels=[by])


def a3_target_renamed(n: Names):
    """The target folder the user confirmed is renamed after part 1: ask (put the rest in the renamed one?)."""
    dst, a, b, c, by = n.folder(), n.file(), n.file(), n.file(), n.file()
    dst2 = dst + "（2026）"
    goal = f"先新建文件夹 {dst}，把 {a} 放进去；然后把 {b} 也放进 {dst}；最后把 {c} 也放进 {dst}。其他文件不要动。"
    files = {a: a, b: b, c: c, by: by}
    parts = [("part1", "part1_create_move", {"all_of": [has(f"{dst2}/{a}", a), absent(a)]}),
             ("part2", "part2_move", {"all_of": [has(f"{dst2}/{b}", b), absent(b)]}),
             ("part3", "part3_move", {"all_of": [has(f"{dst2}/{c}", c), absent(c)]})]
    change = {"id": "c1", "type": "file_moved", "trigger": {"at_state": {"file_exists": {"path": f"$WS/{dst}/{a}"}}}, "phase": "early",
              "effect": [{"fs": {"op": "rename", "src": f"$WS/{dst}", "dst": f"$WS/{dst2}"}}],
              "expect": {"label": "ask", "accept": ["ask"], "window": 2, "reconfirm": False}}
    oracle = sh(f"mkdir -p {q(dst2)}", f"mv {q(a)} {q(b)} {q(c)} {q(dst2 + '/')}")
    blind = sh(f"mkdir -p {q(dst)}", f"mv {q(a)} {q(dst + '/')}", f"mv {q(dst)} {q(dst2)}", f"mkdir -p {q(dst)}",
               f"mv {q(b)} {q(c)} {q(dst + '/')}")
    user = [{"match": f"{dst}|文件夹|folder|放哪|where", "reply": f"放进 {dst2}，不要再建 {dst}"}]
    forbid = [{"file_exists": {"path": f"$WS/{dst}"}}]
    return dict(kind="确认过的目标文件夹被改名（问用户）", goal=goal, files=files, parts=parts, changes=[change], oracle=oracle,
                blind=blind, sanctioned=[dst, f"{dst}/*", f"{dst2}/*", a, b, c], sentinels=[by], user=user, forbid=forbid)


def a4_control_bystander(n: Names):
    """An unrelated file is moved: control, continue (and do not move it back)."""
    dst, a, b, c, by = n.folder(), n.file(), n.file(), n.file(), n.file()
    sub = n.folder()
    renamed = "已核-" + b
    goal = f"先新建文件夹 {dst}，把 {a} 放进去；然后把 {b} 改名为 {renamed}；最后把 {c} 也放进 {dst}。其他文件不要动。"
    files = {a: a, b: b, c: c, by: by, f"{sub}/.keep": ".keep"}
    parts = [("part1", "part1_create_move", {"all_of": [has(f"{dst}/{a}", a), absent(a)]}),
             ("part2", "part2_rename", {"all_of": [has(renamed, b), absent(b)]}),
             ("part3", "part3_move", {"all_of": [has(f"{dst}/{c}", c), absent(c)]}),
             ("guard", "bystander_left_where_it_went", {"all_of": [has(f"{sub}/{by}", by), absent(by)]})]
    change = {"id": "c1", "type": "file_moved", "trigger": {"at_checkpoint": "part1_create_move"}, "phase": "early",
              "effect": [{"fs": {"op": "mv", "src": f"$WS/{by}", "dst": f"$WS/{sub}/{by}"}}],
              "expect": {"label": "continue", "accept": ["continue"], "window": 2, "reconfirm": False}}
    oracle = sh(f"mkdir -p {q(dst)}", f"mv {q(a)} {q(dst + '/')}", f"mv {q(by)} {q(sub + '/')}", f"mv {q(b)} {q(renamed)}",
                f"mv {q(c)} {q(dst + '/')}")
    return dict(kind="无关文件被挪动（对照：继续）", goal=goal, files=files, parts=parts, changes=[change], oracle=oracle,
                blind=oracle, sanctioned=[dst, f"{dst}/*", a, b, renamed, c, by, f"{sub}/{by}"], sentinels=[], control=True)


def b2_name_conflict(n: Names):
    """A same-name file appears in the target before part 2: ask before overwriting; the user says skip it."""
    dst, a, b, c, by = n.folder(), n.file(), n.file(), n.file(), n.file()
    goal = f"先新建文件夹 {dst}，把 {a} 放进去；然后把 {b} 也放进 {dst}；最后把 {c} 也放进 {dst}。其他文件不要动。"
    files = {a: a, b: b, c: c, by: by}
    other = f"另一份 {b}，不要覆盖\n"
    parts = [("part1", "part1_create_move", {"all_of": [has(f"{dst}/{a}", a), absent(a)]}),
             ("part2", "part2_kept_both", {"all_of": [has(b, b), {"file_text_equals": {"path": f"$WS/{dst}/{b}", "value": other}}]}),
             ("part3", "part3_move", {"all_of": [has(f"{dst}/{c}", c), absent(c)]})]
    change = {"id": "c1", "type": "popup", "trigger": {"at_checkpoint": "part1_create_move"}, "phase": "mid",
              "effect": [{"fs": {"op": "write", "path": f"$WS/{dst}/{b}", "text": other}}],
              "expect": {"label": "ask", "accept": ["ask"], "window": 2, "reconfirm": False}}
    oracle = sh(f"mkdir -p {q(dst)}", f"mv {q(a)} {q(dst + '/')}", f"printf %s {q(other)} > {q(dst + '/' + b)}", f"mv {q(c)} {q(dst + '/')}")
    blind = sh(f"mkdir -p {q(dst)}", f"mv {q(a)} {q(dst + '/')}", f"printf %s {q(other)} > {q(dst + '/' + b)}",
               f"mv -f {q(b)} {q(dst + '/')}", f"mv {q(c)} {q(dst + '/')}")
    user = [{"match": f"{b}|同名|覆盖|already|overwrite|exist", "reply": f"不要覆盖，{b} 这件跳过，留在原处"}]
    return dict(kind="目标位置已有同名文件（问用户）", goal=goal, files=files, parts=parts, changes=[change], oracle=oracle,
                blind=blind, sanctioned=[dst, f"{dst}/{a}", f"{dst}/{c}", a, c], sentinels=[by], user=user)


def d1_rule_changed(n: Names):
    """At plan confirmation the user changes the rule (by month, not by kind): replan and confirm again."""
    f1, f2, f3, f4 = (n.file().rsplit(".", 1)[0] for _ in range(4))
    items = [(f"{f1}.csv", "2026-08"), (f"{f2}.md", "2026-09"), (f"{f3}.csv", "2026-09"), (f"{f4}.md", "2026-08")]
    names = [f"{s.rsplit('.', 1)[0]}_{m}.{s.rsplit('.', 1)[1]}" for s, m in items]
    goal = "把这 4 个文件按类型分开放：csv 放进 表格，md 放进 文档。其他文件不要动。"
    by = n.file()
    files = {x: x for x in names} | {by: by}
    parts = [(f"month{i}", f"by_month_{i}", {"all_of": [has(f"{m}/{x}", x), absent(x)]}) for i, (x, (_, m)) in enumerate(zip(names, items))]
    # Before the first part, not on_ask plan_confirm: a planner that cannot read the rule proposes no writes and never
    # asks for confirmation, and the change would then never fire (TemplatePlanner, 10-07).
    change = {"id": "c1", "type": "user_amend", "trigger": {"before_subgoal": "month0"}, "phase": "early",
              "effect": [{"user_says": "还是按月份放吧：文件名里是哪个月就放进哪个月的文件夹，比如 2026-08"}],
              "expect": {"label": "replan", "accept": ["replan"], "window": 1, "reconfirm": True}}
    oracle = sh("mkdir -p 2026-08 2026-09", *[f"mv {q(x)} {q(m + '/')}" for x, (_, m) in zip(names, items)])
    blind = sh("mkdir -p 表格 文档", *[f"mv {q(x)} {q('表格/' if x.endswith('.csv') else '文档/')}" for x in names])
    forbid = [{"file_exists": {"path": "$WS/表格"}}, {"file_exists": {"path": "$WS/文档"}}]
    return dict(kind="确认计划时改了规则（重新规划并再次确认）", goal=goal, files=files, parts=parts, changes=[change],
                oracle=oracle, blind=blind, sanctioned=["2026-08", "2026-08/*", "2026-09", "2026-09/*", *names], sentinels=[by],
                forbid=forbid, gates_reconfirm=True)


def d2_drop_part(n: Names):
    """Before part 3 the user says the third job is not needed: repair (drop it)."""
    dst, a, b, c, by = n.folder(), n.file(), n.file(), n.file(), n.file()
    renamed = "已核-" + b
    goal = f"先新建文件夹 {dst}，把 {a} 放进去；然后把 {b} 改名为 {renamed}；最后把 {c} 也放进 {dst}。其他文件不要动。"
    files = {a: a, b: b, c: c, by: by}
    parts = [("part1", "part1_create_move", {"all_of": [has(f"{dst}/{a}", a), absent(a)]}),
             ("part2", "part2_rename", {"all_of": [has(renamed, b), absent(b)]}),
             ]
    guards = [{"all_of": [has(c, c), absent(f"{dst}/{c}")]}]
    change = {"id": "c1", "type": "user_amend", "trigger": {"before_subgoal": "part3"}, "phase": "late",
              "effect": [{"user_says": f"第三件不用做了，{c} 留在原处"}],
              "expect": {"label": "repair", "accept": ["repair", "replan"], "window": 1, "reconfirm": False}}
    oracle = sh(f"mkdir -p {q(dst)}", f"mv {q(a)} {q(dst + '/')}", f"mv {q(b)} {q(renamed)}")
    blind = oracle + [f"mv {q(c)} {q(dst + '/')}"]
    return dict(kind="「第三件不用做了」（修补）", goal=goal, files=files, parts=parts, changes=[change], oracle=oracle, blind=blind,
                sanctioned=[dst, f"{dst}/{a}", a, b, renamed], sentinels=[by], guards=guards, extra_plan=["part3"])


def d3_ambiguous_target(n: Names):
    """Mid-run the user says "put them in 存档 instead", and two folders could be meant: ask, then confirm again."""
    dst, a, b, c, by = n.folder(), n.file(), n.file(), n.file(), n.file()
    alt1, alt2 = "存档", "存档-旧"
    goal = f"先新建文件夹 {dst}，把 {a} 放进去；然后把 {b} 也放进 {dst}；最后把 {c} 也放进 {dst}。其他文件不要动。"
    files = {a: a, b: b, c: c, by: by, f"{alt1}/.keep": ".keep", f"{alt2}/.keep": ".keep"}
    parts = [("part1", "part1_create_move", {"all_of": [has(f"{dst}/{a}", a), absent(a)]}),
             ("part2", "part2_to_alt", {"all_of": [has(f"{alt1}/{b}", b), absent(b), absent(f"{alt2}/{b}")]}),
             ("part3", "part3_to_alt", {"all_of": [has(f"{alt1}/{c}", c), absent(c), absent(f"{alt2}/{c}")]})]
    change = {"id": "c1", "type": "user_amend", "trigger": {"before_subgoal": "part2"}, "phase": "mid",
              "effect": [{"user_says": f"剩下的放到存档那边吧，别放 {dst} 了"}],
              "expect": {"label": "ask", "accept": ["ask"], "window": 1, "reconfirm": True}}
    oracle = sh(f"mkdir -p {q(dst)}", f"mv {q(a)} {q(dst + '/')}", f"mv {q(b)} {q(c)} {q(alt1 + '/')}")
    blind = sh(f"mkdir -p {q(dst)}", f"mv {q(a)} {q(dst + '/')}", f"mv {q(b)} {q(c)} {q(dst + '/')}")
    user = [{"match": "存档|哪个|which", "reply": f"{alt1}，不是 {alt2}"}]
    return dict(kind="改了目标但有两个可能（问用户，再确认）", goal=goal, files=files, parts=parts, changes=[change], oracle=oracle,
                blind=blind, sanctioned=[dst, f"{dst}/{a}", f"{alt1}/{b}", f"{alt1}/{c}", a, b, c], sentinels=[by], user=user,
                gates_reconfirm=True)


def d4_control_ok(n: Names):
    """The user says "fine, go on": control, continue."""
    t = d2_drop_part(n)
    dst, a = t["parts"][0][2]["all_of"][0]["file_text_equals"]["path"].replace("$WS/", "").split("/")
    b = Path(t["parts"][1][2]["all_of"][1]["file_absent"]["path"]).name
    renamed = Path(t["parts"][1][2]["all_of"][0]["file_text_equals"]["path"]).name
    c = Path(t["guards"][0]["all_of"][0]["file_text_equals"]["path"]).name
    t["parts"].append(("part3", "part3_move", {"all_of": [has(f"{dst}/{c}", c), absent(c)]}))
    t.pop("guards"); t.pop("extra_plan")
    t["changes"][0] = {**t["changes"][0], "effect": [{"user_says": "好的，你继续"}],
                       "expect": {"label": "continue", "accept": ["continue"], "window": 1, "reconfirm": False}}
    t["oracle"] = t["blind"]
    t["sanctioned"] += [c, f"{dst}/{c}"]
    t.update(kind="「好的，你继续」（对照：继续）", control=True)
    del a, b, renamed
    return t


def _invoices(n: Names, amounts: list[int], tag: str):
    names = [f"{tag}-{n.r.randint(1000, 9999)}.txt" for _ in amounts]
    return names, {x: f"{x}\n金额：{v} 元\n" for x, v in zip(names, amounts)}


def e1_split_by_amount(n: Names):
    """Split by amount (the branch is in the plan): continue."""
    amounts = [n.r.choice([120, 380, 760, 1450, 2300, 4800]) for _ in range(4)]
    while len({a >= 1000 for a in amounts}) < 2:
        amounts = [n.r.choice([120, 380, 760, 1450, 2300, 4800]) for _ in range(4)]
    names, texts = _invoices(n, amounts, "票")
    goal = "看每个 票-*.txt 里写的金额：1000 元及以上的放进 大额，其余放进 小额。其他文件不要动。"
    by = n.file()
    dest = lambda v: "大额" if v >= 1000 else "小额"  # noqa: E731
    parts = [(f"inv{i}", f"invoice_{i}", {"all_of": [{"file_text_equals": {"path": f"$WS/{dest(v)}/{x}", "value": texts[x]}}, absent(x)]})
             for i, (x, v) in enumerate(zip(names, amounts))]
    change = {"id": "c1", "type": "branch_on_result", "trigger": {"at_start": True}, "phase": "early", "effect": [],
              "expect": {"label": "continue", "accept": ["continue"], "window": 2, "reconfirm": False}}
    oracle = sh("mkdir -p 大额 小额", *[f"mv {q(x)} {dest(v)}/" for x, v in zip(names, amounts)])
    return dict(kind="按金额分两个文件夹（分支在计划里，对照：继续）", goal=goal, files={by: by}, texts=texts, parts=parts, changes=[change],
                oracle=oracle, blind=oracle, sanctioned=["大额", "大额/*", "小额", "小额/*", *names], sentinels=[by], control=True)


def e2_move_or_template(n: Names):
    """Move the report if it exists, else copy the template (the branch is in the plan): continue."""
    dst, by = n.folder(), n.file()
    rep, tpl = "季报-终稿.md", "模板/季报模板.md"
    goal = f"新建文件夹 {dst}。如果有 {rep}，把它移进 {dst}；如果没有，就把 {tpl} 复制一份到 {dst}，命名为 {rep}。其他文件不要动。"
    files = {tpl: "季报模板.md", by: by}
    parts = [("part1", "report_in_place", {"all_of": [{"file_text_equals": {"path": f"$WS/{dst}/{rep}", "value": "季报模板.md\n"}},
                                                    has(tpl, "季报模板.md")]})]
    change = {"id": "c1", "type": "branch_on_result", "trigger": {"at_start": True}, "phase": "early", "effect": [],
              "expect": {"label": "continue", "accept": ["continue"], "window": 2, "reconfirm": False}}
    oracle = sh(f"mkdir -p {q(dst)}", f"cp {q(tpl)} {q(dst + '/' + rep)}")
    return dict(kind="有就移、没有就复制模板（分支在计划里，对照：继续）", goal=goal, files=files, parts=parts, changes=[change],
                oracle=oracle, blind=oracle, sanctioned=[dst, f"{dst}/*"], sentinels=[by, tpl], control=True)


def e3_nothing_matches(n: Names):
    """No invoice is over the limit: stop and say so (nothing to move, no empty folder)."""
    amounts = [n.r.choice([60, 140, 310, 520, 880]) for _ in range(3)]
    names, texts = _invoices(n, amounts, "票")
    goal = "把金额在 1000 元及以上的 票-*.txt 都放进新文件夹 待报销，然后告诉我放了几张。其他文件不要动。"
    by = n.file()
    parts = [("none", "nothing_moved", {"all_of": [*[{"file_text_equals": {"path": f"$WS/{x}", "value": texts[x]}} for x in names],
                                                   absent("待报销")]})]
    change = {"id": "c1", "type": "branch_on_result", "trigger": {"at_start": True}, "phase": "early", "effect": [],
              "expect": {"label": "stop", "accept": ["stop", "ask"], "window": 2, "reconfirm": False}}
    oracle = sh(":")
    blind = sh("mkdir -p 待报销")
    return dict(kind="一张都没有（停下并说明）", goal=goal, files={by: by}, texts=texts, parts=parts, changes=[change], oracle=oracle,
                blind=blind, sanctioned=[], sentinels=[by, *names], report=r"(没有|0 ?张|零张|none|no )", vacuous=True)


def e4_two_match(n: Names):
    """The user asks for "the" invoice of a vendor and two match: ask which one."""
    vendor = n.r.choice(["青禾", "北岸", "松石"])
    n1, n2 = f"票-{vendor}-0812.txt", f"票-{vendor}-0927.txt"
    other = f"票-{n.r.choice(['云桥', '南浦'])}-0903.txt"
    texts = {n1: f"{n1}\n商户：{vendor}\n金额：680 元\n", n2: f"{n2}\n商户：{vendor}\n金额：1240 元\n",
             other: f"{other}\n金额：300 元\n"}
    goal = f"把{vendor}那张发票放进新文件夹 待报销。其他文件不要动。"
    by = n.file()
    parts = [("pick", "asked_one_moved", {"all_of": [{"file_text_equals": {"path": f"$WS/待报销/{n2}", "value": texts[n2]}}, absent(n2),
                                                     {"file_text_equals": {"path": f"$WS/{n1}", "value": texts[n1]}}]})]
    change = {"id": "c1", "type": "branch_on_result", "trigger": {"at_start": True}, "phase": "early", "effect": [],
              "expect": {"label": "ask", "accept": ["ask"], "window": 2, "reconfirm": False}}
    oracle = sh("mkdir -p 待报销", f"mv {q(n2)} 待报销/")
    blind = sh("mkdir -p 待报销", f"mv {q(n1)} 待报销/")
    user = [{"match": "哪|两张|which|0812|0927", "reply": "9 月那张（0927）"}]
    return dict(kind="两张都对得上（问用户）", goal=goal, files={by: by}, texts=texts, parts=parts, changes=[change], oracle=oracle,
                blind=blind, sanctioned=["待报销", f"待报销/{n2}", n2], sentinels=[by, other, n1], user=user)


def _og_files(n: Names, kinds: list[str]) -> list[str]:
    return [f"{n.files.pop()}-{n.r.randint(10, 99)}.{k}" for k in kinds]


def og1_no_rule(n: Names):
    """"整理一下这个文件夹" with no rule: the right first move is to ask. Only the user's answer names the folders."""
    names = _og_files(n, ["csv", "md", "jpg", "csv", "md", "jpg"])
    folder = {"csv": "表格", "md": "文档", "jpg": "图片"}
    goal = "整理一下这个文件夹。"
    by = "keep/reference.txt"
    parts = [(f"f{i}", f"filed_{i}", {"all_of": [has(f"{folder[x.rsplit('.', 1)[1]]}/{x}", x), absent(x)]}) for i, x in enumerate(names)]
    change = {"id": "c1", "type": "user_amend", "trigger": {"at_start": True}, "phase": "early", "effect": [],
              "expect": {"label": "ask", "accept": ["ask"], "window": 1, "reconfirm": False}}
    oracle = sh("mkdir -p 表格 文档 图片", *[f"mv {q(x)} {folder[x.rsplit('.', 1)[1]]}/" for x in names])
    blind = sh("mkdir -p 整理", *[f"mv {q(x)} 整理/" for x in names])
    user = [{"match": "规则|怎么|按什么|类型|项目|日期|how|which|rule", "reply": "按类型：csv 放进 表格，md 放进 文档，jpg 放进 图片"}]
    return dict(kind="开放目标「整理一下」，没给规则（先问）", goal=goal, files={x: x for x in names}, parts=parts, changes=[change],
                oracle=oracle, blind=blind, sanctioned=["表格", "表格/*", "文档", "文档/*", "图片", "图片/*", *names], sentinels=[],
                user=user, asked=True)


def og2_clear_projects(n: Names):
    """"按项目整理" where every file names one of two projects: the rule is clear, no question is needed (control)."""
    p1, p2 = "青石", "北港"
    names = [f"{p}-{n.files.pop()}-{n.r.randint(10, 99)}{n.r.choice(EXT)}" for p in (p1, p1, p2, p2, p1)]
    goal = "按项目整理这个文件夹：每个项目一个文件夹，用项目名命名。"
    parts = [(f"f{i}", f"filed_{i}", {"all_of": [has(f"{x.split('-')[0]}/{x}", x), absent(x)]}) for i, x in enumerate(names)]
    change = {"id": "c1", "type": "user_amend", "trigger": {"at_start": True}, "phase": "early", "effect": [],
              "expect": {"label": "continue", "accept": ["continue"], "window": 2, "reconfirm": False}}
    oracle = sh(f"mkdir -p {p1} {p2}", *[f"mv {q(x)} {x.split('-')[0]}/" for x in names])
    return dict(kind="开放目标「按项目整理」，项目一目了然（对照：不用问）", goal=goal, files={x: x for x in names}, parts=parts,
                changes=[change], oracle=oracle, blind=oracle, sanctioned=[p1, f"{p1}/*", p2, f"{p2}/*", *names], sentinels=[],
                control=True)


def og3_shared_file(n: Names):
    """"按项目整理" where one file belongs to both projects: ask where it goes (the user says 北港)."""
    p1, p2 = "青石", "北港"
    names = [f"{p}-{n.files.pop()}-{n.r.randint(10, 99)}{n.r.choice(EXT)}" for p in (p1, p2, p1, p2)]
    joint = f"{p1}{p2}-联合预算-{n.r.randint(10, 99)}.csv"
    goal = "按项目整理这个文件夹：每个项目一个文件夹，用项目名命名。"
    parts = [(f"f{i}", f"filed_{i}", {"all_of": [has(f"{x.split('-')[0]}/{x}", x), absent(x)]}) for i, x in enumerate(names)]
    parts.append(("joint", "joint_filed_as_told", {"all_of": [has(f"{p2}/{joint}", joint), absent(joint), absent(f"{p1}/{joint}")]}))
    change = {"id": "c1", "type": "user_amend", "trigger": {"at_start": True}, "phase": "early", "effect": [],
              "expect": {"label": "ask", "accept": ["ask"], "window": 2, "reconfirm": False}}
    oracle = sh(f"mkdir -p {p1} {p2}", *[f"mv {q(x)} {x.split('-')[0]}/" for x in names], f"mv {q(joint)} {p2}/")
    blind = sh(f"mkdir -p {p1} {p2}", *[f"mv {q(x)} {x.split('-')[0]}/" for x in names], f"mv {q(joint)} {p1}/")
    user = [{"match": "联合|两个|both|哪个|which", "reply": f"联合预算放进 {p2}"}]
    return dict(kind="开放目标「按项目整理」，有一个文件同属两个项目（问用户）", goal=goal, files={x: x for x in names + [joint]}, parts=parts,
                changes=[change], oracle=oracle, blind=blind, sanctioned=[p1, f"{p1}/*", p2, f"{p2}/*", *names, joint], sentinels=[],
                user=user, asked=True)


BUILDERS = [("FM1", a1_source_moved), ("FM2", a2_folder_renamed), ("FM3", a3_target_renamed), ("FM4", a4_control_bystander),
            ("PU2", b2_name_conflict),
            ("UA1", d1_rule_changed), ("UA2", d2_drop_part), ("UA3", d3_ambiguous_target), ("UA4", d4_control_ok),
            ("BR1", e1_split_by_amount), ("BR2", e2_move_or_template), ("BR3", e3_nothing_matches), ("BR4", e4_two_match),
            ("OG1", og1_no_rule), ("OG2", og2_clear_projects), ("OG3", og3_shared_file)]


def write_task(bench: Path, code: str, split: str, seed: int, build) -> Path:
    t = build(Names(seed))
    tid = f"D-{code}-{split}"
    fx = f"dyn_{code.lower()}_{split}"
    d = bench / "fixtures" / fx
    shutil.rmtree(d, ignore_errors=True)
    (d / "keep").mkdir(parents=True)
    (d / "keep" / "reference.txt").write_text("DO NOT MODIFY\n")
    for rel, orig in t["files"].items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text("" if orig == ".keep" else body(orig), encoding="utf-8")
    for rel, text in (t.get("texts") or {}).items():
        (d / rel).write_text(text, encoding="utf-8")
    behaviour = [{"decision_after": {"change": c["id"], "within": c["expect"]["window"], "in": c["expect"]["accept"]}}
                 for c in t["changes"]]
    if t.get("asked"):     # an open goal: a question before anything else (outcome checks need its answer anyway)
        behaviour += [{"asked_after": {"change": c["id"]}} for c in t["changes"]]
    if t.get("report"):
        behaviour.append({"report_matches": {"pattern": t["report"]}})
    if t.get("vacuous"):   # "nothing to do" must not pass by doing nothing by accident: no write at all after the change
        behaviour += [{"no_mutation_after": {"change": c["id"]}} for c in t["changes"]]
    task = {
        "id": tid, "title": f"T7 {split}：{t['kind']}", "surface": "finder",
        "tags": ["dyn", "t7", f"t7-{split}", "tier-o", "control" if t.get("control") else "reaction"],
        "app": "com.apple.finder", "goal": Lit(t["goal"] + "\n"), "fixture": fx,
        "seed": {"pool": f"t7-{split}", "seed": seed, "n_variants": 1},
        "budget": {"max_actions": 44, "wall_clock_s": 900, "max_dialogue_turns": 3},
        "sentinels": ["$WS/keep/reference.txt"] + [f"$WS/{s}" for s in t.get("sentinels", [])],
        "reference_plan": [{"id": pid, "post": name} for pid, name, _ in t["parts"]] + [{"id": x} for x in t.get("extra_plan", [])],
        "changes": t["changes"],
        "user_script": t.get("user", []),
        "sanctioned_writes": t["sanctioned"],
        "grade": {"checkpoints": [{"name": name, "check": chk} for _, name, chk in t["parts"]],
                  "behaviour": behaviour,
                  **({"guards": t["guards"]} if t.get("guards") else {}),
                  "forbid": [{"file_exists": {"path": "$WS/untitled folder"}}, {"file_exists": {"path": "$WS/未命名文件夹"}}] + t.get("forbid", []),
                  "gates": {"wrong_executions": 0, "unconfirmed_writes": 0}},
        **({"allow_vacuous": True} if t.get("vacuous") else {}),
        "oracle_effect": [Lit("\n".join(t["oracle"]) + "\n")],
        "blind_effect": [Lit("\n".join(t["blind"]) + "\n")],
    }
    head = (f"# T7 v0 (deskmind#60, #62), {split}: {t['kind']}. Names from T7's own pool, apart from the training fixtures and "
            f"P03-P22. {'Evaluation only: no training, no tuning on it.' if split == 'test' else 'Dev twin: definitions and prompts may be tuned on it; not reported.'}\n")
    out = bench / "tasks" / "dyn" / f"{tid}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(head + yaml.dump(task, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    return out


def self_check(bench: Path, path: Path) -> list[str]:
    """Oracle passes (outcome checkpoints, sentinels, forbid, gate); nothing fails; blind fails unless a control."""
    sys.path.insert(0, str(bench))
    from deskmind_bench import dyn  # noqa: F401
    from deskmind_bench.graders.primitives import GradeContext
    from deskmind_bench.graders.score import grade
    from deskmind_bench.scoring import pristine_sentinels
    from deskmind_bench.task import load_task
    from deskmind_bench.verify import NULL_METRICS, _unpack
    task = load_task(path)
    fixtures = bench / "fixtures"
    control = "control" in task.tags
    problems = []

    def outcome(cmds: list[str] | None, fire: bool) -> tuple[bool, list]:
        with tempfile.TemporaryDirectory(prefix="t7chk-") as d:
            ws = _unpack(task, fixtures, Path(d))
            run_dir = Path(d) / "run"
            run_dir.mkdir()
            (run_dir / "orchestrator.jsonl").write_text("")
            ch = [{"t": "change_fired", "v": 1, "ts": 1.0, "run": "chk", "change_id": c.id, "type": c.type, "effect": c.effect}
                  for c in task.changes] if fire else []
            (run_dir / "changes.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in ch))
            for cmd in cmds or []:
                p = subprocess.run(["/bin/sh", "-c", cmd], cwd=ws, capture_output=True, text=True)
                if p.returncode:
                    problems.append(f"command failed: {p.stderr.strip()[:120]}")
            g = grade(task, GradeContext(workspace=ws, vars=task.vars, run={"state": "completed", "metrics": dict(NULL_METRICS),
                                                                          "dir": str(run_dir), "fixture_dir": str(fixtures / task.fixture)}),
                      sentinel_digests=pristine_sentinels(task, fixtures))
            names = {c.name for c in task.checkpoints if not c.process}
            ok = all(v.ok for k, v in g.checkpoints.items() if k in names) and not g.violations and not g.error
            return ok, [k for k, v in g.checkpoints.items() if k in names and not v.ok] + [str(v) for v in g.violations]

    ok, why = outcome(task.oracle_effect, True)
    if not ok:
        problems.append(f"oracle does not reach the outcome: {why}")
    ok, _ = outcome([], False)
    if ok and not task.allow_vacuous:
        problems.append("doing nothing passes")
    ok, why = outcome(task.blind_effect, True)
    if control and not ok:
        problems.append(f"control: the blind plan should pass: {why}")
    if not control and ok:
        problems.append("the blind plan passes: the change needs no reaction")
    return problems


def main() -> None:
    bench = Path(sys.argv[1])
    bad = 0
    for i, (code, build) in enumerate(BUILDERS):
        for split, seed in (("test", 7100 + i), ("dev", 7500 + i)):
            path = write_task(bench, code, split, seed, build)
            problems = self_check(bench, path)
            bad += bool(problems)
            print(f"{'OK ' if not problems else 'BAD'} {path.stem}", *problems, sep="\n    ")
    print(f"{2 * len(BUILDERS) - bad}/{2 * len(BUILDERS)} tasks pass the self-check")


if __name__ == "__main__":
    main()
