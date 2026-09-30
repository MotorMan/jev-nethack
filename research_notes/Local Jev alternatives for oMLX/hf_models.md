# Open-weights HF models for a fast local "decision picker" (Jev-style choice / noul / score) on Apple Silicon

Research date: 2026-09-29. About 20 search/fetch calls. Several 2026 facts come from single secondary sources, and those are flagged.

## Ranked shortlist (summary; details and sources in the sections below)

| Rank | Model (HF repo) | Size | License | Date | MLX? | Why |
|---|---|---|---|---|---|---|
| 1 | `mstrasser/Jeff-Qwen3.5-0.8B` | 0.8B (1.7 GB bf16) | Apache 2.0 | v1.1 on 2026-09-29 | Runs via MLX (28 ms on M4 Max reported). No mlx-community build found | Built as a direct Jev-compatible replacement: choice / noul / score, calibrated per-option probabilities, up to 254 options |
| 2 | `mstrasser/Jeff-Qwen3.5-2B` | 2B (4.2 GB) | Apache 2.0 | 2026 (v1.1 2026-09-29) | Via MLX (60 ms on M4 Max) | Higher accuracy (82.0-83.1% vs Jev's 83.0%) |
| 3 | Jeff-Gemma4-E2B (repo name not confirmed) | E2B (9.3 GB) | Apache 2.0 | 2026 | Not confirmed | Max 26 options |
| 4 | `Qwen/Qwen3.5-0.8B / 2B / 4B / 9B` | 0.8-9B | not verified here | 2026-03-02 | unsloth GGUF confirmed; MLX not directly confirmed | Base for DIY logprob multiple-choice |
| 5 | Gemma 4 E2B / E4B (+ `mlx-community/gemma-4-12B-it-qat-4bit`) | E2B, E4B, 12B | Apache 2.0 | 2026-04-02 | Yes (mlx-community Gemma 4 collection; `unsloth/gemma-4-E4B-it-MLX-8bit`) | Strong small instruct models for logprob multiple-choice |
| 6 | `mlx-community/Qwen3-Reranker-0.6B-mxfp8` (and 4B/8B) | 0.6B / 4B / 8B | (Qwen3 family; not verified here) | 2025-06 | Yes, and oMLX `/v1/rerank` serves it | Its score is literally P(yes) over {yes,no}, so it maps to noul |
| 7 | `Skywork/Skywork-Reward-V2-Qwen3-0.6B / 1.7B / 4B / 8B` | 0.6-8B | not verified | 2025-07 | Not found | Scalar reward, needs a sigmoid/calibration step to map to 0-1 |
| 8 | `LiquidAI/LFM2.5-2.6B-MLX`, LFM2.5-1.2B, LFM2.5-230M | 0.23-2.6B | lfm1.0 (custom) | 2026 (230M: June, 2.6B: August) | Yes, official MLX | Very fast edge instruct models; no multiple-choice or calibration data found |
| 9 | `knowledgator/gliclass-modern-base-v2.0` / `-large-v2.0` | ModernBERT base/large | not verified | 2025-02 | No MLX (PyTorch/ONNX) | Zero-shot classifier, single forward pass, up to about 100 labels |

Game-specific: I found no open-weights HF model trained for NetHack or BALROG action selection. NitroGen (500M, vision/gamepad) is the closest "game agent foundation model" I found, and it does not fit a text-option picker.

## Which small (<15B) models score best on multiple-choice / calibration benchmarks and have MLX builds?

### Takeaway
The best fit is Jeff (firelex/jeff, weights under `mstrasser/` on HF). It is a Qwen3.5-0.8B/2B and Gemma-4-E2B fine-tune made for Jev-style choice/noul/score. It reports ECE 0.021 and 28-60 ms per decision on an M4 Max with MLX. I found no independent calibration benchmark that ranks Qwen3.5 against Gemma 4 small models.

### Cited Findings
- Jeff is a fine-tune of Qwen3.5 and Gemma 4 for zero-shot classification. You describe a situation and list options in plain words, and Jeff returns a calibrated probability for each option from a single forward pass. It supports three question types: choice, yes/no (noul), and score — [firelex/jeff GitHub](https://github.com/firelex/jeff)
- Jeff models: Jeff-Qwen3.5-0.8B (1.7 GB), Jeff-Qwen3.5-2B (4.2 GB), Jeff-Gemma4-E2B (9.3 GB), and Jeff-Qwen3.5-0.8B-Chess. Code is MIT, weights are Apache 2.0, and v1.1 was published 2026-09-29 — [firelex/jeff GitHub](https://github.com/firelex/jeff)
- Median latency per decision: M4 Max via MLX 28 ms (0.8B) / 60 ms (2B); RTX PRO 6000 22/24 ms; 32-thread CPU 463-708 ms — [firelex/jeff GitHub](https://github.com/firelex/jeff)
- Accuracy across 5 benchmarks: 79.1% (0.8B), 82.0% (2B), vs "Jev's published 83.0%" — [firelex/jeff GitHub](https://github.com/firelex/jeff). A secondary source says 83.1% for the 2B — [ai-tldr / search snippet](https://ai-tldr.dev/releases/firelex-jeff/) (the two numbers conflict slightly)
- v1.1 raised max options from 26 to 254 (Qwen). The 0.8B went from 40% to 95% on their long-list test. The Qwen backbone has a trained 255-option readout head with a fitted temperature — [Release v1.1](https://github.com/firelex/jeff/releases/tag/v1.1) (via search snippet)
- The Jeff-Qwen3.5-0.8B model card reports calibration error 0.021, Apache 2.0, about 2 hours of full-weight SFT on one RTX PRO 6000, and synthetic data plus converted sentiment, entailment, QA, and safety datasets. It "won't match" on multi-step reasoning tasks — [HF: mstrasser/Jeff-Qwen3.5-0.8B](https://huggingface.co/mstrasser/Jeff-Qwen3.5-0.8B)
- An ONNX port exists: `Zatsepin/jeff-qwen3.5-0.8b-onnx` — [HF](https://huggingface.co/Zatsepin/jeff-qwen3.5-0.8b-onnx)
- A secondary source reports 29-49 ms per move for Jeff-0.8B on an M4 Max — [explainx.ai](https://www.explainx.ai/blog/jeff-jev-compatible-08b-decision-models-firelex-2026)
- Qwen3.5 Small (0.8B, 2B, 4B, 9B) was released 2026-03-02. It is natively multimodal and trained with scaled RL. The Medium tier is 27B, 35B-A3B, 122B-A10B, and 397B-A17B — [Qwen on X](https://x.com/Alibaba_Qwen/status/2028460046510965160); [HF Qwen/Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B)
- Gemma 4 was released 2026-04-02 in E2B, E4B, 26B MoE (A4B), and 31B dense, under Apache 2.0 with 128K context — [Google blog](https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/). mlx-community also hosts a 12B (`mlx-community/gemma-4-12B-it-qat-4bit`, `-OptiQ-4bit`) — [HF mlx-community](https://huggingface.co/mlx-community/gemma-4-12B-it-qat-4bit); [collection](https://huggingface.co/collections/mlx-community/gemma-4). The Google blog does not list a 12B, which conflicts with the HF repos.
- Unsloth publishes MLX builds, for example `unsloth/gemma-4-E4B-it-MLX-8bit` and `unsloth/gemma-4-26b-a4b-it-UD-MLX-4bit` — [HF](https://huggingface.co/unsloth/gemma-4-E4B-it-MLX-8bit)
- LFM2.5 (Liquid AI): 1.2B family (28T pretraining tokens + RL), 230M (June 2026), and 2.6B (August 2026, 128K context, tool calling, lfm1.0 license). All have MLX from day one, for example `LiquidAI/LFM2.5-2.6B-MLX` — [Liquid AI blog](https://www.liquid.ai/blog/introducing-lfm2-5-the-next-generation-of-on-device-ai); [MarkTechPost 2.6B](https://www.marktechpost.com/2026/08/06/liquid-ai-lfm2-5-2-6b-on-device-agentic-model/); [HF](https://huggingface.co/LiquidAI/LFM2.5-2.6B-MLX)
- General 2026 guidance: raw LLM confidence signals (verbalized, mean logprob) are "rarely calibrated out of the box". Use Platt/temperature scaling and measure with Brier/ECE — [FutureAGI](https://futureagi.com/blog/evaluating-llm-confidence-uncertainty-2026/)

### Inferences
- For a drop-in local Jev, Jeff-Qwen3.5-0.8B is the obvious first test. It uses Jev's own question types and has published M4 Max MLX latency. The 2B is worth it only if 60 ms is acceptable.
- A DIY route is possible: take option-letter logprobs from Qwen3.5-4B/9B or Gemma-4-E4B through mlx-lm, then fit a temperature on logged Jev decisions. It needs its own calibration step. No published numbers compare it to Jeff.
- The Jeff latency figures appear to be single-decision latency with short prompts. Long NetHack state prompts will cost more because prefill scales with tokens (see the oMLX figure of 0.38 ms/token below).

### Gaps
- I did not find an mlx-community or official MLX-quantized Jeff repo. The 28 ms MLX figure implies it runs under MLX (probably through mlx-lm from bf16 safetensors), but the load path is not confirmed. The Jeff custom readout head may need its own loader code, which is not verified.
- The exact HF repo ID of Jeff-Gemma4-E2B and the Chess variant is not confirmed.
- I found no neutral benchmark of multiple-choice calibration (ECE) for Qwen3.5 vs Gemma 4 vs LFM2.5 small models.
- Qwen3.5 license and mlx-community availability were not directly verified in this pass. An "Qwen3.8" GitHub repo showed up in search, and the Jeff card mentions "Qwen3.8-Flash-Next". I did not verify either.
- Phi, SmolLM, and Llama 2026 releases were not researched (no time left in the call budget).

## Are there rerankers/judges that output a yes/no probability that maps well to Jev's "noul" and "choice"?

### Takeaway
Yes. Qwen3-Reranker's score *is* softmax(P(yes), P(no)) at the final token. mlx-community has an MLX build, and oMLX already serves it on `/v1/rerank`. That maps to noul directly, and to choice if you score each option and then normalize. Reward models (Skywork-Reward-V2) and cross-encoders (bge-reranker) output unbounded logits and need calibration.

### Cited Findings
- Qwen3-Reranker computes relevance as the probability of the "yes" token after a softmax over {yes, no} logits at the answer position. Some implementations use yes_logit − no_logit instead — [oMLX issue #3913](https://github.com/jundot/omlx/issues/3913); [vLLM Qwen3 Reranker example](https://docs.vllm.ai/en/v0.9.2/examples/offline_inference/qwen3_reranker.html)
- oMLX (0.6.4, MLX 0.32.2) serves Qwen3-Reranker-4B (mxfp8) on `/v1/rerank`. Measured: 22 docs in 2.1 s with a 31-char query, 6.5 s with a 2,000-char query, which is about 24 ms/doc + 0.38 ms/token. Each document is a full forward pass that recomputes the shared prefix, and over 80% of tokens are redundant for long queries (opened 2026-09-25) — [oMLX issue #3913](https://github.com/jundot/omlx/issues/3913)
- `mlx-community/Qwen3-Reranker-0.6B-mxfp8` exists (converted with mlx-embeddings 0.0.3). There is also a community build, `mku64/Qwen3-Reranker-0.6B-mlx-8Bit` — [HF](https://huggingface.co/mlx-community/Qwen3-Reranker-0.6B-mxfp8); [HF](https://huggingface.co/mku64/Qwen3-Reranker-0.6B-mlx-8Bit)
- Qwen3-Reranker comes in 0.6B, 4B, and 8B — [Qwen3 Embedding paper](https://arxiv.org/pdf/2506.05176); [FutureAGI rerankers 2026](https://futureagi.com/blog/best-rerankers-for-rag-2026/)
- bge-reranker-v2-m3 is a SequenceClassification cross-encoder that outputs a single logit per [query, doc] pair — [search summary citing Xinference/FutureAGI](https://inference.readthedocs.io/en/latest/models/builtin/rerank/index.html)
- Skywork-Reward-V2 has 8 models (Qwen3 0.6B/1.7B/4B/8B, Llama-3.1-8B, Llama-3.2-1B, and others), trained on 26M preference pairs. It reports SOTA on RewardBench v1/v2, PPE, RMB, RM-Bench, and JudgeBench. The 0.6B nearly matches the older Skywork-Reward-Gemma-2-27B — [HF Skywork-Reward-V2-Qwen3-0.6B](https://huggingface.co/Skywork/Skywork-Reward-V2-Qwen3-0.6B); [arXiv 2507.01352](https://arxiv.org/pdf/2507.01352)

### Inferences
- Qwen3-Reranker-0.6B is the lowest-effort noul scorer on oMLX. Put the state/question as the "query" and "yes" as the document, or ask the instruction directly. For choice, score each option and apply a softmax over the per-option yes-logit margins. This costs N forward passes and has the prefix-recompute problem from issue #3913. A single-pass multi-option model like Jeff avoids both.
- Rerankers are trained for relevance, not for decisions about game states. Their P(yes) will probably need a temperature fitted on logged Jev outputs before it is used as a calibrated probability.
- Reward models score (prompt, response) pairs as a scalar. You can use them as a choice scorer (one response per option), but a sigmoid of the scalar is not a calibrated probability, and I found no MLX builds.

### Gaps
- I did not research Prometheus 2 or JudgeLM updates in 2025-2026, mxbai-rerank-v2 MLX availability, or newer 2026 rerankers (KaLM-Reranker-V1, Querit-Reranker appear on arXiv but were not checked).
- I found no calibration numbers (ECE) for reranker yes-probabilities.

## Any HF models trained for NetHack, roguelikes, or game action selection (BALROG, NLE, NetHack Learning Dataset)?

### Takeaway
I found no open-weights LLM on HF that is fine-tuned for NetHack/BALROG action selection. Published LLM NetHack agents use closed API models. NitroGen is an open 500M game-agent foundation model, but it maps pixels to gamepad actions and is not a text-option picker.

### Cited Findings
- The BALROG leaderboard (balrogai.com) is updated weekly. Top Gemini-3.x entries are at about 57-58% average progress, and NetHack is still the hardest environment — [BenchmarkList](https://benchmarklist.com/benchmarks/balrog_official_llm/); [BALROG paper](https://huggingface.co/papers/2411.13543)
- A January 2026 blog tested only API models (GPT 5.2, Gemini 3 Flash/Pro Preview, Claude Opus 4.5) on NetHack. The best, GPT 5.2, reached Dlvl 10 with a BALROG progression score of 12.56%. There were no ascensions, and spatial awareness was the main weakness. No open-weights or HF models were tested — [Vaguely Aligned](https://kenforthewin.github.io/blog/posts/nethack-agent/)
- A secondary outlet claims a GPT-6 Astra agent ascended in NetHack in September 2026, and that BALROG put Astra at about 13% progress — [itdoeswhatnow](https://itdoeswhatnow.com/m/2026-09-21-gpt-6-astra-becomes-the-first-ai-agent-to-win-nethack/). **Unverified, and a low-quality source.** I found no primary confirmation.
- NetHackers (dunnolab) is a competition to build a bot that reliably wins NetHack 3.6.6. As of 2026-09-30 it has 610 programs, 20 contributors, zero ascensions, and a best progression of 0.807 vs the AutoAscend baseline of 0.077-0.078. The source repo is private, and no models or datasets were released — [NetHackers](https://nethackers.dunnolab.ai/). (The progression scale looks different from BALROG's percentage, so do not compare the two directly.)
- NitroGen is an open foundation model for generalist gaming agents: 500M params, flow-matching GR00T architecture, and it works across genres including roguelikes — [NitroGen](https://nitrogen.minedojo.org/)
- Jeff ships a game-specific variant, Jeff-Qwen3.5-0.8B-Chess, which shows the approach can be fine-tuned per game — [firelex/jeff](https://github.com/firelex/jeff)

### Inferences
- The practical route for NetHack is to fine-tune Jeff (about 2 GPU-hours reported for its SFT) on logged Jev decisions from this project. That is easier than finding a NetHack-trained HF model.

### Gaps
- I did not directly search HF for NLD-trained (NetHack Learning Dataset) checkpoints or for the balrog-ai HF org. Non-LLM NLE RL policies (for example Motif, diff-history) may exist on HF but were not checked.

## Trending HF models in 2026 relevant to this

### Takeaway
The relevant 2026 wave is small, fast models with day-one MLX support: Qwen3.5 Small (March), Gemma 4 E2B/E4B (April), and LFM2.5 230M/1.2B/2.6B (June-August). Jeff v1.1 (released today, 2026-09-29) is the single most on-target release.

### Cited Findings
- Qwen3.5 Small, 2026-03-02 — [Qwen on X](https://x.com/Alibaba_Qwen/status/2028460046510965160)
- Gemma 4, 2026-04-02, with an mlx-community Gemma 4 collection and a Gemma-4 Assistant (MTP) collection — [Google](https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/); [mlx-community](https://huggingface.co/collections/mlx-community/gemma-4-assistant-mtp)
- LFM2.5-230M (June 2026) and LFM2.5-2.6B (August 2026), plus LFM2.5-VL-3B-DSpark with speculative decoding (2026-09-25) — [MarkTechPost](https://www.marktechpost.com/2026/06/27/liquid-ai-ships-lfm2-5-230m-with-llama-cpp-mlx-vllm-sglang-and-onnx-support-for-on-device-inference/); [MarkTechPost](https://www.marktechpost.com/2026/09/25/liquid-ai-releases-lfm2-5-vl-3b-dspark-speculative-decoding-for-vision-language-models-with-up-to-3-13x-faster-decoding/)
- Jeff v1.1, 2026-09-29 — [GitHub release](https://github.com/firelex/jeff/releases/tag/v1.1)
- An HF "State of Open Models: Summer 2026" post exists, but I did not read it — [HF blog](https://huggingface.co/blog/state-of-open-models-summer-2026)

### Inferences
- Candidates to benchmark against Jev on this project's own prompts: Jeff-0.8B, Jeff-2B, Qwen3-Reranker-0.6B (noul only, via oMLX), and Qwen3.5-4B or Gemma-4-E4B with logprob multiple-choice plus fitted temperature.

### Gaps
- I did not scrape the live HF trending page. I did not check r/LocalLLaMA sentiment.
