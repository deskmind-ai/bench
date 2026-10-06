"""A local text server for OpListExecutor's planner: POST {"prompt"} -> {"text"}, the model's own chat template with
thinking off, greedy. Needs mlx_lm, so run it in brain's environment:

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
    model, tokenizer = load(args.model)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            text = tokenizer.apply_chat_template([{"role": "user", "content": body["prompt"]}], tokenize=False,
                                                 add_generation_prompt=True, enable_thinking=False)
            out = generate(model, tokenizer, prompt=text, max_tokens=args.max_tokens, verbose=False)
            data = json.dumps({"text": out}, ensure_ascii=False).encode()
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
