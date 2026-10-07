"""T7 arm (e): every model decision is one explicit lettered choice, answered by the untrained base 4B (deskmind#59
point 3; T7 amendment 4).

Why a separate arm: on T7's dev tasks the fine-tuned G18b, asked the decision question over /v1/systemone, was wrong on
15 of 18 decisions after a change, often confidently. The overnight probe (10-07) found the untrained 4B answers "can
the request settle the method?" right 30/30 when it is asked as one question, while it volunteered a question only
3/30 times when writing plans. So this arm asks, never waits to be told.

Confidence is agreement: the share of answers (greedy plus `samples` sampled ones) that pick the greedy option. It is
reported as the decision's probabilities, so T7's calibration metrics read it like any other decider's.

`complete(messages, temperature)` is any chat endpoint (openai_chat_sampled: mlx_lm.server with the base 4B).
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Callable

from .decide import Context

LETTERS = "ABCDEF"

_DESCRIBE = {
    "continue": "继续按计划做下一件",
    "repair": "这一件重做一次，按刚才出的问题调整；计划不变",
    "replan": "剩下的计划已经不对了，重新写剩下的部分",
    "ask": "问用户：缺信息，或者要动用户确认过的东西",
    "handoff": "交给更强的云端模型",
    "stop": "停下，说明做完了什么、为什么剩下的做不了",
}


def _status(parts: list[dict]) -> str:
    mark = {"done": "已完成", "now": "刚做的", "todo": "还没做"}
    return "\n".join(f"- [{mark.get(p['status'], p['status'])}] {p['goal']}" for p in parts) or "（没有）"


def _letter(text: str, n: int) -> int | None:
    m = re.search(rf"[A-{LETTERS[n - 1]}]", text.strip().upper()[:4])
    return LETTERS.index(m.group(0)) if m else None


class ChatChoiceDecider:
    """A decision point as one lettered question to a chat model. Never falls back to the first option (continue)."""

    def __init__(self, complete: Callable[[list[dict], float], str], samples: int = 4, by: str = "local-4b") -> None:
        self.complete, self.samples, self.by = complete, samples, by

    def prompt(self, ctx: Context, opts: list[str]) -> list[dict]:
        lines = [f"用户的任务：{ctx.goal}", "", "计划：", _status(ctx.parts), "",
                 "刚才那一件：" + {"met": "完成了", "unmet": "没完成", "not_started": "还没开始"}.get(ctx.outcome, ctx.outcome)
                 + (f"（{ctx.detail[:300]}）" if ctx.detail else "")]
        if ctx.signals:
            lines.append("程序发现：" + "、".join(ctx.signals))
        if ctx.said:
            lines += ["用户说过：", *[f"- {s}" for s in ctx.said]]
        lines += ["", "接下来怎么做？", *[f"{LETTERS[i]}. {_DESCRIBE[o]}" for i, o in enumerate(opts)],
                  f"只回答一个字母（{'、'.join(LETTERS[:len(opts)])}）。"]
        return [{"role": "user", "content": "\n".join(lines)}]

    def decide(self, ctx: Context) -> tuple[str, dict | None, str]:
        opts = ctx.options()
        msgs = self.prompt(ctx, opts)
        votes = [_letter(self.complete(msgs, t), len(opts)) for t in [0.0] + [0.7] * self.samples]
        valid = [v for v in votes if v is not None]
        if not valid:
            raise ValueError("the decider answered no option letter")
        pick = votes[0] if votes[0] is not None else max(set(valid), key=valid.count)
        probs = {o: round(sum(1 for v in votes if v == i) / len(votes), 4) for i, o in enumerate(opts)}
        return opts[pick], probs, self.by


class EnoughInfoCheck:
    """Before planning: can the request settle how to do it? One A/B question; True when the greedy answer is A.
    The share of B answers is kept as `p_ask` (last call), for the calibration report."""

    QUESTION = ("用户的要求：{goal}\n\n文件清单：\n{files}\n{said}\n只看上面的要求、文件和用户说过的话，你能确定该把哪些文件放到哪里、要不要改名吗？\n"
                "A. 能确定，说清楚了\nB. 不能确定，得先问用户\n只回答 A 或 B。")

    def __init__(self, complete: Callable[[list[dict], float], str], samples: int = 4) -> None:
        self.complete, self.samples = complete, samples
        self.p_ask: float | None = None
        self.calls = 0

    def __call__(self, goal: str, listing: list[str], said: list[str]) -> bool:
        said_txt = ("\n用户说过：\n" + "\n".join(f"- {s}" for s in said) + "\n") if said else ""
        msgs = [{"role": "user", "content": self.QUESTION.format(goal=goal, files="\n".join(listing[:200]), said=said_txt)}]
        votes = [self.complete(msgs, t).strip().upper()[:1] for t in [0.0] + [0.7] * self.samples]
        self.calls += len(votes)
        self.p_ask = votes.count("B") / len(votes)
        return votes[0] != "B"


def openai_chat_sampled(base_url: str, model: str, api_key: str | None = None, timeout: float = 120.0,
                        max_tokens: int = 8) -> Callable[[list[dict], float], str]:
    """An OpenAI-compatible chat endpoint taking a temperature per call (mlx_lm.server serves it)."""
    url = base_url.rstrip("/") + "/chat/completions"

    def complete(messages: list[dict], temperature: float = 0.0) -> str:
        body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
            "Content-Type": "application/json", **({"Authorization": f"Bearer {api_key}"} if api_key else {})})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)["choices"][0]["message"]["content"]
    return complete
