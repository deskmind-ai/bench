"""A local text server for Tier O's planners: POST {"prompt"} -> {"text"} (OpListExecutor) and POST
/v1/chat/completions (ModelPlanner, via plan_model.openai_chat), the model's own chat template with thinking off,
greedy. Needs mlx_lm, so run it in brain's environment:

    cd ~/projj/github.com/deskmind-ai/brain
    uv run --extra mlx python -m deskmind_bench.dyn.proto.textgen models/brain-4b --port 8899 --max-tokens 1500

(with the bench checkout on PYTHONPATH). Only 127.0.0.1 is served.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m deskmind_bench.dyn.proto.textgen")
    ap.add_argument("model")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--max-tokens", type=int, default=1500)
    args = ap.parse_args()
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler
    model, tokenizer = load(args.model)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            # Two shapes: {"prompt"} -> {"text"}; and OpenAI-style /chat/completions {"messages"} -> {"choices"}, which
            # plan_model.openai_chat speaks (ModelPlanner). Thinking is off in both, unlike mlx_lm.server's default.
            chat = self.path.rstrip("/").endswith("chat/completions")
            messages = body["messages"] if chat else [{"role": "user", "content": body["prompt"]}]
            text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                                 enable_thinking=False)
            temp = float(body.get("temperature") or 0.0)   # arm (e) samples at 0.7 for its agreement confidence
            sampler = make_sampler(temp=temp) if temp > 0 else None
            out = generate(model, tokenizer, prompt=text, max_tokens=int(body.get("max_tokens") or args.max_tokens),
                           verbose=False, **({"sampler": sampler} if sampler else {})).replace("<|im_end|>", "")
            reply = {"choices": [{"message": {"role": "assistant", "content": out}}]} if chat else {"text": out}
            data = json.dumps(reply, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
