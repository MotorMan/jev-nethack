# GitHub projects for a local replacement of the hosted Jev "choice picker" (Apple Silicon)

Method: repo metadata (stars, created, last push) pulled live with `gh api` on 2026-09-29/30 UTC; READMEs and issues read via `gh`. "Trending" is inferred from star counts on repos created in the last ~2 weeks (GitHub's trending page itself was not scraped). Jev = TypeSafe AI's hosted "System One" typed-decision model (`POST /v1/systemone`, question types `choice` / `noul` (yes/no probability) / `score`) — [awesome-jev](https://github.com/yibie/awesome-jev), [TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev).

## Which libraries give per-option probabilities (not just a choice) from a local model?

### Takeaway
The strongest match is a new (Sept 2026) wave of open "Jev-compatible" decision models and servers that speak the exact `/v1/systemone` wire format and return a probability for every option in one forward pass; two run natively on MLX (laya-mlx, SemIf `--backend mlx`) and OpenJev supports MLX too. Classic constrained-generation libraries (outlines, xgrammar, llguidance, lm-format-enforcer) guarantee a valid choice but do not by themselves return a distribution over options; SGLang's `select` does (normalized logprobs per option) but is CUDA-first.

### Cited Findings

**A. Jev-compatible open decision models / servers (drop-in candidates)**

| Repo | Stars | Created / last push | What it does | Apple Silicon |
|---|---|---|---|---|
| [NandhaKishorM/laya](https://github.com/NandhaKishorM/laya) | 28,744 | 2026-09-18 / 2026-09-29 | Non-autoregressive "System 1 decision engine"; typed choice/score/yes-no in a single forward pass (~33 ms), 100+ languages, trained with RL against strictly proper scoring rules; `laya[serve]` HTTP server, MCP, LangChain extras; `laya-multilingual` up to 8,192 tokens; "a 4,000-token input takes about 1.7 s on an Apple GPU" | Yes (Apple GPU via PyTorch; MLX via laya-mlx) |
| [mizorewww/laya-mlx](https://github.com/mizorewww/laya-mlx) | 6,638 | 2026-09-19 / 2026-09-22 | Native MLX runtime for Laya: 13.4 ms median short decision (7.4 ms multilingual) on M3 Max, 0 output tokens, no PyTorch; `pip install laya-mlx`; Snake demo at 75.4 moves/s with a safety layer | Native MLX |
| [mizorewww/laya-coreml](https://github.com/mizorewww/laya-coreml) | 1,530 | — / 2026-09-22 | Laya on Core ML / Neural Engine, ~5 ms short decisions on M3 Max | Core ML / ANE |
| [ollaya-dev/ollaya](https://github.com/ollaya-dev/ollaya) | 993 | 2026-09-23 / 2026-09-29 | "Ollama for decision models": pull/serve Laya, `winnow`, `jevk5`, NLI, GLiClass behind wire-identical `/v1/systemone`; set `TYPESAFE_BASE_URL=http://localhost:11435` and the official SDK works; `winnow:e4b` 0.722 typed-decision accuracy vs Jev 0.738 (their numbers); recommends `laya` without NVIDIA GPU | CPU/ONNX; GGUF models |
| [wfzyx/von](https://github.com/wfzyx/von) | 776 | 2026-09-18 / 2026-09-30 | 395M ModernBERT encoder, non-autoregressive, Choice with probability over all K options, Noul, Score; drop-in `/v1/systemone` server + `von-sdk`; "Sub-15ms"; Doom demo | Apple MPS supported |
| [razorback16/openjev](https://github.com/razorback16/openjev) | 538 | 2026-09-18 / 2026-09-29 | Jev-wire-compatible server; default DiffusionGemma 26B-A4B; also serves `laya-1.0`, `verdict-1.4`, `clm-v0.1`, `jevk5-0.2`; up to 255 choices; images | "through MLX on Apple silicon" |
| [TheoLeeCJ/SemIf-OpenJev](https://github.com/TheoLeeCJ/SemIf-OpenJev) (SemIf) | 4,581 | — / 2026-09-23 | Reads declared option logits from a frozen LLM (Qwen3.5-4B etc.) in one forward pass; shared-state mode prefills state once and branches across criteria; added per-workload temperature calibration (2026-09-22); 21 criteria in 1.02 s vs 5.33 s for JSON generation on a 3090 | Native MLX backend (`--backend mlx`), PyTorch/MPS, llama.cpp |
| [TianyuCodings/NanoJev](https://github.com/TianyuCodings/NanoJev) | 2,440 | — / 2026-09-21 | Qwen3-0.6B + decision heads; Choice over 2–255 candidates via set attention + softmax; trained on game tasks (ViZDoom 128/128 vs Jev 56/128, Maze, Snake); HF weights + dataset | Not stated |
| [feder-cr/jev](https://github.com/feder-cr/jev) (jevos) | 1,119 | — / 2026-09-29 | Yes/no only (P(yes)), GGUF via llama.cpp, 54–220 ms on laptop CPU; accuracy 0.811 vs Jev 0.927 vs Laya 0.489 on their 2,000-question set; choice/score "Soon" (422 today) | CPU / llama.cpp |
| [malevrigns/agent-jev](https://github.com/malevrigns/agent-jev) | 325 | 2026-09-21 / 2026-09-23 | AgentJev-0.6B (Qwen3-0.6B), one forward pass → probability for every option, 79.25% top-1 on 2,000 decisions, 2,048 ctx | Not stated |
| [us/jev-local](https://github.com/us/jev-local) | 8 | 2026-09-18 | `/v1/systemone` server with HF logprob scorer; "light" Qwen2.5-3B fits 16 GB Mac; Qwen2.5-3B (chat) 0.90 choice / 1.00 noul on their set1 | HF transformers |
| [Argos1111/jev_local](https://github.com/Argos1111/jev_local) | 37 | 2026-09-18 / 2026-09-23 | First-answer-token logprob scoring (LFM2.5-1.2B, llama.cpp) or ModernBERT cross-encoder; Japanese-focused | llama.cpp |
| [virajbhartiya/laya-vs-jev](https://github.com/virajbhartiya/laya-vs-jev) | 110 | 2026-09-21 | Laya on MLX vs hosted Jev playing Chrome T-Rex side by side; planner labels moves, model chooses; safety checks override | MLX |
| [tapsin/jev-local](https://github.com/tapsin/jev-local) | 1 | 2026-09-28 | Prompted JSON over Ollama/vLLM/llama.cpp — parses generated JSON, not logprobs | Via Ollama |
| Other trending "System One" repos: [kydlikebtc/awesome-jev](https://github.com/kydlikebtc/awesome-jev) (587), [iapp-technology/openthai-systemone](https://github.com/iapp-technology/openthai-systemone) (65), [Abhinavexists/lev](https://github.com/Abhinavexists/lev) (42), [peterfriese/system-one-foundation-models](https://github.com/peterfriese/system-one-foundation-models) (55, Swift bridge to Apple Foundation Models), [v-modal/awesome-jev-tools](https://github.com/v-modal/awesome-jev-tools) (736) | | Sept 2026 | | |

- awesome-jev warns that many same-day bulk-submitted repos share a scaffold and are "unproven"; listing is not endorsement — [yibie/awesome-jev](https://github.com/yibie/awesome-jev)
- Benchmark numbers above are self-reported by each repo; they use different eval sets and are not comparable (e.g. jevos reports Laya at 0.489 on its set) — [feder-cr/jev](https://github.com/feder-cr/jev), [ollaya](https://github.com/ollaya-dev/ollaya)

**B. Constrained / structured generation libraries**

| Repo | Stars | Last push | Per-option probs? | Apple Silicon |
|---|---|---|---|---|
| [dottxt-ai/outlines](https://github.com/dottxt-ai/outlines) | 15,892 | 2026-09-21 | `Literal[...]` multiple-choice constrains output; returns the choice, not a distribution (README shows `model(prompt, Literal["Positive","Negative","Neutral"])`) | (mlx-lm backend not confirmed in README grep) |
| [guidance-ai/guidance](https://github.com/guidance-ai/guidance) | 21,783 | 2026-05-21 | `select()` constrained choice | via llama.cpp |
| [guidance-ai/llguidance](https://github.com/guidance-ai/llguidance) | 879 | 2026-09-29 | Token-mask engine only; merged into llama.cpp (b4613, 2025-02), SGLang (v0.4.4), vLLM (v0.8.2), Chromium, onnxruntime-genai | via llama.cpp |
| [mlc-ai/xgrammar](https://github.com/mlc-ai/xgrammar) | 1,940 | 2026-09-30 | Grammar mask engine; `pip install "xgrammar[metal]"` for MPS on Apple Silicon | Yes (metal extra) |
| [noamgat/lm-format-enforcer](https://github.com/noamgat/lm-format-enforcer) | 2,042 | 2026-04-04 | Mask engine; llguidance README calls it "significantly slower" | — |
| [sgl-project/sglang](https://github.com/sgl-project/sglang) | 36,617 | 2026-09-30 | Yes: `select` choices methods `TokenLengthNormalized` (argmax of normalized prompt logprobs, returns `normalized_prompt_logprobs` for all options), `GreedyTokenSelection`, `UnconditionalLikelihoodNormalized` (PMI-style) — [choices.py](https://github.com/sgl-project/sglang/blob/main/python/sglang/lang/choices.py) | CUDA-first |
| [eth-sri/lmql](https://github.com/eth-sri/lmql) | 4,217 | 2025-05-22 (stale) | Constraint language with distribution clauses | — |
| [567-labs/instructor](https://github.com/567-labs/instructor) | 13,961 | 2026-09-27 | Structured outputs over APIs (no logprob scoring) | via any OpenAI-compatible server |
| [BoundaryML/baml](https://github.com/BoundaryML/baml) | 9,358 | 2026-09-30 | Typed-prompt language | via servers |

- mlx-lm has an open feature request to "expose per-token logprobs from batch_generate()" (issue #1358, updated 2026-06-10) — [mlx-lm#1358](https://github.com/ml-explore/mlx-lm/issues/1358)

### Inferences
- For a NetHack bot currently calling Jev's `/v1/systemone`, the lowest-effort swap is pointing the SDK/base URL at a wire-compatible local server (ollaya, von, OpenJev, SemIf, jevos for yes/no only) and benchmarking on the bot's own logged decisions; laya-mlx is the fastest MLX-native option but uses its own Python API (`agent.predict`), not the HTTP wire format.
- Encoder-style models (Laya 421M, Von 395M ModernBERT, Verdict 151M) are fast but short-context (Laya default 1,024; Verdict 512); a NetHack state (map + inventory + messages) may exceed that — LLM-logprob scorers (SemIf, jev-local, OpenJev/DiffusionGemma) handle long states better but are slower.
- DIY route: first-token logprob over option letters via mlx-lm is what SemIf/Argos/jev-local do; SGLang's normalization methods are the reference for multi-token option labels.

### Gaps
- No independent, shared benchmark compares these Jev alternatives; all accuracy numbers are self-reported on different sets.
- Did not verify outlines' current mlx-lm integration or whether guidance/outlines expose option probabilities in current releases.
- Repos created within the last 2 weeks with very high star counts (e.g. Laya 28.7k in 11 days) could reflect hype or star inflation; not verified.

## Which Mac servers return logprobs/top_logprobs correctly?

### Takeaway
mlx-lm's own server documents `logprobs` (1–10 top tokens) on completions; oMLX (the "oMLX" server this project is named after) currently returns empty `logprobs.content` — a fix PR (#1591) is open, not merged; vllm-mlx silently ignores logprobs; Ollama supports logprobs but has open correctness bugs; vllm-metal fixed an echo/prompt_logprobs bug in Sept 2026.

### Cited Findings

| Repo | Stars | Last push | Logprobs status |
|---|---|---|---|
| [jundot/omlx](https://github.com/jundot/omlx) (oMLX) | 22,374 | 2026-09-30 | Continuous batching + hot/SSD tiered KV cache, menu-bar app, Homebrew. Issue #1549 (open, 2026-06-30): `/v1/chat/completions` accepts `logprobs`/`top_logprobs` but returns empty `logprobs.content` — [#1549](https://github.com/jundot/omlx/issues/1549). PR #1591 implementing OpenAI-shaped logprobs (0–20 top) for streaming and non-streaming is **OPEN, not merged** — [#1591](https://github.com/jundot/omlx/pull/1591) |
| [ml-explore/mlx-lm](https://github.com/ml-explore/mlx-lm) | 7,176 | 2026-09-29 | `mlx_lm.server` supports `logprobs` integer 1–10; response has `token_logprobs`, `tokens`, `top_logprobs` — [SERVER.md](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md). Note: not OpenAI chat `logprobs.content` shape |
| [waybarrios/vllm-mlx](https://github.com/waybarrios/vllm-mlx) | 1,602 | 2026-09-30 | Issue #786 (open, 2026-09-12): logprobs/top_logprobs "silently ignored", verified on 0.4.1 and main; values computed internally then dropped — [#786](https://github.com/waybarrios/vllm-mlx/issues/786) |
| [vllm-project/vllm-metal](https://github.com/vllm-project/vllm-metal) | 1,794 | 2026-09-29 | Closed bug #680 (2026-09-07): echo+logprobs returned 500 and `prompt_logprobs` silently `[None]` — [#680](https://github.com/vllm-project/vllm-metal/issues/680); also closed #622 sampling corruption at temp>0 — [#622](https://github.com/vllm-project/vllm-metal/issues/622) |
| [ollama/ollama](https://github.com/ollama/ollama) | 181,936 | 2026-09-30 | Logprobs supported but: requesting logprobs changes greedy tokens (#18163, open), logprobs not temperature-scaled (#16196, open), can't get a specific token's logprob unless in top_logprobs (#18579), top_logprobs capped at 20 (#18590), no `logit_bias` (#3795 open) — [#18163](https://github.com/ollama/ollama/issues/18163), [#16196](https://github.com/ollama/ollama/issues/16196), [#18579](https://github.com/ollama/ollama/issues/18579), [#3795](https://github.com/ollama/ollama/issues/3795) |
| LM Studio ([lmstudio-ai/lms](https://github.com/lmstudio-ai/lms) 5,324; [mlx-engine](https://github.com/lmstudio-ai/mlx-engine) 1,183, push 2026-09-25) | | | Logprobs are served (a 2026-09-26 bug reports a memory leak per request with "assistant-prefix + logprobs") — [bug-tracker#2105](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/2105); `logit_bias` regression on CUDA build — [#1932](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/1932) |
| [cubist38/mlx-openai-server](https://github.com/cubist38/mlx-openai-server) | 362 | 2026-09-28 | OpenAI-compatible FastAPI server for MLX; no logprobs issues found |
| [exo-explore/exo](https://github.com/exo-explore/exo) | 47,694 | 2026-09-29 | Distributed "run frontier AI locally"; no logprobs issues found |
| [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp) | 129,915 | 2026-09-30 | Has llguidance integration for grammar-constrained decoding — [llguidance README](https://github.com/guidance-ai/llguidance) |
| [abetlen/llama-cpp-python](https://github.com/abetlen/llama-cpp-python) | 10,637 | 2026-09-22 | Python bindings |
| [Blaizzy/mlx-vlm](https://github.com/Blaizzy/mlx-vlm) | 5,550 | 2026-09-29 | MLX VLM inference; implements logprobs per oMLX #1549 reporter — [#1549](https://github.com/jundot/omlx/issues/1549) |

### Inferences
- If the bot must stay on oMLX, logprob-based choice picking needs PR #1591 (or a local patch); otherwise run `mlx_lm.server` alongside, or skip HTTP and score in-process with mlx-lm/laya-mlx.
- Ollama's temperature/greedy-divergence bugs make its logprobs a poor calibration source.

### Gaps
- Did not verify llama.cpp server's current `logprobs`/`n_probs` behavior against the OpenAI spec in this pass.
- Did not test any server; statuses come from docs and issue trackers only.

## What NetHack LLM agents exist in 2025-2026 and what models/backends do they use locally?

### Takeaway
The headline 2026 event: GPT 6 Astra (via kenforthewin's harness) made what is claimed as the first LLM-agent NetHack ascension on 2026-09-21. Most active NetHack LLM agents use hosted models (OpenRouter, Claude Code); local-only efforts are small and weak (nethack-prime never passed Dlvl 1). BALROG is the main benchmark and supports local vLLM.

### Cited Findings

| Repo | Stars | Last push | Notes / backend |
|---|---|---|---|
| [kenforthewin/nethack_astra](https://github.com/kenforthewin/nethack_astra) | 14 | 2026-09-21 | Harness behind GPT 6 Astra's NetHack 3.6.7 ascension on Hardfought, 2026-09-21: 37,140 turns, 1,766,446 points, lawful dwarven Valkyrie; "first recorded LLM-agent ascension" (priority claim open to correction; BotHack ascended earlier as a non-LLM bot); [dumplog](https://www.hardfought.org/userdata/C/CodexDelver/nethack/dumplog/1788964024.nh.txt) |
| [kenforthewin/glyphbox](https://github.com/kenforthewin/glyphbox) | 17 | 2026-02-05 | LLM gets 24x80 screen, replies with Python code run in a sandbox against a `NetHackAPI` over NLE; OpenRouter default provider |
| [balrog-ai/BALROG](https://github.com/balrog-ai/BALROG) | 272 | 2026-04-09 | Benchmark (NetHack, etc.); leaderboard at balrogai.com; local eval via `vllm serve`; paper [arXiv 2411.13543](https://arxiv.org/abs/2411.13543) |
| [yamaton/agents-play-nethack](https://github.com/yamaton/agents-play-nethack) | 8 | 2026-09-26 | tmux interface for coding-agent harnesses (Claude Code originally) |
| [pj4533/NetHackPlayer](https://github.com/pj4533/NetHackPlayer) | 4 | 2026-01-25 | macOS app watching Claude play via Agent SDK |
| [NiJingzhe/nethack-mcp](https://github.com/NiJingzhe/nethack-mcp) | 1 | 2026-07-22 | MCP server; parses screen into structured state, action DSL with action chunks |
| [salavii/nethack-prime](https://github.com/salavii/nethack-prime) | 0 | 2026-08-31 | Local-inference-only NLE agent measuring prompt interventions; "never descended past dungeon level 1" |
| [Metta-AI/cogame-nethack](https://github.com/Metta-AI/cogame-nethack) | 0 | 2026-09-24 | NetHack-class roguelike coworld, LLM keystroke policy over text |
| [PetrAnokhin/nethacker](https://github.com/PetrAnokhin/nethacker) | 0 | 2026-09-29 | Symbolic agents evolved with GigaEvo |
| [aknsubbu/CausalRLAgent](https://github.com/aknsubbu/CausalRLAgent) | 4 | 2026-01-28 | RL + LLM strategic guidance |
| [CommanderCero/NetPlay](https://github.com/CommanderCero/NetPlay) | 28 | 2024-11-04 (stale) | LLM-powered NetHack agent |
| [facebookresearch/nle](https://github.com/facebookresearch/nle) | 986 | 2024-05-06 | NetHack Learning Environment |
| [upiterbarg/autoascend](https://github.com/upiterbarg/autoascend) | 0 (mirror) | 2023-10-23 | NeurIPS 2021 NetHack Challenge 1st place (symbolic) |
| [kolbytn/nethack-llm](https://github.com/kolbytn/nethack-llm) | 4 | 2023-05-19 | LLM actors for NetHack |

- No NetHack agent found that uses a Jev/System-One decision model; the closest game uses are Laya/Jev on Chrome T-Rex, Snake, and ViZDoom — [laya-vs-jev](https://github.com/virajbhartiya/laya-vs-jev), [laya-mlx](https://github.com/mizorewww/laya-mlx), [NanoJev](https://github.com/TianyuCodings/NanoJev), [von](https://github.com/wfzyx/von)

### Inferences
- The demonstrated game pattern (laya-vs-jev, laya-mlx Snake) is "deterministic planner/candidate generator + fast decision model picks + safety override", which matches this bot's architecture (safety rubric overriding at danger >= 0.6).

### Gaps
- No repo named "jev-doom" was found under the guessed owner; Von's README has a Doom demo and NanoJev plays ViZDoom — these may be what "jev-doom" refers to.
- BALROG leaderboard numbers for NetHack were not fetched.

## What's trending on GitHub right now in this space?

### Takeaway
The dominant trend (created 2026-09-18 onward) is open, local "System One" decision models cloning Jev's API, led by Laya (28.7k stars in ~11 days), laya-mlx (6.6k), SemIf (4.6k), NanoJev (2.4k), and ollaya (1k). Mac inference servers oMLX (22.4k) and exo (47.7k) are highly active. "LLM plays games" repos outside this wave are small.

### Cited Findings
- Laya: 28,744 stars, created 2026-09-18 — [NandhaKishorM/laya](https://github.com/NandhaKishorM/laya)
- laya-mlx: 6,638 stars, created 2026-09-19 — [mizorewww/laya-mlx](https://github.com/mizorewww/laya-mlx)
- Jev-adjacent apps also trending: browser-use/jev-ultrafast (21,437), tamaratran/fast-jev-compaction (7,213), jev-chat/jev-chat-jarvis (7,129), jarrodwatts/jev-trader (2,692), dzhng/jevgrep (1,801) — [jev-ultrafast](https://github.com/browser-use/jev-ultrafast), [fast-jev-compaction](https://github.com/tamaratran/fast-jev-compaction), [jevgrep](https://github.com/dzhng/jevgrep)
- lmgame-org/GamingAgent (983 stars, ICLR 2026, last push 2025-11-16) — LLM/VLM gaming agents and eval — [GamingAgent](https://github.com/lmgame-org/GamingAgent)
- Other "LLMs play X" repos are small (StarCraft II 361, diplobench 65) — [TextStarCraft2](https://github.com/sc2musa/Large-Language-Models-play-StarCraftII), [diplobench](https://github.com/sam-paech/diplobench)

### Calibration / "fast System 1" frameworks
- Laya is trained "with reinforcement learning against strictly proper scoring rules (RLCD)" — [laya](https://github.com/NandhaKishorM/laya)
- SemIf added per-workload temperature calibration and calibrated outputs (PR #19, 2026-09-22) — [SemIf](https://github.com/TheoLeeCJ/SemIf-OpenJev)
- Von ships calibration data and benchmark record on its HF model card — [von](https://github.com/wfzyx/von)
- NanoJev dataset includes a dedicated calibration split — [NanoJev](https://github.com/TianyuCodings/NanoJev)
- TianyuCodings/JevHarness: LLM builds task-specific decision harnesses around Jev, refined with rewards and traces — [NanoJev README](https://github.com/TianyuCodings/NanoJev)

### Inferences
- A GitHub search for "logprob classification calibration" returned nothing; calibration lives inside these decision-model repos rather than in standalone libraries.

### Gaps
- GitHub's /trending page was not fetched; trend is inferred from star count vs creation date.
- HN and r/LocalLLaMA discussion was not surveyed in this pass.
