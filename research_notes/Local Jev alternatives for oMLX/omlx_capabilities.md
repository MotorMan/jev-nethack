# oMLX capabilities for use as a fast multiple-choice decision picker

Scope: oMLX (github.com/jundot/omlx, confirmed as the project; homepage https://omlx.ai; ~22.4k stars as of 2026-09-29). Local install checked read-only: `/usr/local/bin/omlx` -> `~/.omlx/bin/omlx` -> `/Applications/oMLX.app/Contents/MacOS/omlx-cli`. Python source is at `/Applications/oMLX.app/Contents/Resources/omlx/`.

Version facts:
- Local app: **oMLX 0.5.7** (from the app's Info.plist `CFBundleShortVersionString`). It bundles mlx 0.32.0, mlx-lm 0.31.3, xgrammar 0.2.3 and dflash_mlx 0.1.10+omlx.3 (from the dist-info directories in the app bundle).
- Upstream: latest stable is **v0.6.4** (2026-08-29). Latest pre-release is **v0.7.0rc1** (2026-09-24) — [releases](https://github.com/jundot/omlx/releases). The local install is about two minor versions behind.
- Local server was running (`/health` said healthy). One model is registered: `Qwen3.8-27B-Uncensored-MLX` (max_model_len 262144), and it was not loaded. I did not send generation requests, because that would load a 27B model. All capability claims below come from source code, GitHub and docs, not from live tests.
- Local settings (`~/.omlx/settings.json`): `max_concurrent_requests: 8`, `cache.enabled: true`, `chunked_prefill: false`, `max_context_window: 32768`, default sampling `temperature 1.0 / top_p 0.95`. So a picker must send `temperature: 0` explicitly. An API key is required (`skip_api_key_verification: false`).

## Does oMLX return logprobs and top_logprobs? Which endpoints? Open issues/PRs?

### Takeaway
No. Neither the local 0.5.7 nor upstream main (as of 2026-09-29) returns logprobs on any endpoint. The fields are silently ignored or come back empty. The fix is PR #1591. It has been open since 2026-06-02 and is still unmerged. Even that PR drops logprobs when `response_format` is set or a tool/reasoning parser is active, so today you cannot combine "constrain to the choice" and "read the choice probabilities" in oMLX.

### Cited Findings
- Local source (0.5.7): `api/openai_models.py` `ChatCompletionRequest` and `CompletionRequest` have no `logprobs`, `top_logprobs` or `logit_bias` fields. `ChatCompletionChoice` and `CompletionChoice` have no logprobs field. Internally, `request.py` has `logprobs: bool` / `top_logprobs` on the sampling params. `scheduler.py` (~line 9511) throws away mlx-lm's per-token logprobs "if not requested to free memory (~800KB per response)". The only `"logprobs"` strings in `server.py` are hard-coded `"logprobs":null` in SSE chunks. No `logit_bias` exists anywhere in the codebase. (Local inspection of `/Applications/oMLX.app/Contents/Resources/omlx/`.)
- Upstream main `omlx/api/openai_models.py` (fetched via GitHub API 2026-09-29) still has no `logprobs` field — [repo](https://github.com/jundot/omlx).
- Issue #1549 (open, 2026-05-30): "/v1/chat/completions accepts logprobs: true / top_logprobs: N but returns empty logprobs.content". It notes that mlx-lm and mlx-vlm both implement logprobs. A commenter says it is "also of interest for zero-shot classification tasks" — [Issue #1549](https://github.com/jundot/omlx/issues/1549)
- PR #1591 "feat(api): OpenAI-compatible logprobs for /v1/chat/completions (#1549)" is OPEN, created 2026-06-02 and last updated 2026-09-29. It adds `{token, logprob, bytes, top_logprobs[]}` under `choices[].logprobs.content` for streaming and non-streaming chat, with top_logprobs 0–20 and a server cap. It is chat only (no /v1/completions). "Logprobs are omitted when alignment or target-model probabilities cannot be established: speculative/protocol-parser paths, active tool filtering, rewritten non-streaming content, and ambiguous streaming segments." — [PR #1591](https://github.com/jundot/omlx/pull/1591)
- A live test of the PR on 2026-09-29 (Gemma-4-E2B classifier, M3 Ultra) found: plain chat and a JSON-schema request both "omitted `choices[0].logprobs` despite `logprobs: true, top_logprobs: 20`". The gemma4 parser session suppresses it, and "the non-streaming response builder in `server.py` requires `response_format is None`". The top-20 probabilities summed to 1.0024 (a low-precision normalization issue). A follow-up PR (popfido/omlx#2) says that disabling MTP with Qwen3.8-27B still omitted logprobs — [PR #1591 comments](https://github.com/jundot/omlx/pull/1591)
- One user asked for it to land in v0.7.0 (2026-09-19). The v0.7.0rc1 release notes do not mention logprobs — [PR #1591](https://github.com/jundot/omlx/pull/1591), [v0.7.0rc1](https://github.com/jundot/omlx/releases/tag/v0.7.0rc1)
- PR #2790 (open, 2026-08-18): "perf(scheduler): skip full-vocab logprobs when no row requested them". mlx-lm's batch step materializes a [vocab] fp32 array per row per decode step, and oMLX discards it — [PR #2790](https://github.com/jundot/omlx/pull/2790)

### Inferences
- A Jev-style "read the option-letter distribution from top_logprobs" design does not work on oMLX today, on any version. Qwen3.x models (the local model) go through a reasoning/tool parser, which may trigger the PR's suppression path even after it merges.
- The first generated token of a chat response is often a template or thinking token, not the answer letter. So even with logprobs you would need thinking disabled (`chat_template_kwargs: {"enable_thinking": false}`, which oMLX accepts) or a `/v1/completions` raw prompt. The PR does not cover /v1/completions.

### Gaps
- No maintainer comment on whether or when #1591 will merge.
- Not tested live: does 0.5.7 return a `logprobs` key at all in chat responses, or is it simply missing? The source suggests it is missing or null.

## Does it support guided decoding (JSON schema, regex, choice lists)?

### Takeaway
Yes, on `/v1/chat/completions` only. It uses xgrammar 0.2.3, masking tokens at sampling time. It supports OpenAI `response_format` (`json_object`, `json_schema`), a vLLM-style `structured_outputs` object (`json`, `regex`, `choice`, `grammar` in EBNF/GBNF) and `guided_grammar`. It is thinking-aware: the model reasons freely, then the output is constrained. `/v1/completions` has no structured-output fields.

### Cited Findings
- Local `api/openai_models.py`: `StructuredOutputOptions` is "vLLM-compatible … passed via `extra_body` … key is `structured_outputs`". Fields: `json` (alias of `json_schema`), `regex`, `choice: List[str]` ("output will be exactly one"), `grammar` (EBNF/GBNF). "Exactly one field should be set." `ChatCompletionRequest` has `response_format`, `structured_outputs` and `guided_grammar`. `CompletionRequest` has none of them. (Local source inspection.)
- Local `server.py` `_build_format_element`: `choice` is compiled to the EBNF `root ::= "a" | "b" | …` (each choice JSON-quoted). `regex` becomes an xgrammar regex, and `json_object` becomes an empty JSON schema. If grammar compilation is not available, oMLX falls back to injecting a JSON instruction into the system prompt and sets a `Warning` response header (`_response_format_warning_header`, `build_json_system_prompt`). (Local source inspection.)
- Local `api/grammar.py`: "Grammar-constrained decoding via xgrammar … enforces grammar constraints by masking invalid tokens at sampling time". For thinking models it compiles `[tag(<think>, any_text, </think>), constrained_schema]`, so reasoning is unconstrained. Bitmasks can be computed batched across concurrent requests. (Local source inspection.)
- README: "Supports all function calling formats available in mlx-lm, JSON schema validation, and MCP tool integration" — [README](https://github.com/jundot/omlx)
- A diffusion-model path rejects structured outputs (`_reject_diffusion_structured_outputs`). This does not apply to normal LLMs. (Local source inspection.)

### Inferences
- A `structured_outputs: {"choice": ["a","b","c"]}` request with `temperature: 0`, `max_tokens` of a few tokens and thinking disabled is the fastest correct way to use oMLX as a picker today. It returns exactly one valid option in 1–3 decode steps, but gives no confidence score.
- Constrained plus greedy gives the argmax over the allowed first tokens, which is close to what a logprob picker would choose. You lose calibration and the "safest pick when danger is high" style of blending that needs probabilities.

### Gaps
- Latency overhead of xgrammar compilation per request (choice lists change every turn) was not measured. The source mentions a grammar compiler per model but I did not confirm a compiled-grammar cache.

## Does it have a rerank or classification endpoint?

### Takeaway
It has `/v1/rerank` (Cohere/Jina-compatible) and `/v1/embeddings`. It has no generic classification endpoint. The reranker supports cross-encoders (ModernBERT, XLM-RoBERTa) and CausalLM rerankers such as Qwen3-Reranker, which are scored with yes/no logits and return a 0–1 `relevance_score` per document. That could serve as a scored multiple-choice picker (query = game state, documents = options), but the prompt template is fixed.

### Cited Findings
- Routes in local `server.py`: `/v1/models`, `/v1/embeddings`, `/v1/rerank`, `/v1/completions`, `/v1/chat/completions`, `/v1/messages` (Anthropic), `/v1/messages/count_tokens`, `/v1/responses`, plus audio routes (`/v1/audio/transcriptions`, `/v1/audio/speech`) and MCP routes. (Local source inspection.) The README endpoint table matches — [README](https://github.com/jundot/omlx)
- Local `api/rerank_models.py`: request fields are `model`, `query` (str or {text,image}), `documents` (list of str or dicts), `top_n`, `return_documents`, and `max_chunks_per_doc` ("Currently not implemented"). Each result is `{index, relevance_score (0–1), document}`. There is no custom-instruction field. (Local source inspection.)
- Local `models/reranker.py`: "CausalLM-based rerankers (e.g., Qwen3-Reranker) via yes/no logit scoring". It uses a hard-coded system prompt ("Judge whether the Document meets the requirements based on the Query and the Instruct provided… 'yes' or 'no'") and the default instruction "Given a web search query, retrieve relevant passages that answer the query". Qwen3-VL-Reranker is supported for multimodal input. (Local source inspection.)
- Local `model_discovery.py`: a CausalLM reranker is detected when the architecture is `Qwen3ForCausalLM` **and** the directory name contains "rerank" or "reranker". (Local source inspection.)
- README supported models: Embedding = BERT, BGE-M3, ModernBERT; Reranker = ModernBERT, XLM-RoBERTa — [README](https://github.com/jundot/omlx)

### Inferences
- Rerank-as-picker costs one forward pass per option, with no generation, and returns calibrated-ish per-option scores. That is a workable fallback for probabilities. The downsides: the fixed "web search" instruction, a reranker-sized model (Qwen3-Reranker 0.6B/4B/8B) rather than a chat model, and probably no shared-prefix KV reuse across documents. The reranker engine is separate from the paged-cache LLM engine, so the long game-state query is re-encoded for each option.
- A Qwen3ForCausalLM chat model placed in a directory named "*rerank*" would load as a yes/no scorer. This is an unsupported hack, and the chat model was not trained for that template.

### Gaps
- Not confirmed whether `/v1/rerank` batches documents in one forward pass or uses the prefix cache. Reranker latency was not measured.

## How does its prefix cache work and what latency do users report?

### Takeaway
oMLX has a vLLM-style paged, block-based prefix cache (256-token blocks, hash-chained, prefix sharing, copy-on-write). It has a RAM "hot" tier and an SSD "cold" tier (safetensors) that survives restarts. Before v0.7.0 only full blocks were reused. v0.7.0rc1 also reuses the trailing partial block. That matters for a game-state prefix that repeats but whose tail changes each turn. Reported numbers: TTFT falls from 30–90 s to 1–3 s on 50–100K-token agent contexts, and from 0.83 s to 0.42 s at 13.4K tokens with partial-block caching.

### Cited Findings
- README: "Block-based KV cache management inspired by vLLM, with prefix sharing and Copy-on-Write… Hot tier (RAM)… Cold tier (SSD): When the hot cache fills up, blocks are offloaded to SSD in safetensors format. On the next request with a matching prefix, they're restored from disk instead of recomputed from scratch - even after a server restart." — [README](https://github.com/jundot/omlx)
- Local `scheduler.py`: `paged_cache_block_size: int = 256  # Tokens per block`. `cache/prefix_cache.py` is "Block-Aware Prefix Cache… oMLX only supports paged SSD-based caching". It uses `compute_block_hash`, so matching is exact per full block. (Local source inspection.)
- v0.7.0rc1 "Partial Block Caching": "Previously, even a cached conversation could leave thousands of tokens to reprocess simply because they did not fill a complete cache block… In a 13.4K-token Qwen3.6-35B-A3B test, next-turn prefill dropped from 1,174 tokens to 37, cutting time to first token from 0.83s to 0.42s" (#3835) — [v0.7.0rc1 release](https://github.com/jundot/omlx/releases/tag/v0.7.0rc1). Follow-up issue #3940 asks to also snapshot before the final message so a new user turn does not fall back to the last full block — [Issue #3940](https://github.com/jundot/omlx/issues/3940)
- Show HN (about 6 months before 2026-09): "TTFT drops from 30-90s to 1-3s on follow-up requests". M3 Ultra 512GB, Qwen3-Coder-Next-8bit: 58.7 tok/s for a single request and 243 tok/s at batch 8. The thread had no independent user benchmarks — [HN](https://news.ycombinator.com/item?id=47247294)
- v0.7.0rc1 on M5 Max 128GB: Qwen3.8-Flash-Next oQ4e prefill runs at 2,007 tok/s at 16K, and Qwen3.8-27B oQ4e 4-request batch decode at 131.5–136.9 tok/s (DFlash2 / Lightning MTP) — [v0.7.0rc1 release](https://github.com/jundot/omlx/releases/tag/v0.7.0rc1). This is the developer's own benchmark.
- Local setting `preserve_mid_system_cache: true` exists in `~/.omlx/settings.json`. Its exact semantics were not verified. The README's pitch says the cache holds "even when context changes mid-conversation" — [README](https://github.com/jundot/omlx)
- A third-party review says oMLX addresses the problem that "every MLX server throws away its KV cache the moment a prompt prefix shifts" — [andrew.ooo review](https://andrew.ooo/posts/omlx-apple-silicon-ssd-kv-cache-review/) (secondary source)

### Inferences
- For the picker, put all stable content (system prompt, rules, static game info) first and the per-turn state and options last. With 256-token blocks on 0.5.7, up to 255 tokens of the changing tail plus everything after the first changed token is re-prefilled each call. Upgrading to 0.7.0 cuts the recompute to just the new tokens.
- With a warm prefix, a constrained 1–3-token choice on a ~27B 4-bit model should come in at a few hundred ms TTFT plus the decode time of a few tokens on high-end Apple Silicon. This is extrapolated from the 0.42 s at 13.4K figure. I did not measure it on this machine.

### Gaps
- No independent, per-request latency numbers for short-output classification workloads on oMLX. The user reports found concern long-context coding agents.

## Batching/concurrency and supported model formats

### Takeaway
oMLX does continuous batching through mlx-lm's BatchGenerator, with a configurable max concurrency (local setting: 8). It serves MLX-format safetensors models (LLM, VLM, OCR, embedding, reranker, audio), multiple models at once with LRU/pinning, and its own "oQ" quantization. It does not serve GGUF.

### Cited Findings
- "Continuous Batching: Handles concurrent requests through mlx-lm's BatchGenerator. Max concurrent requests is configurable." "Load LLMs, VLMs, embedding models, and rerankers within the same server." "Point `--model-dir` at a directory containing MLX-format model subdirectories." — [README](https://github.com/jundot/omlx)
- `__init__.py` (local): "Continuous batching via vLLM-style scheduler; OpenAI-compatible API server". oMLX "started from vllm-mlx v0.1.0" — [README](https://github.com/jundot/omlx)
- v0.7.0rc1 adds batched DFlash and Lightning MTP speculative decoding for concurrent requests — [release](https://github.com/jundot/omlx/releases/tag/v0.7.0rc1)
- Open crash reports involve concurrent/batched requests on some models, for example "Qwen3.6 VLM build: any second concurrent request crashes engine loop" (#1800) and "Token sampling crashes … Thread group size (1024)… on M2 Ultra" (#2049) — [#1800](https://github.com/jundot/omlx/issues/1800), [#2049](https://github.com/jundot/omlx/issues/2049)

### Inferences
- You can batch several independent choice requests (for example, candidate evaluations) in parallel with good throughput scaling. The HN figure shows about 4x at batch 8.

### Gaps
- Stability of concurrency on the specific local model (Qwen3.8-27B) was not verified.

## How does it compare with mlx-lm server, LM Studio and vllm-mlx on these features?

### Takeaway
For a probability-based picker, **mlx-lm's own `mlx_lm.server` is the strongest MLX option**. It returns `logprobs` plus `top_logprobs` and accepts `logit_bias`, and it also has an LRU prompt cache and batching. oMLX is better on prefix caching (paged + SSD + partial blocks), constrained choice/regex and multi-model management, but has no logprobs. LM Studio's MLX runtime reportedly does not return top_logprobs (its GGUF runtime does). vllm-mlx has JSON-schema output, a prefix cache, batching, embeddings and rerank, but documents no logprobs.

### Cited Findings
- mlx-lm server (bundled mlx-lm 0.31.3, `mlx_lm/server.py`): request args include `logit_bias: Optional[Dict[int, float]]`, `logprobs: bool` and `top_logprobs: int`. `_format_top_logprobs` returns the top-N tokens. It uses `LRUPromptCache.fetch_nearest_cache` for prompt reuse and has a `batch_generator`. (Local inspection of the bundled package.) SERVER.md documents `logprobs` ("number of top tokens and corresponding log probabilities", 1–10) and `logit_bias`, notes batching is disabled with a quantized KV cache, and does not document `response_format` — [mlx-lm SERVER.md](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md)
- LM Studio: "The MLX runtime in LM Studio currently does not return `top_logprobs` on this call (GGUF does), so GGUF is the reliable local path today" (issue about Jev-style decision models) — [nowledge-mem #128](https://github.com/nowledge-co/nowledge-mem/issues/128). The LM Studio mlx-engine logprobs request is at [lmstudio-ai/mlx-engine #37](https://github.com/lmstudio-ai/mlx-engine/issues/37) (status not verified).
- vllm-mlx README: "Structured output: JSON Schema via `response_format` (lm-format-enforcer)", "Prefix cache: trie-based, shared across requests", "Continuous batching", Embeddings, `/v1/rerank`. No logprobs, regex or choice constraints are documented — [vllm-mlx](https://github.com/waybarrios/vllm-mlx)
- mlx-vlm's server supports OpenAI-shaped logprobs (`logprobs.content[]` with `top_logprobs`, capped by `TOP_LOGPROBS_K`) and json_schema structured outputs — [mlx-vlm PyPI](https://pypi.org/project/mlx-vlm/) (via a search snippet, not fetched in full)

Comparison summary (from the sources above):

| Feature | oMLX 0.5.7 / 0.7.0rc1 | mlx_lm.server 0.31.x | LM Studio (MLX) | vllm-mlx |
|---|---|---|---|---|
| logprobs/top_logprobs | No (PR #1591 open) | Yes | No top_logprobs (GGUF yes) | Not documented |
| logit_bias | No | Yes | not checked | not checked |
| JSON schema | Yes (xgrammar) | Not documented | not checked | Yes (lm-format-enforcer) |
| regex / choice / EBNF | Yes (chat only) | No | not checked | Not documented |
| Prefix cache | Paged 256-tok blocks, RAM+SSD, partial block in 0.7 | LRU nearest-prefix | not checked | Trie-based |
| Continuous batching | Yes | Yes (not with quantized KV) | not checked | Yes |
| Rerank / embeddings | Yes / Yes | No / No | not checked | Yes / Yes |

### Inferences
- Practical options for the picker on this Mac:
  - (a) Use oMLX with `structured_outputs.choice` for a fast argmax pick with no confidence. This works today.
  - (b) Run `mlx_lm.server` (already bundled inside oMLX.app, or installed via pip) on another port with `/v1/completions`, `max_tokens: 1`, `logprobs` / `top_logprobs` and `logit_bias` restricted to the option-letter token IDs. That gives full distributions with prompt-cache reuse.
  - (c) Build PR #1591 from source. It is fragile: suppressed with `response_format` and parsers.
  - (d) Use oMLX `/v1/rerank` with a Qwen3-Reranker model for per-option scores.

### Gaps
- LM Studio's current (2026-09) MLX logprobs status and structured-output support were not checked directly. The one source is a third-party issue.
- No head-to-head latency benchmark of these servers for short classification requests was found.
